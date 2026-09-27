"""A to-do that REPEATS is an event series with ONE rolling linked to-do (DEVQA Q61).

Gil, 2026-09-27: *"repeating task always becomes an event, we have on the
calendar that it shows up on due date no? that is essentially part of the
linked event-task thoughts how to handle that."* Asked and answered: one to-do
for the next occurrence; ticking it marks that one done and the to-do moves to
the next date. Before this, "pay rent monthly on the 1st" filed ONE to-do and
dropped the repeat without a word.
"""
from __future__ import annotations

import datetime as dt

import pytest

from assistant.engine.segmentation.fastseg.fastseg import tag_path


@pytest.mark.parametrize("action,when,want", [
    ("pay rent", "monthly on the 1st", ("event", "repeating_task")),
    ("remind me to take out the trash", "every tuesday", ("event", "repeating_task")),
    ("water the plants", "every day", ("event", "repeating_task")),
    ("clean the kitchen", "every other day", ("event", "repeating_task")),
    # a one-off to-do stays a to-do
    ("water the plants", "tomorrow", ("task", None)),
    ("pay rent", "", ("task", None)),
])
def test_the_tagger(action, when, want):
    kind, path = tag_path(action, when)
    assert kind == want[0]
    if want[1]:
        assert path == want[1]
    else:
        assert path != "repeating_task"


def test_an_event_or_a_clocked_reminder_gets_no_todo():
    """An event repeats on its own, and a clocked reminder is an event by Q26
    before Q61 is reached: neither is a to-do that asked for a companion."""
    assert tag_path("gym", "every monday at 7am")[1] != "repeating_task"
    assert tag_path("remind me to take my pills", "every day at 8am")[1] != "repeating_task"


@pytest.fixture
def actions(isolated_registry):
    """The suite clears the action registry per test; the front door needs the
    two create actions back (see `test_rule_parser.parser`)."""
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.todo.action import CreateTodoAction
    for cls in (CreateEventAction, CreateTodoAction):
        isolated_registry._actions[cls.action_name] = cls


def _front(text):
    from assistant.intent.rule_parser import RULE_THRESHOLD
    from assistant.engine.fastrule.fastrule import FastRule
    res = FastRule(RULE_THRESHOLD).run(text, "")
    assert res.committed, text
    return res.intents


@pytest.mark.parametrize("said,title,cadence", [
    ("pay rent monthly on the 1st", "pay rent", "monthly"),
    ("remind me to take out the trash every tuesday", "take out the trash", "weekly"),
    # the TO-DO reader's title: the event reader kept "task to renew …"
    ("add a task to renew the car insurance every year on march 3",
     "renew the car insurance", "yearly"),
    # the front door's own router read a to-do here, not the tagger
    ("put a reminder to water the plants every sunday", None, "weekly"),
])
def test_the_front_door_books_the_series_with_its_todo(actions, said, title, cadence):
    [(name, intent)] = _front(said)
    assert name == "create_event" and intent.recurrence == cadence
    assert intent.linked_todo is True
    if title:
        assert intent.title == title


def test_the_front_door_gives_an_event_series_no_todo(actions):
    [(name, intent)] = _front("gym every monday at 7am")
    assert name == "create_event" and intent.recurrence == "weekly"
    assert not intent.linked_todo


def test_the_deep_track_carries_it_on_the_item():
    from assistant.engine.segmentation import run as segment
    from assistant.engine.state import EngineState
    state = segment(EngineState(raw_text="water the plants every day", text="water the plants every day"), None)
    [item] = state.items
    assert item.kind == "event" and item.slots.get("linked_todo") is True


def test_decompose_validate_files_it_only_for_a_series_it_was_asked_for():
    from assistant.actions.calendar.intent import CalendarIntent
    from assistant.engine.decompose_validate.stage import _files_linked_todo
    from assistant.engine.state import Item
    day = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    series = CalendarIntent(title="pay rent", date=day, start_time="09:00",
                            end_time="10:00", recurrence="monthly")
    asked = Item(id="i", kind="event", text="pay rent", slots={"linked_todo": True})
    assert _files_linked_todo(asked, series)
    # a role call on a series is still one event (the Q50 reading is per call)
    assert not _files_linked_todo(Item(id="i", kind="event", text="call the bank"),
                                  CalendarIntent(title="call the bank", date=day,
                                                 start_time="09:00", end_time="10:00",
                                                 recurrence="weekly"))


# ---------------------------------------------------------------------------
# the executor and the database
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    return _db.get_db()


