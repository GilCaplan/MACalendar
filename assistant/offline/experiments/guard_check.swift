// The guard alone, over many commands, no model (DEVQA Q68): reads JSON lines
// {"id","text"} on stdin, the served guard rules from argv1; prints {"id","leaves"}.
// Compiled with the app's OfflineGuard.swift by guard_board.py.
import Foundation

@main
struct GuardCheck {
    static func main() {
        let rules = FileManager.default.contents(atPath: CommandLine.arguments[1])
            .flatMap { try? JSONDecoder().decode(GuardRules.self, from: $0) } ?? .bundled
        while let line = readLine() {
            guard let d = line.data(using: .utf8),
                  let o = try? JSONSerialization.jsonObject(with: d) as? [String: String],
                  let id = o["id"], let text = o["text"] else { continue }
            let out: [String: Any] = ["id": id, "leaves": OfflineGuard.leavesForMac(text, rules: rules)]
            print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!)
        }
    }
}
