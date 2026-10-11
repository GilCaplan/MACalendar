import Foundation

// MARK: - The API's JSON, as the phone keeps it
//
// The shapes are `assistant/features/flashcards/store.py`'s `library()`,
// `get_set()` and `study()`; the card fields are `cardformat.py`'s, and
// FORMAT.md is the human description of the same rules. Every type here is
// Codable both ways because the phone WRITES them to disk: the library and
// every set's cards are cached so a round can be studied with the Mac away.

/// One subject in the library: a group of sets. `archived` takes it — and so
/// every set in it — out of the library and the study picker, keeping all of
/// it (cards, pictures, progress) until it is unarchived.
struct FlashSubject: Codable, Identifiable, Equatable {
    var id: Int
    var name: String
    var archived: Bool
    var sets: [FlashSetSummary]

    init(id: Int, name: String, archived: Bool = false, sets: [FlashSetSummary]) {
        self.id = id; self.name = name; self.archived = archived; self.sets = sets
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        archived = try c.decodeIfPresent(Bool.self, forKey: .archived) ?? false
        sets = try c.decodeIfPresent([FlashSetSummary].self, forKey: .sets) ?? []
    }
}

/// A set as the library lists it: counts, no cards.
struct FlashSetSummary: Codable, Identifiable, Equatable {
    var id: Int
    var subjectId: Int
    var slug: String
    var name: String
    var source: String
    var lang: String
    var dir: String
    var cards: Int
    var items: Int
    var seen: Int
    var due: Int
    var archived: Bool
    var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, slug, name, source, lang, dir, cards, items, seen, due, archived
        case subjectId = "subject_id", updatedAt = "updated_at"
    }

    init(id: Int, subjectId: Int, slug: String = "", name: String, source: String = "",
         lang: String = "", dir: String = "ltr", cards: Int = 0, items: Int = 0,
         seen: Int = 0, due: Int = 0, archived: Bool = false, updatedAt: String? = nil) {
        self.id = id; self.subjectId = subjectId; self.slug = slug; self.name = name
        self.source = source; self.lang = lang; self.dir = dir; self.cards = cards
        self.items = items; self.seen = seen; self.due = due; self.archived = archived
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        subjectId = try c.decode(Int.self, forKey: .subjectId)
        slug = try c.decodeIfPresent(String.self, forKey: .slug) ?? ""
        name = try c.decode(String.self, forKey: .name)
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
        lang = try c.decodeIfPresent(String.self, forKey: .lang) ?? ""
        dir = try c.decodeIfPresent(String.self, forKey: .dir) ?? "ltr"
        cards = try c.decodeIfPresent(Int.self, forKey: .cards) ?? 0
        items = try c.decodeIfPresent(Int.self, forKey: .items) ?? 0
        seen = try c.decodeIfPresent(Int.self, forKey: .seen) ?? 0
        due = try c.decodeIfPresent(Int.self, forKey: .due) ?? 0
        archived = try c.decodeIfPresent(Bool.self, forKey: .archived) ?? false
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
    }

    var isRTL: Bool { dir == "rtl" }
}

/// `GET /flashcards`: the library, and what was DELETED on the Mac, by id.
/// `deleted` is the only thing that may take a set or subject off this phone
/// (besides deleting it here): one merely missing from an answer is kept.
struct FlashLibrary: Codable {
    var subjects: [FlashSubject]
    var deleted: FlashDeleted?
}

/// What the Mac deleted. Ids are never reused there, so a record here can
/// never land on a set made later.
struct FlashDeleted: Codable, Equatable {
    var sets: [FlashDeletion]
    var subjects: [FlashDeletion]

    init(sets: [FlashDeletion] = [], subjects: [FlashDeletion] = []) {
        self.sets = sets; self.subjects = subjects
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sets = try c.decodeIfPresent([FlashDeletion].self, forKey: .sets) ?? []
        subjects = try c.decodeIfPresent([FlashDeletion].self, forKey: .subjects) ?? []
    }
}

