import SwiftUI

/// "Was this right?" — a quick pass over recent voice commands that have no
/// feedback yet. Each 👍 / 👎 / fix feeds the command memory on the Mac so the
/// assistant's few-shot examples reflect what you actually meant.
struct AssistantReviewView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    @State private var items: [MemoryExample] = []
    @State private var loading = false
    @State private var error: String?
    @State private var done = 0
    @State private var confirmSkip = false
    @State private var fixing: MemoryExample?

    var body: some View {
        StackNavigation {
            Group {
                if let error {
                    VStack(spacing: 10) { Text(error).foregroundColor(.red).multilineTextAlignment(.center); Button("Try again") { Task { await load() } } }.padding()
                } else if items.isEmpty && !loading {
                    VStack(spacing: 10) {
                        AssistantIcon(.approved).frame(width: 40, height: 40).foregroundColor(.green)
                        Text(done > 0 ? "All caught up — \(done) reviewed." : "Nothing to review").font(.headline)
                        Text("Every voice command shows up here until you've said whether it was right. Takes a few seconds a day and makes the assistant learn your phrasing.")
                            .font(.footnote).foregroundColor(.secondary).multilineTextAlignment(.center)
                    }.padding(30)
                } else {
                    List {
                        Section {
                            Text("\(items.count) to review · tap 👍 if it did the right thing, 👎 if not. Only what you tick is stored.")
                                .font(.footnote).foregroundColor(.secondary)
                        }
                        ForEach(items) { ex in
                            ReviewRow(example: ex,
                                      onVerdict: { verdict in Task { await send(ex, verdict) } },
                                      onFix: { fixing = ex })
                        }
                    }
                }
            }
            .navigationTitle("Review commands")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    if !items.isEmpty {
                        Button("Dismiss all") { confirmSkip = true }
                            .confirmationDialog("Dismiss all \(items.count) without a verdict? They won't count as right or wrong.",
                                                isPresented: $confirmSkip, titleVisibility: .visible) {
                                Button("Dismiss all", role: .destructive) { Task { _ = await api.skipAllUnreviewed(); items = []; done = 0 } }
                            }
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) { Button("Done") { dismiss() } }
            }
            .overlay { if loading && items.isEmpty { ProgressView() } }
            .task { await load() }
            .refreshable { await load() }
            .sheet(item: $fixing) { ex in
                CorrectionSheet(example: ex) { plan in
                    Task {
                        // The calendar first, the verdict LAST: deleting or
                        // patching a row a voice command made writes its own
                        // automatic feedback on the Mac, and the sheet's
                        // explicit answer has to be the one that stands.
                        for op in plan.ops { await apply(op) }
                        await api.memoryFeedback(id: ex.id, feedback: plan.feedback,
                                                 correction: plan.correction, notes: plan.notes)
                        withAnimation { items.removeAll { $0.id == ex.id } }
                        done += 1
                        api.requestRefresh()
                    }
                }
            }
        }
    }

    private func apply(_ op: FixOp) async {
        switch op {
        case .patchEvent(let id, let fields): try? await api.updateEvent(id: id, fields: fields)
        case .deleteEvent(let id):            try? await api.deleteEvent(id: id)
        case .createEvent(let fields):        _ = try? await api.createEvent(fields)
        case .patchTodo(let id, let title, let due):
            try? await api.updateTodo(id: id, title: title, dueDate: due)
        case .deleteTodo(let id):             try? await api.deleteTodo(id: id)
        case .toggleTodo(let id):             _ = try? await api.toggleTodo(id: id)
        case .createTodo(let title, let due):
            if let id = try? await api.createTodo(title: title), !due.isEmpty {
                try? await api.updateTodo(id: id, dueDate: due)
            }
        case .restore(let item):              await api.revert([item])
        }
    }

    private func load() async {
        loading = true; defer { loading = false }
        do { items = try await api.unreviewedCommands(); error = nil }
        catch {
            // A cancelled request (sheet closed / view refreshed mid-flight) is not an outage.
            if error is CancellationError || (error as? URLError)?.code == .cancelled
                || error.localizedDescription.lowercased().contains("cancel") { return }
            self.error = "Couldn't reach the Mac: \(error.localizedDescription)"
        }
    }

    private func send(_ ex: MemoryExample, _ verdict: String) async {
        await api.memoryFeedback(id: ex.id, feedback: verdict)
        withAnimation { items.removeAll { $0.id == ex.id } }
        done += 1
    }
}

