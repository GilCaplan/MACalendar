"""The Mac's user screens: sign in, change password, Account & Sharing, and the
admin's console — plus the toolbar chip that opens them (DEVQA Q65).

They act on the same `users.json` / `sessions.json` the API does, in-process,
so the Mac and the phone can never disagree and the screens work with the API
down. Styled by the app stylesheet (`calendar_ui/styles.py`): one accent
button per dialog (`#primary`), everything else quiet.
"""
from __future__ import annotations

import datetime as _dt

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QToolButton,
    QVBoxLayout, QWidget,
)

from assistant import users
from assistant.users import local_session, passwords, registry, sessions

_DESTRUCTIVE = "#e5484d"


def _dot(color: str, size: int = 10) -> QLabel:
    d = QLabel()
    d.setFixedSize(size, size)
    d.setStyleSheet(f"background:{color}; border-radius:{size // 2}px;")
    return d


def _checkbox_style() -> str:
    """A square box that reads in both themes. The app stylesheet leaves
    checkboxes native, and the native dark-on-dark box was invisible wherever
    Qt draws its own style (seen in the offscreen render of these dialogs)."""
    from assistant.calendar_ui import styles as _s
    acc = _s.get_accent()
    return (f"QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 3px;"
            f" border: 2px solid {_s.D_GRAY_MID}; background: transparent; }}"
            f"QCheckBox::indicator:checked {{ background-color: {acc}; border-color: {acc}; }}")


def _error_label() -> QLabel:
    e = QLabel("")
    e.setStyleSheet(f"color:{_DESTRUCTIVE};")
    e.setWordWrap(True)
    e.hide()
    return e


def _say(label: QLabel, text: str) -> None:
    label.setText(text)
    label.setVisible(bool(text))


# ------------------------------------------------------------------ sign in

class LoginDialog(QDialog):
    """Who's using the calendar? Username + password, one accent button."""

    def __init__(self, parent=None, username: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in")
        self.setModal(True)
        self.setMinimumWidth(340)
        self.user_id: "str | None" = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(10)
        title = QLabel("Who's using the calendar?")
        f = title.font(); f.setPointSize(f.pointSize() + 4); f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)
        sub = QLabel("Each person has their own calendar and to-dos.")
        sub.setObjectName("muted")
        lay.addWidget(sub)
        lay.addSpacing(6)
        self.username = QLineEdit(username)
        self.username.setPlaceholderText("Username")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(self.username)
        lay.addWidget(self.password)
        self.error = _error_label()
        lay.addWidget(self.error)
        self.sign_in = QPushButton("Sign in")
        self.sign_in.setObjectName("primary")
        self.sign_in.setDefault(True)
        self.sign_in.clicked.connect(lambda: self._try())
        lay.addWidget(self.sign_in)
        self.password.returnPressed.connect(lambda: self._try())
        (self.password if username else self.username).setFocus()

    def _try(self) -> None:
        uid = registry.verify_login(self.username.text(), self.password.text())
        if uid is None:
            _say(self.error, "That username and password don't match.")
            self.password.selectAll()
            return
        u = registry.get(uid)
        token = sessions.issue(uid, source="mac", label="Mac")
        local_session.write(uid, u["username"], u["display_name"], token)
        users.set_process_default(uid)
        self.user_id = uid
        self.accept()


def sign_in(parent=None) -> "str | None":
    """Make sure someone is signed in on this Mac: the saved session if it is
    still live, else the sign-in dialog. Returns who, or None if cancelled.
    Before the users migration there is nobody to sign in — returns None and
    changes nothing."""
    if not registry.exists():
        return None
    uid = local_session.current_user()
    if uid is None:
        last = (local_session.read() or {}).get("username", "")
        dlg = LoginDialog(parent, username=last)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        uid = dlg.user_id
    users.set_process_default(uid)
    if (registry.get(uid) or {}).get("must_change_password"):
        ChangePasswordDialog(parent, forced=True).exec()
    return uid


# ------------------------------------------------------------------ password

