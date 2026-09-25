"""Tasks' HTTP surface: `/todos*` and `/tags*`.

A Flask blueprint rather than lines in `server.py`, per
`assistant/features/CONVENTION.md`: a surface owns a folder, declares itself
once to a registry, ships its own routes, and the generic layer never learns
its name.

| route | what |
|---|---|
| `GET/POST /todos` | the list, and create (idempotent on `client_token`) |
| `PATCH/DELETE /todos/<id>` | edit one; `PATCH /todos/<id>/toggle` ticks it off |
| `PUT/DELETE /todos/<id>/link` `POST /todos/<id>/event` | link it to an event (one thing), unlink it, or put it on the calendar linked |
| `POST /todos/sync` `POST /todos/reorder` `DELETE /todos/completed` | the bulk operations |
| `GET/POST /tags` `DELETE /tags/<name>` | the tag palette |
| `GET /tags/rules` | the classifier AS DATA, so the phone can tag offline |
| `GET/POST /tags/suggestion*` | mined new-tag proposals and their verdicts |

No `url_prefix`: every path above is already absolute, and a prefix would move
all of them.

`tag_rules()` is imported by `features/calendar/routes.py` for
`/sync/bootstrap`, which serves the same table rather than deriving a second
one — see the ordering note in its docstring for why that matters.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from assistant.api.server import create_todo_from_body

logger = logging.getLogger(__name__)

blueprint = Blueprint("tasks", __name__)


def get_db():
    """Resolved through `assistant.api.server` at CALL time, never bound at
    import. server.py re-exports `assistant.db.get_db`, and a test that swaps
    it there — `tests/integration/test_api_server.py`'s `app_client` fixture —
    has to reach the feature blueprints too. A blueprint holding its own early
    binding would quietly read the REAL ~/.assistant_tools/calendar.db while
    the test watched a temp one."""
    from assistant.api import server
    return server.get_db()


# ------------------------------------------------------------------
# Todos
# ------------------------------------------------------------------

@blueprint.get("/todos")
def todos_list():
    db = get_db()
    list_name = request.args.get("list")  # today | general | all | None
    include_completed = request.args.get("include_completed", "false").lower() == "true"
    tag = request.args.get("tag") or None  # tag name | "__untagged__" | None

    if list_name == "all":
        list_name = None  # get_todos(None) returns everything

    rows = db.get_todos(list_name=list_name, include_completed=include_completed, tag=tag)
    return jsonify(rows)


@blueprint.post("/todos")
def todo_create():
    """Create a task. Idempotent on `client_token` — a repeat returns 200 + the existing id."""
    # todo-create fingerprint: an unidentified localhost client has been
    # duplicating creates (34x "buy groceries"); tokened clients are now
    # idempotent, but a token-less caller still gets through - log enough
    # to name it on its next appearance.
    data = request.get_json(silent=True) or {}
    logger.info("POST /todos from %s ua=%r token=%r",
                request.remote_addr, request.headers.get("User-Agent", ""),
                data.get("client_token"))
    payload, status = create_todo_from_body(data)
    return jsonify(payload), status


@blueprint.patch("/todos/<int:todo_id>")
def todo_update(todo_id: int):
    data = request.get_json(silent=True) or {}
    db = get_db()
    todo = db.get_todo(todo_id)
    if todo is None:
        return jsonify({"error": "Todo not found", "code": 404}), 404

    # Same optimistic-concurrency check as events: a client that edited this
    # while disconnected quotes the version it worked from, and is told when
    # the task has moved on rather than overwriting the newer change.
    base = str(data.pop("base_updated_at", "") or "")
    if base and str(todo.get("updated_at") or "") not in ("", base):
        return jsonify({"error": "Task changed on the Mac since you edited it",
                        "code": 409, "current": todo}), 409

    db.update_todo(todo_id, **data)
    return jsonify({"id": todo_id})


@blueprint.patch("/todos/<int:todo_id>/toggle")
def todo_toggle(todo_id: int):
    db = get_db()
    if db.get_todo(todo_id) is None:
        return jsonify({"error": "Todo not found", "code": 404}), 404
    new_state = db.toggle_todo_complete(todo_id)
    return jsonify({"id": todo_id, "completed": int(new_state)})


@blueprint.delete("/todos/<int:todo_id>")
def todo_delete(todo_id: int):
    db = get_db()
    if db.get_todo(todo_id) is None:
        return jsonify({"error": "Todo not found", "code": 404}), 404
    db.delete_todo(todo_id)
    return jsonify({"deleted": todo_id})


@blueprint.put("/todos/<int:todo_id>/link")
def todo_link(todo_id: int):
    """Link this to-do to `event_id`: from now on they are one thing (see
    db "A to-do and an event linked as ONE THING")."""
    data = request.get_json(silent=True) or {}
    try:
        event_id = int(data.get("event_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "event_id is required", "code": 400}), 400
    db = get_db()
    if not db.link_todo(todo_id, event_id):
        return jsonify({"error": "Todo or event not found", "code": 404}), 404
    return jsonify(db.get_todo(todo_id))


@blueprint.delete("/todos/<int:todo_id>/link")
def todo_unlink(todo_id: int):
    db = get_db()
    if db.get_todo(todo_id) is None:
        return jsonify({"error": "Todo not found", "code": 404}), 404
    db.unlink_todo(todo_id)
    return jsonify(db.get_todo(todo_id))


@blueprint.post("/todos/<int:todo_id>/event")
def todo_to_event(todo_id: int):
    """Put this to-do on the calendar as its linked event — on `date` (else its
    due date, else today) at `start_time` (else 09:00). Returns the existing
    linked event if it already has one."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    event_id = db.create_linked_event(
        todo_id, date=str(data.get("date") or ""),
        start_time=str(data.get("start_time") or "09:00"),
        end_time=str(data.get("end_time") or ""))
    if event_id is None:
        return jsonify({"error": "Todo not found", "code": 404}), 404
    return jsonify({"event": db.get_event(event_id), "todo": db.get_todo(todo_id)}), 201


