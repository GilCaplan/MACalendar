"""Occasions on the Mac (DEVQA Q73): the banner, its editor, the Settings page.

A banner sits in the all-day strip of Month, Week and Day. A person's own
occasion opens its editor on click (*"all day but also customizable by user
if they want to edit it"*); a computed one (parasha, a national holiday …)
says where it is switched, since it has no single record to edit.
"""

from __future__ import annotations

import datetime
import logging

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialog,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QSizePolicy,
                             QSpinBox, QVBoxLayout, QWidget)

logger = logging.getLogger(__name__)

KIND_LABELS = {"birthday": "Birthday", "anniversary": "Anniversary", "yahrzeit": "Yahrzeit",
               "countdown": "Countdown", "custom": "Other yearly date"}
GLYPH = {"birthday": "🎂", "anniversary": "💍", "yahrzeit": "🕯", "countdown": "⏳",
         "custom": "★", "jewish": "✡", "national": "⚑", "christian": "✝", "islamic": "☪"}
SOURCE_LABELS = {"jewish": "Jewish calendar", "national": "national holidays",
                 "christian": "Christian holidays", "islamic": "Islamic holidays"}
HEBREW_MONTHS = ["Nisan", "Iyar", "Sivan", "Tammuz", "Av", "Elul", "Tishrei", "Cheshvan",
                 "Kislev", "Tevet", "Shevat", "Adar", "Adar II"]
GREG_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]


def banners_between(start: datetime.date, end: datetime.date) -> dict:
    """{iso date: [banner, …]} for a view's range — never raises (a Qt slot
    that raises aborts the app)."""
    try:
        from assistant.occasions.feed import banners
        out: dict = {}
        for b in banners(start, end):
            out.setdefault(b["date"], []).append(b)
        return out
    except Exception as exc:
        logger.warning("occasions unavailable: %s", exc)
        return {}


