import Foundation

/// The Easter egg's decisions, shared by the phone and the Mac helper so the
/// two can never disagree: what a heard sentence summons, whether it is only
/// magic words, the surprise rules, the festival season, and when to greet.
/// Foundation only.
enum EggRules {
    /// What to do with words a device heard.
    struct Decision: Equatable {
        /// Play these, as a group or one by one.
        var ids: [String] = []
        var together = true
        /// The words were only magic words: do NOT send them as a command,
        /// whether or not they play this time.
        var bareHandled = false
    }

    static func decide(_ text: String, bare: Bool, settings s: EggSettings, now: Date = Date(),
                       lastPlayed: Date = .distantPast, roll: Int? = nil) -> Decision {
        guard s.enabled, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return Decision() }
        let live = liveObjects(s, now: now)
        let ids = EggMatcher.matches(text, objects: live, plural: s.pluralCount).ids
        guard !ids.isEmpty else { return Decision() }
        if bare {
            guard s.trigger.onItsOwn, EggMatcher.isBare(text, objects: live, groupWords: s.groupWords) else { return Decision() }
        } else {
            guard s.trigger.inCommand else { return Decision() }
        }
        var d = Decision(bareHandled: bare)
        if allowed(s, now: now, lastPlayed: lastPlayed, roll: roll) {
            d.ids = ids
            d.together = together(text, s)
        }
        return d
    }

    /// Words heard LATE — the Mac's transcript, corrected by the vocabulary —
    /// after the device's own hearing played nothing (Gil, 2026-10-01: "it
    /// should always look for words even if it doesnt make an event or
    /// task"). For EVERY magic word and every kind of graphic, on both apps:
    /// said on its own it is a bare magic word (it reached the Mac anyway);
    /// otherwise one inside a command. `bareHandled` here only means "held
    /// back on purpose" (chance, quiet hours) — nothing is left unsent.
    static func decideLate(_ text: String, settings s: EggSettings, now: Date = Date(),
                           lastPlayed: Date = .distantPast, roll: Int? = nil) -> Decision {
        // The words, not a tag the brain was handed ("[TASKS VIEW] Val").
        let words = text.replacingOccurrences(of: #"^\s*\[[A-Z ]+ VIEW\]\s*"#, with: "",
                                              options: .regularExpression)
        let bare = decide(words, bare: true, settings: s, now: now, lastPlayed: lastPlayed, roll: roll)
        if !bare.ids.isEmpty || bare.bareHandled { return bare }
        return decide(words, bare: false, settings: s, now: now, lastPlayed: lastPlayed, roll: roll)
    }

    /// The Jewish set only when it is on, and only in season when asked.
    static func liveObjects(_ s: EggSettings, now: Date = Date()) -> [EggObject] {
        let inSeason = Set(EggFestivals.current(now).flatMap(\.objects))
        return s.objects.filter { o in
            guard EggCatalog.jewish.contains(o.id) else { return true }
            return s.jewish && (!s.jewishInSeason || inSeason.contains(o.id))
        }
    }

    static func together(_ text: String, _ s: EggSettings) -> Bool {
        switch s.group {
        case .together: return true
        case .oneAfterAnother: return false
        case .onGroupWord: return EggMatcher.saysGroup(text, groupWords: s.groupWords)
        }
    }

    static func inQuietHours(_ s: EggSettings, now: Date) -> Bool {
        guard s.quietHours else { return false }
        let c = Calendar.current.dateComponents([.hour, .minute], from: now)
        let m = (c.hour ?? 0) * 60 + (c.minute ?? 0)
        return s.quietFrom <= s.quietTo ? (m >= s.quietFrom && m < s.quietTo) : (m >= s.quietFrom || m < s.quietTo)
    }

    /// Quiet hours, the cooldown, and the one-in-N chance (`roll` fixes the
    /// die for tests: 1 plays).
    static func allowed(_ s: EggSettings, now: Date, lastPlayed: Date, roll: Int? = nil) -> Bool {
        if inQuietHours(s, now: now) { return false }
        if s.cooldown > 0, now.timeIntervalSince(lastPlayed) < s.cooldown { return false }
        if s.chance > 1, (roll ?? Int.random(in: 1...s.chance)) != 1 { return false }
        return true
    }

    /// The festival to greet now, if any: once a day (`greeted` says whether
    /// today's key was used), Shabbat's from Friday midday, never in quiet hours.
    static func festivalToGreet(_ s: EggSettings, now: Date = Date(), greeted: (String) -> Bool) -> (EggFestivals.Festival, String)? {
        guard s.enabled, s.jewish, s.festivalGreeting, !inQuietHours(s, now: now) else { return nil }
        let cal = Calendar.current
        let hour = cal.component(.hour, from: now), weekday = cal.component(.weekday, from: now)
        let open = EggFestivals.current(now).filter { $0.id != "shabbat" || weekday == 7 || hour >= 12 }
        guard let f = open.first else { return nil }
        let key = "egg_greeted_\(f.id)_\(Int(cal.startOfDay(for: now).timeIntervalSince1970))"
        return greeted(key) ? nil : (f, key)
    }

    // MARK: - Suggested words (EggWordSuggester, both sources)

    /// Lower-case, trimmed, one to three words; no repeats, nothing the object
    /// already has, not the name's own words one by one, no leading article,
    /// no "a type of …" descriptions; at most `count`.
    static func cleanWords(_ words: [String], name: String, existing: [String], count: Int) -> [String] {
        let have = Set(existing.map { $0.lowercased() })
        let lowerName = name.lowercased()
        let nameParts = Set(lowerName.split(separator: " ").map(String.init))
        var out: [String] = []
        for w in words {
            var t = w.lowercased().trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
            for article in ["a ", "an ", "the "] where t.hasPrefix(article) { t.removeFirst(article.count) }
            let parts = t.split(separator: " ")
            guard !t.isEmpty, parts.count <= 3, t != lowerName || have.isEmpty == false,
                  !have.contains(t), !out.contains(t),
                  !(nameParts.count > 1 && nameParts.contains(t)),
                  !t.contains("type of"), !t.contains("member of"), !t.contains("kind of")
            else { continue }
            out.append(t)
            if out.count >= count { break }
        }
        return out
    }

    // MARK: - One word, one thing

    /// Do two keywords summon the same speech — equal, or one the other's
    /// plural ("dog" / "dogs")?
    static func sameWord(_ a: String, _ b: String) -> Bool {
        let x = a.lowercased(), y = b.lowercased()
        return x == y || EggMatcher.same(x, y) || EggMatcher.same(y, x)
    }

    /// The other object `word` (or its plural / singular) already summons.
    static func owner(of word: String, besides id: String, in objects: [EggObject]) -> EggObject? {
        objects.first { $0.id != id && $0.keywords.contains { sameWord($0, word) } }
    }

    /// Words that summon more than one thing, with the objects that have them.
    static func conflicts(_ objects: [EggObject]) -> [(word: String, ids: [String])] {
        var out: [(String, [String])] = []
        var seen = Set<String>()
        for o in objects {
            for k in o.keywords where !seen.contains(k.lowercased()) {
                let ids = objects.filter { $0.keywords.contains { sameWord($0, k) } }.map(\.id)
                if ids.count > 1 {
                    out.append((k.lowercased(), ids))
                    for other in objects where ids.contains(other.id) {
                        for w in other.keywords where sameWord(w, k) { seen.insert(w.lowercased()) }
                    }
                }
            }
        }
        return out
    }
}
