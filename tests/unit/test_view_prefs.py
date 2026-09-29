"""How the calendar is drawn (Settings ▸ Appearance; Gil, 2026-09-29: "sure
can add all those"): first day, clock, days in Week, hour-row height, week
numbers — one module every view asks."""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from assistant.calendar_ui import view_prefs as vp


@pytest.fixture(autouse=True)
def defaults():
    vp.apply(SimpleNamespace())
    yield
    vp.apply(SimpleNamespace())


def ui(**kw):
    return SimpleNamespace(**kw)


WED = datetime.date(2026, 9, 30)


def test_the_defaults_are_what_the_app_always_did():
    assert vp.week_start(WED) == datetime.date(2026, 9, 27)          # a Sunday
    assert vp.fmt_hhmm("14:30") == "2:30 PM" and vp.hour_label(0) == "12 AM"
    assert all(vp.shows(WED + datetime.timedelta(days=k)) for k in range(7))
    assert vp.fixed_hour_height() == 0


def test_a_monday_week():
    vp.apply(ui(week_starts="monday"))
    assert vp.week_start(WED) == datetime.date(2026, 9, 28)
    assert vp.week_start(datetime.date(2026, 10, 4)) == datetime.date(2026, 9, 28), "Sunday ends it"
    assert vp.weekday_order() == [0, 1, 2, 3, 4, 5, 6]


def test_a_24_hour_clock():
    vp.apply(ui(clock="24h"))
    assert vp.fmt_hhmm("9:05") == "09:05" and vp.fmt_hhmm("14:30", compact=True) == "14:30"
    assert vp.hour_label(0) == "00:00" and vp.hour_label(13) == "13:00"


def test_twelve_hour_compact_and_bad_input():
    assert vp.fmt_hhmm("14:00", compact=True) == "2p"
    assert vp.fmt_hhmm("09:30", compact=True) == "9:30a"
    assert vp.fmt_hhmm("") == "" and vp.fmt_hhmm("soon") == "soon"


def test_hidden_days_and_never_an_empty_week():
    vp.apply(ui(week_days=["mon", "tue", "wed", "thu", "fri"]))
    sat = datetime.date(2026, 10, 3)
    assert not vp.shows(sat) and vp.shows(WED)
    vp.apply(ui(week_days=[]))
    assert vp.shows(sat), "nothing ticked means every day, not an empty week"


@pytest.mark.parametrize("raw,want", [(48, 48), (0, 0), (5, 0), (999, 0), ("x", 0)])
def test_a_fixed_row_height_within_bounds(raw, want):
    vp.apply(ui(hour_height=raw))
    assert vp.fixed_hour_height() == want


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_week_draws_only_the_shown_days_from_the_first_day(qapp, tmp_path):
    from assistant.calendar_ui.week_view import WeekView
    from assistant.db import CalendarDB
    vp.apply(ui(week_starts="monday", week_days=["mon", "tue", "wed", "thu", "fri", "sun"]))
    v = WeekView(CalendarDB(str(tmp_path / "c.db")))
    v.navigate(vp.week_start(WED))
    dates = [c.date for c in v._day_columns]
    assert dates[0] == datetime.date(2026, 9, 28) and len(dates) == 6
    assert datetime.date(2026, 10, 3) not in dates and dates[-1] == datetime.date(2026, 10, 4)
    assert v._time_labels[13].text() == "1 PM"


def test_week_uses_a_fixed_row_height_when_set(qapp, tmp_path):
    from assistant.calendar_ui.week_view import WeekView
    from assistant.db import CalendarDB
    vp.apply(ui(hour_height=64))
    v = WeekView(CalendarDB(str(tmp_path / "c.db")))
    v._recalc_hour_height(900)
    assert v._hour_height == 64


def test_month_follows_the_first_day_and_the_week_number_switch(qapp, tmp_path):
    from assistant.calendar_ui.month_view import MonthView
    from assistant.db import CalendarDB
    vp.apply(ui(week_starts="monday"))
    m = MonthView(CalendarDB(str(tmp_path / "c.db")))
    m.apply_ui_config(ui(show_week_numbers=False, font_month=11))
    assert [l.text() for l in m._header_labels][:2] == ["Mon", "Tue"]
    assert m._show_wknums is False
    m.apply_ui_config(ui(show_week_numbers=True, font_month=11))
    assert m._show_wknums is True


def test_agenda_rows_follow_the_clock(qapp):
    from assistant.calendar_ui.agenda_view import _EventRow as AgendaRow
    ev = {"id": 1, "title": "Dentist", "date": "2026-09-30",
          "start_time": "10:00", "end_time": "11:30", "color": "#0a84ff"}
    assert AgendaRow(ev)._time_label.text() == "10a–11:30a"
    vp.apply(ui(clock="24h"))
    assert AgendaRow(ev)._time_label.text() == "10:00–11:30"
