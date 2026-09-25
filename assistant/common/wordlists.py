"""Weekday and month words — one table each, in Python's conventions.

Weekdays follow `date.weekday()` (monday = 0); months are 1-based. Before
2026-09-25 the weekday table was typed out in eleven places and the month
table in four; every copy agreed, which is exactly why they can be one.
Read-only by convention: a caller that needs more keys copies first.
"""
from __future__ import annotations

WEEKDAYS: "tuple[str, ...]" = ("monday", "tuesday", "wednesday", "thursday",
                               "friday", "saturday", "sunday")

#: name -> index, full names only.
WEEKDAY_INDEX: "dict[str, int]" = {name: i for i, name in enumerate(WEEKDAYS)}

#: name -> index, full names AND the abbreviations speech and typing use.
WEEKDAY_ABBR_INDEX: "dict[str, int]" = {
    **WEEKDAY_INDEX,
    "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

MONTHS: "tuple[str, ...]" = ("january", "february", "march", "april", "may",
                             "june", "july", "august", "september", "october",
                             "november", "december")

#: name -> 1-based month, full names only.
MONTH_INDEX: "dict[str, int]" = {name: i for i, name in enumerate(MONTHS, start=1)}

#: name -> month, full names, three-letter abbreviations, and "sept".
MONTH_ABBR_INDEX: "dict[str, int]" = {
    **MONTH_INDEX,
    **{name[:3]: i for i, name in enumerate(MONTHS, start=1)},
    "sept": 9,
}
