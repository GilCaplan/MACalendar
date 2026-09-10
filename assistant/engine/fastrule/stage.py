"""The FastRule STAGE: X3 (items) -> X4 (objects ready to commit).

Gil's box:

    IN    List[Item]  — everything segmentation and decompose_validate worked out
    OUT   the objects the software accepts (CalendarIntent / CreateTodoIntent …)
    ELSE  a DEFER with a reason, handed to LLMJudge

**And it does not redo what those two already did.** Six of the ten fields an
object needs were decided upstream — `date`, `start_time`, `end_time`,
`recurrence`, `recur_days`, `recur_until` by decompose_validate, the kind and
the action words by segmentation. `build` COPIES them. What is genuinely left is
the OPERATION, the TITLE, the PEOPLE and the TARGET, and that is all this stage
reads for.

What that removed, when this file was rewritten on 2026-09-10:

    the whole fast track, re-run per item     Atomicity, Gatekeeper, Scorer on
                                              an item already atomic BY CONTRACT
    the date and time, re-read from the words  decompose_validate had resolved
                                              them; B1 measured it right on
                                              573/573 of the rows we deferred
    event-vs-task, re-decided and re-tried     segmentation's `tag` decided it

The model is no longer called from this stage at all. When `build` cannot
produce an object it returns a `Defer`, and `llmjudge.rescue` — which is where
the model lives — takes it from there, starting from the partial parse rather
than cold. That is the whole of *"if there's an issue it tells LLMVerify"*.

It ends by running decompose_validate's OBJECT pass. Those are that stage's
rules, not this one's; they run here only because they need `item.intent` to
exist, which is not true until this stage has run.
"""
from __future__ import annotations

from assistant.engine.decompose_validate import stage as _decompose_validate
from assistant.engine.fastrule.build import (
    Built, Defer, NotAnObject, build_all)
from assistant.engine.state import Item


#: WHICH BUILT OBJECTS THIS STAGE MAY COMMIT — a commit decision, deliberately
#: here and not in `build` (PLAN.md §2c: the converter has "no opinion about
#: whether to commit").
#:
#: Creates and queries only. A target-taking operation names an EXISTING
#: record, and knowing whether it names a REAL one needs a store lookup that
#: `build` cannot do — purity is the point of the converter, and
#: `_names_something_real` left with Gatekeeper in phase A. Committing one
#: unchecked is the expensive direction: the product-shape board weights a
#: wrong delete at 4 and a wrong update or complete at 2, against 1 for a
#: create. "set a reminder note for three o'clock" is the worked example — the
#: parser routes it to update_todo, and the model plus the task fallback turn
#: it into the create it actually is.
#:
#: This is a restriction with a reason and an owner, not a permanent shape;
#: phase C's board decides whether to lift it.
_COMMITTABLE = ("create", "query")


def _may_commit(action: str) -> bool:
    return action.split("_")[0] in _COMMITTABLE


def run(state, cfg):
    """X3 -> X4. Convert every Item, hand what could not convert to LLMJudge,
    then apply decompose_validate's field rules to the objects."""
    from assistant.trace import RULE

    items = list(getattr(state, "items", []) or [])
    results = build_all(items)

    pending: list = []          # [(item, Defer)] — LLMJudge's to answer
    built = flagged = 0
    for item, res in zip(items, results):
        if isinstance(res, NotAnObject):
            # A FLAG IS AN OUTCOME, not a gap. `blocked` is the frozen field
            # for exactly this — "refusal reason, never executed, reported
            # honestly" — and the orchestrator reports it before it skips an
            # empty intent, which is what made this silent before.
            item.action, item.intent = "unknown", None
            item.blocked = res.reason
            flagged += 1
            continue
        if isinstance(res, Built):
            if _may_commit(res.action):
                item.action, item.intent = res.action, res.intent
                # WHO MADE THIS OBJECT. Recorded rather than inferred: the
                # stage board needs the converter/model split, and inferring it
                # from which fixes fired is guesswork that would quietly
                # misreport the one number the restructure is judged on.
                if item.slots is None:
                    item.slots = {}
                item.slots["built_by"] = "rule"
                built += 1
                continue
            # Built, but not ours to commit — see _may_commit. It still goes to
            # the model, and the object we made is not thrown away: it rides
            # along as the partial so the model starts from it.
            pending.append((item, Defer("needs-target-check",
                                        fields={"action": res.action})))
            continue
        pending.append((item, res))

    if state.trace and (built or pending or flagged):
        state.trace.step(
            RULE, "Built the objects",
            f"{built} of {len(items)} converted"
            + (f"; {len(pending)} to the model" if pending else "")
            + (f"; {flagged} not an object" if flagged else ""))

    if pending:
        # THE ONLY REMAINING BACK-EDGE, and it points the right way: the stage
        # that produces DEFERs calls the stage that consumes them. It is a
        # function-local import so nothing resolves at import time.
        from assistant.engine.llmjudge import rescue as _rescue
        _rescue.rescue(state, cfg, pending)
        _expand(state)

    _decompose_validate.run_objects(state, cfg)
    return state


def _expand(state) -> None:
    """An item whose words parsed into SEVERAL intents becomes one sub-item per
    intent — per-item attribution is what keeps feedback from corrupting a
    neighbour (the row-75 lesson). The splice lives here because this stage
    owns the shape of `state.items`; `rescue` only reports what it found.
    """
    from assistant.engine.fastrule.fast_track import kind_for

    out: list = []
    for item in state.items:
        got = (item.slots or {}).pop("_expanded", None)
        if not got:
            out.append(item)
            continue
        for j, (name, intent) in enumerate(got, start=1):
            out.append(Item(id=f"{item.id}-{j}", kind=kind_for(name),
                            text=item.text, slots=dict(item.slots),
                            action=name, intent=intent))
    state.items = out
