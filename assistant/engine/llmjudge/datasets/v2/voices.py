"""The seven voices — one plain register plus the six persona HABITS.

**What is borrowed and what is not.** `dataset/personas/PERSONAS.md` is
TEST-ONLY FOREVER: *"no persona row is ever used to fit a model, select a
feature, sweep a threshold, or seed a few-shot prompt — not the ones scored,
not the ones that fail, not the banks they came from."* So nothing here is
copied out of `personas.jsonl`, `banks/` or `structures.json`. What is
borrowed is the one-line HABIT each persona is DEFINED by in that file's own
table — imperative and complete, rushed and subject-dropping, polished and
hedged, long and polite, verbless and unpunctuated, article-dropping with a
24-hour clock — and the frames below are written fresh against those lines.
The persona board therefore stays a clean instrument: it scores phrasings this
set never contains.

A voice fixes three things and nothing else, so the gold cannot move with it:

    the FRAME      which words wrap the subject ("book X" / "could you block off X")
    the CLOCK FORM which spoken shape the same clock value is said in
    the FINISH     punctuation, case, and the article/preposition habits

The subject, the day, the clock VALUE and the cadence come from the grammar
and are identical across all seven renderings of a command.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# the clock forms — the conventions table's shapes, one renderer each
# ---------------------------------------------------------------------------

#: Every spoken form the two readers know, per `decompose_validate/
#: ARCHITECTURE.md`'s conventions table. `compact_ap` / `compact_bare` /
#: `zero_padded` are cycle 35's (2026-09-22) — six of the real-usage board's
#: eight remaining generic-title failures had lost a stated time to one of them.
CLOCK_FORMS = ("colon", "dotted", "dotted_mer", "compact_ap", "compact_bare",
               "zero_padded", "oclock", "bare_hour", "words", "twentyfour",
               "plain_mer")


def render_clock(clock: dict, form: str) -> "str | None":
    """The clock phrase INCLUDING its preposition, or None if this value
    cannot honestly be said that way.

    A form is refused rather than approximated: "at 8" is not 08:00 to this
    engine (the bare hour 1–8 is PM by convention), so `bare_hour` on an 08:00
    would put a clock in the words that the gold does not claim — which is a
    defect in the DATA, not a hard case.
    """
    h12, mer = clock["h12"], clock["mer"]
    short = h12[:-3] if h12.endswith(":00") else h12
    hour = clock.get("hour")
    if form == "colon":
        return f"at {h12} {mer}"
    if form == "dotted":
        return f"at {h12.replace(':', '.')} {mer}"
    if form == "dotted_mer":
        return f"at {h12} {mer[0]}.{mer[1]}."
    if form == "compact_ap":
        return f"at {clock['compact']}{mer}"
    if form == "compact_bare":
        # a bare hhmm is a clock only after a clock preposition (conventions
        # table), so the preposition is part of the form rather than optional
        return f"for {clock['compact']}"
    if form == "zero_padded":
        return f"at {clock['pad']} {mer}" if clock.get("pad") else None
    if form == "oclock":
        return f"at {clock['oclock']}" if clock.get("oclock") else None
    if form == "bare_hour":
        if hour and ((mer == "pm" and 1 <= hour <= 8)
                     or (mer == "am" and 9 <= hour <= 12)):
            return f"at {hour}"
        return None
    if form == "words":
        return f"at {clock['words']}"
    if form == "twentyfour":
        return f"at {clock['value']}"
    if form == "plain_mer":
        return f"at {short}{mer}"
    return None


@dataclass
class Voice:
    """One speaker's habits. `frames` is keyed by the ask shape's `frame_key`."""
    id: str
    habit: str
    frames: dict
    #: A clock-form HABIT, tried before the family's own choice. Only three
    #: personas have one — PERSONAS.md names the ESL speaker's 24-hour clock
    #: and the retiree's "quarter to four" as speech habits rather than
    #: subject matter, and the student's compact "910am" is the same kind of
    #: thing. The other four leave the form to the grammar, which is what lets
    #: all eleven spoken forms appear across the set instead of seven.
    clock_forms: tuple = ()
    #: "on monday" -> "in monday" (the ESL calque), applied to date phrases.
    date_prep: "str | None" = None
    punctuate: bool = True
    lowercase: bool = False
    drop_articles: bool = False


def _finish(voice: "Voice", text: str) -> str:
    out = " ".join(text.split())
    if voice.lowercase:
        out = out.lower()
    if not voice.punctuate:
        out = out.replace(".", "").replace(",", "")
        out = " ".join(out.split())
    return out


#: The frame keys, one per ask shape's action. A frame is a template over
#: `{s}` — the subject — and NEVER over the time: the time phrase is appended
#: (or prefixed) separately, because `Item.text` is the action words and
#: `Item.time` is the time reference as spoken (`engine/state.py`).
VOICES = [
    Voice(
        id="plain",
        habit="the neutral register — no persona, the control for the six",
        frames={
            "create_event": ["book {s}", "schedule {s}", "create an event for {s}"],
            "create_todo": ["remind me to {s}", "add {s} to my to-do list",
                            "i need to {s}"],
            "query_schedule": ["what do i have", "what is on my calendar"],
            "query_todos": ["what is on my to-do list", "what tasks do i have"],
            "update_event": ["move {s}", "change {s}", "reschedule {s}"],
            "delete_event": ["cancel {s}", "delete {s} from my calendar"],
            "delete_todo": ["remove {s} from my to-do list",
                            "take {s} off my to-do list"],
            "complete_todo": ["mark {s} as done", "tick off {s}"],
            "update_anaphor": ["move {s}", "change {s}"],
            "delete_anaphor": ["cancel {s}", "delete {s}"],
        },
    ),
    Voice(
        id="observant_student",
        habit="imperative, complete sentences (PERSONAS.md's control persona)",
        frames={
            "create_event": ["set an event for {s}", "put {s} in the calendar",
                             "make an event for {s}"],
            "create_todo": ["remind me to {s}", "put {s} on the list",
                            "add {s} to my tasks"],
            "query_schedule": ["what do i have", "tell me what i have"],
            "query_todos": ["what is on my list", "tell me what is on my list"],
            "update_event": ["move {s}", "change {s}"],
            "delete_event": ["cancel {s}", "remove {s} from the calendar"],
            "delete_todo": ["remove {s} from the list", "take {s} off the list"],
            "complete_todo": ["mark {s} as done", "{s} is done"],
            "update_anaphor": ["move {s}", "change {s}"],
            "delete_anaphor": ["cancel {s}", "remove {s}"],
        },
    ),
    Voice(
        id="household_parent",
        habit="rushed and run-on, subject-dropping, afterthoughts",
        frames={
            "create_event": ["stick {s} in the calendar", "put {s} in",
                             "book {s}"],
            "create_todo": ["need to {s}", "remind me to {s}",
                            "add {s} to the list"],
            "query_schedule": ["what have i got", "what is on"],
            "query_todos": ["what is on the list", "what have i got to do"],
            "update_event": ["move {s}", "shift {s}"],
            "delete_event": ["cancel {s}", "drop {s}"],
            "delete_todo": ["take {s} off the list", "remove {s} from the list"],
            "complete_todo": ["mark {s} as done", "{s} is done"],
            "update_anaphor": ["move {s}", "shift {s}"],
            "delete_anaphor": ["cancel {s}", "drop {s}"],
        },
    ),
    Voice(
        id="freelance_consultant",
        habit="polished, hedged politeness, business idiom (block off, pencil in)",
        frames={
            "create_event": ["could you block off {s}", "please pencil in {s}",
                             "i would like to schedule {s}"],
            "create_todo": ["please add {s} to my task list",
                            "could you remind me to {s}"],
            "query_schedule": ["could you tell me what i have",
                               "what does my calendar look like"],
            "query_todos": ["could you tell me what is on my task list",
                            "what is outstanding on my task list"],
            "update_event": ["could you move {s}", "please reschedule {s}"],
            "delete_event": ["please cancel {s}", "could you drop {s}"],
            "delete_todo": ["please remove {s} from my task list",
                            "could you take {s} off my task list"],
            "complete_todo": ["please mark {s} as done", "could you tick off {s}"],
            "update_anaphor": ["could you move {s}", "please reschedule {s}"],
            "delete_anaphor": ["please cancel {s}", "could you drop {s}"],
        },
    ),
    Voice(
        id="retiree",
        habit="long polite sentences, an explanatory aside, spelled-out clocks",
        frames={
            "create_event": ["i would like you to put {s} in the diary",
                             "would you kindly schedule {s}",
                             "please make an appointment for {s}"],
            "create_todo": ["please remind me to {s}",
                            "would you make a note to {s}"],
            "query_schedule": ["would you tell me what i have",
                               "i should like to know what i have"],
            "query_todos": ["would you tell me what is on my list",
                            "i should like to know what is on my list"],
            "update_event": ["would you please move {s}", "kindly change {s}"],
            "delete_event": ["would you please cancel {s}",
                             "kindly remove {s} from the diary"],
            "delete_todo": ["would you please remove {s} from my list",
                            "kindly take {s} off my list"],
            "complete_todo": ["would you mark {s} as done",
                              "kindly tick off {s}"],
            "update_anaphor": ["would you please move {s}", "kindly change {s}"],
            "delete_anaphor": ["would you please cancel {s}", "kindly remove {s}"],
        },
        clock_forms=("words", "oclock"),
    ),
    Voice(
        id="uni_student",
        habit="verbless fragments, no punctuation, no politeness, slang verbs",
        frames={
            "create_event": ["{s}", "chuck {s} in", "add {s}"],
            "create_todo": ["need to {s}", "add {s} to the list",
                            "remind me to {s}"],
            "query_schedule": ["what do i have", "whats on"],
            "query_todos": ["whats on the list", "what do i have to do"],
            "update_event": ["move {s}", "push {s}"],
            "delete_event": ["cancel {s}", "bin {s}"],
            "delete_todo": ["take {s} off the list", "remove {s} from the list"],
            "complete_todo": ["{s} done", "mark {s} as done"],
            "update_anaphor": ["move {s}", "push {s}"],
            "delete_anaphor": ["cancel {s}", "bin {s}"],
        },
        clock_forms=("compact_ap", "compact_bare"),
        punctuate=False,
        lowercase=True,
    ),
    Voice(
        id="esl_speaker",
        habit="article drops, calqued prepositions (in monday), i must to, 24-hour clock",
        frames={
            "create_event": ["please to make event for {s}", "i must to book {s}",
                             "make {s} in calendar"],
            "create_todo": ["please remind me to {s}", "i must to do {s}",
                            "add {s} in my list"],
            "query_schedule": ["what i have", "please to tell what i have"],
            "query_todos": ["what is in my list", "please to tell what is in my list"],
            "update_event": ["please to move {s}", "i must to change {s}"],
            "delete_event": ["please to cancel {s}", "i must to remove {s}"],
            "delete_todo": ["please to remove {s} from my list",
                            "i must to take {s} from my list"],
            "complete_todo": ["please to mark {s} as done", "{s} is done already"],
            "update_anaphor": ["please to move {s}", "i must to change {s}"],
            "delete_anaphor": ["please to cancel {s}", "i must to remove {s}"],
        },
        clock_forms=("twentyfour", "zero_padded"),
        date_prep="in",
        drop_articles=True,
    ),
]

VOICE_IDS = tuple(v.id for v in VOICES)
BY_ID = {v.id: v for v in VOICES}


def date_phrase_for(voice: Voice, phrase: str) -> str:
    """The day as this voice says it. Only the ESL calque changes it —
    "on monday" -> "in monday" — which is a preposition habit, not a different
    day, so the gold's `date_phrase` is unaffected."""
    if voice.date_prep and phrase.startswith("on "):
        return voice.date_prep + phrase[2:]
    return phrase


