"""Emoji in titles (TASKS 51) — a Component of the Label stage.

When the assistant COMMITS an event or a to-do and a word in its title clearly
names something with an emoji, the emoji goes right after that word:

    "walk my dog"        -> "walk my dog 🐕"
    "date with Noa"      -> "date 💕 with Noa"
    "eat a date"         -> unchanged (the fruit)
    "due date for essay" -> unchanged

**A word fires only in the sense that has the emoji.** Each entry is its
words plus, for a word with two senses, the neighbours that CONFIRM the one
we mean (`needs`) or VETO it (`vetoes`). An ambiguous word with neither is
silent — a wrong emoji shows on every screen the row is drawn on, so when the
reading is unsure, nothing happens. No model call: the deterministic reading
is the whole component (CLAUDE.md, deterministic first), and silence is its
answer to doubt.

Where it runs: the create actions, after the row's tags/category are chosen
from the PLAIN title, before the write. Only what the assistant creates — not
calendar sync, which would rewrite the user's Google titles. The setting is
`title_emoji.count` (0 none, 1, 2), off by default. Title matching tokenises
on `\\w+`, which an emoji is not, so "delete walk my dog" still finds it.

Measured before it shipped: `experiments/title_emoji_board.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entry:
    emoji: str
    words: tuple[str, ...]
    #: at least one must match the whole title (lowercased) for it to fire
    needs: tuple[str, ...] = field(default_factory=tuple)
    #: any match and it does not fire
    vetoes: tuple[str, ...] = field(default_factory=tuple)


def E(emoji: str, *words: str, needs=(), vetoes=()) -> Entry:
    return Entry(emoji, tuple(words), tuple(needs), tuple(vetoes))


#: Ordered: the first entry whose word starts at a position wins that position.
LEXICON: tuple[Entry, ...] = (
    # -- animals ---------------------------------------------------------------
    E("🐕", "dog", "dogs", "puppy", "puppies", "doggy"),
    E("🐈", "cat", "cats", "kitten", "kittens"),
    E("🐾", "vet", vetoes=(r"\bvet (the|this|that|it|them|him|her|my (code|essay|draft|plan))\b",
                           r"\bvetting\b", r"\bveteran")),
    E("🐴", "horse", "horses", "horseback"),
    E("🐦", "bird", "birds", "birdwatching"),
    # -- sport and fitness -----------------------------------------------------
    E("🏋️", "gym", "weights", "lifting", "weightlifting"),
    E("💪", "workout", "workouts"),
    E("🏃", "run", "running", "jog", "jogging", "marathon",
      needs=(r"\b(go|going|went|for|a|morning|evening|night|long|easy|short|tempo|recovery|trail|group)\s+(run|running|jog)\b",
             r"\b(run|running|jog|jogging)\s+(\d+|a|the)?\s*(k|km|kms|mile|miles|laps?|5k|10k|half|marathon)\b",
             r"\b\d+\s*(k|km|mile|miles)\s+(run|jog)\b",
             r"\bjog(ging)?\b", r"\bmarathon\b", r"^(run|running)$",
             r"\b(run|running) (club|group|session|training)\b"),
      vetoes=(r"\brun (errands?|to|the|a|my|out|over|through|by|into|late|it|this|that|some)\b",
              r"\brun(ning)? (late|low|out|errands?)\b", r"\bdry run\b", r"\bcode run")),
    E("🏊", "swim", "swimming", "pool",
      vetoes=(r"\bcar ?pool", r"\bpool (table|cue|party planning)\b", r"\b(talent|resource|data|thread|gene) pool\b")),
    E("🧘", "yoga", "pilates", "meditation", "meditate"),
    E("🚴", "bike", "biking", "cycling", "bicycle", "spin class"),
    E("🥾", "hike", "hiking"),
    E("⚽", "soccer", "football"),
    E("🏀", "basketball"),
    E("🎾", "tennis", "padel"),
    E("⛷️", "ski", "skiing"),
    E("🧗", "climbing", "bouldering"),
    E("🥊", "boxing", "kickboxing"),
    E("⛳", "golf"),
    E("🏄", "surf", "surfing"),
    E("💃", "dance", "dancing", "salsa"),
    # -- health ----------------------------------------------------------------
    E("🦷", "dentist", "dental", "orthodontist"),
    E("🩺", "doctor", "doctors", "doctor's", "checkup", "check-up", "physio", "physiotherapy"),
    E("🏥", "hospital"),
    E("💊", "pharmacy", "pills", "medicine", "meds", "prescription", "vitamins"),
    E("💇", "haircut", "barber", "hairdresser"),
    E("💆", "massage", "spa"),
    E("😴", "nap", "sleep"),
    # -- food and drink --------------------------------------------------------
    E("☕", "coffee", "espresso", "latte", "cappuccino"),
    E("🍵", "tea", vetoes=(r"\btea (towel|light)\b", r"\bteam")),
    E("🥞", "breakfast", "brunch", "pancakes"),
    E("🥪", "lunch", "sandwich", "sandwiches"),
    E("🍽️", "dinner", "supper", "restaurant"),
    E("🍕", "pizza"),
    E("🍔", "burger", "burgers"),
    E("🍣", "sushi"),
    E("🎂", "birthday", "bday", "cake"),
    E("🍞", "bread", "challah", "bakery"),
    E("🥛", "milk"),
    E("🥚", "eggs"),
    E("🧀", "cheese"),
    E("🍎", "apple", "apples",
      vetoes=(r"\bapple (store|watch|id|music|tv|pay|support|account|care|pencil|airpods|genius|card|arcade)\b",)),
    E("🍌", "banana", "bananas"),
    E("🍷", "wine"),
    E("🍺", "beer", "beers", "pub"),
    E("🛒", "groceries", "grocery", "supermarket"),
    E("🍦", "ice cream"),
    E("🍫", "chocolate"),
    E("🍖", "bbq", "barbecue", "braai"),
    E("🍪", "cookies", "cookie",
      vetoes=(r"\bcookies? (banner|policy|consent|settings)\b", r"\bbrowser cookies?\b")),
    E("🧺", "picnic", "laundry"),
    # -- occasions -------------------------------------------------------------
    E("🎉", "party", "parties", "celebration",
      vetoes=(r"\bthird[- ]part(y|ies)\b", r"\bparty (line|member|politics)\b", r"\bpolitical part")),
    E("💒", "wedding", "weddings"),
    E("💍", "anniversary", "engagement"),
    E("💕", "date",
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
    E("🎵", "concert", "music", "gig", "choir", "orchestra"),
    E("🎬", "movie", "movies", "cinema", "film",
      vetoes=(r"\b(cling|plastic|food|window|protective) film\b",)),
    E("🎭", "theater", "theatre", "musical", "play rehearsal", "purim"),
    E("🏛️", "museum"),
    E("🎁", "gift", "gifts", "presents"),
    E("🎄", "christmas", "xmas"),
    E("🎃", "halloween"),
    E("🎲", "game night", "board games", "board game"),
    E("♟️", "chess"),
    # -- travel ----------------------------------------------------------------
    E("✈️", "flight", "flights", "airport", "plane"),
    E("🚆", "train",
      needs=(r"\b(the|a|catch|take|taking|by|on|night|early|late|last|first) train\b",
             r"\btrain (to|from|ride|station|ticket|tickets|home)\b"),
      vetoes=(r"\btrain(ing)? (for|the model|my|with|legs|arms|chest|back|core|hard|together)\b",
              r"\b(personal|strength|interval|weight) train",)),
    E("🚌", "bus"),
    E("🚗", "car", "cars", "drive", "driving",
      vetoes=(r"\bcar ?pool", r"\b(hard|thumb|usb|flash|test) drive\b", r"\bdrive(n)? (to succeed|the project|sales|the meeting|growth)\b",
              r"\bgoogle drive\b")),
    E("🚕", "taxi", "uber", "cab"),
    E("🏨", "hotel", "airbnb"),
    E("🏖️", "beach", "vacation"),
    E("🧳", "packing", "suitcase", "trip",
      vetoes=(r"\b(shopping|grocery|store|supermarket|costco|errand|walmart|target|mall) trip\b", r"\btrip (over|up)\b")),
    E("⛽", "gas station", "petrol", "fuel", "refuel"),
    # -- home and errands ------------------------------------------------------
    E("👔", "dry cleaning", "dry cleaner", "dry cleaners", "suit"),
    E("🧹", "clean", "cleaning", "vacuum", "mop", "tidy",
      vetoes=(r"\bclean (code|up the (code|data|repo|branch|pr))\b", r"\bclean (data|slate|energy)\b",
              r"\bclean and jerk\b", r"\bclean (up |out )?(my |the )?(calendar|schedule|inbox|list|shopping list)\b",
              r"\b(calendar|schedule|slate) clean\b")),
    E("🗑️", "trash", "garbage", "recycling", "bins"),
    E("🪴", "plants", "water the plants", "houseplants"),
    E("🌱", "garden", "gardening"),
    E("💐", "flowers", "bouquet"),
    E("📦", "package", "parcel", "delivery", "amazon return",
      vetoes=(r"\b(software|python|npm|pip|r) package\b", r"\bpackage (manager|update|version)\b",
              r"\bdelivery date\b", r"\b(speech|content|training|course|service|project|lecture) delivery\b")),
    E("📮", "post office", "stamps"),
    E("🏦", "bank",
      vetoes=(r"\b(bottle|food|blood|river|power|memory|sperm|question|piggy|west) bank\b", r"\bbank holiday")),
    E("💸", "rent", "bills", "taxes", "invoice",
      vetoes=(r"\brent (a|the) (car|movie|bike|apartment)\b", r"\bpay the (attention|price)\b")),
    E("🔑", "keys", "locksmith"),
    E("👶", "baby", "babysitter", "babysitting"),
    # -- work and study --------------------------------------------------------
    E("📞", "call", "phone call",
      vetoes=(r"\bcall (it|off|out|back later)\b", r"\bso[- ]called\b", r"\b(roll|judgment|judgement|close|wake[- ]?up|curtain|api|function|method) call\b",
              r"\bcall (stack|graph|site|center|centre)\b")),
    E("📧", "email", "emails", "e-mail", "inbox"),
    E("📝", "exam", "exams", "homework", "assignment", "quiz", "essay",
      vetoes=(r"\bhomework club\b", r"\b(eye|medical|physical|hearing|vision|driving|blood) (exam|test)s?\b")),
    E("📚", "study", "studying", "library", "book", "books", "reading", "book club",
      needs=(r"\b(study|studying|library|reading|book club|books)\b",
             r"\b(read|reading|a|the|my|new|finish|return|borrow|library|this|that|his|her|their) book\b"),
      vetoes=(r"^book\b(?! club)", r"\bbook (a|an|the|tickets?|flights?|tables?|appointments?|rooms?|hotels?|it|that|this|"
              r"slots?|seats?|venue|meeting|session|call|time|me|us|him|her|them|in|for)\b",
              r"\b(to|please|and|then|also|can you|could you|i need to|need to|gotta|must) book\b",
              r"\bcase study\b", r"\bstudy (room|group) booking\b", r"\b(meter|gas|electric|water|thermometer|blood pressure) reading\b", r"\breading (the|my) (email|emails|messages|notes)\b")),
    E("🎓", "lecture", "graduation", "seminar", "tutorial", "office hours"),
    E("💻", "coding", "code review", "laptop", "hackathon"),
    E("📊", "presentation", "slides"),
    E("💼", "interview", "interviews"),
    E("📷", "photo", "photos", "photoshoot", "camera"),
    E("🎹", "piano"),
    E("🎸", "guitar"),
    E("🥁", "drums"),
    E("🎨", "painting", "art class", "drawing class"),
    E("🧶", "knitting", "crochet"),
    # -- Jewish life (the user's own calendar) --------------------------------
    E("🕍", "shul", "synagogue"),
    E("🙏", "davening", "daven", "minyan", "mincha", "maariv", "shacharit", "shacharis", "prayers"),
    E("🕯️", "shabbat", "shabbos", "havdalah", "candle lighting", "candles"),
    E("📜", "shiur", "torah", "gemara", "daf yomi", "chavruta", "chavrusa", "mishna", "mishnah", "parsha", "parasha"),
    E("🕎", "chanukah", "hanukkah", "menorah"),
    E("🫓", "pesach", "passover", "matzah", "matza", "seder"),
    E("🌿", "sukkah", "sukkot", "lulav"),
)

# Everything a title might already carry: pictographs, symbols, flags, keycaps.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿\U0001F1E6-\U0001F1FF⌀-⏿]")


def has_emoji(title: str) -> bool:
    return bool(_EMOJI.search(title or ""))


_JOINERS = re.compile("[\ufe0f\u200d\u20e3]")


def strip(title: str) -> str:
    """The title's WORDS: emoji (and their joiners) out, spacing tidied. What a
    duplicate check or a classifier compares, so "walk my dog 🐕" is still
    "walk my dog"."""
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


def matches(title: str) -> list[tuple[int, str, str]]:
    """Every (end offset, emoji, word) whose sense the title confirms, in the
    order the words appear, one per emoji."""
    text = title or ""
    low = text.lower().strip()
    found: dict[str, tuple[int, int, str]] = {}            # emoji -> (start, end, word)
    taken: list[tuple[int, int]] = []
    for e, word, needs, vetoes in _LEX:
        if any(v.search(low) for v in vetoes):
            continue
        if needs and not any(n.search(low) for n in needs):
            continue
        for m in word.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue                                    # inside a longer word already matched
            if e.emoji not in found or m.start() < found[e.emoji][0]:
                found[e.emoji] = (m.start(), m.end(), m.group(1))
            taken.append((m.start(), m.end()))
            break
    ordered = sorted(found.items(), key=lambda kv: kv[1][0])
    return [(end, emoji, w) for emoji, (_s, end, w) in ordered]


def decorate(title: str, count: int) -> str:
    """The title with up to `count` emoji, each right after its word — or the
    title unchanged (count 0, nothing clear, or one already there)."""
    if count <= 0 or not title or has_emoji(title):
        return title
    picks = matches(title)[:count]
    out = title
    for end, emoji, _w in sorted(picks, reverse=True):     # right to left keeps offsets valid
        out = out[:end] + " " + emoji + out[end:]
    return out


def count_from(config) -> int:
    """`title_emoji.count` from config, 0 when absent or out of range."""
    section = getattr(config, "title_emoji", None)
    try:
        n = int(getattr(section, "count", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return n if n in (0, 1, 2) else 0
