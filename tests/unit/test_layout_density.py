"""Row 36 — "Compact layout density" reaches the calendar views.

It used to change only the Settings dialog's own spacing. It now tightens the
rows where a view lists things (Month's pills, Tasks, the agenda), and Month
shows as many pills as FIT rather than a fixed three — the fixed three drew
the third pill and "+N more" over each other in a short cell, at either
density. Rendered both ways and looked at before this shipped.
"""
from __future__ import annotations

import copy
import datetime

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _cell(app, n_events, height, dense, font_month=19):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtWidgets import QApplication
    from assistant.config import UIConfig
    from assistant.calendar_ui.month_view import DayCell
    ui = UIConfig()
    ui.compact_ui, ui.font_month = dense, font_month
    cell = DayCell(datetime.date(2026, 10, 6), True)
    cell._ui_config = ui
    cell.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    cell.resize(150, height)
    cell.show()
    cell.load_events([{"id": i, "title": f"event {i}", "date": "2026-10-06",
                       "start_time": f"{8 + i:02d}:00", "end_time": f"{9 + i:02d}:00",
                       "color": "#3b82f6"} for i in range(n_events)])
    app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    app.processEvents()
    return cell


def _kids(cell):
    lay = cell._event_layout
    return [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget()]


@pytest.mark.parametrize("dense", [False, True])
@pytest.mark.parametrize("height", [88, 100, 140, 220])
def test_a_month_cell_never_draws_past_its_own_bottom(app, dense, height):
    cell = _cell(app, 7, height, dense)
    kids = _kids(cell)
    assert kids, "something is drawn"
    bottom = max(w.geometry().bottom() for w in kids)
    assert bottom <= cell.height(), (height, dense, bottom)
    more = [w for w in kids if "more" in (getattr(w, "text", lambda: "")() or "")]
    pills = len(kids) - len(more)
    assert pills + (int(more[0].text().split("+")[1].split()[0]) if more else 0) == 7


def test_compact_fits_at_least_as_many_and_never_taller_pills(app):
    for fm in (11, 13, 19):
        normal, dense = _cell(app, 7, 160, False, fm), _cell(app, 7, 160, True, fm)
        n_pills = lambda c: sum(1 for w in _kids(c) if "more" not in (getattr(w, "text", lambda: "")() or ""))
        assert n_pills(dense) >= n_pills(normal)
        assert max(w.height() for w in _kids(dense)) <= 20


def test_a_cell_that_grows_shows_more(app):
    cell = _cell(app, 7, 100, False)
    before = len(_kids(cell))
    cell.resize(150, 260)
    app.processEvents()
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    app.processEvents()
    assert len(_kids(cell)) > before


def test_tasks_and_agenda_rows_are_tighter_when_compact(app):
    from assistant.calendar_ui.agenda_view import _EventRow
    ev = {"id": 1, "title": "Gym", "date": "2026-10-06", "start_time": "08:00",
          "end_time": "09:00", "color": "#22c55e"}
    assert _EventRow(ev, compact=True).sizeHint().height() < _EventRow(ev).sizeHint().height()
