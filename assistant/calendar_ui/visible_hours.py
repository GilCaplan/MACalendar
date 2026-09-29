"""Which hours the Week and Day views fit to the window (Settings ▸ Appearance).

Gil, 2026-09-29: *"allow user to control from what hour to what hour shows …
midnight to 7am no point cause usually sleeping, but allow user to
customize"*. The chosen span is what FILLS the window — bigger rows, the view
opening at its first hour — and the hours outside it are a scroll away, not
removed: an event at 5 AM must never become invisible because of a display
preference. Everything else in the views keeps measuring from midnight.
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
    """Pixels per hour so the chosen hours fill the window: never below
    ``min_h`` (then it scrolls), never above ``max_h``."""
    return max(min_h, min(max_h, viewport_h // max(1, last - first)))


def label(hour: int) -> str:
    """0 → "12 AM", 13 → "1 PM", 24 → "12 AM (midnight)"."""
    if hour == 24:
        return "12 AM (midnight)"
    h = hour % 12 or 12
    return f"{h} {'AM' if hour < 12 else 'PM'}"
