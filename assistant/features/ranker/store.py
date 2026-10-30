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

HISTORY (Gil, 2026-10-12: "make it easy to archive, delete history"): every
search that is finished — a New search, or a different table replacing the
one on screen — is kept in `history`, newest first: its table, numbers, the
filter switch and the ranking it used, under an id (`uuid4().hex`; the phone
mints its own). An entry can be reopened (`history_open`), archived out of the
list and back, or deleted; a deleted id is remembered in `deleted_history` so a
device that still has it drops it instead of sending it back. Reopening an
entry and moving on UPDATES that entry rather than filing a copy
(`from_history`).
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid

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
            "last_table": None, "table_at": 0.0,
            "history": [], "deleted_history": [], "from_history": None}


#: How many deleted ids are remembered — enough to outlast any phone's queue.
DELETED_KEPT = 500


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


def _same_table(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return a == b
    return (a.get("filename"), a.get("columns"), a.get("rows")) == (b.get("filename"), b.get("columns"), b.get("rows"))


def snapshot(data: dict) -> dict | None:
    """File the search on screen in `data["history"]` (in place) and return its
    entry; None when there is no table. A search reopened from history updates
    its own entry instead of filing a copy."""
    last = data.get("last_table")
    if not last or not last.get("rows"):
        return None
    hist = data.setdefault("history", [])
    now = time.time()
    fields = {"filename": last.get("filename") or "table",
              "table": {"columns": last.get("columns", []), "rows": last.get("rows", [])},
              "numbers": list(data.get("numbers") or []),
              "use_numbers": bool(data.get("use_numbers", True)),
              "preset": data.get("preset") or "", "saved_at": now}
    fid = data.get("from_history")
    for e in hist:
        if e["id"] == fid:
            e.update(fields)
            hist.remove(e)
            hist.insert(0, e)
            return e
    entry = {"id": uuid.uuid4().hex, "name": fields["filename"], "archived": False, **fields}
    hist.insert(0, entry)
    return entry


def update(*, archive: bool = True, **fields) -> dict:
    """Change what Ranker remembers. A table replacing a DIFFERENT one files
    the old search in history first (`archive=False` for a device that files
    its own — the phone sends its entry separately)."""
    if "last_table" in fields and "table_at" not in fields:
        fields["table_at"] = time.time()
    data = load()
    if "last_table" in fields and not _same_table(data.get("last_table"), fields["last_table"]):
        if archive:
            snapshot(data)
        fields.setdefault("from_history", None)
    data.update(fields)
    save(data)
    return data


def new_search() -> dict:
    """Forget the table and the numbers (the search goes to history); keep the
    saved recipes."""
    return update(numbers=[], use_numbers=True, last_table=None)


# ---------------------------------------------------------------- history

def summary(entry: dict) -> dict:
    """An entry without its rows — what a list shows."""
    t = entry.get("table") or {}
    return {k: v for k, v in entry.items() if k != "table"} | {
        "rows": len(t.get("rows") or []), "columns": len(t.get("columns") or [])}


def history_get(data: dict, hid: str) -> dict | None:
    return next((e for e in data.get("history", []) if e["id"] == hid), None)


def history_put(entry: dict) -> tuple[dict, bool]:
    """Add or replace an entry sent whole (the phone's). Returns (data, kept);
    an id deleted here is not brought back."""
    data = load()
    if entry["id"] in data.get("deleted_history", []):
        return data, False
    hist = [e for e in data.get("history", []) if e["id"] != entry["id"]]
    hist.append(entry)
    hist.sort(key=lambda e: -float(e.get("saved_at") or 0))
    data["history"] = hist
    save(data)
    return data, True


def history_set(hid: str, **fields) -> dict | None:
    """Archive / unarchive / rename one entry. None when there is no such entry."""
    data = load()
    e = history_get(data, hid)
    if e is None:
        return None
    e.update({k: v for k, v in fields.items() if k in ("archived", "name")})
    save(data)
    return data


def history_delete(hid: str) -> dict:
    """Forget an entry for good, and remember that it was deleted. Deleting one
    already gone is not an error: a queued delete may land twice."""
    data = load()
    data["history"] = [e for e in data.get("history", []) if e["id"] != hid]
    gone = [d for d in data.get("deleted_history", []) if d != hid] + [hid]
    data["deleted_history"] = gone[-DELETED_KEPT:]
    if data.get("from_history") == hid:
        data["from_history"] = None
    save(data)
    return data


def history_open(hid: str) -> dict | None:
    """Make an entry the search on screen; the one there goes to history first."""
    data = load()
    e = history_get(data, hid)
    if e is None:
        return None
    if data.get("from_history") != hid:
        snapshot(data)
    data.update(last_table={"filename": e.get("filename"), **(e.get("table") or {})},
                numbers=list(e.get("numbers") or []), use_numbers=bool(e.get("use_numbers", True)),
                table_at=time.time(), from_history=hid)
    if e.get("preset") in data["presets"]:
        data["preset"] = e["preset"]
    save(data)
    return data
