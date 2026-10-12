import Foundation

// MARK: - Ranker's shapes
//
// A recipe is `rank.py`'s: key, derived, filters, criteria, show (the columns
// a ranking shows; empty means every one). A result is what `RankerMath.rank`
// makes on this phone — the same shape `POST /ranker/rank` answers with on the
// Mac. The overview is `GET /ranker`, which the phone syncs with
// (`RankerStore`).
// Read with JSONSerialization rather than Codable because a table's cells are
// numbers OR words, and a condition's value is either — the same column can
// hold `3.62B` read as a number and `—` kept as text.

/// A column: its stable NAME (what a recipe refers to) and the LABEL the
/// header shows (`Burned24h` / its emoji-and-text header).
struct RankerColumn: Identifiable, Hashable {
    var name: String
    var label: String
    var id: String { name }

    init(name: String, label: String) { self.name = name; self.label = label }

    init?(json: Any) {
        guard let o = json as? [String: Any], let name = o["name"] as? String else { return nil }
        self.init(name: name, label: o["label"] as? String ?? name)
    }
}

/// What makes a row better: a column, which direction, how much it counts.
struct RankerCriterion: Identifiable, Hashable {
    let id = UUID()
    var column: String
    var better: String = "higher"
    var weight: Double = 1

    var json: [String: Any] { ["column": column, "better": better, "weight": weight] }
}

/// A condition a row must meet to be ranked at all (`Scrolls <= 1`).
struct RankerCondition: Identifiable, Hashable {
    let id = UUID()
    var column: String
    var op: String = "<="
    var value: String = ""

    static let ops = ["<", "<=", ">", ">=", "=", "!="]

    /// A number goes as a number, anything else as the words typed.
    var json: [String: Any] {
        let v = value.trimmingCharacters(in: .whitespaces)
        if let n = Double(v) { return ["column": column, "op": op, "value": n] }
        return ["column": column, "op": op, "value": v]
    }
}

/// A new column made by adding others up (Strong = the six star/blessed columns).
/// The phone keeps these as they came; editing them is the Mac panel's job.
struct RankerDerived: Hashable {
    var name: String
    var label: String
    var sum: [String]

    var json: [String: Any] { ["name": name, "label": label, "sum": sum] }
}

struct RankerRecipe: Identifiable, Hashable {
    var name: String
    var key: String?
    var derived: [RankerDerived] = []
    var filters: [RankerCondition] = []
    var criteria: [RankerCriterion] = []
    var show: [String] = []
    var id: String { name }

    init(name: String) { self.name = name }

    init?(json: Any) {
        guard let o = json as? [String: Any] else { return nil }
        name = o["name"] as? String ?? "Recipe"
        key = o["key"] as? String
        derived = (o["derived"] as? [[String: Any]] ?? []).compactMap { d in
            guard let n = d["name"] as? String else { return nil }
            return RankerDerived(name: n, label: d["label"] as? String ?? n,
                                 sum: d["sum"] as? [String] ?? [])
        }
        filters = (o["filters"] as? [[String: Any]] ?? []).compactMap { f in
            guard let c = f["column"] as? String else { return nil }
            return RankerCondition(column: c, op: f["op"] as? String ?? "=",
                                   value: RankerCell(json: f["value"]).plain)
        }
        criteria = (o["criteria"] as? [[String: Any]] ?? []).compactMap { c in
            guard let col = c["column"] as? String else { return nil }
            return RankerCriterion(column: col, better: c["better"] as? String ?? "higher",
                                   weight: (c["weight"] as? NSNumber)?.doubleValue ?? 1)
        }
        show = o["show"] as? [String] ?? []
    }

    var json: [String: Any] {
        var o: [String: Any] = ["name": name,
                                "derived": derived.map(\.json),
                                "filters": filters.map(\.json),
                                "criteria": criteria.map(\.json)]
        if let key { o["key"] = key }
        if !show.isEmpty { o["show"] = show }
        return o
    }

    var jsonString: String {
        guard let data = try? JSONSerialization.data(withJSONObject: json) else { return "{}" }
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    /// The recipe's content, stable across reads (criteria carry fresh ids
    /// each time, so `==` cannot say "unchanged since it was saved").
    var signature: String {
        guard let data = try? JSONSerialization.data(withJSONObject: json, options: .sortedKeys) else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }
}

/// One table cell: a number (shown compactly, 3.62B) or the text it held.
enum RankerCell: Hashable {
    case number(Double)
    case text(String)

