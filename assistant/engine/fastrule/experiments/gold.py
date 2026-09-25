"""The FastRule board's GOLD CONVERTERS, side-effect free (2026-09-25).

Phrase -> date, phrase -> clock by the rulings, the harm weights: pure
functions every board that scores FastRule-set rows needs. They lived inside
`fastrule_shape.py`, which sets up its scratch environment when imported —
so no other board could reuse them without resetting its own store paths
mid-run. `fastrule_shape` imports them from here under the same names.
"""
from __future__ import annotations

import datetime as _dt
import re

#: An EXPLICIT spoken time — a digit or a named hour. These are the ones a
#: parse can get objectively wrong, so they are scored against the produced
#: start_time. Vague dayparts ("late afternoon") are deliberately excluded:
#: the engine maps them by a documented convention, and scoring our own
#: convention against itself would prove nothing.
_EXPLICIT_TIME_RE = re.compile(
    r"\b\d{1,2}\s*(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b"
    r"|\bnoon\b|\bmidnight\b|\bquarter (?:to|past)\b|\bhalf past\b", re.I)

_HHMM = re.compile(r"^\d{2}:\d{2}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

from assistant.common.wordlists import MONTH_INDEX as _MONTH  # noqa: E402
from assistant.common.wordlists import WEEKDAY_INDEX as _WEEKDAY  # noqa: E402


def _phrase_to_date(phrase: str, today: "_dt.date") -> "str | None":
    """Resolve a ground-truth date phrase to an ISO date, or None when the
    phrase is inherently a RANGE ("next week", "this weekend") — those have
    no single right answer, so they are excluded from scoring rather than
    guessed at. Dates had NO metric at all until now (Gil, 2026-09-07);
    times were added the same day and immediately exposed a live defect.
    """
    s = (phrase or "").strip().lower()
    if s in ("today", "this afternoon", "this evening", "this morning", "tonight"):
        return today.isoformat()
    if s in ("tomorrow", "tomorrow morning", "tomorrow afternoon", "tomorrow evening"):
        return (today + _dt.timedelta(days=1)).isoformat()
    if s in ("the day after tomorrow",):
        return (today + _dt.timedelta(days=2)).isoformat()
    m = re.match(r"in (\d+|a|two|three|four|five|six|seven) days?$", s)
    if m:
        n = {"a": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7}.get(m.group(1))
        n = n if n else int(m.group(1))
        return (today + _dt.timedelta(days=n)).isoformat()
    m = re.match(r"(?:this|next|coming|on)\s+(\w+day)$", s)
    if m and m.group(1) in _WEEKDAY:
        delta = (_WEEKDAY[m.group(1)] - today.weekday()) % 7
        if s.startswith("next"):
            delta = delta or 7
        return (today + _dt.timedelta(days=delta or 7 if s.startswith("next") else delta)).isoformat()
    m = re.match(r"(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?$", s)
    if m:                                   # "the 21st" — this month or next
        day = int(m.group(1))
        cand = today.replace(day=day) if day >= today.day else None
        if cand is None:
            nm = (today.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
            cand = nm.replace(day=day)
        return cand.isoformat()
    m = re.match(r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?$", s)
    if m and m.group(1) in _MONTH:          # "march 5th"
        mo, day = _MONTH[m.group(1)], int(m.group(2))
        yr = today.year + (1 if (mo, day) < (today.month, today.day) else 0)
        return _dt.date(yr, mo, day).isoformat()
    return None                             # ranges and anything unresolved


#: How much a wrong commit COSTS the user (Gil, 2026-09-07). A wrong title is
#: an annoyance; a wrong DELETE destroys something they may not get back. The
#: project already rules that "deleting is destructive" — the metric should
#: say so too, or the loop has no reason to prefer failing safely.
# NB the escaping: this was written `r"\\b…\\b"` — a raw string with a DOUBLED
# backslash, so it matched a literal "\b" and never a word boundary. The
# pattern could not fire, `NOW_N` stayed 0, and `if NOW_N:` meant the whole
# midnight section below was silently absent from every board this file has
# ever printed. A metric that cannot report is worse than no metric: it reads
# as "nothing to see".
_NOW_RE = re.compile(r"\b(?:right\s+now|now|immediately|asap)\b", re.I)

#: A title that names nothing — the word for a calendar entry rather than a
#: name for one. Same shape as fastrule's `_GENERIC_TARGET_RE`.
_EMPTY_TITLE_RE = re.compile(
    r"^(?:my |the |a |an |this )?"
    r"(?:reminder|alert|event|appointment|task|todo|thing|item|meeting)s?$",
    re.I)

_SEVERITY = {
    "delete_event": 4, "delete_todo": 4,     # irreversible-ish loss
    "update_event": 2, "update_todo": 2,     # overwrote something real
    "complete_todo": 2,                      # marked the wrong thing done
    "create_event": 1, "create_todo": 1,     # a spurious row, easily removed
    "query": 0, "query_schedule": 0, "query_todos": 0,   # read-only
}


#: `\bam\b` does NOT match "8:45am" — digit and letter are both word
#: characters, so there is no boundary between them. The lookbehind is what
#: makes "8:45am" match while "program" does not.
_AMPM = re.compile(r"(?<![a-z])(?:am|pm)\b|\bnoon\b|\bmidnight\b|\bmidday\b", re.I)
_CLOCK24 = re.compile(r"^(?:at\s+)?(\d{1,2}):(\d{2})$")
_EVENING = re.compile(r"\b(?:evening|tonight|night)\b", re.I)
_AFTERNOON = re.compile(r"\bafternoon\b", re.I)
_MORNING = re.compile(r"\bmorning\b", re.I)


def time_is_unambiguous(phrase: str) -> bool:
    """Does the speaker's own phrase FIX the half of the day? ('7pm', '07:00',
    '19:00', 'noon'). Moved here from `scripts/persona_board.py`, which had
    already learned the split; both boards now read this one."""
    s = (phrase or "").strip().lower()
    if _AMPM.search(s):
        return True
    m = _CLOCK24.match(s)
    if m:
        return int(m.group(1)) >= 13 or m.group(1).startswith("0")
    return False


#: Sentinel: the words contradict themselves ("this afternoon at 9:15"), so
#: there is no right answer to score against.
CONTRADICTORY = "contradictory"


def _ruled_hhmm(phrase: str, text: str) -> "str | None":
    """The start time the RULINGS say a spoken time means, in its sentence.

    `_phrase_to_hhmm` reads the phrase alone and puts every bare hour in the
    morning — "6:45" is 06:45 even in "this evening at 6:45", and "half past
    six" is 06:30 though DEVQA Q28 (2026-09-20) says a bare 1-8 is PM. So the
    `explicit time right` line charged the engine for obeying the rulings: 155
    of 708 scored train rows "wrong", nearly all of them right (2026-09-25).

      * said with its half of the day (am/pm, noon, midnight, a 24-hour
        clock): as said — the speaker's own word beats any day word
      * bare, beside a day word: evening/tonight/night -> PM; afternoon ->
        PM for 12-8 (9-11 contradicts it); morning -> AM
      * bare, alone: Q28 — 1-8 PM (7 and 8 are ASKED on the phone, PM when
        told), 9-12 as said; on the clock hour ("quarter to nine" is 8:45)
    """
    base = _phrase_to_hhmm(phrase)
    if base is None or time_is_unambiguous(phrase):
        return base
    h, mins = int(base[:2]), base[3:]
    t = (text or "").lower()
    pm = lambda: f"{h + 12 if h < 12 else 12:02d}:{mins}"
    if _EVENING.search(t):
        return CONTRADICTORY if h == 12 else pm()
    if _AFTERNOON.search(t):
        return pm() if (h == 12 or h <= 8) else CONTRADICTORY
    if _MORNING.search(t):
        return CONTRADICTORY if h == 12 else base
    # On the CLOCK hour, as the front door reads it: "quarter to nine" is
    # rewritten to 8:45 before anything resolves it, and Q28's bare 8 is PM.
    return pm() if 1 <= h <= 8 else base


def _phrase_to_hhmm(phrase: str) -> "str | None":
    """Resolve an explicit spoken time to HH:MM, or None if it isn't one."""
    s = (phrase or "").strip().lower()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
             "twelve": 12}
    m = re.match(r"quarter to (\w+)$", s)
    if m and (m.group(1) in words or m.group(1).isdigit()):
        h = (words.get(m.group(1)) or int(m.group(1))) - 1
        return f"{(12 if h == 0 else h):02d}:45"
    m = re.match(r"(?:quarter past|half past) (\w+)$", s)
    if m and (m.group(1) in words or m.group(1).isdigit()):
        h = words.get(m.group(1)) or int(m.group(1))
        return f"{h:02d}:{'15' if s.startswith('quarter') else '30'}"
    if s in ("noon", "midday"):
        return "12:00"
    if s == "midnight":
        return "00:00"
    m = re.match(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if m:
        h = int(m.group(1)); mins = m.group(2) or "00"; ap = m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mins}"
    return None


