import Foundation
import UIKit

/// The phone's copy of the flashcard library, and what lets it study on a train.
///
/// Cached on disk, under `Documents/flashcards/`:
///   library.json          the subjects and their sets (the front page)
///   sets/<id>.json        every card of a set, with its progress
///   media/<id>/<path>     the pictures those cards name
///
/// A round is built HERE, from that cache, by the same rules as the Mac's
/// `FlashcardStore.study` — so with the Mac away the tab still studies, and an
/// answer moves its card at once with `FSRS.swift`. The answer itself goes out
/// through `APIClient.mutate`, so it is queued and replayed when the Mac is
/// back; the Mac recomputes it from the instant it was given and its result
/// replaces ours. Whichever progress was written LATER wins a merge, so a
/// refresh that lands before a queued review has replayed does not undo it.
///
/// Writes are local first, then the Mac. A write the Mac REFUSES is rolled
/// back and its sentence returned; one it never heard is queued and stands.
@MainActor
final class FlashcardStore: ObservableObject {
    static let shared = FlashcardStore()

    @Published private(set) var subjects: [FlashSubject] = []
    @Published private(set) var sets: [Int: FlashSet] = [:]
    @Published private(set) var isRefreshing = false
    /// True once the Mac has answered at least once this launch.
    @Published private(set) var reachedMac = false
    /// Why the last refresh got nothing — shown when there is no cache to draw.
    @Published private(set) var unreachableReason: String?

    /// This person's `flashcards/` folder, not the shared top of Documents.
    private var root: URL { LocalStore.shared.featureFolder("flashcards") }
    private var images: [String: UIImage] = [:]

    /// Placeholder ids below every other store's (LocalStore counts down from
    /// -1, CourseStore from -1,000,000), because `remapTemporaryID` matches on
    /// the number alone.
    private static let tempBase = -3_000_000
    private var nextTemp = tempBase - 1

    private init() {
        load()
        NotificationCenter.default.addObserver(forName: .localStoreUserChanged, object: nil, queue: .main) { _ in
            Task { @MainActor in FlashcardStore.shared.load() }
        }
    }

    // MARK: - Disk

    private var libraryURL: URL { root.appendingPathComponent("library.json") }
    private func setURL(_ id: Int) -> URL { root.appendingPathComponent("sets/\(id).json") }
    private func mediaURL(_ setId: Int, _ path: String) -> URL {
        root.appendingPathComponent("media/\(setId)/\(path)")
    }

    private func load() {
        try? FileManager.default.createDirectory(at: root.appendingPathComponent("sets"),
                                                 withIntermediateDirectories: true)
        // From scratch: on a change of user nothing of the last person's may stay.
        subjects = []
        sets = [:]
        let d = JSONDecoder()
        if let data = try? Data(contentsOf: libraryURL),
           let lib = try? d.decode([FlashSubject].self, from: data) {
            subjects = lib
        }
        let files = (try? FileManager.default.contentsOfDirectory(
            at: root.appendingPathComponent("sets"), includingPropertiesForKeys: nil)) ?? []
        for f in files where f.pathExtension == "json" {
            if let data = try? Data(contentsOf: f), let s = try? d.decode(FlashSet.self, from: data) {
                sets[s.id] = s
            }
        }
        let negs = subjects.map(\.id) + subjects.flatMap { $0.sets.map(\.id) }
            + sets.values.flatMap { $0.cards.map(\.id) }
        nextTemp = min((negs.filter { $0 < 0 }.min().map { $0 - 1 }) ?? Self.tempBase - 1,
                       Self.tempBase - 1)
        recount()
    }

    private func saveLibrary() {
        try? JSONEncoder().encode(subjects).write(to: libraryURL, options: .atomic)
    }

    private func saveSet(_ id: Int) {
        guard let s = sets[id] else {
            try? FileManager.default.removeItem(at: setURL(id))
            return
        }
        try? JSONEncoder().encode(s).write(to: setURL(id), options: .atomic)
    }

    private func mintTemp() -> Int {
        defer { nextTemp -= 1 }
        return nextTemp
    }

