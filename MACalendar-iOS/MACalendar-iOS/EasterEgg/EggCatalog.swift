import Foundation
import CoreGraphics

// The Easter egg's data: which words show what, and how.
//
// An OBJECT is the unit (Gil, 2026-09-30): a name, the KEYWORDS that summon
// it, and a list of GRAPHICS for it — the built-in original first, which can
// never be removed, then any photos the user has added or edited copies of —
// with a POINTER to the one that plays. Foundation only, so the word matcher
// can be compiled and tested on its own.

/// When a magic word plays.
enum EggTrigger: String, Codable, CaseIterable {
    /// Said on its own ("dragon!") — plays at once, and nothing is sent.
    case onItsOwn
    /// Said inside a command — plays while the command is being made.
    case inCommand
    case both

    var label: String {
        switch self {
        case .onItsOwn: return "When I say just the word"
        case .inCommand: return "When it's in a command"
        case .both: return "Both"
        }
    }
    var onItsOwn: Bool { self != .inCommand }
    var inCommand: Bool { self != .onItsOwn }
}

/// What a tap on a playing graphic does.
enum EggTap: String, Codable, CaseIterable {
    case vanish, finishThenVanish
    var label: String {
        switch self {
        case .vanish: return "Vanish at once"
        case .finishThenVanish: return "Hurry it along, tap again to close"
        }
    }
}

/// How a figure crosses the screen. `auto` means the object's own.
enum EggMotion: String, Codable, CaseIterable {
    case auto, flyBy, run, swoop, pop, spiral, launch, zigzag
    case bounce, orbit, figureEight, drift, dash, peek, wave, dive, drawn
    var label: String {
        switch self {
        case .auto: return "Its own"
        case .flyBy: return "Fly across"
        case .run: return "Run along the bottom"
        case .swoop: return "Swoop"
        case .pop: return "Pop in"
        case .spiral: return "Spiral"
        case .launch: return "Blast off"
        case .zigzag: return "Zigzag"
        case .bounce: return "Bounce across"
        case .orbit: return "Circle the screen"
        case .figureEight: return "Figure of eight"
        case .drift: return "Float up like a balloon"
        case .dash: return "Anime dash"
        case .peek: return "Peek in"
        case .wave: return "Big waves"
        case .dive: return "Drop in and run"
        case .drawn: return "The path I drew"
        }
    }
}

/// Several magic words in one breath.
enum EggGroupMode: String, Codable, CaseIterable {
    case together, oneAfterAnother, onGroupWord
    var label: String {
        switch self {
        case .together: return "Together"
        case .oneAfterAnother: return "One after another"
        case .onGroupWord: return "Together only with a group word"
        }
    }
}

/// How the graphic is drawn over the screen.
enum EggLook: String, Codable, CaseIterable {
    case solid, glow, outline
    var label: String {
        switch self {
        case .solid: return "Solid"
        case .glow: return "Glowing"
        case .outline: return "Outline only"
        }
    }
}

/// Size, as a percentage of the usual — the slider's range. Whatever it
/// says, a figure is kept between `EggRender.minBox` and `maxBox` points.
enum EggSizeRange {
    static let percent: ClosedRange<Double> = 50...160
    static func clamp(_ p: Double) -> Double { min(max(p, percent.lowerBound), percent.upperBound) }
}

/// How big it plays (the first build's three steps; still read from old
/// settings, turned into a percentage).
enum EggSize: String, Codable, CaseIterable {
    case small, normal, big
    var label: String { rawValue.capitalized }
    var scale: CGFloat { self == .small ? 0.65 : self == .big ? 1.35 : 1 }
}

/// Where on the screen it plays.
enum EggLane: String, Codable, CaseIterable {
    case auto, top, middle, bottom
    var label: String { self == .auto ? "Its own" : rawValue.capitalized }
    /// The centre line, as a fraction of the screen's height.
    var y: Double? { switch self { case .auto: return nil; case .top: return 0.25; case .middle: return 0.45; case .bottom: return 0.72 } }
}

