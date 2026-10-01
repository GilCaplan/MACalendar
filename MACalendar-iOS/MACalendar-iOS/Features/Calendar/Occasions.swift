import Contacts
import SwiftUI

// MARK: - Occasions on the phone (DEVQA Q73)
//
// Birthdays, anniversaries, yahrzeits, countdowns and the extra calendars.
// The Mac works out every date (assistant/occasions/) and sends all-day
// BANNERS; the phone draws them, caches them for when the Mac is away, and
// edits a person's own occasions through /occasions.

/// One all-day banner, as `GET /occasions/range` sends it.
struct OccasionBanner: Codable, Equatable, Identifiable {
    let date: String
    let title: String
    let kind: String
    let source: String          // "mine" | "jewish" | "national" | "christian" | "islamic"
    let color: String
    let editable: Bool
    var occasionId: String? = nil
    var years: Int? = nil

    var id: String { "\(date)|\(title)|\(occasionId ?? source)" }
    var uiColor: Color { Color(hex: color) ?? .pink }
    var glyph: String {
        ["birthday": "🎂", "anniversary": "💍", "yahrzeit": "🕯", "countdown": "⏳",
         "custom": "★", "jewish": "✡", "national": "⚑", "christian": "✝", "islamic": "☪"][kind] ?? "•"
    }

    enum CodingKeys: String, CodingKey {
        case date, title, kind, source, color, editable, years
        case occasionId = "occasion_id"
    }
}

/// A person's own occasion — the record the editor changes.
struct Occasion: Codable, Equatable, Identifiable {
    var id: String = ""
    var kind: String = "birthday"
    var title: String = ""
    var calendar: String = "gregorian"
    var month: Int = 1
    var day: Int = 1
    var year: Int? = nil
    var adar: String? = nil
    var remindDays: Int? = nil
    var color: String? = nil
    var note: String = ""

    enum CodingKeys: String, CodingKey {
        case id, kind, title, calendar, month, day, year, adar, color, note
        case remindDays = "remind_days"
    }

    /// What the Mac accepts on POST / PATCH.
    var body: [String: Any] {
        var b: [String: Any] = ["kind": kind, "title": title, "calendar": calendar,
                                "month": month, "day": day, "note": note]
        b["year"] = year ?? NSNull()
        b["adar"] = adar ?? NSNull()
        b["remind_days"] = remindDays ?? NSNull()
        b["color"] = color ?? NSNull()
        return b
    }
}

struct OccasionCountdown: Codable, Equatable, Identifiable {
    let id: String
    let title: String
    let date: String
    let daysLeft: Int
    enum CodingKeys: String, CodingKey { case id, title, date; case daysLeft = "days_left" }

    var label: String { daysLeft == 0 ? "today" : daysLeft == 1 ? "tomorrow" : "\(daysLeft) days" }
}

struct OccasionsPayload: Codable {
    let occasions: [Occasion]
    let countdowns: [OccasionCountdown]
}

/// The phone's copy, for when the Mac is away: banners by date, and countdowns.
final class OccasionCache {
    static let shared = OccasionCache()
    private let key = "macalendar.occasion_banners"
    private let cdKey = "macalendar.occasion_countdowns"

    func store(_ banners: [OccasionBanner], from start: String, to end: String) {
        var all = load().filter { $0.date < start || $0.date > end }
        all += banners
        if let d = try? JSONEncoder().encode(all) { UserDefaults.standard.set(d, forKey: key) }
    }

    func load() -> [OccasionBanner] {
        guard let d = UserDefaults.standard.data(forKey: key) else { return [] }
        return (try? JSONDecoder().decode([OccasionBanner].self, from: d)) ?? []
    }

    func between(_ start: String, _ end: String) -> [OccasionBanner] {
        load().filter { $0.date >= start && $0.date <= end }
    }

    func storeCountdowns(_ c: [OccasionCountdown]) {
        if let d = try? JSONEncoder().encode(c) { UserDefaults.standard.set(d, forKey: cdKey) }
    }

    func countdowns() -> [OccasionCountdown] {
        guard let d = UserDefaults.standard.data(forKey: cdKey) else { return [] }
        return (try? JSONDecoder().decode([OccasionCountdown].self, from: d)) ?? []
    }
}

