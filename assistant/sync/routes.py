"""`/sync/*` — the hub's end of replication. HTTP only: the logic is `hub.py`.

| route | what |
|---|---|
| `GET /sync/pull?since=<seq>&replica=<name>[&url=<base>…]` | what changed (no `since`: everything); `url` is where the replica can be reached |
| `POST /sync/push` `{replica, changes}` | a replica's changes; returns id `remap` |
| `GET /sync/replicas` | the replicas heard from lately and their addresses — a phone's backup (DEVQA Q96) |
| `GET /sync/status` | this server's role; for a replica, whether it is in step with its hub |

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
        hub.note_replica(conn, replica, [u for u in request.args.getlist("url") if u.startswith("http")])
        return jsonify(hub.pull(conn, int(since) if since not in (None, "") else None, replica))
    finally:
        conn.close()


@blueprint.get("/sync/replicas")
def sync_replicas():
    conn = _conn()
    try:
        return jsonify({"replicas": hub.replicas(conn)})
    finally:
        conn.close()


@blueprint.get("/sync/status")
def sync_status():
    """What a phone asks before standing a replica in for its hub, and before
    handing back: `cursor` set = it has synced at least once (a copy that never
    has is not the calendar); `pending` 0 and `ok` = everything written here,
    the phone's writes included, has reached the hub."""
    from assistant.config import load_config
    cfg = load_config()
    if not cfg.sync.hub:
        return jsonify({"role": "hub"})
    from assistant.db import get_db
    from assistant.sync import replica
    rep = replica.Replica(get_db().path, cfg.sync.replica_name, transport=None)
    s = replica.status
    return jsonify({"role": "replica", "hub": cfg.sync.hub, "ok": bool(s.get("ok")),
                    "last_ok": s.get("last_ok"), "error": s.get("error") or "",
                    "cursor": rep.cursor(), "pending": rep.pending()})


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
