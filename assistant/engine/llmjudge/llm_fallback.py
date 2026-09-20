"""The model half of reading an item — and the three guards that make it safe.

PORTED FROM `fastrule/objects.py`, 2026-09-09 (Gil): *"before we start breaking
FastRule code, port what's relevant to the LLMJudge folder."* Step 0 of
`PLAN.md` §1.0. A MOVE with an import redirect, verbatim, **no behaviour
change** — FastRule still calls these at the same branch point.

WHY THE PORT CAME FIRST, and is not merely tidiness. Trim FastRule first and
these ~150 lines exist only in git history when the port happens, at which
point "port" quietly becomes "rewrite from memory". `_guard_inventions` is the
one that would be lost first, and it exists because a model once fabricated an
event onto the calendar (cycle 7) — nothing about its new home makes that risk
smaller.

WHAT IS **NOT** HERE, deliberately. `_parse_item` stays in `objects.py`: it is
the per-item BRANCH POINT (rules-vs-model), not a liftable unit, and splitting
it would be a behaviour change wearing a port's clothes. Phase B replaces it
with a `DEFER(INCAPACITY)` consumer; that is the shape §1.2 describes, and it
is not this step's business.

THE THREE GUARDS, none of which may be dropped on the way:

    _guard_inventions   a model-fabricated event never reaches the calendar.
                        Rule-parser output deliberately never routes through
                        it — rules are grounded by construction.
    _grounded_title     every content word of an LLM title must have been
                        spoken.
    _honour_refusal     a REFUSAL may be RESOLVED by the model, never
                        overturned. The one rule this codebase has already
                        broken once.
"""
from __future__ import annotations

import re

from assistant.engine.llmjudge.verdict import tokens as _tokens
from assistant.engine.state import EngineState, Item


def _llm_trace(state: EngineState, parser, cfg, title: str) -> None:
    from assistant.trace import LLM
    state.llm_ms += parser.last_llm_ms
    if state.trace:
        state.trace.step(LLM, title,
                         f"{cfg.llm_engine}:{getattr(cfg, cfg.llm_engine).model} · "
                         f"{parser.last_examples_used} history example(s) used",
                         raw=(parser.last_raw_response or "")[:1500] or None,
                         examples=parser.last_examples_used)


def _honour_refusal(got, res, item: Item, state: EngineState):
    """FastRule REFUSED this reading — the LLM may resolve the objection, but
    a bare re-read must not overturn it.

    The distinction that matters: for a generic-target veto ("delete this
    event" names nothing), the LLM legitimately fixes it by RESOLVING the
    reference to a real title — anaphora memory is exactly that job. What it
    must not do is hand back the same empty target and have it executed,
    which is what happened before the audit found this path. Empty slots
    surfacing as "I couldn't find…" is the right answer; guessing is not.
    """
    from assistant.trace import RULE

    if not got:
        return got
    if not (res.reason or "").startswith("generic-target"):
        return got          # the other refusals stand as parsed
    from assistant.engine.llmjudge.gatekeeper import _GENERIC_TARGET_RE
    # `_friendly` stays in `fastrule.objects` — it has eight other callers
    # there. Imported lazily, like the trace constant above, so neither module
    # resolves the other at import time and no cycle is possible. When phase B
    # dismantles `objects.py` this import fails loudly, which is the point:
    # a tripwire beats a silent loss.
    from assistant.engine.llmjudge.rescue import friendly as _friendly
    kept = []
    for name, intent in got:
        if name.startswith(("update_", "delete_", "complete_")):
            target = str(getattr(intent, "match_title", "") or "").strip()
            if not target or _GENERIC_TARGET_RE.match(target):
                # unresolved: the model gave back the same bare noun
                state.messages.append(
                    "I wasn't sure which one you meant, so I left it alone.")
                if state.trace:
                    state.trace.step(RULE, f"Held back {_friendly(item.id)}",
                                     f"“{target or 'no target'}” names nothing "
                                     "specific — refusing rather than guessing",
                                     ok=False)
                continue
        kept.append((name, intent))
    return kept


#: Words too generic to ground a title on their own (cycle 7).
_TITLE_STOP = {"the", "a", "an", "and", "with", "for", "new", "my", "our"}


def _grounded_title(title: str, text: str) -> bool:
    """Every content word of an LLM event title must be spoken in the item's
    own words, prefix-stemmed so "Meeting" grounds on "meet". A title the
    words never said is a fabrication (hypothesis #5: garble input produced
    "New Event", conference room, 10:00-11:00 — none of it in the words)."""
    words = [w for w in _tokens(title)
             if len(w) > 2 and w not in _TITLE_STOP]
    if not words:
        return True                       # bare/stopword titles judged elsewhere
    toks = set(_tokens(text))
    def ok(w: str) -> bool:
        stem = w[:4]
        return any(tk.startswith(stem) or w.startswith(tk[:4])
                   for tk in toks if len(tk) > 2)
    return all(ok(w) for w in words)


#: A recurrence is the one word field the speaker never says verbatim — they
#: say "every monday", the object says `weekly`. So it is grounded on the
#: MARKER instead: no marker in the words, no repeat. Measured on dev-100
#: (2026-09-20): "reopen groceries and add milk" came back as a DAILY event.
_RECUR_MARKER_RE = re.compile(
    r"\b(every|each|daily|weekly|monthly|yearly|annually|nightly|"
    r"repeat(?:s|ing|ed)?|recurring|regularly|always|"
    r"mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays|"
    r"weekdays|weekends)\b", re.I)