private struct ReviewRow: View {
    let example: MemoryExample
    let onVerdict: (String) -> Void
    let onFix: () -> Void
    @EnvironmentObject var settings: AppSettings

    /// One line per thing the command did, in the order it did them — the
    /// objects that actually landed where the Mac could say, otherwise what
    /// the command asked for.
    private var lines: [String] { FixObject.build(from: example).map(\.summary) }

    /// "2026-08-27" → "Thu 27 Aug"
    static func prettyDate(_ iso: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        guard let d = f.date(from: iso) else { return iso }
        let o = DateFormatter(); o.dateFormat = "EEE d MMM"
        return o.string(from: d)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                AssistantIcon(example.source == "ios" ? .iphone : .mac).frame(width: 14, height: 14).foregroundColor(.secondary)
                Text(example.time.replacingOccurrences(of: "T", with: " ").prefix(16)).font(.caption2).foregroundColor(.secondary)
                Spacer()
                Text(example.parsePath).font(.caption2.monospaced()).foregroundColor(.secondary)
            }
            Text("“\(example.transcript)”").font(.callout)
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    Text(line).font(.footnote).foregroundColor(.secondary).lineLimit(1)
                }
            }
            HStack(spacing: 18) {
                Button { onVerdict("approved") } label: {
                    Label("Right", systemImage: "").labelStyle(.titleOnly).frame(minWidth: 70)
                        .overlay(alignment: .leading) { AssistantIcon(.thumbsUp).frame(width: 16, height: 16).offset(x: -22) }
                }
                .buttonStyle(.bordered).tint(.green)
                Button { onVerdict("rejected") } label: {
                    Text("Wrong").frame(minWidth: 70)
                        .overlay(alignment: .leading) { AssistantIcon(.thumbsDown).frame(width: 16, height: 16).offset(x: -22) }
                }
                .buttonStyle(.bordered).tint(.red)
                Button { onFix() } label: { Text("Fix…").frame(minWidth: 50) }
                    .buttonStyle(.bordered).tint(.orange)
                Spacer()
            }
            .padding(.leading, 22)
        }
        .padding(.vertical, 4)
    }
}




// MARK: - Fix this

/// One calendar write the sheet will make on Save.
enum FixOp {
    case patchEvent(Int, [String: Any])
    case deleteEvent(Int)
    case createEvent([String: Any])
    case patchTodo(Int, String?, String?)
    case deleteTodo(Int)
    case toggleTodo(Int)
    case createTodo(String, String)
    case restore(RevertItem)
}

/// What Save hands back: the writes, then the verdict that is sent last.
struct FixPlan {
    let ops: [FixOp]
    let feedback: String            // "corrected" | "rejected"
    let correction: [[String: Any]]?
    let notes: String
}

/// One thing a command did (or should have done), as the fix sheet edits it.
struct FixObject: Identifiable {
    enum Choice: Hashable { case right, change, undo }

    let id = UUID()
    /// Position in the command's `actions`; nil for a row the user added.
    var index: Int?
    /// The action that made or touched it; "" for an added row.
    var action: String
    /// The row it landed as, when the Mac linked one.
    var record: ResolvedRecord?
    var choice: Choice = .right
    /// What it SHOULD be — "event" | "todo".
    var kind: String
    var title: String
    var date: String            // yyyy-MM-dd, "" for a to-do with no day
    var start: String           // HH:mm
    var end: String

    var isAdded: Bool { index == nil }
    var isCreate: Bool { action.hasPrefix("create_") }
    var isUpdate: Bool { action.hasPrefix("update_") }
    var isDelete: Bool { action.hasPrefix("delete_") }
    var isComplete: Bool { action == "complete_todo" }
    /// A question answered, a subtask ticked: nothing in the calendar to edit.
    var isReadOnly: Bool { !(isCreate || isUpdate || isDelete || isComplete) && !isAdded }

    /// Can the sheet actually take this back? A create needs its row id; a
    /// delete needs the body the Mac kept; an edit needs the old values.
    var canUndo: Bool {
        if isCreate { return record?.id != nil && record?.isGone == false }
        if isDelete { return record?.restore != nil }
        if isUpdate { return record?.before != nil && record?.id != nil }
        if isComplete { return record?.id != nil && record?.completed == true }
        return false
    }

    var undoLabel: String {
        if isCreate { return "Remove" }
        if isDelete { return "Restore" }
        if isUpdate { return "Put back" }
        if isComplete { return "Reopen" }
        return "Wrong"
    }

