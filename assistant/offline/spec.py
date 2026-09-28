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
SCHEMA = 1

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

date: YYYY-MM-DD, worked out from today's date below. Empty for a todo with \
no day.
start and end: 24-hour HH:MM. Empty when not said. A bare "7" or "8" with no \
am or pm means the evening (19:00, 20:00). Only give an end when one was said.
recurrence: none, daily, weekly, monthly or yearly - only when the speaker \
said it repeats ("every", "each", "daily"). The date is then the first one.

Never invent a date, a time, a place or a person that was not said."""

#: Few-shot examples. Each carries its own "today" so it stays true forever.
EXAMPLES = [
    {"today": "2026-09-28 (Monday)", "said": "dentist tomorrow at 3pm",
     "items": [{"kind": "event", "title": "Dentist", "date": "2026-09-29",
                "start": "15:00", "end": "", "recurrence": "none"}]},
    {"today": "2026-09-28 (Monday)", "said": "remind me to buy milk",
     "items": [{"kind": "todo", "title": "Buy milk", "date": "", "start": "",
                "end": "", "recurrence": "none"}]},
    {"today": "2026-09-28 (Monday)", "said": "call Sarah on Thursday",
     "items": [{"kind": "event", "title": "Call Sarah", "date": "2026-10-01",
                "start": "09:00", "end": "", "recurrence": "none"}]},
    {"today": "2026-09-28 (Monday)", "said": "gym every sunday at 7",
     "items": [{"kind": "event", "title": "Gym", "date": "2026-10-04",
                "start": "19:00", "end": "", "recurrence": "weekly"}]},
    {"today": "2026-09-28 (Monday)", "said": "move my dentist to friday",
     "items": [{"kind": "other", "title": "move my dentist to friday", "date": "",
                "start": "", "end": "", "recurrence": "none"}]},
    {"today": "2026-09-28 (Monday)",
     "said": "meeting with Avi next tuesday from 10 to 11 and email the landlord",
     "items": [{"kind": "event", "title": "Meeting with Avi", "date": "2026-10-06",
                "start": "10:00", "end": "11:00", "recurrence": "none"},
               {"kind": "todo", "title": "Email the landlord", "date": "", "start": "",
                "end": "", "recurrence": "none"}]},
]


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
    }
    return {**body, "version": _version(body), "names": _names()}
