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


def test_a_passed_clock_stays_today_when_the_day_was_named(registry_with_real_actions):
    """Q42 rolls a passed clock to tomorrow only when NO day was said — the
    deep rule's guard (`object_rules._DAY_WORD_RE`), now on the fast path
    too: "this morning" names today even though the recogniser does not read
    it as a date (2026-09-25)."""
    import datetime as dt
    from freezegun import freeze_time
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    fr = FastRule(RULE_THRESHOLD)
    fr.run("book gym tomorrow at 7am")      # load the models OUTSIDE the frozen clock
    with freeze_time(dt.datetime(2026, 9, 9, 10, 0)):
        got = {t: (fr.run(t).intents[0][1].date, fr.run(t).intents[0][1].start_time)
               for t in ("book birthday dinner this morning from 6 to 8", "dentist at 8am")}
    assert got == {"book birthday dinner this morning from 6 to 8": ("2026-09-09", "06:00"),
                   "dentist at 8am": ("2026-09-10", "08:00")}


def test_a_range_is_read_by_the_one_time_reader(registry_with_real_actions):
    """Q53: the fast path takes a RANGE's start and end from decompose_validate's
    resolver, and the range's words leave the title. Before: 'between 5 and
    6:30' booked 18:30-19:30, 'between 2 and 4 this afternoon' 16:00-17:00,
    and 'yoga class from 6 to 8' kept its clock in its name (2026-09-25)."""
    import datetime as dt
    from freezegun import freeze_time
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    fr = FastRule(RULE_THRESHOLD)
    fr.run("book gym tomorrow at 7am")
    with freeze_time(dt.datetime(2026, 9, 9, 10, 0)):
        for said, want in [
                ("put sales call on my calendar tomorrow between 5 and 6:30",
                 ("sales call", "17:00", "18:30")),
                ("set up open house between 2 and 4 this afternoon",
                 ("open house", "14:00", "16:00")),
                ("book yoga class tomorrow from 6 to 8", ("yoga class", "18:00", "20:00"))]:
            i = fr.run(said).intents[0][1]
            assert (i.title, i.start_time, i.end_time) == want, said
