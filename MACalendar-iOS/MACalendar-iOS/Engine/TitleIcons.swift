import Foundation

/// Which drawings a title gets — `label/title_icons.py`, on the phone.
///
/// The Mac serves each row's `icons`. A row the Mac has not seen (made on a
/// phone with no Mac, DEVQA Q85, or offline) has none, so the phone works
/// them out from the same lexicon (`TitleIconsData`, generated from the
/// Python) with the same rule: every word fires only in the sense its
/// neighbours confirm, one drawing once, in the order the words are said.
/// The settings are the same too: `title_emoji.count` and the kinds switched
/// off, read from where Settings keeps them.
enum TitleIcons {

    private struct Compiled {
        let entry: TitleIconsData.Entry
        let word: NSRegularExpression
        let needs: [NSRegularExpression]
        let vetoes: [NSRegularExpression]
    }

    private static let compiled: [Compiled] = TitleIconsData.lexicon.compactMap { e in
        let alts = e.words.sorted { $0.count > $1.count }.map(NSRegularExpression.escapedPattern(for:))
        guard let word = try? NSRegularExpression(pattern: #"(?<![\w'])("# + alts.joined(separator: "|") + #")(?![\w'])"#,
                                                  options: .caseInsensitive) else { return nil }
        return Compiled(entry: e, word: word,
                        needs: e.needs.compactMap { try? NSRegularExpression(pattern: $0, options: .caseInsensitive) },
                        vetoes: e.vetoes.compactMap { try? NSRegularExpression(pattern: $0, options: .caseInsensitive) })
    }

    private static var cache: [String: [String]] = [:]

    /// The drawings for `title` as Settings asks — none unless switched on.
    static func icons(for title: String) -> [String] {
        let d = UserDefaults.standard
        let count = d.integer(forKey: "titleEmojiCount")
        guard count > 0, !title.isEmpty else { return [] }
        let off = Set(d.stringArray(forKey: "titleEmojiOff") ?? [])
        return icons(title, count: count, groups: Set(TitleIconsData.groups).subtracting(off))
    }

    static func icons(_ title: String, count: Int, groups: Set<String>) -> [String] {
        let key = "\(count)|\(groups.sorted().joined(separator: ","))|\(title)"
        if let hit = cache[key] { return hit }
        let text = title
        let low = text.lowercased()
        let full = NSRange(low.startIndex..., in: low)
        var found: [String: Int] = [:]                    // icon -> where its word starts
        var taken: [NSRange] = []
        for c in compiled where groups.contains(c.entry.group) {
            if c.vetoes.contains(where: { $0.firstMatch(in: low, range: full) != nil }) { continue }
            if !c.needs.isEmpty && !c.needs.contains(where: { $0.firstMatch(in: low, range: full) != nil }) { continue }
            for m in c.word.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
                if taken.contains(where: { NSIntersectionRange($0, m.range).length > 0 }) { continue }
                if found[c.entry.icon] == nil || m.range.location < found[c.entry.icon]! {
                    found[c.entry.icon] = m.range.location
                }
                taken.append(m.range)
                break
            }
        }
        let out = Array(found.sorted { $0.value < $1.value }.map(\.key).prefix(count))
        if cache.count > 2000 { cache.removeAll() }
        cache[key] = out
        return out
    }
}
