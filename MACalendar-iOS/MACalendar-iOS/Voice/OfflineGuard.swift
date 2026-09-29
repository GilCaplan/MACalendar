import Foundation

// MARK: - What the phone leaves for the Mac, decided BEFORE any model call
//
// DEVQA Q68, step 1. A 40-row probe of Apple's model as the offline reader
// found it booking a NEW item for 8 of 9 commands that asked to move,
// complete, delete or ask ("push vet appointment to 3:45pm" became a second
// vet appointment). The Mac's engine never asks a model that question: its
// rule tables route those verbs. So the phone applies the SAME tables here,
// in code, first — a command they catch never reaches the model.
//
// The rules are served by the Mac (`assistant/offline/spec.py::guard()`,
// generated from the engine's `INTENT_MAP` and its delete/complete frames);
// `bundled` is the copy for a phone that has not reached the Mac yet, and
// `tests/unit/test_offline_protocol.py` holds it equal to the served one.

struct GuardRules: Codable, Equatable {
    var leaveVerbs: [String]
    var leaveVerbsWithDomain: [String]
    var domainWords: [String]
    var frames: [String]
    var questionStarts: [String]
    var leadIns: [String]

    enum CodingKeys: String, CodingKey {
        case frames
        case leaveVerbs = "leave_verbs"
        case leaveVerbsWithDomain = "leave_verbs_with_domain"
        case domainWords = "domain_words"
        case questionStarts = "question_starts"
        case leadIns = "lead_ins"
    }

    static let bundled = GuardRules(
        leaveVerbs: ["advance", "annotate", "cancel", "complete", "delay", "delete", "done", "edit", "erase", "extend", "finish", "lengthen", "move", "postpone", "prolong", "push", "rename", "reschedule", "scrap", "shift", "shorten", "stretch", "update"],
        leaveVerbsWithDomain: ["change", "check", "clear", "drop", "list", "read", "remove", "rid", "show", "summarize", "trim"],
        domainWords: ["calendar", "schedule", "agenda", "list", "to-do", "todo", "to do", "task", "tasks", "reminder", "reminders"],
        frames: [
            #"\b(?:delete|remove|wipe)\s+(?:it|that)\b|\bfrom\s+(?:my|the)\s+(?:to-?do\s+)?list\b|\bremove\s+from\s+(?:the\s+)?list\b|\bno\s+longer\s+need\b|\bnot\s+needed\b|\bwon'?t\s+be\s+doing\b|\bnever\s+mind\s+about\b|\btake\s+it\s+off\s+(?:my|the)\s+list\b"#,
            #",\s*done\s*[.!]?$|\bis\s+sorted\b|\btick\s+it\s+off\b"#,
            #"\bis\s+now\s+(?:at|on|due|in)\b"#,
            #"\binstead\s+of\b"#,
            #"\bas\s+(?:high|low|medium|top)\s+priority\b"#,
            #"\b(?:i'?m|i\s+am)\s+(?:done|finished)\s+with\b"#,
            #"^(?:(?:please|can you|could you|can we|let's|lets|ok|so)\s+)?change\s+\S.*?\s+to\s+"#,
            #"\b(?:mark|tick)\b.*\b(?:done|complet\w*|finished|off)\b"#,
            #"\balready\s+(?:did|done|finished|paid|sent|mailed|bought|called)\b"#,
            #"\bget\s+rid\s+of\b"#,
            #"\btake\b.+\boff\s+(?:my|the)\s+(?:calendar|calender|list|to-?do)"#,
            #"\bcheck\s+off\b"#,
            #"\bdouble[\s-]+check\b"#
        ],
        questionStarts: ["what", "what's", "whats", "when", "when's", "where", "which", "who", "how", "do i", "does", "did i", "is", "am i", "are", "have i", "tell me", "can you tell me", "could you tell me", "show me", "summarize", "can you check", "could you check", "check what", "check if", "check whether", "walk me through"],
        leadIns: ["please", "hey", "ok", "okay", "so", "um", "uh", "just", "also", "and", "yeah", "yes", "alright", "right", "ok google", "hey google", "hey siri", "siri", "alexa", "assistant", "can we", "could we", "to", "can you", "could you", "would you", "will you", "i need you to", "i want you to", "i've", "i have", "i"])
}