/// The sound a show makes, synthesised on the phone (no recordings).
enum EggSound: String, Codable, CaseIterable {
    case auto, whoosh, chime, pop, boom, thunder, magic, shofar, rattle, none
    var label: String {
        switch self {
        case .auto: return "Its own"
        case .none: return "Silent"
        default: return rawValue.capitalized
        }
    }
}

/// How a PHOTO moves. `auto` uses what the phone recognised in it.
enum EggRig: String, Codable, CaseIterable {
    case auto, walk, roll, flap, hop, still
    var label: String {
        switch self {
        case .auto: return "Automatic"
        case .walk: return "Walk (legs swing)"
        case .roll: return "Roll (wheels spin)"
        case .flap: return "Flap"
        case .hop: return "Hop"
        case .still: return "Stay still"
        }
    }
}

/// Which way it travels. Mirrors the motion; `random` picks per show.
enum EggDirection: String, Codable, CaseIterable {
    case auto, leftToRight, rightToLeft, random
    var label: String {
        switch self {
        case .auto: return "Its own"
        case .leftToRight: return "Left to right"
        case .rightToLeft: return "Right to left"
        case .random: return "Surprise me"
        }
    }
}

/// The subgraphic: what trails behind the main one.
enum EggTrail: String, Codable, CaseIterable {
    case auto, sparkles, stars, hearts, pawPrints, flames, rainbow, bubbles, petals, notes, clouds, leaves, none
    var label: String {
        switch self {
        case .auto: return "Its own"
        case .sparkles: return "Sparkles"
        case .stars: return "Stars"
        case .hearts: return "Hearts"
        case .pawPrints: return "Paw prints"
        case .flames: return "Flames"
        case .rainbow: return "Rainbow ribbon"
        case .bubbles: return "Bubbles"
        case .petals: return "Petals"
        case .notes: return "Music notes"
        case .clouds: return "Clouds"
        case .leaves: return "Leaves"
        case .none: return "Nothing"
        }
    }
}

/// One graphic in an object's list.
struct EggVariant: Codable, Identifiable, Equatable {
    enum Source: Codable, Equatable {
        case figure(String)          // EggFigure raw value
        case effect(String)          // EggEffect raw value
        case image(String)           // the finished PNG's file name, in the eggs folder
        case symbol(String)          // the user's own emoji, flag or SF Symbol (EggSymbol)
    }
    var id: String
    var name: String
    var source: Source
    /// For a photo: the untouched original, kept so it can be re-outlined or
    /// re-styled later without asking for it again.
    var photo: String? = nil
    /// For a photo: the outline drawn by hand (normalised 0…1), or nil for the
    /// automatic cut-out.
    var lasso: [[Double]]? = nil
    /// For a photo: anime-styled, or kept as it is.
    var anime: Bool = false
    /// For a photo: how it moves (nil = automatic), what the phone recognised,
    /// where it found wheels ([cx, cy, r]) and legs ([topX, topY, pawX, pawY]),
    /// all 0…1 of the picture.
    var rig: EggRig? = nil
    var detectedRig: EggRig? = nil
    var wheels: [[Double]]? = nil
    var legs: [[Double]]? = nil
    /// This picture's size against the word's, % (a photo may need to be
    /// bigger or smaller than the drawing it stands beside). nil = 100.
    var scalePercent: Double? = nil

    /// The rig that plays.
    var movement: EggRig {
        let chosen = rig ?? .auto
        return chosen == .auto ? (detectedRig ?? .hop) : chosen
    }

    static let originalID = "original"
    var isOriginal: Bool { id == Self.originalID }
}

