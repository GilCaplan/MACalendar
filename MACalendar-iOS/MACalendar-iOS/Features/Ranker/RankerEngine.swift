import Foundation
import UIKit
import Vision

// MARK: - Ranker, on the phone
//
// Gil, 2026-10-12: "Ranking shouldnt be dependent on the os server… just
// sync otherwise should work on phone". So the phone does all three of the
// Mac's jobs itself, each a port of the Python that does it there:
//
//   RankerTableReader   `assistant/features/ranker/table.py`  an .html page's
//                       first table, or CSV / TSV / JSON
//   RankerMath          `rank.py`  fit, best_key, percentiles, rank
//   RankerVision        `ocr.py` + `vision_numbers.swift`  Apple Vision reads
//                       the screenshot; `numbersIn` is the same strict rule
//
// The Mac is only where the recipes, the number list and the last table are
// kept in step (`RankerStore`). A fix to how a table is read or ranked goes in
// the Python first, then here — `tests/unit/test_ranker_phone.py` pins the
// rules the two must agree on.

/// A table the phone read: columns (stable name, shown label) and rows.
struct RankerTable {
    var columns: [RankerColumn]
    var rows: [[String: RankerCell]]

    var names: [String] { columns.map(\.name) }

    var json: [String: Any] {
        ["columns": columns.map { ["name": $0.name, "label": $0.label] },
         "rows": rows.map { row in row.mapValues { $0.jsonValue } }]
    }

    init(columns: [RankerColumn], rows: [[String: RankerCell]]) {
        self.columns = columns
        self.rows = rows
    }

    /// `{columns, rows}` as the Mac keeps it (`last_table`) and this phone saves it.
    init?(json: Any?) {
        guard let o = json as? [String: Any],
              let cols = o["columns"] as? [Any], let rows = o["rows"] as? [[String: Any]] else { return nil }
        columns = cols.compactMap(RankerColumn.init(json:))
        self.rows = rows.map { $0.mapValues { RankerCell(json: $0) } }
        if columns.isEmpty { return nil }
    }
}

extension RankerCell {
    /// For JSON: a number as a number, words as words.
    var jsonValue: Any {
        switch self {
        case .number(let v): return v
        case .text(let s): return s
        }
    }

    /// `table.number` of the cell: a number cell, or words that read as one.
    var value: Double? {
        switch self {
        case .number(let v): return v
        case .text(let s): return RankerTableReader.number(s)
        }
    }
}

/// A file with no table this can read, or a recipe this table cannot use, said as a sentence.
struct RankerRefusal: LocalizedError {
    let sentence: String
    init(_ sentence: String) { self.sentence = sentence }
    var errorDescription: String? { sentence }
}

// MARK: - Reading a table (table.py)

enum RankerTableReader {

    private static let numberPattern = try! NSRegularExpression(
        pattern: "^([-+]?\\d+(?:\\.\\d+)?)\\s*([kmbt])?%?$", options: [.caseInsensitive])