struct FlashDeletion: Codable, Equatable {
    var id: Int
    var name: String?
    var at: String?
}

/// Where one study item stands: the Mac's `progress` row.
struct FlashProgress: Codable, Equatable {
    var stability: Double?
    var difficulty: Double?
    var due: String
    var last: String
    var reps: Int
    var lapses: Int
}

/// One label on an occlusion picture. `box` is [x, y, w, h] in PERCENT.
struct FlashLabel: Codable, Equatable, Hashable {
    var text: String
    var box: [Double]
    var tag: String?

    var rect: CGRect {
        guard box.count == 4 else { return .zero }
        return CGRect(x: box[0] / 100, y: box[1] / 100, width: box[2] / 100, height: box[3] / 100)
    }
}

/// One card, any type. The fields are a union of FORMAT.md's table — a card
/// carries only the ones its type uses, and `body` writes back exactly those,
/// because the Mac refuses an unknown or misplaced field rather than ignoring it.
struct FlashCard: Codable, Identifiable, Equatable {
    var id: Int
    var position: Int
    var type: String
    var front: String?
    var back: String?
    var bothWays: Bool?
    var image: String?
    var text: String?
    var question: String?
    var choices: [String]?
    var answer: String?
    var prompt: String?
    var steps: [String]?
    var labels: [FlashLabel]?
    var ask: String?
    var tags: [String]?
    var page: String?
    var explain: String?
    var note: String?
    var items: [String]
    var progress: [String: FlashProgress]

    enum CodingKeys: String, CodingKey {
        case id, position, type, front, back, image, text, question, choices, answer
        case prompt, steps, labels, ask, tags, page, explain, note, items, progress
        case bothWays = "both_ways"
    }

    init(id: Int = 0, position: Int = 0, type: String = "basic") {
        self.id = id; self.position = position; self.type = type
        items = [""]; progress = [:]
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(Int.self, forKey: .id) ?? 0
        position = try c.decodeIfPresent(Int.self, forKey: .position) ?? 0
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? "basic"
        front = Self.text(c, .front)
        back = Self.text(c, .back)
        bothWays = try c.decodeIfPresent(Bool.self, forKey: .bothWays)
        image = try c.decodeIfPresent(String.self, forKey: .image)
        text = Self.text(c, .text)
        question = Self.text(c, .question)
        choices = try c.decodeIfPresent([String].self, forKey: .choices)
        answer = Self.text(c, .answer)
        prompt = Self.text(c, .prompt)
        steps = try c.decodeIfPresent([String].self, forKey: .steps)
        labels = try c.decodeIfPresent([FlashLabel].self, forKey: .labels)
        ask = try c.decodeIfPresent(String.self, forKey: .ask)
        tags = try c.decodeIfPresent([String].self, forKey: .tags)
        // `page` is whatever the file said: 12, "12", "ch. 3".
        page = Self.text(c, .page)
        explain = Self.text(c, .explain)
        note = Self.text(c, .note)
        items = []
        progress = try c.decodeIfPresent([String: FlashProgress].self, forKey: .progress) ?? [:]
        items = try c.decodeIfPresent([String].self, forKey: .items) ?? Self.computeItems(self)
    }

    /// Text, or a number written as text — YAML turns `back: 1889` into an int.
    private static func text(_ c: KeyedDecodingContainer<CodingKeys>, _ k: CodingKeys) -> String? {
        if let s = try? c.decodeIfPresent(String.self, forKey: k) { return s }
        if let i = try? c.decodeIfPresent(Int.self, forKey: k) { return String(i) }
        if let d = try? c.decodeIfPresent(Double.self, forKey: k) { return String(d) }
        return nil
    }

    /// `cardformat.items()`: what this card schedules separately.
    static func computeItems(_ card: FlashCard) -> [String] {
        switch card.type {
        case "cloze":
            return (0..<Cloze.gaps(card.text ?? "").count).map { "c\($0)" }
        case "occlusion" where (card.ask ?? "one_at_a_time") == "one_at_a_time":
            return (0..<(card.labels?.count ?? 0)).map { "l\($0)" }
        default:
            return card.bothWays == true ? ["", "rev"] : [""]
        }
    }

