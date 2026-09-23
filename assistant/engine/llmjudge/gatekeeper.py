"""The intent-level vetoes — readings that must not execute as stated.

PORTED FROM FastRule, 2026-09-09 (Gil): *"before we start breaking FastRule
code, port what's relevant to the LLMJudge folder."* This is step 0 of
`PLAN.md` §1.0, and it is a MOVE with an import redirect — the code arrived
verbatim, FastRule still calls it, and **no behaviour changed**. The
restructure that follows (§1.1: the veto becoming prompt CONTEXT rather than a
refusal) is deliberately NOT part of this step, so that any number that moves
later is provably the restructure and not the relocation.

Why it lives here now. As a veto this has exactly one move — refuse — and a
refusal ends the conversation. The objection it raises is precisely the kind a
model CAN answer: "move it" has an antecedent somewhere in the utterance, and
resolving anaphora is what a language model is for. Handed to the model as
context, the same judgement becomes answerable instead of terminal.

    a mutation aimed at a bare noun   "move it to five"        -> move WHAT?
    a rename that would misroute      "rename X to Y"          -> which store?
    an interrogative that would create "should I book the gym?" -> creates 'gym'

THE RULE THIS MUST NOT BREAK. `REFUSAL` means *the LLM may RESOLVE the
objection but must never overturn it* — the deep track once re-committed
exactly what the front door had vetoed, and the engine audit named it:

    the model MAY answer  "move it"  ->  "move the dentist appointment"
    the model may NOT     "move it"  ->  "move it"   (the same empty target)

The reason-class contract (`REFUSAL` / `STRUCTURE` / `INCAPACITY`) deliberately
STAYS in `fastrule.fastrule`: the DEFER is FastRule's product and that is the
vocabulary it is written in, with three other readers. A consumer importing the
vocabulary of a value it consumes is the right direction; moving the contract
into one of its readers would invert it.
"""
from __future__ import annotations

import re

_GENERIC_TARGET_RE = re.compile(
    # "note" and "date" joined on 2026-09-20: "make a NOTE of it on the
    # corresponding date" committed an event titled 'note' at confidence
    # 0.86, and "set a DATE for this" one titled 'date' — the program's words
    # for an entry, not names for one (dev-100 checkpoint).
    # Q42 (Gil, 2026-09-22) split this arm in three. A bare KIND — "event",
    # "an appointment", "the date" — is no longer generic: it commits with its
    # day and clock and the phone hints once. What still names nothing: the
    # kind behind a DEMONSTRATIVE ("this event" — an anaphor), the program's
    # FURNITURE with any article (list, note, calendar, agenda, entry, item,
    # thing), and a kind with a pronoun tail ("note of it", "event for this").
    r"^(?:this |that |these |those )(?:reminder|alert|event|appointment|task|todo|list|note|date|meeting)s?$"
    r"|^(?:my |the |a |an |this |that |new |another )?(?:list|note|calendar|calender|schedule|agenda|entry|item|thing)s?$"
    r"|^(?:my |the |a |an |this |that )?(?:reminder|alert|event|appointment|task|todo|list|note|date|meeting)s?"
    r"\s+(?:of|for|about)\s+(?:it|this|that|me)$"
    # `i` and `we` joined the pronoun list on 2026-09-10. The list already held
    # you/it/me/this/that/them, and "i" fell through every check: it is 1
    # character, so the content-word filters drop it and `names_nothing_spoken`
    # returns False on an empty word list. Measured: "i'm free christmas day so
    # book staff meeting at 5 pm" produced an event titled **"i"** with no
    # finding raised against it.
    r"|^(?:you|i|we|us|it|me|this|that|them)$"
    # A PRONOUN WITH A DESTINATION names nothing either: "add THIS ON MY
    # CALENDER" titled an event 'this on my calender', the judge raised
    # nothing (every word WAS spoken) and it was written (dev-100 run 22 and
    # still in run 26). The anaphor is the subject and the rest is where to
    # put it. Measured before writing: 0 of the 7,200 gold titles and 0 of
    # the 3,000 real utterances have this shape, so nothing legitimate is
    # caught — the deep track may still RESOLVE it, which is what the
    # REFUSAL class means.
    r"|^(?:you|i|we|us|it|me|this|that|them|these|those)\s+"
    r"(?:on|to|in|for|at|from|off|with|about)\b"
    # A DETERMINER AND "ONE" IS A PRONOUN, NOT A NAME (cycle 44, 2026-09-22):
    # "that one", "this one", "the last one", "the other ones". The first
    # pass refused "um can you just delete that one for me" only by accident
    # — validate's anaphor guard matched "you just" and rewrote the target to
    # "it" — and the loop's trim took "can you" off, the guard fell silent,
    # and the model round handed back `delete_event "that one"`: the front
    # door's REFUSAL overturned by the loop, on the seeded Board D the one
    # row it broke. Measured before writing: 16 of 4,629 FastRule train gold
    # titles match, every one a `generic_target` row the corpus itself marks
    # unresolvable; "one on one", "capital one", "the one with dan" do not.
    # The front door (`rule_parser.names_something`) refuses the same shape.
    r"|^(?:the |this |that |these |those |my |your )?"
    r"(?:last |first |next |previous |other |same |new |second )?ones?$",
    re.I)

# "Can you create/add/make …" is a polite imperative, not a question —
# the speaker wants the thing made (F4a; "Can you create a new list in my
# podcast?" was gate-blocked despite a correct create parse).
_POLITE_IMPERATIVE_RE = re.compile(
    r"^\s*(?:hey\s+\w+,?\s*)?(?:can|could|would|will)\s+you\s+(?:please\s+)?"
    r"(?:create|add|make|set|put|start|book|schedule|remind)\b", re.I)

