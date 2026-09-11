"""The model half of judging — ONE call, and it is asked for EVIDENCE.

    ground_claims(state, cfg, objs) -> {(oid, field): words | None}

## What this stage does NOT do any more (Gil, 2026-09-10)

It used to make a second call, `extract_asks`, which asked the model to list the
separate things the raw text asked for — and then diffed that list against the
objects to find a `missing` ask or an `extra` object.

> *"I don't want extraction, that defeats the point of what segmentation →
> decompose_validate → FastRule did. The job of this task is to verify which
> objects to commit and label (or just pass to review panel) or pass back as X1'
> as a rewrite to redo."*

He is right, and the stage's own boards say so. Segmentation ALREADY decided how
many asks there are — deterministically, with its own dataset and its own board.
Asking an 8B to decide again produced a second, weaker answer, and every
disagreement was scored as segmentation's fault. Three things the project had
already measured:

    the only false flag on this stage's board was the extraction inventing an
    ask out of "i already handled it"
    run 8 measured 39 loop storms, most of them the matcher's artefact rather
    than real over-production
    segmentation is FROZEN, so a `missing` finding blamed a stage nobody is
    allowed to change, and X1' existed to work around it

So the recall direction is gone, and with it a model call: this stage is now one
call instead of two, and strictly per-object.

## Why the remaining call asks for evidence and never for a verdict

Asked *"is this object correct?"* an 8B says yes. That is the accept bias, the
same family as the verbosity, position and rubric-order effects the
LLM-as-judge literature measures — prompt SHAPE moves a small model's verdict
more than object QUALITY does. Here a rubber stamp writes a wrong row to the
calendar.

So the model is given a COPYING task: quote the words behind each field, or say
`none`. `verdict.py` turns those answers into findings. The model never sees a
score, never names a stage, and never decides what commits.

`ground_claims` is skipped entirely when no object has a word claim — the
temporal fields are decided from `item.slots` without a model at all
(`render.py` explains why), so a command whose only doubt is a date costs
nothing.
"""
from __future__ import annotations

from assistant.engine.llmjudge import render

# ---------------------------------------------------------------------------
# The words behind each field — the ONE question this stage asks a model
# ---------------------------------------------------------------------------

_GROUND_SCHEMA = {
    "type": "object",
    "properties": {
        "grounding": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "field": {"type": "string"},
                    "words": {"type": "string"},
                },
                "required": ["id", "field", "words"],
            },
        },
    },
    "required": ["grounding"],
}

_GROUND_SYSTEM = """You are given ONE voice command exactly as the speaker said \
it, and the objects a program built from it.

For EVERY field listed under every object, quote the speaker's OWN words that
gave that field its value. Copy the words straight out of the command.

- Never rephrase, never summarise, never explain, never invent.
- If NOTHING in the command supports the field, the answer is exactly: none

A field IS supported when the words mean the same thing in different clothes:
  title=dentist        is supported by "my dentist appointment"  -> "dentist appointment"
  title=call mom       is supported by "ring my mother"          -> "ring my mother"
A field is NOT supported when you cannot point at any words:
  a name nobody said, or a generic word the program supplied itself
  (title=event, title=reminder, title=appointment are almost always none —
   they are the program's own word for a calendar entry, not a name for one).

Answer for every field you are shown, once each, using the exact id and the
exact field name given.

Example.
The command: book gym tomorrow at 7am with Tal
Objects:
[obj_1] create event · title=gym · attendees=Tal
    title = gym
    attendees = Tal
→ {"grounding": [{"id": "obj_1", "field": "title", "words": "gym"},
                 {"id": "obj_1", "field": "attendees", "words": "with Tal"}]}

Example.
The command: set an event for the evening
Objects:
[obj_1] create event · title=Event
    title = Event
→ {"grounding": [{"id": "obj_1", "field": "title", "words": "none"}]}

Return JSON: {"grounding": [{"id": ..., "field": ..., "words": ...}, ...]}"""


def ground_claims(state, cfg, objects) -> "dict | None":
    """`{(oid, field): words}` — words is None when the command never said it.

    `objects` is [(oid, action, intent, slots), …]. Only WORD claims are asked
    about; the slot-backed ones were already decided deterministically, and
    showing them here would invite the model to re-decide an answer it cannot
    improve on.

    None means the model could not be consulted — same contract as
    `extract_asks`, and the same reason.
    """
    from assistant.engine import llm as _llm

    blocks, wanted = [], []
    for oid, action, intent, slots in objects:
        cs = [c for c in render.claims(action, intent, slots) if c.needs_model]
        if not cs:
            continue
        blocks.append(render.render_block(oid, action, intent, slots))
        wanted += [(oid, c.label) for c in cs]
    if not wanted:
        return {}                     # nothing for a model to say — not a failure

    user = (f"The command: {state.raw_text}\n"
            f"Objects:\n" + "\n".join(blocks))
    try:
        out, ms = _llm.call_json(cfg, _GROUND_SYSTEM, user, _GROUND_SCHEMA)
        state.llm_ms += ms
    except Exception:
        return None

    got: dict = {}
    for d in (out.get("grounding") or []):
        if not isinstance(d, dict):
            continue
        key = (str(d.get("id", "")).strip(), str(d.get("field", "")).strip())
        if key not in wanted or key in got:
            continue                  # unknown id/field, or said twice
        words = str(d.get("words", "")).strip()
        got[key] = None if words.lower() in ("", "none", "null", "n/a") else words
    # A field the model simply did not answer for is NOT evidence of invention —
    # it is a model that ran out of attention on a long list. Absent stays
    # absent, and `verdict.py` treats absent as "no opinion", never as "none".
    return got


