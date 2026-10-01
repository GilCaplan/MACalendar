import Foundation

/// The built-in fallback for "Suggest words" (Gil, 2026-09-30): the things
/// people are likely to make magic words of, each with the other names people
/// say for it. When no model answers — or answers with fewer words than were
/// asked for — the rest are drawn from here, at random, so asking again gives
/// different ones. Platform-neutral; `test_easter_egg.py` tests it.
enum EggWordBank {
    /// (what identifies the entry — an object id, a name, a keyword — , its words)
    static let entries: [([String], [String])] = [
        // The built-ins.
        (["dog", "german shepherd", "puppy", "doggy"], ["pup", "pooch", "hound", "doggo", "mutt", "canine", "alsatian",
            "labrador", "retriever", "poodle", "beagle", "husky", "collie", "terrier", "good boy", "woof", "four-legged friend"]),
        (["dragon"], ["drake", "wyvern", "wyrm", "dragonet", "fire drake", "lindworm", "serpent", "fire-breather", "smaug"]),
        (["fairy"], ["fairies", "pixie", "sprite", "fae", "tinker bell", "fairy godmother", "nymph", "tooth fairy", "elf"]),
        (["wolf", "wolves"], ["wolf pack", "grey wolf", "timber wolf", "howl", "alpha", "werewolf", "dire wolf", "lone wolf"]),
        (["car"], ["automobile", "motor car", "sports car", "vroom", "ride", "wheels", "race car", "convertible", "taxi",
            "jeep", "sedan", "road trip", "drive"]),
        (["plane", "airplane", "flight"], ["aeroplane", "jet", "aircraft", "airliner", "jumbo jet", "flying", "airport",
            "take off", "boarding", "fly"]),
        (["unicorn"], ["unicorns", "pegasus", "rainbow horse", "magical horse", "alicorn", "sparkle pony"]),
        (["phoenix"], ["firebird", "fire bird", "rising from the ashes", "flame bird", "sun bird"]),
        (["griffin", "gryphon"], ["griffon", "hippogriff", "eagle lion", "mythical beast"]),
        (["wizard"], ["sorcerer", "magician", "mage", "warlock", "witch", "merlin", "gandalf", "spell", "magic", "abracadabra"]),
        (["cat", "kitten", "kitty"], ["kitty cat", "pussycat", "tabby", "feline", "meow", "moggy", "tomcat", "purr"]),
        (["horse", "pony"], ["stallion", "mare", "foal", "colt", "steed", "horseback", "riding", "gallop", "neigh"]),
        (["lion"], ["lioness", "king of the jungle", "big cat", "roar", "cub", "simba", "leo"]),
        (["eagle"], ["bald eagle", "golden eagle", "bird of prey", "hawk", "falcon", "raptor", "soar"]),
        (["shark"], ["great white", "jaws", "hammerhead", "sharks", "fin", "shark attack", "baby shark"]),
        (["owl"], ["hoot", "barn owl", "night owl", "owlet", "hedwig", "whoo"]),
        (["rocket", "spaceship"], ["space shuttle", "blast off", "launch", "spacecraft", "moon landing", "astronaut",
            "countdown", "liftoff", "to the moon"]),
        (["ufo", "alien"], ["flying saucer", "spaceship", "martian", "extraterrestrial", "et", "abduction", "area 51"]),
        (["train"], ["railway", "choo choo", "locomotive", "steam train", "subway", "metro", "tram", "rail", "platform"]),
        (["motorcycle", "motorbike"], ["motorbike", "bike ride", "harley", "scooter", "vespa", "biker", "moped", "dirt bike"]),
        (["helicopter", "chopper"], ["heli", "whirlybird", "copter", "rotor"]),
        (["fireworks", "firework"], ["pyrotechnics", "sparklers", "rockets", "firecrackers", "bang", "light show",
            "new year", "celebration"]),
        (["confetti", "party", "celebrate"], ["celebration", "hooray", "yay", "woohoo", "congrats", "congratulations",
            "birthday", "surprise", "mazal tov", "mazel tov", "party time"]),
        (["rainbow"], ["rainbows", "colours", "colors", "double rainbow", "pot of gold"]),
        (["lightning", "thunder", "storm"], ["thunderstorm", "lightning bolt", "bolt", "zap", "flash", "thunderbolt"]),
        (["snow", "snowing", "blizzard"], ["snowfall", "snowflake", "snowflakes", "snowman", "winter", "flurries", "ski", "skiing"]),
        // The Jewish festivals set.
        (["sukkah", "sukkot"], ["succah", "sukka", "booth", "sukkot", "succos", "sukkos", "chag", "chol hamoed", "ushpizin", "schach"]),
        (["lulav", "four species"], ["arba minim", "four species", "lulav and etrog", "hadassim", "aravot", "naanuim", "hoshana"]),
        (["etrog", "esrog"], ["esrog", "citron", "arba minim"]),
        (["shofar"], ["tekiah", "shevarim", "teruah", "tekiah gedolah", "ram's horn", "rosh hashanah", "yom kippur", "blow the shofar"]),
        (["apple and honey", "applehoney", "honey"], ["shana tova", "shanah tovah", "sweet new year", "rosh hashanah",
            "honey cake", "pomegranate", "tapuach bidvash"]),
        (["menorah", "chanukah", "hanukkah"], ["chanukiah", "hanukkiah", "hanukkah", "chanukah", "candle lighting",
            "festival of lights", "shamash", "latkes", "sufganiyot", "maoz tzur"]),
        (["dreidel", "sevivon"], ["sevivon", "nun gimel hei shin", "gelt", "spinning top"]),
        (["mask", "costume", "purim"], ["purim", "costume", "dress up", "masquerade", "disguise", "mishloach manot", "megillah"]),
        (["grogger", "haman"], ["raashan", "noisemaker", "rattle", "megillah", "haman"]),
        (["hamantasch"], ["hamantaschen", "oznei haman", "hamentash", "purim cookie", "mishloach manot"]),
        (["matzah", "pesach", "passover"], ["matza", "matzo", "matzos", "seder", "pesach", "passover", "afikoman",
            "haggadah", "charoset", "four cups", "chametz"]),
        (["candles", "shabbat candles"], ["shabbat", "shabbos", "candle lighting", "shabbat shalom", "good shabbos", "havdalah", "kiddush"]),
        (["challah"], ["challot", "chala", "hallah", "braided bread", "shabbat bread", "hamotzi"]),
        (["torah"], ["sefer torah", "simchat torah", "hakafot", "shavuot", "parsha", "aliyah", "torah reading", "scroll"]),
        // Common things people make their own.
        (["baby"], ["newborn", "infant", "little one", "bubba", "tiny human", "diaper", "nap time"]),
        (["grandma", "grandmother"], ["savta", "bubbie", "bubby", "nana", "granny", "oma", "grandmother"]),
        (["grandpa", "grandfather"], ["saba", "zaidy", "zeide", "grandad", "papa", "opa", "grandfather"]),
        (["coffee"], ["espresso", "latte", "cappuccino", "cup of coffee", "caffeine", "americano", "flat white"]),
        (["pizza"], ["slice", "pepperoni", "margherita", "pizza night", "pie"]),
        (["cake", "birthday"], ["birthday cake", "happy birthday", "candles", "cupcake", "yom huledet", "b-day"]),
        (["gym", "workout"], ["training", "lifting", "weights", "exercise", "cardio", "run", "running", "fitness"]),
        (["football", "soccer"], ["soccer", "goal", "match", "kickoff", "the game", "ball"]),
        (["basketball"], ["hoops", "dunk", "slam dunk", "court", "nba"]),
        (["beach", "sea"], ["seaside", "ocean", "waves", "sand", "swim", "surf", "yam"]),
        (["sun", "sunny"], ["sunshine", "sunny day", "heatwave", "summer", "shemesh"]),
        (["moon"], ["full moon", "crescent", "moonlight", "rosh chodesh", "lunar"]),
        (["star", "stars"], ["shooting star", "starry night", "twinkle", "galaxy", "constellation"]),
        (["heart", "love"], ["love", "hearts", "sweetheart", "valentine", "crush", "i love you"]),
        (["flower", "flowers"], ["rose", "roses", "bouquet", "tulip", "blossom", "daisy", "sunflower"]),
        (["tree"], ["forest", "oak", "palm tree", "pine", "tu bishvat", "woods"]),
        (["bike", "bicycle"], ["cycling", "bike ride", "cycle", "pedal", "mountain bike"]),
        (["boat", "ship"], ["sailing", "yacht", "cruise", "ferry", "sailboat", "canoe", "kayak"]),
        (["bus"], ["coach", "bus ride", "school bus", "shuttle", "egged"]),
        (["robot"], ["android", "droid", "bot", "cyborg", "machine", "beep boop"]),
        (["ghost"], ["spooky", "boo", "spirit", "phantom", "haunted"]),
        (["bee"], ["bumblebee", "honeybee", "buzz", "hive", "honey"]),
        (["butterfly"], ["butterflies", "moth", "caterpillar", "monarch", "flutter"]),
        (["fish"], ["goldfish", "nemo", "fishing", "aquarium", "fishy"]),
        (["bird"], ["birdie", "tweet", "songbird", "sparrow", "pigeon", "parrot"]),
        (["rabbit", "bunny"], ["bunny", "bunnies", "hare", "hop", "carrot"]),
        (["bear"], ["teddy bear", "teddy", "grizzly", "polar bear", "panda", "cub"]),
        (["monkey"], ["ape", "chimp", "gorilla", "cheeky monkey", "banana"]),
        (["elephant"], ["dumbo", "trunk", "jumbo", "baby elephant"]),
        (["penguin"], ["penguins", "waddle", "emperor penguin", "pingu"]),
        (["frog"], ["froggy", "toad", "ribbit", "tadpole"]),
        (["turtle"], ["tortoise", "sea turtle", "shell", "slowpoke"]),
        (["dinosaur", "rex", "t-rex"], ["t rex", "t-rex", "tyrannosaurus", "raptor", "dino", "jurassic", "triceratops", "roar"]),
    ]