    /// The card as the Mac takes it on `POST …/cards` / `PATCH /flashcards/cards/<id>`:
    /// only the fields its type allows (`cardformat.REQUIRED/OPTIONAL/COMMON`).
    var body: [String: Any] {
        var b: [String: Any] = ["type": type]
        func put(_ k: String, _ v: String?) {
            if let v, !v.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { b[k] = v }
        }
        switch type {
        case "basic":
            put("front", front); put("back", back)
            if bothWays == true { b["both_ways"] = true }
        case "image":
            put("image", image); put("back", back); put("front", front)
            if bothWays == true { b["both_ways"] = true }
        case "cloze": put("text", text)
        case "mc":
            put("question", question); put("answer", answer)
            b["choices"] = choices ?? []
        case "order":
            put("prompt", prompt); b["steps"] = steps ?? []
        case "typed": put("front", front); put("answer", answer)
        case "occlusion":
            put("image", image); put("prompt", prompt)
            b["ask"] = ask ?? "one_at_a_time"
            b["labels"] = (labels ?? []).map { l -> [String: Any] in
                var d: [String: Any] = ["text": l.text, "box": l.box]
                if let t = l.tag, !t.isEmpty { d["tag"] = t }
                return d
            }
        default: break
        }
        if let tags, !tags.isEmpty { b["tags"] = tags }
        put("page", page); put("explain", explain); put("note", note)
        return b
    }

    /// One line for the editor's list.
    var title: String {
        switch type {
        case "cloze": return Cloze.masked(text ?? "", hide: nil)
        case "mc": return question ?? ""
        case "order", "occlusion": return prompt ?? (type == "order" ? "Order" : "Picture")
        case "image": return front ?? back ?? "Picture"
        default: return front ?? ""
        }
    }

    var isSelfGraded: Bool { !["mc", "order"].contains(type) }
}

/// A set with all its cards — `GET /flashcards/sets/<id>`, and what is cached.
struct FlashSet: Codable, Identifiable, Equatable {
    var id: Int
    var subjectId: Int
    var subject: String
    var slug: String
    var name: String
    var source: String
    var lang: String
    var dir: String
    var updatedAt: String?
    var cards: [FlashCard]

    enum CodingKeys: String, CodingKey {
        case id, subject, slug, name, source, lang, dir, cards
        case subjectId = "subject_id", updatedAt = "updated_at"
    }

    init(id: Int, subjectId: Int, subject: String, slug: String = "", name: String,
         source: String = "", lang: String = "", dir: String = "ltr",
         updatedAt: String? = nil, cards: [FlashCard] = []) {
        self.id = id; self.subjectId = subjectId; self.subject = subject; self.slug = slug
        self.name = name; self.source = source; self.lang = lang; self.dir = dir
        self.updatedAt = updatedAt; self.cards = cards
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        subjectId = try c.decodeIfPresent(Int.self, forKey: .subjectId) ?? 0
        subject = try c.decodeIfPresent(String.self, forKey: .subject) ?? ""
        slug = try c.decodeIfPresent(String.self, forKey: .slug) ?? ""
        name = try c.decode(String.self, forKey: .name)
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
        lang = try c.decodeIfPresent(String.self, forKey: .lang) ?? ""
        dir = try c.decodeIfPresent(String.self, forKey: .dir) ?? "ltr"
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
        cards = try c.decodeIfPresent([FlashCard].self, forKey: .cards) ?? []
    }

    var isRTL: Bool { dir == "rtl" }
}

/// One question in a round: a card and which of its items is asked.
struct StudyItem: Identifiable, Equatable {
    let id = UUID()
    var setId: Int
    var setName: String
    var dir: String
    var card: FlashCard
    var item: String
    var progress: FlashProgress?

