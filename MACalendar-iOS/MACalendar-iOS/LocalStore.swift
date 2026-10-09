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

    /// The body as a dictionary (nil when there is none).
    var body: [String: Any]? {
        bodyJSON.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
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
    /// `waiting`: the Mac took it into ITS OWN queue (its model was busy) and
    /// this row is kept only to hold the offline reading's provisional rows
    /// until the Mac has run it — never sent again (assistant/offline).
    enum Status: String, Codable { case queued, running, done, failed, waiting }

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

    /// When it last came back, done or failed — for the detail screen.
    var finishedAt: Date?

    /// The Mac's whole answer, trace and all, kept so tapping a finished row
    /// shows the run step by step (Gil, 2026-09-28: "make this clickable to see
    /// details of run").
    ///
    /// Stored as its own encoded blob, NOT as a `VoiceResponse` field: this row
    /// lives in the queue file, and `VoiceResponse` nests a dozen types with
    /// hand-written coding. One that stopped round-tripping would make the
    /// WHOLE file fail to decode on the next launch — every queued command
    /// silently gone. As a blob, a bad one costs only its own detail screen.
    var responseData: Data?

    var response: VoiceResponse? {
        responseData.flatMap { try? JSONDecoder().decode(VoiceResponse.self, from: $0) }
    }

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

    // -- the offline reader (assistant/offline/PROTOCOL.md) -------------
    // Optionals, so a queue file written before these existed still decodes.

    /// What the on-device model read, sent with the command as
    /// `offline_reading` so the Mac can compare it with its own reading.
    var offlineReadingData: Data?
    /// The placeholder rows booked from that reading. Removed when the Mac
    /// has answered — its rows replace them, whatever it concluded.
    var provisionalEventIDs: [Int]?
    var provisionalTodoIDs: [Int]?
    /// Set when the Mac queued the command itself (`pending`); the phone asks
    /// `/offline/pending/<id>` until it has run.
    var macPendingID: Int?
    /// The Mac's verdict on the offline reading, for the detail screen.
    var offlineVerdict: String?

    var offlineReading: OfflineReading? {
        offlineReadingData.flatMap { try? JSONDecoder().decode(OfflineReading.self, from: $0) }
    }
    var hasProvisional: Bool {
        !(provisionalEventIDs ?? []).isEmpty || !(provisionalTodoIDs ?? []).isEmpty
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

/// The Shabbat / yom tov windows on disk, with the place they belong to.
struct HolyWindowsCache: Codable {
    var placeKey: String = ""
    var windows: [HolyWindow] = []
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
    /// When Shabbat / yom tov begins and ends — the Mac's answers, kept so the
    /// yellow lines stay on the grid with the Mac away. `placeKey` is where
    /// they were computed for (see `cacheHolyWindows`).
    private var holy = HolyWindowsCache()
    /// The Mac's finished day panels, one per day, kept so the phone can
    /// SCHEDULE tomorrow's notification tonight — and still fire it after a
    /// week off the tailnet. See `ReminderScheduler`.
    private var digests:  [DayDigest]      = []
    /// Readable so the queue can be SHOWN and edited (`PendingQueueView`), and
    /// published so cancelling one updates the list under your finger.
    /// `private(set)`: only this store decides what is queued.
    @Published private(set) var pending: [PendingChange] = []
    private var nextTemp = -1

    /// Where this person's offline copy lives: `Documents/users/<id>/` once
    /// someone has signed in (DEVQA Q65 — each person's calendar is their own,
    /// on a shared phone too), the top of `Documents/` before users existed.
    private var dir: URL = LocalStore.folder(for: LocalStore.storedUserID())

    private init() { load() }

    private static var documents: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    private static func folder(for userID: String?) -> URL {
        guard let userID, !userID.isEmpty else { return documents }
        let d = documents.appendingPathComponent("users/\(userID)", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    private static func storedUserID() -> String? {
        guard let data = UserDefaults.standard.data(forKey: "macalendar.session_user"),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return obj["id"] as? String
    }

    /// Someone else signed in (or out): save what is on screen to its owner's
    /// folder, then load theirs. The ADMIN, signing in on a phone that already
    /// has a cache from before users, takes it over — it was his, as the Mac's
    /// migration decided for its own data; anyone else starts clean and never
    /// sees it. (First version: "the first to sign in" — found in the
    /// simulator handing Dana a cache fetched as the admin.)
    func switchUser(_ userID: String?, mayClaimLegacy: Bool = false) {
        let target = Self.folder(for: userID)
        guard target.standardizedFileURL != dir.standardizedFileURL else { return }
        flushCachesNow()
        persistVoice()
        try? JSONEncoder().encode(pending).write(to: url("mc_pending.json"))
        if let userID, !userID.isEmpty, mayClaimLegacy {
            let owner = UserDefaults.standard.string(forKey: "macalendar.cache_owner")
            if owner == nil || owner == userID {
                Self.claimLegacyCache(into: target)
                UserDefaults.standard.set(userID, forKey: "macalendar.cache_owner")
            }
        }
        dir = target
        load()
    }

    /// Move the pre-users cache files from the top of Documents into `target`
    /// — never over a file already there.
    private static func claimLegacyCache(into target: URL) {
        let fm = FileManager.default
        guard let names = try? fm.contentsOfDirectory(atPath: documents.path) else { return }
        for name in names where name.hasPrefix("mc_") || (name.hasPrefix("voice-") && name.hasSuffix(".wav")) {
            let dst = target.appendingPathComponent(name)
            if !fm.fileExists(atPath: dst.path) {
                try? fm.moveItem(at: documents.appendingPathComponent(name), to: dst)
            }
        }
    }

    // MARK: - Persistence

    private func url(_ name: String) -> URL { dir.appendingPathComponent(name) }

    private func load() {
        let d = JSONDecoder()
        events   = (try? d.decode([CalendarEvent].self, from: Data(contentsOf: url("mc_events.json"))))   ?? []
        todos    = (try? d.decode([Todo].self,          from: Data(contentsOf: url("mc_todos.json"))))    ?? []
        tags     = (try? d.decode([TodoTag].self,       from: Data(contentsOf: url("mc_tags.json"))))     ?? []
        holidays = (try? d.decode([Holiday].self,       from: Data(contentsOf: url("mc_holidays.json")))) ?? []
        holy     = (try? d.decode(HolyWindowsCache.self, from: Data(contentsOf: url("mc_holy_windows.json")))) ?? HolyWindowsCache()
        digests  = (try? d.decode([DayDigest].self,     from: Data(contentsOf: url("mc_digests.json"))))  ?? []
        timers   = (try? d.decode([WorkTimer].self,     from: Data(contentsOf: url("mc_timers.json"))))   ?? []
        counters = (try? d.decode([TallyCounter].self,  from: Data(contentsOf: url("mc_counters.json")))) ?? []
        pending  = (try? d.decode([PendingChange].self, from: Data(contentsOf: url("mc_pending.json"))))  ?? []
        pendingCount = pending.count
        // Prevent temp-ID collisions after a restart: start below the lowest existing negative ID.
        let negIDs = events.map { $0.id }.filter { $0 < 0 } + todos.map { $0.id }.filter { $0 < 0 }
        nextTemp = (negIDs.min().map { $0 - 1 }) ?? -1
        sweepLive(atLaunch: true)
        loadVoice()
        #if DEBUG
        seedVoiceForUITest()
        #endif
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
                                     holidays: holidays, holy: holy, digests: digests,
                                     timers: timers, counters: counters, dir: dir)
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
        let holy: HolyWindowsCache
        let digests: [DayDigest]
        let timers: [WorkTimer]
        let counters: [TallyCounter]
        let dir: URL

        func write() {
            let e = JSONEncoder()
            try? e.encode(events).write(to:   dir.appendingPathComponent("mc_events.json"))
            try? e.encode(todos).write(to:    dir.appendingPathComponent("mc_todos.json"))
            try? e.encode(tags).write(to:     dir.appendingPathComponent("mc_tags.json"))
            try? e.encode(holidays).write(to: dir.appendingPathComponent("mc_holidays.json"))
            try? e.encode(holy).write(to:     dir.appendingPathComponent("mc_holy_windows.json"))
            try? e.encode(digests).write(to:  dir.appendingPathComponent("mc_digests.json"))
            try? e.encode(timers).write(to:   dir.appendingPathComponent("mc_timers.json"))
            try? e.encode(counters).write(to: dir.appendingPathComponent("mc_counters.json"))
        }
    }

    /// Write the caches now, without waiting for the debounce — for the moment
    /// the app goes to the background, where "shortly" may never arrive.
    func flushCachesNow() {
        cacheFlush?.cancel()
        CacheSnapshot(events: events, todos: todos, tags: tags, holidays: holidays,
                      holy: holy, digests: digests, timers: timers, counters: counters,
                      dir: dir).write()
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

    // MARK: - Shabbat / yom tov windows (the yellow lines, offline)

    /// Keep what the Mac computed, the way holidays are kept — but with one
    /// difference that matters: these minutes depend on WHERE they were
    /// computed. A fresh answer for a different place (the phone travelled,
    /// or the offsets were edited) makes every cached window stale, not just
    /// the refetched span, so the whole cache is replaced rather than merged.
    func cacheHolyWindows(_ fresh: HolyWindowsPayload) {
        if fresh.placeKey != holy.placeKey {
            holy = HolyWindowsCache(placeKey: fresh.placeKey, windows: fresh.windows)
        } else {
            // Same place: replace the refetched span, keep the rest.
            let outside = holy.windows.filter { $0.lastDay < fresh.start || $0.firstDay > fresh.end }
            var seen = Set<String>()
            holy.windows = (outside + fresh.windows)
                .filter { seen.insert($0.id).inserted }
                .sorted { $0.start < $1.start }
        }
        persist()
    }

    /// Cached windows touching [start, end] (ISO days).
    func holyWindowsBetween(_ start: String, _ end: String) -> [HolyWindow] {
        holy.windows.filter { $0.lastDay >= start && $0.firstDay <= end }
    }

    // MARK: - Day panels

    /// Replace the cached panels wholesale — the Mac recomputes all of them
    /// together and a half-old set would schedule yesterday's wording for
    /// tomorrow.
    ///
    /// Past days are dropped on the way in rather than accumulating: a panel
    /// whose day has gone can never fire again, and the file is read on every
    /// cold start.
    func cacheDigests(_ fresh: [DayDigest]) {
        let today = DateFormatter.isoDay.string(from: Date())
        digests = fresh.filter { $0.date >= today }.sorted { $0.date < $1.date }
        persist()
        // New panels mean new notifications to schedule.
        ReminderScheduler.shared.reconcile()
    }

    /// What ReminderScheduler turns into pending local notifications.
    func allDigests() -> [DayDigest] { digests }

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
    func allEvents() -> [CalendarEvent] { events + localSeriesOccurrences() }

    /// What may NOTIFY — reminders, the lock-screen card, the widget: this
    /// person's own rows only, never a calendar shared with them (Gil,
    /// 2026-09-28: "notifications should only be the main user").
    func ownEvents() -> [CalendarEvent] { events.filter { $0.shared != true } }

    // MARK: Series made on this phone
    //
    // The Mac stores a series as one row per occurrence. A series made on a
    // phone with no Mac (DEVQA Q85) is ONE row until a Mac exists to expand it
    // — its POST is queued with `recurrence` and the Mac makes the rows on
    // replay. Until then the views must still see every occurrence, so they
    // are drawn here, from the one row: same title, time and colour, on each
    // day the series lands. Their ids are derived from the row's
    // (`id * 10_000 - n`) so SwiftUI can tell them apart, and `event(_:)`
    // answers any of them with the row itself — editing one edits the series.

    static let occurrenceStride = 10_000

    func localSeriesOccurrences() -> [CalendarEvent] {
        var out: [CalendarEvent] = []
        for base in events where base.id < 0 && !base.recurrence.isEmpty {
            out += Self.occurrences(of: base)
        }
        return out
    }

    static func occurrences(of base: CalendarEvent, limit: Int = 400) -> [CalendarEvent] {
        let fmt = DateFormatter.isoDay
        let cal = Calendar(identifier: .gregorian)
        guard let first = fmt.date(from: base.date) else { return [] }
        let last = fmt.date(from: base.recurrenceEnd)
            ?? cal.date(byAdding: .year, value: base.recurrence == "yearly" ? 10 : 1, to: first)!
        let names = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        let days = Set((base.recurDays ?? "").split(separator: ",").compactMap { names.firstIndex(of: String($0).trimmingCharacters(in: .whitespaces)) })
        var out: [CalendarEvent] = []
        var n = 0
        var d = cal.date(byAdding: .day, value: 1, to: first)!
        while d <= last && out.count < limit {
            let wd = cal.component(.weekday, from: d) - 1
            let lands: Bool
            switch base.recurrence {
            case "daily": lands = true
            case "weekly": lands = days.isEmpty ? wd == cal.component(.weekday, from: first) - 1 : days.contains(wd)
            case "monthly": lands = cal.component(.day, from: d) == cal.component(.day, from: first)
            case "yearly": lands = cal.component(.day, from: d) == cal.component(.day, from: first)
                && cal.component(.month, from: d) == cal.component(.month, from: first)
            default: lands = false
            }
            if lands {
                n += 1
                var e = base
                e.id = base.id * occurrenceStride - n
                e.date = fmt.string(from: d)
                out.append(e)
            }
            d = cal.date(byAdding: .day, value: 1, to: d)!
        }
        return out
    }
    func ownTodos(includeCompleted: Bool = false) -> [Todo] {
        allTodos(list: nil, includeCompleted: includeCompleted).filter { $0.shared != true }
    }

    func eventsForDate(_ str: String) -> [CalendarEvent] {
        allEvents().filter { $0.date == str }
    }

    func eventsForMonth(_ year: Int, _ month: Int) -> [CalendarEvent] {
        let pfx = String(format: "%04d-%02d", year, month)
        return allEvents().filter { $0.date.hasPrefix(pfx) }
    }

    func eventsForWeek(startStr: String) -> [CalendarEvent] {
        let fmt = DateFormatter.isoDay
        guard let start = fmt.date(from: startStr) else { return [] }
        let end = Calendar.current.date(byAdding: .day, value: 7, to: start)!
        return allEvents().filter {
            guard let d = fmt.date(from: $0.date) else { return false }
            return d >= start && d < end
        }
    }

    func insertEvent(_ fields: [String: Any]) -> CalendarEvent {
        var e = CalendarEvent(
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
        if let days = fields["recur_days"] as? String, !days.isEmpty { e.recurDays = days }
        // Categorised and coloured the way the Mac will do it on replay
        // (`db.auto_category_and_color`): a category or colour the caller
        // chose stands; otherwise the Mac's labeller, run here. Local only —
        // the caller queues its own `fields`, which say neither.
        if let given = fields["category"] as? String, !given.isEmpty {
            e.category = given
        } else if let label = Labeller.shared.label(
                    title: e.title, attendees: e.attendees, location: e.location,
                    description: e.description, neighbours: neighbourColors(e.date, e.startTime)) {
            e.category = label.category
            if Self.autoColors.contains(e.color), let c = label.color { e.color = c }
        }
        nextTemp -= 1
        PhonePreview.current?.events.append(e.id)
        events.append(e)
        persist()
        ReminderScheduler.shared.reconcile()
        return e
    }

    /// `db._AUTO_COLORS`: a caller passing one of these is asking for the
    /// category's colour, not choosing one.
    private static let autoColors: Set<String> = ["", "#0078d4"]

    /// `db._neighbour_colors`: the colours of the events immediately before
    /// and after this start time on the same day.
    private func neighbourColors(_ date: String, _ start: String) -> [String] {
        let day = events.filter { $0.date == date }.enumerated()
            .sorted { ($0.element.startTime, $0.offset) < ($1.element.startTime, $1.offset) }
            .map { $0.element }
        var out: [String] = []
        if let before = day.last(where: { $0.startTime <= start }) { out.append(before.color) }
        if let after = day.first(where: { $0.startTime > start }) { out.append(after.color) }
        return out.filter { !$0.isEmpty }
    }

    func event(_ id: Int) -> CalendarEvent? {
        if let e = events.first(where: { $0.id == id }) { return e }
        // an occurrence of a series made on this phone: the series row answers
        guard id <= -Self.occurrenceStride else { return nil }
        return events.first { $0.id == canonicalID(id) }
    }

    /// The row an id stands for: itself, or — for an occurrence drawn from a
    /// series made on this phone — the series row (`id * stride - n`).
    func canonicalID(_ id: Int) -> Int {
        id <= -Self.occurrenceStride ? -((-id) / Self.occurrenceStride) : id
    }
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
            items: Self.widgetItems(now: now, events: ownEvents(), accentHex: accent))

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
        PhonePreview.current?.todos.append(t.id)
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
        if let v = fields["completed"] as? Int    { todos[i].completed = v }
        if let v = fields["linked_event_id"] as? Int { todos[i].linkedEventId = v }
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
            return ["Coursework", "Groceries", "Errands", "Work", "Personal", "Admin", "Shabbat"].map { TodoTag(name: $0, builtin: 1) }
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
        if PhonePreview.current != nil { return }      // the Mac gets the command instead
        if !compact(method: method, path: path, body: body) {
            pending.append(PendingChange(method: method, path: path, body: body))
        }
        persist()
    }

    /// Fold a change into what is already queued, when that loses nothing.
    ///
    /// A phone with no Mac (DEVQA Q85) may keep its queue for months, and a
    /// row made here and edited ten times would replay as eleven requests. So,
    /// for a row the Mac has NEVER seen (a temporary id, its create still
    /// queued): an edit merges into the create's body, and a delete removes
    /// the create and every queued edit — the Mac never hears of it. Rows the
    /// Mac knows are left exactly as queued: their edits carry
    /// `base_updated_at` for conflict detection, which a merge would blur.
    /// Returns true when the change was absorbed.
    private func compact(method: String, path: String, body: [String: Any]?) -> Bool {
        let parts = path.split(separator: "/").map(String.init)      // ["events", "-3"]
        guard parts.count == 2, ["events", "todos"].contains(parts[0]),
              let id = Int(parts[1]), id < 0 else { return false }
        let createPath = "/" + parts[0]
        guard let ci = pending.firstIndex(where: { p in
            p.method == "POST" && p.path == createPath && (p.body?["_temp_id"] as? Int) == id
        }) else { return false }
        switch method {
        case "PATCH":
            var merged = pending[ci].body ?? [:]
            for (k, v) in body ?? [:] where k != "base_updated_at" { merged[k] = v }
            pending[ci] = pending[ci].replacingBody(merged)
            return true
        case "DELETE":
            let createID = pending[ci].id
            pending.removeAll { p in p.id == createID || p.path == path || p.path.hasPrefix(path + "/") }
            return true
        default:
            return false
        }
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

    #if DEBUG
    /// UI tests only (`QueuedCommandDetailUITests`): the test passes a REAL
    /// server answer (captured from the engine in scratch stores) and this puts
    /// one finished row and one running row in the queue, through the same
    /// `updateVoice` path a real flush takes — so the detail screen is tested
    /// against a response that has actually been encoded into the queue file
    /// and decoded back out. Compiled out of release builds.
    private func seedVoiceForUITest() {
        let env = ProcessInfo.processInfo.environment
        guard let json = env["MACALENDAR_UITEST_VOICE_RESPONSE"],
              let resp = try? JSONDecoder().decode(VoiceResponse.self, from: Data(json.utf8))
        else { return }
        pendingVoice.removeAll()
        var done = PendingVoiceCommand(audioFile: "", draft: "walk the dog tomorrow at 9")
        done.status = .running
        pendingVoice.append(done)
        updateVoice(done.id, status: .running)
        updateVoice(done.id, status: .done, result: resp.message, response: resp)
        var running = PendingVoiceCommand(audioFile: "", draft: "walk jada every day at 9")
        running.status = .running
        pendingVoice.append(running)
        updateVoice(running.id, status: .running)
    }
    #endif

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

    /// A TYPED command while the Mac is away: no audio, and the text is final —
    /// what was typed is what runs, so it goes as `edited` (sent as text).
    @discardableResult
    func enqueueTyped(_ text: String) -> PendingVoiceCommand {
        var cmd = PendingVoiceCommand(audioFile: "", draft: text)
        cmd.edited = text
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

    // MARK: - Offline reading → provisional rows (assistant/offline)

    /// Book what the phone's model read, as placeholder rows the Mac never
    /// receives as creates — the Mac re-reads the COMMAND instead, and its
    /// rows replace these. Only creates; anything else waits for the Mac.
    /// Returns one line per booked item, for the reply.
    @discardableResult
    func bookProvisional(_ id: UUID, reading: OfflineReading) -> [String] {
        guard let i = pendingVoice.firstIndex(where: { $0.id == id }) else { return [] }
        var evs: [Int] = [], tds: [Int] = [], said: [String] = []
        for it in reading.items where it.bookable {
            if it.kind == "event" {
                var end = it.end
                if end.isEmpty, !it.start.isEmpty,
                   let t = DateFormatter.hhmm.date(from: it.start) {
                    end = DateFormatter.hhmm.string(from: t.addingTimeInterval(3600))
                }
                let e = insertEvent([
                    "title": it.title, "date": it.date, "start_time": it.start,
                    "end_time": end,
                    "recurrence": it.recurrence == "none" ? "" : it.recurrence,
                    "description": "Added on this phone while your Mac was away — your Mac will check it.",
                ])
                evs.append(e.id)
                said.append("'\(it.title)' on \(it.date)" + (it.start.isEmpty ? "" : " at \(it.start)")
                            + (it.recurrence == "none" ? "" : ", \(it.recurrence)"))
            } else {
                let t = insertTodo(title: it.title, list: "today",
                                   tags: Labeller.shared.tags(for: it.title))
                tds.append(t.id)
                said.append("to-do '\(it.title)'")
            }
        }
        pendingVoice[i].offlineReadingData = try? JSONEncoder().encode(reading)
        pendingVoice[i].provisionalEventIDs = evs
        pendingVoice[i].provisionalTodoIDs = tds
        persistVoice()
        return said
    }

    /// Remove a command's placeholder rows — the Mac has answered for it.
    func dropProvisional(_ id: UUID) {
        guard let i = pendingVoice.firstIndex(where: { $0.id == id }) else { return }
        for e in pendingVoice[i].provisionalEventIDs ?? [] { removeEvent(e) }
        for t in pendingVoice[i].provisionalTodoIDs ?? [] { removeTodo(t) }
        pendingVoice[i].provisionalEventIDs = []
        pendingVoice[i].provisionalTodoIDs = []
        persistVoice()
    }

    // MARK: - Phone first, Mac behind (assistant/offline, live)

    /// The placeholder rows of commands the phone did while the Mac WAS
    /// reachable — made at once, then removed when the Mac answers (its rows
    /// are the truth; an edit or delete the phone made to its copy is undone
    /// by the refresh, or kept, by whatever the Mac did). Persisted so a crash between the two can't strand them:
    /// anything past `keepUntil` is swept at launch and at the next booking.
    struct LiveBooking: Codable {
        var events: [Int]
        var todos: [Int]
        var keepUntil: Date
    }
    private static let liveKey = "macalendar.live_placeholders"
    private var live: [String: LiveBooking] {
        get {
            guard let d = UserDefaults.standard.data(forKey: Self.liveKey) else { return [:] }
            return (try? JSONDecoder().decode([String: LiveBooking].self, from: d)) ?? [:]
        }
        set { UserDefaults.standard.set(try? JSONEncoder().encode(newValue), forKey: Self.liveKey) }
    }

    /// Hold the rows a phone-first command made (`PhonePreview`) under
    /// `key` until the Mac answers for it.
    func holdLive(_ key: String, events evs: [Int], todos tds: [Int]) {
        sweepLive()
        guard !evs.isEmpty || !tds.isEmpty else { return }
        live[key] = LiveBooking(events: evs, todos: tds, keepUntil: Date().addingTimeInterval(600))
    }

    /// The Mac has answered for `key`: remove its placeholders.
    func dropLive(_ key: String) {
        guard let b = live[key] else { return }
        for e in b.events { removeEvent(e) }
        for t in b.todos { removeTodo(t) }
        live[key] = nil
    }

    /// The Mac queued the command for its model (`pending`): keep the rows a
    /// while longer — the Mac's twins replace them by title, day and time on a
    /// refresh (`cacheEvents`), and the sweep takes whatever is left.
    func extendLive(_ key: String, by seconds: TimeInterval = 1800) {
        guard var b = live[key] else { return }
        b.keepUntil = Date().addingTimeInterval(seconds)
        live[key] = b
    }

    /// At launch the arrays are filtered directly: `removeEvent` asks the
    /// ReminderScheduler, which reads `LocalStore.shared` — still being built.
    private func sweepLive(atLaunch: Bool = false) {
        let now = Date()
        for (k, b) in live where b.keepUntil < now {
            if atLaunch {
                events.removeAll { b.events.contains($0.id) }
                todos.removeAll { b.todos.contains($0.id) }
                live[k] = nil
            } else {
                dropLive(k)
            }
        }
    }

    func setOfflineVerdict(_ id: UUID, verdict: String?, macPendingID: Int? = nil) {
        guard let i = pendingVoice.firstIndex(where: { $0.id == id }) else { return }
        pendingVoice[i].offlineVerdict = verdict
        if let macPendingID { pendingVoice[i].macPendingID = macPendingID }
        persistVoice()
    }

    func voiceAudio(_ cmd: PendingVoiceCommand) -> Data? {
        try? Data(contentsOf: url(cmd.audioFile))
    }

    func updateVoice(_ id: UUID, status: PendingVoiceCommand.Status, result: String = "",
                     response: VoiceResponse? = nil) {
        guard let i = pendingVoice.firstIndex(where: { $0.id == id }) else { return }
        pendingVoice[i].status = status
        // Stamped on the way IN to `.running` so `reviveStalledVoice` (which
        // only looks at `.running` rows) can tell a command genuinely in flight
        // from one that was abandoned. Kept once it finishes, so the detail
        // screen can say how long the run took; cleared on a requeue.
        if status == .running { pendingVoice[i].startedAt = Date() }
        if status == .queued { pendingVoice[i].startedAt = nil }
        if status == .done || status == .failed { pendingVoice[i].finishedAt = Date() }
        if !result.isEmpty { pendingVoice[i].result = result }
        if let response { pendingVoice[i].responseData = try? JSONEncoder().encode(response) }
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

    /// 24-hour "HH:mm", POSIX, for the offline reader's clock times.
    static let hhmm: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        return f
    }()
}
