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
    # THE END OF THE MONTH is its last day — the project's convention for
    # "until the end of the month" (CLAUDE.md, `rule_parser` "names the final
    # day"), read the same way where it is the day itself. Unscored until
    # 2026-09-25: 108 rows of the FastRule 7,200 train half say it, and the
    # front door booked them mid-month.
    m = re.match(r"(?:(?:at|by|for|on|before|towards?)\s+)?(?:the\s+)?end\s+of\s+"
                 r"(the|this|next)\s+month$", s)
    if m:
        first = today.replace(day=1)
        if m.group(1) == "next":
            first = (first + _dt.timedelta(days=32)).replace(day=1)
        return ((first + _dt.timedelta(days=32)).replace(day=1)
                - _dt.timedelta(days=1)).isoformat()
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
#: "from now" is an offset ("two weeks from now"), not the word NOW as a time:
#: counting it charged six all-day bookings as "booked at midnight" (2026-09-25).
_NOW_RE = re.compile(r"\b(?:right\s+now|(?<!from\s)now|immediately|asap)\b", re.I)

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


#: A spoken RANGE: "from 6 to 8", "between 2 and 4", "from noon to 1",
#: "from 3 to 4pm". Every range was invisible to `explicit time right`, which
#: only scores a phrase carrying am/pm, a colon or o'clock, so 28 of the 43
#: train ranges were never scored at all — and "between 2 and 4 this
#: afternoon" was booked 16:00-17:00 (2026-09-25).
_RANGE = re.compile(
    r"^(?:from\s+|between\s+)?(?P<a>\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|noon|midday)\s+"
    r"(?:to|and|till|until|-)\s+"
    r"(?P<b>\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|noon|midday|midnight)$", re.I)


def ruled_range(phrase: str, text: str) -> "tuple[str, str] | None":
    """(start, end) the rulings give a spoken range, or None if it is not one.

    When only the END carries its half ("from 9 to 11pm", "from 3 to 4pm"),
    the start takes the same half if that keeps it before the end, else the
    other one. Otherwise the start is `_ruled_hhmm`'s — Q28 and the day words
    — and a bare end is the first reading of its hour AFTER the start ("from
    11 to 1" ends 13:00). Written without reference to the engine's reader,
    so the two cannot share a mistake.
    """
    m = _RANGE.match((phrase or "").strip().lower())
    if not m:
        return None
    a, b = m.group("a").strip(), m.group("b").strip()
    a_base, b_base = _phrase_to_hhmm(a), _phrase_to_hhmm(b)
    if a_base is None or b_base is None:
        return None
    mins = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:])
    a_said = time_is_unambiguous(a) or a in ("noon", "midday")
    b_said = time_is_unambiguous(b) or b in ("noon", "midday", "midnight")
    if b_said and not a_said:
        end = b_base
        h = int(a_base[:2]) % 12
        pm_end = mins(end) >= 12 * 60
        first = [h + 12, h] if pm_end else [h, h + 12]
        hh = next((x for x in first if x * 60 + int(a_base[3:]) < mins(end)), None)
        if hh is None:
            return None
        return f"{hh:02d}:{a_base[3:]}", end
    start = _ruled_hhmm(a, text)
    if start in (None, CONTRADICTORY):
        return None if start is None else (CONTRADICTORY, CONTRADICTORY)
    if b_said:
        return start, b_base
    h, bm = int(b_base[:2]) % 12, int(b_base[3:])
    end = next((f"{x:02d}:{bm:02d}" for x in (h, h + 12) if x * 60 + bm > mins(start)), None)
    if end is None:
        return None
    return start, end


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


