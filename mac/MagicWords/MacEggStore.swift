import AVFoundation
import Foundation

/// The Mac's Easter-egg settings — its own, per device (Gil, 2026-09-30: an
/// animation plays on the device the command came from) — kept as one JSON
/// file in this user's data folder. The decisions are EggRules', the same
/// code the phone runs.
@MainActor
final class MacEggStore: ObservableObject {
    static let shared = MacEggStore()

    @Published var settings: EggSettings { didSet { save() } }
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

    /// Returns true when the words were only magic words (don't send them).
    func heard(_ text: String, bare: Bool) -> Bool {
        let d = EggRules.decide(text, bare: bare, settings: settings, lastPlayed: lastPlayed)
        if !d.ids.isEmpty { play(d.ids, together: d.together) }
        return d.bareHandled
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
