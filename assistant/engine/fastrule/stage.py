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

**The model is not called from this stage at all** — not directly and not
transitively. When `build` cannot produce an object it returns a `Defer`, which
is written onto the item as `slots["fastrule_defer"]` and left there. LLMJudge
is the NEXT stage in the chain and picks them up at its own entry. That is the
whole of *"if there's an issue it tells LLMVerify"*, and it is a hand-off rather
than a call: this file used to reach forward into `llmjudge.rescue`, which
duplicated the orchestrator's ordering and made "no model here" untrue.

It ends by running decompose_validate's OBJECT pass. Those are that stage's
rules, not this one's; they run here only because they need `item.intent` to
exist, which is not true until this stage has run.
"""
from __future__ import annotations

from assistant.engine.decompose_validate import stage as _decompose_validate
from assistant.engine.fastrule.build import (
    BadItem, Built, Defer, NotAnObject, build_all)


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


#: How each flagged outcome reads on the review panel. The two are NOT the same
#: thing and must not collapse into one row: `bad_item` says an upstream stage
#: handed this part over damaged, `not_an_ask` says the part was read correctly
#: and simply is not calendar work. A user seeing "I skipped this" needs to know
#: which, because only one of them is a bug.
_FLAG_TITLES = {
    "bad_item":   "Arrived unusable",
    "not_an_ask": "Not a calendar ask",
}


def _flag(state, item, reason: str, kind: str) -> None:
    """Record a non-object outcome ON THE ITEM and IN THE TRACE.

    On the item so the orchestrator reports it to the speaker; in the trace so
    the review panel can DRAW it. Before this, a flagged item was invisible on
    both paths — the panel is downstream of the trace, so an outcome that emits
    no step cannot be shown however the panel is written.
    """
    item.action, item.intent = "unknown", None
    item.blocked = reason
    item.slots = dict(item.slots or {})
    item.slots["fastrule_result"] = kind
    if state.trace:
        from assistant.trace import RULE
        state.trace.step(RULE, _FLAG_TITLES.get(kind, "Not built"),
                         f"“{(item.text or '')[:48]}” — {reason}",
                         ok=(kind == "not_an_ask"),
                         fastrule_result=kind, item_id=item.id)


def run(state, cfg):
    """X3 -> X4. Convert every Item, hand what could not convert to LLMJudge,
    then apply decompose_validate's field rules to the objects."""
    from assistant.trace import RULE

    items = list(getattr(state, "items", []) or [])
    results = build_all(items)

    pending: list = []          # [(item, Defer)] — LLMJudge's to answer
    built = flagged = bad = 0
    for item, res in zip(items, results):
        if isinstance(res, BadItem):
            _flag(state, item, res.reason, "bad_item")
            # A BAD ITEM IS AN ANSWER (Gil): the stage reports what it was
            # handed rather than repairing it. Same carrier as a non-ask —
            # `blocked` — but a DIFFERENT reason, because the review panel
            # shows them differently and because the two mean different
            # things: this one says an upstream stage produced damage.
            bad += 1
            continue
        if isinstance(res, NotAnObject):
            _flag(state, item, res.reason, "not_an_ask")
            # A FLAG IS AN OUTCOME, not a gap. `blocked` is the frozen field
            # for exactly this — "refusal reason, never executed, reported
            # honestly" — and the orchestrator reports it before it skips an
            # empty intent, which is what made this silent before.
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

    if state.trace and (built or pending or flagged or bad):
        state.trace.step(
            RULE, "Built the objects",
            f"{built} of {len(items)} converted"
            + (f"; {len(pending)} to the model" if pending else "")
            + (f"; {flagged} not an ask" if flagged else "")
            + (f"; {bad} arrived unusable" if bad else ""))

    # THE DEFERS RIDE THE ITEM. They are not called forward: `llmjudge` is
    # already the NEXT STAGE in the chain, so this stage reaching into it was a
    # back-edge that duplicated the orchestrator's own ordering — and it meant a
    # stage advertised as model-free reached the model transitively.
    #
    # A DEFER is this item's RESULT, so the item is where it belongs; no new
    # EngineState field, and nothing frozen changes.
    for item, verdict in pending:
        item.slots = dict(item.slots or {})
        item.slots["fastrule_defer"] = {
            "reason": verdict.reason,
            "reason_class": verdict.reason_class,
            **(verdict.fields or {}),
        }
        item.slots["fastrule_result"] = "deferred"

    _decompose_validate.run_objects(state, cfg)
    return state
