"""Disfluent speech, as Gil actually produces it, comes off in ingest.

Cycle 37 (real usage, 2026-09-22). Three shapes the spoken-noise passes did
not know, each from a real command: a trailing interjection said to nobody
after the command, a run of hold-on chatter cutting the command into asks by
its commas, and a one-word self-correction the clause rule rightly refused
("…with pelic sorry, i mean edo"). Plus the pre-existing bug this exposed:
the filler pass ate ", I mean," before the self-correction rule could see it,
so the rule's own docstring example produced two items.

Every rewrite here is a word the speaker did not mean; the negative surface
(every clean corpus row, sealed 300 excluded) is counted in the cycle's
record, because a noise pass that eats a real word is invisible to the user.
"""
from __future__ import annotations

import pytest

from assistant.intent.cleanup import strip_spoken_noise


@pytest.mark.parametrize("said, want", [
    # trailing interjections, repeated, after a full stop or a comma
    ("start emitting for me on wednesday at 6.30. excuse me. excuse me.",
     "start emitting for me on wednesday at 6.30"),
    ("Set a meeting on this coming Sunday for 1 p.m. TA, Office Hour, meeting, excuse me.",
     "Set a meeting on this coming Sunday for 1 p.m. TA, Office Hour, meeting"),
    # hold-on chatter mid-sentence, each with its comma
    ("set a date for tomorrow at 11 o'clock, in one second, one moment, one moment, bear with me, i want to be at the deli",
     "set a date for tomorrow at 11 o'clock, i want to be at the deli"),
    # a one-word self-correction
    ("set a meeting for me tomorrow at 5.30 p.m. with pelic sorry, i mean edo",
     "set a meeting for me tomorrow at 5.30 p.m. with edo"),
    # the clause self-correction, which the filler pass used to eat first
    ("buy milk, I mean, buy bread", "buy bread"),
])
def test_the_disfluency_comes_off(said, want):
    assert strip_spoken_noise(said, drop_courtesy=False) == want


@pytest.mark.parametrize("said", [
    "remind me to say sorry to dana",             # "sorry" as content, no punctuation before it
    "I'm sorry about the delay, book the dentist tomorrow",
    "do you know when the meeting is",
    "hold on the door for me",
    "one second thoughts on the plan",
    "remind me to say thank you to the team",     # never an interjection here
    "book the room for one second interview round",
])
def test_the_same_words_as_content_are_left_alone(said):
    assert strip_spoken_noise(said, drop_courtesy=False) == said


def test_a_filler_without_a_comma_before_it_still_comes_off():
    # the filler pass's own examples keep working after its narrowing
    assert strip_spoken_noise("can you you know, remind me to clean the kitchen", drop_courtesy=False) \
        == "can you remind me to clean the kitchen"
    assert strip_spoken_noise("hang on, hang on, organize the garage", drop_courtesy=False) \
        == "organize the garage"
