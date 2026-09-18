"""Settings ▸ How I Say Things — the engine's word lists, editable.

Gil, 2026-09-18, after "Can you shorten the event at 2pm walk Jada to be 15
minutes" silently did nothing: *"in the settings we should have a section where
these are all listed out and linked to what's in the code and can be dynamically
updated such that the user, if he has some ways that he says how he wants to
shorten or update, then he can just put it there."*

The built-in words are shown as READ-ONLY FACT, read out of the module that
actually uses them (`lexicon.Lexicon.built_in()`) rather than copied here. A
copy is the defect the whole feature exists to prevent — the bug that started it
was two hand-typed lists of the same idea drifting apart.

Adding is the only edit that reaches the engine's own words: a built-in cannot be
removed, so tuning your phrasing can widen what the assistant understands and can
never take a word away and break a command that used to work.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from assistant.calendar_ui import styles as _styles
from assistant.calendar_ui.styles import GRAY_TEXT


class LexiconDialog(QDialog):
    """One collapsible block per list: what the code knows, and what you added."""

    def __init__(self, parent=None, dark: bool = True) -> None:
        super().__init__(parent)
        self._dark = dark
        self.setWindowTitle("How I Say Things")
        self.setMinimumSize(560, 620)

        from assistant.intent.lexicon import get_lexicon
        self._store = get_lexicon()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        intro = QLabel(
            "The assistant recognises these words. Add the ones YOU use and it "
            "will understand them too — your words are only ever added to what "
            "it already knows, never taken away.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color: {_styles.D_GRAY_TEXT if dark else GRAY_TEXT}; font-size: 12px;")
        outer.addWidget(intro)

        self._blocks: dict = {}
        for entry in self._store.describe():
            outer.addWidget(self._block(entry))

        outer.addStretch(1)
        close = QPushButton("Done")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        outer.addLayout(row)

    # ------------------------------------------------------------------

    def _block(self, entry: dict) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(6)

        title = QLabel(entry["label"])
        title.setStyleSheet("font-weight: 600;")
        lay.addWidget(title)

        why = QLabel(entry["why"])
        why.setWordWrap(True)
        why.setStyleSheet(
            f"color: {_styles.D_GRAY_TEXT if self._dark else GRAY_TEXT}; font-size: 11px;")
        lay.addWidget(why)

        # The built-ins, as fact. Not editable, and said plainly rather than
        # hidden — "linked to what's in the code" was the request.
        known = QLabel("Already known: " + ", ".join(entry["built_in"]))
        known.setWordWrap(True)
        known.setStyleSheet(
            f"color: {_styles.D_GRAY_TEXT if self._dark else GRAY_TEXT}; font-size: 11px;")
        known.setToolTip(f"From {entry['source']} — built in, and not removable.")
        lay.addWidget(known)

        mine = QListWidget()
        mine.setObjectName(f"lexicon_added_{entry['name']}")
        mine.setMaximumHeight(96)
        for word in entry["added"]:
            mine.addItem(QListWidgetItem(word))
        lay.addWidget(mine)

        field = QLineEdit()
        field.setObjectName(f"lexicon_input_{entry['name']}")
        field.setPlaceholderText(f"Add a word — e.g. {entry['example']}")
        add = QPushButton("Add")
        add.setObjectName(f"lexicon_add_{entry['name']}")
        remove = QPushButton("Remove")
        remove.setObjectName(f"lexicon_remove_{entry['name']}")
        remove.setToolTip("Removes one of YOUR words. Built-in words stay.")

        controls = QHBoxLayout()
        controls.addWidget(field, 1)
        controls.addWidget(add)
        controls.addWidget(remove)
        lay.addLayout(controls)

        name = entry["name"]

        def _add(_checked=False, _n=name, _f=field, _l=mine):
            word = _f.text().strip()
            if not word:
                return
            if not self._store.add(_n, word):
                QMessageBox.information(
                    self, "Already known",
                    f"“{word}” is already one of the words the assistant uses "
                    f"for this.")
                _f.clear()
                return
            _f.clear()
            self._refill(_n, _l)

        def _remove(_checked=False, _n=name, _l=mine):
            item = _l.currentItem()
            if item is None:
                return
            self._store.remove(_n, item.text())
            self._refill(_n, _l)

        add.clicked.connect(_add)
        field.returnPressed.connect(_add)
        remove.clicked.connect(_remove)
        self._blocks[name] = mine
        return box

    def _refill(self, name: str, widget: QListWidget) -> None:
        widget.clear()
        for word in self._store.added(name):
            widget.addItem(QListWidgetItem(word))
