"""X3 -> X4 — the FastRule stage's deterministic fallbacks.

The LLM paths live in tests/integration (Ollama guard); what's pinned here
is the honest-failure ladder: a task-kind item never parses to nothing
(task_fallback, run 12), and an event-kind item whose words literally ask
for an event/reminder with a grounded when becomes a default-titled event
instead of dying unknown (event_fallback, cycle 5) — while everything less
grounded stays unknown, because a guessed event is worse than none.

RETARGETED 2026-09-10, when `fastrule/objects.py` was dismantled. The
behaviour pinned here did not change; three modules now own what one did:

    the stage        fastrule/stage.py     List[Item] -> objects
    the front door   fastrule/fast_track.py  fast_propose
    the rescue       llmjudge/rescue.py    the model, the two fallbacks and
                                            the invention guard

The ladder is the same ladder; only its address moved.
"""

from __future__ import annotations

import pytest

import assistant.engine.fastrule.fast_track as fast_track
import assistant.engine.fastrule.stage as stage
import assistant.engine.llmjudge.rescue as rescue
import assistant.engine.llmjudge.llm_fallback as guards
from assistant.engine import load_config
from assistant.engine.state import EngineState, Item


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def dead_llm(monkeypatch):
    """The model comes back empty, so the deterministic ladder is what runs."""
    monkeypatch.setattr(rescue, "_ask_the_model",
                        lambda item, state, cfg, verdict: [])


def _run(text, kind, cfg):
    """The chain as the orchestrator runs it: FastRule converts, then LLMJudge
    answers what it deferred.

    Two calls, not one, since 2026-09-10 (B5): FastRule leaves a DEFER on the
    item and stops rather than reaching forward into llmjudge, because llmjudge
    is already the next stage. A test that calls only the first would be
    testing half a chain and would show the deterministic ladder never firing.
    """
    st = EngineState(raw_text=text, text=text)
    st.items = [Item(id="item_1", kind=kind, text=text)]
    stage.run(st, cfg)
    rescue.take_deferrals(st, cfg)
    return st.items[0]


# --- event_fallback: the grounded default-title event (cycle 5) ----------

def test_literal_event_ask_with_time_becomes_default_event(dead_llm, cfg):
    it = _run("Set reminder for three o'clock", "event", cfg)
    assert it.action == "create_event"
    assert it.intent.title == "Reminder"
    assert it.intent.start_time == "15:00"


def test_literal_event_ask_with_date_becomes_default_event(dead_llm, cfg):
    it = _run("please set event on Tuesday", "event", cfg)
    assert it.action == "create_event"
    assert it.intent.title == "Event"
    assert it.intent.date is not None


def test_no_literal_ask_stays_unknown(dead_llm, cfg):
    # An event-kind item with a when but no event/reminder word: defaulting a
    # title here would be invention, not grounding.
    it = _run("something on Tuesday maybe", "event", cfg)
    assert it.action is None


def test_no_grounded_when_stays_unknown(dead_llm, cfg):
    # The ask is literal but names no date and no time - a time is never
    # guessed (hypothesis #2's risk clause).
    it = _run("can you set an event for me", "event", cfg)
    assert it.action is None


def test_task_kind_never_takes_the_event_fallback(dead_llm, cfg):
    # "reminder" in a task-kind item's words must not turn it into an event;
    # the task fallback owns task-kind items.
    it = _run("set a reminder note for three o'clock", "task", cfg)
    assert it.action == "create_todo"


# --- task_fallback: pinned (run 12) --------------------------------------

def test_task_kind_item_never_parses_to_nothing(dead_llm, cfg):
    it = _run("submit the Haxaga grades", "task", cfg)
    assert it.action == "create_todo"
    assert it.intent.titles == ["submit the Haxaga grades"]


# --- fast-path generic-target veto (cycle 6) ------------------------------

class _StubRR:
    def __init__(self, intents):
        self.confidence = 0.95
        self.intents = intents
        self.missing_slots = []


class _StubParser:
    def __init__(self, intents):
        self._rr = _StubRR(intents)

    def analyze(self, text, current_view=None):
        return self._rr


def _fast(monkeypatch, cfg, text, intents):
    from types import SimpleNamespace
    from assistant.engine import llm as _llm
    monkeypatch.setattr(_llm, "get_rule_parser", lambda: _StubParser(intents))
    st = EngineState(raw_text=text, text=text)
    return fast_track.fast_propose(st, cfg), st


def test_mutation_on_a_bare_ask_noun_routes_deep(monkeypatch, cfg):
    from types import SimpleNamespace
    ok, st = _fast(monkeypatch, cfg, "set reminder at 3 pm",
                   [("update_todo", SimpleNamespace(match_title="reminder"))])
    assert ok is False          # the deep track (event_fallback) owns this


def test_mutation_on_a_real_target_still_fast(monkeypatch, cfg):
    from types import SimpleNamespace
    ok, st = _fast(monkeypatch, cfg, "move the gym meeting",
                   [("update_event", SimpleNamespace(match_title="gym meeting"))])
    assert ok is True and st.parse_path == "fast"


def test_creations_never_vetoed(monkeypatch, cfg):
    from types import SimpleNamespace
    ok, st = _fast(monkeypatch, cfg, "reminder tomorrow 9am take pills",
                   [("create_event", SimpleNamespace(title="take pills"))])
    assert ok is True


