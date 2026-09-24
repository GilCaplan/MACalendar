"""Every spoken example on the "How to Talk to Me" screen does what it says.

`assistant/tips.py` quotes sentences — "Dentist Tuesday at 4 and call Mom" is
an appointment and a to-do, "Yoga every Tuesday at 6pm" is one weekly
series — and the reader copies them. `test_tips_current.py` makes a new
engine VERSION re-open the tips; this runs the examples themselves, through
the whole engine (`run_transcript`, scratch stores) with EVERY model door
shut, on every build, so a change that quietly breaks one goes red here
first. Every quoted sentence lands on the fast path, so shutting the model
out is not a stub of what the user gets — it is what the user gets, and it
is exactly what CI (no ollama) sees.

Each case names the fragment the screen QUOTES and the sentence it RUNS; the
first test checks the fragment is still on the screen, so rewording a tip
without updating its case fails too. Time is frozen on an ordinary Monday
(2026-11-09, no Shabbat or yom tov in reach) before any clock in the
examples, so "tomorrow" and "Tuesday" land the same way on every run.

When this goes red: run the sentence live (the way `tips.py`'s comments
say), then fix the engine or change the words on the screen. Never loosen
the assertion to match a claim the engine does not make.
"""
from __future__ import annotations

import os
import sqlite3

import pytest
from freezegun import freeze_time

import assistant.engine as engine
from assistant.tips import STEPS, TIPS

NOW = "2026-11-09 05:00:00"     # Monday, before every clock quoted below
TUE, WED = "2026-11-10", "2026-11-11"
TODAY = "2026-11-09"


pytestmark = pytest.mark.usefixtures("registry_with_real_actions")


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    # `MACALENDAR_LLM_DISABLED` (conftest) shuts `engine.llm.call_json`, but
    # NOT the rescue's parse, which goes through `IntentParser._call_ollama`
    # directly — on a Mac with ollama up, that door reaches the live model
    # from a unit test (found writing this file, 2026-09-24). Shut both, and
    # report the model as offline, as it is on CI.
    import assistant.engine.llm as _llm
    import assistant.intent.parser as _parser
    from assistant.exceptions import OllamaUnavailableError

    def _refuse(*a, **k):
        raise OllamaUnavailableError("model shut out by test_tips_examples")
    monkeypatch.setattr(_parser.IntentParser, "_call_ollama", _refuse)
    monkeypatch.setattr(_llm, "is_reachable", lambda cfg=None: False)


@pytest.fixture(scope="module", autouse=True)
def _frozen_monday():
    # Load the engine's lazy imports (spaCy, pydantic, the recogniser) BEFORE
    # the clock is frozen: freezegun swaps `datetime.date` for a fake, and a
    # library that subclasses `date` at import time fails with a metaclass
    # conflict if its first import happens under the freeze. One freeze for
    # the module, not one per sentence: starting a freeze walks every loaded
    # module, which with the engine loaded cost seconds a call.
    engine.run_transcript("walk the dog", source="test")
    freezer = freeze_time(NOW)
    freezer.start()
    yield
    freezer.stop()


def _screen(where: str) -> str:
    kind, n = where.split(":")
    text = " ".join(STEPS[int(n)] if kind == "step" else TIPS[int(n)])
    return text.lower().replace(" ", " ")


def _run(said: str, confirm: bool = False):
    db = sqlite3.connect(os.environ["MACALENDAR_DB"])
    db.row_factory = sqlite3.Row

    def high(table):
        try:
            return db.execute(f"select coalesce(max(id), 0) from {table}").fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    ev0, td0 = high("events"), high("todos")
    out = engine.run_transcript(said, source="test", supports_confirm=confirm)
    events = [dict(r) for r in db.execute(
        "select * from events where id > ? order by date, start_time", (ev0,))]
    todos = [dict(r) for r in db.execute(
        "select * from todos where id > ? order by id", (td0,))]
    db.close()
    return out, events, todos


# (where the fragment is quoted, the fragment, the sentence run)
CASES = [
    ("step:0", "book the dentist tuesday at 4 and call mom",
     "Book the dentist Tuesday at 4 and call Mom"),
    ("step:1", "walk the dog at 9", "Walk the dog at 9"),
    ("step:1", "walk the dog", "Walk the dog"),
    ("step:2", "book yoga every tuesday at 6pm", "Book yoga every Tuesday at 6pm"),
    ("step:3", "team meeting tomorrow at 7", "Team meeting tomorrow at 7"),
    ("tip:0", "book the dentist tomorrow at 4", "Book the dentist tomorrow at 4"),
    ("tip:0", "leave the time out", "Book the dentist tomorrow"),
    ("tip:1", "meeting with sam tomorrow at 4", "Meeting with Sam tomorrow at 4"),
    ("tip:1", "set a meeting tomorrow at 4", "Set a meeting tomorrow at 4"),
    ("tip:2", "buy milk, eggs, and bread", "Buy milk, eggs, and bread"),
    ("tip:2", "buy milk and call mom", "Buy milk and call Mom"),
    ("tip:3", "next tuesday", "Book the dentist next Tuesday at 4"),
    ("tip:3", "on the 15th", "Book the dentist on the 15th at 4"),
    ("tip:3", "in two weeks", "Book the dentist in two weeks at 4"),
    ("tip:3", "next week", "Book yoga class next week"),
    ("tip:4", "book yoga every tuesday and thursday at 6pm",
     "Book yoga every Tuesday and Thursday at 6pm"),
]


