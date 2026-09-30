// Harness for tests/unit/test_easter_egg.py: EggRules.decide — the decisions
// both the phone and the Mac helper make — for JSON cases on stdin:
// {"text","bare","date":"yyyy-MM-dd HH:mm","roll","lastPlayedAgo", "settings": {...overrides}}
import Foundation

@main
struct EggRulesHarness {
    static func main() {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        f.locale = Locale(identifier: "en_US_POSIX")
        while let line = readLine() {
            guard let c = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { continue }
            var s = EggSettings()
            if let o = c["settings"] as? [String: Any] {
                var base = try! JSONSerialization.jsonObject(with: JSONEncoder().encode(s)) as! [String: Any]
                for (k, v) in o { base[k] = v }
                s = try! JSONDecoder().decode(EggSettings.self, from: JSONSerialization.data(withJSONObject: base))
            }
            let now = f.date(from: c["date"] as? String ?? "2026-07-15 12:00")!
            let last = now.addingTimeInterval(-(c["lastPlayedAgo"] as? Double ?? 1e9))
            let d = EggRules.decide(c["text"] as! String, bare: c["bare"] as? Bool ?? false, settings: s,
                                    now: now, lastPlayed: last, roll: c["roll"] as? Int)
            let out: [String: Any] = ["ids": d.ids, "together": d.together, "bare": d.bareHandled]
            print(String(data: try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]), encoding: .utf8)!)
        }
    }
}
