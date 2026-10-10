"""Occasions by voice (DEVQA Q73, Gil: "add them by voice"): read one.

    "Dana's birthday is March 3rd"            → birthday, Dana, 3 March
    "remember our anniversary, June 20 2021"  → anniversary, Our anniversary, 20 June 2021
    "add grandpa Moshe's yahrzeit, 12 Adar"   → yahrzeit, Grandpa Moshe, 12 Adar (Hebrew)
    "countdown to the wedding on December 1"  → countdown, The wedding, 1 December

NARROW BY DESIGN. FastRule's practice set has 116 commands mentioning these
words and nearly all are EVENTS — "book birthday dinner tomorrow at 7:30",
"put a marker on tonight for our anniversary". So a command is an occasion
only when it has ALL of: an occasion word, a whose/what, and an EXPLICIT
calendar date (a month name, or a Hebrew month); and NONE of: a clock time,
a relative day ("tomorrow", "next tuesday", "tonight"), or an event word
("dinner", "party", "book", "buy" …). Anything else is left to the engine
exactly as before.

``read(text)`` → ``{"kind", "title", "calendar", "month", "day", "year"}`` or
None. ``from_words(kind, name, date_text, year)`` is the same date reading
for the model's path (the ``add_occasion`` action), which passes the day
words as said.
"""

from __future__ import annotations

import datetime
import re

_KIND = {"birthday": "birthday", "bday": "birthday", "b-day": "birthday",
         "anniversary": "anniversary", "yahrzeit": "yahrzeit", "yortzeit": "yahrzeit",
         "yahrtzeit": "yahrzeit", "jahrzeit": "yahrzeit", "yartzeit": "yahrzeit"}
_KIND_RE = r"(birthday|b-day|bday|anniversary|yahrzeit|yortzeit|yahrtzeit|jahrzeit|yartzeit)"

_GREG = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
_GREG.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
              "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
#: Hebrew months → pyluach numbers (Nisan = 1 … Adar = 12, Adar II = 13) —
#: the one table, kept where the engine's named-day reader uses it too.
from assistant.named_days import HEBREW_MONTHS as _HEB  # noqa: E402
from assistant import clock as _clock  # the moment the command was SAID

_GREG_ALT = "|".join(sorted(_GREG, key=len, reverse=True))
_HEB_ALT = "|".join(sorted((re.escape(k) for k in _HEB), key=len, reverse=True))
_ORD = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s+(?:in\s+)?(\d{4}))?"

#: Clock times, relative days and event words: any one leaves the command to
#: the engine (it is an event, or not clearly an occasion).
_NOT_AN_OCCASION = re.compile(
    r"\b(\d{1,2}(:\d\d)?\s*(am|pm|a\.m\.|p\.m\.)|\d{1,2}:\d\d|noon|midnight|o'?clock|"
    r"today|tonight|tomorrow|yesterday|this (morning|afternoon|evening|week|weekend|month)|"
    r"next (week|month|year|mon|tue|wed|thu|fri|sat|sun)\w*|"
    r"(mon|tues|wednes|thurs|fri|satur|sun)day|weekend|"
    r"party|dinner|lunch|breakfast|brunch|drinks|celebration|bash|meal|cake|gift|present|"
    r"shopping|buy|order|call|meeting|surprise|plan|book|reservation|picnic|bbq|barbecue|"
    r"card|flowers|remind me to|every|weekly|daily|monthly)\b", re.I)

_LEAD = re.compile(r"^\s*(please\s+)?(can you\s+|could you\s+)?"
                   r"(add|remember|save|note|put|set|mark|record|store|log|enter|create)?\s*"
                   r"(down\s+)?(that\s+|the fact that\s+)?", re.I)
_TAIL = re.compile(r"\s*(to|in|on|into)\s+(my|the)\s+(calendar|occasions|list|birthdays)\s*$", re.I)


