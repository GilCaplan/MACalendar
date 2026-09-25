"""The calendar opens on the view chosen in Settings → Appearance — Week by
default (Gil, 2026-09-24: "set default on week, and also add toggle option in
settings in existing section")."""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from assistant.config import UIConfig, load_config  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_default_is_week():
    assert UIConfig().start_view == "week"


@pytest.mark.parametrize("mode", ["week", "month", "day"])
def test_the_window_opens_on_the_configured_view(app, mode):
    from assistant.calendar_ui.window import CalendarWindow
    cfg = load_config().model_copy(deep=True)
    cfg.ui.start_view = mode
    w = CalendarWindow(config=cfg)
    try:
        assert w._view_mode == mode
        assert w._stack.currentWidget() is {"week": w._week_view, "month": w._month_view,
                                            "day": w._day_view}[mode]
    finally:
        w.close()
        w.deleteLater()
