"""The orchestrator: track selection, the needs_edit gate, honest refusals,
the offline queue, and the trivial filter.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import assistant.engine as engine
import assistant.engine.llm as engine_llm
import assistant.engine.fastrule.stage as generate
import assistant.engine.llmjudge.rescue as _rescue
import assistant.engine.fastrule.fast_track as fast_track
import assistant.stt.vocab as vocab_mod
from assistant.engine.state import EngineState, Item
from assistant.exceptions import OllamaUnavailableError


@pytest.fixture
def cfg():
    return engine.load_config()


def _fake_registry(monkeypatch, results):
    registry = MagicMock()

    def _get(name):
        cls = MagicMock()
        cls.return_value.execute.side_effect = results.get(name, ["done"])
        return cls

    registry.get.side_effect = _get
    monkeypatch.setattr(engine_llm, "get_registry", lambda: registry)
    return registry


# --- trivial ---------------------------------------------------------------

def test_a_false_start_is_ignored_and_not_remembered():
    out = engine.run_transcript("execute", source="test")
    assert out["parse"] == "ignored"
    assert out["memory_id"] is None
    assert out["actions"] == []


# --- track selection -------------------------------------------------------

def test_confident_rules_take_the_fast_track(monkeypatch, cfg):
    rr = SimpleNamespace(confidence=0.97, missing_slots=[],
                         intents=[("query_schedule", SimpleNamespace())])
    rp = MagicMock()
    rp.analyze.return_value = rr
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: rp)
    _fake_registry(monkeypatch, {"query_schedule": ["all clear"]})

    out = engine.run_transcript("what do I have today", source="test")
    assert out["parse"] == "fast"


def test_unconfident_rules_take_the_deep_track(monkeypatch):
    rr = SimpleNamespace(confidence=0.30, missing_slots=["start_time"], intents=[])
    rp = MagicMock()
    rp.analyze.return_value = rr
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: rp)
    parser = MagicMock()
    parser.parse.return_value = [("create_event", SimpleNamespace(title="x"))]
    parser.parse_with_context.side_effect = Exception("no context parse")
    parser.last_llm_ms = 3
    parser.last_examples_used = 0
    parser.last_raw_response = ""
    monkeypatch.setattr(engine_llm, "get_parser", lambda cfg: parser)
    _fake_registry(monkeypatch, {"create_event": ["made it"]})

    out = engine.run_transcript("do the thing with the stuff sometime", source="test")
    assert out["parse"] == "deep"
    assert out["actions"] == ["create_event"]


# --- the needs_edit gate ---------------------------------------------------

def _doubtful_vocab(monkeypatch):
    monkeypatch.setattr(vocab_mod, "apply_vocab", lambda text, source=None: (text, []))
    fake = MagicMock()
    fake.suggestions.return_value = [{"word": "noa", "suggestion": "Noa"}]
    monkeypatch.setattr(vocab_mod, "get_vocab", lambda: fake)


def test_gate_fires_only_for_capable_clients_with_the_setting_on(monkeypatch, cfg):
    _doubtful_vocab(monkeypatch)
    monkeypatch.setattr(cfg.engine, "confirm_transcript", True)
    monkeypatch.setattr(engine, "load_config", lambda: cfg)

    out = engine.run_transcript("call noa tomorrow at nine", source="test",
                                supports_edit=True)
    assert out["parse"] == "needs_edit"
    assert out["actions"] == []
    assert out["needs_edit"]


def test_gate_never_fires_for_an_old_client(monkeypatch, cfg):
    _doubtful_vocab(monkeypatch)
    monkeypatch.setattr(cfg.engine, "confirm_transcript", True)
    monkeypatch.setattr(engine, "load_config", lambda: cfg)
    rr = SimpleNamespace(confidence=0.97, missing_slots=[],
                         intents=[("query_schedule", SimpleNamespace())])
    rp = MagicMock()
    rp.analyze.return_value = rr
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: rp)
    _fake_registry(monkeypatch, {"query_schedule": ["all clear"]})

    out = engine.run_transcript("call noa tomorrow at nine", source="test",
                                supports_edit=False)
    assert out["parse"] != "needs_edit"


def test_gate_off_means_best_guess(monkeypatch, cfg):
    _doubtful_vocab(monkeypatch)
    monkeypatch.setattr(cfg.engine, "confirm_transcript", False)
    monkeypatch.setattr(engine, "load_config", lambda: cfg)
    rr = SimpleNamespace(confidence=0.97, missing_slots=[],
                         intents=[("query_schedule", SimpleNamespace())])
    rp = MagicMock()
    rp.analyze.return_value = rr
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: rp)
    _fake_registry(monkeypatch, {"query_schedule": ["all clear"]})

    out = engine.run_transcript("call noa tomorrow at nine", source="test",
                                supports_edit=True)
    assert out["parse"] != "needs_edit"


# --- honest refusals -------------------------------------------------------

def test_a_blocked_item_is_reported_never_silent(monkeypatch, cfg):
    _fake_registry(monkeypatch, {})
    st = EngineState(raw_text="gym saturday", text="gym saturday")
    st.items = [Item(id="item_1", kind="event", text="gym saturday",
                     action="create_event",
                     intent=SimpleNamespace(title="gym session"),
                     blocked="that lands on Shabbat (Saturday, Sep 5)")]
    engine._commit(st, cfg)
    assert any("didn't book" in m and "Shabbat" in m for m in st.messages)
    assert st.executed == []


# --- offline queue ---------------------------------------------------------

def test_llm_offline_queues_the_command(monkeypatch):
    monkeypatch.setattr(fast_track, "fast_propose", lambda state, cfg: False)
    monkeypatch.setattr(engine_llm, "is_reachable", lambda cfg: True)   # the row-92 gate: known-up here
    monkeypatch.setattr(generate, "run",
                        lambda state, cfg: (_ for _ in ()).throw(
                            OllamaUnavailableError("Ollama offline at localhost")))

    out = engine.run_transcript("book squash with Yuval next thursday at 8", source="test")
    assert out["parse"] == "error"
    assert "offline" in out["message"].lower() or "saved" in out["message"].lower()
    assert out.get("pending_id") is not None


def test_a_known_offline_model_skips_the_deep_track_walk(monkeypatch):
    """TASKS.md row 92 — the gate. Distinct from the test above: that one
    proves a failure discovered MID-walk still queues correctly; this one
    proves a Mac ALREADY known to be offline never starts the walk at all,
    which is the whole latency point of the fix (segmentation and
    decompose_validate can call the model too, not just this stage)."""
    walked = []
    monkeypatch.setattr(fast_track, "fast_propose", lambda state, cfg: False)
    monkeypatch.setattr(engine_llm, "is_reachable", lambda cfg: False)
    monkeypatch.setattr(generate, "run",
                        lambda state, cfg: walked.append(1) or state)

    out = engine.run_transcript("book squash with Yuval next thursday at 8", source="test")

    assert walked == [], "the deep track ran despite a known-offline model"
    assert out["parse"] == "error"
    assert "offline" in out["message"].lower()
    assert out.get("pending_id") is not None


# --- the gate's learning loop ----------------------------------------------

@pytest.fixture
def scratch_vocab(monkeypatch, tmp_path):
    """A private vocabulary store, so learning tests cannot touch the shared
    scratch one other tests read."""
    import assistant.stt.vocab as vocab_module
    path = str(tmp_path / "vocab.json")
    store = vocab_module.VocabStore(path=path)
    monkeypatch.setattr(vocab_module, "get_vocab", lambda: store)
    monkeypatch.setattr(vocab_module, "VOCAB_PATH", path)
    return store


def test_a_saved_edit_becomes_an_alias(scratch_vocab):
    from assistant.engine.ingest import repair as transcript
    pairs = transcript.learn_from_edit("call noga tomorrow at nine",
                                       "call Noa tomorrow at nine")
    assert pairs == [("noga", "Noa")]
    entry = next(e for e in scratch_vocab.entries if e.word == "Noa")
    assert "noga" in [a.lower() for a in entry.aliases]


def test_an_untouched_resubmit_whitelists_after_two_confirms(scratch_vocab):
    from assistant.engine.ingest import repair as transcript
    text = "meet Moxie at the park tomorrow"
    assert transcript.confirm_unchanged(text) == []          # first confirm
    promoted = transcript.confirm_unchanged(text)            # second
    assert promoted == ["Moxie"]
    assert any(e.word == "Moxie" for e in scratch_vocab.entries)
    # And the gate stays quiet about it from now on.
    assert not any(s["heard"] == "Moxie" for s in scratch_vocab.suggestions(text))


def test_the_endpoint_learns_and_bypasses_the_gate(scratch_vocab, monkeypatch, cfg):
    monkeypatch.setattr(cfg.engine, "confirm_transcript", True)
    monkeypatch.setattr(engine, "load_config", lambda: cfg)
    import assistant.api.server as server
    monkeypatch.setattr(server, "load_config", lambda *a, **k: cfg)
    rr = SimpleNamespace(confidence=0.97, missing_slots=[],
                         intents=[("query_schedule", SimpleNamespace())])
    rp = MagicMock()
    rp.analyze.return_value = rr
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: rp)
    _fake_registry(monkeypatch, {"query_schedule": ["all clear"]})

    app = server.create_app()
    client = app.test_client()
    body = client.post("/voice/text", json={
        "transcript": "call Noa tomorrow", "source": "test",
        "edited_from": "call noga tomorrow", "supports_edit": True,
    }).get_json()
    # The edit taught the alias AND the resubmission was not re-gated.
    assert body["parse"] != "needs_edit"
    entry = next(e for e in scratch_vocab.entries if e.word == "Noa")
    assert "noga" in [a.lower() for a in entry.aliases]


# --- step 0: ingest coalescing ---------------------------------------------

def test_coalesce_wraps_within_budget():
    got = engine.coalesce(["gym tomorrow at 7am", "buy milk"], max_tokens=300)
    assert got == ['("gym tomorrow at 7am")and("buy milk")']


def test_coalesce_overflow_runs_sequentially():
    texts = ["a" * 400, "b" * 400, "c" * 400]
    got = engine.coalesce(texts, max_tokens=150)
    assert got == texts                       # each too big to share a batch


def test_coalesce_single_input_is_unwrapped():
    assert engine.coalesce(["just one thing"], max_tokens=300) == ["just one thing"]


def test_the_wrapper_round_trips_through_segment(cfg):
    from assistant.engine.segmentation.old_seg import segment
    batch = engine.coalesce(["gym tomorrow at 7am", "buy milk"], max_tokens=300)[0]
    st = EngineState(raw_text=batch, text=batch)
    segment.run(st, cfg)
    assert [it.text for it in st.items] == ["gym tomorrow at 7am", "buy milk"]


def test_repeated_attempt_messages_fold_into_one(monkeypatch):
    """A loop-back that fails the same way each attempt must apologise once,
    not once per re-entry (found live: three identical "couldn't read"s)."""
    from assistant.exceptions import ParseError
    monkeypatch.setattr(fast_track, "fast_propose", lambda state, cfg: False)

    def failing_run(state, cfg):
        state.messages.append("Sorry, I couldn't read this part: “x”.")
        return state

    monkeypatch.setattr(generate, "run", failing_run)
    import assistant.engine.llmjudge.llmjudge as crosscheck

    def always_missing(state, cfg):
        from assistant.engine.state import CheckFinding
        state.findings = [CheckFinding(type="missing", item_id=None,
                                       detail="d", blamed_stage="segment")]
        return state

    monkeypatch.setattr(crosscheck, "run", always_missing)
    out = engine.run_transcript("add christmas thing to calendar", source="test")
    assert out["message"].count("couldn't read") == 1


def test_a_task_kind_item_never_parses_to_nothing(monkeypatch, cfg):
    from assistant.engine.state import EngineState, Item
    parser = MagicMock()
    parser.parse.return_value = [("unknown", SimpleNamespace())]
    parser.last_llm_ms = 1
    parser.last_examples_used = 0
    parser.last_raw_response = ""
    monkeypatch.setattr(engine_llm, "get_parser", lambda c: parser)
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: None)
    st = EngineState(raw_text="x", text="x")
    st.items = [Item(id="item_1", kind="task", text="submit the Haxaga grades")]
    generate.run(st, cfg)
    _rescue.take_deferrals(st, cfg)
    assert st.items[0].action == "create_todo"
    assert st.items[0].intent.titles == ["submit the Haxaga grades"]


def test_an_event_kind_item_gets_a_kind_primed_retry(monkeypatch, cfg):
    """The missing-event signature: segmentation says event, the parse says
    todo, and the event half used to die silently — tasks had a fallback,
    events didn't."""
    from assistant.engine.state import EngineState, Item
    parser = MagicMock()
    parser.parse.side_effect = [
        [("create_todo", SimpleNamespace(title="send calendar", titles=["send calendar"]))],
        [("create_event", SimpleNamespace(title="Brunch with James and Alice",
                                          date="2026-09-08", start_time="11:00",
                                          end_time="12:00"))],
    ]
    parser.last_llm_ms = 1
    parser.last_examples_used = 0
    parser.last_raw_response = ""
    monkeypatch.setattr(engine_llm, "get_parser", lambda c: parser)
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: None)
    st = EngineState(raw_text="x", text="x")
    st.items = [Item(id="item_1", kind="event",
                     text="send a calendar invite to James and Alice for brunch at 11 am")]
    generate.run(st, cfg)
    _rescue.take_deferrals(st, cfg)
    assert st.items[0].action == "create_event"
    assert parser.parse.call_args_list[1][0][0].startswith("set an event: ")
    assert "event_kind_retry" in [f.rule for f in st.fixes]