extension APIClient {
    /// Every banner in [start, end]; the cache when the Mac is away.
    func occasionBanners(start: Date, end: Date) async -> [OccasionBanner] {
        let s = ISO8601DateFormatter.yyyyMMdd.string(from: start)
        let e = ISO8601DateFormatter.yyyyMMdd.string(from: end)
        struct R: Codable { let banners: [OccasionBanner] }
        do {
            let r = try JSONDecoder().decode(R.self, from: try await request("/occasions/range?start=\(s)&end=\(e)"))
            OccasionCache.shared.store(r.banners, from: s, to: e)
            return r.banners
        } catch {
            return OccasionCache.shared.between(s, e)
        }
    }

    func occasions() async -> OccasionsPayload? {
        guard let data = try? await request("/occasions"),
              let p = try? JSONDecoder().decode(OccasionsPayload.self, from: data) else { return nil }
        OccasionCache.shared.storeCountdowns(p.countdowns)
        return p
    }

    /// Add (no id) or change an occasion. nil on success, else what to say.
    func saveOccasion(_ o: Occasion) async -> String? {
        do {
            if o.id.isEmpty {
                _ = try await request("/occasions", method: "POST", body: o.body)
            } else {
                _ = try await request("/occasions/\(o.id)", method: "PATCH", body: o.body)
            }
            requestRefresh()
            return nil
        } catch APIError.serverError(let msg) {
            if let d = msg.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
               let e = obj["error"] as? String { return e.prefix(1).uppercased() + e.dropFirst() }
            return msg
        } catch {
            return "Your Mac isn't reachable — try again when it is."
        }
    }

    func deleteOccasion(_ id: String) async -> Bool {
        do {
            _ = try await request("/occasions/\(id)", method: "DELETE")
            requestRefresh()
            return true
        } catch { return false }
    }
}

// MARK: - The editor

