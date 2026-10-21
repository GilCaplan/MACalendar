"""POST /events is idempotent on `client_token`, like timers and to-dos.

The phone queues a create whose reply it never got (a 5 s timeout, a lost
connection) and replays it. Without a token the replay booked the same event
twice whenever the first attempt HAD reached the Mac (2026-10-21 audit).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


BODY = {"title": "Lunch", "date": "2026-11-01", "start_time": "13:00", "end_time": "14:00"}


def _count(client) -> int:
    return len([e for e in client.get("/events?date=2026-11-01").get_json() if e["title"] == "Lunch"])


def test_a_replayed_create_returns_the_same_event(client):
    first = client.post("/events", json={**BODY, "client_token": "tok-1"})
    again = client.post("/events", json={**BODY, "client_token": "tok-1", "_temp_id": -3})
    assert first.status_code == 201 and again.status_code == 200
    assert first.get_json()["id"] == again.get_json()["id"]
    assert _count(client) == 1


def test_creates_without_a_token_are_still_separate(client):
    client.post("/events", json=BODY)
    client.post("/events", json=BODY)
    assert _count(client) == 2
