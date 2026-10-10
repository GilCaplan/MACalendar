"""Days people NAME instead of dating: Hebrew dates, holidays, their own occasions.

Gil, 2026-09-29: *"The engine can deal with given hebrew dates and other built
in events?"* — it could not. Probed on eight commands the same day, five were
booked on the WRONG DAY without a word: the date recogniser read "12 Adar" as
the 12th of THIS month, and a holiday name it did not know ("on erev Pesach",
"the day after Yom Kippur", "the first night of Chanukah") fell through to the
default of today or tomorrow, with the holiday left in the title. Two more went
to the model, which put Rosh Chodesh Kislev six weeks early.

    "dentist on 12 Adar at 3pm"                 12 Adar (Adar II in a leap year)
    "dinner on erev Pesach at 7pm"              the day before Pesach
    "meeting the day after Yom Kippur"          11 Tishrei
    "call mom on the first night of Chanukah"   the evening of 24 Kislev
    "shiur on Rosh Chodesh Kislev"              its first day
    "party on Purim" · "brunch on Easter" · "lunch on Eid al-Fitr"
    "dinner on Dana's birthday"                 from the person's own occasions
    "every monday until Pesach"                 a series bound

``find(text, today)`` returns the one named day in ``text`` as a ``Named`` —
its character spans, the date, and how many days the named thing LASTS — or
None. A holiday that lasts more than one day ("on Pesach", "over Sukkot") is a
RANGE: the date is its first day, and the caller offers it for confirmation
exactly as it already does for "next week".

NARROW IN FREE TEXT, because a holiday is also a NAME. Real speech says "cook
food FOR Shabbat at 3pm today", "add pastries to the Christmas list", "delete
the Christmas party", "three weeks before Thanksgiving" — none of which dates
anything by the holiday. So in free text a name counts only after "on", "over",
"during", "this", "next", "until", "till" or "through", and only when what
follows it is not another noun ("on the Purim party" is not a date); the forms
that are dates by construction — "erev X", "motzei X", "the day before/after X",
"the first night of X" — need no lead. ``whole=True`` is for a resolver's time
words (decompose_validate's ``resolve_date``): there the START of the string
counts as a lead too ("rosh chodesh kislev at 8pm"), and nothing more — the
fast track hands that resolver the WHOLE sentence when an item has no time
words of its own, and "cook food for Shabbat at 3pm today" read as Saturday
when this mode skipped the guards (2026-09-29).

The holidays come from ``hebrew_calendar.enumerate_holidays`` (the table the
calendar draws, with postponed fasts and the Israeli modern days) and
``occasions.calendars`` (Christian, Islamic, Rosh Chodesh) — this module keeps
the SPELLINGS people say, never a second copy of when anything falls.
Everything is offline.
"""

from __future__ import annotations

import dataclasses
import datetime
import functools
import re
from assistant import clock as _clock  # the moment the command was SAID

#: Hebrew months -> pyluach numbers (Nisan = 1 ... Adar = 12, Adar II = 13).
#: Shared with ``occasions.voice``, which reads the same words for occasions.
HEBREW_MONTHS = {
    "nisan": 1, "nissan": 1, "iyar": 2, "iyyar": 2, "sivan": 3, "tammuz": 4, "tamuz": 4,
    "av": 5, "menachem av": 5, "elul": 6, "tishrei": 7, "tishri": 7, "cheshvan": 8,
    "heshvan": 8, "marcheshvan": 8, "kislev": 9, "tevet": 10, "teves": 10, "shevat": 11,
    "shvat": 11, "adar": 12, "adar i": 12, "adar 1": 12, "adar aleph": 12,
    "adar rishon": 12, "adar ii": 13, "adar 2": 13, "adar bet": 13, "adar beis": 13,
    "adar sheni": 13,
}

#: What pyluach calls each month (``month_name()``), for Rosh Chodesh banners.
_PYLUACH_MONTH = {"nissan": 1, "iyar": 2, "sivan": 3, "tammuz": 4, "av": 5, "elul": 6,
                  "tishrei": 7, "cheshvan": 8, "kislev": 9, "teves": 10, "shevat": 11,
                  "adar": 12, "adar 1": 12, "adar 2": 13}

