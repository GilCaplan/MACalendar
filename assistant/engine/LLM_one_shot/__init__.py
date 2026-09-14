"""A PARALLEL engine: one LLM call, transcript in, objects out.

    MACALENDAR_ONESHOT=1   route every command here instead of the chain

Gil, 2026-09-13: *"build a parallel engine which is just an LLM trying to one
shot"*. It exists to answer one question the retrospective raised and cannot
answer from inside the chain:

**Does the six-stage deep track earn its complexity?** On the sealed 300,
`main`'s rules-only fast path scores 93.1% and its deep track — ingest,
segmentation, decompose_validate, fastrule, llmjudge, commit, plus an LLM call
per item — scores 65.3% on the rows it is handed, at ~44 s each. If ONE
schema-constrained call matches that, the machinery is not paying for itself.
If it scores far worse, the machinery is what is holding the number up, and
that is worth knowing before anyone simplifies it.

## What it is, and is not

It is deliberately the DUMBEST honest baseline: the raw transcript, today's
date, and a schema. No vocabulary repair, no segmentation, no rules, no
validation, no judge, no retry. Anything it gets right, it gets right from the
model alone.

It is NOT a proposal to replace the engine, and it changes nothing about the
chain — the flag is off by default and the chain is untouched. This is a
measuring instrument.

## Why it still commits through `_commit`

A comparison is only fair if both sides write the same way. The objects this
produces become the same `(action, intent)` pairs on the same `Item`s, and the
orchestrator's commit step executes them, labels them and records them exactly
as it does for the chain. So the scorer sees two runs that differ in HOW the
objects were decided and in nothing else.
"""
from __future__ import annotations

import datetime as _dt
import logging

logger = logging.getLogger(__name__)

#: The object shapes the actions accept, flattened into one array. Ollama is
#: format-constrained by this, so the model CANNOT emit a shape the mapper
#: below does not understand — only wrong content, which is the thing under
#: test.
SCHEMA = {
    "type": "object",
    "properties": {
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["event", "task", "query_events", "query_tasks"]},
                    "operation": {"type": "string",
                                  "enum": ["create", "update", "delete", "complete", "query"]},
                    "title": {"type": "string"},
                    "match_title": {"type": "string"},
                    "date": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "due_date": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "recurrence": {"type": "string",
                                   "enum": ["", "daily", "weekly", "monthly", "yearly"]},
                    "recur_until": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "priority": {"type": "string",
                                 "enum": ["none", "low", "medium", "high"]},
                    "list_name": {"type": "string", "enum": ["today", "general"]},
                },
                "required": ["kind", "operation"],
            },
        },
    },
    "required": ["objects"],
}

_SYSTEM = """You turn ONE spoken command to a calendar assistant into the \
objects the app should write. Answer with JSON only.

Each object is one thing to do:
- kind "event" — something with a date and usually a time. operation create /
  update / delete.
- kind "task" — a to-do, a reminder to DO something, a shopping item.
  operation create / update / delete / complete.
- kind "query_events" or "query_tasks" — the speaker is ASKING what is
  scheduled or what is on their list. operation query. Create nothing.

Rules, which decide most of the hard cases:
- ONE OBJECT PER THING ASKED FOR. "book gym tomorrow at 7am and remind me to
  buy milk" is two objects: an event and a task.
- A list is one object PER ITEM, each carrying the verb: "add milk, eggs and
  bread to my list" is three tasks — "buy milk", "buy eggs", "buy bread".
- A COUNT is one object: "buy 5 apples" is ONE task, title
  "buy 5 apples" — keep the number in the title. Never five objects.
- People joined by "and" share one object: "meeting with Tal and Ravid" is one
  event, attendees ["Tal", "Ravid"].
- A QUESTION about what is scheduled creates nothing — emit a query object.
- Moving, renaming, deleting or completing something is an object too, with
  match_title naming what to find.

Fields:
- date and due_date are ISO "YYYY-MM-DD". start_time and end_time are 24-hour
  "HH:MM". Resolve "tomorrow", "next friday", "the 3rd" against TODAY, given
  below.
- Leave a field out rather than inventing it. An event with no time stated is
  fine with no start_time.
- title is what the thing IS, without the command verb: "book the dentist at
  3" has title "dentist", not "book the dentist".
- recurrence only when the speaker asks for a repeat, and only daily / weekly /
  monthly / yearly.

Return {"objects": [...]}. If the command asks for nothing the app can do,
return {"objects": []}."""


