"""HTTP for users: log in and out, my account, sharing, and the admin's console.

Registered with ONE line in `server.py`, like every surface that ships its own
routes (CLAUDE.md "a surface owns a FOLDER … ships its own ROUTES"). HTTP
plumbing only: no parsing, no execution — the brain is never reachable here.

Who is asking is `users.current()`, bound per request by `bind_request_user`
(below, installed by `register`). While `policy.require_login` is false a
request with no token acts as the admin — today's single-user behaviour — but
the ADMIN routes and a password change always want a real login: nobody
should be able to reset passwords just by reaching the port.

    POST /auth/login          {username, password, source?, device_id?, label?}
    POST /auth/logout
    GET  /auth/me
    POST /auth/password       {current, new}
    GET  /users
    PUT  /users/me/settings   {notify_shared?, todos_group_by_owner?, color?}
    PUT  /shares/<grantee>    {level: view|edit}      DELETE /shares/<grantee>
    GET  /admin/users         POST /admin/users {username, display_name?, password?}
    PATCH /admin/users/<id>   {display_name?, color?, disabled?}
    DELETE /admin/users/<id>
    POST /admin/users/<id>/password                  → {password} shown ONCE
    PUT  /admin/view/<id>     {shown}
    PUT  /admin/vocab_share/<id> {on}
    PUT  /admin/policy        {require_login?, auto_signout_days?}
    POST /admin/users/<id>/signout                    → sign them out everywhere
"""
from __future__ import annotations

import threading
import time

from flask import Blueprint, g, jsonify, request

from assistant import users
from assistant.users import passwords, registry, sessions

bp = Blueprint("users", __name__)

#: Paths that work with no session at all, whatever the policy.
OPEN_PATHS = frozenset({"/health", "/auth/login", "/devices/enroll"})

# -- login rate limit: 5 failures per (username, address) → 30 s pause ------
_FAIL_LIMIT, _FAIL_WINDOW_S, _LOCK_S = 5, 300, 30
_fails: dict = {}
_fails_lock = threading.Lock()


def _err(msg: str, code: int):
    return jsonify({"error": msg, "code": code}), code


def _token_from_request() -> str:
    tok = request.headers.get("X-Session-Token", "")
    if tok:
        return tok.strip()
    if request.mimetype == "multipart/form-data":
        return (request.form.get("session_token") or "").strip()
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return str(body.get("session_token") or "").strip()
    return ""


def bind_request_user():
    """before_request: bind the session's user for this request.

    A token that does not resolve is always a 401 — the client should log in
    again, not silently become someone else. No token: fine while login is
    not required (the request acts as the admin, as today); a 401 once it is.
    """
    g.users_session = None
    g.users_ctx_token = None
    tok = _token_from_request()
    if tok:
        rec = sessions.resolve(tok)
        if rec is None:
            return _err("login required", 401)
        g.users_session = dict(rec, token=tok)
        g.users_ctx_token = users._current.set(rec["user_id"])
        return None
    if request.path in OPEN_PATHS or request.method == "OPTIONS":
        return None
    if registry.exists() and registry.load().get("policy", {}).get("require_login"):
        return _err("login required", 401)
    return None


def unbind_request_user(_exc=None):
    """teardown_request. Idempotent: a STREAMED response (/voice/stream) tears
    the request down twice, and a ContextVar token resets only once."""
    from assistant.users import sharing
    sharing.release_request()           # an owner bound by a by-id route, first
    tok = getattr(g, "users_ctx_token", None)
    if tok is None:
        return
    g.users_ctx_token = None
    try:
        users._current.reset(tok)
    except (ValueError, RuntimeError):   # another context, or already reset
        users._current.set(None)


def _me() -> "str | None":
    return users.current()


def _need_session():
    """The logged-in user's id, or an error response. For routes that must not
    run on the implicit admin (password changes, the admin console)."""
    s = getattr(g, "users_session", None)
    if not s:
        return None, _err("log in first", 401)
    return s["user_id"], None


def _need_admin():
    uid, err = _need_session()
    if err:
        return None, err
    if (registry.get(uid) or {}).get("role") != "admin":
        return None, _err("admins only", 403)
    return uid, None


def _body() -> dict:
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


# ------------------------------------------------------------------ auth

