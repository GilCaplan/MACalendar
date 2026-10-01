// Harness for tests/unit/test_easter_egg.py: `EggRules.decideLate` — the words
// the Mac heard, checked when the device's own hearing played nothing — over
// the user's OWN objects (a pet's photo, a two-word name, a flag), not only the
// built-ins, under each "Show it" setting. stdin: "<trigger>\t<words>" per line.
// stdout: {"ids": [...], "held": bool} per line.
import Foundation

@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

@main
struct EggLate {
    static func main() {
        var s = EggSettings()
        s.chance = 1; s.cooldown = 0; s.quietHours = false
        func custom(_ id: String, _ name: String, _ words: [String], _ source: EggVariant.Source) -> EggObject {
            EggObject(id: id, name: name, keywords: words,
                      variants: [EggVariant(id: EggVariant.originalID, name: name, source: source)],
                      active: EggVariant.originalID, motion: .flyBy, builtin: false)
        }
        s.objects = EggCatalog.defaults() + [
            custom("custom-val", "Val", ["val"], .image("val.png")),
            custom("custom-cake", "Grandma's cake", ["grandma's cake"], .symbol("🎂")),
            custom("custom-flag", "Israel", ["israel"], .symbol("🇮🇱")),
        ]
        while let line = readLine() {
            let parts = line.split(separator: "\t", maxSplits: 1).map(String.init)
            guard parts.count == 2, let t = EggTrigger(rawValue: parts[0]) else { continue }
            s.trigger = t
            let d = EggRules.decideLate(parts[1], settings: s)
            let out: [String: Any] = ["ids": d.ids, "held": d.bareHandled && d.ids.isEmpty]
            print(String(data: try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]), encoding: .utf8)!)
        }
    }
}
