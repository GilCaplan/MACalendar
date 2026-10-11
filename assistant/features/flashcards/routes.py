"""Flashcards' HTTP surface: `/flashcards*`.

| route | what |
|---|---|
| `GET /flashcards` | subjects → sets (with `archived`, card / due counts), and `deleted`: what was deleted, by id |
| `GET /flashcards/format` | FORMAT.md: the set-file contract, for an agent to read |
| `POST /flashcards/subjects` `PATCH/DELETE /flashcards/subjects/<id>` | subjects; PATCH takes `name` and/or `archived` |
| `POST /flashcards/sets` `GET/PATCH/DELETE /flashcards/sets/<id>` | sets; GET carries every card + progress |
| `GET /flashcards/sets/<id>/export` | the set as a set file (YAML), to edit and re-import |
| `POST /flashcards/sets/<id>/cards` `PATCH/DELETE /flashcards/cards/<id>` | one card at a time (the editors) |
| `POST /flashcards/sets/<id>/media` | upload a picture for a card |
| `GET /flashcards/media/<set id>/<path>` | a card's picture |
| `POST /flashcards/import` | a set file or .zip (multipart `file`), or JSON `{doc, mode}` |
| `POST /flashcards/inbox` | import whatever an agent dropped in the inbox folder |
| `POST /flashcards/study` | a session's queue: `{set_ids, mode, types, limit}` |
| `POST /flashcards/review` | one answer: `{card_id, item, grade, at}` |

HTTP only — every rule lives in `store.py` / `cardformat.py`, so the Mac panel
(which opens the store directly, like every Mac panel) and the phone obey the
same ones.
"""

from __future__ import annotations

import os

from flask import Blueprint, Response, jsonify, request, send_file

from assistant.features.flashcards.cardformat import CardError
from assistant.features.flashcards.store import FlashcardError, FlashcardStore

blueprint = Blueprint("flashcards", __name__)

FORMAT_MD = os.path.join(os.path.dirname(__file__), "FORMAT.md")


def _store() -> FlashcardStore:
    # Built per request: the store path resolves through the BOUND user, and
    # the API serves several.
    return FlashcardStore()


def _bad(e: Exception, code: int = 400):
    return jsonify({"error": str(e), "code": code}), code


def _body() -> dict:
    return request.get_json(silent=True) or {}


@blueprint.errorhandler(FlashcardError)
@blueprint.errorhandler(CardError)
def _handle(e):
    msg = str(e)
    return _bad(e, 404 if msg.startswith("No ") else 400)


@blueprint.get("/flashcards")
def library():
    store = _store()
    return jsonify({"subjects": store.library(), "deleted": store.deleted()})


@blueprint.get("/flashcards/format")
def card_format():
    with open(FORMAT_MD, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/markdown; charset=utf-8")


# ------------------------------------------------------------------ subjects

@blueprint.post("/flashcards/subjects")
def create_subject():
    d = _body()
    store = _store()
    sid = store.subject_id(str(d.get("name") or ""), client_token=str(d.get("client_token") or ""))
    return jsonify({"id": sid}), 201


@blueprint.patch("/flashcards/subjects/<int:sid>")
def rename_subject(sid: int):
    """Rename and/or archive: `{name}`, `{archived: true|false}`."""
    d, store = _body(), _store()
    if "archived" in d:
        store.set_archived("subject", sid, bool(d["archived"]))
    if d.get("name") is not None or "archived" not in d:
        store.rename_subject(sid, str(d.get("name") or ""))
    return jsonify({"id": sid})


@blueprint.delete("/flashcards/subjects/<int:sid>")
def delete_subject(sid: int):
    _store().delete_subject(sid)
    return jsonify({"deleted": sid})


# ------------------------------------------------------------------ sets

@blueprint.post("/flashcards/sets")
def create_set():
    d = _body()
    subject = d.get("subject_id") or d.get("subject") or ""
    set_id = _store().create_set(
        int(subject) if str(subject).isdigit() else str(subject), str(d.get("name") or ""),
        source=str(d.get("source") or ""), lang=str(d.get("lang") or ""),
        dir=str(d.get("dir") or ""), client_token=str(d.get("client_token") or ""))
    return jsonify({"id": set_id}), 201


@blueprint.get("/flashcards/sets/<int:set_id>")
def get_set(set_id: int):
    return jsonify(_store().get_set(set_id))


@blueprint.patch("/flashcards/sets/<int:set_id>")
def update_set(set_id: int):
    _store().update_set(set_id, **_body())
    return jsonify({"id": set_id})


@blueprint.delete("/flashcards/sets/<int:set_id>")
def delete_set(set_id: int):
    _store().delete_set(set_id)
    return jsonify({"deleted": set_id})


@blueprint.post("/flashcards/sets/<int:set_id>/reset")
def reset_set(set_id: int):
    _store().reset_progress(set_id)
    return jsonify({"id": set_id})


@blueprint.get("/flashcards/sets/<int:set_id>/export")
def export_set(set_id: int):
    import yaml
    doc = _store().export_doc(set_id)
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100)
    return Response(text, mimetype="text/yaml; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={doc['set_id']}.yaml"})


