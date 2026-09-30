// Harness for tests/unit/test_easter_egg.py: EggRules.cleanWords on JSON cases
// {"words","name","existing","count"} from stdin; prints the kept list.
import Foundation

@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

@main
struct EggClean {
    static func main() {
        while let line = readLine() {
            let c = try! JSONSerialization.jsonObject(with: Data(line.utf8)) as! [String: Any]
            let kept = EggRules.cleanWords(c["words"] as! [String], name: c["name"] as! String,
                                           existing: c["existing"] as! [String], count: c["count"] as! Int)
            print(String(data: try! JSONSerialization.data(withJSONObject: kept), encoding: .utf8)!)
        }
    }
}
