"""Settings ▸ Assistant: how long the thinking card stays after a command.

The card used to stay until closed and cluttered the screen (Gil, 2026-10-29:
"the review panel kinda clutters and gets in the way"); it now fades away
`ui.thinking_hide_after_sec` after a command, and this is where it is set.
Real key events into the real dialog, saved with the real button.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

import yaml  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDoubleSpinBox  # noqa: E402

from assistant import config_store  # noqa: E402
from assistant.calendar_ui.settings_dialog import open_settings  # noqa: E402
from tests.unit._settings_driver import drive_settings  # noqa: E402
from tests.unit.test_settings_notifications import _Window  # noqa: E402

SAMPLE = """\
theme: "dark"

ui:
  show_thinking: true
  thinking_hide_after_sec: 6   # seconds
"""


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_typing_a_new_delay_and_saving_writes_it(app, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(SAMPLE)
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg): real(updates, path))
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(cfg))

    window = _Window()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        spin = dlg.findChild(QDoubleSpinBox, "thinking_hide_spin")
        assert spin is not None, "the fade delay is missing from Settings"
        seen["shown"] = spin.value()
        spin.lineEdit().selectAll()
        QTest.keyClicks(spin, "15")
        seen["typed"] = spin.value()
        QTest.mouseClick(dlg.save_button, Qt.MouseButton.LeftButton)

    drive_settings(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen == {"shown": 6, "typed": 15}
    data = yaml.safe_load(cfg.read_text())
    assert data["ui"]["thinking_hide_after_sec"] == 15
    assert "# seconds" in cfg.read_text()


def test_a_hand_set_value_survives_an_unrelated_save(app, tmp_path, monkeypatch):
    """An int box 0-120 rewrote 2.5 to 2 and 300 to 120 on any Save."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(SAMPLE.replace("thinking_hide_after_sec: 6", "thinking_hide_after_sec: 2.5"))
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg): real(updates, path))
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(cfg))
    window = _Window()
    window._config.ui.thinking_hide_after_sec = 2.5
    failures: list = []
    drive_settings(lambda dlg: QTest.mouseClick(dlg.save_button, Qt.MouseButton.LeftButton),
                   failures)
    open_settings(window)
    if failures:
        raise failures[0]
    assert yaml.safe_load(cfg.read_text())["ui"]["thinking_hide_after_sec"] == 2.5
