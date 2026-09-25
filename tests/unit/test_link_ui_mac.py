"""Linking a to-do and an event on the Mac, driven by real clicks and keys.

Gil, 2026-09-25: *"add a linking feature between todo and events, they can be
linked and the same thing"*. Two ways in: the event dialog's To-do row, and a
task's right-click menu. Both act at once on the database.
"""
from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt, QTimer                           # noqa: E402
from PyQt6.QtGui import QContextMenuEvent                             # noqa: E402
from PyQt6.QtTest import QTest                                        # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton        # noqa: E402

from assistant.actions.calendar.intent import CalendarIntent          # noqa: E402
from assistant.calendar_ui.event_dialog import EventDialog            # noqa: E402
from assistant.db import CalendarDB                                   # noqa: E402

DAY = (dt.date.today() + dt.timedelta(days=2)).isoformat()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    return CalendarDB(path=str(tmp_path / "link.db"))


def _event(db, title="dentist"):
    return db.create_event(CalendarIntent(title=title, date=DAY, start_time="14:00",
                                          end_time="15:00"))


def _click(w, name):
    btn = w.findChild(QPushButton, name)
    assert btn is not None and btn.isVisible(), f"no visible {name}"
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


_ERRORS: list = []


def _when_modal(act):
    """Run `act(picker)` once the link picker is up. A failure inside a Qt
    callback is swallowed and would leave `exec()` waiting forever, so it is
    recorded and the picker closed instead; `_raise_errors` re-raises it."""
    from assistant.calendar_ui.link_picker import LinkPickerDialog

    def poll():
        dlg = next((w for w in QApplication.topLevelWidgets()
                    if isinstance(w, LinkPickerDialog) and w.isVisible()), None)
        if dlg is None:
            QTimer.singleShot(10, poll)
            return
        try:
            act(dlg)
        except BaseException as exc:          # noqa: BLE001 — re-raised below
            _ERRORS.append(exc)
            dlg.reject()
    QTimer.singleShot(0, poll)


def _raise_errors():
    if _ERRORS:
        raise _ERRORS.pop()


def _choose(picker, needle, want):
    QTest.keyClicks(picker.filter, needle)
    shown = [picker.list.item(i) for i in range(picker.list.count())
             if not picker.list.item(i).isHidden()]
    assert [i.text().split(" — ")[0] for i in shown] == [want]
    rect = picker.list.visualItemRect(shown[0])
    QTest.mouseClick(picker.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    from PyQt6.QtWidgets import QDialogButtonBox
    box = picker.findChild(QDialogButtonBox)
    QTest.mouseClick(box.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)


def test_the_event_dialog_adds_and_unlinks_a_todo(app, db):
    ev = _event(db)
    dlg = EventDialog(event=db.get_event(ev), db=db)
    dlg.show()
    _click(dlg, "add_linked_todo")
    todo = db.linked_todo(ev)
    assert todo["title"] == "dentist" and todo["due_date"] == DAY
    assert "dentist" in dlg.findChild(QLabel, "linked_todo_label").text()
    _click(dlg, "unlink_todo")
    assert db.linked_todo(ev) is None and db.get_todo(todo["id"]) is not None
    assert dlg.findChild(QPushButton, "add_linked_todo") is not None
    dlg.reject()


def test_the_event_dialog_links_an_existing_todo_through_the_picker(app, db):
    ev = _event(db)
    db.create_todo("buy milk")
    want = db.create_todo("book the dentist")
    dlg = EventDialog(event=db.get_event(ev), db=db)
    dlg.show()

    _when_modal(lambda picker: _choose(picker, "dentist", "book the dentist"))
    _click(dlg, "link_existing_todo")
    _raise_errors()
    assert db.linked_todo(ev)["id"] == want
    dlg.reject()


def test_a_read_only_event_offers_no_link(app, db):
    ev = _event(db)
    with db._conn() as conn:
        conn.execute("UPDATE events SET source = 'ics' WHERE id = ?", (ev,))
    dlg = EventDialog(event=db.get_event(ev), db=db)
    assert dlg.findChild(QPushButton, "add_linked_todo") is None


def _menu_pick(widget, text):
    """Open the row's context menu and trigger the item named `text` by key."""
    def poll():
        menu = QApplication.activePopupWidget()
        if menu is None:
            QTimer.singleShot(10, poll)
            return
        (act,) = [a for a in menu.actions() if a.text() == text]
        menu.setActiveAction(act)
        QTest.keyClick(menu, Qt.Key.Key_Return)
    QTimer.singleShot(0, poll)
    widget.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                              QPoint(5, 5), widget.mapToGlobal(QPoint(5, 5))))
    QApplication.processEvents()


def test_the_task_menu_puts_it_on_the_calendar_and_unlinks(app, db):
    from assistant.calendar_ui.todo_view import TodoItemWidget
    todo_id = db.create_todo("renew the passport", due_date=DAY)
    row = TodoItemWidget(db.get_todo(todo_id), db)
    row.show()
    assert not row._link_chip.isVisible()
    _menu_pick(row, "Add to calendar (linked)")
    ev = db.get_todo(todo_id)["linked_event_id"]
    got = db.get_event(ev)
    assert (got["title"], got["date"], got["start_time"]) == ("renew the passport", DAY, "09:00")
    assert row._link_chip.isVisible()
    _menu_pick(row, "Unlink from event")
    assert db.get_todo(todo_id)["linked_event_id"] is None
    assert not row._link_chip.isVisible()


def test_the_task_menu_links_to_an_existing_event(app, db):
    from assistant.calendar_ui.todo_view import TodoItemWidget
    ev = _event(db, "haircut")
    todo_id = db.create_todo("haircut")
    row = TodoItemWidget(db.get_todo(todo_id), db)
    row.show()

    _when_modal(lambda picker: _choose(picker, "hair", "haircut"))
    _menu_pick(row, "Link to an event…")
    _raise_errors()
    assert db.get_todo(todo_id)["linked_event_id"] == ev
