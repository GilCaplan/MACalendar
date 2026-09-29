// The PARITY harness for OfflineDates.swift (DEVQA Q68): tests/unit/test_offline_protocol.py
// compiles this with the app's resolver and compares it with gold._phrase_to_date.
// Resolves phrases from stdin against a fixed "today" (argv1 yyyy-MM-dd); prints JSON lines.
import Foundation

@main
struct DatesParity {
    static func main() {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        let today = f.date(from: CommandLine.arguments[1])!
        while let line = readLine() {
            let out: [String: Any] = ["p": line, "d": OfflineDates.resolve(line, today: today) ?? NSNull()]
            print(String(data: try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]),
                         encoding: .utf8)!)
        }
    }
}
