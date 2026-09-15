"""The DEFER consumer — what happens to an Item FastRule could not build.

    rescue(state, cfg, pending) -> None

Gil's box for FastRule: *"it takes the work from segmentation and
decompose_validate … and makes it into an object format the software accepts,
**and if there's an issue it tells LLMVerify**."* This is the receiving end of
that sentence. FastRule reports a `Defer` and carries its partial parse; the
model call happens where the model lives.

**What moved here, and what was left behind on purpose.** The old per-item path
(`fastrule/objects.py::_parse_item`, deleted 2026-09-10) did four things. Only
the last is this module's:

    1. re-ran the WHOLE fast track per item — Atomicity, Gatekeeper, Scorer
    2. re-read the date and time out of `item.spoken()`
    3. re-decided event-vs-task, then RETRIED the model when it disagreed
    4. asked the model to read what the rules could not

1 is gone: segmentation already split the command, so the item is atomic by
contract and asking again re-decides another component's answer on worse
evidence. 2 is gone: `decompose_validate` resolved the values and `build`
copies them — B1 measured that stage reading the when correctly on 573/573 of
the rows FastRule was deferring. 3 is gone: `build` takes segmentation's `tag`
as the kind rather than arguing with it.

**The model is therefore asked a smaller question than it used to be**, and it
is asked it on the ACTION WORDS. The values are not its business — whatever it
returns, `decompose_validate.run_objects` writes this stage's resolved values
onto the intent afterwards, exactly as it always has.

The guards ride along unchanged (`llm_fallback.py`, ported in phase A):
`_guard_inventions` exists because a model once fabricated an event onto the
calendar (cycle 7), and `_honour_refusal` because a REFUSAL may be RESOLVED but
never overturned — a rule this codebase has already broken once, when the
per-item path re-implemented the commit test with the gates omitted.
"""
from __future__ import annotations

import logging
import re

from assistant.engine.state import EngineState, Item
from assistant.engine.llmjudge.llm_fallback import (
    _guard_inventions, _honour_refusal, _llm_trace)

logger = logging.getLogger(__name__)


def friendly(item_id: str) -> str:
    """item_1 -> "part 1", item_1-2 -> "part 1.2" — legible in the trace chain."""
    return "part " + item_id.replace("item_", "").replace("-", ".")


#: The literal ask that grounds a default title — the noun IS in the words.
_EVENT_ASK = re.compile(
    r"\b(?:set|make|create|add|schedule|book|put)\b[^.!?]*?\b(event|reminder|appointment)\b"
    r"|\b(event|reminder|appointment)\b[^.!?]*?\b(?:set|make|create|add|schedule|book|put)\b",
    re.I)


def _event_fallback(text: str):
    """The event twin of the task fallback (hypothesis #2, cycle 5).

    Fires only after the model also produced nothing: when the words LITERALLY
    ask to set an event/reminder/appointment ("Set a event for the evening",
    "Set reminder for three o'clock") and the date recognizer grounds a when in
    those same words, the honest object is a default-titled event — noun and
    when are both in the transcript, so nothing is invented. No literal ask, or
    no grounded when, returns None and the item stays unknown; a time is never
    guessed.
    """
    m = _EVENT_ASK.search(text)
    if not m:
        return None
    noun = next(g for g in m.groups() if g)
    import datetime as _dt
    from assistant.intent.rule_parser import _extract_temporal
    t = _extract_temporal(text, _dt.date.today())
    if not (t.get("date") or t.get("start_time")):
        return None
    from assistant.actions.calendar.intent import CalendarIntent
    return CalendarIntent(title=noun.capitalize(), date=t.get("date"),
                          start_time=t.get("start_time"),
                          end_time=t.get("end_time"))


def _ask_the_model(item: Item, state: EngineState, cfg, verdict) -> "list | None":
    """One item the rules could not build → intents, from the model.

    `verdict` is FastRule's `Defer`, so the model starts from the partial parse
    rather than cold, and a REFUSAL is honoured rather than re-litigated.
    """
    from assistant.engine.fastrule.fastrule import REFUSAL
    from assistant.engine import llm as _llm

    parser = _llm.get_parser(cfg)
    partial = getattr(verdict, "partial", None)
    got = (parser.parse_with_context(item.spoken(), partial)
           if partial is not None else parser.parse(item.spoken()))
    _llm_trace(state, parser, cfg, f"Read {friendly(item.id)}")
    got = _guard_inventions(got, item, state)
    if verdict is not None and verdict.reason_class == REFUSAL:
        got = _honour_refusal(got, verdict, item, state)
    return got


def take_deferrals(state: EngineState, cfg) -> None:
    """LLMJudge's FIRST job: answer whatever FastRule could not build.

    FastRule leaves a `Defer` on each item it declined (`slots["fastrule_defer"]`)
    and stops. This is the receiving end. It runs at the top of the llmjudge
    stage, BEFORE the crosscheck, because the crosscheck compares what was
    produced against what was said — and an item still waiting on the model has
    not been produced yet.
    """
    pending = []
    for item in list(getattr(state, "items", []) or []):
        d = (item.slots or {}).pop("fastrule_defer", None)
        if d is None:
            continue
        pending.append((item, _Verdict(d.get("reason") or "",
                                       d.get("reason_class"))))
    if not pending:
        return
    rescue(state, cfg, pending)
    _expand(state)
    # The rescued intents still owe decompose_validate's object pass -- they did
    # not exist when the FastRule stage ran it.
    from assistant.engine.decompose_validate import stage as _dv
    _dv.run_objects(state, cfg)


