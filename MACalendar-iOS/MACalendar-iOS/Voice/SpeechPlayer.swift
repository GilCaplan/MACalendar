@preconcurrency import AVFoundation
import Foundation

@MainActor
class SpeechPlayer: NSObject, ObservableObject {
    @Published var isSpeaking = false
    private let synthesizer = AVSpeechSynthesizer()
    /// The reply waiting on the audio session; `stop()` or a newer reply
    /// changes it, so a stale one is never spoken.
    private var speakToken = UUID()

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(_ text: String, voiceIdentifier: String) {
        guard !text.isEmpty else { return }
        // The recorder leaves the session in .record (mic only) — speaking through it is
        // silent. Switch to playback; .spokenAudio + duckOthers reads out over music and
        // respects the silent switch like other assistants do.
        // Switched off the main thread (AudioSessionQueue), then spoken.
        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: voiceIdentifier)
            ?? AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = 0.52
        isSpeaking = true
        let token = UUID()
        speakToken = token
        AudioSessionQueue.run({ session in
            try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
            try? session.setActive(true, options: [])
        }, then: { [weak self] in
            guard let self, self.speakToken == token else { return }
            self.isSpeaking = true      // a cancel of the previous reply may have cleared it
            self.synthesizer.speak(utterance)
        })
    }

    func stop() {
        speakToken = UUID()
        synthesizer.stopSpeaking(at: .immediate)
        isSpeaking = false
    }
}

extension SpeechPlayer: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.isSpeaking = false
            AudioSessionQueue.run { try? $0.setActive(false, options: .notifyOthersOnDeactivation) }
        }
    }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        // Replacing one reply with the next cancels the first; that must not
        // mark the new one as finished.
        Task { @MainActor in if !self.synthesizer.isSpeaking { self.isSpeaking = false } }
    }
}
