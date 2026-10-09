"""Settings ▸ Voice ▸ "While listening" (ui.mic_visual) — the Mac's choice of
how the mic shows it is hearing you (Gil, 2026-10-09).

Gil: "it should fall under system, I think, or voice. See what makes more
sense." Voice: it sits with the other recording options there, where the
phone keeps the same picker. Driven like a person would: open the Assistant
group, open Voice, change the combo with a key press, click Save.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

import yaml                                                          # noqa: E402
from PyQt6.QtCore import QPoint, Qt                                  # noqa: E402
from PyQt6.QtTest import QTest                                       # noqa: E402
from PyQt6.QtWidgets import (                                        # noqa: E402
    QAbstractButton, QApplication, QComboBox, QScrollArea, QToolButton,
)

from tests.unit.test_event_defaults_ui import (                      # noqa: E402,F401
    _Window, _drive, app, scratch,
)


def _click(widget) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(10, widget.height() // 2))
    QApplication.processEvents()


def _open_voice(dlg) -> QComboBox:
    combo = dlg.findChild(QComboBox, "mic_visual")
    assert combo is not None, "no While listening control in Settings"
    header = dlg.findChild(QToolButton, "section_header_voice")
    assert header is not None, "no Voice section in Settings"
    if not header.isVisible():
        _click(dlg.findChild(QAbstractButton, "settings_group_assistant"))
    if not header.isChecked():
        _click(header)
    assert combo.isVisible(), "opening Voice did not show it"
    # The page it is on: each section is a scroll area whose first row is its
    # heading. (Not "hidden until Voice opens" — the dialog reopens on the
    # page it was last left on, so that would depend on the test before.)
    page = combo
    while page is not None and not isinstance(page, QScrollArea):
        page = page.parentWidget()
    heading = page.widget().layout().itemAt(0).widget().text()
    assert heading == "Voice", f"it is on the {heading!r} page"
    return combo


def test_it_lives_in_voice_and_starts_on_the_bars(app, scratch):
    from assistant.calendar_ui.settings_dialog import open_settings
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        combo = _open_voice(dlg)
        seen["value"] = combo.currentData()
        seen["options"] = [combo.itemData(i) for i in range(combo.count())]
        dlg.reject()

    _drive(interact, failures)
    open_settings(_Window())
    if failures:
        raise failures[0]
    assert seen["value"] == "bars"                     # the default Gil chose
    assert seen["options"] == ["bars", "rings", "sunburst", "dots"]


def test_choosing_a_style_and_saving_writes_it(app, scratch):
    from assistant.calendar_ui.settings_dialog import open_settings
    window = _Window()
    failures: list = []

    def interact(dlg):
        combo = _open_voice(dlg)
        combo.setFocus()
        QTest.keyClick(combo, Qt.Key.Key_End)        # the last style: dancing dots
        QApplication.processEvents()
        assert combo.currentData() == "dots"
        QTest.mouseClick(dlg.save_button, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]
    saved = yaml.safe_load(scratch.read_text())
    assert saved["ui"]["mic_visual"] == "dots"
    assert window._config.ui.mic_visual == "dots"     # the open window follows at once
