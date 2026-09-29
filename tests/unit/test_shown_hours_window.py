"""Show hours through the REAL window, not the views alone (Gil, 2026-09-29:
"The display from time x to y doesn't work"). The views' own tests passed
while the calendar app was not running the code at all, so this builds
CalendarWindow with the setting in its config — the way the app starts — and
changes it the way Settings does, and reads what Week and Day then show."""

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent

from assistant.config import load_config


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _settle(app):
    for _ in range(6):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _top_hour(view):
    return view._window.first + view._scroll.verticalScrollBar().value() / view._hour_height


@pytest.mark.parametrize("first,last", [(7, 24), (9, 18), (6, 22)])
def test_the_window_opens_showing_the_configured_hours(app, first, last):
    from assistant.calendar_ui.window import CalendarWindow
    cfg = load_config().model_copy(deep=True)
    cfg.ui.hours_from, cfg.ui.hours_to = first, last
    w = CalendarWindow(config=cfg)
    w.resize(1300, 900)
    w.show()
    _settle(app)
    for view in (w._week_view, w._day_view):
        assert view._hours == (first, last), type(view).__name__
        assert view._span[0] <= first and view._span[1] >= last
        if view._span == (first, last):           # no event outside widened it
            assert _top_hour(view) == first
            assert view._window.height() == (last - first) * view._hour_height
    w.close()


def test_changing_the_setting_applies_at_once(app):
    from assistant.calendar_ui.window import CalendarWindow
    cfg = load_config().model_copy(deep=True)
    w = CalendarWindow(config=cfg)
    w.resize(1300, 900)
    w.show()
    _settle(app)
    w._config.ui.hours_from, w._config.ui.hours_to = 8, 20       # what Settings ▸ Save writes
    w._apply_visible_hours()
    _settle(app)
    assert w._week_view._hours == (8, 20) and w._day_view._hours == (8, 20)
    w.close()


def test_picking_the_hours_in_settings_and_saving_shows_them(app):
    """The whole path a person takes: Settings ▸ Appearance, the two menus,
    Save Config — through the real dialog on the real window, with clicks."""
    import os
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton
    from assistant.calendar_ui.settings_dialog import open_settings
    from assistant.calendar_ui.window import CalendarWindow
    w = CalendarWindow(config=load_config().model_copy(deep=True))
    w.resize(1300, 900)
    w.show()
    _settle(app)

    class _Tts:                              # Settings opens only with a pipeline
        mute, voice, rate = False, "Samantha", 200

    class _Pipeline:
        _tts = _Tts()
    w._pipeline = _Pipeline()
    seen = {}

    def _go():
        from PyQt6.QtWidgets import QDialog
        dlg = QApplication.activeModalWidget() or next(
            (x for x in QApplication.topLevelWidgets() if isinstance(x, QDialog) and x.isVisible()),
            None)
        if dlg is None:
            seen["tries"] = seen.get("tries", 0) + 1
            if seen["tries"] < 300:
                QTimer.singleShot(10, _go)
            return
        try:
            a, b = dlg.findChild(QComboBox, "hours_from"), dlg.findChild(QComboBox, "hours_to")
            a.setCurrentIndex(a.findData(7))
            b.setCurrentIndex(b.findData(24))
            save = next(x for x in dlg.findChildren(QPushButton) if x.text() == "Save Config")
            QTest.mouseClick(save, Qt.MouseButton.LeftButton)
            seen["ok"] = True
        finally:
            if dlg.isVisible():
                dlg.reject()
    QTimer.singleShot(0, _go)
    open_settings(w)
    _settle(app)
    assert seen.get("ok"), "the dialog never came up"
    assert w._week_view._hours == (7, 24) and w._day_view._hours == (7, 24)
    saved = open(os.environ["MACALENDAR_CONFIG"]).read()
    assert "hours_from: 7" in saved and "hours_to: 24" in saved
    w.close()
