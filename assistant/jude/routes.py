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
| `POST /jude/chat` | `{prompt, chat_id?, mode?, lang?, top_k?, skip_clarification?, search?}` -> NDJSON |
| `GET /jude/chats` | past conversations |
| `GET /jude/chats/<id>/history` | one conversation |
| `POST /jude/chats/<id>/answer` | `{question, answer}` — an answer the phone wrote itself |
| `DELETE /jude/chats/<id>` | forget one |
| `PUT /jude/chats/<id>/topic` | confirm a topic pivot |

Event types pass through unchanged: `stage`, `meta`, `token`, `tool_call`,
`clarification`, `topic_pivot`, `done`, `error`.

**History is OURS** (`history.py`, 2026-10-20): every turn is recorded as it
streams past, because Jude's own file only kept the turns Jude itself finished.
**A follow-up does not search again** unless asked (`search: true`): in a chat
with sources it is answered from them and the conversation (`followup.py`).
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
    store = _history()
    chat_id = payload["chat_id"]
    if chat_id:
        _adopt(store, chat_id)
    # A follow-up in a chat that already has its sources is answered from them
    # — no route, no retrieval — unless the client asked to search again.
    # `search` absent means "you decide", and the decision is: reuse. Never for
    # the answer to a CLARIFICATION: Jude asked it, so Jude gets the reply.
    if (chat_id and not body.get("search") and payload["mode"] != "sources"
            and not payload["skip_clarification"]
            and store.latest_kind(chat_id) != "clarification"):
        sources = store.last_sources(chat_id)
        if sources:
            return _followup(store, chat_id, prompt, sources, payload["lang"],
                             str(body.get("source") or ""))
    resp = proxy.stream(_jude(), "/api/chat", payload)
    return _recording(resp, store, prompt, payload["mode"], chat_id)


def _history():
    from assistant.jude.history import JudeHistory
    return JudeHistory()


def _jude_running() -> bool:
    """Is Jude up NOW. A port check — asking a stopped Jude for its list would
    START it (`proxy.call` → `ensure_running`) and hold History for up to two
    minutes, for chats this store mostly already has."""
    try:
        integration = _jude()
        return bool(integration and integration.status().get("running"))
    except Exception:                    # noqa: BLE001
        return False


def _json_of(r):
    resp, status = (r if isinstance(r, tuple) else (r, getattr(r, "status_code", 200)))
    try:
        return resp.get_json(), status
    except Exception:                    # noqa: BLE001
        return None, status


def _adopt(store, chat_id: str, summary: dict | None = None) -> None:
    """Copy a chat only Jude kept into our store before it gains a turn here —
    or History would show only what was said after this store existed.
    `summary` is the chat's row from Jude's list, when known: its title,
    mode and creation time are kept."""
    if store.has(chat_id) or store.is_hidden(chat_id) or not _jude_running():
        return
    data, status = _json_of(proxy.call(_jude(), f"/api/chats/{chat_id}/history"))
    if status == 200 and isinstance(data, list):
        s = summary or {}
        store.adopt(chat_id, data, title=str(s.get("title") or ""),
                    mode=str(s.get("mode") or "qa"), created_at=str(s.get("created_at") or ""))


#: Jude chats already found to hold no messages, so a sync does not ask for
#: their history again on every call. Per process; a restart asks once more.
_EMPTY_IN_JUDE: set = set()


def _adopt_all(store) -> None:
    """Every chat Jude kept and we have not, copied in once — so the phone's
    copy of History holds them all, not only the ones opened since."""
    if not _jude_running():
        return
    data, status = _json_of(proxy.call(_jude(), f"/api/chats?user={OWNER}"))
    if status != 200 or not isinstance(data, list):
        return
    for c in data:
        cid = str(c.get("id") or "") if isinstance(c, dict) else ""
        if not cid or cid in _EMPTY_IN_JUDE or store.has(cid) or store.is_hidden(cid):
            continue
        _adopt(store, cid, c)
        if not store.has(cid):
            _EMPTY_IN_JUDE.add(cid)


