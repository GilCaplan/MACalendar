import Foundation
import UIKit

struct CalendarEvent: Identifiable, Codable, Equatable {
    // var, not let: a row created offline carries a temporary negative id
    // that is rewritten to the Mac's real id once the create syncs.
    var id: Int
    var title: String
    var date: String
    var startTime: String
    var endTime: String
    var attendees: String
    var location: String
    var description: String
    var color: String
    var recurrence: String
    var recurrenceEnd: String
    // Sync bookkeeping — 'local' | 'ics' | 'outlook'. ICS-sourced events are
    // read-only (no write endpoint behind a subscription link); Outlook
    // events stay editable when two-way sync is on.
    var source: String? = nil
    var externalSource: String? = nil
    var externalId: String? = nil
    /// The Mac's version stamp. Quoted back on an edit so the Mac can refuse a
    /// change made from a copy that has since been edited there.
    var updatedAt: String? = nil

    // Pre-event reminders. The server computes the policy (assistant/notify.py)
    // and embeds the verdict in every event payload; the phone only schedules
    // what it is told. All optional so caches written before the feature
    // existed decode unchanged.
    /// Stored per-event override: nil = inherit category/default, 0 = never.
    var reminderMinutes: Int? = nil
    /// When the reminder should fire — ISO local datetime ("2026-09-06T18:30",
    /// no zone; the Mac and phone share one), or nil for no reminder.
    var notifyAt: String? = nil
    /// Why there is no reminder despite a lead being set:
    /// "shabbat" | "yom_tov:<name>" | "clamped_past_start".
    var notifySuppressedReason: String? = nil

    enum CodingKeys: String, CodingKey {
        case id, title, date, color, recurrence, attendees, location, description, source
        case startTime      = "start_time"
        case endTime        = "end_time"
        case recurrenceEnd  = "recurrence_end"
        case externalSource = "external_source"
        case externalId     = "external_id"
        case updatedAt      = "updated_at"
        case reminderMinutes        = "reminder_minutes"
        case notifyAt               = "notify_at"
        case notifySuppressedReason = "notify_suppressed_reason"
    }

    var displayTime: String {
        guard !startTime.isEmpty else { return "" }
        return endTime.isEmpty ? startTime : "\(startTime) – \(endTime)"
    }

    var isReadOnly: Bool { source == "ics" }
}

struct Todo: Identifiable, Codable, Equatable {
    // var, not let: a row created offline carries a temporary negative id
    // that is rewritten to the Mac's real id once the create syncs.
    var id: Int
    var title: String
    var list: String
    var completed: Int
    var priority: String
    var dueDate: String
    var tags: [String]
    /// How many of the thing. "buy pasta times 5" is one task with quantity 5,
    /// not five identical tasks — which is what it used to be.
    var quantity: Int = 1

    /// The Mac's version stamp, quoted back on an edit so a change made from a
    /// stale copy is refused rather than silently overwriting a newer one.
    var updatedAt: String? = nil

    enum CodingKeys: String, CodingKey {
        case id, title, list, completed, priority, tags, quantity
        case dueDate = "due_date"
        case updatedAt = "updated_at"
    }

    init(id: Int, title: String, list: String, completed: Int,
         priority: String, dueDate: String, tags: [String] = [],
         quantity: Int = 1) {
        self.id = id; self.title = title; self.list = list
        self.completed = completed; self.priority = priority
        self.dueDate = dueDate; self.tags = tags
        self.quantity = max(1, quantity)
    }

    // Tolerant decode: older cached JSON (and older servers) have no `tags`.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id        = try c.decode(Int.self,    forKey: .id)
        title     = try c.decode(String.self, forKey: .title)
        list      = try c.decode(String.self, forKey: .list)
        completed = try c.decode(Int.self,    forKey: .completed)
        priority  = try c.decodeIfPresent(String.self, forKey: .priority) ?? "none"
        dueDate   = try c.decodeIfPresent(String.self, forKey: .dueDate)  ?? ""
        tags      = try c.decodeIfPresent([String].self, forKey: .tags)   ?? []
        // Absent from older servers and from every row cached before the
        // column existed, so a missing value means one, not zero.
        quantity  = max(1, try c.decodeIfPresent(Int.self, forKey: .quantity) ?? 1)
    }

    var isDone: Bool { completed != 0 }

    /// Shown next to the title only when there is more than one.
    var quantityLabel: String? { quantity > 1 ? "×\(quantity)" : nil }

    func hasTag(_ name: String) -> Bool {
        tags.contains { $0.caseInsensitiveCompare(name) == .orderedSame }
    }
}