def test_a_confident_event_parse_is_not_retried(monkeypatch, cfg):
    from assistant.engine.state import EngineState, Item
    parser = MagicMock()
    parser.parse.return_value = [("create_event", SimpleNamespace(
        title="gym", date="2026-09-08", start_time="07:00", end_time="08:00"))]
    parser.last_llm_ms = 1
    parser.last_examples_used = 0
    parser.last_raw_response = ""
    monkeypatch.setattr(engine_llm, "get_parser", lambda c: parser)
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: None)
    st = EngineState(raw_text="x", text="x")
    st.items = [Item(id="item_1", kind="event", text="gym tuesday at 7am")]
    generate.run(st, cfg)
    _rescue.take_deferrals(st, cfg)
    assert parser.parse.call_count == 1


def test_the_brain_version_is_stamped_on_every_command(monkeypatch, cfg):
    """The panel matches its chain-of-thought render format to this key, so it
    must be present on both the response (iOS reads it) and the trace-bus
    payload (the HUD reads it). Losing it silently would make the panel fall
    back to a generic render."""
    from assistant.trace import BRAIN_VERSION
    rr = SimpleNamespace(confidence=0.97, missing_slots=[],
                         intents=[("query_schedule", SimpleNamespace())])
    rp = MagicMock(); rp.analyze.return_value = rr
    monkeypatch.setattr(engine_llm, "get_rule_parser", lambda: rp)
    _fake_registry(monkeypatch, {"query_schedule": ["clear"]})
    out = engine.run_transcript("what do I have today", source="test")
    assert out["brain"] == BRAIN_VERSION


