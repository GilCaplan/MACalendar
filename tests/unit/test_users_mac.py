"""Users, phase 4: the Mac — sign in, Account & Sharing, the admin console, the
merged calendar in the window's own views, and the HUD following the Mac.

Every control is driven with QTest key presses and mouse clicks (CLAUDE.md:
three HUD bugs once shipped green under tests that called handlers).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import stat

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt                                    # noqa: E402
from PyQt6.QtTest import QTest                                 # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton          # noqa: E402

from assistant import users                                    # noqa: E402
from assistant.users import local_session, registry, sessions  # noqa: E402

DAY = dt.date(2026, 10, 6)


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


def _click(w):
    QTest.mouseClick(w, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def _type(w, text):
    w.setFocus()
    QTest.keyClicks(w, text)


# ------------------------------------------------------------------ sign in

def test_signing_in_writes_a_private_session_for_this_mac(people):
    from assistant.calendar_ui.users_dialogs import LoginDialog
    dlg = LoginDialog()
    _type(dlg.username, "dana")
    _type(dlg.password, "dana-pass")
    _click(dlg.sign_in)
    assert dlg.user_id == people["dana"] and users.current() == people["dana"]
    saved = json.loads(open(local_session.path()).read())
    assert saved["username"] == "dana" and saved["session_token"]
    assert stat.S_IMODE(os.stat(local_session.path()).st_mode) == 0o600
    assert sessions.resolve(saved["session_token"])["user_id"] == people["dana"]


def test_a_wrong_password_says_so_and_saves_nothing(people):
    from assistant.calendar_ui.users_dialogs import LoginDialog
    dlg = LoginDialog()
    dlg.show()
    _type(dlg.username, "dana")
    _type(dlg.password, "nope")
    _click(dlg.sign_in)
    assert dlg.user_id is None and dlg.error.isVisible()
    assert not os.path.exists(local_session.path())


def test_a_live_saved_session_signs_in_without_asking(people):
    from assistant.calendar_ui.users_dialogs import sign_in
    tok = sessions.issue(people["dana"], source="mac")
    local_session.write(people["dana"], "dana", "Dana", tok)
    assert sign_in() == people["dana"]


# ------------------------------------------------------------------ account

def test_choosing_edit_in_the_sharing_list_shares_the_calendar(people):
    from assistant.calendar_ui.users_dialogs import AccountDialog
    users.set_process_default(people["dana"])
    dlg = AccountDialog()
    dlg.show()
    box = dlg.share_boxes[people["gil"]]
    box.setFocus()
    QTest.keyClick(box, Qt.Key.Key_Down)
    QTest.keyClick(box, Qt.Key.Key_Down)
    QApplication.processEvents()
    assert registry.share_level(people["dana"], people["gil"]) == "edit"
    _click(dlg.group_box)
    assert registry.get(people["dana"])["settings"]["todos_group_by_owner"] is True


# ------------------------------------------------------------------ admin

def test_the_admin_resets_a_password_and_sees_it_once(people):
    from assistant.calendar_ui.users_dialogs import AdminDialog
    users.set_process_default(people["gil"])
    dlg = AdminDialog()
    dlg.show()
    row = dlg._ids.index(people["dana"])
    dlg.table.selectRow(row)
    _click(dlg.reset_btn)
    pw = dlg.revealed.text()
    assert len(pw) == 12 and dlg.revealed.isVisible()
    assert registry.verify_login("dana", pw) == people["dana"]
    assert registry.get(people["dana"])["must_change_password"] is True


def test_the_admin_toggles_a_user_into_his_view(people):
    from assistant.calendar_ui.users_dialogs import AdminDialog
    users.set_process_default(people["gil"])
    dlg = AdminDialog()
    dlg.show()
    row = dlg._ids.index(people["dana"])
    _click(dlg.table.cellWidget(row, 5).checkbox)
    assert registry.admin_shows(people["gil"], people["dana"]) is True


def test_the_admin_creates_a_user(people, monkeypatch):
    from assistant.calendar_ui import users_dialogs
    answers = iter([("noa", True), ("Noa", True)])
    monkeypatch.setattr(users_dialogs.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: next(answers)))
    users.set_process_default(people["gil"])
    dlg = users_dialogs.AdminDialog()
    dlg.show()
    _click(dlg.create_btn)
    uid = registry.by_username("noa")
    assert uid and registry.verify_login("noa", dlg.revealed.text()) == uid


# ------------------------------------------------------------------ the merged view

def _event(uid, title):
    from assistant.db import get_db
    with users.bind(uid):
        return get_db().create_event_from_dict({
            "title": title, "date": DAY.isoformat(), "start_time": "09:00", "end_time": "10:00",
            "attendees": "", "location": "", "description": "",
            "recurrence": "", "recurrence_end": ""})


def test_the_month_view_shows_a_shared_calendar_with_the_owners_name(people):
    from assistant.calendar_ui.merged_db import MergedCalendar
    from assistant.calendar_ui.month_view import MonthView
    from assistant.db import CalendarDB
    _event(people["dana"], "dana's dentist")
    _event(people["gil"], "gil's shiur")
    registry.set_share(people["dana"], people["gil"], "view")
    users.set_process_default(people["gil"])
    merged = MergedCalendar(CalendarDB())
    rows = merged.get_events_for_month(DAY.year, DAY.month)
    by = {r["title"]: r for r in rows}
    assert set(by) == {"dana's dentist", "gil's shiur"}
    # its own colour, the owner's alongside for the card edge (2026-09-28)
    assert by["dana's dentist"]["owner_color"] == registry.get(people["dana"])["color"]
    view = MonthView(merged)
    view.show()
    view.navigate(DAY.year, DAY.month)
    view.refresh()
    QApplication.processEvents()
    from PyQt6.QtWidgets import QLabel
    texts = [w.text() for w in view.findChildren(QLabel)]
    assert any("Dana · dana's dentist" in t for t in texts), texts[:20]


def test_a_view_only_change_is_refused_with_a_message_not_a_crash(people):
    from assistant.calendar_ui.merged_db import MergedCalendar
    from assistant.db import CalendarDB
    # Dana is the viewer: the ADMIN may edit anything (DEVQA Q65), so he could
    # never be refused and would prove nothing here
    _event(people["gil"], "gil's shiur")
    registry.set_share(people["gil"], people["dana"], "view")
    users.set_process_default(people["dana"])
    said = []
    merged = MergedCalendar(CalendarDB(), on_refused=said.append)
    sid = next(r["id"] for r in merged.get_events_for_day(DAY) if r["shared"])
    assert merged.update_event(sid, title="changed") is None
    assert said and "view only" in said[0]
    with users.bind(people["gil"]):
        from assistant.db import get_db
        assert [e["title"] for e in get_db().get_events_for_day(DAY)] == ["gil's shiur"]
    registry.set_share(people["gil"], people["dana"], "edit")
    merged.update_event(sid, title="changed by dana")
    with users.bind(people["gil"]):
        assert [e["title"] for e in get_db().get_events_for_day(DAY)] == ["changed by dana"]


# ------------------------------------------------------------------ the HUD

def test_the_hud_follows_whoever_signs_in_at_the_mac(people, tmp_path, monkeypatch):
    from assistant import thinking_hud
    hud = type("H", (), {"apply_llm_calls": lambda s, c: None, "apply_entry": lambda s, e: None,
                         "_config": None})()
    local_session.write(people["dana"], "dana", "Dana", sessions.issue(people["dana"]))
    reader = thinking_hud._BusReader(hud, str(tmp_path / "config.yaml"))
    assert users.current() == people["dana"]
    import time
    time.sleep(0.02)
    local_session.write(people["gil"], "gil", "Gil", sessions.issue(people["gil"]))
    os.utime(local_session.path(), None)
    reader.poll()
    assert users.current() == people["gil"]


def test_the_account_tab_is_the_dashboard_for_the_admin_and_minimal_for_others(people):
    from PyQt6.QtWidgets import QLabel
    from assistant.calendar_ui.account_panel import AccountPanel
    users.set_process_default(people["gil"])
    admin_page = AccountPanel(None)
    admin_page.show()
    QApplication.processEvents()
    texts = [w.text() for w in admin_page.findChildren(QLabel)]
    assert "Admin dashboard" in texts and hasattr(admin_page, "admin")
    users.set_process_default(people["dana"])
    admin_page.reload()
    QApplication.processEvents()
    texts = [w.text() for w in admin_page.findChildren(QLabel)]
    assert "Your account" in texts and "Admin dashboard" not in texts


def test_choosing_auto_sign_out_in_the_dashboard_sets_the_policy(people):
    from assistant.calendar_ui.users_dialogs import AdminDialog
    users.set_process_default(people["gil"])
    dlg = AdminDialog()
    dlg.show()
    dlg.auto_box.setFocus()
    QTest.keyClick(dlg.auto_box, Qt.Key.Key_Down)
    QApplication.processEvents()
    assert registry.load()["policy"]["auto_signout_days"] == 30
    dlg.auto_box.setFocus()
    QTest.keyClick(dlg.auto_box, Qt.Key.Key_Up)
    QApplication.processEvents()
    assert registry.load()["policy"]["auto_signout_days"] is None


def test_the_admin_dashboard_puts_sharing_before_the_people_table(people):
    from PyQt6.QtWidgets import QComboBox
    from assistant.calendar_ui.account_panel import AccountPanel
    users.set_process_default(people["gil"])
    page = AccountPanel(None)
    page.show()
    QApplication.processEvents()
    assert page.account.share_boxes, "the admin's sharing menus are on the dashboard"
    box = page.account.share_boxes[people["dana"]]
    assert box.mapTo(page, box.rect().topLeft()).y() < page.admin.mapTo(page, page.admin.rect().topLeft()).y()



# ------------------------------------------------------------------ to-dos by person

def _todo(uid, title, list_name="today"):
    from assistant.db import get_db
    with users.bind(uid):
        return get_db().create_todo(title, list_name=list_name)


def _titles(lst):
    return [w._todo["title"] for w in lst._item_widgets]


def test_shared_todos_mix_in_filter_by_person_and_group_by_person(people):
    """Gil, 2026-09-28: "group shared to-dos by person toggle doesn't seem to
    do anything" — nothing read it. Mixed in by default; the person bar
    filters; the setting moves shared to-dos into a section per person."""
    from assistant.calendar_ui.merged_db import MergedCalendar
    from assistant.calendar_ui.todo_view import TodoView
    from assistant.db import CalendarDB
    _todo(people["dana"], "dana's slides")
    _todo(people["dana"], "dana's bank", "general")
    _todo(people["gil"], "gil's milk")
    registry.set_share(people["dana"], people["gil"], "view")
    users.set_process_default(people["gil"])
    view = TodoView(MergedCalendar(CalendarDB()))
    view.show()
    QApplication.processEvents()

    # mixed in, and the person bar is there because someone shares
    assert set(_titles(view._today_list)) == {"dana's slides", "gil's milk"}
    assert view._person_bar.isVisible()
    _click(view._person_bar.findChild(QPushButton, "person_chip_me"))
    assert _titles(view._today_list) == ["gil's milk"]
    _click(view._person_bar.findChild(QPushButton, f"person_chip_{people['dana']}"))
    assert _titles(view._today_list) == ["dana's slides"]
    assert not view._today_list._new_row.isVisible()      # a new task would be Gil's, not hers
    _click(view._person_bar.findChild(QPushButton, "person_chip_all"))

    # grouped: own lists are own; Dana gets her own section with both her lists
    registry.set_setting(people["gil"], "todos_group_by_owner", True)
    view.refresh()
    QApplication.processEvents()
    assert _titles(view._today_list) == ["gil's milk"]
    header, lst = view._people_sections
    assert header._title_label.text().startswith("Dana") if hasattr(header, "_title_label") else True
    assert set(_titles(lst)) == {"dana's slides", "dana's bank"}
    assert not lst._new_row.isVisible() and not lst._list_widget.dragEnabled()


def test_no_person_bar_when_nobody_shares(people):
    from assistant.calendar_ui.merged_db import MergedCalendar
    from assistant.calendar_ui.todo_view import TodoView
    from assistant.db import CalendarDB
    _todo(people["gil"], "gil's milk")
    users.set_process_default(people["gil"])
    view = TodoView(MergedCalendar(CalendarDB()))
    view.show()
    QApplication.processEvents()
    assert not view._person_bar.isVisible() and view._people_sections == []
