"""Dragging an event onto a calendar view must never crash the app.

A user reported the Mac app crashing mid-drag (2026-09-14). The crash report
(SIGABRT) traced through PyQt6's own abort path:

    abort() <- QMessageLogger::fatal() <- pyqt6_err_print()
            <- sipQWidget::dropEvent(QDropEvent*)

PyQt6 aborts the whole process whenever a Python exception escapes an
overridden Qt virtual method — the C++ object is left in an undefined state,
so it treats that as unrecoverable rather than just failing the one call.
`dropEvent` on all three calendar views (day/week/month) had no try/except at
all, and `event_rescheduled.emit(...)` runs its connected slot SYNCHRONOUSLY,
so a failure two calls away (a DB write in `window._on_event_rescheduled`)
would unwind straight back through `dropEvent` and take the process with it.

These don't reproduce the exact exception (the crash report has no Python
traceback — PyQt6 prints it to raw stderr via the default excepthook, which
the launcher script doesn't capture), but they pin the actual guarantee that
matters: whatever a drop's mime data contains, `dropEvent` must return
normally, never raise.
"""

from __future__ import annotations

import datetime

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QByteArray, QMimeData, QPointF  # noqa: E402
from PyQt6.QtGui import QDropEvent, QDragMoveEvent  # noqa: E402
from PyQt6.QtCore import Qt as QtCore_Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from assistant.calendar_ui.day_view import DayTimeline  # noqa: E402
from assistant.calendar_ui.week_view import DayColumn  # noqa: E402
from assistant.calendar_ui.month_view import DayCell  # noqa: E402

TODAY = datetime.date.today()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _drop_event(payload: bytes, pos=QPointF(10, 10)) -> QDropEvent:
    mime = QMimeData()
    mime.setData("application/x-event-id", QByteArray(payload))
    ev = QDropEvent(
        pos, QtCore_Qt.DropAction.MoveAction, mime,
        QtCore_Qt.MouseButton.LeftButton, QtCore_Qt.KeyboardModifier.NoModifier,
    )
    # QDropEvent stores a raw pointer to `mime`; nothing else in the caller
    # keeps the Python QMimeData object alive, so without this it gets
    # garbage-collected and the very first `event.mimeData()` call in
    # dropEvent() segfaults on the dangling pointer. Keep it alive as long
    # as the event is.
    ev._mime_keepalive = mime
    return ev


# Every widget gets the same table: the exact malformed payloads that would
# raise inside the old, unguarded body (empty, non-numeric, a real int with
# surrounding junk a stray extra drag could plausibly produce).
BAD_PAYLOADS = [
    b"",                # ValueError: invalid literal for int() with base 10: ''
    b"not-a-number",    # ValueError
    b"12abc",           # ValueError
    b"1;2",             # ValueError
]


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_day_view_drop_never_raises(qapp, payload):
    w = DayTimeline(TODAY)
    w.dropEvent(_drop_event(payload))  # must return normally, not raise


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_week_view_drop_never_raises(qapp, payload):
    w = DayColumn(TODAY, parent=None)
    w.dropEvent(_drop_event(payload))


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_month_view_drop_never_raises(qapp, payload):
    w = DayCell(TODAY, is_current_month=True)
    w.dropEvent(_drop_event(payload))


def test_day_view_drop_off_the_top_does_not_go_negative(qapp):
    """A drop above y=0 (e.g. autoscroll during a fast drag) used to be able
    to produce a negative hour that got written straight into the DB as an
    invalid time string. `y` is now clamped before the hour math."""
    w = DayTimeline(TODAY)
    seen = {}
    w.event_rescheduled.connect(lambda eid, updates: seen.update(updates))
    w.dropEvent(_drop_event(b"1", pos=QPointF(10, -500)))
    assert seen.get("start_time", "00:00") >= "00:00"


def test_week_view_drop_off_the_top_does_not_go_negative(qapp):
    w = DayColumn(TODAY, parent=None)
    seen = {}
    w.event_rescheduled.connect(lambda eid, updates: seen.update(updates))
    w.dropEvent(_drop_event(b"1", pos=QPointF(10, -500)))
    assert seen.get("start_time", "00:00") >= "00:00"


def test_valid_drop_still_reschedules(qapp):
    """The guard must not swallow a normal, successful drop."""
    w = DayColumn(TODAY, parent=None)
    seen = {}
    w.event_rescheduled.connect(lambda eid, updates: seen.update({"id": eid, **updates}))
    w.dropEvent(_drop_event(b"42", pos=QPointF(10, w.hour_height * 3)))
    assert seen.get("id") == 42
    assert seen.get("date") == TODAY.isoformat()
    assert "start_time" in seen
