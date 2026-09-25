"""Create / edit calendar event dialog."""

from __future__ import annotations

import datetime
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QDate, QTime

import assistant.calendar_ui.styles as _styles
from assistant.calendar_ui.styles import BLUE, EVENT_COLORS, GRAY_BORDER, GRAY_TEXT
from assistant.calendar_ui.dialog_utils import install_enter_confirms


# The Repeat combo's rows, in order. The product's four cadences (CLAUDE.md,
# "Recurring events") — offering a fifth would promise what the db can't keep.
_CADENCES = ["", "daily", "weekly", "monthly", "yearly"]


def _day_label(d: datetime.date, today: Optional[datetime.date] = None) -> str:
    """'Fri 30 Oct', with the year only when it isn't this one."""
    today = today or datetime.date.today()
    text = f"{d:%a} {d.day} {d:%b}"
    return text if d.year == today.year else f"{text} {d.year}"


def _cadence_phrase(recurrence: str, start: datetime.date, recur_days: str = "") -> str:
    days = [x.strip().capitalize() for x in (recur_days or "").split(",") if x.strip()]
    if recurrence == "weekly" and len(days) > 1:
        return "every " + ", ".join(days[:-1]) + " and " + days[-1]
    return {"daily": "every day",
            "weekly": f"every {start:%A}",
            "monthly": f"every month on the {start.day}{_ordinal(start.day)}",
            "yearly": f"every year on {start.day} {start:%B}"}.get(recurrence, "")


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def repeat_hint(recurrence: str, start: datetime.date,
                end: Optional[datetime.date], editing_series: bool = False,
                today: Optional[datetime.date] = None, recur_days: str = "") -> str:
    """The caption under End repeat: what saving will book, in words.

    The end date is INCLUSIVE — "ends on 30 Oct" books the 30th — which is
    how `db._create_series_instances` has always counted it, and the reason
    the hint says "through", the word the project reads as keeping its day
    (CLAUDE.md: "until" excludes the day it names, "through" keeps it).
    """
    if not recurrence:
        return ("Saving stops the series here — the events after this one are removed."
                if editing_series else "")
    what = _cadence_phrase(recurrence, start, recur_days)
    if end is None:
        text = f"Repeats {what} with no end date — the next 12 months are booked."
    else:
        text = (f"Repeats {what} through {_day_label(end, today)}, then stops — "
                "the end date is included.")
    text += " Skips Shabbat and yom tov."
    if editing_series:
        text += " Changing Repeat or End repeat updates the whole series."
    return text


def series_badge(event: Optional[dict], today: Optional[datetime.date] = None) -> str:
    """'Part of a weekly series · ends Fri 30 Oct' — '' for a one-off."""
    if not event or not event.get("series_id") or not event.get("recurrence"):
        return ""
    end = event.get("recurrence_end") or ""
    try:
        tail = f"ends {_day_label(datetime.date.fromisoformat(end), today)}" if end \
            else "no end date"
    except ValueError:
        tail = f"ends {end}"
    return f"Part of a {event['recurrence']} series · {tail}"


def repeat_rule_changed(event: Optional[dict], data: dict) -> bool:
    """Did this save change the series' RULE (cadence or end), not just this row?

    The rule belongs to every instance, so a change to it goes to the whole
    series whatever else was edited — "only this instance" with a new end
    date would leave one row claiming an end the others don't have.
    """
    if not event:
        return False
    return ((event.get("recurrence") or "") != (data.get("recurrence") or "")
            or (event.get("recurrence_end") or "") != (data.get("recurrence_end") or ""))


class ColorDot(QWidget):
    """Small colored circle for color selection."""

    clicked_color = pyqtSignal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QBrush
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(self.color)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(2, 2, 16, 16)

    def mousePressEvent(self, event):
        self.clicked_color.emit(self.color)