/// A tag in the shared palette (server table `todo_tags`).
struct TodoTag: Identifiable, Codable, Equatable, Hashable {
    let name: String
    var color: String
    var builtin: Int

    var id: String { name }

    enum CodingKeys: String, CodingKey { case name, color, builtin }

    init(name: String, color: String = "", builtin: Int = 0) {
        self.name = name; self.color = color; self.builtin = builtin
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name    = try c.decode(String.self, forKey: .name)
        color   = try c.decodeIfPresent(String.self, forKey: .color) ?? ""
        builtin = try c.decodeIfPresent(Int.self, forKey: .builtin) ?? 0
    }

    /// Fallback palette so tags still look distinct when the server sends no color.
    static let defaultPalette: [String: String] = [
        "coursework": "#7c6ff0", "groceries": "#3fb27f", "errands": "#e0a020",
        "work": "#4a9edd", "personal": "#e0608a",
    ]

    var hexColor: String {
        if !color.isEmpty { return color }
        if let c = Self.defaultPalette[name.lowercased()] { return c }
        // Deterministic hue from the name so custom tags get a stable color.
        let h = name.unicodeScalars.reduce(0) { ($0 &* 31 &+ Int($1.value)) & 0xffff }
        let hue = Double(h % 360) / 360.0
        return UIColor(hue: hue, saturation: 0.55, brightness: 0.8, alpha: 1).hexString
    }
}

extension UIColor {
    var hexString: String {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        getRed(&r, green: &g, blue: &b, alpha: &a)
        return String(format: "#%02x%02x%02x", Int(r * 255), Int(g * 255), Int(b * 255))
    }
}

struct VoiceResponse: Codable {
    let message: String
    let actions: [String]
    let refresh: String
    let parse: String           // "rule" | "hybrid" | "llm" | "error"
    let verifyToken: String?    // present only for "rule" responses; poll /voice/verify/<token>
    // Added with the vocabulary / thinking-trace work. All optional so older
    // servers (and the empty-transcript reply) still decode.
    let transcript: String?          // after stop-word strip + vocab auto-correct
    let originalTranscript: String?  // raw Whisper output
    let corrections: [VocabCorrection]?
    let trace: [TraceStep]?
    /// X1…X4 — the value each stage handed the next. Optional so an older
    /// server still decodes.
    let boundaries: [TraceBoundary]?
    let memoryId: Int?               // row in the command memory (for feedback)
    let pendingId: Int?              // set when the command was queued (LLM offline/slow)
    let uncertainWords: [UncertainWord]?
    // parse == "needs_edit": the host doubts these words and executed nothing —
    // show the transcription editor and resubmit. Same list as uncertainWords,
    // but its presence (with the parse value) is the signal to gate.
    let needsEdit: [UncertainWord]?
    // parse == "confirm_create": the words were a question about creating
    // something ("should I add yoga tomorrow?"), so the host parsed it and
    // executed NOTHING. Show the proposal, then POST the answer to
    // /voice/confirm with this token. (DEVQA Q9, Gil 2026-09-07.)
    let confirmToken: String?
    let proposal: [ProposedCreate]?
    let brain: String?               // assistant.trace.BRAIN_VERSION that answered

    enum CodingKeys: String, CodingKey {
        case message, actions, refresh, parse, transcript, corrections, trace, brain
        case boundaries
        case verifyToken = "verify_token"
        case originalTranscript = "original_transcript"
        case memoryId = "memory_id"
        case pendingId = "pending_id"
        case uncertainWords = "uncertain_words"
        case needsEdit = "needs_edit"
        case confirmToken = "confirm_token"
        case proposal
    }
}

/// One thing a confirm_create proposal would create. The host also sends a
/// ready-to-POST `body`, which this client deliberately does not decode: the
/// answer travels by token through /voice/confirm, so the phone never needs to
/// hold — or could accidentally alter — the fields being created.
struct ProposedCreate: Codable, Identifiable {
    var id: String { kind + summary }
    let kind: String       // "event" | "todo"
    let summary: String    // "\u{201C}Yoga\u{201D} on Tuesday, Sep 8, 2026 7 AM\u{2013}8 AM"
}