    init(json: Any?) {
        if let n = json as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() {
            self = .number(n.doubleValue)
        } else if let s = json as? String {
            self = .text(s)
        } else {
            self = .text("")
        }
    }

    var number: Double? { if case .number(let v) = self { return v }; return nil }

    /// As a person would type it back: 261, 0.5, or the words.
    var plain: String {
        switch self {
        case .text(let s): return s
        case .number(let v): return Self.trim(v, places: 4)
        }
    }

    /// 3.62B, 850M, 1.2K, 12, 0.35.
    var compact: String {
        switch self {
        case .text(let s): return s.isEmpty ? "—" : s
        case .number(let v): return Self.compact(v)
        }
    }

    static func compact(_ v: Double) -> String {
        let a = abs(v)
        for (size, suffix) in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")] where a >= size {
            return trim(v / size, places: a / size >= 100 ? 0 : (a / size >= 10 ? 1 : 2)) + suffix
        }
        return trim(v, places: 2)
    }

    static func trim(_ v: Double, places: Int) -> String {
        if v == v.rounded(), abs(v) < 1e15 { return String(Int(v)) }
        var s = String(format: "%.\(places)f", v)
        while s.contains("."), s.hasSuffix("0") { s.removeLast() }
        if s.hasSuffix(".") { s.removeLast() }
        return s
    }
}

/// One ranked row: where it came, its score, every cell, and each
/// criterion's percentile (`_parts`) — the answer to "why is this one first".
struct RankedRow: Identifiable {
    let rank: Int
    let score: Double
    let cells: [String: RankerCell]
    let parts: [String: Double]
    var id: Int { rank }

    init(rank: Int, score: Double, cells: [String: RankerCell], parts: [String: Double]) {
        self.rank = rank
        self.score = score
        self.cells = cells
        self.parts = parts
    }

    init(json: [String: Any]) {
        rank = (json["_rank"] as? NSNumber)?.intValue ?? 0
        score = (json["_score"] as? NSNumber)?.doubleValue ?? 0
        var c: [String: RankerCell] = [:]
        for (k, v) in json where !k.hasPrefix("_") { c[k] = RankerCell(json: v) }
        cells = c
        var p: [String: Double] = [:]
        for (k, v) in json["_parts"] as? [String: Any] ?? [:] {
            p[k] = (v as? NSNumber)?.doubleValue ?? 0
        }
        parts = p
    }
}

/// A ranking: `RankerMath.rank` on this phone, `POST /ranker/rank` on the Mac.
struct RankerResult {
    var columns: [RankerColumn]
    var rows: [RankedRow]
    var kept: Int
    var total: Int
    var missing: [String]
    /// The column the picture's numbers matched — the Mac picks it from the data.
    var key: String
    /// Sentences about recipe parts left out because this table lacks their columns.
    var notes: [String]
    var numbers: [Int]
    /// Whether `numbers` narrowed this ranking (the Mac's filter switch).
    var useNumbers: Bool
    var tableColumns: [RankerColumn]
    var recipe: RankerRecipe?

    init(columns: [RankerColumn], rows: [RankedRow], kept: Int, total: Int, missing: [String],
         key: String, notes: [String], numbers: [Int], useNumbers: Bool,
         tableColumns: [RankerColumn], recipe: RankerRecipe?) {
        self.columns = columns
        self.rows = rows
        self.kept = kept
        self.total = total
        self.missing = missing
        self.key = key
        self.notes = notes
        self.numbers = numbers
        self.useNumbers = useNumbers
        self.tableColumns = tableColumns
        self.recipe = recipe
    }

    init(json o: [String: Any]) {
        columns = (o["columns"] as? [Any] ?? []).compactMap(RankerColumn.init(json:))
        rows = (o["rows"] as? [[String: Any]] ?? []).map(RankedRow.init(json:))
        kept = (o["kept"] as? NSNumber)?.intValue ?? rows.count
        total = (o["total"] as? NSNumber)?.intValue ?? rows.count
        missing = (o["missing"] as? [Any] ?? []).map { RankerCell(json: $0).plain }
        key = o["key"] as? String ?? ""
        notes = (o["notes"] as? [Any] ?? []).compactMap { $0 as? String }
        numbers = RankerOverview.ints(o["numbers"])
        useNumbers = o["use_numbers"] as? Bool ?? true
        tableColumns = (o["table_columns"] as? [Any] ?? []).compactMap(RankerColumn.init(json:))
        recipe = o["recipe"].flatMap(RankerRecipe.init(json:))
    }
}

