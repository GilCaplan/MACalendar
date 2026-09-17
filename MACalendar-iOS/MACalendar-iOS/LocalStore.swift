import Foundation
import WidgetKit

// A write operation that couldn't reach the server and needs to be replayed.
struct PendingChange: Codable, Identifiable {
    let id: UUID
    let method: String   // "POST" | "PATCH" | "DELETE"
    let path: String     // e.g. "/events", "/todos/5"
    let bodyJSON: Data?  // JSON-serialised body dict
    let createdAt: Date

    init(method: String, path: String, body: [String: Any]?) {
        self.id        = UUID()
        self.method    = method
        self.path      = path
        self.bodyJSON  = body.flatMap { try? JSONSerialization.data(withJSONObject: $0) }
        self.createdAt = Date()
    }

    private init(id: UUID, method: String, path: String, bodyJSON: Data?, createdAt: Date) {
        self.id = id; self.method = method; self.path = path
        self.bodyJSON = bodyJSON; self.createdAt = createdAt
    }

    /// Same queued change, pointed at a different path (used when a temporary
    /// offline id is replaced by the real one the Mac assigned).
    func replacingPath(_ newPath: String) -> PendingChange {
        PendingChange(id: id, method: method, path: newPath,
                      bodyJSON: bodyJSON, createdAt: createdAt)
    }

    /// Same queued change with a rewritten body — for when the placeholder id
    /// is INSIDE the request rather than in its path (`course_id`,
    /// `calendar_event_id`).
    func replacingBody(_ newBody: [String: Any]) -> PendingChange {
        PendingChange(id: id, method: method, path: path,
                      bodyJSON: try? JSONSerialization.data(withJSONObject: newBody),
                      createdAt: createdAt)
    }
}

/// A voice command recorded while the Mac was unreachable.
///
/// The Mac does all the thinking, so a command spoken offline cannot be
/// understood on the phone — but the audio is kept and replayed the moment the
/// Mac is back, and the result is reported. Without this the recording was
/// simply thrown away and the user was told it failed.
struct PendingVoiceCommand: Codable, Identifiable {
    enum Status: String, Codable { case queued, running, done, failed }

    let id: UUID
    let recordedAt: Date
    var status: Status
    var result: String        // what the Mac replied, once it has run
    var audioFile: String     // file name inside the store's directory

    /// What the PHONE heard, captured from the on-device recogniser while you
    /// were speaking. Empty when recognition was off or produced nothing.
    ///
    /// This is a DRAFT and never authoritative: Whisper on the Mac, with your
    /// personal vocabulary, is better. It exists so a queued command is not a
    /// blank row — you can see what is waiting and correct it before it runs.
    var draft: String = ""

    /// What you changed the draft to. `nil` means untouched.
    ///
    /// The distinction decides HOW the command is sent. Untouched → the audio
    /// goes, exactly as before, and the Mac transcribes it properly. Edited →
    /// the TEXT goes, because your correction beats any re-transcription.
    var edited: String?

    /// When this row was last moved to `.running`.
    ///
    /// A row is marked running BEFORE the request goes out, and only leaves
    /// that state when the request comes back. If the app is backgrounded, the
    /// process is killed, or the upload never returns, nothing moves it — and
    /// the flush only picks up `.queued` and `.failed`, so the row is stranded
    /// where no retry can ever reach it. One was found stuck for five and a
    /// half hours (2026-09-10), showing "Running now…" the whole time.
    var startedAt: Date?

    /// You are editing this right now, so a flush must walk past it.
    ///
    /// Several things ask for a flush at once — reconnect, foregrounding, the
    /// 30 s poll, opening this screen — and any of them could fire mid-sentence
    /// and send the half-corrected version out from under you.
    var heldForEdit: Bool = false

    /// What actually gets sent, and whether it is text or audio.
    var outgoingText: String? {
        guard let edited, !edited.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return edited
    }

    /// The line the queue screen shows under the status.
    var displayText: String { edited ?? draft }

    init(audioFile: String, draft: String = "") {
        self.id = UUID()
        self.recordedAt = Date()
        self.status = .queued
        self.result = ""
        self.audioFile = audioFile
        self.draft = draft
    }
}

/// Persists events, todos, and queued writes to disk.
/// Temp IDs are negative integers; they're replaced by real server IDs after sync.
@MainActor
class LocalStore: ObservableObject {
    static let shared = LocalStore()

    @Published private(set) var pendingCount = 0
    /// Voice commands waiting for the Mac to come back, newest last.
    @Published private(set) var pendingVoice: [PendingVoiceCommand] = []

    private var events:   [CalendarEvent] = []
    private var todos:    [Todo]          = []
    private var tags:     [TodoTag]       = []
    private var holidays: [Holiday]       = []
    /// Readable so the queue can be SHOWN and edited (`PendingQueueView`), and
    /// published so cancelling one updates the list under your finger.
    /// `private(set)`: only this store decides what is queued.
    @Published private(set) var pending: [PendingChange] = []
    private var nextTemp = -1

