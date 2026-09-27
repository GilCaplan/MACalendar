"""A delete or complete said as a FRAME is read as that change on the deep track.

The front door defers "i no longer need to X, so delete it from the list" and
"never mind about X, take it off my list" (the words say the thing exists);
the deep track then (1) cut the first in two at ", so delete it", and (2) let
the model read either as a NEW to-do — 11 wrong rows on Board D TRAIN
(33e5bd9c, 2026-09-27).
"""
from __future__ import annotations

import pytest

from assistant.engine.segmentation.fastseg.fastseg import fastseg
from assistant.intent.rule_parser import mutation_frame_kind


def test_a_back_reference_stays_with_what_it_points_at():
    got = fastseg("i no longer need to refill the prescription, so delete it from the list")
    assert len(got) == 1
    # two real asks are still two
    assert len(fastseg("book the dentist and remind me to buy milk")) == 2


@pytest.mark.parametrize("said,kind", [
    ("i no longer need to refill the prescription, so delete it from the list", "delete"),
    ("never mind about pack for the trip, take it off my list", "delete"),
    ("wipe feed the cat from the to-do list, i won't be doing it", "delete"),
    ("buy groceries, done", "complete"),
    ("organize the garage is sorted, you can tick it off", "complete"),
    ("buy groceries is due in three weeks now, update it", None),   # needs a value
    ("buy milk", None),
    ("remind me to take the laundry off the line", None),
])
def test_the_frame_kind(said, kind):
    assert mutation_frame_kind(said) == kind


def test_the_rescue_retries_a_create_as_the_frame_says(monkeypatch):
    """The model answered create_todo; the words say delete; one retry with
    the frame stated, and its delete is kept."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import assistant.engine as engine
    import assistant.engine.llm as engine_llm
    from assistant.actions.todo.intent import CreateTodoIntent

    rr = SimpleNamespace(confidence=0.30, missing_slots=["title"], intents=[])
    rp = MagicMock()
    rp.analyze.return_value = rr
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: rp)

    said = "never mind about pack for the trip, take it off my list"
    parser = MagicMock()
    parser.parse_with_context.side_effect = Exception("no context parse")

    def parse(text):
        if text.startswith("remove this from my to-do list"):
            return [("delete_todo", SimpleNamespace(match_title="pack for the trip"))]
        return [("create_todo", CreateTodoIntent(titles=["never mind about pack for the trip"]))]
    parser.parse.side_effect = parse
    parser.last_llm_ms = 3
    parser.last_examples_used = 0
    parser.last_raw_response = ""
    monkeypatch.setattr(engine_llm, "get_parser", lambda cfg: parser)
    monkeypatch.setattr(engine_llm, "is_reachable", lambda cfg=None: True)

    from assistant.engine.state import EngineState
    cfg = engine.load_config()
    st = EngineState(raw_text=said, text=said, source="test")
    E = engine.Engine()
    E.parse(st, cfg)
    E.judge(st, cfg)
    assert [i.action for i in st.items] == ["delete_todo"], [(i.action, i.text) for i in st.items]
    assert any(f.rule == "mutation_frame_retry" for f in st.fixes)
