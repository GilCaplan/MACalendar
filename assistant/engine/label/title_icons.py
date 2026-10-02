"""Icons beside titles (TASKS 51) — a Component of the Label stage.

When a word in an event's or a to-do's title clearly names something we have a
drawing for, the screens draw that icon beside the title:

    "walk my dog"        -> [dog]
    "date with Noa"      -> [heart]
    "eat a date"         -> []          (the fruit)
    "due date for essay" -> [memo]      (the essay, not the date)

**A word fires only in the sense that has the icon.** Each entry is its
words plus, for a word with two senses, the neighbours that CONFIRM the one
we mean (`needs`) or VETO it (`vetoes`). An ambiguous word with neither is
silent — a wrong icon shows on every screen the row is drawn on, so when the
reading is unsure, nothing happens. No model call: the deterministic reading
is the whole component (CLAUDE.md, deterministic first), and silence is its
answer to doubt.

**The title stays words** (2026-10-01, Gil: *"i dont want emojis, rather
custom made graphics"*). This used to write an emoji INTO the stored title at
commit; now it only answers "which icons does this title get", and the
views draw them — the Mac's from `calendar_ui/icons`, the phone's from the
`icons` field the API serves beside each title. So nothing in the database or
a synced Google calendar carries a picture, switching a kind off takes effect
on every row at once, and a manual or synced event gets its icon too.

The icon names are GraphicsLibrary drawings (`scripts/sync_icons.py`); the
setting is still `title_emoji.count` (0 none, 1, 2), off by default — the key
predates the drawings and every saved config uses it.

Measured before it shipped: `experiments/title_emoji_board.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class Entry:
    group: str
    icon: str
    words: tuple[str, ...]
    #: at least one must match the whole title (lowercased) for it to fire
    needs: tuple[str, ...] = field(default_factory=tuple)
    #: any match and it does not fire
    vetoes: tuple[str, ...] = field(default_factory=tuple)


def E(group: str, icon: str, *words: str, needs=(), vetoes=()) -> Entry:
    return Entry(group, icon, tuple(words), tuple(needs), tuple(vetoes))


#: The kinds a person can switch on or off (Gil, 2026-10-01: "allow user to
#: decide for which categories … to allow emojis"). Key -> what Settings shows,
#: and the icon Settings draws beside it.
GROUPS: dict[str, str] = {
    "animals": "Animals",
    "sport": "Sport & fitness",
    "health": "Health",
    "food": "Food & drink",
    "occasions": "Occasions",
    "travel": "Travel",
    "home": "Home & errands",
    "work": "Work & study",
    "jewish": "Jewish life",
}
GROUP_ICONS: dict[str, str] = {
    "animals": "dog", "sport": "run", "health": "tooth", "food": "coffee", "occasions": "cake",
    "travel": "plane", "home": "broom", "work": "books", "jewish": "candles",
}


#: Ordered: the first entry whose word starts at a position wins that position.
LEXICON: tuple[Entry, ...] = (
    # -- animals ---------------------------------------------------------------
    E("animals", "dog", "dog", "dogs", "puppy", "puppies", "doggy"),
    E("animals", "cat", "cat", "cats", "kitten", "kittens"),
    E("animals", "paw", "vet", vetoes=(r"\bvet (the|this|that|it|them|him|her|my (code|essay|draft|plan))\b",
                           r"\bvetting\b", r"\bveteran")),
    E("animals", "horse", "horse", "horses", "horseback"),
    E("animals", "bird", "bird", "birds", "birdwatching"),
    # -- sport and fitness -----------------------------------------------------
    E("sport", "dumbbell", "gym", "weights", "lifting", "weightlifting"),
    E("sport", "bicep", "workout", "workouts"),
    # Calisthenics and the run kinds of a training plan (2026-10-01: the
    # calendar's own top activities — "calisthenics", "threshold run", "speed
    # run", "strides" — had no emoji).
    E("sport", "bicep", "calisthenics", "pull ups", "pull-ups", "pullups", "push ups", "push-ups", "pushups", "chin ups"),
    E("sport", "run", "run", "running", "jog", "jogging", "marathon", "strides",
      needs=(r"\b(go|going|went|for|a|morning|evening|night|long|easy|short|tempo|recovery|trail|group"
             r"|threshold|speed|interval|fartlek|progression|steady|hill)\s+(run|running|jog)\b",
             r"\bstrides\b",
             r"\b(run|running|jog|jogging)\s+(\d+|a|the)?\s*(k|km|kms|mile|miles|laps?|5k|10k|half|marathon)\b",
             r"\b\d+\s*(k|km|mile|miles)\s+(run|jog)\b",
             r"\bjog(ging)?\b", r"\bmarathon\b", r"^(run|running)$",
             r"\b(run|running) (club|group|session|training)\b"),
      vetoes=(r"\brun (errands?|to|the|a|my|out|over|through|by|into|late|it|this|that|some)\b",
              r"\brun(ning)? (late|low|out|errands?)\b", r"\bdry run\b", r"\bcode run")),
    E("sport", "swim", "swim", "swimming", "pool",
      vetoes=(r"\bcar ?pool", r"\bpool (table|cue|party planning)\b", r"\b(talent|resource|data|thread|gene) pool\b")),
    E("sport", "yoga", "yoga", "pilates", "meditation", "meditate"),
    E("sport", "bike", "bike", "biking", "cycling", "bicycle", "spin class"),
    E("sport", "boot", "hike", "hiking"),
    E("sport", "soccer", "soccer", "football"),
    E("sport", "basketball", "basketball"),
    E("sport", "tennis", "tennis", "padel"),
    E("sport", "ski", "ski", "skiing"),
    E("sport", "mountain", "climbing", "bouldering"),
    E("sport", "boxing", "boxing", "kickboxing"),
    E("sport", "golf", "golf"),
    E("sport", "wave", "surf", "surfing"),
    E("sport", "dance", "dance", "dancing", "salsa"),
    # -- health ----------------------------------------------------------------
    E("health", "tooth", "dentist", "dental", "orthodontist"),
    E("health", "stethoscope", "doctor", "doctors", "doctor's", "checkup", "check-up", "physio", "physiotherapy"),
    E("health", "hospital", "hospital"),
    E("health", "pill", "pharmacy", "pills", "medicine", "meds", "prescription", "vitamins"),
    E("health", "scissors", "haircut", "barber", "hairdresser"),
    E("health", "lotus", "massage", "spa"),
    E("health", "bed", "nap", "sleep"),
    # -- food and drink --------------------------------------------------------
    E("food", "coffee", "coffee", "espresso", "latte", "cappuccino"),
    E("food", "tea", "tea", vetoes=(r"\btea (towel|light)\b", r"\bteam")),
    E("food", "pancakes", "breakfast", "brunch", "pancakes"),
    E("food", "sandwich", "lunch", "sandwich", "sandwiches"),
    E("food", "plate", "dinner", "supper", "restaurant"),
    E("food", "pizza", "pizza"),
    E("food", "burger", "burger", "burgers"),
    E("food", "sushi", "sushi"),
    E("food", "cake", "birthday", "bday", "cake"),
    E("food", "bread", "bread", "challah", "bakery"),
    E("food", "milk", "milk"),
    E("food", "eggs", "eggs"),
    E("food", "cheese", "cheese"),
    E("food", "apple", "apple", "apples",
      vetoes=(r"\bapple (store|watch|id|music|tv|pay|support|account|care|pencil|airpods|genius|card|arcade)\b",)),
    E("food", "banana", "banana", "bananas"),
    E("food", "wine", "wine"),
    E("food", "beer", "beer", "beers", "pub"),
    E("food", "cart", "groceries", "grocery", "supermarket"),
    E("food", "ice_cream", "ice cream"),
    E("food", "chocolate", "chocolate"),
    E("food", "grill", "bbq", "barbecue", "braai"),
    E("food", "cookie", "cookies", "cookie",
      vetoes=(r"\bcookies? (banner|policy|consent|settings)\b", r"\bbrowser cookies?\b")),
    E("food", "basket", "picnic", "laundry"),
    # -- occasions -------------------------------------------------------------
    E("occasions", "celebrate", "party", "parties", "celebration",
      vetoes=(r"\bthird[- ]part(y|ies)\b", r"\bparty (line|member|politics)\b", r"\bpolitical part")),
    E("occasions", "wedding", "wedding", "weddings"),
    E("occasions", "ring", "anniversary", "engagement"),
    E("occasions", "heart", "date",
      needs=(r"\bdate (with|night|nite)\b",
             r"\b(a|first|second|third|dinner|lunch|coffee|movie|hot|blind|double|our|romantic|cute) date\b",
             r"\bdate$"),
      vetoes=(r"\bdue date\b", r"\bsave the date\b", r"\b(the|what|which|this|that|a new|new|exact|start|end|"
              r"release|expiry|expiration|deadline|court|target|delivery|closing|launch|submission|cut[- ]off|"
              r"move the|change the|set the|pick a|choose a|another|same) date\b",
              r"\bdates?\b.*\b(fruit|eat|buy|figs|nuts)\b", r"\b(eat|buy|get|bake|pitted|dried|medjool) (some |a |the )?dates?\b",
              r"\bdate (of|for|to|on|by|range|picker|format|stamp)\b", r"\bup ?to ?date\b", r"\bout of date\b",
              # a date ON the calendar, not a date WITH someone (board 2026-10-01: "the interview date")
              r"\b(interview|appointment|meeting|exam|test|court|wedding|birth|trip|travel|event|party|"
              r"payment|shipping|filing|hearing|surgery|flight|class|school|move|moving|closing) date\b")),
    E("occasions", "music", "concert", "music", "gig", "choir", "orchestra"),
    E("occasions", "movie", "movie", "movies", "cinema", "film",
      vetoes=(r"\b(cling|plastic|food|window|protective) film\b",)),
    E("occasions", "masks", "theater", "theatre", "musical", "play rehearsal", "purim"),
    E("occasions", "frame", "museum"),
    E("occasions", "gift", "gift", "gifts", "presents"),
    E("occasions", "tree", "christmas", "xmas"),
    E("occasions", "pumpkin", "halloween"),
    E("occasions", "dice", "game night", "board games", "board game"),
    E("occasions", "chess", "chess"),
    # -- travel ----------------------------------------------------------------
    E("travel", "plane", "flight", "flights", "airport", "plane"),
    E("travel", "train", "train",
      needs=(r"\b(the|a|catch|take|taking|by|on|night|early|late|last|first) train\b",
             r"\btrain (to|from|ride|station|ticket|tickets|home)\b"),
      vetoes=(r"\btrain(ing)? (for|the model|my|with|legs|arms|chest|back|core|hard|together)\b",
              r"\b(personal|strength|interval|weight) train",)),
    E("travel", "bus", "bus"),
    E("travel", "car", "car", "cars", "drive", "driving",
      vetoes=(r"\bcar ?pool", r"\b(hard|thumb|usb|flash|test) drive\b", r"\bdrive(n)? (to succeed|the project|sales|the meeting|growth)\b",
              r"\bgoogle drive\b")),
    E("travel", "taxi", "taxi", "uber", "cab"),
    E("travel", "hotel", "hotel", "airbnb"),
    E("travel", "beach", "beach", "vacation"),
    E("travel", "suitcase", "packing", "suitcase", "trip",
      vetoes=(r"\b(shopping|grocery|store|supermarket|costco|errand|walmart|target|mall) trip\b", r"\btrip (over|up)\b")),
    E("travel", "fuel", "gas station", "petrol", "fuel", "refuel"),
    # -- home and errands ------------------------------------------------------
    E("home", "shirt", "dry cleaning", "dry cleaner", "dry cleaners", "suit"),
    E("home", "broom", "clean", "cleaning", "vacuum", "mop", "tidy",
      vetoes=(r"\bclean (code|up the (code|data|repo|branch|pr))\b", r"\bclean (data|slate|energy)\b",
              r"\bclean and jerk\b", r"\bclean (up |out )?(my |the )?(calendar|schedule|inbox|list|shopping list)\b",
              r"\b(calendar|schedule|slate) clean\b")),
    E("home", "trash", "trash", "garbage", "recycling", "bins"),
    E("home", "plant", "plants", "water the plants", "houseplants"),
    E("home", "seedling", "garden", "gardening"),
    E("home", "flowers", "flowers", "bouquet"),
    E("home", "package", "package", "parcel", "delivery", "amazon return",
      vetoes=(r"\b(software|python|npm|pip|r) package\b", r"\bpackage (manager|update|version)\b",
              r"\bdelivery date\b", r"\b(speech|content|training|course|service|project|lecture) delivery\b")),
    E("home", "mailbox", "post office", "stamps"),
    E("home", "institution", "bank",
      vetoes=(r"\b(bottle|food|blood|river|power|memory|sperm|question|piggy|west) bank\b", r"\bbank holiday")),
    E("home", "money", "rent", "bills", "taxes", "invoice",
      vetoes=(r"\brent (a|the) (car|movie|bike|apartment)\b", r"\bpay the (attention|price)\b")),
    E("home", "key", "keys", "locksmith"),
    E("home", "stroller", "baby", "babysitter", "babysitting"),
    # -- work and study --------------------------------------------------------
    E("work", "handset", "call", "phone call",
      vetoes=(r"\bcall (it|off|out|back later)\b", r"\bso[- ]called\b", r"\b(roll|judgment|judgement|close|wake[- ]?up|curtain|api|function|method) call\b",
              r"\bcall (stack|graph|site|center|centre)\b")),
    E("work", "envelope", "email", "emails", "e-mail", "inbox"),
    E("work", "memo", "exam", "exams", "homework", "assignment", "quiz", "essay",
      vetoes=(r"\bhomework club\b", r"\b(eye|medical|physical|hearing|vision|driving|blood) (exam|test)s?\b")),
    E("work", "books", "study", "studying", "library", "book", "books", "reading", "book club",
      needs=(r"\b(study|studying|library|reading|book club|books)\b",
             r"\b(read|reading|a|the|my|new|finish|return|borrow|library|this|that|his|her|their) book\b"),
      vetoes=(r"^book\b(?! club)", r"\bbook (a|an|the|tickets?|flights?|tables?|appointments?|rooms?|hotels?|it|that|this|"
              r"slots?|seats?|venue|meeting|session|call|time|me|us|him|her|them|in|for)\b",
              r"\b(to|please|and|then|also|can you|could you|i need to|need to|gotta|must) book\b",
              r"\bcase study\b", r"\bstudy (room|group) booking\b", r"\b(meter|gas|electric|water|thermometer|blood pressure) reading\b", r"\breading (the|my) (email|emails|messages|notes)\b")),
    E("work", "graduation", "lecture", "graduation", "seminar", "tutorial", "office hours"),
    E("work", "laptop", "coding", "code review", "laptop", "hackathon"),
    E("work", "chart_bars", "presentation", "slides"),
    E("work", "briefcase", "interview", "interviews"),
    E("work", "camera", "photo", "photos", "photoshoot", "camera"),
    E("work", "piano_keys", "piano"),
    E("work", "guitar", "guitar"),
    E("work", "drum", "drums"),
    E("work", "palette", "painting", "art class", "drawing class"),
    E("work", "yarn", "knitting", "crochet"),
    # -- Jewish life (the user's own calendar) --------------------------------
    E("jewish", "synagogue", "shul", "synagogue"),
    E("jewish", "pray", "davening", "daven", "minyan", "mincha", "maariv", "shacharit", "shacharis", "prayers"),
    E("jewish", "candles", "shabbat", "shabbos", "havdalah", "candle lighting", "candles"),
    E("jewish", "scroll", "shiur", "torah", "gemara", "daf yomi", "chavruta", "chavrusa", "mishna", "mishnah", "parsha", "parasha"),
    E("jewish", "menorah", "chanukah", "hanukkah", "menorah"),
    E("jewish", "matzah", "pesach", "passover", "matzah", "matza", "seder"),
    E("jewish", "sukkah", "sukkah", "sukkot", "lulav"),
)

# Emoji a title might carry from before the drawings (or typed by hand):
# pictographs, symbols, flags, keycaps.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿\U0001F1E6-\U0001F1FF⌀-⏿]")


def has_emoji(title: str) -> bool:
    return bool(_EMOJI.search(title or ""))


_JOINERS = re.compile("[\ufe0f\u200d\u20e3]")


def strip(title: str) -> str:
    """The title's WORDS: emoji (and their joiners) out, spacing tidied. What a
    duplicate check, a classifier or a title drawn beside its icon uses, so a
    row saved as "walk my dog 🐕" before the drawings is "walk my dog"."""
    return re.sub(r"\s+", " ", _JOINERS.sub("", _EMOJI.sub("", title or ""))).strip()


def _compiled():
    out = []
    for e in LEXICON:
        alts = sorted(e.words, key=len, reverse=True)
        word = re.compile(r"(?<![\w'])(" + "|".join(re.escape(w) for w in alts) + r")(?![\w'])", re.IGNORECASE)
        out.append((e, word, [re.compile(n, re.IGNORECASE) for n in e.needs],
                    [re.compile(v, re.IGNORECASE) for v in e.vetoes]))
    return out


_LEX = _compiled()


def matches(title: str, groups: "set[str] | None" = None) -> list[tuple[int, str, str]]:
    """Every (end offset, icon, word) whose sense the title confirms, in the
    order the words appear, one per icon — from the `groups` switched on
    (None: all of them)."""
    text = strip(title)
    low = text.lower()
    found: dict[str, tuple[int, int, str]] = {}            # icon -> (start, end, word)
    taken: list[tuple[int, int]] = []
    for e, word, needs, vetoes in _LEX:
        if groups is not None and e.group not in groups:
            continue
        if any(v.search(low) for v in vetoes):
            continue
        if needs and not any(n.search(low) for n in needs):
            continue
        for m in word.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue                                    # inside a longer word already matched
            if e.icon not in found or m.start() < found[e.icon][0]:
                found[e.icon] = (m.start(), m.end(), m.group(1))
            taken.append((m.start(), m.end()))
            break
    ordered = sorted(found.items(), key=lambda kv: kv[1][0])
    return [(end, icon, w) for icon, (_s, end, w) in ordered]


@lru_cache(maxsize=4096)
def _icons(title: str, count: int, groups: "frozenset[str] | None") -> tuple[str, ...]:
    return tuple(icon for _e, icon, _w in matches(title, None if groups is None else set(groups))[:count])


def icons(title: str, count: int, groups: "set[str] | None" = None) -> list[str]:
    """Up to `count` icon names for `title`, in the order their words appear —
    none when `count` is 0 or nothing is clear. Cached: every screen asks
    again for every row on every redraw."""
    if count <= 0 or not title:
        return []
    return list(_icons(title, count, None if groups is None else frozenset(groups)))


def for_config(title: str, config) -> list[str]:
    """`icons(title)` as the user's `title_emoji` settings ask."""
    return icons(title, count_from(config), groups_from(config))


def groups_from(config) -> "set[str]":
    """The kinds switched on in `title_emoji` (each a bool, on unless set off)."""
    section = getattr(config, "title_emoji", None)
    return {g for g in GROUPS if bool(getattr(section, g, True))}


def count_from(config) -> int:
    """`title_emoji.count` from config, 0 when absent or out of range."""
    section = getattr(config, "title_emoji", None)
    try:
        n = int(getattr(section, "count", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return n if n in (0, 1, 2) else 0


def attach(rows: "list[dict]", config=None) -> "list[dict]":
    """Give each event / to-do payload its `icons` — the serialization hook the
    API runs rows through, so the phone draws what the Mac draws without a
    copy of the lexicon. A row keeps its title untouched."""
    if config is None:
        from assistant.config import load_config
        config = load_config()
    count, groups = count_from(config), groups_from(config)
    for r in rows:
        if isinstance(r, dict):
            r["icons"] = icons(r.get("title") or "", count, groups)
    return rows