def _date(text: str) -> "tuple[str, int, int, int | None] | None":
    """(calendar, month, day, year) from explicit date words, or None."""
    t = text.lower()
    for pat, cal in ((rf"{_ORD}\s+(?:of\s+)?({_HEB_ALT})\b{_YEAR}", "hebrew"),
                     (rf"\b({_HEB_ALT})\s+{_ORD}\b{_YEAR}", "hebrew"),
                     (rf"{_ORD}\s+(?:of\s+)?({_GREG_ALT})\b{_YEAR}", "gregorian"),
                     (rf"\b({_GREG_ALT})\s+{_ORD}\b{_YEAR}", "gregorian")):
        m = re.search(pat, t)
        if not m:
            continue
        a, b, year = m.group(1), m.group(2), m.group(3)
        day, month_word = (a, b) if a.isdigit() else (b, a)
        table = _HEB if cal == "hebrew" else _GREG
        month = table.get(month_word.strip())
        if month is None:
            continue
        # "the 3rd of may" is a date; "may" alone after a number is too — but a
        # bare "may" elsewhere ("I may …") never gets here: it needs a number.
        return cal, month, int(day), int(year) if year else None
    return None


def _clean_name(raw: str) -> str:
    name = _LEAD.sub("", raw).strip(" ,.:;-")
    name = re.sub(r"^(the|a)\s+", "", name, flags=re.I)
    return name[:1].upper() + name[1:] if name else ""


def read(text: str) -> "dict | None":
    """An occasion stated in ``text``, or None (leave it to the engine)."""
    t = " ".join((text or "").split())
    if not t or _NOT_AN_OCCASION.search(t):
        return None
    date = _date(t)
    if date is None:
        return None
    cal, month, day, year = date
    # countdown to X (on) <date>
    m = re.search(r"\bcount\s*down\s+(?:to|until|till)\s+(?:the\s+)?(.+?)\s+(?:on|in|is|at|,)?\s*"
                  r"(?=\d|" + _GREG_ALT + r")", t, re.I)
    if m and cal == "gregorian":
        name = _clean_name(m.group(1))
        if name:
            today = _clock.today()
            y = year or (today.year if (month, day) >= (today.month, today.day) else today.year + 1)
            return {"kind": "countdown", "title": name, "calendar": "gregorian",
                    "month": month, "day": day, "year": y}
        return None
    # <whose>'s <kind> …  |  our/my <kind> …  |  <kind> of/for <whose> …
    m = (re.search(rf"(?:^|\s)(our|my)\s+(?:wedding\s+)?{_KIND_RE}\b", t, re.I)
         or re.search(rf"^(.+?)['’]s?\s+(?:wedding\s+)?{_KIND_RE}\b", t, re.I)
         or re.search(rf"\b{_KIND_RE}\s+(?:of|for)\s+([a-z][\w' .-]*?)\s*(?:,|\bis\b|\bon\b|\bfalls\b|$)",
                      t, re.I))
    if not m:
        return None
    if m.re.pattern.startswith(r"\b"):          # "<kind> of|for <whose>"
        kind_word, who = m.group(1), m.group(2)
    else:
        who, kind_word = m.group(1), m.group(2)
    kind = _KIND[kind_word.lower()]
    who_l = who.strip().lower()
    if who_l in ("our", "my"):
        title = f"{'Our' if who_l == 'our' else 'My'} {kind}"
    else:
        title = _clean_name(who)
        if not title or len(title) > 60:
            return None
    if kind == "yahrzeit" and cal != "hebrew":
        return None                 # a yahrzeit is kept by the Hebrew date: ask the engine
    return {"kind": kind, "title": title, "calendar": cal, "month": month, "day": day,
            "year": year}


def from_words(kind: str, name: str, date_text: str, year: "int | None" = None) -> "dict | None":
    """The model's path: the action passes the day words as said."""
    kind = (kind or "").lower()
    kind = _KIND.get(kind, kind if kind in ("countdown", "custom") else "")
    date = _date(date_text or "")
    if not kind or not (name or "").strip() or date is None:
        return None
    cal, month, day, y = date
    y = y or year
    if kind == "countdown":
        if cal != "gregorian":
            return None
        if not y:
            today = _clock.today()
            y = today.year if (month, day) >= (today.month, today.day) else today.year + 1
    return {"kind": kind, "title": _clean_name(name), "calendar": cal, "month": month,
            "day": day, "year": y}
