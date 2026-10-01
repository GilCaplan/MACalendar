import AppKit
import AVFoundation
import Foundation
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

/// The Mac's Easter-egg settings — its own, per device (Gil, 2026-09-30: an
/// animation plays on the device the command came from) — kept as one JSON
/// file in this user's data folder. The decisions are EggRules', the same
/// code the phone runs.
@MainActor
final class MacEggStore: ObservableObject {
    static let shared = MacEggStore()

    @Published var settings: EggSettings {
        didSet {
            save()
            if settings.loader != oldValue.loader || settings.objects != oldValue.objects { MacLoader.shared.framesSoon() }
        }
    }
    private var lastPlayed = Date.distantPast
    let file: URL
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1)!
    private var soundReady = false

    private init() {
        let dir = CommandLine.arguments.count > 1 ? CommandLine.arguments[1]
            : (NSHomeDirectory() + "/.assistant_tools")
        file = URL(fileURLWithPath: dir).appendingPathComponent("magic_words.json")
        if let data = try? Data(contentsOf: file), var s = try? JSONDecoder().decode(EggSettings.self, from: data) {
            s.objects = EggCatalog.merged(s.objects)
            settings = s
        } else {
            var s = EggSettings()
            s.passThrough = true          // on a Mac, clicks go through by default
            settings = s
        }
        EggStage.shared.onBatchStart = { batch in
            let s = MacEggStore.shared.settings
            if let first = batch.first(where: { $0.sound != .none }) { MacEggStore.shared.play(first.sound, volume: s.volume) }
        }
    }

    private func save() {
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JSONEncoder().encode(settings).write(to: file, options: .atomic)
    }

    /// `bare`: true when the words were only magic words (don't send them).
    /// `played`: whether anything played.
    func heard(_ text: String, bare: Bool) -> (bare: Bool, played: Bool) {
        let d = EggRules.decide(text, bare: bare, settings: settings, lastPlayed: lastPlayed)
        if !d.ids.isEmpty { play(d.ids, together: d.together) }
        return (d.bareHandled, !d.ids.isEmpty)
    }

    /// The words the brain settled on — corrected by your vocabulary — when
    /// the raw hearing played nothing (Gil, 2026-10-01: "i said val but it
    /// didnt show the graphic"). On its own it plays as a bare word would;
    /// otherwise as one inside a command.
    func heardLate(_ text: String) -> Bool {
        let b = heard(text, bare: true)
        if b.played || b.bare { return b.played }
        return heard(text, bare: false).played
    }

    /// "Also for what gets made", as on the phone (`EggStore.made`): the
    /// categories and tags of what a command just wrote — read by the calendar
    /// app, which has the database — pick what plays through `madeMap`.
    func made(_ labels: [String]) {
        let s = settings
        guard s.enabled, s.forWhatsMade, !labels.isEmpty else { return }
        let byLower = Dictionary(s.madeMap.map { ($0.key.lowercased(), $0.value) }, uniquingKeysWith: { a, _ in a })
        var ids: [String] = []
        for l in labels { if let id = byLower[l.lowercased()], !ids.contains(id) { ids.append(id) } }
        guard !ids.isEmpty, EggRules.allowed(s, now: Date(), lastPlayed: lastPlayed) else { return }
        play(ids, together: s.group != .oneAfterAnother)
    }

    func play(_ ids: [String], together: Bool, caption: String? = nil) {
        lastPlayed = Date()
        EggStage.shared.play(ids, settings: settings, together: together, caption: caption)
    }

    func demo() {
        let pool = EggRules.liveObjects(settings).filter(\.enabled).map(\.id).shuffled()
        play(Array(pool.prefix(settings.group == .oneAfterAnother ? 2 : 3)), together: settings.group != .oneAfterAnother)
    }

    // MARK: - Words and graphics (the phone's EggStore rules)

    /// Who else already has this word (or its plural), if anyone.
    func owner(of word: String, besides id: String) -> EggObject? {
        EggRules.owner(of: word.trimmingCharacters(in: .whitespacesAndNewlines), besides: id, in: settings.objects)
    }

    /// Words on more than one object — to repair.
    var conflicts: [(word: String, ids: [String])] { EggRules.conflicts(settings.objects) }

    /// Keep `word` on `id` only.
    func keepWord(_ word: String, on id: String) {
        for j in settings.objects.indices where settings.objects[j].id != id {
            settings.objects[j].keywords.removeAll { EggRules.sameWord($0, word) }
        }
    }

    /// Add a word, moving it here from wherever else it was — the caller has
    /// already asked (a word summons ONE thing).
    func addKeyword(_ raw: String, to id: String) {
        let word = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !word.isEmpty, let i = settings.objects.firstIndex(where: { $0.id == id }) else { return }
        keepWord(word, on: id)
        if !settings.objects[i].keywords.contains(word) { settings.objects[i].keywords.append(word) }
    }

    // MARK: - Photos (TASKS 46 — the phone's, made here with the same pipeline)

    /// Beside magic_words.json, as the phone keeps them beside eggs.json.
    var folder: URL { file.deletingLastPathComponent().appendingPathComponent("eggs", isDirectory: true) }
    private var images: [String: Image] = [:]

    /// The finished graphic a variant names, for the stage and the previews.
    func image(_ name: String) -> Image? {
        if let hit = images[name] { return hit }
        guard let ns = NSImage(contentsOf: folder.appendingPathComponent(name)) else { return nil }
        let img = Image(nsImage: ns)
        images[name] = img
        return img
    }

    /// Writes a picture into the eggs folder; its file name, or nil.
    func write(_ cg: CGImage, jpeg: Bool = false) -> String? {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let name = UUID().uuidString + (jpeg ? ".jpg" : ".png")
        let type = (jpeg ? UTType.jpeg : UTType.png).identifier as CFString
        guard let dest = CGImageDestinationCreateWithURL(folder.appendingPathComponent(name) as CFURL, type, 1, nil)
        else { return nil }
        CGImageDestinationAddImage(dest, cg, jpeg ? [kCGImageDestinationLossyCompressionQuality: 0.85] as CFDictionary : nil)
        return CGImageDestinationFinalize(dest) ? name : nil
    }

    /// A photo file, upright (its EXIF orientation applied), at most 2048 px.
    static func loadUpright(_ url: URL) -> CGImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                     kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceThumbnailMaxPixelSize: 2048]
        return CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary)
    }

    /// The kept original of a photo variant, to re-outline or re-style it.
    func original(_ name: String) -> CGImage? { Self.loadUpright(folder.appendingPathComponent(name)) }

    /// Drop a variant (never the original — the phone's rule); its files go with it.
    func deleteVariant(_ vid: String, from id: String) {
        guard vid != EggVariant.originalID, let i = settings.objects.firstIndex(where: { $0.id == id }),
              let v = settings.objects[i].variants.first(where: { $0.id == vid }) else { return }
        settings.objects[i].variants.removeAll { $0.id == vid }
        if settings.objects[i].active == vid { settings.objects[i].active = EggVariant.originalID }
        var names: [String] = []
        if case .image(let f) = v.source { names.append(f) }
        if let p = v.photo { names.append(p) }
        for n in names { images[n] = nil; try? FileManager.default.removeItem(at: folder.appendingPathComponent(n)) }
    }

    func replaceVariant(_ v: EggVariant, in id: String) {
        guard let i = settings.objects.firstIndex(where: { $0.id == id }),
              let j = settings.objects[i].variants.firstIndex(where: { $0.id == v.id }) else { return }
        let old = settings.objects[i].variants[j]
        if case .image(let f) = old.source, case .image(let g) = v.source, f != g {
            images[f] = nil
            try? FileManager.default.removeItem(at: folder.appendingPathComponent(f))
        }
        settings.objects[i].variants[j] = v
    }

    func addVariant(_ v: EggVariant, to id: String) {
        guard let i = settings.objects.firstIndex(where: { $0.id == id }) else { return }
        settings.objects[i].variants.append(v)
        settings.objects[i].active = v.id
    }

    @discardableResult
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
        settings.objects.removeAll { $0.id == id && !$0.builtin }
    }

    private var greeted: Set<String> = []

    func festivalTick() {
        guard let (f, key) = EggRules.festivalToGreet(settings, greeted: { UserDefaults.standard.bool(forKey: $0) })
        else { return }
        UserDefaults.standard.set(true, forKey: key)
        play(f.objects, together: true, caption: f.greeting)
    }

    // MARK: - Sound (the phone's synthesis, played here)

    func play(_ sound: EggSound, volume: Double) {
        guard settings.sound, sound != .none, sound != .auto else { return }
        if !soundReady {
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: format)
            soundReady = (try? engine.start()) != nil
        }
        guard soundReady else { return }
        let samples = EggSynth.wave(sound, rate: 44_100)
        guard let b = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count)) else { return }
        b.frameLength = AVAudioFrameCount(samples.count)
        for (i, v) in samples.enumerated() { b.floatChannelData![0][i] = v }
        player.volume = Float(volume)
        player.scheduleBuffer(b, at: nil, options: [])
        if !player.isPlaying { player.play() }
    }
}