    private let dir = FileManager.default
        .urls(for: .documentDirectory, in: .userDomainMask)[0]

    private init() { load() }

    // MARK: - Persistence

    private func url(_ name: String) -> URL { dir.appendingPathComponent(name) }

    private func load() {
        let d = JSONDecoder()
        events   = (try? d.decode([CalendarEvent].self, from: Data(contentsOf: url("mc_events.json"))))   ?? []
        todos    = (try? d.decode([Todo].self,          from: Data(contentsOf: url("mc_todos.json"))))    ?? []
        tags     = (try? d.decode([TodoTag].self,       from: Data(contentsOf: url("mc_tags.json"))))     ?? []
        holidays = (try? d.decode([Holiday].self,       from: Data(contentsOf: url("mc_holidays.json")))) ?? []
        timers   = (try? d.decode([WorkTimer].self,     from: Data(contentsOf: url("mc_timers.json"))))   ?? []
        counters = (try? d.decode([TallyCounter].self,  from: Data(contentsOf: url("mc_counters.json")))) ?? []
        pending  = (try? d.decode([PendingChange].self, from: Data(contentsOf: url("mc_pending.json"))))  ?? []
        pendingCount = pending.count
        // Prevent temp-ID collisions after a restart: start below the lowest existing negative ID.
        let negIDs = events.map { $0.id }.filter { $0 < 0 } + todos.map { $0.id }.filter { $0 < 0 }
        nextTemp = (negIDs.min().map { $0 - 1 }) ?? -1
        loadVoice()
    }

    private var cacheFlush: Task<Void, Never>?

    /// Save. Called from every mutation — twenty call sites — so what it costs
    /// is what a tap costs.
    ///
    /// It used to encode SEVEN files and write them all, synchronously, on the
    /// main actor, on every single change. Tapping ＋ on a counter rewrote the
    /// whole events cache and the holiday table with it. That is tens of
    /// kilobytes of JSON per tap on the thread that is supposed to be drawing,
    /// and it is the "laggy" you can feel rather than measure.
    ///
    /// Two changes, and the split between them is about what you can afford to
    /// lose:
    ///
    /// - **The pending queue is written NOW.** It is the one thing that is not
    ///   a cache: if the app is killed a moment after you add a task offline,
    ///   a debounced write would lose it, and nothing would ever replay it.
    ///   It is also the smallest file.
    /// - **The caches are debounced and written OFF the main actor.** They can
    ///   always be refetched from the Mac, so the worst a crash costs is one
    ///   round trip. A burst of taps now collapses into one write instead of
    ///   one per tap.
    func persist() {
        pendingCount = pending.count
        try? JSONEncoder().encode(pending).write(to: url("mc_pending.json"))
        scheduleCacheWrite()
    }

    /// Coalesce the caches into a single write, shortly, somewhere else.
    ///
    /// The snapshot is taken HERE, on the main actor, so the background write
    /// cannot see a half-applied change. Swift arrays are copy-on-write, so
    /// taking it costs a retain rather than a copy.
    private func scheduleCacheWrite() {
        let snapshot = CacheSnapshot(events: events, todos: todos, tags: tags,
                                     holidays: holidays, timers: timers,
                                     counters: counters, dir: dir)
        cacheFlush?.cancel()
        cacheFlush = Task.detached(priority: .utility) {
            // Long enough to swallow a burst of taps, short enough that
            // backgrounding the app a moment later still catches it.
            try? await Task.sleep(nanoseconds: 150_000_000)
            if Task.isCancelled { return }
            snapshot.write()
        }
    }

    /// Everything a cache write needs, detached from the store.
    ///
    /// A plain value carried into the background task, rather than the task
    /// reaching back into `LocalStore` — which is `@MainActor`, so reaching
    /// back would hop to the main thread and undo the point of moving it.
    private struct CacheSnapshot {
        let events: [CalendarEvent]
        let todos: [Todo]
        let tags: [TodoTag]
        let holidays: [Holiday]
        let timers: [WorkTimer]
        let counters: [TallyCounter]
        let dir: URL

        func write() {
            let e = JSONEncoder()
            try? e.encode(events).write(to:   dir.appendingPathComponent("mc_events.json"))
            try? e.encode(todos).write(to:    dir.appendingPathComponent("mc_todos.json"))
            try? e.encode(tags).write(to:     dir.appendingPathComponent("mc_tags.json"))
            try? e.encode(holidays).write(to: dir.appendingPathComponent("mc_holidays.json"))
            try? e.encode(timers).write(to:   dir.appendingPathComponent("mc_timers.json"))
            try? e.encode(counters).write(to: dir.appendingPathComponent("mc_counters.json"))
        }
    }

