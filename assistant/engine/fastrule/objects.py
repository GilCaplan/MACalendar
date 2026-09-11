"""Step 5 — turn items into concrete intents (and own the fast-track proposal).

Contract (see DOCUMENTATION/ENGINE.md):
  fast_propose(state, cfg) -> bool
      The whole-input rule-parser proposal. On confidence ≥ RULE_THRESHOLD
      with no missing slots it fills state.items with one Item per intent,
      sets state.parse_path="fast" and state.rule_confidence, and returns
      True — the orchestrator then commits instantly and runs the deep track
      in the background. Always records the score it saw.
  run(state, cfg) -> state
      Deep track, per item:
      reads   item.spoken() (action WITH its time — a parser needs the
              time in the string), item.slots, state.text
      writes  item.action, item.intent (an item whose text parses into
              several intents is expanded into sub-items, one intent each —
              per-item attribution is what keeps feedback from corrupting a
              neighbour, the row-75 lesson), state.llm_ms, trace (RULE/LLM)

All text→intent conversion lives here and nowhere else. The rule parser is
consulted first per item (free, ~50ms); the LLM fills gaps from the rule
parser's partial analysis or parses from scratch. Prompts are grounded on the
item's own words — never another item's.
"""

from __future__ import annotations

import logging
import re

from assistant.engine.state import EngineState, Item

#: PORTED OUT 2026-09-09 (Gil) — the model half's helpers and its three
#: guards now live in `llmjudge/llm_fallback.py`, where the model lives.
#: This import is the redirect: the code moved, `_parse_item`'s branch
#: below did not, and behaviour is unchanged. `_parse_item` itself stays
#: here — it is the rules-vs-model BRANCH POINT, not a liftable unit, and
#: phase B replaces it with a DEFER(INCAPACITY) consumer.
from assistant.engine.llmjudge.llm_fallback import (   # noqa: F401
    _grounded_title, _guard_inventions, _honour_refusal, _llm_trace,
    _TITLE_STOP)

logger = logging.getLogger(__name__)

#: Fragments of a split command accept rule parses at this relaxed bar
#: (cycle 9, Gil's call); whole commands keep RULE_THRESHOLD.
SUBITEM_RULE_THRESHOLD = 0.60

_parser = None
_rule_parser = None
_RULE_PARSER_MISSING = object()   # spaCy absent: checked once, then skipped


def get_registry():
    """The action registry, with every action module imported (they
    self-register via @register on import)."""
    import assistant.actions.calendar          # noqa: F401
    import assistant.actions.todo              # noqa: F401
    import assistant.actions.clarify           # noqa: F401
    import assistant.actions.workout_routine   # noqa: F401
    import assistant.actions.schedule_workout  # noqa: F401
    from assistant.actions import ActionRegistry
    return ActionRegistry()


def _get_parser(cfg):
    global _parser
    if _parser is None:
        from assistant.intent.parser import IntentParser
        _parser = IntentParser(cfg, get_registry())
    return _parser


def _get_rule_parser():
    global _rule_parser
    if _rule_parser is _RULE_PARSER_MISSING:
        return None
    if _rule_parser is None:
        from assistant.intent.rule_parser import (
            RuleBasedParser, _RULE_PARSER_AVAILABLE,
        )
        if not _RULE_PARSER_AVAILABLE:
            _rule_parser = _RULE_PARSER_MISSING
            return None
        _rule_parser = RuleBasedParser(get_registry())
    return _rule_parser


def reset_parsers() -> None:
    """Tests swap config; cached parsers must not outlive it."""
    global _parser, _rule_parser
    _parser = None
    _rule_parser = None


