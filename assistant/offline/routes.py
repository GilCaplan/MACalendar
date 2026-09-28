"""HTTP for the offline reader: its spec, its measured agreement, and whether
a command the Mac queued has run yet. Plumbing only — no parsing here."""
from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("offline", __name__)


@bp.get("/offline/reader")
def reader():
    """What the phone's on-device model is told. Cached by the phone."""
    from assistant.offline.spec import reader_spec
    return jsonify(reader_spec())


@bp.get("/offline/agreement")
def agreement():
    """How often the phone's offline reading matched the Mac's, from the log."""
    from assistant.offline import log
    return jsonify(log.summary())


@bp.get("/offline/pending/<int:pending_id>")
def pending_status(pending_id: int):
    """Has the Mac run a command it queued? The phone keeps its provisional
    rows for a `pending` verdict and asks here until the answer is no longer
    `pending`, then drops them and shows the Mac's."""
    from assistant.intent.memory import get_memory
    row = get_memory().get_pending(pending_id)
    if row is None:
        return jsonify({"error": "Unknown pending command", "code": 404}), 404
    return jsonify({"id": pending_id, "status": row.get("status", "pending"),
                    "result": row.get("result", "")})


def register(app) -> None:
    app.register_blueprint(bp)
