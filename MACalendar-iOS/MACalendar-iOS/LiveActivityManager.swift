import Foundation
import ActivityKit
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

    private init() {}

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
        guard ReminderScheduler.isEnabled else {
            await endAll(reason: "reminders toggle is off")
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
                await extra.end(nil, dismissalPolicy: .immediate)
            }
            log.notice("ended \(live.count - 1) stray Up Next activities")
        }

        if let activity = live.first {
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
            } catch {
                log.error("Up Next request failed: \(error.localizedDescription, privacy: .public)")
                print("[LiveActivity] request FAILED: \(error)")
            }
        }
    }

    @available(iOS 16.2, *)
    private func endAll(reason: String) async {
        let live = Activity<UpNextAttributes>.activities
        guard !live.isEmpty else { return }
        for activity in live {
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

    /// The accent the calendar itself falls back to for an event with no
    /// category colour. Read straight from UserDefaults, the same way
    /// `ReminderScheduler.isEnabled` does, so no AppSettings instance is needed.
    /// Shared with `LocalStore.refreshWidgetSnapshot`, which resolves colours
    /// for the home-screen widget by exactly the same rule.
    static var accentHex: String {
        UserDefaults.standard.string(forKey: "accentColorHex") ?? Theme.defaultAccentHex
    }
}