/// `GET /ranker` (and what a preset save or delete answers with).
struct RankerOverview {
    var presets: [RankerRecipe]
    var preset: String
    var numbers: [Int]
    /// The filter switch, kept on the Mac: off ranks every row but keeps
    /// `numbers`, so switching it back on restores them.
    var useNumbers: Bool
    /// How the Mac reads pictures: "vision", "tesseract", or "none".
    var engine: String
    var tableName: String?
    var tableRows: Int
    var tableColumns: [RankerColumn]
    /// When the Mac's table was set or cleared — whose table is newer.
    var tableAt: Double

    var hasTable: Bool { !tableColumns.isEmpty }

    init(json o: [String: Any]) {
        presets = (o["presets"] as? [Any] ?? []).compactMap(RankerRecipe.init(json:))
        preset = o["preset"] as? String ?? presets.first?.name ?? ""
        numbers = Self.ints(o["numbers"])
        useNumbers = o["use_numbers"] as? Bool ?? true
        engine = o["engine"] as? String ?? "vision"
        let t = o["table"] as? [String: Any]
        tableName = t?["filename"] as? String
        tableRows = (t?["rows"] as? NSNumber)?.intValue ?? 0
        tableColumns = (t?["columns"] as? [Any] ?? []).compactMap(RankerColumn.init(json:))
        tableAt = (o["table_at"] as? NSNumber)?.doubleValue ?? 0
    }

    static func ints(_ any: Any?) -> [Int] {
        (any as? [Any] ?? []).compactMap { v in
            if let n = v as? NSNumber { return n.intValue }
            if let s = v as? String { return Int(s.trimmingCharacters(in: CharacterSet(charactersIn: "# "))) }
            return nil
        }
    }
}

/// A file picked on the phone: a table or a picture.
struct RankerUpload: Identifiable {
    let id = UUID()
    var filename: String
    var data: Data
    var mime: String
}

/// One past search (`store.py` HISTORY): its table, numbers, the filter switch
/// and the ranking it used. The Mac's list (`GET /ranker/history`) sends no
/// rows — `table` is nil until the whole entry is fetched — so `rowCount`
/// carries the size either way.
struct RankerHistoryEntry: Identifiable {
    var id: String
    var name: String
    var filename: String
    var table: RankerTable?
    var rowCount: Int
    var numbers: [Int]
    var useNumbers: Bool
    var preset: String
    var savedAt: Double
    var archived: Bool

    init(id: String, name: String) {
        self.id = id
        self.name = name
        filename = name
        rowCount = 0
        numbers = []
        useNumbers = true
        preset = ""
        savedAt = Date().timeIntervalSince1970
        archived = false
    }

    init?(json: Any?) {
        guard let o = json as? [String: Any], let id = o["id"] as? String else { return nil }
        self.id = id
        filename = o["filename"] as? String ?? "table"
        name = o["name"] as? String ?? filename
        table = RankerTable(json: o["table"])
        rowCount = table?.rows.count ?? (o["rows"] as? NSNumber)?.intValue ?? 0
        numbers = RankerOverview.ints(o["numbers"])
        useNumbers = o["use_numbers"] as? Bool ?? true
        preset = o["preset"] as? String ?? ""
        savedAt = (o["saved_at"] as? NSNumber)?.doubleValue ?? 0
        archived = o["archived"] as? Bool ?? false
    }

    /// Whole, with its table — what this phone saves and sends.
    var json: [String: Any] {
        var o: [String: Any] = ["id": id, "name": name, "filename": filename, "numbers": numbers,
                                "use_numbers": useNumbers, "preset": preset, "saved_at": savedAt,
                                "archived": archived, "rows": rowCount]
        if let table { o["table"] = table.json }
        return o
    }

    /// "40 rows · 12 numbers · 12 Oct 10:43".
    var subtitle: String {
        var bits = ["\(rowCount) rows"]
        if !numbers.isEmpty { bits.append("\(numbers.count) numbers") }
        if !preset.isEmpty { bits.append(preset) }
        let f = DateFormatter()
        f.dateFormat = "d MMM HH:mm"
        bits.append(f.string(from: Date(timeIntervalSince1970: savedAt)))
        return bits.joined(separator: " · ")
    }
}