class ChangePasswordDialog(QDialog):
    def __init__(self, parent=None, forced: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change password")
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        if forced:
            note = QLabel("You're using a password someone else set. Pick your own.")
            note.setWordWrap(True)
            lay.addWidget(note)
        form = QFormLayout()
        self.current = QLineEdit(); self.current.setEchoMode(QLineEdit.EchoMode.Password)
        self.new = QLineEdit(); self.new.setEchoMode(QLineEdit.EchoMode.Password)
        self.again = QLineEdit(); self.again.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Current", self.current)
        form.addRow("New", self.new)
        form.addRow("Again", self.again)
        lay.addLayout(form)
        self.error = _error_label()
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        later = QPushButton("Later" if forced else "Cancel")
        later.clicked.connect(lambda: self.reject())
        self.save = QPushButton("Change password")
        self.save.setObjectName("primary")
        self.save.clicked.connect(lambda: self._save())
        row.addWidget(later)
        row.addWidget(self.save)
        lay.addLayout(row)

    def _save(self) -> None:
        uid = users.current()
        me = registry.get(uid) or {}
        if registry.verify_login(me.get("username", ""), self.current.text()) != uid:
            return _say(self.error, "The current password is wrong.")
        if self.new.text() != self.again.text():
            return _say(self.error, "The two new passwords differ.")
        try:
            registry.set_password(uid, self.new.text())
        except ValueError as e:
            return _say(self.error, str(e))
        s = local_session.read() or {}
        sessions.revoke_user(uid, keep=s.get("session_token"))
        self.accept()


# ------------------------------------------------------------------ account

class AccountDialog(QDialog):
    """Account & Sharing: who I am, who I share with, what I see of others.
    `embedded=True` is the Account tab's page (no Done / Manage buttons)."""

    changed = pyqtSignal()

    def __init__(self, parent=None, embedded: bool = False) -> None:
        super().__init__(parent)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle("Account & Sharing")
        self.setMinimumWidth(460)
        self.setStyleSheet(_checkbox_style())
        self.me = users.current()
        me = registry.get(self.me)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(_dot(me["color"], 14))
        name = QLabel(f"<b>{me['display_name']}</b>  <span style='color:gray'>@{me['username']}"
                      f"{' · admin' if me['role'] == 'admin' else ''}</span>")
        head.addWidget(name)
        head.addStretch(1)
        pw = QPushButton("Change password…")
        pw.clicked.connect(lambda: ChangePasswordDialog(self).exec())
        head.addWidget(pw)
        lay.addLayout(head)

        lay.addWidget(self._rule())
        lay.addWidget(QLabel("<b>Share my calendar and to-dos</b>"))
        hint = QLabel("Everything, with the people you choose. View lets them see; "
                      "Edit lets them change it too.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        lay.addWidget(hint)
        self.share_boxes: dict = {}
        others = [u for u in (registry.get(i) for i in registry.user_ids()) if u["id"] != self.me]
        if not others:
            lay.addWidget(QLabel("Nobody else has an account yet."))
        for u in others:
            row = QHBoxLayout()
            row.addWidget(_dot(u["color"]))
            row.addWidget(QLabel(u["display_name"]))
            row.addStretch(1)
            box = QComboBox()
            box.addItems(["Not shared", "View", "Edit"])
            level = registry.share_level(self.me, u["id"])
            box.setCurrentIndex({None: 0, "view": 1, "edit": 2}[level])
            box.currentIndexChanged.connect(
                lambda i, uid=u["id"]: self._share(uid, [None, "view", "edit"][i]))
            self.share_boxes[u["id"]] = box
            row.addWidget(box)
            lay.addLayout(row)

        shared_in = registry.shares_in(self.me)
        if shared_in:
            lay.addWidget(self._rule())
            lay.addWidget(QLabel("<b>Shared with me</b>"))
            for s in shared_in:
                o = registry.get(s["owner"]) or {}
                row = QHBoxLayout()
                row.addWidget(_dot(o.get("color", "#888")))
                row.addWidget(QLabel(f"{o.get('display_name', '?')} — {s['level']}"))
                row.addStretch(1)
                lay.addLayout(row)

        lay.addWidget(self._rule())
        st = me["settings"]
        self.group_box = QCheckBox("Group shared to-dos by person (instead of mixed in)")
        self.group_box.setChecked(bool(st.get("todos_group_by_owner")))
        self.group_box.toggled.connect(lambda on: self._setting("todos_group_by_owner", on))
        lay.addWidget(self.group_box)
        note = QLabel("In Tasks: on, each person who shares with you gets their own section "
                      "below yours; off, their to-dos sit in Today and General with yours "
                      "(the Whose chips filter them). Notifications are only ever about "
                      "your own calendar and to-dos.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        if embedded:
            return
        foot = QHBoxLayout()
        if me["role"] == "admin":
            self.manage = QPushButton("Manage users…")
            self.manage.clicked.connect(lambda: self._manage())
            foot.addWidget(self.manage)
        foot.addStretch(1)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(lambda: self.accept())
        foot.addWidget(done)
        lay.addLayout(foot)

    @staticmethod
    def _rule() -> QFrame:
        r = QFrame()
        r.setFrameShape(QFrame.Shape.HLine)
        r.setObjectName("rule")
        return r

    def _share(self, grantee: str, level: "str | None") -> None:
        registry.set_share(self.me, grantee, level)
        self.changed.emit()

    def _setting(self, key: str, on: bool) -> None:
        registry.set_setting(self.me, key, bool(on))
        self.changed.emit()

    def _manage(self) -> None:
        dlg = AdminDialog(self)
        dlg.changed.connect(self.changed)
        dlg.exec()


# ------------------------------------------------------------------ admin

class AdminDialog(QDialog):
    """Every account: create, reset a password (shown once), disable, remove,
    put someone's calendar into my view, share my vocabulary with them."""

    changed = pyqtSignal()
    COLS = ("", "Name", "Username", "Role", "Last seen", "Show in my calendar",
            "My vocabulary")

    def __init__(self, parent=None, embedded: bool = False) -> None:
        super().__init__(parent)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle("Manage users")
        self._embedded = embedded
        if not embedded:
            self.setMinimumSize(720, 380)
        self.setStyleSheet(_checkbox_style())
        self.me = users.current()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # the NAME column takes the slack — stretching the last one made
        # "My vocabulary" a page wide with its checkbox adrift in the middle
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setStretchLastSection(False)
        lay.addWidget(self.table)

        self.revealed = QLineEdit()
        self.revealed.setReadOnly(True)
        self.revealed.hide()
        self.revealed_note = QLabel("")
        self.revealed_note.setWordWrap(True)
        self.revealed_note.hide()
        lay.addWidget(self.revealed_note)
        lay.addWidget(self.revealed)

        row = QHBoxLayout()
        self.create_btn = QPushButton("New user…")
        self.create_btn.setObjectName("primary")
        self.reset_btn = QPushButton("Reset password")
        self.disable_btn = QPushButton("Disable")
        self.signout_btn = QPushButton("Sign out")
        self.signout_btn.setProperty("tip", "Sign this person out on every device (password unchanged)")
        self.remove_btn = QPushButton("Remove…")
        self.remove_btn.setStyleSheet(f"color:{_DESTRUCTIVE};")
        for b in (self.create_btn, self.reset_btn, self.signout_btn, self.disable_btn,
                  self.remove_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.require_box = QCheckBox("Require sign-in everywhere")
        self.require_box.setToolTip("Off: a device nobody signed in on acts as the admin.")
        self.require_box.setChecked(bool(registry.load().get("policy", {}).get("require_login")))
        self.require_box.toggled.connect(
            lambda on: (registry.set_policy(require_login=bool(on)), self.changed.emit()))
        row.addWidget(self.require_box)
        lay.addLayout(row)

        # Auto sign-out: OFF (a sign-in lasts until someone signs it out) or
        # after N days unused — the admin's choice (Gil, 2026-09-28).
        pol = QHBoxLayout()
        pol.addWidget(QLabel("Auto sign-out:"))
        self.auto_box = QComboBox()
        self.auto_box.addItems(["Off — only when signed out", "After"])
        from PyQt6.QtWidgets import QSpinBox
        self.auto_days = QSpinBox()
        self.auto_days.setRange(1, 3650)
        self.auto_days.setSuffix(" days unused")
        # disabled must LOOK disabled — it read as live while auto sign-out was Off
        self.auto_days.setStyleSheet("QSpinBox:disabled { color: rgba(128,128,128,0.55); }")
        days = registry.load().get("policy", {}).get("auto_signout_days")
        self.auto_box.setCurrentIndex(1 if days else 0)
        self.auto_days.setValue(int(days or 30))
        self.auto_days.setEnabled(bool(days))
        self.auto_box.currentIndexChanged.connect(lambda _i: self._auto_changed())
        self.auto_days.valueChanged.connect(lambda _v: self._auto_changed())
        pol.addWidget(self.auto_box)
        pol.addWidget(self.auto_days)
        pol.addStretch(1)
        lay.addLayout(pol)
        self.create_btn.clicked.connect(lambda: self._create())
        self.reset_btn.clicked.connect(lambda: self._reset())
        self.disable_btn.clicked.connect(lambda: self._toggle_disabled())
        self.remove_btn.clicked.connect(lambda: self._remove())
        self.signout_btn.clicked.connect(lambda: self._sign_out())
        self.table.itemSelectionChanged.connect(lambda: self._update_buttons())
        self._fill()

    # -- the table -----------------------------------------------------------

    def _fill(self) -> None:
        keep = self._selected() if hasattr(self, "_ids") else None
        rows = [registry.get(uid) for uid in registry.user_ids(include_disabled=True)]
        self.table.setRowCount(len(rows))
        self._ids = []
        vocab = set(registry.load().get("vocab_shares", {}).get(self.me, []))
        for r, u in enumerate(rows):
            self._ids.append(u["id"])
            dot = QTableWidgetItem("●")
            dot.setForeground(QColor(u["color"]))
            self.table.setItem(r, 0, dot)
            name = u["display_name"] + ("  (disabled)" if u.get("disabled") else "")
            self.table.setItem(r, 1, QTableWidgetItem(name))
            self.table.setItem(r, 2, QTableWidgetItem("@" + u["username"]))
            self.table.setItem(r, 3, QTableWidgetItem(u["role"]))
            seen = max((s["last_seen"] for s in sessions.list_for(u["id"])), default=None)
            self.table.setItem(r, 4, QTableWidgetItem(
                _dt.datetime.fromtimestamp(seen).strftime("%d %b %H:%M") if seen else "—"))
            if u["id"] == self.me:
                for c in (5, 6):
                    self.table.setItem(r, c, QTableWidgetItem("—"))
                continue
            show = QCheckBox()
            show.setChecked(registry.admin_shows(self.me, u["id"]))
            show.toggled.connect(lambda on, uid=u["id"]: self._show(uid, on))
            self.table.setCellWidget(r, 5, self._centered(show))
            voc = QCheckBox()
            voc.setChecked(u["id"] in vocab)
            voc.toggled.connect(lambda on, uid=u["id"]: registry.set_vocab_share(self.me, uid, on))
            self.table.setCellWidget(r, 6, self._centered(voc))
        if keep in self._ids:
            self.table.selectRow(self._ids.index(keep))
        self._update_buttons()
        if self._embedded:
            # a dashboard section, not a window: as tall as its rows, so two
            # people don't sit above a screen of empty table
            h = self.table.horizontalHeader().height() + 4 + sum(
                self.table.rowHeight(r) for r in range(self.table.rowCount()))
            self.table.setFixedHeight(h)

    def _update_buttons(self) -> None:
        """The row buttons act on the SELECTED person, so they are off until
        someone is selected — they used to look live and do nothing — and you
        cannot disable or remove yourself."""
        uid = self._selected()
        for b in (self.reset_btn, self.signout_btn):
            b.setEnabled(uid is not None)
        for b in (self.disable_btn, self.remove_btn):
            b.setEnabled(uid is not None and uid != self.me)
        hint = "" if uid else "Select a person in the table first"
        for b in (self.reset_btn, self.signout_btn, self.disable_btn, self.remove_btn):
            b.setToolTip(hint or b.property("tip") or "")
        if uid:
            u = registry.get(uid) or {}
            self.disable_btn.setText("Enable" if u.get("disabled") else "Disable")

    @staticmethod
    def _centered(w: QWidget) -> QWidget:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addStretch(1); h.addWidget(w); h.addStretch(1)
        box.checkbox = w
        return box

    def _selected(self) -> "str | None":
        rows = self.table.selectionModel().selectedRows()
        r = rows[0].row() if rows else -1
        return self._ids[r] if 0 <= r < len(getattr(self, "_ids", [])) else None

    def _show(self, uid: str, on: bool) -> None:
        registry.set_admin_view(self.me, uid, on)
        self.changed.emit()

    def _reveal(self, who: str, password: str) -> None:
        self.revealed_note.setText(f"New password for {who} — shown once. They'll be asked "
                                   f"to choose their own when they sign in.")
        self.revealed.setText(password)
        self.revealed_note.show()
        self.revealed.show()
        self.revealed.selectAll()

    # -- actions ---------------------------------------------------------------

    def _create(self) -> None:
        name, ok = QInputDialog.getText(self, "New user", "Username (a–z, 0–9):")
        if not ok or not name.strip():
            return
        display, _ = QInputDialog.getText(self, "New user", "Display name:",
                                          text=name.strip().capitalize())
        pw = passwords.generate()
        try:
            uid = registry.create_user(name, pw, display_name=display.strip())
        except ValueError as e:
            QMessageBox.warning(self, "New user", str(e))
            return
        registry.set_password(uid, pw, must_change=True)
        self._fill()
        self._reveal(registry.get(uid)["display_name"], pw)
        self.changed.emit()

    def _reset(self) -> None:
        uid = self._selected()
        if not uid:
            return
        pw = passwords.generate()
        registry.set_password(uid, pw, must_change=True)
        keep = (local_session.read() or {}).get("session_token") if uid == self.me else None
        sessions.revoke_user(uid, keep=keep)
        self._reveal(registry.get(uid)["display_name"], pw)
        self.changed.emit()

    def _auto_changed(self) -> None:
        on = self.auto_box.currentIndex() == 1
        self.auto_days.setEnabled(on)
        registry.set_policy(auto_signout_days=self.auto_days.value() if on else None)

    def _sign_out(self) -> None:
        uid = self._selected()
        if not uid:
            return
        keep = (local_session.read() or {}).get("session_token") if uid == self.me else None
        n = sessions.revoke_user(uid, keep=keep)
        self.revealed_note.setText(f"{registry.get(uid)['display_name']} is signed out "
                                   f"({n} device{'s' if n != 1 else ''}).")
        self.revealed_note.show()
        self.revealed.hide()
        self._fill()
        self.changed.emit()

    def _toggle_disabled(self) -> None:
        uid = self._selected()
        if not uid or uid == self.me:
            return
        u = registry.get(uid)
        registry.update_user(uid, disabled=not u.get("disabled"))
        if not u.get("disabled"):
            sessions.revoke_user(uid)
        self._fill()
        self.changed.emit()

    def _remove(self) -> None:
        uid = self._selected()
        if not uid or uid == self.me:
            return
        u = registry.get(uid)
        typed, ok = QInputDialog.getText(
            self, "Remove user",
            f"Type {u['username']} to remove them. Their calendar is kept in legacy/, not deleted.")
        if not ok or typed.strip().lower() != u["username"]:
            return
        registry.remove_user(uid)
        sessions.revoke_user(uid)
        self._fill()
        self.changed.emit()


# ------------------------------------------------------------------ the chip

class UserChip(QToolButton):
    """The toolbar's "● Gil ▾": Account & Sharing, Switch user, Sign out."""

    switched = pyqtSignal()        # a different user is now signed in
    changed = pyqtSignal()         # sharing or visibility changed
    signed_out = pyqtSignal()      # signed out and nobody signed back in

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("user_chip")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_ = QMenu(self)
        self.act_account = self.menu_.addAction("Account & Sharing…")
        self.act_switch = self.menu_.addAction("Switch user…")
        self.menu_.addSeparator()
        self.act_out = self.menu_.addAction("Sign out")
        self.act_account.triggered.connect(lambda: self.open_account())
        self.act_switch.triggered.connect(lambda: self.switch())
        self.act_out.triggered.connect(lambda: self.sign_out())
        self.setMenu(self.menu_)
        self.refresh()

    def refresh(self) -> None:
        u = registry.get(users.current() or "") or {}
        # The arrow is TEXT, like the "More ▾" beside it: Qt's own menu
        # indicator drew oversized and over the name (Gil, 2026-09-29).
        self.setText(f"● {u.get('display_name', '')} ▾")
        c = u.get("color", "#888888")
        self.setStyleSheet(f"QToolButton#user_chip {{ color: {c}; padding: 2px 10px; "
                           f"border: 1px solid {c}55; border-radius: 12px; }}"
                           f"QToolButton#user_chip:hover {{ background: {c}22; }}"
                           "QToolButton#user_chip::menu-indicator { image: none; width: 0px; }")
        self.setToolTip(f"Signed in as {u.get('display_name', '?')}")
        self.setVisible(bool(u))

    def open_account(self) -> None:
        dlg = AccountDialog(self.window())
        dlg.changed.connect(self.changed)
        dlg.exec()
        self.refresh()

    def switch(self) -> None:
        dlg = LoginDialog(self.window())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if (registry.get(dlg.user_id) or {}).get("must_change_password"):
                ChangePasswordDialog(self.window(), forced=True).exec()
            self.refresh()
            self.switched.emit()

    def sign_out(self) -> None:
        s = local_session.read()
        if s:
            sessions.revoke(s["session_token"])
        local_session.clear()
        dlg = LoginDialog(self.window())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.switched.emit()
        else:
            # nobody signed back in: the window must not go on showing the
            # previous person's calendar
            users.set_process_default(None)
            self.signed_out.emit()
