"""A replayed create must not become a second row.

Replay is AT-LEAST-ONCE: a queued create that reaches the Mac and commits, but
whose reply is lost, stays at the head of the phone's queue and goes out again.
Without a key to recognise it by, the second attempt inserts a duplicate — which
is how 32 "buy groceries" rows accumulated in the Today list over 2026-09-04..06
and why `todos` grew a `client_token`.

Courses, assignments, timers and counters had the same exposure and no key. That
exposure was theoretical only while the phone DROPPED their offline writes; the
moment it started queueing them (tests/unit/test_ios_offline.py) it became real.
"""

from __future__ import annotations

import uuid

import pytest
from flask import Flask

from assistant.db import _IDEMPOTENT_TABLES


@pytest.fixture
def client():
    from assistant.features import registry
    app = Flask(__name__)
    registry.register(app)
    return app.test_client()


def _token():
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.mark.parametrize("path,body,table", [
    ("/courses", {"name": "Modern Vision"}, "courses"),
    ("/timers", {"title": "Thesis"}, "timers"),
    ("/counters", {"title": "Pushups"}, "counters"),
])
def test_replaying_a_create_returns_the_same_row(client, path, body, table):
    token = _token()
    first = client.post(path, json={**body, "client_token": token})
    assert first.status_code == 201, first.get_data(as_text=True)
    first_id = first.get_json()["id"]

    # The same queued entry, replayed because its reply was lost.
    second = client.post(path, json={**body, "client_token": token})
    assert second.status_code == 200, "a replay must not report a fresh create"
    assert second.get_json()["id"] == first_id, "replay created a SECOND row"
    assert second.get_json().get("duplicate") is True


def test_assignments_too(client):
    course = client.post("/courses", json={"name": "Algo", "client_token": _token()})
    cid = course.get_json()["id"]
    token = _token()
    a = client.post("/assignments", json={"course_id": cid, "title": "HW5",
                                          "client_token": token})
    b = client.post("/assignments", json={"course_id": cid, "title": "HW5",
                                          "client_token": token})
    assert a.status_code == 201 and b.status_code == 200
    assert a.get_json()["id"] == b.get_json()["id"]


def test_different_tokens_are_different_rows(client):
    a = client.post("/courses", json={"name": "Same Name", "client_token": _token()})
    b = client.post("/courses", json={"name": "Same Name", "client_token": _token()})
    assert a.get_json()["id"] != b.get_json()["id"], (
        "two genuinely separate creates were collapsed — the token is the key, "
        "not the content")


def test_no_token_still_works(client):
    """The Mac GUI, voice and calendar import create rows in-process and never
    go over the wire, so they have no token and cannot be retried."""
    r = client.post("/courses", json={"name": "Tokenless"})
    assert r.status_code == 201 and r.get_json()["id"] > 0


def test_every_client_creatable_table_has_the_column(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "c.db"))
    from assistant.db import CalendarDB
    db = CalendarDB()
    con = sqlite3.connect(db.path)
    for table in _IDEMPOTENT_TABLES:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        assert "client_token" in cols, table
        idx = [r[0] for r in con.execute(
            "select name from sqlite_master where type='index' and tbl_name=?", (table,))]
        assert any("client_token" in i for i in idx), (
            f"{table} has the column but no UNIQUE INDEX — the column alone "
            f"lets two concurrent replays both miss and both insert")


def test_the_lookup_refuses_a_table_it_was_not_given(tmp_path, monkeypatch):
    """The table name reaches `row_by_client_token` from a ROUTE, and a route's
    input is never a table name."""
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "c.db"))
    from assistant.db import CalendarDB
    db = CalendarDB()
    assert db.row_by_client_token("sqlite_master", "x") is None
    assert db.set_client_token("sqlite_master", 1, "x") is False