def test_the_diagram_chain_labels_exist_for_this_version():
    """CHAINS is the single spec the panel and the explorer diagram share."""
    from assistant.trace import BRAIN_VERSION, CHAINS
    assert BRAIN_VERSION in CHAINS
    stages = {s for s, _label in CHAINS[BRAIN_VERSION]}
    from assistant.trace import VOCAB, RULE, VALIDATE, LLM, EXECUTE, VERIFY, DONE
    assert stages <= {VOCAB, RULE, VALIDATE, LLM, EXECUTE, VERIFY, DONE}


# --- cycle 3: the fast-path compound gate ----------------------------------

def _rp(intents, confidence=0.99):
    rr = SimpleNamespace(confidence=confidence, missing_slots=[], intents=intents)
    rp = MagicMock()
    rp.analyze.return_value = rr
    return rp


def test_a_strong_joiner_with_one_intent_refuses_the_fast_commit(monkeypatch, cfg):
    """Cycle 3 of the dataset loop: '…at 9am, and then Remind me…' was
    confidently committed as todos, one literally titled "then". A
    single-intent parse of two-request wording takes the deep track,
    whatever its confidence."""
    from assistant.engine.state import EngineState
    monkeypatch.setattr(engine_llm, "get_rule_parser",
                        lambda: _rp([("create_todo", SimpleNamespace())]))
    st = EngineState(raw_text="", text="remind me to meet James at work tomorrow "
                                       "at 9am, and then remind me of my meeting")
    assert fast_track.fast_propose(st, cfg) is False