    /// `3.62B` -> 3.62e9, `1,234` -> 1234, `12%` -> 12; nil for words.
    static func number(_ text: String) -> Double? {
        let s = text.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: ",", with: "")
            .replacingOccurrences(of: " ", with: "")
        let ns = s as NSString
        guard let m = numberPattern.firstMatch(in: s, range: NSRange(location: 0, length: ns.length)),
              let v = Double(ns.substring(with: m.range(at: 1))) else { return nil }
        guard m.range(at: 2).location != NSNotFound else { return v }
        switch ns.substring(with: m.range(at: 2)).lowercased() {
        case "k": return v * 1e3
        case "m": return v * 1e6
        case "b": return v * 1e9
        case "t": return v * 1e12
        default: return v
        }
    }

    /// Pick the reader from the name, then from the content.
    static func read(filename: String, data: Data) throws -> RankerTable {
        var text = String(decoding: data, as: UTF8.self)
        if text.hasPrefix("\u{FEFF}") { text.removeFirst() }
        let low = filename.lowercased()
        let head = String(text.drop(while: { $0.isWhitespace }).prefix(200)).lowercased()
        if low.hasSuffix(".html") || low.hasSuffix(".htm")
            || head.hasPrefix("<!doctype") || head.hasPrefix("<html") || head.hasPrefix("<table") {
            return try fromHTML(text)
        }
        if low.hasSuffix(".json") || head.hasPrefix("[") || head.hasPrefix("{") {
            return try fromJSON(text)
        }
        if low.hasSuffix(".csv") || low.hasSuffix(".tsv") || low.hasSuffix(".txt")
            || text.contains(",") || text.contains("\t") {
            return try fromDelimited(text)
        }
        throw RankerRefusal("\(filename.isEmpty ? "That file" : filename): send an .html, .csv, .tsv or .json table.")
    }

    /// A cell's value: `data-raw` when it agrees with what is shown (the
    /// precise copy of it), else what is shown, as a number when it reads as one.
    static func cellValue(_ text: String, raw: String?) -> RankerCell {
        let shown = number(text)
        let r = raw.flatMap(number)
        if let r, let shown, abs(r - shown) <= max(1.0, abs(shown) * 0.01) { return .number(r) }
        if let shown { return .number(shown) }
        return .text(text)
    }

    static func unique(_ names: [String]) -> [String] {
        var seen: [String: Int] = [:]
        return names.map { raw in
            let n = raw.isEmpty ? "column" : raw
            let k = seen[n, default: 0]
            seen[n] = k + 1
            return k == 0 ? n : "\(n) \(k + 1)"
        }
    }

    // -- HTML

    static func fromHTML(_ text: String) throws -> RankerTable {
        var p = HTMLTableScanner()
        p.feed(text)
        if p.tables == 0 { throw RankerRefusal("That page has no table in it.") }
        if p.rows.isEmpty { throw RankerRefusal("The page's table has no rows.") }
        let width = max(p.header.count, p.rows.map(\.count).max() ?? 0)
        var header = p.header
        for i in header.count..<width { header.append(("column \(i + 1)", "column \(i + 1)")) }
        let names = unique(header.map(\.0))
        let columns = zip(names, header).map { n, h in RankerColumn(name: n, label: h.1.isEmpty ? n : h.1) }
        let rows: [[String: RankerCell]] = p.rows.map { r in
            var out: [String: RankerCell] = [:]
            for (i, cell) in r.enumerated() where i < names.count {
                out[names[i]] = cellValue(cell.text, raw: cell.raw)
            }
            return out
        }
        return RankerTable(columns: columns, rows: rows)
    }

    // -- CSV / TSV

    static func fromDelimited(_ text: String) throws -> RankerTable {
        let delimiter = sniff(String(text.prefix(4096)))
        let records = csvRecords(text, delimiter: delimiter)
            .filter { r in r.contains { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } }
        guard records.count >= 2 else {
            throw RankerRefusal(records.isEmpty ? "That file is empty." : "That file has a header but no rows.")
        }
        let names = unique(records[0].map { $0.trimmingCharacters(in: .whitespacesAndNewlines) })
        let rows: [[String: RankerCell]] = records.dropFirst().map { r in
            var out: [String: RankerCell] = [:]
            for (i, c) in r.enumerated() where i < names.count { out[names[i]] = cellValue(c, raw: nil) }
            return out
        }
        return RankerTable(columns: names.map { RankerColumn(name: $0, label: $0) }, rows: rows)
    }

    /// Python's `csv.Sniffer` among `, \t ; |`, simplified: the delimiter that
    /// appears the same (non-zero) number of times on the most lines; a comma
    /// when none does.
    static func sniff(_ sample: String) -> Character {
        let lines = sample.split(whereSeparator: \.isNewline).prefix(20)
        var best: Character = ",", bestScore = 0
        for d in [",", "\t", ";", "|"] as [Character] {
            var counts: [Int: Int] = [:]
            for line in lines {
                var inQuotes = false, n = 0
                for ch in line {
                    if ch == "\"" { inQuotes.toggle() } else if ch == d && !inQuotes { n += 1 }
                }
                if n > 0 { counts[n, default: 0] += 1 }
            }
            let score = counts.values.max() ?? 0
            if score > bestScore { best = d; bestScore = score }
        }
        return best
    }

    /// RFC 4180 records: quoted fields, `""` for a quote, newlines inside quotes.
    static func csvRecords(_ text: String, delimiter: Character) -> [[String]] {
        var records: [[String]] = []
        var record: [String] = []
        var field = ""
        var inQuotes = false
        var chars = text.makeIterator()
        var pending: Character? = nil
        func next() -> Character? {
            if let p = pending { pending = nil; return p }
            return chars.next()
        }
        while let ch = next() {
            if inQuotes {
                if ch == "\"" {
                    if let after = next() {
                        if after == "\"" { field.append("\"") } else { inQuotes = false; pending = after }
                    } else {
                        inQuotes = false
                    }
                } else {
                    field.append(ch)
                }
            } else if ch == "\"" && field.isEmpty {
                inQuotes = true
            } else if ch == delimiter {
                record.append(field); field = ""
            } else if ch.isNewline {
                // "\r\n" is one Character in Swift, so one record break.
                record.append(field); field = ""
                records.append(record); record = []
            } else {
                field.append(ch)
            }
        }
        if !field.isEmpty || !record.isEmpty {
            record.append(field)
            records.append(record)
        }
        return records
    }

    // -- JSON

    static func fromJSON(_ text: String) throws -> RankerTable {
        guard var data = try? JSONSerialization.jsonObject(with: Data(text.utf8), options: [.fragmentsAllowed]) else {
            throw RankerRefusal("A JSON table is a list of objects, one per row.")
        }
        if let o = data as? [String: Any] {
            for k in ["rows", "data", "records"] {
                if let list = o[k] as? [Any] { data = list; break }
            }
        }
        guard let list = data as? [Any], !list.isEmpty,
              let objects = list as? [[String: Any]], objects.count == list.count else {
            throw RankerRefusal("A JSON table is a list of objects, one per row.")
        }
        // Dictionaries here have no order, and the file's order is the order
        // a person reads the columns in: each key goes where the file first names it.
        var keys: [String] = []
        for o in objects { for k in o.keys where !keys.contains(k) { keys.append(k) } }
        let firstSeen = Dictionary(uniqueKeysWithValues: keys.map { k in (k, keyPosition(k, in: text)) })
        let names = keys.enumerated()
            .sorted { (firstSeen[$0.element]!, $0.offset) < (firstSeen[$1.element]!, $1.offset) }
            .map(\.element)
        let rows: [[String: RankerCell]] = objects.map { o in
            var out: [String: RankerCell] = [:]
            for n in names {
                let v: Any? = o[n]
                if let num = v as? NSNumber {
                    out[n] = .number(num.doubleValue)
                } else if let s = v as? String {
                    out[n] = cellValue(s, raw: nil)
                } else if let other = v, !(other is NSNull) {
                    out[n] = .text("\(other)")
                } else {
                    out[n] = .text("")
                }
            }
            return out
        }
        return RankerTable(columns: names.map { RankerColumn(name: $0, label: $0) }, rows: rows)
    }

    /// Where `"key":` first appears in the file (Int.max when it cannot be found).
    private static func keyPosition(_ key: String, in text: String) -> Int {
        guard let encoded = try? JSONSerialization.data(withJSONObject: [key]),
              var quoted = String(data: encoded, encoding: .utf8) else { return Int.max }
        quoted = String(quoted.dropFirst().dropLast())          // ["key"] -> "key"
        var from = text.startIndex
        while let r = text.range(of: quoted, range: from..<text.endIndex) {
            let rest = text[r.upperBound...].drop(while: { $0.isWhitespace })
            if rest.first == ":" { return text.distance(from: text.startIndex, to: r.lowerBound) }
            from = r.upperBound
        }
        return Int.max
    }
}

