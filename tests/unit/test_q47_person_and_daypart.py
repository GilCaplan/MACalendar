"""Q47 (Gil, 2026-09-24): no clock -> a to-do; a person on a stated day -> an event.

"If there's no time involved, then it can just be a to-do due today. But if
there's a time on it, like 6 p.m., then make an event." And: "given a person,
it should be an event no matter what... default time 9 a.m." — read as a
person ON A STATED DAY; the outreach verbs (call, email, text) stay to-dos
until he rules on "call Mom tomorrow".
"""
from __future__ import annotations

import importlib

import pytest

FS = importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")
from assistant.engine.segmentation.fastseg.kind import kind_of  # noqa: E402


def _tag(action, time):
    return FS.tag(action, time) if hasattr(FS, "tag") else None


@pytest.mark.parametrize("action,time", [
    ("i should see Parker", "the 21st"),
    ("i need to talk to Drew", "on next wednesday"),
    ("pick up my sister from school", "tomorrow"),
    ("lunch with dad", "on friday"),
])
def test_a_person_on_a_stated_day_is_an_event(action, time):
    assert FS._meets_a_person(action) or FS._has_person_argument(action) or FS._KIN_RE.search(action)
    got = _tag(action, time)
    if got is not None:
        assert got == "event", (action, time, got)


@pytest.mark.parametrize("action", [
    "remind me to call Morgan", "call mom", "remind me to email Dana",
    "buy a gift for mom",
])
def test_outreach_and_mentions_are_not_encounters(action):
    assert not FS._meets_a_person(action), action


def test_seeing_a_person_is_not_a_schedule_question():
    assert kind_of("see mom") == "event"
    assert kind_of("see Parker") == "event"
    assert kind_of("see my schedule") == "review"