/// The reply to POST /voice/confirm.
struct ConfirmResponse: Codable {
    let ok: Bool
    let accepted: Bool
    let refresh: String
    let message: String
}

/// A word the assistant isn't sure about — near-miss of a vocab word, or an
/// unknown capitalised token that's probably a name.
struct UncertainWord: Codable, Identifiable, Equatable {
    var id: String { heard }
    let heard: String
    let candidate: String?
    let score: Double
    let reason: String   // "near-miss" | "unknown-name"
}

/// One stage of the assistant's "thinking" — streamed live from POST /voice/stream
/// and also returned in full as `VoiceResponse.trace`.
struct TraceStep: Codable, Identifiable, Equatable {
    var id: String { "\(atMs)-\(stage)-\(title)" }
    let stage: String     // stt | vocab | rule | memory | llm | validate | execute | verify | done | error
    let title: String
    let detail: String
    let ms: Int
    let atMs: Int
    let ok: Bool

    /// Which non-object outcome this step reported, when it reported one:
    /// "bad_item" (the words reached the converter damaged) or "not_an_ask"
    /// (read correctly, and simply not calendar work). Only one of the two is
    /// a defect, and the timeline has to be able to say which.
    ///
    /// Lifted out of the step's `data` bag rather than decoding all of it:
    /// `data` is heterogeneous (numbers, lists, strings), and a Codable that
    /// tried to model it would break the first time a stage added a field.
    let fastruleResult: String?

    enum CodingKeys: String, CodingKey {
        case stage, title, detail, ms, ok, data
        case atMs = "at_ms"
    }

    private enum DataKeys: String, CodingKey {
        case fastruleResult = "fastrule_result"
    }

    /// The memberwise init, restored by hand. Declaring `init(from:)` below
    /// suppresses the one Swift would synthesise, and `VoiceButton` builds
    /// steps directly in ten places — the client's own "Sending", "Retrying",
    /// "Saved for later" entries, which never come from the server and so have
    /// no `fastruleResult`.
    init(stage: String, title: String, detail: String = "", ms: Int = 0,
         atMs: Int = 0, ok: Bool = true, fastruleResult: String? = nil) {
        self.stage = stage
        self.title = title
        self.detail = detail
        self.ms = ms
        self.atMs = atMs
        self.ok = ok
        self.fastruleResult = fastruleResult
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        stage = try c.decode(String.self, forKey: .stage)
        title = try c.decode(String.self, forKey: .title)
        detail = (try? c.decode(String.self, forKey: .detail)) ?? ""
        ms = (try? c.decode(Int.self, forKey: .ms)) ?? 0
        atMs = (try? c.decode(Int.self, forKey: .atMs)) ?? 0
        ok = (try? c.decode(Bool.self, forKey: .ok)) ?? true
        let d = try? c.nestedContainer(keyedBy: DataKeys.self, forKey: .data)
        fastruleResult = try? d?.decode(String.self, forKey: .fastruleResult)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(stage, forKey: .stage)
        try c.encode(title, forKey: .title)
        try c.encode(detail, forKey: .detail)
        try c.encode(ms, forKey: .ms)
        try c.encode(atMs, forKey: .atMs)
        try c.encode(ok, forKey: .ok)
    }

    static func == (a: TraceStep, b: TraceStep) -> Bool { a.id == b.id && a.detail == b.detail }
}

/// One value handed from one stage to the next — X1, X2, X3, X4.
///
/// The Mac panel has shown these since 2026-09-10 and the phone did not, which
/// is backwards: most commands are spoken to the phone. The server already
/// sent them (the voice routes return the engine's whole result); nothing here
/// decoded them.
struct TraceBoundary: Codable, Identifiable, Equatable {
    let label: String      // "X1" … "X4"
    let value: String      // what it carried, rendered for a human
    let detail: String?    // what that boundary IS, from the stage contract
    let atMs: Int?

    var id: String { label }

    enum CodingKeys: String, CodingKey {
        case label, value, detail
        case atMs = "at_ms"
    }
}

