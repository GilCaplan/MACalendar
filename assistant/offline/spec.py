"""What the phone's on-device model is told — served, cached, versioned.

The phone compiles only the item SHAPE (`SCHEMA`: kind, title, date, start,
end, recurrence) into a `@Generable` struct; everything the model is TOLD
lives here, so improving the offline reader is an edit to this file and the
phone picks it up the next time it reaches the Mac. `version` is a hash of the
text, so nobody has to remember to bump it.

The rules below are the engine's rulings restated for a small model, each
tagged with the DEVQA question it comes from. They are guidance for a
PROVISIONAL reading — the Mac re-reads every command — so they aim to be right
about the common cases, not complete.
"""
from __future__ import annotations

import hashlib
import json

#: The shape of `offline_reading` and of the reply's `offline` block. Bump when
#: either changes; the Mac answers `unverified` to a protocol it doesn't know.
PROTOCOL = 1

#: The shape of ONE item, compiled into the app (`OfflineReader.swift`). A
#: served spec the app was not built for is ignored in favour of its bundled
#: copy. `tests/unit/test_offline_protocol.py` holds the Swift side to this.
SCHEMA = 2

KINDS = ("event", "todo", "other")
RECURRENCES = ("none", "daily", "weekly", "monthly", "yearly")

#: What the phone may book before the Mac has seen it. Never an edit of an
#: existing row (CLAUDE.md: deleting is destructive; a cache can be stale).
MAY_COMMIT = ("event", "todo")

INSTRUCTIONS = """\
You turn one spoken calendar command into items. The words come from speech \
recognition on a phone and can be slightly misheard.

Give one item per thing the speaker asked for, in the order they said them.

kind:
- event: something that happens on a day or at a time - a meeting, class, \
appointment, meal, trip, or seeing or calling a person.
- todo: something to get done with no day and no time said ("buy milk", \
"email the landlord"). No day and no clock time means a todo.
- other: anything that is not adding something new - moving, changing, \
renaming, deleting, cancelling, completing or ticking off, or a question. \
Put the speaker's request in the title; it is left for the Mac.

Seeing or calling a person is an event, even with no time said: use 09:00 on \
the soonest day that fits.

title: the thing itself, short, in the speaker's own words. Keep people's \
names and the errand verb ("pick up Sarah", "buy flowers for mom"). Leave out \
the date, the time, and openers like "remind me to", "add", "put in".

when: the words that say which DAY, copied exactly as said ("tomorrow", \
"next tuesday", "on friday", "march 5th", "the 21st"). Empty when no day was \
said. Do not work out the date - that is done for you.
start and end: 24-hour HH:MM. Empty when not said. A bare "7" or "8" with no \
am or pm means the evening (19:00, 20:00). Only give an end when one was said.
recurrence: none, daily, weekly, monthly or yearly - only when the speaker \
said it repeats ("every", "each", "daily"). The date is then the first one.

Never invent a date, a time, a place or a person that was not said."""

#: Few-shot examples. Each carries its own "today" so it stays true forever.
EXAMPLES = [
    {"today": "2026-09-28 (Monday)", "said": "dentist tomorrow at 3pm",
     "items": [{"kind": "event", "title": "Dentist", "when": "tomorrow",
                "start": "15:00", "end": "", "recurrence": "none"}]},
    {"today": "2026-09-28 (Monday)", "said": "remind me to buy milk",
     "items": [{"kind": "todo", "title": "Buy milk", "when": "", "start": "",
                "end": "", "recurrence": "none"}]},
    {"today": "2026-09-28 (Monday)", "said": "call Sarah on Thursday",
     "items": [{"kind": "event", "title": "Call Sarah", "when": "on thursday",
                "start": "09:00", "end": "", "recurrence": "none"}]},
    {"today": "2026-09-28 (Monday)", "said": "gym every sunday at 7",
     "items": [{"kind": "event", "title": "Gym", "when": "sunday",
                "start": "19:00", "end": "", "recurrence": "weekly"}]},
    {"today": "2026-09-28 (Monday)", "said": "move my dentist to friday",
     "items": [{"kind": "other", "title": "move my dentist to friday", "when": "",
                "start": "", "end": "", "recurrence": "none"}]},
    {"today": "2026-09-28 (Monday)",
     "said": "meeting with Avi next tuesday from 10 to 11 and email the landlord",
     "items": [{"kind": "event", "title": "Meeting with Avi", "when": "next tuesday",
                "start": "10:00", "end": "11:00", "recurrence": "none"},
               {"kind": "todo", "title": "Email the landlord", "when": "", "start": "",
                "end": "", "recurrence": "none"}]},
]


#: Words said before the command's verb, stripped before the guard looks.
LEAD_INS = ["please", "hey", "ok", "okay", "so", "um", "uh", "just", "also", "and",
            "yeah", "yes", "alright", "right", "ok google", "hey google", "hey siri",
            "siri", "alexa", "assistant",
            "can we", "could we", "to",
            "can you", "could you", "would you", "will you", "i need you to",
            "i want you to", "i've", "i have", "i"]
