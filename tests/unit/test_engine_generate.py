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
    # Case-insensitive since 2026-09-20: "submit" joined the routing table, so
    # this row now builds through FastRule's parser, whose transcript is
    # lowercased — the same fast-path property every other title already had
    # ("movie at the lincoln amc theatre"). The fallback builder that used to
    # catch it kept the item's own casing. That the fast path drops a name's
    # capital is filed as its own defect; this test is about the title existing.
    assert [t.lower() for t in it.intent.titles] == ["submit the haxaga grades"]


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
    """A named target is not vetoed — which is what this test is for.

    The stub carries `new_date` because a real `UpdateEventIntent` always has
    the `new_*` fields and an update with all of them empty is now refused as
    `no-change` (it touches a record to no purpose). Without one the stub was
    indistinguishable from that, and this test would be asserting the opposite
    of what its name says."""
    from types import SimpleNamespace
    ok, st = _fast(monkeypatch, cfg, "move the gym meeting to friday",
                   [("update_event", SimpleNamespace(match_title="gym meeting",
                                                     new_date="2026-09-25"))])
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


def test_a_todo_title_the_words_never_said_is_dropped_too():
    """UNTIL 2026-09-20 this read `test_non_event_actions_never_guarded` and
    asserted the opposite: only events were guarded, so a to-do could carry
    any title the model liked. dev-100 showed what that buys — "make a list
    of thing I have to shop tomorrow" came back as **milk, eggs and bread**,
    a grocery list the speaker never dictated, and it survived every round of
    the loop because the judge can refuse a title but the rewrite cannot
    change what the parser returns. An object whose every title is invented
    is not an object."""
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="task", text="whatever garble")
    got = [("create_todo", SimpleNamespace(titles=["Unrelated Words"]))]
    assert guards._guard_inventions(got, item, st) == []
    assert any("invention_guard" in str(f) for f in st.fixes)


def test_a_todo_keeps_the_titles_that_were_spoken():
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="task", text="add milk and eggs to my list")
    intent = SimpleNamespace(titles=["milk", "eggs", "bread"], quantities=[1, 1, 1])
    assert guards._guard_inventions([("create_todo", intent)], item, st)
    assert intent.titles == ["milk", "eggs"] and intent.quantities == [1, 1]


def test_an_invented_field_is_stripped_and_the_event_kept():
    """A fabricated SUBJECT means there is no object; a fabricated VALUE on a
    real one is a bad field — the same asymmetry the judge routes on. The
    rescue put 'Grocery List Review' AT HOME and made "reopen groceries and
    add milk" a DAILY event (dev-100, 2026-09-20)."""
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="event", text="reopen groceries and add milk")
    intent = SimpleNamespace(title="reopen groceries", location="Home",
                             recurrence="daily", recur_days=["monday"])
    kept = guards._guard_inventions([("create_event", intent)], item, st)
    assert kept, "the event itself was the speaker's"
    assert intent.location is None and intent.recurrence is None
    assert intent.recur_days == []


def test_a_repeat_the_words_asked_for_survives():
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="event",
                text="book standup at the conference room every tuesday")
    intent = SimpleNamespace(title="standup", location="conference room",
                             recurrence="weekly", recur_days=["tuesday"])
    assert guards._guard_inventions([("create_event", intent)], item, st)
    assert intent.recurrence == "weekly" and intent.location == "conference room"
    assert not st.fixes


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
# The model going away MID-COMMAND must not discard a sibling it already
# answered (TASKS.md row 92)
# ---------------------------------------------------------------------------
#
# `rescue()` used to re-raise LLMUnavailableError/LLMTimeoutError straight out
# of its per-item loop ("the orchestrator owns offline queueing") — which
# unwound past `_commit()` in the orchestrator, so a batch where the model
# answered item 1 and then dropped on item 2 lost item 1 too, not just item 2.

def test_a_sibling_the_model_already_answered_still_commits(monkeypatch, cfg):
    from assistant.engine.llmjudge import rescue
    from assistant.exceptions import LLMUnavailableError

    calls = []

    def _flaky(item, state, cfg, verdict):
        calls.append(item.id)
        if item.id == "item_2":
            raise LLMUnavailableError("Ollama offline at http://localhost:11434")
        return [("create_todo", type("I", (), {"title": "buy milk",
                                                "titles": None})())]
    monkeypatch.setattr(rescue, "_ask_the_model", _flaky)

    st = EngineState(raw_text="buy milk and something else", text="buy milk and something else")
    st.items = [
        Item(id="item_1", kind="task", text="buy milk",
            slots={"fastrule_defer": {"reason": "below-threshold", "reason_class": "incapacity"}}),
        Item(id="item_2", kind="task", text="something else",
            slots={"fastrule_defer": {"reason": "below-threshold", "reason_class": "incapacity"}}),
    ]

    rescue.take_deferrals(st, cfg)   # must not raise

    assert calls == ["item_1", "item_2"], calls
    resolved = next(it for it in st.items if it.id == "item_1")
    assert resolved.action == "create_todo", "the item the model DID answer must still commit"
    unresolved = next(it for it in st.items if it.id == "item_2")
    assert unresolved.action is None
    assert any("something else" in m for m in st.messages)


