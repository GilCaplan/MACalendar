import Foundation

/// The event-category classifier as data (GET /categories/rules, and the
/// bootstrap's `category_rules`), so the phone can categorise and colour an
/// event with the Mac away. `rev` changes whenever any of it does.
struct CategoryRules: Codable, Equatable {
    struct Category: Codable, Equatable {
        let name: String
        let color: String
        let alt: String
        let keywords: [String]
    }
    let rev: String
    /// In the Mac's order — a tie goes to the first, as `classify` breaks it.
    let categories: [Category]
    /// The user's single capitalised vocabulary words, lower-cased: who
    /// `classify`'s last rule treats as a person ("Avi" alone → Social).
    let people: [String]
}

/// `assistant/actions/calendar/categories.py`'s `classify` and `pick_color`,
/// running on the phone over the table the Mac serves.
///
/// An event made here while the Mac was away used to have no category and no
/// colour until the queued create replayed. This is the same scorer (the
/// title counts three times anything else; a phrase outweighs a word; a bare
/// "with" is a weak Social signal), so the preview matches what the Mac will
/// do; `LabelModel.stackCategory` then lets the learned model fill a
/// `Personal`. The QUEUED body never carries the answer — on replay the Mac
/// classifies it itself and its answer is the one that lands.
///
/// Foundation only: `tests/unit/test_label_export.py` compiles it on its own
/// and holds it to `classify` over thousands of titles.
enum CategoryClassifier {

    /// `categories.classify(title, attendees, location, description)`.
    static func classify(_ title: String, attendees: [String] = [], location: String = "",
                         description: String = "", rules: CategoryRules) -> String {
        let titleText = clean(title)
        var rest = clean([location, description].joined(separator: " "))
        let att = attendees.filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        if !att.isEmpty {
            rest = String(rest.dropLast()) + " with " + att.joined(separator: " ").lowercased() + " "
        }
        let text = titleText + rest
        let saysWith = hasBoundedWith(text)
        var best = "Personal", bestScore = 0.0
        // A Python dict: first insertion fixes the position, a repeat updates it.
        var order: [String] = []
        var scores: [String: Double] = [:]
        var phraseHit = false
        let titleWeight = 3.0
        for c in rules.categories {
            var score = 0.0
            for kw in c.keywords where !kw.isEmpty {
                let lower = kw.lowercased()
                let phrase: String? = kw.contains(" ") ? " " + lower + " " : nil
                for (haystack, weight) in [(titleText, titleWeight), (rest, 1.0)] {
                    if let phrase, bounded(haystack, phrase, isPart: { _ in false }) {
                        score += (2.0 + 0.2 * Double(kw.split(separator: " ").count)) * weight
                        phraseHit = true
                    } else if containsWord(haystack, lower) {
                        score += (kw.unicodeScalars.count > 3 ? 1.5 : 1.0) * weight
                    }
                }
            }
            if c.name == "Social" && score != 0 && saysWith && score <= 1.0 { score = 0.6 }
            if scores[c.name] == nil { order.append(c.name) }
            scores[c.name] = score
            if score > bestScore { best = c.name; bestScore = score }
        }
        if phraseHit && best == "Social" && saysWith {
            let social = (scores["Social"] ?? 0) - 1.0
            let rival = order.filter { $0 != "Social" }.compactMap { scores[$0] }.max() ?? 0.0
            if rival > social,
               let name = order.first(where: { $0 != "Social" && scores[$0] == rival }) {
                best = name
                bestScore = rival
            }
        }
        if bestScore == 0 {
            let people = Set(rules.people)
            if !people.isEmpty && !Set(nameWords(title)).isDisjoint(with: people) { return "Social" }
        }
        return best
    }

    /// Does the category exist (`categories.get(name) is not None`)?
    static func exists(_ name: String, in rules: CategoryRules) -> Bool {
        rules.categories.contains { $0.name.lowercased() == name.lowercased() }
    }

