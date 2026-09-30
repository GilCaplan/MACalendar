"""Requiring sign-in must not leave the Mac acting as nobody (2026-09-29).

Found by the click-everything sweep (test_gui_crash_sweep.py): a Mac nobody
had signed in on acts as the admin only while sign-in is NOT required. The
admin turned "Require sign-in everywhere" on from the Account tab, the window
went on showing "Gil", and the next click on Account & Sharing raised
TypeError on a missing user record — which PyQt turns into a crash of the
whole app."""

import pytest

from assistant import users
from assistant.users import local_session, registry, sessions


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def admin(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("MACALENDAR_SESSION_FILE", str(tmp_path / "session.json"))
    uid = registry.create_user("gil", "admin-pass", role="admin")
    users.set_process_default(None)          # nobody signed in: the implicit admin
    yield uid
    users.set_process_default(None)


def test_turning_it_on_signs_in_the_admin_who_did_it(app, admin):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from assistant.calendar_ui.account_panel import AccountPanel
    assert users.current() == admin and local_session.current_user() is None
    panel = AccountPanel(None)
    panel.show()
    QTest.mouseClick(panel.require_box, Qt.MouseButton.LeftButton)
    assert registry.load()["policy"]["require_login"] is True
    assert users.current() == admin, "the window must still be acting as the admin"
    assert local_session.current_user() == admin, "and stay signed in after a restart"


def test_account_and_sharing_with_nobody_signed_in_offers_sign_in(app, admin):
    from PyQt6.QtWidgets import QPushButton
    from assistant.calendar_ui.users_dialogs import AccountDialog
    registry.set_policy(require_login=True)          # now nobody is implicit
    assert users.current() is None
    dlg = AccountDialog(None)                         # used to raise TypeError
    assert any(b.text() == "Sign in…" for b in dlg.findChildren(QPushButton))
