"""Which helpers the primary uses, and in what order.

    {"order": ["local", "h-1a2b3c4d", …],
     "helpers": {"h-1a2b3c4d": {"name", "os", "urls": [...], "token", "added_at"}}}

The token is a credential for somebody else's machine, so the file is written
0600. ``MACALENDAR_MODEL_HOSTS`` redirects it, like every store here, and
``tests/conftest.py`` points it at scratch.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
import uuid

PATH = pathlib.Path(os.environ.get("MACALENDAR_MODEL_HOSTS")
                    or (pathlib.Path.home() / ".assistant_tools" / "model_hosts.json"))
LOCAL = "local"

_lock = threading.Lock()


def _empty() -> dict:
    return {"order": [LOCAL], "helpers": {}}


def load() -> dict:
    try:
        data = json.loads(PATH.read_text())
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    helpers = {k: v for k, v in (data.get("helpers") or {}).items() if isinstance(v, dict)}
    order = [h for h in (data.get("order") or []) if h == LOCAL or h in helpers]
    if LOCAL not in order:
        order.append(LOCAL)
    order += [h for h in helpers if h not in order]
    return {"order": order, "helpers": helpers}


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PATH)


def add(name: str, os_name: str, urls: list[str], token: str) -> str:
    """Store a helper and put it FIRST: a machine is added because it is the
    better place for the model. The person reorders from there."""
    with _lock:
        data = load()
        # One entry per machine: re-adding the same helper replaces it.
        for hid, h in list(data["helpers"].items()):
            if set(h.get("urls", [])) & set(urls):
                del data["helpers"][hid]
                data["order"].remove(hid)
        hid = "h-" + uuid.uuid4().hex[:8]
        data["helpers"][hid] = {"name": name, "os": os_name, "urls": list(urls),
                                "token": token, "added_at": time.time()}
        data["order"].insert(0, hid)
        _save(data)
        return hid


def remove(hid: str) -> dict | None:
    with _lock:
        data = load()
        gone = data["helpers"].pop(hid, None)
        if gone is not None:
            data["order"].remove(hid)
            _save(data)
        return gone


def set_order(order: list[str]) -> bool:
    """Accept only a reordering of what exists — nothing added, nothing lost."""
    with _lock:
        data = load()
        if sorted(order) != sorted(data["order"]):
            return False
        data["order"] = list(order)
        _save(data)
        return True