@pytest.mark.parametrize("where,fragment,said", CASES)
def test_the_fragment_is_still_on_the_screen(where, fragment, said):
    assert fragment in _screen(where), (
        f"{where} no longer quotes {fragment!r} — update this case to the "
        "new example and re-run it live")


def test_every_step_and_tip_has_a_case():
    covered = {w for w, _, _ in CASES}
    assert covered == ({f"step:{i}" for i in range(len(STEPS))}
                       | {f"tip:{i}" for i in range(len(TIPS))})


# --- How it works -----------------------------------------------------------

def test_step1_one_sentence_splits_into_an_event_and_a_todo():
    _, events, todos = _run("Book the dentist Tuesday at 4 and call Mom")
    assert [(e["title"].lower(), e["date"], e["start_time"]) for e in events] == \
        [("dentist", TUE, "16:00")]
    assert [t["title"].lower() for t in todos] == ["call mom"]


def test_step2_a_time_makes_an_event_and_an_errand_without_one_a_todo():
    _, events, todos = _run("Walk the dog at 9")
    assert [(e["title"].lower(), e["date"], e["start_time"]) for e in events] == \
        [("walk the dog", TODAY, "09:00")]
    assert todos == []
    _, events, todos = _run("Walk the dog")
    assert events == []
    assert [t["title"].lower() for t in todos] == ["walk the dog"]


def test_step3_every_tuesday_is_one_weekly_series():
    _, events, todos = _run("Book yoga every Tuesday at 6pm")
    assert todos == []
    assert len(events) > 4
    assert {e["recurrence"] for e in events} == {"weekly"}
    assert len({e["series_id"] for e in events}) == 1
    assert events[0]["date"] == TUE and events[0]["start_time"] == "18:00"


def test_step4_a_bare_7_is_asked_on_the_phone_and_told_on_the_mac():
    out, events, _ = _run("Team meeting tomorrow at 7", confirm=True)
    assert out["parse"] == "confirm_create" and events == []
    assert out["proposal"][0]["body"]["start_time"] == "19:00"
    out, events, _ = _run("Team meeting tomorrow at 7", confirm=False)
    assert [(e["date"], e["start_time"]) for e in events] == [(TUE, "19:00")]
    assert "7 PM" in out["message"]


# --- Tips ---------------------------------------------------------------------

def test_tip1_a_day_and_time_lands_and_a_missing_time_is_picked_for_you():
    _, events, _ = _run("Book the dentist tomorrow at 4")
    assert [(e["date"], e["start_time"]) for e in events] == [(TUE, "16:00")]
    # The tip says it has to pick one (9 AM) — NOT that the reply says so:
    # on the fast path the 9 AM is silent (tips.py, tip 1's comment).
    _, events, _ = _run("Book the dentist tomorrow")
    assert [(e["date"], e["start_time"]) for e in events] == [(TUE, "09:00")]


def test_tip2_the_title_is_what_you_say_it_is_about():
    _, events, _ = _run("Meeting with Sam tomorrow at 4")
    assert [e["title"].lower() for e in events] == ["meeting with sam"]
    _, events, _ = _run("Set a meeting tomorrow at 4")
    assert [e["title"].lower() for e in events] == ["meeting"]


def test_tip3_one_verb_over_a_list_is_one_todo_and_two_verbs_are_two():
    _, _, todos = _run("Buy milk, eggs, and bread")
    assert [t["title"].lower() for t in todos] == ["buy milk, eggs, and bread"]
    _, _, todos = _run("Buy milk and call Mom")
    assert [t["title"].lower() for t in todos] == ["buy milk", "call mom"]


@pytest.mark.parametrize("said,day", [
    ("Book the dentist next Tuesday at 4", "2026-11-17"),   # said on a Monday: next week's
    ("Book the dentist on the 15th at 4", "2026-11-15"),
    ("Book the dentist in two weeks at 4", "2026-11-23"),
])
def test_tip4_a_named_or_counted_day_lands_on_that_day(said, day):
    _, events, _ = _run(said)
    assert [(e["date"], e["start_time"]) for e in events] == [(day, "16:00")]


def test_tip4_next_week_is_asked_about_on_the_phone():
    # "ask or guess": this phrasing is ASKED (DEVQA Q22); the guess half is
    # "yoga next week", which needs the model and is recorded in tips.py.
    out, events, _ = _run("Book yoga class next week", confirm=True)
    assert out["parse"] == "confirm_create" and events == []


def test_tip5_several_weekdays_make_one_series_on_both_days():
    # Rewritten 2026-09-24: the caveat this replaced ("every Tuesday and
    # Thursday in one go isn't reliable") went red the day the fast reader
    # learned weekday lists and the series started recording its days.
    _, events, _ = _run("Book yoga every Tuesday and Thursday at 6pm")
    assert events and {e["recurrence"] for e in events} == {"weekly"}
    assert len({e["series_id"] or e["id"] for e in events}) == 1       # ONE series
    days = {e["date"] for e in events}
    assert TUE in days and "2026-11-12" in days                       # both weekdays
    assert len(events) > 8
    assert {e["recur_days"] for e in events} == {"tuesday,thursday"}
