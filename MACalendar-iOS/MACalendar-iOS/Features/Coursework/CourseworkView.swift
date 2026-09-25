import SwiftUI

// MARK: - Main View

struct CourseworkView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = CourseStore.shared
    @State private var showAddCourse = false
    @State private var editingCourse: Course? = nil
    @State private var editMode: EditMode = .inactive

    private var hasCompleted: Bool {
        store.assignments.contains { $0.isDone }
    }

    var body: some View {
        StackNavigation {
            Group {
                if store.courses.isEmpty {
                    VStack(spacing: 16) {
                        Image(systemName: "graduationcap")
                            .font(.system(size: 56))
                            .foregroundColor(.secondary)
                        Text("No Courses Yet")
                            .font(.title2.weight(.semibold))
                        Text("Tap + to add your first course")
                            .foregroundColor(.secondary)
                        Button("Add Course") { showAddCourse = true }
                            .buttonStyle(.borderedProminent)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List {
                        ForEach(store.courses) { course in
                            CourseSection(
                                course: course,
                                onEdit:   { editingCourse = course },
                                onDelete: { deleteCourse(course) }
                            )
                            .environmentObject(api)
                        }
                        .onDelete { offsets in
                            offsets.forEach { deleteCourse(store.courses[$0]) }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .environment(\.editMode, $editMode)
                }
            }
            .navigationTitle("Coursework")
            .toolbar {
                ToolbarItemGroup(placement: .navigationBarLeading) {
                    if !store.courses.isEmpty {
                        Button(editMode == .active ? "Done" : "Edit") {
                            withAnimation { editMode = editMode == .active ? .inactive : .active }
                        }
                    }
                    if hasCompleted {
                        Button(action: { settings.hideCompletedAssignments.toggle() }) {
                            Image(systemName: settings.hideCompletedAssignments ? "eye" : "eye.slash")
                        }
                        Button(action: clearCompleted) {
                            Label("Clear Done", systemImage: "trash.slash")
                                .foregroundColor(.red)
                        }
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { showAddCourse = true } label: { Image(systemName: "plus") }
                        .accessibilityIdentifier("coursework-add-course")
                }
            }
        }
        .task { await load() }
        .onReceive(api.$refreshTick) { _ in Task { await load() } }
        .sheet(isPresented: $showAddCourse) {
            CourseEditSheet(course: nil).environmentObject(api)
        }
        .sheet(item: $editingCourse) { course in
            CourseEditSheet(course: course).environmentObject(api)
        }
    }

    private func load() async {
        async let c = try? api.courses()
        async let a = try? api.allAssignments()
        if let courses = await c { store.cacheCourses(courses) }
        if let assignments = await a { store.cacheAllAssignments(assignments) }
    }

    // The `try?` these used to be is what the whole offline queue was missing:
    // with the Mac away it threw away the failure, the local cache said the
    // course was gone, and the next sync downloaded it again. The client queues
    // it now, so reaching here at all means the Mac ANSWERED and refused — the
    // one case nothing will retry, and so the one worth saying out loud.
    private func deleteCourse(_ course: Course) {
        store.removeCourse(course.id)
        Task {
            do { try await api.deleteCourse(id: course.id) }
            catch { api.announceRefusal(error, doing: "delete that course") }
        }
    }

    private func clearCompleted() {
        store.removeCompletedAssignments()
        Task {
            do { try await api.clearCompletedAssignments() }
            catch { api.announceRefusal(error, doing: "clear the finished assignments") }
            await load()
        }
    }
}

// MARK: - Course Section

private struct CourseSection: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = CourseStore.shared

    let course: Course
    let onEdit: () -> Void
    let onDelete: () -> Void

    @State private var newAssignmentTitle = ""
    @State private var addingAssignment = false

    private var sortedAssignments: [Assignment] {
        let all = store.assignments(for: course.id)
        let visible = settings.hideCompletedAssignments ? all.filter { !$0.isDone } : all
        return visible.sorted { a, b in
            if a.isDone != b.isDone { return !a.isDone }
            if a.dueDate.isEmpty && b.dueDate.isEmpty { return false }
            if a.dueDate.isEmpty { return false }
            if b.dueDate.isEmpty { return true }
            return a.dueDate < b.dueDate
        }
    }

    var body: some View {
        Section {
            if sortedAssignments.isEmpty && !addingAssignment {
                Text("No assignments yet")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }

            ForEach(sortedAssignments) { assignment in
                AssignmentRowView(
                    assignment: assignment,
                    course: course,
                    onToggle:       { toggleAssignment(assignment) },
                    onDelete:       { deleteAssignment(assignment) },
                    onSyncCalendar: { syncToCalendar(assignment) },
                    onSetDueDate:   { date in setDueDate(date, for: assignment) }
                )
            }

            if addingAssignment {
                HStack {
                    TextField("Assignment title…", text: $newAssignmentTitle)
                        .submitLabel(.done)
                        .onSubmit(submitAssignment)
                    Button(action: submitAssignment) {
                        Image(systemName: "plus.circle.fill").foregroundColor(settings.accentColor)
                    }
                    .disabled(newAssignmentTitle.isEmpty)
                    Button {
                        addingAssignment = false
                        newAssignmentTitle = ""
                    } label: {
                        Image(systemName: "xmark.circle").foregroundColor(.secondary)
                    }
                }
                .buttonStyle(.plain)
            } else {
                Button { addingAssignment = true } label: {
                    Label("Add Assignment", systemImage: "plus")
                        .font(.subheadline)
                        .foregroundColor(settings.accentColor)
                }
                .buttonStyle(.plain)
            }
        } header: {
            CourseHeaderView(course: course, onEdit: onEdit, onDelete: onDelete)
        }
    }

    private func submitAssignment() {
        let title = newAssignmentTitle.trimmingCharacters(in: .whitespaces)
        guard !title.isEmpty else { return }
        newAssignmentTitle = ""
        addingAssignment = false
        // The optimistic row belongs to the client now: it inserts the
        // placeholder before asking the Mac, so the assignment is on screen
        // either way, and either remaps it to the real id or queues the create
        // carrying it. Doing it here as well made two rows whenever the Mac
        // was away — one that synced and one that never would.
        Task {
            do {
                let newId = try await api.createAssignment(courseId: course.id, title: title)
                if newId > 0, let fresh = try? await api.allAssignments() {
                    store.cacheAllAssignments(fresh)
                }
            } catch {
                api.announceRefusal(error, doing: "add that assignment")
            }
        }
    }

    private func toggleAssignment(_ assignment: Assignment) {
        store.toggleAssignment(assignment.id)
        Task {
            do { _ = try await api.toggleAssignment(id: assignment.id) }
            catch { api.announceRefusal(error, doing: "tick that assignment off") }
        }
    }

    private func deleteAssignment(_ assignment: Assignment) {
        store.removeAssignment(assignment.id)
        Task {
            do { try await api.deleteAssignment(id: assignment.id) }
            catch { api.announceRefusal(error, doing: "delete that assignment") }
        }
    }

    private func setDueDate(_ date: Date?, for assignment: Assignment) {
        let newStr = date.map { DateFormatter.isoDay.string(from: $0) } ?? ""
        let dateChanged = newStr != assignment.dueDate
        store.patchAssignment(assignment.id, dueDate: newStr)
        if dateChanged { store.clearCalendarEventId(assignment.id) }
        Task {
            do { try await api.updateAssignment(id: assignment.id, dueDate: newStr) }
            catch { api.announceRefusal(error, doing: "save that due date") }
        }
    }

    private func syncToCalendar(_ assignment: Assignment) {
        guard !assignment.dueDate.isEmpty, assignment.calendarEventId == nil else { return }
        Task {
            let fields: [String: Any] = [
                "title":       "📚 \(assignment.title)",
                "date":        assignment.dueDate,
                "start_time":  "23:59",
                "end_time":    "23:59",
                "color":       course.color,
                "description": "\(course.number) — \(course.name)"
            ]
            // A placeholder id (negative, the Mac away) is kept rather than
            // rejected: the event create is queued, and `remapTemporaryID`
            // rewrites `calendar_event_id` here and in the queued PATCH once the
            // Mac issues the real one. Requiring a positive id meant the event
            // was made and the assignment never learned which one it was, so
            // "Add to calendar" made a second copy later.
            guard let eventId = try? await api.createEvent(fields), eventId != 0 else { return }
            store.patchAssignment(assignment.id, calendarEventId: eventId)
            do { try await api.updateAssignment(id: assignment.id, calendarEventId: eventId) }
            catch { api.announceRefusal(error, doing: "link that assignment to its event") }
        }
    }
}

// MARK: - Course Header

private struct CourseHeaderView: View {
    @EnvironmentObject var settings: AppSettings
    let course: Course
    let onEdit: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Circle()
                .fill(Color(hex: course.color) ?? settings.accentColor)
                .frame(width: 10, height: 10)
                .padding(.top, 4)

            VStack(alignment: .leading, spacing: 2) {
                if !course.number.isEmpty {
                    Text(course.number)
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                Text(course.name)
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(.primary)
                    .multilineTextAlignment(.leading)

                if !course.partners.isEmpty {
                    HStack(spacing: 4) {
                        Image(systemName: "person.2")
                            .font(.caption2)
                        Text(course.partners.joined(separator: " · "))
                            .font(.caption2)
                            .lineLimit(1)
                    }
                    .foregroundColor(.secondary)
                }
            }

            Spacer()

            Menu {
                Button { onEdit() } label: {
                    Label("Edit Course", systemImage: "pencil")
                }
                Button(role: .destructive) { onDelete() } label: {
                    Label("Delete Course", systemImage: "trash")
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.body)
                    .foregroundColor(.secondary)
                    .padding(.vertical, 2)
            }
            // Keyed by NAME so a UI test can open one particular course's menu:
            // the id changes under it the moment an offline create syncs.
            .accessibilityIdentifier("course-menu-\(course.name)")
        }
        .textCase(nil)
        .padding(.vertical, 4)
    }
}

// MARK: - Assignment Row

private struct AssignmentRowView: View {
    @EnvironmentObject var settings: AppSettings
    let assignment: Assignment
    let course: Course
    let onToggle: () -> Void
    let onDelete: () -> Void
    let onSyncCalendar: () -> Void
    let onSetDueDate: (Date?) -> Void

    @State private var showDueDatePicker = false

    var body: some View {
        HStack(spacing: 10) {
            Button(action: onToggle) {
                Image(systemName: assignment.isDone ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundColor(assignment.isDone ? (Color(hex: course.color) ?? settings.accentColor) : .secondary)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 2) {
                Text(assignment.title)
                    .font(.body)
                    .strikethrough(assignment.isDone)
                    .foregroundColor(assignment.isDone ? .secondary : .primary)

                if !assignment.dueDate.isEmpty {
                    Text(dueDateLabel)
                        .font(.caption)
                        .foregroundColor(dueDateColor)
                }
            }

            Spacer()

            Button { showDueDatePicker = true } label: {
                Image(systemName: assignment.dueDate.isEmpty ? "calendar.badge.plus" : "calendar")
                    .font(.footnote)
                    .foregroundColor(
                        assignment.dueDate.isEmpty
                            ? .secondary
                            : (Color(hex: course.color) ?? settings.accentColor)
                    )
            }
            .buttonStyle(.plain)

            if !assignment.dueDate.isEmpty {
                Button(action: onSyncCalendar) {
                    Image(systemName: assignment.calendarEventId != nil
                          ? "calendar.badge.checkmark"
                          : "square.and.arrow.up")
                        .font(.footnote)
                        .foregroundColor(assignment.calendarEventId != nil ? .green : .secondary)
                }
                .buttonStyle(.plain)
                .disabled(assignment.calendarEventId != nil)
            }
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive, action: onDelete) {
                Label("Delete", systemImage: "trash")
            }
        }
        .sheet(isPresented: $showDueDatePicker) {
            DueDatePickerSheet(currentDateStr: assignment.dueDate, onSave: onSetDueDate)
        }
    }

    private var dueDateLabel: String {
        guard let date = DateFormatter.isoDay.date(from: assignment.dueDate) else { return assignment.dueDate }
        let cal   = Calendar.current
        let today = cal.startOfDay(for: Date())
        let due   = cal.startOfDay(for: date)
        let days  = cal.dateComponents([.day], from: today, to: due).day ?? 0
        if days == 0 { return "Due today" }
        if days == 1 { return "Due tomorrow" }
        if days  < 0 { return "Overdue (\(-days)d)" }
        let f = DateFormatter(); f.dateFormat = "MMM d"
        return f.string(from: date)
    }

    private var dueDateColor: Color {
        guard let date = DateFormatter.isoDay.date(from: assignment.dueDate) else { return .secondary }
        let cal   = Calendar.current
        let today = cal.startOfDay(for: Date())
        let due   = cal.startOfDay(for: date)
        let days  = cal.dateComponents([.day], from: today, to: due).day ?? 0
        if days <= 0 { return .red }
        if days <= 3 { return .orange }
        return .secondary
    }
}

// MARK: - Due Date Picker Sheet

private struct DueDatePickerSheet: View {
    @Environment(\.dismiss) private var dismiss

    let currentDateStr: String
    let onSave: (Date?) -> Void

    @State private var selectedDate: Date

    init(currentDateStr: String, onSave: @escaping (Date?) -> Void) {
        self.currentDateStr = currentDateStr
        self.onSave = onSave
        _selectedDate = State(initialValue: DateFormatter.isoDay.date(from: currentDateStr) ?? Date())
    }

    var body: some View {
        StackNavigation {
            VStack {
                DatePicker("Due Date", selection: $selectedDate, displayedComponents: .date)
                    .datePickerStyle(.graphical)
                    .padding()
                Spacer()
            }
            .navigationTitle("Set Due Date")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    HStack(spacing: 16) {
                        Button("Cancel") { dismiss() }
                        if !currentDateStr.isEmpty {
                            Button("Clear", role: .destructive) { onSave(nil); dismiss() }
                        }
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Save") { onSave(selectedDate); dismiss() }
                        .fontWeight(.semibold)
                }
            }
        }
    }
}

