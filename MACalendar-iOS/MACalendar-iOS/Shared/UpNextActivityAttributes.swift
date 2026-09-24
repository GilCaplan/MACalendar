import Foundation
import ActivityKit
import AppIntents

/// The contract between the app and the `MACalendarWidgets` extension for the
/// "Up Next" Live Activity — the persistent lock-screen card showing today's
/// remaining agenda, with whatever is running (or coming right up) picked out
/// from the rest.
///
/// **This file is compiled into BOTH targets.** It must therefore stay
/// dependency-free: Foundation, ActivityKit and AppIntents only (the last for
/// the card's one button, `UpNextScrollIntent`), no `CalendarEvent`, no
/// `LocalStore`, no `Theme`, no SwiftUI. Everything the widget needs to draw
/// the card travels inside `ContentState`, including each event's category
/// colour as a hex string, because the extension cannot read the app's
/// settings.
///
/// **No live-ticking numbers.** Earlier versions of this card counted down to
/// an event and up through it with `Text(timerInterval:)`. Gil didn't want a
/// stopwatch — he wanted the day's agenda, with the current/next item picked
/// out visually. Nothing here is system-animated any more: the whole card is
/// a snapshot the app pushes, exactly like the title and time labels always
/// were, and it goes dim via `staleDate` the moment that snapshot can no
/// longer be trusted (the running event ended, or the day rolled over)
/// without a fresh push to correct it.
///
/// Availability: `ActivityAttributes` arrived in iOS 16.1 and the app's
/// deployment target is 16.0, so the type is gated. The extension is built at
/// 16.2 and needs no gate of its own.
@available(iOS 16.1, *)
struct UpNextAttributes: ActivityAttributes {

    /// Everything that changes over the life of one card. The card is *rolled*
    /// from day to day rather than ended and restarted, so the agenda is part
    /// of the dynamic state, not the static attributes.
    struct ContentState: Codable, Hashable {

        /// One row of the agenda, with everything the widget draws already
        /// resolved — the same discipline as `WidgetSnapshot.Item`, the
        /// home-screen widget's counterpart.
        struct AgendaItem: Codable, Hashable, Identifiable {
            var id: Int
            var title: String
            var start: Date
            var end: Date
            /// Human-readable clock label, exactly as the calendar shows it
            /// ("14:05" or "14:05 – 14:35"). Pre-formatted by the app so the
            /// extension needs no formatter or locale knowledge.
            var timeLabel: String
            var location: String
            /// "#RRGGBB" — the event's category colour, or the user's accent
            /// when the event has none. Already resolved by the app.
            var colorHex: String
        }

        /// Today's remaining events, soonest first — the one running (if any),
        /// then whatever else is left before midnight. Capped low: this is a
        /// lock-screen card, not the calendar.
        var items: [AgendaItem]

        /// `items[_].id` of the event currently running, or nil when nothing
        /// is. Named explicitly rather than "the first item", because a Live
        /// Activity view only redraws when the app pushes new content — it
        /// cannot compare `items.first.start` against the live clock itself,
        /// so the app has to say which one is current at push time.
        var currentId: Int?

        /// The instant this agenda stops being an honest picture of the day:
        /// the running event's end, or the next event's start when nothing is
        /// running yet. Handed to ActivityKit as `staleDate` so the system
        /// visually marks the card as out of date the moment it is, instead of
        /// confidently showing "NOW" for an event that already finished.
        var staleDate: Date

        /// Where the card's two-row window starts in `items`, moved by the
        /// card's own button (`UpNextScrollIntent`). Optional so a card
        /// archived by an older build still decodes, and nil — the top — on
        /// every push from the app: a new agenda starts at the top again.
        var offset: Int? = nil

        /// Today's open to-dos, for the card's to-do page (Gil, 2026-09-24:
        /// "to-do sure but build a structure so it looks nice"). Optional so a
        /// card archived before this decodes; nil or empty means no page.
        var todos: [TodoLine]? = nil

        /// How many open to-dos today in all — the page shows the first few.
        var todoCount: Int? = nil

        struct TodoLine: Codable, Hashable, Identifiable {
            var id: Int
            var title: String
            /// Due before today and still open.
            var overdue: Bool
        }
    }

    /// How many to-do lines the to-do page draws before "+N more".
    static let visibleTodos = 4

