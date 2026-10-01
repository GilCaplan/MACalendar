"""Settings › Hebrew Calendar: the master switch, the per-day "keep engine
events off this day" switches in the "This week" box, and the list of days
you changed (DEVQA Q59, Q60), driven with real input.

A UI test that never sends a mouse event tests nothing: the section header,
the week box's header, its checkboxes, Add, a list row, Remove and Save are
all clicked with QTest.mouseClick, and the date picker and the mode combo are
stepped with key presses.

Every write lands in tmp_path: the config writer at a scratch config.yaml
(the `scratch` fixture shared with the event-defaults UI tests) and the
day-override store at a scratch json — never ~/.assistant_tools.
"""
from __future__ import annotations

import datetime as dt
import json
import os

import pytest

pytest.importorskip("PyQt6")

import yaml                                                          # noqa: E402
from PyQt6.QtCore import QDate, QPoint, Qt                           # noqa: E402
from PyQt6.QtTest import QTest                                       # noqa: E402
from PyQt6.QtWidgets import (                                        # noqa: E402
    QApplication, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QLabel, QListWidget,
    QPushButton, QToolButton, QWidget,
)

from assistant import observance                                     # noqa: E402
from tests.unit.test_event_defaults_ui import (                      # noqa: E402,F401
    _drive, _Window, app, scratch,
)

SUKKOT_WEEK = (dt.date(2026, 9, 20), dt.date(2026, 10, 3), "Sukkot")


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "observance_exceptions.json"
    monkeypatch.setattr(observance, "EXCEPTIONS_PATH", str(path))
    # The box shows the current week; pin it to Sukkot 2026 so the test does
    # not change meaning with the calendar.
    monkeypatch.setattr(observance, "week_span", lambda today=None, israel=True: SUKKOT_WEEK)
    observance._exc_cache.clear()
    yield path
    observance._exc_cache.clear()


def test_the_real_store_is_scratched_by_conftest():
    real = os.path.expanduser("~/.assistant_tools")
    assert os.environ["MACALENDAR_OBSERVANCE_EXCEPTIONS"]
    assert not os.environ["MACALENDAR_OBSERVANCE_EXCEPTIONS"].startswith(real)


