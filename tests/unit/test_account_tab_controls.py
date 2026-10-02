"""Every control on the Mac's Account tab, clicked, with its effect checked.

Rewritten 2026-09-28 for the card design (one card per person, the phone's
layout): the row buttons live ON each person's card, so "select a row first"
no longer exists as a way for a button to do nothing.

Gil, 2026-09-28: "not all the toggles/buttons in account tab work properly".
Three did not: the page rebuilt itself on every change (destroying the
control mid-click and wiping a new user's shown-once password), the row
buttons looked live and silently did nothing until a row was selected, and a
sharing change refreshed nothing on the Mac. This file clicks each control
the way a person would — QTest events, not handler calls — as the admin and
as a user, inside a stand-in window that records what it was asked to
refresh.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt                              # noqa: E402
from PyQt6.QtTest import QTest                                   # noqa: E402
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox,  # noqa: E402
                             QMainWindow, QPushButton)

from assistant import users                                      # noqa: E402
from assistant.users import local_session, registry, sessions    # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def people(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("MACALENDAR_SESSION_FILE", str(tmp_path / "session.json"))
    gil = registry.create_user("gil", "admin-pass", role="admin")
    dana = registry.create_user("dana", "dana-pass")
    users.set_process_default(None)
    yield {"gil": gil, "dana": dana}
    users.set_process_default(None)


class _Tasks:
    def __init__(self):
        self.reloads = 0

    def reload(self):
        self.reloads += 1


class _Chip:
    def __init__(self):
        self.signed_out = 0

    def sign_out(self):
        self.signed_out += 1


class _Window(QMainWindow):
    """The calendar window, as far as the Account tab can see it."""

    def __init__(self):
        super().__init__()
        self.calendar_refreshes = 0
        self._panels = {"tasks": _Tasks()}
        self._user_chip = _Chip()

    def refresh_calendar(self):
        self.calendar_refreshes += 1


def _open(uid):
    from assistant.calendar_ui.account_panel import AccountPanel
    users.set_process_default(uid)
    local_session.write(uid, registry.get(uid)["username"], registry.get(uid)["display_name"],
                        sessions.issue(uid))
    win = _Window()
    panel = AccountPanel(None)
    win.setCentralWidget(panel)
    panel._panels = win._panels
    win.resize(1100, 1400)
    win.show()
    QApplication.processEvents()
    return win, panel


def _click(w):
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(min(8, w.width() // 2), w.height() // 2))
    QApplication.processEvents()


def _pick(combo: QComboBox, index: int):
    combo.setFocus()
    while combo.currentIndex() < index:
        QTest.keyClick(combo, Qt.Key.Key_Down)
    while combo.currentIndex() > index:
        QTest.keyClick(combo, Qt.Key.Key_Up)
    QApplication.processEvents()


# -- the admin's page -----------------------------------------------------------


def test_sharing_from_a_card_saves_updates_the_card_and_refreshes_the_calendar(people):
    win, panel = _open(people["gil"])
    card = panel.cards[people["dana"]]
    _pick(card.share_box, 2)                                     # Edit
    assert registry.share_level(people["gil"], people["dana"]) == "edit"
    assert card.relation.text().startswith("You share Edit")
    assert win.calendar_refreshes >= 1
    _pick(card.share_box, 0)                                     # Not shared
    assert registry.share_level(people["gil"], people["dana"]) is None


def test_group_by_person_saves_and_reloads_the_tasks_panel(people):
    win, panel = _open(people["gil"])
    _click(panel.group_box)
    assert registry.get(people["gil"])["settings"]["todos_group_by_owner"] is True
    assert win._panels["tasks"].reloads >= 1
    _click(panel.group_box)
    assert registry.get(people["gil"])["settings"]["todos_group_by_owner"] is False


def test_the_card_checkboxes_work_and_the_page_survives_the_click(people):
    win, panel = _open(people["gil"])
    card = panel.cards[people["dana"]]
    _click(card.show_box)
    assert registry.admin_shows(people["gil"], people["dana"])
    assert panel.cards[people["dana"]] is card, "the page rebuilt itself under the click"
    assert win.calendar_refreshes >= 1
    _click(card.vocab_box)
    assert people["dana"] in registry.load()["vocab_shares"][people["gil"]]


def test_reset_password_shows_it_once_on_the_card_and_it_stays(people):
    _, panel = _open(people["gil"])
    card = panel.cards[people["dana"]]
    _click(card.reset_btn)
    pw = card.revealed.text()
    assert card.revealed.isVisible() and len(pw) >= 8
    assert registry.verify_login("dana", pw) == people["dana"]
    assert panel.cards[people["dana"]] is card and card.revealed.text() == pw


def test_sign_out_everywhere_ends_their_sessions_and_updates_the_counts(people):
    sessions.issue(people["dana"], source="ios", label="iPhone")
    _, panel = _open(people["gil"])
    assert "2 signed-in devices" in panel._sub.text()
    card = panel.cards[people["dana"]]
    _click(card.signout_btn)
    assert sessions.list_for(people["dana"]) == []
    assert "1 signed-in device" in panel._sub.text()
    assert "Signed out of 1 device" in card.note.text()


def test_disable_then_enable(people):
    _, panel = _open(people["gil"])
    card = panel.cards[people["dana"]]
    _click(card.disable_btn)
    assert registry.get(people["dana"]).get("disabled")
    assert card.disable_btn.text() == "Enable"
    _click(card.disable_btn)
    assert not registry.get(people["dana"]).get("disabled")


def test_add_a_person_and_their_password_stays_visible(people, monkeypatch):
    from assistant.calendar_ui import account_panel
    answers = iter([("noa", True), ("Noa", True)])
    monkeypatch.setattr(account_panel.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: next(answers)))
    _, panel = _open(people["gil"])
    _click(panel.add_btn)
    uid = next(i for i in registry.user_ids() if registry.get(i)["username"] == "noa")
    assert uid in panel.cards and panel.created.isVisible()
    assert registry.verify_login("noa", panel.created.text()) == uid
    assert "3 people" in panel._sub.text()


def test_remove_asks_for_the_username_then_removes(people, monkeypatch):
    from assistant.calendar_ui import account_panel
    _, panel = _open(people["gil"])
    card = panel.cards[people["dana"]]
    monkeypatch.setattr(account_panel.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("nope", True)))
    _click(card.remove_btn)
    assert registry.get(people["dana"]) is not None               # wrong name: kept
    monkeypatch.setattr(account_panel.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("dana", True)))
    _click(card.remove_btn)
    assert people["dana"] not in registry.user_ids(include_disabled=True)
    QApplication.processEvents()
    assert people["dana"] not in panel.cards


def test_require_sign_in_and_auto_sign_out(people):
    _, panel = _open(people["gil"])
    _click(panel.require_box)
    assert registry.load()["policy"]["require_login"] is True
    _click(panel.require_box)
    assert registry.load()["policy"]["require_login"] is False
    assert not panel.auto_days.isEnabled()
    _pick(panel.auto_box, 1)
    assert panel.auto_days.isEnabled()
    assert registry.load()["policy"]["auto_signout_days"] == 30
    panel.auto_days.setFocus()
    QTest.keyClick(panel.auto_days, Qt.Key.Key_Up)
    QApplication.processEvents()
    assert registry.load()["policy"]["auto_signout_days"] == 31
    _pick(panel.auto_box, 0)
    assert registry.load()["policy"]["auto_signout_days"] is None


def test_the_admins_password_rules_are_set_from_the_tab(people):
    _, panel = _open(people["gil"])
    assert panel.pw_min.value() == 3 and not panel.pw_empty_box.isChecked()
    panel.pw_min.setFocus()
    QTest.keyClick(panel.pw_min, Qt.Key.Key_Up)
    QApplication.processEvents()
    assert registry.load()["policy"]["password_min_length"] == 4
    _click(panel.pw_empty_box)
    assert registry.load()["policy"]["allow_empty_password"] is True
    assert registry.password_rules(people["dana"]) == (4, True)
    assert registry.password_rules(people["gil"]) == (0, True)


def test_change_password_opens_the_dialog(people, monkeypatch):
    from assistant.calendar_ui import users_dialogs
    opened = []
    monkeypatch.setattr(users_dialogs.ChangePasswordDialog, "exec",
                        lambda self: opened.append(self) or 0)
    _, panel = _open(people["gil"])
    _click(panel.change_pw_btn)
    assert len(opened) == 1


def _no_password(uid):
    """The admin's real state while login is off: migrated with no password."""
    registry._mutate(lambda d: d["users"][uid].__setitem__("password", None))


