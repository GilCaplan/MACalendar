import Foundation
import ActivityKit
import BackgroundTasks
import os

/// Drives the "Up Next" Live Activity — the persistent lock-screen card that
/// shows today's remaining agenda, with the running (or next) event picked
/// out from the rest.
///
/// **Why this can exist in a strictly local-only app.** Live Activities are
/// normally kept alive by APNs push, which this project will never use. The
/// card doesn't need it: the agenda only changes a handful of times a day (an
/// event starts, an event ends, the list is edited), and the app is already
/// woken for those moments — this pushes new content then and sits still the
/// rest of the time. There is no live-ticking element left to justify on its
/// own; the card is simply cheap to keep current.
///
/// **The cost of no push.** Those handful of updates can only happen when iOS
/// gives the app execution time: foregrounding, and the poll paths that already
/// run while it is open. A card whose headline event started while the phone
/// was locked therefore keeps saying "UP NEXT" until the app next wakes — so
/// every card carries a `staleDate` (`ContentState.staleDate`) at exactly the
/// moment it stops being true, and iOS dims it rather than letting it lie.
///
/// Same inputs as `ReminderScheduler`: the `LocalStore` event cache and the
/// device-local `remindersEnabled` toggle. It re-derives nothing about
/// reminder policy — this card is about what is *next*, not about what rings.
@MainActor
final class LiveActivityManager {
    static let shared = LiveActivityManager()

    /// Live Activities are hard-capped at 8 hours by iOS, so there is no point
    /// starting one for an event further out than that.
    static let horizon: TimeInterval = 8 * 3600

    /// Assumed length of an event with no end time — gives a running event a
    /// sensible `staleDate` to go dim at instead of none at all.
    static let assumedDuration: TimeInterval = 3600

    private var pendingSync: Task<Void, Never>? = nil

    private let log = Logger(subsystem: "com.macalendar.app", category: "LiveActivity")

    /// Ids of activities WE ended, so the dismissal watcher can tell the user
    /// swiping the card away from us retiring it. Both arrive as the same
    /// `.dismissed` state update and they mean opposite things: one is "I don't
    /// want this today", the other is "there is nothing left to show".
    private var endedByUs: Set<String> = []

    /// Ids already being watched, so adopting the same long-lived card on every
    /// sync does not pile up one watcher per sync for the life of the app.
    private var watching: Set<String> = []

    private init() {}

    // MARK: - Switched off, or cleared for the day

    private static let enabledKey = "agendaCardEnabled"
    private static let suppressedKey = "agendaCardSuppressedUntil"

    /// The Settings toggle, read straight from UserDefaults so the manager
    /// needs no `AppSettings` instance — same trick as
    /// `ReminderScheduler.isEnabled`. Defaults ON for an install that has
    /// never seen the switch.
    static var isEnabled: Bool {
        UserDefaults.standard.object(forKey: enabledKey) == nil
            ? true : UserDefaults.standard.bool(forKey: enabledKey)
    }

    /// While this is in the future, no card is started.
    ///
    /// **This is the whole fix for "if i clear it, it shouldn't reappear"**
    /// (Gil, 2026-09-17). Dismissing a Live Activity only empties
    /// `Activity.activities` — it records nothing — so the next `sync()` from a
    /// foreground, a `/changes` poll or the 30 s tick saw no card and started a
    /// fresh one. The card came back within seconds of being swiped away, over
    /// and over. The intent to be rid of it has to be written down somewhere,
    /// and it has to survive a relaunch, so it lives here.
    static var suppressedUntil: Date? {
        get {
            let t = UserDefaults.standard.double(forKey: suppressedKey)
            return t > 0 ? Date(timeIntervalSince1970: t) : nil
        }
        set {
            if let d = newValue {
                UserDefaults.standard.set(d.timeIntervalSince1970, forKey: suppressedKey)
            } else {
                UserDefaults.standard.removeObject(forKey: suppressedKey)
            }
        }
    }

    /// The hour a cleared card comes back: 06:00 the following morning (Gil:
    /// "It should respawn everyday at 6am").
    static let respawnHour = 6

    /// The next 06:00 strictly after `now`, in the device's own calendar, so
    /// the card returns with the morning wherever the phone is. Falls back to
    /// "24 h from now" only if the calendar cannot produce that instant, which
    /// it can't during some DST transitions.
    static func nextRespawn(after now: Date, calendar: Calendar = .current) -> Date {
        var comps = calendar.dateComponents([.year, .month, .day], from: now)
        comps.hour = respawnHour
        comps.minute = 0
        comps.second = 0
        if let today = calendar.date(from: comps), today > now { return today }
        if let todayAt6 = calendar.date(from: comps),
           let tomorrow = calendar.date(byAdding: .day, value: 1, to: todayAt6) {
            return tomorrow
        }
        return now.addingTimeInterval(24 * 3600)
    }