def test_a_plain_and_still_commits_fast(monkeypatch, cfg):
    from assistant.engine.state import EngineState
    monkeypatch.setattr(engine_llm, "get_rule_parser",
                        lambda: _rp([("create_event", SimpleNamespace())]))
    st = EngineState(raw_text="", text="meeting with Tal and Ravid at Kems "
                                       "tomorrow at 7")
    assert fast_track.fast_propose(st, cfg) is True
    assert st.parse_path == "fast"


def test_a_two_intent_parse_keeps_fast_despite_a_joiner(monkeypatch, cfg):
    """When the rule parser itself read TWO requests, it did not swallow the
    compound — the gate must not slow it."""
    from assistant.engine.state import EngineState
    monkeypatch.setattr(engine_llm, "get_rule_parser",
                        lambda: _rp([("create_event", SimpleNamespace()),
                                     ("create_todo", SimpleNamespace())]))
    st = EngineState(raw_text="", text="book gym at 7. Also, add milk to my list")
    assert fast_track.fast_propose(st, cfg) is True


def test_fastrule_work_travels_forward_when_it_declines(registry_with_real_actions):
    """Gil's ruling: on a non-atomic command FastRule still does the work —
    it just doesn't commit, and what it concluded goes to the next stage as
    context for the LLM stages. It used to be discarded on defer, so the
    deep track started cold on a command that had already been read once."""
    from assistant.engine import load_config
    from assistant.engine.fastrule import fast_track as generate
    from assistant.engine.state import EngineState

    st = EngineState(raw_text="book the gym at 6 and remind me to buy milk",
                     text="book the gym at 6 and remind me to buy milk",
                     source="test")
    assert fast_track.fast_propose(st, load_config()) is False   # a compound
    v = st.fastrule_verdict
    assert v and v["reason"], "the verdict must survive the deferral"
    assert v["reason_class"] == "structure"      # "this is more than one item"
    assert 0.0 <= v["confidence"] <= 1.0


