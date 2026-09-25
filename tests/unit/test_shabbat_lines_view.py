"""The Mac's Week and Day views draw a yellow line at the exact minute of candle lighting.

Rendered for real (offscreen Qt): the line is found in the grabbed PIXELS at
the y the minute maps to, not just in a list the widget keeps — and a click at
that spot still lands on the event underneath, found through Qt's own hit
testing (`childAt`), then clicked with `QTest.mouseClick`, per this repo's rule
that a UI test which never sends a mouse event tests nothing.

The place is pinned (Jerusalem, 18 minutes before sunset, tzeit at 8.5°) and
the process clock is set to Asia/Jerusalem, so the minute is a known literal:
candle lighting on Friday 4 September 2026 is 18:41:20.
"""
from __future__ import annotations

import datetime
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt                                  # noqa: E402
from PyQt6.QtTest import QTest                                       # noqa: E402
from PyQt6.QtWidgets import QApplication                             # noqa: E402

from assistant import observance as ob                               # noqa: E402
from assistant.calendar_ui import holy_times                         # noqa: E402
from assistant.config import HebrewCalendarConfig                    # noqa: E402

JERUSALEM = ob.ObservanceSettings(latitude=31.7683, longitude=35.2137,
                                  timezone="Asia/Jerusalem", city="Jerusalem",
                                  tzeit_depression=8.5, candle_lighting_minutes=18)
SUNDAY = datetime.date(2026, 8, 30)
FRI = datetime.date(2026, 9, 4)
SAT = datetime.date(2026, 9, 5)
LIT = datetime.time(18, 41, 20)          # candle lighting, Friday 4 Sep 2026


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def jerusalem(monkeypatch):
    """Pin the place and put this process's clock in the same zone."""
    monkeypatch.setattr(ob, "settings_from_config", lambda cfg=None: JERUSALEM)
    monkeypatch.setenv("TZ", "Asia/Jerusalem")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def db(tmp_path):
    from assistant.db import CalendarDB
    d = CalendarDB(str(tmp_path / "cal.db"))
    # An event straddling candle lighting, so the line crosses it.
    d.create_event_from_dict({"title": "Cooking for Shabbat", "date": FRI.isoformat(),
                              "start_time": "18:00", "end_time": "19:30"})
    return d


def _week(qapp, db, show=True):
    from assistant.calendar_ui.week_view import WeekView
    wv = WeekView(db)
    wv.resize(1000, 900)
    wv.apply_hebrew_config(HebrewCalendarConfig(show_shabbat_times=show))
    wv.navigate(SUNDAY)
    wv.show()
    qapp.processEvents()
    return wv


def _column(wv, date):
    [col] = [c for c in wv._day_columns if c.date == date]
    return col


def _is_yellow(c) -> bool:
    return c.red() > 190 and c.green() > 150 and c.blue() < 110


def test_the_known_minute_is_what_observance_says():
    assert ob.candle_lighting(FRI, JERUSALEM).replace(microsecond=0) == LIT


def test_week_view_draws_the_line_at_the_exact_second(qapp, jerusalem, db):
    wv = _week(qapp, db)
    col = _column(wv, FRI)
    h = col.hour_height
    expect_y = (LIT.hour * 3600 + LIT.minute * 60 + LIT.second) / 3600 * h

    [(y, label, is_start)] = col._holy_overlay.lines()
    assert y == pytest.approx(expect_y)
    assert (label, is_start) == ("Shabbat · 18:41", True)
    assert col._holy_overlay.isVisible()

    # In the rendered pixels: yellow on the line, on the left of the column
    # (the label pill sits on the right), across the event block.
    img = col.grab().toImage()
    ry = round(expect_y)
    assert any(_is_yellow(img.pixelColor(6, yy)) for yy in (ry - 1, ry, ry + 1)), \
        "no yellow line at the candle-lighting minute"
    # ...and not an hour earlier, which is what a rounded or wrong-zone
    # minute would look like.
    assert not _is_yellow(img.pixelColor(6, round(expect_y - h)))

    # Saturday carries the end line; a weekday carries none.
    [(_, end_label, end_is_start)] = _column(wv, SAT)._holy_overlay.lines()
    assert end_label.startswith("Shabbat ends · ") and not end_is_start
    assert _column(wv, datetime.date(2026, 9, 2))._holy_overlay.lines() == []
    assert not _column(wv, datetime.date(2026, 9, 2))._holy_overlay.isVisible()


