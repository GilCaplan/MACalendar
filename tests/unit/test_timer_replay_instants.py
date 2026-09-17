"""Timer and counter writes carry the moment they HAPPENED, not the moment they arrive.

The phone queues writes it cannot deliver and replays them when the Mac is back
(`tests/unit/test_ios_offline.py` is the rule). Most writes survive that
untouched because they say what they want — "delete assignment 12" means the
same thing an hour later. The clock does not: "start this timer", read against
the Mac's own `now()` an hour after it was tapped, banks an hour of work that
never happened, and a tap counted after midnight lands on the wrong day.

`assistant/db.py` always accepted an explicit instant for all three; the routes
never passed one through, which is what made these writes unqueueable. These
tests pin the pass-through, because without it the phone's timestamps are
accepted silently and ignored — the worst possible failure for this feature.
"""
from __future__ import annotations

import datetime

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


def _timer(client) -> int:
    r = client.post("/timers", json={"title": "Thesis", "hourly_rate": 60})
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()["id"]


def _counter(client) -> int:
    r = client.post("/counters", json={"title": "Laps", "price_per_unit": 2})
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()["id"]


def test_start_honours_the_instant_it_was_tapped(client):
    tid = _timer(client)
    tapped = datetime.datetime.now().astimezone() - datetime.timedelta(hours=1)

    body = client.post(f"/timers/{tid}/start",
                       json={"start_time": tapped.isoformat()}).get_json()

    assert body["running"] is True
    assert body["seconds"] == pytest.approx(3600, abs=5)


def test_stop_honours_the_instant_it_was_tapped(client):
    tid = _timer(client)
    now = datetime.datetime.now().astimezone()
    client.post(f"/timers/{tid}/start",
                json={"start_time": (now - datetime.timedelta(hours=2)).isoformat()})

    body = client.post(f"/timers/{tid}/stop",
                       json={"end_time": (now - datetime.timedelta(hours=1)).isoformat()}).get_json()

    # An hour of work, not the two it would be if the Mac timed the replay.
    assert body["running"] is False
    assert body["seconds"] == pytest.approx(3600, abs=5)


def test_a_stop_before_its_own_start_is_refused_the_timestamp(client):
    """A wrong phone clock, or a stop replayed against a session the Mac had
    already restarted. A negative duration is worse than an approximate one."""
    tid = _timer(client)
    now = datetime.datetime.now().astimezone()
    client.post(f"/timers/{tid}/start", json={"start_time": now.isoformat()})

    body = client.post(f"/timers/{tid}/stop",
                       json={"end_time": (now - datetime.timedelta(hours=3)).isoformat()}).get_json()

    assert body["seconds"] >= 0


def test_omitting_the_instant_still_means_now(client):
    """The Mac's own Timer tab and any older client send no timestamp at all."""
    tid = _timer(client)

    body = client.post(f"/timers/{tid}/start", json={}).get_json()

    assert body["running"] is True
    assert body["seconds"] == pytest.approx(0, abs=5)


def test_a_z_suffixed_instant_is_read_not_silently_replaced(client):
    """`ISO8601DateFormatter` writes "…Z" for GMT, and `fromisoformat` only
    learned to read it in 3.11 — unhandled it fell into the "call it now"
    fallback, which is a wrong answer that looks like a right one."""
    tid = _timer(client)
    an_hour_ago = (datetime.datetime.now(datetime.timezone.utc)
                   - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = client.post(f"/timers/{tid}/start", json={"start_time": an_hour_ago}).get_json()

    assert body["seconds"] == pytest.approx(3600, abs=5)


def test_a_press_is_counted_on_the_day_it_was_made(client):
    cid = _counter(client)
    yesterday = datetime.datetime.now().astimezone() - datetime.timedelta(days=1)

    body = client.post(f"/counters/{cid}/press",
                       json={"delta": 3, "pressed_at": yesterday.isoformat()}).get_json()

    assert body["total_count"] == 3
    assert body["today_count"] == 0


def test_a_cash_out_is_stamped_when_it_was_asked_for(client):
    cid = _counter(client)
    client.post(f"/counters/{cid}/press", json={"delta": 4})
    asked = (datetime.datetime.now().astimezone() - datetime.timedelta(hours=5)).isoformat()

    client.post(f"/counters/{cid}/cashout", json={"cashed_at": asked})

    payouts = client.get(f"/counters/{cid}/payouts").get_json()["payouts"]
    assert len(payouts) == 1
    assert payouts[0]["payout_at"] == asked
    # The count is still the Mac's, from the presses it holds — the phone's
    # queue replays in order, so every press before the cash-out is already in.
    assert payouts[0]["count"] == 4
