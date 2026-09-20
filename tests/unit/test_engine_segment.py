"""Step 2 — segmentation, the live stage: envelopes, the cut, the tag.

No model is consulted here — FastSeg is deterministic and LLMSeg is off by
default — and the traps live here because the stage is the pipeline's single
point of failure: names joined by "and", idioms, verb lists, batched input.

The LLM-assisted `old_seg` that preceded FastSeg was retired on 2026-09-20;
its own tests (the LLM tier, enumeration headers, loop-back prompts) moved
with it to `retired/segmentation-old-seg/tests/`.
"""

from __future__ import annotations

import pytest

import assistant.engine.llm as engine_llm
import assistant.engine.segmentation as segmentation
from assistant.engine import load_config
from assistant.engine.segmentation.fastseg import kind as _kind
from assistant.engine.state import EngineState


@pytest.fixture
def cfg():
    return load_config()


def _seg(text: str, cfg) -> EngineState:
    st = EngineState(raw_text=text, text=text)
    return segmentation.run(st, cfg)


def _no_llm(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("segmentation must not need the model")
    monkeypatch.setattr(engine_llm, "call_json", _boom)


# --- envelopes: what the transport wraps around a command ------------------

def test_bracket_batch_splits(cfg):
    st = _seg("[gym tomorrow at 7am] [lunch with Tal at noon]", cfg)
    assert [it.spoken() for it in st.items] == ["gym tomorrow at 7am", "lunch with Tal at noon"]
    assert "[" not in st.text            # brackets must not reach a title


def test_coalescing_wrapper_splits(cfg):
    st = _seg('("gym tomorrow at 7am")and("buy milk")', cfg)
    assert len(st.items) == 2
    assert st.items[1].spoken() == "buy milk"


def test_single_item_ids_and_kinds(cfg):
    st = _seg("what do I have this week", cfg)
    assert [it.id for it in st.items] == ["item_1"]
    assert st.items[0].kind == "review"


def test_task_phrasing_is_read_as_task(cfg):
    st = _seg("remind me to call Noa about the trip", cfg)
    assert st.items[0].kind == "task"


# --- the cut: the parse splits what speech actually sounds like -------------

@pytest.mark.parametrize("text,expected", [
    ("book the gym and remind me to buy milk",
     ["book the gym", "remind me to buy milk"]),
    # SPEC's edge rule: a TRAILING day reaches back to an ask with no time of
    # its own, so both asks land on sunday here. Whether a shared day is
    # right for the first ask is the next stage's call (Gil, 2026-09-20),
    # not the cut's; the retired segmenter kept the day on the last ask only
    # because it never separated time from action.
    ("delete the gym session and add yoga on sunday",
     ["delete the gym session on sunday", "add yoga on sunday"]),
    ("call mom then pick up the dry cleaning",
     ["call mom", "pick up the dry cleaning"]),
    ("add gym tomorrow, buy milk, and call the dentist",
     ["add gym tomorrow", "buy milk", "call the dentist"]),
])
def test_two_asks_are_split_without_the_model(text, expected, cfg, monkeypatch):
    _no_llm(monkeypatch)
    st = _seg(text, cfg)
    assert [it.spoken() for it in st.items] == expected


@pytest.mark.parametrize("text", [
    "meeting with Tal and Ravid at Kems tomorrow evening",   # two guests
    "buy chicken and rice for dinner",                        # two things
    "wash and fold the laundry",                              # serial verb
    "meeting with tal and mark tomorrow",                     # a name that is also a verb
])
def test_one_ask_joined_by_and_is_never_split(text, cfg, monkeypatch):
    """The join is inside ONE ask. A wrong merge is recoverable downstream; a
    wrong split creates two garbage items immediately, so this direction is
    the one that must never fail."""
    _no_llm(monkeypatch)
    st = _seg(text, cfg)
    assert len(st.items) == 1


def test_a_date_inside_the_first_ask_is_not_copied_onto_the_second(cfg, monkeypatch):
    """"book gym tomorrow at 7am and remind me to buy milk" is a gym session
    tomorrow and a milk errand with NO date. Only a date the utterance OPENS
    with is shared."""
    _no_llm(monkeypatch)
    st = _seg("book gym tomorrow at 7am and remind me to buy milk", cfg)
    assert [it.spoken() for it in st.items] == [
        "book gym tomorrow at 7am", "remind me to buy milk"]


def test_no_compound_hint_means_no_llm_call(cfg, monkeypatch):
    _no_llm(monkeypatch)
    st = _seg("book the dentist tomorrow morning at nine thirty", cfg)
    assert len(st.items) == 1


# --- the tag: the pinned reminder conventions -------------------------------

def test_a_timed_reminder_is_an_event(cfg):
    st = _seg("remind me about the dentist tomorrow at 9 am", cfg)
    assert st.items[0].kind == "event"


def test_an_untimed_reminder_stays_a_task(cfg):
    st = _seg("remind me to call Ravid", cfg)
    assert st.items[0].kind == "task"


def test_enforce_pinned_kinds_is_narrow():
    f = _kind._enforce_pinned_kinds
    assert f("task", "remind me to go to my doctors at 4pm") == "event"
    assert f("task", "a reminder for the meeting at 3pm") == "event"
    assert f("task", "remind me to buy milk") == "task"                 # no time
    assert f("task", "add milk to the grocery list at 4pm") == "task"   # no remind wording
    assert f("event", "gym at 7") == "event"                            # never flips away from event
    assert f("review", "remind me what is at 4pm") == "review"          # only task labels corrected


def test_the_errand_form_keeps_the_clock_gate():
    f = _kind._enforce_pinned_kinds
    assert f("task", "remind me to buy a present for the wedding on Sunday") == "task"  # to-verb errand
    assert f("task", "set a reminder for my meeting today") == "event"       # occasion + date
    assert f("task", "remind me of my meeting tomorrow") == "event"
    assert f("task", "reminder for a meeting I have on Tuesday") == "event"
    assert f("task", "set a reminder for my meeting") == "task"              # occasion, no date
    assert f("task", "remind me about the thing tomorrow") == "task"         # date, no occasion-noun


def test_cycle4_cues_each_earned_by_a_failing_row():
    """Cycle 4: additions justified by live dev-fast failures, never speculation."""
    f = _kind._enforce_pinned_kinds
    assert f("task", "notify me about any festival occurring next month") == "event"
    assert f("task", "send a calendar invite out to James and Alice for brunch") == "event"
    assert f("task", "notify me when the package arrives tomorrow") == "task"


def test_a_dated_i_need_to_meet_is_an_event_q1():
    """DEVQA Q1 (Gil, 2026-09-06): a dated "I need to <meet/talk/…>" is an
    appointment being made, not an errand."""
    f = _kind._enforce_pinned_kinds
    assert f("task", "on Monday, the 20th, I need to have a conversation with Greg") == "event"
    assert f("task", "I need to meet Sam tomorrow") == "event"
    assert f("task", "I need to talk to the plumber at 3 pm") == "event"
    assert f("task", "I need to buy groceries tomorrow") == "task"
    assert f("task", "I need to talk to Greg") == "task"


# ---------------------------------------------------------------------------
# Politeness at the end of an utterance is not a calendar ask
# ---------------------------------------------------------------------------

def test_a_greeting_with_its_usual_tail_is_not_calendar_work():
    """Bare "thanks" was tagged `other`; "thanks so much" was read as an EVENT.

    The `^…$` anchor meant the politeness people actually say was the thing
    that made a non-ask look like one — and "thanks so much" is Gil's own
    example of an utterance the assistant should decline. Found while wiring
    the review panel's not-an-ask badge, which had nothing to render because
    segmentation never produced the tag.
    """
    import importlib
    _fs = importlib.import_module(
        "assistant.engine.segmentation.fastseg.fastseg")   # the MODULE, not the
                                                           # function the package
                                                           # re-exports by the
                                                           # same name

    for said in ("thanks", "thanks so much", "thank you very much",
                 "thanks a lot", "cheers mate"):
        assert _fs._is_not_calendar(said), f"{said!r} should not be calendar work"
        assert _fs.tag(said, "") == "other"


def test_a_real_ask_that_merely_ends_politely_is_untouched():
    """The closed list is closed on purpose: anything longer than an
    intensifier is a sentence, and a sentence may well be an ask."""
    import importlib
    _fs = importlib.import_module(
        "assistant.engine.segmentation.fastseg.fastseg")   # the MODULE, not the
                                                           # function the package
                                                           # re-exports by the
                                                           # same name

    for said in ("book the gym tomorrow thanks",
                 "thanks for booking the gym, now cancel it",
                 "no thanks to the meeting, delete it"):
        assert not _fs._is_not_calendar(said), f"{said!r} is a real ask"


def test_a_period_separated_clock_is_read_whole():
    """Real live usage, 2026-09-15: "Movie at Lincoln Square tomorrow, AMC,
    11.15 AM tomorrow" put "11" in the action text and "15 AM" in the time —
    the bare "N (am|pm)" pattern can only match starting at a digit directly
    followed by am/pm, so it skipped "11" (followed by "." not "am") and
    matched "15 AM" instead, reading the clock as 15:00 rather than 11:15.
    "11.15am" is the international way of writing an hour/minute separator;
    `find_time_refs` must capture it as ONE span, the same way it already
    does for the colon form, or the fragment reading wins by being findable
    at all."""
    import importlib
    _fs = importlib.import_module(
        "assistant.engine.segmentation.fastseg.fastseg")

    for text, want in (
        ("book flight at 11.15am", "at 11.15am"),   # the leading "at" is
        ("Movie at Lincoln Square tomorrow, AMC, 11.15 AM tomorrow", "11.15 AM"),
        ("meet at 9.05pm", "at 9.05pm"),             # absorbed on purpose (_absorb_preposition)
    ):
        refs = _fs.find_time_refs(text)
        clocks = [r for r in refs if r.kind == "clock"]
        assert len(clocks) == 1, f"{text!r}: expected one clock ref, got {refs}"
        assert clocks[0].text.strip().lower() == want.lower()


def test_a_bare_period_clock_with_no_am_pm_is_read_too():
    """Gil's call, 2026-09-15: protect a bare "H.MM" (a spoken 24-hour time
    like "14.30") the same way the colon form already is, without requiring
    am/pm. Knowingly accepted trade: a plain decimal or a price shaped the
    same way is read as a clock too — see the next test."""
    import importlib
    _fs = importlib.import_module(
        "assistant.engine.segmentation.fastseg.fastseg")

    for text, want in (("meeting at 14.30 tomorrow", "at 14.30"),
                       ("call starts 09.05", "09.05")):
        clocks = [r for r in _fs.find_time_refs(text) if r.kind == "clock"]
        assert len(clocks) == 1, f"{text!r}: expected one clock ref, got {clocks}"
        assert clocks[0].text.strip().lower() == want.lower()


def test_a_bare_decimal_number_is_now_read_as_a_clock_by_design():
    """The accepted trade for the fix above: without an am/pm or a colon to
    disambiguate, "$11.15" and "11.15" are the same shape, and there is no
    general way to tell a price from a time. Documented here so the
    behaviour reads as a decision, not a regression nobody noticed."""
    import importlib
    _fs = importlib.import_module(
        "assistant.engine.segmentation.fastseg.fastseg")

    for text in ("that movie was $11.15", "it's 9.99 for the ticket"):
        clocks = [r for r in _fs.find_time_refs(text) if r.kind == "clock"]
        assert clocks, f"{text!r}: expected the decimal to be read as a clock"


# ---------------------------------------------------------------------------
# A DAMAGED COMMAND FRAME still names a task
#
# Whisper mangles a word inside a fixed frame — "remind MITT to", "remind NEED
# to" — or a UI tag precedes it. `_TASK_RE` then does not match, and `_kind_of`
# fell through to its catch-all `event`, so a reminder landed on the calendar.
# `_REMIND_TO_VERB_RE` already matched all of these; it was consulted only
# inside the branch the damaged text never enters.
#
# The MISHEARD WORD itself is not repaired here — that is the personal
# vocabulary's job (`assistant/stt/vocab.py`, which matches over a window the
# size of the entry). This is the reader being fixed, not the words rewritten.
# ---------------------------------------------------------------------------

def test_a_damaged_remind_frame_is_still_a_task():
    from assistant.engine.segmentation.fastseg.kind import _kind_of

    for text in ("remind mitt to sign the permission slip",
                 "remind need to book the car service",
                 "[TASKS VIEW] can you remind me to book a flight"):
        assert _kind_of(text) == "task", f"{text!r} is a reminder, not a meeting"

    # ...and the intact frame is unaffected, in both directions.
    assert _kind_of("remind me to feed the cat") == "task"
    assert _kind_of("book the dentist on friday") == "event"


def test_the_damaged_frame_still_yields_to_a_stated_clock():
    """Q26 outranks it: `fastseg.tag` promotes on a stated clock AFTER
    `_kind_of` has spoken, so a repaired frame with a time is still an event."""
    from assistant.engine.segmentation.fastseg.fastseg import tag

    assert tag("remind mitt to feed the cat", "at 14:00") == "event"
    assert tag("remind mitt to feed the cat", "tomorrow") == "task"


# ---------------------------------------------------------------------------
# THE COMMAND FRAME ITSELF, repaired deterministically
#
# Gil, 2026-09-20, on what ingest is for: "a. to fix deterministically bad
# transcribe wording  b. finetuned list of vocabulary from user to fix."
#
# "remind me to" belongs to (a), not (b). It is not personal — every speaker
# says it, and the routing depends on it — so a mangled frame is misrouted for
# everyone. Teaching it as a per-user alias was the wrong shelf, and worse: a
# bare alias on "rewind" rewrote "rewind the video to the start".
#
# Measured in the realspeech corpus: 174 clean occurrences of the frame and 20
# damaged ones, in two shapes — "remind MITT to" and "REWIND me to".
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("heard,meant", [
    ("rewind me to pick up the parcel",      "remind me to pick up the parcel"),
    ("remind mitt to sign the permission slip",
     "remind me to sign the permission slip"),
    ("hey rewind me to call the plumber",    "hey remind me to call the plumber"),
    ("and remind mitt to buy milk",          "and remind me to buy milk"),
])
def test_a_misheard_command_frame_is_repaired(heard, meant):
    from assistant.engine.ingest.repair import repair_command_frames
    assert repair_command_frames(heard) == meant


@pytest.mark.parametrize("text", [
    # no "me" — not the frame at all
    "rewind the video to the start",
    # the frame's shape, but "to THE" rather than "to <verb>": a real sentence,
    # and the look-ahead is what keeps it. Without it the repair eats this.
    "rewind me to the start",
    "please rewind that podcast",
    # already correct
    "remind me to feed the cat",
])
def test_an_ordinary_sentence_is_left_alone(text):
    from assistant.engine.ingest.repair import repair_command_frames
    assert repair_command_frames(text) == text


# ---------------------------------------------------------------------------
# A comma after a fronted date must not change the cut (2026-09-20)
# ---------------------------------------------------------------------------

def test_a_comma_after_a_fronted_date_does_not_cut_a_serial_verb():
    """Found by the position-invariance board: 'the 30th wash and fold the
    laundry' was one ask and 'the 30th, wash and fold the laundry' was two,
    because spaCy roots the fronted date and hangs `wash` off it, and the
    walk's 'buried inside the first clause' rescue then fired with nothing
    upstream but the date."""
    from assistant.engine.segmentation.fastseg.fastseg import cut
    assert cut("the 30th, wash and fold the laundry") == ["the 30th, wash and fold the laundry"]
    assert cut("the 30th, clean and organize the garage") == ["the 30th, clean and organize the garage"]
    assert cut("the 30th wash and fold the laundry") == ["the 30th wash and fold the laundry"]
    # a real second ask after a fronted date still cuts
    assert len(cut("tomorrow book the gym and remind me to buy milk")) == 2


# --- the kind tagger: lists, questions, wants (dev-100 checkpoint, 2026-09-20)

def test_a_new_list_or_a_list_of_things_is_a_task():
    """Five of the checkpoint's twelve kind misses were a LIST tagged event:
    "make a new list of dog breeds", "begin new list of lottery numbers",
    "i need a list of my clients". And "groceries list" was not "grocery list"
    to the tagger, which undid a correct model rewrite (run 24)."""
    from assistant.engine.segmentation.fastseg.kind import kind_of
    for t in ("Make a new list of dog breeds", "Begin new list of lottery numbers",
              "i need a list of my clients today", "I would like to start a new list",
              "add milk to my groceries list", "add v8 to my groceries"):
        assert kind_of(t) == "task", t
    assert kind_of("list my events for tomorrow") == "review"


def test_a_wake_word_or_a_yes_no_question_still_reads_as_a_review():
    from assistant.engine.segmentation.fastseg.kind import kind_of
    assert kind_of("PDA do i have any appointments set for tomorrow?") == "review"
    assert kind_of("is today st. patricks day") == "review"
    assert kind_of("Alexa, what's on my calendar") == "review"


def test_i_want_a_thing_is_an_errand_and_i_want_to_meet_is_not():
    from assistant.engine.segmentation.fastseg.kind import kind_of
    assert kind_of("I want sweet potato pie from a local bakery") == "task"
    assert kind_of("i want to meet sam on friday") == "event"
    assert kind_of("i want a meeting with sam tomorrow") == "event"


def test_a_sentence_seam_the_speaker_marked_is_a_cut():
    """". Also," and ", and then" are ask seams FastRule's front door has
    treated as a compound since its first board — and the cutter never cut
    there (four of the checkpoint's 26 misses; decompose_validate then
    multiplied the one item into junk). A bare "and then" is left to the
    clause tier, which wants a verb on each side: "meet sam and then we'll
    see" is an ask and a remark."""
    from assistant.engine.segmentation.fastseg.fastseg import cut
    assert cut("Remind me every Monday to take out the trash. Also, PUT MILK ON MY SHOPPING LIST") \
        == ["Remind me every Monday to take out the trash", "PUT MILK ON MY SHOPPING LIST"]
    assert cut("For the next three Sundays remind me I have yoga class at noon, and then yashas bithday with vinay") \
        == ["For the next three Sundays remind me I have yoga class at noon", "yashas bithday with vinay"]
    assert cut("meet sam and then we'll see") == ["meet sam and then we'll see"]
    assert cut("book gym between 2 and 4 and then dinner") == ["book gym between 2 and 4 and then dinner"]


def test_a_question_that_opens_with_an_auxiliary_is_a_review_even_without_its_time():
    """"is today st. patricks day" reaches the tagger as "is st. patricks day"
    — the time already cut out — so the "is today" form never saw it and an
    event 'St. Patrick's Day' was booked (dev-100 run 25). A command never
    opens with a bare auxiliary; "are you able to add…" is a polite
    imperative and stays out."""
    from assistant.engine.segmentation.fastseg.kind import kind_of
    assert kind_of("is st. patricks day") == "review"
    assert kind_of("does the gym close at nine") == "review"
    assert kind_of("am i free friday") == "review"
    assert kind_of("are you able to add yoga tomorrow") == "event"
