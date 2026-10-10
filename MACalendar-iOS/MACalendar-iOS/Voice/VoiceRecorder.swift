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

    /// How loud the mic is RIGHT NOW, 0…1 (−55 dB…−10 dB), smoothed: fast up,
    /// slower down. Drives the rings and the waveform, so you can see the
    /// phone is hearing you rather than talking to the air (Gil, 2026-10-09).
    @Published private(set) var level: Float = 0
    /// The last `historyCount` levels, oldest first — the scrolling waveform.
    @Published private(set) var levels: [Float] = Array(repeating: 0, count: VoiceRecorder.historyCount)
    static let historyCount = 28
    /// When this recording (not its resume) started — the chip's clock.
    @Published private(set) var startedAt: Date?
    /// Anything louder than room noise has arrived since the take began. The
    /// chip turns to "No sound" while it is false, so a dead mic shows within
    /// two seconds instead of after the whole sentence.
    @Published private(set) var soundSeen = false

    /// What the last recording actually captured — said in the thinking
    /// panel, so "it only heard 'execute'" can be told apart: 0.6 s captured
    /// is the phone, 5 s captured is the Mac.
    struct Capture: Equatable {
        var seconds: Double
        var peakDb: Float           // loudest buffer, dBFS
        var restarts: Int           // times iOS reconfigured the engine mid-take
    }
    @Published private(set) var lastCapture: Capture?
    private var peakDb: Float = -120
    private var restarts = 0

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
    /// The 16 kHz PCM, appended ON the tap thread under a lock. It used to be
    /// handed to the main actor one Task per buffer, so stop() read it before
    /// the last buffers landed (the tail was dropped) and a new recording's
    /// reset could be followed by the previous one's stragglers.
    private nonisolated let pcmLock = NSLock()
    private nonisolated(unsafe) var pcmStore = Data()
    private var pcm: Data {
        get { pcmLock.lock(); defer { pcmLock.unlock() }; return pcmStore }
        set { pcmLock.lock(); pcmStore = newValue; pcmLock.unlock() }
    }
    private var configObserver: NSObjectProtocol?
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
    /// What was heard before an "Add more" resumed the take: the recogniser
    /// restarts with the mic, so its words would otherwise start over.
    private var heardBefore = ""
    /// The recogniser has given its last word for this take (or failed).
    private var heardFinal = false
    private var heardWaiters: [CheckedContinuation<Void, Never>] = []

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
        heardBefore = resume ? liveText : ""
        heardFinal = false
        if !resume {
            pcm = Data(); liveText = ""
            peakDb = -120; restarts = 0; startedAt = Date(); soundSeen = false
        }
        heardSpeech = false; stopping = false; lastVoiceAt = Date(); stopReason = .manual
        level = 0; levels = Array(repeating: 0, count: Self.historyCount)
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
        // On-device stop-word listener (optional — recording works without it)
        // Always, when allowed: the phone transcribes its own recordings and
        // sends the words, not the audio (Gil, 2026-10-10 — "whatever device
        // it comes from, just use that one"). Stop words and magic words read
        // the same partials.
        if SFSpeechRecognizer.authorizationStatus() == .authorized {
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
                task = rec.recognitionTask(with: req) { [weak self] result, error in
                    guard let self else { return }
                    let text = result?.bestTranscription.formattedString
                    let done = (result?.isFinal ?? false) || error != nil
                    Task { @MainActor in
                        if let text { self.handlePartial(text) }
                        if done { self.finishHearing() }
                    }
                }
            }
        }

        tapAndRun()

        // iOS stops the engine when the audio route or format changes under it
        // — AirPods connecting, a call, another app taking the mic — and never
        // starts it again: the recording carried on in name, capturing nothing,
        // until something restarted it. Pick it straight back up instead.
        if configObserver == nil {
            configObserver = NotificationCenter.default.addObserver(
                forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main
            ) { [weak self] _ in
                Task { @MainActor in
                    guard let self, self.isRecording, !self.stopping else { return }
                    self.restarts += 1
                    self.tapAndRun()
                }
            }
        }

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

    /// (Re)install the tap at the input's CURRENT format and run the engine —
    /// at the start, and again after iOS reconfigures it mid-recording.
    private func tapAndRun() {
        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        converter = AVAudioConverter(from: inFormat, to: targetFormat)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { [weak self] buffer, _ in
            guard let self else { return }
            self.request?.append(buffer)
            self.appendConverted(buffer)
            let rms = Self.rms(buffer)
            Task { @MainActor in
                if rms > 0.012 { self.lastVoiceAt = Date(); self.heardSpeech = true }
                self.push(rms: rms)
            }
        }
        engine.prepare()
        try? engine.start()
    }

    /// One buffer's loudness into the meter: dBFS mapped −55…−10 dB onto 0…1,
    /// rising at once and falling over a few buffers so it reads as a voice
    /// rather than flicker.
    private func push(rms: Float) {
        let db = 20 * log10(max(rms, 1e-6))
        peakDb = max(peakDb, db)
        let target = min(1, max(0, (db + 55) / 45))
        if target > 0.3, !soundSeen { soundSeen = true }
        level = target > level ? target : level * 0.75 + target * 0.25
        levels.removeFirst()
        levels.append(level)
    }

    /// Stop and return a WAV file (16 kHz, mono, 16-bit) for the Mac.
    func stop() -> Data? {
        teardown(keepHearing: true)
        let audio = pcm
        lastCapture = Capture(seconds: Double(audio.count) / 32_000, peakDb: peakDb, restarts: restarts)
        guard !audio.isEmpty else { return nil }
        return Self.wav(from: audio, sampleRate: 16000)
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

    /// The phone's transcript of the take, final: the mic has stopped, and the
    /// recogniser is given up to `timeout` to settle its last words (it
    /// usually needs a few hundred ms). Empty when it never ran — no
    /// permission, or no on-device recognition — and the caller then sends
    /// the audio instead.
    func heardText(timeout: Double = 1.2) async -> String {
        if task != nil && !heardFinal {
            await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
                heardWaiters.append(c)
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                    self.finishHearing()
                }
            }
        }
        task?.cancel(); task = nil; request = nil
        return liveText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func finishHearing() {
        heardFinal = true
        let waiting = heardWaiters
        heardWaiters = []
        waiting.forEach { $0.resume() }
    }

    private func teardown(keepHearing: Bool = false) {
        startToken = UUID()             // a session still switching on must not start the engine
        silenceTimer?.invalidate(); silenceTimer = nil
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        request?.endAudio()
        // A stop keeps the recogniser a moment for its last words (heardText);
        // a cancel drops it at once.
        if !keepHearing { task?.cancel(); task = nil; request = nil; finishHearing() }
        if let o = configObserver { NotificationCenter.default.removeObserver(o); configObserver = nil }
        isRecording = false
        level = 0
        AudioSessionQueue.run { try? $0.setActive(false, options: .notifyOthersOnDeactivation) }
    }

    // MARK: - Internals

    private func handlePartial(_ text: String) {
        liveText = heardBefore.isEmpty ? text : heardBefore + " " + text
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
        pcmLock.lock(); pcmStore.append(bytes); pcmLock.unlock()
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