class EventDialog(QDialog):
    """
    Dialog for creating or editing a calendar event.
    On save, returns the event data as a dict via .event_data attribute.
    """

    def __init__(
        self,
        parent=None,
        event: Optional[dict] = None,
        default_date: Optional[datetime.date] = None,
        default_time: Optional[datetime.time] = None,
        db=None,
    ):
        super().__init__(parent)
        self._event = event  # None = create mode
        # WHAT THE DIALOG SHOWS vs WHAT IT SENDS. The swatch has to be painted
        # with something, but a NEW event whose picker was never touched has no
        # colour choice to report — and sending the paint colour as if it were a
        # choice is exactly what suppressed category colours for voice-created
        # events (2026-09-10; `db._AUTO_COLORS` carries the full story).
        #
        # So the displayed colour and the reported one are separate: `_picked`
        # stays False until the user actually clicks a swatch, and `""` — an
        # auto marker — is what goes to the server until they do.
        self._selected_color = (event or {}).get("color", BLUE)
        self._picked = bool((event or {}).get("color"))
        self._default_time = default_time
        self.event_data: Optional[dict] = None
        self.delete_requested: bool = False
        self.duplicate_requested: bool = False
        self.delete_series_requested: bool = False

        # ICS-subscribed events are always read-only (no write endpoint
        # behind a webcal/ICS link). Outlook-synced events are read-only
        # too unless two-way sync is currently on — editing one while it's
        # off would silently and permanently diverge from the real Outlook
        # event. CalendarDB.is_event_locked() is the single source of truth
        # for this policy (also enforced at the DB layer for drag/API paths).
        # *db* should be the same CalendarDB instance the caller already has
        # (e.g. CalendarWindow._db) rather than reaching for the global
        # get_db() singleton here — those happen to be the same underlying
        # file in the running app, but coupling to the global would be a
        # silent footgun for any caller that legitimately uses a different
        # CalendarDB instance (tests, an alternate window, etc).
        if event:
            if db is None:
                from assistant.db import get_db
                db = get_db()
            self._read_only = db.is_event_locked(event)
        else:
            self._read_only = False
        self._db = db

        self.setWindowTitle("New Event" if event is None else "Edit Event")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._build_ui(default_date or datetime.date.today())

    def _build_ui(self, default_date: datetime.date) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(12)

        source = (self._event or {}).get("source", "local")
        if source == "ics":
            banner = QLabel("🔗 Synced from a subscribed calendar — read-only. "
                             "Unsubscribe in Connected Calendars to remove it.")
            banner.setWordWrap(True)
            banner_text = _styles.D_GRAY_TEXT if _styles._dark else GRAY_TEXT
            banner.setStyleSheet(f"color: {banner_text}; font-size: 12px; padding-bottom: 4px;")
            layout.addWidget(banner)
        elif source in ("outlook", "google"):
            name = "Outlook" if source == "outlook" else "Google Calendar"
            if self._read_only:
                text = (f"🔗 Synced from {name} — read-only. Turn on two-way sync in "
                        "Connected Calendars to edit this event.")
            else:
                text = f"🔗 Synced with {name} — edits are pushed back automatically."
            banner = QLabel(text)
            banner.setWordWrap(True)
            banner_text = _styles.D_GRAY_TEXT if _styles._dark else GRAY_TEXT
            banner.setStyleSheet(f"color: {banner_text}; font-size: 12px; padding-bottom: 4px;")
            layout.addWidget(banner)

        # Title
        self._title = QLineEdit()
        self._title.setObjectName("title_input")
        self._title.setPlaceholderText("Add title")
        if self._event:
            self._title.setText(self._event["title"])
        layout.addWidget(self._title)

        # Which series this row belongs to, before anything is edited — the
        # only other sign of it was the question Save asks afterwards.
        badge = series_badge(self._event)
        if badge:
            self._series_badge = QLabel(f"🔁 {badge}")
            self._series_badge.setObjectName("series_badge")
            badge_color = _styles.D_GRAY_TEXT if _styles._dark else GRAY_TEXT
            self._series_badge.setStyleSheet(f"color: {badge_color}; font-size: 12px;")
            layout.addWidget(self._series_badge)

        # Form fields
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        # Date
        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("dddd, MMMM d, yyyy")
        d = self._event["date"] if self._event else default_date.isoformat()
        self._date.setDate(QDate.fromString(d, "yyyy-MM-dd"))
        form.addRow("Date", self._date)

        # Time row
        time_row = QHBoxLayout()
        self._start = QTimeEdit()
        self._start.setDisplayFormat("hh:mm AP")
        self._end = QTimeEdit()
        self._end.setDisplayFormat("hh:mm AP")
        if self._event:
            self._start.setTime(QTime.fromString(self._event["start_time"], "HH:mm"))
            self._end.setTime(QTime.fromString(self._event["end_time"], "HH:mm"))
        else:
            if self._default_time:
                sh, sm = self._default_time.hour, self._default_time.minute
            else:
                now = datetime.datetime.now()
                sh, sm = now.hour, 0
            self._start.setTime(QTime(sh, sm))
            end_dt = (datetime.datetime.combine(datetime.date.today(), datetime.time(sh, sm))
                      + datetime.timedelta(hours=1))
            self._end.setTime(QTime(end_dt.hour, end_dt.minute))
        time_row.addWidget(self._start)
        time_row.addWidget(QLabel("–"))
        time_row.addWidget(self._end)
        time_row.addStretch()
        form.addRow("Time", time_row)

        # Attendees
        self._attendees = QLineEdit()
        self._attendees.setPlaceholderText("Add attendees (names or emails, comma-separated)")
        if self._event:
            self._attendees.setText(self._event.get("attendees", ""))
        form.addRow("Attendees", self._attendees)

        # Location
        self._location = QLineEdit()
        self._location.setPlaceholderText("Add location or meeting link")
        if self._event:
            self._location.setText(self._event.get("location", ""))
        form.addRow("Location", self._location)

        # Description
        self._description = QTextEdit()
        self._description.setPlaceholderText("Add description")
        self._description.setFixedHeight(80)
        if self._event:
            self._description.setPlainText(self._event.get("description", ""))
        form.addRow("Notes", self._description)

        # Repeat
        self._repeat = QComboBox()
        self._repeat.addItems(["None", "Daily", "Weekly", "Monthly", "Yearly"])
        self._repeat.setMinimumWidth(120)
        if self._event and self._event.get("recurrence"):
            # Missing "yearly" here silently dropped a yearly event's
            # recurrence to "None" the moment any OTHER field was edited and
            # saved — the dropdown showed None selected, and saving read that
            # back literally.
            idx = {"daily": 1, "weekly": 2, "monthly": 3,
                  "yearly": 4}.get(self._event["recurrence"], 0)
            self._repeat.setCurrentIndex(idx)
        form.addRow("Repeat", self._repeat)

        # End repeat: Never | On date. This row used to be a bare "Until" date
        # with no way to say "never" — so opening an open-ended series ("gym
        # every day", no end) showed today + 1 year, and saving ANY other
        # change wrote that year back as a real end date.
        self._ends = QComboBox()
        self._ends.setObjectName("ends_mode")
        self._ends.addItems(["Never", "On date"])
        self._until = QDateEdit()
        self._until.setObjectName("ends_date")
        self._until.setCalendarPopup(True)
        self._until.setMinimumWidth(220)
        self._until.setDisplayFormat("dddd, MMMM d, yyyy")
        # Never before the event's own date: the end is INCLUSIVE, and an end
        # earlier than the event would describe a series with no room in it.
        self._until.setMinimumDate(self._date.date())
        existing_end = (self._event or {}).get("recurrence_end") or ""
        if existing_end:
            self._until.setDate(QDate.fromString(existing_end, "yyyy-MM-dd"))
            self._ends.setCurrentIndex(1)
        else:
            self._until.setDate(QDate.fromString(d, "yyyy-MM-dd").addMonths(1))
            # Something being made to repeat is offered an end by default —
            # most things that repeat stop — while an existing open-ended
            # series keeps saying Never.
            already_repeats = bool((self._event or {}).get("recurrence"))
            self._ends.setCurrentIndex(0 if already_repeats else 1)
        ends_row = QHBoxLayout()
        ends_row.addWidget(self._ends)
        ends_row.addWidget(self._until)
        ends_row.addStretch()
        self._ends_label = QLabel("End repeat")
        form.addRow(self._ends_label, ends_row)

        # The hint says in words what the two controls will do, including the
        # two things nobody could guess: that the end date itself is booked,
        # and that the series skips Shabbat and yom tov.
        self._repeat_hint = QLabel()
        self._repeat_hint.setObjectName("repeat_hint")
        self._repeat_hint.setWordWrap(True)
        hint_color = _styles.D_GRAY_TEXT if _styles._dark else GRAY_TEXT
        self._repeat_hint.setStyleSheet(f"color: {hint_color}; font-size: 11px;")
        form.addRow("", self._repeat_hint)
        self._form = form

        self._repeat.currentIndexChanged.connect(lambda _i: self._sync_repeat_rows())
        self._ends.currentIndexChanged.connect(lambda _i: self._sync_repeat_rows())
        self._until.dateChanged.connect(lambda _d: self._sync_repeat_rows())
        self._date.dateChanged.connect(lambda _d: self._on_start_date_changed())
        self._sync_repeat_rows()

        # Color
        color_row = QHBoxLayout()
        self._color_dots: list[ColorDot] = []
        for c in EVENT_COLORS:
            dot = ColorDot(c)
            dot.clicked_color.connect(self._on_color_selected)
            self._color_dots.append(dot)
            color_row.addWidget(dot)
        color_row.addStretch()
        self._update_color_dots()
        form.addRow("Color", color_row)

        # The to-do this event IS (Gil, 2026-09-25: "they can be linked and
        # the same thing"). Acts at once, like the delete and share buttons —
        # the link is not a field of the event, so Cancel does not undo it.
        if self._event and self._event.get("id") and not self._read_only \
                and self._db is not None:
            self._todo_row = QHBoxLayout()
            form.addRow("To-do", self._todo_row)
            self._render_todo_link()

        layout.addLayout(form)

        # Button row
        btn_row = QHBoxLayout()

        if self._read_only:
            btn_row.addStretch()
            close_btn = QPushButton("Close")
            close_btn.setDefault(True)
            close_btn.clicked.connect(self.reject)
            btn_row.addWidget(close_btn)
            layout.addLayout(btn_row)
            self._set_read_only_widgets()
            return

        # Delete button (edit mode only)
        if self._event:
            del_btn = QPushButton("🗑 Delete")
            del_btn.setObjectName("destructive")
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setAutoDefault(False)
            del_btn.setDefault(False)
            del_btn.clicked.connect(self._on_delete)
            btn_row.addWidget(del_btn)

            share_btn = QPushButton("Share .ics")
            share_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            share_btn.setAutoDefault(False)
            share_btn.setDefault(False)
            share_btn.clicked.connect(lambda: self._on_share_ics())
            btn_row.addWidget(share_btn)

            dup_btn = QPushButton("Duplicate")
            dup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            dup_btn.setAutoDefault(False)
            dup_btn.setDefault(False)
            dup_btn.clicked.connect(lambda: self._on_duplicate())
            btn_row.addWidget(dup_btn)

        btn_row.addStretch()

        # Cancel + Save
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setObjectName("primary")
        save_btn.setDefault(True)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        install_enter_confirms(self, save_btn)
        btn_row.addWidget(buttons)

        layout.addLayout(btn_row)

        self._title.setFocus()

    def _on_duplicate(self) -> None:
        # The caller owns the copy (same flag pattern as delete): it strips
        # series identity so duplicating one instance yields a one-off, not a
        # second parallel series.
        self.duplicate_requested = True
        self.accept()

    def _on_share_ics(self) -> None:
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        from assistant.ics_export import event_to_ics, filename_for
        import os
        default = os.path.join(os.path.expanduser("~/Desktop"),
                               filename_for(self._event))
        path, _ = QFileDialog.getSaveFileName(
            self, "Share event as .ics", default, "Calendar file (*.ics)")
        if not path:
            return
        try:
            with open(path, "w") as f:
                f.write(event_to_ics(self._event))
        except OSError as e:
            QMessageBox.warning(self, "Share failed", str(e))

    # -- End repeat ---------------------------------------------------------

    def _recurrence(self) -> str:
        return _CADENCES[self._repeat.currentIndex()]

    def _end_date(self) -> Optional[datetime.date]:
        """The series' last day, or None for Never (or no repeat at all)."""
        if not self._recurrence() or self._ends.currentIndex() == 0:
            return None
        return self._until.date().toPyDate()

    def _sync_repeat_rows(self) -> None:
        repeating = bool(self._recurrence())
        hint = repeat_hint(
            self._recurrence(), self._date.date().toPyDate(), self._end_date(),
            editing_series=bool(self._event and self._event.get("series_id")),
            recur_days=(self._event or {}).get("recur_days") or "")
        self._form.setRowVisible(self._ends_label, repeating)
        self._form.setRowVisible(self._repeat_hint, bool(hint))
        self._until.setVisible(repeating and self._ends.currentIndex() == 1)
        self._repeat_hint.setText(hint)

    def _on_start_date_changed(self) -> None:
        # The floor follows the event: moving it later drags an end that would
        # now fall before it along (QDateEdit clamps to its minimum).
        self._until.setMinimumDate(self._date.date())
        self._sync_repeat_rows()

    # ------------------------------------------------------------------
    # The linked to-do
    # ------------------------------------------------------------------

    def _render_todo_link(self) -> None:
        while self._todo_row.count():
            w = self._todo_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        todo = self._db.linked_todo(self._event["id"])
        if todo:
            label = QLabel(("☑ " if todo.get("completed") else "☐ ") + f"🔗 {todo['title']}")
            label.setObjectName("linked_todo_label")
            label.setToolTip("Linked: renaming or moving one changes the other; "
                             "deleting the event removes the to-do")
            unlink = QPushButton("Unlink")
            unlink.setObjectName("unlink_todo")
            unlink.setAutoDefault(False)
            unlink.clicked.connect(lambda: self._unlink_todo(todo["id"]))
            self._todo_row.addWidget(label)
            self._todo_row.addStretch()
            self._todo_row.addWidget(unlink)
            return
        add = QPushButton("Also add as a to-do")
        add.setObjectName("add_linked_todo")
        add.setAutoDefault(False)
        add.clicked.connect(lambda: self._add_linked_todo())
        pick = QPushButton("Link a to-do…")
        pick.setObjectName("link_existing_todo")
        pick.setAutoDefault(False)
        pick.clicked.connect(lambda: self._pick_todo())
        self._todo_row.addWidget(add)
        self._todo_row.addWidget(pick)
        self._todo_row.addStretch()

    def _add_linked_todo(self) -> None:
        self._db.create_linked_todo(self._event["id"])
        self._render_todo_link()

    def _pick_todo(self) -> None:
        from assistant.calendar_ui.link_picker import LinkPickerDialog, todo_rows
        dlg = LinkPickerDialog("Link a to-do", todo_rows(self._db), self,
                               empty="No open to-dos without an event")
        if dlg.exec() and dlg.chosen_id is not None:
            self._db.link_todo(dlg.chosen_id, self._event["id"])
            self._render_todo_link()

    def _unlink_todo(self, todo_id: int) -> None:
        self._db.unlink_todo(todo_id)
        self._render_todo_link()

    def _set_read_only_widgets(self) -> None:
        for w in (
            self._title, self._date, self._start, self._end, self._attendees,
            self._location, self._description, self._repeat, self._ends, self._until,
        ):
            w.setEnabled(False)
        for dot in self._color_dots:
            dot.setEnabled(False)

    def _on_color_selected(self, color: str) -> None:
        self._selected_color = color
        self._picked = True          # an actual click — now there IS a choice
        self._update_color_dots()

    def _update_color_dots(self) -> None:
        for dot in self._color_dots:
            dot.setFixedSize(24 if dot.color == self._selected_color else 20, 24 if dot.color == self._selected_color else 20)

    def _on_delete(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        if self._event and self._event.get("series_id"):
            msg = QMessageBox(self)
            msg.setWindowTitle("Delete Event")
            msg.setText("This is a repeating event.")
            msg.setInformativeText("Do you want to delete only this instance, or the entire series?")
            btn_only_this = msg.addButton("Only this instance", QMessageBox.ButtonRole.ActionRole)
            btn_series = msg.addButton("Entire series", QMessageBox.ButtonRole.DestructiveRole)
            msg.addButton(QMessageBox.StandardButton.Cancel)
            msg.setDefaultButton(btn_only_this)  # Enter confirms; Escape/Cancel button still cancels
            msg.exec()
            if msg.clickedButton() == btn_only_this:
                self.delete_requested = True
                self.accept()
            elif msg.clickedButton() == btn_series:
                self.delete_series_requested = True
                self.accept()
        else:
            title = self._event["title"] if self._event else "this event"
            reply = QMessageBox.question(
                self,
                "Delete Event",
                f"Delete \"{title}\"?\n(⌘Z undoes this if you change your mind.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,  # Enter confirms; Escape/Cancel button still cancels
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.delete_requested = True
                self.accept()

    def _on_save(self) -> None:
        title = self._title.text().strip()
        if not title:
            self._title.setPlaceholderText("Title is required")
            return

        date_str = self._date.date().toString("yyyy-MM-dd")
        start_str = self._start.time().toString("HH:mm")
        end_str = self._end.time().toString("HH:mm")

        recurrence = self._recurrence()
        end = self._end_date()
        recur_until = end.isoformat() if end else ""

        self.event_data = {
            "title": title,
            "date": date_str,
            "start_time": start_str,
            "end_time": end_str,
            "attendees": self._attendees.text().strip(),
            "location": self._location.text().strip(),
            "description": self._description.toPlainText().strip(),
            "color": self._selected_color if self._picked else "",
            "recurrence": recurrence,
            "recurrence_end": recur_until,
        }
        if self._event:
            self.event_data["id"] = self._event["id"]
            if self._event.get("series_id"):
                self.event_data["series_id"] = self._event["series_id"]

        self.accept()
