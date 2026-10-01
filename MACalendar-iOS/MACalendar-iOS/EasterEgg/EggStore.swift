import SwiftUI
import UIKit

/// The Easter egg's settings and pictures, on this phone only.
///
/// Per device on purpose: an animation plays on the device the command came
/// from (Gil, 2026-09-30), so each device keeps its own words and pictures.
/// Saved as one JSON file beside the photos in Documents/eggs/.
@MainActor
final class EggStore: ObservableObject {
    static let shared = EggStore()

    @Published var settings: EggSettings { didSet { save() } }

    let folder: URL = {
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("eggs", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()
    private var file: URL { folder.appendingPathComponent("eggs.json") }
    private var images: [String: Image] = [:]

    private init() {
        let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("eggs/eggs.json")
        if let data = try? Data(contentsOf: url),
           var s = try? JSONDecoder().decode(EggSettings.self, from: data) {
            s.objects = EggCatalog.merged(s.objects)
            settings = s
        } else {
            settings = EggSettings()
        }
        EggStage.shared.onBatchStart = { batch in
            let s = EggStore.shared.settings
            if s.haptics { EggSounds.shared.haptic(true) }
            // One sound per batch — a pack of five dogs is one whoosh, not five.
            if let first = batch.first(where: { $0.sound != .none }) {
                EggSounds.shared.play(first.sound, volume: s.volume)
            }
        }
    }

    // MARK: - Playing (the decisions are EggRules', shared with the Mac)

    private var lastPlayed = Date.distantPast

    func allowed(now: Date = Date()) -> Bool {
        EggRules.allowed(settings, now: now, lastPlayed: lastPlayed)
    }

    private func play(_ ids: [String], together: Bool, caption: String? = nil) {
        lastPlayed = Date()
        EggStage.shared.play(ids, settings: settings, together: together, caption: caption)
    }

    private func save() {
        try? JSONEncoder().encode(settings).write(to: file, options: .atomic)
    }

    /// A command's words, as the phone heard them. Returns true when they
    /// were ONLY magic words — the caller then sends nothing (a bare magic
    /// word held back by the surprise rules still isn't a command).
    @discardableResult
    func heard(_ text: String, bare: Bool) -> Bool {
        let d = EggRules.decide(text, bare: bare, settings: settings, lastPlayed: lastPlayed)
        if !d.ids.isEmpty { play(d.ids, together: d.together) }
        return d.bareHandled || (!bare && !d.ids.isEmpty)
    }

    func liveObjects(_ now: Date = Date()) -> [EggObject] { EggRules.liveObjects(settings, now: now) }

    // MARK: - Festival days

    /// On opening the app: the festival app icon, and on a festival day its
    /// show with its greeting — once a day.
    func festivalTick(now: Date = Date()) {
        syncIcon(now: now)
        guard let (f, key) = EggRules.festivalToGreet(settings, now: now,
                                                      greeted: { UserDefaults.standard.bool(forKey: $0) }) else { return }
        UserDefaults.standard.set(true, forKey: key)
        greet(f)
    }

    func greet(_ f: EggFestivals.Festival) {
        play(f.objects, together: true, caption: f.greeting)
    }

    /// The festival's app icon in its days, the usual one otherwise.
    func syncIcon(now: Date = Date()) {
        guard UIApplication.shared.supportsAlternateIcons else { return }
        let want = settings.festivalIcon && settings.jewish ? EggFestivals.current(now).compactMap(\.icon).first : nil
        if UIApplication.shared.alternateIconName != want {
            UIApplication.shared.setAlternateIconName(want) { _ in }
        }
    }

    func demo(_ ids: [String]) {
        play(ids, together: settings.group != .oneAfterAnother)
    }

    /// What a command MADE: each created event's category and task's tags,
    /// through the map in Settings. Runs after the reply, once the rows can
    /// be read back.
    func made(_ rows: [(kind: String, id: Int)], api: APIClient) async {
        let s = settings
        guard s.enabled, s.forWhatsMade, !rows.isEmpty else { return }
        var labels: [String] = []
        for r in rows {
            if r.kind == "event" {
                if let data = try? await api.request("/events/\(r.id)"),
                   let e = try? JSONDecoder().decode(CalendarEvent.self, from: data), let c = e.category {
                    labels.append(c)
                }
            } else if r.kind == "todo" {
                _ = try? await api.todos(list: "all", includeCompleted: true)
                if let t = LocalStore.shared.todo(r.id) { labels.append(contentsOf: t.tags) }
            }
        }
        let byLower = Dictionary(s.madeMap.map { ($0.key.lowercased(), $0.value) }, uniquingKeysWith: { a, _ in a })
        let ids = labels.compactMap { byLower[$0.lowercased()] }
        guard !ids.isEmpty, allowed() else { return }
        play(ids, together: s.group != .oneAfterAnother)
    }

    // MARK: - Pictures

    func image(_ file: String) -> Image? {
        if let hit = images[file] { return hit }
        guard let ui = UIImage(contentsOfFile: folder.appendingPathComponent(file).path) else { return nil }
        let img = Image(uiImage: ui)
        images[file] = img
        return img
    }

    func uiImage(_ file: String) -> UIImage? {
        UIImage(contentsOfFile: folder.appendingPathComponent(file).path)
    }

    func write(_ image: UIImage, jpeg: Bool = false) -> String? {
        let name = UUID().uuidString + (jpeg ? ".jpg" : ".png")
        guard let data = jpeg ? image.jpegData(compressionQuality: 0.85) : image.pngData(),
              (try? data.write(to: folder.appendingPathComponent(name))) != nil else { return nil }
        return name
    }

    private func removeFiles(of v: EggVariant) {
        var names: [String] = []
        if case .image(let f) = v.source { names.append(f) }
        if let p = v.photo { names.append(p) }
        for n in names {
            images[n] = nil
            try? FileManager.default.removeItem(at: folder.appendingPathComponent(n))
        }
    }

    // MARK: - Editing objects

    func index(_ id: String) -> Int? { settings.objects.firstIndex { $0.id == id } }

    /// The other object this word (or its plural) already summons — the
    /// caller asks the user before adding it (Gil: keep, or change).
    func owner(of word: String, besides id: String) -> EggObject? {
        EggRules.owner(of: word.trimmingCharacters(in: .whitespacesAndNewlines), besides: id, in: settings.objects)
    }

    /// Words on more than one object — to repair.
    var conflicts: [(word: String, ids: [String])] { EggRules.conflicts(settings.objects) }

    /// Keep `word` on `id` only: take it (and its plural/singular) off every
    /// other object.
    func keepWord(_ word: String, on id: String) {
        for j in settings.objects.indices where settings.objects[j].id != id {
            settings.objects[j].keywords.removeAll { EggRules.sameWord($0, word) }
        }
    }

    /// Add a keyword. A keyword summons ONE object: the caller has asked the
    /// user (`owner`) and this moves it here, returning where it came from.
    @discardableResult
    func addKeyword(_ raw: String, to id: String) -> String? {
        let word = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !word.isEmpty, let i = index(id) else { return nil }
        var movedFrom: String?
        for j in settings.objects.indices where j != i {
            if settings.objects[j].keywords.contains(where: { EggRules.sameWord($0, word) }) {
                settings.objects[j].keywords.removeAll { EggRules.sameWord($0, word) }
                movedFrom = settings.objects[j].name
            }
        }
        if !settings.objects[i].keywords.contains(word) { settings.objects[i].keywords.append(word) }
        return movedFrom
    }

    func removeKeyword(_ word: String, from id: String) {
        guard let i = index(id) else { return }
        settings.objects[i].keywords.removeAll { $0 == word }
    }

    /// The pointer: which of the object's graphics plays.
    func setActive(_ variant: String, for id: String) {
        guard let i = index(id) else { return }
        settings.objects[i].active = variant
    }

    func addVariant(_ v: EggVariant, to id: String, makeActive: Bool = true) {
        guard let i = index(id) else { return }
        settings.objects[i].variants.append(v)
        if makeActive { settings.objects[i].active = v.id }
    }

    /// Replace an edited photo in place, keeping its place in the list and
    /// the pointer if it was the one playing.
    func replaceVariant(_ v: EggVariant, in id: String) {
        guard let i = index(id), let j = settings.objects[i].variants.firstIndex(where: { $0.id == v.id }) else { return }
        let old = settings.objects[i].variants[j]
        if case .image(let f) = old.source, case .image(let g) = v.source, f != g {
            images[f] = nil
            try? FileManager.default.removeItem(at: folder.appendingPathComponent(f))
        }
        settings.objects[i].variants[j] = v
    }

    /// The original can never go; anything else can.
    func deleteVariant(_ variant: String, from id: String) {
        guard let i = index(id), variant != EggVariant.originalID,
              let j = settings.objects[i].variants.firstIndex(where: { $0.id == variant }) else { return }
        removeFiles(of: settings.objects[i].variants[j])
        settings.objects[i].variants.remove(at: j)
        if settings.objects[i].active == variant { settings.objects[i].active = EggVariant.originalID }
    }

    /// A new object of the user's own, its first photo as its original.
    func addCustom(name: String, keywords: [String], original: EggVariant) -> String {
        let id = "custom-" + UUID().uuidString.prefix(8).lowercased()
        var v = original
        v.id = EggVariant.originalID
        settings.objects.append(EggObject(id: id, name: name, keywords: [], variants: [v],
                                          active: EggVariant.originalID, motion: .flyBy, builtin: false))
        for k in keywords { addKeyword(k, to: id) }
        return id
    }

    func deleteObject(_ id: String) {
        guard let i = index(id), !settings.objects[i].builtin else { return }
        for v in settings.objects[i].variants { removeFiles(of: v) }
        settings.objects.remove(at: i)
    }

    /// A built-in's words back to how they shipped.
    func resetKeywords(_ id: String) {
        guard let d = EggCatalog.defaults().first(where: { $0.id == id }) else { return }
        for k in d.keywords { addKeyword(k, to: id) }
        if let i = index(id) { settings.objects[i].keywords = d.keywords }
    }
}
