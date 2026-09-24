"""A weekly series may name several weekdays, and the fast reader reads them all.

2026-09-24: "book yoga every tuesday and thursday at 6pm" became a
Thursday-only series on the fast path — `recurrence.detect` stopped at the
first weekday, the recogniser's date (Thursday) started the series, and the
database never recorded the days. Found verifying the tutorial's tips.
"""
from __future__ import annotations

import datetime

from assistant.intent import recurrence as R


def test_a_weekday_list_after_every_is_one_weekly_series():
    r = R.detect("book yoga every tuesday and thursday at 6pm")
    assert r.cadence == "weekly" and r.days == ["tuesday", "thursday"]


def test_plural_weekdays_and_abbreviations_and_commas():
    assert R.detect("yoga on tuesdays and thursdays").days == ["tuesday", "thursday"]
    assert R.detect("gym every mon, wed and fri at 7").days == ["monday", "wednesday", "friday"]
    assert R.detect("yoga on tuesdays").cadence == "weekly"


def test_one_day_and_a_bound_are_not_a_list():
    assert R.detect("book yoga every tuesday at 6pm").days == []
    assert R.detect("yoga every tuesday until friday").days == []
    assert R.detect("dentist tuesday at 4").cadence is None


def test_the_series_starts_on_the_soonest_named_day():
    monday = datetime.date(2026, 11, 9)
    assert R.detect("every tuesday and thursday").start_date(monday) == datetime.date(2026, 11, 10)
    wednesday = datetime.date(2026, 11, 11)
    assert R.detect("every tuesday and thursday").start_date(wednesday) == datetime.date(2026, 11, 12)


def test_the_whole_list_leaves_the_title():
    text = "book yoga every tuesday and thursday at 6pm"
    s, e = R.detect(text).span
    assert "thursday" in text[s:e] and "tuesday" in text[s:e]