    // MARK: - Reading

    var allSets: [FlashSetSummary] { subjects.flatMap(\.sets) }

    func summary(_ id: Int) -> FlashSetSummary? { allSets.first { $0.id == id } }

    func subjectName(of setId: Int) -> String {
        subjects.first { $0.sets.contains { $0.id == setId } }?.name ?? ""
    }

    /// Whether a set's cards are on this phone, i.e. it can be studied offline.
    func isCached(_ id: Int) -> Bool { sets[id] != nil }

    /// Card / item / seen / due counts from the cached cards, so a review given
    /// offline moves the numbers at once. A set never downloaded keeps the
    /// counts the Mac last sent.
    private func recount(now: Date = Date()) {
        for si in subjects.indices {
            for i in subjects[si].sets.indices {
                guard let full = sets[subjects[si].sets[i].id] else { continue }
                var items = 0, seen = 0, due = 0
                for c in full.cards {
                    for it in c.items {
                        items += 1
                        if let p = c.progress[it] {
                            seen += 1
                            if let d = FlashDates.parse(p.due), d <= now { due += 1 }
                        }
                    }
                }
                subjects[si].sets[i].cards = full.cards.count
                subjects[si].sets[i].items = items
                subjects[si].sets[i].seen = seen
                subjects[si].sets[i].due = due
            }
        }
    }

    // MARK: - Refresh from the Mac

