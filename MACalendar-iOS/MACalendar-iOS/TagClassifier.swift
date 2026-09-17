import Foundation

/// The Mac's task-tag classifier, running on the phone.
///
/// `assistant/actions/todo/tagging.py` is the classifier — a keyword list per
/// tag, scored over the title, and **no tag at all** when nothing matches. It
/// only runs where the database is, so a task typed on the phone with the Mac
/// away was created untagged and stayed untagged: the Mac never re-tags a task
/// it did not create, so the queued create arrived hours later and landed in
/// the untagged pile for good.
///
/// This is that scorer, with the table it scores against served by the Mac
/// (`GET /tags/rules`) rather than copied into Swift. That distinction is the
/// point: a second keyword list in a second language is a list that drifts, and
/// the personal half of the table — the user's own vocabulary labels, the ones
/// that know "Haxaga" is a course — could not be shipped in an app binary at
/// all. What ships here is the ~40 lines of arithmetic; what syncs is the data.
///
/// Anything it decides offline is **provisional**: the tags ride along on the
/// queued create, and when the Mac replays it the Mac's own answer is what
/// lands. See `DOCUMENTATION/SYNC_PROTOCOL.md`.
@MainActor
final class TagClassifier: ObservableObject {
    static let shared = TagClassifier()

    /// The table last served by the Mac, or nil before the first contact.
    @Published private(set) var rules: TagRules?

    private let file = FileManager.default
        .urls(for: .documentDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("mc_tag_rules.json")

    private init() {
        if let data = try? Data(contentsOf: file) {
            rules = try? JSONDecoder().decode(TagRules.self, from: data)
        }
    }

    /// Adopt a freshly served table. A no-op when the revision is unchanged,
    /// so the bootstrap can hand it over on every foreground without churning
    /// the disk or republishing to every subscriber.
    func update(_ fresh: TagRules) {
        guard fresh.rev != rules?.rev else { return }
        rules = fresh
        try? JSONEncoder().encode(fresh).write(to: file)
    }

    // MARK: - The classifier

    /// The tag for a task title, or nil when nothing matches.
    ///
    /// Untagged is the honest answer when nothing matches: a wrongly tagged
    /// task has to be undone by hand, an untagged one merely sits in the
    /// untagged pile. Same judgement as the Mac's.
    func tag(for title: String) -> String? {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        // Never-synced phone: no keyword table, so the only thing that can be
        // said honestly is "this title names a tag outright". The real table
        // arrives on the first contact with the Mac.
        guard let rules else { return namedOutright(in: trimmed, palette: fallbackPalette) }

        let never = Set(rules.neverInfer.map { $0.lowercased() })
        // Kept in the palette's order, not a dictionary's: the "named
        // outright" rule below returns the FIRST match, and tagging.py walks
        // the palette in the order the Mac serves it.
        let allowedNames = rules.palette.filter { !$0.isEmpty && !never.contains($0.lowercased()) }
        var allowed: [String: String] = [:]           // lower-cased → real casing
        for name in allowedNames { allowed[name.lowercased()] = name }
        guard !allowed.isEmpty else { return nil }

        let text = Self.normalise(trimmed)

        // This user's own words come first — a label they set by hand outranks
        // any list that ships with the app.
        if let personal = personalLabel(in: text, rules: rules),
           let real = allowed[personal.lowercased()] {
            return real
        }

        var best: String?
        var bestScore = 0.0
        for (tag, keywords) in rules.keywords {
            guard let real = allowed[tag.lowercased()] else { continue }
            let s = Self.score(text, keywords)
            if s > bestScore { best = real; bestScore = s }
        }

        // A tag whose own name is in the title beats a keyword match — that is
        // the user naming it outright, and it is the only way a custom tag with
        // no keyword list of its own can ever match.
        if let named = namedOutright(in: trimmed, palette: allowedNames) { return named }

        return best
    }

    /// `tag(for:)` as the list the create endpoints take.
    func tags(for title: String) -> [String] {
        tag(for: title).map { [$0] } ?? []
    }

    // MARK: - Internals (mirrors of tagging.py)

    private var fallbackPalette: [String] {
        LocalStore.shared.allTags().map { $0.name }
    }

    /// `" " + title.lower() with punctuation blanked + " "`, whitespace
    /// collapsed — the same haystack `tagging._score` and `vocab.label_for`
    /// build, so a leading/trailing word still matches as a whole word.
    static func normalise(_ title: String) -> String {
        let blanked = String(title.lowercased().map { ch in
            (ch.isLetter || ch.isNumber || ch == "_" || ch == "'" || ch == "-"
             || ch.isWhitespace) ? ch : " "
        })
        let collapsed = blanked.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        return " " + collapsed + " "
    }

    /// Multi-word keywords are matched as phrases and score higher; single
    /// words must match whole (so "tea" does not fire inside "team").
    static func score(_ text: String, _ keywords: [String]) -> Double {
        var total = 0.0
        for raw in keywords {
            let kw = raw.lowercased()
            if kw.isEmpty { continue }
            if kw.contains(" ") {
                if text.contains(" " + kw + " ") {
                    total += 2.0 + 0.2 * Double(kw.split(separator: " ").count)
                }
            } else if containsWord(text, kw) {
                total += kw.count > 3 ? 1.5 : 1.0
            }
        }
        return total
    }

    /// Whole-word containment with the Python lookarounds' definition of a
    /// word character: letters, digits, `_`, `'` and `-`. Written out rather
    /// than done with a regex because this runs once per keyword per keystroke-
    /// free create, and the escaping rules are one more thing to get wrong.
    static func containsWord(_ text: String, _ word: String) -> Bool {
        guard !word.isEmpty else { return false }
        let chars = Array(text)
        let needle = Array(word)
        func isWordChar(_ c: Character) -> Bool {
            c.isLetter || c.isNumber || c == "_" || c == "'" || c == "-"
        }
        var i = 0
        while i + needle.count <= chars.count {
            if Array(chars[i..<(i + needle.count)]) == needle {
                let beforeOK = i == 0 || !isWordChar(chars[i - 1])
                let after = i + needle.count
                let afterOK = after == chars.count || !isWordChar(chars[after])
                if beforeOK && afterOK { return true }
            }
            i += 1
        }
        return false
    }

    /// `vocab.label_for` — the label implied by any of this user's own words,
    /// longest word first so "Modern Computer Vision" wins over "vision".
    private func personalLabel(in normalisedText: String, rules: TagRules) -> String? {
        for word in rules.personalLabels.keys.sorted(by: { $0.count > $1.count }) {
            if normalisedText.contains(" " + word + " ") { return rules.personalLabels[word] }
        }
        return nil
    }

    /// A tag whose own name appears in the title, in palette order — the first
    /// match wins, exactly as `tagging.infer_tag`'s final loop does. ("Work"
    /// cannot fire inside "coursework": the whole-word rule sees the "e".)
    private func namedOutright(in title: String, palette: [String]) -> String? {
        let text = Self.normalise(title)
        for name in palette where Self.containsWord(text, name.lowercased()) {
            return name
        }
        return nil
    }
}