// MARK: - Course Edit Sheet

private let courseColorPalette = [
    "#4BA8A0", "#6B42C8", "#B05090", "#5AACBA",
    "#8855D0", "#4A82C8", "#6A9FD0", "#5A8A60", "#7A3A3A"
]

struct CourseEditSheet: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = CourseStore.shared
    @Environment(\.dismiss) private var dismiss

    private let existingCourse: Course?

    @State private var number: String
    @State private var name: String
    @State private var selectedColor: String
    @State private var partners: [String]
    @State private var newPartner = ""

    init(course: Course?) {
        self.existingCourse = course
        _number        = State(initialValue: course?.number   ?? "")
        _name          = State(initialValue: course?.name     ?? "")
        _selectedColor = State(initialValue: course?.color    ?? courseColorPalette[0])
        _partners      = State(initialValue: course?.partners ?? [])
    }

    var body: some View {
        StackNavigation {
            Form {
                Section("Course Info") {
                    TextField("Course Number (e.g. 00960336)", text: $number)
                        .keyboardType(.numbersAndPunctuation)
                    TextField("Course Name", text: $name)
                        .accessibilityIdentifier("course-name-field")
                }

                Section("Color") {
                    LazyVGrid(columns: Array(repeating: .init(.flexible()), count: 6), spacing: 12) {
                        ForEach(courseColorPalette, id: \.self) { hex in
                            Circle()
                                .fill(Color(hex: hex) ?? .blue)
                                .frame(width: 36, height: 36)
                                .overlay(
                                    Circle()
                                        .stroke(Color.primary.opacity(selectedColor == hex ? 1 : 0), lineWidth: 3)
                                        .padding(2)
                                )
                                .onTapGesture { selectedColor = hex }
                        }
                    }
                    .padding(.vertical, 4)
                }

                Section("Partners") {
                    ForEach(partners, id: \.self) { partner in
                        Label(partner, systemImage: "person")
                    }
                    .onDelete { offsets in partners.remove(atOffsets: offsets) }

                    HStack {
                        TextField("Add partner name…", text: $newPartner)
                            .submitLabel(.done)
                            .onSubmit(addPartner)
                        Button(action: addPartner) {
                            Image(systemName: "plus.circle.fill").foregroundColor(settings.accentColor)
                        }
                        .disabled(newPartner.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                    .buttonStyle(.plain)
                }

            }
            .navigationTitle(existingCourse == nil ? "Add Course" : "Edit Course")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Save", action: save)
                        .accessibilityIdentifier("course-save")
                        .fontWeight(.semibold)
                        .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }

    private func addPartner() {
        let p = newPartner.trimmingCharacters(in: .whitespaces)
        guard !p.isEmpty, !partners.contains(p) else { return }
        partners.append(p)
        newPartner = ""
    }

    private func save() {
        let trimmedName   = name.trimmingCharacters(in: .whitespaces)
        let trimmedNumber = number.trimmingCharacters(in: .whitespaces)
        guard !trimmedName.isEmpty else { return }

        if let existing = existingCourse {
            store.patchCourse(existing.id, number: trimmedNumber, name: trimmedName,
                              color: selectedColor, partners: partners)
            Task {
                do {
                    try await api.updateCourse(id: existing.id, number: trimmedNumber,
                                               name: trimmedName, color: selectedColor,
                                               partners: partners)
                } catch { api.announceRefusal(error, doing: "save that course") }
            }
        } else {
            // The local row is the client's doing (it needs the placeholder id
            // to put in the queued create), so this no longer inserts one of its
            // own on failure — that is what used to leave a duplicate course
            // behind after the queued create finally landed.
            Task {
                do {
                    let newId = try await api.createCourse(number: trimmedNumber, name: trimmedName,
                                                           color: selectedColor, partners: partners)
                    if newId > 0, let fresh = try? await api.courses() { store.cacheCourses(fresh) }
                } catch {
                    api.announceRefusal(error, doing: "add that course")
                }
            }
        }
        dismiss()
    }
}