/// The first `<table>` of a page, as Python's `HTMLParser` subclass in
/// `table.py` reads it: the header from the first header row with text (a
/// second one of filter boxes is skipped), each cell's text and `data-raw`,
/// a column's name from `data-column`. Bytes, not Characters: every bit of
/// markup is ASCII, and an export can be megabytes.
private struct HTMLTableScanner {
    struct Cell { var tag: String; var text: String; var raw: String?; var col: String? }

    var tables = 0
    var header: [(String, String)] = []
    var rows: [[(text: String, raw: String?)]] = []

    private var depth = 0
    private var row: [Cell]? = nil
    private var cell: Cell? = nil
    private var inHead = false
    private var headerDone = false

    mutating func feed(_ text: String) {
        let b = Array(text.utf8)
        let n = b.count
        var i = 0
        var textStart = 0
        func lower(_ c: UInt8) -> UInt8 { (c >= 65 && c <= 90) ? c + 32 : c }
        func isLetter(_ c: UInt8) -> Bool { (c >= 65 && c <= 90) || (c >= 97 && c <= 122) }
        func isSpace(_ c: UInt8) -> Bool { c == 32 || c == 9 || c == 10 || c == 13 || c == 12 }
        func find(_ needle: [UInt8], from: Int, caseless: Bool = false) -> Int? {
            guard needle.count <= n else { return nil }
            var j = from
            while j + needle.count <= n {
                var k = 0
                while k < needle.count && (caseless ? lower(b[j + k]) : b[j + k]) == needle[k] { k += 1 }
                if k == needle.count { return j }
                j += 1
            }
            return nil
        }
        func string(_ from: Int, _ to: Int) -> String { String(decoding: b[from..<to], as: UTF8.self) }

        while i < n {
            guard b[i] == 60, i + 1 < n else { i += 1; continue }              // "<"
            let next = b[i + 1]
            guard isLetter(next) || next == 47 || next == 33 || next == 63 else { i += 1; continue }
            if i > textStart { data(Self.decodeEntities(string(textStart, i))) }

            if next == 33, i + 3 < n, b[i + 2] == 45, b[i + 3] == 45 {          // <!-- -->
                let end = find(Array("-->".utf8), from: i + 4) ?? n
                i = min(n, end + 3); textStart = i; continue
            }
            if next == 33 || next == 63 {                                       // <!doctype>, <?xml?>
                let end = find([62], from: i) ?? n
                i = min(n, end + 1); textStart = i; continue
            }
            if next == 47 {                                                     // </tag>
                var j = i + 2
                let s = j
                while j < n && (isLetter(b[j]) || (b[j] >= 48 && b[j] <= 57)) { j += 1 }
                let name = string(s, j).lowercased()
                let end = find([62], from: j) ?? n
                if !name.isEmpty { endTag(name) }
                i = min(n, end + 1); textStart = i; continue
            }
            // <tag attr="v" attr='v' attr=v attr>
            var j = i + 1
            let s = j
            while j < n && (isLetter(b[j]) || (b[j] >= 48 && b[j] <= 57) || b[j] == 45) { j += 1 }
            let name = string(s, j).lowercased()
            var attrs: [String: String] = [:]
            while j < n && b[j] != 62 {
                if isSpace(b[j]) || b[j] == 47 { j += 1; continue }
                let ks = j
                while j < n && !isSpace(b[j]) && b[j] != 61 && b[j] != 62 && b[j] != 47 { j += 1 }
                let key = string(ks, j).lowercased()
                while j < n && isSpace(b[j]) { j += 1 }
                var value: String? = nil
                if j < n && b[j] == 61 {                                        // =
                    j += 1
                    while j < n && isSpace(b[j]) { j += 1 }
                    if j < n && (b[j] == 34 || b[j] == 39) {                    // " or '
                        let q = b[j]
                        let vs = j + 1
                        j = vs
                        while j < n && b[j] != q { j += 1 }
                        value = string(vs, min(j, n))
                        j = min(n, j + 1)
                    } else {
                        let vs = j
                        while j < n && !isSpace(b[j]) && b[j] != 62 { j += 1 }
                        value = string(vs, j)
                    }
                }
                if ks == j { j += 1; continue }                                 // never stall
                if !key.isEmpty, attrs[key] == nil {
                    attrs[key] = value.map(Self.decodeEntities) ?? ""
                }
            }
            i = min(n, j + 1)
            startTag(name, attrs)
            if name == "script" || name == "style" {                            // their text is not data
                let close = Array("</\(name)".utf8)
                let end = find(close, from: i, caseless: true) ?? n
                i = end
            }
            textStart = i
        }
        if textStart < n { data(Self.decodeEntities(string(textStart, n))) }
    }