struct VocabCorrection: Codable, Identifiable, Equatable {
    var id: String { from + "→" + to }
    let from: String
    let to: String
    let reason: String    // "alias" | "fuzzy"
    let score: Double
}

struct VocabWord: Codable, Identifiable, Equatable {
    var id: String { word }
    let word: String
    let aliases: [String]
    let hits: Int
    /// What this word implies about a task or event — "Coursework" for a
    /// course name. Used to tag tasks and colour events.
    var label: String = ""
    /// What the shorthand stands for. Never substituted into your text; it is
    /// context for labelling and for the model, so the words stay yours.
    var expandsTo: String = ""

    enum CodingKeys: String, CodingKey {
        case word, aliases, hits, label
        case expandsTo = "expands_to"
    }

    // Both fields arrived after the first 374 words were saved, so most
    // entries on disk have neither and a strict decode would fail on them.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        word      = try c.decode(String.self, forKey: .word)
        aliases   = try c.decodeIfPresent([String].self, forKey: .aliases) ?? []
        hits      = try c.decodeIfPresent(Int.self, forKey: .hits) ?? 0
        label     = try c.decodeIfPresent(String.self, forKey: .label) ?? ""
        expandsTo = try c.decodeIfPresent(String.self, forKey: .expandsTo) ?? ""
    }

    init(word: String, aliases: [String] = [], hits: Int = 0,
         label: String = "", expandsTo: String = "") {
        self.word = word; self.aliases = aliases; self.hits = hits
        self.label = label; self.expandsTo = expandsTo
    }

    /// True when the word does more than fix a mishearing.
    var carriesMeaning: Bool { !label.isEmpty || !expandsTo.isEmpty }
}

struct VocabRecent: Codable, Identifiable {
    var id: Double { ts }
    let ts: Double
    let source: String
    let original: String
    let corrected: String
    let corrections: [VocabCorrection]
}

struct VocabState: Codable {
    let autoCorrect: Bool
    let learnAliases: Bool
    let threshold: Double
    let onboarded: Bool?
    let words: [VocabWord]
    let recent: [VocabRecent]

    enum CodingKeys: String, CodingKey {
        case words, recent, threshold, onboarded
        case autoCorrect = "auto_correct"
        case learnAliases = "learn_aliases"
    }
}

struct VocabQuestion: Codable, Identifiable {
    let id: String
    let question: String
    let hint: String
    let examples: [String]
}

struct VocabPreset: Codable, Identifiable {
    let id: String
    let label: String
    let words: [String]
    let already: Int
}

struct VocabOnboarding: Codable {
    let done: Bool
    let questions: [VocabQuestion]
    let presets: [VocabPreset]
    let wordCount: Int
    enum CodingKeys: String, CodingKey {
        case done, questions, presets
        case wordCount = "word_count"
    }
}

/// Returned by GET /voice/verify/<token>
struct VerifyResult: Codable {
    let pending: Bool?          // true = LLM not done yet
    let ok: Bool?               // true = no correction needed
    let severity: String?       // "minor" | "major"
    let patch: [String: String]? // minor: fields to PATCH on existing record
    let action: String?         // major: corrected action name
    let parameters: [String: AnyCodable]? // major: corrected params
    let speech: String?         // TTS string for user
    let refresh: String?        // "events" | "todos" | ""
    let revert: [RevertItem]?   // destructive: rows removed, re-POST to undo
}

/// A mined new-tag proposal (GET /tags/suggestion) — consent-based growth of
/// the finite tag class set. Empty name = nothing to ask this week.
struct TagSuggestion: Codable {
    let name: String?
    let evidence: Int?
    let samples: [String]?
}

/// One row of the record behind the weekly "add 'Pharmacy' as a tag?" popup —
/// `GET /tags/suggestions/history`, newest first.
///
/// The Mac keeps the verdict for every name it has ever proposed, so a "no"
/// is never re-asked; this is the reviewable version of that record, and the
/// only place an answer can be changed after the fact.
struct TagSuggestionRecord: Codable, Identifiable, Equatable {
    /// Capitalised by the server; also the key every write is addressed by,
    /// which is why it can serve as the identity.
    let name: String
    /// "accepted" | "refused". Anything else is a name that was asked about
    /// but never answered.
    let status: String
    /// The Mac's local ISO timestamp of the last change ("2026-09-05T12:34:56.789012").
    /// No zone: the phone and the Mac share one.
    let ts: String
    /// Folded out of the visible history. Optional so a payload from a Mac
    /// predating the flag still decodes.
    let hidden: Bool?