    var verb: String {
        switch action {
        case "create_event": return "New event"
        case "create_todo": return "New to-do"
        case "update_event": return "Changed event"
        case "update_todo": return "Changed to-do"
        case "delete_event": return "Deleted event"
        case "delete_todo": return "Deleted to-do"
        case "complete_todo": return "Ticked off"
        case "query_schedule": return "Read your schedule"
        case "query_todos": return "Read your to-dos"
        case "": return kind == "event" ? "Missed event" : "Missed to-do"
        default: return action.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    var when: String {
        let day = date.isEmpty ? "" : Self.pretty(date)
        if kind == "todo" { return day.isEmpty ? "" : "due \(day)" }
        let clock = start.isEmpty ? "" : (end.isEmpty ? start : "\(start)–\(end)")
        return [day, clock].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    var summary: String {
        let t = title.isEmpty ? "" : " · \(title)"
        let w = when.isEmpty ? "" : " · \(when)"
        return "\(verb)\(t)\(w)"
    }

    static func pretty(_ iso: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX")
        guard let d = f.date(from: iso) else { return iso }
        let o = DateFormatter(); o.dateFormat = "EEE d MMM"
        return o.string(from: d)
    }

    /// Every object a command touched, in the order it ran: the rows the Mac
    /// linked, and — for an action it linked nothing to — what was asked.
    static func build(from ex: MemoryExample) -> [FixObject] {
        let resolved = ex.resolved ?? []
        let indexed = resolved.contains { ($0.index ?? -1) >= 0 }
        var unclaimed = resolved                      // older Macs send no index
        var out: [FixObject] = []
        for (i, a) in ex.actions.enumerated() {
            let p = a.parameters
            var mine: [ResolvedRecord]
            if indexed {
                mine = resolved.filter { $0.index == i }
            } else if let k = unclaimed.firstIndex(where: { $0.action == a.action }) {
                mine = [unclaimed.remove(at: k)]
            } else { mine = [] }
            if !mine.isEmpty {
                for r in mine {
                    out.append(FixObject(index: i, action: a.action, record: r, kind: r.type,
                                         title: r.title, date: r.date, start: r.startTime,
                                         end: r.endTime ?? ""))
                }
                continue
            }
            // Nothing linked: show what was ASKED.
            switch a.action {
            case "create_todo":
                var titles = (p["titles"]?.arrayValue ?? []).compactMap { $0.stringValue }
                if titles.isEmpty, let t = p["title"]?.stringValue { titles = [t] }
                for t in (titles.isEmpty ? [""] : titles) {
                    out.append(FixObject(index: i, action: a.action, kind: "todo", title: t,
                                         date: p["due_date"]?.stringValue ?? "", start: "", end: ""))
                }
            default:
                let isTodo = a.action.hasSuffix("_todo") || a.action.hasSuffix("_todos")
                out.append(FixObject(
                    index: i, action: a.action, kind: isTodo ? "todo" : "event",
                    title: p["title"]?.stringValue ?? p["match_title"]?.stringValue ?? "",
                    date: p["date"]?.stringValue ?? p["match_date"]?.stringValue ?? "",
                    start: p["start_time"]?.stringValue ?? "", end: p["end_time"]?.stringValue ?? ""))
            }
        }
        return out
    }
}

/// "What should it have done?" — every object the command touched, each with
/// its own verdict (right / change it / take it back), a one-tap "nothing
/// should have been done", a way to add what it missed, and why.
///
/// Gil, 2026-09-24: a six-part command opened this sheet showing one event,
/// and there was no way to say the command should not have done anything.
private struct CorrectionSheet: View {
    let example: MemoryExample
    let onDone: (FixPlan) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var rows: [FixObject] = []
    @State private var reasons: Set<String> = []
    @State private var notes = ""

    private static let reasonChips = [
        "Misheard a word", "Wrong day or time", "Should be a to-do",
        "Should be an event", "Split it wrong", "Missed part of it", "Didn't ask for this",
    ]

    private var nothingMode: Bool {
        let undoable = rows.filter { !$0.isAdded }
        return !undoable.isEmpty && undoable.allSatisfy { $0.choice == .undo }
            && !rows.contains { $0.isAdded }
    }
    private var touched: Bool { rows.contains { $0.choice != .right || $0.isAdded } }
    private var canSave: Bool {
        touched || !reasons.isEmpty || !notes.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        StackNavigation {
            Form {
                Section("You said") { Text("“\(example.transcript)”").font(.callout) }

                Section {
                    Button {
                        withAnimation { setNothing(!nothingMode) }
                    } label: {
                        HStack {
                            Image(systemName: nothingMode ? "checkmark.circle.fill" : "circle")
                                .foregroundColor(nothingMode ? .red : .secondary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Nothing should have been done").foregroundColor(.primary)
                                Text("Takes back everything below that it can.")
                                    .font(.caption).foregroundColor(.secondary)
                            }
                        }
                    }
                }

                Section {
                    ForEach($rows) { $row in
                        if !row.isAdded { FixRowView(row: $row) }
                    }
                } header: {
                    let n = rows.filter { !$0.isAdded }.count
                    Text("What it did · \(n) \(n == 1 ? "thing" : "things")")
                }

                Section {
                    ForEach($rows) { $row in
                        if row.isAdded {
                            FixRowView(row: $row, onRemove: { rows.removeAll { $0.id == row.id } })
                        }
                    }
                    HStack(spacing: 12) {
                        Button { add("event") } label: { Label("Event", systemImage: "plus") }
                            .buttonStyle(.bordered)
                        Button { add("todo") } label: { Label("To-do", systemImage: "plus") }
                            .buttonStyle(.bordered)
                    }
                } header: { Text("Missed something?") }

                Section {
                    FlowChips(options: Self.reasonChips, selected: $reasons)
                    TextField("Anything else? e.g. it heard 'Aura' but I said 'Nurit'",
                              text: $notes, axis: .vertical)
                        .lineLimit(1...4)
                } header: { Text("What went wrong?") } footer: {
                    Text(footer)
                }
            }
            .navigationTitle("Fix this")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { onDone(plan()); dismiss() }.disabled(!canSave)
                }
            }
            .onAppear { if rows.isEmpty { rows = FixObject.build(from: example) } }
        }
    }

    private var footer: String {
        if nothingMode { return "Saving takes it all back and teaches the assistant this should have done nothing." }
        if touched { return "Saving fixes your calendar and teaches the assistant the corrected version." }
        return "Stored with the command so the assistant can learn from it."
    }

    private func setNothing(_ on: Bool) {
        if on { rows.removeAll { $0.isAdded } }
        for i in rows.indices where !rows[i].isAdded {
            rows[i].choice = on ? .undo : .right
        }
        if on { reasons.insert("Didn't ask for this") } else { reasons.remove("Didn't ask for this") }
    }

    private func add(_ kind: String) {
        let today = FixRowView.iso.string(from: Date())
        withAnimation {
            rows.append(FixObject(index: nil, action: "", choice: .change, kind: kind, title: "",
                                  date: kind == "event" ? today : "",
                                  start: kind == "event" ? "09:00" : "",
                                  end: kind == "event" ? "10:00" : ""))
        }
        reasons.insert("Missed part of it")
    }

    // MARK: Save

    private func plan() -> FixPlan {
        var ops: [FixOp] = []
        for r in rows { ops += Self.ops(for: r) }
        let why = reasons.sorted().joined(separator: "; ")
        let text = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        let note = [why.isEmpty ? "" : "[\(why)]", text].filter { !$0.isEmpty }.joined(separator: " ")
        guard touched else {
            return FixPlan(ops: [], feedback: "rejected", correction: nil, notes: note)
        }
        return FixPlan(ops: ops, feedback: "corrected", correction: gold(), notes: note)
    }

    /// The calendar writes one row asks for.
    static func ops(for r: FixObject) -> [FixOp] {
        let id = r.record?.id
        if r.isAdded {
            guard !r.title.trimmingCharacters(in: .whitespaces).isEmpty else { return [] }
            return r.kind == "event" ? [.createEvent(eventFields(r))] : [.createTodo(r.title, r.date)]
        }
        switch r.choice {
        case .right:
            return []
        case .undo:
            guard r.canUndo else { return [] }
            if r.isCreate, let id { return [r.record?.type == "event" ? .deleteEvent(id) : .deleteTodo(id)] }
            if r.isDelete, let item = r.record?.restore { return [.restore(item)] }
            if r.isComplete, let id { return [.toggleTodo(id)] }
            if r.isUpdate, let id, let b = r.record?.before {
                if r.record?.type == "event" {
                    var f: [String: Any] = ["title": b.title, "date": b.date, "start_time": b.startTime]
                    if let e = b.endTime, !e.isEmpty { f["end_time"] = e }
                    return [.patchEvent(id, f)]
                }
                return [.patchTodo(id, b.title, b.date)]
            }
            return []
        case .change:
            guard let id, let landed = r.record?.type, r.record?.isGone == false else {
                // Nothing to edit in place (a deleted row, or one never linked):
                // the corrected version is still taught, just not written.
                return []
            }
            if landed != r.kind {
                // The wrong KIND: take the row out and make the right one.
                let out: FixOp = landed == "event" ? .deleteEvent(id) : .deleteTodo(id)
                let make: FixOp = r.kind == "event" ? .createEvent(eventFields(r)) : .createTodo(r.title, r.date)
                return [out, make]
            }
            return r.kind == "event" ? [.patchEvent(id, eventFields(r))] : [.patchTodo(id, r.title, r.date)]
        }
    }

    static func eventFields(_ r: FixObject) -> [String: Any] {
        var f: [String: Any] = ["title": r.title]
        if !r.date.isEmpty { f["date"] = r.date }
        if !r.start.isEmpty { f["start_time"] = r.start }
        if !r.end.isEmpty { f["end_time"] = r.end }
        return f
    }

    /// What the command SHOULD have produced, action by action in the order
    /// it ran, so the Mac can pair it with what it did (an action taken back
    /// is simply absent; "nothing should have been done" is an empty list).
    private func gold() -> [[String: Any]] {
        var out: [[String: Any]] = []
        for (i, a) in example.actions.enumerated() {
            let mine = rows.filter { $0.index == i }
            if mine.isEmpty || mine.allSatisfy({ $0.choice == .right }) {
                out.append(["action": a.action, "parameters": a.parameters.mapValues { $0.value }])
                continue
            }
            let kept = mine.filter { $0.choice != .undo }
            guard !kept.isEmpty else { continue }
            if a.action.hasPrefix("create_") {
                let todos = kept.filter { $0.kind == "todo" }.map(\.title)
                if !todos.isEmpty {
                    var p: [String: Any] = ["titles": todos]
                    if let d = kept.first(where: { $0.kind == "todo" && !$0.date.isEmpty })?.date { p["due_date"] = d }
                    out.append(["action": "create_todo", "parameters": p])
                }
                for e in kept where e.kind == "event" {
                    out.append(["action": "create_event", "parameters": Self.eventFields(e)])
                }
            } else {
                var p = a.parameters.mapValues { $0.value }
                if let r = kept.first, r.choice == .change {
                    for (k, v) in Self.eventFields(r) { p[k] = v }
                }
                out.append(["action": a.action, "parameters": p])
            }
        }
        for r in rows where r.isAdded && !r.title.trimmingCharacters(in: .whitespaces).isEmpty {
            out.append(r.kind == "event"
                       ? ["action": "create_event", "parameters": Self.eventFields(r)]
                       : ["action": "create_todo", "parameters": ["titles": [r.title]].merging(
                            r.date.isEmpty ? [:] : ["due_date": r.date]) { a, _ in a }])
        }
        return out
    }
}

/// One object in the fix sheet: what it is now, the verdict, and — when
/// being changed — the fields, with real pickers rather than typed dates.
private struct FixRowView: View {
    @Binding var row: FixObject
    var onRemove: (() -> Void)? = nil