@blueprint.post("/todos/sync")
def todos_sync():
    data = request.get_json(silent=True) or {}
    list_name = data.get("list_name", "today")
    db = get_db()
    count = db.sync_calendar_to_todos(list_name=list_name)
    return jsonify({"synced": count, "list": list_name})


@blueprint.post("/todos/reorder")
def todos_reorder():
    data = request.get_json(silent=True) or {}
    list_name = data.get("list")
    ids = data.get("ids", [])
    if not list_name or not isinstance(ids, list):
        return jsonify({"error": "Missing 'list' or 'ids'", "code": 400}), 400
    db = get_db()
    db.reorder_todos(list_name, [int(i) for i in ids])
    return jsonify({"ok": True})


@blueprint.delete("/todos/completed")
def todos_clear_completed():
    list_name = request.args.get("list")  # optional filter
    db = get_db()
    count = db.delete_completed_todos(list_name=list_name or None)
    return jsonify({"deleted": count})


# ------------------------------------------------------------------
# Todo tags
# ------------------------------------------------------------------

@blueprint.get("/tags")
def tags_list():
    return jsonify(get_db().get_tags())


@blueprint.post("/tags")
def tag_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Missing 'name' field", "code": 400}), 400
    row = get_db().create_tag(name, color=data.get("color", ""))
    return jsonify(row), 201


@blueprint.delete("/tags/<path:name>")
def tag_delete(name: str):
    get_db().delete_tag(name)
    return jsonify({"deleted": name})


