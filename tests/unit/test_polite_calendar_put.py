"""Polite wrappers and "put X in my calendar" (2026-09-27, TRAIN family
s_tr_ce_polite_verbose / c_tr_mark_fronted_statement): the deep track read
them as schedule QUESTIONS."""
from __future__ import annotations

import pytest

from assistant.intent.cleanup import strip_spoken_noise


@pytest.mark.parametrize("said,clean", [
    ("do me a favour and put car service appointment in my calendar for friday",
     "put car service appointment in my calendar for friday"),
    ("would you be so kind as to put flight to Chicago in my calendar",
     "put flight to Chicago in my calendar"),
    ("book the dentist at 3, thank you", "book the dentist at 3"),
    ("thank you for the reminder about the dentist", "thank you for the reminder about the dentist"),
])
def test_manners_come_off_the_ends_only(said, clean):
    assert strip_spoken_noise(said) == clean


def test_put_it_on_the_calendar_is_an_event_not_a_question():
    import importlib
    F = importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")
    got = F.fastseg("this friday is the big game, put it on the calendar")
    assert [d["tag"] for d in got] == ["event"]
    assert [d["tag"] for d in F.fastseg("what's on my calendar tomorrow")] == ["review"]


@pytest.mark.parametrize("said,title", [
    ("this friday is the big game, put it on the calendar", "the big game"),
    ("the big game is this friday, put it on the calendar", "the big game"),
    ("march 5th is the interview, add it to my calendar", "the interview"),
])
def test_a_statement_then_put_it_names_its_subject(said, title):
    """TASKS 27: the rejoined ask's title was the whole span, 'is the big game,
    put it on the calendar'. It is what the statement names; the kind is still
    read from the whole ask, so it stays an event."""
    import importlib
    F = importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")
    got = F.fastseg(said)
    assert [(d["tag"], d["action"]) for d in got] == [("event", title)]


def test_an_ordinary_back_reference_is_untouched():
    import importlib
    F = importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")
    got = F.fastseg("i no longer need to refill the prescription, so delete it from the list")
    assert len(got) == 1 and "refill the prescription" in got[0]["action"]
