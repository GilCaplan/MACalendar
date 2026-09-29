"""The Servers panel: which computers run the model, and the server's log.

One widget, two homes (DEVQA Q70): the menu-bar app's "Servers & logs"
window and the calendar's Settings ▸ Server. It talks to the API over HTTP on
this machine — the only place the helper list may be changed — so it shows
the same thing wherever it is opened. ``api`` is injectable: tests hand it a
fake, and never reach the live server.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)

Api = Callable[..., dict]


def http_api(port: int = 8080) -> Api:
    """``api(method, path, body=None) -> dict`` against this machine's API."""
    def call(method: str, path: str, body: dict | None = None) -> dict:
        from assistant.host.supervisor import api_headers
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=data, method=method,
            headers=dict(api_headers(), **({"Content-Type": "application/json"} if data else {})))
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return {"error": json.loads(e.read().decode()).get("error", str(e))}
            except ValueError:
                return {"error": str(e)}
        except Exception as e:                  # not running, refused, timed out
            return {"error": f"the server isn't answering ({type(e).__name__})"}
    return call


def _dot(host: dict) -> str:
    if not host.get("up"):
        return "○"
    return "●" if host.get("matched") else "◐"


def describe(host: dict) -> str:
    """One line per machine, in words."""
    who = "This computer" if host.get("kind") == "this" else host.get("name", "")
    bits = [f"{_dot(host)}  {who}"]
    if host.get("kind") != "this":
        bits.append(f"· {host.get('os') or '?'}")
    else:
        bits.append(f"({host.get('name', '')} · {host.get('os', '')})")
    if not host.get("up"):
        bits.append(f"— {host.get('why') or 'not reachable'}")
    elif not host.get("matched"):
        bits.append(f"— not used: {host.get('why')}")
    elif host.get("busy"):
        bits.append("— busy")
    else:
        bits.append("— ready")
    return " ".join(bits)


class AddHelperDialog(QDialog):
    """Pick a helper found on the network (or type its address) and enter the
    code its screen shows."""

    def __init__(self, parent=None, api: Api | None = None, found: list | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add a model helper")
        self._api = api
        self.added: dict | None = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("On the other computer, open MACalendar Server and choose\n"
                             "“This computer is ▸ A model helper”. It shows a code."))
        self.found = QListWidget()
        for f in (found or []):
            item = QListWidgetItem(f"{f.get('name')} · {f.get('os', '?')}  —  "
                                   + ", ".join(u.removeprefix('http://') for u in f.get("urls", [])))
            item.setData(Qt.ItemDataRole.UserRole, f.get("urls", []))
            self.found.addItem(item)
        if found:
            self.found.setCurrentRow(0)
        self.found.setVisible(bool(found))
        lay.addWidget(self.found)
        self.none = QLabel("No helper announced itself on this network. Type its address\n"
                           "instead (for example 100.x.x.x:11436 over Tailscale).")
        self.none.setVisible(not found)
        lay.addWidget(self.none)
        self.address = QLineEdit()
        self.address.setPlaceholderText("Address, if it isn't listed — host:11436")
        lay.addWidget(self.address)
        self.code = QLineEdit()
        self.code.setPlaceholderText("The code on the helper's screen, e.g. ABCD-EFGH")
        lay.addWidget(self.code)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #e5484d;")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.reject())
        self.add_btn = QPushButton("Add")
        self.add_btn.setDefault(True)
        self.add_btn.clicked.connect(lambda: self._add())
        row.addWidget(cancel)
        row.addWidget(self.add_btn)
        lay.addLayout(row)
        self.setMinimumWidth(460)

    def urls(self) -> list[str]:
        typed = self.address.text().strip()
        if typed:
            if not typed.startswith("http"):
                typed = "http://" + typed
            if typed.count(":") < 2:
                typed += ":11436"
            return [typed]
        item = self.found.currentItem()
        return list(item.data(Qt.ItemDataRole.UserRole)) if item else []

    def _add(self) -> None:
        urls, code = self.urls(), self.code.text().strip()
        if not urls or not code:
            self.error.setText("Pick a computer (or type its address) and enter its code.")
            self.error.show()
            return
        got = self._api("POST", "/servers/helpers", {"urls": urls, "code": code})
        if got.get("error"):
            self.error.setText(got["error"])
            self.error.show()
            return
        self.added = got
        self.accept()


