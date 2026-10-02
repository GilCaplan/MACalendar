import Foundation

/// Runs a command on a phone with NO Mac ("This phone only", DEVQA Q85).
///
/// `LocalEngine` says what the words mean; this does it — through the same
/// `APIClient` writes every screen uses, so each change lands in the phone's
/// own store at once and is queued for a Mac if one is ever paired (the queue
/// IS the upload: nothing is lost by starting without a Mac).
///
/// What it will not do is guess. An edit, a delete or a tick that cannot name
/// ONE row says so — "I couldn't find…", or "Which one…?" with the choices —
/// and changes nothing (CLAUDE.md: deleting is destructive; empty slots are
/// the right answer). When the rules read nothing, Apple's on-device model
/// (Q66's reader) gets the words, and only for creates.
@MainActor
enum LocalCommand {

    struct Outcome {
        var reply: String
        var steps: [TraceStep]
        var changed: Bool
    }

    static func run(_ said: String, api: APIClient, now: Date = Date()) async -> Outcome {
        let text = said.trimmingCharacters(in: .whitespacesAndNewlines)
        var steps = [TraceStep(stage: "stt", title: "Heard", detail: text, ms: 0, atMs: 0, ok: true)]
        guard !text.isEmpty else {
            return Outcome(reply: "I didn't catch that.", steps: steps, changed: false)
        }
        let t0 = Date()
        var reading = LocalEngine.read(text, now: now)
        steps.append(TraceStep(stage: "rule", title: "Read on this phone",
                               detail: reading.actions.map(describe).joined(separator: " · "),
                               ms: Int(Date().timeIntervalSince(t0) * 1000), atMs: 0, ok: reading.understood))
        // Nothing the rules could read: Apple's model, creates only (Q66).
        if !reading.understood, OfflineReader.isAvailable, let fm = await OfflineReader.read(text, now: now) {
            let creates = fm.items.filter { $0.kind != "other" && !$0.title.isEmpty }.map { item -> LocalEngine.Action in
                var a = LocalEngine.Action(op: .create, kind: item.kind == "event" ? .event : .todo, title: item.title)
                a.date = item.date.isEmpty ? nil : item.date
                a.start = item.start.isEmpty ? nil : item.start
                a.end = item.end.isEmpty ? nil : item.end
                if ["daily", "weekly", "monthly", "yearly"].contains(item.recurrence) { a.recurrence = item.recurrence }
                if a.kind == .event, a.start == nil { a.start = "09:00"; a.end = "10:00" }
                return a
            }
            if !creates.isEmpty {
                reading = LocalEngine.Reading(actions: creates, understood: true)
                steps.append(TraceStep(stage: "llm", title: "Apple's on-device model",
                                       detail: creates.map(describe).joined(separator: " · "),
                                       ms: fm.ms, atMs: 0, ok: true))
            }
        }
        guard !reading.actions.isEmpty else {
            return Outcome(reply: "I couldn't tell what to do with that. Try “add …”, “move …” or “what do I have tomorrow?”",
                           steps: steps, changed: false)
        }
        var replies: [String] = []
        var changed = false
        for action in reading.actions {
            let (line, did) = await execute(action, api: api, now: now)
            replies.append(line)
            changed = changed || did
            steps.append(TraceStep(stage: did ? "execute" : "verify", title: did ? "Done" : "Nothing changed",
                                   detail: line, ms: 0, atMs: 0, ok: did || action.op == .query))
        }
        return Outcome(reply: replies.joined(separator: " "), steps: steps, changed: changed)
    }

    // MARK: - Acting

    static func execute(_ a: LocalEngine.Action, api: APIClient, now: Date) async -> (String, Bool) {
        switch a.op {
        case .create:   return await create(a, api: api)
        case .query:    return (answer(a, now: now), false)
        case .other:    return ("I couldn't tell what to do with that.", false)
        case .update, .delete, .complete:
            let rows = Self.rows(preferring: a.kind)
            let match = LocalEngine.find(a.target ?? "", date: a.targetDate,
                                         start: a.op == .delete ? a.start : nil, kind: nil, in: rows)
            switch match {
            case .none:
                let what = (a.target ?? "").isEmpty ? "which one you mean" : "“\(a.target!)”"
                return ("I couldn't find \(what). Nothing was changed.", false)
            case .many(let rs):
                let list = rs.prefix(4).map { r in r.date.isEmpty ? r.title : "\(r.title) (\(pretty(r.date)))" }
                return ("Which one: " + list.joined(separator: ", ") + "? Say it with the day.", false)
            case .one(let row):
                return await act(a, on: row, api: api)
            }
        }
    }