struct OccasionEditor: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.dismiss) private var dismiss
    @State var occasion: Occasion
    var onDone: () -> Void = {}
    @State private var date = Date()
    @State private var yearKnown = true
    @State private var hebYear = ""
    @State private var useColor = false
    @State private var pickedColor = Color.pink
    @State private var error: String?

    static let kinds: [(String, String)] = [("birthday", "Birthday"), ("anniversary", "Anniversary"),
                                            ("yahrzeit", "Yahrzeit"), ("countdown", "Countdown"),
                                            ("custom", "Other yearly date")]
    static let hebrewMonths = ["Nisan", "Iyar", "Sivan", "Tammuz", "Av", "Elul", "Tishrei",
                               "Cheshvan", "Kislev", "Tevet", "Shevat", "Adar", "Adar II"]

    var body: some View {
        NavigationView {
            Form {
                Section {
                    Picker("What", selection: $occasion.kind) {
                        ForEach(Self.kinds, id: \.0) { Text($0.1).tag($0.0) }
                    }
                    TextField("Name — Dana, Gil & Dana, Grandpa Moshe …", text: $occasion.title)
                }
                Section {
                    if occasion.kind != "countdown" {
                        Picker("Repeats by", selection: $occasion.calendar) {
                            Text("Regular calendar").tag("gregorian")
                            Text("Hebrew calendar").tag("hebrew")
                        }
                    }
                    if occasion.calendar == "hebrew" && occasion.kind != "countdown" {
                        Stepper("Day \(occasion.day)", value: $occasion.day, in: 1...30)
                        Picker("Month", selection: $occasion.month) {
                            ForEach(1...13, id: \.self) { Text(Self.hebrewMonths[$0 - 1]).tag($0) }
                        }
                        TextField("Hebrew year (optional, e.g. 5750)", text: $hebYear)
                            .keyboardType(.numberPad)
                        if occasion.month == 12 || occasion.month == 13 {
                            Picker("In a leap year", selection: Binding(
                                get: { occasion.adar ?? (occasion.kind == "yahrzeit" ? "adar1" : "adar2") },
                                set: { occasion.adar = $0 })) {
                                Text("Adar I").tag("adar1")
                                Text("Adar II").tag("adar2")
                                Text("Both").tag("both")
                            }
                            HStack(spacing: 6) {
                                Text("Which Adar").font(.caption).foregroundColor(.secondary)
                                InfoTip("In a leap year there are two Adars. Common custom: a yahrzeit in Adar I, a birthday or anniversary in Adar II.")
                            }
                        }
                    } else {
                        DatePicker("Date", selection: $date, displayedComponents: .date)
                        if occasion.kind != "countdown" {
                            Toggle("Year known", isOn: $yearKnown)
                        }
                    }
                } footer: {
                    Text(occasion.kind == "countdown"
                         ? "Shows “N days to …” until the day comes."
                         : "With the year, the banner counts them — “Dana's 30th birthday”.")
                }
                Section {
                    Picker("Reminder", selection: Binding(
                        get: { occasion.remindDays ?? -99 },
                        set: { occasion.remindDays = $0 == -99 ? nil : $0 })) {
                        Text("As in Settings").tag(-99)
                        Text("No reminder").tag(-1)
                        Text("On the day").tag(0)
                        ForEach([1, 2, 3, 7, 14], id: \.self) { Text("\($0) day\($0 == 1 ? "" : "s") before").tag($0) }
                    }
                    Toggle("Own colour", isOn: $useColor)
                    if useColor { ColorPicker("Colour", selection: $pickedColor, supportsOpacity: false) }
                    TextField("Note (optional)", text: $occasion.note)
                }
                if let error {
                    Section { Text(error).foregroundColor(.red) }
                }
                if !occasion.id.isEmpty {
                    Section {
                        Button("Delete", role: .destructive) {
                            Task {
                                if await api.deleteOccasion(occasion.id) { onDone(); dismiss() }
                                else { error = "Couldn't delete — is your Mac reachable?" }
                            }
                        }
                    }
                }
            }
            .navigationTitle(occasion.id.isEmpty ? "Add occasion" : "Edit occasion")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { save() } }
            }
            .onAppear(perform: load)
        }
    }

    private func load() {
        if occasion.calendar == "gregorian", !occasion.id.isEmpty {
            var c = DateComponents()
            c.year = occasion.year ?? 2000; c.month = occasion.month; c.day = occasion.day
            date = Calendar.current.date(from: c) ?? Date()
            yearKnown = occasion.year != nil
        }
        if occasion.calendar == "hebrew", let y = occasion.year { hebYear = String(y) }
        if let hex = occasion.color, let c = Color(hex: hex) { useColor = true; pickedColor = c }
    }

    private func save() {
        var o = occasion
        if o.kind == "countdown" { o.calendar = "gregorian" }
        if o.calendar == "gregorian" {
            let c = Calendar.current.dateComponents([.year, .month, .day], from: date)
            o.month = c.month ?? 1; o.day = c.day ?? 1
            o.year = (o.kind == "countdown" || yearKnown) ? c.year : nil
            o.adar = nil
        } else {
            o.year = Int(hebYear.trimmingCharacters(in: .whitespaces))
        }
        o.color = useColor ? pickedColor.hexString : nil
        Task {
            if let e = await api.saveOccasion(o) { error = e } else { onDone(); dismiss() }
        }
    }
}

// MARK: - Importing birthdays from Contacts

enum ContactOccasions {
    /// Birthdays (and "anniversary" dates) from Contacts, as occasions not
    /// already present. A contact's Hebrew-calendar birthday is kept Hebrew.
    static func fromContacts(existing: [Occasion]) async -> (found: [Occasion], denied: Bool) {
        let store = CNContactStore()
        let granted = (try? await store.requestAccess(for: .contacts)) ?? false
        guard granted else { return ([], true) }
        let keys = [CNContactGivenNameKey, CNContactFamilyNameKey, CNContactBirthdayKey,
                    CNContactNonGregorianBirthdayKey, CNContactDatesKey] as [CNKeyDescriptor]
        var out: [Occasion] = []
        let have = Set(existing.map { "\($0.kind)|\($0.title.lowercased())" })
        let request = CNContactFetchRequest(keysToFetch: keys)
        try? store.enumerateContacts(with: request) { c, _ in
            let name = [c.givenName, c.familyName].filter { !$0.isEmpty }.joined(separator: " ")
            guard !name.isEmpty else { return }
            if let hb = c.nonGregorianBirthday, hb.calendar?.identifier == .hebrew,
               let m = hb.month, let d = hb.day {
                var o = Occasion(kind: "birthday", title: name, calendar: "hebrew",
                                 month: pyluachMonth(appleMonth: m, year: hb.year), day: d)
                o.year = hb.year
                if !have.contains("birthday|\(name.lowercased())") { out.append(o) }
            } else if let b = c.birthday, let m = b.month, let d = b.day {
                var o = Occasion(kind: "birthday", title: name, month: m, day: d)
                o.year = b.year
                if !have.contains("birthday|\(name.lowercased())") { out.append(o) }
            }
            for labeled in c.dates where labeled.label == CNLabelDateAnniversary {
                let v = labeled.value as DateComponents
                if let m = v.month, let d = v.day {
                    var o = Occasion(kind: "anniversary", title: name, month: m, day: d)
                    o.year = v.year
                    if !have.contains("anniversary|\(name.lowercased())") { out.append(o) }
                }
            }
        }
        return (out, false)
    }

