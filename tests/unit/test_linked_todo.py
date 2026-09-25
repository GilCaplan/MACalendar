"""A call to a ROLE is an event AND a linked to-do (DEVQA Q50).

Gil, 2026-09-25: calling the plumber or the bank is an event like calling a
person ("Two also same thing"), and then: *"can you also make it a to-do in
addition, in parallel, and it should be linked."* A call to a person stays one
event (Q47); a written message stays one to-do.
"""
from __future__ import annotations

import datetime as dt

import pytest

from assistant.intent.encounter import is_encounter, is_role_call


@pytest.mark.parametrize("said,encounter,role", [
    ("call the plumber tomorrow", True, True),
    ("remind me to call the bank", True, True),
    ("phone the landlord at 3pm", True, True),
    ("call my accountant", True, True),
    ("call back the dentist", True, True),
    # a person: an event (Q47), and no companion to-do
    ("call my mom", True, False),
    ("Call Mom", True, False),
    ("call Dana tomorrow", True, False),
    # not a call to anyone
    ("call off the meeting", False, False),
    ("call it a day", False, False),
    ("call the meeting to order", False, False),
    # written, or put on the list by name: a to-do (Q47)
    ("email the plumber", False, False),
    ("text the landlord", False, False),
    ("add call the plumber to my list", False, False),
])
def test_the_rule(said, encounter, role):
    assert (is_encounter(said), is_role_call(said)) == (encounter, role)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    return _db.get_db()


def _create(title, date=None, recurrence=None):
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.calendar.intent import CalendarIntent
    date = date or (dt.date.today() + dt.timedelta(days=1)).isoformat()
    intent = CalendarIntent(title=title, date=date, start_time="09:00",
                            end_time="10:00", recurrence=recurrence)
    return CreateEventAction().execute(intent, None)


def _only_event(db, title):
    with db._conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE title = ? ORDER BY id", (title,))]
    assert len(rows) >= 1
    return rows[0]


def test_a_role_call_files_the_pair_and_says_so(db):
    reply = _create("call the plumber")
    ev = _only_event(db, "call the plumber")
    todos = db.linked_todos(ev["id"])
    assert [(t["title"], t["due_date"], t["list"]) for t in todos] == [
        ("call the plumber", ev["date"], "general")]
    assert "to-do" in reply


def test_a_call_today_lands_on_today(db):
    _create("call the bank", date=dt.date.today().isoformat())
    ev = _only_event(db, "call the bank")
    assert db.linked_todos(ev["id"])[0]["list"] == "today"


@pytest.mark.parametrize("title", ["call Mom", "dentist", "email the plumber"])
def test_anything_else_is_one_event(db, title):
    reply = _create(title)
    assert db.linked_todos(_only_event(db, title)["id"]) == []
    assert "to-do" not in reply


def test_a_series_gets_no_companion(db):
    """One to-do cannot stand for every instance of a weekly call."""
    _create("call the bank", recurrence="weekly")
    ev = _only_event(db, "call the bank")
    assert db.linked_todos(ev["id"]) == []


def test_moving_or_renaming_the_event_carries_to_the_todo(db):
    _create("call the plumber")
    ev = _only_event(db, "call the plumber")
    later = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    db.update_event(ev["id"], date=later, title="call the electrician")
    (todo,) = db.linked_todos(ev["id"])
    assert (todo["title"], todo["due_date"]) == ("call the electrician", later)


def test_renaming_the_todo_renames_the_event(db):
    _create("call the plumber")
    ev = _only_event(db, "call the plumber")
    (todo,) = db.linked_todos(ev["id"])
    db.update_todo(todo["id"], title="call the landlord")
    assert db.get_event(ev["id"])["title"] == "call the landlord"


def test_deleting_the_event_takes_the_todo_with_it(db):
    _create("call the plumber")
    ev = _only_event(db, "call the plumber")
    (todo,) = db.linked_todos(ev["id"])
    db.delete_event(ev["id"])
    assert db.get_todo(todo["id"]) is None


def test_ticking_or_deleting_the_todo_leaves_the_event(db):
    _create("call the plumber")
    _create("call the bank")
    plumber, bank = _only_event(db, "call the plumber"), _only_event(db, "call the bank")
    db.toggle_todo_complete(db.linked_todos(plumber["id"])[0]["id"])
    db.delete_todo(db.linked_todos(bank["id"])[0]["id"])
    assert db.get_event(plumber["id"]) and db.get_event(bank["id"])


def test_the_calendar_sync_never_touches_a_linked_todo(db):
    """Both features use `source_event_id`; each keeps to its own `source`."""
    _create("call the plumber", date=dt.date.today().isoformat())
    ev = _only_event(db, "call the plumber")
    db.sync_calendar_to_todos("today")
    (todo,) = db.linked_todos(ev["id"])
    db.delete_todos_by_source("calendar_sync")
    assert db.get_todo(todo["id"]) is not None


def test_the_phone_is_told_which_todos_are_linked(db):
    """iOS draws the link mark from `source` + `source_event_id` on GET /todos."""
    from assistant.api.server import create_app
    _create("call the plumber", date=dt.date.today().isoformat())
    ev = _only_event(db, "call the plumber")
    body = create_app().test_client().get("/todos?list=today").get_json()
    rows = body if isinstance(body, list) else body.get("todos", [])
    (row,) = [r for r in rows if r["title"] == "call the plumber"]
    assert (row["source"], row["source_event_id"]) == ("linked_event", ev["id"])
