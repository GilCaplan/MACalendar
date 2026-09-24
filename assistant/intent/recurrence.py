"""Recurrence as a SLOT of one atomic item (Gil's architecture call).

A recurring command is ONE atomic item that happens to repeat — never N
items. `db.create_event()` already expands a single intent carrying
`recurrence` + `recurrence_end` into the series (shared `series_id`,
`_next_date`, the Shabbat/yom-tov skip), so the only thing missing was the
extractor: FastRule never filled the slot, so "book haircut every monday at
9am" produced no cadence AND no date, and deferred. Recurring rows were 412
of the 7,200 dataset's atomic train rows and 72% of them failed.

Two rules the project already fixed elsewhere and this must honour:

  • the cadence is only ever daily / weekly / monthly / yearly (the fourth
    added 2026-09-08: rounding a yearly series to monthly is 12x wrong and
    fires eleven times nobody asked for, so it is the one cadence rounding
    could not honestly cover) — anything else is ROUNDED to one of those,
    and `rounded_from` carries the original words so the reply can announce
    it ("every other tuesday" → weekly).
  • a weekly series starts on the SOONEST day the sentence names, not on
    whatever date happened to parse.
"""
from __future__ import annotations

import datetime
import re

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6,
             "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3,
             "thurs": 3, "fri": 4, "sat": 5, "sun": 6}

_FULL = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY_ALT = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
#: One weekday, singular or plural ("tuesday", "tuesdays", "tue").
_DAY = rf"(?:{_DAY_ALT})s?"
#: A LIST of weekdays behind "every"/"each"/"on" — "every tuesday and thursday",
#: "on tuesdays and thursdays", "every mon, wed and fri" — or a bare run of
#: PLURAL weekdays, which is recurring English on its own ("tuesdays and
#: thursdays"). The whole list is one cadence phrase (2026-09-24): the reader
#: used to stop at the first day, so "book yoga every tuesday and thursday at
#: 6pm" became a Thursday-only series and the Tuesdays were lost, although
#: the database has expanded a multi-weekday series (`recur_days`) since
#: 2026-09-08. The deep path's resolver already read the list.
_DAY_LIST_RE = re.compile(
    rf"\b(?:(?:every|each|on)\s+{_DAY}|(?:{'|'.join(_FULL)})s)"
    rf"(?:\s*(?:,|&|\band\b|\bor\b)\s*(?:and\s+)?{_DAY}\b)*", re.I)

#: (pattern, cadence, needs_announcing) — order matters, first match wins.
_PATTERNS = [
    (r"\bevery\s+other\s+(\w+)\b", "weekly", True),      # rounded: fortnightly
    (r"\bevery\s+(?:week)?day\b", "daily", True),        # "every weekday" rounds
    (r"\bevery\s+day\b|\bdaily\b|\beach\s+day\b", "daily", False),
    (r"\bevery\s+week\b|\bweekly\b|\beach\s+week\b", "weekly", False),
    (r"\bevery\s+month\b|\bmonthly\b|\beach\s+month\b", "monthly", False),
    (r"\btwice\s+a\s+(?:week|month)\b|\b\d+\s+times\s+a\s+(?:week|month)\b",
     "weekly", True),                                    # rounded: no N-per-period
    (r"\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
     r"mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b", "weekly", False),
    # A plural weekday is a series on its own: "yoga on tuesdays".
    (r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s\b", "weekly", False),
    (r"\bevery\s+year\b|\byearly\b|\bannually\b", "yearly", False),
]

#: "until the end of September", "through friday", "starting march 3"
_UNTIL_RE = re.compile(r"\b(?:until|till|through|thru|up to)\b", re.I)


class Recurrence:
    """What one command said about repeating. `cadence` None ⇒ not recurring."""

    __slots__ = ("cadence", "anchor_weekday", "rounded_from", "has_until", "span", "days")

    def __init__(self, cadence=None, anchor_weekday=None,
                 rounded_from=None, has_until=False, span=None, days=None):
        self.cadence = cadence
        self.anchor_weekday = anchor_weekday     # 0=Monday … 6=Sunday, or None
        self.rounded_from = rounded_from         # the words we rounded, or None
        self.has_until = has_until
        #: (start, end) of the cadence phrase in the text it was read from, or
        #: None. The subtractive title blanks it: "book annual checkup MONTHLY
        #: at 8:30pm" titled itself "annual checkup monthly" without this, and
        #: the adverb sitting right after the title is 13 of the 19 bounded-row
        #: deferrals the last cycle left behind.
        self.span = span
        #: Full weekday names a WEEKLY series lands on when the sentence named
        #: more than one ("tuesday", "thursday"); empty for one day or none.
        self.days = list(days or [])

    def __bool__(self) -> bool:
        return self.cadence is not None

    def start_date(self, today: datetime.date) -> datetime.date:
        """The series anchor: the SOONEST day the sentence names (today
        counts), else today."""
        if self.days:
            nums = [_FULL.index(d) for d in self.days]
            return today + datetime.timedelta(
                days=min((n - today.weekday()) % 7 for n in nums))
        if self.anchor_weekday is None:
            return today
        delta = (self.anchor_weekday - today.weekday()) % 7
        return today + datetime.timedelta(days=delta)


def detect(text: str) -> Recurrence:
    """Read the cadence out of a command. Deterministic, no LLM."""
    low = text.lower()
    for pattern, cadence, rounds in _PATTERNS:
        m = re.search(pattern, low)
        if not m:
            continue
        anchor = None
        # a named weekday anywhere in the phrase anchors a weekly series
        for word, idx in _WEEKDAYS.items():
            if re.search(rf"\b{word}s?\b", low):   # "tuesdays" names Tuesday too
                anchor = idx
                break
        span = (m.start(), m.end())
        days: list = []
        if cadence == "weekly" and not rounds:
            lm = _DAY_LIST_RE.search(low)
            if lm:
                named = []
                for w in re.findall(rf"\b({_DAY_ALT})s?\b", lm.group(0)):
                    full = _FULL[_WEEKDAYS[w]]
                    if full not in named:
                        named.append(full)
                if len(named) > 1:
                    days = named
                # The whole list is the cadence phrase, so the title never
                # keeps "and thursday".
                span = (min(span[0], lm.start()), max(span[1], lm.end()))
        return Recurrence(cadence, anchor,
                          m.group(0) if rounds else None,
                          bool(_UNTIL_RE.search(low)),
                          span, days)
    return Recurrence()
