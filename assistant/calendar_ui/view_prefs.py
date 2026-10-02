"""How the calendar is DRAWN — one place every view asks (Settings ▸ Appearance).

Gil, 2026-09-29, after asking what he could change about the views: *"sure
can add all those"* —

    first day of the week   Sunday or Monday          ui.week_starts
    clock                   12-hour or 24-hour        ui.clock
    days Week shows         any of the seven          ui.week_days
    hour-row height         fit the chosen hours, or  ui.hour_height
                            a fixed size (scrolls)
    week numbers            in Month                  ui.show_week_numbers

The views used to decide these on their own, and disagreed: the time column
said "2 PM" while an event block said "14:30", and "the week starts on
Sunday" was written out in five places. Now `apply(ui)` sets the answers once
(at startup and on Save) and the views read them. Display only: dates are
stored as dates and times as 24-hour "HH:MM" whatever this says.
"""

from __future__ import annotations

import datetime

MONDAY, SUNDAY = 0, 6                       # Python's weekday() numbers
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_first = SUNDAY
_clock24 = False
_days = frozenset(range(7))
_hour_height = 0                            # 0 = fit the window
_icon_count, _icon_groups = 0, frozenset()  # title icons (label/title_icons)


def apply(ui) -> None:
    """Take the settings from a config's ``ui`` section (tolerant of anything)."""
    global _first, _clock24, _days, _hour_height
    _first = MONDAY if str(getattr(ui, "week_starts", "sunday")).lower() == "monday" else SUNDAY
    _clock24 = str(getattr(ui, "clock", "12h")).lower() == "24h"
    names = getattr(ui, "week_days", None) or list(DAY_NAMES)
    days = {DAY_NAMES.index(n) for n in (str(x).lower()[:3] for x in names) if n in DAY_NAMES}
    _days = frozenset(days) or frozenset(range(7))          # never an empty week
    try:
        h = int(getattr(ui, "hour_height", 0) or 0)
    except (TypeError, ValueError):
        h = 0
    _hour_height = h if 20 <= h <= 160 else 0


def apply_titles(config) -> None:
    """Take the `title_emoji` settings: how many icons a title gets, of which
    kinds. Read once here, like the rest, so a redraw never re-reads config."""
    global _icon_count, _icon_groups
    from assistant.engine.label import title_icons
    _icon_count = title_icons.count_from(config)
    _icon_groups = frozenset(title_icons.groups_from(config))


def title_icons(title: str) -> "list[str]":
    """The icons drawn before `title` on every view — none unless switched on."""
    if not _icon_count:
        return []
    from assistant.engine.label import title_icons as _ti
    return _ti.icons(title, _icon_count, set(_icon_groups))


# -- the first day of the week ---------------------------------------------------

def first_weekday() -> int:
    return _first


def week_start(d: datetime.date) -> datetime.date:
    """The first day of the week holding ``d``."""
    return d - datetime.timedelta(days=(d.weekday() - _first) % 7)


def weekday_order() -> list[int]:
    """weekday() numbers in display order: Sun…Sat or Mon…Sun."""
    return [(_first + i) % 7 for i in range(7)]


# -- density -----------------------------------------------------------------------

def dense(ui) -> bool:
    """Settings ▸ Appearance ▸ Compact layout density. Tighter rows where a
    view lists things — Month's pills, Tasks, the agenda; Week and Day are
    sized by Hour rows instead. It used to tighten only the Settings dialog's
    own spacing, which nobody looks at long enough to want denser (row 36)."""
    return bool(getattr(ui, "compact_ui", False))


# -- the clock ---------------------------------------------------------------------

def clock24() -> bool:
    return _clock24


def fmt_hhmm(hhmm: str, compact: bool = False) -> str:
    """"14:30" as this person reads times: "14:30", or "2:30 PM" ("2:30p"
    compact). Anything unparseable comes back as it was."""
    try:
        h, m = (int(x) for x in str(hhmm).split(":")[:2])
    except (TypeError, ValueError):
        return hhmm
    if _clock24:
        return f"{h:02d}:{m:02d}"
    h12 = h % 12 or 12
    if compact:
        return f"{h12}:{m:02d}{'a' if h < 12 else 'p'}" if m else f"{h12}{'a' if h < 12 else 'p'}"
    return f"{h12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def hour_label(h: int) -> str:
    """The time column's label for hour ``h`` (0…23)."""
    if _clock24:
        return f"{h:02d}:00"
    return "12 AM" if h == 0 else f"{h} AM" if h < 12 else "12 PM" if h == 12 else f"{h - 12} PM"


# -- the week's days, and the row height -----------------------------------------------

def shows(d: datetime.date) -> bool:
    """Does Week draw this day?"""
    return d.weekday() in _days


def fixed_hour_height() -> int:
    """A fixed px per hour, or 0 to fit the chosen hours to the window."""
    return _hour_height
