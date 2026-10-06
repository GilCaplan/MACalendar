import SwiftUI

/// Small pill used for task tags everywhere in the Tasks tab (rows, filter bar,
/// tag pickers). `selected` fills it with the tag color; otherwise it's outlined.
struct TagChip: View {
    let name: String
    let hex: String
    var selected: Bool = true
    var compact: Bool = false

    private var color: Color { Color(hex: hex) ?? .accentColor }

    var body: some View {
        Text(name)
            .font(.system(size: compact ? 10 : 12, weight: .semibold))
            .lineLimit(1)
            .padding(.horizontal, compact ? 6 : 10)
            .padding(.vertical, compact ? 2 : 5)
            .background(
                Capsule().fill(selected ? color.opacity(0.9) : color.opacity(0.12))
            )
            .overlay(Capsule().stroke(color.opacity(selected ? 0 : 0.6), lineWidth: 1))
            .foregroundColor(selected ? Color.onColor(hex: hex) : color)
    }
}

struct TaskRowView: View {
    @EnvironmentObject var settings: AppSettings
    @EnvironmentObject var api: APIClient
    @State private var pickingEvent = false
    var todo: Todo
    var allTags: [TodoTag]
    var onToggle: () -> Void
    var onDelete: () -> Void
    var onSave: (String, String, String, [String], Int) -> Void  // title, priority, dueDate, tags, quantity
    var onMoveList: (String) -> Void   // "today" | "general"
    var onTagsChanged: ([String]) -> Void

    @State private var isExpanded = false
    /// The title IS a text field, always — one tap puts the cursor in it, and
    /// Return or tapping away saves (Gil, 2026-10-06). The first attempt drew
    /// a Text and swapped in a field on tap, then focused it from code; inside
    /// a List row that programmatic focus is dropped on device, so the first
    /// tap only swapped two identical-looking views and it took a second tap
    /// to type. A real field needs no focus code to work.
    @FocusState private var titleFocused: Bool
    @State private var editTitle: String
    @State private var editQuantity: Int
    @State private var editPriority: String
    @State private var editDueDate: Date?
    @State private var editTags: [String]

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    init(todo: Todo,
         allTags: [TodoTag] = [],
         onToggle: @escaping () -> Void,
         onDelete: @escaping () -> Void,
         onSave: @escaping (String, String, String, [String], Int) -> Void,
         onMoveList: @escaping (String) -> Void,
         onTagsChanged: @escaping ([String]) -> Void) {
        self.todo = todo
        self.allTags = allTags
        self.onToggle = onToggle
        self.onDelete = onDelete
        self.onSave = onSave
        self.onMoveList = onMoveList
        self.onTagsChanged = onTagsChanged
        _editTitle    = State(initialValue: todo.title)
        _editQuantity = State(initialValue: max(1, todo.quantity))
        _editPriority = State(initialValue: Self.pickerPriority(todo.priority))
        _editDueDate  = State(initialValue: Self.dateFormatter.date(from: todo.dueDate))
        _editTags     = State(initialValue: todo.tags)
    }

    /// The DB's "no priority" is "none" (db.py's column default), and the
    /// picker used to tag None as "" — so every unprioritised task opened a
    /// picker with no matching row ("Picker: the selection \"none\" is
    /// invalid"). Anything the picker does not offer reads as None.
    private static func pickerPriority(_ p: String) -> String {
        ["low", "medium", "high"].contains(p) ? p : "none"
    }

    private func hex(for name: String) -> String {
        allTags.first { $0.name.caseInsensitiveCompare(name) == .orderedSame }?.hexColor
            ?? TodoTag(name: name).hexColor
    }

    /// The list this task is NOT on — where a move sends it.
    private var otherList: String { todo.list == "today" ? "general" : "today" }
    private var otherListName: String { otherList == "today" ? "Today" : "General" }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            // ── Main row ──────────────────────────────────────────────
            HStack(spacing: 12) {
                Button(action: onToggle) {
                    Image(systemName: todo.isDone ? "checkmark.circle.fill" : "circle")
                        .font(.system(size: settings.fontTasks + 4))
                        .foregroundColor(todo.isDone ? settings.accentColor : .secondary)
                }
                .buttonStyle(.plain)

                VStack(alignment: .leading, spacing: 4) {
                    // Title and count share a line: the count is part of what
                    // the task says, so putting it on its own row would read as
                    // a second, unrelated fact about the task.
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        ForEach(todo.icons ?? TitleIcons.icons(for: todo.title), id: \.self) {
                            Ico($0, size: settings.fontTasks)
                        }
                        if !todo.ownerPrefix.isEmpty {
                            Text(todo.ownerPrefix)
                                .font(.system(size: settings.fontTasks))
                                .foregroundColor(.secondary)
                        }
                        // Vertical so a long title wraps like the Text it
                        // replaced; a Return is caught below and means "done".
                        TextField("Title", text: $editTitle, axis: .vertical)
                            .font(.system(size: settings.fontTasks))
                            .strikethrough(todo.isDone && !titleFocused)
                            .foregroundColor(todo.isDone && !titleFocused ? .secondary : .primary)
                            .focused($titleFocused)
                            .submitLabel(.done)
                            .disabled(todo.canEdit == false)
                            .onChange(of: editTitle) { t in
                                if t.contains("\n") {
                                    editTitle = t.replacingOccurrences(of: "\n", with: "")
                                    titleFocused = false
                                }
                            }
                            .accessibilityIdentifier("task-title-field")

                        if let label = todo.quantityLabel {
                            Text(label)
                                .font(.system(size: settings.fontTasks - 2,
                                              weight: .semibold,
                                              design: .rounded))
                                .monospacedDigit()
                                .foregroundColor(settings.accentColor)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 1)
                                .background(
                                    Capsule().fill(settings.accentColor.opacity(0.15))
                                )
                                .opacity(todo.isDone ? 0.5 : 1)
                                .accessibilityLabel("quantity \(todo.quantity)")
                        }

                        if todo.linkedEventId != nil {
                            Image(systemName: "link")
                                .font(.system(size: settings.fontTasks - 4, weight: .semibold))
                                .foregroundColor(.secondary)
                                .opacity(todo.isDone ? 0.5 : 1)
                                .accessibilityLabel("linked to a calendar event")
                        }
                    }

