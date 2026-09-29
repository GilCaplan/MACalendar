"""The "Pair a phone or tablet" window: a QR code and how to use it.

Opened from the server's menu-bar icon and from the calendar's More menu.
It asks the running API for a one-time code (``POST /pair/start``), paints
the ``macalendar://pair`` link as a QR, counts the code down, and fetches a
fresh one when it runs out — so the window can be left open.

``fetch`` is injectable: the tests hand it a dict instead of reaching the live
API (tests/conftest.py refuses the API port, and a test must not mint codes on
the real server).
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from assistant.pairing.link import qr_matrix


class QRView(QWidget):
    """A QR code painted module by module — black on white whatever the theme,
    because a camera reads contrast, not the user's colour scheme."""

    def __init__(self, parent=None, side: int = 240):
        super().__init__(parent)
        self._m: list[list[bool]] = []
        self.setFixedSize(side, side)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_text(self, text: str) -> None:
        self._m = qr_matrix(text) if text else []
        self.update()

    def modules(self) -> int:
        return len(self._m)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        if not self._m:
            p.end()
            return
        n = len(self._m)
        cell = (min(self.width(), self.height()) - 16) / n
        off = (self.width() - cell * n) / 2
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setBrush(QColor("#000000"))
        for y, row in enumerate(self._m):
            for x, dark in enumerate(row):
                if dark:
                    p.drawRect(QRectF(off + x * cell, off + y * cell, cell + 0.5, cell + 0.5))
        p.end()


class PairDialog(QDialog):
    def __init__(self, parent=None, fetch: Callable[[], dict] | None = None,
                 port: int = 8080):
        super().__init__(parent)
        self.setWindowTitle("Pair a phone or tablet")
        self._port = port
        self._fetch = fetch or self._fetch_live
        self._left = 0
        self.info: dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(14)

        title = QLabel("Pair a phone or tablet")
        f = title.font()
        f.setPointSizeF(f.pointSizeF() * 1.35)
        f.setWeight(f.Weight.DemiBold)
        title.setFont(f)
        lay.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.qr = QRView(self)
        lay.addWidget(self.qr, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.steps = QLabel(
            "1.  Open the <b>Camera</b> on your iPhone or iPad and point it at the code.<br>"
            "2.  Tap <b>Open in MACalendar</b>. That's all — it connects by itself.")
        self.steps.setWordWrap(True)
        self.steps.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.steps)

        self.wifi = QLabel("On the same Wi-Fi? In MACalendar open <b>Settings ▸ Your "
                           "Mac</b> and tap this computer instead.")
        self.wifi.setWordWrap(True)
        self.wifi.setTextFormat(Qt.TextFormat.RichText)
        self.wifi.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.wifi)

        self.code = QLabel("")
        self.code.setStyleSheet("color: palette(placeholder-text);")
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.code, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #e5484d;")
        self.error.hide()
        lay.addWidget(self.error)

        row = QHBoxLayout()
        self.new_btn = QPushButton("New code")
        self.new_btn.clicked.connect(lambda: self.refresh())
        self.done_btn = QPushButton("Done")
        self.done_btn.setDefault(True)
        self.done_btn.clicked.connect(lambda: self.accept())
        row.addWidget(self.new_btn)
        row.addStretch(1)
        row.addWidget(self.done_btn)
        lay.addLayout(row)

        self.setFixedWidth(400)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._count_down)
        self.refresh()

    def _fetch_live(self) -> dict:
        from assistant.host.supervisor import start_pairing
        return start_pairing(self._port)

    def refresh(self) -> None:
        """Fetch a fresh code and draw it."""
        try:
            info = self._fetch()
            if not info.get("link"):
                raise RuntimeError(info.get("error") or "no link in the answer")
        except Exception as exc:
            self.info = {}
            self.qr.set_text("")
            self.code.setText("")
            self.error.setText("The server isn't answering, so there is no code to show "
                               f"yet. Start MACalendar Server and try again.\n({exc})")
            self.error.show()
            self._tick.stop()
            return
        self.info = info
        self.error.hide()
        self.qr.set_text(info["link"])
        self._left = int(info.get("expires_in") or 600)
        self._draw_code()
        self._tick.start()

    def _draw_code(self) -> None:
        m, s = divmod(max(0, self._left), 60)
        where = ", ".join(u.removeprefix("http://") for u in self.info.get("urls", [])) \
            or "no network address found"
        self.code.setText(f"{self.info.get('name', '')}  ·  code {self.info.get('pretty', '')}"
                          f"  ·  {m}:{s:02d}\n{where}")
        self.code.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    def _count_down(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self.refresh()          # the old code is dead; show a live one
        else:
            self._draw_code()
