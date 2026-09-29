import Foundation

// MARK: - Which day the words name, worked out in CODE (DEVQA Q68, step 1)
//
// A 40-row probe of Apple's model found it doing date arithmetic badly: with
// today Wednesday 9 September, "this friday" came back as the 17th, "next
// tuesday" as 1 October, "march 5th" as a date already past. The Mac's engine
// never asks its model that question — rules resolve dates. So the phone's
// model now returns the day WORDS as said (`when`), and this resolves them by
// the project's rules — a port of `_phrase_to_date` in
// `assistant/engine/fastrule/experiments/gold.py`, the reading the FastRule
// board scores the engine against. `tests/unit/test_offline_protocol.py`
// runs both over the same phrases and requires the same answers.
//
// A phrase with no single day ("next week", "this weekend") resolves to nil,
// and an event with no day is left for the Mac rather than guessed.

enum OfflineDates {
    static func isoDay(_ d: Date) -> String {
        let f = DateFormatter()
        f.calendar = cal
        f.timeZone = cal.timeZone
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d)
    }

    static let weekdays = ["monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                           "friday": 4, "saturday": 5, "sunday": 6]
    static let months = ["january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
                         "june": 6, "july": 7, "august": 8, "september": 9,
                         "october": 10, "november": 11, "december": 12]
    static let small = ["a": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7]

    static var cal: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone.current
        return c
    }()

    /// ISO "yyyy-MM-dd" for the day `phrase` names, relative to `today`; nil
    /// for a range or anything unresolved.
    static func resolve(_ phrase: String, today: Date) -> String? {
        var s = phrase.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !s.isEmpty else { return nil }
        // Two readings the board's rules leave unresolved but speech uses all
        // the time — the phone's own additions, allowed by the parity test only
        // where the Python rules give no day at all:
        //   a bare weekday ("dentist friday") is the coming one, as "on friday";
        //   a leading "on" ("on the 15th", "on march 5th") changes nothing.
        // A trailing clock rides along in `when` sometimes ("every other
        // tuesday at 5 pm"); the day is what is resolved here.
        if let r = s.range(of: #"\s+at\s+.*$"#, options: .regularExpression) { s.removeSubrange(r) }
        // "this coming saturday" is "coming saturday".
        if s.hasPrefix("this coming ") { s = String(s.dropFirst(5)) }
        // A REPEAT's first day (CLAUDE.md: a weekly series starts on the
        // soonest weekday the sentence names): "every sunday", "every other
        // tuesday", "every tuesday and thursday" → the soonest named weekday;
        // "daily", "weekly", "every week", "once a month"… → today; "every
        // weekday" → today if a weekday, else Monday.
        if let r = s.range(of: #"^(?:every|each)\s+(?:other\s+)?"#, options: .regularExpression) {
            let rest = String(s[r.upperBound...])
            let named = rest.split(whereSeparator: { !$0.isLetter }).compactMap { weekdays[String($0)] }
            if !named.isEmpty {
                let todayWd = (cal.component(.weekday, from: cal.startOfDay(for: today)) + 5) % 7
                let delta = named.map { (($0 - todayWd) % 7 + 7) % 7 }.min()!
                return isoDay(cal.date(byAdding: .day, value: delta, to: cal.startOfDay(for: today))!)
            }
            if rest.hasPrefix("weekday") {
                let wd = (cal.component(.weekday, from: cal.startOfDay(for: today)) + 5) % 7
                let delta = wd >= 5 ? 7 - wd : 0
                return isoDay(cal.date(byAdding: .day, value: delta, to: cal.startOfDay(for: today))!)
            }
            if ["day", "morning", "evening", "night", "week", "month", "year"].contains(where: { rest.hasPrefix($0) }) {
                return isoDay(cal.startOfDay(for: today))
            }
        }
        if ["daily", "weekly", "monthly", "yearly", "once a week", "once a month", "twice a week",
            "every day", "nightly"].contains(s) {
            return isoDay(cal.startOfDay(for: today))
        }
        // Fixed offsets: "in three weeks", "two weeks from now", "a week from
        // today", "tomorrow week" (a week after tomorrow).
        let n: [String: Int] = ["a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6]
        if let r = s.range(of: #"^(?:in\s+)?(a|one|two|three|four|five|six|\d+)\s+weeks?(?:\s+from\s+(?:now|today))?$"#,
                           options: .regularExpression) {
            let word = String(s[r]).replacingOccurrences(of: "in ", with: "").split(separator: " ")[0]
            if let k = n[String(word)] ?? Int(word) {
                return isoDay(cal.date(byAdding: .day, value: 7 * k, to: cal.startOfDay(for: today))!)
            }
        }
        if s == "tomorrow week" || s == "a week tomorrow" {
            return isoDay(cal.date(byAdding: .day, value: 8, to: cal.startOfDay(for: today))!)
        }
        // Named days with one date: the next one.
        let named: [String: (Int, Int)] = ["christmas day": (12, 25), "christmas": (12, 25),
                                           "christmas eve": (12, 24), "new year's eve": (12, 31),
                                           "new years eve": (12, 31), "new year's day": (1, 1),
                                           "new years day": (1, 1), "valentine's day": (2, 14),
                                           "halloween": (10, 31)]
        if let (mo, day) = named[s] {
            let c = cal.dateComponents([.year, .month, .day], from: today)
            let past = (mo, day) < (c.month!, c.day!)
            return isoDay(cal.date(from: DateComponents(year: c.year! + (past ? 1 : 0), month: mo, day: day))!)
        }
        if weekdays[s] != nil { s = "on " + s }
        if s.hasPrefix("on the ") || (s.hasPrefix("on ") && months[String(s.dropFirst(3).split(separator: " ").first ?? "")] != nil) {
            s = String(s.dropFirst(3))
        }
        let t = cal.startOfDay(for: today)
        func iso(_ d: Date) -> String {
            let f = DateFormatter()
            f.calendar = cal
            f.timeZone = cal.timeZone
            f.locale = Locale(identifier: "en_US_POSIX")
            f.dateFormat = "yyyy-MM-dd"
            return f.string(from: d)
        }
        func add(_ days: Int) -> Date { cal.date(byAdding: .day, value: days, to: t)! }
        func match(_ pattern: String) -> [String]? {
            guard let re = try? NSRegularExpression(pattern: "^" + pattern + "$"),
                  let m = re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) else { return nil }
            return (0..<m.numberOfRanges).map {
                Range(m.range(at: $0), in: s).map { String(s[$0]) } ?? ""
            }
        }
        if ["today", "this afternoon", "this evening", "this morning", "tonight"].contains(s) {
            return iso(t)
        }
        if ["tomorrow", "tomorrow morning", "tomorrow afternoon", "tomorrow evening"].contains(s) {
            return iso(add(1))
        }
        // the end of the month is its last day (CLAUDE.md, "until the end of September")
        if let g = match(#"(?:(?:at|by|for|on|before|towards?)\s+)?(?:the\s+)?end\s+of\s+(the|this|next)\s+month"#) {
            var first = cal.date(from: cal.dateComponents([.year, .month], from: t))!
            if g[1] == "next" { first = cal.date(byAdding: .month, value: 1, to: first)! }
            let next = cal.date(byAdding: .month, value: 1, to: first)!
            return iso(cal.date(byAdding: .day, value: -1, to: next)!)
        }
        if s == "the day after tomorrow" { return iso(add(2)) }
        if let g = match(#"in (\d+|a|two|three|four|five|six|seven) days?"#) {
            let n = small[g[1]] ?? Int(g[1]) ?? 0
            return iso(add(n))
        }
        if let g = match(#"(?:this|next|coming|on)\s+(\w+day)"#), let wd = weekdays[g[1]] {
            // Foundation's weekday: 1 = Sunday … 7 = Saturday → Monday = 0
            let todayWd = (cal.component(.weekday, from: t) + 5) % 7
            var delta = ((wd - todayWd) % 7 + 7) % 7
            if s.hasPrefix("next") { delta = delta == 0 ? 7 : delta }
            return iso(add(delta))
        }
        if let g = match(#"(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?"#), let day = Int(g[1]) {
            // "the 21st" — this month, or next when it has passed
            var comps = cal.dateComponents([.year, .month, .day], from: t)
            if day < comps.day! {
                let nm = cal.date(byAdding: .month, value: 1, to: cal.date(from: DateComponents(
                    year: comps.year, month: comps.month, day: 1))!)!
                comps = cal.dateComponents([.year, .month], from: nm)
            }
            comps.day = day
            guard let d = cal.date(from: comps),
                  cal.component(.day, from: d) == day else { return nil }
            return iso(d)
        }
        if let g = match(#"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?"#), let mo = months[g[1]],
           let day = Int(g[2]) {
            // "march 5th" — the next one: this year, or next when it has passed
            let c = cal.dateComponents([.year, .month, .day], from: t)
            let past = (mo, day) < (c.month!, c.day!)
            guard let d = cal.date(from: DateComponents(year: c.year! + (past ? 1 : 0),
                                                        month: mo, day: day)),
                  cal.component(.month, from: d) == mo else { return nil }   // no 29 Feb → nil
            return iso(d)
        }
        return nil
    }
}
