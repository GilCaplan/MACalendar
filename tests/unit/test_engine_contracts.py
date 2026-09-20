"""The engine's frozen contracts, pinned.

A stage's input/output contract is designed once and then does not change at
any point of development — fixing a weak stage means improving its internals,
never reshaping what it receives or hands on. This file is the enforcement:
if a field or entry point here goes red, the change is a contract change, and
the answer is to revert it, not to update this file. (Adding a NEW field is a
deliberate contract extension: it requires updating DOCUMENTATION/ENGINE.md
in the same commit — the assertion failure text says so on purpose.)
"""

from __future__ import annotations

import pathlib

import dataclasses
import inspect

from assistant.engine import state as engine_state
from assistant.engine.state import (
    STAGES, ITEM_KINDS, CheckFinding, EngineState, ExecutedAction, Fix, Item,
)

FROZEN = "frozen contract — see DOCUMENTATION/ENGINE.md before touching this"


def _field_names(cls) -> set:
    return {f.name for f in dataclasses.fields(cls)}


def test_stage_roster_is_fixed():
    # Re-cut 2026-09-08 with the rewire (Gil's chain) — a DESIGN change, made
    # deliberately and recorded, not drift: decompose+validate became one box,
    # generate became fastrule, crosscheck became llmjudge, label moved into
    # commit. See assistant/engine/ARCHITECTURE.md.
    assert STAGES == (
        "ingest", "transcript", "segment", "decompose_validate",
        "fastrule", "llmjudge", "commit",
    ), FROZEN


def test_item_kinds_are_fixed():
    assert ITEM_KINDS == ("event", "task", "review", "other"), FROZEN


def test_engine_state_fields():
    assert _field_names(EngineState) == {
        # ingest
        "raw_text", "source",
        # `device` added 2026-09-10 (Gil): WHICH client, where `source` is only
        # what KIND of client. Two iPhones are two request streams and must
        # never be concatenated; `source` says "ios" for both. Contract
        # EXTENSION, recorded in DOCUMENTATION/ENGINE.md in the same change.
        "device",
        # `stream` added 2026-09-10 (Gil, "prevents malicious actors"): what the
        # server CONCLUDED, where `device` is what the client CLAIMED. A caller
        # can assert any device id, so the grouping identity must be the
        # post-verification one. Contract EXTENSION — ENGINE.md in the same change.
        "stream",
        "current_view", "supports_edit",
        "supports_confirm", "mode",
        # step 1
        "text", "corrections", "needs_edit",
        # steps 2/3
        "items",
        # commit
        "executed", "messages", "refresh",
        # step 6
        "findings", "retries", "mistakes", "asked_fastrule", "fastrule_verdict",
        # bookkeeping
        "fixes", "trace", "parse_path", "llm_ms", "rule_confidence",
        "ignored", "memory_id", "verify_token", "pending_id",
    }, FROZEN


def test_item_fields():
    assert _field_names(Item) == {
        # `time` added 2026-09-08 (Gil): segmentation returns
        # (action, time, tag), so the item carries the time separately instead
        # of leaving it buried in `text`. A deliberate contract change, not a
        # drift — see assistant/engine/segmentation/ARCHITECTURE.md.
        "id", "kind", "text", "time", "slots", "action", "intent", "blocked",
        "labels",
        # `source` added 2026-09-10 (Gil): the VERBATIM span this item was cut
        # from. A DELIBERATE contract extension, like `time` before it — the
        # reasoning is on the field in state.py and in DOCUMENTATION/ENGINE.md.
        #
        # It exists so a finished ask can be subtracted from the command
        # EXACTLY. `text` cannot: the time is split off it and
        # decompose_validate may repair its words, so it stops being a
        # substring of anything. Without a span the trim in X1' is something
        # the model is INSTRUCTED to do rather than something already done.
        "source",
    }, FROZEN


def test_fix_fields():
    assert _field_names(Fix) == {"stage", "rule", "before", "after", "note"}, FROZEN


