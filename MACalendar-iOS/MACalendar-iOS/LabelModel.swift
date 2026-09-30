import Foundation

/// The Mac's learned labellers — event category and task tags — running on
/// the phone.
///
/// On the Mac each is a pickled sklearn pipeline, and the half that answers
/// there reads the title's nomic-embed-text vector from ollama, so neither
/// could ever run here. Their OTHER half is two TF-IDF vectorisers and a
/// logistic regression: a tokeniser, a dictionary lookup and a dot product.
/// The Mac serves that half as data (`GET /labels/model/<kind>`,
/// `assistant/engine/label/export.py`) and this file is the arithmetic —
/// the same split `TagClassifier` made for the keyword rules. A retrain
/// reaches the phone without a reinstall, and so does the user's PERSONAL
/// model, fitted from their own corrections, which no app binary could carry.
///
/// **The phone is the Mac with ollama down.** Without the vector the Mac
/// answers from this same pipeline, held to the fallback bar the payload
/// carries; `stackCategory` / `stackTags` are `model.category_for` /
/// `tags_for`: the rules answer first, the model fills only what they left
/// blank (unless `model_first`), and a class the user deleted never returns.
///
/// Foundation only, on purpose: `tests/unit/test_label_export.py` compiles
/// this file on its own and holds it to sklearn's probabilities.
struct LabelModelPayload: Codable {
    struct Block: Codable {
        let name: String
        let analyzer: String          // "word" | "char_wb"
        let ngram: [Int]
        let terms: [String]
    }

    let format: Int
    let kind: String
    let rev: String
    let enabled: Bool
    let modelFirst: Bool
    let link: String                  // "softmax" (one label) | "sigmoid" (a set)
    let classes: [String]
    let bar: Double
    let blocks: [Block]
    let idf: String                   // base64, little-endian float32, blocks in order
    let coef: String                  // base64 float32, classes × features, row-major
    let intercept: [Double]

    enum CodingKeys: String, CodingKey {
        case format, kind, rev, enabled, link, classes, bar, blocks, idf, coef, intercept
        case modelFirst = "model_first"
    }
}

final class LabelModel {
    /// The payload format this build implements; a newer one is refused and
    /// the rules answer alone, as they did before this file existed.
    static let supportedFormat = 1

    let kind: String
    let rev: String
    let enabled: Bool
    let modelFirst: Bool
    let classes: [String]
    let bar: Double
    private let softmax: Bool
    private let blocks: [(analyzer: String, lo: Int, hi: Int, index: [String: Int])]
    private let idf: [Float]
    private let coef: [Float]
    private let intercept: [Double]
    private let width: Int

    init?(_ p: LabelModelPayload) {
        guard p.format == Self.supportedFormat, !p.classes.isEmpty,
              p.intercept.count == p.classes.count,
              p.link == "softmax" || p.link == "sigmoid",
              let idf = Self.floats(p.idf), let coef = Self.floats(p.coef)
        else { return nil }
        var built: [(String, Int, Int, [String: Int])] = []
        var start = 0
        for b in p.blocks {
            guard b.analyzer == "word" || b.analyzer == "char_wb", b.ngram.count == 2 else { return nil }
            var index: [String: Int] = [:]
            index.reserveCapacity(b.terms.count)
            for (i, t) in b.terms.enumerated() { index[t] = start + i }
            built.append((b.analyzer, b.ngram[0], b.ngram[1], index))
            start += b.terms.count
        }
        guard idf.count == start, coef.count == start * p.classes.count else { return nil }
        kind = p.kind; rev = p.rev; enabled = p.enabled; modelFirst = p.modelFirst
        classes = p.classes; bar = p.bar; softmax = p.link == "softmax"
        blocks = built.map { (analyzer: $0.0, lo: $0.1, hi: $0.2, index: $0.3) }
        self.idf = idf; self.coef = coef; intercept = p.intercept; width = start
    }

    private static func floats(_ b64: String) -> [Float]? {
        guard let raw = Data(base64Encoded: b64), raw.count % 4 == 0 else { return nil }
        var out = [Float](repeating: 0, count: raw.count / 4)
        _ = out.withUnsafeMutableBytes { raw.copyBytes(to: $0) }
        return out.map { Float(bitPattern: UInt32(littleEndian: $0.bitPattern)) }
    }

    // MARK: - Inference (export.ngram_proba, line for line)

    /// P(class) for one title, over `classes`.
    func probabilities(_ title: String) -> [Double] {
        let doc = title.lowercased()
        var x: [Int: Double] = [:]
        for b in blocks {
            var counts: [Int: Int] = [:]
            for g in Self.analyze(doc, analyzer: b.analyzer, lo: b.lo, hi: b.hi) {
                if let j = b.index[g] { counts[j, default: 0] += 1 }
            }
            var vals: [Int: Double] = [:]
            var sq = 0.0
            for (j, c) in counts {
                let v = (1.0 + log(Double(c))) * Double(idf[j])
                vals[j] = v
                sq += v * v
            }
            let norm = sq.squareRoot()
            if norm > 0 { for (j, v) in vals { x[j] = v / norm } }
        }
        let z = (0..<classes.count).map { c -> Double in
            var s = intercept[c]
            let row = c * width
            for (j, v) in x { s += v * Double(coef[row + j]) }
            return s
        }
        if softmax {
            let m = z.max() ?? 0
            let e = z.map { exp($0 - m) }
            let total = e.reduce(0, +)
            return e.map { $0 / total }
        }
        return z.map { 1.0 / (1.0 + exp(-$0)) }
    }