@blueprint.get("/tags/rules")
def tag_rules():
    """The task-tag classifier, as data, so a client can run it offline.

    `assistant/actions/todo/tagging.py` is the one classifier — but it
    only runs where the database is, so a task typed on the phone with the
    Mac away was created untagged and stayed that way. The phone carries a
    port of the scorer (`TagClassifier.swift`); this endpoint hands it the
    table the scorer reads, so the two agree by construction instead of by
    a second list nobody remembers to update.

    Served, not hardcoded on the phone, for the same reason the palette is:
    `personal_labels` is the user's OWN vocabulary labels ("Haxaga" is a
    course), which no shipped list can contain. `rev` changes whenever any
    of it does, so a client can tell in one comparison whether its copy is
    current.
    """
    import hashlib
    import json as _json

    from assistant.actions.todo import tagging

    palette = [row["name"] for row in get_db().get_tags()]

    # ORDERED, and that is not cosmetic. `infer_tag` keeps the best score
    # with a strict `>`, so a tie goes to whichever tag came first — and
    # "buy twelve eggs and book haircut" is exactly that tie (Groceries 1.5,
    # Errands 1.5). In Python the order is KEYWORDS' insertion order. In
    # JSON it is whatever the serialiser felt like (Flask sorts keys), and
    # in Swift a Dictionary has no order at all and is not even stable
    # between runs — so the phone would break ties at random and disagree
    # with the Mac about one title in five hundred. Measured: 20 of 10,200
    # real strings, every one of them a tie. The order travels with the
    # table.
    personal: list = []
    try:
        from assistant.stt.vocab import get_vocab
        # Exactly the order `vocab.label_for` considers them in: longest
        # word first, over an `entries` list that is already sorted by
        # word, and Python's sort is stable — so ties resolve identically
        # on both sides instead of "whichever the dictionary yields".
        for entry in sorted(get_vocab().entries, key=lambda e: -len(e.word)):
            if entry.label:
                personal.append({"word": entry.word.lower(), "label": entry.label})
    except Exception:      # no vocabulary yet, or it cannot be read
        personal = []

    payload = {
        "keywords": tagging.KEYWORDS,
        "order": list(tagging.KEYWORDS),
        "never_infer": sorted(tagging._NEVER_INFER),
        "palette": palette,
        "personal_labels": personal,
    }
    payload["rev"] = hashlib.sha1(
        _json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return jsonify(payload)


@blueprint.get("/tags/suggestion")
def tag_suggestion():
    """A new-tag proposal mined from the user's untagged history, or {}.

    {"name": "Pharmacy", "evidence": 6, "samples": [...]} when enough
    distinct untagged tasks share a theme no existing class covers.
    Server-side politeness: handing one out costs the week's cooldown even
    if it goes unanswered, refused names never return, and clients call
    this only while the app is actively in the foreground — the server
    never pushes."""
    from assistant.actions.todo.tag_discovery import candidate, record_ask
    c = candidate()
    if not c:
        return jsonify({})
    record_ask()
    return jsonify(c)


@blueprint.post("/tags/suggestion/answer")
def tag_suggestion_answer():
    """{"name": "...", "accept": true|false} — yes adds the class to the
    registry; no is remembered forever."""
    from assistant.actions.todo.tag_discovery import answer
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Missing 'name'", "code": 400}), 400
    created = answer(name, bool(body.get("accept")))
    return jsonify({"name": name, "accepted": bool(body.get("accept")),
                    "tag": created})


@blueprint.get("/tags/suggestions/history")
def tag_suggestion_history():
    """Every past suggestion + verdict, newest first, incl. hidden flags —
    the reviewable record behind the app's history view."""
    from assistant.actions.todo.tag_discovery import history
    return jsonify(history())


@blueprint.post("/tags/suggestions/revise")
def tag_suggestion_revise():
    """{"name": ..., "accept": bool} changes a past verdict (un-accepting
    removes the class from the registry again); {"name": ..., "hidden":
    bool} folds an entry out of the visible history without deleting it."""
    from assistant.actions.todo.tag_discovery import change_answer, set_hidden
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Missing 'name'", "code": 400}), 400
    if "hidden" in body:
        set_hidden(name, bool(body.get("hidden")))
        return jsonify({"name": name, "hidden": bool(body.get("hidden"))})
    created = change_answer(name, bool(body.get("accept")))
    return jsonify({"name": name, "accepted": bool(body.get("accept")),
                    "tag": created})