struct EggObject: Codable, Identifiable, Equatable {
    var id: String
    var name: String
    var keywords: [String]
    var variants: [EggVariant]
    /// The pointer: which graphic plays.
    var active: String
    var motion: EggMotion = .auto
    var enabled: Bool = true
    var builtin: Bool
    var direction: EggDirection = .auto
    var trail: EggTrail = .auto
    /// The path drawn for `.drawn`: [x, y, t] each 0…1 of the screen and of
    /// the drawing's own time, so pauses and bursts replay as drawn.
    var drawnPath: [[Double]]? = nil
    /// This word's own timing, look, size, place and sound; nil follows the
    /// Easter egg page.
    var entrance: Double? = nil
    var pause: Double? = nil
    var exit: Double? = nil
    var opacity: Double? = nil
    var look: EggLook? = nil
    var size: EggSize? = nil
    /// This word's own size, % of the usual (nil = like the rest).
    var sizePercent: Double? = nil
    var lane: EggLane? = nil
    var sound: EggSound? = nil

    var activeVariant: EggVariant {
        variants.first { $0.id == active } ?? variants[0]
    }

    init(id: String, name: String, keywords: [String], variants: [EggVariant], active: String,
         motion: EggMotion = .auto, enabled: Bool = true, builtin: Bool,
         direction: EggDirection = .auto, trail: EggTrail = .auto) {
        self.id = id; self.name = name; self.keywords = keywords; self.variants = variants
        self.active = active; self.motion = motion; self.enabled = enabled; self.builtin = builtin
        self.direction = direction; self.trail = trail
    }

    /// Settings saved by an earlier build lack the newer fields; they get
    /// their defaults instead of failing the whole file.
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        keywords = try c.decode([String].self, forKey: .keywords)
        variants = try c.decode([EggVariant].self, forKey: .variants)
        active = try c.decode(String.self, forKey: .active)
        builtin = try c.decode(Bool.self, forKey: .builtin)
        motion = (try? c.decodeIfPresent(EggMotion.self, forKey: .motion)) ?? .auto
        enabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? true
        direction = (try? c.decodeIfPresent(EggDirection.self, forKey: .direction)) ?? .auto
        trail = (try? c.decodeIfPresent(EggTrail.self, forKey: .trail)) ?? .auto
        drawnPath = try? c.decodeIfPresent([[Double]].self, forKey: .drawnPath)
        entrance = try? c.decodeIfPresent(Double.self, forKey: .entrance)
        pause = try? c.decodeIfPresent(Double.self, forKey: .pause)
        exit = try? c.decodeIfPresent(Double.self, forKey: .exit)
        opacity = try? c.decodeIfPresent(Double.self, forKey: .opacity)
        look = try? c.decodeIfPresent(EggLook.self, forKey: .look)
        size = try? c.decodeIfPresent(EggSize.self, forKey: .size)
        sizePercent = (try? c.decodeIfPresent(Double.self, forKey: .sizePercent)) ?? size.map { Double($0.scale) * 100 }
        lane = try? c.decodeIfPresent(EggLane.self, forKey: .lane)
        sound = try? c.decodeIfPresent(EggSound.self, forKey: .sound)
    }
}

