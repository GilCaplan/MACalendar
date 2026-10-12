"""Ranker's HTTP surface: `/ranker*`.

| route | what |
|---|---|
| `GET /ranker` | recipes, the current one, the saved number list, the last table's columns |
| `POST /ranker/numbers` | pictures (multipart `image`, repeatable) -> their unique numbers, saved as the list |
| `POST /ranker/new` | start a new search: forget the table and the numbers, keep recipes |
| `PUT /ranker/numbers` | `{numbers: [...], use_numbers?}` — the list as edited, and the filter switch |
| `GET /ranker/table` | the last table, every row (the phone syncs it) |
| `PUT /ranker/table` | `{table: {filename, columns, rows} or null, table_at}` — a table the phone read; older than the one kept, it is ignored |
| `POST /ranker/rank` | rank: multipart `table` (.html/.csv/.tsv/.json) and/or `image`s, plus `recipe` (JSON) or `preset`, `numbers`, `use_numbers` (the filter switch); any of them left out uses the saved one |
| `PUT /ranker/presets/<name>` `DELETE /ranker/presets/<name>` | save / remove a recipe |
| `GET /ranker/history` | past searches, newest first, without their rows, and the ids deleted |
| `GET /ranker/history/<id>` | one past search, every row |
| `PUT /ranker/history/<id>` | a past search filed on the phone, whole; a deleted id is ignored |
| `PATCH /ranker/history/<id>` | `{archived?, name?}` |
| `DELETE /ranker/history/<id>` | forget it (remembered as deleted) |
| `POST /ranker/history/<id>/open` | make it the search on screen; the current one is filed first |

HTTP only. Reading tables is `table.py`, choosing numbers `ocr.py`, ranking
`rank.py` — the Mac panel calls those directly. The phone has its own copy of
all three (`Features/Ranker/RankerEngine.swift`) and ranks with no Mac at all
(Gil, 2026-10-12: "Ranking shouldnt be dependent on the os server… just
sync"); it uses these routes to keep the recipes, the number list and the last
table the same on both.
"""

from __future__ import annotations

import json
import time

from flask import Blueprint, jsonify, request

from assistant.features.ranker import ocr, rank as ranking, store, table

blueprint = Blueprint("ranker", __name__)


def _bad(msg: str, code: int = 400):
    return jsonify({"error": msg, "code": code}), code


@blueprint.errorhandler(table.TableError)
@blueprint.errorhandler(ranking.RecipeError)
@blueprint.errorhandler(ocr.OCRError)
def _refused(e):
    return _bad(str(e))


def _summary(data: dict) -> dict:
    last = data.get("last_table") or {}
    return {"presets": list(data["presets"].values()), "preset": data["preset"],
            "numbers": data["numbers"], "use_numbers": data.get("use_numbers", True),
            "engine": ocr.engine(),
            "table_at": data.get("table_at", 0.0),
            "table": {"filename": last.get("filename"), "rows": len(last.get("rows", [])),
                      "columns": last.get("columns", [])} if last else None}


@blueprint.get("/ranker")
def overview():
    return jsonify(_summary(store.load()))


@blueprint.post("/ranker/numbers")
def numbers_from_pictures():
    """Read the numbers in one or more pictures and keep them as the list."""
    images = [(f.filename or "image.png", f.read()) for f in request.files.getlist("image")]
    if not images:
        return _bad("Send the picture as multipart field 'image'.")
    found = ocr.numbers_from_images(images)
    store.update(numbers=found)
    return jsonify({"numbers": found})


@blueprint.post("/ranker/new")
def new_search():
    """Start over: no table, no numbers. Saved recipes stay."""
    return jsonify(_summary(store.new_search()))