class _Verdict:
    """The DEFER, rebuilt from what rode the item. Only the two fields the
    rescue reads survive the trip, which is deliberate: a partial PARSE object
    cannot be put on an item without making `slots` un-serialisable, and the
    model is given the item's words either way."""

    __slots__ = ("reason", "reason_class", "partial")

    def __init__(self, reason: str, reason_class: "str | None") -> None:
        self.reason = reason
        self.reason_class = reason_class
        self.partial = None


def _expand(state: EngineState) -> None:
    """An item whose words parsed into SEVERAL intents becomes one sub-item per
    intent — per-item attribution is what keeps feedback from corrupting a
    neighbour (the row-75 lesson)."""
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


def rescue(state: EngineState, cfg, pending: list) -> None:
    """Consume FastRule's DEFERs. `pending` is [(item, Defer), …].

    Each item is handled on its own: one unreadable item must not kill its
    neighbours (a validation error on "bowling tuesday night" once took a whole
    command down). Honest per-item failure; the rest still executes.

    THE SAME HOLDS FOR THE MODEL GOING AWAY MID-COMMAND (TASKS.md row 92).
    Re-raising `LLMUnavailableError`/`LLMTimeoutError` used to unwind all the
    way past `_commit()` in the orchestrator — so a three-item command where
    the model answered two items and then dropped lost ALL THREE, not just
    the one it never got to. The gate `Engine.parse()`'s caller now runs
    before entering the deep track at all handles the common case (offline
    from the start); this is the narrower one, the model going away partway
    through a batch of deferred items. Once it is confirmed unreachable,
    retrying each remaining item would each pay its own timeout for an
    identical answer, so the rest are marked unread rather than attempted —
    honest per-item failure, same as a ParseError, not a silent auto-retry
    (which would risk the Mac's own pending-command queue and this loop both
    replaying the same words later).
    """
    from assistant.exceptions import (LLMTimeoutError, LLMUnavailableError,
                                      ParseError)
    from assistant.actions.todo.intent import CreateTodoIntent

    model_gone = False
    for item, verdict in pending:
        if item.slots is None:
            item.slots = {}
        item.slots["built_by"] = "model"
        if model_gone:
            state.add_fix("llmjudge", "item_parse_failed", item.text[:40], "",
                          note="the model was unreachable for an earlier item")
            state.messages.append(
                f"Sorry, I couldn't read this part: “{item.text[:60]}”.")
            continue
        try:
            got = _ask_the_model(item, state, cfg, verdict)
        except (LLMUnavailableError, LLMTimeoutError) as e:
            model_gone = True
            logger.warning("Model unreachable on item %s: %s", item.id, e)
            state.add_fix("llmjudge", "item_parse_failed", item.text[:40], "",
                          note=str(e)[:120])
            state.messages.append(
                f"Sorry, I couldn't read this part: “{item.text[:60]}”.")
            continue
        except ParseError as e:
            logger.warning("Item %s failed to parse: %s", item.id, e)
            state.add_fix("llmjudge", "item_parse_failed", item.text[:40], "",
                          note=str(e)[:120])
            state.messages.append(
                f"Sorry, I couldn't read this part: “{item.text[:60]}”.")
            continue

        # THE KIND-PRIMED RETRY. Segmentation judged these words an EVENT; a
        # parse that comes back with only todos or unknowns CONTRADICTS that
        # judgement. This is not re-deciding the kind -- it is enforcing the
        # upstream's answer against a model that disagreed with it, which is the
        # opposite relationship. Tasks had a fallback and events silently died
        # instead: the missing-event signature, 72% of event+task failures. One
        # retry, restating segment's own judgement in the words.
        if item.kind == "event" and got is not None and \
                not any(("event" in n or n in ("clarify", "query_schedule"))
                        for n, _ in got if n != "unknown"):
            try:
                from assistant.engine import llm as _llm
                parser = _llm.get_parser(cfg)
                retried = parser.parse(f"set an event: {item.spoken()}")
                _llm_trace(state, parser, cfg,
                           f"Re-read {friendly(item.id)} as an event")
            except Exception:
                retried = None
            if retried and any("event" in n for n, _ in retried if n != "unknown"):
                state.add_fix("generate", "event_kind_retry", "", item.text[:40],
                              note="the parse contradicted the item's event kind")
                got = retried

        empty = not got or all(n == "unknown" for n, _ in got)

        # THE TWO KIND-GROUNDED FALLBACKS. Both exist because segmentation
        # already judged what these words are, and a model that comes back
        # empty for them is the model failing the words, not the words failing
        # to be an event or a task.
        if empty and item.kind == "event":
            fb = _event_fallback(item.spoken())
            if fb is not None:
                item.action, item.intent = "create_event", fb
                state.add_fix("llmjudge", "event_fallback", "", item.text[:40],
                              note="literal set-an-event ask with a grounded when")
                continue
        if empty and item.kind == "task":
            # "submit the Haxaga grades" -> unknown, run 12. The item text IS
            # the task.
            try:
                item.action = "create_todo"
                item.intent = CreateTodoIntent(titles=[item.text.strip()])
                state.add_fix("llmjudge", "task_fallback", "", item.text[:40],
                              note="a task-kind item never parses to nothing")
                continue
            except Exception:
                pass

        if not got:
            continue
        if len(got) == 1:
            item.action, item.intent = got[0]
            continue
        # An item whose words parse into SEVERAL intents is expanded into
        # sub-items, one intent each — per-item attribution is what keeps
        # feedback from corrupting a neighbour (the row-75 lesson).
        item.slots["_expanded"] = [
            (name, intent) for name, intent in got]
