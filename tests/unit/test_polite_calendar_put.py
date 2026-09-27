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
