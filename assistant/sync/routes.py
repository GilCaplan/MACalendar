"""`/sync/*` — the hub's end of replication. HTTP only: the logic is `hub.py`.

| route | what |
|---|---|
| `GET /sync/pull?since=<seq>&replica=<name>` | what changed (no `since`: everything) |
| `POST /sync/push` `{replica, changes}` | a replica's changes; returns id `remap` |

The user is whoever the request is bound to — the same binding every other
route uses, so a replica syncs the calendar its requests open.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from assistant.sync import changelog as cl
from assistant.sync import hub

blueprint = Blueprint("sync", __name__)


def _conn():
    from assistant.db import get_db
    return cl.connect(get_db().path)


@blueprint.get("/sync/pull")
def sync_pull():
    since = request.args.get("since")
    replica = (request.args.get("replica") or "").strip()
    if not replica:
        return jsonify({"error": "replica is required", "code": 400}), 400
    conn = _conn()
    try:
        return jsonify(hub.pull(conn, int(since) if since not in (None, "") else None, replica))
    finally:
        conn.close()


@blueprint.post("/sync/push")
def sync_push():
    b = request.get_json(silent=True) or {}
    replica = str(b.get("replica") or "").strip()
    if not replica:
        return jsonify({"error": "replica is required", "code": 400}), 400
    conn = _conn()
    try:
        return jsonify(hub.apply_push(conn, replica, list(b.get("changes") or [])))
    finally:
        conn.close()


def register(app) -> None:
    app.register_blueprint(blueprint)