class OccasionBanner(QLabel):
    """One all-day occasion. Clicking a person's own opens its editor."""

    changed = pyqtSignal()

    def __init__(self, banner: dict, font_size: int = 8, parent=None):
        super().__init__(parent)
        self.banner = banner
        self._color = banner.get("color") or "#8b5cf6"
        self._font_size = font_size
        self._text = f"{GLYPH.get(banner.get('kind'), '•')} {banner.get('title', '')}"
        self.setText(self._text)
        self.setFixedHeight(20)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("background: transparent;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if banner.get("editable"):
            self.setToolTip(f"{banner.get('title')} — click to edit")
        else:
            src = SOURCE_LABELS.get(banner.get("source"), banner.get("source", ""))
            self.setToolTip(f"{banner.get('title')}\nFrom the {src} — switch it in "
                            "Settings ▸ Occasions")

    def paintEvent(self, _event):  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(self._color)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect().adjusted(0, 1, -1, -2), 4, 4)
        from assistant.calendar_ui.styles import on_color
        p.setPen(QColor(on_color(self._color)))
        f = self.font()
        f.setPointSize(self._font_size)
        f.setWeight(f.Weight.DemiBold)
        p.setFont(f)
        elided = p.fontMetrics().elidedText(self._text, Qt.TextElideMode.ElideRight, self.width() - 8)
        p.drawText(self.rect().adjusted(4, 0, -4, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        p.end()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(ev)
        if not self.banner.get("editable"):
            from PyQt6.QtWidgets import QToolTip
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self)
            return
        from assistant.occasions import store
        rec = next((r for r in store.load() if r.get("id") == self.banner.get("occasion_id")), None)
        if rec is None:
            return
        if OccasionDialog(self.window(), rec).exec():
            self.changed.emit()
            win = self.window()
            if hasattr(win, "refresh_calendar"):
                win.refresh_calendar()


class OccasionDialog(QDialog):
    """Add or edit one occasion."""

    def __init__(self, parent=None, rec: "dict | None" = None, kind: str = "birthday"):
        super().__init__(parent)
        self.rec = dict(rec or {})
        self.result_rec: "dict | None" = None
        self.deleted = False
        self.setWindowTitle("Edit occasion" if rec else "Add an occasion")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self.kind = QComboBox()
        for k, label in KIND_LABELS.items():
            self.kind.addItem(label, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(self.rec.get("kind", kind))))
        form.addRow("What:", self.kind)

        self.title = QLineEdit(self.rec.get("title", ""))
        self.title.setPlaceholderText("Dana · Gil & Dana · Grandpa Moshe · Trip to Rome")
        form.addRow("Name:", self.title)

        self.calendar = QComboBox()
        self.calendar.addItem("Regular calendar", "gregorian")
        self.calendar.addItem("Hebrew calendar", "hebrew")
        self.calendar.setCurrentIndex(1 if self.rec.get("calendar") == "hebrew" else 0)
        form.addRow("Repeats by:", self.calendar)

        # Regular date: a date picker; "year known" decides whether it counts years.
        self.greg_row = QWidget()
        gl = QHBoxLayout(self.greg_row)
        gl.setContentsMargins(0, 0, 0, 0)
        self.greg_date = QDateEdit()
        self.greg_date.setCalendarPopup(True)
        self.greg_date.setDisplayFormat("d MMMM yyyy")
        g = self.rec
        if g.get("calendar", "gregorian") == "gregorian" and g.get("month"):
            self.greg_date.setDate(QDate(int(g.get("year") or 2000), int(g["month"]), int(g["day"])))
        else:
            self.greg_date.setDate(QDate.currentDate())
        self.greg_year_known = QCheckBox("Year known")
        self.greg_year_known.setToolTip("With the year, the banner counts them: \"Dana's 30th birthday\".")
        self.greg_year_known.setChecked(bool(g.get("year")) or not rec)
        gl.addWidget(self.greg_date)
        gl.addWidget(self.greg_year_known)
        form.addRow("Date:", self.greg_row)

        # Hebrew date: day + month (+ optional Hebrew year) + the Adar choice.
        self.heb_row = QWidget()
        hl = QHBoxLayout(self.heb_row)
        hl.setContentsMargins(0, 0, 0, 0)
        self.heb_day = QSpinBox()
        self.heb_day.setRange(1, 30)
        self.heb_month = QComboBox()
        for i, m in enumerate(HEBREW_MONTHS, start=1):
            self.heb_month.addItem(m, i)
        self.heb_year = QSpinBox()
        self.heb_year.setRange(0, 6000)
        self.heb_year.setSpecialValueText("year unknown")
        if g.get("calendar") == "hebrew":
            self.heb_day.setValue(int(g.get("day") or 1))
            self.heb_month.setCurrentIndex(max(0, self.heb_month.findData(int(g.get("month") or 1))))
            self.heb_year.setValue(int(g.get("year") or 0))
        hl.addWidget(self.heb_day)
        hl.addWidget(self.heb_month)
        hl.addWidget(self.heb_year)
        form.addRow("Hebrew date:", self.heb_row)

        self.adar = QComboBox()
        self.adar.addItem("Adar I", "adar1")
        self.adar.addItem("Adar II", "adar2")
        self.adar.addItem("Both", "both")
        self.adar.setToolTip("In a leap year there are two Adars. Common custom: a yahrzeit in\n"
                             "Adar I, a birthday or anniversary in Adar II.")
        form.addRow("In a leap year:", self.adar)
        if g.get("adar"):
            self.adar.setCurrentIndex(max(0, self.adar.findData(g["adar"])))

        self.remind = QComboBox()
        self.remind.addItem("As in Settings", None)
        self.remind.addItem("No reminder", -1)
        self.remind.addItem("On the day", 0)
        for n in (1, 2, 3, 7, 14):
            self.remind.addItem(f"{n} day{'s' if n > 1 else ''} before", n)
        self.remind.setCurrentIndex(max(0, self.remind.findData(g.get("remind_days"))))
        form.addRow("Reminder:", self.remind)

        colour_row = QHBoxLayout()
        self._color = g.get("color")
        self.colour_btn = QPushButton("Default colour" if not self._color else self._color)
        self.colour_btn.clicked.connect(lambda: self._pick_colour())
        colour_row.addWidget(self.colour_btn)
        colour_row.addStretch(1)
        form.addRow("Colour:", colour_row)

        self.note = QLineEdit(g.get("note", ""))
        self.note.setPlaceholderText("Optional — a gift idea, where …")
        form.addRow("Note:", self.note)

        self.error = QLabel("")
        self.error.setStyleSheet("color: #e5484d;")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)

        row = QHBoxLayout()
        if rec:
            self.delete_btn = QPushButton("Delete")
            self.delete_btn.clicked.connect(lambda: self._delete())
            row.addWidget(self.delete_btn)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.reject())
        self.save_btn = QPushButton("Save")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(lambda: self._save())
        row.addWidget(cancel)
        row.addWidget(self.save_btn)
        lay.addLayout(row)

        self.kind.currentIndexChanged.connect(lambda _i: self._sync())
        self.calendar.currentIndexChanged.connect(lambda _i: self._sync())
        self.heb_month.currentIndexChanged.connect(lambda _i: self._sync())
        self._form = form
        self._sync()

    def _sync(self) -> None:
        """Show the rows that apply: a countdown is a one-off regular date;
        the Adar choice only for a Hebrew date in Adar."""
        countdown = self.kind.currentData() == "countdown"
        if countdown and self.calendar.currentData() != "gregorian":
            self.calendar.setCurrentIndex(0)
        self.calendar.setEnabled(not countdown)
        hebrew = self.calendar.currentData() == "hebrew"
        self._form.setRowVisible(self.greg_row, not hebrew)
        self._form.setRowVisible(self.heb_row, hebrew)
        self._form.setRowVisible(self.adar, hebrew and self.heb_month.currentData() in (12, 13))
        self.greg_year_known.setVisible(not countdown)

    def _pick_colour(self) -> None:
        c = QColorDialog.getColor(QColor(self._color or "#ec4899"), self, "Banner colour")
        if c.isValid():
            self._color = c.name()
            self.colour_btn.setText(self._color)

    def values(self) -> dict:
        hebrew = self.calendar.currentData() == "hebrew"
        kind = self.kind.currentData()
        if hebrew:
            month, day = self.heb_month.currentData(), self.heb_day.value()
            year = self.heb_year.value() or None
        else:
            d = self.greg_date.date()
            month, day = d.month(), d.day()
            year = d.year() if (kind == "countdown" or self.greg_year_known.isChecked()) else None
        return {"kind": kind, "title": self.title.text().strip(),
                "calendar": "hebrew" if hebrew else "gregorian", "month": month, "day": day,
                "year": year, "adar": self.adar.currentData() if hebrew else None,
                "remind_days": self.remind.currentData(), "color": self._color,
                "note": self.note.text().strip()}

    def _save(self) -> None:
        from assistant.occasions import store
        vals = self.values()
        got, why = (store.update(self.rec["id"], vals) if self.rec.get("id") else store.add(vals))
        if got is None:
            self.error.setText(why)
            self.error.show()
            return
        self.result_rec = got
        self.accept()

    def _delete(self) -> None:
        from assistant.occasions import store
        if QMessageBox.question(self, "Delete occasion",
                                f"Delete “{self.rec.get('title')}”?") != QMessageBox.StandardButton.Yes:
            return
        store.delete(self.rec["id"])
        self.deleted = True
        self.accept()


