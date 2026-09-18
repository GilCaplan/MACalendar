import Foundation
import UIKit
@preconcurrency import UserNotifications

/// Schedules THE DAY PANEL — one notification a morning, summarising the day.
///
/// Gil, 2026-09-11: *"more of a panel that nicely shows what i have today and
/// not when something is about to pop up… it's on or off."* That replaced a
/// stream of pre-event banners, and this class with it: it used to mirror up
/// to 55 per-event `notify_at` verdicts into pending notifications. The Mac
/// stopped issuing those the same day (`notifications.pre_event` ships
/// `false`), so the mirror had been running empty ever since — the machinery
/// is dormant on both sides rather than deleted, and turning `pre_event` back
/// on restores it whole.
///
/// Three things decide the shape of this:
///
/// - **The Mac writes the words.** `title` and `body` arrive finished from
///   `assistant/notify.py:build_digest`, so this phone's banner and the Mac's
///   say the same thing. There is no formatter on this side to drift.
/// - **It is SCHEDULED, not pushed.** This app is local-only — there is no
///   server that can reach the phone at 07:00. iOS fires from a request
///   lodged earlier, so tomorrow's panel has to be in hand tonight. Hence a
///   week of panels cached (`LocalStore.allDigests`) and a week of requests
///   standing at any moment.
/// - **Being offline costs nothing.** The panels already lodged with iOS fire
///   on time with the Mac asleep, the tailnet down and this app never opened.
///   That is the whole reason the phone, not the Mac, is the ringer.
///
/// Coexistence with the workout rest timer: iOS caps pending local
/// notifications at 64 per app, and WorkoutStore schedules its rest-end
/// notification with a bare-UUID identifier. A week of panels is 7 of the 64,
/// where the old per-event mirror took 55 — and we still only ever REMOVE
/// requests whose identifier is one of ours, so the rest timer's is untouched.
@MainActor
final class ReminderScheduler {
    static let shared = ReminderScheduler()

    /// Identifier prefix for a day panel: `panel-YYYY-MM-DD`. (nonisolated:
    /// NotificationRouter reads it from the notification-center callback
    /// queue.)
    nonisolated static let panelPrefix = "panel-"

    /// The retired per-event mirror's prefix. Still swept on every reconcile
    /// because an app updating from a build that scheduled them has up to 55
    /// of its requests sitting in iOS's queue — they belong to no code any
    /// more and nothing else would ever clear them.
    nonisolated static let idPrefix = "evt-"

    private var pendingReconcile: Task<Void, Never>? = nil

    private init() {}

    /// Device-local master switch (Settings › Notifications). Read straight
    /// from UserDefaults so the scheduler needs no AppSettings instance.
    ///
    /// The key is the old `remindersEnabled` on purpose: it is the same
    /// question asked about a different notification, and renaming it would
    /// silently switch the panel back ON for anyone who had turned reminders
    /// off.
    static var isEnabled: Bool {
        UserDefaults.standard.object(forKey: "remindersEnabled") == nil
            ? true : UserDefaults.standard.bool(forKey: "remindersEnabled")
    }

