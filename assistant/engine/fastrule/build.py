"""FastRule's one job — one `Item`, one object the system accepts.

    build(item, *, today) -> Built | Defer

`PLAN.md` §2d is the specification; this is it. Gil's box:

> *"It takes the work from segmentation and decompose_validate — which is a
> `List[Item]` — and makes it into an object format the software accepts, and
> if there's an issue it tells LLMVerify."*

So this module is a CONVERTER, not a parser. What it does, in order:

    1. read the OPERATION from the action words, narrowed by `item.kind`
    2. read the object's own fields from the action words — title, attendees
    3. COPY `item.slots` onto the object — all eight values, unconditionally
    4. can't build it? -> Defer(reason), carrying the partial parse

**It does not read the date, the time or the recurrence.** `decompose_validate`
already did, and B1 measured it resolving the when on 573/573 of the rows
FastRule currently defers on (`experiments/RESULTS.md`, 2026-09-10). Re-deriving
it is how the same date came to be computed three times in one chain, and how
"i need to talk to Sage the 3rd about yoga class" ended up with an event titled
`'3rd'`.

**Purity is the point, not a style preference.** No database, no model, no
config, no clock of its own — `today` arrives as an argument. That is what lets
the board be a table of Items and expected objects, and a failure be
reproducible from the row alone. The rule parser is consulted for the ACTION
WORDS only (`PLAN.md` §2b keeps the parser plumbing); it is deterministic, so
the property survives.

**`Built`/`Defer` are INTERNAL to this folder.** X4 is still `item.action` +
`item.intent` on the frozen `Item`, pinned by `test_engine_contracts.py`;
`stage.py` unwraps a result onto them. Making this the stage's real output would
be an `Item`-contract change — a TASKS.md design decision, not part of phase B.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from assistant.engine.state import Item
from assistant.engine.fastrule.fastrule import reason_class

#: The eight values `decompose_validate` resolved. Kept as a literal rather than
#: imported so a change on that side turns a TEST red here instead of silently
#: re-shaping this stage's copy — the two stages are contract-coupled, not
#: implementation-coupled.
VALUE_FIELDS = ("date", "start_time", "end_time", "recurrence", "recur_days",
                "recur_until", "quantity", "reminder_minutes")


@dataclass
class Built:
    """A finished object, ready for whoever decides to commit."""
    action: str                 # registry action name, e.g. "create_event"
    intent: object              # the BaseIntent subclass instance
    copied: tuple = ()          # which VALUE_FIELDS were copied — trace/testing
    rule_parse: object = None   # the RuleParseResult that produced it, for a
                                 # caller that ends up deferring anyway (stage.py's
                                 # not-ours-to-commit case) to hand the model as
                                 # `Defer`'s `partial` instead of a cold re-read


@dataclass
class BadItem:
    """The item ARRIVED malformed, and this stage does not try to repair it.

    Gil, 2026-09-10: *"for a valid item make a relevant object; for a bad item
    a BAD ITEM OBJECT is expected — not expecting to fix a bad item."*

    So this is a SUCCESS for this stage, not a failure: the words it was handed
    cannot support an object, it says so, and the damage is attributed to
    whoever produced them. Repairing upstream damage here is the thing that
    would be wrong — it hides which stage failed, and it is guesswork about
    words nobody said.

    Distinct from `Defer`, which means *"I cannot, but the model might"*. A
    `BadItem` is not deferrable: there is nothing in it for anyone to read.
    """
    reason: str
    item_id: str = ""


@dataclass
class NotAnObject:
    """The item is not something the software can hold at all.

    Gil, 2026-09-10: *"those you don't create an object — you can just flag to
    the user for this item it's not an object. This in itself can be a type of
    object."* So it is one. `build_all` is a TOTAL function: every Item gets a
    result, and "there is nothing here to build" is an answer with a name
    rather than an absence.

    That matters because the absence was silent. Segmentation tags "thanks" or
    "play some music" as `other`; the old code set `action="unknown",
    intent=None` and the orchestrator's execute loop skips a `None` intent
    BEFORE it looks at anything else — so the speaker was told nothing at all.
    A command that quietly does nothing is the worst outcome available: the
    user cannot tell it from success.
    """
    reason: str
    item_id: str = ""


@dataclass
class Defer:
    """FastRule's other product. A DEFER is an OUTPUT, not an exception.

    Which is what keeps the primary metric a PAIR — how often it builds, and
    how right it is when it does. Either number alone is gameable: a converter
    that defers everything is never wrong, and one that guesses everything
    always answers.
    """
    reason: str
    partial: object = None      # what WAS read, so LLMJudge starts warm
    fields: dict = field(default_factory=dict)

    @property
    def reason_class(self) -> "str | None":
        """REFUSAL / STRUCTURE / INCAPACITY — the vocabulary the deep track
        branches on. It lives in `fastrule.py` and is imported, never
        re-stated: a contract does not belong inside one of its consumers."""
        return reason_class(self.reason)


def hint_fields(rr) -> dict:
    """The rule parser's OWN reading, as JSON-safe primitives for a `Defer`'s
    `fields` — the only channel that survives the trip, since `item.slots`
    crosses the stage boundary and has to stay serializable (no back-edge
    into another stage's live objects). `llmjudge/rescue.py` reconstructs a
    `RuleParseResult` from these to give the model a head start instead of a
    cold re-read.

    ONLY for a Defer whose reading FastRule itself trusts — i.e. one it would
    have committed if something else hadn't stopped it (`needs-target-check`:
    a permission gate; `kind-conflict`: the title is fine, the STORE is in
    question). Never for `generic-title` / `generic-target` / `missing-slots`:
    those exist because FastRule rejected this exact reading as bad, and the
    model is told "do not contradict filled slots" — handing it a rejected
    value as a trusted one would make the model repeat the mistake rather
    than fix it.
    """
    if rr is None:
        return {}
    return {"raw_slots": rr.raw_slots, "rule_confidence": rr.confidence,
            "transcript": rr.transcript, "missing_slots": rr.missing_slots}


# ---------------------------------------------------------------------------
# 1 · the OPERATION — the verb decides, `item.kind` narrows
# ---------------------------------------------------------------------------

#: Which of the five operations a registry action name is. Read off the name
#: rather than kept as a second table, so a new action cannot drift from this.
def _operation_of(action_name: str) -> "str | None":
    for op in ("create", "update", "delete", "complete", "query"):
        if action_name.startswith(op):
            return op
    return None


#: (operation, kind) -> the registry action. `item.kind` is segmentation's `tag`
#: — it decided event-vs-task-vs-review, and B1 found 66 rows where FastRule
#: re-derived that and disagreed with it (the gap between the strict 78.7%
#: operation accuracy and the family-level 90.2%). The upstream answer wins:
#: this stage has no better information, and re-deciding it is exactly the
#: duplication the restructure exists to remove.
_ACTION_FOR = {
    ("create", "event"): "create_event",
    ("create", "task"): "create_todo",
    ("update", "event"): "update_event",
    ("update", "task"): "update_todo",
    ("delete", "event"): "delete_event",
    ("delete", "task"): "delete_todo",
    ("complete", "task"): "complete_todo",
    ("query", "event"): "query_schedule",
    ("query", "review"): "query_schedule",
    ("query", "task"): "query_todos",
}

#: Which operations may be re-kinded from `item.kind`. A create or a query is
#: safe: it needs a title, not a target, so choosing the calendar over the task
#: list changes where the new record lands and nothing else. An update, a delete
#: or a complete names an EXISTING record, and the kind decides which store is
#: searched for it — see the DEFER in `build` for why that is not a re-kind.
_RE_KINDABLE = ("create", "query")

#: Which store a route reads, for the target-taking operations.
_STORE_OF = {
    "update_event": "event", "delete_event": "event",
    "update_todo": "task", "delete_todo": "task", "complete_todo": "task",
}

#: `complete` has no event form — you do not tick off an appointment. When the
#: verb says complete and the kind says event, the kind is the thing that was
#: read from more evidence, so it wins and the operation falls back to update.
#: This is the `mark X as the Y` collision B1 counted: 122 rows routed to
#: complete_todo where the ask was create_event, on a DESTRUCTIVE operation.
_NO_EVENT_FORM = ("complete",)


# ---------------------------------------------------------------------------
# 2 · the object's own fields — title, attendees
# ---------------------------------------------------------------------------

#: Leading verb phrases to strip when the parser gave no title and the item's
#: own words have to serve as one. Deliberately small: this is a fallback, and
#: a title that keeps a stray word beats one that loses a real one.
_LEAD_VERB = re.compile(
    r"^\s*(?:(?:hey|ok|okay|please|can you|could you|would you|i need to|"
    r"i want to|i have to|gotta|remind me to|remind me|"
    r"set up|set|make|create|add|schedule|book|put|block)\s+)+",
    re.I)
#: "a call with Jesse" -> "call with Jesse". One word, and it was costing the
#: whole attendee class: the rest of the title was already right.
#:
#: ONLY "a"/"an", never "the"/"my"/"our" — measured, not assumed. Across the
#: 7,200's train half NO gold title begins with "a" or "an" (0 of 6,216) while
#: 177 begin with "the", "my" or "our": "the release date", "my whole day".
#: The first cut stripped "the" as well, which reads as tidier and would have
#: broken up to 130 rows that were already right.
_LEAD_ARTICLE = re.compile(r"^\s*(?:an?)\s+", re.I)
_TRAILING_FILLER = re.compile(
    r"\s+(?:please|thanks|thank you)\s*$", re.I)
#: "an appointment for X", "an event for X" — the noun is the parser's word for
#: a calendar entry, not a name for one. B1: "create an event for staff meeting"
#: produced the title 'event'.
_ENTRY_NOUN = re.compile(
    r"^\s*(?:an?|the)?\s*(?:event|reminder|appointment|meeting on the calendar)"
    r"\s+(?:for|about|called|named)\s+", re.I)


def _title_from_words(text: str) -> str:
    """The ask minus its verb — the fallback when the parse read no title."""
    # ORDER MATTERS: the entry noun is `^`-anchored, so "create an event for
    # staff meeting" only matches it once "create" is gone. Anchoring the other
    # way round is what made this a no-op on exactly the rows it was written for.
    t = _LEAD_VERB.sub("", (text or "").strip())
    t = _ENTRY_NOUN.sub("", t)
    t = _LEAD_VERB.sub("", t)
    t = _TRAILING_FILLER.sub("", t)
    t = _LEAD_ARTICLE.sub("", t)
    return t.strip(" ,.;:").strip()


#: A title that names nothing — the word for a calendar entry rather than a name
#: for one. A DEFER here is a REFUSAL, not an incapacity: the reading is correct
#: and must not execute as stated, and the model may resolve it to a real title.
_NAMES_NOTHING = re.compile(
    r"^(?:an?|the|my)?\s*(?:event|reminder|appointment|task|todo|to-do|item|"
    r"thing|meeting|entry|calendar|whole calendar|marker|note|block|slot|"
    # PRONOUNS NAME NOTHING EITHER, and leaving them out was a live regression:
    # the container rule below reads the tail of "can you set an event for me"
    # and happily titled the event 'me'. The guarded case is the point of
    # test_no_grounded_when_stays_unknown -- a literal ask with no real subject
    # must stay unknown rather than become a plausible-looking event.
    r"me|you|us|him|her|them|myself|yourself|ourselves|"
    r"it|that|this|one)s?\s*$", re.I)


#: Heads that NAME AN INTERACTION, so the person is part of what the thing IS
#: rather than someone attending it. The first five are measured — they are the
#: entire KEEP set of the 137 train rows. The rest are the same class of word
#: and are NOT measured here; they are included because a closed set of five
#: would be a template artifact rather than a rule about English, and real
#: speech has more ways to say it.
_INTERACTION_HEAD = {
    "meeting", "call", "catch up", "speak", "touch base",      # measured
    "chat", "coffee", "lunch", "dinner", "drinks", "sync",     # same class
    "one on one", "1:1", "check in", "interview",
}

#: "… for blood test", "… for the release date" — what the entry is FOR.
_FOR_TAIL = re.compile(r"\bfor\s+(.{2,60})$", re.I)

#: "… with Morgan", "… with Jamie and Rowan" — the people, not the event.
_ATTENDEE_ONLY = re.compile(r"\bwith\s+([A-Z][A-Za-z]*(?:\s+and\s+[A-Z][A-Za-z]*)*)")


#: Words that cannot, alone, be an ask: they carry no subject. A stripped item
#: made of nothing but these arrived broken.
_NO_SUBJECT = re.compile(
    r"^(?:\s*(?:please|thanks|ok|okay|and|then|also|hey|um|uh|so|"
    r"a|an|the|my|to|for|of|on|at|in|it|that|this)\b)+\s*$", re.I)


def _why_unusable(item: Item) -> "str | None":
    """Whether the ITEM is malformed, independent of what could be built.

    Deliberately conservative — it answers "are there words here at all",
    not "are they the right words". Judging the CONTENT would be re-deciding
    segmentation's job, which is the thing this stage stopped doing.
    """
    text = (getattr(item, "text", "") or "").strip()
    if not text:
        return "the item arrived with no action words"
    if _NO_SUBJECT.match(text):
        return f"the item's words name nothing to act on: {text!r}"
    return None


def _read_action_words(item: Item, parser) -> tuple:
    """(route, title, attendees, rr) — everything taken from the ACTION WORDS.

    Returns the route the parser SELECTED, not the intent it was willing to
    emit. B1's finding is the reason: the parser withholds an intent when the
    when is unfilled ("create an event for staff meeting" -> no intent,
    missing ['date','start_time']), and after this restructure the when is
    supposed to be missing — it arrives in `item.slots`. Asking for the intent
    would throw away a route that is correct on 573/573 rows.

    `rr`, the raw `RuleParseResult`, rides back too — a caller that ends up
    deferring can hand it to the model as the "partial" `Defer` already
    promises ("what WAS read, so LLMJudge starts warm") instead of the model
    re-reading the same words cold.
    """
    if parser is None:
        return None, "", [], None
    try:
        rr = parser.analyze(item.text or "", current_view="month")
    except Exception:
        return None, "", [], None
    raw = getattr(rr, "raw_slots", None) or {}
    if not raw:
        return None, "", [], None
    route = next(iter(raw))
    slots = raw.get(route) or {}
    # THREE NAMES FOR THE SAME THING, and missing one of them is a real defect:
    # a create carries `title` (events) or `titles` (todos), and every
    # target-taking operation carries `match_title`. Reading only the first two
    # sent "set a reminder note for three o'clock" through the fallback, which
    # made the whole utterance the target -- an update aimed at a record called
    # "a reminder note for three o'clock".
    title = slots.get("title") or slots.get("match_title") or ""
    if not title:
        titles = slots.get("titles") or []
        title = titles[0] if titles else ""
    attendees = list(slots.get("attendees") or [])
    title = str(title or "").strip()

    # A BARE ATTENDEE NAME IS NEVER THE TITLE. "book workshop with Morgan"
    # came back titled 'morgan'; "schedule conference call with Jesse" titled
    # 'jesse'. 244 train rows carry a "with <Name>" and the parser does this on
    # 142 of them.
    # A CONTAINER IS NOT A TITLE EITHER. "create an event for staff meeting"
    # comes back titled 'event'; "put a marker on for the release date" titled
    # 'marker'; "block my whole calendar for blood test" titled 'whole
    # calendar'. In every one the sentence names the KIND OF ENTRY and then
    # says what it is FOR — and the thing after "for" is the title. 71 train
    # rows are shaped this way.
    #
    # This is the attendee rule's twin: refuse a title that names the container
    # rather than the contents. Both used to end as a `generic-title` DEFER, so
    # this turns a refusal into a correct object rather than trading one error
    # for another.
    if title and _NAMES_NOTHING.match(title):
        for_m = _FOR_TAIL.search(item.text or "")
        if for_m:
            inner = _title_from_words(for_m.group(1))
            if inner and not _NAMES_NOTHING.match(inner):
                title = inner

    m = _ATTENDEE_ONLY.search(item.text or "")
    if title and m and title.lower() in {
            w.strip(" ,").lower() for w in re.split(r"\s+and\s+|,", m.group(1))}:
        head = _title_from_words((item.text or "")[:m.start()])
        people = [w.strip(" ,") for w in re.split(r"\s+and\s+|,", m.group(1))
                  if w.strip(" ,")]
        if head:
            # WHETHER THE `with` PHRASE IS PART OF THE TITLE depends on the
            # HEAD, and the corpus settles it exactly: keep it for an
            # INTERACTION ("a call with Jesse", "catch up with Cameron" — 137
            # rows), drop it for an event someone merely attends ("workshop",
            # "job interview", "sales call" — 107 rows). Note the match is on
            # the WHOLE head, not a substring: "call" keeps, "sales call"
            # drops, and treating them alike would get one of the two wrong.
            title = (f"{head} with {' and '.join(people)}"
                     if head.lower() in _INTERACTION_HEAD else head)
            attendees = attendees or people
    return route, title, attendees, rr


# ---------------------------------------------------------------------------
# 3 · the COPY — slot specs as data
# ---------------------------------------------------------------------------

#: Where each of the eight values lands, per action. This is the whole of what
#: §2b called "the job the stage exists for" — which was eleven lines copying
#: two of eight values, defensively, as a "hint". Here it is the answer: the
#: stage that produced these is measured at 99.9% train / 98.7% sealed on
#: exactly this question, and this stage has no better information.
#:
#: An action absent from a row simply does not carry that value — a
#: `complete_todo` has no date to carry, and inventing a field for it would be
#: the invention this stage exists to stop.
_VALUE_MAP = {
    "create_event": {"date": "date", "start_time": "start_time",
                     "end_time": "end_time", "recurrence": "recurrence",
                     "recur_days": "recur_days", "recur_until": "recur_until",
                     "reminder_minutes": "reminder_minutes"},
    "create_todo": {"date": "due_date"},
    "update_event": {"date": "new_date", "start_time": "new_start_time",
                     "end_time": "new_end_time"},
    "delete_event": {"date": "match_date", "start_time": "match_start_time"},
    "update_todo": {"date": "new_due_date"},
    "query_schedule": {"date": "date"},
    "complete_todo": {},
    "delete_todo": {},
    "query_todos": {},
}


def _value_kwargs(action: str, slots: dict) -> tuple:
    """The eight values as CONSTRUCTOR ARGUMENTS. Returns (kwargs, copied).

    Constructor arguments, not attributes set afterwards, and the reason is a
    defect this stage would otherwise ship. `CalendarIntent.fill_defaults` is a
    pydantic `model_validator(mode="after")`: the moment the object exists it
    stamps `date = today`, `start_time = <the current hour>` and
    `end_time = start + 1h`. Build it empty and assign `start_time = "11:00"`
    afterwards and `end_time` is still 08:00 — computed from a default start
    that no longer exists. **An event ending three hours before it begins.**

    Handing the values to the constructor lets the validators see the real
    ones, so the derived fields derive from the truth.

    (That fill also means an item with NO when at all still comes out dated
    today at the current hour. That is the intent class's behaviour, shared
    with every other producer of these objects, and not this stage's to
    change — but it is where the product-shape board's "INVENTED a time"
    rows come from, and it is recorded in experiments/RESULTS.md rather than
    quietly worked around here.)
    """
    kwargs, copied = {}, []
    for src, dst in _VALUE_MAP.get(action, {}).items():
        v = (slots or {}).get(src)
        if v in (None, "", [], {}):
            continue
        kwargs[dst] = v
        copied.append(src)
    return kwargs, tuple(copied)


def _apply_quantity(action: str, intent, slots: dict) -> bool:
    """`quantity` is the one value that must land AFTER construction.

    `CreateTodoIntent.fold_quantities` is a `model_validator(mode="after")`
    that recomputes `quantities` from the TITLES unconditionally — "filled by
    the validator below, never by the model" — so a count handed to the
    constructor is discarded on the way in. It has to be written over the
    validator's answer, not through it.

    The predecessor got this wrong in a way no test caught: `_apply_slots`
    guarded its quantity copy with `hasattr(intent, "quantity")`, and the field
    is `quantities`. The attribute does not exist, so the branch was False on
    every row it could ever have run on — **the copy never happened**. Of the
    two of eight values PLAN §2b credits the old code with copying, it was
    really copying one.
    """
    q = (slots or {}).get("quantity")
    if not q or action != "create_todo":
        return False
    try:
        n = len(getattr(intent, "titles", []) or []) or 1
        intent.quantities = [int(q)] * n
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 4 · build
# ---------------------------------------------------------------------------

#: Which actions cannot be built without something to act ON. A create can
#: default a title from its own words; an update or a delete cannot invent the
#: record it is aimed at, and "deleting is destructive — when the engine cannot
#: identify what to delete, empty slots are the right answer. Guessing is not."
_NEEDS_A_TARGET = ("update_event", "delete_event", "update_todo",
                   "delete_todo", "complete_todo")


def _new_intent(action: str, title: str, attendees: list, values: dict):
    """Construct the object for an action, values and all. Import-local so
    this module stays cheap and so a missing action module cannot break the
    import."""
    from assistant.actions.calendar.intent import (
        CalendarIntent, DeleteEventIntent, QueryScheduleIntent, UpdateEventIntent)
    from assistant.actions.todo.intent import (
        CompleteTodoIntent, CreateTodoIntent, DeleteTodoIntent,
        QueryTodoIntent, UpdateTodoIntent)
    if action == "create_event":
        return CalendarIntent(title=title, attendees=list(attendees or []), **values)
    if action == "create_todo":
        return CreateTodoIntent(titles=[title], **values)
    if action == "update_event":
        return UpdateEventIntent(match_title=title, **values)
    if action == "delete_event":
        return DeleteEventIntent(match_title=title, **values)
    if action == "update_todo":
        return UpdateTodoIntent(match_title=title, **values)
    if action == "delete_todo":
        return DeleteTodoIntent(match_title=title, **values)
    if action == "complete_todo":
        return CompleteTodoIntent(match_title=title, **values)
    if action == "query_schedule":
        return QueryScheduleIntent(**values)
    if action == "query_todos":
        return QueryTodoIntent(**values)
    return None


def build(item: Item, *, today: "_dt.date | None" = None,
          parser=None) -> "Built | Defer":
    """One `Item` -> one object the system accepts, or a DEFER saying why.

    `today` is accepted and deliberately unused for value filling: every date
    in `item.slots` arrived already resolved to ISO by `decompose_validate`.
    It stays in the signature because a TARGET ("move the dentist to next
    week") is the one field this stage may still have to ground, and a stage
    that reads the clock itself is not a pure function.

    `parser` is the rule parser, injected for tests; production passes the
    shared accessor. It is consulted for the ACTION WORDS only.
    """
    if parser is None:
        from assistant.engine import llm as _llm
        parser = _llm.get_rule_parser()

    # IS THE ITEM ITSELF USABLE? Asked BEFORE the parser, because a parser
    # handed nothing will invent a reading of nothing.
    unusable = _why_unusable(item)
    if unusable:
        return BadItem(unusable, item_id=getattr(item, "id", ""))

    slots = dict(item.slots or {})
    route, title, attendees, rr = _read_action_words(item, parser)

    if route is None:
        return Defer("no-parser" if parser is None else "skip",
                     fields={"kind": item.kind})

    # --- 1 · the operation: the verb decides, the kind narrows -------------
    op = _operation_of(route)
    if op is None:
        return Defer("skip", fields={"route": route})
    kind = item.kind if item.kind in ("event", "task", "review") else None
    if kind is None:
        # segmentation had no opinion; keep whatever the verb routed to
        action = route
    elif op in _RE_KINDABLE:
        # A create or a query only needs a title, so moving it between the
        # calendar and the task list is safe and `item.kind` is the better
        # evidence — this is where B1's 66 rows of create_todo/create_event
        # confusion get fixed.
        action = _ACTION_FOR.get((op, kind)) or route
    elif _STORE_OF.get(route) == kind or (kind == "review"):
        action = route
    else:
        # A TARGET-TAKING OPERATION WHOSE STORE THE KIND DISAGREES WITH.
        # Re-kinding here would change WHICH STORE is searched for the record
        # to change or remove, which is a different and destructive action --
        # "set reminder for three o'clock" routes to update_todo, and re-kinding
        # it to update_event produced an event-update aimed at a record called
        # "three o'clock". Neither reading is trustworthy when the two
        # disagree, so this is exactly what the DEFER is for: the deep track
        # gets the conflict and the partial parse rather than a guess.
        return Defer("kind-conflict",
                     fields={"route": route, "kind": kind, "title": title,
                             **hint_fields(rr)})

    # --- 2 · the object's own fields ---------------------------------------
    if not title:
        title = _title_from_words(item.text)
    if not title:
        return Defer("missing-slots", fields={"action": action, "missing": ["title"]})
    if _NAMES_NOTHING.match(title):
        # a correct reading that must not execute as stated
        return Defer("generic-title" if action.startswith("create")
                     else "generic-target",
                     fields={"action": action, "title": title})
    if action in _NEEDS_A_TARGET and not title:
        return Defer("generic-target", fields={"action": action})

    # --- 3 · COPY the values, INTO the constructor --------------------------
    values, copied = _value_kwargs(action, slots)
    try:
        intent = _new_intent(action, title, attendees, values)
    except Exception as exc:
        # a validation refusal is the object telling us this is not buildable
        # as read — which is a DEFER, this stage's other product, not a crash
        return Defer("missing-slots",
                     fields={"action": action, "title": title, "why": str(exc)[:80]})
    if intent is None:
        return Defer("skip", fields={"action": action})
    if _apply_quantity(action, intent, slots):
        copied = copied + ("quantity",)
    return Built(action=action, intent=intent, copied=copied, rule_parse=rr)


# ---------------------------------------------------------------------------
# 5 · the STAGE's shape — List[Item] -> List[BuildResult]
# ---------------------------------------------------------------------------

def build_all(items: "list[Item]", *, today: "_dt.date | None" = None,
              parser=None) -> list:
    """Every Item converted. `None` in the result means "not a calendar ask".

    This is the shape Gil's box describes — `List[Item]` in, objects out — and
    it is deliberately a plain map with no state of its own. Each item is
    converted from ITS OWN words and its own slots, so the question "which
    date belongs to which event" is never asked here; segmentation and
    decompose_validate already answered it.

    The parser is resolved ONCE for the whole list rather than per item: it is
    a cached singleton either way, but looking it up here makes it obvious that
    a converter is not entitled to a different one per row.
    """
    if parser is None:
        from assistant.engine import llm as _llm
        parser = _llm.get_rule_parser()

    out: list = []
    for item in items:
        if getattr(item, "kind", None) == "other":
            # NOT A CALENDAR ASK. Segmentation already decided this is none of
            # event/task/review ("thanks", "play some music", "turn on the
            # lights"), so there is nothing here to turn into an object — and
            # re-deciding it is exactly what this stage stopped doing.
            out.append(NotAnObject("not something I can put on the calendar "
                                   "or a list", item_id=item.id))
            continue
        try:
            out.append(build(item, today=today, parser=parser))
        except Exception as exc:      # a converter never takes a command down
            out.append(Defer("error", fields={"why": str(exc)[:100]}))
    return out