    /// Called by the Settings toggle. Switching ON clears any dismissal, which
    /// is what makes the toggle a way to get the card back NOW instead of
    /// waiting for 06:00; switching OFF ends the card immediately.
    func setEnabled(_ on: Bool) {
        UserDefaults.standard.set(on, forKey: Self.enabledKey)
        if on { Self.suppressedUntil = nil }
        sync()
    }

    // MARK: - Coming back in the morning

    /// The background-refresh identifier, also listed under
    /// `BGTaskSchedulerPermittedIdentifiers` in Info.plist. iOS matches the two
    /// as exact strings and silently ignores a task whose id is not permitted,
    /// so these two spellings have to stay identical.
    static let refreshTaskID = "com.macalendar.app.agenda-refresh"

    /// Register the handler. Must run before launch finishes, so it is called
    /// from `MACalendarApp.init()` and not from a view.
    static func registerBackgroundRefresh() {
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: refreshTaskID, using: nil
        ) { task in
            Task { @MainActor in
                // Re-arm FIRST. A run that throws or is cut short still has to
                // leave tomorrow's wake-up scheduled, or the card stops coming
                // back after a single bad morning.
                scheduleBackgroundRefresh()
                LiveActivityManager.shared.sync()
                // The sync is debounced 300 ms and then talks to ActivityKit;
                // give it room before telling iOS the task is done, or the work
                // is cancelled the instant it starts.
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                task.setTaskCompleted(success: true)
            }
        }
    }

    /// Ask iOS to wake the app at the next 06:00.
    ///
    /// **This is a REQUEST, not a timer** — and the honest limit of the feature.
    /// `BGAppRefreshTask` gives no time guarantee: iOS decides, weighing
    /// battery, charge state and how much you use the app, and may run it late
    /// or not at all. A Live Activity can only be started by the app with
    /// execution time, and the only way to be exact would be an APNs push,
    /// which this project will never have. So the card is ALSO started by the
    /// first ordinary `sync()` after 06:00 — a foreground, a poll, a tick —
    /// which is the path that actually carries it most mornings. Together:
    /// usually there when you first look, always there once you open the app.
    static func scheduleBackgroundRefresh() {
        let request = BGAppRefreshTaskRequest(identifier: refreshTaskID)
        request.earliestBeginDate = nextRespawn(after: Date())
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            // Simulators refuse this outright, and a device can refuse it too.
            // Not worth surfacing: the foreground path still works.
            Logger(subsystem: "com.macalendar.app", category: "LiveActivity")
                .notice("agenda refresh not scheduled: \(error.localizedDescription, privacy: .public)")
        }
    }

    /// True when the card is being deliberately held back right now. Clears an
    /// expired suppression on the way past, so 06:00 needs no timer to arrive —
    /// the next sync after it simply stops being suppressed.
    private static func isSuppressed(now: Date) -> Bool {
        guard let until = suppressedUntil else { return false }
        if now >= until {
            suppressedUntil = nil
            return false
        }
        return true
    }

    // MARK: - Entry point

    /// The single entry point, called from every place the app already wakes:
    /// `ContentView`'s foreground handler, its `/changes` poll branch and its
    /// 30 s tick, and `ReminderScheduler.reconcile()` (which covers every
    /// cache write). Idempotent, cheap and debounced 300 ms so the bursty
    /// paths collapse into one pass, exactly like `reconcile()`.
    func sync() {
        pendingSync?.cancel()
        pendingSync = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled else { return }
            await self?.performSync()
        }
    }

    private func performSync() async {
        // The home-screen widget rides the same wake moments. It is not gated
        // on 16.2 — a phone too old for a Live Activity still has widgets —
        // and it is a no-op unless the snapshot actually changed.
        LocalStore.shared.refreshWidgetSnapshot()

        // Everything below is 16.2 API (`ActivityContent`, `staleDate`, the
        // request/update overloads that take it). Older phones simply never
        // get a card; nothing else in the app notices.
        guard #available(iOS 16.2, *) else { return }
        await syncActivity()
    }

    // MARK: - The work

    @available(iOS 16.2, *)
    private func syncActivity() async {
        // The user can switch Live Activities off for the app in Settings, and
        // the app has its own reminders switch. Either one off means no card —
        // and any card already up is ended, not left orphaned.
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            await endAll(reason: "Live Activities disabled for this app")
            return
        }
        guard Self.isEnabled else {
            await endAll(reason: "agenda card switched off in Settings")
            return
        }
        // Cleared by hand: stay gone. NOT `endAll` — there is nothing to end,
        // the user already did that, and the point is to start nothing new.
        if Self.isSuppressed(now: Date()) {
            log.notice("""
                suppressed until \(Self.suppressedUntil ?? Date(), privacy: .public) \
                — cleared by hand, back at 0\(Self.respawnHour, privacy: .public):00
                """)
            return
        }

        guard let state = Self.currentCard(now: Date(),
                                           events: LocalStore.shared.allEvents(),
                                           accentHex: Self.accentHex) else {
            await endAll(reason: "nothing running and nothing starting within 8 h")
            return
        }

        let content = ActivityContent(state: state, staleDate: state.staleDate)
        let live = Activity<UpNextAttributes>.activities

        // Belt and braces: only one "Up Next" card is ever meaningful. If a
        // crash or a reinstall left more than one behind, keep the first and
        // end the strays.
        if live.count > 1 {
            for extra in live.dropFirst() {
                endedByUs.insert(extra.id)
                await extra.end(nil, dismissalPolicy: .immediate)
            }
            log.notice("ended \(live.count - 1) stray Up Next activities")
        }

        if let activity = live.first {
            // A card that outlived the app's last launch has no watcher on it,
            // so a swipe would go unrecorded and the card would come straight
            // back — the original bug, just one relaunch later. Adopting it
            // here is idempotent: `watching` keeps a second watcher off the
            // same id.
            watchForDismissal(activity)
            guard !Self.sameCard(activity.content.state, state) else { return }
            await activity.update(content)
            log.notice("""
                updated Up Next → \(state.items.count, privacy: .public) item(s), \
                current=\(state.currentId.map(String.init) ?? "none", privacy: .public) \
                (stale at \(state.staleDate, privacy: .public))
                """)
            print("[LiveActivity] updated → \(state.items.count) item(s), current=\(state.currentId?.description ?? "none")")
        } else {
            do {
                let activity = try Activity.request(
                    attributes: UpNextAttributes(),
                    content: content,
                    pushType: nil            // local-only: never APNs
                )
                // "Started" is precisely this: the API returned an Activity
                // instead of throwing. Logged so a device run can be verified
                // without seeing the lock screen.
                log.notice("""
                    STARTED Up Next id=\(activity.id, privacy: .public) \
                    \(state.items.count, privacy: .public) item(s), \
                    current=\(state.currentId.map(String.init) ?? "none", privacy: .public)
                    """)
                print("[LiveActivity] STARTED id=\(activity.id) \(state.items.count) item(s), "
                      + "current=\(state.currentId?.description ?? "none")")
                watchForDismissal(activity)
            } catch {
                log.error("Up Next request failed: \(error.localizedDescription, privacy: .public)")
                print("[LiveActivity] request FAILED: \(error)")
            }
        }
    }

    /// Notice the user swiping the card away, and hold it back until 06:00.
    ///
    /// `activityStateUpdates` reports `.dismissed` for BOTH a swipe and our own
    /// `end(...)`, so an unfiltered watcher would suppress the card every time
    /// the day simply ran out of events — and then not show it again tomorrow
    /// either, which is worse than the bug it fixes. `endedByUs` is how the two
    /// are told apart.
    @available(iOS 16.2, *)
    private func watchForDismissal(_ activity: Activity<UpNextAttributes>) {
        let id = activity.id
        guard !watching.contains(id) else { return }
        watching.insert(id)
        Task { [weak self] in
            for await state in activity.activityStateUpdates {
                guard state == .dismissed || state == .ended else { continue }
                guard let self else { return }
                self.watching.remove(id)
                if self.endedByUs.remove(id) != nil {
                    self.log.notice("card \(id, privacy: .public) ended by us — not suppressing")
                } else {
                    let until = Self.nextRespawn(after: Date())
                    Self.suppressedUntil = until
                    self.log.notice("""
                        card \(id, privacy: .public) CLEARED BY HAND \
                        — suppressed until \(until, privacy: .public)
                        """)
                    print("[LiveActivity] cleared by hand — back at \(until)")
                }
                return
            }
        }
    }

    @available(iOS 16.2, *)
    private func endAll(reason: String) async {
        let live = Activity<UpNextAttributes>.activities
        guard !live.isEmpty else { return }
        for activity in live {
            endedByUs.insert(activity.id)
            await activity.end(nil, dismissalPolicy: .immediate)
        }
        log.notice("ended \(live.count) Up Next activities: \(reason, privacy: .public)")
        print("[LiveActivity] ended \(live.count): \(reason)")
    }

    // MARK: - Choosing what the card shows

    /// How many rows the card shows. A lock-screen card, not the calendar —
    /// the current/next item is the point, the rest is context.
    static let maxAgendaItems = 5

    /// Today's remaining agenda: the event currently running (if any), then
    /// whatever else is left before midnight, soonest first. Pure and static
    /// so it can be reasoned about (and tested) without ActivityKit or a
    /// device.
    ///
    /// The card only exists — same as before — when something is running or
    /// something starts within the 8-hour ActivityKit horizon; once it does,
    /// every other event still left today rides along in `items` rather than
    /// being dropped, so the card reads as an agenda and not a single ticket.
    /// An in-progress event always wins the `currentId` slot over an upcoming
    /// one: a card that marks "Standup" current while standup is happening is
    /// the whole point of the "then rolls to the next one" behaviour.
    @available(iOS 16.1, *)
    static func currentCard(now: Date,
                            events: [CalendarEvent],
                            accentHex: String) -> UpNextAttributes.ContentState? {
        struct Slot { let event: CalendarEvent; let start: Date; let end: Date }

        let midnight = Calendar.current.startOfDay(for: now).addingTimeInterval(86_400)

        let slots: [Slot] = events.compactMap { e in
            // An all-day / timeless row has no clock position to place.
            guard !e.startTime.isEmpty,
                  let start = ReminderScheduler.parseLocal("\(e.date)T\(e.startTime)")
            else { return nil }
            var end = (e.endTime.isEmpty ? nil : ReminderScheduler.parseLocal("\(e.date)T\(e.endTime)"))
                ?? start.addingTimeInterval(assumedDuration)
            // "23:00 – 01:00" parses both ends onto the same day; the end
            // belongs to the next one. Without this the event looks like it
            // ended 22 hours before it began.
            if end <= start { end = end.addingTimeInterval(86_400) }
            return Slot(event: e, start: start, end: end)
        }
        // Today's remaining events only — this card is an agenda for the
        // day, not a peek at tomorrow.
        .filter { $0.end > now && $0.start < midnight }
        .sorted { $0.start < $1.start }

        let running = slots.last { $0.start <= now && now < $0.end }
        let next    = slots.first { $0.start > now && $0.start <= now.addingTimeInterval(horizon) }
        guard running != nil || next != nil else { return nil }

        let items = slots.prefix(maxAgendaItems).map { slot -> UpNextAttributes.ContentState.AgendaItem in
            let e = slot.event
            return UpNextAttributes.ContentState.AgendaItem(
                id: e.id,
                title: e.title.isEmpty ? "Untitled event" : e.title,
                start: slot.start,
                end: slot.end,
                timeLabel: e.displayTime,
                location: e.location,
                colorHex: e.color.isEmpty ? accentHex : e.color)
        }

        return UpNextAttributes.ContentState(
            items: Array(items),
            currentId: running?.event.id,
            staleDate: running?.end ?? next?.start ?? now
        )
    }

    /// Does this card show the same thing as that one?
    @available(iOS 16.1, *)
    static func sameCard(_ a: UpNextAttributes.ContentState,
                         _ b: UpNextAttributes.ContentState) -> Bool {
        a.currentId == b.currentId && a.items == b.items && a.staleDate == b.staleDate
    }

    /// A one-shot text summary of the WHOLE day's agenda — every event today,
    /// not just what's left — mirroring the Mac's "Brief Me" phrasing
    /// (`_on_briefing_requested`, `window.py`) so the two surfaces read the
    /// same. Unlike `currentCard`, no 8-hour horizon and no remaining-only
    /// filter: a settings button asking to see today's plan wants the whole
    /// day, whether it's checked at 6 AM or 11 PM.
    static func todaysAgendaSummary(now: Date, events: [CalendarEvent]) -> String {
        let today = DateFormatter.isoDay.string(from: now)
        let todays = events.filter { $0.date == today }
                            .sorted { $0.startTime < $1.startTime }

        func label(_ e: CalendarEvent) -> String {
            let title = e.title.isEmpty ? "Untitled event" : e.title
            return e.displayTime.isEmpty ? title : "\(title) at \(e.displayTime)"
        }

        switch todays.count {
        case 0:
            return "Your schedule is clear today. Nothing planned."
        case 1:
            return "You have one event today: \(label(todays[0]))."
        default:
            let parts = todays.map(label)
            let schedule = parts.count == 2
                ? "\(parts[0]) and \(parts[1])"
                : parts.dropLast().joined(separator: ", ") + ", and \(parts.last!)"
            return "You have \(todays.count) events today: \(schedule)."
        }
    }

    /// The accent the calendar itself falls back to for an event with no
    /// category colour. Read straight from UserDefaults, the same way
    /// `ReminderScheduler.isEnabled` does, so no AppSettings instance is needed.
    /// Shared with `LocalStore.refreshWidgetSnapshot`, which resolves colours
    /// for the home-screen widget by exactly the same rule.
    static var accentHex: String {
        UserDefaults.standard.string(forKey: "accentColorHex") ?? Theme.defaultAccentHex
    }
}
