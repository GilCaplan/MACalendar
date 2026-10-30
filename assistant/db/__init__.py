"""SQLite-backed local storage: the user's calendar.db.

One file, one `CalendarDB`, split by area (2026-10-30, Gil: "make sure it's
cleaner and better"). Each area's code lives in its own module and
`CalendarDB` is all of them together, so every caller still writes
`get_db().create_event(...)` and nothing outside this package changed:

    schema.py      every table, migration and index, in one place
    base.py        opening the file: test guard, connection, migrations
    events.py      events, repeating series, reminders
    links.py       a to-do and an event linked as one thing (Q50, Q61)
    todos.py       to-dos, tags, subtasks, calendar -> to-do sync
    timers.py      timers, sessions, counters, presses, payouts
    coursework.py  courses and assignments
    workout.py     exercises, templates, plans, sessions
    sources.py     connected calendars and sync bookkeeping
    series.py / observance.py / colours.py / common.py   shared helpers
    verify.py      `python -m assistant.db.verify`: check a real file, on a copy

Only this package opens calendar.db: anything else that needs a query asks
for a CalendarDB method in its area. test_db_is_the_only_door holds that,
listing the few modules that open a database of their own and why.

The file on disk is unchanged by the split: same tables, same columns.
`tests/unit/test_db_legacy_file.py` opens a file written by the single-file
version and requires every row back, value for value.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

# Repeating events skip Shabbat and yom tov. The rest of this project is
# already observance-aware — the training planner will not put a run on
# Shabbat — so a nightly prayer series that lands on one was inconsistent
# rather than merely unhelpful.
RECURRENCE_SKIPS_OBSERVANCE = True

from assistant.db.base import StoreBase
from assistant.db.colours import _AUTO_COLORS, _neighbour_colors, auto_category_and_color  # noqa: F401
from assistant.db.common import (  # noqa: F401
    _OWN_WRITES,
    DB_PATH,
    _memory_feedback,
    _note_own_write,
    _utcnow_iso,
    own_write_mtime,
)
from assistant.db.coursework import CourseworkMixin
from assistant.db.events import EventsMixin
from assistant.db.links import LinksMixin
from assistant.db.observance import _MEAL_WORDS, _is_meal, _skip_for_observance, _skip_user_day  # noqa: F401

# Every name the single-file module had stays importable from here.
from assistant.db.schema import (  # noqa: F401
    _CALENDAR_SOURCE_MIGRATIONS,
    _COUNTER_PRESS_MIGRATIONS,
    _CREATE_ASSIGNMENTS_TABLE,
    _CREATE_CALENDAR_SOURCES_TABLE,
    _CREATE_COUNTER_PAYOUTS_TABLE,
    _CREATE_COUNTER_PRESSES_TABLE,
    _CREATE_COUNTERS_TABLE,
    _CREATE_COURSES_TABLE,
    _CREATE_INDEXES,
    _CREATE_REMINDER_LOG_TABLE,
    _CREATE_SUBTASKS_TABLE,
    _CREATE_SYNC_DELETES_TABLE,
    _CREATE_TABLE,
    _CREATE_TAGS_TABLE,
    _CREATE_TIMER_SESSIONS_TABLE,
    _CREATE_TIMERS_TABLE,
    _CREATE_TODOS_TABLE,
    _CREATE_WORKOUT_EXERCISES_TABLE,
    _CREATE_WORKOUT_PLAN_ITEMS_TABLE,
    _CREATE_WORKOUT_PLANS_TABLE,
    _CREATE_WORKOUT_SESSIONS_TABLE,
    _CREATE_WORKOUT_SET_LOGS_TABLE,
    _CREATE_WORKOUT_TEMPLATE_BLOCKS_TABLE,
    _CREATE_WORKOUT_TEMPLATE_SETS_TABLE,
    _CREATE_WORKOUT_TEMPLATES_TABLE,
    _IDEMPOTENT_TABLES,
    _LEGACY_LINK_SOURCE,
    _MIGRATIONS,
    _TIMER_MIGRATIONS,
    _TODO_MIGRATIONS,
    _WORKOUT_MIGRATIONS,
    DEFAULT_TODO_TAGS,
    SCHEMA_VERSION,  # noqa: F401
    TWO_WAY_SOURCES,
)
from assistant.db.series import _next_date, _SeriesSeed  # noqa: F401
from assistant.db.sources import (
    SourcesMixin,
    _source_for,  # noqa: F401
)
from assistant.db.timers import (
    TimersMixin,
    counter_press_amount,  # noqa: F401
)
from assistant.db.todos import TodosMixin
from assistant.db.workout import WorkoutMixin


class CalendarDB(EventsMixin, LinksMixin, TodosMixin, TimersMixin, CourseworkMixin,
                 WorkoutMixin, SourcesMixin, StoreBase):
    """Thread-safe SQLite store for the user's calendar.db.

    The areas are mixins over one connection and one file (see the module
    docstring). They share no state beyond `self.path`, `self.owner_id` and
    `self._conn()`, all set up by `StoreBase`.
    """

# ---------------------------------------------------------------------------
# Module-level singleton — avoids re-running migrations on every action call
# ---------------------------------------------------------------------------

_db_instance: CalendarDB | None = None


#: One CalendarDB per user's file, once there are users (assistant/users).
_user_dbs: dict[str, CalendarDB] = {}
_user_dbs_lock = threading.Lock()


def get_db() -> CalendarDB:
    """The calendar of whoever the assistant is working for right now.

    Nobody bound (before the users migration, and in every test that does not
    bind one) → the shared instance, exactly as always. A user bound → that
    user's own file under `users/<uid>/`, one instance per file."""
    global _db_instance
    from assistant import users
    uid = users.current()
    if uid is None:
        if _db_instance is None:
            _db_instance = CalendarDB()
        return _db_instance
    from assistant.users import paths as _paths
    path = _paths.resolve(os.environ.get("MACALENDAR_DB") or DB_PATH, uid)
    with _user_dbs_lock:
        db = _user_dbs.get(path)
        if db is None:
            db = _user_dbs[path] = CalendarDB(path)
            db.owner_id = uid
        return db