    // MARK: - Adjectives (Gil: "prefixes of adjectives is important here")

    /// Adjectives that fit a kind of thing. "baby dragon" is a word worth
    /// having: the matcher prefers the longer phrase, so it can summon a
    /// different object (a photo of a baby dragon) than plain "dragon".
    static let adjectives: [String: [String]] = [
        "animal": ["big", "little", "baby", "cute", "fluffy", "happy", "sleepy", "fierce", "brave", "fat",
                   "tiny", "giant", "good", "naughty", "wild"],
        "mythic": ["baby", "giant", "magic", "flying", "golden", "fire", "ice", "tiny", "ancient", "friendly", "evil"],
        "vehicle": ["fast", "red", "old", "new", "racing", "little", "big", "shiny", "electric", "vintage"],
        "sky": ["big", "huge", "beautiful", "massive", "crazy", "first"],
        "festival": ["happy", "beautiful", "big", "family", "first", "last"],
        "food": ["fresh", "warm", "sweet", "homemade", "big", "delicious", "hot"],
        "person": ["my", "dear", "sweet", "little", "old"],
        "thing": ["big", "little", "new", "old", "beautiful", "favourite"],
    ]

    static func kind(of match: [String]) -> String {
        let m = Set(match)
        func any(_ ids: [String]) -> Bool { !m.isDisjoint(with: ids) }
        if any(["dragon", "fairy", "unicorn", "phoenix", "griffin", "wizard", "ufo", "alien", "ghost", "robot", "dinosaur"]) { return "mythic" }
        if any(["car", "plane", "rocket", "train", "motorcycle", "helicopter", "bike", "boat", "bus"]) { return "vehicle" }
        if any(["fireworks", "confetti", "rainbow", "lightning", "snow", "sun", "moon", "star"]) { return "sky" }
        if any(["sukkah", "lulav", "etrog", "shofar", "menorah", "dreidel", "mask", "grogger", "torah", "candles"]) { return "festival" }
        if any(["hamantasch", "matzah", "challah", "applehoney", "coffee", "pizza", "cake"]) { return "food" }
        if any(["baby", "grandma", "grandpa"]) { return "person" }
        if any(["dog", "wolf", "cat", "horse", "lion", "eagle", "shark", "owl", "bee", "butterfly", "fish", "bird",
                "rabbit", "bear", "monkey", "elephant", "penguin", "frog", "turtle"]) { return "animal" }
        return "thing"
    }

