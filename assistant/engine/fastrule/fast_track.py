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
        # A date CHOSEN out of a range ("book yoga class next week") is asked
        # about rather than committed — Gil's ruling, 2026-09-17: ask instead of
        # guessing. The item carries the same `confirm_create` flag the
        # interrogative gate uses (DEVQA Q9), so the orchestrator's existing
        # `_confirm_proposal` offers it with the chosen DAY NAMED and nothing is
        # written until the speaker accepts. No model call: this is the fast
        # path, and the proposal is built from the rule parse.
        #
        # Two guards, both bought with a real failure mode:
        #   - only when the CLIENT can render the prompt, or a proposal is a
        #     dead end and the date would be lost again;
        #   - only on a SINGLE item, because a confirmation holds EVERYTHING —
        #     "book gym at 7 and yoga next week" would strand the booking
        #     behind a dialog about the yoga. Same guard the interrogative rule
        #     carries, for the same reason.
        ranged = getattr(res.rule_result, "range_dates", None)
        # A BARE 7 OR 8 is asked about too (Gil, 2026-09-20, DEVQA Q28), on
        # the same terms as a range date: the client must be able to render a
        # prompt, and only when the command is one item. Without a prompt the
        # hour resolves PM and the reply says so, which is what both tracks
        # have always done for 1 to 6.
        from assistant.engine.decompose_validate.resolve import bare_hour_is_ambiguous
        bare_hour = bare_hour_is_ambiguous(state.text or "")
        ask_first = (bool(ranged) or bare_hour is not None) \
            and state.supports_confirm and len(res.intents) == 1 \
            and all(n == "create_event" for n, _ in res.intents)
        base_slots: dict = {"confirm_create": True} if ask_first else {}
        if bare_hour is not None and not ask_first:
            base_slots["assumed_pm"] = bare_hour
        # A single item's SOURCE is the whole sentence. decompose_validate's
        # passed-clock rule reads the spoken words for a named day, and a fast
        # item's text is only its title — so "book haircut with Dana for this
        # morning" said after the default hour moved to TOMORROW: 20 of the
        # 1,200 train rows of Board D run as production (2026-09-26). With
        # several items the sentence would lend one item another's day, so
        # they keep none, as before.
        one = len(res.intents) == 1
        state.items = [
            Item(id=f"item_{i + 1}", kind=kind_for(name),
                 text=_fast_item_words(intent, state.text),
                 source=state.text if one else "",
                 action=name, intent=intent, slots=dict(base_slots))
            for i, (name, intent) in enumerate(res.intents)
        ]
        state.parse_path = "fast"
        if bare_hour is not None and state.trace:
            state.trace.step(RULE, "Rule parser",
                             f"\"at {bare_hour}\" names no half of the day — "
                             + ("asking which" if ask_first
                                else f"taking {bare_hour + 12}:00"),
                             confidence=round(res.confidence, 2))
        if ranged and state.trace:
            state.trace.step(RULE, "Rule parser",
                             f"\"{ranged[0]}\" is a span, not a day — "
                             + ("asking which day" if ask_first
                                else "taking its soonest day"),
                             confidence=round(res.confidence, 2))
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
