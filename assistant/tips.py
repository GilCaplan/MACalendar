"""User-facing tips: the most effective ways to talk to the assistant.

Shown from Settings -> Assistant -> "How to Talk to Me..." on the Mac
(`calendar_ui/tips_dialog.py`) and the phone (`TipsView.swift`, via
`GET /tips`). Kept SHORT on purpose (Gil, 2026-09-16: "don't want to overload
them with content") — four one-line "how it works" STEPS and at most five
TIPS, about one phone screen, not a manual.

TIED to the engine version, not just written once and left. Each step and
tip below is a factual claim about how the pipeline actually behaves TODAY,
verified live against `assistant.engine.run_transcript` when written, not
folklore — one candidate claim ("pick up the kids at 3" reads as a scheduled event)
turned out to be FALSE when checked and was replaced before it ever
shipped. `tests/unit/test_tips_current.py` fails the build the moment
`assistant.trace.BRAIN_VERSION` moves past `TIPS_BRAIN_VERSION` below — the
same "downstream of the pipeline, and the build catches you if you miss it"
contract `test_panel_agreement.py` already holds the thinking panel to.
Bump `TIPS_BRAIN_VERSION` ONLY in the same change that re-verifies every
step and tip below against the new engine (the same way, live, not by
reasoning about the diff) and updates whatever changed. Their spoken examples
are also re-run on every build by `tests/unit/test_tips_examples.py`, so a
change that breaks one goes red before the version bump.
"""
from __future__ import annotations

#: The BRAIN_VERSION these tips were last verified against — bump together
#: with a re-verification of STEPS and TIPS, never on its own.
TIPS_BRAIN_VERSION = "engine-v3"

#: HOW IT WORKS — shown ABOVE the tips on both surfaces (Gil, 2026-09-24:
#: "perhaps include a brief explanatory of how the system works high level
#: like with segmentation on how to seperate events/tasks and then
#: reoccurence split etc... so user can understand how to speak more
#: clearly"). Four steps, one sentence each, in the order the engine does
#: them — segmentation, event-vs-task, recurrence, the check — in plain words
#: with no stage names. (text, spoken example).
#:
#: HOW EVERY EXAMPLE BELOW WAS CHECKED (2026-09-24, engine-v3): run through
#: `assistant.engine.run_transcript` against scratch stores three ways —
#: with every model door BLOCKED (the rescue's `IntentParser._call_ollama`
#: too: `MACALENDAR_LLM_DISABLED` alone does not stop it), with the live
#: model seeded, and unseeded — and all three agreed. Every quoted sentence
#: lands on the FAST path (FastRule commits it, no model), which is why most
#: of them open with a verb: "Dentist on the 15th at 4" DEFERS to the model
#: (the same answer, several seconds later, and nothing without it), while
#: "Book the dentist on the 15th at 4" commits at once.
#: `tests/unit/test_tips_examples.py` re-runs each one on every build with
#: the model blocked, so CI checks exactly what is claimed here.
#:   1. "Book the dentist Tuesday at 4 and call Mom" -> event 'dentist' Tue
#:      16:00 + to-do 'call mom': two items from one sentence
#:   2. "Walk the dog at 9" -> event 09:00 today; "Walk the dog" -> to-do
#:      (fastseg.py's TAG lexicon veto: the stated time is the difference).
#:      Deliberately NOT "one without a time becomes a to-do": "Book the
#:      dentist tomorrow" is an EVENT at 9 AM (tip 1), so the step says an
#:      ERRAND with no time becomes a to-do
#:   3. "Book yoga every Tuesday at 6pm" -> ONE weekly series (53 instances,
#:      recurrence='weekly', from the coming Tuesday)
#:   4. "Team meeting tomorrow at 7" -> the phone (supports_confirm) is ASKED
#:      "Want me to add “team meeting” on ... 7 PM–8 PM?" (DEVQA Q28); the
#:      Mac creates it and the reply says "I read "7" as 7 PM — say "change
#:      it to 7 AM" if you meant the morning." Hence "asks or tells you"
STEPS: list[tuple[str, str]] = [
    ("It splits what you say into separate requests.",
     "“Book the dentist Tuesday at 4 and call Mom” → an appointment and "
     "a to-do."),
    ("A time puts it on the calendar as an event; an errand with no time "
     "becomes a to-do.",
     "“Walk the dog at 9” → event. “Walk the dog” → to-do."),
    ("Words like “every Tuesday” make it a repeating series.",
     "“Book yoga every Tuesday at 6pm” → one weekly series."),
    ("It checks what it made, and asks or tells you when it had to guess.",
     "“Team meeting tomorrow at 7” → it checks you meant 7\u00a0PM."),
]

