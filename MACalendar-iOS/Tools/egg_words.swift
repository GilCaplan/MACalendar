// Harness for tests/unit/test_easter_egg.py: compiled with EggCatalog.swift.
// stdin: one utterance per line. stdout: {"ids", "bare", "pack" (plurals bring 3), "group"} per line.
import Foundation

// The stage asks the app's overlay to show; a harness has none.
@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

@main
struct EggWords {
    static func main() {
        let objects = EggCatalog.defaults()
        while let line = readLine() {
            let out: [String: Any] = ["ids": EggMatcher.matches(line, objects: objects).ids,
                                      "bare": EggMatcher.isBare(line, objects: objects),
                                      "pack": EggMatcher.matches(line, objects: objects, plural: 3).ids,
                                      "group": EggMatcher.saysGroup(line, groupWords: EggCatalog.groupWords)]
            print(String(data: try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]),
                         encoding: .utf8)!)
        }
    }
}
