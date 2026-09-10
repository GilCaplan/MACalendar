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
        "raw_text", "source", "current_view", "supports_edit",
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
    import assistant.engine.segmentation.old_seg.segment
    import assistant.engine.ingest.repair
    import assistant.engine.decompose_validate.stage

    for mod in (assistant.engine.ingest.repair, assistant.engine.segmentation.old_seg.segment,
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
    assert params == ["text", "trace", "source", "current_view",
                      "trace_run", "supports_edit", "supports_confirm"], FROZEN


def test_crosscheck_blame_router_is_deterministic():
    """The model never picks the stage: mismatch type → stage is a fixed map,
    and every target is a real stage."""
    from assistant.engine.llmjudge.llmjudge import BLAME, MAX_REENTRIES
    assert set(BLAME) == {"missing", "extra", "wrong_fields", "format"}, FROZEN
    assert all(stage in STAGES for stage in BLAME.values()), FROZEN
    assert MAX_REENTRIES == 3, FROZEN
