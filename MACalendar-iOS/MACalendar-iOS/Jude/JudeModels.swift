import Foundation

// MARK: - Jude — the wire contract
//
// Jude is a separate repository (a RAG pipeline over ~289,000 Sefaria
// passages) running beside the assistant on the Mac. The phone never talks to
// it directly: it goes through the assistant's own API, over the same tailnet,
// with the same key, and gets back the NDJSON stream `/voice/stream` uses.
//
// Everything in this file is the shape of that wire and nothing else.
// `assistant/jude/ARCHITECTURE.md` is the contract these types are built to —
// if a field here has no counterpart there, it is drift, not a feature.
//
// These lived in `API/Models.swift` until 2026-09-17, alongside the calendar's
// own types. They moved because Jude is one guest system with one home: the
// models, the calls and the views are now all under `Jude/`, so a change to
// Jude's protocol touches one folder instead of four files in three.

/// What the Mac can offer for Jude right now, from `GET /jude/status` — the
/// one route that never errors.
///
/// `ready` is NOT `running`. An integration that autostarts is ready before
/// its server is up: the first question is what starts it, and that first
/// question can take two minutes while the index loads. A surface that waits
/// for `running` before letting you type would never let you type.
///
/// `reason` is the sentence to show when `ready` is false — never empty in
/// that case, always empty otherwise. "Not installed" is a normal answer with
/// something to do about it, not an error.
struct JudeStatus: Decodable, Equatable {
    var name: String = ""
    var label: String = "Jude"
    var enabled: Bool = false
    var installed: Bool = false
    var running: Bool = false
    var ready: Bool = false
    var path: String = ""
    var port: Int = 0
    var repo: String = ""
    var reason: String = ""
    var model: String = ""
    var cloud: Bool = false
    var gated: Bool = false
    var priority: String = ""

    enum CodingKeys: String, CodingKey {
        case name, label, enabled, installed, running, ready, path, port
        case repo, reason, model, cloud, gated, priority
    }

    /// Every field has a default because `GET /jude/status` answers with
    /// whatever it knows: the "Jude isn't configured here" branch on the Mac
    /// sends five keys, not fourteen. A strict decode would turn the one route
    /// designed never to fail into the one that always does.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func str(_ k: CodingKeys) -> String { (try? c.decode(String.self, forKey: k)) ?? "" }
        func flag(_ k: CodingKeys) -> Bool { (try? c.decode(Bool.self, forKey: k)) ?? false }
        name = str(.name)
        label = (try? c.decode(String.self, forKey: .label)) ?? "Jude"
        enabled = flag(.enabled)
        installed = flag(.installed)
        running = flag(.running)
        ready = flag(.ready)
        path = str(.path)
        port = (try? c.decode(Int.self, forKey: .port)) ?? 0
        repo = str(.repo)
        reason = str(.reason)
        model = str(.model)
        cloud = flag(.cloud)
        gated = flag(.gated)
        priority = str(.priority)
    }

    /// For the locally-built "your Mac isn't reachable" status.
    init(ready: Bool, reason: String, repo: String = "") {
        self.ready = ready
        self.reason = reason
        self.repo = repo
    }
}

// MARK: - Sources

/// A retrieved passage. Jude's convention is that every answer cites its
/// sources and every source links back to Sefaria, which is what makes an
/// answer checkable rather than something to take on faith — so the phone
/// shows them rather than just the prose.
struct JudeSource: Decodable, Identifiable {
    var ref: String
    var book: String = ""
    var category: String = ""
    var enText: String = ""
    var heText: String = ""
    var score: Double?
    /// Present ONLY for a detected halachic topic, where retrieval is dual:
    /// primaries come from the topic's canonical hierarchy (Torah → Mishnah →
    /// Talmud → Rambam → Shulchan Arukh) and are cited first. `nil` therefore
    /// means "this answer had no halachic topic", which is a third state, not
    /// a false — the UI draws one flat list for it rather than an empty
    /// "Primary Sources" heading.
    var isPrimary: Bool?
    /// Sources mode only: the category the router *planned* to draw from,
    /// which is what that grid groups by.
    var plannedCategory: String = ""

    /// Identity is per-instance, not per-ref: a `tool_call` can append a
    /// passage the retrieval step already returned, and two rows with the same
    /// `id` make SwiftUI's `ForEach` drop one and animate the other wrongly.
    private let localID = UUID()
    var id: UUID { localID }

