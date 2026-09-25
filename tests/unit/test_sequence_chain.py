"""A sequence is split, keeps its relationships, and chains its times (DEVQA Q51).

Gil, 2026-09-25: "X followed by Y followed by Z … if the time isn't given …
maybe Y is just the following hour after X". Segmentation cuts at the
sequence words and writes `Item.relation`; decompose_validate's `chain.py`
fills each untimed part from the one before it; FastRule's gate hands every
sequence to the deep track so the chain can run at all.
"""
from __future__ import annotations

import datetime as dt
import types

import pytest

from assistant.engine import segmentation as S
from assistant.engine.decompose_validate import stage as DV
from assistant.engine.state import EngineState

DAY = dt.date(2026, 9, 9)                       # a Wednesday
TOMORROW = "2026-09-10"
_CFG = types.SimpleNamespace(engine=types.SimpleNamespace(kind_router=True))


def _run(text):
    st = EngineState(raw_text=text, text=text, source="test")
    S.run(st, _CFG)
    DV.resolve_values(st, DAY)
    return [(it.kind, it.slots.get("date"), it.slots.get("start_time"), it.slots.get("end_time"),
             (it.relation or {}).get("kind"), bool(it.slots.get("linked_todo")))
            for it in st.items]


@pytest.mark.parametrize("text,kinds", [
    ("tomorrow walk the dog at 5 followed by lunch followed by gym", [None, "sequence", "sequence"]),
    ("dentist at 9 and after that lunch", [None, "sequence"]),
    ("buy milk and eggs, and book the dentist at 3. Also call mom", [None, "list", "sentence"]),
    ("walk the dog at 9 and 2:30", [None, "same_span"]),
])
def test_every_item_says_how_it_relates_to_the_one_before(text, kinds):
    assert [r[4] for r in _run(text)] == kinds


@pytest.mark.parametrize("text", ["meet sam and then we'll see", "remind me to call mom then"])
def test_a_remark_or_a_trailing_then_is_not_a_seam(text):
    assert len(_run(text)) == 1


def test_untimed_parts_start_when_the_one_before_ends():
    rows = _run("tomorrow walk the dog at 5 followed by lunch followed by gym")
    assert [(r[1], r[2], r[3]) for r in rows[1:]] == [(TOMORROW, "18:00", "19:00"),
                                                      (TOMORROW, "19:00", "20:00")]


def test_the_chain_beats_a_meals_own_hour():
    assert _run("tomorrow gym at 9, then lunch")[1][2] == "10:00"


def test_a_stated_clock_wins_and_the_chain_runs_on_from_it():
    rows = _run("tomorrow dentist at 9 then lunch then gym at 3 then dinner")
    assert [r[2] for r in rows] == ["09:00", "10:00", "15:00", "16:00"]


def test_a_stated_duration_moves_what_follows():
    assert _run("tomorrow walk the dog at 5 for 2 hours followed by dinner")[1][2] == "19:00"


def test_a_part_with_no_day_takes_the_day_before_it():
    assert _run("book gym tomorrow at 7 and afterwards coffee with Dana")[1][1] == TOMORROW


def test_a_todo_in_a_chain_is_an_event_and_a_linked_todo():
    rows = _run("walk the dog at 5 then do the laundry")
    assert rows[1][0] == "event" and rows[1][2] == "18:00" and rows[1][5]


def test_right_after_a_named_thing_chains_from_that_thing():
    rows = _run("tomorrow davening at 8am then lunch and then training with Mark right after davening")
    assert rows[-1][2] == "09:00"


def test_a_list_is_not_chained():
    rows = _run("book the dentist tomorrow at 9 and buy milk")
    assert rows[1][4] == "list"
    assert rows[1][0] == "task" and rows[1][2] is None and not rows[1][5]


