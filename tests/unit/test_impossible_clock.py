"""An impossible clock never reaches the database (Gil, 2026-09-22: "invalid
clock should be handled by validate_decompose").

`start_time = '30:00'` was written on two live rows on 2026-09-09 and seen
again on 2026-09-22 ("…at 9am and 2.30pm" torn into "9am" and "30pm"). Two
gates now: the resolver never returns a reading that is not on the clock, and
decompose_validate refuses any that still reaches an intent, since it is the
stage that writes those values past the intent's own validator.
"""
from __future__ import annotations

import datetime
import sqlite3
from types import SimpleNamespace

from assistant.engine.decompose_validate import object_rules as OR
from assistant.engine.decompose_validate import resolve as R
from assistant.engine.state import EngineState

ANCHOR = datetime.datetime(2026, 8, 26, 11, 1)


def test_the_resolver_returns_nothing_for_an_hour_that_does_not_exist():
    assert R.resolve_clock("30pm") is None
    assert R.resolve_clock("at 30pm") is None
    assert R.resolve_clock("25:00") is None
    assert R.resolve("30pm", ANCHOR, "x", action="x")["start_time"] is None
    assert R._bare_hour(30, 0, "") is None
    assert R.resolve_clock("2.30pm") == "14:30"       # the real one still reads


def test_the_validate_rule_drops_an_impossible_clock_and_records_it():
    st = EngineState(raw_text="x", source="test")
    intent = SimpleNamespace(date="2026-09-08", start_time="30:00", end_time="31:00")
    OR._rule_impossible_clock(st, intent)
    assert intent.start_time is None and intent.end_time is None
    assert [f.rule for f in st.fixes] == ["impossible_clock", "impossible_clock"]


def test_the_validate_rule_leaves_a_real_clock_alone():
    st = EngineState(raw_text="x", source="test")
    intent = SimpleNamespace(date="2026-09-08", start_time="14:30", end_time="15:30:00")
    OR._rule_impossible_clock(st, intent)
    assert (intent.start_time, intent.end_time) == ("14:30", "15:30:00")
    assert not st.fixes


def test_old_running_and_gym_rows_become_fitness_on_open(tmp_path, monkeypatch):
    """Gil ruled Running and Gym fold into Fitness on 2026-09-10; 38 rows
    written before that still carried the old names on 2026-09-22."""
    from assistant import db as _db
    path = tmp_path / "calendar.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, title TEXT, date TEXT, start_time TEXT, end_time TEXT, category TEXT NOT NULL DEFAULT '')")
    con.executemany("INSERT INTO events (title, date, start_time, end_time, category) VALUES (?,?,?,?,?)",
                    [("run", "2026-09-01", "07:00", "08:00", "Running"), ("gym", "2026-09-02", "18:00", "19:00", "Gym"),
                     ("lunch", "2026-09-03", "13:00", "14:00", "Meal")])
    con.commit(); con.close()
    calendar = _db.CalendarDB(str(path))
    con = sqlite3.connect(path)
    got = dict(con.execute("SELECT title, category FROM events").fetchall())
    assert got == {"run": "Fitness", "gym": "Fitness", "lunch": "Meal"}