def test_background_verify_is_silent_in_measurement_runs(monkeypatch):
    """MACALENDAR_NO_WARMUP is the project's no-daemon-threads flag; this
    spawn site ignored it and fired an LLM call per fast-committed row,
    which the sealed-test eval saw as p95 136s (engine audit P8)."""
    import assistant.engine as engine
    from assistant.engine.state import EngineState
    spawned = []
    monkeypatch.setattr(engine.threading, "Thread",
                        lambda *a, **k: spawned.append(k) or type(
                            "T", (), {"start": lambda self: None})())
    st = EngineState(raw_text="buy milk", text="buy milk", source="test")
    engine._start_background_verify(st, engine.load_config())
    assert spawned == []


# --- the judge loop: judge once unless a re-run actually happened -----------

def _counting_judge(state_findings):
    """A stand-in for the llmjudge Stage that counts calls and re-publishes
    the same findings each time — which is what the real one does when
    nothing upstream has changed."""
    calls = []

    class _Fake:
        def run(self, state, cfg):
            calls.append(1)
            state.findings = list(state_findings)
            return state

    return _Fake(), calls


def _missing(stage="fastrule"):
    """A loopable finding. `type="missing"` is GONE with the ask-list judge
    (2026-09-10, `llmjudge/findings.py`): `ungrounded_subject` is what now
    routes to REWRITE — the only route `_loop_target` treats as earning a
    round (`findings.ROUTE`). `blamed_stage` is a free field on the
    synthetic finding here (real ones get it from `findings.BLAMED`, fixed
    per type); `_loop_target`'s actual target is always "segment" regardless."""
    from assistant.engine.state import CheckFinding
    return [CheckFinding(type="ungrounded_subject", item_id=None,
                         detail="the words ask for a task — “buy milk” — "
                                "but nothing produced covers it",
                         blamed_stage=stage)]


