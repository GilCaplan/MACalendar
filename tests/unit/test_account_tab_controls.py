"""Every control on the Mac's Account tab, clicked, with its effect checked.

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


def _select_row(admin, uid):
    row = admin._ids.index(uid)
    item = admin.table.item(row, 1)
    rect = admin.table.visualItemRect(item)
    QTest.mouseClick(admin.table.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, rect.center())
    QApplication.processEvents()


def _cell_box(admin, uid, col) -> QCheckBox:
    return admin.table.cellWidget(admin._ids.index(uid), col).checkbox


# -- the admin's dashboard -----------------------------------------------------


def test_sharing_from_the_dashboard_saves_and_refreshes_the_calendar(people):
    win, panel = _open(people["gil"])
    combo = panel.account.share_boxes[people["dana"]]
    _pick(combo, 2)                                              # Edit
    assert registry.share_level(people["gil"], people["dana"]) == "edit"
    assert win.calendar_refreshes >= 1
    _pick(combo, 0)                                              # Not shared
    assert registry.share_level(people["gil"], people["dana"]) is None


def test_group_by_person_saves_and_reloads_the_tasks_panel(people):
    win, panel = _open(people["gil"])
    _click(panel.account.group_box)
    assert registry.get(people["gil"])["settings"]["todos_group_by_owner"] is True
    assert win._panels["tasks"].reloads >= 1
    _click(panel.account.group_box)
    assert registry.get(people["gil"])["settings"]["todos_group_by_owner"] is False


def test_the_table_checkboxes_work_and_the_page_survives_the_click(people):
    win, panel = _open(people["gil"])
    admin = panel.admin
    _click(_cell_box(admin, people["dana"], 5))                   # show in my calendar
    assert registry.admin_shows(people["gil"], people["dana"])
    assert panel.admin is admin, "the page rebuilt itself under the click"
    assert win.calendar_refreshes >= 1
    _click(_cell_box(admin, people["dana"], 6))                   # my vocabulary
    assert people["dana"] in registry.load()["vocab_shares"][people["gil"]]


def test_row_buttons_wait_for_a_selection_and_never_act_on_yourself(people):
    _, panel = _open(people["gil"])
    admin = panel.admin
    assert not any(b.isEnabled() for b in (admin.reset_btn, admin.signout_btn,
                                           admin.disable_btn, admin.remove_btn))
    assert "Select a person" in admin.reset_btn.toolTip()
    _select_row(admin, people["gil"])
    assert admin.reset_btn.isEnabled() and admin.signout_btn.isEnabled()
    assert not admin.disable_btn.isEnabled() and not admin.remove_btn.isEnabled()
    _select_row(admin, people["dana"])
    assert all(b.isEnabled() for b in (admin.reset_btn, admin.signout_btn,
                                       admin.disable_btn, admin.remove_btn))


def test_reset_password_shows_it_once_and_it_stays_on_screen(people):
    _, panel = _open(people["gil"])
    admin = panel.admin
    _select_row(admin, people["dana"])
    _click(admin.reset_btn)
    pw = admin.revealed.text()
    assert admin.revealed.isVisible() and len(pw) >= 8
    assert registry.verify_login("dana", pw) == people["dana"]
    assert panel.admin is admin and admin.revealed.text() == pw


def test_sign_out_ends_their_sessions_and_updates_the_devices(people):
    sessions.issue(people["dana"], source="ios", label="iPhone")
    _, panel = _open(people["gil"])
    assert "2 signed-in devices" in panel._sub.text()
    _select_row(panel.admin, people["dana"])
    _click(panel.admin.signout_btn)
    assert sessions.list_for(people["dana"]) == []
    assert "1 signed-in device" in panel._sub.text()


def test_disable_then_enable(people):
    _, panel = _open(people["gil"])
    admin = panel.admin
    _select_row(admin, people["dana"])
    _click(admin.disable_btn)
    assert registry.get(people["dana"]).get("disabled")
    assert admin.disable_btn.text() == "Enable"
    _click(admin.disable_btn)
    assert not registry.get(people["dana"]).get("disabled")


def test_new_user_is_created_and_its_password_stays_visible(people, monkeypatch):
    from assistant.calendar_ui import users_dialogs
    answers = iter([("noa", True), ("Noa", True)])
    monkeypatch.setattr(users_dialogs.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: next(answers)))
    _, panel = _open(people["gil"])
    admin = panel.admin
    _click(admin.create_btn)
    uid = registry.find("noa") if hasattr(registry, "find") else next(
        i for i in registry.user_ids() if registry.get(i)["username"] == "noa")
    assert uid and panel.admin is admin and admin.revealed.isVisible()
    assert registry.verify_login("noa", admin.revealed.text()) == uid
    assert "3 users" in panel._sub.text()


def test_remove_asks_for_the_username_then_removes(people, monkeypatch):
    from assistant.calendar_ui import users_dialogs
    _, panel = _open(people["gil"])
    admin = panel.admin
    _select_row(admin, people["dana"])
    monkeypatch.setattr(users_dialogs.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("nope", True)))
    _click(admin.remove_btn)
    assert registry.get(people["dana"]) is not None               # wrong name: kept
    monkeypatch.setattr(users_dialogs.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("dana", True)))
    _click(admin.remove_btn)
    assert people["dana"] not in registry.user_ids(include_disabled=True)


def test_require_sign_in_and_auto_sign_out(people):
    _, panel = _open(people["gil"])
    admin = panel.admin
    _click(admin.require_box)
    assert registry.load()["policy"]["require_login"] is True
    _click(admin.require_box)
    assert registry.load()["policy"]["require_login"] is False
    assert not admin.auto_days.isEnabled()
    _pick(admin.auto_box, 1)
    assert admin.auto_days.isEnabled()
    assert registry.load()["policy"]["auto_signout_days"] == 30
    admin.auto_days.setFocus()
    QTest.keyClick(admin.auto_days, Qt.Key.Key_Up)
    QApplication.processEvents()
    assert registry.load()["policy"]["auto_signout_days"] == 31
    _pick(admin.auto_box, 0)
    assert registry.load()["policy"]["auto_signout_days"] is None


def test_change_password_opens_the_dialog(people, monkeypatch):
    from assistant.calendar_ui import users_dialogs
    opened = []
    monkeypatch.setattr(users_dialogs.ChangePasswordDialog, "exec",
                        lambda self: opened.append(self) or 0)
    _, panel = _open(people["gil"])
    btn = next(b for b in panel.account.findChildren(QPushButton)
               if b.text().startswith("Change password"))
    _click(btn)
    assert len(opened) == 1


def test_sign_out_of_this_mac_goes_through_the_window(people):
    win, panel = _open(people["gil"])
    _click(panel.sign_out_btn)
    assert win._user_chip.signed_out == 1


# -- a user's own page ---------------------------------------------------------------


def test_a_users_page_shares_groups_and_signs_out(people):
    win, panel = _open(people["dana"])
    assert not hasattr(panel, "admin") or panel.__dict__.get("admin") is None
    _pick(panel.account.share_boxes[people["gil"]], 1)            # View
    assert registry.share_level(people["dana"], people["gil"]) == "view"
    _click(panel.account.group_box)
    assert registry.get(people["dana"])["settings"]["todos_group_by_owner"] is True
    assert win.calendar_refreshes >= 1
    _click(panel.sign_out_btn)
    assert win._user_chip.signed_out == 1
