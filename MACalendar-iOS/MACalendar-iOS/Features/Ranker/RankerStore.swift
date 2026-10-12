import Foundation

/// Ranker's state on the phone — the recipes, the number list, the filter
/// switch and the last table — kept in `Documents/ranker/state.json`, so the
/// tab ranks on a train exactly as it does at home (Gil, 2026-10-12:
/// "Ranking shouldnt be dependent on the os server… just sync otherwise
/// should work on phone").
///
/// Every change is made HERE first and then sent to the Mac with `mutate`
/// (queued while it is away), so the Mac panel shows the same thing. A newer
/// queued overwrite replaces an older one still waiting — the list as it is
/// now is the only one worth sending.
///
/// Coming back from the Mac (`sync`): with none of this tab's writes still
/// queued, the Mac's recipes, list and switch are taken — they are what was
/// last chosen, here or there. The TABLE goes by its stamp (`table_at`, when it
/// was chosen or cleared): whichever device chose later wins, so a table read
/// on the Mac shows up here and one read here is not undone by an older one.
@MainActor
final class RankerStore: ObservableObject {
    static let shared = RankerStore()

    @Published private(set) var presets: [RankerRecipe] = [RankerStore.blank]
    @Published private(set) var preset: String = RankerStore.blank.name
    @Published private(set) var numbers: [Int] = []
    @Published private(set) var useNumbers = true
    @Published private(set) var table: RankerTable?
    @Published private(set) var tableName: String?
    /// When the table was chosen or cleared (seconds since 1970) — the sync's tiebreak.
    private(set) var tableAt: Double = 0

    /// `store.BLANK_RECIPE`: nothing to rank by yet, the table's own order.
    static let blank = RankerRecipe(name: "My ranking")

    private let url: URL