    /// Apple's Hebrew months (1 Tishrei … 6 Adar I, 7 Adar/Adar II … 13 Elul)
    /// → pyluach's (1 Nisan … 12 Adar, 13 Adar II), as the Mac stores them.
    static func pyluachMonth(appleMonth m: Int, year: Int?) -> Int {
        switch m {
        case 8...13: return m - 7          // Nisan … Elul
        case 1...5: return m + 6           // Tishrei … Shevat
        case 6: return 12                  // Adar I
        default:                           // 7: Adar, or Adar II in a leap year
            if let y = year, (7 * y + 1) % 19 < 7 { return 13 }
            return 12
        }
    }
}

// MARK: - Settings ▸ Occasions

struct OccasionsSettingsView: View {
    @ObservedObject private var fold = SettingsFold.shared
    @EnvironmentObject var api: APIClient
    @State private var mine: [Occasion] = []
    @State private var cfg: [String: Any] = [:]
    @State private var editing: Occasion?
    @State private var importNote: String?
    @State private var toImport: [Occasion] = []
    @State private var confirmImport = false
    @State private var teachNote: String?

    static let countries: [(String, String)] = [
        ("", "Off"), ("IL", "Israel"), ("US", "United States"), ("GB", "United Kingdom"),
        ("CA", "Canada"), ("AU", "Australia"), ("NZ", "New Zealand"), ("IE", "Ireland"),
        ("ZA", "South Africa"), ("FR", "France"), ("DE", "Germany"), ("NL", "Netherlands"),
        ("BE", "Belgium"), ("CH", "Switzerland"), ("AT", "Austria"), ("IT", "Italy"),
        ("ES", "Spain"), ("PT", "Portugal"), ("SE", "Sweden"), ("NO", "Norway"),
        ("DK", "Denmark"), ("PL", "Poland"), ("RU", "Russia"), ("UA", "Ukraine"),
        ("AR", "Argentina"), ("BR", "Brazil"), ("MX", "Mexico"), ("IN", "India"), ("JP", "Japan")]

    private let styleKinds: [(String, String)] = [
        ("birthday", "Birthdays"), ("anniversary", "Anniversaries"), ("yahrzeit", "Yahrzeits"),
        ("countdown", "Countdowns"), ("custom", "Other dates"), ("jewish", "Jewish extras"),
        ("national", "National"), ("christian", "Christian"), ("islamic", "Islamic")]