# A joiner that all but announces a second request. Deliberately much narrower
# than segment's _COMPOUND_HINT: a plain "and" joins guests and groceries far
# more often than requests, but ". Also," / ", and then" / " — and" almost
# never appear inside ONE ask. Cycle 3 of the dataset loop: every observed
# fast-path mangle ("…at 9am, and then Remind me…" committing a todo literally
# titled "then") was a confident SINGLE-intent parse of text carrying one of
# these.
def fast_propose(state: EngineState, cfg) -> bool:
    """Whole-command fast track: FastRule at RULE_THRESHOLD (the conservative
    front-door instance; the deep track is its net). A thin adapter — the
    parser + gates + threshold live in assistant/engine/fastrule.FastRule."""
    from assistant.intent.rule_parser import RULE_THRESHOLD
    from assistant.engine.fastrule.fastrule import FastRule   # v2 structure, v1 behavior (diff-gated 7200/7200)
    from assistant.trace import RULE

    res = FastRule(RULE_THRESHOLD).run(state.text, state.current_view)
    state.rule_confidence = res.confidence

    if res.committed:
        state.items = [
            Item(id=f"item_{i + 1}", kind=_kind_for(name),
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
    from assistant.engine.fastrule.fastrule import reason_class
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


def _fast_item_words(intent, whole: str) -> str:
    """The words THIS fast intent can honestly claim, not the whole command.

    Every fast item used to be built with `text=state.text`, so a two-ask
    command committed on the fast path produced two items both carrying the
    entire utterance. `llmjudge._produced` tokenizes `it.text` into the set it
    matches asks against, so both items presented the same token set — every
    ask overlapped every item and `_overlap` could not tell them apart. The
    background judge is the ONLY check on the fast path, which commits BEFORE
    it runs, so the discrimination was worst exactly where it matters most.

    FastRule returns intents, not spans, so the item's own words cannot be
    recovered from the parse — but the title is what the intent claims those
    words said, and it is what every reader of `item.text` on this path
    actually wants (the judge's token set, the reply's title fallback at
    `engine/__init__.py:382`, the loop-back's re-run signature at :171).
    `titles` first: a fast `create_todo` carries every title in ONE intent
    ("milk, eggs and bread"), and one of the three is not the item.

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


def _kind_for(action_name: str) -> str:
    if "todo" in action_name:
        return "task"
    if "event" in action_name:
        return "event"
    if "query" in action_name or "schedule" in action_name:
        return "review"
    return "other"


def _friendly(item_id: str) -> str:
    """item_1 -> "part 1", item_1-2 -> "part 1.2" — legible in the trace chain."""
    return "part " + item_id.replace("item_", "").replace("-", ".")


# --- the two ways an item leaves this stage without an object --------------
#
# Every other item becomes a calendar or to-do object. These two do not, and
# they are NOT the same kind of thing, which is the whole reason they are named
# rather than both just "nothing happened":
#
#   NOT_AN_ASK  a CORRECT READING. Segmentation placed the words outside the
#               calendar altogether ("thanks", "play some music"). The engine
#               behaved properly and there is nothing to fix.
#   BAD_ITEM    an UPSTREAM DEFECT. The words were calendar work and the item
#               still could not be read — something earlier in the chain handed
#               this stage damage. Worth someone's attention.
#
# Until now both were recorded only in `state.fixes`, which nothing outside
# decompose_validate ever traces (ENGINE_AUDIT.md P6), so the review panel —
# the surface built to expose exactly this — showed a run that simply did
# nothing. The step below is what carries them out, and `data["outcome"]` is
# the key the panel renders them apart by.
NOT_AN_ASK = "not_an_ask"
BAD_ITEM = "bad_item"

_OUTCOME_WHY = {
    NOT_AN_ASK: "Nothing to add — these words aren't a calendar or to-do ask.",
    BAD_ITEM: "It reads as calendar work, but nothing writable could be built "
              "from it.",
}


def _trace_outcome(state: EngineState, outcome: str, item: Item,
                   detail: str = "") -> None:
    """Put a non-object outcome on the trace, tagged for the review panel.

    Stage RULE, so it lands on the chain rail's "make each object" slot like
    every other per-item step — this is a thing that HAPPENED to an item, not
    a stage of its own. Titled like them too ("Read part 1"), because the
    reader is looking at one list: what the OUTCOME was belongs in the panel's
    chip, which is the one place the two are told apart, and repeating it in
    the title would both say it twice and push the row wider than the card.

    `ok` is False only for BAD_ITEM: a correct reading is not a failure, and
    colouring it as one is how "we don't do that here" starts looking like a
    bug.
    """
    if not state.trace:
        return
    from assistant.trace import RULE

    body = f"“{item.text[:60]}” — {_OUTCOME_WHY[outcome]}"
    if detail:
        body = f"{body} ({detail})"
    state.trace.step(RULE, f"Read {_friendly(item.id)}", body,
                     ok=(outcome != BAD_ITEM), outcome=outcome, item=item.id)



def _parse_item(item: Item, state: EngineState, cfg) -> "list | None":
    """One atomic item → intents. FastRule first, the LLM for what it can't
    read — and the deep track HONOURS what FastRule refuses.

    This used to re-implement FastRule's commit test inline, at the
    whole-command bar, with BOTH gate layers omitted — so an item the front
    door had vetoed (a mutation aimed at a bare noun, say) was re-committed
    here with no safety check. The engine audit named it: the rail only
    guarded the front door. Now the real object runs, at the fragment bar,
    gates on, and its REASON CLASS decides the handoff:

      STRUCTURE  → still more than one item; the caller must split further
      REFUSAL    → the LLM may RESOLVE the objection (anaphora → a real
                   target) but a bare re-read must not overturn it
      INCAPACITY → "I couldn't read this": the LLM takes over, as designed
    """
    from assistant.engine.fastrule.fastrule import (FastRule, REFUSAL, STRUCTURE,
                                           reason_class)
    from assistant.intent.rule_parser import RULE_THRESHOLD, RuleParserSkip

    parser = _get_parser(cfg)
    rule_parser = _get_rule_parser()
    if rule_parser is not None:
        try:
            # A fragment of a split command is a simple shape (the sandbox
            # measured the rules high on those), so it trusts them at a
            # relaxed bar; crosscheck remains the net. The whole command
            # keeps the front door's bar.
            is_fragment = item.text.strip() != state.text.strip()
            bar = SUBITEM_RULE_THRESHOLD if is_fragment else RULE_THRESHOLD
            # Q12 (Gil): FastRule is DETERMINISTIC — asking it the same text
            # twice cannot produce a different verdict, so a loop-back that
            # did not change this item's words must skip straight to the LLM
            # rather than burn a re-parse that is guaranteed to fail again.
            seen = state.asked_fastrule
            # Keyed on what FastRule is ASKED, which is `spoken()` — the action
            # WITH its time. Keyed on `text` (the action alone), "gym at 7" and
            # "gym at 9" are one key: the second item was recorded as already
            # asked and skipped FastRule entirely, on a verdict formed from a
            # different time.
            asked = item.spoken()
            asked_before = asked in seen
            seen.add(asked)
            res = None if asked_before else FastRule(bar).run(asked, state.current_view)
            if res is None:
                if state.trace:
                    from assistant.trace import RULE
                    state.trace.step(RULE, f"Read {_friendly(item.id)}",
                                     "unchanged since the last attempt — "
                                     "straight to the model", ok=True)
                got = parser.parse(item.spoken())
                _llm_trace(state, parser, cfg, f"Read {_friendly(item.id)}")
                return _guard_inventions(got, item, state)
            if res.committed:
                if state.trace:
                    from assistant.trace import RULE
                    state.trace.step(RULE, f"Read {_friendly(item.id)}",
                                     f"{res.confidence:.2f}"
                                     + (" (fragment bar)" if is_fragment
                                        and res.confidence < RULE_THRESHOLD else "")
                                     + ": " + ", ".join(n for n, _ in res.intents))
                return res.intents

            cls = reason_class(res.reason)
            if cls == STRUCTURE:
                # Not one atomic item — say so and let the caller split it
                # again rather than asking the model to read a compound.
                item.slots["needs_breakdown"] = res.reason
                if state.trace:
                    from assistant.trace import RULE
                    state.trace.step(RULE, f"Read {_friendly(item.id)}",
                                     f"still more than one item ({res.reason})")
            rr = res.rule_result
            got = parser.parse_with_context(item.spoken(), rr) if rr is not None \
                else parser.parse(item.spoken())
            _llm_trace(state, parser, cfg, f"Read {_friendly(item.id)}")
            got = _guard_inventions(got, item, state)
            if cls == REFUSAL:
                got = _honour_refusal(got, res, item, state)
            return got
        except RuleParserSkip:
            pass          # the designed "the rules decline" signal
        except Exception:
            # NOT the same thing, and it used to be indistinguishable. This
            # `try` wraps the model call and its guards as well as the rule
            # parse, so anything raised in there fell through to the bare
            # `parser.parse` below — a second model call WITHOUT
            # `_honour_refusal`, which is the gate CLAUDE.md records as having
            # been re-implemented-without-its-gates once already. Still
            # non-fatal (one unreadable item must not take its neighbours
            # down), but no longer silent.
            logger.exception("The rule path raised on item %s (%r); falling "
                             "back to the model", item.id, item.spoken()[:60])
    got = parser.parse(item.spoken())
    _llm_trace(state, parser, cfg, f"Read {_friendly(item.id)}")
    return _guard_inventions(got, item, state)


def run(state: EngineState, cfg) -> EngineState:
    from assistant.exceptions import LLMTimeoutError, LLMUnavailableError, ParseError

    out: list = []
    for item in state.items:
        if item.kind == "other":
            # NOT A CALENDAR ASK. Segmentation has already decided this is none of
            # event/task/review ("thanks", "play some music", "turn on the
            # lights"), so there is nothing here to turn into an object. Skipped
            # BEFORE `_parse_item`, which saves the LLM call as well as the wrong
            # answer — and `action = "unknown"` routes it to the orchestrator's
            # existing honest reply rather than a new branch that says the same
            # thing differently.
            item.action, item.intent = "unknown", None
            state.add_fix("generate", "not_a_calendar_ask", item.text[:40], "",
                          note="tagged `other` by segmentation")
            _trace_outcome(state, NOT_AN_ASK, item)
            out.append(item)
            continue
        try:
            got = _parse_item(item, state, cfg)
        except (LLMUnavailableError, LLMTimeoutError):
            raise            # the orchestrator owns offline queueing
        except ParseError as e:
            # One unreadable item must not kill its neighbours (a validation
            # error on "bowling tuesday night" once took the whole command
            # down). Honest per-item failure; the rest still executes.
            logger.warning("Item %s failed to parse: %s", item.id, e)
            state.add_fix("generate", "item_parse_failed", item.text[:40], "",
                          note=str(e)[:120])
            _trace_outcome(state, BAD_ITEM, item, detail=str(e)[:120])
            state.messages.append(
                f"Sorry, I couldn't read this part: “{item.text[:60]}”.")
            out.append(item)
            continue
        if item.kind == "event" and got is not None and \
                not any(("event" in n or n in ("clarify", "query_schedule"))
                        for n, _ in got if n != "unknown"):
            # Segmentation judged these words an EVENT; a parse that yields
            # only todos or unknowns contradicts that judgment. Tasks have a
            # fallback — events silently died instead (the missing-event
            # signature: 72% of event+task failures). One retry, restating
            # segment's own judgment in the words.
            try:
                retried = _get_parser(cfg).parse(f"set an event: {item.spoken()}")
                _llm_trace(state, _get_parser(cfg), cfg, f"Re-read {_friendly(item.id)} as an event")
            except Exception:
                retried = None
            if retried and any("event" in n for n, _ in retried if n != "unknown"):
                state.add_fix("generate", "event_kind_retry", "", item.text[:40],
                              note="the parse contradicted the item's event kind")
                got = retried
        if item.kind == "event" and (not got or all(n == "unknown" for n, _ in got)):
            fb = _event_fallback(item.spoken())
            if fb is not None:
                item.action, item.intent = "create_event", fb
                _apply_slots(item)      # a stripped lead time rides fallbacks too
                state.add_fix("generate", "event_fallback", "", item.text[:40],
                              note="literal set-an-event ask with a grounded when")
                out.append(item)
                continue
        if item.kind == "task" and (not got or all(n == "unknown" for n, _ in got)):
            # Segmentation already judged these words a to-do; a parse that
            # comes back empty for them is the model failing the words, not
            # the words failing to be a task ("submit the Haxaga grades" →
            # unknown, run 12). The item text IS the task.
            from assistant.actions.todo.intent import CreateTodoIntent
            try:
                item.action = "create_todo"
                item.intent = CreateTodoIntent(titles=[item.text.strip()])
                state.add_fix("generate", "task_fallback", "", item.text[:40],
                              note="a task-kind item never parses to nothing")
                out.append(item)
                continue
            except Exception:
                pass
        if not got:
            out.append(item)
            continue
        if len(got) == 1:
            item.action, item.intent = got[0]
            _apply_slots(item)
            out.append(item)
            continue
        for j, (name, intent) in enumerate(got, start=1):
            sub = Item(id=f"{item.id}-{j}", kind=_kind_for(name), text=item.text,
                       slots=dict(item.slots), action=name, intent=intent)
            _apply_slots(sub)
            out.append(sub)
    state.items = out
    return state


#: The literal ask that grounds a default title — the noun IS in the words.
_EVENT_ASK = re.compile(
    r"\b(?:set|make|create|add|schedule|book|put)\b[^.!?]*?\b(event|reminder|appointment)\b"
    r"|\b(event|reminder|appointment)\b[^.!?]*?\b(?:set|make|create|add|schedule|book|put)\b",
    re.I)


def _event_fallback(text: str):
    """The event twin of task_fallback (hypothesis #2, cycle 5).

    Fires only after the event-kind retry also produced nothing: when the
    words LITERALLY ask to set an event/reminder/appointment ("Set a event
    for the evening", "Set reminder for three o'clock") and the date
    recognizer grounds a when in those same words, the honest object is a
    default-titled event — noun and when are both in the transcript, so
    nothing is invented. No literal ask, or no grounded when, returns None
    and the item stays unknown; a time is never guessed.
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


def _apply_slots(item: Item) -> None:
    """Structured hints from decomposition land on the intent, when it can
    carry them — a count the words stated beats one the model guessed."""
    rm = item.slots.get("reminder_minutes")
    if rm and item.action == "create_event" and hasattr(item.intent, "reminder_minutes"):
        if getattr(item.intent, "reminder_minutes", None) is None:
            item.intent.reminder_minutes = int(rm)
    q = item.slots.get("quantity")
    if q and item.action == "create_todo" and hasattr(item.intent, "quantity"):
        if getattr(item.intent, "quantity", None) in (None, 0, 1):
            item.intent.quantity = q
