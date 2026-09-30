import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

/// "Suggest words" for a magic-word object (TASKS 49).
///
/// It used to come back EMPTY, silently. Probed on the Mac's copy of the same
/// on-device model (2026-09-30): greedy sampling made it repeat itself
/// ("dragon" ×8, "rex" ×8), and every repeat of a word the object already had
/// was filtered out; "Sukkah" tripped the default guardrail ("may contain
/// unsafe content"); an unbounded list ran into the context limit; and every
/// one of those failures was swallowed by a `try?`. Now:
///
///     this device first   Apple's on-device model, a fixed count per round,
///                         sampled, the permissive guardrail, rounds until
///                         there are enough clean words
///     then the Mac        its model (POST /magic/suggest-words), when this
///                         device can't, or when asked ("Ask my Mac")
///     else                a plain sentence saying no model is available
///
/// Nothing is ever added here: the caller shows the words and the user picks.
enum EggWordSuggester {
    enum Source: String {
        case phone = "this iPhone", mac = "your Mac", bank = "the built-in list"
    }

    struct Result {
        var words: [String] = []
        var source: Source?
        /// How many of `words` were topped up from the built-in list.
        var fromBank = 0
        /// Why there are no words, in words a person can act on.
        var problem: String?
    }

    /// What the on-device model last said when it failed, for the message.
    @MainActor static var lastPhoneError: String?

    static var phoneCan: Bool {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *), case .available = SystemLanguageModel.default.availability { return true }
        #endif
        return false
    }

    /// A model's words, topped up from the built-in list to `count` (Gil,
    /// 2026-09-30: "create our own fallback … some randomness … if the llm
    /// doesn't work nor generate the right number").
    @MainActor
    static func suggest(for name: String, id: String? = nil, existing: [String], count: Int, api: APIClient,
                        preferMac: Bool = false) async -> Result {
        var r = await modelSuggest(for: name, existing: existing, count: count, api: api, preferMac: preferMac)
        let filled = EggWordBank.fill(r.words, id: id, name: name, existing: existing, count: count)
        guard filled.fromBank > 0 else { return r }
        r.words = filled.words
        r.fromBank = filled.fromBank
        if r.source == nil || filled.fromBank == filled.words.count { r.source = .bank }
        r.problem = nil
        return r
    }

    @MainActor
    private static func modelSuggest(for name: String, existing: [String], count: Int, api: APIClient,
                                     preferMac: Bool) async -> Result {
        let thing = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !thing.isEmpty else { return Result(problem: "Give it a name first.") }
        let macReachable = api.settings.serverEnabled && api.isOnline
        if !preferMac, phoneCan {
            let words = await onPhone(thing, existing: existing, count: count)
            if !words.isEmpty { return Result(words: words, source: .phone) }
        }
        if macReachable {
            switch await onMac(thing, existing: existing, count: count, api: api) {
            case .success(let words) where !words.isEmpty: return Result(words: words, source: .mac)
            case .success: return Result(source: .mac, problem: "Your Mac couldn't think of any new words for “\(thing)”.")
            case .failure(let why): if !phoneCan { return Result(problem: why.text) }
            }
        }
        if phoneCan && preferMac {                          // asked for the Mac, but it isn't there
            let words = await onPhone(thing, existing: existing, count: count)
            if !words.isEmpty { return Result(words: words, source: .phone) }
        }
        if !phoneCan && !macReachable {
            return Result(problem: "No model is available to suggest words: this iPhone needs Apple Intelligence "
                          + "(iOS 26), and your Mac isn't connected.")
        }
        let why = lastPhoneError.map { " (\($0))" } ?? ""
        return Result(problem: "No new words came back for “\(thing)”\(why) — try again, or add your own.")
    }

    // MARK: - This device

    @MainActor
    private static func onPhone(_ thing: String, existing: [String], count: Int) async -> [String] {
        lastPhoneError = nil
        #if canImport(FoundationModels)
        guard #available(iOS 26.0, *), phoneCan else { return [] }
        var got: [String] = []
        let model = SystemLanguageModel(guardrails: .permissiveContentTransformations)
        for _ in 0..<3 where got.count < count {
            let session = LanguageModelSession(model: model, instructions: instructions)
            let prompt = "Thing: \(thing)\nAlready listed: \((existing + got).joined(separator: ", ").ifEmpty("nothing"))"
            let round: [String]?
            do {
                round = try await withThrowingTaskGroup(of: [String]?.self) { group in
                    group.addTask {
                        try await session.respond(to: prompt, generating: GenEggIdeas.self,
                                                  options: GenerationOptions(temperature: 0.7)).content.ideas.map(\.phrase)
                    }
                    group.addTask { try await Task.sleep(nanoseconds: 30_000_000_000); return nil }
                    let first = try await group.next() ?? nil
                    group.cancelAll()
                    return first
                }
                if round == nil { lastPhoneError = "the on-device model took too long" }
            } catch {
                lastPhoneError = "the on-device model said: \(error)"
                round = nil
            }
            guard let round else { break }
            got = clean(got + round, name: thing, existing: existing, count: count)
        }
        return got
        #else
        return []
        #endif
    }

    static let instructions = """
        You list the other names people use for a thing, for a word game in a calendar app. Give words \
        someone might say in a sentence that clearly mean that same thing: synonyms, kinds, breeds, types, \
        famous examples, nicknames, other spellings. Lower case. Never repeat a word, never repeat the ones \
        already listed, never split a name into its separate words.
        """

    // MARK: - The Mac

    private struct MacReply: Decodable { let words: [String]? ; let error: String? }

    @MainActor
    private static func onMac(_ thing: String, existing: [String], count: Int,
                              api: APIClient) async -> Swift.Result<[String], MacError> {
        do {
            let data = try await api.request("/magic/suggest-words", method: "POST",
                                             body: ["name": thing, "existing": existing, "count": count, "source": "ios"])
            let reply = try JSONDecoder().decode(MacReply.self, from: data)
            return .success(clean(reply.words ?? [], name: thing, existing: existing, count: count))
        } catch {
            return .failure(MacError("Your Mac's model couldn't be reached."))
        }
    }

    struct MacError: Error { let text: String; init(_ t: String) { text = t } }

    static func clean(_ words: [String], name: String, existing: [String], count: Int) -> [String] {
        EggRules.cleanWords(words, name: name, existing: existing, count: count)
    }
}

private extension String {
    func ifEmpty(_ other: String) -> String { isEmpty ? other : self }
}

#if canImport(FoundationModels)
@available(iOS 26.0, *)
@Generable
struct GenEggIdea {
    @Guide(description: "A word or short phrase, one to three words, that a person would say to mean the thing")
    var phrase: String
}

@available(iOS 26.0, *)
@Generable
struct GenEggIdeas {
    @Guide(description: "Different phrases for the same thing, no repeats", .count(10))
    var ideas: [GenEggIdea]
}
#endif
