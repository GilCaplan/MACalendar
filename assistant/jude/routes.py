"""Jude's HTTP surface: `/jude/*`, proxied to its server on loopback.

A Flask blueprint rather than lines in `server.py`. CLAUDE.md's rule for that
file is that it stays HTTP — routes, request shapes, CRUD — and the previous
integration put ~120 lines of Jude-specific proxying in the middle of it. Now
`server.py` registers the blueprint and knows nothing else about Jude.

**The brain is untouched.** Nothing here parses or executes anything: Jude is
not wired into `assistant/engine/` and cannot be asked to create an event.

| route | what |
|---|---|
| `GET /jude/status` | enabled / installed / running / ready + `reason`. Never an error. |
| `POST /jude/chat` | `{prompt, chat_id?, mode?, lang?, top_k?, skip_clarification?}` -> NDJSON |
| `GET /jude/chats` | past conversations |
| `GET /jude/chats/<id>/history` | one conversation |
| `DELETE /jude/chats/<id>` | forget one |
| `PUT /jude/chats/<id>/topic` | confirm a topic pivot |

Event types pass through unchanged: `stage`, `meta`, `token`, `tool_call`,
`clarification`, `topic_pivot`, `done`, `error`.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from assistant.integrations import proxy

blueprint = Blueprint("jude", __name__, url_prefix="/jude")

#: Jude scopes chat history per user — a convenience for shared local
#: deployments, where several people use one browser. This assistant is one
#: person's Mac and one person's phone, so a login screen would be friction
#: buying nothing. One fixed owner, and every chat is yours on both surfaces.
OWNER = "macalendar"

#: Jude clamps to 1..30 itself; clamping here too means a bad client gets a
#: sane answer instead of a 422 it has to interpret.
K_MIN, K_MAX, K_DEFAULT = 1, 30, 25

MODES = ("qa", "study", "sources")


def _jude():
    from assistant.integrations import registry
    return registry.get("jude")


@blueprint.get("/status")
def status():
    """Never an error — a client draws whatever this says."""
    integration = _jude()
    if integration is None:
        return jsonify({"enabled": False, "installed": False, "running": False,
                        "ready": False, "reason": "Jude isn't configured here."})
    return jsonify(integration.status())


@blueprint.post("/chat")
def chat():
    """Ask Jude a question; stream the answer back as NDJSON."""
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Missing 'prompt'", "code": 400}), 400

    mode = (body.get("mode") or "qa").strip().lower()
    # `or K_DEFAULT` would be wrong here: it treats an explicit 0 as absent and
    # silently returns 25 sources, when what the client asked for was clamped
    # to the floor. Only a MISSING value takes the default.
    raw_k = body.get("top_k")
    try:
        top_k = K_DEFAULT if raw_k is None else int(raw_k)
    except (TypeError, ValueError):
        top_k = K_DEFAULT

    payload = {
        "prompt": prompt,
        "chat_id": body.get("chat_id") or None,
        "lang": "he" if (body.get("lang") or "en").strip().lower() == "he" else "en",
        "mode": mode if mode in MODES else "qa",
        "top_k": max(K_MIN, min(top_k, K_MAX)),
        "skip_clarification": bool(body.get("skip_clarification")),
        "user": OWNER,
    }
    return proxy.stream(_jude(), "/api/chat", payload)


@blueprint.get("/chats")
def chats():
    """List past conversations, newest first."""
    return proxy.call(_jude(), f"/api/chats?user={OWNER}")


@blueprint.get("/chats/<chat_id>/history")
def chat_history(chat_id: str):
    """Every message in one conversation."""
    return proxy.call(_jude(), f"/api/chats/{chat_id}/history")


@blueprint.delete("/chats/<chat_id>")
def chat_delete(chat_id: str):
    """Forget one conversation."""
    return proxy.call(_jude(), f"/api/chats/{chat_id}?user={OWNER}", method="DELETE")


@blueprint.put("/chats/<chat_id>/topic")
def chat_topic(chat_id: str):
    """Confirm a topic pivot.

    Jude emits `topic_pivot` when a question moves to a subject this
    conversation has not covered, and keeps answering regardless — the
    confirmation is asynchronous, so a client that ignores it loses nothing but
    the label.
    """
    body = request.get_json(silent=True) or {}
    topic = (body.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Missing 'topic'", "code": 400}), 400
    return proxy.call(_jude(), f"/api/chats/{chat_id}/topic", method="PUT",
                      payload={"topic": topic})
