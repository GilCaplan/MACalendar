"""Step 2 — segmentation. The pipeline's single point of failure, so the
traps live here: names joined by "and", idioms, verb lists, batched input.

The LLM is faked throughout (unit tests need no model); the live behaviour is
gated on scripts/engine_stage_check.py --stage segment.
"""

from __future__ import annotations

import pytest

import assistant.engine.llm as engine_llm
import assistant.engine.segmentation.old_seg.segment as segment
from assistant.engine import load_config
from assistant.engine.state import EngineState


@pytest.fixture
def cfg():
    return load_config()


def _seg(text: str, cfg) -> EngineState:
    st = EngineState(raw_text=text, text=text)
    return segment.run(st, cfg)


# --- deterministic splits: free, and never wrong ---------------------------

def test_bracket_batch_splits(cfg):
    st = _seg("[gym tomorrow at 7am] [lunch with Tal at noon]", cfg)
    assert [it.text for it in st.items] == ["gym tomorrow at 7am", "lunch with Tal at noon"]
    assert "[" not in st.text            # brackets must not reach a title


def test_coalescing_wrapper_splits(cfg):
    st = _seg('("gym tomorrow at 7am")and("buy milk")', cfg)
    assert len(st.items) == 2
    assert st.items[1].text == "buy milk"


def test_single_item_ids_and_kinds(cfg):
    st = _seg("what do I have this week", cfg)
    assert [it.id for it in st.items] == ["item_1"]
    assert st.items[0].kind == "review"


def test_task_phrasing_is_read_as_task(cfg):
    st = _seg("remind me to call Noa about the trip", cfg)
    assert st.items[0].kind == "task"


# --- the clause tier: the parse splits what speech actually sounds like ----
#
# Every delimiter above is something the PHONE inserts, so on dictated speech
# none of them can fire — the board measured 0 splits in 4,920 rows, which is
# why only 6.2% of compounds were atomized correctly. These pin the tier that
# reads the dependency parse instead, and the LLM must not be consulted for
# any of them.

