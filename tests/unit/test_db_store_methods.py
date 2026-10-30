"""The store methods that replaced SQL written outside the store (2026-10-30).

The calendar action, offline reconciliation, vocabulary mining, the importer,
the engine's existence check and tag discovery each opened the database
themselves. Each now calls one CalendarDB method, pinned here.
"""
import pytest


@pytest.fixture
def db(tmp_path):
    from assistant.db import CalendarDB
    return CalendarDB(str(tmp_path / "c.db"))


def test_find_events_at_filters_by_date_and_or_time_earliest_first(db):
    a = db.create_event_from_dict({"title": "B", "date": "2026-11-02", "start_time": "11:00", "end_time": "12:00"})
    b = db.create_event_from_dict({"title": "A", "date": "2026-11-02", "start_time": "09:00", "end_time": "10:00"})
    db.create_event_from_dict({"title": "C", "date": "2026-11-03", "start_time": "09:00", "end_time": "10:00"})
    assert [e["id"] for e in db.find_events_at("2026-11-02")] == [b, a]
    assert [e["title"] for e in db.find_events_at(start_time="09:00")] == ["A", "C"]
    assert [e["id"] for e in db.find_events_at("2026-11-02", "11:00")] == [a]
    assert db.find_events_at() == []          # no filter is no answer, not every event


def test_series_first_date(db):
    db.create_event_from_dict({"title": "Run", "date": "2026-11-02", "start_time": "07:00",
                               "end_time": "07:30", "recurrence": "weekly"})
    sid = next(e["series_id"] for e in db.find_events_at("2026-11-09") if e.get("series_id"))
    assert db.series_first_date(sid) == "2026-11-02"
    assert db.series_first_date(999999) == ""


def test_titles_keys_and_existence(db):
    assert not db.has_rows("events") and not db.has_rows("todos")
    db.create_event_from_dict({"title": "Dentist", "date": "2026-11-02", "start_time": "10:00", "end_time": "11:00"})
    db.create_todo("Buy milk")
    assert db.has_rows("events") and db.has_rows("todos")
    assert db.event_titles() == ["Dentist"] and db.todo_titles() == ["Buy milk"]
    assert ("Dentist", "2026-11-02", "10:00") in db.event_keys()
    with pytest.raises(ValueError):
        db.has_rows("events; DROP TABLE todos")


def test_tag_suggestion_record(db):
    assert db.tag_suggestion("garden") is None
    db.record_tag_suggestion("garden", "refused", "2026-10-01T10:00:00")
    db.record_tag_suggestion("garden", "accepted", "2026-10-02T10:00:00", keep_status=True)
    row = db.tag_suggestion("garden")
    assert row["status"] == "refused" and row["ts"] == "2026-10-02T10:00:00"   # status kept
    db.record_tag_suggestion("garden", "accepted", "2026-10-03T10:00:00")
    assert db.tag_suggestion("garden")["status"] == "accepted"
    db.record_tag_suggestion("__last_asked__", "asked", "2026-10-04T10:00:00")
    db.hide_tag_suggestion("garden", True)
    rows = db.tag_suggestions(exclude="__last_asked__")
    assert [(r["name"], r["hidden"]) for r in rows] == [("garden", 1)]
    todo = db.create_todo("Weed the beds", tags=["garden"])
    assert {"title": "Weed the beds", "tags": ["garden"]} in db.todo_titles_and_tags()
    del todo
