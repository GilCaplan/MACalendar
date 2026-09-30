import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

/// "Suggest words" for a magic-word object, from Apple's on-device model
/// (iOS 26, the same one the offline reader uses). On the phone, offline, and
/// only a suggestion: each word is added by a tap, never automatically — a
/// generic word ("walk") would fire on half of all commands.
enum EggWordSuggester {
    static var isAvailable: Bool {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *), case .available = SystemLanguageModel.default.availability { return true }
        #endif
        return false
    }

    /// Up to ten words or short phrases for `name`, minus the ones it has.
    static func suggest(for name: String, existing: [String]) async -> [String] {
        let thing = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !thing.isEmpty else { return [] }
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *), isAvailable {
            let session = LanguageModelSession(instructions: """
                You suggest trigger words for a fun animation in a calendar app. The animation plays \
                whenever the user says one of the words in a command, so every word must clearly and only \
                mean the thing itself: synonyms, kinds, nicknames, well-known names. Never a generic verb \
                or everyday word that could mean something else. Lower case. One to three words each.
                """)
            let prompt = "The thing: \(thing)\nWords it already has: \(existing.joined(separator: ", "))"
            let got: [String]? = try? await withThrowingTaskGroup(of: [String]?.self) { group in
                group.addTask {
                    try await session.respond(to: prompt, generating: GenEggWords.self,
                                              options: GenerationOptions(sampling: .greedy)).content.words
                }
                group.addTask {
                    try await Task.sleep(nanoseconds: 12_000_000_000)
                    return nil
                }
                let first = try await group.next() ?? nil
                group.cancelAll()
                return first
            }
            return clean(got ?? [], existing: existing)
        }
        #endif
        return []
    }

    static func clean(_ words: [String], existing: [String]) -> [String] {
        let have = Set(existing.map { $0.lowercased() })
        var out: [String] = []
        for w in words {
            let t = w.lowercased().trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
            guard !t.isEmpty, t.split(separator: " ").count <= 3, !have.contains(t), !out.contains(t) else { continue }
            out.append(t)
        }
        return Array(out.prefix(10))
    }
}

#if canImport(FoundationModels)
@available(iOS 26.0, *)
@Generable
struct GenEggWords {
    @Guide(description: "Words or short phrases that mean the thing", .maximumCount(10))
    var words: [String]
}
#endif
