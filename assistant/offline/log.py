"""Every phone-vs-Mac comparison, one JSON line each, per user.

This is the offline reader's only honest instrument: how often the phone's
provisional reading turned out to be what the Mac's engine read, measured on
the commands actually given offline. `summary()` is what
`GET /offline/agreement` returns.

`MACALENDAR_OFFLINE_LOG` redirects it (tests/conftest.py scratches it): it is
a personal store like the trace bus, holding what was said.
"""
from __future__ import annotations

import json
import os
import threading
from collections import Counter

from assistant import users

OFFLINE_LOG = os.path.expanduser(
    os.environ.get("MACALENDAR_OFFLINE_LOG", "~/.assistant_tools/offline_readings.jsonl"))

_lock = threading.Lock()


def path() -> str:
    return str(users.paths.resolve(OFFLINE_LOG))


def append(row: dict) -> None:
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, sort_keys=True)
    with _lock, open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def rows() -> list[dict]:
    try:
        with open(path(), encoding="utf-8") as f:
            out = []
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue            # a torn last line costs that line only
            return out
    except FileNotFoundError:
        return []


def summary() -> dict:
    """Counts by verdict, and agreement over the rows where both sides read
    something to compare — `pending` and `deferred` have no Mac reading yet
    or no phone reading, so they are counted but not scored."""
    rs = rows()
    by = Counter(r.get("verdict", "?") for r in rs)
    scored = by["same"] + by["changed"]
    fields = Counter(f for r in rs if r.get("verdict") == "changed"
                     for f in r.get("differences", {}).get("fields", []))
    return {
        "n": len(rs),
        "by_verdict": dict(by),
        "scored": scored,
        "agreement": round(by["same"] / scored, 3) if scored else None,
        "differences": dict(fields),
        "readers": dict(Counter(f"{r.get('reader', '?')}@{r.get('spec_version', '?')}"
                                for r in rs)),
    }