def test_the_gap_and_length_settings_are_read(monkeypatch):
    from assistant import event_defaults as E
    monkeypatch.setattr(E, "gap_minutes", lambda category=None: 15)
    monkeypatch.setattr(E, "length_minutes", lambda category=None: 30)
    rows = _run("tomorrow walk the dog at 5 followed by gym")
    assert (rows[1][2], rows[1][3]) == ("17:45", "18:15")


@pytest.mark.parametrize("text", [
    "tomorrow walk the dog at 5 followed by lunch followed by gym",
    "book gym tomorrow at 7 and afterwards coffee with Dana",
    "walk the dog at 5 then do the laundry",
])
def test_the_front_door_hands_a_sequence_to_the_deep_track(text):
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    assert getattr(FastRule(RULE_THRESHOLD).run(text), "reason", None) == "strong-compound"


def test_a_chained_todo_is_filed_as_both(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.calendar.intent import CalendarIntent
    CreateEventAction().execute(CalendarIntent(title="do the laundry", date=TOMORROW,
                                               start_time="18:00", linked_todo=True), None)
    db = _db.get_db()
    with db._conn() as conn:
        ev = conn.execute("SELECT id FROM events WHERE title = 'do the laundry'").fetchone()[0]
    assert db.linked_todo(ev)["title"] == "do the laundry"


@pytest.mark.parametrize("text,parts", [
    ("tomorrow walk the dog at 5 folowed by lunch", 2),        # misspelled, not fixed upstream
    ("gym at 9 and afterwords coffee", 2),
    ("gym at 9, than lunch", 2),
    ("gym at 9, once that's done lunch", 2),
    ("gym at 9 and when i'm done with that do the laundry", 2),
    ("gym at 9 then then lunch", 2),
    ("it costs more than 5 dollars", 1),                         # "than" alone is not a seam
    ("dinner at 7 when finished work", 1),                       # a time, not a seam
    ("mark wash the car as done, finally got to it", 1),         # an aside
])
def test_the_wording_and_its_misspellings(text, parts):
    assert len(_run(text)) == parts


def test_the_ordinal_words_leave_the_titles():
    st = EngineState(raw_text="x", text="first walk the dog at 5, then finally gym", source="test")
    st.text = st.raw_text = "first walk the dog at 5, then finally gym"
    S.run(st, _CFG)
    DV.resolve_values(st, DAY)
    assert [i.text for i in st.items] == ["walk the dog", "gym"]


# --- the cycles on the sequence corpus (2026-09-25), one shape each ---------

@pytest.mark.parametrize("text,actions", [
    # A1 · a postposed marker makes the comma before it a seam
    ("physio at 2, product demo after that", ["physio", "product demo"]),
    ("product demo at 11:15, a working lunch afterwards", ["product demo", "a working lunch"]),
    # A2 · "next", set off, is a joiner; before a date it is not
    ("first a run at ten, next flight to Chicago, then lunch", ["a run", "flight to Chicago", "lunch"]),
    ("book gym next friday at 5", ["book gym"]),
    ("cancel the next meeting", ["cancel the next meeting"]),
    # A3 · a seam word before an action VERB cuts; before a noun it is a time
    ("therapy session at 2 and after water the plants", ["therapy session", "water the plants"]),
    ("conference call at 4 and when finished pack for the trip", ["conference call", "pack for the trip"]),
    ("gym at 9 and after lunch", ["gym and after lunch"]),
    ("schedule workshop for this friday, add water the plants to my list, and book moving day for next month",
     ["schedule workshop", "add water the plants to my list", "book moving day"]),
    # A4 · ", finally" closes a sequence; alone it is an aside
    ("first gym at 16:30 then yoga class, finally dinner", ["gym", "yoga class", "dinner"]),
    ("first conference call at 7pm then team meeting, then finally dinner", ["conference call", "team meeting", "dinner"]),
])
def test_the_cut(text, actions):
    """Through the STAGE: a postposed marker leaves the title in `relate`."""
    st = EngineState(raw_text=text, text=text, source="test")
    S.run(st, _CFG)
    assert [i.text for i in st.items] == actions