enum OfflineGuard {
    /// True when the command asks to change, delete, complete or look up
    /// something — the phone books nothing and the Mac decides.
    static func leavesForMac(_ text: String, rules: GuardRules = .bundled) -> Bool {
        let t = text.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return false }
        if t.hasSuffix("?") { return true }
        for f in rules.frames {
            if let re = try? NSRegularExpression(pattern: f, options: [.caseInsensitive]),
               re.firstMatch(in: t, range: NSRange(t.startIndex..., in: t)) != nil {
                return true
            }
        }
        let tokens = t.split(whereSeparator: { !$0.isLetter && $0 != "-" }).map(String.init)
        let hasDomain = rules.domainWords.contains { d in
            has(word: d, in: t) || (!d.contains(" ") && tokens.contains { near($0, d) })   // "calender"
        }
        let clauses = t.components(separatedBy: CharacterSet(charactersIn: ",.;!?"))
            .flatMap { $0.components(separatedBy: " and then ") }
            .flatMap { $0.components(separatedBy: " then ") }
            .flatMap { $0.components(separatedBy: " and ") }
        for raw in clauses {
            let c = stripLeadIns(raw.trimmingCharacters(in: .whitespaces), rules)
            // a question in ANY clause: "before i book anything, what does friday look like"
            if rules.questionStarts.contains(where: { c == $0 || c.hasPrefix($0 + " ") }) {
                return true
            }
            guard let first = c.split(separator: " ").first.map(String.init) else { continue }
            let forms = lemmas(first)
            if forms.contains(where: { f in rules.leaveVerbs.contains { near(f, $0) } }) { return true }
            if hasDomain, forms.contains(where: { f in rules.leaveVerbsWithDomain.contains { near(f, $0) } }) {
                return true
            }
        }
        return false
    }

    static func stripLeadIns(_ s: String, _ rules: GuardRules) -> String {
        var c = s
        var changed = true
        let leads = rules.leadIns.sorted { $0.count > $1.count }      // "i need you to" before "i"
        while changed {
            changed = false
            for l in leads where c == l || c.hasPrefix(l + " ") {
                c = String(c.dropFirst(l.count)).trimmingCharacters(in: .whitespaces)
                changed = true
                break
            }
        }
        return c
    }

    /// "postponed" → postpone, "finished" → finish, "moving" → move,
    /// "cancelled" → cancel. Candidates, not a stemmer: a verb matches if any
    /// candidate is in the table.
    static func lemmas(_ w: String) -> [String] {
        let w = w.trimmingCharacters(in: CharacterSet.letters.inverted)
        var out = [w]
        func drop(_ n: Int) -> String { String(w.dropLast(n)) }
        if w.hasSuffix("s") { out.append(drop(1)) }
        if w.hasSuffix("es") { out.append(drop(2)) }
        if w.hasSuffix("d") { out.append(drop(1)) }
        if w.hasSuffix("ed") {
            let stem = drop(2)
            out.append(stem)
            if stem.count > 2, stem.last == stem.dropLast().last { out.append(String(stem.dropLast())) }
        }
        // No "-ing" forms: a command leads with the base verb, and "moving day"
        // matched "move" (first guard run, 2026-09-29).
        return out
    }

    /// The same word, or one slip away when both are long enough to tell
    /// ("updat", "reshedule" — speech-to-text and typing both drop a letter).
    static func near(_ a: String, _ b: String) -> Bool {
        if a == b { return true }
        // the table word must be 6+ letters: "chuck" is not a slip of "check"
        guard a.count >= 5, b.count >= 6, abs(a.count - b.count) <= 1 else { return false }
        return editDistance(Array(a), Array(b)) <= 1
    }

    static func editDistance(_ a: [Character], _ b: [Character]) -> Int {
        var prev = Array(0...b.count)
        for (i, ca) in a.enumerated() {
            var cur = [i + 1] + Array(repeating: 0, count: b.count)
            for (j, cb) in b.enumerated() {
                cur[j + 1] = min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca == cb ? 0 : 1))
            }
            prev = cur
        }
        return prev[b.count]
    }

    static func has(word: String, in text: String) -> Bool {
        let esc = NSRegularExpression.escapedPattern(for: word)
        return text.range(of: "\\b" + esc + "\\b", options: .regularExpression) != nil
    }
}
