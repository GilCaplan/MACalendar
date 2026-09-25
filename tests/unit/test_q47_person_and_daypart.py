"""Q47 (Gil, 2026-09-24): no clock -> a to-do; an encounter with a person -> an event.

"If there's no time involved, then it can just be a to-do due today. But if
there's a time on it, like 6 p.m., then make an event." "Given a person, it
should be an event no matter what... default time 9 a.m." And: "Call mum is
an event at a default time like 9, same for similar events." A WRITTEN
message, a mention, and a named to-do list stay to-dos.
"""
from __future__ import annotations

import importlib

import pytest

from assistant.intent.encounter import is_encounter
from assistant.engine.segmentation.fastseg.kind import kind_of

FS = importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")


@pytest.mark.parametrize("action,time", [
    ("i should see Parker", "the 21st"),
    ("i need to talk to Drew", "on next wednesday"),
    ("pick up my sister from school", "tomorrow"),
    ("lunch with dad", "on friday"),
    ("call mum", ""),
    ("remind me to call Morgan", "tomorrow"),
    ("facetime Grandma", ""),
])
def test_an_encounter_is_an_event_day_or_no_day(action, time):
    assert is_encounter(action)
    assert FS.tag(action, time) == "event", (action, time)


@pytest.mark.parametrize("action", [
    "email Dana the report", "text Sam about the party", "buy a gift for mom",
    "call the plumber", "add call Dana to my to-do list", "add swe epthe balcony to my tasks",
])
def test_written_messages_mentions_and_a_named_list_are_not_encounters(action):
    assert not is_encounter(action), action


def test_seeing_a_person_is_not_a_schedule_question():
    assert kind_of("see mom") == "event"
    assert kind_of("see Parker") == "event"
    assert kind_of("see my schedule") == "review"


@pytest.mark.parametrize("action,time,want", [
    ("add a note to pay the electricity bill", "", "task"),     # no time: a to-do
    ("make a note to call the plumber", "", "task"),
    ("add a note to walk the dog", "at 6pm", "event"),           # a clock makes it an event (Q25)
    ("make a note to call Mom", "", "event"),                    # an encounter (Q47)
])
def test_a_note_to_frame_is_a_todo_unless_a_clock_or_a_person_says_otherwise(action, time, want):
    """Gil, 2026-09-24: "todo is fine if not given a time, if time given make
    an event, i have been clear on previous similar things"."""
    assert FS.tag(action, time) == want