    enum CodingKeys: String, CodingKey {
        case ref, book, category, score
        case enText = "en_text"
        case heText = "he_text"
        case isPrimary = "is_primary"
        case plannedCategory = "planned_category"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ref = (try? c.decode(String.self, forKey: .ref)) ?? ""
        book = (try? c.decode(String.self, forKey: .book)) ?? ""
        category = (try? c.decode(String.self, forKey: .category)) ?? ""
        enText = (try? c.decode(String.self, forKey: .enText)) ?? ""
        heText = (try? c.decode(String.self, forKey: .heText)) ?? ""
        score = try? c.decode(Double.self, forKey: .score)
        isPrimary = try? c.decode(Bool.self, forKey: .isPrimary)
        plannedCategory = (try? c.decode(String.self, forKey: .plannedCategory)) ?? ""
    }

    var hasHebrew: Bool { !heText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    /// The retrieval score is a DISTANCE — smaller is closer — so the match
    /// percentage counts down from it rather than up.
    var matchPercent: Int? {
        guard let score else { return nil }
        return Int((1 - min(max(score, 0), 1)) * 100)
    }

    /// Where this passage lives on Sefaria, per `ARCHITECTURE.md`'s rules.
    ///
    /// Strip surrounding brackets, split the trailing section off the book
    /// name, `Book Name` → `Book_Name`, `1:2:3` → `1.2.3`.
    ///
    /// **Talmud is the exception.** Our coordinates are chapter-based and
    /// Sefaria addresses Talmud by daf (2a, 3b…), so `Shabbat 3.1` is not a
    /// page there — it is a 404 or, worse, a different passage. A Talmud ref
    /// links to the tractate overview, which is always right if less precise.
    var sefariaURL: URL? {
        let cleaned = ref.trimmingCharacters(in: CharacterSet(charactersIn: "[] "))
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return nil }

        func searchURL() -> URL? {
            let q = cleaned.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            return URL(string: "https://www.sefaria.org/search#q=\(q)")
        }

        // Split on the LAST space: "Shulchan Arukh, Orach Chayim 1:2" is a
        // three-word book plus one section, not a book plus three sections.
        guard let lastSpace = cleaned.lastIndex(of: " ") else { return searchURL() }
        let book = String(cleaned[cleaned.startIndex..<lastSpace])
        let section = String(cleaned[cleaned.index(after: lastSpace)...])
            .replacingOccurrences(of: ":", with: ".")
        guard !book.isEmpty, !section.isEmpty else { return searchURL() }

        let encodedBook = book.replacingOccurrences(of: " ", with: "_")
            .addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? book
        if category == "Talmud" {
            return URL(string: "https://www.sefaria.org/\(encodedBook)")
        }
        let encodedSection = section
            .addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? section
        return URL(string: "https://www.sefaria.org/\(encodedBook).\(encodedSection)")
            ?? searchURL()
    }
}

// MARK: - The trace

/// One pipeline step, for the trace: `{module, duration_ms, result{…}}`.
///
/// `result` is deliberately untyped. Each module puts different keys in it
/// (Router: tier/categories/search_queries/depth; Retrieval: sources_found/
/// top_source; Filter: kept/dropped) and Jude is a separate project still
/// being worked on — a struct per module here would go stale the first time
/// one of them learned a new field, and would fail the whole decode with it.
struct JudeStep: Decodable, Identifiable {
    var module: String = ""
    var durationMs: Double?
    var result: [String: JudeJSON] = [:]

    private let localID = UUID()
    var id: UUID { localID }

    enum CodingKeys: String, CodingKey {
        case module, result
        case durationMs = "duration_ms"
    }

    /// Hand-written for the same reason the events are: a synthesised decoder
    /// does NOT fall back to a property's default value when a key is absent,
    /// it throws — and one step missing `result` would take the whole `steps`
    /// array down with it, leaving a blank trace instead of a partial one.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        module = (try? c.decode(String.self, forKey: .module)) ?? ""
        durationMs = try? c.decode(Double.self, forKey: .durationMs)
        result = (try? c.decode([String: JudeJSON].self, forKey: .result)) ?? [:]
    }
}

/// A tool Jude reached for mid-synthesis. `new_sources` are merged into the
/// answer's source list as they arrive — they are as citable as the ones
/// retrieval found, and an answer that quotes a passage the source list
/// doesn't show is exactly the unfalsifiable answer Jude exists to avoid.
struct JudeToolCall: Identifiable {
    let tool: String
    let args: [String: JudeJSON]
    let resultSummary: String
    let id = UUID()

