"""The Mac event dialog's Repeat + End repeat rows, driven by real clicks.

Per this repo's rule that a UI test which never sends an input event tests
nothing: every choice here is typed into the combo (its incremental search,
the same way the Settings tests drive theirs), and Save is a mouse click on
the Save button.

What was wrong before (2026-09-25): the only end control was a bare "Until"
date with no "Never", so opening an open-ended series showed today + 1 year and
saving any other change wrote that year back as a real end date. There was no
caption saying the end date is booked or that Shabbat is skipped, and nothing
said a row belonged to a series until Save asked.
"""
from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QDate, Qt                                    # noqa: E402
from PyQt6.QtTest import QTest                                        # noqa: E402
from PyQt6.QtWidgets import (                                         # noqa: E402
    QApplication, QComboBox, QDateEdit, QDialogButtonBox, QLabel,
)

from assistant.calendar_ui.event_dialog import (                      # noqa: E402
    EventDialog, repeat_hint, repeat_rule_changed, series_badge,
)
from assistant.db import CalendarDB                                   # noqa: E402

START = dt.date(2026, 10, 5)          # a Monday


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    return CalendarDB(path=str(tmp_path / "dialog.db"))


def _pick(combo: QComboBox, text: str) -> None:
    """Type `text` into the closed combo — its incremental search selects the
    row, a real key event the way test_settings_notifications drives combos
    (a popup row click does not land under the offscreen platform)."""
    assert combo.findText(text) >= 0, f"{text!r} not offered"
    combo.setFocus()
    QTest.keyClicks(combo, text)
    QApplication.processEvents()
    assert combo.currentText() == text


def _save(dlg: EventDialog) -> dict:
    buttons = dlg.findChild(QDialogButtonBox)
    QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Save),
                     Qt.MouseButton.LeftButton)
    assert dlg.event_data is not None
    return dlg.event_data


def _new(app, db) -> EventDialog:
    dlg = EventDialog(default_date=START, default_time=dt.time(9, 0), db=db)
    dlg.show()
    QTest.keyClicks(dlg.findChild(type(dlg._title), "title_input"), "Standup")
    return dlg


def _repeat_combo(dlg) -> QComboBox:
    # The Repeat combo is the one offering the cadences.
    return next(c for c in dlg.findChildren(QComboBox) if c.findText("Weekly") >= 0)


def test_the_end_rows_appear_only_once_something_repeats(app, db):
    dlg = _new(app, db)
    ends = dlg.findChild(QComboBox, "ends_mode")
    assert not ends.isVisible()
    _pick(_repeat_combo(dlg), "Weekly")
    assert ends.isVisible()
    hint = dlg.findChild(QLabel, "repeat_hint")
    assert hint.isVisible() and "Shabbat" in hint.text()
    dlg.close()


def test_a_new_weekly_event_defaults_to_ending_a_month_later(app, db):
    dlg = _new(app, db)
    _pick(_repeat_combo(dlg), "Weekly")
    until = dlg.findChild(QDateEdit, "ends_date")
    assert until.isVisible()
    assert until.date() == QDate(2026, 11, 5)
    hint = dlg.findChild(QLabel, "repeat_hint").text()
    assert "every Monday" in hint and "through Thu 5 Nov" in hint
    assert "end date is included" in hint
    data = _save(dlg)
    assert data["recurrence"] == "weekly"
    assert data["recurrence_end"] == "2026-11-05"


def test_choosing_never_hides_the_date_and_saves_no_end(app, db):
    dlg = _new(app, db)
    _pick(_repeat_combo(dlg), "Daily")
    _pick(dlg.findChild(QComboBox, "ends_mode"), "Never")
    assert not dlg.findChild(QDateEdit, "ends_date").isVisible()
    assert "no end date" in dlg.findChild(QLabel, "repeat_hint").text()
    data = _save(dlg)
    assert data["recurrence"] == "daily" and data["recurrence_end"] == ""


def test_the_end_can_never_be_before_the_event(app, db):
    dlg = _new(app, db)
    _pick(_repeat_combo(dlg), "Weekly")
    until = dlg.findChild(QDateEdit, "ends_date")
    assert until.minimumDate() == QDate(2026, 10, 5)
    # Moving the event later drags an end that would now precede it along.
    dlg._date.setDate(QDate(2026, 12, 7))
    assert until.minimumDate() == QDate(2026, 12, 7)
    assert until.date() >= QDate(2026, 12, 7)
    dlg.close()


