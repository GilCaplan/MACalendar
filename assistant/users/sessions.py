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

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

#: The default when the admin has chosen nothing: a sign-in lasts until you
#: sign out, the admin signs you out, or the password changes. Gil, 2026-09-28:
#: "have it stay logged in" — then: the ADMIN chooses, off or "every x time"
#: (`registry.policy.auto_signout_days`, read by `idle_days()`).
IDLE_DAYS: int | None = None


def idle_days() -> int | None:
    """Days idle before a sign-in ends — the admin's choice, else IDLE_DAYS."""
    from assistant.users import registry
    days = registry.load().get("policy", {}).get("auto_signout_days")
    return int(days) if days else IDLE_DAYS
#: `last_seen` is written at most this often: a phone polling /changes every
#: second must not rewrite the file every second.
_TOUCH_EVERY_S = 3600

_DEFAULT = os.path.expanduser("~/.assistant_tools/sessions.json")
_lock = threading.RLock()


@contextlib.contextmanager
def _locked():
    """One writer at a time ACROSS PROCESSES, not only threads.

    The GUI, the HUD and the API all resolve sessions, and `resolve()` writes
    (it drops expired sessions and refreshes `last_seen`). With only a thread
    lock, two processes saving at once shared one `.tmp` file and left a stray
    byte at the end of `sessions.json` (2026-10-18: it ended in `}}`); the file
    then failed to parse, every token looked unknown, and every request from a
    logged-in client was a 401 — the Mac's voice commands among them."""
    with _lock:
        p = path() + ".lock"
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


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
            text = f.read()
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        # Keep the logins a damaged file still holds rather than signing
        # everyone out: take the first complete JSON object and say so.
        try:
            data, end = json.JSONDecoder().raw_decode(text.lstrip())
            log.warning("sessions.json had %d stray byte(s) after its JSON; "
                        "recovered %d session(s)", len(text.lstrip()) - end,
                        len(data) if isinstance(data, dict) else 0)
        except ValueError:
            log.error("sessions.json is unreadable; treating it as empty")
            return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    p = path()
    _guard(p)
    d = os.path.dirname(p)
    os.makedirs(d, exist_ok=True)
    # A temp file of its own: a shared `p + ".tmp"` is what two processes
    # wrote into at once (see `_locked`).
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".sessions.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def issue(user_id: str, device_id: str = "", source: str = "", label: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _locked():
        data = _load()
        data[_key(token)] = {"user_id": user_id, "device_id": device_id or "",
                             "source": source or "", "label": label or "",
                             "created_at": now, "last_seen": now}
        _save(data)
    return token


def resolve(token: str | None) -> dict | None:
    """The live session for `token`, or None. Expired sessions and those of a
    deleted or disabled user are dropped on sight."""
    if not token:
        return None
    from assistant.users import registry
    k = _key(token)
    now = time.time()
    with _locked():
        data = _load()
        rec = data.get(k)
        if rec is None:
            return None
        u = registry.load()["users"].get(rec["user_id"])
        limit = idle_days()
        expired = limit is not None and now - rec.get("last_seen", 0) > limit * 86400
        if u is None or u.get("disabled") or expired:
            del data[k]
            _save(data)
            return None
        # With auto sign-out on, `last_seen` must be fresh to the hour or a
        # day's use would not count; with it off it is only for the console.
        if now - rec.get("last_seen", 0) > _TOUCH_EVERY_S:
            rec["last_seen"] = now
            _save(data)
        return dict(rec, key=k)


def revoke(token: str) -> bool:
    with _locked():
        data = _load()
        if data.pop(_key(token), None) is None:
            return False
        _save(data)
        return True


def revoke_user(user_id: str, keep: str | None = None) -> int:
    """Sign `user_id` out everywhere — except the session `keep`, when given
    (the device that just changed its own password stays signed in)."""
    keep_k = _key(keep) if keep else None
    with _locked():
        data = _load()
        gone = [k for k, r in data.items() if r["user_id"] == user_id and k != keep_k]
        for k in gone:
            del data[k]
        if gone:
            _save(data)
        return len(gone)


def list_for(user_id: str | None = None) -> list[dict[str, Any]]:
    """Sessions (hash keys omitted), for the admin console."""
    return [{k: v for k, v in r.items()} for r in _load().values()
            if user_id is None or r["user_id"] == user_id]