#: Spoken spellings -> the key ``_holiday`` resolves. Spaces in a spelling
#: match any run of spaces, apostrophes or hyphens ("lag b'omer", "tu-bishvat").
_SPELLINGS: dict[str, tuple[str, ...]] = {
    "Rosh Hashana": ("rosh hashana", "rosh hashanah", "rosh hashono", "rosh ha shana",
                     "rosh ha shanah"),
    "Tzom Gedalia": ("tzom gedalia", "tzom gedaliah", "fast of gedalia", "fast of gedaliah"),
    "Yom Kippur": ("yom kippur", "yom kipur", "yom kippor"),
    "Succos": ("sukkot", "succot", "sukkos", "succos", "sukkoth", "sukot"),
    "Hoshana Rabba": ("hoshana rabba", "hoshana raba", "hoshana rabbah", "hoshanah rabbah"),
    "Shmini Atzeres": ("shemini atzeret", "shmini atzeret", "shemini atzeres", "shmini atzeres"),
    "Simchas Torah": ("simchat torah", "simchas torah", "simhat torah"),
    "Chanuka": ("chanukah", "chanuka", "hanukkah", "hanukah", "chanukkah", "hannukah",
                "hanuka", "channukah"),
    "10 of Teves": ("asara b tevet", "asarah b tevet", "fast of tevet", "tenth of tevet"),
    "Tu B'shvat": ("tu bishvat", "tu b shvat", "tu beshvat", "tu bshvat"),
    "Taanis Esther": ("taanit esther", "taanis esther", "ta anit esther", "fast of esther"),
    "Purim": ("purim",),
    "Shushan Purim": ("shushan purim",),
    "Pesach": ("pesach", "passover", "pesah"),
    "Pesach Sheni": ("pesach sheni",),
    "Lag Ba'omer": ("lag baomer", "lag b omer", "lag laomer", "lag bomer"),
    "Shavuos": ("shavuot", "shavuos", "shavuoth", "shavuous"),
    "17 of Tamuz": ("shiva asar b tammuz", "shiva asar b tamuz", "fast of tammuz",
                    "seventeenth of tammuz"),
    "9 of Av": ("tisha b av", "tisha bav", "tisha beav", "tishah b av", "tisha b ab"),
    "Tu B'av": ("tu b av", "tu bav", "tu beav"),
    "Yom HaShoah": ("yom hashoah", "yom ha shoah", "holocaust remembrance day"),
    "Yom HaZikaron": ("yom hazikaron", "yom ha zikaron", "yom hazikkaron"),
    "Yom Ha'atzmaut": ("yom haatzmaut", "yom ha atzmaut", "yom hatzmaut",
                       "israel independence day", "israeli independence day"),
    "Yom Yerushalayim": ("yom yerushalayim", "jerusalem day"),
    "Sigd": ("sigd",),
    "Seder": ("seder night", "the seder", "first seder"),
    "Second seder": ("second seder",),
    "Kol Nidre": ("kol nidre", "kol nidrei"),
    "Chol Hamoed Succos": ("chol hamoed sukkot", "chol hamoed succot", "chol hamoed sukkos",
                           "chol hamoed succos", "hol hamoed sukkot"),
    "Chol Hamoed Pesach": ("chol hamoed pesach", "chol hamoed passover", "hol hamoed pesach"),
    "Rosh Chodesh": ("rosh chodesh", "rosh hodesh"),
    "Shabbat": ("shabbat", "shabbos", "shabat", "sabbath"),
    # Christian (occasions.calendars.christian)
    "Easter Sunday": ("easter", "easter sunday"),
    "Good Friday": ("good friday",),
    "Palm Sunday": ("palm sunday",),
    "Ash Wednesday": ("ash wednesday",),
    "Pentecost": ("pentecost",),
    "Ascension Day": ("ascension day",),
    "Epiphany": ("epiphany",),
    # Islamic (occasions.calendars.islamic) — "(expected)": sighting decides
    "Eid al-Fitr": ("eid al fitr", "eid ul fitr", "eid el fitr"),
    "Eid al-Adha": ("eid al adha", "eid ul adha", "eid el adha"),
    "Ramadan begins": ("ramadan",),
    "Ashura": ("ashura",),
    "Islamic New Year": ("islamic new year", "hijri new year"),
    "Laylat al-Qadr": ("laylat al qadr",),
    "Day of Arafah": ("day of arafah", "day of arafat"),
}

