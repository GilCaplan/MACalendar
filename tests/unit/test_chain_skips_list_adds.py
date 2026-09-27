"""A to-do said onto a named list is never chained into an event (Q47 over Q51).

Real speech (verification pool, dev range, 2026-09-27): "…meeting with Julie at
5 pm this evening, and then Add broccoli to my shopping list" came out as two
events — the sequence chain made the list add "the next thing in the day".
"""
from __future__ import annotations

from assistant.engine import Engine, load_config
from assistant.engine.state import EngineState


def _kinds(text):
    cfg, eng = load_config(), Engine()
    st = EngineState(raw_text=text, text=text, source="test")
    eng.transcript.run(st, cfg)
    for stage in eng.stages:
        stage.run(st, cfg)
    return [i.kind for i in st.items]


def test_a_list_add_after_then_stays_a_todo():
    assert _kinds("Remind me about the meeting at 5 pm, and then add sugar to my grocery list") \
        == ["event", "task"]


def test_a_real_chain_still_chains():
    assert _kinds("gym at 9 then walk the dog") == ["event", "event"]