#: (headline, body). What each one is actually claiming, and where that
#: claim was checked (2026-09-24, all three ways as above):
#:   1. a day AND a time is what makes an event land exactly (Gil,
#:      2026-09-24: "for events its best to say a day and time")
#:      -- "Book the dentist tomorrow at 4" -> tomorrow 16:00; "Book the
#:      dentist tomorrow" -> tomorrow 09:00, SILENTLY on the fast path (the
#:      deep path's "I went ahead, but start_time = 09:00 — nothing in the
#:      words said it" note appears only for "Dentist tomorrow", which needs
#:      the model), so the tip does not promise the reply says it guessed.
#:      NOT claimed: that a clock with no day means today-or-tomorrow (DEVQA
#:      Q42 rule 2) — "dentist at 8am" said at 08:49 was booked for 08:00
#:      TODAY, already past; the rule did not fire on that path
#:   2. the words after the kind become the title (the `generic-title`
#:      class, 42% of Gil's real-usage failures; DEVQA Q41)
#:      -- "Meeting with Sam tomorrow at 4" -> 'meeting with sam';
#:      "Set a meeting tomorrow at 4" -> 'meeting' (+ the bare_title hint)
#:   3. a shared verb over a list is ONE task (DEVQA Q14 reversed
#:      2026-09-16); a verb each splits it
#:      -- "Buy milk, eggs, and bread" -> one to-do with the whole list;
#:      "Buy milk and call Mom" -> two to-dos
#:   4. a named or counted day resolves; a range does not name one
#:      -- "Book the dentist next Tuesday at 4" -> a Tuesday (said on a
#:      Thursday, the coming one; on a Monday, the one after); "... on the
#:      15th at 4" -> the 15th; "... in two weeks at 4" -> today+14. On tasks
#:      too: "renew the passport in two weeks" and "... the 15th" carry the
#:      right due date (both fell back to today on 2026-09-17, which is why
#:      the old tip warned about them; that warning is gone). "Next week"
#:      (DEVQA Q22): "Book yoga class next week" and "yoga next week at 6pm"
#:      are ASKED on the phone; "yoga next week" is NOT — it commits Monday
#:      09:00 with a note, even on the phone. Hence "ask or guess"
#:   5. one weekday per series
#:      -- "Book yoga every Tuesday at 6pm and book yoga every Thursday at
#:      6pm" -> two weekly series. The single-phrase form is WRONG every way
#:      it was tried: "Book yoga every Tuesday and Thursday at 6pm" -> one
#:      THURSDAY-only series ("“two days a week” became weekly"), Tuesdays
#:      lost; "Yoga every Tuesday and Thursday at 6pm" (deep) -> two one-offs,
#:      the first on a MONDAY with the model blocked, or a weekly series that
#:      ends a week later with it; "on tuesdays and thursdays" -> one-offs.
#: Dropped 2026-09-24: "A word it isn't sure of, it'll check" — it pointed
#: at a Mac-only setting ("Check doubted words with me before acting"), so
#: the phone's copy sent the reader to a toggle its Settings does not have,
#: and step 4 now carries "it asks when unsure". "A time is what makes it an
#: appointment" became step 2.
TIPS: list[tuple[str, str]] = [
    ("For an event, say the day and the time",
     "“Book the dentist tomorrow at 4” lands exactly. Leave the time out "
     "and it has to pick one for you (9\u00a0AM)."),
    ("Say what it’s about",
     "“Meeting with Sam tomorrow at 4” is saved as ‘meeting with sam’. "
     "“Set a meeting tomorrow at 4” is saved as just ‘meeting’."),
    ("One verb, one to-do",
     "“Buy milk, eggs, and bread” is one task with the whole list. Give "
     "each its own verb — “buy milk and call Mom” — to get two."),
    ("Name a day, not a week",
     "“Next Tuesday”, “on the 15th” and “in two weeks” each land on one "
     "day. “Next week” names no single day, so it has to ask or guess."),
    ("One weekday per repeating series",
     "“Book yoga every Tuesday at 6pm and book yoga every Thursday at 6pm” "
     "makes two weekly series. “Every Tuesday and Thursday” in one go "
     "isn’t reliable yet."),
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
    """What `GET /tips` serves: the how-it-works steps, the tips, the hints,
    and the engine version they were verified against — one copy for every
    client. `steps` arrived 2026-09-24; the phone decodes it as OPTIONAL so a
    host from before then still loads the tips."""
    return {
        "brain": TIPS_BRAIN_VERSION,
        "steps": [{"text": t, "example": e} for t, e in STEPS],
        "tips": [{"headline": h, "body": b} for h, b in TIPS],
        "hints": {code: {"headline": h, "body": b}
                  for code, (h, b) in HINTS.items()},
    }