                    if !todo.tags.isEmpty && !isExpanded {
                        HStack(spacing: 4) {
                            ForEach(todo.tags, id: \.self) { t in
                                TagChip(name: t, hex: hex(for: t), selected: true, compact: true)
                                    .opacity(todo.isDone ? 0.5 : 1)
                            }
                        }
                    }
                }

                Spacer()

                // Use .highPriorityGesture on a plain Image — NOT a Button.
                // Button inside a List row conflicts with the row's swipe gesture
                // recognizer even with .buttonStyle(.plain), causing the swipe-delete
                // action to fire on tap. A bare onTapGesture / highPriorityGesture
                // on a non-Button view bypasses that conflict entirely.
                Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(.secondary)
                    .frame(width: 32, height: 32)
                    .contentShape(Rectangle())
                    .highPriorityGesture(
                        TapGesture().onEnded { toggleExpand() }
                    )
            }

            // ── Expanded detail panel ─────────────────────────────────
            if isExpanded {
                VStack(alignment: .leading, spacing: 10) {
                    // Which list — moves the task the moment it changes,
                    // like the swipe and the long-press menu do.
                    HStack(spacing: 6) {
                        Text("List")
                            .font(.system(size: settings.fontTasks - 2))
                            .foregroundColor(.secondary)
                        // Two borderless buttons, not a segmented Picker: in
                        // a List row only a .borderless button gets its own
                        // tap rather than the row's.
                        ForEach(["today", "general"], id: \.self) { l in
                            let on = todo.list == l
                            Button { if !on { onMoveList(l) } } label: {
                                Text(l == "today" ? "Today" : "General")
                                    .font(.system(size: settings.fontTasks - 2,
                                                  weight: on ? .semibold : .regular))
                                    .padding(.horizontal, 12).padding(.vertical, 5)
                                    .background(Capsule().fill(on ? settings.accentColor
                                                                  : Color.secondary.opacity(0.15)))
                                    .foregroundColor(on ? .white : .primary)
                            }
                            .buttonStyle(.borderless)
                            .accessibilityIdentifier("task-list-\(l)")
                        }
                    }

                    // Tags — tap to toggle membership
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Tags")
                            .font(.system(size: settings.fontTasks - 2))
                            .foregroundColor(.secondary)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 6) {
                                ForEach(allTags) { tag in
                                    let on = editTags.contains { $0.caseInsensitiveCompare(tag.name) == .orderedSame }
                                    TagChip(name: tag.name, hex: tag.hexColor, selected: on)
                                        .contentShape(Capsule())
                                        .onTapGesture { toggleTag(tag.name) }
                                }
                                if allTags.isEmpty {
                                    Text("No tags yet — add one with the tag button above.")
                                        .font(.system(size: settings.fontTasks - 3))
                                        .foregroundColor(.secondary)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }

                    // Quantity — the parser reads counts out of speech, and
                    // when it reads one wrong this is the only way to fix it.
                    HStack(spacing: 6) {
                        Text("Quantity")
                            .font(.system(size: settings.fontTasks - 2))
                            .foregroundColor(.secondary)
                        Stepper(value: $editQuantity, in: 1...99) {
                            Text(editQuantity > 1 ? "×\(editQuantity)" : "one")
                                .font(.system(size: settings.fontTasks - 1))
                                .monospacedDigit()
                        }
                    }

                    // Priority picker
                    HStack(spacing: 6) {
                        Text("Priority")
                            .font(.system(size: settings.fontTasks - 2))
                            .foregroundColor(.secondary)
                        Picker("Priority", selection: $editPriority) {
                            Text("None").tag("none")
                            Text("Low").tag("low")
                            Text("Medium").tag("medium")
                            Text("High").tag("high")
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                    }

                    // Due date picker + clear button
                    HStack(spacing: 6) {
                        Text("Due date")
                            .font(.system(size: settings.fontTasks - 2))
                            .foregroundColor(.secondary)

                        DatePicker(
                            "",
                            selection: Binding(
                                get: { editDueDate ?? Date() },
                                set: { editDueDate = $0 }
                            ),
                            displayedComponents: .date
                        )
                        .labelsHidden()
                        .opacity(editDueDate == nil ? 0.4 : 1)

                        if editDueDate == nil {
                            Button("Set") { editDueDate = Date() }
                                .font(.system(size: settings.fontTasks - 2))
                                .buttonStyle(.plain)
                                .foregroundColor(settings.accentColor)
                        } else {
                            Button(action: { editDueDate = nil }) {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundColor(.secondary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(.top, 10)
                .padding(.horizontal, 4)
                .padding(.bottom, 6)
            }
        }
        // Keep edit fields in sync when the parent refreshes (but only when closed
        // so we don't stomp on the user's in-progress edits).
        .onChange(of: todo) { newTodo in
            if !titleFocused { editTitle = newTodo.title }
            guard !isExpanded else { return }
            editQuantity = max(1, newTodo.quantity)
            editPriority = Self.pickerPriority(newTodo.priority)
            editDueDate  = Self.dateFormatter.date(from: newTodo.dueDate)
            editTags     = newTodo.tags
        }
        .onChange(of: titleFocused) { focused in
            // Return, tapping another row, scrolling the keyboard away — every
            // way of leaving the field saves it.
            if !focused { endTitleEdit() }
        }
        .swipeActions(edge: .leading) {
            Button { onMoveList(otherList) } label: {
                Label(otherListName, systemImage: otherList == "today" ? "sun.max" : "tray")
            }
            .tint(settings.accentColor)
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive, action: onDelete) {
                Label("Delete", systemImage: "trash")
            }
        }
        // The event this task IS (Gil, 2026-09-25) — see LinkedTodo.swift.
        // The ONE long-press menu. TasksView used to wrap this row in a
        // second .contextMenu (Tags, Delete) and only one of two stacked
        // menus is ever shown.
        .contextMenu {
            Button { onMoveList(otherList) } label: {
                Label("Move to \(otherListName)",
                      systemImage: otherList == "today" ? "sun.max" : "tray")
            }
            if !allTags.isEmpty {
                Menu("Tags") {
                    ForEach(allTags) { tag in
                        Button {
                            var t = todo.tags
                            if let i = t.firstIndex(where: { $0.caseInsensitiveCompare(tag.name) == .orderedSame }) {
                                t.remove(at: i)
                            } else {
                                t.append(tag.name)
                            }
                            editTags = t
                            onTagsChanged(t)
                        } label: {
                            if todo.hasTag(tag.name) {
                                Label(tag.name, systemImage: "checkmark")
                            } else {
                                Text(tag.name)
                            }
                        }
                    }
                }
            }
            if todo.linkedEventId != nil {
                Button { link { try await api.unlinkTodo(todoId: todo.id) } } label: {
                    Label("Unlink from Event", systemImage: "minus.circle")
                }
            } else if todo.id > 0 {
                Button { link { try await api.putTodoOnCalendar(todoId: todo.id) } } label: {
                    Label("Add to Calendar", systemImage: "calendar.badge.plus")
                }
                Button { pickingEvent = true } label: {
                    Label("Link to Event…", systemImage: "link")
                }
            }
            Button(role: .destructive, action: onDelete) {
                Label("Delete", systemImage: "trash")
            }
        }
        .sheet(isPresented: $pickingEvent) {
            EventPickerSheet { ev in
                link { try await api.linkTodo(todoId: todo.id, eventId: ev.id) }
            }
            .environmentObject(api)
        }
    }

    private func link(_ work: @escaping () async throws -> Void) {
        Task {
            do { try await work() } catch { api.announceRefusal(error, doing: "link the task") }
        }
    }

    private func toggleTag(_ name: String) {
        if let i = editTags.firstIndex(where: { $0.caseInsensitiveCompare(name) == .orderedSame }) {
            editTags.remove(at: i)
        } else {
            editTags.append(name)
        }
    }

    private func endTitleEdit() {
        let trimmed = editTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        // An emptied title is a slip, not a rename — put the old one back.
        guard !trimmed.isEmpty, trimmed != todo.title else {
            editTitle = todo.title
            return
        }
        editTitle = trimmed
        commitEdits()
    }

    private func commitEdits() {
        let dueDateStr = editDueDate.map { Self.dateFormatter.string(from: $0) } ?? ""
        onSave(editTitle, editPriority, dueDateStr, editTags, editQuantity)
    }

    private func toggleExpand() {
        if isExpanded {
            // Collapsing — persist edits
            commitEdits()
        }
        withAnimation(.easeInOut(duration: 0.2)) {
            isExpanded.toggle()
        }
    }
}
