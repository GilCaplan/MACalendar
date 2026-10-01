// Harness for tests/unit/test_easter_egg.py: a saved "what plays for what" map
// takes in defaults added after it was saved, and never brings back one the
// person cleared. Prints one JSON line per case.
import Foundation
import SwiftUI

@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

@main
struct EggMadeMap {
    static func main() throws {
        func load(_ json: String) throws -> EggSettings { try JSONDecoder().decode(EggSettings.self, from: Data(json.utf8)) }
        // 1. A map saved before the activities set: Study cleared by the person.
        let old = try load(#"{"madeMap": {"Travel": "plane", "Dog walking": "dog"}}"#)
        // 2. Saved by this build, then the person clears Groceries: it stays cleared.
        var now = old
        now.madeMap["Groceries"] = nil
        let again = try load(String(decoding: try JSONEncoder().encode(now), as: UTF8.self))
        let out: [String: Any] = [
            "old_has_groceries": old.madeMap["Groceries"] ?? "",
            "old_has_study": old.madeMap["Study"] ?? "",
            "old_keeps_travel": old.madeMap["Travel"] ?? "",
            "cleared_stays_cleared": again.madeMap["Groceries"] == nil,
            "fresh_has_fitness": EggSettings().madeMap["Fitness"] ?? "",
        ]
        print(String(decoding: try JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]), as: UTF8.self))
    }
}
