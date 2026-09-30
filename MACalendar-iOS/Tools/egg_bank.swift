// Harness for tests/unit/test_easter_egg.py: EggWordBank.fill for JSON cases
// {"words","id","name","existing","count","seed"} on stdin; prints the result.
import Foundation

@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

@main
struct EggBank {
    static func main() {
        while let line = readLine() {
            let c = try! JSONSerialization.jsonObject(with: Data(line.utf8)) as! [String: Any]
            let r = EggWordBank.fill(c["words"] as! [String], id: c["id"] as? String, name: c["name"] as! String,
                                     existing: c["existing"] as! [String], count: c["count"] as! Int,
                                     seed: (c["seed"] as? Int).map { UInt64($0) })
            let out: [String: Any] = ["words": r.words, "fromBank": r.fromBank]
            print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!)
        }
    }
}
