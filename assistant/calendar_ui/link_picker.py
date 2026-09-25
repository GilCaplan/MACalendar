"""Choosing the other half of a to-do <-> event link, on the Mac.

Gil, 2026-09-25: *"add a linking feature between todo and events, they can be
linked and the same thing"*. The link itself is `db.link_todo` (see "A to-do
and an event linked as ONE THING" there); this is only the list you pick from,
shared by the event dialog ("Link a to-do…") and a task's right-click menu
("Link to an event…"). A filter box on top, because the event list spans two
months and the task list can be long.
"""
from __future__ import annotations

import datetime
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLineEdit, QListWidget,
                             QListWidgetItem, QVBoxLayout)

#: The window of events offered: a week back (a to-do for something that just
#: happened) to two months ahead.
EVENTS_BACK, EVENTS_AHEAD = 7, 60


def event_label(ev: dict) -> str:
    try:
        day = datetime.date.fromisoformat(ev.get("date") or "").strftime("%a %b %-d")
    except ValueError:
        day = ev.get("date") or ""
    clock = (ev.get("start_time") or "")[:5]
    return f"{ev.get('title') or 'Untitled'} — {day}{' ' + clock if clock else ''}"


def todo_label(todo: dict) -> str:
    due = todo.get("due_date") or ""
    return f"{todo.get('title') or 'Untitled'}{' — due ' + due if due else ''}"


class LinkPickerDialog(QDialog):
    """Pick one row. `chosen_id` is its id, or None if cancelled."""

    def __init__(self, title: str, rows: "list[tuple[int, str]]", parent=None,
                 empty: str = "Nothing to link to") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(420, 420)
        self.chosen_id: Optional[int] = None
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setObjectName("link_filter")
        self.filter.setPlaceholderText("Filter")
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setObjectName("link_list")
        for rid, label in rows:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, rid)
            self.list.addItem(item)
        if not rows:
            none = QListWidgetItem(empty)
            none.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(none)
        self.list.itemDoubleClicked.connect(lambda _i: self._accept())
        self.list.itemActivated.connect(lambda _i: self._accept())
        lay.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Link")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _accept(self) -> None:
        item = self.list.currentItem()
        rid = item.data(Qt.ItemDataRole.UserRole) if item else None
        if rid is None:
            return
        self.chosen_id = int(rid)
        self.accept()


def event_rows(db, around: Optional[datetime.date] = None) -> "list[tuple[int, str]]":
    today = datetime.date.today()
    lo = min(around or today, today) - datetime.timedelta(days=EVENTS_BACK)
    hi = max(around or today, today) + datetime.timedelta(days=EVENTS_AHEAD)
    return [(int(e["id"]), event_label(e)) for e in db.get_events_between(lo, hi)]


def todo_rows(db) -> "list[tuple[int, str]]":
    return [(int(t["id"]), todo_label(t)) for t in db.get_todos(None)
            if not t.get("linked_event_id")]