    /// Write the caches now, without waiting for the debounce — for the moment
    /// the app goes to the background, where "shortly" may never arrive.
    func flushCachesNow() {
        cacheFlush?.cancel()
        CacheSnapshot(events: events, todos: todos, tags: tags, holidays: holidays,
                      timers: timers, counters: counters, dir: dir).write()
    }

    // MARK: - Timers and counters, offline

    /// The Timer tab was the ONLY surface with no cache at all.
    ///
    /// `APIClient.timers()`/`counters()` were the only reads in the app that
    /// did not fall back to this store, so away from the Mac the tab had
    /// nothing to draw — and tapping ＋ queued the press correctly while the
    /// screen showed no count to increment, which reads as "the button is
    /// broken". Queueing the write was never enough on its own: a surface with
    /// no local state has nothing to apply it to.
    @Published var timers: [WorkTimer] = []
    @Published var counters: [TallyCounter] = []

    /// Merge rather than replace.
    ///
    /// The app normally fetches `archived=false`, so a wholesale replace meant
    /// the cache only ever held UNARCHIVED rows — and "Show archived" offline
    /// filtered a list that had never contained one, so the switch appeared to
    /// do nothing. Merging by id keeps an archived row once it has been seen,
    /// and the fresh copy still wins for anything in this answer.
    func cacheTimers(_ fresh: [WorkTimer]) {
        var byID = Dictionary(uniqueKeysWithValues: timers.map { ($0.id, $0) })
        for t in fresh { byID[t.id] = t }
        timers = byID.values.sorted { $0.id < $1.id }
        persist()
    }

    func cacheCounters(_ fresh: [TallyCounter]) {
        var byID = Dictionary(uniqueKeysWithValues: counters.map { ($0.id, $0) })
        for c in fresh { byID[c.id] = c }
        counters = byID.values.sorted { $0.id < $1.id }
        persist()
    }

    /// Start a timer in the cache, so the clock runs from the moment of the tap.
    ///
    /// The same gap `bumpCounter` closed, on the surface where it shows most:
    /// starting a timer offline queued the write correctly, but the cached
    /// timer still said `running: nil`, so the row sat at 00:00 next to a
    /// timer the user had just started. `TimerRow.liveSeconds` reads
    /// `running.startedAt`; with no session there is nothing for the
    /// once-a-second tick to count from.
    ///
    /// `id: 0` marks it as ours: the Mac assigns the real session id when the
    /// queued start replays, and its answer replaces this wholesale.
    func startTimerLocally(_ id: Int, at when: Date = Date()) {
        guard let i = timers.firstIndex(where: { $0.id == id }), timers[i].running == nil else { return }
        let stamp = ISO8601DateFormatter().string(from: when)
        timers[i].running = TimerSession(
            id: 0, title: timers[i].title, startTime: stamp, endTime: nil,
            notes: "", seconds: 0, running: true,
            startEpoch: when.timeIntervalSince1970, endEpoch: nil)
        persist()
    }

    /// Stop it, and fold the elapsed time into the totals the row displays.
    func stopTimerLocally(_ id: Int, at when: Date = Date()) {
        guard let i = timers.firstIndex(where: { $0.id == id }),
              let session = timers[i].running else { return }
        let started = session.startEpoch
            ?? ISO8601DateFormatter().date(from: session.startTime)?.timeIntervalSince1970
            ?? when.timeIntervalSince1970
        let elapsed = max(0, when.timeIntervalSince1970 - started)
        timers[i].running = nil
        timers[i].totalSeconds += elapsed
        timers[i].todaySeconds += elapsed
        timers[i].sessionCount += 1
        timers[i].earnings = ((timers[i].totalSeconds / 3600) * timers[i].hourlyRate * 100).rounded() / 100
        persist()
    }

    func allTimers(includeArchived: Bool = false) -> [WorkTimer] {
        includeArchived ? timers : timers.filter { $0.archived == 0 }
    }

    func allCounters(includeArchived: Bool = false) -> [TallyCounter] {
        includeArchived ? counters : counters.filter { $0.archived == 0 }
    }

    /// Apply a press to the cached counter, so ＋ moves the number immediately
    /// whether or not the Mac is there.
    ///
    /// This is a PREVIEW, not a second source of truth: the queued press
    /// carries its own `pressed_at`, and when it replays the Mac recomputes
    /// every total from the presses it holds. Its answer is the one that
    /// lands. `payout` is derived here the same way the Mac derives it
    /// (`count × price_per_unit`) so the two agree while offline.
    func bumpCounter(_ id: Int, delta: Int) {
        guard let i = counters.firstIndex(where: { $0.id == id }) else { return }
        counters[i].count += delta
        counters[i].totalCount += delta
        counters[i].todayCount += delta
        counters[i].payout = (Double(counters[i].count) * counters[i].pricePerUnit * 100).rounded() / 100
        persist()
    }

    // MARK: - Holidays (the Hebrew calendar, offline)

