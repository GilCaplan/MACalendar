"""Which days a repeating event skips (Shabbat, yom tov, the user's kept-off days).

The switch itself, `RECURRENCE_SKIPS_OBSERVANCE`, lives on `assistant.db` and is
read there at call time, so `monkeypatch.setattr(assistant.db, ...)` still works."""

from __future__ import annotations

import datetime


def _pkg():
    import assistant.db as pkg
    return pkg


def _skip_for_observance(date: datetime.date, start_time: str = "",
                         title: str = "", description: str = "",
                         user_days: bool = True) -> bool:
    """Should a repeating event skip this slot?

    Every day's "keep engine events off this day" switch decides (DEVQA Q60):
    Shabbat and yom tov are on by default, chol hamoed and ordinary days off,
    and the user can flip any date either way. `user_days=False` asks the
    Shabbat / yom tov question alone — the series loop's anchor check, so a
    series that merely STARTS on a day the user switched on still skips
    Shabbat after it.

    Shabbat and yom tov are bounded by candle lighting and tzeit hakochavim at
    the configured location, not by midnight. That matters: at Israeli
    latitudes candle lighting swings well over two hours between September and
    December, so a 19:00 event on a Friday is outside Shabbat in one and well
    inside it in the other. Using the date alone would skip a whole Friday in
    summer and admit a Friday evening in winter, both wrong.

    Meals are the exception, because they are what the day is for — kiddush and
    seudah belong on Shabbat. Unless it is a fast, where a meal is the one thing
    that must not be booked. Yom Kippur is both, and the fast check wins.

    The evening after a fast needs no special case: a minor fast ends at tzeit
    and is not yom tov, so nothing about that evening is blocked.

    Best effort throughout. If observance cannot be computed — pyluach absent,
    astral without solar data, an unparseable time — nothing is skipped. A
    recurring event quietly losing days is worse than one landing where it
    should not.
    """
    if not _pkg().RECURRENCE_SKIPS_OBSERVANCE:
        return False
    try:
        from assistant.observance import (
            candle_lighting,
            holy_kept_off,
            is_enabled,
            is_fast_day,
            tzeit,
            whole_day_kept_off,
        )

        if not is_enabled():
            return False                    # gating switched off in settings
        if user_days and whole_day_kept_off(date):
            # A day the user switched on by hand (DEVQA Q60) — chol hamoed, a
            # weekday: the whole calendar day, meals included. They chose it.
            return True

        # Shabbat / yom tov with the per-day switch on (its default). A day
        # the user ALLOWED is not holy here, and its eve is not an eve.
        holy = holy_kept_off(date)
        tomorrow = date + datetime.timedelta(days=1)
        eve_of_holy = holy_kept_off(tomorrow)
        if not (holy or eve_of_holy):
            return False

        if _is_meal(title, description) and not is_fast_day(date):
            return False

        try:
            when = datetime.time.fromisoformat(start_time) if start_time else None
        except ValueError:
            when = None
        if when is None:
            # No usable time: fall back to the date, which is the safe
            # direction — a recurring event with no time on Shabbat is not
            # something to insert on a guess.
            return holy

        if holy:
            ends = tzeit(date)
            if ends is not None and when >= ends.replace(microsecond=0):
                return False            # after tzeit: the day is over
            return True
        # Erev: blocked only once candles are lit.
        starts = candle_lighting(date)
        return starts is not None and when >= starts.replace(microsecond=0)
    except Exception:                       # pragma: no cover - defensive
        return False

def _skip_user_day(date: datetime.date) -> bool:
    """A non-holy day the user switched "keep engine events off" on (Q60)."""
    if not _pkg().RECURRENCE_SKIPS_OBSERVANCE:
        return False
    try:
        from assistant.observance import is_enabled, whole_day_kept_off
        return is_enabled() and whole_day_kept_off(date)
    except Exception:                       # pragma: no cover - defensive
        return False

# Words that mean food is the event. Deliberately NOT the category
# classifier: that one colours by social context, so it files "lunch" and
# "dinner" under Social and "kiddush" and "seudah" under Prayer — sensible for
# a calendar's palette, useless for "may this happen on Shabbat".
_MEAL_WORDS = (
    "meal", "lunch", "dinner", "breakfast", "brunch", "supper", "feast",
    "seudah", "seuda", "seudat", "kiddush", "melave malka", "melaveh malka",
    "shalosh seudos", "shalosh seudot", "seudah shlishit", "se'udah",
    "eat", "eating", "food", "bbq", "barbecue", "picnic",
)

def _is_meal(title: str, description: str = "") -> bool:
    """Is food the point of this event?

    The one thing that belongs on Shabbat and yom tov — kiddush, the seudot,
    Friday night dinner — and the one thing that must not be booked on a fast.

    Asks the classifier first, so the "Shabbat Meal" category and this rule
    cannot drift apart: an event coloured as a Shabbat meal is one that may be
    booked on Shabbat, and the two answers come from the same word list. The
    literal check below still catches an ordinary weekday "lunch", which the
    classifier files as Social because it is colouring by social context.
    """
    text = f"{title or ''} {description or ''}".lower()
    try:
        from assistant.actions.calendar.categories import classify
        if classify(title or "", "", "", description or "") in ("Shabbat Meal", "Meal"):
            return True
    except Exception:                       # pragma: no cover - defensive
        pass
    return any(w in text for w in _MEAL_WORDS)
