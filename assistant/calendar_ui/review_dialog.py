"""“Was this right?” — review recent voice commands (Mac).

The desktop twin of the iPhone's Review-commands screen. Every command the
assistant runs is kept in the shared memory DB (~/.assistant_tools) with no
verdict until someone gives one; a 👍 / 👎 / fix here feeds the few-shot
examples the parser learns from. Since the Mac *is* the brain, this talks to
`assistant.intent.memory` directly rather than through the API the phone uses.
"""

from __future__ import annotations

import datetime as _dt

from PyQt6.QtCore import QDate, Qt, QTime
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTimeEdit,
    QVBoxLayout, QWidget,
)

from assistant.calendar_ui import icons
from assistant.calendar_ui import styles as _styles


def _pretty_date(iso: str) -> str:
    """2026-08-27 → Thu 27 Aug."""
    try:
        return _dt.date.fromisoformat(iso).strftime("%a %-d %b")
    except Exception:
        return iso


def _summarise(example: dict) -> str:
    """One line per thing the command did, in the order it did them."""
    from assistant.intent import review
    lines = []
    for r in review.rows_for(example):
        day = _pretty_date(r.date) if r.date else ""
        when = (f"due {day}" if day else "") if r.kind == "todo" else \
            " ".join(x for x in (day, r.start) if x)
        lines.append(" · ".join(x for x in (r.verb, r.title, when) if x))
    return "\n".join(lines)


def unreviewed(limit: int = 30) -> list[dict]:
    """Successful commands nobody has judged yet, with every row they touched.

    The same join GET /memory/unreviewed serves, so the phone and the Mac show
    the same backlog in the same order (`assistant/intent/review.py`).
    Module-level so the Settings button can show the count without opening
    the dialog.
    """
    from assistant.intent import review
    return review.unreviewed(limit)


