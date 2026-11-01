"""Cash out pays what is owed, once, on every surface, whatever order it syncs in.

Gil, 2026-11-01: "When I press the cash out, it doesn't seem to do anything,
or maybe it's just super slow." Then: "if I press the cash out multiple times
… then what … if it's cash out, and then there are more pluses done on the
Mac, then you do the cash out, and then you add on top of that."

Each press records the cash-out that paid it (`counter_presses.payout_id`);
a press no cash-out has paid is owed. That one fact answers every case:

- tapped twice, or a queued cash-out replayed after its reply was lost: the
  second finds nothing owed and writes nothing;
- a plus on the Mac after the phone's cash-out: stamped later, so not paid by
  it, and it sits on top of the new cycle;
- a plus made offline BEFORE a cash-out but synced AFTER it: it was not in what
  was paid, so it is still owed. The old rule ("after the last cash-out's
  time") dropped it from both the payout and the new cycle, and the money was
  lost.

The phone zeroes the cycle in its cache at the tap and keeps that row until
its queued write lands, so it does not wait on, or get reverted by, the Mac.
"""

from __future__ import annotations

import datetime
import sqlite3

import pytest

from assistant.db import CalendarDB, open_presses
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


def _press(client, cid, at=None):
    return client.post(f"/counters/{cid}/press", json={"delta": 1, **({"pressed_at": at} if at else {})}).get_json()


def _cash(client, cid, at):
    return client.post(f"/counters/{cid}/cashout", json={"cashed_at": at})


def _payouts(client, cid):
    return client.get(f"/counters/{cid}/payouts").get_json()["payouts"]


def test_cash_out_empties_the_cycle_and_keeps_the_history(client):
    cid = _counter(client)
    for at in ("2026-10-20T08:00:00+03:00", "2026-10-31T08:00:00+02:00", "2026-11-01T09:00:00.250000+02:00"):
        _press(client, cid, at)

    r = _cash(client, cid, "2026-11-01T09:00:01+02:00")
    assert r.status_code == 201
    out = r.get_json()
    assert (out["count"], out["payout"], out["total_count"]) == (0, 0, 3)
    assert [(p["count"], p["amount"]) for p in _payouts(client, cid)] == [(3, 22.5)]

    after = _press(client, cid)
    assert (after["count"], after["payout"]) == (1, 7.5)


def test_pressing_cash_out_again_does_nothing(client):
    cid = _counter(client)
    _press(client, cid, "2026-11-01T09:00:00+02:00")
    _press(client, cid, "2026-11-01T09:01:00+02:00")

    assert _cash(client, cid, "2026-11-01T09:02:00+02:00").status_code == 201
    again = _cash(client, cid, "2026-11-01T09:02:03+02:00")            # a second, impatient tap
    replay = _cash(client, cid, "2026-11-01T09:02:00+02:00")           # the queue replaying the first
    assert again.status_code == replay.status_code == 200
    assert again.get_json()["nothing_owed"] is True
    assert [(p["count"], p["amount"]) for p in _payouts(client, cid)] == [(2, 15.0)]


def test_pluses_after_a_cash_out_land_on_top(client):
    """Phone cashes out at 09:01; the Mac had a plus at 09:05 before the
    phone's request arrived. That plus is not paid; it starts the new cycle."""
    cid = _counter(client)
    _press(client, cid, "2026-11-01T09:00:00+02:00")
    _press(client, cid, "2026-11-01T09:05:00+02:00")

    out = _cash(client, cid, "2026-11-01T09:01:00+02:00").get_json()
    (paid,) = _payouts(client, cid)
    assert (paid["count"], paid["amount"]) == (1, 7.5)
    assert (out["count"], out["payout"]) == (1, 7.5)
    assert paid["count"] + out["count"] == out["total_count"]          # never owed twice


def test_a_plus_synced_late_is_still_owed(client):
    """A plus made offline at 10:00, synced after an 11:00 cash-out on the Mac.
    It was not in what was paid, so it is owed now, not lost."""
    cid = _counter(client)
    _press(client, cid, "2026-11-01T09:00:00+02:00")
    _cash(client, cid, "2026-11-01T11:00:00+02:00")
    late = _press(client, cid, "2026-11-01T10:00:00+02:00")
    assert (late["count"], late["payout"]) == (1, 7.5)
    assert [p["count"] for p in _payouts(client, cid)] == [1]