    /// The Mac computes the holiday list (`pyluach`, one implementation, so
    /// both devices agree) and this is where the answers are kept.
    ///
    /// They were the one part of the calendar with no cache at all: the fetch
    /// returned `[]` when the Mac was unreachable, so going offline emptied the
    /// Hebrew calendar out of every month view — while the Hebrew *dates* beside
    /// them, which iOS computes locally, stayed. Holidays move slowly and a
    /// bootstrap covers three months at a time, so keeping every one we have
    /// ever been told costs a few kilobytes and survives a long trip.
    func cacheHolidays(_ fresh: [Holiday], from start: String, to end: String) {
        // Replace the window that was just refetched — a holiday the Mac has
        // since dropped (a changed observance setting) must not linger — and
        // keep everything outside it.
        let outside = holidays.filter { $0.gregorianEnd < start || $0.gregorianErevStart > end }
        var merged = outside + fresh
        var seen = Set<String>()
        merged = merged.filter { seen.insert($0.id).inserted }
        holidays = merged.sorted { $0.gregorianErevStart < $1.gregorianErevStart }
        persist()
    }

    /// Cached holidays overlapping [start, end] (ISO days), the same span the
    /// server would have answered for.
    func holidaysBetween(_ start: String, _ end: String) -> [Holiday] {
        holidays.filter { $0.gregorianEnd >= start && $0.gregorianErevStart <= end }
    }

    // MARK: - Events

    func cacheEvents(_ fresh: [CalendarEvent]) {
        // Keep items created offline that the Mac hasn't got yet — but drop any
        // whose twin is already in the fresh data, or they show up twice for
        // ever: once as the local placeholder, once as the Mac's copy.
        let arrived = Set(fresh.map { "\($0.title)|\($0.date)|\($0.startTime)" })
        let local = events.filter {
            $0.id < 0 && !arrived.contains("\($0.title)|\($0.date)|\($0.startTime)")
        }
        events = local + fresh
        persist()
        // Fresh payloads carry fresh notify_at verdicts — re-mirror them into
        // the pending local notifications. Debounced and idempotent, so the
        // frequent refresh paths (month loads, the 2 s token poll) are fine.
        ReminderScheduler.shared.reconcile()
    }

    /// Every cached event — what ReminderScheduler mirrors into scheduled
    /// local notifications.
    func allEvents() -> [CalendarEvent] { events }

    func eventsForDate(_ str: String) -> [CalendarEvent] {
        events.filter { $0.date == str }
    }

    func eventsForMonth(_ year: Int, _ month: Int) -> [CalendarEvent] {
        let pfx = String(format: "%04d-%02d", year, month)
        return events.filter { $0.date.hasPrefix(pfx) }
    }

    func eventsForWeek(startStr: String) -> [CalendarEvent] {
        let fmt = DateFormatter.isoDay
        guard let start = fmt.date(from: startStr) else { return [] }
        let end = Calendar.current.date(byAdding: .day, value: 7, to: start)!
        return events.filter {
            guard let d = fmt.date(from: $0.date) else { return false }
            return d >= start && d < end
        }
    }

    func insertEvent(_ fields: [String: Any]) -> CalendarEvent {
        let e = CalendarEvent(
            id: nextTemp,
            title:         fields["title"]          as? String ?? "New Event",
            date:          fields["date"]           as? String ?? DateFormatter.isoDay.string(from: Date()),
            startTime:     fields["start_time"]     as? String ?? "",
            endTime:       fields["end_time"]       as? String ?? "",
            attendees:     fields["attendees"]      as? String ?? "",
            location:      fields["location"]       as? String ?? "",
            description:   fields["description"]    as? String ?? "",
            color:         fields["color"]          as? String ?? "",
            recurrence:    fields["recurrence"]     as? String ?? "",
            recurrenceEnd: fields["recurrence_end"] as? String ?? ""
        )
        nextTemp -= 1
        events.append(e)
        persist()
        ReminderScheduler.shared.reconcile()
        return e
    }

    func event(_ id: Int) -> CalendarEvent? { events.first { $0.id == id } }
    func todo(_ id: Int) -> Todo? { todos.first { $0.id == id } }

    func patchEvent(_ id: Int, fields: [String: Any]) {
        guard let i = events.firstIndex(where: { $0.id == id }) else { return }
        if let v = fields["title"]      as? String { events[i].title     = v }
        if let v = fields["date"]       as? String { events[i].date      = v }
        if let v = fields["start_time"] as? String { events[i].startTime = v }
        if let v = fields["end_time"]   as? String { events[i].endTime   = v }
        if let v = fields["location"]   as? String { events[i].location  = v }
        if let v = fields["attendees"]  as? String { events[i].attendees = v }
        // Present-but-null (NSNull) clears the override back to "inherit" —
        // `as? Int` yields nil for NSNull, which is exactly the clear.
        if fields.keys.contains("reminder_minutes") {
            events[i].reminderMinutes = fields["reminder_minutes"] as? Int
        }
        persist()
        ReminderScheduler.shared.reconcile()
    }

