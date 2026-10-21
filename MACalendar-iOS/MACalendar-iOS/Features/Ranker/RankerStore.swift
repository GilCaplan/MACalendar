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
///
/// HISTORY (Gil, 2026-10-12: "make it easy to archive, delete history"): a
/// search is filed in `history` when it is finished — New search, or a
/// different table — with its table, numbers and ranking, under an id this
/// phone mints, and sent whole to the Mac (`PUT /ranker/history/<id>`). Mac
/// entries are pulled in on `sync`; an id deleted on either side is dropped
/// on both (`deleted`), never sent back. Reopening an entry and moving on
/// updates it rather than filing a copy (`fromHistory`).
@MainActor
final class RankerStore: ObservableObject {
    static let shared = RankerStore()

    @Published private(set) var presets: [RankerRecipe] = [RankerStore.blank]
    @Published private(set) var preset: String = RankerStore.blank.name
    @Published private(set) var numbers: [Int] = []
    @Published private(set) var useNumbers = true
    @Published private(set) var table: RankerTable?
    @Published private(set) var tableName: String?
    /// Past searches, newest first.
    @Published private(set) var history: [RankerHistoryEntry] = []
    /// Ids deleted (here or on the Mac), so neither sends one back.
    private var deletedHistory: [String] = []
    /// The past search on screen, when it was reopened from history.
    private(set) var fromHistory: String?
    /// When the table was chosen or cleared (seconds since 1970) — the sync's tiebreak.
    private(set) var tableAt: Double = 0

    /// `store.BLANK_RECIPE`: nothing to rank by yet, the table's own order.
    static let blank = RankerRecipe(name: "My ranking")

    /// This person's `ranker/` folder, not the shared top of Documents.
    private var url: URL { LocalStore.shared.featureFolder("ranker").appendingPathComponent("state.json") }

    private init() {
        load()
        NotificationCenter.default.addObserver(forName: .localStoreUserChanged, object: nil, queue: .main) { _ in
            Task { @MainActor in RankerStore.shared.reloadForUser() }
        }
    }

    /// A different person: their saved recipes, or the blank one.
    func reloadForUser() {
        presets = [Self.blank]
        preset = Self.blank.name
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
        history = (o["history"] as? [Any] ?? []).compactMap(RankerHistoryEntry.init(json:))
        deletedHistory = o["deleted_history"] as? [String] ?? []
        fromHistory = o["from_history"] as? String
    }

    private func save() {
        var o: [String: Any] = ["presets": presets.map(\.json), "preset": preset,
                                "numbers": numbers, "use_numbers": useNumbers, "table_at": tableAt]
        if let table { o["table"] = table.json }
        if let tableName { o["filename"] = tableName }
        o["history"] = history.map(\.json)
        o["deleted_history"] = deletedHistory
        if let fromHistory { o["from_history"] = fromHistory }
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
        if let old = table, tableName != file.filename
            || !(old.json as NSDictionary).isEqual(to: t.json) {
            fileCurrent(api: api)                         // a different table: keep the old search
        }
        table = t
        tableName = file.filename
        fromHistory = nil
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

    /// Start over: no table, no numbers; the search goes to history, saved
    /// rankings stay.
    func newSearch(api: APIClient) {
        fileCurrent(api: api)
        fromHistory = nil
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

    // MARK: - History

    /// File the search on screen (nothing without a table). A search reopened
    /// from history updates its own entry and moves it to the top.
    private func fileCurrent(api: APIClient) {
        guard let table, !table.rows.isEmpty else { return }
        var e: RankerHistoryEntry
        if let fid = fromHistory, let i = history.firstIndex(where: { $0.id == fid }) {
            e = history.remove(at: i)
        } else {
            e = RankerHistoryEntry(id: UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
                                   name: tableName ?? "table")
        }
        e.filename = tableName ?? "table"
        e.table = table
        e.rowCount = table.rows.count
        e.numbers = numbers
        e.useNumbers = useNumbers
        e.preset = preset
        e.savedAt = Date().timeIntervalSince1970
        history.insert(e, at: 0)
        save()
        supersede("/ranker/history/\(e.id)")
        let entry = e
        Task { try? await api.putRankerHistory(entry) }
    }

    /// Make a past search the one on screen; the current one is filed first.
    /// nil when done, or why not (its rows are on the Mac and it is away).
    func open(_ id: String, api: APIClient) async -> String? {
        guard var e = history.first(where: { $0.id == id }) else { return "That search is no longer kept." }
        if e.table == nil {
            guard let full = try? await api.rankerHistoryEntry(id), full.table != nil else {
                return "This search's table is on your Mac — open it again when the Mac is reachable."
            }
            e.table = full.table
            e.rowCount = full.rowCount
            if let i = history.firstIndex(where: { $0.id == id }) { history[i].table = full.table }
        }
        if fromHistory != id { fileCurrent(api: api) }
        table = e.table
        tableName = e.filename
        if presets.contains(where: { $0.name == e.preset }) { preset = e.preset }
        fromHistory = id
        tableAt = Date().timeIntervalSince1970
        setNumbers(e.numbers, useNumbers: e.useNumbers, api: api)      // saves
        supersede("/ranker/table")
        let (t, name, at) = (table, tableName, tableAt)
        Task { try? await api.setRankerTable(t, filename: name, at: at, fromHistory: id) }
        return nil
    }

    func setArchived(_ id: String, _ on: Bool, api: APIClient) {
        guard let i = history.firstIndex(where: { $0.id == id }) else { return }
        history[i].archived = on
        save()
        supersede("/ranker/history/\(id)", method: "PATCH")
        Task { try? await api.setRankerHistoryArchived(id, on) }
    }

    /// Forget a past search here and on the Mac, for good.
    func deleteHistory(_ id: String, api: APIClient) {
        history.removeAll { $0.id == id }
        deletedHistory = Array((deletedHistory.filter { $0 != id } + [id]).suffix(500))
        if fromHistory == id { fromHistory = nil }
        save()
        supersede("/ranker/history/\(id)")
        supersede("/ranker/history/\(id)", method: "PATCH")
        Task { try? await api.deleteRankerHistory(id) }
    }

    /// Past searches the Mac has that this phone does not are pulled in whole;
    /// ones deleted on the Mac go; archive state follows the Mac unless a
    /// change made here is still on its way.
    private func syncHistory(api: APIClient) async {
        guard let h = try? await api.rankerHistory() else { return }
        let gone = Set(h.deleted)
        history.removeAll { gone.contains($0.id) }
        deletedHistory = Array(Set(deletedHistory).union(gone)).suffix(500).map { $0 }
        let mine = Set(deletedHistory)
        for s in h.entries where !mine.contains(s.id) {
            if let i = history.firstIndex(where: { $0.id == s.id }) {
                if !pending("/ranker/history/\(s.id)") {
                    history[i].archived = s.archived
                    history[i].name = s.name
                }
            } else if let full = try? await api.rankerHistoryEntry(s.id) {
                history.append(full)
            }
        }
        history.sort { $0.savedAt > $1.savedAt }
        save()
    }

    // MARK: - Sync

    /// Bring this phone in step with the Mac, when it answers. Never needed
    /// for ranking; quiet when the Mac is away.
    func sync(api: APIClient) async {
        guard let o = try? await api.rankerOverview() else { return }
        await syncHistory(api: api)
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
    private func supersede(_ path: String, method: String = "PUT") {
        for change in LocalStore.shared.allPending() where change.method == method && change.path == path {
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
