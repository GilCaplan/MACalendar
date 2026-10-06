@preconcurrency import AVFoundation
import Foundation
import Speech

/// Records 16 kHz mono PCM for the Mac's Whisper, and — like the Mac app — listens
/// for a stop word while you talk. Stop-word detection uses Apple's on-device
/// speech recogniser purely as a trigger; the actual transcript still comes from
/// Whisper + your vocabulary on the Mac. Also auto-stops after a stretch of silence.
/// Every AVAudioSession activate / deactivate, in order, OFF the main thread.
///
/// `setActive` blocks until the audio hardware has started or stopped — Xcode
/// logs "This method can lead to UI unresponsiveness if called on the main
/// thread" (2026-10-06). iOS has no asynchronous form of it for an iPhone app,
/// so the calls go to one SERIAL queue: serial, because a deactivate left
/// running behind a new recording's activate would switch the mic off under it.
enum AudioSessionQueue {
    private static let queue = DispatchQueue(label: "MACalendar.audio-session", qos: .userInitiated)

    /// `work` on the session queue, then `then` back on the main actor.
    static func run(_ work: @escaping @Sendable (AVAudioSession) -> Void,
                    then: (@MainActor @Sendable () -> Void)? = nil) {
        queue.async {
            work(AVAudioSession.sharedInstance())
            if let then { Task { @MainActor in then() } }
        }
    }
}

@MainActor
class VoiceRecorder: NSObject, ObservableObject {
    @Published var isRecording = false
    /// Live on-device partial transcript (for the thinking sheet's "hearing…" row).
    @Published var liveText = ""

    /// Same defaults as the Mac (`config.audio` stop words); extra words from Settings.
    static let defaultStopWords = ["execute", "done", "go", "stop", "submit", "confirm"]
    var stopWords: [String] = VoiceRecorder.defaultStopWords
    var silenceStopSeconds: Double = 6.0
    var stopWordsEnabled = true
    /// Run the on-device recogniser even with stop words off — the Easter
    /// egg reads what was said before the audio leaves the phone. It never
    /// ends a recording by itself; only a stop word does.
    var transcribe = false
    /// Called on the main actor when a stop word or silence ends the recording.
    var onAutoStop: (() -> Void)?

    /// Why the recording ended. A spoken stop word is an explicit "go", so the
    /// caller sends immediately instead of showing the Redo / Add more / Send
    /// countdown — saying "execute" and then waiting three seconds is silly.
    enum StopReason { case manual, stopWord, silence, cancelled }
    private(set) var stopReason: StopReason = .manual

    private let engine = AVAudioEngine()
    private var pcm = Data()
    // Touched from the audio tap thread; the converter is created before the tap starts.
    private nonisolated(unsafe) var converter: AVAudioConverter?
    private nonisolated let targetFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!

    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    private var lastVoiceAt = Date()
    private var heardSpeech = false
    private var silenceTimer: Timer?
    private var stopping = false
    /// The recording whose session is being switched on; a stop or cancel
    /// before it lands changes this, so the engine never starts afterwards.
    private var startToken = UUID()

    // MARK: - Permissions