def next_date(rec: dict, today: "datetime.date | None" = None) -> "datetime.date | None":
    """When an occasion next falls (for sorting the list)."""
    from assistant.occasions.dates import occurrences
    today = today or datetime.date.today()
    hits = occurrences(rec, today, today + datetime.timedelta(days=400))
    return datetime.date.fromisoformat(hits[0]["date"]) if hits else None


class OccasionsList(QWidget):
    """Settings ▸ Occasions: a person's own, soonest first, with Add / Edit /
    Delete. Changes are saved at once (they are records, not settings)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMinimumHeight(160)
        self.list.itemDoubleClicked.connect(lambda _i: self.edit())
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.add_btn = QPushButton("Add…")
        self.add_btn.clicked.connect(lambda: self.add())
        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.clicked.connect(lambda: self.edit())
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(lambda: self.delete())
        for b in (self.add_btn, self.edit_btn, self.delete_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.list.currentRowChanged.connect(lambda _r: self._buttons())
        self.reload()

    def reload(self) -> None:
        from assistant.occasions import store
        keep = self._selected_id()
        self.list.clear()
        recs = store.load()
        far = datetime.date.max
        for rec in sorted(recs, key=lambda r: next_date(r) or far):
            nd = next_date(rec)
            when = nd.strftime("%a %-d %b %Y") if nd else "—"
            kind = KIND_LABELS.get(rec.get("kind"), rec.get("kind", ""))
            cal = " · Hebrew date" if rec.get("calendar") == "hebrew" else ""
            item = QListWidgetItem(f"{GLYPH.get(rec.get('kind'), '•')}  {rec.get('title')}"
                                   f"   —   {kind}{cal} · next {when}")
            item.setData(Qt.ItemDataRole.UserRole, rec.get("id"))
            self.list.addItem(item)
            if rec.get("id") == keep:
                self.list.setCurrentItem(item)
        if not recs:
            item = QListWidgetItem("Nothing yet — Add… a birthday, an anniversary, a yahrzeit "
                                   "or a countdown.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self._buttons()

    def _selected_id(self) -> "str | None":
        item = self.list.currentItem() if hasattr(self, "list") else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _buttons(self) -> None:
        on = bool(self._selected_id())
        self.edit_btn.setEnabled(on)
        self.delete_btn.setEnabled(on)

    def _refresh_window(self) -> None:
        win = self.window()
        parent = win.parent() if win is not None else None
        for w in (win, parent):
            if w is not None and hasattr(w, "refresh_calendar"):
                w.refresh_calendar()
                break

    def add(self) -> None:
        if OccasionDialog(self).exec():
            self.reload()
            self._refresh_window()

    def edit(self) -> None:
        from assistant.occasions import store
        oid = self._selected_id()
        rec = next((r for r in store.load() if r.get("id") == oid), None)
        if rec and OccasionDialog(self, rec).exec():
            self.reload()
            self._refresh_window()

    def delete(self) -> None:
        from assistant.occasions import store
        oid = self._selected_id()
        if not oid:
            return
        rec = next((r for r in store.load() if r.get("id") == oid), {})
        if QMessageBox.question(self, "Delete occasion",
                                f"Delete “{rec.get('title', '')}”?") == QMessageBox.StandardButton.Yes:
            store.delete(oid)
            self.reload()
            self._refresh_window()


class CountdownList(QWidget):
    """The sidebar's countdowns: "12 days · Wedding", soonest first; hidden
    when there are none. A row opens its editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(8, 10, 8, 4)
        self._lay.setSpacing(2)
        self.reload()

    def reload(self) -> None:
        while self._lay.count():
            it = self._lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        try:
            from assistant.occasions.feed import countdowns
            items = countdowns()
        except Exception:
            items = []
        self.setVisible(bool(items))
        if not items:
            return
        head = QLabel("COUNTDOWNS")
        head.setStyleSheet("color: #8a8a90; font-size: 10px; font-weight: 600;")
        self._lay.addWidget(head)
        for c in items[:5]:
            n = c["days_left"]
            when = "today" if n == 0 else "tomorrow" if n == 1 else f"{n} days"
            b = QPushButton(f"⏳  {when} · {c['title']}")
            b.setObjectName("countdown_row")
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton#countdown_row { text-align: left; border: none;"
                            " padding: 3px 4px; }")
            b.setToolTip(f"{c['title']} — {c['date']}. Click to edit.")
            b.clicked.connect(lambda _c=False, oid=c["id"]: self._edit(oid))
            self._lay.addWidget(b)

    def _edit(self, oid: str) -> None:
        from assistant.occasions import store
        rec = next((r for r in store.load() if r.get("id") == oid), None)
        if rec and OccasionDialog(self.window(), rec).exec():
            win = self.window()
            if hasattr(win, "refresh_calendar"):
                win.refresh_calendar()
            else:
                self.reload()