_INTERROGATIVE_RE = re.compile(
    r"^\s*(?:hey\s+\w+,?\s*)?(?:who|what|when|where|which|whose|how|do|does|did|is|are|am|can|could|would|will|should)\b"
    r"|\bcould you (?:tell|let me know|check)\b|\bdo i have\b|\?\s*$",
    re.I)


def _which_store_holds(title: str) -> "str | None":
    """"event", "task", or None — where the user's own data says this lives.

    This is the question the rename gate was created because FastRule could
    NOT answer: "rename flu shot to sales call" defers because the rules
    cannot know whether "flu shot" is on the calendar or the task list. The
    user's own stores know. One indexed query answers it, for any user, on
    day one, with no training and no developer.
    """
    q = (title or "").strip()
    if len(q) < 3:
        return None
    try:
        from assistant.db import get_db
        db = get_db()
        ev = db.search_events(q, limit=2)
        td = db.search_todos(q, limit=2)
    except Exception:
        return None
    if ev and not td:
        return "event"
    if td and not ev:
        return "task"
    return None          # absent, or ambiguous — defer, never guess


def _names_something_real(target: str) -> bool:
    """Does the user's own calendar or task list actually contain this?

    PERSONALISATION BY LOOKUP, NOT BY TRAINING (Gil, 2026-09-07). The shipped
    models stay generic and identical for every user; the personal part is
    the data they are pointed at. So "delete the dentist" is generic English
    to a model, but if THIS user has an event called "dentist appointment",
    it names something real and FastRule can act on it. Works for a brand-new
    user on day one, needs no refit, and needs no developer.

    Costs one indexed query. Any failure means "not resolved" — a lookup
    problem must never turn into a commit.
    """
    q = (target or "").strip()
    if len(q) < 3:
        return False
    try:
        from assistant.db import get_db
        db = get_db()
        return bool(db.search_events(q, limit=1) or db.search_todos(q, limit=1))
    except Exception:
        return False


class Gatekeeper:
    """Intent-level vetoes, v1 order: interrogative (with the polite
    exemption), rename-misroute, generic-target."""

    def judge(self, text: str, intents) -> "str | None":
        if (_INTERROGATIVE_RE.search(text)
                and not _POLITE_IMPERATIVE_RE.search(text)
                and any(n.startswith("create_") for n, _ in intents)):
            return "interrogative-create"
        if re.match(r"^\s*(?:please\s+)?rename\b", text, re.I):
            # ON THE PHRASING, not on the misroute. Until 2026-09-20 this fired
            # only when the rename parsed as a CREATE — which every rename did,
            # so the condition was invisible. The router now reads the leading
            # imperative first and "rename flu shot to sales call" parses as
            # the update it is; the gate's reason still holds (the rules cannot
            # know WHICH store holds the old title), so it must fire on the
            # word "rename" itself, and the lookup below decides.
            # The gate exists because the rules cannot know WHICH store holds
            # the old title. The user's own data can: if exactly one store
            # has it, the rename is resolvable and no longer a misroute.
            # …and only when the PARSE AGREES with what the data says. The
            # probe that built this found the gate was doing double duty: it
            # deferred both because the store was unknown AND because the
            # parse was wrong ("rename flu shot to sales call" parses as
            # create_todo). Resolving the store alone would have committed
            # that wrong action, so the lookup must CONFIRM the parse, never
            # merely permit it.
            m = re.match(r"^\s*(?:please\s+)?rename\s+(.+?)\s+to\s+", text, re.I)
            store = _which_store_holds(m.group(1)) if m else None
            parsed_domain = ("task" if any("todo" in n for n, _ in intents)
                             else "event")
            if store is not None and store == parsed_domain and not any(
                    n.startswith("create_") for n, _ in intents):
                pass                    # data and parse agree — resolvable
            else:
                return "rename-misroute"
        # The same veto on the CREATE side, which it never had. "Create an
        # event now to go out for a run" parses to a create_event titled
        # "event" — the word for a calendar entry, not a name for one — and
        # FastRule committed it at confidence 1.00. Real usage, 2026-09-08:
        # the user got an event called "event" at midnight.
        #
        # A generic TARGET on a mutation and a generic TITLE on a create are
        # the same failure: the rules found a shape and no subject. It is a
        # REFUSAL, so the deep track may RESOLVE it — the model reads "go out
        # for a run" as the title, which it does — but must not re-commit the
        # empty one.
        #
        # Deliberately `_GENERIC_TARGET_RE`, NOT validate's
        # `is_placeholder_title`: that one answers "could this title be
        # improved?" and flags "meeting with Sam", a perfectly good event to
        # create. Using it as a commit veto broke 14 tests. The question here
        # is the narrow one — is the title ONLY the generic noun, no subject.
        for name, intent in intents:
            if not name.startswith("create_"):
                continue
            titles = [str(getattr(intent, "title", "") or "")]
            titles += [str(x) for x in (getattr(intent, "titles", None) or [])]
            for title in titles:
                title = title.strip()
                if title and _GENERIC_TARGET_RE.match(title):
                    return f"generic-title:{title}"
        for name, intent in intents:
            if name.startswith(("update_", "delete_", "complete_")):
                target = str(getattr(intent, "match_title", "") or "").strip()
                if _GENERIC_TARGET_RE.match(target):
                    # …unless the user's own data says it names something.
                    # "the dentist" is generic English and a real event.
                    if _names_something_real(target):
                        continue
                    return f"generic-target:{target}"
        return None
