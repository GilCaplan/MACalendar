"""The Account tab on the Mac — the same design as the phone's (2026-09-28).

Gil asked for the Account tab to be revamped, and then for the whole Mac app
to be cleaned up. The page used to embed two dialogs: a sharing list that
split "share my calendar" from "shared with me", and a people TABLE whose
buttons acted on whichever row happened to be selected. It is now what the
phone shows:

    a header card    you, and (admin) how many people and devices
    People           one card per person — both directions of sharing in one
                     line, and every control about them ON the card: what
                     they can do with yours, and for the admin whether theirs
                     shows in your calendar, your vocabulary, and their
                     account (reset, sign out everywhere, disable, remove)
    Tasks            group shared to-dos by person, explained
    Sign-in          (admin) require sign-in, auto sign-out
    Devices          (admin) who is signed in where
    Sign out of this Mac

A change updates what depends on it — the card's own line, the counts, the
device list, the calendar and the other panels — and never rebuilds the page
under the control being clicked (that destroyed the control mid-click and
wiped a new user's shown-once password; test_account_tab_controls.py).
"""
from __future__ import annotations

import datetime as _dt
import os

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from assistant import users
from assistant.calendar_ui import styles as _styles
from assistant.calendar_ui.feature_panel import FeaturePanel
from assistant.users import local_session, passwords, registry, sessions

_LEVELS = [None, "view", "edit"]


def _palette(dark: bool) -> dict:
    return {
        "card": _styles.D_GRAY_LIGHT if dark else _styles.WHITE,
        "border": _styles.D_GRAY_BORDER if dark else _styles.GRAY_BORDER,
        "text": _styles.D_GRAY_DARK if dark else _styles.GRAY_DARK,
        "muted": _styles.D_GRAY_TEXT if dark else _styles.GRAY_TEXT,
        "danger": _styles.DESTRUCTIVE_DARK if dark else _styles.DESTRUCTIVE,
    }


def _card_style(pal: dict) -> str:
    return (f"QFrame#person_card {{ background:{pal['card']};"
            f" border:1px solid {pal['border']}; border-radius:{_styles.RADIUS_LG}px; }}"
            " QFrame#person_card QLabel { background: transparent; border: none; }")


def _avatar(name: str, color: str, size: int = 36, uid: str = "") -> QLabel:
    """Their photo in a circle, or their initial on their colour."""
    color = color or "#888888"
    found = registry.avatar_file(uid) if uid else None
    pix = QPixmap(found[0]) if found else QPixmap()
    if not pix.isNull():
        a = QLabel()
        a.setFixedSize(size, size)
        a.setPixmap(_round(pix, size))
        a.setStyleSheet("background: transparent;")
        return a
    a = QLabel((name[:1] or "?").upper())
    a.setFixedSize(size, size)
    a.setAlignment(Qt.AlignmentFlag.AlignCenter)
    a.setStyleSheet(f"background:{color}; color:{_styles.on_color(color)};"
                    f" border-radius:{size // 2}px; font-weight:700; font-size:{int(size * 0.42)}px;")
    return a


