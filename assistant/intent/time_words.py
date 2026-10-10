"""WORDS THAT NAME A TIME — one table, one function (Gil, 2026-10-01).

*"the now thing could be applied to other words so perhaps make it a function
that applies those changes wherever then we can key in a word and time, so
midnight would be 00:00, sunrise when that is which can be calculated or given
for each day, now is now etc..."*

    word                    the time it names
    now, right now          the present minute          (`now_word`: its vetoes)
    midnight                00:00
    noon, midday            12:00
    at sunrise / sunup      that day's sunrise           at the configured place
    at sunset / sundown     that day's sunset            (`observance`, offline)
    at candle lighting      sunset - the configured minutes
    at nightfall / tzeit    tzeit hakochavim
    YOUR OWN, two kinds     (Settings ▸ How I say things ▸ Words that name a
                            time — the personal lexicon, per user)
      a fixed time          "lunch break = 13:30"
      bound to a key time   "straight away = now", "first light = sunrise",
                            "mincha = sunset-20" — ONE WAY: the word follows
                            its key; the key itself is not editable (Gil:
                            "only for words where the time can be hardcoded
                            so not now or midnight, for those can add words
                            to bind to the key time")

`time_for(text, date)` is the one function every reader calls: FastRule's
time reader, segmentation's tagger (through `find`), and Decompose/Validate's
net. A word that names a time is a CLOCK, so Q26 makes the thing an event.

**A computed or personal word needs "at", "around", "about" or "by" before
it** — except a word bound to now, noon or midnight, which is said the way
its key is ("call mom straight away"). "hike at sunrise" is a time; "watch the sunrise" and "Sunset Boulevard"
are names, and a word read as a time is lifted OUT of the title — "watch the".
`now`, `noon` and `midnight` keep the forms they always had.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from assistant.intent.now_word import NOW_RE, clock as _now_clock
from assistant import clock as _clock  # the moment the command was SAID

#: The lead-in a computed or personal word must have (see the docstring).
_AT = r"\b(?:at|around|about|by)\s+(?:the\s+)?"


@dataclass(frozen=True)
class TimeWord:
    name: str              # what the settings screen shows
    rx: "re.Pattern"       # how it is said
    value: str             # "HH:MM", "now", or a sun time with an offset ("sunset-20")
    yours: bool = False    # added by the person, not shipped


_SUN = ("sunrise", "sunset", "candle lighting", "nightfall")

BUILT_IN = (
    TimeWord("now", NOW_RE, "now"),
    TimeWord("midnight", re.compile(r"\bmidnight\b", re.I), "00:00"),
    TimeWord("noon", re.compile(r"\b(?:12\s*)?(?:noon|midday)\b", re.I), "12:00"),
    TimeWord("sunrise", re.compile(_AT + r"(?:sunrise|sun\s*-?\s*up)\b", re.I), "sunrise"),
    TimeWord("sunset", re.compile(_AT + r"(?:sunset|sun\s*-?\s*down)\b", re.I), "sunset"),
    TimeWord("candle lighting", re.compile(_AT + r"candle[\s-]*lighting\b", re.I), "candle lighting"),
    TimeWord("nightfall", re.compile(_AT + r"(?:nightfall|tzeit|tzeis|tzais)\b", re.I), "nightfall"),
)

#: What the settings screen lists as built in (`lexicon.LEXICONS["time_words"]`).
BUILT_IN_ENTRIES = frozenset({
    "now = the current minute", "midnight = 00:00", "noon = 12:00",
    "at sunrise = that day's sunrise", "at sunset = that day's sunset",
    "at candle lighting = sunset minus your candle-lighting minutes",
    "at nightfall = tzeit hakochavim",
})

#: The KEY TIMES a personal word may bind to. The sun keys take an offset.
KEYS = ("now", "midnight", "noon", "sunrise", "sunset", "candle lighting", "nightfall")
_BARE_KEYS = ("now", "midnight", "noon")      # said without "at", as their key is
_VALUE = re.compile(r"^(?:(\d{1,2}):(\d{2})|(now|midnight|noon)"
                    r"|(sunrise|sunset|candle lighting|nightfall)\s*(?:([+-])\s*(\d{1,3}))?)$")


def parse_entry(entry: str) -> "tuple[str, str] | None":
    """"lunch break = 13:30" -> ("lunch break", "13:30"); "mincha = sunset-20"
    -> ("mincha", "sunset-20"); "straight away = now" -> ("straight away",
    "now"). None when it is not that shape, or when it would REDEFINE a key
    time ("now = 9:00") — the store refuses it rather than keeping a word that
    can never resolve or one that changes what "now" means."""
    word, sep, value = (entry or "").partition("=")
    word = " ".join(word.lower().split())
    value = " ".join(value.lower().split())
    if not sep or not word or not re.search(r"[a-z]", word):
        return None
    if any(w.rx.fullmatch(word) or w.name == word for w in BUILT_IN) or word in KEYS:
        return None                      # a key time is not editable
    m = _VALUE.match(value)
    if not m:
        return None
    if m.group(1) is not None:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return None
        return word, f"{h:02d}:{mi:02d}"
    if m.group(3):
        return word, m.group(3)
    base, sign, n = m.group(4), m.group(5), m.group(6)
    return word, base + (f"{sign}{int(n)}" if sign else "")


def normalize_entry(entry: str) -> "str | None":
    """The stored form of a personal entry, or None to refuse it."""
    p = parse_entry(entry)
    return f"{p[0]} = {p[1]}" if p else None


def _yours() -> "list[TimeWord]":
    try:
        from assistant.intent import lexicon
        entries = lexicon.get_lexicon().added("time_words")
    except Exception:                    # noqa: BLE001 — a store problem never breaks a parse
        return []
    out = []
    for e in entries:
        p = parse_entry(e)
        if p:
            word, value = p
            words = r"\s+".join(map(re.escape, word.split()))
            lead = r"\b" if value in _BARE_KEYS else _AT
            out.append(TimeWord(word, re.compile(lead + words + r"\b", re.I), value, yours=True))
    return out


def words() -> "list[TimeWord]":
    """Every word that names a time: the person's own first, so "at sunset =
    19:00" they keyed in wins over the computed one."""
    return _yours() + list(BUILT_IN)