# ---------------------------------------------------------------------------
# The NAME question — cycle 7, 2026-09-10
# ---------------------------------------------------------------------------

_NAME_SCHEMA = {
    "type": "object",
    "properties": {
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["id", "name"],
            },
        },
    },
    "required": ["names"],
}

_NAME_SYSTEM = """You are given ONE voice command and a list of calendar entries \
a program made from it. Each entry is described by its WHEN only — its name has \
been hidden from you.

For each entry, write what the COMMAND calls that thing, using the speaker's own
words. Copy the words; do not rephrase and do not invent.

- Give the subject only — not the verb, not the date, not the time.
  "book a meeting with Sage this evening"  -> "meeting with Sage"
  "remind me to call the plumber tomorrow" -> "call the plumber"
- If the command names nothing for an entry, the answer is exactly: none

Example.
The command: book gym tomorrow at 7am and call mum at 6
Entries:
[obj_1] an event on Tuesday at 07:00
[obj_2] an event on Tuesday at 18:00
→ {"names": [{"id": "obj_1", "name": "gym"},
             {"id": "obj_2", "name": "call mum"}]}

Example.
The command: set an event for the evening
Entries:
[obj_1] an event on Tuesday at 19:00
→ {"names": [{"id": "obj_1", "name": "none"}]}

Return JSON: {"names": [{"id": ..., "name": ...}, ...]}"""


def name_objects(state, cfg, objects) -> "dict | None":
    """`{oid: what the COMMAND calls this thing}` — None where it names nothing.

    ## Why this replaced "which words support this title?"

    Cycle 5 measured the near-miss case at **1 caught in 19**: shown
    "meeting groceries" against *"book a meeting with Sage this evening"*, the
    model quotes "meeting" and calls the field supported. Every failure had that
    shape.

    A SHOWN VALUE IS AN ANCHOR. Asking an 8B whether a value it can see is
    supported invites it to find any thread connecting the two, and a near miss
    always has one — that is what makes it near. So the title is HIDDEN and the
    model is asked to produce one from the words instead.

    The founding rule is untouched: this is still extraction, and
    `verdict.py` still does the deciding by diffing the produced name against
    the object's actual title. What changes is that the model can no longer
    rationalise, because it has nothing to rationalise toward.

    Objects are identified to the model by their WHEN alone, which is what makes
    the question answerable for a multi-object command without showing the very
    thing being checked.
    """
    from assistant.engine import llm as _llm

    lines, wanted = [], []
    for oid, action, intent, slots in objects:
        if not any(c.needs_model and _IDENTITY_LABEL(c.label)
                   for c in render.claims(action, intent, slots)):
            continue
        kind = "a to-do" if "todo" in (action or "") else "an event"
        when = _when_phrase(intent)
        lines.append(f"[{oid}] {kind}{when}")
        wanted.append(oid)
    if not wanted:
        return {}

    user = (f"The command: {state.raw_text}\n"
            f"Entries:\n" + "\n".join(lines))
    try:
        out, ms = _llm.call_json(cfg, _NAME_SYSTEM, user, _NAME_SCHEMA)
        state.llm_ms += ms
    except Exception:
        return None

    got: dict = {}
    for d in (out.get("names") or []):
        if not isinstance(d, dict):
            continue
        oid = str(d.get("id", "")).strip()
        if oid not in wanted or oid in got:
            continue
        name = str(d.get("name", "")).strip()
        got[oid] = None if name.lower() in ("", "none", "null", "n/a") else name
    return got


def _IDENTITY_LABEL(label: str) -> bool:
    return label == "target" or label == "title" or label.startswith("title_")


def _when_phrase(intent) -> str:
    """The locator shown instead of the name. Deliberately vague — enough to
    tell two entries apart, never enough to hint at what either is called."""
    import datetime as _dt
    date = str(getattr(intent, "date", "") or getattr(intent, "due_date", "") or "")
    start = str(getattr(intent, "start_time", "") or "")
    bits = []
    try:
        bits.append(_dt.date.fromisoformat(date).strftime("on %A %-d %B"))
    except (ValueError, TypeError):
        pass
    if start:
        bits.append(f"at {start}")
    return (" " + " ".join(bits)) if bits else ""