    private mutating func startTag(_ tag: String, _ a: [String: String]) {
        if tag == "table" {
            tables += 1
            if tables == 1 { depth = 1 }
            return
        }
        guard depth == 1 else { return }
        if tag == "thead" {
            inHead = true
        } else if tag == "tr" {
            row = []
        } else if (tag == "td" || tag == "th") && row != nil {
            cell = Cell(tag: tag, text: "", raw: a["data-raw"], col: a["data-column"])
        }
    }

    private mutating func endTag(_ tag: String) {
        if tag == "table" && depth == 1 { depth = 2; return }
        guard depth == 1 else { return }
        if (tag == "td" || tag == "th"), let c = cell, row != nil {
            row?.append(c)
            cell = nil
        } else if tag == "tr", let r = row {
            row = nil
            if r.isEmpty { return }
            let trimmed = r.map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }
            let allTH = r.allSatisfy { $0.tag == "th" }
            if !headerDone && (inHead || allTH) {
                // The first header row names the columns; a second one (the
                // migration export's filter inputs) has no text and is skipped.
                if zip(r, trimmed).contains(where: { !$1.isEmpty || !($0.col ?? "").isEmpty }) {
                    header = zip(r, trimmed).map { c, t -> (String, String) in
                        let col = c.col ?? ""
                        return (col.isEmpty ? t : col, t)
                    }
                    headerDone = true
                }
                return
            }
            if inHead || allTH || !trimmed.contains(where: { !$0.isEmpty }) { return }
            rows.append(zip(r, trimmed).map { (text: $1, raw: $0.raw) })
        } else if tag == "thead" {
            inHead = false
        }
    }

    private mutating func data(_ d: String) {
        if cell != nil { cell?.text += d }
    }

    /// `&amp;` `&lt;` `&#39;` `&#x1F525;` `&nbsp;` …, as `convert_charrefs` does.
    static func decodeEntities(_ s: String) -> String {
        guard s.contains("&") else { return s }
        let named: [String: String] = ["amp": "&", "lt": "<", "gt": ">", "quot": "\"", "apos": "'",
                                       "nbsp": "\u{00A0}", "ndash": "–", "mdash": "—", "hellip": "…"]
        var out = ""
        var i = s.startIndex
        while i < s.endIndex {
            if s[i] == "&", let semi = s[i...].prefix(12).firstIndex(of: ";") {
                let body = String(s[s.index(after: i)..<semi])
                var decoded: String? = named[body]
                if decoded == nil, body.hasPrefix("#") {
                    let digits = body.dropFirst()
                    let code = digits.lowercased().hasPrefix("x")
                        ? UInt32(digits.dropFirst(), radix: 16) : UInt32(digits)
                    decoded = code.flatMap { Unicode.Scalar($0) }.map { String(Character($0)) }
                }
                if let decoded {
                    out += decoded
                    i = s.index(after: semi)
                    continue
                }
            }
            out.append(s[i])
            i = s.index(after: i)
        }
        return out
    }
}

