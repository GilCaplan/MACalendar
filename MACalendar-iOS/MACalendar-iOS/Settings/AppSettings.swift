import Foundation
import Combine
import SwiftUI

class AppSettings: ObservableObject {
    /// Where the Mac is, by default.
    ///
    /// This used to default to "" while the app hardcoded the address in THREE
    /// other places — the Settings help text, a comment in `APIClient.base`,
    /// and the very error message telling you to go and type it in. So a fresh
    /// install could name the host it was refusing to call, and the app sat
    /// there saying "Your Mac isn't reachable" about a Mac it knew the address
    /// of.
    ///
    /// The tailnet IP rather than the MagicDNS name: MagicDNS needs the
    /// tailnet's DNS to be on, and this is verified reachable. Anything you
    /// type wins, and `APIClient.base` accepts a bare host, a host:port, or a
    /// MagicDNS name just the same.
    static let defaultServerURL: String = {
        // From the build, not from source: `MACALENDAR_SERVER_URL` in
        // Base.xcconfig (overridden by the gitignored Local.xcconfig) reaches
        // us through the Info.plist key `MACalendarServerURL`. An address that
        // names one laptop does not belong in a shared repository.
        //
        // Empty is a legitimate answer — Base.xcconfig ships the placeholder
        // blank on purpose, so a fresh clone asks for an address rather than
        // silently trying somebody else's.
        let raw = Bundle.main.object(forInfoDictionaryKey: "MACalendarServerURL") as? String
        return (raw ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }()

    /// Whether the app may talk to the Mac at all.
    ///
    /// A deliberate "work offline", distinct from the Mac merely being
    /// unreachable. Everything keeps working from the cache and every write is
    /// queued exactly as it is when the Mac is asleep — the difference is that
    /// this is a CHOICE, so the app stops probing, stops waiting, and stops
    /// reporting an unreachable Mac as a problem.
    @Published var serverEnabled: Bool {
        didSet { UserDefaults.standard.set(serverEnabled, forKey: "serverEnabled") }
    }

    @Published var serverURL: String {
        didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") }
    }
    @Published var apiKey: String {
        didSet { UserDefaults.standard.set(apiKey, forKey: "apiKey") }
    }
    @Published var ttsVoice: String {
        didSet { UserDefaults.standard.set(ttsVoice, forKey: "ttsVoice") }
    }
    @Published var theme: String {
        didSet { UserDefaults.standard.set(theme, forKey: "userTheme") }
    }
    /// Whether this device tells the host where it is, so sundown is computed
    /// for here rather than for the place set in the host's configuration.
    /// Off by default: it is an improvement, not a requirement, and asking for
    /// a position on first launch without a reason is rude.
    @Published var followMyLocation: Bool {
        didSet { UserDefaults.standard.set(followMyLocation, forKey: "followMyLocation") }
    }

    @Published var accentColorHex: String {
        didSet { UserDefaults.standard.set(accentColorHex, forKey: "accentColorHex") }
    }
    var accentColor: Color { Color(hex: accentColorHex) ?? Theme.defaultAccent }

    /// Which calendar view the app opens on: "month" | "week" | "day".
    /// Week by default (Gil, 2026-09-24). Per device — the Mac keeps its own.
    @Published var defaultCalendarView: String {
        didSet { UserDefaults.standard.set(defaultCalendarView, forKey: "defaultCalendarView") }
    }

    /// The week's first day in Month and Week (Settings ▸ Appearance), per
    /// device like the Mac's own (Gil, 2026-09-29).
    @Published var weekStartsMonday: Bool {
        didSet { UserDefaults.standard.set(weekStartsMonday, forKey: "weekStartsMonday") }
    }

    /// The hours Day and Week fit to the screen and open at, first to last
    /// (24 = midnight); the rest are a scroll away (Gil, 2026-09-29: "start
    /// is 7am … end is midnight"). 7 → 24 is where the phone always opened.
    @Published var hoursFrom: Int {
        didSet { UserDefaults.standard.set(hoursFrom, forKey: "hoursFrom") }
    }
    @Published var hoursTo: Int {
        didSet { UserDefaults.standard.set(hoursTo, forKey: "hoursTo") }
    }

    /// Hour labels as 24-hour ("14:00") instead of "2 PM".
    @Published var clock24: Bool {
        didSet { UserDefaults.standard.set(clock24, forKey: "clock24") }
    }

    @Published var fontMonth: Double {
        didSet { UserDefaults.standard.set(fontMonth, forKey: "fontMonth") }
    }
    @Published var fontWeek: Double {
        didSet { UserDefaults.standard.set(fontWeek, forKey: "fontWeek") }
    }
    @Published var fontDay: Double {
        didSet { UserDefaults.standard.set(fontDay, forKey: "fontDay") }
    }
    @Published var fontTasks: Double {
        didSet { UserDefaults.standard.set(fontTasks, forKey: "fontTasks") }
    }

    // Hebrew calendar — local-only, mirrors the Mac's config.yaml options but
    // isn't synced from it (same precedent as the font settings above).
    @Published var hebrewDisplayMode: String {
        didSet { UserDefaults.standard.set(hebrewDisplayMode, forKey: "hebrewDisplayMode") }
    }
    @Published var showHolidays: Bool {
        didSet { UserDefaults.standard.set(showHolidays, forKey: "showHolidays") }
    }
    @Published var israelHolidays: Bool {
        didSet { UserDefaults.standard.set(israelHolidays, forKey: "israelHolidays") }
    }
    /// Yellow lines on the Day and Week grids at the exact minute Shabbat /
    /// yom tov begins and ends (Gil, 2026-09-24). On by default; shared with
    /// the Mac as `hebrew_calendar.show_shabbat_times`.
    @Published var showShabbatTimes: Bool {
        didSet { UserDefaults.standard.set(showShabbatTimes, forKey: "showShabbatTimes") }
    }
    /// The Shabbat / yom tov rule for what the ENGINE books (DEVQA Q59, Gil
    /// 2026-09-26): a series skips those days and a one-off is added with a
    /// note. On by default; shared with the Mac as `observance.enabled`, which
    /// the Mac's "Keep engine-made events off Shabbat & yom tov" box also sets.
    @Published var observanceEnabled: Bool {
        didSet { UserDefaults.standard.set(observanceEnabled, forKey: "observanceEnabled") }
    }

    // Local-only, mirrors the Mac's config.yaml `todo.show_completed` (default
    // off) but isn't synced from it — same precedent as the Hebrew settings
    // above. Unlike Mac, which only exposes this via config.yaml, iOS gets an
    // in-app toggle (TasksView toolbar) since editing a config file on a
    // phone isn't practical.
    @Published var hideCompletedTasks: Bool {
        didSet { UserDefaults.standard.set(hideCompletedTasks, forKey: "hideCompletedTasks") }
    }

    // Tasks tab tag filters: tag names and/or "__untagged__". Empty = show everything.
    // A task is shown when it matches ANY selected filter.
    @Published var taskTagFilters: [String] {
        didSet { UserDefaults.standard.set(taskTagFilters, forKey: "taskTagFilters") }
    }

    // "Tag mode": every task added from this phone gets this tag ("" = off).
    @Published var taskAutoTag: String {
        didSet { UserDefaults.standard.set(taskAutoTag, forKey: "taskAutoTag") }
    }

    // Same pattern as hideCompletedTasks above, applied to Coursework assignments.
    @Published var hideCompletedAssignments: Bool {
        didSet { UserDefaults.standard.set(hideCompletedAssignments, forKey: "hideCompletedAssignments") }
    }

    // Which tabs are shown is NOT here any more. It used to be five
    // `show*Tab` flags, each with its own UserDefaults key, its own hand-written
    // Toggle in SettingsView and — where someone remembered — its own bounce-off
    // handler in ContentView. It is now one map in `FeatureVisibility`, keyed by
    // the feature name the Mac and the API already use, and shared with the Mac
    // over /features. The five old keys are still READ ONCE to seed that map, so
    // an existing install keeps the setup it had.

    // Show the assistant's step-by-step "thinking" timeline while a voice
    // command runs (streams live from the Mac). Local-only preference.
    @Published var showThinking: Bool {
        didSet { UserDefaults.standard.set(showThinking, forKey: "showThinking") }
    }

    // Read the assistant's reply aloud (mirrors the Mac's tts.mute).
    @Published var speakReplies: Bool {
        didSet { UserDefaults.standard.set(speakReplies, forKey: "speakReplies") }
    }

    // Stop-word / silence auto-stop while recording (mirrors the Mac's behaviour).
    @Published var stopWordsEnabled: Bool {
        didSet { UserDefaults.standard.set(stopWordsEnabled, forKey: "stopWordsEnabled") }
    }
    /// After a recording stops, show Redo / Add more / Send for a few seconds.
    @Published var reviewBeforeSend: Bool {
        didSet { UserDefaults.standard.set(reviewBeforeSend, forKey: "reviewBeforeSend") }
    }
    /// Off = keep recording until the button is tapped or a stop word is said.
    @Published var silenceStopEnabled: Bool {
        didSet { UserDefaults.standard.set(silenceStopEnabled, forKey: "silenceStopEnabled") }
    }
    @Published var silenceStopSeconds: Double {
        didSet { UserDefaults.standard.set(silenceStopSeconds, forKey: "silenceStopSeconds") }
    }

    // First-run vocabulary interview shown/skipped (local-only flag).
    @Published var vocabOnboardingDone: Bool {
        didSet { UserDefaults.standard.set(vocabOnboardingDone, forKey: "vocabOnboardingDone") }
    }

    /// Hint codes the mic's tip card has already shown on this phone — each
    /// hint appears once, after that only Settings → How to Talk to Me.
    @Published var shownHints: [String] {
        didSet { UserDefaults.standard.set(shownHints, forKey: "shownHints") }
    }

    /// Device-local master switch for pre-event reminder rings on THIS phone.
    /// The lead-time policy (what fires when) lives on the Mac and is edited
    /// via PATCH /config; this only decides whether this device schedules the
    /// local notifications it is told about. ReminderScheduler reads the same
    /// UserDefaults key directly.
    @Published var remindersEnabled: Bool {
        didSet { UserDefaults.standard.set(remindersEnabled, forKey: "remindersEnabled") }
    }

    /// Device-local switch for the lock-screen agenda card (the "Up Next" Live
    /// Activity). Deliberately NOT the same switch as `remindersEnabled`: a
    /// card you want sitting on the lock screen and reminders you want ringing
    /// before each event are different wants, and the card used to disappear
    /// when you silenced the rings (Gil, 2026-09-17, asking for "a toggle
    /// button in the settings" of its own).
    ///
    /// Switching it ON also CLEARS a dismissal — see
    /// `LiveActivityManager.setEnabled` — so the toggle is how you get the card
    /// back today rather than waiting for tomorrow morning.
    /// Which list the Tasks tab is showing: "both" | "today" | "general".
    /// The TAG filter then applies only within that scope (Gil, 2026-09-18), so
    /// "Groceries" while General is selected means "general groceries" rather
    /// than every grocery task on both lists.
    @Published var taskListScope: String {
        didSet { UserDefaults.standard.set(taskListScope, forKey: "taskListScope") }
    }

    @Published var agendaCardEnabled: Bool {
        didSet {
            UserDefaults.standard.set(agendaCardEnabled, forKey: "agendaCardEnabled")
        }
    }

    /// How long an event lasts when no end was given, and the gap between
    /// chained events (DEVQA Q51). SHARED with the Mac through `events:` in
    /// config.yaml (GET/PATCH /config); these are the phone's cached copies,
    /// under the same keys `EventDefaults` reads when a sheet has no settings
    /// object in reach.
    @Published var eventLengthMinutes: Int {
        didSet { UserDefaults.standard.set(eventLengthMinutes, forKey: EventDefaults.lengthKey) }
    }
    @Published var chainGapMinutes: Int {
        didSet { UserDefaults.standard.set(chainGapMinutes, forKey: EventDefaults.gapKey) }
    }

    /// Where a repeating event with no end said stops, per cadence (DEVQA Q57),
    /// each a count in its cadence's own unit. SHARED with the Mac through
    /// `events.series_end_*` in config.yaml; these are the phone's cached copies.
    @Published var seriesEndDailyDays: Int { didSet { SeriesEnd.daily.store(seriesEndDailyDays) } }
    @Published var seriesEndWeeklyWeeks: Int { didSet { SeriesEnd.weekly.store(seriesEndWeeklyWeeks) } }
    @Published var seriesEndMonthlyMonths: Int { didSet { SeriesEnd.monthly.store(seriesEndMonthlyMonths) } }
    @Published var seriesEndYearlyYears: Int { didSet { SeriesEnd.yearly.store(seriesEndYearlyYears) } }

    init() {
        self.eventLengthMinutes = EventDefaults.globalLength
        self.chainGapMinutes = EventDefaults.globalGap
        self.seriesEndDailyDays = SeriesEnd.daily.cached
        self.seriesEndWeeklyWeeks = SeriesEnd.weekly.cached
        self.seriesEndMonthlyMonths = SeriesEnd.monthly.cached
        self.seriesEndYearlyYears = SeriesEnd.yearly.cached
        self.followMyLocation = UserDefaults.standard.bool(forKey: "followMyLocation")
        self.speakReplies = UserDefaults.standard.object(forKey: "speakReplies") == nil
            ? true : UserDefaults.standard.bool(forKey: "speakReplies")
        self.stopWordsEnabled = UserDefaults.standard.object(forKey: "stopWordsEnabled") == nil
            ? true : UserDefaults.standard.bool(forKey: "stopWordsEnabled")
        self.reviewBeforeSend = UserDefaults.standard.object(forKey: "reviewBeforeSend") == nil
            ? true : UserDefaults.standard.bool(forKey: "reviewBeforeSend")
        self.silenceStopEnabled = UserDefaults.standard.object(forKey: "silenceStopEnabled") == nil
            ? true : UserDefaults.standard.bool(forKey: "silenceStopEnabled")
        let sil = UserDefaults.standard.double(forKey: "silenceStopSeconds")
        self.silenceStopSeconds = sil == 0 ? 6 : sil
        self.vocabOnboardingDone = UserDefaults.standard.bool(forKey: "vocabOnboardingDone")
        self.shownHints = UserDefaults.standard.stringArray(forKey: "shownHints") ?? []
        self.remindersEnabled = UserDefaults.standard.object(forKey: "remindersEnabled") == nil
            ? true : UserDefaults.standard.bool(forKey: "remindersEnabled")
        self.taskListScope = UserDefaults.standard.string(forKey: "taskListScope") ?? "both"
        self.agendaCardEnabled = UserDefaults.standard.object(forKey: "agendaCardEnabled") == nil
            ? true : UserDefaults.standard.bool(forKey: "agendaCardEnabled")
        self.showThinking = UserDefaults.standard.object(forKey: "showThinking") == nil
            ? true : UserDefaults.standard.bool(forKey: "showThinking")
        self.serverEnabled = UserDefaults.standard.object(forKey: "serverEnabled") == nil
            ? true : UserDefaults.standard.bool(forKey: "serverEnabled")
        self.serverURL = UserDefaults.standard.string(forKey: "serverURL")
            ?? Self.defaultServerURL
        self.apiKey    = UserDefaults.standard.string(forKey: "apiKey") ?? ""
        self.ttsVoice  = UserDefaults.standard.string(forKey: "ttsVoice") ?? "en-US"
        self.theme     = UserDefaults.standard.string(forKey: "userTheme") ?? "dark"
        self.accentColorHex = UserDefaults.standard.string(forKey: "accentColorHex") ?? Theme.defaultAccentHex

        self.defaultCalendarView = UserDefaults.standard.string(forKey: "defaultCalendarView") ?? "week"
        self.weekStartsMonday = UserDefaults.standard.bool(forKey: "weekStartsMonday")
        self.clock24 = UserDefaults.standard.bool(forKey: "clock24")
        self.hoursFrom = UserDefaults.standard.object(forKey: "hoursFrom") as? Int ?? 7
        self.hoursTo = UserDefaults.standard.object(forKey: "hoursTo") as? Int ?? 24

        let fm = UserDefaults.standard.double(forKey: "fontMonth")
        self.fontMonth = fm == 0 ? 13 : fm
        
        let fw = UserDefaults.standard.double(forKey: "fontWeek")
        self.fontWeek  = fw == 0 ? 13 : fw
        
        let fd = UserDefaults.standard.double(forKey: "fontDay")
        self.fontDay   = fd == 0 ? 15 : fd
        
        let ft = UserDefaults.standard.double(forKey: "fontTasks")
        self.fontTasks = ft == 0 ? 16 : ft

        self.hebrewDisplayMode = UserDefaults.standard.string(forKey: "hebrewDisplayMode") ?? "both"
        self.showHolidays = UserDefaults.standard.object(forKey: "showHolidays") == nil
            ? true : UserDefaults.standard.bool(forKey: "showHolidays")
        self.israelHolidays = UserDefaults.standard.object(forKey: "israelHolidays") == nil
            ? true : UserDefaults.standard.bool(forKey: "israelHolidays")
        self.showShabbatTimes = UserDefaults.standard.object(forKey: "showShabbatTimes") == nil
            ? true : UserDefaults.standard.bool(forKey: "showShabbatTimes")
        self.observanceEnabled = UserDefaults.standard.object(forKey: "observanceEnabled") == nil
            ? true : UserDefaults.standard.bool(forKey: "observanceEnabled")

        self.hideCompletedTasks = UserDefaults.standard.object(forKey: "hideCompletedTasks") == nil
            ? true : UserDefaults.standard.bool(forKey: "hideCompletedTasks")

        if let arr = UserDefaults.standard.stringArray(forKey: "taskTagFilters") {
            self.taskTagFilters = arr
        } else {
            // Migrate the old single-value filter.
            let old = UserDefaults.standard.string(forKey: "taskTagFilter") ?? ""
            self.taskTagFilters = old.isEmpty ? [] : [old]
        }
        self.taskAutoTag   = UserDefaults.standard.string(forKey: "taskAutoTag") ?? ""

        self.hideCompletedAssignments = UserDefaults.standard.object(forKey: "hideCompletedAssignments") == nil
            ? true : UserDefaults.standard.bool(forKey: "hideCompletedAssignments")
    }
}

/// The default event length and chain gap as this phone last heard them from
/// the Mac (DEVQA Q51): the global pair, plus each category's own length.
///
/// Read through UserDefaults rather than `AppSettings` so a sheet that was not
/// handed the settings object (the event editor) still gets the number, and so
/// it works on a train: the Mac is the source of truth, this is its cache, and
/// an empty cache means the built-in hour.
enum EventDefaults {
    static let lengthKey = "eventLengthMinutes"
    static let gapKey = "chainGapMinutes"
    static let categoryLengthsKey = "categoryDefaultMinutes"