@dataclass(frozen=True)
class Found:
    word: TimeWord
    start: int
    end: int


def find_all(text: str) -> "list[Found]":
    """Every time word in `text`, left to right, longest first at a place."""
    got: list[Found] = []
    from assistant.intent import now_word as _now_word
    for w in words():
        for m in w.rx.finditer(text or ""):
            if w.rx.pattern == NOW_RE.pattern and _now_word.vetoed(text, m.start()):
                continue                    # "X is due friday now" (now_word)
            got.append(Found(w, m.start(), m.end()))
    got.sort(key=lambda f: (f.start, -(f.end - f.start)))
    out: list[Found] = []
    for f in got:
        if not out or f.start >= out[-1].end:
            out.append(f)
    return out


def find(text: str) -> "Found | None":
    hits = find_all(text)
    return hits[0] if hits else None


def names_a_time(text: str) -> bool:
    return find(text) is not None


def _sun(name: str, date: datetime.date) -> "datetime.time | None":
    from assistant import observance
    try:
        return {"sunrise": observance.sunrise, "sunset": observance.sunset,
                "candle lighting": observance.candle_lighting,
                "nightfall": observance.tzeit}[name](date)
    except Exception:                    # noqa: BLE001 — no place configured: no time
        return None


def resolve(w: TimeWord, date: "datetime.date | None" = None,
            now: "datetime.datetime | None" = None) -> "str | None":
    """The clock `w` names on `date` (today if None), "HH:MM"; None when it
    cannot be computed — no location set — and then nothing is invented."""
    v = w.value
    if v == "now":
        return _now_clock(now)
    v = {"midnight": "00:00", "noon": "12:00"}.get(v, v)
    if re.fullmatch(r"\d{2}:\d{2}", v):
        return v
    m = re.fullmatch(r"(sunrise|sunset|candle lighting|nightfall)(?:([+-])(\d+))?", v)
    if not m:
        return None
    day = date or (now or _clock.now()).date()
    t = _sun(m.group(1), day)
    if t is None:
        return None
    shift = int(m.group(3) or 0) * (-1 if m.group(2) == "-" else 1)
    at = datetime.datetime.combine(day, t) + datetime.timedelta(minutes=shift)
    return at.strftime("%H:%M")


def time_for(text: str, date: "datetime.date | None" = None,
             now: "datetime.datetime | None" = None) -> "str | None":
    """THE function: the clock the first time word in `text` names, or None."""
    f = find(text)
    return resolve(f.word, date, now) if f else None
