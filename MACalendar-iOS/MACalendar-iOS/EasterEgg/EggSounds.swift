import AVFoundation
import UIKit

/// The shows' sounds and haptics. Every sound is SYNTHESISED here — a noise
/// sweep for a whoosh, a few decaying sines for a chime — so nothing is
/// recorded, licensed or downloaded. Played through the app's own audio
/// engine, mixing with whatever else is playing and silent with the ring
/// switch off (the ambient category), and only when Settings says so.
@MainActor
final class EggSounds {
    static let shared = EggSounds()
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1)!
    private var cache: [EggSound: AVAudioPCMBuffer] = [:]
    private var ready = false

    private func prepare() -> Bool {
        if ready { return true }
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
        do {
            let session = AVAudioSession.sharedInstance()
            // Never take over the session a recording or a spoken reply is using.
            if session.category != .record && session.category != .playAndRecord && session.category != .playback {
                try? session.setCategory(.ambient, options: [.mixWithOthers])
            }
            try engine.start()
            ready = true
        } catch { ready = false }
        return ready
    }

    func play(_ sound: EggSound, volume: Double) {
        guard sound != .none, sound != .auto, prepare(), let buffer = buffer(sound) else { return }
        player.volume = Float(max(0, min(1, volume)))
        player.scheduleBuffer(buffer, at: nil, options: [])
        if !player.isPlaying { player.play() }
    }

    func haptic(_ strong: Bool = false) {
        UIImpactFeedbackGenerator(style: strong ? .medium : .light).impactOccurred()
    }

    private func buffer(_ sound: EggSound) -> AVAudioPCMBuffer? {
        if let b = cache[sound] { return b }
        let samples = Self.synth(sound, rate: 44_100)
        guard let b = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count)) else { return nil }
        b.frameLength = AVAudioFrameCount(samples.count)
        for (i, v) in samples.enumerated() { b.floatChannelData![0][i] = v }
        cache[sound] = b
        return b
    }

    nonisolated static func synth(_ sound: EggSound, rate: Double) -> [Float] { EggSynth.wave(sound, rate: rate) }
}
