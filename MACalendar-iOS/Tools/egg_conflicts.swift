// Harness for tests/unit/test_easter_egg.py: one word, one thing — EggRules'
// sameWord / owner / conflicts over a fixed set of objects. Prints JSON.
import Foundation

@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

@main
struct EggConflicts {
    static func main() {
        func obj(_ id: String, _ words: [String]) -> EggObject {
            EggObject(id: id, name: id.capitalized, keywords: words,
                      variants: [EggVariant(id: "original", name: "o", source: .figure("dog"))], active: "original", builtin: false)
        }
        let objects = [obj("dog", ["dog", "puppy"]), obj("rex", ["dogs", "rex"]), obj("cat", ["cat"]),
                       obj("puppies", ["puppies"])]
        let out: [String: Any] = [
            "same": [EggRules.sameWord("dog", "dogs"), EggRules.sameWord("puppy", "puppies"), EggRules.sameWord("cat", "car")],
            "owner_cat_for_dog": EggRules.owner(of: "cat", besides: "dog", in: objects)?.id ?? NSNull(),
            "owner_dogs_for_cat": EggRules.owner(of: "Dogs", besides: "cat", in: objects)?.id ?? NSNull(),
            "owner_cat_for_cat": EggRules.owner(of: "cat", besides: "cat", in: objects)?.id ?? NSNull(),
            "conflicts": EggRules.conflicts(objects).map { ["word": $0.word, "ids": $0.ids] },
        ]
        print(String(data: try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]), encoding: .utf8)!)
    }
}
