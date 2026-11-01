"""A timer or counter says which way its money runs: owed to me, or I owe.

Gil, 2026-11-01: "when I create a timer or count … especially if it's
money-wise. It should also be like I owe or I'm owed … for now, it's just I'm
owed." `direction` is 'owed_to_me' (the default, and what every existing row
meant) or 'i_owe'. It changes the words and keeps owed money out of
"earned"; the arithmetic is the same either way.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from assistant.db import DIRECTIONS, SCHEMA_VERSION, CalendarDB  # noqa: E402
from tests.unit._ios_sources import ios_source  # noqa: E402


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


@pytest.mark.parametrize("kind", ["timers", "counters"])
def test_the_api_takes_and_returns_a_direction(client, kind):
    plain = client.post(f"/{kind}", json={"title": "a"}).get_json()
    assert plain["direction"] == "owed_to_me"          # what it always meant

    mine = client.post(f"/{kind}", json={"title": "b", "direction": "i_owe"}).get_json()
    assert mine["direction"] == "i_owe"

    flipped = client.patch(f"/{kind}/{mine['id']}", json={"direction": "owed_to_me"}).get_json()
    assert flipped["direction"] == "owed_to_me"


@pytest.mark.parametrize("kind", ["timers", "counters"])
def test_a_misspelt_direction_is_refused_not_stored(client, kind):
    r = client.post(f"/{kind}", json={"title": "a", "direction": "they_owe"})
    assert r.status_code == 400
    cid = client.post(f"/{kind}", json={"title": "b"}).get_json()["id"]
    assert client.patch(f"/{kind}/{cid}", json={"direction": "nope"}).status_code == 400
    listed = client.get(f"/{kind}?archived=1").get_json()[kind]
    assert {x["direction"] for x in listed} == {"owed_to_me"}


def test_a_file_from_before_reads_as_owed_to_me(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE counters (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, "
                  "price_per_unit REAL NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'ILS', "
                  "color TEXT NOT NULL DEFAULT '#1a6fc4', created_at TEXT NOT NULL, "
                  "archived INTEGER NOT NULL DEFAULT 0)")
        c.execute("INSERT INTO counters (title, price_per_unit, created_at) VALUES ('Carpool', 7.5, '2026-10-01')")
    db = CalendarDB(str(path))
    (row,) = db.get_counters()
    assert (row["title"], row["direction"]) == ("Carpool", "owed_to_me")
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2


def test_the_mac_dialogs_offer_it_and_the_card_says_it(qapp, tmp_path):
    from assistant.calendar_ui import timer_view as tv

    for dialog in (tv.CounterDialog(direction="i_owe"), tv.TimerDialog(direction="i_owe")):
        combo = dialog._direction_combo
        assert [combo.itemData(i) for i in range(combo.count())] == list(DIRECTIONS)
        assert dialog.result_direction == "i_owe"
        combo.setCurrentIndex(0)
        assert dialog.result_direction == "owed_to_me"

    assert tv._money_phrase("₪87.50", "i_owe") == "you owe ₪87.50"
    assert tv._money_phrase("₪87.50", "owed_to_me") == "owed to you ₪87.50"

    db = CalendarDB(str(tmp_path / "c.db"))
    cid = db.create_counter(title="Driver", price_per_unit=10, direction="i_owe")
    db.create_counter_press(cid, delta=2)
    card = tv.CounterCard(next(c for c in db.get_counters() if c["id"] == cid), db)
    card.refresh()
    assert card._payout_lbl.text() == "you owe ₪20.00"


VIEW = ios_source("TimerView.swift")
API = ios_source("APIClient.swift")
STORE = ios_source("LocalStore.swift")


def test_the_phone_offers_it_and_sends_it_everywhere():
    assert 'case id, title, color, currency, archived, running, earnings, direction' in VIEW
    assert 'case id, title, currency, color, archived, count, payout, direction' in VIEW
    assert '[("owed_to_me", "They owe me"), ("i_owe", "I owe them")]' in VIEW
    assert 'Picker("Money", selection: $direction)' in VIEW
    # create and edit, timer and counter: all four send it
    assert VIEW.count('"direction": direction') == 4
    # the words follow it
    assert "TimerFormat.owed(counter.payout, counter.currency, counter.direction)" in VIEW
    assert '" · owed \\(' not in VIEW
    # and a row created with the Mac away keeps it
    assert API.count('direction: body["direction"] as? String') == 2
    assert "direction: String? = nil) -> TallyCounter" in STORE