_CHRISTIAN = {"Easter Sunday", "Good Friday", "Palm Sunday", "Ash Wednesday", "Pentecost",
              "Ascension Day", "Epiphany"}
_ISLAMIC = {"Eid al-Fitr", "Eid al-Adha", "Ramadan begins", "Ashura", "Islamic New Year",
            "Laylat al-Qadr", "Day of Arafah"}

#: The switch each name answers to (Settings ▸ Occasions, ``occasions.by_name``).
FAMILIES = ("jewish", "christian", "islamic", "mine")


def _family(key: str) -> str:
    return "christian" if key in _CHRISTIAN else "islamic" if key in _ISLAMIC else "jewish"


_SEP = r"[\s'’\-]*"


def _alt(words) -> str:
    """One alternation, longest first, with flexible separators."""
    parts = sorted(set(words), key=len, reverse=True)
    return "|".join(_SEP.join(re.escape(w) for w in p.split()) for p in parts)


_KEY_OF: dict[str, str] = {}
for _key, _words in _SPELLINGS.items():
    for _w in _words:
        _KEY_OF[re.sub(r"[\s'’\-]+", " ", _w)] = _key

_HOLIDAY = _alt(sum(_SPELLINGS.values(), ()))
_JEWISH = _alt(sum((w for k, w in _SPELLINGS.items()
                    if k not in _CHRISTIAN and k not in _ISLAMIC), ()))
_MONTH = _alt(HEBREW_MONTHS)
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
             "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6,
             "seventh": 7, "7th": 7, "eighth": 8, "8th": 8, "last": -1}
_ORD = "|".join(_ORDINALS)

#: In free text a holiday name dates something only after one of these.
_LEAD = r"\b(?:on|over|during|this|next|until|till|through|thru)\s+(?:the\s+)?"
#: ... and only when the word after it does not make it a NAME ("the Purim
#: party", "the Christmas list"): the next word is one of these, or nothing.
_FOLLOW = frozenset("""at from in with to for and or then but so around about between
until till through thru morning afternoon evening night day eve please too also as by
this next i we remind starting before after each every all it is will me us my our
""".split())
_YEAR = r"(?:,?\s+(20\d\d|5\d\d\d)\b)?"

_HEB_DATE = re.compile(
    rf"\b(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\b{_YEAR}"
    rf"|\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*(?::|\.\d|am\b|pm\b|a\.m|p\.m|"
    rf"o'?clock|min|minutes|hours?|hrs?|people|times|x\b)){_YEAR}", re.I)
#: A Hebrew month after these is a PERSON (Sivan, Elul and Adar are names).
_PERSON_LEAD = re.compile(r"\b(with|call|text|tell|ask|meet|email|see|visit|and|to)\s+$", re.I)
_RC = re.compile(rf"\b(?:rosh{_SEP}c?hodesh)(?:\s+({_MONTH}))?\b", re.I)
_EXPLICIT = re.compile(
    rf"\b(?P<rel>erev|motzei|motzai|motzash|the\s+(?:day|night|evening)\s+(?:before|after)"
    rf"|(?:the\s+)?(?P<ord>{_ORD})\s+(?P<unit>day|night|candle|evening)\s+of)"
    rf"\s+(?:the\s+)?(?P<name>{_HOLIDAY})\b", re.I)
