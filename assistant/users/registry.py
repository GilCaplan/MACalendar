"""`users.json` — accounts, shares, the admin's view toggles, per-user settings.

    {"version": 1,
     "policy": {"require_login": false},
     "users": {"u_3f9a12c0": {"username": "gil", "display_name": "Gil",
                              "role": "admin", "seq": 1, "color": "#f5a524",
                              "created_at": 0.0, "disabled": false,
                              "must_change_password": false,
                              "password": {<passwords.hash_password record>},
                              "settings": {...SETTINGS_DEFAULTS}}},
     "shares": [{"owner": uid, "grantee": uid, "level": "view" | "edit",
                 "created_at": 0.0}],
     "admin_view": {admin_uid: {other_uid: true}},
     "vocab_shares": {owner_uid: [grantee_uid, ...]}}

Gil's rulings (2026-09-28) it encodes: exactly one admin, who may see and edit
everything and toggles each user's calendar into his view (**off until he turns
it on**); a user shares their WHOLE calendar + to-dos per person as VIEW or
EDIT; learning is per user, and the admin decides whether his VOCABULARY is
shared and with whom (`vocab_shares`); shared to-dos sit mixed in, with a
per-user setting to group them by person instead (`todos_group_by_owner`).

`policy.require_login` lives here, not in config.yaml: it is account policy the
admin console changes, and while it is false (the default, until the phone can
log in) a process nobody has logged into acts as the admin — which is exactly
today's single-user behaviour, moved into the admin's folder.

Written atomically (tmp + replace), read through an mtime cache: `current()`
consults it on every store access.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from typing import Any

from assistant.users import passwords, paths

SETTINGS_DEFAULTS: dict[str, Any] = {
    "notify_shared": False,          # digests include what others share with me
    "todos_group_by_owner": False,   # shared to-dos mixed in (False) or grouped per person
}
LEVELS = ("view", "edit")
_USERNAME = re.compile(r"^[a-z0-9_.-]{2,32}$")
#: One per user, cycled; a user can pick another. The admin keeps the app accent.
PALETTE = ["#f5a524", "#3b82f6", "#10b981", "#ec4899", "#8b5cf6", "#ef4444",
           "#14b8a6", "#eab308", "#f97316", "#6366f1"]

_lock = threading.RLock()
_cache: dict[str, Any] = {"path": None, "mtime": None, "data": None}


def _empty() -> dict:
    return {"version": 1, "policy": {"require_login": False}, "users": {},
            "shares": [], "admin_view": {}, "vocab_shares": {}}


def _guard(path: str) -> None:
    """Under pytest, never the real registry — the calendar DB's rule."""
    if not (os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION")):
        return
    if os.path.realpath(path) == os.path.realpath(paths.DEFAULT_REGISTRY):
        raise RuntimeError(
            f"Refusing to open the real user registry ({path}) from a test. "
            "Set MACALENDAR_USERS (tests/conftest.py does).")


def exists() -> bool:
    return os.path.exists(paths.registry_path())


def load() -> dict:
    """The registry, or an empty one. Cached until the file changes."""
    path = paths.registry_path()
    _guard(path)
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return _empty()
    with _lock:
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return _cache["data"]
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return _empty()
        base = _empty()
        base.update(data)
        _cache.update(path=path, mtime=mtime, data=base)
        return base


def save(data: dict) -> None:
    path = paths.registry_path()
    _guard(path)
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        _cache.update(path=None, mtime=None, data=None)


# ------------------------------------------------------------------ reading

def implicit_user() -> "str | None":
    """Who a process nobody logged into acts as: the admin while login is not
    required, nobody otherwise — and nobody before the migration (no file)."""
    if not exists():
        return None
    data = load()
    if data.get("policy", {}).get("require_login"):
        return None
    return admin_id(data)


def admin_id(data: "dict | None" = None) -> "str | None":
    data = data or load()
    for uid, u in data["users"].items():
        if u.get("role") == "admin":
            return uid
    return None


def user_ids(include_disabled: bool = False) -> list[str]:
    return [uid for uid, u in load()["users"].items()
            if include_disabled or not u.get("disabled")]


def get(user_id: str) -> "dict | None":
    u = load()["users"].get(user_id)
    return public(user_id, u) if u else None


def public(user_id: str, u: dict) -> dict:
    """A user record with the password hash taken out."""
    out = {k: v for k, v in u.items() if k != "password"}
    out["id"] = user_id
    out["settings"] = {**SETTINGS_DEFAULTS, **u.get("settings", {})}
    return out


def by_username(username: str) -> "str | None":
    name = (username or "").strip().lower()
    for uid, u in load()["users"].items():
        if u.get("username") == name:
            return uid
    return None


def verify_login(username: str, password: str) -> "str | None":
    """The user id for a correct username + password, else None. A disabled
    account never logs in. Always runs one scrypt, so a wrong USERNAME takes
    as long as a wrong password and the timing says nothing."""
    uid = by_username(username)
    rec = load()["users"].get(uid, {}) if uid else {}
    if uid and not rec.get("password") and password == "" and password_rules(uid)[1]:
        ok = True                       # an empty password, where one is allowed
    else:
        ok = passwords.verify(password, rec.get("password") or _dummy())
    return uid if (uid and ok and not rec.get("disabled")) else None


def check_password(user_id: str, password: str) -> bool:
    """Is `password` this account's current password? For a password CHANGE,
    not a login. An account with no password set (the admin's, migrated with
    none while login is off) has an empty current password: without that the
    change dialog asked for a password that did not exist and refused every
    answer, so it could never be set."""
    rec = load()["users"].get(user_id, {})
    if not rec.get("password"):
        return (password or "") == ""
    return passwords.verify(password or "", rec["password"])


def has_password(user_id: str) -> bool:
    return bool(load()["users"].get(user_id, {}).get("password"))


_DUMMY: "dict | None" = None


def _dummy() -> dict:
    """Built on first use, not at import: `current()` imports this module on
    every process's first store access, and scrypt is not free."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = passwords.hash_password("x" * passwords.MIN_LENGTH)
    return _DUMMY


# ------------------------------------------------------------------ writing

def _mutate(fn) -> Any:
    with _lock:
        data = json.loads(json.dumps(load()))   # a private copy
        out = fn(data)
        save(data)
        return out


def create_user(username: str, password: str, display_name: str = "",
                role: str = "user", color: "str | None" = None) -> str:
    name = (username or "").strip().lower()
    if not _USERNAME.match(name):
        raise ValueError("a username is 2–32 of a–z, 0–9, _ . -")
    if role not in ("admin", "user"):
        raise ValueError(f"unknown role {role!r}")
    record = passwords.hash_password(password, min_length=0)   # the admin chose it

    def go(data):
        if any(u["username"] == name for u in data["users"].values()):
            raise ValueError(f"the username {name!r} is taken")
        if role == "admin" and admin_id(data):
            raise ValueError("there is already an admin")
        uid = "u_" + secrets.token_hex(4)
        seq = 1 + max((u.get("seq", 0) for u in data["users"].values()), default=0)
        data["users"][uid] = {
            "username": name, "display_name": display_name or name.capitalize(),
            "role": role, "seq": seq,
            "color": color or PALETTE[(seq - 1) % len(PALETTE)],
            "created_at": time.time(), "disabled": False,
            "must_change_password": False, "password": record, "settings": {}}
        return uid
    uid = _mutate(go)
    os.makedirs(paths.user_dir(uid), exist_ok=True)
    return uid


def password_rules(user_id: str) -> "tuple[int, bool]":
    """(shortest allowed, may it be empty) for a password `user_id` CHOOSES.
    The admin follows no rule (Gil, 2026-10-02: "admin can change however he
    wants"); everyone else follows the admin's policy."""
    data = load()
    if (data["users"].get(user_id) or {}).get("role") == "admin":
        return 0, True
    pol = data.get("policy", {})
    return (int(pol.get("password_min_length") or passwords.MIN_LENGTH),
            bool(pol.get("allow_empty_password")))


def set_password(user_id: str, password: str, must_change: bool = False,
                 min_length: "int | None" = None, allow_empty: "bool | None" = None) -> None:
    """Rules default to `password_rules(user_id)`; the admin setting someone
    else's passes `min_length=0, allow_empty=True`. Empty = no password."""
    rule_min, rule_empty = password_rules(user_id)
    min_length = rule_min if min_length is None else min_length
    allow_empty = rule_empty if allow_empty is None else allow_empty
    if not password:
        if not allow_empty:
            raise ValueError("a password can't be empty")
        record = None
    else:
        record = passwords.hash_password(password, min_length=min_length)

    def go(data):
        u = data["users"][user_id]
        u["password"], u["must_change_password"] = record, must_change
    _mutate(go)


def update_user(user_id: str, **fields: Any) -> None:
    allowed = {"display_name", "color", "disabled"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"not editable here: {sorted(bad)}")

    def go(data):
        u = data["users"][user_id]
        if fields.get("disabled") and u.get("role") == "admin":
            raise ValueError("the admin cannot be disabled")
        u.update(fields)
    _mutate(go)


def set_setting(user_id: str, key: str, value: Any) -> None:
    if key not in SETTINGS_DEFAULTS:
        raise ValueError(f"unknown setting {key!r}")
    _mutate(lambda data: data["users"][user_id].setdefault("settings", {}).__setitem__(key, value))


def set_policy(require_login: "bool | None" = None,
               auto_signout_days: "int | None | bool" = False,
               password_min_length: "int | None" = None,
               allow_empty_password: "bool | None" = None) -> None:
    """The admin's account policy. `auto_signout_days`: None or 0 = off (a
    sign-in lasts until someone signs it out), N = end a sign-in after N days
    unused. `False` (the default) leaves it as it is."""
    def go(data):
        pol = data.setdefault("policy", {})
        if require_login is not None:
            pol["require_login"] = bool(require_login)
        if auto_signout_days is not False:
            days = int(auto_signout_days or 0)
            if days < 0 or days > 3650:
                raise ValueError("auto sign-out is 1–3650 days, or off")
            pol["auto_signout_days"] = days or None
        if password_min_length is not None:
            n = int(password_min_length)
            if n < 1 or n > 64:
                raise ValueError("the shortest password is 1–64 characters")
            pol["password_min_length"] = n
        if allow_empty_password is not None:
            pol["allow_empty_password"] = bool(allow_empty_password)
    _mutate(go)


# ------------------------------------------------------------------ sharing

def set_share(owner: str, grantee: str, level: "str | None") -> None:
    """Share `owner`'s whole calendar + to-dos with `grantee` at `level`, or
    stop sharing (`level=None`). One row per pair; the level replaces."""
    if owner == grantee:
        raise ValueError("nobody shares with themselves")
    if level is not None and level not in LEVELS:
        raise ValueError(f"level is one of {LEVELS}")

    def go(data):
        for uid in (owner, grantee):
            if uid not in data["users"]:
                raise ValueError(f"no such user {uid!r}")
        data["shares"] = [s for s in data["shares"]
                          if not (s["owner"] == owner and s["grantee"] == grantee)]
        if level:
            data["shares"].append({"owner": owner, "grantee": grantee,
                                   "level": level, "created_at": time.time()})
    _mutate(go)


def share_level(owner: str, grantee: str) -> "str | None":
    for s in load()["shares"]:
        if s["owner"] == owner and s["grantee"] == grantee:
            return s["level"]
    return None


def shares_out(owner: str) -> list[dict]:
    return [s for s in load()["shares"] if s["owner"] == owner]


def shares_in(grantee: str) -> list[dict]:
    return [s for s in load()["shares"] if s["grantee"] == grantee]


def set_admin_view(admin: str, other: str, shown: bool) -> None:
    def go(data):
        if data["users"].get(admin, {}).get("role") != "admin":
            raise ValueError("only the admin has a view to toggle")
        data.setdefault("admin_view", {}).setdefault(admin, {})[other] = bool(shown)
    _mutate(go)


def admin_shows(admin: str, other: str) -> bool:
    """Is `other`'s calendar in the admin's views? His switch decides, both
    ways, once he has touched it. Untouched, it follows whether they share
    with him — off for everyone else (Gil, 2026-09-28: off until he turns it
    on). It used to ignore shares, so for someone ALREADY sharing with him
    the switch changed nothing he could see ("button circled isn't
    working")."""
    data = load()
    choice = data.get("admin_view", {}).get(admin, {})
    if other in choice:
        return bool(choice[other])
    return any(s.get("owner") == other and s.get("grantee") == admin
               for s in data.get("shares", []))


def set_vocab_share(owner: str, grantee: str, on: bool) -> None:
    """The admin decides whether his vocabulary is shared and with whom."""
    def go(data):
        lst = set(data.setdefault("vocab_shares", {}).get(owner, []))
        (lst.add if on else lst.discard)(grantee)
        data["vocab_shares"][owner] = sorted(lst)
    _mutate(go)


def vocab_sources(user_id: str) -> list[str]:
    """Whose vocabularies `user_id`'s speech is corrected with: their own,
    then any shared with them."""
    shared = [o for o, gs in load().get("vocab_shares", {}).items() if user_id in gs]
    return [user_id] + sorted(shared)


def remove_user(user_id: str) -> str:
    """Take a user out of the registry — shares, view toggles and vocabulary
    shares with them — and move their folder to `legacy/<uid>-<ts>`. NEVER a
    delete: a removed person's calendar is still on disk if it was a mistake.
    Returns where the folder went ("" when there was none)."""
    import shutil

    def go(data):
        u = data["users"].get(user_id)
        if u is None:
            raise ValueError(f"no such user {user_id!r}")
        if u.get("role") == "admin":
            raise ValueError("the admin cannot be removed")
        del data["users"][user_id]
        data["shares"] = [s for s in data["shares"]
                          if user_id not in (s["owner"], s["grantee"])]
        for view in data.get("admin_view", {}).values():
            view.pop(user_id, None)
        vs = data.get("vocab_shares", {})
        vs.pop(user_id, None)
        for owner in vs:
            vs[owner] = [g for g in vs[owner] if g != user_id]
    _mutate(go)
    src = paths.user_dir(user_id)
    if not os.path.isdir(src):
        return ""
    dest = os.path.join(paths.root(), "legacy", f"{user_id}-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(src, dest)
    return dest