# ------------------------------------------------------------------ cards

@blueprint.post("/flashcards/sets/<int:set_id>/cards")
def add_card(set_id: int):
    d = _body()
    token = str(d.pop("client_token", "") or "")
    card = d.get("card", d)
    cid = _store().add_card(set_id, card, client_token=token)
    return jsonify({"id": cid}), 201


@blueprint.patch("/flashcards/cards/<int:card_id>")
def update_card(card_id: int):
    d = _body()
    _store().update_card(card_id, d.get("card", d))
    return jsonify({"id": card_id})


@blueprint.delete("/flashcards/cards/<int:card_id>")
def delete_card(card_id: int):
    _store().delete_card(card_id)
    return jsonify({"deleted": card_id})


@blueprint.post("/flashcards/sets/<int:set_id>/media")
def upload_media(set_id: int):
    f = request.files.get("file")
    if f is None:
        return _bad(ValueError("Send the picture as multipart field 'file'."))
    store = _store()
    store.get_set(set_id)
    rel = request.form.get("path") or f"images/{os.path.basename(f.filename or 'picture.png')}"
    return jsonify({"path": store.save_media(set_id, rel, f.read())}), 201


@blueprint.get("/flashcards/media/<int:set_id>/<path:rel>")
def media(set_id: int, rel: str):
    path = _store().media_path(set_id, rel)
    if not os.path.isfile(path):
        return _bad(FlashcardError(f"No picture {rel!r} in set {set_id}."), 404)
    return send_file(path, max_age=86400)


# ------------------------------------------------------------------ import

@blueprint.post("/flashcards/import")
def import_set():
    store = _store()
    f = request.files.get("file")
    if f is not None:
        mode = request.form.get("mode", "replace")
        return jsonify({"imported": store.import_file(f.filename or "set.yaml", f.read(), mode=mode)})
    d = _body()
    doc = d.get("doc")
    if doc is None and d.get("yaml"):
        from assistant.features.flashcards.store import _load
        doc = _load("set.yaml", str(d["yaml"]).encode("utf-8"))
    if doc is None:
        return _bad(ValueError("Send a multipart 'file', or JSON {doc: {...}} or {yaml: '...'}."))
    return jsonify({"imported": store.import_doc(doc, mode=str(d.get("mode") or "replace"))})


@blueprint.post("/flashcards/inbox")
def import_inbox():
    store = _store()
    return jsonify({"imported": store.import_inbox(), "inbox": store.inbox_dir})


# ------------------------------------------------------------------ study

@blueprint.post("/flashcards/study")
def study():
    d = _body()
    ids = [int(x) for x in d.get("set_ids") or []]
    return jsonify({"queue": _store().study(
        ids, mode=str(d.get("mode") or "smart"), types=d.get("types") or None,
        limit=int(d.get("limit") if d.get("limit") is not None else 20))})


@blueprint.post("/flashcards/review")
def review():
    d = _body()
    try:
        card_id, grade = int(d["card_id"]), int(d["grade"])
    except (KeyError, TypeError, ValueError):
        return _bad(ValueError("Send card_id and grade (1-4)."))
    return jsonify(_store().review(
        card_id, str(d.get("item") or ""), grade, at=d.get("at"),
        source=str(d.get("source") or ""), client_token=str(d.get("client_token") or "")))
