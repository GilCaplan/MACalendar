"""Step 3 — decompose items that are really several things, or one thing × N.

Contract (see DOCUMENTATION/ENGINE.md):
  reads   state.items
  writes  state.items (may replace an item with sub-items id "item_N-M",
          may fill item.slots: quantity, reminder_minutes), trace steps (RULE)

Bounded: one decomposition pass over the step-2 items — an item is split at
most once (ids go one level deep, "item_1-2", never "item_1-2-3").

Deterministic reuse, no LLM here yet:
  • task lists ride assistant/intent/list_split.py — "buy chicken and rice"
    is two tasks, the verb handed down, idioms and prepositions respected;
  • counts ride assistant/intent/quantity.py — "buy 5 apples" is ONE task of
    (apples, 5), never five rows (ticking one of five identical rows tells
    you nothing);
  • an event said at two times ("walk the dog at 9am and 2:30pm") is split by
    SEGMENTATION, not here (2026-09-26).
"""

from __future__ import annotations

import re

from assistant.engine.state import EngineState, Item

# THE TIME SPLITTERS ARE GONE (2026-09-26, Gil: "sure can try"). "walk the dog
# at 9 and 2:30" is two items straight out of segmentation (its bounded
# enumeration, §8.1), so the regex split here never fired — 0 of 2,699 real
# commands and 0 of 6,000 FastRule train commands — and the model split fired
# only where segmentation's time list did not know a spoken clock ("at 6 in
# the evening and 7am"), which segmentation now reads. Splitting is
# segmentation's (decompose_validate/PLAN.md §4d, 2026-09-08); this stage made
# its only model call here.


def _split_tasks(item: Item) -> "list[Item] | None":
    """The list splitter, with the same discipline segment's clause tier has:
    every piece must be an ASK.

    `list_split` is pure string work, so it cuts at commas and "and" without
    being able to tell a request from the words around one. That was invisible
    while most to-dos were mis-kinded as events and never reached here; fixing
    the kind decision routed them all in at once and the tears surfaced —
    "wash the car, done and dusted" became "wash done" + "wash dusted",
    "pack and label the boxes" left a task called "pack", and a tag question
    ("does that seem right") became an item of its own.

    The whole split is refused rather than the bad piece dropped: those words
    are still part of the command, and a merged item is recoverable where
    deleted words are not.
    """
    from assistant.intent.asks import every_part_is_an_ask
    from assistant.intent.list_split import ACTION_VERBS, split_items

    parts = [p.strip() for p in split_items(item.spoken()) if p.strip()]
    if len(parts) <= 1:
        return None
    if not every_part_is_an_ask(parts, ACTION_VERBS):
        return None
    # ONE ERRAND, SEVERAL THINGS — the only shape this split is for (Gil,
    # 2026-09-26: a list is "another type of recurrence, which would be fine
    # to keep"). Measured on the FastRule 7,200 train half, 253 splits and
    # about 180 of them were not lists at all: a comma before a remark ("mark
    # it done, finally got to it"), a time ("block out the 30th …, all day"),
    # a weekday ("every tuesday and thursday" -> 'print thursday'). Every part
    # must read "<errand verb> <a short thing>"; otherwise the item stays whole
    # and an under-split is segmentation's to fix.
    from assistant.intent.list_split import is_errand_list
    if not is_errand_list(parts):
        return None
    return [Item(id=f"{item.id}-{j}", kind="task", text=p,
                 slots=dict(item.slots))
            for j, p in enumerate(parts, start=1)]


def _extract_quantity(item: Item) -> None:
    from assistant.intent.quantity import split_quantity
    clean, count = split_quantity(item.spoken())
    if count > 1:
        item.slots["quantity"] = count
        item.text = clean
        item.time = None   # folded into text above


def _strip_reminder_clause(item) -> None:
    """Pull a spoken lead time out of the item text into slots (cycle 8).

    The clause pattern and the minute arithmetic live in
    assistant/intent/lead_time.py — FastRule needs the same reader, and one
    copy cannot drift from the other."""
    from assistant.intent import lead_time

    rest, minutes = lead_time.split(item.spoken())
    if minutes is None:
        return
    item.slots["reminder_minutes"] = minutes
    item.text = rest
    item.time = None   # folded into text above


def run(state: EngineState, cfg) -> EngineState:
    from assistant.trace import RULE

    out: list = []
    split_notes: list[str] = []
    for item in state.items:
        if item.kind == "event":
            _strip_reminder_clause(item)
        subs = None
        if item.kind == "task":
            subs = _split_tasks(item)
            if subs:
                split_notes.append(f"{item.id}: {len(subs)} tasks")
        for it in (subs or [item]):
            if it.kind == "task":
                _extract_quantity(it)
                if it.slots.get("quantity"):
                    split_notes.append(f"{it.id}: ×{it.slots['quantity']}")
            out.append(it)
    state.items = out

    if state.trace and split_notes:
        state.trace.step(RULE, "Decomposed", "; ".join(split_notes))
    return state
