"""What a MODEL HELPER shows on its own screen (DEVQA Q70): the code a primary
types to start using it, who uses it now, and its log."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QPushButton,
                             QVBoxLayout)

from assistant.host import logs
from assistant.pairing import codes


class HelperWindow(QDialog):
    def __init__(self, helper, parent=None, open_terminal: Callable[[], None] | None = None):
        super().__init__(parent)
        self.helper = helper
        self._open_terminal = open_terminal or (lambda: logs.open_terminal(logs.HOST_LOG))
        self.setWindowTitle("Model helper")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)

        head = QLabel(f"<b>{helper.name}</b> lends its model to your primary.")
        head.setWordWrap(True)
        lay.addWidget(head)
        how = QLabel("On the primary: MACalendar Server ▸ Servers & logs ▸ Add a helper, "
                     "pick this computer, and type this code:")
        how.setWordWrap(True)
        lay.addWidget(how)
        self.code = QLabel("")
        f = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        f.setPointSizeF(f.pointSizeF() * 2.2)
        f.setWeight(QFont.Weight.DemiBold)
        self.code.setFont(f)
        self.code.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.code)

        lay.addWidget(QLabel("Using this computer's model:"))
        self.users = QListWidget()
        self.users.setMaximumHeight(90)
        self.users.currentRowChanged.connect(
            lambda r: self.forget_btn.setEnabled(r >= 0 and bool(self.users.item(r).data(Qt.ItemDataRole.UserRole))))
        lay.addWidget(self.users)
        row = QHBoxLayout()
        self.forget_btn = QPushButton("Stop lending to it")
        self.forget_btn.setEnabled(False)
        self.forget_btn.clicked.connect(lambda: self.forget())
        row.addWidget(self.forget_btn)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(QLabel("Log"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.setMinimumHeight(160)
        lay.addWidget(self.log, 1)
        lrow = QHBoxLayout()
        self.terminal_btn = QPushButton("Open in Terminal")
        self.terminal_btn.clicked.connect(lambda: self._open_terminal())
        lrow.addWidget(self.terminal_btn)
        lrow.addStretch(1)
        done = QPushButton("Done")
        done.clicked.connect(lambda: self.accept())
        lrow.addWidget(done)
        lay.addLayout(lrow)
        self.setMinimumWidth(460)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.reload)
        self._timer.start()
        self.reload()

    def reload(self) -> None:
        self.code.setText(codes.pretty(self.helper.code))
        keep = self.users.currentRow()
        self.users.clear()
        people = self.helper.primaries()
        for p in people:
            item = QListWidgetItem(p.get("primary", "a primary"))
            item.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.users.addItem(item)
        if not people:
            item = QListWidgetItem("Nobody yet")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.users.addItem(item)
        if 0 <= keep < self.users.count():
            self.users.setCurrentRow(keep)
        text = "\n".join(logs.tail(logs.HOST_LOG, 200)) or "(nothing logged yet)"
        if text != self.log.toPlainText():
            self.log.setPlainText(text)
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def forget(self) -> None:
        item = self.users.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole):
            self.helper.forget(item.data(Qt.ItemDataRole.UserRole))
            self.reload()
