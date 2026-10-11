"""What Ranker remembers between uses: the recipes, the number list, the last table.

One JSON file per user (`ranker.json`, override `MACALENDAR_RANKER`, resolved
through `users.paths.resolve`). Small on purpose — the last table is kept so
changing a recipe re-ranks without sending the file again (the phone picks a
file once, then tunes).

The number list is the picture's answer as the person EDITED it: an empty list
means "no filter", which is how the filter is switched off.
"""

from __future__ import annotations

import copy
import json
import os
import threading

from assistant.features.ranker.rank import MIGRATION

DEFAULT_PATH = os.path.expanduser("~/.assistant_tools/ranker.json")
_lock = threading.Lock()


def store_path() -> str:
    from assistant.users import paths
    return paths.resolve(os.environ.get("MACALENDAR_RANKER") or DEFAULT_PATH)


def _blank() -> dict:
    return {"presets": {MIGRATION["name"]: copy.deepcopy(MIGRATION)},
            "preset": MIGRATION["name"], "numbers": [], "last_table": None}


def load() -> dict:
    try:
        with open(store_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _blank()
    base = _blank()
    base.update({k: v for k, v in data.items() if k in base})
    if not base["presets"]:
        base["presets"] = _blank()["presets"]
    return base


def save(data: dict) -> None:
    path = store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)


def update(**fields) -> dict:
    data = load()
    data.update(fields)
    save(data)
    return data
