import Foundation

/// "Suggest words" for a magic-word object (TASKS 49).
///
/// It used to come back EMPTY, silently — `EggOnDevice` says why. Now:
///
///     this device first   Apple's on-device model (`EggOnDevice`, shared
///                         with the Mac)
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

    static var phoneCan: Bool { EggOnDevice.available }

    /// A model's words, topped up from the built-in list to `count` (Gil,
    /// 2026-09-30: "create our own fallback … some randomness … if the llm
    /// doesn't work nor generate the right number").
    @MainActor
    static func suggest(for name: String, id: String? = nil, existing: [String], count: Int, api: APIClient,
                        preferMac: Bool = false) async -> Result {
        var r = await modelSuggest(for: name, existing: existing, count: count, api: api, preferMac: preferMac)
        // Every word another magic word already has is dropped, and the bank
        // tops the list back up — a suggestion is never a conflict.
        let taken = EggStore.shared.settings.objects.filter { $0.id != id }.flatMap(\.keywords)
        let filled = EggWordBank.fill(r.words, id: id, name: name, existing: existing, count: count, taken: taken)
        r.words = filled.words
        guard filled.fromBank > 0 else {
            if r.words.isEmpty, r.problem == nil { r.problem = "Every word that came back already summons something else." }
            return r
        }
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
        let r = await EggOnDevice.words(for: thing, existing: existing, count: count)
        lastPhoneError = r.error
        return r.words
    }

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