_BARE = re.compile(rf"\b(?P<name>{_HOLIDAY})\b{_YEAR}", re.I)
_OWN = re.compile(r"\b(birthday|bday|b-day|anniversary|yahrzeit|yortzeit|yahrtzeit)\b", re.I)
#: whose, read BACK from the kind word: "on (grandpa Moshe)'s yahrzeit"
_WHO = re.compile(r"(\bon\s+(?:the\s+)?)?((?:[\w\-]+\s+)?[\w\-]+?)(?:['’]s|s['’]|['’])?\s+$", re.I)
_OWN_KIND = {"birthday": "birthday", "bday": "birthday", "b-day": "birthday",
             "anniversary": "anniversary", "yahrzeit": "yahrzeit", "yortzeit": "yahrzeit",
             "yahrtzeit": "yahrzeit"}


@dataclasses.dataclass(frozen=True)
class Named:
    """A day the speaker named. ``spans`` are the characters of ``text`` it
    claims (more than one when a word inside stays for the clock reader —
    "the first NIGHT of Chanukah" keeps "night", which gives the evening).
    ``days`` > 1 means the words named a RANGE and ``date`` is its first day."""
    spans: tuple
    date: datetime.date
    name: str
    days: int = 1

    @property
    def phrase_span(self) -> tuple:
        return (min(s for s, _ in self.spans), max(e for _, e in self.spans))


# -- resolving --------------------------------------------------------------------


def enabled() -> set:
    """The families switched on (all of them when there is no config)."""
    try:
        from assistant.occasions.feed import settings
        flags = dict(getattr(settings(), "by_name", None) or {})
    except Exception:
        flags = {}
    return {f for f in FAMILIES if flags.get(f, True)}


def _israel() -> bool:
    try:
        from assistant.occasions.feed import _cfg
        cfg = _cfg()
        return bool(getattr(getattr(cfg, "hebrew_calendar", None), "israel_holidays", True))
    except Exception:
        return True


@functools.lru_cache(maxsize=8)
def _jewish(today: datetime.date, israel: bool) -> tuple:
    """(name, first day, last day) for every holiday from a week ago to 400 days on."""
    from assistant.hebrew_calendar import enumerate_holidays
    got = enumerate_holidays(today - datetime.timedelta(days=8),
                             today + datetime.timedelta(days=400), israel=israel)
    return tuple((h.name_en, h.gregorian_erev_start + datetime.timedelta(days=1),
                  h.gregorian_end) for h in got)


def _next_jewish(name: str, today: datetime.date, israel: bool, year: "int | None"):
    """(first, last) of the next occurrence of ``name`` still under way today."""
    for n, first, last in _jewish(today, israel):
        if n != name or last < today:
            continue
        if year and not _in_year(first, year):
            continue
        return first, last
    if year:                       # a stated year further out than the table
        from assistant.hebrew_calendar import enumerate_holidays
        start = datetime.date(year, 1, 1) if year < 3000 else _hebrew_year_start(year)
        if start is None:
            return None
        for h in enumerate_holidays(start, start + datetime.timedelta(days=400), israel=israel):
            if h.name_en == name:
                first = h.gregorian_erev_start + datetime.timedelta(days=1)
                if _in_year(first, year):
                    return first, h.gregorian_end
    return None


def _hebrew_year_start(hy: int) -> "datetime.date | None":
    try:
        from pyluach import dates as _hd
        return _hd.HebrewDate(hy, 7, 1).to_pydate()
    except Exception:
        return None


def _in_year(d: datetime.date, year: int) -> bool:
    if year < 3000:
        return d.year == year
    from pyluach import dates as _hd
    return _hd.HebrewDate.from_pydate(d).year == year


