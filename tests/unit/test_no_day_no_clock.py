"""No day and no clock, and nothing to infer where it goes, is a to-do (DEVQA Q63).

Gil, 2026-09-27: *"if the date isn't given, then we can just make it a to-do,
to be honest... if we don't have a time to put in at all, and nothing to infer
where we would go, then it would just become a to-do."* "Book a flight" and
"schedule a haircut" said on their own were events at a made-up hour.
"""
from __future__ import annotations

import pytest

from assistant.engine.segmentation.fastseg.fastseg import fastseg, tag_path
from assistant.intent.placed import nothing_to_infer


@pytest.mark.parametrize("said,placed", [
    ("book a flight", False),
    ("schedule a haircut and water the garden", False),
    ("book a flight today", True),                    # a day
    ("book a flight at 3pm", True),                    # a clock
    ("create an event now to go out for a run", True),  # "now", and "an event"
    ("schedule birthday dinner and invite Harper", True),  # a person (Q47 B)
    ("walk the dog then lunch", True),                 # a sequence (Q51)
    ("add this on my calender", True),                 # the calendar named
])
def test_what_places_a_command(said, placed):
    assert nothing_to_infer(said) is not placed


@pytest.mark.parametrize("said,tags", [
    ("book a flight", ["task"]),
    ("schedule a haircut", ["task"]),
    ("book a flight today", ["event"]),
    ("book the gym and remind me to pick up my prescription", ["task", "task"]),
    ("schedule birthday dinner and invite Harper", ["event", "event"]),
    ("go to the gym and then have lunch", ["event", "event"]),
    ("call mom", ["event"]),
])
def test_segmentation(said, tags):
    assert [d["tag"] for d in fastseg(said)] == tags


@pytest.mark.parametrize("words", [
    "cancel team meeting", "move the standup", "um can you just delete this event for me",
])
def test_a_change_to_something_that_exists_is_left_alone(words):
    """Q63 is about what to CREATE; the first cut flipped every timeless
    mutation to the to-do list."""
    assert tag_path(words, "", nothing_said=True)[0] == "event"


def test_an_empty_time_alone_still_means_unknown():
    """Only the two whole-command readers say "nothing was said"; an empty
    time_str from any other caller is the catch-all path the router owns."""
    assert tag_path("book a flight", "") == tag_path("book a flight", "today")


@pytest.fixture
def actions(isolated_registry):
    from assistant.actions.calendar.action import CreateEventAction, DeleteEventAction
    from assistant.actions.todo.action import CreateTodoAction, DeleteTodoAction
    for cls in (CreateEventAction, DeleteEventAction, CreateTodoAction, DeleteTodoAction):
        isolated_registry._actions[cls.action_name] = cls


def test_the_front_door(actions):
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    got = FastRule(RULE_THRESHOLD).run("book a flight", "")
    assert [n for n, _ in got.intents] == ["create_todo"]
    got = FastRule(RULE_THRESHOLD).run("book a flight today", "")
    assert [n for n, _ in got.intents] == ["create_event"]
    # a delete's TARGET is read without Q63: "blood test" names an event
    got = FastRule(RULE_THRESHOLD).run("scrap blood test", "")
    assert [n for n, _ in got.intents] == ["delete_event"]


def test_a_piece_of_a_command_that_named_a_time_keeps_its_reading():
    """The loop-back re-segments one ask on its own; what was SAID decides."""
    from assistant.engine import load_config
    from assistant.engine.segmentation import run as segment
    from assistant.engine.state import EngineState
    st = EngineState(raw_text="yoga at noon and then book the gym", text="book the gym")
    segment(st, load_config())
    assert [i.kind for i in st.items] == ["event"]
    st = EngineState(raw_text="book the gym", text="book the gym")
    segment(st, load_config())
    assert [i.kind for i in st.items] == ["task"]
