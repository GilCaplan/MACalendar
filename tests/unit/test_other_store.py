"""A change aimed at one list finds its target on the other (2026-09-24).

"rename pack for the trip to …" routed to the calendar answered "I couldn't
find an event" while the task sat on the to-do list — the largest group of
wrong-kind misses on changes. The save step now looks on the other list when
the first finds nothing, and runs the change there only on exactly ONE clear
match.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import assistant.engine as E
from assistant.actions.calendar.intent import CalendarIntent, DeleteEventIntent, UpdateEventIntent
from assistant.actions.todo.intent import DeleteTodoIntent, UpdateTodoIntent
from assistant.db import get_db


@pytest.fixture
def stores():
    db = get_db()
    for t in list(db.get_todos(include_completed=True)):
        db.delete_todo(t["id"])
    db.create_todo("pack for the trip", "general")
    db.create_todo("pay the electricity bill", "general")
    db.create_todo("call the plumber", "today")
    db.create_todo("call the plumber about the sink", "today")
    import datetime as dt
    day = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    db.create_event(CalendarIntent(title="dentist appointment", date=day, start_time="10:00"))
    return db


def _item(action, intent):
    return SimpleNamespace(action=action, intent=intent, id="item_1")


def _state():
    return SimpleNamespace(trace=None)


def test_a_calendar_delete_finds_the_task(stores):
    got = E._other_store(_state(), _item("delete_event", DeleteEventIntent(match_title="pack for the trip")))
    assert got and got[0] == "delete_todo" and got[1].match_title == "pack for the trip"


def test_a_calendar_rename_finds_the_task(stores):
    got = E._other_store(_state(), _item("update_event", UpdateEventIntent(
        match_title="electricity bill", new_title="pay the water bill")))
    assert got and got[0] == "update_todo" and got[1].new_title == "pay the water bill"


def test_a_task_delete_finds_the_event(stores):
    got = E._other_store(_state(), _item("delete_todo", DeleteTodoIntent(match_title="dentist appointment")))
    assert got and got[0] == "delete_event"


@pytest.mark.parametrize("action,intent", [
    ("delete_event", DeleteEventIntent(match_title="call the plumber")),        # two candidates
    ("delete_event", DeleteEventIntent(match_title="it")),                      # an anaphor
    ("delete_event", DeleteEventIntent(match_title="gym")),                     # nothing there
    ("update_event", UpdateEventIntent(match_title="pack for the trip",
                                       new_start_time="17:00")),               # a clock is the calendar's
    ("update_todo", UpdateTodoIntent(match_title="dentist appointment",
                                     new_priority="high")),                    # priority is the list's
    ("complete_todo", DeleteTodoIntent(match_title="dentist appointment")),     # completing never crosses
])
def test_it_refuses_rather_than_guesses(stores, action, intent):
    assert E._other_store(_state(), _item(action, intent)) is None
