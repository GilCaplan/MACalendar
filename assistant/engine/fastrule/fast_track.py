"""The FAST TRACK — the whole-command front door, before any Item exists.

    fast_propose(state, cfg) -> bool

This is NOT the FastRule stage. The stage is `stage.run`: `List[Item]` in,
committable objects out (`build.py`). This is the other thing the folder owns —
the instant path, where a confident rule parse of the WHOLE utterance commits
without the deep track running at all.

**Why `Atomicity` belongs here and not in the converter** (PLAN.md §2c). At the
front door there is no Item yet, so *"is this one ask or several?"* is exactly
the right question to ask, and `FastRule` asks it. By the time the deep track
reaches `build`, the item is atomic **by contract** — segmentation and
decompose_validate have already split it — so asking again is re-deciding a
question another component already answered, on worse evidence. That was the
single largest piece of the old per-item path, and removing it is most of what
"stop redoing the upstream's work" means for this stage.

On a decline the work is not wasted: `state.fastrule_verdict` carries the
reason, its class and the confidence forward, and segment uses it as both
evidence and prompt grounding (Gil's ruling).
"""
from __future__ import annotations

from assistant.engine.state import EngineState, Item


def kind_for(action_name: str) -> str:
    """The registry action name -> the Item kind segmentation would have given
    it. Only the fast track needs this: it builds Items FROM intents, which is
    the one direction where the kind is not already known."""
    if "todo" in action_name:
        return "task"
    if "event" in action_name:
        return "event"
    if "query" in action_name or "schedule" in action_name:
        return "review"
    return "other"


def _fast_item_words(intent, whole: str) -> str:
    """The words THIS fast intent can honestly claim, not the whole command.

    Ported from `fastrule/objects.py` (deleted with the restructure, TASKS.md
    row 91) rather than dropped: every fast item used to be built with
    `text=state.text`, so a two-ask command committed on the fast path
    produced two items both carrying the entire utterance.
    `llmjudge._produced` tokenizes `it.text` into the set it matches asks
    against, so both items presented the same token set — every ask
    overlapped every item and `_overlap` could not tell them apart. The fast
    track commits BEFORE the judge runs, so the discrimination was worst
    exactly where it matters most.

    FastRule returns intents, not spans, so the item's own words cannot be
    recovered from the parse — but the title is what the intent claims those
    words said, and it is what every reader of `item.text` on this path
    actually wants. `titles` first: a fast `create_todo` carries every title
    in ONE intent ("milk, eggs and bread"), and one of the three is not the
    item.

    Falls back to the whole command when the intent names nothing — a
    `query_schedule` has no title, and there the old behaviour was right.
    """
    titles = [t for t in (getattr(intent, "titles", None) or []) if t]
    if titles:
        return ", ".join(titles)
    for field in ("title", "match_title"):
        value = (getattr(intent, field, None) or "").strip()
        if value:
            return value
    return whole


def fast_propose(state: EngineState, cfg) -> bool:
    """Whole-command fast track: FastRule at RULE_THRESHOLD (the conservative
    front-door instance; the deep track is its net). A thin adapter — the
    parser + gates + threshold live in `fastrule.FastRule`."""
    from assistant.intent.rule_parser import RULE_THRESHOLD
    from assistant.engine.fastrule.fastrule import FastRule, reason_class
    from assistant.trace import RULE

    res = FastRule(RULE_THRESHOLD).run(state.text, state.current_view)
    state.rule_confidence = res.confidence

    if res.committed:
        state.items = [
            Item(id=f"item_{i + 1}", kind=kind_for(name),
                 text=_fast_item_words(intent, state.text),
                 action=name, intent=intent)
            for i, (name, intent) in enumerate(res.intents)
        ]
        state.parse_path = "fast"
        if state.trace:
            state.trace.step(RULE, "Rule parser",
                             f"Confident ({res.confidence:.2f}) — instant: "
                             + ", ".join(n for n, _ in res.intents),
                             confidence=round(res.confidence, 2),
                             actions=[n for n, _ in res.intents])
        return True

    # Declined — but the work is not wasted: what FastRule concluded travels
    # forward as context for the deep track's LLM stages (Gil's ruling).
    state.fastrule_verdict = {
        "reason": res.reason,
        "reason_class": reason_class(res.reason),
        "confidence": res.confidence,
        "actions": [n for n, _ in res.intents],
    }
    if state.trace:
        state.trace.step(RULE, "Rule parser",
                         f"({res.confidence:.2f}) {res.reason} — deep track",
                         confidence=round(res.confidence, 2),
                         missing=res.missing_slots)
    return False