def test_an_open_ended_series_stays_open_ended_when_edited(app, db):
    """The regression: this used to save today + 1 year as the end."""
    sid = db.create_event_from_dict({
        "title": "Gym", "date": "2026-10-05", "start_time": "07:00",
        "end_time": "08:00", "recurrence": "weekly", "recurrence_end": ""})
    event = db.get_event(sid)
    dlg = EventDialog(event=event, db=db)
    dlg.show()
    assert dlg.findChild(QComboBox, "ends_mode").currentText() == "Never"
    badge = dlg.findChild(QLabel, "series_badge")
    assert badge is not None and "Part of a weekly series · no end date" in badge.text()
    assert "updates the whole series" in dlg.findChild(QLabel, "repeat_hint").text()
    data = _save(dlg)
    assert data["recurrence_end"] == ""
    assert not repeat_rule_changed(event, data)


def test_a_one_off_made_to_repeat_is_offered_an_end(app, db):
    eid = db.create_event_from_dict({
        "title": "Dentist", "date": "2026-10-05", "start_time": "09:00",
        "end_time": "10:00"})
    dlg = EventDialog(event=db.get_event(eid), db=db)
    dlg.show()
    assert dlg.findChild(QLabel, "series_badge") is None
    _pick(_repeat_combo(dlg), "Monthly")
    assert dlg.findChild(QComboBox, "ends_mode").currentText() == "On date"
    data = _save(dlg)
    assert (data["recurrence"], data["recurrence_end"]) == ("monthly", "2026-11-05")


def test_stopping_a_series_says_what_saving_removes(app, db):
    sid = db.create_event_from_dict({
        "title": "Gym", "date": "2026-10-05", "start_time": "07:00",
        "end_time": "08:00", "recurrence": "weekly", "recurrence_end": "2026-10-26"})
    dlg = EventDialog(event=db.get_event(sid), db=db)
    dlg.show()
    _pick(_repeat_combo(dlg), "None")
    hint = dlg.findChild(QLabel, "repeat_hint")
    assert hint.isVisible() and "stops the series here" in hint.text()
    assert not dlg.findChild(QComboBox, "ends_mode").isVisible()
    dlg.close()


def test_setting_an_end_on_a_series_is_a_rule_change(app, db):
    sid = db.create_event_from_dict({
        "title": "Gym", "date": "2026-10-05", "start_time": "07:00",
        "end_time": "08:00", "recurrence": "weekly", "recurrence_end": ""})
    event = db.get_event(sid)
    dlg = EventDialog(event=event, db=db)
    dlg.show()
    _pick(dlg.findChild(QComboBox, "ends_mode"), "On date")
    dlg.findChild(QDateEdit, "ends_date").setDate(QDate(2026, 10, 26))
    data = _save(dlg)
    assert data["recurrence_end"] == "2026-10-26"
    assert repeat_rule_changed(event, data)
    # ... and window.py hands a rule change to update_series, whole series
    # (it pops `id` and `series_id` off the dialog's data first, as here):
    db.update_series(sid, sid, **{k: v for k, v in data.items()
                                  if k not in ("id", "series_id")})
    dates = sorted(e["date"] for e in db.get_series_events(sid))
    assert dates == ["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"]


# ---------------------------------------------------------------- the words

def test_hint_wording():
    today = dt.date(2026, 9, 25)
    assert repeat_hint("", START, None) == ""
    assert "stops the series here" in repeat_hint("", START, None, editing_series=True)
    assert repeat_hint("weekly", START, dt.date(2026, 10, 30), today=today) == (
        "Repeats every Monday through Fri 30 Oct, then stops — the end date is "
        "included. Skips Shabbat and yom tov.")
    assert "next year" not in repeat_hint("monthly", START, None, today=today)
    assert "every month on the 5th" in repeat_hint("monthly", START, None)
    assert "2027" in repeat_hint("daily", START, dt.date(2027, 1, 4), today=today)
    assert "every Tuesday and Thursday" in repeat_hint(
        "weekly", START, None, recur_days="tuesday,thursday")


def test_badge_wording():
    today = dt.date(2026, 9, 25)
    assert series_badge(None) == ""
    assert series_badge({"id": 3, "series_id": None, "recurrence": ""}) == ""
    assert series_badge({"series_id": 3, "recurrence": "weekly",
                         "recurrence_end": "2026-10-30"}, today=today) \
        == "Part of a weekly series · ends Fri 30 Oct"
