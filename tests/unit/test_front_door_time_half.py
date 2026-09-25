"""The half of the day, on the front door, agrees with the rulings and with
the deep track's reader (FastRule board, 2026-09-25).

Two defects, one cycle each:
  * a bare 8 stayed in the morning while Q28 (and the reply it writes) said
    PM — the post-process bumped 1-7 only;
  * a spoken am/pm, noon or midnight lost to a day word beside it ("this
    evening at 11am" -> 23:00).
The deep reader (`decompose_validate.resolve`) already answered every one of
these the ruled way, so the test pins the two tracks to EACH OTHER as well as
to the answer: a divergence between them is how Q28 was found.
"""
from __future__ import annotations

import datetime as dt

import pytest
from freezegun import freeze_time

from assistant.engine.decompose_validate import resolve as R
from assistant.intent.rule_parser import _extract_temporal

CLOCK = dt.datetime(2026, 9, 9, 10, 0)


@pytest.mark.parametrize("said,want", [
    ("tomorrow at 8", "20:00"),                   # Q28: a bare 8 is PM
    ("tomorrow at 8:45", "20:45"),
    ("the 21st at quarter to nine", "20:45"),
    ("tomorrow at 8 o'clock", "08:00"),           # "8 o'clock" keeps its morning
    ("tomorrow morning at 8", "08:00"),           # a morning word wins
    ("tomorrow at 8am", "08:00"),
    ("tomorrow at 7", "19:00"),
    ("tomorrow at 9", "09:00"),
    ("this evening at 11am", "11:00"),            # the spoken half wins
    ("this morning at noon", "12:00"),
    ("tonight at midnight", "00:00"),
    ("tonight at 7:30am", "07:30"),
    ("at 5 pm in the morning", "17:00"),
    ("at 8:30pm in the morning", "20:30"),
    ("from 9 to 11am tomorrow", "09:00"),         # a range's end never moves its start
    ("tomorrow morning at 6.30am", "06:30"),      # a DOT clock keeps its minutes (id 213)
    ("tomorrow at 6.30", "18:30"),
    ("tomorrow evening at 6.30pm", "18:30"),
])
def test_both_tracks_read_the_half_of_the_day_the_same(said, want):
    with freeze_time(CLOCK):
        front = _extract_temporal(said, CLOCK.date())["start_time"]
        deep = R.resolve(said, CLOCK.date(), said).get("start_time")
    assert front == want, f"front door read {said!r} as {front}"
    assert deep == want, f"deep track read {said!r} as {deep}"


@pytest.mark.parametrize("text", ["walk for 2.5 hours", "costs $5.99", "version 2.10 update"])
def test_a_decimal_is_never_read_as_a_clock(text):
    from assistant.intent.rule_parser import _dot_clocks_to_colons
    assert _dot_clocks_to_colons(text) == text