    private init() {
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("ranker", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        url = dir.appendingPathComponent("state.json")
        load()
    }

    var current: RankerRecipe {
        presets.first { $0.name == preset } ?? presets.first ?? Self.blank
    }

    // MARK: - Disk

    private func load() {
        guard let data = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        let saved = (o["presets"] as? [Any] ?? []).compactMap(RankerRecipe.init(json:))
        if !saved.isEmpty { presets = saved }
        preset = o["preset"] as? String ?? presets[0].name
        numbers = RankerOverview.ints(o["numbers"])
        useNumbers = o["use_numbers"] as? Bool ?? true
        table = RankerTable(json: o["table"])
        tableName = o["filename"] as? String
        tableAt = (o["table_at"] as? NSNumber)?.doubleValue ?? 0
    }

    private func save() {
        var o: [String: Any] = ["presets": presets.map(\.json), "preset": preset,
                                "numbers": numbers, "use_numbers": useNumbers, "table_at": tableAt]
        if let table { o["table"] = table.json }
        if let tableName { o["filename"] = tableName }
        if let data = try? JSONSerialization.data(withJSONObject: o) {
            try? data.write(to: url, options: .atomic)
        }
    }

    // MARK: - Ranking (no Mac involved)

    /// Rank the table by `recipe` (the current one when nil), narrowed to the
    /// numbers while the switch is on. nil when there is no table yet.
    func rank(_ recipe: RankerRecipe? = nil) throws -> RankerResult? {
        guard let table else { return nil }
        var r = try RankerMath.rank(table, recipe: recipe ?? current, numbers: useNumbers ? numbers : [])
        r.numbers = numbers
        r.useNumbers = useNumbers
        return r
    }

    /// Read a table file here. Off the main thread: an export can be megabytes.
    func readTable(_ file: RankerUpload, api: APIClient) async throws {
        let t = try await Task.detached(priority: .userInitiated) {
            try RankerTableReader.read(filename: file.filename, data: file.data)
        }.value
        table = t
        tableName = file.filename
        tableAt = Date().timeIntervalSince1970
        save()
        supersede("/ranker/table")
        try? await api.setRankerTable(t, filename: file.filename, at: tableAt)
    }

    /// The numbers in the pictures, read here by Apple Vision; they REPLACE the list.
    func readNumbers(_ images: [RankerUpload], api: APIClient) async throws -> [Int] {
        let found = try await RankerVision.numbers(in: images.map(\.data))
        setNumbers(found, useNumbers: true, api: api)
        return found
    }

    // MARK: - Edits, sent on to the Mac

    func setNumbers(_ list: [Int], useNumbers on: Bool, api: APIClient) {
        var seen = Set<Int>()
        numbers = list.filter { seen.insert($0).inserted }
        useNumbers = on
        save()
        supersede("/ranker/numbers")
        let (n, u) = (numbers, useNumbers)
        Task { try? await api.setRankerNumbers(n, useNumbers: u) }
    }

    /// Start over: no table, no numbers; saved rankings stay.
    func newSearch(api: APIClient) {
        table = nil
        tableName = nil
        tableAt = Date().timeIntervalSince1970
        setNumbers([], useNumbers: true, api: api)        // saves
        supersede("/ranker/table")
        let at = tableAt
        Task { try? await api.setRankerTable(nil, filename: nil, at: at) }
    }

    func choose(_ name: String) {
        guard presets.contains(where: { $0.name == name }) else { return }
        preset = name
        save()
    }

    /// Keep a recipe under its name (replacing one of that name). nil when
    /// done — queued counts — or the sentence the Mac refused it with.
    func savePreset(_ recipe: RankerRecipe, api: APIClient) async -> String? {
        let before = (presets, preset)
        presets.removeAll { $0.name == recipe.name }
        presets.append(recipe)
        preset = recipe.name
        save()
        do {
            if let o = try await api.saveRankerPreset(recipe) { adopt(o, numbersToo: false) }
            return nil
        } catch {
            presets = before.0
            preset = before.1
            save()
            return Self.sentence(error)
        }
    }

    func deletePreset(_ name: String, api: APIClient) async -> String? {
        guard presets.count > 1 else { return "Keep at least one ranking — edit this one instead." }
        let before = (presets, preset)
        presets.removeAll { $0.name == name }
        if preset == name { preset = presets[0].name }
        save()
        do {
            if let o = try await api.deleteRankerPreset(name) { adopt(o, numbersToo: false) }
            return nil
        } catch {
            presets = before.0
            preset = before.1
            save()
            return Self.sentence(error)
        }
    }

    // MARK: - Sync

    /// Bring this phone in step with the Mac, when it answers. Never needed
    /// for ranking; quiet when the Mac is away.
    func sync(api: APIClient) async {
        guard let o = try? await api.rankerOverview() else { return }
        if !pending("/ranker/numbers") && !pending("/ranker/presets") {
            adopt(o, numbersToo: true)
        }
        // A Mac that predates the stamp says 0; its table still counts when
        // this phone has never had one.
        let macNewer = o.tableAt > tableAt || (tableAt == 0 && table == nil && o.hasTable)
        guard macNewer, !pending("/ranker/table") else { return }
        if o.hasTable {
            guard let t = try? await api.rankerTable(), let got = t.table else { return }
            table = got
            tableName = t.filename
            tableAt = max(t.at, o.tableAt)
        } else {
            table = nil
            tableName = nil
            tableAt = o.tableAt
        }
        save()
    }

    private func adopt(_ o: RankerOverview, numbersToo: Bool) {
        if !o.presets.isEmpty {
            presets = o.presets
            preset = o.presets.contains { $0.name == o.preset } ? o.preset : o.presets[0].name
        }
        if numbersToo {
            numbers = o.numbers
            useNumbers = o.useNumbers
        }
        save()
    }

    private func pending(_ prefix: String) -> Bool {
        LocalStore.shared.allPending().contains { $0.path.hasPrefix(prefix) }
    }

    /// Drop a queued overwrite of `path` that a newer one is about to replace.
    private func supersede(_ path: String) {
        for change in LocalStore.shared.allPending() where change.method == "PUT" && change.path == path {
            LocalStore.shared.removePending(change.id)
        }
    }

    static func sentence(_ error: Error) -> String {
        if let e = error as? APIError, case .serverError = e {
            return e.serverSentence ?? "Your Mac answered with something this app could not read."
        }
        return error.localizedDescription
    }
}
