"""Expanding a repeating event into dated instances."""

from __future__ import annotations

import calendar
import datetime

from assistant.common.wordlists import WEEKDAY_INDEX as _WEEKDAY_NUM


class _SeriesSeed:
    """The fields `_create_series_instances` reads, taken from a ROW or a
    dialog/API dict instead of a parsed `CalendarIntent`.

    The three manual paths into a series — `create_event_from_dict` (the Mac
    dialog, `POST /events`), `promote_to_series` and `update_series` — each
    used to declare their own ad-hoc `_FakeIntent`, and each was missing
    something the voice path carried: the dialog's copy had `attendees = []`
    (so only the FIRST instance of a manually created series had its guests),
    none had `recur_days` (so regenerating a "tuesday and thursday" series
    after an end-date change collapsed it to one weekday), and none had
    `reminder_minutes`. One seed, built the same way everywhere.
    """

    def __init__(self, row: dict, date: str | None = None):
        self.title = row.get("title", "")
        self.date = date or row["date"]
        self.start_time = row.get("start_time", "")
        self.end_time = row.get("end_time", "")
        att = row.get("attendees") or ""
        self.attendees = (list(att) if isinstance(att, (list, tuple))
                          else [a.strip() for a in str(att).split(",") if a.strip()])
        self.location = row.get("location", "") or ""
        self.description = row.get("description", "") or ""
        days = row.get("recur_days") or ""
        if isinstance(days, str):
            days = [d.strip() for d in days.split(",")]
        self.recur_days = [d for d in days if d in _WEEKDAY_NUM]
        self.reminder_minutes = row.get("reminder_minutes")

def _next_date(d: datetime.date, recurrence: str, anchor_day: int | None = None,
               recur_days: list[str] | None = None) -> datetime.date:
    """Advance d by one recurrence period.

    `recur_days` makes a WEEKLY series able to name several weekdays — "gym
    every tuesday and thursday" (Gil, 2026-09-08). Without it, a multi-weekday
    ask had only bad answers: keep one day and silently lose the other, or make
    two separate series for one spoken sentence. With it, the series steps to
    the next NAMED day instead of always +7.

    For monthly recurrence, `anchor_day` (the original series day-of-month, e.g.
    31 for a "31st of every month" series) is used instead of `d.day` so a
    short-month clamp doesn't permanently stick — Jan 31 -> Feb 28 -> Mar 31,
    not Mar 28. Without an anchor, falls back to `d.day` (chains from the
    previous instance), which is what causes the drift.
    """
    if recurrence == "daily":
        return d + datetime.timedelta(days=1)
    if recurrence == "weekly":
        wanted = sorted({_WEEKDAY_NUM[x] for x in (recur_days or [])
                         if x in _WEEKDAY_NUM})
        if len(wanted) > 1:
            # The soonest named weekday strictly after d, wrapping the week.
            ahead = [(n - d.weekday()) % 7 or 7 for n in wanted]
            return d + datetime.timedelta(days=min(ahead))
        return d + datetime.timedelta(weeks=1)
    if recurrence == "monthly":
        month = d.month + 1
        year = d.year
        if month > 12:
            month = 1
            year += 1
        day = anchor_day if anchor_day is not None else d.day
        # Clamp day to the last valid day of the target month
        max_day = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, min(day, max_day))
    if recurrence == "yearly":
        # A FOURTH CADENCE (Gil, 2026-09-08). Feb 29 is the whole difficulty:
        # stepping it a year lands on a date that does not exist, so it clamps to
        # the 28th — and `anchor_day` is not enough to undo that, because the
        # month matters too. Chaining from the previous instance would turn one
        # leap-day series into a permanent 28th, so the ANCHOR month/day is what
        # each step is computed from where it is known.
        day = anchor_day if anchor_day is not None else d.day
        year, month = d.year + 1, d.month
        max_day = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, min(day, max_day))
    raise ValueError(f"Unknown recurrence: {recurrence!r}")
