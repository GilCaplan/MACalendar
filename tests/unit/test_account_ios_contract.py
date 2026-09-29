"""The phone's Account screens against the server they talk to.

Gil, 2026-09-28: "not all the toggles/buttons in account tab work". On the
phone a control fails silently if its request goes to a path or method the
server doesn't have, or with a body key the route doesn't read. So:

1. every request `UsersViews.swift` makes must match a real route + method —
   a new call without a route goes red here;
2. each one, replayed with the body the Swift sends, must succeed and have
   its effect, as the admin and (for the person's own controls) as a user.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import assistant.api.server as server
from assistant import users
from assistant.users import registry, sessions

SWIFT = (pathlib.Path(__file__).resolve().parents[2]
         / "MACalendar-iOS" / "MACalendar-iOS" / "Views" / "UsersViews.swift")


def _calls():
    """(METHOD, path-with-<x>) for every literal request in the Swift."""
    src = SWIFT.read_text()
    out = set()
    norm = lambda p: re.sub(r"\\\([^)]*\)", "<x>", p)            # noqa: E731
    for m in re.finditer(r'request\("(/[^"]+)"(?:\s*,\s*method:\s*"(\w+)")?', src):
        out.add(((m.group(2) or "GET").upper(), norm(m.group(1))))
    for m in re.finditer(r'accountCall\(api,\s*"(/[^"]+)"(?:\s*,\s*method:\s*"(\w+)")?', src):
        out.add(((m.group(2) or "PUT").upper(), norm(m.group(1))))
    for m in re.finditer(r'\bput\("(/[^"]+)"', src):
        out.add(("PUT", norm(m.group(1))))
    return out


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(tmp_path / "sessions.json"))
    gil = registry.create_user("gil", "admin-pass", role="admin")
    dana = registry.create_user("dana", "dana-pass")
    users.set_process_default(None)
    app = server.create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    tok = {n: c.post("/auth/login", json={"username": n, "password": f"{n if n != 'gil' else 'admin'}-pass"}
                     ).get_json()["session_token"] for n in ("gil", "dana")}
    yield c, {"gil": gil, "dana": dana}, tok
    users.set_process_default(None)


def _h(t):
    return {"X-Session-Token": t}


def test_every_request_the_account_screens_make_has_a_route(world):
    c, _, _ = world
    app = c.application
    routes = {(m, re.sub(r"<[^>]+>", "<x>", r.rule))
              for r in app.url_map.iter_rules() for m in r.methods}
    calls = _calls()
    assert len(calls) >= 12, calls                    # the parse found the calls
    missing = sorted(c_ for c_ in calls if c_ not in routes)
    assert not missing, f"the phone calls routes the server does not have: {missing}"


def test_the_admins_controls_each_take_effect(world):
    c, u, tok = world
    g, d = tok["gil"], u["dana"]
    ok = lambda r: r.status_code < 300 or pytest.fail(r.get_data(as_text=True))  # noqa: E731
    # dashboard: require sign-in, auto sign-out on / days / off
    ok(c.put("/admin/policy", json={"require_login": True}, headers=_h(g)))
    assert registry.load()["policy"]["require_login"] is True
    ok(c.put("/admin/policy", json={"require_login": False}, headers=_h(g)))
    ok(c.put("/admin/policy", json={"auto_signout_days": 30}, headers=_h(g)))
    assert registry.load()["policy"]["auto_signout_days"] == 30
    ok(c.put("/admin/policy", json={"auto_signout_days": 0}, headers=_h(g)))
    assert registry.load()["policy"]["auto_signout_days"] is None
    # a person's page: show in mine, share my calendar, my vocabulary
    ok(c.put(f"/admin/view/{d}", json={"shown": True}, headers=_h(g)))
    assert registry.admin_shows(u["gil"], d)
    ok(c.put(f"/shares/{d}", json={"level": "edit"}, headers=_h(g)))
    assert registry.share_level(u["gil"], d) == "edit"
    ok(c.delete(f"/shares/{d}", headers=_h(g)))
    assert registry.share_level(u["gil"], d) is None
    ok(c.put(f"/admin/vocab_share/{d}", json={"on": True}, headers=_h(g)))
    assert d in c.get("/auth/me", headers=_h(g)).get_json()["vocab_shared_with"]
    # their account: reset, sign out, disable, enable
    pw = c.post(f"/admin/users/{d}/password", json={}, headers=_h(g)).get_json()["password"]
    assert registry.verify_login("dana", pw) == d
    sessions.issue(d)
    assert c.post(f"/admin/users/{d}/signout", json={}, headers=_h(g)).get_json()["signed_out"] >= 1
    ok(c.patch(f"/admin/users/{d}", json={"disabled": True}, headers=_h(g)))
    rows = {r["id"]: r for r in c.get("/admin/users", headers=_h(g)).get_json()}
    assert rows[d]["disabled"] is True and "sessions" in rows[d] and "shown_in_my_view" in rows[d]
    ok(c.patch(f"/admin/users/{d}", json={"disabled": False}, headers=_h(g)))
    # add a person
    r = c.post("/admin/users", json={"username": "noa"}, headers=_h(g))
    assert r.status_code == 201 and len(r.get_json()["password"]) >= 8


def test_a_users_own_controls_take_effect_and_admin_ones_are_refused(world):
    c, u, tok = world
    t = tok["dana"]
    assert c.put(f"/shares/{u['gil']}", json={"level": "view"}, headers=_h(t)).status_code == 200
    assert registry.share_level(u["dana"], u["gil"]) == "view"
    assert c.put("/users/me/settings", json={"todos_group_by_owner": True},
                 headers=_h(t)).status_code == 200
    assert registry.get(u["dana"])["settings"]["todos_group_by_owner"] is True
    me = c.get("/auth/me", headers=_h(t)).get_json()
    assert me["shares_out"] and "settings" in me
    others = c.get("/users", headers=_h(t)).get_json()
    assert {o["username"] for o in others} >= {"gil", "dana"}
    for method, path in (("PUT", "/admin/policy"), ("PUT", f"/admin/view/{u['gil']}"),
                         ("POST", f"/admin/users/{u['gil']}/signout")):
        assert c.open(path, method=method, json={}, headers=_h(t)).status_code == 403


def test_tasks_follows_the_grouping_switch_without_reappearing():
    """The phone's tabs are layers kept alive, so Tasks' onAppear runs once:
    a grouping read there went stale the moment Account changed it (Gil,
    2026-09-28: switching it off changed nothing). It lives in UserSession,
    which Account writes and Tasks observes."""
    root = SWIFT.parents[1]
    tasks = (root / "Features" / "Tasks" / "TasksView.swift").read_text()
    session = (root / "API" / "UserSession.swift").read_text()
    assert "@Published var groupSharedTodos" in session
    assert "session.groupSharedTodos" in tasks
    assert not re.search(r"@State private var groupByOwner", tasks)
    assert "session.groupSharedTodos = v" in SWIFT.read_text()