    func removeEvent(_ id: Int) {
        events.removeAll { $0.id == id }
        persist()
        ReminderScheduler.shared.reconcile()
    }

    // MARK: - Home-screen widget snapshot

    /// Mirror the near future into the shared App Group container, where the
    /// widget extension can read it.
    ///
    /// The widget runs in its own process and cannot see this store's
    /// Documents directory; an App Group container is the only sanctioned
    /// channel between the two. Everything here is deliberately defensive —
    /// when the group is not available (`snapshotURL` nil, because the
    /// entitlement has not reached a provisioning profile yet, or the build
    /// was never signed with it) this is a silent no-op and the widget draws
    /// its "no data yet" placeholder instead.
    ///
    /// Called from `LiveActivityManager.sync()`, so the snapshot is refreshed
    /// on exactly the moments the lock-screen card is: foregrounding, the
    /// `/changes` poll, the 30 s tick, and every write to the event cache.
    func refreshWidgetSnapshot(now: Date = Date()) {
        guard let url = WidgetBridge.snapshotURL else { return }

        let accent = LiveActivityManager.accentHex
        let snapshot = WidgetSnapshot(
            generated: now,
            accentHex: accent,
            items: Self.widgetItems(now: now, events: events, accentHex: accent))

        // Write — and reload — only when the content actually moved. `sync()`
        // runs on every 30 s tick, and WidgetKit budgets timeline reloads:
        // spending them redrawing an unchanged widget is how a widget ends up
        // refusing to update at the moment it matters. Same discipline as
        // `LiveActivityManager.sameCard`.
        if let data = try? Data(contentsOf: url),
           let old = try? WidgetBridge.decoder().decode(WidgetSnapshot.self, from: data),
           old.items == snapshot.items, old.accentHex == snapshot.accentHex {
            return
        }
        guard let data = try? WidgetBridge.encoder().encode(snapshot),
              (try? data.write(to: url, options: .atomic)) != nil
        else { return }

        WidgetCenter.shared.reloadTimelines(ofKind: WidgetBridge.homeWidgetKind)
    }

    /// Today's and tomorrow's still-relevant timed events, soonest first.
    ///
    /// Pure and static so what the widget will show can be reasoned about (and
    /// tested) without a container or a device — the same treatment
    /// `LiveActivityManager.currentCard` gets, and the same parsing rules:
    /// all-day rows have nothing to point at, a missing end time means an hour,
    /// and "23:00 – 01:00" belongs to two days.
    static func widgetItems(now: Date, events: [CalendarEvent],
                            accentHex: String) -> [WidgetSnapshot.Item] {
        let cal = Calendar.current
        guard let horizon = cal.date(byAdding: .day, value: 2,
                                     to: cal.startOfDay(for: now)) else { return [] }

        let items: [WidgetSnapshot.Item] = events.compactMap { e in
            guard !e.startTime.isEmpty,
                  let start = ReminderScheduler.parseLocal("\(e.date)T\(e.startTime)")
            else { return nil }
            var end = (e.endTime.isEmpty ? nil : ReminderScheduler.parseLocal("\(e.date)T\(e.endTime)"))
                ?? start.addingTimeInterval(LiveActivityManager.assumedDuration)
            if end <= start { end = end.addingTimeInterval(86_400) }
            // Already over, or further out than tomorrow: not this widget's job.
            guard end > now, start < horizon else { return nil }
            return WidgetSnapshot.Item(
                id: e.id,
                title: e.title.isEmpty ? "Untitled event" : e.title,
                start: start,
                end: end,
                timeLabel: e.displayTime,
                location: e.location,
                colorHex: e.color.isEmpty ? accentHex : e.color)
        }
        .sorted { $0.start < $1.start }

        return Array(items.prefix(WidgetSnapshot.maxItems))
    }

    // MARK: - Search (offline cache)

    /// Case-insensitive substring search over every cached event — the same
    /// cache the calendar reads when the Mac is unreachable, so search works
    /// entirely offline. Upcoming events first (soonest on top), then past
    /// ones (most recent first): a hit you can still make it to beats one
    /// that's over.
    func searchEvents(_ query: String) -> [CalendarEvent] {
        let q = query.lowercased()
        guard !q.isEmpty else { return [] }
        let hits = events.filter {
            $0.title.lowercased().contains(q)
                || $0.location.lowercased().contains(q)
                || $0.description.lowercased().contains(q)
        }
        let today = DateFormatter.isoDay.string(from: Date())
        let upcoming = hits.filter { $0.date >= today }
            .sorted { ($0.date, $0.startTime) < ($1.date, $1.startTime) }
        let past = hits.filter { $0.date < today }
            .sorted { ($0.date, $0.startTime) > ($1.date, $1.startTime) }
        return upcoming + past
    }