struct EggSettings: Codable, Equatable {
    var enabled = true
    var trigger: EggTrigger = .both
    /// Several words at once: together as a group, one after another, or
    /// together only when a group word ("pack", "flock"…) is said too.
    var group: EggGroupMode = .together
    var groupWords: [String] = EggCatalog.groupWords
    /// A plural ("dogs") brings this many; 1 means just one.
    var pluralCount = 3
    /// The three steps of a show: coming in, pausing mid-screen, going out.
    var entrance: Double = 1.5
    var pause: Double = 0
    var exit: Double = 1.5
    /// Hold mid-screen until tapped (or until the next one, with touches off).
    var untilTapped = false
    /// Touches go through to the app underneath while it plays.
    var passThrough = false
    /// 0.15…1 — see the screen through it, or not.
    var opacity: Double = 1
    var look: EggLook = .solid
    var size: EggSize = .normal
    /// Size for every word, % of the usual (`EggSizeRange`).
    var sizePercent: Double = 100
    var lane: EggLane = .auto
    var tap: EggTap = .vanish
    /// Sound (off unless switched on — it's a surprise in a quiet room), its
    /// volume, and a tap of haptics as it arrives.
    var sound = false
    var volume: Double = 0.6
    var haptics = true
    /// Keep it a surprise: play one time in `chance`, not within `cooldown`
    /// seconds of the last one, and never in quiet hours (minutes of the day).
    var chance = 1
    var cooldown: Double = 0
    var quietHours = false
    var quietFrom = 22 * 60
    var quietTo = 7 * 60
    /// Also play for what a command MADE: an event's category or a task's
    /// tag → the object that plays for it.
    var forWhatsMade = false
    var madeMap: [String: String] = EggCatalog.madeMap
    /// The Jewish festivals set: on or off as a whole; its words only in
    /// their season; a greeting on festival days; a festive touch in the
    /// app; the festival's app icon.
    var jewish = true
    var jewishInSeason = false
    var festivalGreeting = true
    var festivalDecor = true
    var festivalIcon = false
    /// The loading screen the user builds (EggLoader.swift).
    var loader = EggLoaderConfig()
    /// Seconds of motion, entrance plus exit.
    var seconds: Double { entrance + exit }
    /// Override every object's own choice unless `.auto`.
    var motion: EggMotion = .auto
    var direction: EggDirection = .auto
    var trail: EggTrail = .auto
    /// The path for everything when `motion` is `.drawn`.
    var drawnPath: [[Double]]? = nil
    var objects: [EggObject] = EggCatalog.defaults()

    init() {}

