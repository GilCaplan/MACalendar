"""What Ranker remembers between uses: the recipes, the number list, the last table.

One JSON file per user (`ranker.json`, override `MACALENDAR_RANKER`, resolved
through `users.paths.resolve`). Small on purpose — the last table is kept so
changing a recipe re-ranks without sending the file again (the phone picks a
file once, then tunes).

The number list is the picture's answer as the person EDITED it: an empty list
means "no filter", which is how the filter is switched off. `use_numbers` is
the Mac panel's on/off switch: off ranks as if the list were empty but keeps
it, so switching back on restores it.

`table_at` is when the last table was set or cleared (seconds since the
epoch), so the phone — which reads tables itself and syncs them here — can
tell whose table is newer, and a queued write replayed late cannot replace a
table chosen after it.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time


DEFAULT_PATH = os.path.expanduser("~/.assistant_tools/ranker.json")
_lock = threading.Lock()


def store_path() -> str:
    from assistant.users import paths
    return paths.resolve(os.environ.get("MACALENDAR_RANKER") or DEFAULT_PATH)


#: What a first use starts with: nothing to rank by yet, the table's own
#: columns to pick from. (It used to start on the migration recipe, which tied
#: every new table to one example.)
BLANK_RECIPE = {"name": "My ranking", "key": "", "derived": [], "filters": [], "criteria": [], "show": []}


def _blank() -> dict:
    return {"presets": {BLANK_RECIPE["name"]: copy.deepcopy(BLANK_RECIPE)},
            "preset": BLANK_RECIPE["name"], "numbers": [], "use_numbers": True,
            "last_table": None, "table_at": 0.0}


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
    if "last_table" in fields and "table_at" not in fields:
        fields["table_at"] = time.time()
    data = load()
    data.update(fields)
    save(data)
    return data


def new_search() -> dict:
    """Forget the table and the numbers; keep the saved recipes."""
    return update(numbers=[], use_numbers=True, last_table=None)