    static func create(_ a: LocalEngine.Action, api: APIClient) async -> (String, Bool) {
        do {
            if a.kind == .event {
                var f: [String: Any] = ["title": a.title, "date": a.date ?? DateFormatter.isoDay.string(from: Date()),
                                        "start_time": a.allDay ? "" : (a.start ?? ""), "end_time": a.allDay ? "" : (a.end ?? "")]
                if let r = a.recurrence {
                    f["recurrence"] = r
                    f["recurrence_end"] = a.recurrenceEnd ?? ""
                    if !a.recurDays.isEmpty { f["recur_days"] = a.recurDays.joined(separator: ",") }
                }
                _ = try await api.createEvent(f)
                var line = "Added \(a.title) " + when(a)
                if let r = a.recurrence { line += ", \(r)" + (a.recurrenceEnd.map { " until \(pretty($0))" } ?? "") }
                for n in a.notes where n.hasPrefix("rounded:") { line += " (\(n.dropFirst(9).trimmingCharacters(in: .whitespaces)))" }
                if a.linkedTodo {
                    // Q50: a call to a role is an event AND a to-do on the day
                    let id = try await api.createTodo(title: a.title, list: "general")
                    if let d = a.date { try await api.updateTodo(id: id, dueDate: d) }
                    line += ", and on your to-do list"
                }
                return (line + ".", true)
            } else {
                let id = try await api.createTodo(title: a.title, list: a.list ?? "today")
                if a.date != nil || a.quantity > 1 {
                    try await api.updateTodo(id: id, dueDate: a.date, quantity: a.quantity > 1 ? a.quantity : nil)
                }
                let qty = a.quantity > 1 ? " ×\(a.quantity)" : ""
                return ("Added “\(a.title)\(qty)” to your to-dos" + (a.date.map { ", due \(pretty($0))" } ?? "") + ".", true)
            }
        } catch {
            return ("Couldn't add \(a.title): \(error.localizedDescription)", false)
        }
    }

    static func act(_ a: LocalEngine.Action, on row: LocalEngine.Row, api: APIClient) async -> (String, Bool) {
        do {
            switch (a.op, row.kind) {
            case (.delete, .event):
                try await api.deleteEvent(id: row.id)
                return ("Deleted \(row.title)" + (row.date.isEmpty ? "" : " on \(pretty(row.date))") + ".", true)
            case (.delete, .todo):
                try await api.deleteTodo(id: row.id)
                return ("Removed “\(row.title)” from your to-dos.", true)
            case (.complete, .todo):
                if row.done { return ("“\(row.title)” is already done.", false) }
                _ = try await api.toggleTodo(id: row.id)
                return ("Ticked off “\(row.title)”.", true)
            case (.complete, .event):
                return ("\(row.title) is an event — there's nothing to tick.", false)
            case (.update, .todo):
                guard a.date != nil || a.newTitle != nil || a.priority != nil else {
                    return ("What should change about “\(row.title)”?", false)
                }
                try await api.updateTodo(id: row.id, title: a.newTitle, priority: a.priority, dueDate: a.date)
                if let t = a.newTitle { return ("Renamed “\(row.title)” to “\(t)”.", true) }
                if let p = a.priority { return ("“\(row.title)” is now \(p) priority.", true) }
                return ("“\(row.title)” is now due \(pretty(a.date!)).", true)
            case (.update, .event):
                return await updateEvent(a, row: row, api: api)
            default:
                return ("I couldn't tell what to do with that.", false)
            }
        } catch {
            return ("Couldn't change \(row.title): \(error.localizedDescription)", false)
        }
    }

