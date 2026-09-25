"""The Mac's event-default controls (DEVQA Q51), driven with real input.

Per this repo's rule, a UI test that never sends a mouse event tests nothing:
the spin boxes and line edits are typed into with QTest.keyClick/keyClicks,
sections are opened and Save is pressed with QTest.mouseClick.

Three surfaces:

* Settings › Events — two spin boxes, saved into `events:` in config.yaml;
* the category editor — optional length / gap per category, empty = global;
* the New Event dialog — the end defaults to start + the length (by the
  title's category), follows the start and title, and stops following once
  the user sets an end.

Every write lands in tmp_path: `MACALENDAR_CONFIG` and the config writer are
both aimed at a scratch config.yaml, and the categories store at a scratch json.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil

import pytest

pytest.importorskip("PyQt6")

import yaml                                                          # noqa: E402
from PyQt6.QtCore import QPoint, Qt, QTimer                          # noqa: E402
from PyQt6.QtTest import QTest                                       # noqa: E402
from PyQt6.QtWidgets import (                                        # noqa: E402
    QApplication, QDialogButtonBox, QLineEdit, QPushButton, QSpinBox, QToolButton, QWidget,
)

from assistant import config_store, event_defaults                   # noqa: E402
from assistant.actions.calendar import categories as cat             # noqa: E402
from assistant.config import (                                       # noqa: E402
    AudioConfig, EventsConfig, HebrewCalendarConfig, NLUConfig, NotificationsConfig, UIConfig,
)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    shutil.copyfile(os.path.join(_REPO, "config.example.yaml"), cfg)
    monkeypatch.setenv("MACALENDAR_CONFIG", str(cfg))
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg): real(updates, path))
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(cat, "CATEGORIES_PATH", str(tmp_path / "categories.json"))
    cat._cache = None
    cat._mtime = -1.0
    event_defaults._cfg_cache.clear()
    yield cfg
    cat._cache = None
    cat._mtime = -1.0
    event_defaults._cfg_cache.clear()


def _set_events(cfg, **values) -> None:
    data = yaml.safe_load(cfg.read_text()) or {}
    data["events"] = values
    cfg.write_text(yaml.safe_dump(data))
    st = os.stat(cfg)
    os.utime(cfg, (st.st_atime, st.st_mtime + 1))


def _retype(widget, text: str) -> None:
    """Clear a field and type into it with real key events: select-all (the
    platform's SelectAll chord — Qt maps ControlModifier to Cmd on macOS),
    then type over it. End + Backspace does not work on a spin box with a
    suffix: the cursor lands past " min" and the suffix is not deletable."""
    widget.setFocus()
    QTest.keyClick(widget, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    if text:
        QTest.keyClicks(widget, text)
    else:
        QTest.keyClick(widget, Qt.Key.Key_Backspace)
    QApplication.processEvents()


# ── Settings › Events ─────────────────────────────────────────────────


class _Tts:
    mute, voice, rate = False, "Samantha", 200


class _Pipeline:
    def __init__(self):
        self._tts = _Tts()


class _Observance:
    enabled = True


class _Config:
    def __init__(self):
        self.theme = "dark"
        self.ui = UIConfig()
        self.audio = AudioConfig()
        self.nlu = NLUConfig()
        self.hebrew_calendar = HebrewCalendarConfig()
        self.observance = _Observance()
        self.notifications = NotificationsConfig()
        self.events = EventsConfig()


class _Btn:
    def setVisible(self, _visible):
        pass


class _Window(QWidget):
    def __init__(self):
        super().__init__()
        self._pipeline = _Pipeline()
        self._config = _Config()
        self._dark = True
        self._view_mode = "month"
        self._view_btn_coursework = _Btn()
        self._view_btn_workout = _Btn()
        self._view_btn_timer = _Btn()

    def show_toast(self, *_):
        pass

    def refresh_calendar(self):
        pass

    def _apply_ui_config(self):
        pass

    def _apply_theme(self, _dark):
        pass

    def _set_view(self, _mode):
        pass


def _drive(interact, failures):
    def _go():
        dlg = QApplication.activeModalWidget()
        if dlg is None:
            QTimer.singleShot(10, _go)
            return
        try:
            interact(dlg)
        except Exception as e:               # noqa: BLE001 — re-raised below
            failures.append(e)
            dlg.reject()
    QTimer.singleShot(0, _go)


def _open_events_section(dlg) -> None:
    header = dlg.findChild(QToolButton, "section_header_events")
    assert header is not None, "no Events section in Settings"
    if not header.isChecked():
        QTest.mouseClick(header, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(10, header.height() // 2))
    assert header.isChecked(), "clicking the header did not open the section"


def test_settings_show_the_values_from_the_file(app, scratch):
    """Read from config.yaml, not the window's startup config — the phone can
    change them while the calendar is open."""
    from assistant.calendar_ui.settings_dialog import open_settings
    _set_events(scratch, event_length_minutes=50, chain_gap_minutes=20)
    window = _Window()                        # its in-memory config still says 60 / 0
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        _open_events_section(dlg)
        seen["length"] = dlg.findChild(QSpinBox, "events_length_spin").value()
        seen["gap"] = dlg.findChild(QSpinBox, "events_gap_spin").value()
        dlg.reject()

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]
    assert (seen["length"], seen["gap"]) == (50, 20)


def test_typing_and_saving_writes_the_events_section(app, scratch):
    from assistant.calendar_ui.settings_dialog import open_settings
    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        _open_events_section(dlg)
        length = dlg.findChild(QSpinBox, "events_length_spin")
        gap = dlg.findChild(QSpinBox, "events_gap_spin")
        assert length is not None and gap is not None
        _retype(length, "45")
        _retype(gap, "15")
        seen["typed"] = (length.value(), gap.value())
        save = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Save Config")
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen["typed"] == (45, 15), "the keys did not reach the spin boxes"
    data = yaml.safe_load(scratch.read_text())
    assert data["events"] == {"event_length_minutes": 45, "chain_gap_minutes": 15}
    # The comments in the example survived the save.
    assert "# How long an event lasts when nobody said" in scratch.read_text()
    # ...and the engine's read sees it.
    assert event_defaults.length_minutes() == 45
    assert event_defaults.gap_minutes() == 15
    assert window._config.events.event_length_minutes == 45


# ── the category editor ───────────────────────────────────────────────


def _save_category(dlg) -> None:
    box = dlg.findChild(QDialogButtonBox)
    QTest.mouseClick(box.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton)


def test_category_editor_sets_a_length_and_gap(app, scratch):
    from assistant.calendar_ui.categories_dialog import CategoryEditDialog
    _set_events(scratch, event_length_minutes=45, chain_gap_minutes=0)
    dlg = CategoryEditDialog(cat.get("Fitness"))
    dlg.show()
    length = dlg.findChild(QLineEdit, "cat_length_edit")
    gap = dlg.findChild(QLineEdit, "cat_gap_edit")
    assert length.text() == "" and length.placeholderText() == "global (45)"
    _retype(length, "90")
    _retype(gap, "10")
    _save_category(dlg)

    got = cat.get("Fitness")
    assert got["default_minutes"] == 90 and got["chain_gap_minutes"] == 10
    assert "gym" in got["keywords"], "saving the times dropped the keywords"
    assert event_defaults.length_minutes("Fitness") == 90


def test_category_editor_empty_field_goes_back_to_global(app, scratch):
    from assistant.calendar_ui.categories_dialog import CategoryEditDialog
    _set_events(scratch, event_length_minutes=45, chain_gap_minutes=0)
    cat.upsert("Fitness", default_minutes=90, chain_gap_minutes=10)
    dlg = CategoryEditDialog(cat.get("Fitness"))
    dlg.show()
    length = dlg.findChild(QLineEdit, "cat_length_edit")
    assert length.text() == "90"
    _retype(length, "")
    _save_category(dlg)

    got = cat.get("Fitness")
    assert "default_minutes" not in got
    assert got["chain_gap_minutes"] == 10          # the untouched field kept
    assert event_defaults.length_minutes("Fitness") == 45


# ── the New Event dialog ──────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    from assistant.db import CalendarDB
    return CalendarDB(path=str(tmp_path / "dialog.db"))


def _hhmm(edit) -> str:
    return edit.time().toString("HH:mm")


def test_new_event_end_follows_the_length_setting_and_the_category(app, scratch, db):
    from assistant.calendar_ui.event_dialog import EventDialog
    _set_events(scratch, event_length_minutes=45, chain_gap_minutes=0)
    cat.upsert("Fitness", default_minutes=90)

    dlg = EventDialog(default_date=dt.date(2026, 10, 1), default_time=dt.time(9, 0), db=db)
    dlg.show()
    assert _hhmm(dlg._end) == "09:45"               # the global length, not an hour

    title = dlg.findChild(QLineEdit, "title_input")
    title.setFocus()
    QTest.keyClicks(title, "gym")
    QApplication.processEvents()
    assert _hhmm(dlg._end) == "10:30"               # Fitness's own 90 minutes

    # Moving the start keeps the length.
    dlg._start.setFocus()
    QTest.keyClick(dlg._start, Qt.Key.Key_Home)     # the hour section
    QTest.keyClick(dlg._start, Qt.Key.Key_Up)
    QApplication.processEvents()
    assert _hhmm(dlg._start) == "10:00"
    assert _hhmm(dlg._end) == "11:30"


def test_a_hand_set_end_is_never_overwritten(app, scratch, db):
    from assistant.calendar_ui.event_dialog import EventDialog
    _set_events(scratch, event_length_minutes=45, chain_gap_minutes=0)
    cat.upsert("Fitness", default_minutes=90)

    dlg = EventDialog(default_date=dt.date(2026, 10, 1), default_time=dt.time(9, 0), db=db)
    dlg.show()
    dlg._end.setFocus()
    QTest.keyClick(dlg._end, Qt.Key.Key_Home)
    QTest.keyClick(dlg._end, Qt.Key.Key_Up)         # 09:45 -> 10:45, by hand
    QApplication.processEvents()
    assert _hhmm(dlg._end) == "10:45"

    title = dlg.findChild(QLineEdit, "title_input")
    title.setFocus()
    QTest.keyClicks(title, "gym")
    QApplication.processEvents()
    assert _hhmm(dlg._end) == "10:45", "a title change overwrote the end the user set"


def test_editing_an_existing_event_keeps_its_end(app, scratch, db):
    from assistant.calendar_ui.event_dialog import EventDialog
    _set_events(scratch, event_length_minutes=45, chain_gap_minutes=0)
    eid = db.create_event_from_dict({"title": "gym", "date": "2026-10-01",
                                     "start_time": "09:00", "end_time": "09:20"})
    dlg = EventDialog(event=db.get_event(eid), db=db)
    dlg.show()
    title = dlg.findChild(QLineEdit, "title_input")
    title.setFocus()
    QTest.keyClicks(title, " session")
    QApplication.processEvents()
    assert _hhmm(dlg._end) == "09:20"