    /// The bounds the Mac enforces (`assistant/config.py`); a zero length
    /// would read there as "no end said".
    static let minLength = 5
    static let maxMinutes = 24 * 60

    static var globalLength: Int {
        let v = UserDefaults.standard.integer(forKey: lengthKey)
        return v >= minLength ? v : 60
    }

    static var globalGap: Int {
        guard UserDefaults.standard.object(forKey: gapKey) != nil else { return 0 }
        return max(0, UserDefaults.standard.integer(forKey: gapKey))
    }

    /// The length for an event of this category: its own if it has one, else
    /// the global.
    static func length(for category: String?) -> Int {
        if let category, !category.isEmpty,
           let map = UserDefaults.standard.dictionary(forKey: categoryLengthsKey) as? [String: Int],
           let own = map[category.lowercased()], own >= minLength {
            return own
        }
        return globalLength
    }

    /// Remember every category's own length from a /categories answer.
    static func remember(categories: [EventCategory]) {
        var map: [String: Int] = [:]
        for c in categories { if let m = c.defaultMinutes { map[c.name.lowercased()] = m } }
        UserDefaults.standard.set(map, forKey: categoryLengthsKey)
    }

    /// Remember one answer from GET /event_defaults: the global, and the
    /// category's own length when it differs from it.
    static func remember(_ d: ResolvedEventDefaults) {
        UserDefaults.standard.set(d.eventLengthMinutes, forKey: lengthKey)
        UserDefaults.standard.set(d.chainGapMinutes, forKey: gapKey)
        guard let category = d.category, !category.isEmpty else { return }
        var map = (UserDefaults.standard.dictionary(forKey: categoryLengthsKey) as? [String: Int]) ?? [:]
        map[category.lowercased()] = d.lengthMinutes == d.eventLengthMinutes ? nil : d.lengthMinutes
        UserDefaults.standard.set(map, forKey: categoryLengthsKey)
    }

