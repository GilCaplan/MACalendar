"""A Mac that keeps its own copy stays in step with the hub (assistant/sync).

2026-10-22: the main server moved to the PC. The phone followed it; the Mac's
window kept writing its own file, so the two drifted — the Mac had a ₪5 carpool
the phone never saw. These drive a REAL hub (the API app, Flask test client)
against a second file, the way the Mac runs it.
"""
from __future__ import annotations

import pytest

from assistant.db import CalendarDB
from assistant.sync import changelog as cl
from assistant.sync.replica import Replica


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "hub.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _transport(client):
    def call(method, path, body):
        r = client.open(path, method=method, json=body)
        assert r.status_code == 200, r.get_json()
        return r.get_json()
    return call


@pytest.fixture
def mac(tmp_path, hub):
    db = CalendarDB(str(tmp_path / "mac.db"))
    return db, Replica(db.path, "mac", _transport(hub))


def _presses(client, cid):
    return client.get(f"/counters/{cid}/presses").get_json()["presses"]


def test_first_sync_sends_what_only_the_mac_has_and_takes_the_rest(hub, mac):
    db, rep = mac
    # The split: both copies start from the same counter and four presses…
    cid = hub.post("/counters", json={"title": "CarPool", "price_per_unit": 7.5}).get_json()["id"]
    for _ in range(4):
        hub.post(f"/counters/{cid}/press", json={"delta": 1})
    rep.reconcile(rep.reconcile_plan(), backup=False)
    assert len(db.get_counter_presses(cid)) == 4
    # …then the Mac's file goes its own way for a while (no sync running).
    cl.connect(db.path).execute(f"UPDATE {cl.STATE} SET cursor = NULL")
    db.create_counter_press(cid, amount=5.0)
    hub.post("/todos", json={"title": "made on the phone"})

    plan = rep.reconcile_plan()
    assert plan["tables"]["counter_presses"]["mac_only"]
    assert plan["tables"]["todos"]["hub_only"]
    rep.reconcile(plan, backup=False)

    presses = _presses(hub, cid)
    assert len(presses) == 5 and [p["amount"] for p in presses].count(5.0) == 1
    assert hub.get("/counters").get_json()["counters"][0]["payout"] == 35.0
    assert any(t["title"] == "made on the phone" for t in db.get_todos(list_name=None))


@pytest.fixture
def synced(hub, mac):
    db, rep = mac
    rep.reconcile(rep.reconcile_plan(), backup=False)
    return hub, db, rep


def test_a_mac_write_reaches_the_hub_and_a_phone_write_reaches_the_mac(synced):
    hub, db, rep = synced
    cid = db.create_counter(title="Laps", price_per_unit=2)
    db.create_counter_press(cid)
    rep.sync()
    assert hub.get("/counters").get_json()["counters"][0]["count"] == 1

    hub.post(f"/counters/{cid}/press", json={"delta": 1, "amount": 3})     # the phone
    rep.sync()
    assert len(db.get_counter_presses(cid)) == 2
    assert rep.pending() == 0


def test_deletes_travel_both_ways(synced):
    hub, db, rep = synced
    a = db.create_counter(title="A")
    b = db.create_counter(title="B")
    rep.sync()
    db.delete_counter(a)
    hub.delete(f"/counters/{b}")
    rep.sync()
    assert hub.get("/counters").get_json()["counters"] == []
    assert db.get_counters() == []


def test_two_new_rows_with_one_id_both_survive_and_children_follow(synced):
    hub, db, rep = synced
    # Offline, the Mac makes a counter and a press; the phone makes a counter
    # on the hub, which takes the same id.
    mine = db.create_counter(title="Mac's")
    db.create_counter_press(mine, amount=4.0)
    theirs = hub.post("/counters", json={"title": "Phone's"}).get_json()["id"]
    assert mine == theirs
    rep.sync()

    titles = {c["title"]: c["id"] for c in hub.get("/counters").get_json()["counters"]}
    assert set(titles) == {"Mac's", "Phone's"}
    assert [p["amount"] for p in _presses(hub, titles["Mac's"])] == [4.0]
    assert _presses(hub, titles["Phone's"]) == []
    local = {c["title"]: c["id"] for c in db.get_counters()}
    assert local == titles                                     # the Mac moved its copy too
    assert len(db.get_counter_presses(titles["Mac's"])) == 1


def test_an_unsent_edit_here_is_not_overwritten_by_the_hubs_older_copy(synced):
    hub, db, rep = synced
    cid = db.create_counter(title="Old")
    rep.sync()
    hub.patch(f"/counters/{cid}", json={"title": "Phone"})
    db.update_counter(cid, title="Mac")
    rep.pull()                                   # the hub's change arrives first
    assert db.get_counters()[0]["title"] == "Mac"
    rep.push()
    assert hub.get("/counters").get_json()["counters"][0]["title"] == "Mac"


def test_what_each_machine_keeps_to_itself_is_not_replicated(synced):
    hub, db, rep = synced
    conn = cl.connect(db.path)
    assert "calendar_sources" not in cl.tables(conn)
    assert "reminder_log" not in cl.tables(conn)
    assert "counters" in cl.tables(conn)


def test_pulled_rows_are_not_sent_back(synced):
    hub, db, rep = synced
    hub.post("/counters", json={"title": "From the phone"})
    rep.pull()
    assert rep.pending() == 0