    /// Re-derive the pending panel notifications from the cached digests.
    /// Idempotent and cheap to call often — every caller after any cache
    /// refresh is correct. Debounced 300 ms so the bursty paths (month load +
    /// token poll firing together) do the work once.
    func reconcile() {
        pendingReconcile?.cancel()
        pendingReconcile = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled else { return }
            await self?.performReconcile()
        }
    }

    private func performReconcile() async {
        // The "Up Next" lock-screen card is derived from the same cache and
        // the same enable flag, so every path that re-derives the panel
        // should re-derive it too. Placed before the isEnabled guard on
        // purpose: turning notifications off has to END the card, not just
        // stop scheduling. The manager decides for itself whether to start,
        // roll or end, and debounces exactly like this method.
        LiveActivityManager.shared.sync()

        let center = UNUserNotificationCenter.current()

        // Remove everything of ours first (and ONLY ours — the prefix filter
        // is what keeps the workout rest timer's UUID-identified request
        // alive), then rebuild from the cache. Simpler and safer than diffing.
        let pending = await center.pendingNotificationRequests()
        let mine = pending.map(\.identifier).filter {
            $0.hasPrefix(Self.panelPrefix) || $0.hasPrefix(Self.idPrefix)
        }
        if !mine.isEmpty {
            center.removePendingNotificationRequests(withIdentifiers: mine)
        }

        guard Self.isEnabled else { return }

        let now = Date()
        // `enabled` is the Mac's copy of the same switch; `firesAt` is nil
        // when the panel is held for Shabbat or yom tov. Either way there is
        // nothing to schedule, and the phone does not second-guess the
        // verdict — the observance maths happened on the Mac, sundown-bounded,
        // which this device could not repeat.
        let due = LocalStore.shared.allDigests().filter {
            $0.enabled && ($0.firesAt.flatMap(Self.parseLocal).map { $0 > now } ?? false)
        }
        guard !due.isEmpty else { return }

        // Ask the FIRST time there is actually something to schedule.
        //
        // The panel ships ON, and nothing else on this path ever asked: a
        // fresh install fetched a week of panels, called `add` for each,
        // and iOS rejected every one of them for want of authorization —
        // silently, because the adds are fire-and-forget. The feature was
        // therefore dead on arrival unless the user happened to open
        // Settings and find the permission row. Verified on a clean
        // simulator (2026-09-17): the digests were fetched, nothing was
        // scheduled, and nothing said so.
        //
        // This is still not "at app launch" — it is the first moment the
        // feature has a real notification to lodge, which is the moment the
        // ask is explicable. `request()` prompts only when the answer is
        // notDetermined, and we AWAIT it so this same pass schedules rather
        // than waiting for the next reconcile.
        _ = await NotificationPermission.request()

        for digest in due {
            guard let fire = digest.firesAt.flatMap(Self.parseLocal) else { continue }

            let content = UNMutableNotificationContent()
            content.title = digest.title
            content.body  = digest.body
            content.sound = .default

            let comps = Calendar.current.dateComponents(
                [.year, .month, .day, .hour, .minute], from: fire)
            let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: false)
            let request = UNNotificationRequest(identifier: "\(Self.panelPrefix)\(digest.date)",
                                                content: content, trigger: trigger)
            // Fire-and-forget, same as the rest timer's add — a failed add
            // just means this one won't ring, and the next reconcile retries.
            try? await center.add(request)
        }
    }

    /// The server writes its datetimes as naive local with minute precision
    /// ("2026-09-06T18:30" — isoformat(timespec="minutes")); the Mac and this
    /// phone share a wall clock. Seconds tolerated just in case.
    static func parseLocal(_ s: String) -> Date? {
        minuteFmt.date(from: s) ?? secondFmt.date(from: s)
    }

    private static let minuteFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm"
        return f
    }()

    private static let secondFmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()
}

// MARK: - Permission

/// The one place notification permission is requested — lifted from
/// WorkoutStore's rest timer (which now calls this) so every feature shares
/// one ask. Requested when the panel is first enabled or used, never at
/// app launch.
enum NotificationPermission {
    /// Ask only if the user has never been asked; a settled answer (granted
    /// or denied) is left alone — re-prompting is impossible on iOS anyway,
    /// Settings deep-links instead.
    static func requestIfNeeded() {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            guard settings.authorizationStatus == .notDetermined else { return }
            center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
        }
    }

    /// Current authorization, for the Settings status row.
    static func status() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    /// Async variant for UI that wants the settled status back (the Settings
    /// permission row). Same notDetermined-only guard as requestIfNeeded.
    @discardableResult
    static func request() async -> UNAuthorizationStatus {
        let center = UNUserNotificationCenter.current()
        if await center.notificationSettings().authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound])
        }
        return await center.notificationSettings().authorizationStatus
    }
}

// MARK: - Delegate / deep link

/// The app's UNUserNotificationCenterDelegate: presents banners while the
/// app is foregrounded, and turns a tap on a notification into a calendar
/// navigation — a day panel opens its DAY, a legacy per-event reminder opens
/// its event. Publishes the target; ContentView observes it, hands the date to
/// `CalendarNavigator` and asks `FeatureRouter` for the calendar tab — the
/// same two seams SearchView's onOpenEvent uses. (An @Published projected
/// publisher replays its current value on subscription, so a cold-start tap
/// set here before ContentView renders still lands.)
final class NotificationRouter: NSObject, UNUserNotificationCenterDelegate, ObservableObject {
    static let shared = NotificationRouter()

    @Published var pendingEventId: Int? = nil
    /// "YYYY-MM-DD" — the day a tapped panel was summarising.
    @Published var pendingDay: String? = nil

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler:
                                    @escaping (UNNotificationPresentationOptions) -> Void) {
        // Without a delegate, foreground notifications are silently dropped —
        // a panel that only works when the app is closed isn't reliable.
        completionHandler([.banner, .list, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let id = response.notification.request.identifier
        if id.hasPrefix(ReminderScheduler.panelPrefix) {
            let day = String(id.dropFirst(ReminderScheduler.panelPrefix.count))
            DispatchQueue.main.async { self.pendingDay = day }
        } else if id.hasPrefix(ReminderScheduler.idPrefix),
                  let eventId = Int(id.dropFirst(ReminderScheduler.idPrefix.count)) {
            DispatchQueue.main.async { self.pendingEventId = eventId }
        }
        completionHandler()
    }
}
