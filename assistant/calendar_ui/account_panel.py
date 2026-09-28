"""The Account tab on the Mac: the admin's dashboard, or a person's own page.

`assistant/features/account/feature.py` has the why. The two pages reuse the
dialogs the toolbar chip opens (`users_dialogs`), embedded, so there is one
implementation of each screen, not a dialog and a tab that drift apart.
"""
from __future__ import annotations

import datetime as _dt

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from assistant import users
from assistant.calendar_ui.feature_panel import FeaturePanel
from assistant.users import registry, sessions


class AccountPanel(FeaturePanel):
    feature_name = "account"

    def __init__(self, db=None, dark: bool = True) -> None:
        super().__init__()
        self._db = db
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(self._scroll)
        self.reload()

    # -- the contract -----------------------------------------------------------

    def reload(self) -> None:
        """Rebuilt, not refreshed: who is signed in decides which page this is."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        self._sub = self._devices_lay = None
        uid = users.current()
        me = registry.get(uid) if (uid and registry.exists()) else None
        if me is None:
            msg = QLabel("No accounts on this Mac yet.")
            msg.setObjectName("muted")
            lay.addWidget(msg)
        elif me["role"] == "admin":
            self._admin_page(lay, me)
        else:
            self._user_page(lay, me)
        lay.addStretch(1)
        self._scroll.setWidget(page)

    # -- pages ----------------------------------------------------------------

    def _title(self, lay, text: str, sub: str = "") -> None:
        t = QLabel(text)
        t.setObjectName("account_title")
        # a stylesheet, not setFont: the app's stylesheet sets every QLabel's
        # font and silently wins over setFont — the title rendered body-sized
        t.setStyleSheet("font-size: 22px; font-weight: 700;")
        lay.addWidget(t)
        self._sub = None
        if sub:
            s = QLabel(sub)
            s.setObjectName("muted")
            s.setWordWrap(True)
            lay.addWidget(s)
            self._sub = s

    def _section(self, lay, text: str) -> None:
        h = QLabel(text.upper())
        h.setObjectName("muted")
        f = h.font(); f.setBold(True); f.setPointSize(max(9, f.pointSize() - 1))
        h.setFont(f)
        lay.addSpacing(8)
        lay.addWidget(h)

    def _summary(self) -> str:
        n = len(registry.user_ids())
        live = len(sessions.list_for())
        return (f"{n} user{'s' if n != 1 else ''} · {live} signed-in device"
                f"{'s' if live != 1 else ''}")

    def _changed(self) -> None:
        """Something on the page changed the world. Update what DEPENDS on it
        — the counts, the device list, the calendar and the other panels —
        and leave the page itself alone: rebuilding it destroyed the control
        mid-click and wiped a new user's shown-once password the instant it
        appeared (Gil, 2026-09-28: "not all the toggles/buttons work")."""
        if getattr(self, "_sub", None) is not None:
            self._sub.setText(self._summary())
        if getattr(self, "_devices_lay", None) is not None:
            while self._devices_lay.count():
                it = self._devices_lay.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self._devices(self._devices_lay)
        win = self.window()
        if win is not self and hasattr(win, "refresh_calendar"):
            win.refresh_calendar()
        for panel in getattr(win, "_panels", {}).values():
            if panel is not self and hasattr(panel, "reload"):
                panel.reload()

    def _admin_page(self, lay, me: dict) -> None:
        from assistant.calendar_ui.users_dialogs import AccountDialog, AdminDialog
        self._title(lay, "Admin dashboard", self._summary())
        # Sharing first: it is the thing a person comes here to change, and it
        # sat at the bottom under "My own account" where Gil could not find it.
        self._section(lay, "My account · share my calendar and to-dos")
        self.account = AccountDialog(self, embedded=True)
        self.account.changed.connect(lambda: self._changed())
        lay.addWidget(self.account)
        self._section(lay, "People · what you see of each, your vocabulary, sign-in")
        hint = QLabel("Tick a column to show that person's calendar in yours, or to give "
                      "them your vocabulary. Select a row, then reset their password, "
                      "sign them out everywhere, or disable them.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.admin = AdminDialog(self, embedded=True)
        self.admin.changed.connect(lambda: self._changed())
        lay.addWidget(self.admin)
        self._section(lay, "Signed-in devices")
        box = QWidget()
        self._devices_lay = QVBoxLayout(box)
        self._devices_lay.setContentsMargins(0, 0, 0, 0)
        self._devices(self._devices_lay)
        lay.addWidget(box)
        self._sign_out_row(lay)

    def _user_page(self, lay, me: dict) -> None:
        from assistant.calendar_ui.users_dialogs import AccountDialog
        self._title(lay, "Your account", "Your calendar, who you share it with, and how "
                    "you are signed in.")
        self.account = AccountDialog(self, embedded=True)
        self.account.changed.connect(lambda: self._changed())
        lay.addWidget(self.account)
        self._sign_out_row(lay)

    def _devices(self, lay) -> None:
        rows = sorted(sessions.list_for(), key=lambda r: -r.get("last_seen", 0))
        if not rows:
            lay.addWidget(QLabel("Nobody is signed in anywhere."))
        for r in rows:
            u = registry.get(r["user_id"]) or {}
            where = r.get("label") or r.get("source") or "device"
            seen = _dt.datetime.fromtimestamp(r.get("last_seen", 0)).strftime("%d %b %H:%M")
            line = QLabel(f"<b>{u.get('display_name', '?')}</b> — {where}  "
                          f"<span style='color:gray'>last seen {seen}</span>")
            lay.addWidget(line)

    def _sign_out_row(self, lay) -> None:
        row = QHBoxLayout()
        row.addStretch(1)
        self.sign_out_btn = QPushButton("Sign out of this Mac")
        self.sign_out_btn.clicked.connect(lambda: self._sign_out())
        row.addWidget(self.sign_out_btn)
        lay.addLayout(row)

    def _sign_out(self) -> None:
        chip = getattr(self.window(), "_user_chip", None)
        if chip is not None:
            chip.sign_out()