def _change(dialog, current, new):
    for field, text in ((dialog.current, current), (dialog.new, new), (dialog.again, new)):
        QTest.keyClicks(field, text)
    _click(dialog.save)


def test_save_sets_a_first_password_with_current_left_blank(people):
    """Gil, 2026-10-02: "when i try to change password, the save button doesn't
    work". His account had no password, so no answer to "Current" matched."""
    from assistant.calendar_ui.users_dialogs import ChangePasswordDialog
    _no_password(people["gil"])
    users.set_process_default(people["gil"])
    d = ChangePasswordDialog(None)
    d.show()
    assert d.current.placeholderText()
    _change(d, "", "brand-new-pass")
    assert d.result() == d.DialogCode.Accepted, d.error.text()
    assert registry.verify_login("gil", "brand-new-pass") == people["gil"]


def test_save_still_refuses_a_wrong_current_password(people):
    from assistant.calendar_ui.users_dialogs import ChangePasswordDialog
    users.set_process_default(people["dana"])
    for current in ("", "not-it"):
        d = ChangePasswordDialog(None)
        d.show()
        _change(d, current, "brand-new-pass")
        assert d.result() != d.DialogCode.Accepted and "wrong" in d.error.text()
    assert registry.verify_login("dana", "dana-pass") == people["dana"]


