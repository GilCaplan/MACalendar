import SwiftUI

// A to-do and an event linked as ONE THING (Gil, 2026-09-25: "add a linking
// feature between todo and events, they can be linked and the same thing").
//
// Two ways in, mirroring the Mac:
//   • an event's detail sheet — `LinkedTodoSection`: its to-do (tick it off
//     from here), Unlink; or "Also add as a to-do" / "Link a to-do…"
//   • a task's context menu — `TaskRowView`: "Add to Calendar", "Link to
//     Event…" (`EventPickerSheet`), "Unlink from Event"
// The Mac owns the link and its rules (`db` "A to-do and an event linked as
// ONE THING"); nothing here decides anything.

struct LinkedTodoSection: View {
    @EnvironmentObject var api: APIClient
    let eventId: Int

    @State private var todo: Todo?
    @State private var loaded = false
    @State private var picking = false
    @State private var busy = false

    var body: some View {
        Section {
            if let todo {
                HStack(spacing: 10) {
                    Button { toggle(todo) } label: {
                        Image(systemName: todo.isDone ? "checkmark.circle.fill" : "circle")
                            .font(.title3)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(todo.isDone ? "mark not done" : "mark done")
                    Label(todo.title, systemImage: "link")
                        .strikethrough(todo.isDone)
                        .foregroundColor(todo.isDone ? .secondary : .primary)
                    Spacer()
                    Button("Unlink") { run { try await api.unlinkTodo(todoId: todo.id) } }
                        .buttonStyle(.borderless)
                }
            } else if loaded {
                Button {
                    run { try await api.addLinkedTodo(eventId: eventId) }
                } label: {
                    Label("Also add as a to-do", systemImage: "checklist")
                }
                Button { picking = true } label: {
                    Label("Link a to-do…", systemImage: "link")
                }
            } else {
                ProgressView()
            }
        } header: {
            Text("To-do")
        } footer: {
            if todo != nil {
                Text("Linked: renaming or moving one changes the other. Deleting the event removes the to-do.")
            }
        }
        .disabled(busy || eventId <= 0)
        .task(id: eventId) { await load() }
        .onReceive(api.$refreshTick) { _ in Task { await load() } }
        .sheet(isPresented: $picking) {
            TodoPickerSheet { picked in
                run { try await api.linkTodo(todoId: picked.id, eventId: eventId) }
            }
            .environmentObject(api)
        }
    }

    private func load() async {
        todo = try? await api.linkedTodo(eventId: eventId)
        loaded = true
    }

    private func toggle(_ t: Todo) {
        run { _ = try await api.toggleTodo(id: t.id) }
    }

    private func run(_ work: @escaping () async throws -> Void) {
        busy = true
        Task {
            do { try await work() } catch { api.announceRefusal(error, doing: "link the to-do") }
            await load()
            busy = false
        }
    }
}

/// Open to-dos with no event yet, searchable.
struct TodoPickerSheet: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.dismiss) private var dismiss
    let onPick: (Todo) -> Void

    @State private var todos: [Todo] = []
    @State private var query = ""

    private var shown: [Todo] {
        let open = todos.filter { $0.linkedEventId == nil && !$0.isDone }
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        return q.isEmpty ? open : open.filter { $0.title.lowercased().contains(q) }
    }

    var body: some View {
        NavigationStack {
            List(shown) { t in
                Button {
                    onPick(t)
                    dismiss()
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t.title).foregroundColor(.primary)
                        if !t.dueDate.isEmpty {
                            Text("due \(t.dueDate)").font(.caption).foregroundColor(.secondary)
                        }
                    }
                }
            }
            .overlay {
                if shown.isEmpty {
                    Text("No open to-dos without an event").foregroundColor(.secondary)
                }
            }
            .searchable(text: $query)
            .navigationTitle("Link a to-do")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
            .task { todos = (try? await api.todos(list: "all")) ?? [] }
        }
    }
}

/// Events from a week back to two months ahead, searchable — the same window
/// the Mac's picker offers (`link_picker.EVENTS_BACK / EVENTS_AHEAD`).
struct EventPickerSheet: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.dismiss) private var dismiss
    let onPick: (CalendarEvent) -> Void

    @State private var events: [CalendarEvent] = []
    @State private var query = ""

    private static let back = 7, ahead = 60

    private var shown: [CalendarEvent] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        return q.isEmpty ? events : events.filter { $0.title.lowercased().contains(q) }
    }

    var body: some View {
        NavigationStack {
            List(shown) { e in
                Button {
                    onPick(e)
                    dismiss()
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(e.title).foregroundColor(.primary)
                        Text("\(e.date)  \(e.startTime)").font(.caption).foregroundColor(.secondary)
                    }
                }
            }
            .overlay {
                if shown.isEmpty {
                    Text("No events in the next two months").foregroundColor(.secondary)
                }
            }
            .searchable(text: $query)
            .navigationTitle("Link to an event")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
            .task { await load() }
        }
    }

    private func load() async {
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        guard let lo = cal.date(byAdding: .day, value: -Self.back, to: today),
              let hi = cal.date(byAdding: .day, value: Self.ahead, to: today) else { return }
        let fmt = ISO8601DateFormatter.yyyyMMdd
        let loS = fmt.string(from: lo), hiS = fmt.string(from: hi)
        var seen = Set<Int>(), out: [CalendarEvent] = []
        var month = cal.date(from: cal.dateComponents([.year, .month], from: lo)) ?? lo
        while month <= hi {
            let c = cal.dateComponents([.year, .month], from: month)
            let rows = (try? await api.eventsForMonth(year: c.year ?? 0, month: c.month ?? 0)) ?? []
            for e in rows where e.date >= loS && e.date <= hiS && e.id > 0 && !seen.contains(e.id) {
                seen.insert(e.id)
                out.append(e)
            }
            month = cal.date(byAdding: .month, value: 1, to: month) ?? hi.addingTimeInterval(1)
        }
        events = out.sorted { ($0.date, $0.startTime) < ($1.date, $1.startTime) }
    }
}
