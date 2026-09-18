import Foundation
import ActivityKit

/// The contract between the app and the `MACalendarWidgets` extension for the
/// "Up Next" Live Activity — the persistent lock-screen card showing today's
/// remaining agenda, with whatever is running (or coming right up) picked out
/// from the rest.
///
/// **This file is compiled into BOTH targets.** It must therefore stay
/// dependency-free: Foundation + ActivityKit only, no `CalendarEvent`, no
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
    }

    /// Fixed for the life of the activity. There is exactly one kind today;
    /// the field exists so a second activity type can be told apart later
    /// without breaking the archived attributes of a running card.
    var kind: String = "upNext"
}
