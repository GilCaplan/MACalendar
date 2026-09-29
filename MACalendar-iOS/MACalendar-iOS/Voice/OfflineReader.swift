import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

// MARK: - The phone's offline reader (assistant/offline/PROTOCOL.md)
//
// Gil, 2026-09-28: when the Mac can't be reached, read the command HERE with
// Apple's on-device model and book it at once — then let the Mac's engine
// re-read it on reconnect, and let the Mac's reading win.
//
// Only the item SHAPE is compiled in (`schema`). What the model is TOLD is
// served by the Mac (`GET /offline/reader`) and cached, so improving the
// offline reader is an edit on the Mac, not a reinstall. A served spec for a
// schema this build doesn't know is ignored in favour of the bundled copy.
// `tests/unit/test_offline_protocol.py` holds these constants to the Mac's.

/// One item the reader produced. The same six fields as the Mac's
/// `assistant/offline/spec.py` examples.
struct OfflineItem: Codable, Equatable {
    var kind: String          // "event" | "todo" | "other"
    var title: String
    var date: String          // YYYY-MM-DD or ""
    var start: String         // HH:MM or ""
    var end: String           // HH:MM or ""
    var recurrence: String    // "none" | "daily" | "weekly" | "monthly" | "yearly"

    /// What the phone may book before the Mac has seen it: creates only.
    var bookable: Bool { OfflineReader.mayCommit.contains(kind) }
}

/// What travels to the Mac with the resent command, as `offline_reading`.
struct OfflineReading: Codable {
    var `protocol`: Int
    var schema: Int
    var reader: String
    var specVersion: String
    var text: String
    var ms: Int
    var items: [OfflineItem]

    enum CodingKeys: String, CodingKey {
        case `protocol`, schema, reader, text, ms, items
        case specVersion = "spec_version"
    }
}

/// The Mac's `offline` block on a reply to a resent command.
struct OfflineVerdict: Codable {
    let verdict: String       // same | changed | pending | deferred | unverified
    let said: String?
}

struct OfflineReaderSpec: Codable {
    struct Example: Codable { let today: String; let said: String; let items: [OfflineItem] }
    let `protocol`: Int
    let schema: Int
    let version: String
    let instructions: String
    let examples: [Example]
    let names: [String]?
    /// What to leave for the Mac, decided before the model (Q68). Optional:
    /// a spec from before the guard has none, and the bundled rules apply.
    let guardRules: GuardRules?

    enum CodingKeys: String, CodingKey {
        case `protocol`, schema, version, instructions, examples, names
        case guardRules = "guard"
    }
}

enum OfflineReader {
    static let schema = 2
    static let protocolVersion = 1
    static let kinds = ["event", "todo", "other"]
    static let recurrences = ["none", "daily", "weekly", "monthly", "yearly"]
    static let mayCommit: Set<String> = ["event", "todo"]
    static let readerName = "apple-fm"

    private static let specKey = "offlineReaderSpec"
    private static let specFetchedKey = "offlineReaderSpecFetchedAt"

    /// Used only until the phone has fetched the Mac's spec once. Short on
    /// purpose: the served one is the real one.
    static let bundled = OfflineReaderSpec(
        protocol: protocolVersion, schema: schema, version: "bundled",
        instructions: """
        You turn one spoken calendar command into items, one per thing asked for.
        kind is "event" (on a day or at a time, or seeing or calling a person - 09:00 \
        on the soonest day if no time), "todo" (no day and no time), or "other" \
        (moving, changing, deleting, completing, or a question).
        title is the thing itself in the speaker's words, keeping names; no date or time.
        date is YYYY-MM-DD from today's date, start and end are 24-hour HH:MM, empty \
        when not said. A bare 7 or 8 means evening. recurrence is "none" unless the \
        speaker said it repeats. Never invent a date, time or person.
        """,
        examples: [], names: [], guardRules: nil)

    // MARK: availability