def _followup(store, chat_id: str, prompt: str, sources: list, lang: str, source: str):
    from contextlib import nullcontext

    from flask import Response, stream_with_context

    from assistant import model_protocol
    from assistant.jude import followup
    window = store.window(chat_id)

    def done(answer, shown):
        store.record(chat_id, prompt, answer, sources=shown, mode="followup", kind="followup")

    def gen():
        # A person asking is LIVE — the default when nothing says otherwise;
        # a client that labels itself ("test") is served at its own priority.
        with (model_protocol.serving(source) if source else nullcontext()):
            yield from followup.stream(chat_id, prompt, sources, window, model=_jude().model(),
                                       lang=lang, source=source, on_done=done)

    return Response(stream_with_context(gen()), mimetype="application/x-ndjson",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _recording(resp, store, prompt: str, mode: str, chat_id: str | None):
    """Pass the stream through untouched, and keep the turn when it ends.

    Records whatever arrived: the answer's tokens, the sources from `meta` and
    from tool calls (Jude's own store keeps both, and an answer cites both), a
    clarification's question — and an empty answer for a "sources" request,
    which the phone fills with `POST /chats/<id>/answer` once it has written
    one. A stream that ended in an error, or before `done`, is kept as
    "incomplete": shown, never followed up on as if finished. Nothing is
    recorded without a chat id to file it under.
    """
    import json as _json

    from flask import Response
    if not isinstance(resp, Response) or not resp.is_streamed:
        return resp                      # a 503 with a sentence, passed on as is
    upstream = resp.response
    turn = {"chat_id": chat_id, "answer": [], "sources": [], "kind": "answer", "mode": mode,
            "done": False, "error": False, "extra": {}}

    def take(line) -> None:
        try:
            ev = _json.loads(line if isinstance(line, str) else line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        kind = ev.get("type")
        if ev.get("chat_id"):
            turn["chat_id"] = ev["chat_id"]
        if kind == "token":
            turn["answer"].append(str(ev.get("text") or ""))
        elif kind == "meta":
            turn["sources"] = list(ev.get("sources") or [])
            turn["mode"] = ev.get("mode") or mode
        elif kind == "tool_call":
            turn["sources"].extend(ev.get("new_sources") or [])
        elif kind == "clarification":
            # Options are {label, prompt} — or a bare string from an
            # older Jude. The text is what History reads; `extra` is
            # what lets a reopened card still be answered.
            opts = [o if isinstance(o, dict) else {"label": str(o), "prompt": str(o)}
                    for o in ev.get("options") or []]
            question = str(ev.get("question") or "")
            turn["kind"] = "clarification"
            turn["answer"] = [question + "".join(f"\n- {o.get('label', '')}" for o in opts)]
            turn["extra"] = {"clarification": {"question": question, "options": opts}}
        elif kind == "done":
            turn["done"] = True
        elif kind == "error":
            turn["error"] = True

    def keep() -> None:
        if turn["kind"] == "answer" and (turn["error"] or not turn["done"]):
            turn["kind"] = "incomplete"
        if not turn["chat_id"]:
            return
        try:
            store.record(turn["chat_id"], prompt, "".join(turn["answer"]),
                         sources=turn["sources"], mode=turn["mode"], kind=turn["kind"],
                         extra=turn["extra"])
        except Exception as e:      # noqa: BLE001 — the answer was delivered; say why it was not kept
            import logging
            logging.getLogger(__name__).warning("jude: could not keep the turn: %s", e)

    def finish_unread() -> None:
        # The phone left mid-answer (backgrounded, switched chats): Jude goes
        # on writing anyway, so read the rest here and keep the WHOLE answer
        # rather than the half that had arrived — History is where it will be
        # read now.
        try:
            for line in upstream:
                take(line)
        except Exception:                # noqa: BLE001 — keep what did arrive
            pass
        keep()

    def tap():
        try:
            for line in upstream:
                take(line)
                yield line
        except GeneratorExit:
            import threading
            threading.Thread(target=finish_unread, daemon=True, name="jude-finish").start()
            raise
        keep()

    resp.response = tap()
    return resp


@blueprint.get("/chats")
def chats():
    """Past conversations, newest first: ours, then any only Jude has.

    Jude's list is the fallback for chats from before `history.py`, asked only
    while Jude is RUNNING — with it stopped, the conversations kept here list
    at once instead of waiting for it to start. A chat deleted here stays
    deleted even if Jude still has it.
    """
    store = _history()
    mine = store.chats()
    skip = {c["id"] for c in mine} | store.hidden_ids()
    theirs = []
    if _jude_running():
        data, status = _json_of(proxy.call(_jude(), f"/api/chats?user={OWNER}"))
        if status == 200 and isinstance(data, list):
            theirs = [c for c in data if isinstance(c, dict) and c.get("id") not in skip]
    both = mine + theirs
    both.sort(key=lambda c: c.get("updated_at") or c.get("created_at") or "", reverse=True)
    return jsonify(both)


@blueprint.get("/chats/<chat_id>/history")
def chat_history(chat_id: str):
    """Every message in one conversation — ours, adopting Jude's copy first."""
    store = _history()
    _adopt(store, chat_id)
    if store.has(chat_id):
        return jsonify(store.messages(chat_id))
    # Not here, and Jude is stopped (or it is deleted): asking would START
    # Jude and hold the page for up to two minutes for a chat with nothing
    # in it — a chat with messages was adopted above, or by `/sync`.
    return jsonify([])


@blueprint.get("/sync")
def sync():
    """What the phone's copy of History needs to catch up, in one call.

    `?since=<iso>` → `{chats: [{id, title, mode, created_at, updated_at,
    messages}], deleted: [ids], next: <iso>}` — every chat changed after
    `since` (all of them when absent), and every chat deleted here. `next`
    is the newest change returned, the `since` for the call after; taken
    from the rows rather than the clock, so a write landing mid-call is
    picked up next time instead of skipped.
    """
    store = _history()
    _adopt_all(store)
    # An unencoded "+00:00" arrives as " 00:00" — and then every chat
    # compares as changed, every call. Put the plus back.
    since = (request.args.get("since") or "").replace(" ", "+")
    changed = store.changed_since(since)
    nxt = max([since] + [c["updated_at"] for c in changed])
    return jsonify({"chats": changed, "deleted": sorted(store.hidden_ids()), "next": nxt})


@blueprint.post("/chats/<chat_id>/answer")
def chat_answer(chat_id: str):
    """An answer the PHONE wrote (from sources the Mac found), so it is kept too.

    `{question, answer, sources?, mode?, kind?}` — the sources and kind matter
    for a follow-up the phone answered from sources it already had, which the
    Mac never saw and so has no turn to fill.
    """
    body = request.get_json(silent=True) or {}
    question = str(body.get("question") or "").strip()
    answer = str(body.get("answer") or "").strip()
    if not question or not answer:
        return jsonify({"error": "Missing 'question' or 'answer'", "code": 400}), 400
    kind = body.get("kind") if body.get("kind") in ("answer", "followup") else "answer"
    mode = str(body.get("mode") or ("followup" if kind == "followup" else "qa"))
    sources = body.get("sources") if isinstance(body.get("sources"), list) else None
    store = _history()
    _adopt(store, chat_id)
    store.fill_answer(chat_id, question, answer, by="phone", sources=sources, mode=mode, kind=kind)
    return jsonify({"ok": True})


@blueprint.delete("/chats/<chat_id>")
def chat_delete(chat_id: str):
    """Forget one conversation — here for good, and in Jude when it is up.

    Remembered as deleted here, so a copy Jude still holds (stopped, or its
    delete failed) cannot come back through the fallback list.
    """
    store = _history()
    ours = store.has(chat_id) or any(c["id"] == chat_id for c in store.chats())
    store.delete(chat_id)
    if not _jude_running():
        return jsonify({"ok": True})
    r = proxy.call(_jude(), f"/api/chats/{chat_id}?user={OWNER}", method="DELETE")
    # Jude's answer decides the reply only for a chat we never kept — a 404
    # about one it never saved would read on the phone as a refusal.
    return jsonify({"ok": True}) if ours else r


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
