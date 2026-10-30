"""Build `legacy_calendar.db`: a calendar file written by the CalendarDB that
predates the per-area split (assistant/db.py as of main 2026-10-30, d2bc2ae1).

`test_db_legacy_file.py` opens it with today's code and reads every row back.
That is the check that a data file written before the split still opens and
reads unchanged after it. Re-run this only to add rows a newer table needs,
and only with the OLD code checked out (`git worktree add /tmp/old d2bc2ae1`).

All the content is invented: this repo is public.

    python tests/fixtures/db/build_legacy_db.py
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "legacy_calendar.db"
DUMP = HERE / "legacy_calendar.rows.json"


def build() -> None:
    from assistant.db import CalendarDB

    if OUT.exists():
        OUT.unlink()
    db = CalendarDB(str(OUT))
    today = datetime.date(2026, 10, 30)
    ev = db.create_event_from_dict({
        "title": "Dentist", "date": today.isoformat(), "start_time": "10:00",
        "end_time": "11:00", "location": "Main St", "description": "check-up"})
    db.create_event_from_dict({
        "title": "Run", "date": today.isoformat(), "start_time": "07:00",
        "end_time": "07:45", "recurrence": "weekly"})
    db.log_reminder(ev, f"{today.isoformat()}T09:50", "shown")
    tag = db.create_tag("errands", "#ff8800")
    todo = db.create_todo("Buy milk", list_name="today", priority="high",
                          due_date=today.isoformat(), notes="2 litres",
                          tags=["errands"], client_token="tok-1")
    db.create_subtask(todo, "check the fridge")
    db.create_linked_todo(ev)
    t = db.create_timer("Consulting", hourly_rate=100.0)
    db.create_timer_session(t, "kickoff", start_time=f"{today.isoformat()}T09:00:00")
    c = db.create_counter("Bus rides", price_per_unit=7.5)
    db.create_counter_press(c, 1, "to work", pressed_at=f"{today.isoformat()}T08:00:00")
    db.create_counter_press(c, 1, "home", pressed_at=f"{today.isoformat()}T18:00:00", amount=5.0)
    db.create_counter_payout(c, f"{today.isoformat()}T00:00:00", f"{today.isoformat()}T20:00:00",
                             2, 12.5, "ILS", "October")
    course = db.create_course("101", "Intro to Things", "#3366cc", ["Pat"])
    db.create_assignment(course, "Problem set 1", today.isoformat())
    db.create_workout_exercise("ex-squat", "Squat")
    db.create_calendar_source("ics", "Holidays", "https://example.invalid/h.ics")
    del tag

    # Any table the public calls above did not reach gets one row written
    # straight from its own columns, so every table in the file holds data.
    with sqlite3.connect(OUT) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            if conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
                continue
            cols = list(conn.execute(f"PRAGMA table_info({table})"))
            names, values = [], []
            for _cid, name, ctype, _notnull, default, pk in cols:
                if pk and "INT" in (ctype or "").upper():
                    continue
                names.append(name)
                t = (ctype or "").upper()
                values.append(1 if "INT" in t else 1.5 if ("REAL" in t or "FLOA" in t)
                              else f"{table}-{name}")
            conn.execute(f"INSERT INTO {table} ({', '.join(names)}) "
                         f"VALUES ({', '.join('?' * len(values))})", values)

    rows = dump(OUT)
    DUMP.write_text(json.dumps(rows, indent=1, sort_keys=True, default=str) + "\n")
    print(f"{OUT.name}: {len(rows)} tables, "
          f"{sum(len(v) for v in rows.values())} rows")


def dump(path) -> dict:
    """Every row of every table, as plain data, in primary-key order."""
    out = {}
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = sorted(r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        for table in tables:
            out[table] = [dict(r) for r in conn.execute(
                f"SELECT * FROM {table} ORDER BY rowid")]
    return out


if __name__ == "__main__":
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    build()
