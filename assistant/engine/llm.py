"""Shared LLM transport for engine stages — infrastructure, not a stage.

Stages must not import each other's internals, but they all speak to the same
local model. This module is the one sanctioned door (documented in
DOCUMENTATION/ENGINE.md alongside state.py): a schema-constrained JSON call,
grounded on whatever the caller passes, riding the exact per-provider paths
`IntentParser` already maintains — no second HTTP client to drift.

Every call is loopback-only by construction (the parser's transports are), so
tests/unit/test_offline.py keeps holding.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# The shared ACCESSORS — the action registry and the two parsers.
#
# They lived in `fastrule/objects.py`, which made a STAGE the owner of
# infrastructure six call sites outside it reach through, including the API
# server's warm-up. That collided head-on with what FastRule is becoming: a
# pure `Item -> object` converter with no model and no I/O cannot also be the
# door to the LLM parser. So they moved here, next to `call_json`, which is
# already the sanctioned door for the same reason (2026-09-10, PLAN.md §3 W5:
# "decide this in B3, not in B6 -- discovering it during a deletion is how a
# warm-up path silently stops warming up").
#
# `_get_parser` was ALSO duplicated: this module built its own `IntentParser`
# with its own cache while `objects.py` built another. Two caches of the same
# object, one of them reset by `reset()` and the other not. Now there is one.
# ---------------------------------------------------------------------------

_registry = None
_parser = None                    # IntentParser — the LLM parser
_rule_parser = None               # RuleBasedParser — deterministic, needs spaCy
_RULE_PARSER_MISSING = object()   # spaCy absent: checked once, then skipped


def get_registry():
    """The action registry, with every action module imported (they
    self-register via @register on import)."""
    import assistant.actions.calendar          # noqa: F401
    import assistant.actions.todo              # noqa: F401
    import assistant.actions.clarify           # noqa: F401
    import assistant.actions.workout_routine   # noqa: F401
    import assistant.actions.schedule_workout  # noqa: F401
    from assistant.actions import ActionRegistry
    return ActionRegistry()


def get_parser(cfg):
    """The LLM-backed `IntentParser`, cached."""
    global _parser
    if _parser is None:
        from assistant.intent.parser import IntentParser
        _parser = IntentParser(cfg, get_registry())
    return _parser


def get_rule_parser():
    """The deterministic `RuleBasedParser`, cached. None when spaCy is absent —
    checked once, then skipped, because the import is expensive to retry."""
    global _rule_parser
    if _rule_parser is _RULE_PARSER_MISSING:
        return None
    if _rule_parser is None:
        from assistant.intent.rule_parser import (
            RuleBasedParser, _RULE_PARSER_AVAILABLE,
        )
        if not _RULE_PARSER_AVAILABLE:
            _rule_parser = _RULE_PARSER_MISSING
            return None
        _rule_parser = RuleBasedParser(get_registry())
    return _rule_parser


#: The old private name, kept because `call_json` below and a few callers use
#: it. One cache, two names — not two caches.
_get_parser = get_parser


def reset() -> None:
    """Tests swap config and empty the registry; cached parsers must not
    outlive either."""
    global _parser, _rule_parser, _registry
    _parser = None
    _rule_parser = None
    _registry = None


def call_json(cfg, system: str, user: str, schema: "dict | None" = None) -> "tuple[dict, int]":
    """One structured-output call. Returns (parsed dict, elapsed ms).

    With a schema and Ollama, the model is format-constrained (it CANNOT emit
    malformed JSON, only wrong content); other engines fall back to the
    free-JSON path. Raises AssistantError subclasses on transport failure —
    the caller decides whether that skips the stage or fails the command.
    """
    import os
    import time

    if os.environ.get("MACALENDAR_LLM_DISABLED") == "1":
        from assistant.exceptions import OllamaUnavailableError
        raise OllamaUnavailableError("engine LLM calls are disabled (MACALENDAR_LLM_DISABLED)")
    parser = _get_parser(cfg)
    t0 = time.perf_counter()
    if schema is not None and cfg.llm_engine == "ollama":
        raw = parser._call_ollama(system, user, schema)
        out = json.loads(parser._extract_json(raw))
    else:
        out = parser.call_llm_json(system, user)
    return out, int((time.perf_counter() - t0) * 1000)
