"""`POST /magic/suggest-words` — more words for a magic-word object, from the
Mac's model, for a phone that can't make them itself (TASKS 49).

The phone asks its own on-device model first (the device of origin); this is
its fallback, and "Ask my Mac" when the user wants a stronger model. Nothing
here parses or executes a command — it asks the model for a list of words
and hands it back; the phone cleans the list and the user picks from it.

    body   {"name": "German Shepherd", "existing": ["dog", "puppy"], "count": 10, "source": "ios"}
    reply  {"words": [...], "source": "mac"}   or   {"error": ..., "code": 503}
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)
bp = Blueprint("magic", __name__)

SYSTEM = (
    "You list the other names people use for a thing, for a word game in a calendar app. "
    "Give words and short phrases someone might say in a sentence that clearly mean that same "
    "thing: synonyms, kinds, breeds, types, famous examples, nicknames, other spellings. Lower "
    "case, one to three words each. Never repeat a word, never repeat the ones already listed, "
    "never split a name into its separate words, never a generic everyday word."
)
SCHEMA = {"type": "object", "properties": {"words": {"type": "array", "items": {"type": "string"}}},
          "required": ["words"]}


def suggest(name: str, existing: list, count: int, cfg, source: str = "") -> list:
    """The model's words for `name`, raw (the phone cleans them).

    Through the model protocol like every generating call: `route_post` (the
    gate, `hold()`, and any model helper), seeded when a board pins the seed,
    and logged to the call bus. The caller sets the priority (`serving`)."""
    import time as _t

    from assistant import llm_bus as _bus
    from assistant import model_protocol
    conf = cfg.ollama
    user = (f"Thing: {name}\nAlready listed: {', '.join(existing) or 'nothing'}\n"
            f"Give {count} more.")
    payload = {"model": conf.model, "stream": False, "format": SCHEMA,
               "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
               "keep_alive": conf.keep_alive,
               "options": {"temperature": 0.7, **model_protocol.seed_options()}}
    t0 = _t.perf_counter()
    try:
        resp = model_protocol.route_post("/api/chat", payload, 45, conf.base_url)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
    except Exception as e:
        _bus.record(transport="chat", caller="magic.suggest_words", model=conf.model, system=SYSTEM,
                    user=user, error=f"{type(e).__name__}: {e}", ms=int((_t.perf_counter() - t0) * 1000),
                    source=source)
        raise
    _bus.record(transport="chat", caller="magic.suggest_words", model=conf.model, system=SYSTEM,
                user=user, response=content, ms=int((_t.perf_counter() - t0) * 1000), source=source)
    words = json.loads(content).get("words") or []
    return [str(w) for w in words if isinstance(w, (str, int))][: count * 2]


@bp.post("/magic/suggest-words")
def suggest_words():
    from assistant.api.server import load_config
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Missing 'name'", "code": 400}), 400
    existing = [str(w) for w in (body.get("existing") or [])][:60]
    try:
        count = max(1, min(30, int(body.get("count") or 10)))
    except (TypeError, ValueError):
        count = 10
    from assistant import model_protocol
    source = str(body.get("source") or "")
    try:
        # A phone asking is a person waiting (live); a test is background.
        with model_protocol.serving(source):
            words = suggest(name, existing, count, load_config(), source=source)
    except Exception as e:                  # noqa: BLE001 — any model failure is "no model"
        logger.warning("suggest-words: the model could not answer: %s", e)
        return jsonify({"error": "Your Mac's model isn't available right now.", "code": 503}), 503
    return jsonify({"words": words, "source": "mac"})


def register(app) -> None:
    app.register_blueprint(bp)