#: A command starting with one of these asks, not tells.
QUESTION_STARTS = ["what", "what's", "whats", "when", "when's", "where", "which", "who",
                   "how", "do i", "does", "did i", "is", "am i", "are", "have i",
                   "tell me", "can you tell me", "could you tell me", "show me",
                   "summarize", "can you check", "could you check",
                   "check what", "check if", "check whether", "walk me through"]
#: Phrasings of an EDIT that do not lead with the verb (TRAIN families of the
#: first guard run, 2026-09-29: "X is now at 9:15", "call it X instead of Y",
#: "set X as high priority", "i'm done with X", "change X to 9", "mark X as done").
EDIT_FRAMES = [
    r"\bis\s+now\s+(?:at|on|due|in)\b",
    r"\binstead\s+of\b",
    r"\bas\s+(?:high|low|medium|top)\s+priority\b",
    r"\b(?:i'?m|i\s+am)\s+(?:done|finished)\s+with\b",
    r"^(?:(?:please|can you|could you|can we|let's|lets|ok|so)\s+)?change\s+\S.*?\s+to\s+",
    r"\b(?:mark|tick)\b.*\b(?:done|complet\w*|finished|off)\b",
    r"\balready\s+(?:did|done|finished|paid|sent|mailed|bought|called)\b",
    r"\bget\s+rid\s+of\b",
    r"\btake\b.+\boff\s+(?:my|the)\s+(?:calendar|calender|list|to-?do)",
    r"\bcheck\s+off\b",
    r"\bdouble[\s-]+check\b",
]
#: Verbs the engine's table routes to an edit or delete only beside a domain
#: word, which the phone treats as an edit whenever they LEAD the command:
#: a false guard costs a wait for the Mac, a miss books something wrong
#: ("scrap vet appointment", "delete this for me", "update feed the cat").
LEAD_EDITS = {"delete", "scrap", "erase", "update", "edit"}
#: Verbs whose table entry is a completion only when a done-word says so:
#: "mark the 30th as the tax deadline" is a create. The frame above covers them.
DONE_FRAMED = {"mark", "tick"}
#: With a leave-for-the-Mac verb that needs a domain, these words supply it.
DOMAIN_WORDS = ["calendar", "schedule", "agenda", "list", "to-do", "todo", "to do",
                "task", "tasks", "reminder", "reminders"]


def guard() -> dict:
    """What the phone must LEAVE FOR THE MAC, decided before any model call
    (DEVQA Q68, step 1). Generated from the engine's own tables, so the phone's
    guard and the Mac's routing cannot disagree: every verb `INTENT_MAP` routes
    to an update, delete, complete or query, and the engine's own delete and
    complete frames. A verb whose table entry needs a domain ("delete" means
    delete only about the calendar or a list — "clear the gutters" is an
    errand) guards only when a domain word is present. 'set' and 'note' are
    left out: "set a meeting at 3" and "note to self…" are creates.

    The 40-row probe that motivated it: Apple's model booked a NEW item for
    8 of 9 rows that asked to move, complete, delete or ask."""
    from assistant.intent.rule_parser import _COMPLETE_FRAME, _DELETE_FRAME, INTENT_MAP
    any_domain, with_domain = set(), set()
    for (verb, domain), action in INTENT_MAP.items():
        if action.startswith("create") or verb in ("set", "note") or verb in DONE_FRAMED:
            continue
        (any_domain if domain is None else with_domain).add(verb)
    with_domain -= any_domain
    any_domain |= LEAD_EDITS
    with_domain -= LEAD_EDITS
    return {
        "leave_verbs": sorted(any_domain),
        "leave_verbs_with_domain": sorted(with_domain),
        "domain_words": DOMAIN_WORDS,
        "frames": [_DELETE_FRAME.pattern, _COMPLETE_FRAME.pattern] + EDIT_FRAMES,
        "question_starts": QUESTION_STARTS,
        "lead_ins": LEAD_INS,
    }


def _version(body: dict) -> str:
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def _names(limit: int = 150) -> list[str]:
    """This user's own words — names, places, courses — so the phone's model
    spells them the way the Mac's vocabulary does. Data, not instructions: it
    is left out of `version`, so learning a word does not look like a fix."""
    try:
        from assistant.stt.vocab import get_vocab
        entries = sorted(get_vocab().entries(), key=lambda e: -int(e.hits or 0))
        return [e.word for e in entries if e.word][:limit]
    except Exception:                                   # noqa: BLE001
        return []


def reader_spec() -> dict:
    body = {
        "protocol": PROTOCOL,
        "schema": SCHEMA,
        "kinds": list(KINDS),
        "recurrences": list(RECURRENCES),
        "may_commit": list(MAY_COMMIT),
        "instructions": INSTRUCTIONS,
        "examples": EXAMPLES,
        "guard": guard(),
    }
    return {**body, "version": _version(body), "names": _names()}
