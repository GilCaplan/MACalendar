"""End repeat: a series made or edited by hand is ONE linked thing, and its
end date grows it, trims it, or goes away.

Gil, 2026-09-25: "On repeat there should be an option to set a end date for
reoccurring events and have it all linked as a series of calendar objects."

The db had the series machinery; what these pin is the MANUAL paths into it
(the Mac dialog and `POST /events` go through `create_event_from_dict`, the
phone's series edits through `PATCH /events/<id>/series` → `update_series`),
which had each dropped something the voice path kept: guests past the first
instance, the category, and — on regeneration — a multi-weekday series'
second weekday. Real temp-file SQLite, same class production uses.
"""
from __future__ import annotations

import datetime as dt

import pytest

import assistant.api.server as server_module
from assistant.db import CalendarDB


@pytest.fixture
def db(tmp_path) -> CalendarDB:
    return CalendarDB(path=str(tmp_path / "series_end.db"))


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(server_module, "get_db", lambda: db)
    return server_module.create_app().test_client()


def _weekly(db, end="2026-11-02", **kw):
    data = {"title": "Standup", "date": "2026-10-05",   # a Monday
            "start_time": "09:00", "end_time": "09:30",
            "recurrence": "weekly", "recurrence_end": end}
    data.update(kw)
    return db.create_event_from_dict(data)


def _dates(db, sid):
    return sorted(e["date"] for e in db.get_series_events(sid))


# ------------------------------------------------------------------ creating

def test_the_end_date_is_included(db):
    """'Ends on Mon 2 Nov' books Mon 2 Nov — the hint says so, and so must the db."""
    sid = _weekly(db, end="2026-11-02")
    assert _dates(db, sid) == ["2026-10-05", "2026-10-12", "2026-10-19",
                               "2026-10-26", "2026-11-02"]


def test_every_instance_carries_one_series_id(db):
    sid = _weekly(db)
    assert {e["series_id"] for e in db.get_series_events(sid)} == {sid}


def test_never_books_a_year_ahead(db):
    sid = _weekly(db, end="")
    dates = _dates(db, sid)
    assert dates[-1] > "2027-09-27" and dates[-1] <= "2027-10-05"
    assert all(e["recurrence_end"] == "" for e in db.get_series_events(sid))


def test_a_hand_made_series_keeps_its_guests_and_category_on_every_instance(db):
    """The dialog's path generated instances with NO attendees and NO category —
    one categorised event and the rest grey, guests on the first only."""
    sid = _weekly(db, attendees="Dana, Yoni", category="Work")
    rows = db.get_series_events(sid)
    assert len(rows) == 5
    assert {r["attendees"] for r in rows} == {"Dana, Yoni"}
    assert {r["category"] for r in rows} == {"Work"}


def test_a_hand_made_series_still_skips_shabbat(db):
    """Same db path as voice, so the same observance rule — not a second copy."""
    sid = db.create_event_from_dict({
        "title": "Mincha Maariv", "date": "2026-08-31",   # Monday
        "start_time": "19:00", "end_time": "19:30",
        "recurrence": "daily", "recurrence_end": "2026-09-06"})
    dates = _dates(db, sid)
    # Friday 19:00 is after candle lighting (18:43), Saturday 19:00 before tzeit
    assert "2026-09-04" not in dates and "2026-09-05" not in dates
    assert "2026-09-03" in dates and "2026-09-06" in dates


# ------------------------------------------------------------------- editing

def test_extending_the_end_grows_the_series_under_the_same_id(db):
    sid = _weekly(db, end="2026-10-19")
    db.update_series(sid, sid, recurrence_end="2026-11-09")
    assert _dates(db, sid)[-1] == "2026-11-09"
    assert {e["series_id"] for e in db.get_series_events(sid)} == {sid}
    assert {e["recurrence_end"] for e in db.get_series_events(sid)} == {"2026-11-09"}


def test_shortening_from_a_later_instance_trims_and_keeps_the_past(db):
    sid = _weekly(db, end="2026-11-30")
    second = sorted(db.get_series_events(sid), key=lambda e: e["date"])[1]
    db.update_series(sid, second["id"], recurrence_end="2026-10-26")
    assert _dates(db, sid) == ["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"]


def test_never_to_a_date_and_back(db):
    sid = _weekly(db, end="")
    long = len(_dates(db, sid))
    db.update_series(sid, sid, recurrence_end="2026-10-19")
    assert _dates(db, sid) == ["2026-10-05", "2026-10-12", "2026-10-19"]
    db.update_series(sid, sid, recurrence_end="")
    assert len(_dates(db, sid)) == long


def test_regenerating_keeps_guests_category_and_both_weekdays(db):
    """A 'tuesday and thursday' series whose end moved came back Tuesday-only:
    the regeneration seed had no `recur_days`."""
    sid = db.create_event_from_dict({
        "title": "Gym", "date": "2026-10-06", "start_time": "07:00",   # Tuesday
        "end_time": "08:00", "recurrence": "weekly",
        "recurrence_end": "2026-10-15", "attendees": "Dana", "category": "Health"})
    with db._conn() as conn:        # recur_days is written by the voice path
        conn.execute("UPDATE events SET recur_days = 'tuesday,thursday' "
                     "WHERE series_id = ?", (sid,))
    db.update_series(sid, sid, recurrence_end="2026-10-22")
    rows = db.get_series_events(sid)
    weekdays = {dt.date.fromisoformat(r["date"]).weekday() for r in rows}
    assert weekdays == {1, 3}, _dates(db, sid)
    assert _dates(db, sid)[-1] == "2026-10-22"
    assert {r["attendees"] for r in rows} == {"Dana"}
    assert {r["category"] for r in rows} == {"Health"}


def test_an_end_before_the_edited_instance_is_refused(db):
    sid = _weekly(db, end="2026-11-30")
    third = sorted(db.get_series_events(sid), key=lambda e: e["date"])[2]
    before = _dates(db, sid)
    with pytest.raises(ValueError):
        db.update_series(sid, third["id"], recurrence_end="2026-10-12")
    assert _dates(db, sid) == before


# -------------------------------------------------------------------- routes

def test_post_events_makes_a_linked_series(client, db):
    r = client.post("/events", json={
        "title": "Standup", "date": "2026-10-05", "start_time": "09:00",
        "end_time": "09:30", "recurrence": "weekly", "recurrence_end": "2026-10-19"})
    assert r.status_code == 201
    got = client.get(f"/events/{r.get_json()['id']}/series").get_json()
    assert got["count"] == 3 and got["recurrence_end"] == "2026-10-19"


def test_patch_series_moves_the_end_and_answers_with_the_new_count(client, db):
    sid = _weekly(db, end="2026-10-19")
    out = client.patch(f"/events/{sid}/series", json={"recurrence_end": "2026-11-02"})
    assert out.status_code == 200
    assert out.get_json()["count"] == 5
    assert out.get_json()["series_id"] == sid


def test_patch_series_refuses_an_end_before_the_event(client, db):
    sid = _weekly(db)
    r = client.patch(f"/events/{sid}/series", json={"recurrence_end": "2026-09-01"})
    assert r.status_code == 400
    assert "before this event" in r.get_json()["error"]
    assert len(_dates(db, sid)) == 5


def test_patch_series_refuses_an_end_that_is_not_a_date(client, db):
    sid = _weekly(db)
    r = client.patch(f"/events/{sid}/series", json={"recurrence_end": "next month"})
    assert r.status_code == 400
