import Foundation

/// What the phone labels a row with when it has to decide by itself — a task
/// typed or an event made with the Mac away, and the offline reader's
/// provisional rows. The Mac's labeller, in the Mac's order:
///
///     task    TagClassifier (the keyword rules)   → the learned tag model
///     event   CategoryClassifier (the rules)      → the learned category model
///             → a colour, avoiding the neighbours' (`pick_color`)
///
/// Online nothing here runs: the Mac labels what it creates, with the full
/// model (embedding and all), and the phone draws the Mac's answer. Offline
/// this is a PREVIEW — the queued create still says only what the user said,
/// so on replay the Mac labels it itself and its answer is the one that lands
/// (`DOCUMENTATION/SYNC_PROTOCOL.md`).
///
/// Everything it reads is served by the Mac and cached here, so it works on
/// a train: the category table rides the bootstrap, and the two models are
/// fetched when their `rev` changes (a retrain, the user's personal model, a
/// switch flipped in config) — checked at most hourly, one small request each.
@MainActor
final class Labeller {
    static let shared = Labeller()

    private(set) var categoryRules: CategoryRules?
    /// Decoded lazily: the event model is ~2 MB of JSON, and most launches
    /// never create anything offline.
    private var models: [String: LabelModel] = [:]
    private static let kinds = ["event", "task"]
    private static let fetchedKey = "mc_label_models_fetched"
    private static func revKey(_ kind: String) -> String { "mc_label_model_rev_\(kind)" }

    private let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    private var rulesFile: URL { dir.appendingPathComponent("mc_category_rules.json") }
    private func modelFile(_ kind: String) -> URL { dir.appendingPathComponent("mc_label_model_\(kind).json") }

    private init() {
        if let data = try? Data(contentsOf: rulesFile) {
            categoryRules = try? JSONDecoder().decode(CategoryRules.self, from: data)
        }
    }

    // MARK: - Keeping the served data current

    /// Adopt the bootstrap's category table; a no-op when the rev is unchanged.
    func update(categoryRules fresh: CategoryRules) {
        guard fresh.rev != categoryRules?.rev else { return }
        categoryRules = fresh
        try? JSONEncoder().encode(fresh).write(to: rulesFile)
    }

    /// Fetch a model only when the Mac's differs from ours (`?have=` answers
    /// "unchanged" in a few bytes). A failure — Mac away, a Mac from before
    /// this endpoint — keeps the copy we have, which is the point of caching.
    func refreshModels(api: APIClient, force: Bool = false) async {
        let last = UserDefaults.standard.double(forKey: Self.fetchedKey)
        if !force, Date().timeIntervalSince1970 - last < 3600 { return }
        var reached = false
        for kind in Self.kinds {
            let have = UserDefaults.standard.string(forKey: Self.revKey(kind)) ?? ""
            guard let data = try? await api.request("/labels/model/\(kind)?have=\(have)") else { continue }
            reached = true
            struct Head: Decodable { let rev: String; let unchanged: Bool? }
            guard let head = try? JSONDecoder().decode(Head.self, from: data),
                  head.unchanged != true,
                  let payload = try? JSONDecoder().decode(LabelModelPayload.self, from: data),
                  let model = LabelModel(payload) else { continue }
            try? data.write(to: modelFile(kind))
            UserDefaults.standard.set(payload.rev, forKey: Self.revKey(kind))
            models[kind] = model
        }
        if reached { UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: Self.fetchedKey) }
    }

    private func model(_ kind: String) -> LabelModel? {
        if let m = models[kind] { return m }
        guard let data = try? Data(contentsOf: modelFile(kind)),
              let payload = try? JSONDecoder().decode(LabelModelPayload.self, from: data),
              let m = LabelModel(payload) else { return nil }
        models[kind] = m
        return m
    }

    // MARK: - The two answers

    /// A task's tags: the rules, then the model where they were silent.
    func tags(for title: String) -> [String] {
        LabelModel.stackTags(rule: TagClassifier.shared.tags(for: title), title: title,
                             model: model("task"),
                             palette: LocalStore.shared.allTags().map { $0.name })
    }

    /// An event's category and colour, or nil before the first contact with
    /// the Mac (no table: the row stays uncategorised, as it always was).
    /// `neighbours` are the colours of the events either side on its day.
    func label(title: String, attendees: String, location: String, description: String,
               neighbours: [String]) -> (category: String, color: String?)? {
        // Never reached a Mac (or phone only): the defaults compiled in.
        guard let rules = categoryRules ?? DefaultRules.categoryRules else { return nil }
        let rule = CategoryClassifier.classify(
            title, attendees: attendees.components(separatedBy: ","),
            location: location, description: description, rules: rules)
        let category = LabelModel.stackCategory(
            rule: rule, title: title, model: model("event"),
            exists: { CategoryClassifier.exists($0, in: rules) })
        return (category, CategoryClassifier.pickColor(category, neighbours: neighbours, rules: rules))
    }
}
