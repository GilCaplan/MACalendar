"""Ranker's HTTP surface: `/ranker*`.

| route | what |
|---|---|
| `GET /ranker` | recipes, the current one, the saved number list, the last table's columns |
| `POST /ranker/numbers` | pictures (multipart `image`, repeatable) -> their unique numbers, saved as the list |
| `PUT /ranker/numbers` | `{numbers: [...]}` — the list as edited; `[]` switches the filter off |
| `POST /ranker/rank` | rank: multipart `table` (.html/.csv/.tsv/.json) and/or `image`s, plus `recipe` (JSON) or `preset`, `numbers`; any of them left out uses the saved one |
| `PUT /ranker/presets/<name>` `DELETE /ranker/presets/<name>` | save / remove a recipe |

HTTP only. Reading tables is `table.py`, choosing numbers `ocr.py`, ranking
`rank.py` — the Mac panel calls those directly, the phone through here.
"""

from __future__ import annotations

import json

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
            "numbers": data["numbers"], "engine": ocr.engine(),
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


@blueprint.put("/ranker/numbers")
def set_numbers():
    raw = (request.get_json(silent=True) or {}).get("numbers")
    if not isinstance(raw, list):
        return _bad("Send {numbers: [...]}; an empty list switches the filter off.")
    try:
        nums = [int(str(n).strip().lstrip("#")) for n in raw if str(n).strip()]
    except ValueError:
        return _bad("Every entry in numbers must be a whole number.")
    store.update(numbers=nums)
    return jsonify({"numbers": nums})


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
        data["last_table"] = {"filename": f.filename, **t.to_json()}
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

    recipe = get("recipe")
    if recipe:
        recipe = json.loads(recipe) if isinstance(recipe, str) else recipe
    else:
        name = get("preset") or data["preset"]
        if name not in data["presets"]:
            return _bad(f"No saved recipe called {name!r}.")
        recipe = data["presets"][name]
        data["preset"] = name
    result = ranking.rank(t, recipe, data["numbers"])
    store.save(data)
    result["numbers"] = data["numbers"]
    result["table_columns"] = [{"name": n, "label": l} for n, l in t.columns]
    result["recipe"] = recipe
    return jsonify(result)


@blueprint.put("/ranker/presets/<name>")
def save_preset(name: str):
    recipe = request.get_json(silent=True) or {}
    if not recipe.get("criteria"):
        return _bad("A recipe needs at least one thing to rank by.")
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
