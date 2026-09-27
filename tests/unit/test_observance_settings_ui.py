"""Settings › Hebrew Calendar: the Shabbat / yom tov switch and its exception
days (DEVQA Q59), driven with real input.

A UI test that never sends a mouse event tests nothing: the section header,
the checkbox, Add, a list row, Remove and Save are all clicked with
QTest.mouseClick, and the date picker is stepped with a key press.

Every write lands in tmp_path: the config writer at a scratch config.yaml
(the `scratch` fixture shared with the event-defaults UI tests) and the
exception store at a scratch json — never ~/.assistant_tools.
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
    QApplication, QCheckBox, QDateEdit, QDateTimeEdit, QListWidget, QPushButton, QToolButton,
)

from assistant import observance                                     # noqa: E402
from tests.unit.test_event_defaults_ui import (                      # noqa: E402,F401
    _drive, _Window, app, scratch,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "observance_exceptions.json"
    monkeypatch.setattr(observance, "EXCEPTIONS_PATH", str(path))
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
    if not header.isChecked():
        QTest.mouseClick(header, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(10, header.height() // 2))
    assert header.isChecked(), "clicking the header did not open the section"
    QApplication.processEvents()


def _click(widget) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def _save(dlg) -> None:
    save = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Save Config")
    QTest.mouseClick(save, Qt.MouseButton.LeftButton)


def test_add_and_remove_exception_days_and_switch_the_rule_off(app, scratch, store):
    from assistant.calendar_ui.settings_dialog import open_settings
    observance.set_exception_dates(["2026-10-10"])     # already there: a plain Shabbat
    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        _open_hebrew_section(dlg)
        cb = dlg.findChild(QCheckBox, "observance_enabled_cb")
        lst = dlg.findChild(QListWidget, "observance_exceptions_list")
        picker = dlg.findChild(QDateEdit, "observance_exception_date")
        add = dlg.findChild(QPushButton, "observance_exception_add")
        remove = dlg.findChild(QPushButton, "observance_exception_remove")
        assert None not in (cb, lst, picker, add, remove)
        seen["label"] = cb.text()
        seen["visible"] = all(w.isVisible() for w in (cb, lst, picker, add, remove))
        seen["shown"] = [lst.item(i).text() for i in range(lst.count())]
        seen["remove_enabled_before"] = remove.isEnabled()

        # Friday 2 Oct, stepped a day forward with the keyboard -> Sat 3 Oct
        # (Shabbat, and Shemini Atzeret in Israel).
        picker.setDate(QDate(2026, 10, 2))
        picker.setFocus()
        picker.setCurrentSection(QDateTimeEdit.Section.DaySection)
        QTest.keyClick(picker, Qt.Key.Key_Up)
        seen["picked"] = picker.date().toString("yyyy-MM-dd")
        _click(add)
        seen["after_add"] = [lst.item(i).data(Qt.ItemDataRole.UserRole)
                             for i in range(lst.count())]
        seen["added_label"] = lst.item(0).text()

        # Select 10 Oct by clicking its row, then Remove.
        row = next(i for i in range(lst.count())
                   if lst.item(i).data(Qt.ItemDataRole.UserRole) == "2026-10-10")
        rect = lst.visualItemRect(lst.item(row))
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rect.center())
        seen["selected"] = lst.currentRow() == row
        seen["remove_enabled"] = remove.isEnabled()
        _click(remove)
        seen["after_remove"] = [lst.item(i).data(Qt.ItemDataRole.UserRole)
                                for i in range(lst.count())]

        assert cb.isChecked()
        _click(cb)                                  # switch the rule off
        seen["checked"] = cb.isChecked()
        _save(dlg)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen["label"] == "Keep engine-made events off Shabbat && yom tov"
    assert seen["visible"], "opening the section did not show the controls"
    assert seen["shown"] == ["Sat 10 Oct 2026 — Shabbat"]
    assert seen["remove_enabled_before"] is False, "Remove was live with nothing selected"
    assert seen["picked"] == "2026-10-03", "the key did not reach the date picker"
    assert seen["after_add"] == ["2026-10-03", "2026-10-10"]
    assert seen["added_label"].startswith("Sat 3 Oct 2026 — Shabbat · ")
    assert seen["selected"] and seen["remove_enabled"]
    assert seen["after_remove"] == ["2026-10-03"]
    assert seen["checked"] is False

    # The store the engine reads, and the switch in config.yaml.
    assert json.loads(store.read_text()) == {"dates": ["2026-10-03"]}
    assert observance.exception_dates() == frozenset({dt.date(2026, 10, 3)})
    assert yaml.safe_load(scratch.read_text())["observance"]["enabled"] is False


def test_opening_and_saving_does_not_rewrite_the_exception_days(app, scratch, store):
    """Save writes the list only when it was edited here, so a list the phone
    changed while the dialog was open is not overwritten by an untouched one."""
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


def test_an_ordinary_day_says_so(app, scratch, store):
    """A date that is not Shabbat, yom tov or a fast has nothing to switch
    off, and its row says so; chol hamoed is one of those days."""
    from assistant.calendar_ui.settings_dialog import open_settings
    observance.set_exception_dates(["2026-09-29"])     # chol hamoed Sukkot
    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        _open_hebrew_section(dlg)
        lst = dlg.findChild(QListWidget, "observance_exceptions_list")
        seen["shown"] = [lst.item(i).text() for i in range(lst.count())]
        dlg.reject()

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]
    assert seen["shown"] == ["Tue 29 Sep 2026 — an ordinary day"]