    static let iso: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()
    static let hm: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "HH:mm"; f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()

    private var choices: [FixObject.Choice] {
        if row.isReadOnly { return [.right, .undo] }
        if row.isDelete || row.isComplete { return [.right, .undo] }
        return [.right, .change, .undo]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: icon).foregroundColor(tint).frame(width: 18)
                VStack(alignment: .leading, spacing: 2) {
                    Text(row.verb.uppercased()).font(.caption2.weight(.semibold)).foregroundColor(.secondary)
                    Text(row.title.isEmpty ? (row.isAdded ? "New" : "—") : row.title)
                        .font(.body).strikethrough(row.choice == .undo && !row.isReadOnly)
                    if !row.when.isEmpty {
                        Text(row.when).font(.footnote).foregroundColor(.secondary)
                    }
                    if let b = row.record?.before, row.isUpdate {
                        Text("was: \(b.title)\(b.date.isEmpty ? "" : " · " + FixObject.pretty(b.date))\(b.startTime.isEmpty ? "" : " " + b.startTime)")
                            .font(.caption).foregroundColor(.secondary)
                    }
                    if row.record?.isGone == true && row.isCreate {
                        Text("Already removed from your calendar").font(.caption).foregroundColor(.secondary)
                    }
                }
                Spacer()
                if let onRemove {
                    Button(role: .destructive, action: onRemove) { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.borderless).foregroundColor(.secondary)
                }
            }