// MARK: - Ranking (rank.py)

enum RankerMath {

    static let ops = RankerCondition.ops

    /// The identifier form a picture's number and a key cell are compared in:
    /// a whole number without ".0", anything else as written without "#".
    static func key(_ cell: RankerCell?) -> String {
        guard let cell else { return "" }
        if let n = cell.value, n == n.rounded(), abs(n) < 1e15 { return String(Int(n)) }
        var s = cell.plain.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasPrefix("#") { s.removeFirst() }
        return s
    }

    /// The recipe, minus whatever names a column this table does not have —
    /// and a sentence for each thing left out (`rank.fit`).
    static func fit(_ table: RankerTable, _ recipe: RankerRecipe) -> (RankerRecipe, [String]) {
        var have = Set(table.names)
        var notes: [String] = []
        var out = recipe
        out.derived = recipe.derived.filter { d in
            let gone = d.sum.filter { !have.contains($0) }
            if gone.isEmpty { return true }
            notes.append("Left out the combined column '\(d.label.isEmpty ? d.name : d.label)': this table has no \(gone.joined(separator: ", ")).")
            return false
        }
        have.formUnion(out.derived.map(\.name))
        out.criteria = recipe.criteria.filter { c in
            if have.contains(c.column) { return true }
            notes.append("Not ranking by '\(c.column)': this table has no such column.")
            return false
        }
        out.filters = recipe.filters.filter { f in
            if have.contains(f.column) { return true }
            notes.append("Ignored the condition on '\(f.column)': this table has no such column.")
            return false
        }
        let kept = have
        out.show = recipe.show.filter { kept.contains($0) }
        if let k = out.key, !k.isEmpty, !table.names.contains(k) { out.key = "" }
        return (out, notes)
    }