    var id: String { name }
    var isHidden: Bool { hidden ?? false }

    enum Verdict { case accepted, declined, pending }

    var verdict: Verdict {
        switch status {
        case "accepted": return .accepted
        case "refused":  return .declined
        default:         return .pending
        }
    }

    /// When the verdict was recorded. Nil rather than a wrong date if the
    /// stamp is in a shape neither formatter knows — the view then falls back
    /// to showing the raw string.
    var answeredAt: Date? {
        DateFormatter.macMicroseconds.date(from: ts)
            ?? DateFormatter.macSeconds.date(from: ts)
    }
}

extension DateFormatter {
    /// Python's `datetime.isoformat()` — six fractional digits, no zone.
    /// (`ReminderScheduler.parseLocal` reads the same family of stamps but is
    /// main-actor isolated, and these are decoded off the main actor.)
    static let macMicroseconds: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        return f
    }()

    /// The same stamp when the microseconds happen to be zero — Python drops
    /// the fractional part entirely in that case.
    static let macSeconds: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()
}

/// One row a destructive background patch removed. `body` is exactly what
/// POST /events / POST /todos accept, so reverting is a re-create (one tap).
struct RevertItem: Codable, Identifiable {
    var id = UUID()
    let kind: String                 // "event" | "todo"
    let body: [String: AnyCodable]
    enum CodingKeys: String, CodingKey { case kind, body }
}

struct Holiday: Codable, Equatable, Identifiable {
    var nameEn: String
    var nameHe: String
    var category: String   // "major" | "minor" | "fast" | "modern"
    var gregorianErevStart: String   // ISO date — evening-before civil date
    var gregorianEnd: String         // ISO date — last full civil day

    enum CodingKeys: String, CodingKey {
        case nameEn = "name_en"
        case nameHe = "name_he"
        case category
        case gregorianErevStart = "gregorian_erev_start"
        case gregorianEnd = "gregorian_end"
    }

    var id: String { "\(nameEn)-\(gregorianErevStart)" }

    /// True if *date* (yyyy-MM-dd) is the erev (evening-before) day of this holiday.
    func isErev(on date: String) -> Bool { date == gregorianErevStart }

    /// True if *date* (yyyy-MM-dd) falls anywhere within this holiday's span.
    func spans(_ date: String) -> Bool { date >= gregorianErevStart && date <= gregorianEnd }
}

struct HealthResponse: Codable {
    let status: String
    let llm: String
    let db: String
}

/// The `notifications` section of the Mac's config (GET /config). The server
/// is the policy brain — this is only read to render the Settings controls
/// and written back whole-field via PATCH /config.
struct NotificationsConfig: Codable, Equatable {
    var enabled: Bool
    /// THE day-panel switch — the one notification control this app shows.
    /// Shared with the Mac on purpose (Gil, 2026-09-11: "it's on or off"), so
    /// turning it off here stops the Mac's banner too.
    var dailyDigest: Bool
    /// Local "HH:MM" the panel fires at. Shown, not edited — a knob rather
    /// than another control to think about.
    var digestTime: String
    /// The lock-screen agenda card. Shared with the Mac so the two cannot
    /// disagree and the choice survives a reinstall; the phone mirrors it into
    /// `agendaCardEnabled` in UserDefaults, which is what
    /// `LiveActivityManager` reads (synchronously, offline, no server).
    var agendaCard: Bool
    var defaultLeadMinutes: Int
    /// Category name → lead minutes; 0 mutes the whole category.
    var categoryLeads: [String: Int]
    var respectObservance: Bool
    var catchUpMinutes: Int
    var sound: Bool
    var speak: Bool

    enum CodingKeys: String, CodingKey {
        case enabled, sound, speak
        case dailyDigest        = "daily_digest"
        case digestTime         = "digest_time"
        case agendaCard         = "agenda_card"
        case defaultLeadMinutes = "default_lead_minutes"
        case categoryLeads      = "category_leads"
        case respectObservance  = "respect_observance"
        case catchUpMinutes     = "catch_up_minutes"
    }