@bp.post("/auth/login")
def login():
    b = _body()
    name = str(b.get("username") or "").strip().lower()
    key = (name, request.remote_addr or "?")
    now = time.time()
    with _fails_lock:
        hist = [t for t in _fails.get(key, []) if now - t < _FAIL_WINDOW_S]
        _fails[key] = hist
        if len(hist) >= _FAIL_LIMIT and now - hist[-1] < _LOCK_S:
            return _err("too many tries — wait half a minute", 429)
    uid = registry.verify_login(name, str(b.get("password") or ""))
    if uid is None:
        with _fails_lock:
            _fails.setdefault(key, []).append(now)
        return _err("wrong username or password", 401)
    with _fails_lock:
        _fails.pop(key, None)
    source = str(b.get("source") or "").strip().lower()
    token = sessions.issue(uid, device_id=str(b.get("device_id") or "")[:64],
                           source=source if source in ("mac", "ios", "test") else "",
                           label=str(b.get("label") or "")[:64])
    return jsonify({"session_token": token, "user": registry.get(uid)})


@bp.post("/auth/logout")
def logout():
    s = getattr(g, "users_session", None)
    if s:
        sessions.revoke(s["token"])
    return jsonify({"ok": True})


@bp.get("/auth/me")
def me():
    uid = _me()
    if not uid:
        return _err("no users yet", 404)
    out = registry.get(uid)
    out["shares_out"] = registry.shares_out(uid)
    out["shares_in"] = registry.shares_in(uid)
    out["logged_in"] = bool(getattr(g, "users_session", None))
    if out.get("role") == "admin":
        out["vocab_shared_with"] = registry.load().get("vocab_shares", {}).get(uid, [])
        out["policy"] = registry.load().get("policy", {})
    return jsonify(out)


@bp.post("/auth/password")
def change_password():
    uid, err = _need_session()
    if err:
        return err
    b = _body()
    if not registry.verify_login((registry.get(uid) or {}).get("username", ""),
                                 str(b.get("current") or "")):
        return _err("the current password is wrong", 403)
    try:
        registry.set_password(uid, str(b.get("new") or ""))
    except ValueError as e:
        return _err(str(e), 400)
    sessions.revoke_user(uid, keep=g.users_session["token"])
    return jsonify({"ok": True})


# ------------------------------------------------------------------ me

@bp.get("/users")
def list_users():
    """Everyone's name and colour — a user needs the list to pick who to share
    with. No passwords, no settings."""
    if not _me():
        return jsonify([])
    return jsonify([{k: u[k] for k in ("id", "username", "display_name", "color", "role")}
                    for u in (registry.get(i) for i in registry.user_ids())])


@bp.put("/users/me/settings")
def my_settings():
    uid = _me()
    if not uid:
        return _err("no users yet", 404)
    b = _body()
    try:
        for k in registry.SETTINGS_DEFAULTS:
            if k in b:
                registry.set_setting(uid, k, bool(b[k]))
        if "color" in b:
            registry.update_user(uid, color=str(b["color"])[:16])
    except ValueError as e:
        return _err(str(e), 400)
    return jsonify(registry.get(uid))


@bp.put("/shares/<grantee>")
def share(grantee):
    uid = _me()
    if not uid:
        return _err("no users yet", 404)
    level = str(_body().get("level") or "")
    try:
        registry.set_share(uid, grantee, level)
    except ValueError as e:
        return _err(str(e), 400)
    return jsonify({"owner": uid, "grantee": grantee, "level": level})


@bp.delete("/shares/<grantee>")
def unshare(grantee):
    uid = _me()
    if not uid:
        return _err("no users yet", 404)
    try:
        registry.set_share(uid, grantee, None)
    except ValueError as e:
        return _err(str(e), 400)
    return jsonify({"owner": uid, "grantee": grantee, "level": None})


# ------------------------------------------------------------------ admin

@bp.get("/admin/users")
def admin_users():
    admin, err = _need_admin()
    if err:
        return err
    out = []
    for uid in registry.user_ids(include_disabled=True):
        u = registry.get(uid)
        ss = sessions.list_for(uid)
        u["sessions"] = len(ss)
        u["last_seen"] = max((s["last_seen"] for s in ss), default=None)
        u["devices"] = sorted({s["device_id"] for s in ss if s.get("device_id")})
        u["shown_in_my_view"] = uid == admin or registry.admin_shows(admin, uid)
        out.append(u)
    return jsonify(out)