def _open_hebrew_section(dlg) -> None:
    header = dlg.findChild(QToolButton, "section_header_hebrew_calendar")
    assert header is not None, "no Hebrew Calendar section in Settings"
    if not header.isVisible():
        # The sidebar's groups start folded (TASKS 50): open Calendar first,
        # as a person would.
        from PyQt6.QtWidgets import QAbstractButton
        group = dlg.findChild(QAbstractButton, "settings_group_calendar")
        QTest.mouseClick(group, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(10, group.height() // 2))
        QApplication.processEvents()
    if not header.isChecked():
        QTest.mouseClick(header, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(10, header.height() // 2))
    assert header.isChecked(), "clicking the header did not open the section"
    QApplication.processEvents()


def _click(widget) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def _click_checkbox(cb) -> None:
    # On the box itself, not the middle of the text: that is where a user
    # clicks, and a click past the text's end misses on some styles.
    QTest.mouseClick(cb, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(8, cb.height() // 2))
    QApplication.processEvents()


def _save(dlg) -> None:
    save = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Save Config")
    QTest.mouseClick(save, Qt.MouseButton.LeftButton)


def _rows(lst) -> list:
    return [lst.item(i).text() for i in range(lst.count())]


def test_the_week_box_folds_open_and_flips_days_either_way(app, scratch, store):
    from assistant.calendar_ui.settings_dialog import open_settings
    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        _open_hebrew_section(dlg)
        header = dlg.findChild(QToolButton, "observance_week_header")
        body = dlg.findChild(QWidget, "observance_week_body")
        seen["title"] = header.text()
        seen["folded"] = not body.isVisible()
        QTest.mouseClick(header, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(10, header.height() // 2))
        QApplication.processEvents()
        seen["open"] = body.isVisible()
        boxes = {d: dlg.findChild(QCheckBox, f"observance_day_{d}")
                 for d in ("2026-09-20", "2026-09-26", "2026-09-29", "2026-10-03")}
        seen["rows"] = len([c for c in body.findChildren(QCheckBox)])
        seen["defaults"] = {d: c.isChecked() for d, c in boxes.items()}
        seen["all_visible"] = all(c.isVisible() for c in boxes.values())

        _click_checkbox(boxes["2026-09-29"])     # keep a chol hamoed day off
        _click_checkbox(boxes["2026-10-03"])     # let the engine book Shmini Atzeret
        lst = dlg.findChild(QListWidget, "observance_overrides_list")
        seen["list"] = _rows(lst)
        labels = [lbl for lbl in body.findChildren(QLabel) if lbl.text().startswith("Tue 29 Sep")]
        seen["tue_label"] = labels[0].text()
        seen["tue_bold"] = labels[0].font().bold()
        _save(dlg)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen["title"] == "This week — all of Sukkot"
    assert seen["folded"], "the week box should start folded"
    assert seen["open"], "clicking its header did not open the week box"
    assert seen["rows"] == 14, "Sun 20 Sep through Shmini Atzeret is 14 days"
    assert seen["all_visible"]
    assert seen["defaults"] == {"2026-09-20": False, "2026-09-26": True,
                                "2026-09-29": False, "2026-10-03": True}
    assert seen["list"] == [
        "Tue 29 Sep 2026 — Chol hamoed Succos: kept off",
        "Sat 3 Oct 2026 — Shabbat · Shmini Atzeres: engine may book",
    ]
    assert seen["tue_label"] == "Tue 29 Sep — Chol hamoed Succos  (changed)"
    assert seen["tue_bold"]
    assert json.loads(store.read_text()) == {"allow": ["2026-10-03"], "keep_off": ["2026-09-29"]}
    assert observance.kept_off(dt.date(2026, 9, 29))
    assert not observance.kept_off(dt.date(2026, 10, 3))


def test_add_and_remove_days_and_switch_the_rule_off(app, scratch, store):
    from assistant.calendar_ui.settings_dialog import open_settings
    # Q59's shape, as the phone or an older Mac wrote it: read as "allow".
    store.write_text(json.dumps({"dates": ["2026-10-10"]}))
    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        _open_hebrew_section(dlg)
        cb = dlg.findChild(QCheckBox, "observance_enabled_cb")
        lst = dlg.findChild(QListWidget, "observance_overrides_list")
        picker = dlg.findChild(QDateEdit, "observance_override_date")
        mode = dlg.findChild(QComboBox, "observance_override_mode")
        add = dlg.findChild(QPushButton, "observance_override_add")
        remove = dlg.findChild(QPushButton, "observance_override_remove")
        assert None not in (cb, lst, picker, mode, add, remove)
        seen["visible"] = all(w.isVisible() for w in (cb, lst, picker, mode, add, remove))
        seen["shown"] = _rows(lst)
        seen["remove_enabled_before"] = remove.isEnabled()

        # Mon 28 Sep, stepped a day forward with the keyboard -> Tue 29 Sep.
        picker.setDate(QDate(2026, 9, 28))
        picker.setFocus()
        picker.setCurrentSection(QDateTimeEdit.Section.DaySection)
        QTest.keyClick(picker, Qt.Key.Key_Up)
        seen["picked"] = picker.date().toString("yyyy-MM-dd")
        seen["mode"] = mode.currentData()           # "Keep off" is first
        _click(add)
        seen["after_add"] = [lst.item(i).data(Qt.ItemDataRole.UserRole)
                             for i in range(lst.count())]

        # Allow on a Sunday that is open anyway: nothing to add, and it says so.
        picker.setDate(QDate(2026, 10, 11))
        mode.setFocus()
        QTest.keyClick(mode, Qt.Key.Key_Down)
        seen["mode2"] = mode.currentData()
        _click(add)
        seen["after_noop"] = lst.count()
        status = dlg.findChild(QLabel, "observance_override_status")
        seen["status"] = status.text() if status.isVisible() else ""

        # Select 10 Oct by clicking its row, then Remove.
        row = next(i for i in range(lst.count())
                   if lst.item(i).data(Qt.ItemDataRole.UserRole) == "2026-10-10")
        rect = lst.visualItemRect(lst.item(row))
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rect.center())
        seen["selected"] = lst.currentRow() == row
        seen["remove_enabled"] = remove.isEnabled()
        _click(remove)
        seen["after_remove"] = _rows(lst)

        assert cb.isChecked()
        _click(cb)                                  # switch the rule off
        seen["checked"] = cb.isChecked()
        _save(dlg)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen["visible"], "opening the section did not show the controls"
    assert seen["shown"] == ["Sat 10 Oct 2026 — Shabbat: engine may book"]
    assert seen["remove_enabled_before"] is False, "Remove was live with nothing selected"
    assert seen["picked"] == "2026-09-29", "the key did not reach the date picker"
    assert seen["mode"] == "keep_off" and seen["mode2"] == "allow"
    assert seen["after_add"] == ["2026-09-29", "2026-10-10"]
    assert seen["after_noop"] == 2, "an allow on an open day is not an override"
    assert seen["status"] == "Sun 11 Oct is already open to the engine by default."
    assert seen["selected"] and seen["remove_enabled"]
    assert seen["after_remove"] == ["Tue 29 Sep 2026 — Chol hamoed Succos: kept off"]
    assert seen["checked"] is False

    # The store the engine reads, in the new shape, and the switch in config.yaml.
    assert json.loads(store.read_text()) == {"allow": [], "keep_off": ["2026-09-29"]}
    assert observance.day_overrides() == {dt.date(2026, 9, 29): "keep_off"}
    assert yaml.safe_load(scratch.read_text())["observance"]["enabled"] is False


def test_opening_and_saving_does_not_rewrite_the_days(app, scratch, store):
    """Save writes the overrides only when they were edited here, so days the
    phone changed while the dialog was open are not overwritten."""
    from assistant.calendar_ui.settings_dialog import open_settings
    window = _Window()
    failures: list = []

    def interact(dlg):
        _open_hebrew_section(dlg)
        _save(dlg)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]
    assert not store.exists(), "an untouched list was written on Save"