@blueprint.put("/ranker/numbers")
def set_numbers():
    """The number list as edited, and (optionally) the filter switch."""
    body = request.get_json(silent=True) or {}
    raw = body.get("numbers")
    if not isinstance(raw, list):
        return _bad("Send {numbers: [...]}; an empty list switches the filter off.")
    try:
        nums = [int(str(n).strip().lstrip("#")) for n in raw if str(n).strip()]
    except ValueError:
        return _bad("Every entry in numbers must be a whole number.")
    fields = {"numbers": nums}
    if isinstance(body.get("use_numbers"), bool):
        fields["use_numbers"] = body["use_numbers"]
    data = store.update(**fields)
    return jsonify({"numbers": nums, "use_numbers": data.get("use_numbers", True)})


@blueprint.get("/ranker/table")
def last_table():
    """The last table with every row, for the phone to rank with."""
    data = store.load()
    return jsonify({"table": data.get("last_table"), "table_at": data.get("table_at", 0.0)})


@blueprint.put("/ranker/table")
def set_table():
    """A table the phone read (or `null`: it started a new search). Stamped
    with when the phone chose it, so a write queued offline and replayed
    after a newer table was chosen on either device changes nothing."""
    body = request.get_json(silent=True) or {}
    if "table" not in body:
        return _bad("Send {table: {filename, columns, rows} or null, table_at}.")
    t = body["table"]
    if t is not None:
        if (not isinstance(t, dict) or not isinstance(t.get("columns"), list)
                or not isinstance(t.get("rows"), list)
                or not all(isinstance(c, dict) and isinstance(c.get("name"), str) for c in t["columns"])
                or not all(isinstance(r, dict) for r in t["rows"])):
            return _bad("A table is {filename, columns: [{name, label}], rows: [{name: value}]}.")
        t = {"filename": t.get("filename"), "columns": t["columns"], "rows": t["rows"]}
    try:
        at = float(body.get("table_at") or 0)
    except (TypeError, ValueError):
        return _bad("table_at is seconds since the epoch.")
    data = store.load()
    if at and at < float(data.get("table_at") or 0):
        return jsonify({**_summary(data), "ignored": True})
    # The phone files its own history (PUT /ranker/history/<id>), so a table
    # it sends never files the Mac's copy of the same search a second time.
    fields = {"last_table": t, **({"table_at": at} if at else {})}
    if isinstance(body.get("from_history"), str) or body.get("from_history") is None:
        fields["from_history"] = body.get("from_history")
    data = store.update(archive=False, **fields)
    return jsonify(_summary(data))


@blueprint.post("/ranker/rank")
def rank_table():
    """Rank a table by a recipe, narrowed to the picture's numbers when there are any."""
    data = store.load()
    form = request.form
    body = request.get_json(silent=True) or {}
    get = lambda k: form.get(k) if k in form else body.get(k)

    f = request.files.get("table")
    if f is not None:
        t = table.read(f.filename or "table", f.read())
        new = {"filename": f.filename, **t.to_json()}
        if not store._same_table(data.get("last_table"), new):
            store.snapshot(data)
            data["from_history"] = None
        data["last_table"] = new
        data["table_at"] = time.time()
    elif data.get("last_table"):
        lt = data["last_table"]
        t = table.Table([(c["name"], c["label"]) for c in lt["columns"]], lt["rows"])
    else:
        return _bad("Send a table first (.html, .csv, .tsv or .json).")

    images = [(i.filename or "image.png", i.read()) for i in request.files.getlist("image")]
    if images:
        data["numbers"] = ocr.numbers_from_images(images)
    elif get("numbers") is not None:
        raw = get("numbers")
        raw = json.loads(raw) if isinstance(raw, str) else raw
        data["numbers"] = [int(str(n).strip().lstrip("#")) for n in raw if str(n).strip()]

    # The filter switch: off ranks every row but KEEPS the list, so turning it
    # back on restores it. Sending `numbers: []` to switch it off would erase
    # the list instead — that is what `use_numbers` is for.
    use = get("use_numbers")
    if use is not None:
        data["use_numbers"] = use if isinstance(use, bool) else str(use).lower() in ("1", "true", "yes", "on")

    recipe = get("recipe")
    if recipe:
        recipe = json.loads(recipe) if isinstance(recipe, str) else recipe
    else:
        name = get("preset") or data["preset"]
        if name not in data["presets"]:
            return _bad(f"No saved recipe called {name!r}.")
        recipe = data["presets"][name]
        data["preset"] = name
    result = ranking.rank(t, recipe, data["numbers"] if data.get("use_numbers", True) else [])
    store.save(data)
    result["numbers"] = data["numbers"]
    result["use_numbers"] = data.get("use_numbers", True)
    result["table_columns"] = [{"name": n, "label": l} for n, l in t.columns]
    result["recipe"] = recipe
    return jsonify(result)