def subject_for(voice: Voice, subject: str) -> str:
    """The subject as this voice says it. The ESL speaker drops the article;
    the CONTENT WORDS are untouched, which is what keeps the gold title
    reachable from the words under `intent/correction.py`'s rule."""
    if voice.drop_articles and subject.startswith(("the ", "a ", "an ")):
        return subject.split(" ", 1)[1]
    return subject


def finish(voice: Voice, text: str) -> str:
    return _finish(voice, text)


# ---------------------------------------------------------------------------
# the TIER voices (2026-10-01) — rendered only in the 10k / 40k tiers
# ---------------------------------------------------------------------------
#
# Six more speaking habits, written fresh for the size tiers. They are NOT the
# persona sets' new speakers either — `dataset/personas/` is test-only forever,
# so nothing here was taken from its banks, and its tier personas were written
# against different habits (a nurse's shift shorthand, a tradesperson's jobs,
# …) so the two never share a frame. The base `VOICES` list is untouched:
# `build_commands()` still renders exactly the seven it always did.
TIER_VOICES = [
    Voice(
        id="voice_memo",
        habit="dictating a note to self — 'note to self', 'memo', a label first",
        frames={
            "create_event": ["note to self, {s}", "memo, {s} in the calendar",
                             "calendar note, {s}"],
            "create_todo": ["note to self, {s}", "memo to {s}",
                            "to do note, {s}"],
            "query_schedule": ["memo, what is in the calendar",
                               "note, read me the calendar"],
            "query_todos": ["memo, read me the to do notes",
                            "note, what is still open"],
            "update_event": ["memo, shift {s}", "note to self, move {s}"],
            "delete_event": ["memo, scrap {s}", "note to self, cancel {s}"],
            "delete_todo": ["memo, strike {s} from the notes",
                            "note to self, delete {s} from the list"],
            "complete_todo": ["memo, {s} finished", "note to self, {s} sorted"],
            "update_anaphor": ["memo, shift {s}", "note to self, move {s}"],
            "delete_anaphor": ["memo, scrap {s}", "note to self, cancel {s}"],
        },
        clock_forms=("colon",),
    ),
    Voice(
        id="texting_shorthand",
        habit="typed-message register spoken aloud — pls, u, thx, no capitals",
        frames={
            "create_event": ["pls add {s}", "can u book {s}", "add {s} thx"],
            "create_todo": ["pls remind me to {s}", "can u remind me to {s}",
                            "remind me to {s} thx"],
            "query_schedule": ["what have i got pls", "can u check what i have"],
            "query_todos": ["whats on my list pls", "can u check my list"],
            "update_event": ["pls move {s}", "can u move {s}"],
            "delete_event": ["pls cancel {s}", "can u cancel {s}"],
            "delete_todo": ["pls take {s} off my list",
                            "can u remove {s} from my list"],
            "complete_todo": ["{s} done thx", "pls mark {s} done"],
            "update_anaphor": ["pls move {s}", "can u move {s}"],
            "delete_anaphor": ["pls cancel {s}", "can u cancel {s}"],
        },
        clock_forms=("plain_mer",),
        punctuate=False,
        lowercase=True,
    ),
    Voice(
        id="hands_free_driver",
        habit="talking while driving — 'ok', 'hey', 'for me', short and loud",
        frames={
            "create_event": ["ok put {s} in for me", "hey add {s}",
                             "ok calendar, {s}"],
            "create_todo": ["ok remind me to {s}", "hey i need to {s}",
                            "ok add {s} to the list for me"],
            "query_schedule": ["ok what have i got", "hey what is on"],
            "query_todos": ["ok what is on my list", "hey read me my list"],
            "update_event": ["ok move {s} for me", "hey shift {s}"],
            "delete_event": ["ok cancel {s} for me", "hey kill {s}"],
            "delete_todo": ["ok take {s} off the list for me",
                            "hey drop {s} from the list"],
            "complete_todo": ["ok {s} is done", "hey tick off {s} for me"],
            "update_anaphor": ["ok move {s} for me", "hey shift {s}"],
            "delete_anaphor": ["ok cancel {s} for me", "hey kill {s}"],
        },
        clock_forms=("bare_hour", "oclock"),
    ),
    Voice(
        id="academic",
        habit="formal and conditional — 'i'd appreciate it', 'might you', 'arrange'",
        frames={
            "create_event": ["might you arrange {s}",
                             "i'd appreciate it if you scheduled {s}",
                             "please arrange {s}"],
            "create_todo": ["i'd appreciate a reminder to {s}",
                            "might you note that i must {s}"],
            "query_schedule": ["might you summarise my commitments",
                               "what commitments do i have"],
            "query_todos": ["might you summarise my outstanding tasks",
                            "which tasks remain outstanding"],
            "update_event": ["might you postpone {s}", "please rearrange {s}"],
            "delete_event": ["might you withdraw {s}", "please call off {s}"],
            "delete_todo": ["please strike {s} from my task list",
                            "might you delete {s} from my tasks"],
            "complete_todo": ["please record {s} as complete",
                              "might you mark {s} complete"],
            "update_anaphor": ["might you postpone {s}", "please rearrange {s}"],
            "delete_anaphor": ["might you withdraw {s}", "please call off {s}"],
        },
        clock_forms=("dotted_mer", "colon"),
    ),
    Voice(
        id="sports_coach",
        habit="clipped team-talk imperatives — 'lock in', 'get it on the board'",
        frames={
            "create_event": ["lock in {s}", "get {s} on the board",
                             "pencil {s} on the board"],
            "create_todo": ["get it done, {s}", "jobs list, {s}",
                            "remind me to {s}"],
            "query_schedule": ["whats on the board", "run me through the board"],
            "query_todos": ["whats on the jobs list", "run me through the jobs"],
            "update_event": ["shift {s}", "bump {s}"],
            "delete_event": ["scratch {s}", "pull {s} off the board"],
            "delete_todo": ["scratch {s} off the jobs list",
                            "pull {s} off the jobs"],
            "complete_todo": ["{s} is sorted", "tick {s} off the jobs"],
            "update_anaphor": ["shift {s}", "bump {s}"],
            "delete_anaphor": ["scratch {s}", "pull {s}"],
        },
        clock_forms=("compact_ap", "twentyfour"),
    ),
    Voice(
        id="hospitality_manager",
        habit="front-of-house idiom — 'pop it in the book', 'we've got', 'cheers'",
        frames={
            "create_event": ["pop {s} in the book", "we've got {s}, put it in",
                             "can we book in {s}"],
            "create_todo": ["can we remember to {s}", "pop {s} on the list",
                            "we need to {s}"],
            "query_schedule": ["what's in the book", "what have we got on"],
            "query_todos": ["what's on our list", "what have we still got to do"],
            "update_event": ["can we move {s}", "shuffle {s}"],
            "delete_event": ["take {s} out of the book", "we're not doing {s}"],
            "delete_todo": ["take {s} off our list", "scrub {s} from the list"],
            "complete_todo": ["{s} is done, cheers", "tick off {s}, cheers"],
            "update_anaphor": ["can we move {s}", "shuffle {s}"],
            "delete_anaphor": ["take {s} out of the book", "scrub {s}"],
        },
        clock_forms=("oclock", "plain_mer"),
    ),
]

TIER_VOICE_IDS = tuple(v.id for v in TIER_VOICES)
ALL_VOICES = VOICES + TIER_VOICES
BY_ID.update({v.id: v for v in TIER_VOICES})
