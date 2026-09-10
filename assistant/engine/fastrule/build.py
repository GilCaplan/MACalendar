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
    return t.strip(" ,.;:").strip()


#: A title that names nothing — the word for a calendar entry rather than a name
#: for one. A DEFER here is a REFUSAL, not an incapacity: the reading is correct
#: and must not execute as stated, and the model may resolve it to a real title.
_NAMES_NOTHING = re.compile(
    r"^(?:an?|the)?\s*(?:event|reminder|appointment|task|todo|to-do|item|"
    r"thing|meeting|entry|calendar|whole calendar|it|that|this|one)s?\s*$", re.I)


def _read_action_words(item: Item, parser) -> tuple:
    """(route, title, attendees) — everything taken from the ACTION WORDS.

    Returns the route the parser SELECTED, not the intent it was willing to
    emit. B1's finding is the reason: the parser withholds an intent when the
    when is unfilled ("create an event for staff meeting" -> no intent,
    missing ['date','start_time']), and after this restructure the when is
    supposed to be missing — it arrives in `item.slots`. Asking for the intent
    would throw away a route that is correct on 573/573 rows.
    """
    if parser is None:
        return None, "", []
    try:
        rr = parser.analyze(item.text or "", current_view="month")
    except Exception:
        return None, "", []
    raw = getattr(rr, "raw_slots", None) or {}
    if not raw:
        return None, "", []
    route = next(iter(raw))
    slots = raw.get(route) or {}
    title = slots.get("title") or ""
    if not title:
        titles = slots.get("titles") or []
        title = titles[0] if titles else ""
    attendees = list(slots.get("attendees") or [])
    return route, str(title or "").strip(), attendees


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
        from assistant.engine.fastrule.objects import _get_rule_parser
        parser = _get_rule_parser()

    slots = dict(item.slots or {})
    route, title, attendees = _read_action_words(item, parser)

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
    else:
        if op in _NO_EVENT_FORM and kind == "event":
            op = "update"
        action = _ACTION_FOR.get((op, kind)) or route

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
    return Built(action=action, intent=intent, copied=copied)