def _holiday(key: str, today: datetime.date, israel: bool,
             year: "int | None" = None) -> "tuple[datetime.date, int] | None":
    """(first day, days it lasts) of the next ``key``, or None."""
    if key == "Shabbat":
        d = today + datetime.timedelta(days=(5 - today.weekday()) % 7)
        return d, 1
    if key in _CHRISTIAN or key in _ISLAMIC:
        from assistant.occasions import calendars
        fn = calendars.christian if key in _CHRISTIAN else calendars.islamic
        for b in fn(today, today + datetime.timedelta(days=400)):
            if b["title"].replace(" (expected)", "") == key:
                d = datetime.date.fromisoformat(b["date"])
                if year and not _in_year(d, year):
                    continue
                return d, (29 if key == "Ramadan begins" else 1)
        return None
    if key == "Rosh Chodesh":
        return None                                   # read by _RC, with its month
    if key in ("Seder", "Second seder", "Kol Nidre"):
        base = _next_jewish("Pesach" if "eder" in key else "Yom Kippur", today, israel, year)
        if not base:
            return None
        first = base[0]
        return (first if key == "Second seder" else first - datetime.timedelta(days=1)), 1
    if key == "Hoshana Rabba":
        base = _next_jewish("Succos", today, israel, year)
        return (base[0] + datetime.timedelta(days=6), 1) if base else None
    if key.startswith("Chol Hamoed"):
        which = key.split()[-1]
        base = _next_jewish(which, today, israel, year)
        if not base:
            return None
        first, last = base
        start = first + datetime.timedelta(days=1 if israel else 2)
        end = last if which == "Succos" else last - datetime.timedelta(days=1 if israel else 2)
        if end < start:
            return None
        return max(start, today) if start <= today <= end else start, (end - start).days + 1
    if key == "Simchas Torah" and israel:
        key = "Shmini Atzeres"
    got = _next_jewish(key, today, israel, year)
    if not got:
        return None
    first, last = got
    return first, (last - first).days + 1


def _hebrew_date(month: int, day: int, today: datetime.date,
                 year: "int | None") -> "datetime.date | None":
    """The next ``day`` of Hebrew ``month`` on or after today — Adar is Adar II
    in a leap year, as for every dated event (a yahrzeit is the occasions
    reader's, not this one's)."""
    from pyluach import dates as _hd
    from assistant.occasions.dates import hebrew_months
    if not 1 <= day <= 30:
        return None
    start = _hd.HebrewDate.from_pydate(today).year
    years = [year] if year and year >= 3000 else range(start, start + 3)
    for hy in years:
        for m in hebrew_months(hy, month, "adar2"):
            try:
                d = _hd.HebrewDate(hy, m, day).to_pydate()
            except ValueError:
                continue                              # no 30th this year
            if year and year < 3000 and d.year != year:
                continue
            if d >= today or (year and year >= 3000):
                return d
    return None


def _rosh_chodesh(month_word: "str | None", today: datetime.date) -> "tuple[datetime.date, int] | None":
    from assistant.occasions import calendars
    want = HEBREW_MONTHS.get(re.sub(r"[\s'’\-]+", " ", month_word.lower())) if month_word else None
    days: list[datetime.date] = []
    title = None
    for b in calendars.rosh_chodesh(today, today + datetime.timedelta(days=400)):
        m = _PYLUACH_MONTH.get(b["title"].replace("Rosh Chodesh ", "").lower())
        # "Adar" said in a leap year means Adar II's (see _hebrew_date)
        if want is not None and m != want and not (want == 12 and m == 13):
            continue
        d = datetime.date.fromisoformat(b["date"])
        if title is None:
            title = b["title"]
        if b["title"] != title or (days and d != days[-1] + datetime.timedelta(days=1)):
            break
        days.append(d)
    if want == 12 and title and title.endswith("Adar 1"):
        # a leap year's plain "Adar" is the second one; look past the first
        later = _rosh_chodesh("adar ii", days[-1] + datetime.timedelta(days=1))
        if later:
            return later
    return (days[0], len(days)) if days else None


def _own(who: str, kind: str, today: datetime.date) -> "tuple[datetime.date, str] | None":
    """The next date of one of the person's OWN occasions, matched by name."""
    try:
        from assistant.occasions import dates as _od, store
        recs = store.load()
    except Exception:
        return None
    who = who.strip().lower()
    for rec in recs:
        if rec.get("kind") != kind:
            continue
        title = str(rec.get("title") or "").lower()
        if who in ("my", "our"):
            ok = title.startswith(who + " ")
        else:
            ok = title == who or title.split()[:len(who.split())] == who.split()
        if not ok:
            continue
        occ = _od.occurrences(rec, today, today + datetime.timedelta(days=400))
        if occ:
            return datetime.date.fromisoformat(occ[0]["date"]), rec.get("title", "")
    return None


# -- finding ----------------------------------------------------------------------