    /// The column the picture's numbers belong to: the one whose values match the most of them.
    static func bestKey(_ table: RankerTable, numbers: [Int], preferred: String) -> String {
        let wanted = Set(numbers.map(String.init))
        var best = table.names.contains(preferred) ? preferred : (table.names.first ?? "")
        var score = -1
        for name in table.names {
            let hits = wanted.intersection(table.rows.map { Self.key($0[name]) }).count
            if hits > score || (hits == score && name == preferred) {
                best = name
                score = hits
            }
        }
        return best
    }

    /// Each value's share of the others it beats, ties counted half; 0...1.
    static func percentiles(_ values: [Double]) -> [Double] {
        let n = values.count
        if n == 1 { return [1.0] }
        let order = values.indices.sorted { (values[$0], $0) < (values[$1], $1) }
        var out = [Double](repeating: 0, count: n)
        var i = 0
        while i < n {
            var j = i
            while j + 1 < n && values[order[j + 1]] == values[order[i]] { j += 1 }
            let mid = Double(i + j) / 2 / Double(n - 1)
            for k in i...j { out[order[k]] = mid }
            i = j + 1
        }
        return out
    }

    static func passes(_ row: [String: RankerCell], _ f: RankerCondition) throws -> Bool {
        guard ops.contains(f.op) else {
            throw RankerRefusal("A condition's comparison is one of \(ops.joined(separator: " ")), not '\(f.op)'.")
        }
        let cell = row[f.column] ?? .text("")
        if let v = cell.value, let want = RankerTableReader.number(f.value) {
            switch f.op {
            case "<": return v < want
            case "<=": return v <= want
            case ">": return v > want
            case ">=": return v >= want
            case "=": return v == want
            default: return v != want
            }
        }
        let v = cell.plain.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let want = f.value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        switch f.op {
        case "<": return v < want
        case "<=": return v <= want
        case ">": return v > want
        case ">=": return v >= want
        case "=": return v == want
        default: return v != want
        }
    }

    private static func round1(_ v: Double) -> Double { (v * 10).rounded() / 10 }

