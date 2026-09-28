"""The same event is not booked twice (Gil, 2026-09-28: "reason duplicates if
same event were created").

One queued command booked the same daily series four times, each with a
linked to-do. `api/receipts.py` stops the same UPLOAD running twice; this stops
the same EVENT being written twice however it arrives.
"""
from __future__ import annotations

import datetime as dt

import pytest

TOMORROW = (dt.date.today() + dt.timedelta(days=1)).isoformat()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    return _db.get_db()


def _create(title, start="09:00", recurrence=None, recur_until=None, linked=False):
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.calendar.intent import CalendarIntent
    intent = CalendarIntent(title=title, date=TOMORROW, start_time=start,
                            end_time=f"{int(start[:2]) + 1:02d}{start[2:]}",
                            recurrence=recurrence, recur_until=recur_until,
                            linked_todo=linked)
    return CreateEventAction().execute(intent, None)


def _rows(db, title):
    with db._conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE lower(title) = lower(?) ORDER BY id", (title,))]


def test_the_same_event_again_is_not_booked_and_the_reply_says_so(db):
    _create("dentist")
    reply = _create("dentist")
    assert len(_rows(db, "dentist")) == 1
    assert "already on your calendar" in reply and "didn't add it again" in reply


def test_case_and_spacing_do_not_make_it_a_different_event(db):
    _create("walk jada")
    _create("  Walk Jada ")
    assert len(_rows(db, "walk jada")) == 1


def test_a_different_time_is_a_different_event(db):
    _create("walk jada", start="09:00")
    _create("walk jada", start="17:30")
    assert len(_rows(db, "walk jada")) == 2


def test_the_observed_case_one_series_not_four_and_one_linked_todo(db):
    """'Walk Jada every day …' — a daily series with a linked to-do (Q61)."""
    until = (dt.date.today() + dt.timedelta(days=13)).isoformat()
    for _ in range(4):
        _create("walk jada", recurrence="daily", recur_until=until, linked=True)
    rows = _rows(db, "walk jada")
    assert len({r["series_id"] for r in rows}) == 1
    first = min(rows, key=lambda r: r["id"])
    assert len(db.linked_todos(first["id"])) == 1


def test_a_one_off_does_not_block_a_series_of_the_same_name(db):
    _create("walk jada")
    reply = _create("walk jada", recurrence="daily",
                    recur_until=(dt.date.today() + dt.timedelta(days=5)).isoformat())
    assert "Created recurring" in reply


def test_it_still_points_at_the_event_that_was_already_there(db):
    from assistant.intent.context import context_memory
    _create("dentist")
    first = _rows(db, "dentist")[0]["id"]
    _create("something else", start="12:00")
    _create("dentist")
    assert context_memory.last_event_id == first
