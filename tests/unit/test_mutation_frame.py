"""A create read over a MUTATION FRAME is not committed by the front door.

A to-do's name usually opens with a verb, so the router's first-word pass took
"renew" in "i no longer need to renew the passport, so delete it from the list"
as the command and CREATED the thing to be removed (92 FastRule TRAIN rows,
2026-09-27). The frame defers; the deep track reads what to do with it.
"""
from __future__ import annotations

import pytest

from assistant.intent.rule_parser import _MUTATION_FRAME


@pytest.mark.parametrize("said", [
    "i no longer need to renew the passport, so delete it from the list",
    "buy groceries, done",
    "wipe feed the cat from the to-do list, i won't be doing it",
    "order new office supplies not needed anymore, remove from list",
    "on my list, change sign the permission slip to say confirm the reservation",
    "buy groceries is due in three weeks now, update it",
    "organize the garage is sorted, you can tick it off",
])
def test_the_frame_is_seen(said):
    assert _MUTATION_FRAME.search(said)


@pytest.mark.parametrize("said", [
    "buy milk",
    "add walk the dog to my list",
    "remind me to take the laundry off the line",
    "oil change this sunday at 9am",
    "book the dentist tomorrow at 3",
    "remind me to update the resume",
])
def test_a_plain_create_is_not_a_frame(said):
    assert not _MUTATION_FRAME.search(said)


@pytest.fixture
def actions(isolated_registry):
    from assistant.actions.calendar.action import CreateEventAction, DeleteEventAction
    from assistant.actions.todo.action import (CompleteTodoAction, CreateTodoAction,
                                               DeleteTodoAction)
    for cls in (CreateEventAction, DeleteEventAction, CreateTodoAction,
                DeleteTodoAction, CompleteTodoAction):
        isolated_registry._actions[cls.action_name] = cls


def test_the_front_door_defers_instead_of_creating(actions):
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    res = FastRule(RULE_THRESHOLD).run(
        "i no longer need to renew the passport, so delete it from the list", "")
    assert not res.committed
    assert FastRule(RULE_THRESHOLD).run("buy milk", "").committed