def test_a_clean_judgement_runs_the_model_once(cfg):
    eng = engine.Engine()
    eng.llmjudge, calls = _counting_judge([])
    st = EngineState(raw_text="buy milk", text="buy milk", source="test")
    st.items = [Item(id="item_1", kind="task", text="buy milk")]

    eng.judge(st, cfg)
    assert len(calls) == 1


def test_an_unrewritable_complaint_does_not_judge_twice(monkeypatch, cfg):
    """With reentries == 0 (no re-run happened — whether because the rewrite
    declined or, before it went live, because it was a stub), the state has
    not changed since the judge ran above, so judging it again pays a second
    schema-constrained LLM extraction for an identical answer, on the rows
    that are already the slowest."""
    eng = engine.Engine()
    eng.llmjudge, calls = _counting_judge(_missing())
    # The rewrite is real now (2026-09-10), not always a stub — this test is
    # specifically the case where it DECLINES, so that has to be forced rather
    # than assumed.
    monkeypatch.setattr(engine._crosscheck, "rewrite_for_retry",
                        lambda state, cfg: None)
    st = EngineState(raw_text="buy milk", text="buy milk", source="test")
    st.items = [Item(id="item_1", kind="task", text="buy milk")]

    eng.judge(st, cfg)

    assert len(calls) == 1, "no re-run happened, so the first judgement stands"
    # the honest warning still reaches the speaker
    assert any("every part of that" in m for m in st.messages)


def test_a_real_re_run_is_judged_before_it_commits(monkeypatch, cfg):
    """The counterpart, and the reason the post-loop judge exists at all: once
    a rewrite DOES re-parse, the objects about to be committed are not the
    ones the last judgement described, so they must be judged again."""
    eng = engine.Engine()
    eng.llmjudge, calls = _counting_judge(_missing("segment"))
    monkeypatch.setattr(engine._crosscheck, "rewrite_for_retry",
                        lambda state, cfg: "buy milk")
    monkeypatch.setattr(eng, "parse", lambda state, cfg, **kw: None)
    st = EngineState(raw_text="buy milk", text="buy milk", source="test")
    st.items = [Item(id="item_1", kind="task", text="buy milk")]

    eng.judge(st, cfg)

    # two rounds inside the loop, then the parse that will actually commit
    assert len(calls) == 3
    assert st.retries.get("segment") == 1


# ---------------------------------------------------------------------------
# ONE STREAM PER SOURCE (Gil, 2026-09-10)
# ---------------------------------------------------------------------------

