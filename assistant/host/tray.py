"""The server's menu-bar icon (system tray on Windows and Linux) and its menu.

One instance per machine: a second click on the app finds the first through a
local socket and asks it to show the pairing window instead of starting again
— so "click the Server app" always does something useful.
"""

from __future__ import annotations

import platform
import signal
import sys
import threading

from PyQt6.QtCore import QObject, QPointF, QRectF, QSettings, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from assistant.host import autostart
from assistant.host import role as role_mod
from assistant.host.supervisor import Stack

INSTANCE = "macalendar-server-host"
OLLAMA_DOWNLOAD = "https://ollama.com/download"
POLL_MS = 5000


def tray_icon(color: str = "#000000", mask: bool = True) -> QIcon:
    """A small calendar page: outline, header bar, two binder rings. Drawn as a
    macOS TEMPLATE (black + alpha, ``setIsMask``) so the menu bar tints it for
    light and dark; elsewhere drawn in ``color``."""
    pm = QPixmap(36, 36)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = QColor(color)
    p.setPen(QPen(c, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 4.0, 13.0, 12.0), 2.5, 2.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(2.5, 4.0, 13.0, 3.6))
    for x in (6.0, 12.0):
        p.drawRoundedRect(QRectF(x - 0.9, 2.0, 1.8, 3.6), 0.9, 0.9)
    for i, (x, y) in enumerate(((6, 10.5), (9, 10.5), (12, 10.5), (6, 13.3), (9, 13.3))):
        p.drawEllipse(QPointF(x, y), 0.9, 0.9)
    p.end()
    icon = QIcon(pm)
    icon.setIsMask(mask)
    return icon


class _Poller(QObject):
    """Reads the stack's status off the UI thread (a /health that hangs must
    not freeze the menu) and hands it back as a signal."""
    got = pyqtSignal(dict)

    def __init__(self, stack: Stack):
        super().__init__()
        self._stack = stack
        self._busy = False

    def poll(self) -> None:
        if self._busy:
            return
        self._busy = True

        def run():
            try:
                st = self._stack.status()
            except Exception as exc:          # never let a reading kill the app
                st = {"api": False, "error": str(exc)}
            self._busy = False
            self.got.emit(st)
        threading.Thread(target=run, name="host-status", daemon=True).start()


