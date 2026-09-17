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
