"""The Mac's Settings, laid out like the phone's — driven with real clicks.

Gil, 2026-09-29: *"fix UI of settings on macos app to be like ios app UI of
settings"*. A sidebar of rows with coloured tiles, grouped as the phone
groups them, and one page per row. It replaced the folding sections of
2026-09-17 (*"a minimize on each section"*): the sidebar keeps every name on
screen and the page beside it.

Per this repo's rule — a UI test that never sends a mouse event tests nothing —
rows are clicked with `QTest.mouseClick`, and the assertions are about what a
person would SEE. The remembered page writes through `_ui_state()`, which
`conftest.py` redirects to scratch.
"""
from __future__ import annotations

import pathlib

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt, QTimer                          # noqa: E402
from PyQt6.QtTest import QTest                                       # noqa: E402
from PyQt6.QtWidgets import (                                        # noqa: E402
    QApplication, QGroupBox, QToolButton, QWidget,
)

from assistant.calendar_ui.settings_dialog import open_settings, _ui_state  # noqa: E402
from assistant.config import (                                       # noqa: E402
    AudioConfig, HebrewCalendarConfig, NLUConfig, UIConfig,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _clean_ui_state():
    """Each test starts with every section open, and leaves nothing behind —
    these tests would otherwise order-depend on each other through the very
    persistence they are checking."""
    s = _ui_state()
    s.clear()
    s.sync()
    yield
    s = _ui_state()
    s.clear()
    s.sync()


# ── the least window open_settings(self) needs (see test_settings_observance) ──

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
        finally:
            dlg.reject()
    QTimer.singleShot(0, _go)


def _header(dlg, name: str) -> QToolButton:
    h = dlg.findChild(QToolButton, f"section_header_{name}")
    assert h is not None, f"no collapsible header for {name!r}"
    return h


def _page_of(dlg, header: QToolButton) -> QWidget:
    """The page this row shows: the settings stack's current page after a click."""
    from PyQt6.QtWidgets import QStackedWidget
    return dlg.findChild(QStackedWidget, "settings_pages").currentWidget()


SECTIONS = ["appearance", "tabs", "hebrew_calendar", "events", "notifications",
            "voice", "assistant", "connected_calendars", "server"]


# ── the tests ────────────────────────────────────────────────────────


def test_every_section_has_a_row_with_a_tile_and_one_page_shows(app):
    failures = []

    def interact(dlg):
        from PyQt6.QtWidgets import QStackedWidget
        pages = dlg.findChild(QStackedWidget, "settings_pages")
        assert pages is not None and pages.count() == len(SECTIONS)
        for name in SECTIONS:
            h = _header(dlg, name)
            assert not h.icon().isNull(), f"{name} has no tile"
        checked = [n for n in SECTIONS if _header(dlg, n).isChecked()]
        assert checked == ["appearance"], "the first page, and only it, is selected"
    _drive(interact, failures)
    open_settings(_Window())
    if failures:
        raise failures[0]


def test_clicking_a_row_shows_its_page_and_only_its_page(app):
    failures = []

    def interact(dlg):
        before = _page_of(dlg, _header(dlg, "appearance"))
        h = _header(dlg, "notifications")
        QTest.mouseClick(h, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(10, h.height() // 2))
        QApplication.processEvents()
        assert h.isChecked() and not _header(dlg, "appearance").isChecked()
        page = _page_of(dlg, h)
        assert page is not before and page.isVisible() and not before.isVisible()
    _drive(interact, failures)
    open_settings(_Window())
    if failures:
        raise failures[0]


def test_the_page_you_left_open_is_open_next_time(app):
    failures = []

    def pick(dlg):
        h = _header(dlg, "voice")
        QTest.mouseClick(h, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(10, h.height() // 2))
    _drive(pick, failures)
    open_settings(_Window())

    def check(dlg):
        assert _header(dlg, "voice").isChecked()
    _drive(check, failures)
    open_settings(_Window())
    if failures:
        raise failures[0]


def test_the_rows_are_grouped_as_the_phone_groups_them():
    from assistant.calendar_ui.settings_dialog import _SECTION_GROUPS
    assert [g for g, _ in _SECTION_GROUPS] == [
        "Calendar", "Notifications & tabs", "Assistant", "Connection"]
    ios = (pathlib.Path(__file__).resolve().parents[2]
           / "MACalendar-iOS/MACalendar-iOS/Views/SettingsView.swift").read_text()
    for heading in ("Calendar", "Assistant", "Connection"):
        assert f'"{heading}"' in ios or f'Text("{heading}")' in ios, heading
