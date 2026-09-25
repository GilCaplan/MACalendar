"""Settings → Connected Calendars on the Mac: connect Google / Outlook, see
status, disconnect, sync now.

A CLIENT of the brain, exactly like the phone's screen: every button is a call
to `/calendar_sync/*` on the local API, which holds the tokens and runs the
sync. Nothing here talks to Google or Microsoft, and nothing here touches the
calendar database — that is what keeps the two apps from drifting.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import urllib.error
import urllib.request
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

PROVIDERS = (("google", "Google Calendar"), ("outlook", "Outlook Calendar"))
_POLL_MS = 1500
_POLL_LIMIT = 15 * 60 * 1000 // _POLL_MS         # a sign-in expires in 15 minutes


class BrainClient:
    """`(status, json)` from the local API — the same door the phone uses."""

    def __init__(self, config) -> None:
        api = getattr(config, "api", None)
        self.base = f"http://127.0.0.1:{getattr(api, 'port', 8080)}"
        self.key = getattr(api, "key", None)

    def call(self, method: str, path: str, body: Optional[dict] = None,
             timeout: float = 15) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        if self.key:
            req.add_header("X-API-Key", self.key)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "{}")
            except ValueError:
                return e.code, {"error": str(e)}
        except Exception as e:  # noqa: BLE001 — the brain is down or refused
            return 0, {"error": f"The assistant server isn't reachable ({e})."}


def _when(iso: str) -> str:
    if not iso:
        return "never"
    try:
        t = datetime.datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return iso[:16]
    today = datetime.date.today()
    return t.strftime("%H:%M") if t.date() == today else t.strftime("%d %b %H:%M")


class ConnectedCalendarsSection(QWidget):
    """The Google + Outlook rows, Sync now, and a door to the ICS links."""

    _delivered = pyqtSignal(object, object)          # (callback, (status, body))

    def __init__(self, parent=None, config=None, client: Optional[BrainClient] = None,
                 open_url: Optional[Callable[[str], None]] = None,
                 on_links: Optional[Callable[[], None]] = None,
                 toast: Optional[Callable[[str], None]] = None,
                 on_synced: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent)
        self._client = client or BrainClient(config)
        self._open_url = open_url or (lambda u: QDesktopServices.openUrl(QUrl(u)))
        self._toast = toast or (lambda _m: None)
        self._on_synced = on_synced or (lambda: None)
        self._status: dict = {}
        self._polls: dict[str, QTimer] = {}
        self._code_dialog: Optional[QDialog] = None
        # A bound method, so the worker thread's emit is QUEUED onto this
        # widget's (the GUI) thread — widgets are only touched there.
        self._delivered.connect(self._deliver)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.summary = QLabel("Checking…")
        self.summary.setObjectName("calsync_summary")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)

        self.rows: dict[str, dict] = {}
        for key, title in PROVIDERS:
            row = QHBoxLayout()
            col = QVBoxLayout()
            name = QLabel(f"<b>{title}</b>")
            state = QLabel("")
            state.setObjectName(f"{key}_status")
            state.setWordWrap(True)
            state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            col.addWidget(name)
            col.addWidget(state)
            row.addLayout(col, 1)
            two_way = QCheckBox("Two-way")
            two_way.setObjectName(f"{key}_two_way")
            two_way.setToolTip("Push edits and deletes made here back to the account")
            connect_btn = QPushButton("Connect…")
            connect_btn.setObjectName(f"{key}_connect")
            setup_btn = QPushButton("Set up…")
            setup_btn.setObjectName(f"{key}_setup")
            disconnect_btn = QPushButton("Disconnect")
            disconnect_btn.setObjectName(f"{key}_disconnect")
            for w in (two_way, setup_btn, connect_btn, disconnect_btn):
                row.addWidget(w)
            v.addLayout(row)
            connect_btn.clicked.connect(lambda _=False, k=key: self.connect_provider(k))
            setup_btn.clicked.connect(lambda _=False, k=key: self.open_setup(k))
            disconnect_btn.clicked.connect(lambda _=False, k=key: self.disconnect_provider(k))
            two_way.clicked.connect(lambda on, k=key: self._set_two_way(k, on))
            self.rows[key] = {"state": state, "connect": connect_btn, "setup": setup_btn,
                              "disconnect": disconnect_btn, "two_way": two_way}

        actions = QHBoxLayout()
        self.sync_btn = QPushButton("Sync now")
        self.sync_btn.setObjectName("calsync_sync_now")
        self.sync_btn.clicked.connect(self.sync_now)
        actions.addWidget(self.sync_btn)
        if on_links is not None:
            links = QPushButton("Read-only calendar links (ICS)…")
            links.setObjectName("calsync_links")
            links.setToolTip("Subscribe to a secret iCal address — Gmail, iCloud, Outlook.com")
            links.clicked.connect(lambda: on_links())
            actions.addWidget(links)
        guide = QPushButton("How to connect…")
        guide.setObjectName("calsync_guide")
        guide.setToolTip("Step-by-step: Gmail read-only, Google two-way, Outlook two-way")
        guide.clicked.connect(lambda: self.open_guide())
        actions.addWidget(guide)
        actions.addStretch(1)
        v.addLayout(actions)
        self.refresh()

    # ── plumbing ──────────────────────────────────────────────────
    def _deliver(self, then, res) -> None:
        then(res)

    def _async(self, method: str, path: str, body: Optional[dict], then) -> None:
        def work() -> None:
            self._delivered.emit(then, self._client.call(method, path, body))
        threading.Thread(target=work, daemon=True, name="calsync-ui").start()

    def refresh(self) -> None:
        self._async("GET", "/calendar_sync/status", None, self._render)

    def _render(self, res) -> None:
        code, st = res
        if code != 200:
            self.summary.setText(st.get("error") or "Couldn't read the sync status.")
            return
        self._status = st
        last = (st.get("last_run") or {}).get("finished", "")
        running = " · syncing now…" if st.get("running") else ""
        if st.get("enabled"):
            self.summary.setText(f"Syncs every {st.get('interval_minutes', 15)} min, calendar "
                                 f"window open or not · last run {_when(last)}{running}")
        else:
            self.summary.setText("Automatic sync is off (calendar_sync.enabled).")
        for key, _title in PROVIDERS:
            p = (st.get("providers") or {}).get(key, {})
            w = self.rows[key]
            if p.get("pending_flow"):
                text = "Waiting for you to finish signing in…"
            elif p.get("connected"):
                who = p.get("account") or "connected"
                text = f"Connected — {who} · last synced {_when(p.get('last_synced', ''))}"
                if p.get("last_error"):
                    text += f"\n⚠ {p['last_error']}"
            elif p.get("setup_needed"):
                text = "Set-up needed — see steps (a free one-time client registration)."
            else:
                text = "Not connected."
            w["state"].setText(text)
            w["connect"].setText("Reconnect…" if p.get("connected") else "Connect…")
            w["connect"].setEnabled(bool(p.get("configured")))
            w["disconnect"].setVisible(bool(p.get("connected")))
            w["two_way"].setVisible(bool(p.get("connected")))
            w["two_way"].setChecked(bool(p.get("two_way")))

    def _say(self, message: str) -> None:
        self._toast(message)

    # ── connect ───────────────────────────────────────────────────
    def connect_provider(self, key: str) -> None:
        path = f"/calendar_sync/{key}/start"
        body = {"platform": "mac"} if key == "google" else {}
        self.rows[key]["connect"].setEnabled(False)
        self._async("POST", path, body, lambda res, k=key: self._started(k, res))

    def _started(self, key: str, res) -> None:
        code, body = res
        self.rows[key]["connect"].setEnabled(True)
        if code == 409 and body.get("setup_needed"):
            self.rows[key]["state"].setText("Set-up needed — " + body.get("error", ""))
            return
        if code != 200:
            self.rows[key]["state"].setText("Couldn't start sign-in: " + str(body.get("error", code)))
            return
        if key == "google":
            self._open_url(body["auth_url"])
            self.rows[key]["state"].setText("Finish signing in to Google in your browser…")
        else:
            self._show_device_code(body)
        self._poll(key, body["id"])

    def _show_device_code(self, flow: dict) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Connect Outlook")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Sign in at the Microsoft page and enter this code:"))
        code = QLabel(f"<span style='font-size:22px; font-weight:600'>{flow.get('user_code', '')}</span>")
        code.setObjectName("outlook_user_code")
        code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(code, alignment=Qt.AlignmentFlag.AlignHCenter)
        go = QPushButton("Copy code && open microsoft.com/devicelogin")
        go.setDefault(True)

        def _go() -> None:
            QGuiApplication.clipboard().setText(flow.get("user_code", ""))
            self._open_url(flow.get("verification_uri") or "https://microsoft.com/devicelogin")
        go.clicked.connect(_go)
        v.addWidget(go)
        hint = QLabel("This window closes by itself once you have signed in.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self._code_dialog = dlg
        dlg.setModal(False)
        dlg.show()

    def _poll(self, key: str, flow_id: str) -> None:
        old = self._polls.pop(key, None)
        if old:
            old.stop()
        timer = QTimer(self)
        timer.setInterval(_POLL_MS)
        ticks = {"n": 0}

        def tick() -> None:
            ticks["n"] += 1
            if ticks["n"] > _POLL_LIMIT:
                timer.stop()
                return
            self._async("GET", f"/calendar_sync/flows/{flow_id}", None,
                        lambda res, k=key: self._flow_update(k, res))
        timer.timeout.connect(tick)
        self._polls[key] = timer
        timer.start()

    def _flow_update(self, key: str, res) -> None:
        code, flow = res
        if code == 200 and flow.get("state") == "pending":
            return
        timer = self._polls.pop(key, None)
        if timer:
            timer.stop()
        if key == "outlook" and self._code_dialog is not None:
            self._code_dialog.close()
            self._code_dialog = None
        name = dict(PROVIDERS)[key]
        if code == 200 and flow.get("state") == "done":
            self._say(f"{name} connected{' as ' + flow['account'] if flow.get('account') else ''}")
        else:
            self._say(f"{name}: sign-in failed — {flow.get('error', code)}")
        self.refresh()

    # ── disconnect / two-way / sync ───────────────────────────────
    def disconnect_provider(self, key: str, keep_events: Optional[bool] = None) -> None:
        name = dict(PROVIDERS)[key]
        if keep_events is None:
            box = QMessageBox(self)
            box.setWindowTitle(f"Disconnect {name}")
            box.setText(f"Stop syncing with {name} and sign out?")
            box.setInformativeText("Keep the events it synced on this calendar as ordinary "
                                   "local events, or remove them? (They stay in your "
                                   f"{name.split()[0]} account either way.)")
            keep = box.addButton("Keep events", QMessageBox.ButtonRole.AcceptRole)
            remove = box.addButton("Remove events", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() not in (keep, remove):
                return
            keep_events = box.clickedButton() is keep
        self._async("POST", f"/calendar_sync/{key}/disconnect", {"keep_events": keep_events},
                    lambda res: (self._say(f"{name} disconnected"), self.refresh(),
                                 self._on_synced()))

    def _set_two_way(self, key: str, on: bool) -> None:
        sid = ((self._status.get("providers") or {}).get(key) or {}).get("source_id")
        if sid is None:
            return
        self._async("PATCH", f"/calendar_sources/{sid}", {"two_way": int(on)},
                    lambda _res: self.refresh())

    def sync_now(self) -> None:
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("Syncing…")
        self._async("POST", "/calendar_sync/sync", {"wait": True}, self._synced)

    def _synced(self, res) -> None:
        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("Sync now")
        code, body = res
        if body.get("busy"):
            self._say("A sync is already running")
        elif code != 200:
            self._say("Sync failed: " + str(body.get("error", code)))
        else:
            r = body.get("results") or {}
            pulled = sum(r.get(k, 0) for k in ("ics_synced", "outlook_pulled", "google_pulled"))
            pushed = r.get("outlook_pushed", 0) + r.get("google_pushed", 0)
            self._say("Calendar sync had errors — see Connected Calendars" if r.get("errors")
                      else f"Calendars synced ({pulled} pulled, {pushed} pushed)")
            self._on_synced()
        self.refresh()

    # ── set-up (client ids) ───────────────────────────────────────
    def open_setup(self, key: str) -> None:
        SetupDialog(self, key, self._client, self._open_url, on_saved=self.refresh).exec()

    def open_guide(self, key: str = "") -> None:
        GuideDialog(self, self._open_url, start=key or self._first_unconnected()).exec()

    def _first_unconnected(self) -> str:
        providers = (self._status or {}).get("providers") or {}
        return next((k for k, _t in PROVIDERS if not (providers.get(k) or {}).get("connected")), "ics")


class GuideDialog(QDialog):
    """How to connect, step by step — one tab per way in, the same steps the
    phone draws (`assistant/calendar_sync/guide.py`). A step can be ticked
    off, so coming back from the browser you can see where you were."""

    def __init__(self, parent, open_url, start: str = "ics") -> None:
        super().__init__(parent)
        from assistant.calendar_sync.guide import guides
        self.setWindowTitle("How to connect a calendar")
        self.setMinimumSize(560, 560)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.checks: dict[str, list[QCheckBox]] = {}
        for g in guides():
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setSpacing(10)
            head = QLabel(f"{g['summary']}<br><span style='color: gray;'>⏱ {g['time']}</span>")
            head.setWordWrap(True)
            pv.addWidget(head)
            boxes = []
            for i, step in enumerate(g["steps"], 1):
                row = QHBoxLayout()
                tick = QCheckBox(f"{i}.")
                tick.setObjectName(f"{g['key']}_step_{i}")
                tick.setToolTip("Tick it off when done")
                row.addWidget(tick, 0, Qt.AlignmentFlag.AlignTop)
                text = step["text"]
                if step.get("link"):
                    text += f"<br><a href='{step['link']}'>{step['link_label']} ↗</a>"
                lbl = QLabel(text)
                lbl.setWordWrap(True)
                lbl.setTextFormat(Qt.TextFormat.RichText)
                lbl.setOpenExternalLinks(False)
                lbl.linkActivated.connect(lambda url, t=tick: (open_url(url), t.setChecked(True)))
                row.addWidget(lbl, 1)
                pv.addLayout(row)
                boxes.append(tick)
            done = QLabel(f"<b>When it's done:</b> {g['done']}")
            done.setWordWrap(True)
            pv.addWidget(done)
            pv.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, g["title"])
            self.checks[g["key"]] = boxes
        keys = [g["key"] for g in guides()]
        self.tabs.setCurrentIndex(keys.index(start) if start in keys else 0)
        v.addWidget(self.tabs)
        close = QPushButton("Done")
        close.clicked.connect(self.accept)
        v.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)


class SetupDialog(QDialog):
    """Paste the one-time client registration: Google's Desktop JSON / iOS
    client id, or Outlook's client id. The steps are in CALENDAR_SYNC.md."""

    def __init__(self, parent, key: str, client: BrainClient, open_url, on_saved) -> None:
        super().__init__(parent)
        self._client = client
        self._on_saved = on_saved
        self.setWindowTitle("Set up " + dict(PROVIDERS)[key])
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        steps = QPushButton("How to connect, step by step…")
        steps.clicked.connect(lambda: GuideDialog(self, open_url, start=key).exec())
        v.addWidget(steps)
        self.result = QLabel("")
        self.result.setObjectName("setup_result")
        self.result.setWordWrap(True)
        if key == "google":
            v.addWidget(QLabel("<b>Mac sign-in</b> — the “Desktop app” client JSON you downloaded:"))
            pick = QPushButton("Choose client JSON…")
            pick.setObjectName("setup_pick_json")
            pick.clicked.connect(self._pick_json)
            v.addWidget(pick)
            v.addWidget(QLabel("<b>iPhone sign-in</b> — the “iOS” client id (optional):"))
            self.id_edit = QLineEdit()
            self.id_edit.setPlaceholderText("1234-abcd.apps.googleusercontent.com")
            self._field = "google_ios_client_id"
        else:
            v.addWidget(QLabel("<b>Application (client) ID</b> of your Entra app registration:"))
            self.id_edit = QLineEdit()
            self.id_edit.setPlaceholderText("00000000-0000-0000-0000-000000000000")
            self._field = "outlook_client_id"
        self.id_edit.setObjectName("setup_client_id")
        v.addWidget(self.id_edit)
        save = QPushButton("Save client id")
        save.setObjectName("setup_save")
        save.clicked.connect(self._save_id)
        v.addWidget(save)
        v.addWidget(self.result)
        close = QPushButton("Done")
        close.clicked.connect(self.accept)
        v.addWidget(close)

    def _pick_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Google client JSON",
                                              os.path.expanduser("~/Downloads"), "JSON (*.json)")
        if not path:
            return
        try:
            with open(path) as f:
                raw = f.read()
        except OSError as e:
            self.result.setText(str(e))
            return
        self.submit_json(raw)

    def submit_json(self, raw: str) -> None:
        code, body = self._client.call("POST", "/calendar_sync/google/client", {"client_json": raw})
        self.result.setText("Saved — you can Connect now." if code == 200
                            else "Not saved: " + str(body.get("error", code)))
        self._on_saved()

    def _save_id(self) -> None:
        text = self.id_edit.text().strip()
        if not text:
            return
        code, body = self._client.call("PUT", "/calendar_sync/setup", {self._field: text})
        self.result.setText("Saved — you can Connect now." if code == 200
                            else "Not saved: " + str(body.get("error", code)))
        self._on_saved()