class ServersPanel(QWidget):
    def __init__(self, parent=None, port: int = 8080, api: Api | None = None,
                 open_terminal: Callable[[], None] | None = None):
        super().__init__(parent)
        self._api = api or http_api(port)
        self._open_terminal = open_terminal
        self.state: dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.this = QLabel("")
        self.this.setWordWrap(True)
        self.this.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.this)

        title = QLabel("Where model calls run")
        f = title.font()
        f.setWeight(QFont.Weight.DemiBold)
        title.setFont(f)
        lay.addWidget(title)
        self.hosts = QListWidget()
        self.hosts.setMinimumHeight(90)
        self.hosts.currentRowChanged.connect(lambda _r: self._update_buttons())
        lay.addWidget(self.hosts)
        self.hint = QLabel("A call goes to the first computer that is up and has the same "
                           "model. This computer is skipped while it is busy if a helper "
                           "comes after it. Boards always stay on this computer.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.hint)

        row = QHBoxLayout()
        self.up_btn = QPushButton("Move up")
        self.up_btn.clicked.connect(lambda: self.move(-1))
        self.down_btn = QPushButton("Move down")
        self.down_btn.clicked.connect(lambda: self.move(1))
        self.remove_btn = QPushButton("Stop using")
        self.remove_btn.clicked.connect(lambda: self.remove())
        self.add_btn = QPushButton("Add a helper…")
        self.add_btn.clicked.connect(lambda: self.add_helper())
        for b in (self.up_btn, self.down_btn, self.remove_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.add_btn)
        lay.addLayout(row)

        self.error = QLabel("")
        self.error.setStyleSheet("color: #e5484d;")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(line)
        log_title = QLabel("Server log")
        log_title.setFont(f)
        lay.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.setMinimumHeight(180)
        lay.addWidget(self.log, 1)
        lrow = QHBoxLayout()
        self.terminal_btn = QPushButton("Open in Terminal")
        self.terminal_btn.clicked.connect(lambda: self.open_terminal())
        lrow.addWidget(self.terminal_btn)
        lrow.addStretch(1)
        lay.addLayout(lrow)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh_log)
        self.reload()

    # -- loading ----------------------------------------------------------------
    def reload(self) -> None:
        got = self._api("GET", "/servers")
        if got.get("error") or "hosts" not in got:
            self.state = {}
            self.this.setText("The server isn't answering. Start MACalendar Server and "
                              "this fills in.")
            self.hosts.clear()
            self._update_buttons()
            return
        self.state = got
        t = got["this"]
        where = ", ".join(u.removeprefix("http://") for u in t.get("urls", [])) or "—"
        self.this.setText(f"<b>{t['name']}</b> · {t['os']} · the primary (the brain)"
                          f"<br>Reachable at {where} · model {t.get('model', '')}")
        keep = self.hosts.currentRow()
        self.hosts.clear()
        for h in got["hosts"]:
            item = QListWidgetItem(describe(h))
            item.setData(Qt.ItemDataRole.UserRole, h["id"])
            self.hosts.addItem(item)
        self.hosts.setCurrentRow(min(max(keep, 0), self.hosts.count() - 1))
        self._update_buttons()
        self.refresh_log()

    def refresh_log(self) -> None:
        got = self._api("GET", "/servers/logs?lines=300")
        lines = got.get("lines")
        if lines is None:
            return
        text = "\n".join(lines) or "(nothing logged yet)"
        if text != self.log.toPlainText():
            at_end = self.log.verticalScrollBar().value() >= self.log.verticalScrollBar().maximum() - 4
            self.log.setPlainText(text)
            if at_end:
                self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def showEvent(self, ev):                # live only while someone is looking
        super().showEvent(ev)
        self._timer.start()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._timer.stop()

    # -- actions ----------------------------------------------------------------
    def _selected(self) -> str | None:
        item = self.hosts.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self) -> None:
        row, n = self.hosts.currentRow(), self.hosts.count()
        self.up_btn.setEnabled(row > 0)
        self.down_btn.setEnabled(0 <= row < n - 1)
        self.remove_btn.setEnabled(self._selected() not in (None, "local"))
        self.add_btn.setEnabled(bool(self.state))

    def _show_error(self, got: dict) -> bool:
        if got.get("error"):
            self.error.setText(got["error"])
            self.error.show()
            return True
        self.error.hide()
        return False

    def move(self, step: int) -> None:
        order = [self.hosts.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.hosts.count())]
        row = self.hosts.currentRow()
        to = row + step
        if not (0 <= row < len(order) and 0 <= to < len(order)):
            return
        order[row], order[to] = order[to], order[row]
        if not self._show_error(self._api("PUT", "/servers/order", {"order": order})):
            self.reload()
            self.hosts.setCurrentRow(to)

    def remove(self) -> None:
        hid = self._selected()
        if hid in (None, "local"):
            return
        if not self._show_error(self._api("DELETE", f"/servers/helpers/{hid}")):
            self.reload()

    def add_helper(self) -> None:
        found = self._api("GET", "/servers/found").get("found", [])
        dlg = AddHelperDialog(self, api=self._api, found=found)
        if dlg.exec() and dlg.added:
            self.reload()

    def open_terminal(self) -> None:
        if self._open_terminal is not None:
            self._open_terminal()
            return
        from assistant.host import logs
        logs.open_terminal()