    /// Case-insensitive substring search over cached tasks. The iOS Todo
    /// model carries no notes field, so the title (plus tags) is what there
    /// is to match. Open tasks come before completed ones.
    func searchTodos(_ query: String) -> [Todo] {
        let q = query.lowercased()
        guard !q.isEmpty else { return [] }
        return todos.filter { todo in
            todo.title.lowercased().contains(q)
                || todo.tags.contains { $0.lowercased().contains(q) }
        }
        .sorted { a, b in
            if a.isDone != b.isDone { return !a.isDone }
            return a.title.lowercased() < b.title.lowercased()
        }
    }

    // MARK: - Todos

    func cacheTodos(_ fresh: [Todo]) {
        let arrived = Set(fresh.map { "\($0.title)|\($0.list)" })
        let local = todos.filter { $0.id < 0 && !arrived.contains("\($0.title)|\($0.list)") }
        todos = local + fresh
        persist()
    }

    func allTodos(list: String?, includeCompleted: Bool) -> [Todo] {
        todos.filter {
            (list == nil || $0.list == list) && (includeCompleted || $0.completed == 0)
        }
    }

    func insertTodo(title: String, list: String, tags: [String] = []) -> Todo {
        let t = Todo(id: nextTemp, title: title, list: list,
                     completed: 0, priority: "none", dueDate: "", tags: tags)
        nextTemp -= 1
        todos.append(t)
        persist()
        return t
    }

    @discardableResult
    func toggleTodo(_ id: Int) -> Bool {
        guard let i = todos.firstIndex(where: { $0.id == id }) else { return false }
        todos[i].completed = todos[i].completed == 0 ? 1 : 0
        persist()
        return todos[i].completed != 0
    }

    func patchTodo(_ id: Int, fields: [String: Any]) {
        guard let i = todos.firstIndex(where: { $0.id == id }) else { return }
        if let v = fields["title"]     as? String { todos[i].title    = v }
        if let v = fields["list_name"] as? String { todos[i].list     = v }
        if let v = fields["priority"]  as? String { todos[i].priority = v }
        if let v = fields["due_date"]  as? String { todos[i].dueDate  = v }
        if let v = fields["tags"]      as? [String] { todos[i].tags   = v }
        if let v = fields["quantity"]  as? Int    { todos[i].quantity = max(1, v) }
        persist()
    }

    func removeTodo(_ id: Int) { todos.removeAll { $0.id == id }; persist() }

    // MARK: - Tags (palette cache)

    func cacheTags(_ fresh: [TodoTag]) {
        tags = fresh
        persist()
    }

    func allTags() -> [TodoTag] {
        if tags.isEmpty {
            // Never-synced device: show the server's built-in set so tag mode is usable offline.
            return ["Coursework", "Groceries", "Errands", "Work", "Personal"].map { TodoTag(name: $0, builtin: 1) }
        }
        return tags
    }

    func insertTag(_ tag: TodoTag) {
        var current = allTags()
        guard !current.contains(where: { $0.name.caseInsensitiveCompare(tag.name) == .orderedSame }) else { return }
        current.append(tag)
        tags = current
        persist()
    }

    func removeTag(_ name: String) {
        tags = allTags().filter { $0.name.caseInsensitiveCompare(name) != .orderedSame }
        for i in todos.indices {
            todos[i].tags.removeAll { $0.caseInsensitiveCompare(name) == .orderedSame }
        }
        persist()
    }

    // MARK: - Pending queue

    func enqueue(method: String, path: String, body: [String: Any]? = nil) {
        pending.append(PendingChange(method: method, path: path, body: body))
        persist()
    }

    // MARK: - Voice commands queued while offline

    private var voiceURL: URL { url("mc_pending_voice.json") }

    private func loadVoice() {
        guard let data = try? Data(contentsOf: voiceURL),
              let rows = try? JSONDecoder().decode([PendingVoiceCommand].self, from: data)
        else { return }
        pendingVoice = rows
        reclaimStaleRunning()
    }

    /// A command marked `.running` on disk is an ORPHAN — nothing is running it.
    ///
    /// `syncPendingVoice` sets `.running`, awaits the upload, then writes
    /// `.done` / `.queued` / `.failed`. If the process does not survive that
    /// await — and iOS suspends and kills backgrounded apps freely, well inside
    /// the 120 s the voice request allows — the status persists as `.running`
    /// and nothing ever moves it again: the replay loop only picks up `.queued`
    /// and `.failed`, and `clearFinishedVoice` only drops `.done` and
    /// `.failed`. The row is stranded, shown as running forever, and the
    /// recording it is holding is never replayed.
    ///
    /// So at load — and on any flush that finds one while no flush is in
    /// progress — a `.running` row goes back to `.queued`. Replaying is the
    /// safe direction: the alternative is a command the speaker gave and the
    /// Mac never saw.
    func reclaimStaleRunning() {
        var changed = false
        for i in pendingVoice.indices where pendingVoice[i].status == .running {
            pendingVoice[i].status = .queued
            changed = true
        }
        if changed { persistVoice() }
    }