# --- invention guard (cycle 7) --------------------------------------------

def test_fabricated_title_is_dropped():
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="event",
                text="new scenario, time or calendar to new list")
    got = [("create_event", SimpleNamespace(title="New Event"))]
    assert guards._guard_inventions(got, item, st) == []
    assert any("invention_guard" in str(f) for f in st.fixes)


def test_paraphrased_title_survives_via_stems():
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="event", text="meet Dana tomorrow at noon")
    got = [("create_event", SimpleNamespace(title="Meeting with Dana"))]
    assert guards._guard_inventions(got, item, st) == got


def test_grounded_title_untouched():
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="event", text="dentist on Wednesday at noon")
    got = [("create_event", SimpleNamespace(title="Dentist"))]
    assert guards._guard_inventions(got, item, st) == got


def test_non_event_actions_never_guarded():
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="task", text="whatever garble")
    got = [("create_todo", SimpleNamespace(titles=["Unrelated Words"]))]
    assert guards._guard_inventions(got, item, st) == got


def test_the_deep_track_does_not_undo_a_refusal(monkeypatch, cfg):
    """The engine audit's headline: the per-item path re-implemented the
    commit test with BOTH gate layers omitted, so an item the front door had
    vetoed was re-committed here. A generic target must survive the deep
    track as an honest "I couldn't find it", not a guess."""
    from assistant.engine import run_transcript
    out = run_transcript("remove my reminder", source="test")
    assert out["actions"] == [], out


# --- the two non-object outcomes, and why they are named apart ------------
#
# Every other item leaves this stage as a calendar or to-do object. These two
# do not, and they are different KINDS of event: `not_an_ask` is the engine
# reading the words correctly and finding no calendar work in them;
# `bad_item` is an item that should have become something and could not.
# Both were recorded only in `state.fixes`, which nothing outside
# decompose_validate traces (ENGINE_AUDIT.md P6) — so the review panel built
# to expose exactly this showed a run that simply did nothing.

def _traced(text, kind, cfg, trace):
    from assistant.engine.state import EngineState, Item
    st = EngineState(raw_text=text, text=text, trace=trace)
    st.items = [Item(id="item_1", kind=kind, text=text)]
    return stage.run(st, cfg)


@pytest.fixture
def trace():
    from assistant.trace import Trace
    return Trace(source="test")


def _outcomes(trace):
    return [s.data.get("outcome") for s in trace.steps if s.data.get("outcome")]


def test_a_non_calendar_ask_says_so_on_the_trace(cfg, trace):
    _traced("play some music", "other", cfg, trace)
    assert _outcomes(trace) == ["not_an_ask"]


def test_a_correct_reading_is_not_marked_as_a_failure(cfg, trace):
    """`ok` is what the panel colours by, and amber on a correct reading is
    how "we don't do that here" starts looking like a bug."""
    _traced("play some music", "other", cfg, trace)
    step = next(s for s in trace.steps if s.data.get("outcome"))
    assert step.ok is True
    assert "item_1" == step.data.get("item_id")


def test_an_unreadable_item_is_marked_as_damage(cfg, trace):
    """"Damage" post-restructure means `build._why_unusable`: the item itself
    is malformed (no words at all), checked BEFORE parsing rather than caught
    from a parse exception — `build_all` now routes an exception during a
    real parse to a `Defer` (the model gets a chance to salvage it), not
    straight to `bad_item`. An empty-text item is the case nothing downstream
    can recover."""
    from assistant.engine.state import EngineState, Item
    st = EngineState(raw_text="", text="", trace=trace)
    st.items = [Item(id="item_1", kind="event", text="")]
    stage.run(st, cfg)
    step = next(s for s in trace.steps if s.data.get("outcome"))
    assert step.data["outcome"] == "bad_item"
    assert step.ok is False, "an upstream defect must not read as a clean step"
    assert "no action words" in step.detail


def test_the_two_outcomes_are_not_the_same_value(cfg):
    """They are rendered apart, so they must BE apart."""
    assert "not_an_ask" != "bad_item"


def test_an_ordinary_item_carries_no_outcome(dead_llm, cfg, trace):
    _traced("Set reminder for three o'clock", "event", cfg, trace)
    assert _outcomes(trace) == []


# ---------------------------------------------------------------------------
# GONE, not fixed: the per-item FastRule memo (`state.asked_fastrule`)
# ---------------------------------------------------------------------------
#
# This test pinned a real bug in `objects.py::_parse_item` — the memo was
# keyed on `item.text` (the action alone) while FastRule ran on
# `item.spoken()` (the action WITH its time), so "gym at 7" and "gym at 9"
# shared one key and the second item skipped FastRule on a verdict formed
# from a different time (second review session, 2026-09-11).
#
# There is nothing to port forward: `_parse_item` itself — "FastRule first,
# the LLM for what it can't", re-asked per item — is what the 2026-09-10
# restructure removed on purpose (`fastrule/stage.py`'s docstring: "the whole
# fast track, re-run per item... on an item already atomic BY CONTRACT").
# A deferred item now goes straight to the model (`llmjudge/rescue.py
# ::_ask_the_model`) with no FastRule recheck at all, so there is no
# redundant call left for a memo to guard against. `state.asked_fastrule`
# is still a field on `EngineState` (frozen contract) but nothing reads or
# writes it any more — confirmed by grep, not assumed.
