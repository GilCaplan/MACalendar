"""User-facing tips: the most effective ways to talk to the assistant.

Shown from Settings -> Assistant -> "Tips..." (`calendar_ui/tips_dialog.py`).
Kept SHORT on purpose (Gil, 2026-09-16: "don't want to overload them with
content") — five items, not a manual.

TIED to the engine version, not just written once and left. Each tip below
is a factual claim about how the pipeline actually behaves TODAY, verified
live against `assistant.engine.run_transcript` when written, not folklore —
one candidate claim ("pick up the kids at 3" reads as a scheduled event)
turned out to be FALSE when checked and was replaced before it ever
shipped. `tests/unit/test_tips_current.py` fails the build the moment
`assistant.trace.BRAIN_VERSION` moves past `TIPS_BRAIN_VERSION` below — the
same "downstream of the pipeline, and the build catches you if you miss it"
contract `test_panel_agreement.py` already holds the thinking panel to.
Bump `TIPS_BRAIN_VERSION` ONLY in the same change that re-verifies every
tip below against the new engine (the same way, live, not by reasoning
about the diff) and updates whatever changed.
"""
from __future__ import annotations

#: The BRAIN_VERSION these tips were last verified against — bump together
#: with a re-verification of TIPS, never on its own.
TIPS_BRAIN_VERSION = "engine-v3"

#: (headline, body). What each one is actually claiming, and where that
#: claim was checked:
#:   1. one-breath multi-item commands split on their own
#:      -- coordination.py's clause split; verified live,
#:      "book the dentist tomorrow and remind me to pay rent" -> 2 items
#:   2. a stated time is what turns a task into an event
#:      -- fastseg.py's TAG lexicon veto; verified live with the exact
#:      example the veto's own docstring uses ("walk the dog" -> task,
#:      "walk the dog at 9" -> event) after a DIFFERENT example ("pick up
#:      the kids at 3") turned out not to trigger the same path and was
#:      dropped
#:   3. a coordinated bare object list stays ONE task
#:      -- DEVQA Q14 (reversed 2026-09-16): a shared verb over "milk, eggs,
#:      and bread" is one segmentation item, not three; verified live
#:   4. relative dates resolve
#:      -- verified live for "next <weekday>" and "on the <ordinal>"
#:      specifically; "in two weeks" and a bare "the <ordinal>" (no "on")
#:      were tried too and silently fell back to today (TASKS.md,
#:      2026-09-17, filed not fixed) — deliberately NOT claimed here
#:   5. the doubted-word check exists and is a real, user-facing setting
#:      -- Settings -> Assistant -> "Check doubted words with me before
#:      acting" (`calendar_ui/settings_dialog.py`), matching trace.py's own
#:      "fix words" stage description
TIPS: list[tuple[str, str]] = [
    ("Say everything in one breath",
     "“Book the dentist tomorrow and remind me to pay rent” "
     "becomes two separate items on its own — no need to give "
     "commands one at a time."),
    ("A time is what makes it an appointment",
     "“Walk the dog” is a to-do for today. “Walk the dog at "
     "9” is a scheduled event. Same words, the time is the only "
     "difference."),
    ("Lists stay together",
     "“Buy milk, eggs, and bread” is saved as one task with "
     "everything on it, not three separate ones."),
    ("Say the day by name",
     "“Next tuesday” and “on the 15th” both resolve "
     "correctly. When in doubt, name the day rather than counting "
     "forward — some relative phrasings (“in two weeks”) "
     "aren’t reliable yet."),
    ("A word it isn’t sure of, it’ll check",
     "Turn on “Check doubted words with me before acting” in "
     "Settings → Assistant to see a quick confirmation whenever the "
     "assistant doubts a name it heard, before anything is created."),
]


#: CONTEXTUAL hints — one line the client shows right after a reply, keyed on
#: what the engine just did, once per code, dismissable (Gil, 2026-09-22: a
#: tooltip that "pops up easily and intuitively without getting in the way").
#: These are NOT the five tips above and do not count against their cap: a tip
#: is read in Settings, a hint arrives at the moment it applies. Each code is a
#: real-usage failure class from `DOCUMENTATION/experiments/real_usage/
#: RESULTS.md` — `generic-title` was 42% of Gil's own failures, and the engine
#: COMMITS those (Q41: "a meeting according to the other details with a bare
#: title is fine"), so the hint is the only thing that can improve the title.
#: The engine picks the code in `assistant.engine._hint`; the words live here
#: so `test_tips_current.py` holds them to the same length and version rules.
HINTS: dict[str, tuple[str, str]] = {
    "bare_title": (
        "Say what it’s about",
        "“Meeting with Sam about the budget” becomes the title. "
        "“Set a meeting” alone is saved as ‘meeting’ — "
        "right day and time, nothing more."),
    "title_refused": (
        "Lead with the thing",
        "Put what it is first — “dentist tomorrow at 4”, "
        "“buy milk”. This one wasn’t saved because there was "
        "nothing to call it."),
}

#: A committed title that is only the KIND of thing, not the thing — the
#: `generic-title` class as it looks after the parser: the program word with
#: the frame and the time stripped off. Kept to words that name nothing on
#: their own; "lunch" or "gym" are real titles and stay out.
_BARE_TITLES = frozenset(
    "meeting meetings appointment appointments appt event events call "
    "session reminder task todo to-do note item thing something stuff "
    "plan plans errand".split())
_BARE_LEAD = frozenset("a an the my our your this that".split())


def is_bare_title(title: str) -> bool:
    """True when `title` names only a kind of thing ('meeting', 'an event')."""
    words = (title or "").strip().lower().replace("’", "'").split()
    while words and words[0] in _BARE_LEAD:
        words = words[1:]
    return len(words) == 1 and words[0].strip(".,!") in _BARE_TITLES


def hint(code: str) -> "dict | None":
    """The reply-shaped hint for `code`: {code, headline, body}, or None."""
    got = HINTS.get(code)
    if not got:
        return None
    headline, body = got
    return {"code": code, "headline": headline, "body": body}


def payload() -> dict:
    """What `GET /tips` serves: the tips, the hints, and the engine version
    they were verified against — one copy for every client."""
    return {
        "brain": TIPS_BRAIN_VERSION,
        "tips": [{"headline": h, "body": b} for h, b in TIPS],
        "hints": {code: {"headline": h, "body": b}
                  for code, (h, b) in HINTS.items()},
    }