    var body: some View {
        List {
            Section {
                ForEach(mine) { o in
                    Button { editing = o } label: {
                        HStack {
                            Text(glyph(o.kind))
                            VStack(alignment: .leading) {
                                Text(o.title).foregroundColor(.primary)
                                Text(summary(o)).font(.caption).foregroundColor(.secondary)
                            }
                        }
                    }
                }
                Button { editing = Occasion() } label: { Label("Add an occasion", systemImage: "plus") }
                Button { Task { await startImport() } } label: {
                    Label("Import birthdays from Contacts", systemImage: "person.crop.circle.badge.plus")
                }
                if let importNote { Text(importNote).font(.caption).foregroundColor(.secondary) }
            } header: { Text("Yours") } footer: {
                Text("All-day banners on the calendar. Tap one here or on the calendar to edit it.")
            }

            Section { if fold.isOpen("occ.Holidays") {
                typeToggle("major", "Festivals")
                typeToggle("minor", "Minor holidays")
                typeToggle("fast", "Fast days")
                typeToggle("modern", "Modern Israeli days")
            } } header: { FoldHeader("occ.Holidays", label: "Jewish holidays shown") } footer: { if fold.isOpen("occ.Holidays") {
                Text("Only what the calendar shows — Shabbat and yom tov are kept free whatever is hidden.")
            } }

            Section { if fold.isOpen("occ.Weekly") {
                flag("parasha", "Parasha", "The weekly Torah portion, on each Shabbat.")
                flag("omer", "Omer count", "Day 1–49 between Pesach and Shavuot.")
                flag("rosh_chodesh", "Rosh Chodesh", "The 30th of a month and the 1st of the next.")
                flag("daf_yomi", "Daf Yomi", "Today's daf in the Babylonian Talmud cycle — a banner every day.")
            } } header: { FoldHeader("occ.Weekly", label: "Jewish weekly extras") }

            Section { if fold.isOpen("occ.Other") {
                Picker("National holidays", selection: Binding(
                    get: { (cfg["country"] as? String ?? "").uppercased() },
                    set: { patch(["country": $0]) })) {
                    ForEach(Self.countries, id: \.0) { Text($0.1).tag($0.0) }
                }
                flag("christian", "Christian holidays", "Easter and the dates that move with it, and the fixed feasts.")
                flag("islamic", "Islamic holidays", "By the Umm al-Qura calendar; marked “expected” — moon sighting can move them a day.")
            } } header: { FoldHeader("occ.Other", label: "Other calendars") }

            Section { if fold.isOpen("occ.Named") {
                byName("jewish", "Jewish days", "Hebrew dates (“12 Adar”), holidays, erev / motzei, Rosh Chodesh, “the first night of Chanukah”, Shabbat.")
                byName("christian", "Christian days", "Easter and the dates that move with it.")
                byName("islamic", "Islamic days", "Eid al-Fitr, Eid al-Adha, Ramadan … (expected dates).")
                byName("mine", "My occasions", "Your own birthdays, anniversaries and yahrzeits — “on Dana's birthday”.")
                Button {
                    Task {
                        let n = (try? await api.vocabAddPresets(["chagim", "hebrew_months"])) ?? -1
                        teachNote = n < 0 ? "Couldn't reach the Mac." : n == 0
                            ? "Already in your vocabulary." : "Added \(n) word\(n == 1 ? "" : "s")."
                    }
                } label: {
                    HStack(spacing: 6) {
                        Text("Add holiday and Hebrew-month names to my vocabulary")
                        InfoTip("So a misheard “Cheshvan” or “Shavuot” is corrected before it is read.")
                    }
                }
                if let teachNote { Text(teachNote).font(.caption).foregroundColor(.secondary) }
            } } header: { FoldHeader("occ.Named", label: "Days you can say by name") } footer: { if fold.isOpen("occ.Named") {
                Text("“Dinner on erev Pesach”, “brunch on Easter” — booked on that day. Switch a family off and its names are just words again.")
            } }

            Section { if fold.isOpen("occ.Colours") {
                ForEach(styleKinds, id: \.0) { k in
                    HStack {
                        ColorPicker(k.1, selection: colourBinding(k.0), supportsOpacity: false)
                    }
                    if ["birthday", "anniversary", "yahrzeit", "countdown", "custom"].contains(k.0) {
                        Picker("  Reminder", selection: remindBinding(k.0)) {
                            Text("No reminder").tag(-1)
                            Text("On the day").tag(0)
                            ForEach([1, 2, 3, 7, 14], id: \.self) { Text("\($0) day\($0 == 1 ? "" : "s") before").tag($0) }
                        }
                        .font(.caption)
                    }
                }
            } } header: { FoldHeader("occ.Colours", label: "Colours and reminders") } footer: { if fold.isOpen("occ.Colours") {
                Text("Reminders arrive in the daily summary (Notifications) on the day chosen — “🎂 Dana's 30th birthday — in 3 days”.")
            } }
        }
        .navigationTitle("Occasions")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .sheet(item: $editing) { o in
            OccasionEditor(occasion: o, onDone: { Task { await load() } })
        }
        .alert("Import \(toImport.count) from Contacts?", isPresented: $confirmImport) {
            Button("Import") { Task { await doImport() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(toImport.prefix(6).map(\.title).joined(separator: ", ")
                 + (toImport.count > 6 ? " …" : ""))
        }
    }

    // MARK: rows

    private func glyph(_ kind: String) -> String {
        ["birthday": "🎂", "anniversary": "💍", "yahrzeit": "🕯", "countdown": "⏳"][kind] ?? "★"
    }

    private func summary(_ o: Occasion) -> String {
        let kind = OccasionEditor.kinds.first { $0.0 == o.kind }?.1 ?? o.kind
        if o.calendar == "hebrew" {
            return "\(kind) · \(o.day) \(OccasionEditor.hebrewMonths[max(0, min(12, o.month - 1))])"
        }
        let f = DateFormatter(); f.dateFormat = o.year != nil ? "d MMM yyyy" : "d MMM"
        var c = DateComponents(); c.year = o.year ?? 2000; c.month = o.month; c.day = o.day
        return "\(kind) · " + (Calendar.current.date(from: c).map { f.string(from: $0) } ?? "")
    }

    private func typeToggle(_ key: String, _ label: String) -> some View {
        Toggle(label, isOn: Binding(
            get: { (cfg["holiday_types"] as? [String] ?? ["major", "minor", "fast", "modern"]).contains(key) },
            set: { on in
                var t = cfg["holiday_types"] as? [String] ?? ["major", "minor", "fast", "modern"]
                t.removeAll { $0 == key }
                if on { t.append(key) }
                patch(["holiday_types": t])
            }))
    }

    private func flag(_ key: String, _ label: String, _ tip: String) -> some View {
        Toggle(isOn: Binding(get: { cfg[key] as? Bool ?? false }, set: { patch([key: $0]) })) {
            HStack(spacing: 6) { Text(label); InfoTip(tip) }
        }
    }

    private func byName(_ key: String, _ label: String, _ tip: String) -> some View {
        Toggle(isOn: Binding(
            get: { (cfg["by_name"] as? [String: Bool])?[key] ?? true },
            set: { v in
                var all = cfg["by_name"] as? [String: Bool]
                    ?? ["jewish": true, "christian": true, "islamic": true, "mine": true]
                all[key] = v
                patch(["by_name": all])
            })) {
            HStack(spacing: 6) { Text(label); InfoTip(tip) }
        }
    }

    private func colourBinding(_ kind: String) -> Binding<Color> {
        Binding(
            get: { Color(hex: (cfg["colors"] as? [String: String])?[kind] ?? "") ?? .pink },
            set: { c in
                var colors = cfg["colors"] as? [String: String] ?? [:]
                colors[kind] = c.hexString
                patch(["colors": colors])
            })
    }

    private func remindBinding(_ kind: String) -> Binding<Int> {
        Binding(
            get: { (cfg["remind_days"] as? [String: Int])?[kind] ?? 1 },
            set: { v in
                var r = cfg["remind_days"] as? [String: Int] ?? [:]
                r[kind] = v
                patch(["remind_days": r])
            })
    }

    // MARK: data

    private func load() async {
        if let p = await api.occasions() { mine = p.occasions.sorted { $0.title < $1.title } }
        if let data = try? await api.request("/config"),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let occ = obj["occasions"] as? [String: Any] { cfg = occ }
    }

    private func patch(_ fields: [String: Any]) {
        for (k, v) in fields { cfg[k] = v }
        Task {
            if await api.patchShared(["occasions": fields]) { api.requestRefresh() }
        }
    }

    private func startImport() async {
        let (found, denied) = await ContactOccasions.fromContacts(existing: mine)
        if denied { importNote = "Contacts access is off — allow it in iOS Settings ▸ MACalendar."; return }
        if found.isEmpty { importNote = "No new birthdays or anniversaries in Contacts."; return }
        toImport = found
        confirmImport = true
    }

    private func doImport() async {
        var added = 0
        for o in toImport where await api.saveOccasion(o) == nil { added += 1 }
        importNote = "Imported \(added) of \(toImport.count)."
        toImport = []
        await load()
    }
}