    static func updateEvent(_ a: LocalEngine.Action, row: LocalEngine.Row, api: APIClient) async -> (String, Bool) {
        guard let ev = LocalStore.shared.event(row.id) else { return ("I couldn't find \(row.title).", false) }
        var f: [String: Any] = [:]
        let length = minutes(ev.endTime) - minutes(ev.startTime)
        if let t = a.newTitle { f["title"] = t }
        if let d = a.date { f["date"] = d }
        if let s = a.start {
            f["start_time"] = s
            f["end_time"] = a.end ?? (length > 0 ? LocalEngineClock.add(s, length) : LocalEngineClock.add(s, 60))
        }
        if let shift = a.shiftMinutes, !ev.startTime.isEmpty {
            f["start_time"] = LocalEngineClock.add(ev.startTime, shift)
            f["end_time"] = LocalEngineClock.add(ev.endTime.isEmpty ? ev.startTime : ev.endTime, shift)
        }
        if let ext = a.extendMinutes, !ev.endTime.isEmpty { f["end_time"] = LocalEngineClock.add(ev.endTime, ext) }
        if let len = a.lengthMinutes, !ev.startTime.isEmpty { f["end_time"] = LocalEngineClock.add(ev.startTime, len) }
        guard !f.isEmpty else { return ("What should change about \(row.title)?", false) }
        do {
            try await api.updateEvent(id: row.id, fields: f)
        } catch {
            return ("Couldn't change \(row.title): \(error.localizedDescription)", false)
        }
        if let t = a.newTitle { return ("Renamed \(row.title) to \(t).", true) }
        let day = (f["date"] as? String) ?? ev.date
        let start = (f["start_time"] as? String) ?? ev.startTime
        return ("Moved \(row.title) to \(pretty(day))" + (start.isEmpty ? "" : " at \(start)") + ".", true)
    }

    // MARK: - Questions

    static func answer(_ a: LocalEngine.Action, now: Date) -> String {
        let from = a.date ?? DateFormatter.isoDay.string(from: now)
        let to = a.rangeEnd ?? from
        let events = LocalStore.shared.allEvents()
            .filter { $0.date >= from && $0.date <= to }
            .sorted { ($0.date, $0.startTime) < ($1.date, $1.startTime) }
        let todos = LocalStore.shared.allTodos(list: nil, includeCompleted: false)
            .filter { !$0.dueDate.isEmpty && $0.dueDate >= from && $0.dueDate <= to }
        let span = from == to ? pretty(from) : "\(pretty(from)) to \(pretty(to))"
        if events.isEmpty && todos.isEmpty { return "Nothing on \(span)." }
        var parts: [String] = []
        if !events.isEmpty {
            parts.append(events.prefix(8).map { e in
                (from == to ? "" : pretty(e.date) + " ") + (e.startTime.isEmpty ? "" : e.startTime + " ") + e.title
            }.joined(separator: "; "))
        }
        if !todos.isEmpty { parts.append("to do: " + todos.prefix(6).map(\.title).joined(separator: ", ")) }
        return "\(span.prefix(1).uppercased() + span.dropFirst()): " + parts.joined(separator: ". ") + "."
    }

    // MARK: - Helpers

    /// Every row the reader may point at; the kind the words suggested first.
    static func rows(preferring kind: LocalEngine.Kind) -> [LocalEngine.Row] {
        let events = LocalStore.shared.ownEvents().map {
            LocalEngine.Row(id: $0.id, kind: .event, title: $0.title, date: $0.date, start: $0.startTime)
        }
        let todos = LocalStore.shared.ownTodos(includeCompleted: true).map {
            LocalEngine.Row(id: $0.id, kind: .todo, title: $0.title, date: $0.dueDate, start: "", done: $0.isDone)
        }
        return kind == .todo ? todos + events : events + todos
    }

    static func describe(_ a: LocalEngine.Action) -> String {
        switch a.op {
        case .create: return "\(a.kind == .event ? "event" : "to-do") “\(a.title)” \(when(a))"
        case .query: return "a question about \(a.date.map(pretty) ?? "today")"
        case .other: return "not understood"
        default: return "\(a.op.rawValue) “\(a.target ?? "")”"
        }
    }

    static func when(_ a: LocalEngine.Action) -> String {
        var w = a.date.map { "on \(pretty($0))" } ?? ""
        if let s = a.start, !a.allDay { w += (w.isEmpty ? "" : " ") + "at \(s)" }
        return w
    }

    static func pretty(_ iso: String) -> String {
        guard let d = DateFormatter.isoDay.date(from: iso) else { return iso }
        if Calendar.current.isDateInToday(d) { return "today" }
        if Calendar.current.isDateInTomorrow(d) { return "tomorrow" }
        let f = DateFormatter()
        f.dateFormat = "EEE d MMM"
        return f.string(from: d)
    }

    static func minutes(_ hhmm: String) -> Int {
        let p = hhmm.split(separator: ":").compactMap { Int($0) }
        return p.count == 2 ? p[0] * 60 + p[1] : 0
    }
}

/// The engine's clock arithmetic, named for the executor.
enum LocalEngineClock {
    static func add(_ hhmm: String, _ minutes: Int) -> String { DateParse.addMinutes(hhmm, minutes) }
}
