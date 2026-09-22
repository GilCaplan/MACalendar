"""When the words name BOTH a weekday and a stated day, the stated day wins.

Cycle 36 (real usage, 2026-09-22): three of Gil's commands carried a weekday
that was simply wrong beside a day he meant — "tomorrow on tuesday" said on a
Wednesday, "monday the 13th" when the 13th was a Sunday, "the 14th on tuesday"
when the 14th was a Monday — and the fast path took the weekday every time,
because "the day the clock is attached to wins" (a rule bought with "book
monday standup tomorrow at 9am") let a weekday carrying the clock beat a
"tomorrow" read earlier. A stated day — today, tomorrow, an ordinal, a
month-day — is the deliberate one; a weekday is a gloss. Both rules coexist:
the standup case still lands on tomorrow.
"""
from __future__ import annotations

import datetime

import pytest

from assistant.intent import rule_parser as RP

TODAY = datetime.date(2026, 8, 26)     # a Wednesday


@pytest.mark.parametrize("said, date, start", [
    ("set a meeting tomorrow on tuesday at 6pm with etai", "2026-08-27", "18:00"),
    ("please make a meeting for me at 1040 on monday the 13th for makabi", "2026-09-13", "10:40"),
    ("can you set a meeting for next week on the 14th on tuesday at 2pm", "2026-09-14", "14:00"),
    ("dentist tomorrow tuesday at 4pm", "2026-08-27", "16:00"),
])
def test_the_stated_day_wins_over_a_wrong_weekday(said, date, start):
    got = RP._extract_temporal(said, TODAY)
    assert (got["date"], got["start_time"]) == (date, start)


@pytest.mark.parametrize("said, date", [
    ("book monday standup tomorrow at 9am", "2026-08-27"),   # the rule this coexists with
    ("meeting on tuesday the 1st at 2pm", "2026-09-01"),     # an agreeing pair
    ("gym on friday the 28th", "2026-08-28"),
    ("dentist on tuesday at 4pm", "2026-09-01"),             # a lone weekday still dates
    ("meeting on the 13th", "2026-09-13"),                   # a lone ordinal still dates
])
def test_nothing_else_about_the_reading_moves(said, date):
    assert RP._extract_temporal(said, TODAY)["date"] == date


def test_the_winning_ordinal_leaves_the_title():
    got = RP._extract_temporal("meeting at 1040 on monday the 13th", TODAY)
    text = "meeting at 1040 on monday the 13th"
    assert any("13th" in text[a:b] for a, b in got["spans"])
