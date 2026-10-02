"""Users, phase 2: log in, sessions, the admin's console — over HTTP.

Everything goes through `create_app().test_client()` (the live port is refused
by conftest). The registry and the sessions file are each test's own.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from assistant.users import registry, sessions


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(tmp_path / "sessions.json"))
    from assistant.users import routes
    routes._fails.clear()
    from assistant.api import server
    return server.create_app().test_client()


@pytest.fixture
def people(app_client):
    admin = registry.create_user("gil", "admin-pass", role="admin")
    dana = registry.create_user("dana", "dana-pass")
    return admin, dana


def _login(c, name, pw, **kw):
    return c.post("/auth/login", json={"username": name, "password": pw, "source": "test", **kw})


def _tok(c, name, pw):
    r = _login(c, name, pw)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["session_token"]


def _h(tok):
    return {"X-Session-Token": tok}


# ------------------------------------------------------------------ login

def test_login_returns_a_token_and_the_user_never_the_hash(app_client, people):
    r = _login(app_client, "Gil", "admin-pass")
    body = r.get_json()
    assert r.status_code == 200 and body["session_token"]
    assert body["user"]["username"] == "gil" and "password" not in body["user"]


def test_a_wrong_password_is_a_401_and_five_in_a_row_a_pause(app_client, people):
    for _ in range(5):
        assert _login(app_client, "gil", "nope").status_code == 401
    assert _login(app_client, "gil", "admin-pass").status_code == 429


def test_a_disabled_account_cannot_log_in(app_client, people):
    registry.update_user(people[1], disabled=True)
    assert _login(app_client, "dana", "dana-pass").status_code == 401


def test_tokens_are_stored_only_as_hashes(app_client, people):
    tok = _tok(app_client, "dana", "dana-pass")
    text = pathlib.Path(sessions.path()).read_text()
    assert tok not in text and len(json.loads(text)) == 1


def test_an_unknown_token_is_always_a_401(app_client, people):
    assert app_client.get("/events", headers=_h("made-up")).status_code == 401


def test_logout_ends_the_session(app_client, people):
    tok = _tok(app_client, "dana", "dana-pass")
    app_client.post("/auth/logout", headers=_h(tok))
    assert app_client.get("/auth/me", headers=_h(tok)).status_code == 401


# ------------------------------------------------------------------ binding

def test_each_request_acts_as_its_sessions_user(app_client, people):
    """The binding is real: a to-do Dana adds is in Dana's list and nowhere else."""
    admin, dana = people
    d, g_ = _tok(app_client, "dana", "dana-pass"), _tok(app_client, "gil", "admin-pass")
    assert app_client.post("/todos", json={"title": "dana's milk"}, headers=_h(d)).status_code in (200, 201)
    mine = [t["title"] for t in app_client.get("/todos?list=today", headers=_h(d)).get_json()]
    his = [t["title"] for t in app_client.get("/todos?list=today", headers=_h(g_)).get_json()]
    assert "dana's milk" in mine and "dana's milk" not in his
    assert app_client.get("/auth/me", headers=_h(d)).get_json()["username"] == "dana"


def test_no_token_acts_as_the_admin_until_login_is_required(app_client, people):
    assert app_client.get("/auth/me").get_json()["username"] == "gil"
    registry.set_policy(require_login=True)
    assert app_client.get("/events").status_code == 401
    assert app_client.get("/health").status_code == 200           # always open
    assert _login(app_client, "dana", "dana-pass").status_code == 200


# ------------------------------------------------------------------ admin

def test_the_admin_console_wants_a_real_admin_login(app_client, people):
    assert app_client.get("/admin/users").status_code == 401        # implicit admin: no
    d = _tok(app_client, "dana", "dana-pass")
    assert app_client.get("/admin/users", headers=_h(d)).status_code == 403
    g_ = _tok(app_client, "gil", "admin-pass")
    rows = app_client.get("/admin/users", headers=_h(g_)).get_json()
    assert {r["username"] for r in rows} == {"gil", "dana"}
    assert all("password" not in r for r in rows)


def test_the_admin_creates_a_user_and_sees_the_generated_password_once(app_client, people):
    g_ = _tok(app_client, "gil", "admin-pass")
    r = app_client.post("/admin/users", json={"username": "noa", "display_name": "Noa"}, headers=_h(g_))
    body = r.get_json()
    assert r.status_code == 201 and len(body["password"]) == 12 and body["must_change_password"]
    assert _login(app_client, "noa", body["password"]).status_code == 200
    assert body["password"] not in pathlib.Path(registry.paths.registry_path()).read_text()


def test_a_reset_signs_the_user_out_everywhere_and_the_new_password_works(app_client, people):
    d = _tok(app_client, "dana", "dana-pass")
    g_ = _tok(app_client, "gil", "admin-pass")
    pw = app_client.post(f"/admin/users/{people[1]}/password", headers=_h(g_)).get_json()["password"]
    assert app_client.get("/auth/me", headers=_h(d)).status_code == 401
    assert _login(app_client, "dana", "dana-pass").status_code == 401
    assert _login(app_client, "dana", pw).status_code == 200


