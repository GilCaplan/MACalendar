"""Settings ▸ Appearance ▸ Show hours (Gil, 2026-09-29): Week and Day fit the
chosen hours to the window and open at the first; the rest stay a scroll away
— nothing is hidden."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from assistant.calendar_ui import visible_hours as vh


@pytest.mark.parametrize("first,last,want", [
    (7, 24, (7, 24)), (0, 24, (0, 24)), (6, 22, (6, 22)),
    (9, 9, (0, 24)), (10, 8, (0, 24)), (-1, 24, (0, 24)), (0, 25, (0, 24)),
    ("x", 24, (0, 24)),
])
def test_a_span_is_sane_or_the_whole_day(first, last, want):
    assert vh.span(SimpleNamespace(hours_from=first, hours_to=last)) == want


def test_a_config_without_the_setting_is_the_whole_day():
    assert vh.span(SimpleNamespace()) == (0, 24)


def test_the_chosen_hours_fill_the_window_within_the_bounds():
    assert vh.fit(900, 0, 24, 22, 60) == 37          # 900 / 24
    assert vh.fit(900, 7, 24, 22, 60) == 52          # 900 / 17: bigger rows
    assert vh.fit(900, 8, 12, 22, 60) == 60          # capped
    assert vh.fit(300, 0, 24, 22, 60) == 22          # floor; then it scrolls


def test_labels_read_like_a_clock():
    assert [vh.label(h) for h in (0, 7, 12, 13, 24)] == \
        ["12 AM", "7 AM", "12 PM", "1 PM", "12 AM (midnight)"]


@pytest.fixture
def week(qapp_offscreen, tmp_path):
    from assistant.calendar_ui.week_view import WeekView
    from assistant.db import CalendarDB
    v = WeekView(CalendarDB(str(tmp_path / "c.db")))
    v.resize(1200, 900)
    v.show()
    qapp_offscreen.processEvents()
    return v


@pytest.fixture
def qapp_offscreen():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_week_opens_at_the_first_hour_and_keeps_the_rest(week, qapp_offscreen):
    week.set_visible_hours(7, 24)
    qapp_offscreen.processEvents()
    bar = week._scroll.verticalScrollBar()
    assert bar.value() == min(week._hour_height * 7, bar.maximum())
    assert week._time_col.height() == week._hour_height * 24, "midnight–7 AM still there"
