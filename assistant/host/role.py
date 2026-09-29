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
