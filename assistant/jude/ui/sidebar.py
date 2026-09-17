"""New chat, the three modes, and every conversation you have had.

There is deliberately no account, no sign-in and no user chip, although Jude's
own web UI has all three: Jude scopes its history per user because it is used
from a shared browser, and `routes.py` pins that to one fixed owner. This is
one person's Mac talking to one person's assistant, and a login screen here
would be friction buying nothing.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

# Wide enough for the three mode buttons on ONE ROW without eliding. At 236 they
# rendered as "QA | Stud | Sourc": the app QSS gives #seg_btn 14px of horizontal
# padding each, which with the emoji needs ~272px of the ~212px there were. The
# extra width also gives chat titles somewhere to go.
SIDEBAR_WIDTH = 280

MODES = [("qa", "⚡ Q&A"), ("study", "📖 Study"), ("sources", "📋 Sources")]


class _ChatRow(QWidget):
    opened = pyqtSignal(str, str)         # id, title
    deleted = pyqtSignal(str)

    def __init__(self, chat: dict, theme, parent=None) -> None:
        super().__init__(parent)
        self._id = str(chat.get("id") or "")
        self._title = str(chat.get("title") or "Untitled")
        self._theme = theme

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._open = QPushButton("📝  " + self._title)
        self._open.setObjectName("flat")
        self._open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open.setToolTip(self._title)
        self._open.clicked.connect(lambda: self.opened.emit(self._id, self._title))
        lay.addWidget(self._open, 1)

        remove = QPushButton("✕")
        remove.setObjectName("flat")
        remove.setFixedWidth(24)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip("Delete this conversation")
        remove.setStyleSheet(f"color:{theme.text2};")
        remove.clicked.connect(lambda: self.deleted.emit(self._id))
        lay.addWidget(remove)

        self.set_active(False)

    def set_active(self, active: bool) -> None:
        theme = self._theme
        # Elide in the stylesheet's own terms — a long question would otherwise
        # widen the button and push the delete control off the sidebar.
        self._open.setStyleSheet(
            f"text-align:left; padding:5px 8px; font-size:12px;"
            f" color:{theme.text if active else theme.text2};"
            + (f" background:{theme.surface}; border:1px solid {theme.border};"
               f" border-radius:{theme.radius_sm}px;" if active else ""))


class Sidebar(QWidget):
    new_chat = pyqtSignal()
    mode_changed = pyqtSignal(str)
    chat_opened = pyqtSignal(str, str)
    chat_deleted = pyqtSignal(str)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._rows: "dict[str, _ChatRow]" = {}
        self._mode = "qa"
        self.setObjectName("sidebar")          # styled by get_app_style()
        self.setFixedWidth(SIDEBAR_WIDTH)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(8)

        brand = QLabel("🕎  <b>Jude</b>")
        brand.setStyleSheet(f"color:{theme.text}; font-size:15px;")
        lay.addWidget(brand)
        tagline = QLabel("Your Judaic study assistant")
        tagline.setStyleSheet(f"color:{theme.text2}; font-size:11px;")
        lay.addWidget(tagline)

        new = QPushButton("＋  New chat")
        new.setObjectName("primary")
        new.setCursor(Qt.CursorShape.PointingHandCursor)
        # ⌘N is a window-level shortcut (see JudeWindow), NOT one on this
        # button: two objects claiming the same sequence makes Qt call it
        # ambiguous and fire neither.
        new.setToolTip("New chat (⌘N)")
        new.clicked.connect(self.new_chat)
        lay.addWidget(new)

        modes = QHBoxLayout()
        modes.setSpacing(2)
        self._mode_buttons: "dict[str, QPushButton]" = {}
        for key, label in MODES:
            button = QPushButton(label)
            button.setObjectName("seg_btn")
            # Tighter than the app default (5px 14px): three of these share one
            # row, and the shared style is written for toolbars with space.
            button.setStyleSheet("QPushButton#seg_btn { padding: 5px 8px; }")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.set_mode(k))
            self._mode_buttons[key] = button
            modes.addWidget(button)
        lay.addLayout(modes)
        self._paint_modes()

        heading = QLabel("CONVERSATIONS")
        heading.setStyleSheet(
            f"color:{theme.text2}; font-size:10px; font-weight:700;"
            " letter-spacing:0.06em; padding-top:4px;")
        lay.addWidget(heading)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._holder = QWidget()
        self._list = QVBoxLayout(self._holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(1)
        self._list.addStretch(1)
        self._scroll.setWidget(self._holder)
        lay.addWidget(self._scroll, 1)

        self._footer = QLabel("")
        self._footer.setWordWrap(True)
        self._footer.setStyleSheet(f"color:{theme.text2}; font-size:10px;")
        lay.addWidget(self._footer)

    # ---------------------------------------------------------------- mode

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._paint_modes()
        self.mode_changed.emit(mode)

    def _paint_modes(self) -> None:
        for key, button in self._mode_buttons.items():
            # The app stylesheet styles seg_btn[active="true"]; a dynamic
            # property only repaints after the style is re-polished.
            button.setProperty("active", "true" if key == self._mode else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    # --------------------------------------------------------------- chats

    def set_chats(self, chats: list, active_id: "str | None" = None) -> None:
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows.clear()

        for chat in chats or []:
            if not isinstance(chat, dict) or not chat.get("id"):
                continue
            row = _ChatRow(chat, self._theme, self._holder)
            row.opened.connect(self.chat_opened)
            row.deleted.connect(self.chat_deleted)
            self._rows[str(chat["id"])] = row
            self._list.insertWidget(self._list.count() - 1, row)
        self.set_active(active_id)

    def set_active(self, chat_id: "str | None") -> None:
        for key, row in self._rows.items():
            row.set_active(key == chat_id)

    def set_footer(self, text: str) -> None:
        self._footer.setText(text)