    // Tolerant decode so an older server (no notifications section yet, or a
    // partial one) still yields a usable default instead of a decode failure.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled            = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? true
        dailyDigest        = try c.decodeIfPresent(Bool.self, forKey: .dailyDigest) ?? true
        digestTime         = try c.decodeIfPresent(String.self, forKey: .digestTime) ?? "07:00"
        agendaCard         = try c.decodeIfPresent(Bool.self, forKey: .agendaCard) ?? true
        defaultLeadMinutes = try c.decodeIfPresent(Int.self,  forKey: .defaultLeadMinutes) ?? 0
        categoryLeads      = try c.decodeIfPresent([String: Int].self, forKey: .categoryLeads) ?? [:]
        respectObservance  = try c.decodeIfPresent(Bool.self, forKey: .respectObservance) ?? true
        catchUpMinutes     = try c.decodeIfPresent(Int.self,  forKey: .catchUpMinutes) ?? 10
        sound              = try c.decodeIfPresent(Bool.self, forKey: .sound) ?? true
        speak              = try c.decodeIfPresent(Bool.self, forKey: .speak) ?? false
    }
}

/// One day's panel, built entirely on the Mac — `GET /digest/upcoming`.
///
/// **The wording arrives finished.** `title` and `body` are what the
/// notification says, composed by `assistant/notify.py:build_digest`, so this
/// phone's banner and the Mac's read identically. A client that formatted its
/// own would drift the moment one of them learned about all-day events and the
/// other did not — which is why there is no formatter anywhere on this side.
struct DayDigest: Codable, Equatable, Identifiable {
    /// "YYYY-MM-DD". Also the identity: one panel per day, and the scheduled
    /// notification is keyed on it.
    var date: String
    var id: String { date }
    /// Whether the panel is switched on at all (master switch AND daily_digest).
    var enabled: Bool
    /// Local "YYYY-MM-DDTHH:MM" the panel is due, or nil when it will not fire
    /// — switched off, or held for Shabbat / yom tov.
    var firesAt: String?
    /// Why it will not fire: "shabbat", "yom_tov:<name>". nil when it will.
    var suppressedReason: String?
    var title: String
    var body: String

    enum CodingKeys: String, CodingKey {
        case date, enabled, title, body
        case firesAt          = "fires_at"
        case suppressedReason = "suppressed_reason"
    }

    // Tolerant, like NotificationsConfig: an older Mac that does not serve
    // this yet should leave the phone on what it already cached rather than
    // failing the whole decode.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date             = try c.decodeIfPresent(String.self, forKey: .date) ?? ""
        enabled          = try c.decodeIfPresent(Bool.self,   forKey: .enabled) ?? false
        firesAt          = try c.decodeIfPresent(String.self, forKey: .firesAt)
        suppressedReason = try c.decodeIfPresent(String.self, forKey: .suppressedReason)
        title            = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        body             = try c.decodeIfPresent(String.self, forKey: .body) ?? ""
    }

    init(date: String, enabled: Bool, firesAt: String?, suppressedReason: String?,
         title: String, body: String) {
        self.date = date; self.enabled = enabled; self.firesAt = firesAt
        self.suppressedReason = suppressedReason; self.title = title; self.body = body
    }
}

struct Course: Identifiable, Codable, Equatable {
    // `var`, not `let`: a row created offline is remapped in place when the Mac
    // answers with the real id (see CourseStore.remapTemporaryID), exactly as
    // Todo and CalendarEvent already are.
    var id: Int           // negative = local temp, positive = server ID
    var number: String
    var name: String
    var color: String
    var partners: [String]

    enum CodingKeys: String, CodingKey {
        case id, number, name, color, partners
    }
}

struct Assignment: Identifiable, Codable, Equatable {
    var id: Int           // negative = local temp, positive = server ID
    var courseId: Int
    var title: String
    var dueDate: String   // "YYYY-MM-DD" or ""
    // The server serializes this straight from a SQLite INTEGER column (0/1),
    // never a JSON true/false, so JSONDecoder's strict Bool decoding threw on
    // every GET /assignments — which silently broke loading (and, via the
    // try? refresh after a save, made new assignments vanish right after
    // being added). Int + isDone mirrors Todo.completed's already-correct pattern.
    var completed: Int
    var calendarEventId: Int?