    /// "HH:MM" plus minutes, capped at 23:59 the way the Mac's engine caps it.
    static func end(from start: String, minutes: Int) -> String? {
        let parts = start.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else { return nil }
        let total = min(parts[0] * 60 + parts[1] + minutes, 23 * 60 + 59)
        return String(format: "%02d:%02d", total / 60, total % 60)
    }
}

/// The four "a repeating event with no end stops after" settings (DEVQA Q57,
/// Gil 2026-09-26: daily 2 weeks, weekly 8 weeks, monthly 12 months, yearly
/// 10 years, "can be changed in settings"). The Mac owns the value and does
/// the stopping; the phone only shows and edits it.
enum SeriesEnd: String, CaseIterable, Identifiable {
    case daily, weekly, monthly, yearly

    var id: String { rawValue }

    /// The cadence's own unit — the count is also how many times it happens.
    var unit: String {
        switch self {
        case .daily: return "days"
        case .weekly: return "weeks"
        case .monthly: return "months"
        case .yearly: return "years"
        }
    }

    var singularUnit: String { String(unit.dropLast()) }

    /// `events.<configKey>` in config.yaml: series_end_daily_days, …
    var configKey: String { "series_end_\(rawValue)_\(unit)" }

    /// (built-in default, most a setting may ask for); the least is 1.
    /// A COPY of `SERIES_END_BOUNDS` in assistant/config.py — the table
    /// PATCH /config refuses against. Keep the two in step: a stepper that
    /// went past the Mac's bound would have its PATCH refused.
    var bounds: (builtIn: Int, max: Int) {
        switch self {
        case .daily: return (14, 366)
        case .weekly: return (8, 104)
        case .monthly: return (12, 120)
        case .yearly: return (10, 50)
        }
    }

