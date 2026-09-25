"""A call to a ROLE is an event AND a linked to-do (DEVQA Q50), and any
to-do and event can be linked as one thing (Gil, 2026-09-25).

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
    """The sync mirrors events through `source_event_id`; the link is its own
    column, so clearing the mirrors cannot take a linked to-do with them."""
    _create("call the plumber", date=dt.date.today().isoformat())
    ev = _only_event(db, "call the plumber")
    db.sync_calendar_to_todos("today")
    (todo,) = db.linked_todos(ev["id"])
    db.delete_todos_by_source("calendar_sync")
    assert db.get_todo(todo["id"]) is not None


def test_the_phone_is_told_which_todos_are_linked(db):
    """iOS draws the link mark from `linked_event_id` on GET /todos."""
    from assistant.api.server import create_app
    _create("call the plumber", date=dt.date.today().isoformat())
    ev = _only_event(db, "call the plumber")
    body = create_app().test_client().get("/todos?list=today").get_json()
    rows = body if isinstance(body, list) else body.get("todos", [])
    (row,) = [r for r in rows if r["title"] == "call the plumber"]
    assert row["linked_event_id"] == ev["id"]


# ---------------------------------------------------------------------------
# Linking any pair, from either side (Gil, 2026-09-25: "add a linking feature
# between todo and events, they can be linked and the same thing")
# ---------------------------------------------------------------------------

def _event(db, title="dentist", days=2, start="14:00"):
    from assistant.actions.calendar.intent import CalendarIntent
    return db.create_event(CalendarIntent(
        title=title, date=(dt.date.today() + dt.timedelta(days=days)).isoformat(),
        start_time=start, end_time="15:00"))


def test_linking_an_existing_pair_makes_them_one_thing(db):
    ev = _event(db)
    todo = db.create_todo("book the dentist")
    assert db.link_todo(todo, ev)
    t = db.get_todo(todo)
    assert (t["linked_event_id"], t["due_date"]) == (ev, db.get_event(ev)["date"])
    db.update_todo(todo, title="dentist checkup")
    assert db.get_event(ev)["title"] == "dentist checkup"


def test_re_dating_the_todo_moves_the_event_and_keeps_its_clock(db):
    ev = _event(db, start="14:00")
    todo = db.create_todo("dentist")
    db.link_todo(todo, ev)
    later = (dt.date.today() + dt.timedelta(days=9)).isoformat()
    db.update_todo(todo, due_date=later)
    got = db.get_event(ev)
    assert (got["date"], got["start_time"]) == (later, "14:00")
    db.update_todo(todo, due_date="")          # no deadline is not a move
    assert db.get_event(ev)["date"] == later


def test_an_event_has_one_todo(db):
    ev = _event(db)
    first, second = db.create_todo("a"), db.create_todo("b")
    db.link_todo(first, ev)
    db.link_todo(second, ev)
    assert db.get_todo(first)["linked_event_id"] is None      # released, kept
    assert db.linked_todo(ev)["id"] == second


def test_unlinking_leaves_two_independent_items(db):
    ev = _event(db)
    todo = db.create_todo("dentist")
    db.link_todo(todo, ev)
    db.unlink_todo(todo)
    db.update_todo(todo, title="something else")
    assert db.get_event(ev)["title"] == "dentist"
    db.delete_event(ev)
    assert db.get_todo(todo) is not None


def test_putting_a_todo_on_the_calendar(db):
    day = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    todo = db.create_todo("renew the passport", due_date=day)
    ev = db.create_linked_event(todo)
    got = db.get_event(ev)
    assert (got["title"], got["date"], got["start_time"], got["end_time"]) == \
        ("renew the passport", day, "09:00", "10:00")
    assert db.create_linked_event(todo) == ev                  # not a second one
    assert db.create_linked_todo(ev) == todo


def test_an_event_that_vanishes_any_other_way_only_unlinks(db):
    """A sync or a series regeneration deletes rows the user never asked to
    delete; the to-do survives them, unlinked."""
    ev = _event(db)
    todo = db.create_todo("dentist")
    db.link_todo(todo, ev)
    with db._conn() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (ev,))
    assert db.get_todo(todo)["linked_event_id"] is None


def test_deleting_a_series_takes_its_linked_todos(db):
    from assistant.actions.calendar.intent import CalendarIntent
    root = db.create_event(CalendarIntent(
        title="gym", date=dt.date.today().isoformat(), start_time="07:00",
        end_time="08:00", recurrence="weekly"))
    sid = db.get_event(root).get("series_id") or root
    with db._conn() as conn:
        later = conn.execute("SELECT id FROM events WHERE series_id = ? AND id != ? "
                             "ORDER BY date LIMIT 1", (sid, root)).fetchone()[0]
    todo = db.create_todo("gym")
    db.link_todo(todo, later)
    db.delete_series(sid)
    assert db.get_todo(todo) is None


def test_this_mornings_links_are_carried_over(tmp_path):
    """Q50's first rows stored the link as source='linked_event'."""
    import sqlite3
    from assistant.db import CalendarDB
    path = str(tmp_path / "old.db")
    db = CalendarDB(path)
    ev = _event(db)
    todo = db.create_todo("call the plumber")
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE todos SET source = 'linked_event', source_event_id = ?, "
                     "linked_event_id = NULL WHERE id = ?", (ev, todo))
    t = CalendarDB(path).get_todo(todo)
    assert (t["linked_event_id"], t["source"], t["source_event_id"]) == (ev, "manual", None)


def test_the_routes(db):
    from assistant.api.server import create_app
    c = create_app().test_client()
    ev = _event(db)
    todo = db.create_todo("dentist")
    assert c.get(f"/events/{ev}/todo").get_json() == {"todo": None}
    r = c.put(f"/todos/{todo}/link", json={"event_id": ev})
    assert r.status_code == 200 and r.get_json()["linked_event_id"] == ev
    assert c.get(f"/events/{ev}/todo").get_json()["todo"]["id"] == todo
    assert c.delete(f"/todos/{todo}/link").get_json()["linked_event_id"] is None
    assert c.put(f"/todos/{todo}/link", json={}).status_code == 400
    assert c.put(f"/todos/{todo}/link", json={"event_id": 99999}).status_code == 404
    body = c.post(f"/todos/{todo}/event", json={"start_time": "16:30"}).get_json()
    assert body["event"]["start_time"] == "16:30" and body["todo"]["linked_event_id"] == body["event"]["id"]
    ev2 = _event(db, "haircut")
    got = c.post(f"/events/{ev2}/todo").get_json()["todo"]
    assert (got["title"], got["linked_event_id"]) == ("haircut", ev2)