    enum CodingKeys: String, CodingKey {
        case id, courseId = "course_id", title, dueDate = "due_date", completed, calendarEventId = "calendar_event_id"
    }

    var isDone: Bool { completed != 0 }
}

// Lightweight type-erased Codable value for heterogeneous JSON dicts
struct AnyCodable: Codable {
    let value: Any
    init(_ value: Any) { self.value = value }
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let v = try? c.decode(Bool.self)   { value = v; return }
        if let v = try? c.decode(Int.self)    { value = v; return }
        if let v = try? c.decode(Double.self) { value = v; return }
        if let v = try? c.decode(String.self) { value = v; return }
        if let v = try? c.decode([String].self) { value = v; return }
        value = ""
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch value {
        case let v as Bool:     try c.encode(v)
        case let v as Int:      try c.encode(v)
        case let v as Double:   try c.encode(v)
        case let v as String:   try c.encode(v)
        case let v as [String]: try c.encode(v)
        default: try c.encodeNil()
        }
    }
}

/// A vocabulary candidate mined from text / contacts / calendar (POST /vocab/import).
struct VocabCandidate: Codable, Identifiable {
    var id: String { word }
    let word: String
    let count: Int
    let reason: String   // sender | contact | name | hebrew | non-english
    let sample: String
}

struct VocabImportResult: Codable { let candidates: [VocabCandidate] }

extension AnyCodable {
    var stringValue: String? {
        if let s = value as? String { return s }
        if let i = value as? Int { return String(i) }
        if let d = value as? Double { return String(d) }
        return nil
    }
    var arrayValue: [AnyCodable]? {
        if let a = value as? [String] { return a.map { AnyCodable($0) } }
        if let a = value as? [AnyCodable] { return a }
        return nil
    }
}

/// One executed action inside a remembered command (GET /memory, /memory/unreviewed).
struct MemoryAction: Codable {
    let action: String
    let parameters: [String: AnyCodable]
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        action = try c.decode(String.self, forKey: .action)
        parameters = (try? c.decode([String: AnyCodable].self, forKey: .parameters)) ?? [:]
    }
    enum CodingKeys: String, CodingKey { case action, parameters }
}

/// A remembered voice command from the Mac's command memory.
struct MemoryExample: Codable, Identifiable {
    let id: Int
    let ts: Double
    let time: String
    let source: String
    let transcript: String
    let parsePath: String
    let actions: [MemoryAction]
    let result: String
    let feedback: String
    var resolved: [ResolvedRecord]? = nil
    enum CodingKeys: String, CodingKey {
        case id, ts, time, source, transcript, actions, result, feedback, resolved
        case parsePath = "parse_path"
    }
}

struct UnreviewedResponse: Codable { let examples: [MemoryExample]; let count: Int }
/// GET /memory — same rows, no `count` field.
struct MemoryListResponse: Codable { let examples: [MemoryExample] }

/// What a voice command actually put in the calendar (server joins example → record).
struct ResolvedRecord: Codable, Equatable {
    let type: String
    var id: Int? = nil
    let action: String
    let title: String
    let date: String
    let startTime: String
    var endTime: String? = nil
    enum CodingKeys: String, CodingKey { case type, id, action, title, date; case startTime = "start_time", endTime = "end_time" }
}

// MARK: - Sync bootstrap (GET /sync/bootstrap)

/// Everything a cold start needs, in one payload — see
/// `DOCUMENTATION/SYNC_PROTOCOL.md`. `timers` and `counters` ride along in the
/// JSON too; they are not decoded here because the Timer tab loads its own
/// (with a live `running` session that a snapshot would date instantly).
struct BootstrapSnapshot: Codable {
    struct Window: Codable { let start: String; let end: String }

    let token: String
    let window: Window
    let events: [CalendarEvent]
    let todos: [Todo]
    let tags: [TodoTag]
    let holidays: [Holiday]
    var tagRules: TagRules? = nil

    enum CodingKeys: String, CodingKey {
        case token, window, events, todos, tags, holidays
        case tagRules = "tag_rules"
    }
}