def test_changing_my_password_keeps_this_device_and_signs_out_the_rest(app_client, people):
    here, there = _tok(app_client, "dana", "dana-pass"), _tok(app_client, "dana", "dana-pass")
    r = app_client.post("/auth/password", json={"current": "dana-pass", "new": "new-dana-pass"},
                        headers=_h(here))
    assert r.status_code == 200
    assert app_client.get("/auth/me", headers=_h(here)).status_code == 200
    assert app_client.get("/auth/me", headers=_h(there)).status_code == 401
    wrong = app_client.post("/auth/password", json={"current": "bad", "new": "x" * 9}, headers=_h(here))
    assert wrong.status_code == 403


def test_an_account_with_no_password_sets_one_with_current_blank(app_client, people):
    registry._mutate(lambda d: d["users"][people[0]].__setitem__("password", None))
    tok = sessions.issue(people[0])
    assert app_client.post("/auth/password", json={"current": "x", "new": "x" * 9},
                           headers=_h(tok)).status_code == 403
    r = app_client.post("/auth/password", json={"current": "", "new": "first-pass"}, headers=_h(tok))
    assert r.status_code == 200, r.get_json()
    assert _login(app_client, "gil", "first-pass").status_code == 200
    blank = app_client.post("/auth/password", json={"current": "", "new": "x" * 9}, headers=_h(tok))
    assert blank.status_code == 403                  # once set, blank is wrong again


def test_removing_a_user_moves_their_folder_never_deletes_it(app_client, people):
    g_ = _tok(app_client, "gil", "admin-pass")
    d_dir = pathlib.Path(registry.paths.user_dir(people[1]))
    (d_dir / "calendar.db").write_bytes(b"dana's data")
    body = app_client.delete(f"/admin/users/{people[1]}", headers=_h(g_)).get_json()
    assert pathlib.Path(body["data_moved_to"], "calendar.db").read_bytes() == b"dana's data"
    assert registry.get(people[1]) is None
    assert app_client.delete(f"/admin/users/{people[0]}", headers=_h(g_)).status_code == 400


def test_the_admin_toggles_his_view_and_his_vocabulary_share(app_client, people):
    g_ = _tok(app_client, "gil", "admin-pass")
    assert app_client.put(f"/admin/view/{people[1]}", json={"shown": True},
                          headers=_h(g_)).get_json()["shown"] is True
    app_client.put(f"/admin/vocab_share/{people[1]}", json={"on": True}, headers=_h(g_))
    assert registry.vocab_sources(people[1]) == [people[1], people[0]]


# ------------------------------------------------------------------ sharing + settings

def test_a_user_shares_their_calendar_view_or_edit(app_client, people):
    d = _tok(app_client, "dana", "dana-pass")
    assert app_client.put(f"/shares/{people[0]}", json={"level": "edit"}, headers=_h(d)).status_code == 200
    assert registry.share_level(people[1], people[0]) == "edit"
    assert app_client.put(f"/shares/{people[0]}", json={"level": "own"}, headers=_h(d)).status_code == 400
    app_client.delete(f"/shares/{people[0]}", headers=_h(d))
    assert registry.share_level(people[1], people[0]) is None


def test_settings_are_mine_to_change(app_client, people):
    d = _tok(app_client, "dana", "dana-pass")
    body = app_client.put("/users/me/settings", json={"todos_group_by_owner": True},
                          headers=_h(d)).get_json()
    assert body["settings"]["todos_group_by_owner"] is True
    assert registry.get(people[0])["settings"]["todos_group_by_owner"] is False


def test_a_voice_command_runs_as_the_speaker_even_on_the_streams_worker_thread(app_client, people, monkeypatch):
    """/voice/text runs on the request thread; /voice/stream runs the engine on
    a worker thread, which starts with no bound user unless users.thread
    carried it across."""
    from assistant import users
    import assistant.engine as eng
    seen = []

    def fake(transcript, trace=None, **kw):
        seen.append(users.current())
        return {"message": "ok", "actions": [], "refresh": "none", "parse": "rule"}
    monkeypatch.setattr(eng, "run_transcript", fake)
    d = _tok(app_client, "dana", "dana-pass")
    app_client.post("/voice/text", json={"transcript": "buy milk", "source": "test"}, headers=_h(d))
    r = app_client.post("/voice/stream", json={"transcript": "buy eggs", "source": "test"}, headers=_h(d))
    r.get_data()
    assert seen == [people[1], people[1]], seen


def test_a_sign_in_never_times_out(app_client, people, monkeypatch):
    """Gil, 2026-09-28: "have it stay logged in" — only sign-out or a
    password change ends a session."""
    import time
    tok = _tok(app_client, "dana", "dana-pass")
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 400 * 86400)   # 400 days later
    assert app_client.get("/auth/me", headers=_h(tok)).get_json()["username"] == "dana"