    /// "adjective noun" phrases for an object: the kind's adjectives on its
    /// main word (its first keyword, else its name).
    static func adjectivePhrases(id: String?, name: String, keywords: [String]) -> [String] {
        let noun = (keywords.first ?? name).lowercased()
        guard !noun.isEmpty, noun.split(separator: " ").count <= 2 else { return [] }
        let kinds = Set(matching(id: id, name: name, keywords: keywords).map { kind(of: $0.0) })
        let adjs = (kinds.isEmpty ? ["thing"] : Array(kinds)).flatMap { adjectives[$0] ?? [] }
        return Array(Set(adjs)).sorted().map { "\($0) \(noun)" }
    }

    /// The entries an object draws from: the ones its id or keywords name —
    /// and only when those name none, the ones its name does (a dog called
    /// "Rex" is a dog, not a T. rex).
    static func matching(id: String?, name: String, keywords: [String]) -> [([String], [String])] {
        let strong = Set(([id ?? ""] + keywords.map { $0.lowercased() }).filter { !$0.isEmpty })
        let byStrong = entries.filter { $0.0.contains(where: { strong.contains($0) }) }
        if !byStrong.isEmpty { return byStrong }
        let weak = Set([name.lowercased()] + EggMatcher.tokens(name))
        return entries.filter { $0.0.contains(where: { weak.contains($0) }) }
    }