    enum CodingKeys: String, CodingKey {
        case enabled, trigger, together, group, groupWords, pluralCount, entrance, pause, exit, untilTapped, passThrough, opacity, look, tap
        case size, sizePercent, lane, sound, volume, haptics, chance, cooldown, quietHours, quietFrom, quietTo, forWhatsMade, madeMap
        case jewish, jewishInSeason, festivalGreeting, festivalDecor, festivalIcon, loader
        case motion, direction, trail, drawnPath, objects
        case legacySeconds = "seconds"
    }

    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: CodingKeys.self)
        try c.encode(enabled, forKey: .enabled); try c.encode(trigger, forKey: .trigger)
        try c.encode(group, forKey: .group); try c.encode(groupWords, forKey: .groupWords)
        try c.encode(pluralCount, forKey: .pluralCount); try c.encode(entrance, forKey: .entrance)
        try c.encode(pause, forKey: .pause); try c.encode(exit, forKey: .exit)
        try c.encode(untilTapped, forKey: .untilTapped); try c.encode(passThrough, forKey: .passThrough)
        try c.encode(opacity, forKey: .opacity); try c.encode(look, forKey: .look); try c.encode(tap, forKey: .tap)
        try c.encode(motion, forKey: .motion); try c.encode(direction, forKey: .direction)
        try c.encode(trail, forKey: .trail); try c.encodeIfPresent(drawnPath, forKey: .drawnPath)
        try c.encode(size, forKey: .size); try c.encode(sizePercent, forKey: .sizePercent)
        try c.encode(lane, forKey: .lane); try c.encode(sound, forKey: .sound)
        try c.encode(volume, forKey: .volume); try c.encode(haptics, forKey: .haptics)
        try c.encode(chance, forKey: .chance); try c.encode(cooldown, forKey: .cooldown)
        try c.encode(quietHours, forKey: .quietHours); try c.encode(quietFrom, forKey: .quietFrom)
        try c.encode(quietTo, forKey: .quietTo); try c.encode(forWhatsMade, forKey: .forWhatsMade)
        try c.encode(madeMap, forKey: .madeMap)
        try c.encode(jewish, forKey: .jewish); try c.encode(jewishInSeason, forKey: .jewishInSeason)
        try c.encode(festivalGreeting, forKey: .festivalGreeting); try c.encode(festivalDecor, forKey: .festivalDecor)
        try c.encode(festivalIcon, forKey: .festivalIcon)
        try c.encode(loader, forKey: .loader)
        try c.encode(objects, forKey: .objects)
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        let base = EggSettings()
        enabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? base.enabled
        trigger = (try? c.decodeIfPresent(EggTrigger.self, forKey: .trigger)) ?? base.trigger
        if let old = try? c.decodeIfPresent(Bool.self, forKey: .together) { group = old ? .together : .oneAfterAnother }
        group = (try? c.decodeIfPresent(EggGroupMode.self, forKey: .group)) ?? group
        groupWords = (try? c.decodeIfPresent([String].self, forKey: .groupWords)) ?? base.groupWords
        pluralCount = (try? c.decodeIfPresent(Int.self, forKey: .pluralCount)) ?? base.pluralCount
        // An earlier build saved one length; it becomes the two halves.
        if let old = try? c.decodeIfPresent(Double.self, forKey: .legacySeconds) {
            entrance = old / 2; exit = old / 2
        }
        entrance = (try? c.decodeIfPresent(Double.self, forKey: .entrance)) ?? entrance
        exit = (try? c.decodeIfPresent(Double.self, forKey: .exit)) ?? exit
        pause = (try? c.decodeIfPresent(Double.self, forKey: .pause)) ?? 0
        untilTapped = (try? c.decodeIfPresent(Bool.self, forKey: .untilTapped)) ?? false
        passThrough = (try? c.decodeIfPresent(Bool.self, forKey: .passThrough)) ?? false
        opacity = (try? c.decodeIfPresent(Double.self, forKey: .opacity)) ?? 1
        look = (try? c.decodeIfPresent(EggLook.self, forKey: .look)) ?? .solid
        size = (try? c.decodeIfPresent(EggSize.self, forKey: .size)) ?? .normal
        sizePercent = (try? c.decodeIfPresent(Double.self, forKey: .sizePercent)) ?? Double(size.scale) * 100
        lane = (try? c.decodeIfPresent(EggLane.self, forKey: .lane)) ?? .auto
        sound = (try? c.decodeIfPresent(Bool.self, forKey: .sound)) ?? false
        volume = (try? c.decodeIfPresent(Double.self, forKey: .volume)) ?? 0.6
        haptics = (try? c.decodeIfPresent(Bool.self, forKey: .haptics)) ?? true
        chance = (try? c.decodeIfPresent(Int.self, forKey: .chance)) ?? 1
        cooldown = (try? c.decodeIfPresent(Double.self, forKey: .cooldown)) ?? 0
        quietHours = (try? c.decodeIfPresent(Bool.self, forKey: .quietHours)) ?? false
        quietFrom = (try? c.decodeIfPresent(Int.self, forKey: .quietFrom)) ?? 22 * 60
        quietTo = (try? c.decodeIfPresent(Int.self, forKey: .quietTo)) ?? 7 * 60
        forWhatsMade = (try? c.decodeIfPresent(Bool.self, forKey: .forWhatsMade)) ?? false
        madeMap = (try? c.decodeIfPresent([String: String].self, forKey: .madeMap)) ?? base.madeMap
        jewish = (try? c.decodeIfPresent(Bool.self, forKey: .jewish)) ?? true
        jewishInSeason = (try? c.decodeIfPresent(Bool.self, forKey: .jewishInSeason)) ?? false
        festivalGreeting = (try? c.decodeIfPresent(Bool.self, forKey: .festivalGreeting)) ?? true
        festivalDecor = (try? c.decodeIfPresent(Bool.self, forKey: .festivalDecor)) ?? true
        festivalIcon = (try? c.decodeIfPresent(Bool.self, forKey: .festivalIcon)) ?? false
        loader = (try? c.decodeIfPresent(EggLoaderConfig.self, forKey: .loader)) ?? EggLoaderConfig()
        tap = (try? c.decodeIfPresent(EggTap.self, forKey: .tap)) ?? base.tap
        motion = (try? c.decodeIfPresent(EggMotion.self, forKey: .motion)) ?? .auto
        direction = (try? c.decodeIfPresent(EggDirection.self, forKey: .direction)) ?? .auto
        trail = (try? c.decodeIfPresent(EggTrail.self, forKey: .trail)) ?? .auto
        drawnPath = try? c.decodeIfPresent([[Double]].self, forKey: .drawnPath)
        objects = (try? c.decodeIfPresent([EggObject].self, forKey: .objects)) ?? base.objects
    }
}