def test_the_admins_own_password_follows_no_rule(app_client, people):
    """Gil, 2026-10-02: "admin can change however he wants"."""
    g_ = _tok(app_client, "gil", "admin-pass")
    r = app_client.post("/auth/password", json={"current": "admin-pass", "new": "1"}, headers=_h(g_))
    assert r.status_code == 200
    r = app_client.post("/auth/password", json={"current": "1", "new": ""}, headers=_h(g_))
    assert r.status_code == 200 and not registry.has_password(people[0])
    assert _login(app_client, "gil", "").status_code == 200
    assert _login(app_client, "gil", "x").status_code == 401


def test_everyone_else_follows_the_admins_password_policy(app_client, people):
    d = _tok(app_client, "dana", "dana-pass")

    def change(cur, new):
        return app_client.post("/auth/password", json={"current": cur, "new": new}, headers=_h(d))
    assert change("dana-pass", "ab").status_code == 400                # default minimum is 3
    assert change("dana-pass", "").status_code == 400                  # empty off by default
    assert change("dana-pass", "abc").status_code == 200
    g_ = _tok(app_client, "gil", "admin-pass")
    r = app_client.put("/admin/policy", json={"password_min_length": 6, "allow_empty_password": True},
                       headers=_h(g_))
    assert r.get_json()["password_min_length"] == 6 and r.get_json()["allow_empty_password"]
    assert app_client.put("/admin/policy", json={"password_min_length": 6},
                          headers=_h(d)).status_code == 403          # only the admin sets it
    assert change("abc", "abcde").status_code == 400
    assert change("abc", "").status_code == 200
    assert _login(app_client, "dana", "").status_code == 200
    app_client.put("/admin/policy", json={"allow_empty_password": False}, headers=_h(g_))
    assert _login(app_client, "dana", "").status_code == 401           # turned off: no way in


def test_auto_sign_out_follows_the_admins_choice(app_client, people, monkeypatch):
    """Off (default): a year unused is fine. On, N days: longer than N ends it."""
    import time
    tok = _tok(app_client, "dana", "dana-pass")
    real = time.time
    g_ = _tok(app_client, "gil", "admin-pass")
    r = app_client.put("/admin/policy", json={"auto_signout_days": 7}, headers=_h(g_))
    assert r.get_json()["auto_signout_days"] == 7
    monkeypatch.setattr(time, "time", lambda: real() + 3 * 86400)
    assert app_client.get("/auth/me", headers=_h(tok)).status_code == 200      # 3 days: fine
    monkeypatch.setattr(time, "time", lambda: real() + 11 * 86400)
    assert app_client.get("/auth/me", headers=_h(tok)).status_code == 401      # 8 idle days: out
    monkeypatch.setattr(time, "time", real)
    g_ = _tok(app_client, "gil", "admin-pass")
    app_client.put("/admin/policy", json={"auto_signout_days": 0}, headers=_h(g_))
    assert registry.load()["policy"]["auto_signout_days"] is None


def test_the_admin_signs_a_person_out_everywhere(app_client, people):
    a, b = _tok(app_client, "dana", "dana-pass"), _tok(app_client, "dana", "dana-pass")
    d = _tok(app_client, "dana", "dana-pass")
    assert app_client.post(f"/admin/users/{people[1]}/signout", headers=_h(d)).status_code == 403
    g_ = _tok(app_client, "gil", "admin-pass")
    out = app_client.post(f"/admin/users/{people[1]}/signout", headers=_h(g_)).get_json()
    assert out["signed_out"] == 3
    for t in (a, b, d):
        assert app_client.get("/auth/me", headers=_h(t)).status_code == 401
    assert _login(app_client, "dana", "dana-pass").status_code == 200       # password unchanged


# ------------------------------------------------------------------ deleting your own account

def test_a_person_can_delete_their_own_account_with_their_password(app_client, people):
    """App Store 5.1.1(v): an account can be deleted in the app it lives in."""
    tok = _tok(app_client, "dana", "dana-pass")
    assert app_client.delete("/auth/me", headers=_h(tok), json={"password": "wrong"}).status_code == 401
    r = app_client.delete("/auth/me", headers=_h(tok), json={"password": "dana-pass"})
    assert r.status_code == 200 and r.get_json()["removed"] == people[1]
    assert registry.get(people[1]) is None
    assert app_client.get("/auth/me", headers=_h(tok)).status_code == 401      # signed out everywhere
    assert _login(app_client, "dana", "dana-pass").status_code == 401


def test_the_admin_cannot_delete_themself_and_nobody_without_a_session(app_client, people):
    tok = _tok(app_client, "gil", "admin-pass")
    r = app_client.delete("/auth/me", headers=_h(tok), json={"password": "admin-pass"})
    assert r.status_code == 400 and registry.get(people[0]) is not None
    assert app_client.delete("/auth/me", json={"password": "x"}).status_code == 401