    /// `LabelModel.predict`'s n-gram path: the top class, or nil under the bar.
    func predict(_ title: String) -> (label: String, confidence: Double)? {
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let p = probabilities(title)
        var best = 0
        for i in p.indices where p[i] > p[best] { best = i }    // first max, as Python's max()
        return p[best] < bar ? nil : (classes[best], p[best])
    }

    /// `LabelModel.predict_tags`' n-gram path: every class over the bar.
    func predictTags(_ title: String) -> (tags: [String], confidence: Double)? {
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let p = probabilities(title)
        let picked = p.indices.filter { p[$0] >= bar }
        guard !picked.isEmpty else { return nil }
        return (picked.map { classes[$0] }, picked.map { p[$0] }.min() ?? 0)
    }

    // MARK: - The two analysers sklearn uses, on Unicode scalars (Python's
    // string indexing is by code point; Swift's Character is a grapheme).

    /// Python's `\w`: a letter or number (`str.isalnum`) or `_`. Not a
    /// combining mark — Python's re does not count those as word characters.
    static func isWord(_ s: Unicode.Scalar) -> Bool {
        if s == "_" { return true }
        switch s.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter,
             .decimalNumber, .letterNumber, .otherNumber:
            return true
        default:
            return false
        }
    }

    static func analyze(_ doc: String, analyzer: String, lo: Int, hi: Int) -> [String] {
        let scalars = Array(doc.unicodeScalars)
        var out: [String] = []
        func text(_ s: ArraySlice<Unicode.Scalar>) -> String {
            var v = String.UnicodeScalarView()
            v.append(contentsOf: s)
            return String(v)
        }
        if analyzer == "word" {
            // `(?u)\b\w\w+\b`: every maximal run of word characters, 2+ long.
            var toks: [String] = []
            var i = 0
            while i < scalars.count {
                guard isWord(scalars[i]) else { i += 1; continue }
                var j = i
                while j < scalars.count && isWord(scalars[j]) { j += 1 }
                if j - i >= 2 { toks.append(text(scalars[i..<j])) }
                i = j
            }
            for n in lo...hi where toks.count >= n {
                for k in 0...(toks.count - n) { out.append(toks[k..<(k + n)].joined(separator: " ")) }
            }
            return out
        }
        // char_wb: each whitespace-separated word, padded with one space each
        // side; a word shorter than n yields itself once and stops.
        var words: [ArraySlice<Unicode.Scalar>] = []
        var i = 0
        while i < scalars.count {
            guard !scalars[i].properties.isWhitespace else { i += 1; continue }
            var j = i
            while j < scalars.count && !scalars[j].properties.isWhitespace { j += 1 }
            words.append(scalars[i..<j])
            i = j
        }
        for w in words {
            let padded: [Unicode.Scalar] = [" "] + Array(w) + [" "]
            for n in lo...hi {
                var offset = 0
                out.append(text(padded[offset..<min(offset + n, padded.count)]))
                while offset + n < padded.count {
                    offset += 1
                    out.append(text(padded[offset..<(offset + n)]))
                }
                if offset == 0 { break }
            }
        }
        return out
    }

    // MARK: - Stacked behind the rules (model.category_for / tags_for)

    /// The event category: the rules' answer stands unless it is the catch-
    /// all `Personal` (or `model_first` is on); a model answer counts only if
    /// the category still exists.
    static func stackCategory(rule: String, title: String, model: LabelModel?,
                              exists: (String) -> Bool) -> String {
        guard let model, model.enabled else { return rule }
        if !model.modelFirst && !rule.isEmpty && rule != "Personal" { return rule }
        guard let got = model.predict(title), exists(got.label) else { return rule }
        return got.label
    }

    /// The task's tags: the rules' tags stand when they fired at all (unless
    /// `model_first`); the model's count only as far as the palette still
    /// holds them, in the palette's casing.
    static func stackTags(rule: [String], title: String, model: LabelModel?,
                          palette: [String]) -> [String] {
        guard let model, model.enabled else { return rule }
        if !model.modelFirst && !rule.isEmpty { return rule }
        guard let got = model.predictTags(title) else { return rule }
        var real: [String: String] = [:]           // later wins, as the Mac's dict does
        for name in palette where !name.isEmpty { real[name.lowercased()] = name }
        let live = got.tags.compactMap { real[$0.lowercased()] }
        return live.isEmpty ? rule : live
    }
}