enum EggCatalog {
    /// What plays for what gets made, out of the box: an event's category or
    /// a task's tag → an object. Editable in Settings.
    static let madeMap: [String: String] = [
        "Travel": "plane", "Dog walking": "dog", "Social": "confetti", "Study": "owl", "Family": "fireworks",
    ]

    /// The object's own sound, for `.auto`.
    static func defaultSound(_ id: String, motion: EggMotion) -> EggSound {
        switch id {
        case "fireworks": return .boom
        case "lightning": return .thunder
        case "fairy", "wizard", "unicorn", "rainbow", "phoenix": return .magic
        case "confetti", "snow", "menorah", "candles": return .chime
        case "shofar": return .shofar
        case "grogger": return .rattle
        default: return motion == .pop ? .pop : .whoosh
        }
    }

    /// Words that ask for a group when `group` is `.onGroupWord`.
    static let groupWords = ["pack", "group", "gang", "herd", "flock", "squad", "team", "crowd", "family"]

    /// Built-ins: (id, name, keywords, figure or effect, is effect).
    static let builtins: [(String, String, [String], Bool)] = [
        ("dog", "German Shepherd", ["dog", "puppy", "doggy", "pup", "german shepherd"], false),
        ("dragon", "Dragon", ["dragon"], false),
        ("fairy", "Fairy", ["fairy"], false),
        ("wolf", "Wolf", ["wolf", "wolves"], false),
        ("car", "Car", ["car"], false),
        ("plane", "Plane", ["plane", "airplane", "aeroplane", "flight"], false),
        ("unicorn", "Unicorn", ["unicorn"], false),
        ("phoenix", "Phoenix", ["phoenix"], false),
        ("griffin", "Griffin", ["griffin", "gryphon"], false),
        ("wizard", "Wizard", ["wizard"], false),
        ("cat", "Cat", ["cat", "kitten", "kitty"], false),
        ("horse", "Horse", ["horse", "pony"], false),
        ("lion", "Lion", ["lion"], false),
        ("eagle", "Eagle", ["eagle"], false),
        ("shark", "Shark", ["shark"], false),
        ("owl", "Owl", ["owl"], false),
        ("rocket", "Rocket", ["rocket", "spaceship"], false),
        ("ufo", "UFO", ["ufo", "alien"], false),
        ("train", "Train", ["train"], false),
        ("motorcycle", "Motorcycle", ["motorcycle", "motorbike"], false),
        ("helicopter", "Helicopter", ["helicopter", "chopper"], false),
        ("fireworks", "Fireworks", ["fireworks", "firework"], true),
        ("confetti", "Confetti", ["confetti", "party", "celebrate"], true),
        ("rainbow", "Rainbow", ["rainbow"], true),
        ("lightning", "Lightning", ["lightning", "thunder", "storm"], true),
        ("snow", "Snow", ["snow", "snowing", "blizzard"], true),
        // The Jewish festivals set — one switch in Settings covers them all.
        ("sukkah", "Sukkah", ["sukkah", "succah", "sukka", "sukkot", "succot", "succos", "sukkos"], false),
        ("lulav", "Lulav", ["lulav", "four species", "arba minim", "naanuim"], false),
        ("etrog", "Etrog", ["etrog", "esrog"], false),
        ("shofar", "Shofar", ["shofar", "rosh hashanah", "rosh hashana", "tekiah"], false),
        ("applehoney", "Apple and honey", ["apple and honey", "apples and honey", "honey", "shana tova", "shanah tovah"], false),
        ("menorah", "Menorah", ["menorah", "chanukiah", "hanukiah", "chanukah", "hanukkah"], false),
        ("dreidel", "Dreidel", ["dreidel", "sevivon"], false),
        ("mask", "Purim mask", ["mask", "costume", "purim"], false),
        ("grogger", "Grogger", ["grogger", "raashan", "ra'ashan", "haman"], false),
        ("hamantasch", "Hamantasch", ["hamantasch", "hamantaschen", "hamentash", "oznei haman"], false),
        ("matzah", "Matzah", ["matzah", "matza", "matzo", "pesach", "passover", "seder"], false),
        ("candles", "Shabbat candles", ["shabbat candles", "candle lighting", "candles", "shabbat shalom"], false),
        ("challah", "Challah", ["challah", "chala", "hallah"], false),
        ("torah", "Torah", ["torah", "sefer torah", "simchat torah", "shavuot", "hakafot"], false),
    ]

