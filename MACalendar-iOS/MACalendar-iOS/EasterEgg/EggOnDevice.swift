import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

/// Apple's on-device model, asked for more words for a magic word — the same
/// call on the phone and on the Mac (shared, like the drawings).
///
/// Why it is shaped like this (TASKS 49, probed 2026-09-30): greedy sampling
/// made the small model repeat itself ("dragon" ×8), so it is sampled; the
/// default guardrail refused "Sukkah", so it is the permissive one; an
/// unbounded list ran into the context limit, so every round asks for a fixed
/// ten and rounds repeat until there are enough clean words; and a failure is
/// returned in words, never swallowed.
enum EggOnDevice {
    static var available: Bool {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, macOS 26.0, *), case .available = SystemLanguageModel.default.availability { return true }
        #endif
        return false
    }

    static let instructions = """
        You list the other names people use for a thing, for a word game in a calendar app. Give words \
        someone might say in a sentence that clearly mean that same thing: synonyms, kinds, breeds, types, \
        famous examples, nicknames, other spellings. Lower case. Never repeat a word, never repeat the ones \
        already listed, never split a name into its separate words.
        """

    /// Cleaned words (up to `count`), and why there are none when that happens.
    static func words(for thing: String, existing: [String], count: Int) async -> (words: [String], error: String?) {
        #if canImport(FoundationModels)
        guard #available(iOS 26.0, macOS 26.0, *), available else { return ([], nil) }
        var got: [String] = []
        var error: String?
        let model = SystemLanguageModel(guardrails: .permissiveContentTransformations)
        for _ in 0..<3 where got.count < count {
            let session = LanguageModelSession(model: model, instructions: instructions)
            let listed = (existing + got).joined(separator: ", ")
            let prompt = "Thing: \(thing)\nAlready listed: \(listed.isEmpty ? "nothing" : listed)"
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
                if round == nil { error = "the on-device model took too long" }
            } catch let e {
                error = "the on-device model said: \(e)"
                round = nil
            }
            guard let round else { break }
            got = EggRules.cleanWords(got + round, name: thing, existing: existing, count: count)
        }
        return (got, got.isEmpty ? error : nil)
        #else
        return ([], nil)
        #endif
    }
}

#if canImport(FoundationModels)
@available(iOS 26.0, macOS 26.0, *)
@Generable
struct GenEggIdea {
    @Guide(description: "A word or short phrase, one to three words, that a person would say to mean the thing")
    var phrase: String
}

@available(iOS 26.0, macOS 26.0, *)
@Generable
struct GenEggIdeas {
    @Guide(description: "Different phrases for the same thing, no repeats", .count(10))
    var ideas: [GenEggIdea]
}
#endif