    /// The one argument worth showing in a one-line trace row.
    var headlineArg: String {
        for key in ["query", "ref", "text"] {
            if let v = args[key]?.stringValue, !v.isEmpty { return v }
        }
        return ""
    }
}

/// The breakdown on the `done` event. Every leg of the pipeline, in ms.
struct JudeTiming: Decodable {
    var routeMs: Double?
    var retrieveMs: Double?
    var filterMs: Double?
    var synthFirstTokenMs: Double?
    var synthTotalMs: Double?
    var totalMs: Double?

    enum CodingKeys: String, CodingKey {
        case routeMs = "route_ms"
        case retrieveMs = "retrieve_ms"
        case filterMs = "filter_ms"
        case synthFirstTokenMs = "synth_first_token_ms"
        case synthTotalMs = "synth_total_ms"
        case totalMs = "total_ms"
    }

    /// The legs worth a row of their own, in pipeline order, already labelled.
    /// Nil legs are dropped rather than shown as "—": Jude omits a leg it
    /// skipped, and a zero would read as "instant" instead of "didn't happen".
    var steps: [JudeTimingStep] {
        let legs: [(String, Double?)] = [("Route", routeMs), ("Retrieve", retrieveMs),
                                         ("Filter", filterMs), ("Synthesis", synthTotalMs)]
        return legs.compactMap { leg in
            leg.1.map { JudeTimingStep(name: leg.0, ms: $0) }
        }
    }
}

struct JudeTimingStep: Identifiable {
    let name: String
    let ms: Double
    var id: String { name }
}

/// ms → "840ms" / "31.4s". Seconds once past a second, because "31392ms" is a
/// number you have to parse and "31.4s" is one you read.
func judeFormatMs(_ ms: Double?) -> String {
    guard let ms else { return "" }
    return ms < 1000 ? "\(Int(ms))ms" : String(format: "%.1fs", ms / 1000)
}

// MARK: - The stream

/// One NDJSON line from `POST /jude/chat`. The server passes Jude's event
/// types through unchanged: stage, meta, token, tool_call, clarification,
/// topic_pivot, done, error.
///
/// Every field is optional because this is a union of eight shapes on one
/// line-oriented wire, and an unknown eighth event must not fail the decode
/// and take the stream down with it.
struct JudeEvent: Decodable {
    var type: String = ""

    // stage
    var name: String = ""

    // meta
    var chatId: String?
    var sources: [JudeSource] = []
    var steps: [JudeStep] = []
    var mode: String = ""
    var studyPoolSize: Int?
    var halachicTopic: String = ""
    var halachicLabel: String = ""
    var halachicSeder: String = ""

    // token
    var text: String = ""

    // tool_call
    var tool: String = ""
    var args: [String: JudeJSON] = [:]
    var resultSummary: String = ""
    var newSources: [JudeSource] = []

    // clarification
    var question: String = ""
    var options: [JudeClarificationOption] = []

    // topic_pivot
    var previousTopic: String = ""
    var candidateTopic: String = ""

    // done / error
    var timing: JudeTiming?
    var message: String = ""

    enum CodingKeys: String, CodingKey {
        case type, name, text, message, sources, steps, mode, question, options
        case tool, args, timing
        case chatId = "chat_id"
        case studyPoolSize = "study_pool_size"
        case halachicTopic = "halachic_topic"
        case halachicLabel = "halachic_label"
        case halachicSeder = "halachic_seder"
        case resultSummary = "result_summary"
        case newSources = "new_sources"
        case previousTopic = "previous_topic"
        case candidateTopic = "candidate_topic"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func str(_ k: CodingKeys) -> String { (try? c.decode(String.self, forKey: k)) ?? "" }
        type = str(.type)
        name = str(.name)
        chatId = try? c.decode(String.self, forKey: .chatId)
        sources = (try? c.decode([JudeSource].self, forKey: .sources)) ?? []
        steps = (try? c.decode([JudeStep].self, forKey: .steps)) ?? []
        mode = str(.mode)
        studyPoolSize = try? c.decode(Int.self, forKey: .studyPoolSize)
        halachicTopic = str(.halachicTopic)
        halachicLabel = str(.halachicLabel)
        halachicSeder = str(.halachicSeder)
        text = str(.text)
        tool = str(.tool)
        args = (try? c.decode([String: JudeJSON].self, forKey: .args)) ?? [:]
        resultSummary = str(.resultSummary)
        newSources = (try? c.decode([JudeSource].self, forKey: .newSources)) ?? []
        question = str(.question)
        options = (try? c.decode([JudeClarificationOption].self, forKey: .options)) ?? []
        previousTopic = str(.previousTopic)
        candidateTopic = str(.candidateTopic)
        timing = try? c.decode(JudeTiming.self, forKey: .timing)
        message = str(.message)
    }