    /// The Jewish festivals set.
    static let jewish: Set<String> = ["sukkah", "lulav", "etrog", "shofar", "applehoney", "menorah", "dreidel",
                                      "mask", "grogger", "hamantasch", "matzah", "candles", "challah", "torah"]

    static func defaults() -> [EggObject] {
        builtins.map { id, name, words, effect in
            EggObject(id: id, name: name, keywords: words,
                      variants: [EggVariant(id: EggVariant.originalID, name: "Original",
                                            source: effect ? .effect(id) : .figure(id))],
                      active: EggVariant.originalID, builtin: true)
        }
    }

    /// Add any built-in a newer build ships that this saved list lacks —
    /// without touching the user's own keywords, photos or pointers.
    static func merged(_ saved: [EggObject]) -> [EggObject] {
        var out = saved
        let have = Set(saved.map(\.id))
        for d in defaults() where !have.contains(d.id) { out.append(d) }
        return out
    }

    /// The object's own motion, for `.auto`.
    static func defaultMotion(_ id: String) -> EggMotion {
        switch id {
        case "dog", "wolf", "cat", "horse", "unicorn", "lion", "car", "motorcycle", "train": return .run
        case "dragon", "phoenix", "griffin", "eagle": return .swoop
        case "fairy": return .zigzag
        case "ufo": return .figureEight
        case "rocket": return .launch
        case "wizard": return .pop
        case "shark": return .wave
        case "lulav", "sukkah", "shofar", "menorah", "candles", "grogger", "applehoney": return .pop
        case "etrog", "hamantasch", "challah": return .bounce
        case "dreidel", "torah": return .run
        case "mask": return .zigzag
        default: return .flyBy
        }
    }

    /// The object's own trail, for `.auto`.
    static func defaultTrail(_ id: String) -> EggTrail {
        switch id {
        case "dog", "wolf", "cat", "lion": return .pawPrints
        case "dragon", "phoenix": return .flames
        case "unicorn": return .rainbow
        case "fairy", "griffin", "ufo": return .sparkles
        case "wizard", "rocket": return .stars
        case "shark": return .bubbles
        case "plane", "helicopter", "eagle", "horse": return .clouds
        case "owl": return .leaves
        case "lulav", "sukkah": return .leaves
        case "mask", "menorah", "candles", "torah": return .stars
        case "grogger", "shofar": return .notes
        case "applehoney": return .hearts
        default: return .sparkles
        }
    }
}

// MARK: - Finding magic words

enum EggMatcher {
    /// Words that do not make an utterance a command: "a dragon!", "wow, a
    /// unicorn", and the spoken stop words the recogniser also hears.
    static let filler: Set<String> = [
        "a", "an", "the", "some", "my", "and", "or", "please", "hey", "oh", "wow", "look",
        "show", "me", "lots", "of", "more", "another", "one", "two", "three", "many", "big",
        "little", "cute", "yay", "its", "it's", "so", "cool", "awesome", "super", "hi", "hello",
        "execute", "done", "go", "stop", "submit", "confirm", "like", "um", "uh", "yes",
    ]

    /// Lower-case words, apostrophes kept inside, a trailing "'s" dropped.
    static func tokens(_ text: String) -> [String] {
        var out: [String] = []
        var cur = ""
        for ch in text.lowercased() {
            if ch.isLetter || ch.isNumber || ch == "'" || ch == "’" {
                cur.append(ch == "’" ? "'" : ch)
            } else if !cur.isEmpty {
                out.append(cur); cur = ""
            }
        }
        if !cur.isEmpty { out.append(cur) }
        return out.map { w in
            var w = w.trimmingCharacters(in: CharacterSet(charactersIn: "'"))
            if w.hasSuffix("'s") { w.removeLast(2) }
            return w
        }.filter { !$0.isEmpty }
    }

