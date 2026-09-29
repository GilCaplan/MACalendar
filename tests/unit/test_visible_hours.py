"""Settings ▸ Appearance ▸ Show hours (Gil, 2026-09-29): Week and Day SHOW
only the chosen hours — the first at the top edge, the last at the bottom,
filling the window — and widen them for an event outside, which must never
be hidden. The first build left the night a scroll away; Gil: "doesn't work
well enough"."""
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


def _settle(app):
    from PyQt6.QtCore import QCoreApplication, QEvent
    for _ in range(5):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _shown(view):
    """(top hour, bottom hour) actually on screen."""
    bar, h = view._scroll.verticalScrollBar(), view._hour_height
    top = view._window.first + bar.value() / h
    return top, top + min(view._scroll.viewport().height(), view._window.height()) / h


def test_the_week_shows_the_chosen_hours_and_nothing_else(week, qapp_offscreen):
    week.set_visible_hours(7, 24)
    _settle(qapp_offscreen)
    top, bottom = _shown(week)
    assert top == 7, "no sliver of 6 AM above the first hour"
    assert 23.5 < bottom <= 24
    assert week._scroll.verticalScrollBar().maximum() == 0, "nothing to scroll into"


def test_an_event_outside_the_hours_widens_them(qapp_offscreen, tmp_path):
    import datetime
    from assistant.actions.calendar.intent import CalendarIntent
    from assistant.calendar_ui.day_view import DayView
    from assistant.calendar_ui.week_view import WeekView
    from assistant.db import CalendarDB
    db = CalendarDB(str(tmp_path / "c.db"))
    today = datetime.date.today()
    db.create_event(CalendarIntent(title="early run", date=today.isoformat(),
                                   start_time="05:30", end_time="06:30"))
    for cls in (WeekView, DayView):
        v = cls(db)
        v.resize(1200, 900)
        v.show()
        _settle(qapp_offscreen)
        v.set_visible_hours(7, 24)
        v.refresh()
        _settle(qapp_offscreen)
        assert v._span == (5, 24), cls.__name__
        assert _shown(v)[0] == 5, f"{cls.__name__}: the 5:30 run is on screen"


def test_a_short_window_scrolls_within_the_chosen_hours_only(week, qapp_offscreen):
    week.resize(1200, 420)
    _settle(qapp_offscreen)
    week.set_visible_hours(7, 24)
    _settle(qapp_offscreen)
    bar = week._scroll.verticalScrollBar()
    bar.setValue(bar.minimum())
    assert _shown(week)[0] == 7, "scrolling up stops at the first chosen hour"
    bar.setValue(bar.maximum())
    assert _shown(week)[1] <= 24


def test_the_whole_day_still_opens_at_8(week, qapp_offscreen):
    week.set_visible_hours(0, 24)
    _settle(qapp_offscreen)
    assert week._span == (0, 24)


@pytest.mark.parametrize("events,want", [
    ([], (7, 24)),
    ([{"start_time": "05:30", "end_time": "06:30"}], (5, 24)),
    ([{"start_time": "22:00", "end_time": "01:00"}], (7, 24)),      # runs past midnight
    ([{"start_time": "06:00", "end_time": None}], (6, 24)),
    ([{"start_time": None}], (7, 24)),                                # all-day
    ([{"start_time": "03:00", "end_time": "04:00", "all_day": 1}], (7, 24)),
])
def test_widen(events, want):
    assert vh.widen(7, 24, events) == want


def test_widen_grows_the_end_too():
    assert vh.widen(7, 20, [{"start_time": "21:00", "end_time": "22:30"}]) == (7, 23)