def test_sign_out_of_this_mac_goes_through_the_window(people):
    win, panel = _open(people["gil"])
    _click(panel.sign_out_btn)
    assert win._user_chip.signed_out == 1


# -- a user's own page ---------------------------------------------------------------


def test_a_users_page_shares_groups_and_signs_out(people):
    win, panel = _open(people["dana"])
    assert not panel.is_admin
    card = panel.cards[people["gil"]]
    assert not hasattr(card, "reset_btn")                        # no account controls
    _pick(card.share_box, 1)                                     # View
    assert registry.share_level(people["dana"], people["gil"]) == "view"
    _click(panel.group_box)
    assert registry.get(people["dana"])["settings"]["todos_group_by_owner"] is True
    assert win.calendar_refreshes >= 1
    _click(panel.sign_out_btn)
    assert win._user_chip.signed_out == 1


def test_the_non_obvious_controls_have_an_info_button(people):
    """Gil, 2026-09-29: "add info tooltip for non trivial features". The ⓘ
    says what the control's own tooltip says — including after the person
    cards are rebuilt by a change."""
    from PyQt6.QtWidgets import QToolButton
    win, panel = _open(people["gil"])

    def texts():
        return {t.toolTip() for t in panel.findChildren(QToolButton, "info_tip")}
    card = panel.cards[people["dana"]]
    for w in (card.share_box, card.show_box, card.vocab_box, panel.require_box, panel.auto_box):
        assert w.toolTip() and w.toolTip() in texts(), w.objectName() or w.text()
    _pick(card.share_box, 1)                                     # a change rebuilds the cards
    assert panel.cards[people["dana"]].share_box.toolTip() in texts()
