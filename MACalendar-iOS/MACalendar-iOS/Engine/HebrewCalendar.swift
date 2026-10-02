import Foundation

/// The Jewish calendar and Shabbat times, worked out ON the phone.
///
/// The Mac computes both (`assistant/hebrew_calendar.py` with pyluach,
/// `assistant/observance.py` with astral) and the phone caches what it serves.
/// A phone with no Mac (DEVQA Q85) has nothing to cache, so this is the same
/// computation in Swift: pyluach's holiday rules, the Mac's grouping and
/// erev convention, and astral's NOAA sun equations — ported, not
/// approximated, because a candle-lighting minute is the whole point.
/// `tests/unit/test_hebrew_calendar_phone.py` holds the two to agreement over
/// years of dates.
///
/// Months are pyluach's numbering (Nissan = 1 … Adar = 12, Adar II = 13);
/// weekdays are pyluach's too (1 = Sunday … 7 = Saturday).
enum HebrewCalendar {

    // MARK: - Dates

    struct HDate { let year: Int; let month: Int; let day: Int; let weekday: Int; let leap: Bool }

    static let greg: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }()
    static let hebrew: Calendar = {
        var c = Calendar(identifier: .hebrew)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }()

    static func date(_ iso: String) -> Date? {
        let p = iso.split(separator: "-").compactMap { Int($0) }
        guard p.count == 3 else { return nil }
        return greg.date(from: DateComponents(year: p[0], month: p[1], day: p[2], hour: 12))
    }

    static func iso(_ d: Date) -> String {
        let c = greg.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }

    static func addDays(_ d: Date, _ n: Int) -> Date { greg.date(byAdding: .day, value: n, to: d)! }

    static func isLeap(_ year: Int) -> Bool { ((7 * year + 1) % 19) < 7 }

    /// Foundation counts from Tishrei (1) and puts Adar I at 6, Adar / Adar II at 7.
    static func pyMonth(_ foundation: Int, leap: Bool) -> Int {
        switch foundation {
        case 1...5: return foundation + 6           // Tishrei … Shevat → 7 … 11
        case 6: return 12                           // Adar I
        case 7: return leap ? 13 : 12               // Adar II, or plain Adar
        default: return foundation - 7              // Nissan … Elul → 1 … 6
        }
    }

    static func foundationMonth(_ py: Int, leap: Bool) -> Int {
        switch py {
        case 7...11: return py - 6
        case 12: return leap ? 6 : 7
        case 13: return 7
        default: return py + 7
        }
    }

    static func hdate(_ d: Date) -> HDate {
        let c = hebrew.dateComponents([.year, .month, .day], from: d)
        let leap = isLeap(c.year!)
        let wd = greg.component(.weekday, from: d)               // 1 = Sunday
        return HDate(year: c.year!, month: pyMonth(c.month!, leap: leap), day: c.day!, weekday: wd, leap: leap)
    }

    static func gregorian(year: Int, month: Int, day: Int) -> Date? {
        let leap = isLeap(year)
        return hebrew.date(from: DateComponents(year: year, month: foundationMonth(month, leap: leap), day: day, hour: 12))
    }

    static func monthLength(year: Int, month: Int) -> Int {
        guard let d = gregorian(year: year, month: month, day: 1),
              let r = hebrew.range(of: .day, in: .month, for: d) else { return 30 }
        return r.count
    }

    // MARK: - pyluach's days

    typealias Name = (en: String, he: String)

    static let names: [String: String] = [
        "Rosh Hashana": "ראש השנה", "Yom Kippur": "יום כיפור", "Succos": "סוכות",
        "Shmini Atzeres": "שמיני עצרת", "Simchas Torah": "שמחת תורה", "Chanuka": "חנוכה",
        "Tu B'shvat": "ט״ו בשבט", "Purim Katan": "פורים קטן", "Purim": "פורים",
        "Shushan Purim": "שושן פורים", "Pesach": "פסח", "Pesach Sheni": "פסח שני",
        "Lag Ba'omer": "ל״ג בעומר", "Shavuos": "שבועות", "Tu B'av": "ט״ו באב",
        "Tzom Gedalia": "צום גדליה", "10 of Teves": "י׳ בטבת", "Taanis Esther": "תענית אסתר",
        "17 of Tamuz": "י״ז בתמוז", "9 of Av": "ט׳ באב",
    ]

    static func fastDay(_ h: HDate) -> String? {
        let adar = h.leap ? 13 : 12
        switch h.month {
        case 7: if (h.weekday == 1 && h.day == 4) || (h.weekday != 7 && h.day == 3) { return "Tzom Gedalia" }
        case 10: if h.day == 10 { return "10 of Teves" }
        case adar: if (h.weekday == 5 && h.day == 11) || (h.weekday != 7 && h.day == 13) { return "Taanis Esther" }
        case 4: if (h.weekday == 1 && h.day == 18) || (h.weekday != 7 && h.day == 17) { return "17 of Tamuz" }
        case 5: if (h.weekday == 1 && h.day == 10) || (h.weekday != 7 && h.day == 9) { return "9 of Av" }
        default: break
        }
        return nil
    }

    static func festival(_ h: HDate, israel: Bool, workingDays: Bool = true) -> String? {
        let d = h.day
        switch h.month {
        case 7:
            if d == 1 || d == 2 { return "Rosh Hashana" }
            if d == 10 { return "Yom Kippur" }
            if !workingDays && ((17...21).contains(d) || (israel && d == 16)) { return nil }
            if (15...21).contains(d) { return "Succos" }
            if d == 22 { return "Shmini Atzeres" }
            if d == 23 && !israel { return "Simchas Torah" }
        case 9, 10:
            guard workingDays else { return nil }
            let kislev = monthLength(year: h.year, month: 9)
            if (h.month == 9 && (25...kislev).contains(d)) || (h.month == 10 && d >= 1 && d < 8 - (kislev - 25)) {
                return "Chanuka"
            }
        case 11: if workingDays && d == 15 { return "Tu B'shvat" }
        case 12:
            guard workingDays else { return nil }
            if d == 14 { return h.leap ? "Purim Katan" : "Purim" }
            if d == 15 && !h.leap { return "Shushan Purim" }
        case 13:
            guard workingDays else { return nil }
            if d == 14 { return "Purim" }
            if d == 15 { return "Shushan Purim" }
        case 1:
            if !workingDays && ((17...20).contains(d) || (israel && d == 16)) { return nil }
            if d >= 15 && d < (israel ? 22 : 23) { return "Pesach" }
        case 2:
            if workingDays && d == 14 { return "Pesach Sheni" }
            if workingDays && d == 18 { return "Lag Ba'omer" }
        case 3: if d == 6 || (!israel && d == 7) { return "Shavuos" }
        case 5: if workingDays && d == 15 { return "Tu B'av" }
        default: break
        }
        return nil
    }

    static func holiday(_ h: HDate, israel: Bool) -> String? {
        fastDay(h) ?? festival(h, israel: israel)
    }

    static let majorFestivals: Set<String> = ["Rosh Hashana", "Yom Kippur", "Succos", "Shmini Atzeres",
                                              "Simchas Torah", "Pesach", "Shavuos"]

    // MARK: - Holidays (hebrew_calendar.enumerate_holidays)

    static func holidays(from start: String, to end: String, israel: Bool = true) -> [Holiday] {
        guard let s = date(start), let e = date(end), s <= e else { return [] }
        var occ: [(en: String, fast: Bool, day: Date)] = []
        var cur = addDays(s, -1)
        let stop = addDays(e, 1)
        while cur <= stop {
            let h = hdate(cur)
            if let en = holiday(h, israel: israel) { occ.append((en, fastDay(h) != nil, cur)) }
            cur = addDays(cur, 1)
        }
        var out: [Holiday] = []
        var i = 0
        while i < occ.count {
            var j = i
            while j + 1 < occ.count && occ[j + 1].en == occ[i].en && occ[j + 1].day == addDays(occ[j].day, 1) { j += 1 }
            let erev = addDays(occ[i].day, -1)
            if erev <= e && occ[j].day >= s {
                let cat = occ[i].fast ? "fast" : majorFestivals.contains(occ[i].en) ? "major" : "minor"
                out.append(Holiday(nameEn: occ[i].en, nameHe: names[occ[i].en] ?? occ[i].en, category: cat,
                                   gregorianErevStart: iso(erev), gregorianEnd: iso(occ[j].day)))
            }
            i = j + 1
        }
        out += modern(from: s, to: e)
        // a STABLE sort by erev, as Python's
        return out.enumerated().sorted { ($0.element.gregorianErevStart, $0.offset) < ($1.element.gregorianErevStart, $1.offset) }
            .map(\.element)
    }

    static let modernHebrew = ["Yom HaShoah": "יום השואה", "Yom HaZikaron": "יום הזיכרון",
                               "Yom Ha'atzmaut": "יום העצמאות", "Yom Yerushalayim": "יום ירושלים", "Sigd": "סיגד"]

    static func modern(from s: Date, to e: Date) -> [Holiday] {
        var out: [Holiday] = []
        for year in hdate(s).year...hdate(e).year {
            func on(_ m: Int, _ d: Int) -> Date? { gregorian(year: year, month: m, day: d) }
            guard let n27 = on(1, 27), let i5 = on(2, 5) else { continue }
            let wShoah = greg.component(.weekday, from: n27)
            let shoahDay = wShoah == 6 ? 26 : wShoah == 1 ? 28 : 27
            let wAtz = greg.component(.weekday, from: i5)
            let atzDay = wAtz == 7 ? 3 : wAtz == 6 ? 4 : wAtz == 2 ? 6 : 5
            let picks: [(String, Date?)] = [("Yom HaShoah", on(1, shoahDay)), ("Yom HaZikaron", on(2, atzDay - 1)),
                                            ("Yom Ha'atzmaut", on(2, atzDay)), ("Yom Yerushalayim", on(2, 28)),
                                            ("Sigd", on(8, 29))]
            for (en, day) in picks {
                guard let day else { continue }
                let erev = addDays(day, -1)
                if erev <= e && day >= s {
                    out.append(Holiday(nameEn: en, nameHe: modernHebrew[en]!, category: "modern",
                                       gregorianErevStart: iso(erev), gregorianEnd: iso(day)))
                }
            }
        }
        return out
    }

    // MARK: - Shabbat and yom tov (observance.holy_windows)

    struct Place {
        var latitude = 31.7683, longitude = 35.2137            // Jerusalem, the Mac's default
        var timeZone = TimeZone(identifier: "Asia/Jerusalem")!
        var candleMinutes = 18
        var tzeitDepression = 8.5

        /// Where this phone last was when "Sundown follows this device" is on;
        /// otherwise the Mac's default, Jerusalem — the same answer a Mac
        /// with no device position gives.
        static var current: Place {
            var p = Place()
            let d = UserDefaults.standard
            if d.bool(forKey: "followMyLocation"), let ll = d.array(forKey: "phonePlace") as? [Double], ll.count == 2 {
                p.latitude = ll[0]; p.longitude = ll[1]
                p.timeZone = d.string(forKey: "phonePlaceZone").flatMap(TimeZone.init(identifier:)) ?? .current
            }
            return p
        }
    }

    static func holyDayName(_ d: Date, israel: Bool) -> String {
        if let yt = festival(hdate(d), israel: israel, workingDays: false) { return yt }
        return greg.component(.weekday, from: d) == 7 ? "Shabbat" : ""
    }

    static func holyWindows(from start: String, to end: String, israel: Bool = true, place: Place = Place()) -> [HolyWindow] {
        guard let s = date(start), let e = date(end) else { return [] }
        let first = addDays(s, -4), stop = addDays(e, 4)
        var groups: [[Date]] = []
        var cur = first
        while cur <= stop {
            if !holyDayName(cur, israel: israel).isEmpty {
                if let last = groups.last?.last, last == addDays(cur, -1) { groups[groups.count - 1].append(cur) }
                else { groups.append([cur]) }
            }
            cur = addDays(cur, 1)
        }
        let isoFull = ISO8601DateFormatter()
        isoFull.timeZone = place.timeZone
        isoFull.formatOptions = [.withFullDate, .withTime, .withColonSeparatorInTime, .withDashSeparatorInDate,
                                 .withColonSeparatorInTimeZone, .withTimeZone]
        var out: [HolyWindow] = []
        for days in groups {
            let eve = addDays(days[0], -1), last = days.last!
            if last < s || eve > e { continue }
            if days[0] == first || last == stop { continue }
            guard let set = sun(on: eve, zenith: 90 + 32.0 / 120.0, place: place),
                  let dusk = sun(on: last, zenith: 90 + place.tzeitDepression, place: place) else { continue }
            let lit = Date(timeIntervalSince1970: floor(set.timeIntervalSince1970 - Double(place.candleMinutes * 60)))
            let night = Date(timeIntervalSince1970: floor(dusk.timeIntervalSince1970))
            var names: [String] = []
            for d in days { let n = holyDayName(d, israel: israel); if !names.contains(n) { names.append(n) } }
            var tcal = Calendar(identifier: .gregorian)
            tcal.timeZone = place.timeZone
            let hm = { (d: Date) -> String in
                let c = tcal.dateComponents([.hour, .minute], from: d)
                return String(format: "%02d:%02d", c.hour!, c.minute!)
            }
            // the end's minute rounds UP once its (whole) seconds are not zero
            let endUp = night.timeIntervalSince1970.truncatingRemainder(dividingBy: 60) > 0
                ? Date(timeIntervalSince1970: floor(night.timeIntervalSince1970 / 60) * 60 + 60) : night
            out.append(HolyWindow(name: names.joined(separator: " & "),
                                  startName: holyDayName(days[0], israel: israel),
                                  endName: holyDayName(last, israel: israel),
                                  start: isoFull.string(from: lit), end: isoFull.string(from: night),
                                  startLabel: hm(lit), endLabel: hm(endUp), days: days.map(iso)))
        }
        return out
    }

    // MARK: - The sun (astral 3.2's NOAA equations, ported)

    /// When the sun SETS through `zenith` degrees on `day` (a civil date in
    /// the place's own zone), or nil where it never does.
    static func sun(on day: Date, zenith: Double, place: Place) -> Date? {
        let comps = greg.dateComponents([.year, .month, .day], from: day)
        var tcal = Calendar(identifier: .gregorian)
        tcal.timeZone = place.timeZone
        func localDay(_ d: Date) -> DateComponents { tcal.dateComponents([.year, .month, .day], from: d) }
        guard var t = transit(comps.year!, comps.month!, comps.day!, zenith: zenith, place: place) else { return nil }
        let got = localDay(t)
        if got.year != comps.year || got.month != comps.month || got.day != comps.day {
            let shifted = addDays(day, (got.year!, got.month!, got.day!) < (comps.year!, comps.month!, comps.day!) ? 1 : -1)
            let c2 = greg.dateComponents([.year, .month, .day], from: shifted)
            guard let t2 = transit(c2.year!, c2.month!, c2.day!, zenith: zenith, place: place) else { return nil }
            let again = localDay(t2)
            guard again.year == comps.year, again.month == comps.month, again.day == comps.day else { return nil }
            t = t2
        }
        return t
    }

    private static func rad(_ d: Double) -> Double { d * .pi / 180 }
    private static func deg(_ r: Double) -> Double { r * 180 / .pi }

    static func julianDay(_ y: Int, _ m: Int, _ d: Int) -> Double {
        var year = y, month = m
        if month <= 2 { year -= 1; month += 12 }
        let a = Int(Double(year) / 100)
        let b = 2 - a + Int(Double(a) / 4)
        return Double(Int(365.25 * Double(year + 4716))) + Double(Int(30.6001 * Double(month + 1))) + Double(d) + Double(b) - 1524.5
    }

    private static func meanLong(_ jc: Double) -> Double {
        (280.46646 + jc * (36000.76983 + 0.0003032 * jc)).truncatingRemainder(dividingBy: 360).py360
    }
    private static func meanAnomaly(_ jc: Double) -> Double { 357.52911 + jc * (35999.05029 - 0.0001537 * jc) }
    private static func eccentricity(_ jc: Double) -> Double { 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc) }
    private static func eqOfCenter(_ jc: Double) -> Double {
        let m = rad(meanAnomaly(jc))
        return sin(m) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + sin(m + m) * (0.019993 - 0.000101 * jc) + sin(m + m + m) * 0.000289
    }
    private static func apparentLong(_ jc: Double) -> Double {
        let omega = 125.04 - 1934.136 * jc
        return meanLong(jc) + eqOfCenter(jc) - 0.00569 - 0.00478 * sin(rad(omega))
    }
    private static func obliquity(_ jc: Double) -> Double {
        let seconds = 21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))
        let e0 = 23.0 + (26.0 + seconds / 60.0) / 60.0
        return e0 + 0.00256 * cos(rad(125.04 - 1934.136 * jc))
    }
    private static func declination(_ jc: Double) -> Double { deg(asin(sin(rad(obliquity(jc))) * sin(rad(apparentLong(jc))))) }
    private static func eqOfTime(_ jc: Double) -> Double {
        let l0 = meanLong(jc), e = eccentricity(jc), m = meanAnomaly(jc)
        var y = tan(rad(obliquity(jc)) / 2); y *= y
        let t = y * sin(2 * rad(l0)) - 2 * e * sin(rad(m)) + 4 * e * y * sin(rad(m)) * cos(2 * rad(l0))
            - 0.5 * y * y * sin(4 * rad(l0)) - 1.25 * e * e * sin(2 * rad(m))
        return deg(t) * 4
    }
    private static func refraction(atZenith z: Double) -> Double {
        let elevation = 90 - z
        if elevation >= 85 { return 0 }
        let te = tan(rad(elevation))
        var r: Double
        if elevation > 5 { r = 58.1 / te - 0.07 / (te * te * te) + 0.000086 / (te * te * te * te * te) }
        else if elevation > -0.575 { r = 1735.0 + elevation * (-518.2 + elevation * (103.4 + elevation * (-12.79 + elevation * 0.711))) }
        else { r = -20.774 / te }
        return r / 3600
    }

    /// astral `time_of_transit(…, SunDirection.SETTING)` as a UTC instant.
    static func transit(_ y: Int, _ m: Int, _ d: Int, zenith: Double, place: Place) -> Date? {
        let lat = max(-89.8, min(89.8, place.latitude))
        let z = zenith + refraction(atZenith: zenith)
        let jd = julianDay(y, m, d)
        var adjustment = 0.0, timeUTC = 0.0
        for _ in 0..<2 {
            let jc = (jd + adjustment - 2451545.0) / 36525.0
            let decl = declination(jc)
            let h = (cos(rad(z)) - sin(rad(lat)) * sin(rad(decl))) / (cos(rad(lat)) * cos(rad(decl)))
            guard h >= -1, h <= 1 else { return nil }
            let hourAngle = -acos(h)
            let delta = -place.longitude - deg(hourAngle)
            var offset = delta * 4 - eqOfTime(jc)
            if offset < -720 { offset += 1440 }
            timeUTC = 720 + offset
            adjustment = timeUTC / 1440
        }
        guard let midnight = greg.date(from: DateComponents(year: y, month: m, day: d)) else { return nil }
        // astral's minutes_to_timedelta keeps microseconds: so do we
        return Date(timeIntervalSince1970: midnight.timeIntervalSince1970 + (timeUTC * 60 * 1_000_000).rounded(.towardZero) / 1_000_000)
    }
}

private extension Double {
    /// Python's `%`: the result takes the divisor's sign.
    var py360: Double { self < 0 ? self + 360 : self }
}