def test_a_click_on_the_line_still_opens_the_event_underneath(qapp, jerusalem, db):
    wv = _week(qapp, db)
    col = _column(wv, FRI)
    [(y, _, _)] = col._holy_overlay.lines()
    spot = QPoint(20, round(y))

    # Qt's own hit test: the overlay is transparent to the mouse, so what is
    # under the line is the event block, not the line.
    target = col.childAt(spot)
    assert target is not None and target is not col._holy_overlay
    assert getattr(target, "event", {}).get("title") == "Cooking for Shabbat"

    opened = []
    col.event_clicked.connect(opened.append)
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFrom(col, spot))
    qapp.processEvents()
    assert [e["title"] for e in opened] == ["Cooking for Shabbat"]


def test_the_setting_off_draws_nothing(qapp, jerusalem, db):
    wv = _week(qapp, db, show=False)
    assert all(c._holy_overlay.lines() == [] for c in wv._day_columns)
    img = _column(wv, FRI).grab().toImage()
    h = _column(wv, FRI).hour_height
    y = round((LIT.hour * 3600 + LIT.minute * 60 + LIT.second) / 3600 * h)
    assert not any(_is_yellow(img.pixelColor(6, yy)) for yy in (y - 1, y, y + 1))


def test_day_view_draws_the_same_line(qapp, jerusalem, db):
    from assistant.calendar_ui.day_view import DayView
    dv = DayView(db)
    dv.resize(700, 900)
    dv.apply_hebrew_config(HebrewCalendarConfig())
    dv.navigate(FRI)
    dv.show()
    qapp.processEvents()
    tl = dv._timeline
    [(y, label, _)] = tl._holy_overlay.lines()
    assert y == pytest.approx((18 * 3600 + 41 * 60 + 20) / 3600 * tl.hour_height)
    assert label == "Shabbat · 18:41"


def test_a_moved_phone_moves_the_line_on_the_next_tick(qapp, jerusalem, db, monkeypatch):
    """The API writes the phone's position; the GUI notices on its minute tick."""
    wv = _week(qapp, db)
    [(before, _, _)] = _column(wv, FRI)._holy_overlay.lines()
    haifa = ob.ObservanceSettings(latitude=32.7940, longitude=34.9896,
                                  timezone="Asia/Jerusalem", city="Haifa")
    monkeypatch.setattr(ob, "settings_from_config", lambda cfg=None: haifa)
    wv._tick_time()
    [(after, _, _)] = _column(wv, FRI)._holy_overlay.lines()
    assert after != pytest.approx(before)


def test_where_observance_cannot_be_computed_nothing_is_drawn(qapp, monkeypatch, db):
    polar = ob.ObservanceSettings(latitude=78.22, longitude=15.65, timezone="Arctic/Longyearbyen")
    monkeypatch.setattr(ob, "settings_from_config", lambda cfg=None: polar)
    assert holy_times.windows_for(datetime.date(2026, 6, 1), datetime.date(2026, 6, 30)) == []


def test_the_settings_switch_is_on_by_default_and_saves_off(qapp, tmp_path, monkeypatch):
    """Settings → Hebrew Calendar, clicked and saved like a person would."""
    from PyQt6.QtWidgets import QCheckBox, QPushButton

    from assistant import config_store
    from assistant.calendar_ui.settings_dialog import open_settings
    from tests.unit.test_settings_observance import SAMPLE, _Window, _click, _drive

    cfg = tmp_path / "config.yaml"
    cfg.write_text(SAMPLE + "hebrew_calendar:\n  show_holidays: true\n")
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg): real(updates, path))

    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        cb = dlg.findChild(QCheckBox, "shabbat_lines_cb")
        assert cb is not None, "Shabbat-lines checkbox missing from the dialog"
        seen["initially"] = cb.isChecked()
        _click(cb)
        seen["after_click"] = cb.isChecked()
        save = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Save Config")
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen == {"initially": True, "after_click": False}
    assert window._config.hebrew_calendar.show_shabbat_times is False
    section = cfg.read_text().split("hebrew_calendar:")[1]
    assert "show_shabbat_times: false" in section


def test_the_line_is_in_the_places_wall_clock_whatever_this_machines_zone(qapp, db, monkeypatch):
    """Events are naive wall-clock times and the series skip compares against
    candle lighting's wall clock at the observance place — so the line is drawn
    there too, not converted into the Mac's own zone. Converting put Shabbat
    at noon when the clock was New York and the place Jerusalem."""
    monkeypatch.setattr(ob, "settings_from_config", lambda cfg=None: JERUSALEM)
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        wv = _week(qapp, db)
        col = _column(wv, FRI)
        [(y, label, _)] = col._holy_overlay.lines()
        assert label == "Shabbat · 18:41"
        assert y == pytest.approx((18 * 3600 + 41 * 60 + 20) / 3600 * col.hour_height)
    finally:
        monkeypatch.undo()
        time.tzset()