    /// True when this device can run Apple's on-device model right now
    /// (iOS 26, Apple Intelligence on and the model downloaded).
    static var isAvailable: Bool {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            if case .available = SystemLanguageModel.default.availability { return true }
        }
        #endif
        return false
    }

    /// Why not, in words for Settings.
    static var availabilityNote: String {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            switch SystemLanguageModel.default.availability {
            case .available: return "Ready — commands are read on this device when your Mac is away."
            case .unavailable(.deviceNotEligible): return "This device can't run Apple's on-device model, so offline commands wait for your Mac."
            case .unavailable(.appleIntelligenceNotEnabled): return "Turn on Apple Intelligence in iOS Settings to read commands offline."
            case .unavailable(.modelNotReady): return "Apple's model is still downloading."
            case .unavailable: return "Apple's on-device model isn't available right now."
            }
        }
        #endif
        return "Needs iOS 26 — offline commands wait for your Mac."
    }

    // MARK: the spec

    static func spec() -> OfflineReaderSpec {
        guard let data = UserDefaults.standard.data(forKey: specKey),
              let s = try? JSONDecoder().decode(OfflineReaderSpec.self, from: data),
              s.schema == schema else { return bundled }
        return s
    }

    /// Fetch the Mac's spec at most once an hour. A spec built for another
    /// schema is not stored — this build could not honour it.
    @MainActor
    static func refreshSpec(api: APIClient, force: Bool = false) async {
        let last = UserDefaults.standard.double(forKey: specFetchedKey)
        if !force, Date().timeIntervalSince1970 - last < 3600 { return }
        guard let data = try? await api.request("/offline/reader"),
              let s = try? JSONDecoder().decode(OfflineReaderSpec.self, from: data) else { return }
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: specFetchedKey)
        guard s.schema == schema else { return }
        UserDefaults.standard.set(data, forKey: specKey)
    }

    // MARK: reading

    static func dayLine(_ now: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd (EEEE)"
        return f.string(from: now)
    }

    static func instructions(_ s: OfflineReaderSpec) -> String {
        var out = s.instructions
        if !s.examples.isEmpty {
            out += "\n\nExamples:"
            let enc = JSONEncoder()
            enc.outputFormatting = [.sortedKeys]
            for ex in s.examples {
                let items = (try? enc.encode(ex.items)).flatMap { String(data: $0, encoding: .utf8) } ?? "[]"
                out += "\nToday: \(ex.today)\nSaid: \(ex.said)\nItems: \(items)"
            }
        }
        if let names = s.names, !names.isEmpty {
            out += "\n\nWords this speaker uses (spell them this way): "
                + names.prefix(150).joined(separator: ", ")
        }
        return out
    }

    /// Read one command. nil when the model is unavailable or fails — the
    /// command then simply waits for the Mac, exactly as before.
    static func read(_ text: String, now: Date = Date()) async -> OfflineReading? {
        let said = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !said.isEmpty else { return nil }
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            let s = spec()
            // Q68 step 1: an edit, delete, completion or question is the Mac's
            // — decided by the engine's own tables, before (and instead of)
            // a model call, so it can never be booked as something new.
            if OfflineGuard.leavesForMac(said, rules: s.guardRules ?? .bundled) {
                return OfflineReading(protocol: protocolVersion, schema: schema,
                                      reader: "guard", specVersion: s.version, text: said, ms: 0,
                                      items: [OfflineItem(kind: "other", title: said, date: "",
                                                          start: "", end: "", recurrence: "none")])
            }
            guard isAvailable else { return nil }
            let t0 = Date()
            do {
                let session = LanguageModelSession(instructions: instructions(s))
                let prompt = "Today: \(dayLine(now))\nSaid: \(said)"
                let out = try await session.respond(to: prompt, generating: GenReading.self,
                                                    options: GenerationOptions(sampling: .greedy))
                // Q68 step 1: the DAY is worked out here, by the project's
                // rules (OfflineDates.swift) — never by the model.
                let items = out.content.items.map {
                    OfflineItem(kind: $0.kind, title: $0.title,
                                date: OfflineDates.resolve($0.when, today: now) ?? "",
                                start: $0.start, end: $0.end, recurrence: $0.recurrence)
                }
                return OfflineReading(protocol: protocolVersion, schema: schema,
                                      reader: readerName, specVersion: s.version, text: said,
                                      ms: Int(Date().timeIntervalSince(t0) * 1000),
                                      items: sanitize(items))
            } catch {
                return nil
            }
        }
        #endif
        return nil
    }

    /// The model's guided output is shaped, not trusted: anything malformed
    /// becomes "other", which the phone leaves for the Mac rather than booking.
    static func sanitize(_ items: [OfflineItem]) -> [OfflineItem] {
        let day = try! NSRegularExpression(pattern: #"^\d{4}-\d{2}-\d{2}$"#)
        let clock = try! NSRegularExpression(pattern: #"^([01]\d|2[0-3]):[0-5]\d$"#)
        func matches(_ re: NSRegularExpression, _ s: String) -> Bool {
            re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
        }
        return items.map { raw in
            var it = raw
            it.title = it.title.trimmingCharacters(in: .whitespacesAndNewlines)
            if !kinds.contains(it.kind) { it.kind = "other" }
            if !recurrences.contains(it.recurrence) { it.recurrence = "none" }
            if !it.date.isEmpty && (!matches(day, it.date)
                                    || DateFormatter.isoDay.date(from: it.date) == nil) { it.date = "" }
            if !it.start.isEmpty && !matches(clock, it.start) { it.start = "" }
            if !it.end.isEmpty && !matches(clock, it.end) { it.end = "" }
            if it.start.isEmpty { it.end = "" }
            if it.title.isEmpty { it.kind = "other" }
            // An event needs a day to land on; without one it is not safe to
            // guess, so the Mac decides.
            if it.kind == "event" && it.date.isEmpty { it.kind = "other" }
            return it
        }
    }
}

#if canImport(FoundationModels)
@available(iOS 26.0, *)
@Generable
struct GenItem {
    @Guide(description: "event, todo or other", .anyOf(["event", "todo", "other"]))
    var kind: String
    @Guide(description: "The thing itself, short, in the speaker's words; no date or time")
    var title: String
    @Guide(description: "The words that say which day, exactly as said (tomorrow, next tuesday, march 5th), or empty")
    var when: String
    @Guide(description: "24-hour HH:MM start, or empty")
    var start: String
    @Guide(description: "24-hour HH:MM end, or empty unless an end was said")
    var end: String
    @Guide(description: "none unless the speaker said it repeats",
           .anyOf(["none", "daily", "weekly", "monthly", "yearly"]))
    var recurrence: String
}

@available(iOS 26.0, *)
@Generable
struct GenReading {
    // At most 6 (DEVQA Q68 step 1c): uncapped, the model looped on repeat
    // phrases until its context window filled — 21 of 1,200, ~37 s each.
    @Guide(description: "One item per thing the speaker asked for, in order", .maximumCount(6))
    var items: [GenItem]
}
#endif
