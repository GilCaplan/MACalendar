"""THIS Mac's logged-in user — `~/.assistant_tools/session.json` (0600).

The calendar window writes it on login and clears it on log-out; the HUD and
the API's Mac-banner notifier read it, so all three follow the same person.
Every HTTP request the Mac makes to the API carries the session token
(`headers()`), because the API binds its user from the token: without it,
Dana speaking at the Mac would be heard as the admin (DEVQA Q65).

    {"user_id": "u_…", "username": "dana", "display_name": "Dana",
     "session_token": "…", "saved_at": 0.0}
"""
from __future__ import annotations

import json
import os
import time

_DEFAULT = os.path.expanduser("~/.assistant_tools/session.json")


def path() -> str:
    return os.environ.get("MACALENDAR_SESSION_FILE") or _DEFAULT


def read() -> "dict | None":
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("session_token") else None
    except (OSError, ValueError):
        return None


def write(user_id: str, username: str, display_name: str, token: str) -> None:
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"user_id": user_id, "username": username,
                   "display_name": display_name, "session_token": token,
                   "saved_at": time.time()}, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def clear() -> None:
    try:
        os.remove(path())
    except OSError:
        pass


def current_user() -> "str | None":
    """The Mac's logged-in user if the session is still live, else None."""
    s = read()
    if not s:
        return None
    from assistant.users import sessions
    rec = sessions.resolve(s["session_token"])
    return rec["user_id"] if rec else None


def headers() -> dict:
    """`X-Session-Token` for a request to the API, or nothing."""
    s = read()
    return {"X-Session-Token": s["session_token"]} if s else {}


def adopt() -> "str | None":
    """Bind this process to the Mac's logged-in user (HUD, notifier, scripts
    that act for the person at the Mac). Returns who, or None."""
    from assistant import users
    uid = current_user()
    users.set_process_default(uid)
    return uid