    /// Rank the table's rows by the recipe, narrowed to `numbers` when there are any.
    static func rank(_ table: RankerTable, recipe original: RankerRecipe, numbers: [Int]) throws -> RankerResult {
        let (recipe, notes) = fit(table, original)
        for c in recipe.criteria where c.better != "higher" && c.better != "lower" {
            throw RankerRefusal("'\(c.column)': better is higher or lower.")
        }
        var rows = table.rows
        for d in recipe.derived {
            for i in rows.indices {
                let row = rows[i]
                rows[i][d.name] = .number(d.sum.reduce(0.0) { $0 + (row[$1]?.value ?? 0) })
            }
        }
        let preferred = recipe.key ?? ""
        let key = !numbers.isEmpty ? bestKey(table, numbers: numbers, preferred: preferred)
            : (preferred.isEmpty ? (table.names.first ?? "") : preferred)
        var missing: [String] = []
        if !numbers.isEmpty {
            let wanted = Set(numbers.map(String.init))
            let present = Set(rows.map { Self.key($0[key]) })
            missing = wanted.subtracting(present).sorted { ($0.count, $0) < ($1.count, $1) }
            rows = rows.filter { wanted.contains(Self.key($0[key])) }
        }
        let total = rows.count
        rows = try rows.filter { r in try recipe.filters.allSatisfy { try Self.passes(r, $0) } }

        let criteria = recipe.criteria.filter { $0.weight > 0 }
        let weightSum = criteria.reduce(0.0) { $0 + $1.weight }
        let weight = weightSum == 0 ? 1.0 : weightSum
        var parts = [[String: Double]](repeating: [:], count: rows.count)
        for c in criteria where !rows.isEmpty {
            let pct = Self.percentiles(rows.map { $0[c.column]?.value ?? -Double.infinity })
            for (i, p) in pct.enumerated() {
                parts[i][c.column] = Self.round1(100 * (c.better == "higher" ? p : 1 - p))
            }
        }
        let scores = parts.map { part in
            criteria.isEmpty ? 0.0
                : Self.round1(criteria.reduce(0.0) { $0 + $1.weight * (part[$1.column] ?? 0) } / weight)
        }
        // Highest score first; a tie keeps the table's order (Python's sort is stable).
        let order = rows.indices.sorted { (-scores[$0], $0) < (-scores[$1], $1) }
        let ranked = order.enumerated().map { place, i in
            RankedRow(rank: place + 1, score: scores[i], cells: rows[i], parts: parts[i])
        }

        var labels = Dictionary(table.columns.map { ($0.name, $0.label) }, uniquingKeysWith: { a, _ in a })
        for d in recipe.derived { labels[d.name] = d.label.isEmpty ? d.name : d.label }
        // Every column unless the recipe says otherwise: the key and what it
        // ranks by first, then the rest of the table in its own order.
        var show = recipe.show
        if show.isEmpty {
            var seen = Set<String>()
            show = ([key] + criteria.map(\.column) + recipe.derived.map(\.name) + table.names)
                .filter { seen.insert($0).inserted }
        }
        return RankerResult(
            columns: show.compactMap { n in labels[n].map { RankerColumn(name: n, label: $0) } },
            rows: ranked, kept: ranked.count, total: total, missing: missing, key: key,
            notes: notes, numbers: numbers, useNumbers: !numbers.isEmpty,
            tableColumns: table.columns, recipe: original)
    }
}

// MARK: - Reading a picture's numbers (ocr.py + vision_numbers.swift)

enum RankerVision {

    private static let hashed = try! NSRegularExpression(pattern: "^(?:#\\s?\\d{1,7}[\\s,;|]*)+$")
    private static let bare = try! NSRegularExpression(pattern: "^(?:\\d{1,7}[\\s,;|]*)+$")
    private static let hashedNumber = try! NSRegularExpression(pattern: "#\\s?(\\d+)")
    private static let anyNumber = try! NSRegularExpression(pattern: "\\d+")

