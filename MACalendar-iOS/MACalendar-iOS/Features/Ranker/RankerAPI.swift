import Foundation

// MARK: - Ranker's calls
//
// The routes are `assistant/features/ranker/routes.py` (documented at its
// top). An extension, like Flashcards' and Jude's, so the offline breaker, the
// key and the address are the shared ones.
//
// None of these is needed to RANK: the phone reads tables, reads pictures and
// ranks by itself (`RankerEngine.swift`; Gil, 2026-10-12: "Ranking shouldnt be
// dependent on the os server… just sync"). They keep the recipes, the number
// list and the last table the same on the phone and the Mac, so every write
// is a plain overwrite through `mutate` — with the Mac away it queues and
// lands when it is back. A table carries when it was chosen (`table_at`), and
// the Mac ignores one older than the table it has, so a replay that arrives
// after a newer table was picked on either device changes nothing.
extension APIClient {

    // -- reads ----------------------------------------------------------

    func rankerOverview() async throws -> RankerOverview {
        RankerOverview(json: try Self.rankerObject(try await request("/ranker")))
    }

    /// The Mac's last table, every row; nil when it has none.
    func rankerTable() async throws -> (table: RankerTable?, filename: String?, at: Double) {
        let o = try Self.rankerObject(try await request("/ranker/table"))
        let t = o["table"] as? [String: Any]
        return (RankerTable(json: t), t?["filename"] as? String,
                (o["table_at"] as? NSNumber)?.doubleValue ?? 0)
    }

    // -- plain overwrites (queued offline) ----------------------------

    /// The list as edited, and the filter switch. False when queued. (Off
    /// ranks every row but KEEPS the list; `[]` erases it.)
    @discardableResult
    func setRankerNumbers(_ numbers: [Int], useNumbers: Bool) async throws -> Bool {
        try await mutate("/ranker/numbers", method: "PUT",
                         body: ["numbers": numbers, "use_numbers": useNumbers]) != nil
    }

    /// The table this phone read (nil: a new search), stamped with when.
    @discardableResult
    func setRankerTable(_ table: RankerTable?, filename: String?, at: Double) async throws -> Bool {
        var t: Any = NSNull()
        if let table {
            var o = table.json
            o["filename"] = filename ?? "table"
            t = o
        }
        return try await mutate("/ranker/table", method: "PUT", body: ["table": t, "table_at": at]) != nil
    }

    /// Save a recipe under its name. nil when the Mac was away and it queued.
    @discardableResult
    func saveRankerPreset(_ recipe: RankerRecipe) async throws -> RankerOverview? {
        guard let data = try await mutate("/ranker/presets/\(Self.rankerSegment(recipe.name))",
                                          method: "PUT", body: recipe.json) else { return nil }
        return RankerOverview(json: try Self.rankerObject(data))
    }

    @discardableResult
    func deleteRankerPreset(_ name: String) async throws -> RankerOverview? {
        guard let data = try await mutate("/ranker/presets/\(Self.rankerSegment(name))",
                                          method: "DELETE") else { return nil }
        return RankerOverview(json: try Self.rankerObject(data))
    }

    private static func rankerObject(_ data: Data) throws -> [String: Any] {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw APIError.serverError("{\"error\": \"Your Mac answered with something this app could not read.\"}")
        }
        return obj
    }

    /// A recipe name as one path segment ("Migration — active, populous…").
    private static func rankerSegment(_ name: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return name.addingPercentEncoding(withAllowedCharacters: allowed) ?? name
    }
}
