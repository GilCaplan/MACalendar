import Foundation

/// Local JSON cache for courses and assignments.
///
/// Mirrors LocalStore's pattern: a row created offline gets a negative
/// placeholder id, and the write itself is queued by `APIClient.mutate` /
/// `enqueue` and replayed on reconnect. That second half was a LIE until
/// 2026-09-17 — this comment claimed it while `/courses` and `/assignments`
/// appeared in no enqueue call site at all, which is precisely what stopped
/// anyone checking. When the create comes back with a real id,
/// `LocalStore.remapTemporaryID` calls `remapTemporaryID` below so the rows
/// here, and any queued write still naming the placeholder, follow it.
@MainActor
class CourseStore: ObservableObject {
    static let shared = CourseStore()

    @Published private(set) var courses:     [Course]    = []
    @Published private(set) var assignments: [Assignment] = []

    private let dir = FileManager.default
        .urls(for: .documentDirectory, in: .userDomainMask)[0]

    /// Placeholder ids live BELOW LocalStore's, never among them.
    ///
    /// Both stores counted down from -1, and `remapTemporaryID` matches on the
    /// number alone — so a todo created offline as -1 and a course created
    /// offline as -1 were the same key, and syncing the todo renamed the
    /// course. A million apart keeps the two spaces disjoint without either
    /// store having to know about the other's counter.
    private static let tempBase = -1_000_000
    private var nextTemp = tempBase - 1

    private init() { load() }

    private func url(_ name: String) -> URL { dir.appendingPathComponent(name) }

    private func load() {
        let d = JSONDecoder()
        courses     = (try? d.decode([Course].self,     from: Data(contentsOf: url("mc_courses.json"))))     ?? []
        assignments = (try? d.decode([Assignment].self, from: Data(contentsOf: url("mc_assignments.json")))) ?? []
        // Start temp IDs below the lowest existing negative — and never above
        // the base, so ids minted before the two spaces were separated cannot
        // be handed out again.
        let negIds = courses.map { $0.id }.filter { $0 < 0 }
                   + assignments.map { $0.id }.filter { $0 < 0 }
        nextTemp = min((negIds.min().map { $0 - 1 }) ?? Self.tempBase - 1, Self.tempBase - 1)
    }

    func persist() {
        let e = JSONEncoder()
        try? e.encode(courses).write(to:     url("mc_courses.json"))
        try? e.encode(assignments).write(to: url("mc_assignments.json"))
    }

    // MARK: - Cache (called after successful API fetch)

    func cacheCourses(_ fresh: [Course]) {
        let local = courses.filter { $0.id < 0 }
        courses = local + fresh
        persist()
    }

    func cacheAllAssignments(_ fresh: [Assignment]) {
        let local = assignments.filter { $0.id < 0 }
        assignments = local + fresh
        persist()
    }

    // MARK: - Reads

    func assignments(for courseId: Int) -> [Assignment] {
        assignments.filter { $0.courseId == courseId }
    }

    // MARK: - Optimistic local writes (offline path)

    func insertCourse(number: String, name: String, color: String, partners: [String]) -> Course {
        let c = Course(id: nextTemp, number: number, name: name, color: color, partners: partners)
        nextTemp -= 1
        courses.append(c)
        persist()
        return c
    }

    func patchCourse(_ id: Int, number: String, name: String, color: String, partners: [String]) {
        guard let i = courses.firstIndex(where: { $0.id == id }) else { return }
        courses[i].number   = number
        courses[i].name     = name
        courses[i].color    = color
        courses[i].partners = partners
        persist()
    }

    func removeCourse(_ id: Int) {
        courses.removeAll { $0.id == id }
        assignments.removeAll { $0.courseId == id }
        persist()
    }

    func insertAssignment(courseId: Int, title: String, dueDate: String = "") -> Assignment {
        let a = Assignment(id: nextTemp, courseId: courseId, title: title,
                           dueDate: dueDate, completed: 0)
        nextTemp -= 1
        assignments.append(a)
        persist()
        return a
    }

    func patchAssignment(_ id: Int, title: String? = nil, dueDate: String? = nil,
                         completed: Int? = nil, calendarEventId: Int? = nil) {
        guard let i = assignments.firstIndex(where: { $0.id == id }) else { return }
        if let v = title           { assignments[i].title           = v }
        if let v = dueDate         { assignments[i].dueDate         = v }
        if let v = completed       { assignments[i].completed       = v }
        if let v = calendarEventId { assignments[i].calendarEventId = v }
        persist()
    }

    func clearCalendarEventId(_ id: Int) {
        guard let i = assignments.firstIndex(where: { $0.id == id }) else { return }
        assignments[i].calendarEventId = nil
        persist()
    }

    func toggleAssignment(_ id: Int) {
        guard let i = assignments.firstIndex(where: { $0.id == id }) else { return }
        assignments[i].completed = assignments[i].completed == 0 ? 1 : 0
        persist()
    }

    func removeAssignment(_ id: Int) {
        assignments.removeAll { $0.id == id }
        persist()
    }

    func removeCompletedAssignments() {
        assignments.removeAll { $0.isDone }
        persist()
    }

    // MARK: - Reconnect

    /// Point everything here that still names a placeholder at the real id.
    ///
    /// Called by `LocalStore.remapTemporaryID` when a queued create comes back
    /// with the id the Mac assigned. The `courseId` pass matters as much as the
    /// `id` one: an assignment added to a course that had not synced yet is
    /// filed under the course's placeholder, and would otherwise be orphaned
    /// the moment the course became real.
    func remapTemporaryID(_ tempID: Int, to realID: Int) {
        guard tempID < 0 else { return }
        var changed = false
        for (i, c) in courses.enumerated() where c.id == tempID {
            courses[i].id = realID
            changed = true
        }
        for (i, a) in assignments.enumerated() {
            if a.id == tempID       { assignments[i].id = realID;       changed = true }
            if a.courseId == tempID { assignments[i].courseId = realID; changed = true }
            // The calendar event an assignment was pinned to can be a
            // placeholder too — it lives in LocalStore's id space, which is why
            // the two spaces are kept apart (see `tempBase`).
            if a.calendarEventId == tempID { assignments[i].calendarEventId = realID; changed = true }
        }
        if changed { persist() }
    }
}