def test_coalesce_groups_map_back_to_their_rows():
    """The group IS the row mapping. The previous code re-derived the batch size
    by counting ")and(" in the RENDERED string, which desynchronises the moment
    a transcript contains that literal — and then the wrong pending row gets
    marked done."""
    from assistant.engine.ingest.coalesce import coalesce_groups, wrap

    texts = ["book gym at 7", 'weird )and( text', "buy milk"]
    groups = coalesce_groups(texts, max_tokens=300)
    assert groups == [texts]                       # one batch, three members
    rendered = wrap(groups[0])
    # The naive count would say FOUR commands went in. The group says three.
    assert rendered.count(")and(") == 3
    assert len(groups[0]) == 3


def test_the_retry_loop_never_mixes_two_sources():
    """A `test` sandbox's queued words must never be concatenated with a real
    phone command — the sandbox's prompt would execute on the real calendar, and
    the batch would be attributed to one source, defeating weekly_review's
    test-traffic filter.

    `pending.source` was recorded on every row all along and simply never read
    by the retry loop."""
    from assistant.api.server import retry_pending_once

    rows = [
        {"id": 1, "source": "ios",  "transcript": "book gym at 7",     "attempts": 0},
        {"id": 2, "source": "test", "transcript": "delete everything", "attempts": 0},
        {"id": 3, "source": "ios",  "transcript": "buy milk",          "attempts": 0},
        {"id": 4, "source": "mac",  "transcript": "call the dentist",  "attempts": 0},
    ]
    resolved: list = []

    class _Mem:
        def pending(self): return list(rows)
        def resolve_pending(self, rid, status, result=""): resolved.append((rid, status))
        def bump_pending(self, rid): pass

    seen: list = []

    def _run(text, **kw):
        seen.append((kw.get("source"), text))
        return {"parse": "fast", "message": "ok"}

    assert retry_pending_once(_run, _Mem(), 300) == 3      # one batch per source

    by_source = dict(seen)
    assert set(by_source) == {"ios", "test", "mac"}
    # The two iOS commands DID coalesce with each other — that is the feature.
    assert "gym" in by_source["ios"] and "milk" in by_source["ios"]
    # …and nothing crossed a source boundary.
    assert "delete everything" not in by_source["ios"]
    assert "gym" not in by_source["test"] and "milk" not in by_source["test"]
    assert by_source["mac"] == "call the dentist"
    assert {r for r, _ in resolved} == {1, 2, 3, 4}


def test_two_different_iphones_are_never_spoken_as_one_utterance():
    """THE DEFECT `source`-GROUPING COULD NOT SEE (Gil, 2026-09-10).

    *"each device is its own unique requests; two different iphones or my
    laptop that send requests should be queued; the same device can merge."*

    `source` is "ios" for every iPhone on the tailnet, so the flush treated all
    of them as ONE stream: two people's queued commands were concatenated into
    ("a")and("b") and parsed as one person speaking. Nothing about the old test
    above could catch it — both phones pass every assertion it makes.
    """
    from assistant.api.server import retry_pending_once

    rows = [
        {"id": 1, "source": "ios", "device": "phone-A",
         "transcript": "book gym at 7", "attempts": 0},
        {"id": 2, "source": "ios", "device": "phone-B",
         "transcript": "cancel my dentist", "attempts": 0},
        {"id": 3, "source": "ios", "device": "phone-A",
         "transcript": "buy milk", "attempts": 0},
    ]

    class _Mem:
        def pending(self): return list(rows)
        def resolve_pending(self, rid, status, result=""): pass
        def bump_pending(self, rid): pass

    seen: list = []

    def _run(text, **kw):
        seen.append((kw.get("source"), text))
        return {"parse": "fast", "message": "ok"}

    assert retry_pending_once(_run, _Mem(), 300) == 2      # one batch PER PHONE

    texts = [t for _src, t in seen]
    a = next(t for t in texts if "gym" in t)
    b = next(t for t in texts if "dentist" in t)
    # phone A's two commands merged with each other — that is the feature.
    assert "milk" in a
    # …and phone B's never joined them, in either direction.
    assert "dentist" not in a
    assert "gym" not in b and "milk" not in b
    # Both batches are still attributed to the SOURCE the engine understands.
    # `EngineState.source` is "mac"|"ios"|"test"; a stream key like "ios:phone-A"
    # is not one of them, and passing the key through would put an unknown
    # source on every trace, vocabulary correction and memory row — which is the
    # value `weekly_review.py` filters test traffic on.
    assert {src for src, _ in seen} == {"ios"}


