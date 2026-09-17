"""Where the question is typed, and the two dials that shape the answer.

`top_k` is how many passages Jude retrieves before it filters — the difference
between a quick answer and a sugya — and the language toggle decides which
language it answers in, not which language you ask in. Both sit above the
entry rather than behind a menu because they are changed per question.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QTextEdit,
    QVBoxLayout, QWidget,
)

TOP_K_MIN, TOP_K_MAX, TOP_K_DEFAULT = 5, 30, 25

# One line to start with, five before it stops growing — past that the entry
# would eat the answer it is about to be added to.
ENTRY_MIN_H = 38
ENTRY_MAX_H = 130


class _Entry(QTextEdit):
    """Multiline, but Enter sends.

    A study question is usually one line and occasionally a paragraph, so the
    field has to be both: Enter sends, Shift+Enter is a newline. That is the
    convention every chat surface uses, including Jude's own web UI, and the
    reverse would surprise everyone who has used one.
    """

    submitted = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setPlaceholderText("Ask Jude about Torah, Talmud, Halacha, Kabbalah…")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(ENTRY_MIN_H)
        self.textChanged.connect(self._grow)

    def keyPressEvent(self, event) -> None:            # noqa: N802 - Qt naming
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if enter and not shift:
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def _grow(self) -> None:
        height = int(self.document().size().height()) + 14
        self.setFixedHeight(max(ENTRY_MIN_H, min(height, ENTRY_MAX_H)))


class Composer(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._lang = "en"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 12)
        lay.setSpacing(6)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self._k_group = QWidget(self)
        k_lay = QHBoxLayout(self._k_group)
        k_lay.setContentsMargins(0, 0, 0, 0)
        k_lay.setSpacing(6)
        k_label = QLabel("Sources")
        k_label.setStyleSheet(f"color:{theme.text2}; font-size:11px;")
        k_lay.addWidget(k_label)
        self._k = QSlider(Qt.Orientation.Horizontal, self._k_group)
        self._k.setRange(TOP_K_MIN, TOP_K_MAX)
        self._k.setValue(TOP_K_DEFAULT)
        self._k.setFixedWidth(120)
        k_lay.addWidget(self._k)
        self._k_value = QLabel(str(TOP_K_DEFAULT))
        self._k_value.setFixedWidth(20)
        self._k_value.setStyleSheet(
            f"color:{theme.text}; font-size:11px; font-family:{theme.mono};")
        self._k.valueChanged.connect(lambda v: self._k_value.setText(str(v)))
        k_lay.addWidget(self._k_value)
        controls.addWidget(self._k_group)
        controls.addStretch(1)

        self._lang_buttons = {}
        for key, label in (("en", "EN"), ("he", "עב")):
            button = QPushButton(label)
            button.setObjectName("seg_btn")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedWidth(42)
            button.clicked.connect(lambda _checked=False, k=key: self.set_lang(k))
            self._lang_buttons[key] = button
            controls.addWidget(button)
        self._paint_lang()
        lay.addLayout(controls)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._entry = _Entry(self)
        self._entry.submitted.connect(self._submit)
        row.addWidget(self._entry, 1)

        self._ask = QPushButton("Ask")
        self._ask.setObjectName("primary")
        self._ask.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ask.setFixedHeight(ENTRY_MIN_H)
        self._ask.clicked.connect(self._submit)
        row.addWidget(self._ask)
        lay.addLayout(row)

        disclaimer = QLabel("⚠ Jude can make mistakes. Verify rulings and citations "
                            "with a qualified rabbi.")
        disclaimer.setStyleSheet(f"color:{theme.text2}; font-size:10px;")
        lay.addWidget(disclaimer)

    # ------------------------------------------------------------- values

    @property
    def top_k(self) -> int:
        return self._k.value()

    @property
    def lang(self) -> str:
        return self._lang

    def set_lang(self, lang: str) -> None:
        self._lang = "he" if lang == "he" else "en"
        self._paint_lang()

    def _paint_lang(self) -> None:
        for key, button in self._lang_buttons.items():
            button.setProperty("active", "true" if key == self._lang else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def set_top_k_visible(self, visible: bool) -> None:
        """Sources mode ignores it — the count comes from the router's source
        plan — and a dial that does nothing is worse than no dial."""
        self._k_group.setVisible(visible)

    def set_text(self, text: str) -> None:
        self._entry.setPlainText(text)
        self._entry.moveCursor(self._entry.textCursor().MoveOperation.End)

    def focus_entry(self) -> None:
        self._entry.setFocus()

    def set_busy(self, busy: bool) -> None:
        self._ask.setEnabled(not busy)
        self._ask.setText("Thinking…" if busy else "Ask")

    def set_enabled(self, enabled: bool) -> None:
        self._entry.setEnabled(enabled)
        self._ask.setEnabled(enabled)

    def _submit(self) -> None:
        text = self._entry.toPlainText().strip()
        if not text:
            return
        self._entry.clear()
        self.submitted.emit(text)
