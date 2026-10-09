"""A command is read as of when it was SAID (assistant/clock).

Gil, 2026-10-09: two commands typed on Thursday sat in the phone's queue and
would have been read on Friday — "date tomorrow at 10:30" landing on
Saturday. *"the now should be a variable and used by the timestamp of the
command not hardcoded"*. These pin that a resend carrying `said_at` reads
"tomorrow" from then, that a live command is unchanged, and that a moment
the clock cannot vouch for is not believed.
"""
from __future__ import annotations

import datetime as dt
import time

import pytest

import assistant.api.server as server
from assistant import clock
from assistant.api import receipts
from assistant.db import get_db


@pytest.fixture
def client(registry_with_real_actions):
    receipts._reset()
    app = server.create_app()
    app.config.update(TESTING=True)
    yield app.test_client()
    receipts._reset()


def _yesterday_2pm() -> float:
    d = dt.datetime.combine(dt.date.today() - dt.timedelta(days=1), dt.time(14, 0))
    return d.timestamp()


def _dates(word: str) -> list[str]:
    """The days `word` is booked on — each test books its own word, since the
    scratch calendar is shared by the session."""
    return sorted(e["date"] for e in get_db().get_events_between(
        dt.date.today() - dt.timedelta(days=3), dt.date.today() + dt.timedelta(days=3))
        if word in e["title"].lower())


def test_the_clock_is_the_real_one_unless_told(monkeypatch):
    before = dt.datetime.now()
    assert abs((clock.now() - before).total_seconds()) < 2
    with clock.said_at(time.time() - 86400):
        assert clock.today() == dt.date.today() - dt.timedelta(days=1)
        assert 86390 < clock.behind() < 86410
    assert clock.behind() == 0


@pytest.mark.parametrize("ts", [None, "", "junk", time.time() + 3600,
                                time.time() - 400 * 86400])
def test_a_moment_the_clock_cannot_vouch_for_is_now(ts):
    with clock.said_at(ts):
        assert clock.behind() == 0


def test_a_queued_command_reads_tomorrow_from_when_it_was_said(client):
    out = client.post("/voice/text", json={
        "transcript": "book squash tomorrow at 7am", "source": "test",
        "client_id": "said-1", "said_at": _yesterday_2pm()}).get_json()
    assert out.get("committed"), out
    assert _dates("squash") == [dt.date.today().isoformat()]


def test_a_live_command_is_read_as_of_now(client):
    client.post("/voice/text", json={"transcript": "book tennis tomorrow at 7am",
                                     "source": "test"})
    assert _dates("tennis") == [(dt.date.today() + dt.timedelta(days=1)).isoformat()]


def test_the_stream_route_reads_as_of_said_at_too(client):
    import json
    raw = client.post("/voice/stream", json={"transcript": "book yoga tomorrow at 7am",
                                              "said_at": _yesterday_2pm()})
    last = [json.loads(x) for x in raw.get_data(as_text=True).splitlines() if x.strip()][-1]
    assert last.get("committed"), last
    assert _dates("yoga") == [dt.date.today().isoformat()]


def test_a_command_the_mac_parks_keeps_the_moment_it_was_said():
    from assistant.intent.memory import get_memory
    said = time.time() - 3 * 3600
    with clock.said_at(said):
        pid = get_memory().add_pending("buy milk tomorrow", "model offline", source="test")
    row = get_memory().get_pending(pid)
    assert abs(row["ts"] - said) < 5