    var toolCall: JudeToolCall {
        JudeToolCall(tool: tool, args: args, resultSummary: resultSummary)
    }
}

/// One way Jude offers to read an ambiguous question.
///
/// Decodes from EITHER a bare string or `{label, prompt}`: Jude's own web UI
/// reads `opt.label` and `opt.prompt`, while `ARCHITECTURE.md` writes the
/// field as `options[]` with no shape. Accepting both costs six lines and
/// means the phone keeps working whichever one a future Jude sends.
struct JudeClarificationOption: Decodable, Identifiable {
    let label: String
    /// What to actually ask when this option is tapped — usually a fuller
    /// rewrite of the question, not the button's own text.
    let prompt: String
    let id = UUID()

    enum CodingKeys: String, CodingKey { case label, prompt }

    init(from decoder: Decoder) throws {
        if let single = try? decoder.singleValueContainer(),
           let raw = try? single.decode(String.self) {
            label = raw
            prompt = raw
            return
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let text = (try? c.decode(String.self, forKey: .label)) ?? ""
        label = text
        prompt = (try? c.decode(String.self, forKey: .prompt)) ?? text
    }
}

// MARK: - Past conversations

/// A row in `GET /jude/chats`.
struct JudeChatSummary: Decodable, Identifiable {
    var id: String = ""
    var title: String = ""
    var mode: String = ""
    var createdAt: String = ""
    var user: String = ""

    enum CodingKeys: String, CodingKey {
        case id, title, mode, user
        case createdAt = "created_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // `id` may be a number on the wire — Jude's store numbers its rows and
        // only the web UI's `==` hid that, since JS compares '3' and 3 happily.
        if let s = try? c.decode(String.self, forKey: .id) { id = s }
        else if let n = try? c.decode(Int.self, forKey: .id) { id = String(n) }
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        mode = (try? c.decode(String.self, forKey: .mode)) ?? ""
        createdAt = (try? c.decode(String.self, forKey: .createdAt)) ?? ""
        user = (try? c.decode(String.self, forKey: .user)) ?? ""
    }

    /// 📖 study · 📋 sources · nothing for plain Q&A, mirroring the badge the
    /// web UI puts on a conversation's title.
    var modeGlyph: String {
        switch mode {
        case "study": return "📖"
        case "sources": return "📋"
        default: return ""
        }
    }
}

/// One message from `GET /jude/chats/<id>/history`.
struct JudeHistoryMessage: Decodable, Identifiable {
    var role: String = ""
    var content: String = ""
    var sources: [JudeSource] = []
    let id = UUID()

    enum CodingKeys: String, CodingKey { case role, content, sources }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        role = (try? c.decode(String.self, forKey: .role)) ?? ""
        content = (try? c.decode(String.self, forKey: .content)) ?? ""
        sources = (try? c.decode([JudeSource].self, forKey: .sources)) ?? []
    }
}

// MARK: - Untyped JSON

/// Just enough JSON to carry a trace step's `result` and a tool call's `args`
/// across without knowing their shape. See `JudeStep` for why that matters.
enum JudeJSON: Decodable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case array([JudeJSON])
    case object([String: JudeJSON])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JudeJSON].self) { self = .array(v) }
        else if let v = try? c.decode([String: JudeJSON].self) { self = .object(v) }
        else { self = .null }
    }

    /// A value's display text. Numbers lose a trailing ".0" — `kept: 8` came
    /// off the wire as a Double and read as "8.0 kept" in the trace.
    var stringValue: String? {
        switch self {
        case .string(let s): return s
        case .number(let n): return n == n.rounded() ? String(Int(n)) : String(n)
        case .bool(let b): return b ? "true" : "false"
        default: return nil
        }
    }

    var intValue: Int? {
        switch self {
        case .number(let n): return Int(n)
        case .string(let s): return Int(s)
        default: return nil
        }
    }

    /// The elements of an array, as display strings — Router's `categories`
    /// and `search_queries` are both of these.
    var stringArray: [String] {
        guard case .array(let items) = self else { return [] }
        return items.compactMap { $0.stringValue }
    }
}