    /// Unique numbers, first-seen order, from recognised pieces of text. A
    /// piece counts only when it is NOTHING BUT numbers (`#1172`), which drops
    /// "Ruling Guild: #1169", timers and the like; `#`-numbers are preferred,
    /// bare ones used only when no piece has a `#` (`ocr.numbers_in`).
    static func numbersIn(_ lines: [String]) -> [Int] {
        var hashedFound: [String] = [], bareFound: [String] = []
        for line in lines {
            let s = line.trimmingCharacters(in: .whitespacesAndNewlines)
            let ns = s as NSString
            let all = NSRange(location: 0, length: ns.length)
            if hashed.firstMatch(in: s, range: all) != nil {
                hashedFound += hashedNumber.matches(in: s, range: all).map { ns.substring(with: $0.range(at: 1)) }
            } else if bare.firstMatch(in: s, range: all) != nil {
                bareFound += anyNumber.matches(in: s, range: all).map { ns.substring(with: $0.range) }
            }
        }
        var seen = Set<Int>()
        return (hashedFound.isEmpty ? bareFound : hashedFound)
            .compactMap { Int($0) }
            .filter { seen.insert($0).inserted }
    }

    /// A recognised piece of text and where it sat, 0-1 from the picture's TOP-left.
    struct Piece { var image: Int; var top: Double; var left: Double; var height: Double; var text: String }

    /// Rows are pieces whose tops are within half a line of each other, then
    /// left to right; pictures in the order given — so the list reads like the screen.
    static func readingOrder(_ pieces: [Piece]) -> [String] {
        guard !pieces.isEmpty else { return [] }
        let line = pieces.map(\.height).sorted()[pieces.count / 2]
        let sorted = pieces.enumerated()
            .sorted { ($0.element.image, $0.element.top, $0.offset) < ($1.element.image, $1.element.top, $1.offset) }
            .map(\.element)
        var out: [String] = []
        var row: [Piece] = []
        for p in sorted {
            if let first = row.first, p.image != first.image || p.top - first.top > line / 2 {
                out += row.sorted { $0.left < $1.left }.map(\.text)
                row = []
            }
            row.append(p)
        }
        out += row.sorted { $0.left < $1.left }.map(\.text)
        return out
    }

    /// Every unique number in the pictures, read here by Apple Vision — the
    /// same reader the Mac uses, so no Mac is needed.
    static func numbers(in images: [Data]) async throws -> [Int] {
        try await Task.detached(priority: .userInitiated) {
            var pieces: [Piece] = []
            for (index, data) in images.enumerated() {
                guard let image = UIImage(data: data), let cg = image.cgImage else {
                    throw RankerRefusal("Couldn't open picture \(index + 1).")
                }
                let request = VNRecognizeTextRequest()
                request.recognitionLevel = .accurate
                request.usesLanguageCorrection = false        // "#1172" is not a word to correct
                try VNImageRequestHandler(cgImage: cg, orientation: RankerVision.orientation(image.imageOrientation))
                    .perform([request])
                for observation in request.results ?? [] {
                    guard let best = observation.topCandidates(1).first else { continue }
                    let b = observation.boundingBox
                    pieces.append(Piece(image: index, top: Double(1 - b.maxY), left: Double(b.minX),
                                        height: Double(b.height), text: best.string))
                }
            }
            return RankerVision.numbersIn(RankerVision.readingOrder(pieces))
        }.value
    }

    private static func orientation(_ o: UIImage.Orientation) -> CGImagePropertyOrientation {
        switch o {
        case .up: return .up
        case .down: return .down
        case .left: return .left
        case .right: return .right
        case .upMirrored: return .upMirrored
        case .downMirrored: return .downMirrored
        case .leftMirrored: return .leftMirrored
        case .rightMirrored: return .rightMirrored
        @unknown default: return .up
        }
    }
}