            if !row.isAdded {
                Picker("", selection: $row.choice) {
                    ForEach(choices, id: \.self) { c in Text(label(c)).tag(c) }
                }
                .pickerStyle(.segmented)
                if row.choice == .undo && !row.canUndo && !row.isReadOnly {
                    Text("Can't take this back from here — it's recorded so the assistant learns.")
                        .font(.caption).foregroundColor(.secondary)
                }
            }

            if row.choice == .change || row.isAdded { editor }
        }
        .padding(.vertical, 4)
    }

    private func label(_ c: FixObject.Choice) -> String {
        switch c {
        case .right: return "Right"
        case .change: return "Change"
        case .undo: return row.undoLabel
        }
    }

    private var icon: String {
        if row.isReadOnly { return "text.bubble" }
        if row.isDelete { return "trash" }
        return row.kind == "event" ? "calendar" : "checklist"
    }
    private var tint: Color {
        switch row.choice {
        case .right: return .secondary
        case .change: return .orange
        case .undo: return .red
        }
    }

    @ViewBuilder private var editor: some View {
        VStack(alignment: .leading, spacing: 8) {
            if row.isCreate || row.isAdded {
                Picker("Kind", selection: kindBinding) {
                    Text("Event").tag("event")
                    Text("To-do").tag("todo")
                }
                .pickerStyle(.segmented)
            }
            TextField("Title", text: $row.title)
                .textFieldStyle(.roundedBorder)
            if row.kind == "event" {
                DatePicker("Day", selection: dateBinding, displayedComponents: .date)
                HStack {
                    DatePicker("From", selection: timeBinding(\.start), displayedComponents: .hourAndMinute)
                    DatePicker("to", selection: timeBinding(\.end), displayedComponents: .hourAndMinute)
                }
            } else {
                Toggle("Due on a day", isOn: dueBinding)
                if !row.date.isEmpty {
                    DatePicker("Due", selection: dateBinding, displayedComponents: .date)
                }
            }
        }
        .font(.subheadline)
    }

    /// Switching to an event gives it a day and the ruled default hour
    /// (DEVQA Q47: an event with no stated clock sits at 09:00).
    private var kindBinding: Binding<String> {
        Binding(get: { row.kind }, set: { k in
            row.kind = k
            if k == "event" {
                if row.date.isEmpty { row.date = Self.iso.string(from: Date()) }
                if row.start.isEmpty { row.start = "09:00"; row.end = "10:00" }
            }
        })
    }
    private var dateBinding: Binding<Date> {
        Binding(get: { Self.iso.date(from: row.date) ?? Date() },
                set: { row.date = Self.iso.string(from: $0) })
    }
    private var dueBinding: Binding<Bool> {
        Binding(get: { !row.date.isEmpty },
                set: { row.date = $0 ? Self.iso.string(from: Date()) : "" })
    }
    private func timeBinding(_ key: WritableKeyPath<FixObject, String>) -> Binding<Date> {
        Binding(get: { Self.hm.date(from: row[keyPath: key]) ?? Self.hm.date(from: "09:00")! },
                set: { row[keyPath: key] = Self.hm.string(from: $0) })
    }
}

/// Tappable reason chips that wrap onto as many lines as they need.
private struct FlowChips: View {
    let options: [String]
    @Binding var selected: Set<String>

    var body: some View {
        ChipFlow(spacing: 8) {
            ForEach(options, id: \.self) { o in
                let on = selected.contains(o)
                Button {
                    if on { selected.remove(o) } else { selected.insert(o) }
                } label: {
                    Text(o).font(.footnote)
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(Capsule().fill(on ? Color.accentColor.opacity(0.18) : Color.secondary.opacity(0.10)))
                        .overlay(Capsule().stroke(on ? Color.accentColor : .clear, lineWidth: 1))
                        .foregroundColor(on ? .accentColor : .primary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 2)
    }
}

/// A left-to-right wrapping layout.
private struct ChipFlow: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, line: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > 0 && x + s.width > width { x = 0; y += line + spacing; line = 0 }
            x += s.width + spacing; line = max(line, s.height)
        }
        return CGSize(width: width.isFinite ? width : x, height: y + line)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, line: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > bounds.minX && x + s.width > bounds.maxX { x = bounds.minX; y += line + spacing; line = 0 }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing; line = max(line, s.height)
        }
    }
}