def test_deleting_a_cash_out_makes_its_presses_owed_again(tmp_path):
    db = CalendarDB(str(tmp_path / "c.db"))
    cid = db.create_counter(title="x", price_per_unit=2)
    db.create_counter_press(cid, pressed_at="2026-11-01T09:00:00+02:00")
    paid = db.cash_out_counter(cid, "2026-11-01T10:00:00+02:00")
    assert open_presses(db.get_counter_presses(cid)) == []
    db.delete_counter_payout(paid["id"])
    assert len(open_presses(db.get_counter_presses(cid))) == 1


def test_an_older_file_keeps_its_counts(tmp_path):
    """Opening a file from before `payout_id` gives each press the cash-out
    that, by the old time rule, paid it — so no count changes on upgrade."""
    path = tmp_path / "old.db"
    db = CalendarDB(str(path))
    cid = db.create_counter(title="x", price_per_unit=1)
    for at in ("2026-10-01T09:00:00+03:00", "2026-10-02T09:00:00+03:00", "2026-10-05T09:00:00+03:00"):
        db.create_counter_press(cid, pressed_at=at)
    with sqlite3.connect(path) as c:              # what an older file looks like
        c.execute("INSERT INTO counter_payouts (counter_id, cycle_started_at, payout_at, count, amount, "
                  "currency, note, created_at) VALUES (?, '', '2026-10-03T00:00:00+03:00', 2, 2, 'ILS', '', '')",
                  (cid,))
        c.execute("ALTER TABLE counter_presses DROP COLUMN payout_id")
        c.execute("PRAGMA user_version = 2")

    reopened = CalendarDB(str(path))
    presses = reopened.get_counter_presses(cid)
    assert [p["pressed_at"][:10] for p in open_presses(presses)] == ["2026-10-05"]
    assert sum(1 for p in presses if p["payout_id"] is not None) == 2


def test_the_mac_pays_what_its_dialog_showed(tmp_path):
    db = CalendarDB(str(tmp_path / "c.db"))
    cid = db.create_counter(title="x", price_per_unit=1)
    db.create_counter_press(cid, pressed_at="2026-11-01T09:00:00+02:00")
    db.create_counter_press(cid, pressed_at="2026-11-01T09:30:00+02:00")    # the phone, while it was open
    paid = db.cash_out_counter(cid, "2026-11-01T09:00", bank_until="2026-11-01T09:10:00+02:00",
                               count=1, amount=5.0)
    assert (paid["count"], paid["amount"]) == (1, 5.0)                     # the dialog's numbers
    assert len(open_presses(db.get_counter_presses(cid))) == 1
    from assistant.calendar_ui import timer_view
    assert timer_view._presses_since(db.get_counter_presses(cid)) == open_presses(db.get_counter_presses(cid))


def test_the_latest_cash_out_is_the_latest_moment(tmp_path):
    db = CalendarDB(str(tmp_path / "c.db"))
    cid = db.create_counter(title="x", price_per_unit=1)
    # As text, the naive dialog stamp sorts first; as a moment it is later.
    db.create_counter_payout(cid, "2026-11-01T00:00:00+02:00", "2026-11-01T12:00:00+02:00", 1, 1.0, "ILS")
    later_naive = (datetime.datetime(2026, 11, 1, 12, 0).astimezone()
                   + datetime.timedelta(hours=1)).replace(tzinfo=None).isoformat()
    db.create_counter_payout(cid, "2026-11-01T12:00:00+02:00", later_naive, 1, 1.0, "ILS")
    assert db.get_counter_cycle_start(cid) == later_naive


def test_sync_carries_the_link_when_a_payout_is_renumbered():
    from assistant.sync.changelog import FKS
    assert ("counter_presses", "payout_id") in FKS["counter_payouts"]


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
    assert ".onReceive(LocalStore.shared.$counters)" in VIEW          # the tab redraws from it
    # and the button cannot be pressed again on an empty cycle
    assert '.disabled(counter.count == 0)' in VIEW


def test_the_phone_does_not_take_an_older_mac_row_over_a_queued_tap():
    cache = _func(STORE, "func cacheCounters(_ fresh: [TallyCounter], listed: Listed? = nil) {")
    assert '!hasQueuedWrite("/counters", c.id)' in cache
    assert "return LocalStore.shared.preferQueued(items)" in _func(API, "func counters(archived: Bool = false)")