    /// Pull the library and every set whose cards changed, and their pictures,
    /// and MERGE them into the phone's copy (`mergeLibrary`). Once a set is on
    /// the phone it stays there, studiable with no Mac, until somebody deletes
    /// it — here, or on the Mac (`deleted` in the answer). An unreachable Mac,
    /// a refusal, an unreadable reply or an empty library removes nothing.
    func refresh(api: APIClient) async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }

        // Anything of ours still queued goes first, so the Mac's answer
        // already includes it — otherwise a refresh would draw the old name
        // for a moment, or a card added on the train would blink out.
        if hasQueuedWrites { await api.syncPending() }
        let stillQueued = hasQueuedWrites

        _ = await api.flashcardInbox()

        let lib: FlashLibrary
        do {
            lib = try await api.flashcardLibrary()
        } catch {
            // Unreachable, refused, or a reply this app could not decode:
            // nothing is taken off the phone.
            unreachableReason = Self.sentence(for: error)
            return
        }
        reachedMac = true
        unreachableReason = nil

        let pendingTemps = queuedTempIDs
        let plan = Self.mergeLibrary(cached: subjects, fresh: lib.subjects,
                                     deleted: lib.deleted ?? FlashDeleted(),
                                     pendingTemps: pendingTemps, keepLocalEdits: stillQueued)
        let previous = Dictionary(allSets.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        subjects = plan.subjects

        // A set leaves the phone ONLY because it was deleted — here (deleteSet)
        // or on the Mac, which lists it in `deleted`. One merely missing from
        // the answer stays, cards, progress, pictures and all.
        for id in plan.removeSets {
            sets[id] = nil
            saveSet(id)
            removeMedia(id)
        }

        let fromMac = Set(lib.subjects.flatMap { $0.sets.map(\.id) })
        let merged = plan.subjects
        // Download a set's cards when it is new to us, edited on the Mac, or
        // its counts disagree with ours (reviews made on the Mac).
        for summary in merged.flatMap(\.sets) where summary.id > 0 && fromMac.contains(summary.id) {
            let cached = sets[summary.id]
            let mineCounts = previous[summary.id]
            let stale = cached == nil
                || cached?.updatedAt != summary.updatedAt
                || mineCounts?.due != summary.due || mineCounts?.seen != summary.seen
                || mineCounts?.cards != summary.cards
            guard stale else { continue }
            guard let full = try? await api.flashcardSet(summary.id) else { continue }
            sets[summary.id] = mergeProgress(full, into: cached, keeping: pendingTemps)
            saveSet(summary.id)
            await fetchPictures(of: summary.id, api: api)
        }
        recount()
        saveLibrary()
    }

    /// What a refresh does to the library, decided from data alone.
    ///
    /// - A subject or set the Mac sent replaces ours with the same id.
    /// - One we hold that the Mac did NOT send stays, unless the Mac lists it
    ///   in `deleted` (a set of a deleted subject counts as deleted).
    /// - A placeholder (negative id) stays while its create is still queued;
    ///   one whose create is no longer queued was cancelled and goes.
    /// - While our own writes are still queued, our names and archive flags
    ///   win over the Mac's, so a rename or an archive does not flicker back.
    ///
    /// `removeSets` is every cached set to drop, with its pictures: exactly the
    /// deleted ones plus cancelled placeholders. An empty answer removes nothing.
    struct LibraryMerge {
        var subjects: [FlashSubject]
        var removeSets: Set<Int>
    }

    nonisolated static func mergeLibrary(cached: [FlashSubject], fresh: [FlashSubject],
                                         deleted: FlashDeleted, pendingTemps: Set<Int>,
                                         keepLocalEdits: Bool) -> LibraryMerge {
        let goneSubjects = Set(deleted.subjects.map(\.id))
        var goneSets = Set(deleted.sets.map(\.id))
        for sub in cached where goneSubjects.contains(sub.id) {
            goneSets.formUnion(sub.sets.map(\.id))
        }
        func alive(_ id: Int, gone: Set<Int>) -> Bool {
            if gone.contains(id) { return false }
            return id > 0 || pendingTemps.contains(id)
        }

        var merged = fresh.filter { !goneSubjects.contains($0.id) }
        for i in merged.indices { merged[i].sets.removeAll { goneSets.contains($0.id) } }

        // Subjects we hold that the Mac did not send: kept, empty for now —
        // their sets are put back below with everyone else's.
        let sent = Set(merged.map(\.id))
        for local in cached where !sent.contains(local.id) && alive(local.id, gone: goneSubjects) {
            var kept = local
            kept.sets = []
            merged.append(kept)
        }

        // Sets we hold that the Mac did not send, under the subject they were in.
        let placed = Set(merged.flatMap { $0.sets.map(\.id) })
        for local in cached {
            for s in local.sets where !placed.contains(s.id) && alive(s.id, gone: goneSets) {
                if let i = merged.firstIndex(where: { $0.id == local.id }) {
                    merged[i].sets.append(s)
                }
            }
        }

        if keepLocalEdits {
            let mineSubjects = Dictionary(cached.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
            let mineSets = Dictionary(cached.flatMap(\.sets).map { ($0.id, $0) },
                                      uniquingKeysWith: { a, _ in a })
            for si in merged.indices {
                if let mine = mineSubjects[merged[si].id] {
                    merged[si].name = mine.name
                    merged[si].archived = mine.archived
                }
                for i in merged[si].sets.indices {
                    if let mine = mineSets[merged[si].sets[i].id] {
                        merged[si].sets[i].name = mine.name
                        merged[si].sets[i].archived = mine.archived
                    }
                }
            }
        }

        // Cancelled placeholders: made here, never reached the Mac, no longer queued.
        let kept = Set(merged.flatMap { $0.sets.map(\.id) })
        let cancelled = Set(cached.flatMap { $0.sets.map(\.id) }
            .filter { $0 < 0 && !kept.contains($0) && !pendingTemps.contains($0) })
        let sorted = merged.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        return LibraryMerge(subjects: sorted, removeSets: goneSets.union(cancelled))
    }

    /// The Mac's set, with two things of ours kept: progress written LATER than
    /// the Mac's (a review still in the queue), and cards made here that have
    /// not reached it.
    private func mergeProgress(_ fresh: FlashSet, into old: FlashSet?, keeping temps: Set<Int>) -> FlashSet {
        guard let old else { return fresh }
        var out = fresh
        let oldCards = Dictionary(old.cards.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        for i in out.cards.indices {
            guard let before = oldCards[out.cards[i].id] else { continue }
            for (item, mine) in before.progress {
                let theirs = out.cards[i].progress[item]
                if theirs == nil || (FlashDates.parse(mine.last) ?? .distantPast)
                    > (FlashDates.parse(theirs!.last) ?? .distantPast) {
                    if out.cards[i].items.contains(item) { out.cards[i].progress[item] = mine }
                }
            }
        }
        out.cards += old.cards.filter { $0.id < 0 && temps.contains($0.id) }
        return out
    }

    private var hasQueuedWrites: Bool {
        LocalStore.shared.allPending().contains { $0.path.hasPrefix("/flashcards") }
    }

    private var queuedTempIDs: Set<Int> {
        var out: Set<Int> = []
        for p in LocalStore.shared.allPending() where p.path.hasPrefix("/flashcards") {
            if let data = p.bodyJSON,
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let t = obj["_temp_id"] as? Int { out.insert(t) }
        }
        return out
    }

    static func sentence(for error: Error) -> String {
        if let e = error as? APIError {
            switch e {
            case .badURL: return "Set your Mac's address in Settings first."
            case .offline: return "Your Mac isn't reachable right now."
            case .serverError: return e.serverSentence ?? "Your Mac answered with something this app could not read."
            }
        }
        return error.localizedDescription
    }

    // MARK: - Pictures

    private func fetchPictures(of setId: Int, api: APIClient) async {
        guard let s = sets[setId] else { return }
        let paths = Set(s.cards.compactMap(\.image))
        for path in paths {
            let url = mediaURL(setId, path)
            if FileManager.default.fileExists(atPath: url.path) { continue }
            guard let data = try? await api.flashcardMedia(setId: setId, path: path) else { continue }
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                     withIntermediateDirectories: true)
            try? data.write(to: url, options: .atomic)
        }
    }

    /// A card's picture from the cache; nil if it was never downloaded.
    func image(setId: Int, path: String) -> UIImage? {
        let key = "\(setId)/\(path)"
        if let hit = images[key] { return hit }
        guard let img = UIImage(contentsOfFile: mediaURL(setId, path).path) else { return nil }
        images[key] = img
        return img
    }

    /// Fetch one picture now (a card opened before its set finished downloading).
    func loadImage(setId: Int, path: String, api: APIClient) async -> UIImage? {
        if let img = image(setId: setId, path: path) { return img }
        guard setId > 0, let data = try? await api.flashcardMedia(setId: setId, path: path) else { return nil }
        let url = mediaURL(setId, path)
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                 withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
        return image(setId: setId, path: path)
    }

    /// Keep a picture just uploaded, so the editor and the next round have it.
    func storeImage(_ data: Data, setId: Int, path: String) {
        let url = mediaURL(setId, path)
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                 withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
        images["\(setId)/\(path)"] = nil
    }

    // MARK: - A round

    /// The same rules as the Mac's `FlashcardStore.study`:
    /// - smart: items due now, most overdue first, then new ones shuffled;
    /// - all:   every item, shuffled;
    /// - exam:  multiple choice only, shuffled.
    func round(setIds: [Int], mode: StudyMode, types: Set<String>, limit: Int?,
               now: Date = Date()) -> [StudyItem] {
        let want: Set<String> = mode == .exam ? ["mc"] : (types.isEmpty ? Set(FlashTypes.all) : types)
        var due: [(Date, StudyItem)] = [], new: [StudyItem] = []
        for id in setIds {
            guard let s = sets[id] else { continue }
            for card in s.cards where want.contains(card.type) {
                for it in card.items {
                    let p = card.progress[it]
                    let entry = StudyItem(setId: s.id, setName: s.name, dir: s.dir,
                                          card: card, item: it, progress: p)
                    if let p {
                        let d = FlashDates.parse(p.due) ?? .distantPast
                        if mode != .smart || d <= now { due.append((d, entry)) }
                    } else {
                        new.append(entry)
                    }
                }
            }
        }
        var queue: [StudyItem]
        if mode == .smart {
            queue = due.sorted { $0.0 < $1.0 }.map(\.1) + new.shuffled()
        } else {
            queue = (due.map(\.1) + new).shuffled()
        }
        if let limit, limit > 0, queue.count > limit { queue = Array(queue.prefix(limit)) }
        return queue
    }

    /// How many types each selection holds, for the type filter.
    func types(in setIds: [Int]) -> [String] {
        let present = Set(setIds.compactMap { sets[$0] }.flatMap { $0.cards.map(\.type) })
        return FlashTypes.all.filter(present.contains)
    }

    // MARK: - An answer

    /// Move the item now with FSRS.swift, then tell the Mac (queued if away).
    func review(_ entry: StudyItem, grade: Int, at: Date = Date(), api: APIClient) {
        apply(setId: entry.setId, cardId: entry.card.id, item: entry.item) { FSRS.apply($0, grade: grade, at: at) }
        let cardId = entry.card.id, setId = entry.setId, item = entry.item
        Task {
            do {
                if let theirs = try await api.reviewFlashCard(cardId: cardId, item: item, grade: grade, at: at) {
                    apply(setId: setId, cardId: cardId, item: item) { _ in theirs }
                }
            } catch {
                // The Mac refused (a card deleted there meanwhile). Nothing will
                // replay it, so say so rather than keep a schedule it lacks.
                api.announceRefusal(error, doing: "record that answer")
            }
        }
    }

    func progress(setId: Int, cardId: Int, item: String) -> FlashProgress? {
        sets[setId]?.cards.first { $0.id == cardId }?.progress[item]
    }

    private func apply(setId: Int, cardId: Int, item: String,
                       _ f: (FlashProgress?) -> FlashProgress) {
        guard var s = sets[setId], let i = s.cards.firstIndex(where: { $0.id == cardId }) else { return }
        s.cards[i].progress[item] = f(s.cards[i].progress[item])
        sets[setId] = s
        saveSet(setId)
        recount()
        saveLibrary()
    }

    // MARK: - Writes: subjects and sets

    /// nil when it stands (done, or queued); otherwise the Mac's refusal.
    func createSubject(_ name: String, api: APIClient) async -> String? {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return "A subject needs a name." }
        if subjects.contains(where: { $0.name == name }) { return nil }
        let temp = mintTemp()
        subjects.append(FlashSubject(id: temp, name: name, sets: []))
        saveLibrary()
        do {
            if let real = try await api.createFlashSubject(name: name, tempId: temp) {
                LocalStore.shared.remapTemporaryID(temp, to: real)
            }
            return nil
        } catch {
            subjects.removeAll { $0.id == temp }
            saveLibrary()
            return Self.sentence(for: error)
        }
    }

    func renameSubject(_ id: Int, to name: String, api: APIClient) async -> String? {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return "A subject needs a name." }
        guard let i = subjects.firstIndex(where: { $0.id == id }) else { return nil }
        let old = subjects[i].name
        subjects[i].name = name
        saveLibrary()
        do { try await api.renameFlashSubject(id, name: name); return nil }
        catch {
            if let j = subjects.firstIndex(where: { $0.id == id }) { subjects[j].name = old }
            saveLibrary()
            return Self.sentence(for: error)
        }
    }

    // MARK: - Archive (a flag: cards, pictures and progress all stay)

    /// Archived subjects, and live subjects whose own sets were archived.
    var activeSubjects: [FlashSubject] {
        subjects.filter { !$0.archived }.map { sub in
            var s = sub
            s.sets = sub.sets.filter { !$0.archived }
            return s
        }
    }

    /// The sets the library shows and a round may be built from.
    var activeSets: [FlashSetSummary] { activeSubjects.flatMap(\.sets) }

    var archivedSubjects: [FlashSubject] { subjects.filter(\.archived) }

    /// Sets archived one by one, inside subjects that are not archived (a set
    /// of an archived subject goes with its subject's row).
    var archivedSets: [FlashSetSummary] {
        subjects.filter { !$0.archived }.flatMap { $0.sets.filter(\.archived) }
    }

    /// nil when it stands (done, or queued); otherwise the Mac's refusal.
    func archiveSubject(_ id: Int, _ on: Bool, api: APIClient) async -> String? {
        guard let i = subjects.firstIndex(where: { $0.id == id }) else { return nil }
        let old = subjects[i].archived
        subjects[i].archived = on
        saveLibrary()
        do { try await api.archiveFlashSubject(id, archived: on); return nil }
        catch {
            if let j = subjects.firstIndex(where: { $0.id == id }) { subjects[j].archived = old }
            saveLibrary()
            return Self.sentence(for: error)
        }
    }

    func archiveSet(_ id: Int, _ on: Bool, api: APIClient) async -> String? {
        let old = summary(id)?.archived ?? false
        setArchivedFlag(id, on)
        do { try await api.archiveFlashSet(id, archived: on); return nil }
        catch { setArchivedFlag(id, old); return Self.sentence(for: error) }
    }

    private func setArchivedFlag(_ id: Int, _ on: Bool) {
        for si in subjects.indices {
            if let i = subjects[si].sets.firstIndex(where: { $0.id == id }) { subjects[si].sets[i].archived = on }
        }
        saveLibrary()
    }

    func deleteSubject(_ id: Int, api: APIClient) async -> String? {
        guard let sub = subjects.first(where: { $0.id == id }) else { return nil }
        subjects.removeAll { $0.id == id }
        for s in sub.sets { sets[s.id] = nil; saveSet(s.id); removeMedia(s.id) }
        saveLibrary()
        do { try await api.deleteFlashSubject(id); return nil }
        catch { await refresh(api: api); return Self.sentence(for: error) }
    }

    /// Returns the new set's id (a placeholder until the Mac answers), or the refusal.
    func createSet(subjectId: Int, name: String, lang: String, rtl: Bool,
                   api: APIClient) async -> Result<Int, FlashError> {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return .failure(FlashError("A set needs a name.")) }
        guard let si = subjects.firstIndex(where: { $0.id == subjectId }) else {
            return .failure(FlashError("Pick a subject for the set."))
        }
        let temp = mintTemp()
        let dir = rtl ? "rtl" : "ltr"
        subjects[si].sets.append(FlashSetSummary(id: temp, subjectId: subjectId, name: name,
                                                 lang: lang, dir: dir))
        sets[temp] = FlashSet(id: temp, subjectId: subjectId, subject: subjects[si].name,
                              name: name, lang: lang, dir: dir)
        saveSet(temp)
        saveLibrary()
        do {
            if let real = try await api.createFlashSet(subjectId: subjectId, name: name, lang: lang,
                                                       dir: dir, tempId: temp) {
                LocalStore.shared.remapTemporaryID(temp, to: real)
                return .success(real)
            }
            return .success(temp)
        } catch {
            dropSet(temp)
            return .failure(FlashError(Self.sentence(for: error)))
        }
    }

    func renameSet(_ id: Int, to name: String, api: APIClient) async -> String? {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return "A set needs a name." }
        let old = summary(id)?.name ?? ""
        setName(id, name)
        do { try await api.updateFlashSet(id, fields: ["name": name]); return nil }
        catch { setName(id, old); return Self.sentence(for: error) }
    }

    private func setName(_ id: Int, _ name: String) {
        for si in subjects.indices {
            if let i = subjects[si].sets.firstIndex(where: { $0.id == id }) { subjects[si].sets[i].name = name }
        }
        sets[id]?.name = name
        saveSet(id)
        saveLibrary()
    }

    func resetSet(_ id: Int, api: APIClient) async -> String? {
        let before = sets[id]
        if var s = sets[id] {
            for i in s.cards.indices { s.cards[i].progress = [:] }
            sets[id] = s
            saveSet(id)
        }
        recount()
        saveLibrary()
        do { try await api.resetFlashSet(id); return nil }
        catch {
            sets[id] = before
            saveSet(id)
            recount()
            return Self.sentence(for: error)
        }
    }

    func deleteSet(_ id: Int, api: APIClient) async -> String? {
        dropSet(id)
        do { try await api.deleteFlashSet(id); return nil }
        catch { await refresh(api: api); return Self.sentence(for: error) }
    }

    private func dropSet(_ id: Int) {
        for si in subjects.indices { subjects[si].sets.removeAll { $0.id == id } }
        sets[id] = nil
        saveSet(id)
        removeMedia(id)
        saveLibrary()
    }

    private func removeMedia(_ setId: Int) {
        try? FileManager.default.removeItem(at: root.appendingPathComponent("media/\(setId)"))
        images = images.filter { !$0.key.hasPrefix("\(setId)/") }
    }

    // MARK: - Writes: cards

    /// Add (`card.id == 0`) or change a card. nil when it stands.
    func saveCard(_ card: FlashCard, setId: Int, api: APIClient) async -> String? {
        guard var s = sets[setId] else { return "This set's cards are not on the phone yet." }
        var card = card
        card.items = FlashCard.computeItems(card)
        let body = card.body
        if card.id == 0 {
            let temp = mintTemp()
            card.id = temp
            card.position = (s.cards.map(\.position).max() ?? -1) + 1
            s.cards.append(card)
            sets[setId] = s
            saveSet(setId)
            recount(); saveLibrary()
            do {
                if let real = try await api.addFlashCard(setId: setId, card: body, tempId: temp) {
                    LocalStore.shared.remapTemporaryID(temp, to: real)
                }
                return nil
            } catch {
                sets[setId]?.cards.removeAll { $0.id == temp }
                saveSet(setId)
                recount(); saveLibrary()
                return Self.sentence(for: error)
            }
        }
        guard let i = s.cards.firstIndex(where: { $0.id == card.id }) else { return nil }
        let old = s.cards[i]
        // Progress on items the card no longer has means nothing (the Mac drops it too).
        card.progress = old.progress.filter { card.items.contains($0.key) }
        s.cards[i] = card
        sets[setId] = s
        saveSet(setId)
        recount(); saveLibrary()
        do { try await api.updateFlashCard(card.id, card: body); return nil }
        catch {
            if let j = sets[setId]?.cards.firstIndex(where: { $0.id == card.id }) { sets[setId]?.cards[j] = old }
            saveSet(setId)
            recount(); saveLibrary()
            return Self.sentence(for: error)
        }
    }

    func deleteCard(_ cardId: Int, setId: Int, api: APIClient) async -> String? {
        let before = sets[setId]
        sets[setId]?.cards.removeAll { $0.id == cardId }
        saveSet(setId)
        recount(); saveLibrary()
        do { try await api.deleteFlashCard(cardId); return nil }
        catch {
            sets[setId] = before
            saveSet(setId)
            recount(); saveLibrary()
            return Self.sentence(for: error)
        }
    }

    // MARK: - Placeholder ids

    /// A create reached the Mac: put its real id everywhere ours was.
    /// Called by `LocalStore.remapTemporaryID`, which also repoints the queue.
    func remapTemporaryID(_ temp: Int, to real: Int) {
        guard temp <= Self.tempBase else { return }
        var touched = false
        for si in subjects.indices {
            if subjects[si].id == temp { subjects[si].id = real; touched = true }
            for i in subjects[si].sets.indices {
                if subjects[si].sets[i].id == temp { subjects[si].sets[i].id = real; touched = true }
                if subjects[si].sets[i].subjectId == temp { subjects[si].sets[i].subjectId = real; touched = true }
            }
        }
        if var s = sets[temp] {
            s.id = real
            sets[temp] = nil
            saveSet(temp)
            sets[real] = s
            saveSet(real)
            touched = true
        }
        for (id, var s) in sets {
            var changed = false
            if s.subjectId == temp { s.subjectId = real; changed = true }
            for i in s.cards.indices where s.cards[i].id == temp { s.cards[i].id = real; changed = true }
            if changed { sets[id] = s; saveSet(id); touched = true }
        }
        if touched { saveLibrary() }
        remapped[temp] = real
    }

    /// Placeholder -> real id, for a screen still holding the placeholder.
    private(set) var remapped: [Int: Int] = [:]

    func current(_ id: Int) -> Int { remapped[id] ?? id }
}

struct FlashError: Error, Identifiable {
    let message: String
    var id: String { message }
    init(_ message: String) { self.message = message }
}
