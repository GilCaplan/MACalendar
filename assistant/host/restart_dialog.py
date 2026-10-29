"""The "Restart the brain" window: what a click on the Server's icon opens.

The brain is the API every app talks to (the calendar, the HUD, the phones).
Clicking the icon while the Server runs used to only show the pairing QR, so
after an update the old code went on serving until someone found the service
to restart by hand (2026-10-24). Now the click offers the restart, with the
one setting a restart can change — the port, 8080 unless config.yaml says
otherwise — and the QR stays one button away.

``restart`` and ``save_port`` are injectable: the tests click the window
without stopping a real server or writing the real config.yaml.
"""

from __future__ import annotations

import threading
from typing import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                             QSpinBox, QVBoxLayout)

DEFAULT_PORT = 8080


def _save_port_live(port: int) -> bool:
    from assistant.config_store import set_values
    return set_values({"api": {"port": port}})


class RestartDialog(QDialog):
    #: (ok, message) — the restart ran on a thread; this lands on the UI one.
    finished_restart = pyqtSignal(bool, str)

    def __init__(self, parent=None, port: int = DEFAULT_PORT,
                 restart: Callable[[int], str] | None = None,
                 save_port: Callable[[int], bool] | None = None,
                 pair: Callable[[], None] | None = None):
        super().__init__(parent)
        self.setWindowTitle("MACalendar Server")
        self._current = port
        self._restart = restart
        self._save_port = save_port or _save_port_live
        self._pair = pair

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(14)

        title = QLabel("Restart the brain")
        f = title.font()
        f.setPointSizeF(f.pointSizeF() * 1.35)
        f.setWeight(f.Weight.DemiBold)
        title.setFont(f)
        lay.addWidget(title)

        about = QLabel("The brain is the server the calendar, the thinking card and your "
                       "phones connect to. Restarting it loads the newest version; they "
                       "reconnect by themselves in a few seconds.")
        about.setWordWrap(True)
        lay.addWidget(about)

        row = QHBoxLayout()
        row.addWidget(QLabel("Port"))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(port)
        self.port.valueChanged.connect(lambda _v: self._show_port_note())
        row.addWidget(self.port)
        self.default_btn = QPushButton(f"Default ({DEFAULT_PORT})")
        self.default_btn.clicked.connect(lambda: self.port.setValue(DEFAULT_PORT))
        row.addWidget(self.default_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self.port_note = QLabel("")
        self.port_note.setWordWrap(True)
        self.port_note.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.port_note)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.hide()
        lay.addWidget(self.status)

        buttons = QHBoxLayout()
        self.pair_btn = QPushButton("Pair a phone…")
        self.pair_btn.clicked.connect(lambda: self._on_pair())
        self.pair_btn.setVisible(pair is not None)
        buttons.addWidget(self.pair_btn)
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(lambda: self.reject())
        buttons.addWidget(self.cancel_btn)
        self.restart_btn = QPushButton("Restart")
        self.restart_btn.setDefault(True)
        self.restart_btn.clicked.connect(lambda: self.do_restart())
        buttons.addWidget(self.restart_btn)
        lay.addLayout(buttons)

        self.finished_restart.connect(self._on_done)
        self._show_port_note()

    def _show_port_note(self) -> None:
        moved = self.port.value() != self._current
        self.port_note.setText(
            f"Moving off port {self._current}: the calendar and the thinking card follow, "
            "but a phone paired on the old port has to pair again." if moved else "")
        self.port_note.setVisible(moved)

    def _on_pair(self) -> None:
        self.accept()
        self._pair()

    def do_restart(self) -> None:
        port = self.port.value()
        if port != self._current and not self._save_port(port):
            self._on_done(False, "Couldn't save the port: config.yaml is missing.")
            return
        self.restart_btn.setEnabled(False)
        self.port.setEnabled(False)
        self.status.setStyleSheet("")
        self.status.setText("Restarting…")
        self.status.show()

        old = self._current

        def run():
            try:
                self.finished_restart.emit(True, self._restart(port) or "")
            except Exception as exc:
                # The API reads the port at start, so it was saved first; a
                # restart that failed must not leave every client pointed at
                # a port nothing listens on.
                if port != old:
                    self._save_port(old)
                self.finished_restart.emit(False, str(exc))
        threading.Thread(target=run, name="host-restart", daemon=True).start()

    def _on_done(self, ok: bool, message: str) -> None:
        self.restart_btn.setEnabled(True)
        self.port.setEnabled(True)
        self.status.show()
        if ok:
            self._current = self.port.value()
            self._show_port_note()
            self.status.setStyleSheet("color: #30a46c;")
            self.status.setText(f"Restarted — the brain is coming back on port {self._current}.")
        else:
            self.port.setValue(self._current)
            self.status.setStyleSheet("color: #e5484d;")
            self.status.setText(message)