    /// The candidate words for an object, from the entries it draws from.
    static func candidates(id: String?, name: String, keywords: [String]) -> [String] {
        var out: [String] = []
        for (match, words) in matching(id: id, name: name, keywords: keywords) {
            for w in match + words where !out.contains(w) { out.append(w) }
        }
        return out
    }

    /// `words`, topped up from the bank to `count`, drawn at random (a fixed
    /// `seed` for tests), never repeating a word the object has or already got.
    static func fill(_ words: [String], id: String?, name: String, existing: [String], count: Int,
                     taken: [String] = [], seed: UInt64? = nil) -> (words: [String], fromBank: Int) {
        // Never a word another object already has (Gil: remove conflicts,
        // deterministically, and top up from the bank instead).
        let words = words.filter { w in !taken.contains { EggRules.sameWord($0, w) } }
        guard words.count < count else { return (Array(words.prefix(count)), 0) }
        let have = Set((existing + words).map { $0.lowercased() })
        func free(_ w: String) -> Bool { !have.contains(w) && !taken.contains { EggRules.sameWord($0, w) } }
        var names = candidates(id: id, name: name, keywords: existing).filter(free)
        var phrases = adjectivePhrases(id: id, name: name, keywords: existing).filter(free)
        var g = SeededGenerator(state: seed ?? UInt64.random(in: 1...UInt64.max))
        names.shuffle(using: &g)
        phrases.shuffle(using: &g)
        // Mostly other names; about a third adjective phrases ("baby dragon").
        let need = count - words.count
        let phraseShare = min(phrases.count, max(need / 3, names.count < need ? need - names.count : 0))
        let picked = Array(names.prefix(need - phraseShare)) + Array(phrases.prefix(phraseShare))
        var extra = picked
        extra.shuffle(using: &g)
        return (words + extra, extra.count)
    }

    struct SeededGenerator: RandomNumberGenerator {
        var state: UInt64
        mutating func next() -> UInt64 {
            state = state &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
            return state
        }
    }
}