    var keyPath: ReferenceWritableKeyPath<AppSettings, Int> {
        switch self {
        case .daily: return \.seriesEndDailyDays
        case .weekly: return \.seriesEndWeeklyWeeks
        case .monthly: return \.seriesEndMonthlyMonths
        case .yearly: return \.seriesEndYearlyYears
        }
    }

    private var defaultsKey: String { "seriesEnd.\(rawValue)" }

    /// The last value heard from the Mac, else the built-in default.
    var cached: Int {
        let v = UserDefaults.standard.integer(forKey: defaultsKey)
        return (1...bounds.max).contains(v) ? v : bounds.builtIn
    }

    func store(_ v: Int) { UserDefaults.standard.set(v, forKey: defaultsKey) }
}

/// GET /event_defaults — the length and gap resolved for one title or
/// category, with the global pair alongside.
struct ResolvedEventDefaults: Decodable {
    let category: String?
    let lengthMinutes: Int
    let gapMinutes: Int
    let eventLengthMinutes: Int
    let chainGapMinutes: Int

    enum CodingKeys: String, CodingKey {
        case category
        case lengthMinutes = "length_minutes"
        case gapMinutes = "gap_minutes"
        case eventLengthMinutes = "event_length_minutes"
        case chainGapMinutes = "chain_gap_minutes"
    }
}


/// How the calendar is drawn, from the settings above — the one place the
/// views ask (the Mac's calendar_ui/view_prefs.py is the same idea).
enum CalendarPrefs {
    /// The first day of the week holding `date` (Sunday, or Monday).
    static func weekStart(of date: Date, mondayFirst: Bool) -> Date {
        let cal = Calendar(identifier: .gregorian)
        let wd = cal.component(.weekday, from: date)           // 1 = Sunday … 7 = Saturday
        let back = mondayFirst ? (wd + 5) % 7 : wd - 1
        return cal.date(byAdding: .day, value: -back, to: cal.startOfDay(for: date)) ?? date
    }