#: THE COMMAND FRAME, not the thing asked for. A model answering "send me a
#: reminder to pick up my dog from the groomer" hands back the whole sentence
#: as the title, and every grounding test passes it — the words ARE the
#: speaker's, sliced in the wrong place. Six of the thirteen junk titles left
#: on dev-100 after cycle 29 are this one shape (2026-09-20).
#:
#: DELIBERATELY ONLY THE REMINDER FRAMES. `build._title_from_words` strips a
#: much wider set, and measured against the 7,200's gold it would rewrite
#: **206** titles the parser already had right — "book club" -> "club",
#: "schedule a haircut" -> "haircut". These frames rewrite **0**. A title that
#: keeps a stray word beats one that loses a real one.
_COMMAND_FRAME = re.compile(
    r"^\s*(?:(?:please\s+)?(?:send|give)\s+me\s+(?:an?\s+)?"
    r"(?:reminder|alert|notification)\s+(?:to|about|of|for|that)\s+"
    r"|(?:set|create|add|make)\s+(?:an?\s+)?(?:reminder|alert)\s+"
    r"(?:to|about|of|for|that)\s+"
    r"|remind\s+(?:me\s+)?(?:to|about|of|when|that|early)\s+)", re.I)


def _trim_command_frame(value: str) -> str:
    """The title minus the frame that asked for it. Empty result means the
    title was ALL frame ('remind me'), and the original is kept so the
    names-nothing veto judges it rather than a blank."""
    trimmed = _COMMAND_FRAME.sub("", value or "").strip(" ,.;:")
    return trimmed or value


def _guard_inventions(got, item: Item, state: EngineState):
    """Drop LLM-fabricated events, and STRIP fabricated fields off real ones.

    Cycle 7 built the first half: an event whose TITLE the words never said is
    a fabrication and the whole object goes (rule-parser output never routes
    through here — rules are grounded by construction). An emptied list falls
    through to the event-kind retry / event_fallback / honest unknown.

    Cycle 29 (2026-09-20) adds the second half, and the asymmetry is the same
    one the judge routes on: a fabricated SUBJECT means there is no object,
    while a fabricated VALUE on a real object is one bad field. The rescue was
    inventing three of them and the loop could not fix any — the judge refuses
    them every round and the rewrite cannot change what the parser returns:

        "The list should not contain all food items with the prefix dry"
            -> 'Grocery List Review' AT HOME
        "reopen groceries and add milk"       -> a DAILY event
        "make a list of thing I have to shop" -> todo titles milk, eggs, bread

    So: an ungrounded location is dropped and the event kept; a recurrence
    with no marker in the words is dropped; a to-do's ungrounded titles are
    dropped and the object goes only when none survive. Every drop is a `Fix`
    in the trace, because a field removed silently is as dishonest as one
    invented.
    """
    if not got:
        return got
    kept = []
    for name, intent in got:
        if name == "create_event" and item.kind != "task":
            title = str(getattr(intent, "title", "") or "")
            framed = _trim_command_frame(title)
            if framed != title:
                state.add_fix("generate", "title_frame_trimmed", title[:40], framed[:40],
                              note="the command frame is not the thing asked for")
                intent.title = title = framed
            if not _grounded_title(title, item.text):
                state.add_fix("generate", "invention_guard", title[:40], "",
                              note="LLM title not grounded in the item's words")
                continue
        _strip_ungrounded_fields(name, intent, item, state)
        if name == "create_todo" and not (getattr(intent, "titles", None) or []):
            continue                      # nothing of it was the speaker's
        kept.append((name, intent))
    return kept


def _strip_ungrounded_fields(name: str, intent, item: Item, state: EngineState) -> None:
    """Remove the word fields the item's own words do not support."""
    words = item.text or ""

    location = str(getattr(intent, "location", "") or "")
    if location and not _grounded_title(location, words):
        state.add_fix("generate", "invention_guard", location[:40], "",
                      note="LLM location not grounded in the item's words")
        intent.location = None

    recurrence = str(getattr(intent, "recurrence", "") or "")
    if recurrence and not _RECUR_MARKER_RE.search(words):
        state.add_fix("generate", "invention_guard", recurrence, "",
                      note="a repeat the words never asked for")
        intent.recurrence = None
        if getattr(intent, "recur_days", None):
            intent.recur_days = []

    titles = list(getattr(intent, "titles", None) or [])
    if name == "create_todo" and titles:
        framed = [_trim_command_frame(str(t)) for t in titles]
        if framed != [str(t) for t in titles]:
            state.add_fix("generate", "title_frame_trimmed",
                          ", ".join(map(str, titles))[:40], ", ".join(framed)[:40],
                          note="the command frame is not the thing asked for")
            intent.titles = titles = framed
        good = [t for t in titles if _grounded_title(str(t), words)]
        if len(good) != len(titles):
            dropped = [t for t in titles if t not in good]
            state.add_fix("generate", "invention_guard", ", ".join(map(str, dropped))[:40], "",
                          note="LLM to-do titles not grounded in the item's words")
            intent.titles = good
            q = list(getattr(intent, "quantities", None) or [])
            if len(q) == len(titles):
                intent.quantities = [n for n, t in zip(q, titles) if t in good]
