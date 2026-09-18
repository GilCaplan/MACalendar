"""Folding a settings section away, driven with real clicks.

Gil, 2026-09-17: *"perhaps add a minimize on each section starting to be a lot
of things there"*. Six sections on the Mac had grown past one screenful.

Per this repo's rule — a UI test that never sends a mouse event tests nothing —
the header is clicked with `QTest.mouseClick` rather than by calling the slot,
and the assertions are about what a person would SEE: does the body disappear,
does the arrow turn, and is it still folded the next time the dialog opens.

The persistence half matters more than it looks. It writes through
`_ui_state()`, whose default is the user's REAL macOS preferences —
`conftest.py` redirects it to `MACALENDAR_UI_STATE` in the scratch directory,
and this test would be reaching into the app Gil has open without it.
"""
from __future__ import annotations

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


def _body_of(header: QToolButton) -> QWidget:
    """The widget a header folds: its section box's second child widget."""
    box = header.parent()
    assert isinstance(box, QGroupBox)
    bodies = [w for w in box.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
              if w is not header]
    assert bodies, "section has no body widget"
    return bodies[0]


# ── the tests ────────────────────────────────────────────────────────


def test_every_section_starts_folded_and_has_a_fold_header(app):
    """Gil, 2026-09-18: "Default is minimized please".

    This asserted the opposite until then — "a first run must show every
    section open" — on the reasoning that an all-folded screen looks empty.
    It reads as a list of section NAMES, which is what you are scanning for;
    six open bodies push five of the six names off the screen.
    """
    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        names = ["appearance", "tabs", "hebrew_calendar", "notifications",
                 "voice", "assistant"]
        seen["headers"] = {n: _header(dlg, n).isChecked() for n in names}
        seen["arrows"] = {n: _header(dlg, n).arrowType() for n in names}

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert not any(seen["headers"].values()), \
        f"a first run must show every section folded, got {seen['headers']}"
    assert all(a == Qt.ArrowType.RightArrow for a in seen["arrows"].values())


def test_clicking_a_header_shows_that_section_and_turns_its_arrow(app):
    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        h = _header(dlg, "voice")
        body = _body_of(h)
        seen["before"] = (h.isChecked(), body.isVisible(), h.arrowType())
        QTest.mouseClick(h, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(8, h.height() // 2))
        seen["after"] = (h.isChecked(), body.isVisible(), h.arrowType())
        # ...and again, which must put it back.
        QTest.mouseClick(h, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(8, h.height() // 2))
        seen["again"] = (h.isChecked(), body.isVisible(), h.arrowType())
        # ...and the section next to it is untouched throughout.
        seen["neighbour"] = _body_of(_header(dlg, "appearance")).isVisible()

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen["before"] == (False, False, Qt.ArrowType.RightArrow)
    assert seen["after"] == (True, True, Qt.ArrowType.DownArrow), \
        "a real click must reveal the body and turn the arrow"
    assert seen["again"] == (False, False, Qt.ArrowType.RightArrow), \
        "clicking a second time must fold it back"
    assert seen["neighbour"] is False, "opening one section moved another"


def test_a_section_you_opened_is_still_open_next_time(app):
    """The whole point, the way round it now runs: open what you use and it
    stays open, while everything you never touched stays folded.

    Before the default flipped this folded a section and checked it stayed
    folded — which a `return False` would also have passed. Opening is the
    direction that now carries information.
    """
    window = _Window()
    failures: list = []

    def unfold(dlg):
        h = _header(dlg, "tabs")
        QTest.mouseClick(h, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(8, h.height() // 2))
        assert h.isChecked()

    _drive(unfold, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    # A SECOND dialog, built fresh from the stored state.
    seen: dict = {}

    def reopen(dlg):
        seen["tabs"] = _header(dlg, "tabs").isChecked()
        seen["tabs_body"] = _body_of(_header(dlg, "tabs")).isVisible()
        seen["voice"] = _header(dlg, "voice").isChecked()

    failures = []
    _drive(reopen, failures)
    open_settings(_Window())
    if failures:
        raise failures[0]

    assert seen["tabs"] is True, "the choice was forgotten between openings"
    assert seen["tabs_body"] is True
    assert seen["voice"] is False, "a section nobody opened came back open"