    /// `color_for`: the category's pair, else Personal's.
    static func colors(for category: String, in rules: CategoryRules) -> (color: String, alt: String)? {
        let c = rules.categories.first { $0.name.lowercased() == category.lowercased() }
            ?? rules.categories.first { $0.name.lowercased() == "personal" }
        return c.map { ($0.color, $0.alt.isEmpty ? $0.color : $0.alt) }
    }

    /// `pick_color`: the primary colour unless a neighbouring event already
    /// has it, then the alternate; both taken, a lighter primary.
    static func pickColor(_ category: String, neighbours: [String], rules: CategoryRules) -> String? {
        guard let (primary, alt) = colors(for: category, in: rules) else { return nil }
        let taken = Set(neighbours.filter { !$0.isEmpty }.map { $0.lowercased() })
        if !taken.contains(primary.lowercased()) { return primary }
        if !taken.contains(alt.lowercased()) { return alt }
        let hex = Array(primary.unicodeScalars)
        guard hex.count >= 7 else { return primary }
        func channel(_ i: Int) -> Int {
            var v = String.UnicodeScalarView(); v.append(contentsOf: hex[i..<(i + 2)])
            return Int(String(v), radix: 16) ?? 0
        }
        let rgb = [channel(1), channel(3), channel(5)].map { min(255, Int(Double($0) * 0.7 + 60)) }
        return String(format: "#%02x%02x%02x", rgb[0], rgb[1], rgb[2])
    }

    // MARK: - The Python regexes, written out

    /// `" " + re.sub(r"[^\w\s'-]", " ", x.lower()) + " "` — NOT collapsed:
    /// "dinner, with" keeps two spaces, and a phrase then cannot span them.
    static func clean(_ x: String) -> String {
        var v = String.UnicodeScalarView()
        for s in x.lowercased().unicodeScalars {
            v.append(LabelModel.isWord(s) || s.properties.isWhitespace || s == "'" || s == "-" ? s : " ")
        }
        return " " + String(v) + " "
    }

    /// `(?<![\w'-])kw(?![\w'-])` — a whole word, where `'` and `-` are part of one.
    static func containsWord(_ text: String, _ word: String) -> Bool {
        bounded(text, word) { LabelModel.isWord($0) || $0 == "'" || $0 == "-" }
    }

    /// `\bwith\b` — Python's word boundary, where only `\w` is part of a word.
    static func hasBoundedWith(_ text: String) -> Bool {
        bounded(text, "with") { LabelModel.isWord($0) }
    }

    private static func bounded(_ text: String, _ word: String, isPart: (Unicode.Scalar) -> Bool) -> Bool {
        let t = Array(text.unicodeScalars), w = Array(word.unicodeScalars)
        guard !w.isEmpty, t.count >= w.count else { return false }
        for i in 0...(t.count - w.count) where t[i..<(i + w.count)].elementsEqual(w) {
            let beforeOK = i == 0 || !isPart(t[i - 1])
            let after = i + w.count
            if beforeOK && (after == t.count || !isPart(t[after])) { return true }
        }
        return false
    }

    /// `re.findall(r"[a-zA-Z][a-zA-Z'-]+", title)`, lower-cased.
    static func nameWords(_ title: String) -> [String] {
        func letter(_ s: Unicode.Scalar) -> Bool { ("a"..."z").contains(s) || ("A"..."Z").contains(s) }
        let t = Array(title.unicodeScalars)
        var out: [String] = []
        var i = 0
        while i < t.count {
            guard letter(t[i]) else { i += 1; continue }
            var j = i + 1
            while j < t.count && (letter(t[j]) || t[j] == "'" || t[j] == "-") { j += 1 }
            if j - i >= 2 {
                var v = String.UnicodeScalarView(); v.append(contentsOf: t[i..<j])
                out.append(String(v).lowercased())
            }
            i = j
        }
        return out
    }
}
