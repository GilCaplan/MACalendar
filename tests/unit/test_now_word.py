""""now" is the present minute — and only when it is a time (Gil, 2026-09-30).

The three real commands of that evening, all wrong before: "Walk, Val, now"
(a to-do, no time), "Walk my dog Val now, thanks to …" (the right clock,
TOMORROW), "create an event now to go out for a run" (00:00 from the date
recogniser). Then the senses that must NOT become a clock, the negative
surface: on the 11,700-row corpus diff the first cut turned ten "X is done,
now add Y to my list" rows into events.
"""
from __future__ import annotations

import datetime

import pytest
from freezegun import freeze_time

from assistant.intent.now_word import says_now

CLOCK = datetime.datetime(2026, 9, 30, 21, 2, 30)

TIME = ["Walk, Val, now", "Walk my dog Val now, thanks to Kupah.", "walk the dog now",
        "create an event now to go out for a run", "go for a run right now", "remind me now to call mom",
        "call mom now.", "add event now for walking my dog with my ex-girl"]
VAGUE = ["buy milk for now", "from now on remind me to drink water", "now that the exam is over book a party",
         "every now and then call grandma", "meeting with dana two weeks from now at 3pm", "by now the laundry is done",
         "until now i forgot", "not now, maybe dinner tomorrow", "Now, what do I have today",
         "i just now remembered the dentist", "as of now", "now and again check the oven",
         "feed the cat is done, now add take out the trash to my list", "I need a new list, do it now",
         "Now add buy milk to my list", "eye exam next month is now at 8:30pm", "snowboard trip friday"]


@pytest.mark.parametrize("text", TIME)
def test_now_said_as_a_time(text):
    assert says_now(text)


@pytest.mark.parametrize("text", VAGUE)
def test_now_that_is_not_a_time(text):
    assert not says_now(text)


@pytest.fixture
def fastrule(isolated_registry):
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.todo.action import CreateTodoAction
    for cls in (CreateEventAction, CreateTodoAction):
        isolated_registry._actions[cls.action_name] = cls
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    fr = FastRule(RULE_THRESHOLD)
    fr.run("book gym tomorrow at 7am")      # warm outside the frozen clock, as the board does
    return fr


@pytest.mark.parametrize("text,title", [
    ("Walk, Val, now", "walk val"),
    ("Walk my dog Val now, thanks to Kupah.", "walk my dog val thanks to kupah"),
    ("create an event now to go out for a run", "go out for a run"),
    ("walk the dog now", "walk the dog"),
])
def test_now_books_an_event_at_this_minute_today(fastrule, text, title):
    with freeze_time(CLOCK):
        r = fastrule.run(text)
    assert r.committed
    (action, intent), = r.intents
    assert action == "create_event", "a stated clock makes it an event (Q26)"
    assert intent.title == title
    assert intent.date == "2026-09-30", "never rolled to tomorrow: the minute has not passed"
    assert intent.start_time == "21:02"


def test_two_weeks_from_now_keeps_its_own_clock(fastrule):
    """The old fallback read any "now" — "two weeks from now at 7am" was
    booked at the current clock."""
    with freeze_time(CLOCK):
        r = fastrule.run("set up training session every monday at 7am starting two weeks from now")
    (_, intent), = r.intents
    assert intent.start_time == "07:00"


def test_vague_now_stays_a_to_do(fastrule):
    with freeze_time(CLOCK):
        r = fastrule.run("buy milk for now")
    assert [a for a, _ in r.intents] == ["create_todo"]


def test_the_deep_tracks_floor_does_not_roll_now_to_tomorrow():
    from types import SimpleNamespace as NS
    from assistant.engine.decompose_validate.object_rules import _rule_passed_clock_means_tomorrow
    fixes = []
    state = NS(add_fix=lambda *a, **k: fixes.append(a))
    intent = NS(date="2026-09-30", start_time="21:02", recurrence=None)
    item = NS(source="walk my dog now", time="", text="walk my dog")
    _rule_passed_clock_means_tomorrow(state, item, intent, datetime.datetime(2026, 9, 30, 21, 3))
    assert intent.date == "2026-09-30" and not fixes