def _follow_ok(text: str, end: int) -> bool:
    m = re.match(r"\s*([a-z']+)", text[end:], re.I)
    if not m:
        return True                               # end of text, a clock, punctuation
    return m.group(1).lower() in _FOLLOW or text[end:end + 1] in ",.;!?"


def _year(g: "str | None") -> "int | None":
    return int(g) if g else None


def find(text: str, today: datetime.date, *, whole: bool = False,
         israel: "bool | None" = None, families: "set | None" = None) -> "Named | None":
    """The day ``text`` names by a Hebrew date, a holiday or an own occasion,
    among the ``families`` switched on (Settings ▸ Occasions by default)."""
    t = text or ""
    if not t.strip() or not _ANY.search(t):
        return None
    fams = enabled() if families is None else set(families)
    israel = _israel() if israel is None else israel
    try:
        got = ((_find_hebrew_date(t, today) if "jewish" in fams else None)
               or (_find_rosh_chodesh(t, today, whole) if "jewish" in fams else None)
               or _find_explicit(t, today, israel, fams)
               or _find_bare(t, today, israel, whole, fams)
               or (_find_own(t, today, whole) if "mine" in fams else None))
    except Exception:               # a date library failing must never kill a parse
        return None
    if got is None:
        return None
    # The "on" in front belongs to the date, as it does for every date the
    # recogniser reads: left behind, "dentist on" failed the title's
    # time-residue check and the command was not read at all.
    lead = re.search(r"\bon\s+(?:the\s+)?$", t[:got.phrase_span[0]], re.I)
    if lead:
        (a, b), rest = got.spans[0], got.spans[1:]
        got = dataclasses.replace(got, spans=((lead.start(), b),) + rest)
    return got


def find_all(text: str, today: "datetime.date | None" = None) -> "list[Named]":
    """Every named day in ``text``, left to right (a command may hold two:
    "dinner on erev shabbat and dentist on 12 Adar")."""
    today = today or _clock.today()
    t, out = text or "", []
    for _ in range(4):
        got = find(t, today)
        if got is None:
            break
        out.append(got)
        a, b = got.phrase_span
        t = t[:a] + " " * (b - a) + t[b:]
    return sorted(out, key=lambda n: n.phrase_span[0])


def _led(t: str, start: int, whole: bool) -> "int | None":
    """Where a name's date phrase starts, counting its lead word — or None
    when nothing makes it a date. ``whole``: the string's own start counts as
    a lead too (a resolver's time words: "erev pesach at 7pm")."""
    lead = re.search(_LEAD + r"$", t[:start], re.I)
    if lead:
        return lead.start()
    if whole and not t[:start].strip(" ,"):
        return start
    return None


def _find_hebrew_date(t: str, today: datetime.date) -> "Named | None":
    for m in _HEB_DATE.finditer(t):
        if m.group(1):
            day, word, year = int(m.group(1)), m.group(2), _year(m.group(3))
        else:
            word, day, year = m.group(4), int(m.group(5)), _year(m.group(6))
            if _PERSON_LEAD.search(t[:m.start()]):
                continue                          # "call Sivan 5 …" is a person
        month = HEBREW_MONTHS.get(re.sub(r"[\s'’\-]+", " ", word.lower()))
        if month is None:
            continue
        d = _hebrew_date(month, day, today, year)
        if d:
            return Named(((m.start(), m.end()),), d, f"{day} {word.title()}")
    return None


def _find_rosh_chodesh(t: str, today: datetime.date, whole: bool) -> "Named | None":
    for m in _RC.finditer(t):
        start = _led(t, m.start(), whole)
        if start is None or not _follow_ok(t, m.end()):
            continue
        got = _rosh_chodesh(m.group(1), today)
        if got:
            return Named(((start, m.end()),), got[0], m.group(0).title(), got[1])
    return None