    private func persistVoice() {
        if let data = try? JSONEncoder().encode(pendingVoice) {
            try? data.write(to: voiceURL)
        }
    }

    /// Park a recording until the Mac is reachable. Returns the queued command.
    ///
    /// `draft` is what the on-device recogniser heard while you were speaking —
    /// the recorder already publishes it as `liveText` for the thinking sheet,
    /// so it costs nothing to keep. Without it a queued command is an anonymous
    /// row you cannot check or correct until it has already run.
    @discardableResult
    func enqueueVoice(_ audio: Data, draft: String = "") -> PendingVoiceCommand {
        let name = "voice-\(UUID().uuidString).wav"
        try? audio.write(to: url(name))
        let cmd = PendingVoiceCommand(audioFile: name, draft: draft)
        pendingVoice.append(cmd)
        persistVoice()
        return cmd
    }

    /// Put back any row that has been "running" for longer than a command can
    /// plausibly take.
    ///
    /// Called before every flush and on launch. `.running` is a promise that
    /// something is in flight; once nothing is, the promise is stale and the
    /// row should be retryable again. Fifteen minutes is far beyond the slowest
    /// real command (the deep path's worst measured case is ~30 s) and short
    /// enough that a user who reopens the app finds it recovered.
    func reviveStalledVoice(after seconds: TimeInterval = 900) -> Int {
        let cutoff = Date().addingTimeInterval(-seconds)
        var revived = 0
        for i in pendingVoice.indices where pendingVoice[i].status == .running {
            // No `startedAt` means the row predates this field — treat it as
            // stale rather than leaving it stuck for ever.
            if (pendingVoice[i].startedAt ?? .distantPast) < cutoff {
                pendingVoice[i].status = .queued
                pendingVoice[i].startedAt = nil
                revived += 1
            }
        }
        if revived > 0 { persistVoice() }
        return revived
    }

    /// Mark a queued command as being edited (or no longer being edited).
    /// While `held` is true no flush will send it.
    func holdVoiceForEdit(_ id: UUID, _ held: Bool) {
        guard let i = pendingVoice.firstIndex(where: { $0.id == id }) else { return }
        pendingVoice[i].heldForEdit = held
        persistVoice()
    }

    /// Store a correction. Sending switches from audio to text at the same time,
    /// and the hold is released so the next flush picks it up.
    func editVoice(_ id: UUID, text: String) {
        guard let i = pendingVoice.firstIndex(where: { $0.id == id }) else { return }
        pendingVoice[i].edited = text
        pendingVoice[i].heldForEdit = false
        persistVoice()
    }

    func voiceAudio(_ cmd: PendingVoiceCommand) -> Data? {
        try? Data(contentsOf: url(cmd.audioFile))
    }

    func updateVoice(_ id: UUID, status: PendingVoiceCommand.Status, result: String = "") {
        guard let i = pendingVoice.firstIndex(where: { $0.id == id }) else { return }
        pendingVoice[i].status = status
        // Stamped on the way IN to `.running` so `reviveStalledVoice` can tell
        // a command that is genuinely in flight from one that was abandoned.
        pendingVoice[i].startedAt = (status == .running) ? Date() : nil
        if !result.isEmpty { pendingVoice[i].result = result }
        persistVoice()
    }

    func removeVoice(_ id: UUID) {
        if let cmd = pendingVoice.first(where: { $0.id == id }) {
            try? FileManager.default.removeItem(at: url(cmd.audioFile))
        }
        pendingVoice.removeAll { $0.id == id }
        persistVoice()
    }

    /// Drop finished entries once they have been seen.
    func clearFinishedVoice() {
        for cmd in pendingVoice where cmd.status == .done || cmd.status == .failed {
            try? FileManager.default.removeItem(at: url(cmd.audioFile))
        }
        pendingVoice.removeAll { $0.status == .done || $0.status == .failed }
        persistVoice()
    }

    func allPending() -> [PendingChange] { pending }

    func removePending(_ id: UUID) {
        pending.removeAll { $0.id == id }
        persist()
    }

    /// Drop a queued change the user has decided against — and anything that
    /// only made sense because of it.
    ///
    /// The queue is a SEQUENCE, not a set. A create made offline gets a
    /// negative placeholder id, and later edits and deletes are queued against
    /// that id. Removing just the create would leave those pointed at a row
    /// the Mac will never have: on reconnect they 404, get dropped, and the
    /// user is none the wiser — except that the thing they DID want to keep
    /// quietly did not happen.
    ///
    /// So cancelling a create cancels its dependants too, and the caller is
    /// told how many went with it.
    @discardableResult
    func cancelPending(_ id: UUID) -> Int {
        guard let change = pending.first(where: { $0.id == id }) else { return 0 }
        var doomed: Set<UUID> = [id]

        if change.method == "POST",
           let data = change.bodyJSON,
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let temp = obj["_temp_id"] as? Int, temp < 0 {
            for other in pending where other.id != id {
                // Anything addressed to the placeholder, or carrying it as a
                // parent (an assignment queued under an unsynced course).
                if other.path.contains("/\(temp)") {
                    doomed.insert(other.id)
                } else if let d = other.bodyJSON,
                          let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
                          o.contains(where: { $0.key.hasSuffix("_id") && ($0.value as? Int) == temp }) {
                    doomed.insert(other.id)
                }
            }
        }
        pending.removeAll { doomed.contains($0.id) }
        persist()
        return doomed.count
    }