    static let numberWords: [String: Int] = [
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "couple": 2, "pair": 2, "few": 3, "several": 4, "dozen": 8,
    ]

    /// A count said just before word `i`: "three", "3", "a couple of", "a
    /// pair of", skipping one describing word ("three big dogs").
    static func number(before i: Int, in words: [String]) -> Int? {
        var j = i - 1
        if j >= 0, words[j] == "of" { j -= 1 }
        for _ in 0..<2 where j >= 0 {
            if let n = numberWords[words[j]] ?? Int(words[j]), n > 0 { return n }
            j -= 1
        }
        return nil
    }

    /// Does the spoken `word` say `keyword` — itself, or a regular plural?
    static func same(_ word: String, _ keyword: String) -> Bool {
        if word == keyword { return true }
        if word == keyword + "s" || word == keyword + "es" { return true }
        if keyword.hasSuffix("y"), word == keyword.dropLast() + "ies" { return true }
        return false
    }

    /// The objects the text summons, in the order they are said, repeats kept
    /// ("a dog and another dog" is two dogs). Longer keywords win, so
    /// "german shepherd" is one dog, not a dog and a stray word.
    static func matches(_ text: String, objects: [EggObject], plural: Int = 1) -> (ids: [String], covered: Set<Int>) {
        let words = tokens(text)
        var table: [(id: String, phrase: [String])] = []
        for o in objects where o.enabled {
            for k in o.keywords {
                let phrase = tokens(k)
                if !phrase.isEmpty { table.append((o.id, phrase)) }
            }
        }
        table.sort { $0.phrase.count > $1.phrase.count }
        var ids: [String] = []
        var covered = Set<Int>()
        var i = 0
        while i < words.count {
            var hit = false
            for entry in table where i + entry.phrase.count <= words.count {
                let n = entry.phrase.count
                let ok = (0..<n).allSatisfy { j in
                    j == n - 1 ? same(words[i + j], entry.phrase[j]) : words[i + j] == entry.phrase[j]
                }
                if ok {
                    // "dogs" is a pack when plurals are on; "dog" is one dog.
                    let last = words[i + n - 1]
                    let kw = entry.phrase[n - 1]
                    // Said as a plural ("dogs" for "dog"), or the keyword is
                    // itself an irregular plural ("wolves").
                    let isPlural = last != kw || kw.hasSuffix("ves") || kw.hasSuffix("ies")
                    // "three dogs" / "3 dogs" / "a couple of dogs" is exactly that many.
                    var count = isPlural ? max(1, plural) : 1
                    if let said = number(before: i, in: words) { count = said }
                    ids.append(contentsOf: Array(repeating: entry.id, count: min(count, 8)))
                    for j in 0..<n { covered.insert(i + j) }
                    i += n
                    hit = true
                    break
                }
            }
            if !hit { i += 1 }
        }
        return (ids, covered)
    }

    /// Nothing but magic words (and filler, and group words): play them,
    /// send nothing.
    static func isBare(_ text: String, objects: [EggObject], groupWords: [String] = EggCatalog.groupWords) -> Bool {
        let words = tokens(text)
        let m = matches(text, objects: objects)
        guard !m.ids.isEmpty else { return false }
        let group = Set(groupWords.map { $0.lowercased() })
        return words.indices.allSatisfy { m.covered.contains($0) || filler.contains(words[$0]) || group.contains(words[$0]) }
    }

    /// Does the text ask for a group ("a pack of dogs")?
    static func saysGroup(_ text: String, groupWords: [String]) -> Bool {
        let group = Set(groupWords.map { $0.lowercased() })
        return tokens(text).contains { group.contains($0) }
    }
}
