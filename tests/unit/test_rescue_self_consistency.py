"""H1 of the llmjudge program (PLAN §7.5): rescue self-consistency.

Off unless `MACALENDAR_RESCUE_SC=1` (a board's arm); when on, an item FastRule
declined as more than one thing is read twice, and only a disagreement on
how many objects of which kind reaches the one comparative call.
"""
from __future__ import annotations

import types

import pytest

from assistant.engine.llmjudge import rescue as R
from assistant.engine.state import EngineState, Item


class _I:
    def __init__(self, **kw):
        self.kw = kw

    def model_dump(self):
        return dict(self.kw)


A = [("create_event", _I(title="dentist")), ("create_todo", _I(titles=["milk"]))]
B = [("create_event", _I(title="dentist and milk"))]


def _state():
    st = EngineState(raw_text="x", text="x", source="test")
    return st, Item(id="i1", text="book the dentist and buy milk", kind="event")


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("MACALENDAR_RESCUE_SC", raising=False)
    assert not R._self_consistency_on()
    monkeypatch.setenv("MACALENDAR_RESCUE_SC", "1")
    assert R._self_consistency_on()


def test_only_a_compound_is_read_twice():
    structure = types.SimpleNamespace(reason_class="structure")
    incapacity = types.SimpleNamespace(reason_class="incapacity")
    assert R._is_compound(structure, B)
    assert R._is_compound(incapacity, A)            # the parse itself said two
    assert not R._is_compound(incapacity, B)


def test_agreement_keeps_the_first_reading_and_asks_nothing(monkeypatch):
    st, item = _state()
    same = [("create_event", _I(title="the dentist")), ("create_todo", _I(titles=["milk"]))]
    called = []
    monkeypatch.setattr("assistant.engine.llm.call_json",
                        lambda *a, **k: called.append(1) or ({"choice": "B"}, 5))
    monkeypatch.setattr(R, "_llm_trace", lambda *a, **k: None)
    got = R._second_opinion(A, lambda: same, item, st, None, None)
    assert got is A and not called
    assert [f.note for f in st.fixes if f.rule == "rescue_sc"] == ["agree"]


@pytest.mark.parametrize("choice,want", [("A", "first"), ("B", "second")])
def test_a_disagreement_is_settled_by_one_choice(monkeypatch, choice, want):
    st, item = _state()
    monkeypatch.setattr("assistant.engine.llm.call_json", lambda *a, **k: ({"choice": choice}, 5))
    monkeypatch.setattr(R, "_llm_trace", lambda *a, **k: None)
    got = R._second_opinion(A, lambda: B, item, st, None, None)
    assert got is (A if want == "first" else B)
    assert st.llm_ms == 5


def test_a_failed_second_call_keeps_the_first(monkeypatch):
    st, item = _state()

    def boom(*a, **k):
        raise RuntimeError("ollama down")
    monkeypatch.setattr("assistant.engine.llm.call_json", boom)
    monkeypatch.setattr(R, "_llm_trace", lambda *a, **k: None)
    assert R._second_opinion(A, lambda: B, item, st, None, None) is A


def test_the_second_sample_gets_its_own_temperature(monkeypatch):
    from assistant.intent import parser as P
    seen = {}
    st, item = _state()
    monkeypatch.setattr(R, "_llm_trace", lambda *a, **k: None)
    monkeypatch.setattr("assistant.engine.llm.call_json", lambda *a, **k: ({"choice": "A"}, 1))

    def read():
        seen.update(P._SAMPLING.get())
        return A
    R._second_opinion(A, read, item, st, None, None)
    assert seen["temperature"] == R._SC_TEMPERATURE and "seed" in seen
    assert P._SAMPLING.get() == {}                  # and it does not leak