@bp.post("/admin/users")
def admin_create():
    _, err = _need_admin()
    if err:
        return err
    b = _body()
    pw = str(b.get("password") or "") or passwords.generate()
    try:
        uid = registry.create_user(str(b.get("username") or ""), pw,
                                   display_name=str(b.get("display_name") or ""))
    except ValueError as e:
        return _err(str(e), 400)
    registry.set_password(uid, pw, must_change=not b.get("password"))
    out = registry.get(uid)
    out["password"] = pw            # shown ONCE; never stored readably
    return jsonify(out), 201


@bp.patch("/admin/users/<uid>")
def admin_update(uid):
    _, err = _need_admin()
    if err:
        return err
    b = _body()
    fields = {k: b[k] for k in ("display_name", "color", "disabled") if k in b}
    try:
        registry.update_user(uid, **fields)
    except (ValueError, KeyError) as e:
        return _err(str(e), 400)
    if fields.get("disabled"):
        sessions.revoke_user(uid)
    return jsonify(registry.get(uid))


@bp.delete("/admin/users/<uid>")
def admin_remove(uid):
    _, err = _need_admin()
    if err:
        return err
    try:
        moved = registry.remove_user(uid)
    except ValueError as e:
        return _err(str(e), 400)
    sessions.revoke_user(uid)
    return jsonify({"removed": uid, "data_moved_to": moved})


@bp.post("/admin/users/<uid>/password")
def admin_reset_password(uid):
    admin, err = _need_admin()
    if err:
        return err
    if registry.get(uid) is None:
        return _err("no such user", 404)
    pw = passwords.generate()
    registry.set_password(uid, pw, must_change=True)
    sessions.revoke_user(uid, keep=g.users_session["token"] if uid == admin else None)
    return jsonify({"id": uid, "password": pw})


@bp.put("/admin/view/<uid>")
def admin_view(uid):
    admin, err = _need_admin()
    if err:
        return err
    try:
        registry.set_admin_view(admin, uid, bool(_body().get("shown")))
    except ValueError as e:
        return _err(str(e), 400)
    return jsonify({"id": uid, "shown": registry.admin_shows(admin, uid)})


@bp.put("/admin/vocab_share/<uid>")
def admin_vocab_share(uid):
    admin, err = _need_admin()
    if err:
        return err
    if registry.get(uid) is None:
        return _err("no such user", 404)
    registry.set_vocab_share(admin, uid, bool(_body().get("on")))
    return jsonify({"shared_with": registry.load()["vocab_shares"].get(admin, [])})


@bp.put("/admin/policy")
def admin_policy():
    """{require_login?, auto_signout_days?: null|0 (off) | N days}"""
    _, err = _need_admin()
    if err:
        return err
    b = _body()
    try:
        registry.set_policy(
            require_login=bool(b["require_login"]) if "require_login" in b else None,
            auto_signout_days=b["auto_signout_days"] if "auto_signout_days" in b else False)
    except (ValueError, TypeError) as e:
        return _err(str(e), 400)
    return jsonify(registry.load().get("policy", {}))


@bp.post("/admin/users/<uid>/signout")
def admin_sign_out(uid):
    """Sign a person out everywhere — the admin's half of "only manual logout
    or admin logs out". Their password is unchanged."""
    admin, err = _need_admin()
    if err:
        return err
    if registry.get(uid) is None:
        return _err("no such user", 404)
    keep = g.users_session["token"] if uid == admin else None
    return jsonify({"id": uid, "signed_out": sessions.revoke_user(uid, keep=keep)})


def register(app) -> None:
    """The one line `server.py` calls: routes, plus the per-request binding —
    installed AFTER the API-key check, so a wrong key still fails first."""
    from assistant.users import sharing
    app.before_request(bind_request_user)
    app.teardown_request(unbind_request_user)
    app.register_error_handler(sharing.NotFound, lambda e: _err("not found", 404))
    app.register_error_handler(sharing.Forbidden, lambda e: _err(str(e), 403))
    app.register_blueprint(bp)
