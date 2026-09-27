"""The observance gate — one implementation, now a FLAG rather than a refusal.

Gil, 2026-09-08: it stops refusing and becomes a note carried to commit. The
LOGIC is unchanged and deliberately so: this is the ONE-OFF rule (an event the
engine creates inside Shabbat or yom tov must be leyning, a meal or davening;
on a fast a meal must not be booked before the fast ends), which is NOT the
same as `db._skip_for_observance`, the series rule that excepts only meals.
Swapping one for the other would flag a leyning event that is allowed, so the
verified implementation moves across intact and only its CONSUMER changes.

RETIRED FROM `validate.py` (Gil, 2026-09-08). That module was the ported v1
implementation of this stage; `resolve.py` + `checks.py` replaced everything it
did with VALUES, and what remained were rules that were never value resolution.
Leaving them in a file called `validate.py` made the file's name a lie, so they
live where they belong. The original is in `retired/decompose-validate-v1/`.
"""
from __future__ import annotations

import datetime as _dt
import re

from assistant.engine.state import EngineState

_LEYNING_RE = re.compile(
    r"\b(leyn|leyning|laining|kriah|kriat|torah reading|parsha|megillah?|shiur)\b", re.I)


_DAVENING_RE = re.compile(
    r"\b(daven|davening|shacharit|mincha|maariv|arvit|musaf|selichot|tefill?ah|"
    r"prayer|shul|synagogue|minyan)\b", re.I)


def _observance_verdict(intent, cfg) -> "str | None":
    """Refusal reason if this AI-created one-off event may not be booked.

    On Shabbat / yom tov (sundown-bounded, same windows the recurring-series
    skip uses) only leyning / meals / davening belong; on a fast day a meal is
    the one thing that must not be booked before the fast ends, and Yom Kippur
    is both — the fast wins. Manual edits through the GUI or endpoints are
    never gated; this runs only on what the engine itself creates.

    None (allowed) on ANY doubt or computation failure — refusing a legitimate
    event is worse than admitting one, and `db._skip_for_observance` already
    keeps series honest.
    """
    try:
        from assistant.db import _is_meal
        from assistant.observance import (
            ALLOW, candle_lighting, day_override, holy_kept_off, is_enabled,
            is_fast_day, is_shabbat, tzeit, whole_day_kept_off,
        )

        if not is_enabled():
            return None                      # gating switched off in settings
        if getattr(intent, "recurrence", None):
            return None                      # series: db-level skipping owns it
        d = getattr(intent, "date", None)
        if not d:
            return None
        date = _dt.date.fromisoformat(str(d))
        title = getattr(intent, "title", "") or ""
        desc = getattr(intent, "description", "") or ""
        try:
            when = _dt.time.fromisoformat(getattr(intent, "start_time", "") or "")
        except ValueError:
            when = None

        # A day the user switched "keep engine events off" on by hand (DEVQA
        # Q60) — chol hamoed, a weekday: the whole CALENDAR day, 00:00-24:00,
        # not sundown-bounded, and no meal / leyning / davening exemption.
        # The user named the date; nothing halachic starts the evening before.
        if whole_day_kept_off(date):
            return (f"you set {date:%a %-d %b} to keep engine events off")

        meal = _is_meal(title, desc)
        davening = bool(_DAVENING_RE.search(title) or _DAVENING_RE.search(desc))
        leyning = bool(_LEYNING_RE.search(title) or _LEYNING_RE.search(desc))
        # a day the user ALLOWED switches the whole rule off, the fast check
        # included (as Q59's exception days did)
        fast = is_fast_day(date) and day_override(date) != ALLOW

        # A meal on a fast day, before the fast is out, must not be booked —
        # whatever kind of day it otherwise is.
        if meal and fast:
            ends = tzeit(date)
            if when is None or ends is None or when < ends.replace(microsecond=0):
                name = "a fast day"
                out = f" — it ends at {ends:%H:%M}" if ends else ""
                return (f"that's a meal on {name} ({date:%A, %b %-d}){out}")

        # Shabbat / yom tov with the per-day switch on, its default.
        holy = holy_kept_off(date)
        eve_of_holy = holy_kept_off(date + _dt.timedelta(days=1))
        inside = False
        if holy:
            ends = tzeit(date)
            inside = when is None or ends is None or when < ends.replace(microsecond=0)
        elif eve_of_holy and when is not None:
            starts = candle_lighting(date)
            inside = starts is not None and when >= starts.replace(microsecond=0)
        if not inside:
            return None
        if leyning or davening or (meal and not fast):
            return None
        day = "Shabbat" if (is_shabbat(date) or (eve_of_holy and is_shabbat(date + _dt.timedelta(days=1)))) \
            else "yom tov"
        ends = tzeit(date if holy else date)
        after = f" — after {ends:%H:%M} works" if holy and ends else ""
        return f"that lands on {day} ({date:%A, %b %-d}){after}"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The two passes
# ---------------------------------------------------------------------------

