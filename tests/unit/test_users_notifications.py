"""Users, phase 6: notifications follow the person (DEVQA Q65).

Each person's day panel is their own; what others share with them joins it
only if they asked; the admin's view toggles are a VIEW, never a subscription
— so the admin is not spammed with everyone's day. The Mac's banners belong to
whoever is signed in at the Mac.
"""
from __future__ import annotations

import datetime as dt

import pytest

from assistant import users
from assistant.users import local_session, registry, sessions

TODAY = dt.date.today()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("MACALENDAR_SESSION_FILE", str(tmp_path / "session.json"))
    from assistant.users import routes
    routes._fails.clear()
    gil = registry.create_user("gil", "admin-pass", role="admin")
    dana = registry.create_user("dana", "dana-pass", display_name="Dana")
    noa = registry.create_user("noa", "noa-pass", display_name="Noa")
    from assistant.db import get_db
    for uid, title in ((gil, "gil's shiur"), (dana, "dana's dentist"), (noa, "noa's exam")):
        with users.bind(uid):
            get_db().create_event_from_dict({
                "title": title, "date": TODAY.isoformat(), "start_time": "09:00",
                "end_time": "10:00", "attendees": "", "location": "", "description": "",
                "recurrence": "", "recurrence_end": ""})
    from assistant.api import server
    c = server.create_app().test_client()
    tok = {n: c.post("/auth/login", json={"username": n, "password": f"{'admin' if n == 'gil' else n}-pass"}
                     ).get_json()["session_token"] for n in ("gil", "dana", "noa")}
    users.set_process_default(None)
    yield c, {"gil": gil, "dana": dana, "noa": noa}, tok
    users.set_process_default(None)


def _digest(c, tok):
    return c.get(f"/digest?date={TODAY.isoformat()}", headers={"X-Session-Token": tok}).get_json()


def test_each_persons_day_panel_is_their_own(world):
    c, u, tok = world
    assert _digest(c, tok["dana"])["body"].count("dentist") == 1
    assert "shiur" not in _digest(c, tok["dana"])["body"]


def test_shared_items_never_notify_even_with_the_old_opt_in_set(world):
    """Gil, 2026-09-28: "notifications should only be the main user, not
    include shared events" — the Q65 opt-in is gone, and a stale setting
    left in users.json does nothing."""
    c, u, tok = world
    registry.set_share(u["dana"], u["noa"], "view")
    registry.set_setting(u["noa"], "notify_shared", True)
    body = _digest(c, tok["noa"])["body"]
    assert "dentist" not in body and "noa's exam" in body


def test_a_shared_event_carries_no_reminder_time(world):
    c, u, tok = world
    registry.set_share(u["dana"], u["noa"], "view")
    rows = c.get(f"/events?date={TODAY.isoformat()}",
                 headers={"X-Session-Token": tok["noa"]}).get_json()
    shared = [r for r in rows if r.get("shared")]
    own = [r for r in rows if not r.get("shared")]
    assert shared and own
    assert all(r["notify_at"] is None and r["notify_suppressed_reason"] == "shared"
               for r in shared)
    assert all(r["notify_suppressed_reason"] != "shared" for r in own)


def test_the_admin_is_not_spammed_by_his_view_toggles(world):
    c, u, tok = world
    registry.set_admin_view(u["gil"], u["dana"], True)
    registry.set_admin_view(u["gil"], u["noa"], True)
    registry.set_setting(u["gil"], "notify_shared", True)       # even asking: a toggle is no share
    body = _digest(c, tok["gil"])["body"]
    assert "shiur" in body and "dentist" not in body and "exam" not in body


def test_the_macs_banners_belong_to_whoever_is_signed_in_there(world):
    from assistant.notifier import mac_user
    _, u, _ = world
    assert mac_user() == (u["gil"], True)                        # nobody: the admin, for now
    local_session.write(u["dana"], "dana", "Dana", sessions.issue(u["dana"]))
    assert mac_user() == (u["dana"], True)
    local_session.clear()
    registry.set_policy(require_login=True)
    assert mac_user() == (None, False)                           # nobody, and sign-in required: silent
