import Foundation

// Drives `LocalEngine` from the command line, one JSON request per line:
//   {"text": "…", "now": "2026-10-02T10:00:00", "rows": [{"id":1,"kind":"event","title":"…","date":"…","start":"…"}]}
// and prints one JSON reading per line. Built by tests/unit/test_phone_engine.py
// and scripts/phone_engine_board.py with:
//   swiftc -parse-as-library MACalendar-iOS/Engine/LocalEngine.swift Tools/local_engine_cli.swift

@main
struct LocalEngineCLI {
    static func main() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withFullDate, .withTime, .withColonSeparatorInTime, .withDashSeparatorInDate]
        fmt.timeZone = cal.timeZone
        while let line = readLine() {
            guard let data = line.data(using: .utf8),
                  let req = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let text = req["text"] as? String else { print("{}"); continue }
            let now = (req["now"] as? String).flatMap { fmt.date(from: $0) } ?? Date()
            let reading = LocalEngine.read(text, now: now, calendar: cal)
            var acts: [[String: Any]] = []
            for a in reading.actions {
                var d: [String: Any] = ["op": a.op.rawValue, "kind": a.kind.rawValue, "title": a.title,
                                        "all_day": a.allDay, "linked_todo": a.linkedTodo, "notes": a.notes,
                                        "recur_days": a.recurDays]
                d["date"] = a.date; d["start"] = a.start; d["end"] = a.end
                d["recurrence"] = a.recurrence; d["recurrence_end"] = a.recurrenceEnd
                d["list"] = a.list; d["target"] = a.target; d["target_date"] = a.targetDate
                d["shift_minutes"] = a.shiftMinutes; d["new_title"] = a.newTitle; d["range_end"] = a.rangeEnd
                if let rows = req["rows"] as? [[String: Any]], a.target != nil || (a.op != .create && a.op != .query) {
                    let rs = rows.map { r in
                        LocalEngine.Row(id: r["id"] as? Int ?? 0,
                                        kind: (r["kind"] as? String) == "todo" ? .todo : .event,
                                        title: r["title"] as? String ?? "", date: r["date"] as? String ?? "",
                                        start: r["start"] as? String ?? "", done: r["done"] as? Bool ?? false)
                    }
                    switch LocalEngine.find(a.target ?? "", date: a.targetDate, start: a.op == .delete ? a.start : nil,
                                            kind: nil, in: rs) {
                    case .one(let r): d["match"] = r.id
                    case .many(let rr): d["match_many"] = rr.map(\.id)
                    case .none: d["match"] = NSNull()
                    }
                }
                acts.append(d.compactMapValues { $0 })
            }
            let out: [String: Any] = ["actions": acts, "understood": reading.understood]
            let json = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
            print(String(data: json, encoding: .utf8)!)
            fflush(stdout)
        }
    }
}
