"""A follow-up in a Jude conversation: the chat so far + its sources, no new search.

Gil, 2026-10-20: *"perhaps the chat back is just the chat conversation and the
existing sources without pulling more"*. Asking Jude again runs its whole
pipeline — route, retrieve, filter, synthesise, five model calls — and whether
it reuses the earlier sources is its router's guess, made from a window Jude
only has when it saved the turns (`history.py` says when it did not). A
follow-up about what was just answered does not need any of that: the sources
are already chosen, so this answers from them and from the conversation.

"Search again" in either client sends `search: true` and goes to Jude as
before. A chat with no stored sources has nothing to follow up on and goes to
Jude too — `routes.chat` decides, this module only answers.

One model call through `model_protocol.route_post` like every generating
call (the gate, `hold()`, a helper), seeded when a board pins the seed, and
logged to the call bus. Jude's own model is used (`JudeIntegration.model()`),
so nothing new has to be resident.

This is a Jude answer, not a command: nothing here parses or executes, and the
engine is not imported (`test_jude.py` holds routes to that; this is held the
same way).
"""

from __future__ import annotations

import contextvars
import json
import queue
import threading
import time

#: The sources shown to the model. Jude retrieves up to 30; the first dozen,
#: already ranked, are what an answer cites, and the rest only cost context.
MAX_SOURCES = 12
SOURCE_CHARS = 700
KEEPALIVE_S = 15
TIMEOUT_S = 300

SYSTEM = (
    "You are Jude, a Judaic study assistant, continuing a conversation. Answer the "
    "follow-up using ONLY the numbered sources below and what was already said. "
    "After each claim, cite the source as [n]. If the sources do not cover the "
    "question, say so plainly and suggest asking again with a new search — do not "
    "answer from memory."
)


def _sources_block(sources: list) -> str:
    lines = []
    for i, s in enumerate(sources[:MAX_SOURCES], 1):
        text = (s.get("en_text") or s.get("text") or s.get("he_text") or "").strip()
        lines.append(f"[{i}] {s.get('ref', '')}\n{text[:SOURCE_CHARS]}")
    return "\n\n".join(lines)


def messages(question: str, sources: list, window: list, lang: str = "en") -> list:
    """The chat the model is given: system, sources, the conversation, the question."""
    system = SYSTEM + ("\nAnswer in Hebrew." if lang == "he" else "")
    out = [{"role": "system", "content": f"{system}\n\nSources:\n\n{_sources_block(sources)}"}]
    for t in window:
        out.append({"role": "user", "content": t["question"]})
        out.append({"role": "assistant", "content": t["answer"]})
    out.append({"role": "user", "content": question})
    return out


def _ask(msgs: list, model: str, source: str = "") -> str:
    from assistant import llm_bus as _bus
    from assistant import model_protocol
    from assistant.api.server import load_config
    conf = load_config().ollama
    payload = {"model": model or conf.model, "stream": False, "messages": msgs,
               "keep_alive": conf.keep_alive,
               "options": {"temperature": 0.3, **model_protocol.seed_options()}}
    user = msgs[-1]["content"]
    t0 = time.perf_counter()
    try:
        resp = model_protocol.route_post("/api/chat", payload, TIMEOUT_S, conf.base_url)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
    except Exception as e:
        _bus.record(transport="chat", caller="jude.followup", model=payload["model"], system=SYSTEM,
                    user=user, error=f"{type(e).__name__}: {e}",
                    ms=int((time.perf_counter() - t0) * 1000), source=source)
        raise
    _bus.record(transport="chat", caller="jude.followup", model=payload["model"], system=SYSTEM,
                user=user, response=content, ms=int((time.perf_counter() - t0) * 1000), source=source)
    return content


def stream(chat_id: str, question: str, sources: list, window: list, *,
           model: str, lang: str = "en", source: str = "", on_done=None):
    """NDJSON lines in Jude's own event shapes, so both clients render it unchanged.

    The model call runs on a worker thread (in a copy of this context, so the
    request's priority and user go with it) and this generator says
    `keepalive` while it waits — the same reason `proxy.stream` does: silence
    reads as a dead Mac on the phone.
    """
    msgs = messages(question, sources, window, lang)
    shown = sources[:MAX_SOURCES]
    q: queue.Queue = queue.Queue()
    ctx = contextvars.copy_context()

    def work():
        try:
            answer = ctx.run(_ask, msgs, model, source)
        except Exception as e:          # noqa: BLE001 — the stream must say why
            q.put(("error", e))
            return
        # Kept HERE, not after the generator resumes: a phone that went to the
        # background mid-answer closes the generator, and the answer the model
        # still finished would otherwise be paid for and thrown away.
        if on_done:
            try:
                on_done(answer, shown)
            except Exception:           # noqa: BLE001 — delivering it matters more
                pass
        q.put(("ok", answer))

    def gen():
        yield json.dumps({"type": "stage", "name": "Answering from this conversation's sources…"}) + "\n"
        yield json.dumps({"type": "meta", "chat_id": chat_id, "mode": "followup", "sources": shown,
                          "steps": [{"module": "Follow-up",
                                     "result": {"sources_reused": len(shown), "turns_shown": len(window)}}]},
                         ensure_ascii=False) + "\n"
        t0 = time.monotonic()
        threading.Thread(target=work, daemon=True, name="jude-followup").start()
        while True:
            try:
                kind, val = q.get(timeout=KEEPALIVE_S)
                break
            except queue.Empty:
                yield json.dumps({"type": "keepalive"}) + "\n"
        if kind == "error":
            yield json.dumps({"type": "error", "message": f"Your Mac's model couldn't answer: {val}"}) + "\n"
            return
        yield json.dumps({"type": "token", "text": val}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "done", "timing": {"total_ms": int((time.monotonic() - t0) * 1000)}}) + "\n"

    return gen()
