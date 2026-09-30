import Foundation

/// The shows' sounds, synthesised — shared by the phone and the Mac helper.
/// Nothing is recorded, licensed or downloaded: a whoosh is a noise sweep, a
/// chime a few decaying sines, a shofar a rising horn tone.
enum EggSynth {
    /// The waveform for a sound, -1…1.
    static func wave(_ sound: EggSound, rate: Double) -> [Float] {
        var seed: UInt32 = 0x9E37
        func noise() -> Double {
            seed = seed &* 1_664_525 &+ 1_013_904_223
            return Double(seed >> 8) / Double(1 << 24) * 2 - 1
        }
        func env(_ t: Double, _ attack: Double, _ length: Double) -> Double {
            t < attack ? t / attack : max(0, 1 - (t - attack) / (length - attack))
        }
        let length: Double
        switch sound {
        case .whoosh: length = 0.7
        case .chime: length = 1.0
        case .pop: length = 0.18
        case .boom: length = 1.2
        case .thunder: length = 2.0
        case .magic: length = 1.1
        case .shofar: length = 1.8
        case .rattle: length = 0.9
        case .none, .auto: return []
        }
        let n = Int(length * rate)
        var out = [Float](repeating: 0, count: n)
        var low = 0.0
        for i in 0..<n {
            let t = Double(i) / rate
            var v = 0.0
            switch sound {
            case .whoosh:
                // Noise through a low-pass whose cut-off sweeps up then down.
                let k = 0.02 + 0.25 * sin(.pi * t / length)
                low += k * (noise() - low)
                v = low * 2.2 * env(t, 0.25, length)
            case .chime:
                for (j, f) in [1046.5, 1318.5, 1568.0].enumerated() {
                    let t0 = Double(j) * 0.09
                    if t >= t0 { v += 0.3 * sin(2 * .pi * f * (t - t0)) * exp(-(t - t0) * 4) }
                }
            case .pop:
                let f = 900 - 3000 * t
                v = sin(2 * .pi * f * t) * exp(-t * 28)
            case .boom:
                low += 0.03 * (noise() - low)
                v = (0.8 * sin(2 * .pi * 55 * t) + 3 * low) * exp(-t * 3.2)
            case .thunder:
                low += 0.015 * (noise() - low)
                v = 5 * low * env(t, 0.05, length) * (0.7 + 0.3 * sin(t * 9))
            case .magic:
                let f = 600 * pow(2, t * 1.6)
                v = 0.35 * sin(2 * .pi * f * t) * env(t, 0.05, length)
                    + 0.15 * sin(2 * .pi * f * 1.5 * t) * env(t, 0.2, length)
            case .shofar:
                // A tekiah: a horn's rich, slightly rising note.
                let f = 330 + 45 * min(1, t * 2.5)
                let ph = 2 * .pi * f * t
                v = 0.3 * (sin(ph) + 0.55 * sin(2 * ph) + 0.35 * sin(3 * ph) + 0.2 * sin(4 * ph))
                    * env(t, 0.18, length) * (1 + 0.04 * sin(t * 30))
            case .rattle:
                // A grogger: a fast train of wooden clicks.
                let phase = (t * 38).truncatingRemainder(dividingBy: 1)
                v = phase < 0.12 ? noise() * 0.9 * (1 - phase / 0.12) * env(t, 0.02, length) : 0
            case .none, .auto:
                break
            }
            out[i] = Float(max(-1, min(1, v)))
        }
        return out
    }
}
