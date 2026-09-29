"""Which hours the Week and Day views show (Settings ▸ Appearance ▸ Show hours).

Gil, 2026-09-29: *"allow user to control from what hour to what hour shows …
midnight to 7am no point cause usually sleeping"*, then *"end is midnight and
start is 7am so calendar displays from 7am to midnight"* — and, of the first
build: *"The show 7am to midnight doesn't work well enough"*. That build FIT
the chosen hours to the window and left the rest a scroll away: the grid
still ran midnight to midnight, a sliver of 6 AM showed above 7 AM (the rows
are whole pixels), and a 5:30 AM event sat invisible above the top with
nothing saying it was there.

So the views now DRAW only the chosen hours (``HourWindow``): 7 AM is the
top edge, midnight the bottom, the rows fill the window, and there is nothing
above or below to scroll into. What made the first build keep the night
hours still holds — an event at 5 AM must never vanish because of a display
preference — and is kept by ``widen``: when the days on screen hold an event
outside the chosen hours, the window grows to include it, for those days only.
Everything inside the views still measures from midnight; the window only
decides which slice of that 24-hour canvas is on screen.
"""

from __future__ import annotations


def span(ui) -> tuple[int, int]:
    """``(first, last)`` hour — 0…23 and 1…24, last after first. Anything
    malformed is the whole day."""
    try:
        first = int(getattr(ui, "hours_from", 0))
        last = int(getattr(ui, "hours_to", 24))
    except (TypeError, ValueError):
        return 0, 24
    if not (0 <= first <= 23 and 1 <= last <= 24 and last > first):
        return 0, 24
    return first, last


def fit(viewport_h: int, first: int, last: int, min_h: int, max_h: int) -> int:
    """Pixels per hour so the shown hours fill the window: never below
    ``min_h`` (then it scrolls), never above ``max_h``. Rounded down, so the
    last hour ends at most a few pixels above the bottom edge and never
    past it."""
    return max(min_h, min(max_h, viewport_h // max(1, last - first)))


def widen(first: int, last: int, events) -> tuple[int, int]:
    """The chosen hours, grown to hold every TIMED event in ``events`` — an
    event outside them must never be hidden by a display preference."""
    if (first, last) == (0, 24):
        return first, last
    for ev in events or ():
        start, end = _hm(ev.get("start_time")), _hm(ev.get("end_time"))
        if start is None or ev.get("all_day"):
            continue
        if end is None or end <= start:
            end = 24 * 60 if end is not None and end <= start else start + 60
        first = min(first, start // 60)
        last = max(last, min(24, -(-end // 60)))
    return first, last


def _hm(value) -> "int | None":
    try:
        h, m = str(value).split(":")[:2]
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        return None


def HourWindow(body):
    """The scroll area's widget: a window onto ``body`` — a 24-hour canvas —
    showing hours ``first``…``last`` only. ``body`` keeps its own
    coordinates, so everything drawn or dragged inside it is untouched."""
    from PyQt6.QtWidgets import QWidget

    class _HourWindow(QWidget):
        def __init__(self, inner):
            super().__init__()
            self._inner = inner
            inner.setParent(self)
            self.first, self.last, self.hour_h = 0, 24, 48

        def set_window(self, first: int, last: int, hour_h: int) -> None:
            self.first, self.last, self.hour_h = first, last, hour_h
            self.setFixedHeight((last - first) * hour_h)
            self._place()

        def resizeEvent(self, event):              # noqa: N802 — Qt's name
            super().resizeEvent(event)
            self._place()

        def _place(self) -> None:
            self._inner.setGeometry(0, -self.first * self.hour_h, self.width(),
                                    24 * self.hour_h)

    return _HourWindow(body)


def label(hour: int) -> str:
    """0 → "12 AM", 13 → "1 PM", 24 → "12 AM (midnight)"."""
    if hour == 24:
        return "12 AM (midnight)"
    h = hour % 12 or 12
    return f"{h} {'AM' if hour < 12 else 'PM'}"
