"""The Mac window clean-up (Gil, 2026-09-28: "revamp and clean the UI … it's
messy and not so nice to look at"), held in place.

- The month grid put every day one column LEFT of its header: Sunday sat in
  the 26px week-number slot and Saturday's column was always empty.
- The feature panels (Tasks, Timer, Account…) crowded the toolbar's view
  strip; they are the sidebar's section list now, and the toolbar keeps the
  calendar's four views, search, one "More" menu and the account/settings.
- The mini-calendar's weekday row was Qt's default white bar in dark mode.
"""
from __future__ import annotations

import datetime

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QWidget     # noqa: E402

from assistant.calendar_ui.window import CalendarWindow   # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_every_day_sits_under_its_own_header(qapp):
    from assistant.calendar_ui.month_view import DayCell, MonthView

    class _DB:
        def __getattr__(self, name):
            return lambda *a, **k: []
    view = MonthView(_DB())
    view.navigate(2026, 9)
    off = 1 if view._show_wknums else 0
    for col in range(7):
        item = view._grid.itemAtPosition(0, col + off)
        assert item is not None and isinstance(item.widget(), DayCell), col
        # Sunday-first: column 0 is Sunday (weekday 6), column 6 Saturday (5)
        assert item.widget().date.weekday() == (6 + col) % 7
    if off:
        wk = view._grid.itemAtPosition(0, 0).widget()
        assert not isinstance(wk, DayCell), "a day cell is in the week-number column"


def _window_parts(qapp):
    from assistant.calendar_ui.sidebar import Sidebar
    win = CalendarWindow.__new__(CalendarWindow)
    QWidget.__init__(win)
    win._config = None
    win._pipeline = None
    win._dark = True
    bar = win._build_toolbar()
    win._sidebar = Sidebar()
    win._build_sidebar_nav()
    return win, bar


def test_feature_panels_are_sidebar_sections_not_toolbar_buttons(qapp):
    from PyQt6.QtWidgets import QPushButton
    win, bar = _window_parts(qapp)
    toolbar_labels = {b.text() for b in bar.findChildren(QPushButton)}
    assert {"Month", "Week", "Day", "Agenda"} <= toolbar_labels
    assert "Tasks" not in toolbar_labels and "Account" not in toolbar_labels
    for mode in ("tasks", "account"):
        btn = getattr(win, f"_view_btn_{mode}")
        assert btn.parent() is not None and win._sidebar.isAncestorOf(btn), mode
    assert win._sidebar.isAncestorOf(win._nav_calendar_btn)


def test_the_occasional_tools_are_one_labelled_menu(qapp):
    from PyQt6.QtWidgets import QPushButton
    win, bar = _window_parts(qapp)
    labels = {b.text() for b in bar.findChildren(QPushButton)}
    assert not labels & {"🔗", "🏷", "📖", "Import"}
    actions = [a.text() for a in win._more_menu.actions() if a.text()]
    assert actions[:3] == ["Import events…", "Connected calendars…", "Tag suggestion history…"]


def test_the_mini_calendars_weekday_row_follows_the_theme(qapp):
    from assistant.calendar_ui import styles as _styles
    from assistant.calendar_ui.sidebar import MiniCalendar
    cal = MiniCalendar()
    cal.apply_theme(True)
    bg = cal._cal.headerTextFormat().background().color().name().lower()
    assert bg == _styles.D_GRAY_BG.lower()
