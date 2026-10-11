import Foundation

/// When a card comes back: FSRS-4.5 with its published default weights.
///
/// A Swift copy of `assistant/features/flashcards/fsrs.py`, so a review given
/// on a train moves the card AT ONCE — the next round, still offline, already
/// knows it is not due. The Mac replays the same answer (the review carries
/// the instant it happened, `at`) and its result replaces this one on sync.
///
/// The weights are written out exactly as Python's `W`:
/// `tests/unit/test_flashcards.py::test_the_phone_schedules_with_the_same_weights`
/// reads the `static let w` line below and compares it number for number, so a
/// retune on one side that forgets the other goes red.
enum FSRS {
    static let w: [Double] = [0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031, 1.6474, 0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755]
    static let decay = -0.5
    static let factor = 19.0 / 81.0
    /// An AGAIN comes back inside the same sitting.
    static let relearnMinutes = 10
    static let maxDays = 36500

    private static func clampD(_ d: Double) -> Double { min(10, max(1, d)) }

    static func retrievability(elapsedDays: Double, stability: Double) -> Double {
        pow(1 + factor * max(0, elapsedDays) / stability, decay)
    }

    private static func initD(_ g: Int) -> Double { clampD(w[4] - Double(g - 3) * w[5]) }

    /// (stability, difficulty) after `grade` (1 again … 4 easy), from the state
    /// before it. `stability == nil` is an item never reviewed.
    static func nextState(stability: Double?, difficulty: Double?,
                          elapsedDays: Double, grade: Int) -> (Double, Double) {
        let g = min(4, max(1, grade))
        guard let s0 = stability, let d0 = difficulty else {
            return (w[g - 1], initD(g))
        }
        let r = retrievability(elapsedDays: elapsedDays, stability: s0)
        var d = d0 - w[6] * Double(g - 3)
        d = clampD(w[7] * initD(4) + (1 - w[7]) * d)
        var s: Double
        if g == 1 {
            s = w[11] * pow(d0, -w[12]) * (pow(s0 + 1, w[13]) - 1) * exp(w[14] * (1 - r))
            s = min(s, s0)
        } else {
            let hard = g == 2 ? w[15] : 1.0
            let easy = g == 4 ? w[16] : 1.0
            s = s0 * (1 + exp(w[8]) * (11 - d0) * pow(s0, -w[9])
                      * (exp(w[10] * (1 - r)) - 1) * hard * easy)
        }
        return (max(0.1, s), d)
    }

    /// Days to the next review at a 90% recall target.
    static func intervalDays(_ stability: Double) -> Int {
        // Python's round() is banker's rounding; .toNearestOrEven matches it.
        Int(min(Double(maxDays), max(1, stability.rounded(.toNearestOrEven))))
    }

    /// The progress an item has after `grade` at `at` — the same arithmetic as
    /// `FlashcardStore.review` on the Mac, including lapses counting only for a
    /// card that had been seen before.
    static func apply(_ p: FlashProgress?, grade: Int, at: Date) -> FlashProgress {
        let last = p.flatMap { FlashDates.parse($0.last) }
        let elapsed = last.map { at.timeIntervalSince($0) / 86400 } ?? 0
        let (s, d) = nextState(stability: p?.stability, difficulty: p?.difficulty,
                               elapsedDays: elapsed, grade: grade)
        let due = grade == 1
            ? at.addingTimeInterval(Double(relearnMinutes) * 60)
            : at.addingTimeInterval(Double(intervalDays(s)) * 86400)
        return FlashProgress(stability: s, difficulty: d,
                             due: FlashDates.iso(due), last: FlashDates.iso(at),
                             reps: (p?.reps ?? 0) + 1,
                             lapses: (p?.lapses ?? 0) + (grade == 1 && p != nil ? 1 : 0))
    }

    /// "10m", "3d", "2mo", "1y" — the hint under each grade button.
    static func hint(_ p: FlashProgress?, grade: Int, at: Date = Date()) -> String {
        if grade == 1 { return "\(relearnMinutes)m" }
        let next = apply(p, grade: grade, at: at)
        let days = intervalDays(next.stability ?? 1)
        if days < 30 { return "\(days)d" }
        if days < 365 { return "\(Int((Double(days) / 30).rounded()))mo" }
        let years = Double(days) / 365
        return years < 10 ? String(format: "%.1fy", years) : "\(Int(years))y"
    }
}