    var isRTL: Bool { dir == "rtl" }
}

enum StudyMode: String, CaseIterable, Identifiable {
    case smart, all, exam
    var id: String { rawValue }
    var label: String {
        switch self {
        case .smart: return "Spaced review"
        case .all: return "All cards"
        case .exam: return "Exam"
        }
    }
}

enum FlashTypes {
    static let all = ["basic", "image", "cloze", "mc", "order", "typed", "occlusion"]
    static func label(_ t: String) -> String {
        switch t {
        case "basic": return "Basic"
        case "image": return "Picture"
        case "cloze": return "Fill the gap"
        case "mc": return "Multiple choice"
        case "order": return "Order"
        case "typed": return "Write it out"
        case "occlusion": return "Labelled picture"
        default: return t
        }
    }
}

// MARK: - Helpers shared by study and editor

enum FlashDates {
    private static let parser: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let writer: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss'+00:00'"
        return f
    }()

    static func parse(_ s: String) -> Date? {
        parser.date(from: s) ?? fractional.date(from: s)
    }

    /// The Mac's own spelling (`_iso`: UTC, seconds, "+00:00"), so a value the
    /// phone wrote and one the Mac wrote compare the same way.
    static func iso(_ d: Date) -> String { writer.string(from: d) }
}

enum Cloze {
    static let regex = try! NSRegularExpression(pattern: "\\{\\{(.+?)\\}\\}",
                                                options: [.dotMatchesLineSeparators])

    /// The gaps' answers, in order.
    static func gaps(_ text: String) -> [String] {
        let ns = text as NSString
        return regex.matches(in: text, range: NSRange(location: 0, length: ns.length))
            .map { ns.substring(with: $0.range(at: 1)) }
    }

    /// The text with gap `hide` shown as "[…]" and every other gap's answer
    /// in place. `hide == nil` shows them all (the editor's one-line title).
    static func masked(_ text: String, hide: Int?, reveal: Bool = false) -> String {
        let ns = text as NSString
        var out = ""
        var cursor = 0
        for (i, m) in regex.matches(in: text, range: NSRange(location: 0, length: ns.length)).enumerated() {
            out += ns.substring(with: NSRange(location: cursor, length: m.range.location - cursor))
            let answer = ns.substring(with: m.range(at: 1))
            if i == hide { out += reveal ? "[\(answer)]" : "[ … ]" } else { out += answer }
            cursor = m.range.location + m.range.length
        }
        out += ns.substring(from: cursor)
        return out
    }
}

enum TypedCheck {
    /// Hebrew points and cantillation (U+0591–U+05C7) are not what is being
    /// tested — "שָׁלוֹם" and "שלום" are the same answer.
    static func strip(_ s: String) -> String {
        String(String.UnicodeScalarView(s.unicodeScalars.filter {
            !(0x0591...0x05C7).contains($0.value) || $0.value == 0x05BE || $0.value == 0x05C0
                || $0.value == 0x05C3 || $0.value == 0x05C6
        }))
    }

    static func normal(_ word: String) -> String {
        strip(word).lowercased().trimmingCharacters(in: .punctuationCharacters.union(.symbols))
    }

    /// The answer's words, each marked whether the typed text contains it —
    /// matched in order, so a word typed twice only counts once.
    /// One array per line of the answer, so a verse keeps its line breaks.
    static func marks(answer: String, typed: String) -> [[(word: String, hit: Bool)]] {
        var pool: [String: Int] = [:]
        for w in typed.split(whereSeparator: { $0.isWhitespace }) {
            let n = normal(String(w))
            if !n.isEmpty { pool[n, default: 0] += 1 }
        }
        return answer.components(separatedBy: "\n").map { line in
            line.split(whereSeparator: { $0.isWhitespace }).map { raw in
                let word = String(raw)
                let n = normal(word)
                if n.isEmpty { return (word, true) }
                if let c = pool[n], c > 0 { pool[n] = c - 1; return (word, true) }
                return (word, false)
            }
        }
    }
}
