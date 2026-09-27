""""X … is now at <when>" is a move, read with the right values (TASKS 26).

Routing it alone moved the event to TODAY at 00:00 — the span's reading took
"now" as the time — and a board that checks only the action family scored that
as right. So this pins the values, not the route.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def actions(isolated_registry):
    from assistant.actions.calendar.action import CreateEventAction, UpdateEventAction
    from assistant.actions.todo.action import CreateTodoAction
    for cls in (CreateEventAction, UpdateEventAction, CreateTodoAction):
        isolated_registry._actions[cls.action_name] = cls


def _read(text):
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    return FastRule(RULE_THRESHOLD).run(text, "")


def test_the_new_time_is_the_one_after_is_now(actions):
    got = _read("oil change this friday is now at 11am")
    [(name, intent)] = got.intents
    assert name == "update_event"
    assert intent.match_title == "oil change"
    assert intent.new_start_time == "11:00"
    assert intent.new_date is None               # the day it is ON is how to find it
    assert intent.match_date                      # "this friday"


def test_a_new_day_after_is_now_on_moves_the_day(actions):
    [(name, intent)] = _read("team meeting is now on thursday at 3pm").intents
    assert (name, intent.new_start_time) == ("update_event", "15:00")
    assert intent.new_date


def test_a_place_is_not_a_move(actions):
    assert not _read("the party is now at my place").committed
