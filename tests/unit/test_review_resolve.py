"""The review sheet sees every row a command touched, and can undo a change.

Gil, 2026-09-24: a six-part command opened a fix sheet showing one event, and
there was no way to say "nothing should have been done". Two things were
missing underneath: the join fed only the first event to the sheet, and a
DELETE linked no record at all (the context forgets a deleted row), so a wrong
delete could not even be seen in review. `assistant/intent/review.py` is the
join; the actions note the row as it was before they change it.
"""
from __future__ import annotations

import datetime as _dt

import pytest

import assistant.engine as engine


@pytest.fixture(autouse=True)
def _rules_only(monkeypatch, registry_with_real_actions):
    # The commands below are ones the front door answers alone; the model is
    # never needed, and must not be reached from a unit test.
    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    import assistant.engine.llm as _llm
    monkeypatch.setattr(_llm, "is_reachable", lambda cfg=None: True)


def _tomorrow() -> str:
    return (_dt.date.today() + _dt.timedelta(days=1)).isoformat()


def _resolved(memory_id):
    from assistant.intent import review
    return review.resolve(memory_id)


def test_every_created_object_is_listed_in_action_order():
    out = engine.run_transcript(
        "schedule a meeting tomorrow at 3pm and buy milk", source="mac")
    rows = _resolved(out["memory_id"])
    assert [(r["type"], r["action"]) for r in rows] == [
        ("event", "create_event"), ("todo", "create_todo")]
    assert [r["index"] for r in rows] == [0, 1]
    assert all(r["state"] == "live" and r["before"] is None for r in rows)
    assert rows[0]["start_time"] == "15:00" and rows[0]["date"] == _tomorrow()


def test_a_delete_is_linked_with_what_it_removed_and_how_to_restore_it():
    from assistant.db import get_db
    db = get_db()
    ev_id = db.create_event_from_dict(dict(title="dentist appointment", date=_tomorrow(),
                            start_time="10:00", end_time="11:00"))
    out = engine.run_transcript("cancel my dentist appointment", source="mac")
    assert db.get_event(ev_id) is None, out.get("result")
    (row,) = _resolved(out["memory_id"])
    assert row["action"] == "delete_event" and row["state"] == "gone"
    assert row["before"]["title"] == "dentist appointment"
    assert row["restore"]["kind"] == "event"
    body = row["restore"]["body"]
    assert (body["title"], body["date"], body["start_time"]) == (
        "dentist appointment", _tomorrow(), "10:00")


def test_an_update_keeps_the_row_as_it_was():
    from assistant.db import get_db
    db = get_db()
    ev_id = db.create_event_from_dict(dict(title="team sync", date=_tomorrow(),
                            start_time="10:00", end_time="11:00"))
    out = engine.run_transcript("move team sync to 4pm tomorrow", source="mac")
    rows = [r for r in _resolved(out["memory_id"]) if r["id"] == ev_id]
    assert rows, out.get("result")
    assert rows[0]["state"] == "live"
    assert rows[0]["before"]["start_time"] == "10:00"
    assert rows[0]["start_time"] != "10:00"


def test_a_completed_todo_keeps_its_open_state():
    from assistant.db import get_db
    db = get_db()
    td_id = db.create_todo(title="pay rent")
    out = engine.run_transcript("complete pay rent", source="mac")
    rows = [r for r in _resolved(out["memory_id"]) if r["id"] == td_id]
    assert rows, out.get("result")
    assert rows[0]["completed"] is True
    assert rows[0]["before"]["completed"] is False


def test_memory_rows_written_before_the_column_still_read():
    """A record linked without a before row (every row before 2026-09-24)
    reads back with before=None, not an error."""
    from assistant.intent.memory import get_memory
    mem = get_memory()
    ex = mem.record(transcript="x", actions=[("create_todo", {"titles": ["x"]})],
                    records=[("todo", 999999, "create_todo", 0)])
    (rec,) = mem.records_for(ex)
    assert rec["before"] is None and rec["action_index"] == 0


# --- the fix sheet's plan ----------------------------------------------------

def _example_for(out):
    from assistant.intent import review
    from assistant.intent.memory import get_memory
    ex = get_memory().get(out["memory_id"])
    ex["resolved"] = review.resolve(out["memory_id"])
    return ex


def test_nothing_should_have_been_done_takes_every_create_back():
    from assistant.db import get_db
    from assistant.intent import review
    out = engine.run_transcript("schedule a meeting tomorrow at 3pm and buy milk", source="mac")
    ex = _example_for(out)
    rows = review.rows_for(ex)
    assert len(rows) == 2 and all(r.can_undo for r in rows)
    for r in rows:
        r.choice = review.UNDO
    p = review.plan(ex, rows, reasons={"Didn't ask for this"})
    assert p["feedback"] == "corrected" and p["correction"] == []
    assert p["notes"] == "[Didn't ask for this]"
    assert review.apply(p["ops"]) == []
    db = get_db()
    assert db.get_event(rows[0].record["id"]) is None
    assert db.get_todo(rows[1].record["id"]) is None


def test_the_wrong_kind_is_swapped_and_taught():
    from assistant.db import get_db
    from assistant.intent import review
    out = engine.run_transcript("buy milk", source="mac")
    ex = _example_for(out)
    (row,) = review.rows_for(ex)
    row.choice, row.kind = review.CHANGE, "event"
    row.date, row.start, row.end = _tomorrow(), "18:00", "19:00"
    p = review.plan(ex, [row])
    assert [op[0] for op in p["ops"]] == ["delete_todo", "create_event"]
    assert p["correction"] == [{"action": "create_event", "parameters": {
        "title": row.title, "date": _tomorrow(), "start_time": "18:00", "end_time": "19:00"}}]
    assert review.apply(p["ops"]) == []
    assert get_db().get_todo(row.record["id"]) is None
    assert any(e["start_time"] == "18:00" for e in get_db().get_events_for_day(_dt.date.fromisoformat(_tomorrow())))


def test_a_wrong_delete_is_restored():
    from assistant.db import get_db
    from assistant.intent import review
    db = get_db()
    db.create_event_from_dict(dict(title="dentist appointment", date=_tomorrow(),
                                   start_time="10:00", end_time="11:00"))
    ex = _example_for(engine.run_transcript("cancel my dentist appointment", source="mac"))
    (row,) = review.rows_for(ex)
    assert row.is_delete and row.can_undo and row.undo_label == "Restore"
    row.choice = review.UNDO
    assert review.apply(review.plan(ex, [row])["ops"]) == []
    back = [e for e in db.get_events_for_day(_dt.date.fromisoformat(_tomorrow())) if e["title"] == "dentist appointment"]
    assert back and back[0]["start_time"] == "10:00"


def test_an_added_row_is_created_and_appended_to_the_gold():
    from assistant.intent import review
    ex = _example_for(engine.run_transcript("buy milk", source="mac"))
    rows = review.rows_for(ex) + [review.FixRow(index=None, action="", kind="todo",
                                                title="pay rent", choice=review.CHANGE)]
    p = review.plan(ex, rows)
    assert p["correction"][0]["action"] == "create_todo"            # the untouched original
    assert p["correction"][-1] == {"action": "create_todo", "parameters": {"titles": ["pay rent"]}}
    assert p["ops"] == [("create_todo", "pay rent", "")]


def test_a_verdict_with_no_edit_is_a_plain_reject():
    from assistant.intent import review
    ex = _example_for(engine.run_transcript("buy milk", source="mac"))
    p = review.plan(ex, review.rows_for(ex), notes="misheard")
    assert p == {"ops": [], "feedback": "rejected", "correction": None, "notes": "misheard"}