def test_executed_action_fields():
    assert _field_names(ExecutedAction) == {
        "item_id", "action", "message", "ok", "record",
    }, FROZEN


def test_check_finding_fields():
    assert _field_names(CheckFinding) == {
        "type", "item_id", "detail", "blamed_stage",
    }, FROZEN


def test_every_stage_module_exposes_run():
    """One module per step, one public entry point: run(state, cfg) -> state.
    (ingest lives inside the orchestrator, so it has no module.)

    RECORDED MODULE RE-CUT, 2026-09-10 — the FastRule stage's module is now
    `fastrule.stage`, not `fastrule.objects`. This line is deliberately part of
    the frozen contract, so changing it is a design change and not a fix: it is
    written down here, in `fastrule/PLAN.md` §3 (phase B6) and in that stage's
    ARCHITECTURE.md, the same way the 2026-09-08 re-cut was.

    What changed is which module IS the stage, not the contract it satisfies.
    `objects.py` was four things at once — the per-item loop, the fast track,
    the LLM fallback and the engine's shared parser accessors — and only the
    first was ever the stage. The other three moved to `fastrule/fast_track.py`,
    `llmjudge/rescue.py` and `engine/llm.py`. `run(state, cfg) -> state` is
    unchanged, which is why this is a one-name edit and not a new contract.
    """
    import assistant.engine.llmjudge.llmjudge
    import assistant.engine.decompose_validate.decompose
    import assistant.engine.fastrule.stage
    import assistant.engine.label.label
    import assistant.engine.segmentation
    import assistant.engine.ingest.repair
    import assistant.engine.decompose_validate.stage

    for mod in (assistant.engine.ingest.repair, assistant.engine.segmentation,
                assistant.engine.decompose_validate.decompose, assistant.engine.decompose_validate.stage,
                assistant.engine.fastrule.stage, assistant.engine.llmjudge.llmjudge,
                assistant.engine.label.label):
        run = getattr(mod, "run", None)
        assert callable(run), f"{mod.__name__}.run missing — {FROZEN}"
        params = list(inspect.signature(run).parameters)
        assert params == ["state", "cfg"], f"{mod.__name__}.run{params} — {FROZEN}"


def test_validate_has_object_pass():
    """Step 4 runs twice by design: on items before generation, on generated
    objects after — both entry points are contract."""
    import assistant.engine.decompose_validate.stage as v
    params = list(inspect.signature(v.run_objects).parameters)
    assert params == ["state", "cfg"], FROZEN


def test_fastrule_owns_the_fast_track():
    """The whole-command front door. It moved to its own module on 2026-09-10
    (`fastrule/fast_track.py`) because it is NOT the stage: at the front door
    there is no Item yet, which is exactly why "one ask or several?" belongs
    there and nowhere else. The signature is unchanged."""
    import assistant.engine.fastrule.fast_track as g
    params = list(inspect.signature(g.fast_propose).parameters)
    assert params == ["state", "cfg"], FROZEN


def test_the_fastrule_stage_is_a_converter():
    """X3 -> X4 is `List[Item]` -> objects, and `build` is a PURE function of
    one item: no model, no database, no clock of its own. That purity is what
    makes the stage testable from a table, so it is worth pinning."""
    import inspect as _i
    from assistant.engine.fastrule.build import build, build_all
    assert list(_i.signature(build).parameters)[0] == "item"
    assert list(_i.signature(build_all).parameters)[0] == "items"


def test_orchestrator_signature():
    """The API server, the audit and the pending-retry loop all call this;
    its shape is the outermost contract."""
    from assistant.engine import run_transcript
    params = list(inspect.signature(run_transcript).parameters)
    # `device` added 2026-09-10 (Gil) beside `source`, which it completes
    # rather than replaces: source is what KIND of client, device is WHICH one.
    # Contract EXTENSION — DOCUMENTATION/ENGINE.md moves in the same change.
    # Safe in this position because no caller passes past `text` positionally
    # (checked); every one uses keywords.
    assert params == ["text", "trace", "source", "device", "stream",
                      "current_view", "trace_run", "supports_edit",
                      "supports_confirm"], FROZEN