def _iso(value, today):
    """A date the model returned, kept only if it is really a date."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    try:
        _dt.date.fromisoformat(v)
        return v
    except ValueError:
        return None


def _clock(value):
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if len(v) == 5 and v[2] == ":" and v[:2].isdigit() and v[3:].isdigit():
        return v
    return None


def build_objects(text: str, cfg) -> "tuple[list, int]":
    """The single call. Returns ([(action_name, intent)], llm_ms)."""
    from assistant.engine import llm as _llm

    today = _dt.date.today()
    user = (f"TODAY is {today.isoformat()} ({today.strftime('%A')}).\n"
            f"The command: {text}")
    out, ms = _llm.call_json(cfg, _SYSTEM, user, SCHEMA)
    return _to_intents(out.get("objects") or [], today), ms


def _to_intents(objects: list, today) -> list:
    """Objects -> the same (action, intent) pairs the chain produces.

    Anything malformed is DROPPED rather than repaired. The point is to measure
    what one call gets right; quietly fixing its output would measure the fixer.
    """
    from assistant.actions.calendar.intent import (
        CalendarIntent, DeleteEventIntent, QueryScheduleIntent, UpdateEventIntent)
    from assistant.actions.todo.intent import (
        CompleteTodoIntent, CreateTodoIntent, DeleteTodoIntent, QueryTodoIntent)

    pairs = []
    for o in objects:
        if not isinstance(o, dict):
            continue
        kind = str(o.get("kind", "")).strip()
        op = str(o.get("operation", "")).strip()
        title = (o.get("title") or "").strip()
        match = (o.get("match_title") or "").strip() or title
        try:
            if kind == "event" and op == "create":
                if not title:
                    continue
                pairs.append(("create_event", CalendarIntent(
                    title=title,
                    date=_iso(o.get("date"), today),
                    start_time=_clock(o.get("start_time")),
                    end_time=_clock(o.get("end_time")),
                    attendees=[a for a in (o.get("attendees") or []) if isinstance(a, str)],
                    location=(o.get("location") or None),
                    recurrence=(o.get("recurrence") or None) or None,
                    recur_until=_iso(o.get("recur_until"), today))))
            elif kind == "event" and op == "update":
                pairs.append(("update_event", UpdateEventIntent(
                    match_title=match or None,
                    new_date=_iso(o.get("date"), today),
                    new_start_time=_clock(o.get("start_time")))))
            elif kind == "event" and op == "delete":
                pairs.append(("delete_event", DeleteEventIntent(
                    match_title=match or None,
                    match_date=_iso(o.get("date"), today))))
            elif kind == "task" and op == "create":
                if not title:
                    continue
                # `quantities` is NOT passed: CreateTodoIntent's
                # fold_quantities is an after-validator that derives it from
                # the titles and overwrites whatever was handed in, so passing
                # it would be a dead parameter that merely looked wired. The
                # count travels in the title as the speaker said it ("buy 5
                # apples"), which is also how the rule path carries it — and
                # count-correctness reads len(titles) either way.
                pairs.append(("create_todo", CreateTodoIntent(
                    titles=[title],
                    list_name=(o.get("list_name") or "today"),
                    priority=(o.get("priority") or "none"),
                    due_date=_iso(o.get("due_date"), today),
                    tags=[])))
            elif kind == "task" and op == "complete":
                pairs.append(("complete_todo", CompleteTodoIntent(match_title=match or None)))
            elif kind == "task" and op == "delete":
                pairs.append(("delete_todo", DeleteTodoIntent(match_title=match or None)))
            elif kind == "query_events":
                pairs.append(("query_schedule", QueryScheduleIntent(
                    date=_iso(o.get("date"), today))))
            elif kind == "query_tasks":
                pairs.append(("query_todos", QueryTodoIntent()))
        except Exception as e:                      # a validator refused it
            logger.debug("one-shot object rejected: %s (%s)", o, e)
            continue
    return pairs


def run(state, cfg):
    """Stage-shaped entry: fill `state.items` from ONE model call."""
    from assistant.engine.state import Item
    from assistant.trace import LLM

    pairs, ms = build_objects(state.text, cfg)
    state.llm_ms += ms
    state.parse_path = "oneshot"
    state.items = [
        Item(id=f"item_{i + 1}",
             kind=("task" if "todo" in name else
                   "review" if "query" in name else "event"),
             text=state.text, action=name, intent=intent)
        for i, (name, intent) in enumerate(pairs)
    ]
    if state.trace:
        state.trace.step(LLM, "One-shot",
                         f"{len(pairs)} object(s) in {ms} ms: "
                         + ", ".join(n for n, _ in pairs) or "nothing",
                         path="oneshot")
    return state