class HostTray(QObject):
    def __init__(self, app: QApplication, stack: Stack | None = None,
                 start: bool = True):
        super().__init__()
        self.app = app
        self.stack = stack or Stack()
        self.state: dict = {}
        self._dialog = None
        self._servers_win = None
        self.role = role_mod.get()
        self.helper = None
        self._settings = QSettings("MACalendar", "Server")
        self._started = self._start_role() if start else []

        mac = platform.system() == "Darwin"
        self.tray = QSystemTrayIcon(tray_icon("#000000" if mac else "#f5a524", mask=mac))
        self.tray.setToolTip("MACalendar Server")
        self.menu = QMenu()
        self.status_act = self._info("Starting…")
        self.where_act = self._info("")
        self.devices_act = self._info("")
        self.setup_act = QAction("", self.menu)
        self.setup_act.triggered.connect(lambda: self._fix_setup())
        self.menu.addAction(self.setup_act)
        self.menu.addSeparator()
        self.pair_act = self.menu.addAction("Pair a phone or tablet…")
        self.pair_act.triggered.connect(lambda: self.show_pairing())
        self.servers_act = self.menu.addAction("Servers & logs…")
        self.servers_act.triggered.connect(lambda: self.show_servers())
        self.open_act = self.menu.addAction("Open calendar")
        self.open_act.triggered.connect(lambda: self.open_calendar())
        self.menu.addSeparator()
        # The role (DEVQA Q70): the brain, or a machine that lends its model.
        self.role_menu = self.menu.addMenu("This computer is")
        group = QActionGroup(self.role_menu)
        group.setExclusive(True)
        self.primary_act = self.role_menu.addAction("The primary (the brain)")
        self.helper_act = self.role_menu.addAction("A model helper (lends its model)")
        for act, r in ((self.primary_act, role_mod.PRIMARY), (self.helper_act, role_mod.HELPER)):
            act.setCheckable(True)
            act.setChecked(self.role == r)
            group.addAction(act)
            act.triggered.connect(lambda _c=False, r=r: self.set_role(r))
        self.login_act = self.menu.addAction("Open at login")
        self.login_act.setCheckable(True)
        self.login_act.setChecked(autostart.is_enabled())
        self.login_act.toggled.connect(lambda on: self._set_login(on))
        self.menu.addSeparator()
        self.quit_act = self.menu.addAction("Quit MACalendar Server")
        self.quit_act.triggered.connect(lambda: self.quit())
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.poller = _Poller(self.stack)
        self.poller.got.connect(self.apply_status)
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.poller.poll)
        self.timer.start()
        self.poller.poll()
        app.aboutToQuit.connect(self.stack.stop)

    def _info(self, text: str) -> QAction:
        act = self.menu.addAction(text)
        act.setEnabled(False)
        return act

    # -- role ---------------------------------------------------------------
    def _start_role(self) -> list[str]:
        did = self.stack.start(api=self.role == role_mod.PRIMARY)
        if self.role == role_mod.HELPER:
            self._start_helper()
        return did

    def _start_helper(self) -> None:
        if self.helper is None:
            from assistant.host.helper import Helper
            self.helper = Helper()
            try:
                self.helper.start()
            except OSError as exc:            # the port is taken
                self.tray.showMessage("MACalendar Server",
                                      f"Couldn't lend the model: {exc}") if hasattr(self, "tray") else None
                self.helper = None

    def set_role(self, new: str, confirm: bool = True) -> None:
        if new == self.role:
            return
        if confirm:
            text = ("This computer will stop being the brain: phones and the calendar "
                    "need a primary somewhere else, and your calendar data stays here."
                    if new == role_mod.HELPER else
                    "This computer will become the brain again and stop lending its model.")
            if QMessageBox.question(None, "Change this computer's role?", text) \
                    != QMessageBox.StandardButton.Yes:
                (self.primary_act if self.role == role_mod.PRIMARY else self.helper_act).setChecked(True)
                return
        role_mod.set(new)
        self.role = new
        if new == role_mod.HELPER:
            self.stack.stop_api()
            self._start_helper()
        else:
            if self.helper is not None:
                self.helper.stop()
                self.helper = None
            self._started = self.stack.start(api=True)
        self.poller.poll()

    # -- status -----------------------------------------------------------
    def apply_status(self, st: dict) -> None:
        self.state = st
        if self.role == role_mod.HELPER:
            self._apply_helper_status(st)
            return
        self.pair_act.setVisible(True)
        self.servers_act.setText("Servers & logs…")
        up = bool(st.get("api"))
        if up:
            self.status_act.setText("●  Running")
        elif "api" in self._started:
            self.status_act.setText("◌  Starting…")
        else:
            self.status_act.setText("○  Not running")
        urls = [u.removeprefix("http://").rsplit(":", 1)[0] for u in st.get("urls", [])]
        self.where_act.setText("Reachable at " + " · ".join(urls) if urls else "")
        self.where_act.setVisible(bool(urls))
        n = st.get("devices")
        self.devices_act.setVisible(n is not None)
        if n is not None:
            self.devices_act.setText("No devices yet" if n == 0 else
                                     f"{n} device{'s' if n != 1 else ''} joined")
        self.pair_act.setEnabled(up)
        self._show_setup(st)
        self.tray.setToolTip("MACalendar Server — " + self.status_act.text().split(None, 1)[-1])
        # The first time the server is up with nothing joined, offer the QR
        # straight away: that is what someone who just clicked the app wants.
        if up and n == 0 and not self._settings.value("offered_pairing", False, type=bool):
            self._settings.setValue("offered_pairing", True)
            self.show_pairing()

    def _apply_helper_status(self, st: dict) -> None:
        from assistant.pairing import codes
        lending = bool(st.get("ollama")) and self.helper is not None
        self.status_act.setText("●  Lending its model" if lending else "○  Model not running")
        self.where_act.setText("Code for your primary: " + codes.pretty(self.helper.code)
                               if self.helper else "")
        self.where_act.setVisible(self.helper is not None)
        n = len(self.helper.primaries()) if self.helper else 0
        self.devices_act.setVisible(True)
        self.devices_act.setText("Not used by a primary yet" if n == 0 else
                                 f"Used by {n} primar{'ies' if n != 1 else 'y'}")
        self.pair_act.setVisible(False)
        self.servers_act.setText("Helper code & log…")
        self._show_setup(st)
        self.tray.setToolTip("MACalendar Server — " + self.status_act.text().split(None, 1)[-1])

    def _show_setup(self, st: dict) -> None:
        if not st.get("ollama_installed", True):
            text, enabled = "⚠  Ollama isn't installed — Get Ollama…", True
        elif st.get("pulling"):
            text, enabled = "Downloading the assistant's model…", False
        elif st.get("model_ready") is False:
            text, enabled = "⚠  The assistant's model isn't downloaded — Download…", True
        else:
            text, enabled = "", False
        self.setup_act.setText(text)
        self.setup_act.setEnabled(enabled)
        self.setup_act.setVisible(bool(text))

    def _fix_setup(self) -> None:
        if not self.state.get("ollama_installed", True):
            QDesktopServices.openUrl(QUrl(OLLAMA_DOWNLOAD))
        elif self.state.get("model_ready") is False:
            if self.stack.pull_model():
                self.state["pulling"] = True
                self._show_setup(self.state)

    # -- actions ----------------------------------------------------------
    def show_pairing(self) -> None:
        from assistant.host.pair_dialog import PairDialog
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        self._dialog = PairDialog(port=self.stack.port)
        self._dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._dialog.finished.connect(lambda _r: setattr(self, "_dialog", None))
        _bring_forward()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def show_servers(self) -> None:
        """Servers & logs (primary) or the helper's code and log (helper)."""
        if self._servers_win is not None and self._servers_win.isVisible():
            self._servers_win.raise_()
            self._servers_win.activateWindow()
            return
        if self.role == role_mod.HELPER and self.helper is not None:
            from assistant.host.helper_window import HelperWindow
            win = HelperWindow(self.helper)
        else:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout
            from assistant.host.servers_panel import ServersPanel
            win = QDialog()
            win.setWindowTitle("Servers & logs")
            lay = QVBoxLayout(win)
            lay.addWidget(ServersPanel(win, port=self.stack.port))
            win.resize(620, 640)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        win.finished.connect(lambda _r: setattr(self, "_servers_win", None))
        self._servers_win = win
        _bring_forward()
        win.show()
        win.raise_()
        win.activateWindow()

    def open_calendar(self) -> None:
        import subprocess
        from pathlib import Path
        from assistant.host.supervisor import ROOT
        app = Path("/Applications/MACalendar APPs/MACalendar.app")
        if platform.system() == "Darwin" and app.exists():
            subprocess.Popen(["/usr/bin/open", "-a", str(app)])
        else:
            subprocess.Popen([sys.executable, "-m", "assistant.main"], cwd=str(ROOT))

    def _set_login(self, on: bool) -> None:
        (autostart.enable if on else autostart.disable)()

    def quit(self) -> None:
        if self.helper is not None:
            self.helper.stop()
        self.tray.hide()
        self.app.quit()