def test_the_same_phone_still_merges_after_the_split():
    """The split must not cost the feature it was protecting: one device's
    backlog is one person's, and coalescing it into one parse is the point."""
    from assistant.api.server import retry_pending_once

    rows = [{"id": i, "source": "ios", "device": "phone-A",
             "transcript": t, "attempts": 0}
            for i, t in enumerate(("buy milk", "call Sam", "book gym"), start=1)]

    class _Mem:
        def pending(self): return list(rows)
        def resolve_pending(self, rid, status, result=""): pass
        def bump_pending(self, rid): pass

    seen: list = []
    assert retry_pending_once(lambda text, **kw: (seen.append(text),
                                                  {"parse": "fast", "message": "ok"})[1],
                              _Mem(), 300) == 1
    assert len(seen) == 1
    for word in ("milk", "Sam", "gym"):
        assert word in seen[0]
    # The wrapper is the deterministic one segmentation knows how to split.
    assert seen[0].count(")and(") == 2


def test_a_client_that_sends_no_device_id_behaves_exactly_as_before():
    """Old clients must keep working. With no id, grouping degrades to source —
    a Mac still never merges with a phone, and two silent phones merge as they
    always did. Worse than knowing which phone, better than today, and pinned
    here so the degradation is a decision rather than a surprise."""
    from assistant.api.server import retry_pending_once

    rows = [
        {"id": 1, "source": "ios", "device": "", "transcript": "buy milk", "attempts": 0},
        {"id": 2, "source": "ios", "device": "", "transcript": "book gym", "attempts": 0},
        {"id": 3, "source": "mac", "device": "", "transcript": "call Sam", "attempts": 0},
    ]

    class _Mem:
        def pending(self): return list(rows)
        def resolve_pending(self, rid, status, result=""): pass
        def bump_pending(self, rid): pass

    seen: list = []
    assert retry_pending_once(lambda text, **kw: (seen.append((kw.get("source"), text)),
                                                  {"parse": "fast", "message": "ok"})[1],
                              _Mem(), 300) == 2
    by_source = dict(seen)
    assert "milk" in by_source["ios"] and "gym" in by_source["ios"]
    assert by_source["mac"] == "call Sam"


def test_rows_written_before_the_device_column_existed_still_flush():
    """A live queue has rows from before the migration. They carry no `device`
    key at all — not an empty one — and the flush must not raise on them."""
    from assistant.api.server import retry_pending_once

    rows = [{"id": 1, "source": "ios", "transcript": "buy milk", "attempts": 0}]

    class _Mem:
        def pending(self): return list(rows)
        def resolve_pending(self, rid, status, result=""): pass
        def bump_pending(self, rid): pass

    seen: list = []
    assert retry_pending_once(lambda text, **kw: (seen.append(text),
                                                  {"parse": "fast", "message": "ok"})[1],
                              _Mem(), 300) == 1
    assert seen == ["buy milk"]


def test_a_single_queued_command_is_not_wrapped():
    """One command from one source is passed through untouched — the ("…")and(…)
    wrapper exists for BATCHES and would otherwise be noise segmentation has to
    undo."""
    from assistant.api.server import retry_pending_once

    class _Mem:
        def pending(self):
            return [{"id": 1, "source": "ios", "transcript": "book gym at 7",
                     "attempts": 0}]
        def resolve_pending(self, *a, **k): pass
        def bump_pending(self, *a, **k): pass

    seen: list = []
    retry_pending_once(lambda text, **kw: (seen.append(text), {"parse": "fast"})[1],
                       _Mem(), 300)
    assert seen == ["book gym at 7"]