    /// How many agenda rows the lock-screen card draws at once.
    ///
    /// **Two, because of a hard limit, not a taste.** iOS truncates a Live
    /// Activity on the Lock Screen past 160 points of height. The card used to
    /// draw every item (up to five) at ~56 pt a row, so from the third row on
    /// the system clipped it top AND bottom — the header vanished and a row
    /// was cut through the middle (Gil's screenshot, 2026-09-23). A Live
    /// Activity cannot scroll: it is an archived snapshot with no gestures
    /// but buttons. So the card shows a window of two rows and a button that
    /// steps it down the day, one row at a time, with a push transition —
    /// the nearest thing to scrolling the platform allows.
    static let visibleRows = 2

    /// Fixed for the life of the activity. There is exactly one kind today;
    /// the field exists so a second activity type can be told apart later
    /// without breaking the archived attributes of a running card.
    var kind: String = "upNext"
}


// MARK: - The window and the roll, shared by the card and its button

@available(iOS 16.1, *)
extension UpNextAttributes.ContentState {

    // THE PAGES. The step button walks the day's events a row at a time,
    // then — when any to-do is open today — one TO-DO page, then back to the
    // top. `offset` is the page number.

    /// How many event windows there are: one per starting row.
    var eventPages: Int {
        items.isEmpty ? 0 : max(items.count - UpNextAttributes.visibleRows, 0) + 1
    }

    var hasTodoPage: Bool { !(todos ?? []).isEmpty }

    var pageCount: Int { eventPages + (hasTodoPage ? 1 : 0) }

    /// The page showing now, clamped.
    var page: Int { min(max(offset ?? 0, 0), max(pageCount - 1, 0)) }

    /// True when the to-do page is the one showing.
    var onTodoPage: Bool { hasTodoPage && page >= eventPages }

    /// Where the event window starts, clamped so it never runs off the end.
    var windowStart: Int {
        let last = max(items.count - UpNextAttributes.visibleRows, 0)
        return min(max(onTodoPage ? 0 : page, 0), last)
    }

    /// The rows the lock-screen card draws right now.
    var window: [AgendaItem] {
        Array(items.dropFirst(windowStart).prefix(UpNextAttributes.visibleRows))
    }

    /// "1–2 of 5" on an event page, "To-do" on the to-do page.
    var positionLabel: String {
        if onTodoPage { return "To-do" }
        let first = windowStart + 1
        let last = min(windowStart + UpNextAttributes.visibleRows, items.count)
        return "\(first)–\(last) of \(items.count)"
    }

    /// The next page, back to the top after the last one.
    var steppedOffset: Int {
        pageCount > 0 ? (page + 1) % pageCount : 0
    }

    /// The agenda as it stands at `date`, from what this card already knows.
    ///
    /// **Why the card can roll once without the app.** A Live Activity is
    /// redrawn by the system at exactly one moment nobody pushes: when its
    /// `staleDate` passes, with `context.isStale` set. Every row already
    /// carries its start and end, so at that moment the card can work out the
    /// NEXT picture itself — the event that just started becomes "NOW", the
    /// one that just ended drops off — instead of showing the old one dimmed
    /// until the phone is unlocked. It is one step, not a clock: the rolled
    /// picture has its own boundary and nothing redraws the card at that
    /// one. The same rule as `LiveActivityManager.currentCard`: the running
    /// event is the last one started, the stale date its end, else the next
    /// start.
    func rolled(at date: Date) -> Self {
        var s = self
        s.items = items.filter { $0.end > date }
        let running = s.items.last { $0.start <= date && date < $0.end }
        let next = s.items.first { $0.start > date }
        s.currentId = running?.id
        s.staleDate = running?.end ?? next?.start ?? date
        return s
    }
}

/// The card's one button: step the agenda window down one row.
///
/// A `LiveActivityIntent` runs in the APP's process (iOS launches it in the
/// background if it is not running), and updating the card needs nothing
/// but ActivityKit, so it lives here beside the state it moves rather than
/// in `LiveActivityManager`, which the widget target cannot see. The app's
/// own syncs leave the offset alone unless the agenda itself changed —
/// `LiveActivityManager.sameCard` does not compare it.
@available(iOS 17.0, *)
struct UpNextScrollIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Show more of today"
    static var isDiscoverable: Bool = false

    init() {}

    func perform() async throws -> some IntentResult {
        for activity in Activity<UpNextAttributes>.activities {
            var state = activity.content.state
            state.offset = state.steppedOffset
            await activity.update(ActivityContent(state: state,
                                                  staleDate: activity.content.staleDate))
        }
        return .result()
    }
}