def _bring_forward() -> None:
    """An accessory app's windows open BEHIND the frontmost app on macOS."""
    if platform.system() != "Darwin":
        return
    try:
        import AppKit
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


def _hide_from_dock() -> None:
    """The tray is the whole UI: no Dock icon, no app menu (macOS). The .app's
    LSUIElement does not reach this Python process, so it is set here."""
    if platform.system() != "Darwin":
        return
    try:
        import AppKit
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass


def main() -> None:
    # `--role primary|helper` sets this machine's role and leaves (the
    # installer's question, DEVQA Q70).
    if "--role" in sys.argv:
        i = sys.argv.index("--role")
        want = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        role_mod.set(want)
        print(f"This computer is now: {want}")
        return
    from assistant.host.logs import HOST_LOG, install_file_handler
    import logging
    logging.basicConfig(level=logging.INFO)
    install_file_handler(HOST_LOG)
    app = QApplication(sys.argv)
    app.setApplicationName("MACalendar Server")
    app.setQuitOnLastWindowClosed(False)

    # Already running? Ask it to show the QR and leave.
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE)
    if probe.waitForConnected(300):
        # --background (the calendar's launcher on Linux/Windows): make sure a
        # server runs, and if one does, do nothing — no pairing window.
        if "--background" in sys.argv:
            return
        probe.write(b"pair")
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return
    QLocalServer.removeServer(INSTANCE)       # a stale socket from a crash
    server = QLocalServer()
    server.listen(INSTANCE)

    _hide_from_dock()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("No system tray on this desktop; the server runs without an icon.",
              file=sys.stderr)
    host = HostTray(app)

    def on_other():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: (conn.readAll(), host.show_pairing()))
    server.newConnection.connect(on_other)

    # Stopped by the launcher (SIGTERM) or Ctrl-C: quit through Qt so
    # aboutToQuit stops the children. Python only sees signals between
    # bytecodes, so a timer gives it some.
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(500)
    sys.exit(app.exec())
