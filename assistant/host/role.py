"""This machine's role: the PRIMARY (the brain) or a MODEL HELPER (DEVQA Q70).

A per-machine fact, not a setting that travels with the checkout, so it lives
beside the other per-machine state: ``~/.assistant_tools/host.json``
(``MACALENDAR_HOST_STATE`` redirects it; ``tests/conftest.py`` does).
The installer sets it (``python -m assistant.host --role helper``); the
menu-bar app switches it.
"""

from __future__ import annotations

import json
import os
import pathlib

PRIMARY = "primary"
HELPER = "helper"
ROLES = (PRIMARY, HELPER)

PATH = pathlib.Path(os.environ.get("MACALENDAR_HOST_STATE")
                    or (pathlib.Path.home() / ".assistant_tools" / "host.json"))


def _read() -> dict:
    try:
        data = json.loads(PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get() -> str:
    role = _read().get("role")
    return role if role in ROLES else PRIMARY


def set(role: str) -> None:                     # noqa: A001 — the module's verb
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    data = _read()
    data["role"] = role
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2))


#: Where this machine's Mac apps live: the installer's question (DEVQA Q71).
DEFAULT_APPS_DIR = "/Applications/MACalendar APPs"


def recall(key: str, default=None):
    """Another per-machine fact the installer recorded (e.g. ``apps_dir``)."""
    return _read().get(key, default)


def remember(key: str, value) -> None:
    data = _read()
    data[key] = value
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2))


def apps_dir() -> pathlib.Path:
    return pathlib.Path(recall("apps_dir") or DEFAULT_APPS_DIR)