    static func requestSpeechPermission() async -> Bool {
        await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in cont.resume(returning: status == .authorized) }
        }
    }

    // MARK: - Start / stop

    func start(resume: Bool = false) {
        if !resume { pcm = Data(); liveText = "" }
        heardSpeech = false; stopping = false; lastVoiceAt = Date(); stopReason = .manual
        isRecording = true
        let token = UUID()
        startToken = token
        AudioSessionQueue.run({ session in
            try? session.setCategory(.record, mode: .measurement, options: [.duckOthers])
            try? session.setActive(true, options: .notifyOthersOnDeactivation)
        }, then: { [weak self] in
            guard let self, self.startToken == token, self.isRecording else { return }
            self.startEngine()
        })
    }

    /// The mic, once the session is on.
    private func startEngine() {
        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        converter = AVAudioConverter(from: inFormat, to: targetFormat)

        // On-device stop-word listener (optional — recording works without it)
        if stopWordsEnabled || transcribe, SFSpeechRecognizer.authorizationStatus() == .authorized {
            let rec = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
            // On-device only. Where the device can't recognise locally, skip the
            // stop-word listener entirely rather than letting Apple's servers see
            // the audio — the whole point is that the Mac is the only peer.
            // Recording (and the stop button) work fine without it.
            if let rec, rec.isAvailable, rec.supportsOnDeviceRecognition {
                let req = SFSpeechAudioBufferRecognitionRequest()
                req.shouldReportPartialResults = true
                req.requiresOnDeviceRecognition = true
                req.taskHint = .dictation
                recognizer = rec; request = req
                task = rec.recognitionTask(with: req) { [weak self] result, _ in
                    guard let self, let result else { return }
                    let text = result.bestTranscription.formattedString
                    Task { @MainActor in self.handlePartial(text) }
                }
            }
        }

        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { [weak self] buffer, _ in
            guard let self else { return }
            self.request?.append(buffer)
            self.appendConverted(buffer)
            let level = Self.rms(buffer)
            Task { @MainActor in
                if level > 0.012 { self.lastVoiceAt = Date(); self.heardSpeech = true }
            }
        }
        engine.prepare()
        try? engine.start()

        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isRecording, self.heardSpeech, self.silenceStopSeconds > 0 else { return }
                if Date().timeIntervalSince(self.lastVoiceAt) >= self.silenceStopSeconds {
                    self.autoStop(reason: .silence)
                }
            }
        }
    }

    /// Stop and return a WAV file (16 kHz, mono, 16-bit) for the Mac.
    func stop() -> Data? {
        teardown()
        guard !pcm.isEmpty else { return nil }
        return Self.wav(from: pcm, sampleRate: 16000)
    }

    /// Throw the recording away: stop listening and drop the audio unheard.
    ///
    /// Not `stop()` with the result ignored — `start(resume: true)` keeps `pcm`
    /// on purpose, so audio that was merely discarded by the caller would come
    /// back attached to the *next* recording. Cancelling has to clear it here.
    func cancel() {
        teardown()
        pcm = Data()
        liveText = ""
        stopReason = .cancelled
    }

    private func teardown() {
        startToken = UUID()             // a session still switching on must not start the engine
        silenceTimer?.invalidate(); silenceTimer = nil
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        request?.endAudio(); task?.cancel(); task = nil; request = nil
        isRecording = false
        AudioSessionQueue.run { try? $0.setActive(false, options: .notifyOthersOnDeactivation) }
    }

    // MARK: - Internals

    private func handlePartial(_ text: String) {
        liveText = text
        guard stopWordsEnabled, !stopping else { return }
        let words = text.lowercased().replacingOccurrences(of: "[^a-z' ]", with: " ", options: .regularExpression)
            .split(separator: " ").map(String.init)
        guard let last = words.last else { return }
        // Only the trailing word counts — "go to Shul at 7" must not stop on "go".
        // "done"/"go"/"stop" need a second of trailing quiet so mid-sentence use is ignored;
        // "execute"/"submit"/"confirm" are unambiguous and fire immediately.
        let strong = ["execute", "submit", "confirm"]
        if stopWords.contains(last) {
            if strong.contains(last) || Date().timeIntervalSince(lastVoiceAt) > 0.9 {
                autoStop(reason: .stopWord)
            }
        }
    }

    private func autoStop(reason: StopReason) {
        guard isRecording, !stopping else { return }
        stopping = true
        stopReason = reason
        onAutoStop?()
    }

    private nonisolated func appendConverted(_ buffer: AVAudioPCMBuffer) {
        guard let converter else { return }
        let ratio = targetFormat.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 16
        guard let out = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else { return }
        var consumed = false
        var err: NSError?
        converter.convert(to: out, error: &err) { _, status in
            if consumed { status.pointee = .noDataNow; return nil }
            consumed = true; status.pointee = .haveData; return buffer
        }
        guard err == nil, let ch = out.int16ChannelData else { return }
        let bytes = Data(bytes: ch[0], count: Int(out.frameLength) * 2)
        Task { @MainActor in self.pcm.append(bytes) }
    }

    private nonisolated static func rms(_ buffer: AVAudioPCMBuffer) -> Float {
        guard let ch = buffer.floatChannelData else { return 0 }
        let n = Int(buffer.frameLength); if n == 0 { return 0 }
        var sum: Float = 0
        for i in 0..<n { let v = ch[0][i]; sum += v * v }
        return (sum / Float(n)).squareRoot()
    }

    private static func wav(from pcm: Data, sampleRate: Int) -> Data {
        var d = Data()
        func u32(_ v: UInt32) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 4)) }
        func u16(_ v: UInt16) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 2)) }
        d.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + pcm.count)); d.append("WAVE".data(using: .ascii)!)
        d.append("fmt ".data(using: .ascii)!); u32(16); u16(1); u16(1); u32(UInt32(sampleRate)); u32(UInt32(sampleRate * 2)); u16(2); u16(16)
        d.append("data".data(using: .ascii)!); u32(UInt32(pcm.count)); d.append(pcm)
        return d
    }
}