def _no_llm(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("the clause tier must not need the model")
    monkeypatch.setattr(engine_llm, "call_json", _boom)


@pytest.mark.parametrize("text,expected", [
    ("book the gym and remind me to buy milk",
     ["book the gym", "remind me to buy milk"]),
    ("delete the gym session and add yoga on sunday",
     ["delete the gym session", "add yoga on sunday"]),
    ("call mom then pick up the dry cleaning",
     ["call mom", "pick up the dry cleaning"]),
    ("add gym tomorrow, buy milk, and call the dentist",
     ["add gym tomorrow", "buy milk", "call the dentist"]),
])
def test_two_asks_are_split_without_the_model(text, expected, cfg, monkeypatch):
    _no_llm(monkeypatch)
    st = _seg(text, cfg)
    assert [it.text for it in st.items] == expected


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
    tomorrow and a milk errand with NO date.

    Copying "tomorrow" onto the milk invents a deadline the speaker never
    gave — the same failure as a repeated relative date overwriting other
    events' real dates, which shipped once already. Only a date the utterance
    OPENS with is shared."""
    _no_llm(monkeypatch)
    st = _seg("book gym tomorrow at 7am and remind me to buy milk", cfg)
    assert [it.text for it in st.items] == [
        "book gym tomorrow at 7am", "remind me to buy milk"]


def test_an_enumeration_header_is_left_to_the_llm_tier(cfg, monkeypatch):
    """A clause split cuts at the "and" but not at the colon, which would glue
    the header onto the first item and lose the shared deadline from the rest.
    The LLM tier owns headers; this one must decline."""
    seen = {}

    def _capture(cfg_, system, user, schema=None):
        seen["called"] = True
        return {"items": []}, 1

    monkeypatch.setattr(engine_llm, "call_json", _capture)
    _seg("two tasks due tomorrow: buy groceries and return the library book", cfg)
    assert seen.get("called"), "the enumeration must reach the LLM tier"


# --- the LLM path: consulted only when the words suggest compounding -------

def test_no_compound_hint_means_no_llm_call(cfg, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("LLM must not be consulted for a simple command")
    monkeypatch.setattr(engine_llm, "call_json", _boom)
    st = _seg("book the dentist tomorrow morning at nine thirty", cfg)
    assert len(st.items) == 1


def test_llm_split_of_two_independent_requests(cfg, monkeypatch):
    """The LLM tier still splits what the parse could not read confidently.

    The input is deliberately one the deterministic tier declines (an event
    chain sharing a leading date, where no clause boundary is confident) —
    otherwise this would never reach the model and would be testing nothing.
    """
    monkeypatch.setattr(engine_llm, "call_json", lambda *a, **k: ({"items": [
        {"kind": "event", "text": "gym at 7 am tomorrow"},
        {"kind": "event", "text": "a meeting with Tal at 11 tomorrow"},
    ]}, 5))
    st = _seg("tomorrow gym at 7 am and a meeting with Tal at 11", cfg)
    assert [(it.kind, it.text) for it in st.items] == [
        ("event", "gym at 7 am tomorrow"),
        ("event", "a meeting with Tal at 11 tomorrow")]
    assert st.llm_ms == 5


def test_a_fragment_split_is_refused(cfg, monkeypatch):
    """A 'split' that produced a lone word is the model imagining structure —
    under-split bias says one item beats two broken ones."""
    monkeypatch.setattr(engine_llm, "call_json", lambda *a, **k: ({"items": [
        {"kind": "event", "text": "meeting with Tal and Ravid at Kems tomorrow"},
        {"kind": "event", "text": "Ravid"},
    ]}, 5))
    st = _seg("meeting with Tal and Ravid at Kems tomorrow evening", cfg)
    assert len(st.items) == 1


def test_llm_answering_one_item_keeps_one_item(cfg, monkeypatch):
    monkeypatch.setattr(engine_llm, "call_json", lambda *a, **k: ({"items": [
        {"kind": "event", "text": "meeting with Tal and Ravid at Kems tomorrow evening"},
    ]}, 5))
    st = _seg("meeting with Tal and Ravid at Kems tomorrow evening", cfg)
    assert len(st.items) == 1


def test_llm_failure_never_loses_the_command(cfg, monkeypatch):
    def _offline(*a, **k):
        raise RuntimeError("ollama offline")
    monkeypatch.setattr(engine_llm, "call_json", _offline)
    st = _seg("tomorrow gym at 7 am and a meeting with Tal at 11", cfg)
    assert len(st.items) == 1            # one item is always a legitimate reading


def test_loop_back_mistakes_reach_the_prompt(cfg, monkeypatch):
    seen = {}

    def _capture(cfg_, system, user, schema=None):
        seen["system"] = system
        return {"items": []}, 1

    monkeypatch.setattr(engine_llm, "call_json", _capture)
    st = EngineState(raw_text="x",
                     text="tomorrow gym at 7 am and a meeting with Tal at 11")
    st.mistakes = ["you merged two independent requests"]
    segment.run(st, cfg)
    assert "merged two independent requests" in seen["system"]


def test_enumeration_headers_are_dropped_from_a_split(cfg, monkeypatch):
    """Run 11: "add tasks:" survived as an item and parsed to unknown, eating
    a real task; "two tasks due tomorrow" became a phantom third create."""
    monkeypatch.setattr(engine_llm, "call_json", lambda *a, **k: ({"items": [
        {"kind": "task", "text": "add tasks"},
        {"kind": "task", "text": "submit the Haxaga grades"},
        {"kind": "task", "text": "pay rent"},
    ]}, 4))
    st = _seg("add tasks: submit the Haxaga grades and pay rent", cfg)
    assert [it.text for it in st.items] == ["submit the Haxaga grades", "pay rent"]


def test_a_header_with_a_due_phrase_is_still_a_header(cfg, monkeypatch):
    monkeypatch.setattr(engine_llm, "call_json", lambda *a, **k: ({"items": [
        {"kind": "task", "text": "two tasks due tomorrow"},
        {"kind": "task", "text": "buy groceries due tomorrow"},
        {"kind": "task", "text": "return the library book due tomorrow"},
    ]}, 4))
    st = _seg("two tasks due tomorrow: buy groceries and return the library book", cfg)
    assert len(st.items) == 2
    assert all("due tomorrow" in it.text for it in st.items)


def test_a_schedule_only_fragment_is_dropped(cfg, monkeypatch):
    monkeypatch.setattr(engine_llm, "call_json", lambda *a, **k: ({"items": [
        {"kind": "task", "text": "buy groceries due tomorrow"},
        {"kind": "task", "text": "due tomorrow"},
        {"kind": "task", "text": "return the library book due tomorrow"},
    ]}, 4))
    st = _seg("two tasks due tomorrow: buy groceries and return the library book", cfg)
    assert len(st.items) == 2


def test_a_timed_reminder_is_an_event(cfg):
    st = _seg("remind me about the dentist tomorrow at 9 am", cfg)
    assert st.items[0].kind == "event"


def test_an_untimed_reminder_stays_a_task(cfg):
    st = _seg("remind me to call Ravid", cfg)
    assert st.items[0].kind == "task"


# --- cycle 1: the pinned reminder rule is enforced over the LLM's labels ---

def test_a_timed_reminder_mislabelled_task_by_the_llm_becomes_an_event(cfg, monkeypatch):
    """Cycle 1 of the dataset loop (dev-fast 250): 'create a birthday wish
    reminder for tomorrow at 10 AM' was split correctly but labelled task, so
    it landed as a todo and generate's event-kind retry never fired — the
    event half of a compound was mis-kinded far more often than dropped. The
    deterministic rule (remind + clock time ⇒ calendar) now corrects the
    label; same rule on both paths."""
    monkeypatch.setattr(engine_llm, "call_json", lambda *a, **k: ({"items": [
        {"kind": "task", "text": "set a reminder for my meeting today"},
        {"kind": "task", "text": "create a birthday wish reminder for tomorrow at 10 AM"},
    ]}, 5))
    st = _seg("Olly, set a reminder for my meeting today and create a birthday "
              "wish reminder for tomorrow at 10 AM", cfg)
    kinds = [it.kind for it in st.items]
    assert kinds[1] == "event"     # clock time ⇒ calendar, whatever the label said
    # cycle 2 (Gil, 2026-09-04) extended the convention: a date-only reminder
    # ABOUT an occasion ("for my meeting today") is also a calendar entry.
    assert kinds[0] == "event"


def test_enforce_pinned_kinds_is_narrow():
    f = segment._enforce_pinned_kinds
    assert f("task", "remind me to go to my doctors at 4pm") == "event"
    assert f("task", "a reminder for the meeting at 3pm") == "event"
    assert f("task", "remind me to buy milk") == "task"                 # no time
    assert f("task", "add milk to the grocery list at 4pm") == "task"   # no remind wording
    assert f("event", "gym at 7") == "event"                            # never flips away from event
    assert f("review", "remind me what is at 4pm") == "review"          # only task labels corrected


# --- cycle 2: a dated occasion reminder is a calendar entry ----------------

def test_a_dated_occasion_reminder_becomes_an_event(cfg, monkeypatch):
    """Cycle 2 (product convention, Gil 2026-09-04): a reminder ABOUT an
    occasion — meeting, party, get-together — with a date is a calendar entry
    even without a clock time. The errand form ("remind me to <verb>") keeps
    cycle 1's clock gate."""
    monkeypatch.setattr(engine_llm, "call_json", lambda *a, **k: ({"items": [
        {"kind": "task", "text": "set a reminder for my meeting today"},
        {"kind": "task", "text": "remind me of my meeting tomorrow"},
    ]}, 5))
    st = _seg("set a reminder for my meeting today and remind me of my meeting "
              "tomorrow", cfg)
    assert [it.kind for it in st.items] == ["event", "event"]


def test_the_errand_form_keeps_the_clock_gate():
    f = segment._enforce_pinned_kinds
    assert f("task", "remind me to buy a present for the wedding on Sunday") == "task"  # to-verb errand
    assert f("task", "set a reminder for my meeting today") == "event"       # occasion + date
    assert f("task", "remind me of my meeting tomorrow") == "event"
    assert f("task", "reminder for a meeting I have on Tuesday") == "event"
    assert f("task", "set a reminder for my meeting") == "task"              # occasion, no date
    assert f("task", "remind me about the thing tomorrow") == "task"         # date, no occasion-noun


def test_cycle4_cues_each_earned_by_a_failing_row():
    """Cycle 4: additions justified by live dev-fast failures, never speculation."""
    f = segment._enforce_pinned_kinds
    # "notify me about any festival occurring next month" — 0 events before
    assert f("task", "notify me about any festival occurring next month") == "event"
    # "send a calendar invite … for brunch at 11 am on Tuesday" — no remind-word
    assert f("task", "send a calendar invite out to James and Alice for brunch") == "event"
    # notify without an occasion stays a task — the cue must not over-fire
    assert f("task", "notify me when the package arrives tomorrow") == "task"


def test_a_dated_i_need_to_meet_is_an_event_q1():
    """DEVQA Q1 (Gil, 2026-09-06): a dated "I need to <meet/talk/…>" is an
    appointment being made, not an errand — the dataset's ground truth calls
    it a calendar event. Undated encounters and dated errands are unchanged."""
    from assistant.engine.segmentation.old_seg.segment import _enforce_pinned_kinds
    assert _enforce_pinned_kinds(
        "task", "on Monday, the 20th, I need to have a conversation with Greg") == "event"
    assert _enforce_pinned_kinds("task", "I need to meet Sam tomorrow") == "event"
    assert _enforce_pinned_kinds("task", "I need to talk to the plumber at 3 pm") == "event"
    # counterexamples: errand with a date stays a task; undated encounter too
    assert _enforce_pinned_kinds("task", "I need to buy groceries tomorrow") == "task"
    assert _enforce_pinned_kinds("task", "I need to talk to Greg") == "task"


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
    from assistant.engine.segmentation.old_seg.segment import _kind_of

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