/// The task-tag classifier as data (GET /tags/rules), so the phone can run the
/// Mac's classifier without the Mac. `rev` changes whenever any of it does.
struct TagRules: Codable, Equatable {
    let rev: String
    /// tag name → keywords, exactly `tagging.KEYWORDS`.
    let keywords: [String: [String]]
    /// Tags that are never inferred ("Personal" is the shrug bucket).
    let neverInfer: [String]
    /// The tags that actually exist, so a renamed or deleted one never returns.
    let palette: [String]

    // Both of these arrived after the first version of this endpoint, and both
    // are decoded as OPTIONAL for one reason: a non-optional property missing
    // from the JSON fails the whole decode, and a failed decode here is silent
    // — the phone would simply keep no rules and go back to tagging nothing.
    // Degrading a field is better than losing the table.
    private let orderRaw: [String]?
    private let personalLabelsRaw: [PersonalLabel]?

    /// The order to score `keywords` in — and NOT cosmetic. `infer_tag` keeps
    /// the best score with a strict `>`, so a tie goes to whichever tag came
    /// first. A Swift `Dictionary` has no order and is not stable between
    /// runs, so without this the phone breaks ties at random and disagrees
    /// with the Mac on about one title in five hundred.
    ///
    /// Falling back to sorted keys against an older Mac loses the Mac's
    /// tie-break, but keeps the more important half: the same answer every
    /// launch.
    var order: [String] { orderRaw ?? keywords.keys.sorted() }

    /// The user's own vocabulary labels, in the order `vocab.label_for`
    /// considers them (longest word first). A LIST for the same reason `order`
    /// is one. These cannot ship with the app: "Haxaga" is a course because
    /// they said so.
    var personalLabels: [PersonalLabel] { personalLabelsRaw ?? [] }

    struct PersonalLabel: Codable, Equatable {
        let word: String     // already lower-cased by the server
        let label: String
    }

    enum CodingKeys: String, CodingKey {
        case rev, keywords, palette
        case orderRaw = "order"
        case neverInfer = "never_infer"
        case personalLabelsRaw = "personal_labels"
    }
}

/// One surface, as the Mac describes it (`GET /features`).
///
/// The client declares its own features in code (`FeatureRegistry`) and reads
/// only `visible` out of this — see `assistant/features/CONVENTION.md`:
/// structure is declared on each platform, and only the on/off switch travels.
/// The rest is carried anyway because the Mac sends one shape for every
/// feature, and `mac: false` (Teach is iOS-only) is a real answer rather than
/// something a client should have to guess.
struct FeatureManifest: Codable, Identifiable, Equatable {
    let name: String
    let label: String
    let icon: String
    let order: Int
    let pinned: Bool
    let visible: Bool
    /// Whether `visible` is a CHOICE someone made, or just the Mac quoting its
    /// own default back. The merge in `FeatureVisibility.refresh` turns on it:
    /// a default must never overwrite a switch you actually flipped here.
    let explicit: Bool
    /// Whether this feature also has a panel on the Mac.
    let mac: Bool

    var id: String { name }
}

/// One editable word list — `GET /lexicon`.
///
/// `builtIn` is READ-ONLY fact, read on the Mac out of the module that actually
/// uses the words (`assistant/intent/lexicon.py`). It is shown rather than
/// hidden because "linked to what's in the code" was the point of the request:
/// you can see what the assistant already knows before adding to it.
struct LexiconEntry: Codable, Equatable, Identifiable {
    var name: String
    var label: String
    var why: String
    var example: String
    /// Where the built-in words live, e.g. `assistant.intent.rule_parser._EXTEND_VERBS`.
    var source: String
    var builtIn: [String]
    var added: [String]

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, label, why, example, source, added
        case builtIn = "built_in"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name    = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        label   = try c.decodeIfPresent(String.self, forKey: .label) ?? name
        why     = try c.decodeIfPresent(String.self, forKey: .why) ?? ""
        example = try c.decodeIfPresent(String.self, forKey: .example) ?? ""
        source  = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
        builtIn = try c.decodeIfPresent([String].self, forKey: .builtIn) ?? []
        added   = try c.decodeIfPresent([String].self, forKey: .added) ?? []
    }
}

struct LexiconState: Codable, Equatable {
    var lexicons: [LexiconEntry]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        lexicons = try c.decodeIfPresent([LexiconEntry].self, forKey: .lexicons) ?? []
    }
    enum CodingKeys: String, CodingKey { case lexicons }
}
