"""Login sessions: a random token per device login, stored only as its hash.

    issue(user_id, device_id, source, label) -> token     (shown to the client once)
    resolve(token) -> record | None                      (None: unknown, expired, user gone)
    revoke(token) / revoke_user(user_id, keep=token) / list_for(user_id)

Gil, 2026-09-28 (DEVQA Q65): a login lasts until logout, **90 days idle**, and
a password change or reset signs that user out everywhere (but the device that
changed it). The token is `secrets.token_urlsafe(32)`; `sessions.json` keeps
`sha256(token)` only, so a copy of the file logs nobody in.

A session is issued TO a device: `device_id` is the enrolled phone or Mac
(`model_protocol`), recorded so the admin console can say who is signed in
where. The device token still decides the command STREAM; the session decides
whose CALENDAR — two different questions (USERS_PLAN.md §C).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from typing import Any

#: None: a sign-in lasts until you sign out or the password changes. Gil,
#: 2026-09-28: "have it stay logged in" — replacing the 90-day idle expiry he
#: had first chosen (DEVQA Q65).
IDLE_DAYS: "int | None" = None
#: `last_seen` is written at most this often: a phone polling /changes every
#: second must not rewrite the file every second.
_TOUCH_EVERY_S = 3600

_DEFAULT = os.path.expanduser("~/.assistant_tools/sessions.json")
_lock = threading.RLock()


def path() -> str:
    return os.environ.get("MACALENDAR_SESSIONS") or _DEFAULT


def _guard(p: str) -> None:
    if not (os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION")):
        return
    if os.path.realpath(p) == os.path.realpath(_DEFAULT):
        raise RuntimeError("Refusing to open the real sessions file from a test. "
                           "Set MACALENDAR_SESSIONS (tests/conftest.py does).")


def _key(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def _load() -> dict:
    p = path()
    _guard(p)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    p = path()
    _guard(p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def issue(user_id: str, device_id: str = "", source: str = "", label: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        data = _load()
        data[_key(token)] = {"user_id": user_id, "device_id": device_id or "",
                             "source": source or "", "label": label or "",
                             "created_at": now, "last_seen": now}
        _save(data)
    return token


def resolve(token: "str | None") -> "dict | None":
    """The live session for `token`, or None. Expired sessions and those of a
    deleted or disabled user are dropped on sight."""
    if not token:
        return None
    from assistant.users import registry
    k = _key(token)
    now = time.time()
    with _lock:
        data = _load()
        rec = data.get(k)
        if rec is None:
            return None
        u = registry.load()["users"].get(rec["user_id"])
        expired = IDLE_DAYS is not None and now - rec.get("last_seen", 0) > IDLE_DAYS * 86400
        if u is None or u.get("disabled") or expired:
            del data[k]
            _save(data)
            return None
        if now - rec.get("last_seen", 0) > _TOUCH_EVERY_S:
            rec["last_seen"] = now
            _save(data)
        return dict(rec, key=k)


def revoke(token: str) -> bool:
    with _lock:
        data = _load()
        if data.pop(_key(token), None) is None:
            return False
        _save(data)
        return True


def revoke_user(user_id: str, keep: "str | None" = None) -> int:
    """Sign `user_id` out everywhere — except the session `keep`, when given
    (the device that just changed its own password stays signed in)."""
    keep_k = _key(keep) if keep else None
    with _lock:
        data = _load()
        gone = [k for k, r in data.items() if r["user_id"] == user_id and k != keep_k]
        for k in gone:
            del data[k]
        if gone:
            _save(data)
        return len(gone)


def list_for(user_id: "str | None" = None) -> list[dict[str, Any]]:
    """Sessions (hash keys omitted), for the admin console."""
    return [{k: v for k, v in r.items()} for r in _load().values()
            if user_id is None or r["user_id"] == user_id]