def test_a_third_item_is_not_individually_retried_once_the_model_is_gone(monkeypatch, cfg):
    """Once unreachable, the remaining items are marked unread rather than
    each paying their own timeout for an identical failure."""
    from assistant.engine.llmjudge import rescue
    from assistant.exceptions import LLMTimeoutError

    calls = []

    def _flaky(item, state, cfg, verdict):
        calls.append(item.id)
        raise LLMTimeoutError("Ollama timed out")
    monkeypatch.setattr(rescue, "_ask_the_model", _flaky)

    st = EngineState(raw_text="a, b and c", text="a, b and c")
    st.items = [Item(id=f"item_{i}", kind="task", text=w,
                     slots={"fastrule_defer": {"reason": "below-threshold",
                                               "reason_class": "incapacity"}})
                for i, w in enumerate(("a", "b", "c"), start=1)]

    rescue.take_deferrals(st, cfg)

    assert calls == ["item_1"], (
        f"items after the first failure were asked again: {calls}")
    assert all(it.action is None for it in st.items)
    assert len(st.messages) == 3, "each unread item still gets its own honest apology"


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


def test_every_model_parse_in_the_rescue_runs_through_the_invention_guard():
    """A GUARD WITH A HOLE READS AS COVERED — the same lesson the ollama gate
    learned, in the same shape.

    `_guard_inventions` was widened on 2026-09-20 to strip invented locations,
    repeats and to-do titles, and a whole dev-100 run went by with it firing
    on NOTHING: the event-kind retry called `parser.parse(...)` and assigned
    the result straight to `got`, so the fabrications everyone could see
    ('Grocery List Review' AT HOME) came through the one door nobody had
    gated. This reads the tree rather than remembering, so the third door
    fails here instead of in a board six weeks later.
    """
    import pathlib
    import re

    src = pathlib.Path("assistant/engine/llmjudge/rescue.py").read_text()
    lines = src.splitlines()
    calls = [(i, ln) for i, ln in enumerate(lines)
             if re.search(r"\bparser\.parse(_with_context)?\(", ln)]
    assert calls, "no model parse found — did the rescue move?"
    ungated = []
    for i, ln in calls:
        window = "\n".join(lines[i:i + 12])
        if "_guard_inventions" not in window:
            ungated.append(f"rescue.py:{i + 1}  {ln.strip()[:60]}")
    assert not ungated, (
        "these model parses reach the engine without the invention guard:\n  "
        + "\n  ".join(ungated))


def test_the_command_frame_is_trimmed_off_a_model_title():
    """"Send me a reminder to pick up my dog from the groomer" came back as
    the whole sentence for a title, and every grounding test passes it — the
    words ARE the speaker's, sliced in the wrong place. Six of the thirteen
    junk titles left on dev-100 after cycle 29 were this shape."""
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="event",
                text="Send me a reminder to pick up my dog from the groomer at 1pm")
    intent = SimpleNamespace(title="Send me a reminder to pick up my dog from the groomer")
    assert guards._guard_inventions([("create_event", intent)], item, st)
    assert intent.title == "pick up my dog from the groomer"
    assert any("title_frame_trimmed" in str(f) for f in st.fixes)


def test_only_the_reminder_frames_are_trimmed():
    """`build._title_from_words` strips a much wider set of lead verbs, and
    measured against the 7,200's gold it would rewrite 206 titles the parser
    already had right — "book club" -> "club", "schedule a haircut" ->
    "haircut". These frames rewrite none of them."""
    from types import SimpleNamespace
    for text, title in (("book club on friday", "book club"),
                        ("schedule a haircut tomorrow", "schedule a haircut"),
                        ("set up the new laptop", "set up the new laptop")):
        st = EngineState(raw_text="x", text="x")
        item = Item(id="item_1", kind="event", text=text)
        intent = SimpleNamespace(title=title)
        guards._guard_inventions([("create_event", intent)], item, st)
        assert intent.title == title, (text, intent.title)
        assert not st.fixes


def test_a_title_that_is_ALL_FRAME_is_dropped():
    """UNTIL 2026-09-20 this asserted that "remind me" was LEFT for the
    names-nothing veto to judge, because trimming it would hand the veto a
    blank. The naming gate then reached this path too (cycle 33) and the
    answer is better: a title that is all frame names nothing, so the object
    goes here and the veto never has to see it."""
    from types import SimpleNamespace
    st = EngineState(raw_text="x", text="x")
    item = Item(id="item_1", kind="task", text="remind me")
    intent = SimpleNamespace(titles=["remind me"])
    assert guards._guard_inventions([("create_todo", intent)], item, st) == []
    assert any("invention_guard" in str(f) for f in st.fixes)