def test_llmjudge_router_is_deterministic():
    """The model never picks the route or the stage: finding type → route is a
    fixed map, every finding type has one, and every blamed stage is real.

    RE-CUT 2026-09-10 (Gil): `missing` and `extra` are gone with the ask
    extraction — *"that defeats the point of what segmentation →
    decompose_validate → FastRule did"*. Every remaining finding is a statement
    about ONE OBJECT, checkable against the transcript alone, so the stage no
    longer needs a second opinion on how many asks a command contained.
    """
    from assistant.engine.llmjudge import findings as F
    from assistant.engine.llmjudge.llmjudge import MAX_REENTRIES

    types = {F.UNGROUNDED_SUBJECT, F.UNSUPPORTED_FIELD, F.NOT_AN_ASK,
             F.COORDINATED_SUBJECT, F.UNSPLIT_SUBJECT}
    assert set(F.ROUTE) == types, FROZEN
    assert set(F.BLAMED) == types, FROZEN
    assert set(F.ROUTE.values()) == {F.REWRITE, F.COMMIT_FLAGGED, F.PANEL}, FROZEN
    assert all(stage in STAGES for stage in F.BLAMED.values()), FROZEN
    # Only the SUBJECT earns a round. A rewrite cannot invent a value nobody
    # said, and an object nothing asks for is not made real by re-parsing —
    # both are the 2026-09-08 loop storm in code form. The COORDINATED subject
    # joined on 2026-09-20 (Gil): one event titled "dentist, haircut and gym"
    # is three, and the rewrite is one clause per thing in the speaker's own
    # words — still nothing invented, still the subject. The UNSPLIT subject
    # (same day): one object whose words still hold an ask seam; the
    # deterministic rewrite cannot split it, so it is what reaches the model
    # round of the rewrite.
    assert {t for t, r in F.ROUTE.items() if r == F.REWRITE} == {
        F.UNGROUNDED_SUBJECT, F.COORDINATED_SUBJECT, F.UNSPLIT_SUBJECT}, FROZEN
    assert MAX_REENTRIES == 3, FROZEN


def test_the_judge_makes_no_model_call_at_all():
    """The stage JUDGES deterministically. There is no model call left in it.

    Pinned because each removal was the design, not a cleanup, and both would be
    easy to restore helpfully:

    * `extract_asks` (gone 2026-09-10) re-derived segmentation's answer with an
      8B and then blamed segmentation for the disagreement.
    * `ground_claims` (gone the same day, Gil approved) asked the model to quote
      the words behind each field. It was **57% of every Ollama call the system
      made** and it changed no outcome — 32 hand-written cases score identically
      with and without it. Shown a title of "gym membership" the model quotes
      "gym session", the words behind the title the object SHOULD have had, and
      a non-`none` answer is an accepted one. `retired/llmjudge-grounding-call/`
      has the module and the ledger.

    `rescue.py` still calls a model and that is correct: parsing what FastRule
    DEFERRED is the model doing a parse, not judging one. So does `rewrite.py`
    since 2026-09-20 (Gil: *"the whole point of the loop is that the llm sends
    a fix if relevant as X1'"*) — and that is the LOOP-BACK writing X1' once
    the deterministic rewrite has nothing new, not the judge judging. The
    verdict stays model-free.
    """
    from assistant.engine.llmjudge import llmjudge, verdict
    assert not pathlib.Path("assistant/engine/llmjudge/evidence.py").exists(), FROZEN
    for mod in (llmjudge, verdict):
        src = pathlib.Path(mod.__file__).read_text()
        code = "\n".join(ln for ln in src.splitlines()
                          if not ln.lstrip().startswith("#"))
        assert "call_json" not in code, (
            f"{mod.__name__} calls the model again — {FROZEN}")
    import inspect
    assert list(inspect.signature(verdict.judge).parameters) == ["state", "produced"], (
        f"judge() grew a model argument back — {FROZEN}")