def _series(db, title="take out the trash", start=None, recurrence="daily", until=None):
    """A repeating to-do as the engine hands it to the executor. Daily from
    tomorrow by default, on weekdays only so no instance meets Shabbat."""
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.calendar.intent import CalendarIntent
    start = start or _next_weekday(dt.date.today() + dt.timedelta(days=1))
    intent = CalendarIntent(title=title, date=start.isoformat(), start_time="09:00",
                            end_time="10:00", recurrence=recurrence,
                            recur_until=(until or start + dt.timedelta(days=3)).isoformat())
    intent.linked_todo = True
    reply = CreateEventAction().execute(intent, None)
    todo = next(t for t in db.get_todos(include_completed=True) if t["title"] == title)
    return reply, todo


def _next_weekday(d):
    while d.weekday() >= 4:           # Friday / Saturday may be skipped for Shabbat
        d += dt.timedelta(days=1)
    return d


def _instances(db, todo):
    ev = db.get_event(todo["linked_event_id"])
    return db.get_series_events(ev["series_id"])


def test_one_todo_for_the_whole_series_and_the_reply_says_so(db):
    reply, todo = _series(db)
    assert "to-do list" in reply
    todos = [t for t in db.get_todos(include_completed=True) if t["title"] == "take out the trash"]
    assert len(todos) == 1
    first = _instances(db, todo)[0]
    assert todo["linked_event_id"] == first["id"] and todo["due_date"] == first["date"]


def test_ticking_moves_it_to_the_next_date_instead_of_completing(db):
    _, todo = _series(db)
    dates = [e["date"] for e in _instances(db, todo)]
    assert len(dates) >= 3
    assert db.toggle_todo_complete(todo["id"]) is False       # it rolled, it is not done
    now = db.get_todo(todo["id"])
    assert not now["completed"] and now["due_date"] == dates[1]
    # the same through the PATCH shape the phone sends
    db.update_todo(todo["id"], completed=1, completed_at="x")
    assert db.get_todo(todo["id"])["due_date"] == dates[2]


def test_the_last_one_completes(db):
    _, todo = _series(db)
    n = len(_instances(db, todo))
    for _ in range(n - 1):
        db.toggle_todo_complete(todo["id"])
    assert db.toggle_todo_complete(todo["id"]) is True
    assert db.get_todo(todo["id"])["completed"]


def test_an_overdue_one_rolls_to_the_next_date_from_today(db):
    """Three missed dates do not take three ticks: the list shows what is next."""
    start = dt.date.today() - dt.timedelta(days=5)
    _, todo = _series(db, start=start, until=dt.date.today() + dt.timedelta(days=10))
    db.toggle_todo_complete(todo["id"])
    assert db.get_todo(todo["id"])["due_date"] >= dt.date.today().isoformat()


def test_deleting_that_occurrence_moves_the_todo_on(db):
    _, todo = _series(db)
    dates = [e["date"] for e in _instances(db, todo)]
    db.delete_event(todo["linked_event_id"])
    now = db.get_todo(todo["id"])
    assert now is not None and now["due_date"] == dates[1]


def test_deleting_the_series_takes_it(db):
    _, todo = _series(db)
    ev = db.get_event(todo["linked_event_id"])
    db.delete_series(ev["series_id"])
    assert db.get_todo(todo["id"]) is None


def test_editing_the_series_keeps_the_link_and_the_name(db):
    _, todo = _series(db)
    db.toggle_todo_complete(todo["id"])                    # linked to the 2nd instance
    first = _instances(db, todo)[0]
    db.update_series(first["series_id"], first["id"], title="bins out", start_time="08:00")
    now = db.get_todo(todo["id"])
    assert now["title"] == "bins out"
    assert now["linked_event_id"] and db.get_event(now["linked_event_id"])["title"] == "bins out"


def test_a_plain_linked_todo_still_completes(db):
    """Q50's pair is one event: ticking its to-do completes it, as before."""
    from assistant.actions.calendar.intent import CalendarIntent
    day = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    ev = db.create_event(CalendarIntent(title="call the bank", date=day,
                                        start_time="09:00", end_time="10:00"))
    todo_id = db.create_linked_todo(ev)
    assert db.toggle_todo_complete(todo_id) is True


def test_the_phone_is_told_where_it_rolled_to(db):
    """The phone ticks optimistically; the toggle answer carries the next date
    so it can put the to-do back instead of showing it done."""
    from assistant.api.server import create_app
    _, todo = _series(db)
    second = _instances(db, todo)[1]
    body = create_app().test_client().patch(f"/todos/{todo['id']}/toggle").get_json()
    assert body["completed"] == 0
    assert (body["due_date"], body["linked_event_id"]) == (second["date"], second["id"])
    assert body["list_name"] in ("today", "general")