    /// Everything queued, thrown away. Used by "Clear all" behind a confirm.
    func clearPending() {
        pending.removeAll()
        persist()
    }

    /// One queued change, in the words of what the user did.
    ///
    /// A queue you cannot read is one you have to trust blindly, and
    /// "POST /todos" is not something anyone should have to decode to decide
    /// whether they still want it.
    nonisolated static func describe(_ c: PendingChange) -> String {
        let body = c.bodyJSON.flatMap {
            try? JSONSerialization.jsonObject(with: $0) as? [String: Any]
        } ?? [:]
        let title = (body["title"] as? String) ?? (body["name"] as? String) ?? ""
        let named = title.isEmpty ? "" : " “\(title)”"
        let noun: String
        switch true {
        case c.path.hasPrefix("/todos"):        noun = "task"
        case c.path.hasPrefix("/events"):       noun = "event"
        case c.path.hasPrefix("/courses"):      noun = "course"
        case c.path.hasPrefix("/assignments"):  noun = "assignment"
        case c.path.hasPrefix("/timers"):       noun = "timer"
        case c.path.hasPrefix("/counters"):     noun = "counter"
        case c.path.hasPrefix("/tags"):         noun = "tag"
        case c.path.hasPrefix("/categories"):   noun = "category"
        case c.path.hasPrefix("/vocab"):        noun = "vocabulary entry"
        case c.path.hasPrefix("/labels"):       noun = "label"
        default:                                noun = "change"
        }
        if c.path.contains("/toggle") { return "Tick off a \(noun)" }
        if c.path.contains("/press")  { return "Count on a \(noun)" }
        if c.path.contains("/start")  { return "Start a \(noun)" }
        if c.path.contains("/stop")   { return "Stop a \(noun)" }
        switch c.method {
        case "POST":   return "Add \(noun)\(named)"
        case "PATCH":  return "Edit \(noun)\(named)"
        case "DELETE": return "Delete \(noun)\(named)"
        default:       return "\(c.method) \(c.path)"
        }
    }

    /// Rewrite queued requests that still refer to an item by the temporary
    /// negative id it was given while offline.
    ///
    /// Anything created offline gets a placeholder id (`nextTemp`, counting
    /// down from -1). If you then tick it off or edit it, that action was
    /// queued against the placeholder — e.g. `PATCH /todos/-1/toggle`. Once the
    /// create is replayed the Mac assigns a real id, and the queued action
    /// 404s forever: the change is silently lost AND (since the sync loop stops
    /// at the first failure) it blocks everything queued behind it.
    func remapTemporaryID(_ tempID: Int, to realID: Int) {
        guard tempID < 0 else { return }
        for (i, change) in pending.enumerated() {
            guard change.path.contains("/\(tempID)") else { continue }
            pending[i] = change.replacingPath(
                change.path.replacingOccurrences(of: "/\(tempID)", with: "/\(realID)"))
        }
        // A placeholder also travels INSIDE a queued body: an assignment added
        // to a course that has not synced yet carries `course_id: -1000001`,
        // and an assignment pointed at an event created offline carries
        // `calendar_event_id: -3`. Rewriting only the path left those attached
        // to an id the Mac never issued — the assignment arrived under no
        // course at all. Only `*_id` keys are considered, so a number that
        // happens to equal a placeholder (a quantity, a lead time) is left
        // alone; `_temp_id` is skipped because it is the create's own name for
        // itself, and it is about to be dropped with the row anyway.
        for (i, change) in pending.enumerated() {
            guard let data = change.bodyJSON,
                  var obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { continue }
            var rewritten = false
            for (key, value) in obj where key.hasSuffix("_id") && key != "_temp_id" {
                if let n = value as? Int, n == tempID { obj[key] = realID; rewritten = true }
            }
            if rewritten { pending[i] = change.replacingBody(obj) }
        }
        for (i, t) in todos.enumerated() where t.id == tempID { todos[i].id = realID }
        for (i, e) in events.enumerated() where e.id == tempID { events[i].id = realID }
        // Coursework keeps its own cache and mints its own placeholders, and
        // nothing else knows about `mc_courses.json` — so it has to be told.
        // Without this a course created offline kept its placeholder for ever:
        // the next fetch brought the real row down beside it, and any edit made
        // in between replayed against an id the Mac never issued.
        CourseStore.shared.remapTemporaryID(tempID, to: realID)
        persist()
    }
}

extension DateFormatter {
    static let isoDay: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()
}