@blueprint.put("/ranker/presets/<name>")
def save_preset(name: str):
    recipe = request.get_json(silent=True) or {}
    recipe["name"] = name
    data = store.load()
    data["presets"][name] = recipe
    data["preset"] = name
    store.save(data)
    return jsonify(_summary(data))


@blueprint.delete("/ranker/presets/<name>")
def delete_preset(name: str):
    data = store.load()
    if name not in data["presets"]:
        return _bad(f"No saved recipe called {name!r}.", 404)
    if len(data["presets"]) == 1:
        return _bad("Keep at least one recipe — edit this one instead.", 409)
    del data["presets"][name]
    if data["preset"] == name:
        data["preset"] = next(iter(data["presets"]))
    store.save(data)
    return jsonify(_summary(data))


# ---------------------------------------------------------------- history

@blueprint.get("/ranker/history")
def history():
    data = store.load()
    return jsonify({"entries": [store.summary(e) for e in data.get("history", [])],
                    "deleted": data.get("deleted_history", []),
                    "current": data.get("from_history")})


@blueprint.get("/ranker/history/<hid>")
def history_entry(hid: str):
    e = store.history_get(store.load(), hid)
    if e is None:
        return _bad("No such past search.", 404)
    return jsonify(e)


@blueprint.put("/ranker/history/<hid>")
def history_put(hid: str):
    """A past search the phone filed, sent whole. Idempotent, so it can queue."""
    e = request.get_json(silent=True) or {}
    t = e.get("table")
    if (not isinstance(t, dict) or not isinstance(t.get("columns"), list)
            or not isinstance(t.get("rows"), list)):
        return _bad("A past search carries its table: {columns, rows}.")
    try:
        nums = [int(n) for n in e.get("numbers") or []]
        saved_at = float(e.get("saved_at") or time.time())
    except (TypeError, ValueError):
        return _bad("numbers are whole numbers and saved_at is seconds since the epoch.")
    entry = {"id": hid, "name": str(e.get("name") or e.get("filename") or "table"),
             "filename": str(e.get("filename") or "table"),
             "table": {"columns": t["columns"], "rows": t["rows"]}, "numbers": nums,
             "use_numbers": bool(e.get("use_numbers", True)), "preset": str(e.get("preset") or ""),
             "saved_at": saved_at, "archived": bool(e.get("archived", False))}
    _data, kept = store.history_put(entry)
    return jsonify({"id": hid, "kept": kept})


@blueprint.patch("/ranker/history/<hid>")
def history_patch(hid: str):
    body = request.get_json(silent=True) or {}
    fields = {}
    if isinstance(body.get("archived"), bool):
        fields["archived"] = body["archived"]
    if isinstance(body.get("name"), str) and body["name"].strip():
        fields["name"] = body["name"].strip()
    if not fields:
        return _bad("Send {archived: true|false} and/or {name: \"...\"}.")
    data = store.history_set(hid, **fields)
    if data is None:
        return _bad("No such past search.", 404)
    return jsonify(store.summary(store.history_get(data, hid)))


@blueprint.delete("/ranker/history/<hid>")
def history_delete(hid: str):
    store.history_delete(hid)
    return jsonify({"id": hid, "deleted": True})


@blueprint.post("/ranker/history/<hid>/open")
def history_open(hid: str):
    data = store.history_open(hid)
    if data is None:
        return _bad("No such past search.", 404)
    return jsonify(_summary(data))
