"""Cash out closes a counter's cycle, at once, on every surface.

Gil, 2026-11-01: "When I press the cash out, it doesn't seem to do anything,
or maybe it's just super slow." Two causes:

- The server decided which presses were in the open cycle by comparing
  timestamps as TEXT. The Mac writes microseconds, the phone whole seconds and
  a dialog no offset, and "12:00:00.5+02:00" sorts after "12:00:00+02:00", so
  a press made in the same second as the cash-out survived it. The Mac card
  had its own parsed copy of the rule (with `>=`), so the two surfaces could
  show different counts. There is one rule now, `db.presses_in_cycle`.
- The phone waited for the Mac's reply and a full reload before anything
  moved, and with the Mac away it changed nothing at all. It now zeroes the
  cycle in its cache at the tap, as `pressCounter` already did.
"""

from __future__ import annotations

import datetime

import pytest

from assistant.db import presses_in_cycle
from tests.unit._ios_sources import ios_source


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _counter(client, price=7.5):
    return client.post("/counters", json={"title": "Carpool", "price_per_unit": price}).get_json()["id"]


def _now_whole_seconds() -> str:
    """How the phone stamps a cash-out: local offset, no fraction."""
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def test_cash_out_from_the_phone_empties_the_cycle(client):
    cid = _counter(client)
    for stamp in ("2026-10-20T08:00:00+03:00", "2026-10-31T08:00:00+02:00", "2026-11-01T09:00:00.250000+02:00"):
        client.post(f"/counters/{cid}/press", json={"delta": 1, "pressed_at": stamp})

    r = client.post(f"/counters/{cid}/cashout", json={"cashed_at": "2026-11-01T09:00:01+02:00"})
    assert r.status_code == 201
    out = r.get_json()
    assert out["count"] == 0, "a press survived the cash-out that closed it"
    assert out["payout"] == 0
    assert out["total_count"] == 3                        # history stays

    payouts = client.get(f"/counters/{cid}/payouts").get_json()["payouts"]
    assert [(p["count"], p["amount"]) for p in payouts] == [(3, 22.5)]

    after = client.post(f"/counters/{cid}/press", json={"delta": 1}).get_json()
    assert (after["count"], after["payout"]) == (1, 7.5)


def test_a_press_is_never_owed_twice(client):
    """A press stamped after the cash-out (another device, while the phone's
    request waited in its queue) stays in the new cycle and is not banked."""
    cid = _counter(client)
    client.post(f"/counters/{cid}/press", json={"delta": 1, "pressed_at": "2026-11-01T09:00:00+02:00"})
    client.post(f"/counters/{cid}/press", json={"delta": 1, "pressed_at": "2026-11-01T09:05:00+02:00"})

    out = client.post(f"/counters/{cid}/cashout", json={"cashed_at": "2026-11-01T09:01:00+02:00"}).get_json()
    banked = client.get(f"/counters/{cid}/payouts").get_json()["payouts"][0]
    assert (banked["count"], banked["amount"]) == (1, 7.5)
    assert (out["count"], out["payout"]) == (1, 7.5)
    assert banked["count"] + out["count"] == out["total_count"]


def test_the_cycle_is_compared_by_moment_not_by_spelling():
    start = "2026-11-01T12:00:00+02:00"
    presses = [
        {"pressed_at": "2026-11-01T12:00:00.500000+02:00"},   # Mac clock, same second, AFTER
        {"pressed_at": "2026-11-01T11:59:59+02:00"},          # before
        {"pressed_at": "2026-11-01T10:00:30+00:00"},          # 12:00:30 local, written in UTC: after
        {"pressed_at": "2026-11-01T12:00:00+02:00"},          # the cash-out's own instant: banked
        {"pressed_at": "not a time"},                         # unreadable: kept, never hidden
    ]
    kept = [p["pressed_at"] for p in presses_in_cycle(presses, start)]
    assert kept == ["2026-11-01T12:00:00.500000+02:00", "2026-11-01T10:00:30+00:00", "not a time"]
    assert presses_in_cycle(presses, None) == presses


def test_the_latest_cash_out_is_the_latest_moment(tmp_path):
    from assistant.db import CalendarDB
    db = CalendarDB(str(tmp_path / "c.db"))
    cid = db.create_counter(title="x", price_per_unit=1)
    # As text, the naive dialog stamp sorts first; as a moment it is later.
    db.create_counter_payout(cid, "2026-11-01T00:00:00+02:00", "2026-11-01T12:00:00+02:00", 1, 1.0, "ILS")
    later_naive = (datetime.datetime(2026, 11, 1, 12, 0).astimezone()
                   + datetime.timedelta(hours=1)).replace(tzinfo=None).isoformat()
    db.create_counter_payout(cid, "2026-11-01T12:00:00+02:00", later_naive, 1, 1.0, "ILS")
    assert db.get_counter_cycle_start(cid) == later_naive


def test_the_mac_card_and_the_api_use_one_rule():
    from assistant.calendar_ui import timer_view
    presses = [{"pressed_at": "2026-11-01T12:00:00+02:00"}, {"pressed_at": "2026-11-01T12:00:01+02:00"}]
    start = "2026-11-01T12:00:00+02:00"
    assert timer_view._presses_since(presses, start) == presses_in_cycle(presses, start)
    routes = open("assistant/features/timer/routes.py", encoding="utf-8").read()
    assert "presses_in_cycle(presses, cycle)" in routes
    assert '["pressed_at"] > cycle' not in routes


VIEW = ios_source("TimerView.swift")
API = ios_source("APIClient.swift")
STORE = ios_source("LocalStore.swift")


def _func(src: str, sig: str) -> str:
    return src.split(sig, 1)[1].split("\n    }\n", 1)[0]


def test_the_phone_cashes_out_at_the_tap():
    body = _func(API, "func cashOutCounter(_ id: Int) async {")
    assert body.index("LocalStore.shared.cashOutCounter(id)") < body.index("mutateOrTell("), \
        "the cache must move before the Mac is asked"
    local = _func(STORE, "func cashOutCounter(_ id: Int) {")
    assert "counters[i].count = 0" in local and "counters[i].payout = 0" in local
    assert "totalCount" not in local and "todayCount" not in local   # history is not cleared
    # the tab redraws from the cache it just changed
    assert ".onReceive(LocalStore.shared.$counters)" in VIEW