def _round(pix: QPixmap, size: int) -> QPixmap:
    """`pix` filled into a `size` circle, drawn at the screen's pixel ratio."""
    ratio = 2.0
    side = int(size * ratio)
    src = pix.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(side, side)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, side, side)
    p.setClipPath(clip)
    p.drawPixmap((side - src.width()) // 2, (side - src.height()) // 2, src)
    p.end()
    out.setDevicePixelRatio(ratio)
    return out


def photo_bytes(path: str, side: int = 512) -> bytes:
    """A picked file as the server wants it: cropped square from the middle,
    at most `side` pixels, JPEG. Raises ValueError for a file that is not a
    picture Qt can read."""
    img = QImage(path)
    if img.isNull():
        raise ValueError("that file isn't a picture")
    n = min(img.width(), img.height())
    img = img.copy((img.width() - n) // 2, (img.height() - n) // 2, n, n)
    if n > side:
        img = img.scaled(side, side, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.convertToFormat(QImage.Format.Format_RGB32).save(buf, "JPEG", 88)
    return bytes(buf.data())


def _relation(me: str, other: str) -> str:
    """"You share View · They share nothing" — both directions in one line."""
    def word(level):
        return {"view": "View", "edit": "Edit"}.get(level or "", "nothing")
    return (f"You share {word(registry.share_level(me, other))} · "
            f"They share {word(registry.share_level(other, me))}")


class _PersonCard(QFrame):
    """Everything about one person, on one card."""

    def __init__(self, panel: "AccountPanel", uid: str) -> None:
        super().__init__()
        self.panel, self.uid = panel, uid
        me, admin = panel.me, panel.is_admin
        u = registry.get(uid) or {}
        pal = _palette(panel._dark)
        self.setObjectName("person_card")
        self.setStyleSheet(_card_style(pal))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(_avatar(u.get("display_name", "?"), u.get("color", ""), uid=uid))
        names = QVBoxLayout()
        names.setSpacing(1)
        title = QLabel(f"<b>{u.get('display_name', '?')}</b>  <span style='color:{pal['muted']}'>"
                       f"@{u.get('username', '')}</span>"
                       + (f"  <span style='color:{pal['danger']}'>disabled</span>"
                          if u.get("disabled") else ""))
        title.setStyleSheet(f"font-size:14px; color:{pal['text']};")
        names.addWidget(title)
        self.relation = QLabel(_relation(me, uid))
        self.relation.setStyleSheet(f"font-size:12px; color:{pal['muted']};")
        names.addWidget(self.relation)
        head.addLayout(names, 1)
        lay.addLayout(head)

        # what they can do with yours — for everyone
        row = QHBoxLayout()
        row.addWidget(self._label("Your calendar & to-dos — they can", pal))
        row.addStretch(1)
        self.share_box = QComboBox()
        self.share_box.addItems(["Not shared", "View", "Edit"])
        self.share_box.setCurrentIndex(_LEVELS.index(registry.share_level(me, uid)))
        self.share_box.currentIndexChanged.connect(lambda i: self._share(_LEVELS[i]))
        self.share_box.setToolTip(
            "Not shared: they see nothing of yours.\n"
            "View: your calendar and to-dos appear in theirs, read-only.\n"
            "Edit: they can also add to them and change them.")
        row.addWidget(self.share_box)
        lay.addLayout(row)

        if admin:
            row = QHBoxLayout()
            self.show_box = QCheckBox("Show their calendar && to-dos in mine")
            self.show_box.setChecked(registry.admin_shows(me, uid))
            self.show_box.toggled.connect(lambda on: self._show(on))
            self.show_box.setToolTip(
                "Whether their calendar and to-dos appear in yours. Left alone,\n"
                "it follows whether they share with you; ticking or unticking it\n"
                "decides for good.")
            row.addWidget(self.show_box)
            row.addSpacing(18)
            self.vocab_box = QCheckBox("Share my vocabulary")
            self.vocab_box.setChecked(uid in registry.load().get("vocab_shares", {}).get(me, []))
            self.vocab_box.toggled.connect(lambda on: self._vocab(on))
            self.vocab_box.setToolTip(
                "Lets the assistant use the names and words you have taught it\n"
                "when it listens to them too, so they are heard the same way.")
            row.addWidget(self.vocab_box)
            row.addStretch(1)
            lay.addLayout(row)

            row = QHBoxLayout()
            row.setSpacing(6)
            self.reset_btn = QPushButton("Reset password")
            self.signout_btn = QPushButton("Sign out everywhere")
            self.disable_btn = QPushButton("Enable" if u.get("disabled") else "Disable")
            self.remove_btn = QPushButton("Remove…")
            self.remove_btn.setStyleSheet(f"color:{pal['danger']};")
            self.reset_btn.clicked.connect(lambda: self._reset())
            self.signout_btn.clicked.connect(lambda: self._sign_out())
            self.disable_btn.clicked.connect(lambda: self._toggle_disabled())
            self.remove_btn.clicked.connect(lambda: self._remove())
            for b in (self.reset_btn, self.signout_btn, self.disable_btn, self.remove_btn):
                row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
        else:
            theirs = registry.share_level(uid, me)
            lay.addWidget(self._label(
                "Their calendar & to-dos: "
                + (f"shared with you ({theirs})" if theirs else "not shared with you"), pal))

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"font-size:12px; color:{pal['muted']};")
        self.note.hide()
        lay.addWidget(self.note)
        self.revealed = QLineEdit()
        self.revealed.setReadOnly(True)
        self.revealed.hide()
        lay.addWidget(self.revealed)

    @staticmethod
    def _label(text: str, pal: dict) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size:13px; color:{pal['text']};")
        return lbl

    def _say(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    # -- actions ---------------------------------------------------------

    def _share(self, level) -> None:
        registry.set_share(self.panel.me, self.uid, level)
        self.relation.setText(_relation(self.panel.me, self.uid))
        self.panel._changed()

    def _show(self, on: bool) -> None:
        registry.set_admin_view(self.panel.me, self.uid, on)
        self.panel._changed()

    def _vocab(self, on: bool) -> None:
        registry.set_vocab_share(self.panel.me, self.uid, on)

    def _reset(self) -> None:
        pw = passwords.generate()
        registry.set_password(self.uid, pw, must_change=True, min_length=0)
        sessions.revoke_user(self.uid)
        self._say("New password — shown once. They'll choose their own when they sign in.")
        self.revealed.setText(pw)
        self.revealed.show()
        self.revealed.selectAll()
        self.panel._changed()

    def _sign_out(self) -> None:
        n = sessions.revoke_user(self.uid)
        self._say(f"Signed out of {n} device{'s' if n != 1 else ''}. Their password is unchanged.")
        self.panel._changed()

    def _toggle_disabled(self) -> None:
        u = registry.get(self.uid) or {}
        registry.update_user(self.uid, disabled=not u.get("disabled"))
        if not u.get("disabled"):
            sessions.revoke_user(self.uid)
        self.disable_btn.setText("Disable" if u.get("disabled") else "Enable")
        self._say("" if u.get("disabled") else "Disabled — they can't sign in until you enable them.")
        self.panel._changed()

    def _remove(self) -> None:
        u = registry.get(self.uid) or {}
        typed, ok = QInputDialog.getText(
            self, "Remove person",
            f"Type {u.get('username')} to remove them. Their calendar is kept in legacy/, not deleted.")
        if not ok or typed.strip().lower() != u.get("username"):
            return
        registry.remove_user(self.uid)
        sessions.revoke_user(self.uid)
        self.panel._rebuild_people()
        self.panel._changed()


class AccountPanel(FeaturePanel):
    feature_name = "account"

    def __init__(self, db=None, dark: bool = True) -> None:
        super().__init__()
        self._db = db
        self._dark = dark
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(self._scroll)
        self.reload()

    # -- the contract -----------------------------------------------------------

    def reload(self) -> None:
        """Rebuilt, not refreshed: who is signed in decides what the page is."""
        self.me = users.current()
        me = registry.get(self.me) if (self.me and registry.exists()) else None
        self.is_admin = bool(me and me.get("role") == "admin")
        self.cards: dict = {}
        self._sub = self._devices_lay = self._people_lay = None
        page = QWidget()
        from assistant.calendar_ui.users_dialogs import _checkbox_style
        page.setStyleSheet(_checkbox_style())     # boxes that read in both themes
        outer = QHBoxLayout(page)
        outer.setContentsMargins(28, 22, 28, 22)
        wrap = QWidget()
        wrap.setMaximumWidth(820)             # a readable column, not a 1400px page
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        outer.addWidget(wrap, 1, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        if me is None:
            msg = QLabel("No accounts on this Mac yet.")
            msg.setObjectName("muted")
            col.addWidget(msg)
        else:
            self._build(col, me)
        col.addStretch(1)
        self._scroll.setWidget(page)
        self._attach_info()

    def apply_theme(self, dark: bool) -> None:
        self._dark = dark
        self.reload()

    # -- the page ---------------------------------------------------------------

    def _build(self, col, me: dict) -> None:
        pal = _palette(self._dark)
        head = QFrame()
        head.setObjectName("person_card")
        head.setStyleSheet(_card_style(pal))
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 16, 18, 16)
        h.setSpacing(14)
        self.avatar = _avatar(me["display_name"], me.get("color", ""), 52, uid=self.me)
        h.addWidget(self.avatar)
        names = QVBoxLayout()
        names.setSpacing(2)
        t = QLabel(me["display_name"])
        t.setObjectName("account_title")
        t.setStyleSheet(f"font-size: 22px; font-weight: 700; color:{pal['text']};")
        names.addWidget(t)
        sub = QLabel(f"@{me['username']}{' · admin' if self.is_admin else ''}")
        sub.setStyleSheet(f"font-size:13px; color:{pal['muted']};")
        names.addWidget(sub)
        if self.is_admin:
            self._sub = QLabel(self._summary())
            self._sub.setStyleSheet(f"font-size:12px; color:{pal['muted']};")
            names.addWidget(self._sub)
        h.addLayout(names, 1)
        btns = QVBoxLayout()
        btns.setSpacing(6)
        self.change_pw_btn = QPushButton("Change password…")
        self.change_pw_btn.clicked.connect(lambda: self._change_password())
        btns.addWidget(self.change_pw_btn)
        photo = QHBoxLayout()
        photo.setSpacing(6)
        self.photo_btn = QPushButton("Change photo…" if me.get("avatar") else "Add photo…")
        self.photo_btn.clicked.connect(lambda: self._pick_photo())
        photo.addWidget(self.photo_btn)
        self.clear_photo_btn = QPushButton("Remove")
        self.clear_photo_btn.setToolTip("Remove your photo — your initial shows instead.")
        self.clear_photo_btn.clicked.connect(lambda: self._clear_photo())
        self.clear_photo_btn.setVisible(bool(me.get("avatar")))
        photo.addWidget(self.clear_photo_btn)
        btns.addLayout(photo)
        h.addLayout(btns)
        h.setAlignment(btns, Qt.AlignmentFlag.AlignVCenter)
        col.addWidget(head)

        self._section(col, "People", pal)
        self.created_note = QLabel("")
        self.created_note.setWordWrap(True)
        self.created_note.hide()
        self.created = QLineEdit()
        self.created.setReadOnly(True)
        self.created.hide()
        col.addWidget(self.created_note)
        col.addWidget(self.created)
        box = QWidget()
        self._people_lay = QVBoxLayout(box)
        self._people_lay.setContentsMargins(0, 0, 0, 0)
        self._people_lay.setSpacing(10)
        col.addWidget(box)
        self._rebuild_people()
        if self.is_admin:
            row = QHBoxLayout()
            self.add_btn = QPushButton("+ Add a person")
            self.add_btn.setObjectName("primary")
            self.add_btn.clicked.connect(lambda: self._create())
            row.addWidget(self.add_btn)
            row.addStretch(1)
            col.addLayout(row)

        self._section(col, "Tasks", pal)
        self.group_box = QCheckBox("Group shared to-dos by person")
        self.group_box.setChecked(bool((me.get("settings") or {}).get("todos_group_by_owner")))
        self.group_box.toggled.connect(lambda on: self._setting("todos_group_by_owner", on))
        col.addWidget(self.group_box)
        col.addWidget(self._hint(
            "On: each person who shares with you gets their own section in Tasks, below "
            "yours. Off: their to-dos sit in Today and General with yours — the Whose chips "
            "filter them. Notifications are only ever about your own calendar and to-dos.", pal))

        if self.is_admin:
            self._section(col, "Sign-in", pal)
            policy = registry.load().get("policy", {})
            self.require_box = QCheckBox("Require sign-in everywhere")
            self.require_box.setChecked(bool(policy.get("require_login")))
            self.require_box.toggled.connect(lambda on: self._require_changed(bool(on)))
            self.require_box.setToolTip(
                "On: every phone, tablet and computer must sign in as someone\n"
                "before it shows anything. Off: a device nobody signed in on\n"
                "acts as the admin.")
            col.addWidget(self.require_box)
            row = QHBoxLayout()
            row.addWidget(QLabel("Auto sign-out:"))
            self.auto_box = QComboBox()
            self.auto_box.addItems(["Off — only when signed out", "After"])
            self.auto_box.setToolTip("Sign a device out on its own once it has gone this many\n"
                                     "days without being used.")
            self.auto_days = QSpinBox()
            self.auto_days.setRange(1, 3650)
            self.auto_days.setSuffix(" days unused")
            self.auto_days.setStyleSheet("QSpinBox:disabled { color: rgba(128,128,128,0.55); }")
            days = policy.get("auto_signout_days")
            self.auto_box.setCurrentIndex(1 if days else 0)
            self.auto_days.setValue(int(days or 30))
            self.auto_days.setEnabled(bool(days))
            self.auto_box.currentIndexChanged.connect(lambda _i: self._auto_changed())
            self.auto_days.valueChanged.connect(lambda _v: self._auto_changed())
            row.addWidget(self.auto_box)
            row.addWidget(self.auto_days)
            row.addStretch(1)
            col.addLayout(row)
            col.addWidget(self._hint("Off: a device nobody signed in on acts as you, the admin.", pal))
            row = QHBoxLayout()
            row.addWidget(QLabel("Shortest password:"))
            self.pw_min = QSpinBox()
            self.pw_min.setRange(1, 64)
            self.pw_min.setSuffix(" characters")
            self.pw_min.setValue(int(policy.get("password_min_length") or passwords.MIN_LENGTH))
            self.pw_min.valueChanged.connect(
                lambda v: registry.set_policy(password_min_length=int(v)))
            row.addWidget(self.pw_min)
            row.addStretch(1)
            col.addLayout(row)
            self.pw_empty_box = QCheckBox("Allow empty passwords")
            self.pw_empty_box.setChecked(bool(policy.get("allow_empty_password")))
            self.pw_empty_box.toggled.connect(
                lambda on: registry.set_policy(allow_empty_password=bool(on)))
            self.pw_empty_box.setToolTip("On: a person may choose no password at all, and signs in\n"
                                         "with the password field left blank.")
            col.addWidget(self.pw_empty_box)
            col.addWidget(self._hint("For everyone else when they choose a password. "
                                     "Yours follows no rule.", pal))

            self._section(col, "Signed-in devices", pal)
            dev = QWidget()
            self._devices_lay = QVBoxLayout(dev)
            self._devices_lay.setContentsMargins(0, 0, 0, 0)
            self._devices(self._devices_lay, pal)
            col.addWidget(dev)

        col.addSpacing(10)
        row = QHBoxLayout()
        row.addStretch(1)
        self.sign_out_btn = QPushButton("Sign out of this Mac")
        self.sign_out_btn.clicked.connect(lambda: self._sign_out())
        row.addWidget(self.sign_out_btn)
        col.addLayout(row)

    def _rebuild_people(self) -> None:
        if self._people_lay is None:
            return
        while self._people_lay.count():
            it = self._people_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.cards = {}
        others = [uid for uid in registry.user_ids(include_disabled=self.is_admin)
                  if uid != self.me]
        if not others:
            self._people_lay.addWidget(self._hint("Nobody else has an account yet.",
                                                  _palette(self._dark)))
        for uid in others:
            card = _PersonCard(self, uid)
            self.cards[uid] = card
            self._people_lay.addWidget(card)
        self._attach_info()

    def _attach_info(self) -> None:
        """ⓘ beside every control that explains itself (Gil, 2026-09-29)."""
        from assistant.calendar_ui.info_tip import attach
        attach(self)

    # -- pieces ---------------------------------------------------------------

    @staticmethod
    def _section(col, text: str, pal: dict) -> None:
        h = QLabel(text.upper())
        h.setStyleSheet(f"font-size:11px; font-weight:700; letter-spacing:1px; color:{pal['muted']};")
        col.addSpacing(10)
        col.addWidget(h)

    @staticmethod
    def _hint(text: str, pal: dict) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"font-size:12px; color:{pal['muted']};")
        return lbl

    def _summary(self) -> str:
        n = len(registry.user_ids())
        live = len(sessions.list_for())
        return (f"{n} {'person' if n == 1 else 'people'} · {live} signed-in device"
                f"{'s' if live != 1 else ''}")

    def _devices(self, lay, pal: dict) -> None:
        rows = sorted(sessions.list_for(), key=lambda r: -r.get("last_seen", 0))
        if not rows:
            lay.addWidget(self._hint("Nobody is signed in anywhere.", pal))
        for r in rows:
            u = registry.get(r["user_id"]) or {}
            where = r.get("label") or r.get("source") or "device"
            seen = _dt.datetime.fromtimestamp(r.get("last_seen", 0)).strftime("%d %b %H:%M")
            line = QLabel(f"<b>{u.get('display_name', '?')}</b> — {where}  "
                          f"<span style='color:{pal['muted']}'>last seen {seen}</span>")
            line.setStyleSheet(f"font-size:13px; color:{pal['text']};")
            lay.addWidget(line)

    # -- what a change touches ----------------------------------------------------

    def _changed(self) -> None:
        """Update what DEPENDS on a change — counts, devices, the calendar, the
        other panels — and leave the page alone (see the module docstring)."""
        if self._sub is not None:
            self._sub.setText(self._summary())
        if self._devices_lay is not None:
            while self._devices_lay.count():
                it = self._devices_lay.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self._devices(self._devices_lay, _palette(self._dark))
        win = self.window()
        if win is not self and hasattr(win, "refresh_calendar"):
            win.refresh_calendar()
        for panel in getattr(win, "_panels", {}).values():
            if panel is not self and hasattr(panel, "reload"):
                panel.reload()

    def _setting(self, key: str, on: bool) -> None:
        registry.set_setting(self.me, key, bool(on))
        self._changed()

    def _require_changed(self, on: bool) -> None:
        """Requiring sign-in must not sign out the admin who asked for it.
        A Mac nobody signed in on acts as the admin only WHILE sign-in is not
        required; turning it on left this window acting as nobody, and the
        next click on Account & Sharing crashed the app (found by the
        click-everything sweep, 2026-09-29). So the person flipping the switch
        is signed in for real first — a session that survives a restart."""
        if on:
            from assistant.calendar_ui.users_dialogs import keep_signed_in
            keep_signed_in(users.current())
        registry.set_policy(require_login=on)
        self._changed()

    def _auto_changed(self) -> None:
        on = self.auto_box.currentIndex() == 1
        self.auto_days.setEnabled(on)
        registry.set_policy(auto_signout_days=self.auto_days.value() if on else None)

    def _create(self) -> None:
        name, ok = QInputDialog.getText(self, "Add a person", "Username (a–z, 0–9):")
        if not ok or not name.strip():
            return
        display, _ = QInputDialog.getText(self, "Add a person", "Display name:",
                                          text=name.strip().capitalize())
        pw = passwords.generate()
        try:
            uid = registry.create_user(name, pw, display_name=display.strip())
        except ValueError as e:
            QMessageBox.warning(self, "Add a person", str(e))
            return
        registry.set_password(uid, pw, must_change=True, min_length=0)
        self.created_note.setText(f"{registry.get(uid)['display_name']}'s password — shown once. "
                                  "They'll choose their own when they sign in.")
        self.created.setText(pw)
        self.created_note.show()
        self.created.show()
        self.created.selectAll()
        self._rebuild_people()
        self._changed()

    def _pick_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a photo", os.path.expanduser("~/Pictures"),
            "Pictures (*.png *.jpg *.jpeg *.heic *.heif *.webp *.bmp *.gif *.tif *.tiff)")
        if not path:
            return
        try:
            registry.set_avatar(self.me, photo_bytes(path))
        except ValueError as e:
            QMessageBox.warning(self, "Profile photo", str(e))
            return
        self._photo_changed()

    def _clear_photo(self) -> None:
        registry.clear_avatar(self.me)
        self._photo_changed()

    def _photo_changed(self) -> None:
        """Swap the header's picture in place — the page is not rebuilt under
        the button that was just clicked (module docstring)."""
        me = registry.get(self.me) or {}
        fresh = _avatar(me.get("display_name", "?"), me.get("color", ""), 52, uid=self.me)
        lay = self.avatar.parentWidget().layout()
        lay.replaceWidget(self.avatar, fresh)
        self.avatar.deleteLater()
        self.avatar = fresh
        self.photo_btn.setText("Change photo…" if me.get("avatar") else "Add photo…")
        self.clear_photo_btn.setVisible(bool(me.get("avatar")))

    def _change_password(self) -> None:
        from assistant.calendar_ui.users_dialogs import ChangePasswordDialog
        ChangePasswordDialog(self).exec()

    def _sign_out(self) -> None:
        chip = getattr(self.window(), "_user_chip", None)
        if chip is not None:
            chip.sign_out()
        else:
            s = local_session.read()
            if s:
                sessions.revoke(s["session_token"])