class _ReviewRow(QFrame):
    """One command awaiting a verdict."""

    def __init__(self, example: dict, on_verdict, on_fix, dark: bool, parent=None) -> None:
        super().__init__(parent)
        self._example = example
        text2 = _styles.D_GRAY_TEXT if dark else _styles.GRAY_TEXT
        border = _styles.D_GRAY_BORDER if dark else _styles.GRAY_BORDER
        surface = _styles.D_GRAY_LIGHT if dark else _styles.GRAY_LIGHT
        self.setStyleSheet(
            f"QFrame {{ background-color: {surface}; border: 1px solid {border};"
            f" border-radius: {_styles.RADIUS_MD}px; }} QLabel {{ border: none; }}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        src = QLabel()
        src.setPixmap(icons.pixmap("iphone" if example.get("source") == "ios" else "mac",
                                   text2, 13))
        head.addWidget(src)
        when = QLabel(str(example.get("time", "")).replace("T", " ")[:16])
        when.setStyleSheet(f"color: {text2}; font-size: 11px;")
        head.addWidget(when)
        head.addStretch(1)
        path = QLabel(example.get("parse_path") or "-")
        path.setStyleSheet(f"color: {text2}; font-size: 11px;")
        head.addWidget(path)
        lay.addLayout(head)

        said = QLabel(f"“{example.get('transcript', '')}”")
        said.setWordWrap(True)
        lay.addWidget(said)

        summary = _summarise(example)
        if summary:
            lbl = QLabel(summary)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {text2};")
            lay.addWidget(lbl)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        right = QPushButton(icons.icon("thumbs_up", size=14), " Right")
        right.clicked.connect(lambda: on_verdict(example, "approved"))
        wrong = QPushButton(icons.icon("thumbs_down", size=14), " Wrong")
        wrong.clicked.connect(lambda: on_verdict(example, "rejected"))
        fix = QPushButton(icons.icon("corrected", size=14), " Fix…")
        fix.clicked.connect(lambda: on_fix(example))
        for b in (right, wrong, fix):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.addWidget(b)
        buttons.addStretch(1)
        lay.addLayout(buttons)


_REASONS = ("Misheard a word", "Wrong day or time", "Should be a to-do",
            "Should be an event", "Split it wrong", "Missed part of it",
            "Didn't ask for this")


class _FixRowWidget(QFrame):
    """One object in the fix dialog: what it is now, the verdict, and — when
    it is being changed — the fields, with real date and time pickers."""

    def __init__(self, row, on_remove=None, parent=None) -> None:
        super().__init__(parent)
        from assistant.intent import review
        self.row = row
        self.setObjectName("fixRow")
        self.setStyleSheet("QFrame#fixRow { border: 1px solid rgba(128,128,128,0.35);"
                           " border-radius: 8px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(1)
        verb = QLabel(row.verb.upper())
        verb.setStyleSheet("font-size: 10px; font-weight: 600; color: gray;")
        text.addWidget(verb)
        self._title_lbl = QLabel(row.title or ("New" if row.added else "—"))
        text.addWidget(self._title_lbl)
        when = self._when()
        if when:
            w = QLabel(when)
            w.setStyleSheet("color: gray; font-size: 11px;")
            text.addWidget(w)
        before = (row.record or {}).get("before")
        if before and row.is_update:
            b = QLabel(f"was: {before.get('title', '')} · {_pretty_date(before.get('date', ''))}"
                       f" {before.get('start_time', '')}")
            b.setStyleSheet("color: gray; font-size: 11px;")
            text.addWidget(b)
        head.addLayout(text, 1)
        if on_remove is not None:
            x = QPushButton("✕")
            x.setFlat(True)
            x.setFixedWidth(28)
            x.clicked.connect(lambda: on_remove(self))
            head.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        self._choice_btns: dict = {}
        if not row.added:
            choices = [review.RIGHT, review.UNDO] if (row.read_only or row.is_delete or row.is_complete) \
                else [review.RIGHT, review.CHANGE, review.UNDO]
            seg = QHBoxLayout()
            seg.setSpacing(0)
            group = QButtonGroup(self)
            for c in choices:
                label = {"right": "Right", "change": "Change"}.get(c, row.undo_label)
                b = QPushButton(label)
                b.setCheckable(True)
                b.setChecked(c == row.choice)
                b.clicked.connect(lambda _=False, c=c: self.set_choice(c))
                group.addButton(b)
                seg.addWidget(b)
                self._choice_btns[c] = b
            lay.addLayout(seg)
            self._cant = QLabel("Can't take this back from here — it's recorded so the assistant learns.")
            self._cant.setWordWrap(True)
            self._cant.setStyleSheet("color: gray; font-size: 11px;")
            lay.addWidget(self._cant)

        self._editor = QWidget()
        form = QFormLayout(self._editor)
        form.setContentsMargins(0, 4, 0, 0)
        self._kind = QComboBox()
        self._kind.addItem("Event", "event")
        self._kind.addItem("To-do", "todo")
        self._kind.setCurrentIndex(0 if row.kind == "event" else 1)
        self._kind.currentIndexChanged.connect(self._kind_changed)
        if row.is_create or row.added:
            form.addRow("Kind", self._kind)
        self._title = QLineEdit(row.title)
        self._title.setPlaceholderText("Title")
        form.addRow("Title", self._title)
        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("ddd d MMM yyyy")
        self._date.setDate(QDate.fromString(row.date, "yyyy-MM-dd") if row.date else QDate.currentDate())
        self._due = QCheckBox("Due on a day")
        self._due.setChecked(bool(row.date))
        self._due.toggled.connect(lambda on: self._date.setEnabled(on or self.kind() == "event"))
        self._start = QTimeEdit(QTime.fromString(row.start or "09:00", "HH:mm"))
        self._end = QTimeEdit(QTime.fromString(row.end or "10:00", "HH:mm"))
        for t in (self._start, self._end):
            t.setDisplayFormat("HH:mm")
        form.addRow("Day", self._date)
        form.addRow("", self._due)
        times = QHBoxLayout()
        times.addWidget(self._start)
        times.addWidget(QLabel("–"))
        times.addWidget(self._end)
        self._times_row = QWidget()
        self._times_row.setLayout(times)
        form.addRow("Time", self._times_row)
        self._form = form
        lay.addWidget(self._editor)
        self._refresh()

    def _when(self) -> str:
        r = self.row
        day = _pretty_date(r.date) if r.date else ""
        if r.kind == "todo":
            return f"due {day}" if day else ""
        clock = f"{r.start}–{r.end}" if r.start and r.end else r.start
        return " · ".join(x for x in (day, clock) if x)

    def kind(self) -> str:
        return self._kind.currentData()

    def set_choice(self, choice: str) -> None:
        self.row.choice = choice
        if choice in self._choice_btns:
            self._choice_btns[choice].setChecked(True)
        self._refresh()

    def _kind_changed(self) -> None:
        # Switching to an event gives it a day and the ruled default hour
        # (DEVQA Q47: an event with no stated clock sits at 09:00).
        self._refresh()

    def _refresh(self) -> None:
        from assistant.intent import review
        editing = self.row.added or self.row.choice == review.CHANGE
        self._editor.setVisible(editing)
        is_event = self.kind() == "event"
        self._times_row.setVisible(is_event)
        self._form.labelForField(self._times_row).setVisible(is_event)
        self._due.setVisible(not is_event)
        self._date.setEnabled(is_event or self._due.isChecked())
        if not self.row.added:
            self._cant.setVisible(self.row.choice == review.UNDO and not self.row.can_undo
                                  and not self.row.read_only)
        font = self._title_lbl.font()
        font.setStrikeOut(self.row.choice == review.UNDO and not self.row.read_only)
        self._title_lbl.setFont(font)

    def commit(self):
        """Copy the fields back onto the row, when it is being edited."""
        from assistant.intent import review
        r = self.row
        if r.added or r.choice == review.CHANGE:
            r.kind = self.kind()
            r.title = self._title.text().strip()
            if r.kind == "event":
                r.date = self._date.date().toString("yyyy-MM-dd")
                r.start = self._start.time().toString("HH:mm")
                r.end = self._end.time().toString("HH:mm")
            else:
                r.date = self._date.date().toString("yyyy-MM-dd") if self._due.isChecked() else ""
                r.start = r.end = ""
        return r


class CorrectionDialog(QDialog):
    """“What should it have done?” — every object the command touched, each
    with its own verdict (right / change it / take it back), a one-click
    "nothing should have been done", a way to add what it missed, and why.
    The Mac twin of the iOS Fix… sheet; the rules are `intent/review.py`'s.

    Gil, 2026-09-24: a six-part command showed one event here, and there was
    no way to say the command should not have done anything.
    """

    def __init__(self, example: dict, parent=None) -> None:
        super().__init__(parent)
        from assistant.intent import review
        self.setWindowTitle("Fix this")
        self.setMinimumSize(480, 560)
        self._example = example
        self.plan: dict | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        said = QLabel(f"You said: “{example.get('transcript', '')}”")
        said.setWordWrap(True)
        lay.addWidget(said)

        self._nothing = QCheckBox("Nothing should have been done — take back everything below")
        self._nothing.toggled.connect(self._set_nothing)
        lay.addWidget(self._nothing)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self._rows_lay = QVBoxLayout(host)
        self._rows_lay.setContentsMargins(0, 0, 6, 0)
        self._rows_lay.setSpacing(6)
        self._widgets: list[_FixRowWidget] = []
        rows = review.rows_for(example)
        head = QLabel(f"What it did · {len(rows)} {'thing' if len(rows) == 1 else 'things'}")
        head.setStyleSheet("font-weight: 600;")
        self._rows_lay.addWidget(head)
        for r in rows:
            w = _FixRowWidget(r)
            self._widgets.append(w)
            self._rows_lay.addWidget(w)

        missed = QHBoxLayout()
        missed.addWidget(QLabel("Missed something?"))
        for kind, label in (("event", "+ Event"), ("todo", "+ To-do")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, k=kind: self._add(k))
            missed.addWidget(b)
        missed.addStretch(1)
        self._missed_row = QWidget()
        self._missed_row.setLayout(missed)
        self._rows_lay.addWidget(self._missed_row)
        self._rows_lay.addStretch(1)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        lay.addWidget(QLabel("What went wrong?"))
        chips = QGridLayout()
        chips.setSpacing(6)
        self._chips: dict[str, QPushButton] = {}
        for i, reason in enumerate(_REASONS):
            b = QPushButton(reason)
            b.setCheckable(True)
            chips.addWidget(b, i // 3, i % 3)
            self._chips[reason] = b
        lay.addLayout(chips)
        self._notes = QPlainTextEdit()
        self._notes.setPlaceholderText("Anything else? e.g. it heard 'Aura' but I said 'Nurit'")
        self._notes.setFixedHeight(56)
        lay.addWidget(self._notes)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                               | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _set_nothing(self, on: bool) -> None:
        from assistant.intent import review
        for w in list(self._widgets):
            if w.row.added:
                self._remove(w)
            else:
                w.set_choice(review.UNDO if on else review.RIGHT)
        self._chips["Didn't ask for this"].setChecked(on)

    def _add(self, kind: str) -> None:
        from assistant.intent import review
        import datetime as _d
        row = review.FixRow(index=None, action="", kind=kind, choice=review.CHANGE,
                            date=_d.date.today().isoformat() if kind == "event" else "",
                            start="09:00" if kind == "event" else "",
                            end="10:00" if kind == "event" else "")
        w = _FixRowWidget(row, on_remove=self._remove)
        self._widgets.append(w)
        self._rows_lay.insertWidget(self._rows_lay.indexOf(self._missed_row), w)
        self._chips["Missed part of it"].setChecked(True)

    def _remove(self, w) -> None:
        self._widgets.remove(w)
        w.setParent(None)
        w.deleteLater()

    def _save(self) -> None:
        from assistant.intent import review
        rows = [w.commit() for w in self._widgets]
        reasons = {r for r, b in self._chips.items() if b.isChecked()}
        notes = self._notes.toPlainText().strip()
        plan = review.plan(self._example, rows, reasons, notes)
        if plan["feedback"] == "rejected" and not plan["notes"]:
            QMessageBox.information(self, "Fix this",
                                    "Change something above, or say what went wrong.")
            return
        self.plan = plan
        self.accept()


class ReviewDialog(QDialog):
    """The backlog of commands with no verdict yet."""

    def __init__(self, parent=None, dark: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review commands")
        self.setMinimumSize(560, 560)
        self._dark = dark
        self._done = 0
        from assistant.intent.memory import get_memory
        self._memory = get_memory()

        root = QVBoxLayout(self)
        self._intro = QLabel()
        self._intro.setWordWrap(True)
        self._intro.setObjectName("muted")
        root.addWidget(self._intro)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget()
        self._list = QVBoxLayout(self._host)
        self._list.setContentsMargins(0, 0, 6, 0)
        self._list.setSpacing(8)
        self._list.addStretch(1)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, 1)

        buttons = QHBoxLayout()
        self._skip_btn = QPushButton("Dismiss all")
        self._skip_btn.setToolTip("Clear the backlog without marking anything right or wrong")
        self._skip_btn.clicked.connect(self._skip_all)
        buttons.addWidget(self._skip_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("Done")
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self.reload()

    # ---------------------------------------------------------------- data

    def reload(self) -> None:
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        items = unreviewed()
        self._skip_btn.setVisible(bool(items))
        if not items:
            self._intro.setText(
                f"All caught up — {self._done} reviewed." if self._done
                else "Nothing to review. Every voice command shows up here until you've said "
                     "whether it was right; a few seconds a day and the assistant learns your phrasing.")
            return
        self._intro.setText(
            f"{len(items)} to review · 👍 if it did the right thing, 👎 if not. "
            "Only what you tick is stored.")
        for ex in items:
            self._list.insertWidget(self._list.count() - 1,
                                    _ReviewRow(ex, self._verdict, self._fix, self._dark))

    # -------------------------------------------------------------- actions

    def _verdict(self, example: dict, value: str) -> None:
        self._memory.set_feedback(int(example["id"]), value)
        self._done += 1
        self.reload()

    def _fix(self, example: dict) -> None:
        dlg = CorrectionDialog(example, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        from assistant.intent import review
        plan = dlg.plan
        # The calendar first, the verdict LAST: deleting or patching a row a
        # voice command made writes its own automatic feedback, and the
        # dialog's explicit answer has to be the one that stands.
        failed = review.apply(plan["ops"])
        if failed:
            QMessageBox.warning(self, "Fix this", "Some changes didn't apply:\n" + "\n".join(failed))
        self._memory.set_feedback(int(example["id"]), plan["feedback"],
                                  correction=plan["correction"], notes=plan["notes"])
        self._done += 1
        self.reload()

    def _skip_all(self) -> None:
        count = len(unreviewed(limit=1000))
        if QMessageBox.question(
                self, "Dismiss all",
                f"Dismiss all {count} without a verdict? They won't count as right or wrong."
        ) != QMessageBox.StandardButton.Yes:
            return
        self._memory.skip_unreviewed()
        self._done = 0
        self.reload()
