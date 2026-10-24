"""A counter press can be worth something other than the counter's price.

A carpool counter costs 7.5 a ride, but one ride cost 5. Until 2026-10-22 the
payout was `count × price_per_unit`, so the only way to log that ride was to
log it wrong. A press now carries an optional `amount`; NULL keeps meaning
"the counter's price", read when the total is computed, so changing the rate
still reprices every ordinary press as before.
"""
from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest                      # noqa: E402
from PyQt6.QtWidgets import QApplication            # noqa: E402

from assistant.calendar_ui import timer_view as tv  # noqa: E402
from assistant.db import CalendarDB, counter_press_amount  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_a_press_is_its_own_amount_or_the_price():
    assert counter_press_amount({"delta": 1, "amount": None}, 7.5) == 7.5
    assert counter_press_amount({"delta": 1, "amount": 5.0}, 7.5) == 5.0
    assert counter_press_amount({"delta": -1, "amount": 5.0}, 7.5) == -5.0
    assert counter_press_amount({"delta": -1}, 7.5) == -7.5


def test_the_api_payout_adds_up_each_press(client):
    cid = client.post("/counters", json={"title": "Carpool", "price_per_unit": 7.5}).get_json()["id"]
    client.post(f"/counters/{cid}/press", json={"delta": 1})
    client.post(f"/counters/{cid}/press", json={"delta": 1})
    body = client.post(f"/counters/{cid}/press", json={"delta": 1, "amount": 5}).get_json()
    assert body["count"] == 3
    assert body["payout"] == 20.0
    # Cash out banks that figure, not 3 × 7.5.
    client.post(f"/counters/{cid}/cashout", json={})
    payouts = client.get(f"/counters/{cid}/payouts").get_json()["payouts"]
    assert payouts[0]["amount"] == 20.0


def test_an_old_database_gains_the_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE counter_presses (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "counter_id INTEGER NOT NULL, delta INTEGER NOT NULL DEFAULT 1, "
                     "label TEXT NOT NULL DEFAULT '', pressed_at TEXT NOT NULL, created_at TEXT NOT NULL)")
    db = CalendarDB(str(path))
    cid = db.create_counter(title="Carpool", price_per_unit=7.5)
    db.create_counter_press(cid, amount=5.0)
    assert db.get_counter_presses(cid)[0]["amount"] == 5.0


def test_the_mac_button_asks_and_adds_that_amount(qapp, tmp_path, monkeypatch):
    db = CalendarDB(str(tmp_path / "cal.db"))
    cid = db.create_counter(title="Carpool", price_per_unit=7.5)
    db.create_counter_press(cid)
    view = tv.TimerView(db)
    card = view._counter_cards[cid]
    from PyQt6.QtWidgets import QInputDialog
    asked = {}

    def fake_get_double(parent, title, label, value, *a, **k):
        asked["default"] = value
        return 5.0, True
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(fake_get_double))

    QTest.mouseClick(card._plus_amount_btn, Qt.MouseButton.LeftButton)

    assert asked["default"] == 7.5                  # opens on the usual price
    assert card.current_count() == 2
    assert card._payout_lbl.text() == "₪12.50"
    assert db.get_counter_presses(cid)[-1]["amount"] == 5.0