    /// Weekday names in display order.
    static func dayHeaders(mondayFirst: Bool) -> [String] {
        mondayFirst ? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    : ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    }

    /// Points per hour so hours `from`…`to` fill `viewport`, within
    /// `minH`…`maxH`; `fallback` until the screen has been measured. A range
    /// that makes no sense is the whole day.
    static func hourHeight(viewport: CGFloat, from: Int, to: Int,
                           minH: CGFloat, maxH: CGFloat, fallback: CGFloat) -> CGFloat {
        guard viewport > 0 else { return fallback }
        let span = (0...23).contains(from) && (1...24).contains(to) && to > from ? to - from : 24
        return Swift.min(maxH, Swift.max(minH, (viewport / CGFloat(span)).rounded(.down)))
    }

    /// Where Day and Week open: the first shown hour.
    static func firstHour(from: Int, to: Int) -> Int {
        (0...23).contains(from) && (1...24).contains(to) && to > from ? from : 0
    }

    /// The time column's label for hour `h` (0…23).
    static func hourLabel(_ h: Int, clock24: Bool) -> String {
        if clock24 { return String(format: "%02d:00", h) }
        return h == 0 ? "12 AM" : h < 12 ? "\(h) AM" : h == 12 ? "12 PM" : "\(h - 12) PM"
    }
}