def _find_explicit(t: str, today: datetime.date, israel: bool, fams: set) -> "Named | None":
    for m in _EXPLICIT.finditer(t):
        key = _KEY_OF.get(re.sub(r"[\s'’\-]+", " ", m.group("name").lower()))
        if not key or _family(key) not in fams:
            continue
        got = _holiday(key, today, israel)
        if not got:
            continue
        first, days = got
        last = first + datetime.timedelta(days=days - 1)
        eve = first - datetime.timedelta(days=1)
        rel = (m.group("rel") or "").lower()
        spans = ((m.start(), m.end()),)
        if m.group("ord"):
            n = _ORDINALS[m.group("ord").lower()]
            unit = m.group("unit").lower()
            n = days if n == -1 else n
            if n > days:
                continue
            base = first if unit == "day" else eve     # a night begins the day after it
            d = base + datetime.timedelta(days=n - 1)
            if unit in ("night", "evening"):
                # keep the word for the clock reader: it is the evening
                u = m.start("unit")
                spans = ((m.start(), u), (m.end("unit"), m.end()))
        elif rel.startswith("erev"):
            d = eve
        elif rel.startswith("motz"):
            d = last                                  # the evening it goes out
        elif "before" in rel:
            d = eve
        else:                                         # "the day/night after"
            d = last + datetime.timedelta(days=1)
        return Named(spans, d, m.group(0).strip())
    return None


def _find_bare(t: str, today: datetime.date, israel: bool, whole: bool,
               fams: set) -> "Named | None":
    for m in _BARE.finditer(t):
        key = _KEY_OF.get(re.sub(r"[\s'’\-]+", " ", m.group("name").lower()))
        if not key or key == "Rosh Chodesh" or _family(key) not in fams:
            continue
        start = _led(t, m.start(), whole)
        if start is None or not _follow_ok(t, m.end()):
            continue
        # "until"/"through" belong to the series-bound reader, which asks for
        # them itself (whole=True on the words after the keyword)
        if re.match(r"(?:until|till|through|thru)\b", t[start:], re.I):
            continue
        got = _holiday(key, today, israel, _year(m.group(2)))
        if not got:
            continue
        first, days = got
        if first < today:          # under way already ("over Sukkot", said mid-Sukkot)
            got = today, days - (today - first).days
        end = m.end()
        # "on Purim day" — the word says nothing more; claim it with the name
        tail = re.match(r"\s+day\b", t[end:], re.I)
        if tail and key != "Shabbat":
            end += tail.end()
        return Named(((start, end),), got[0], m.group("name").title(), got[1])
    return None


def _find_own(t: str, today: datetime.date, whole: bool) -> "Named | None":
    for m in _OWN.finditer(t):
        w = _WHO.search(t[:m.start()])
        if not w or not _follow_ok(t, m.end()):
            continue
        if not w.group(1) and not (whole and not t[:w.start()].strip(" ,")):
            continue                      # "buy Dana's birthday present": not a date
        words = w.group(2).split()
        kind = _OWN_KIND[m.group(1).lower()]
        for who in ([" ".join(words[-2:]), words[-1]] if len(words) > 1 else words):
            got = _own(who, kind, today)
            if got:
                return Named(((w.start(), m.end()),), got[0], got[1])
    return None


#: A cheap first look: nothing below runs on a command without one of these.
_ANY = re.compile(rf"(?:{_HOLIDAY}|{_MONTH}|birthday|bday|b-day|anniversary|yahrzeit|"
                  rf"yortzeit|yahrtzeit)", re.I)

#: A holiday or Hebrew month in DATE position ("on …", "erev …") — what
#: ``unread`` looks for when ``find`` came back empty.
_DATE_POSITION = re.compile(
    rf"(?:{_LEAD}|\b(?:erev|motzei|motzash)\s+)(?:the\s+)?(?:{_JEWISH}|{_MONTH}|"
    rf"yom\s+tov|chag|the\s+fast|chol\s+hamoed)\b", re.I)


def unread(text: str, today: datetime.date) -> "str | None":
    """The words of a named day ``find`` could not place, or None. A command
    carrying one must not be committed on a DEFAULT day: that is exactly how
    "dinner on erev Pesach" was booked for today."""
    if "jewish" not in enabled():
        return None                      # switched off: the words are just words
    m = _DATE_POSITION.search(text or "")
    if not m or find(text, today) is not None:
        return None
    return m.group(0).strip()
