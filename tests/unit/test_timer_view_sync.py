"""A timer or counter changed on the PHONE shows on the Mac's tab.

The tab's reload added and removed cards only: a card that stayed kept its old
row and its cached sessions/presses, so a start, stop, rename or press made on
the phone never reached it until a restart (2026-10-21 audit).
"""
from __future__ import annotations

import datetime
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication            # noqa: E402

from assistant.calendar_ui import timer_view as tv  # noqa: E402
from assistant.db import CalendarDB                 # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_an_existing_timer_card_takes_the_phones_changes(qapp, tmp_path):
    db = CalendarDB(str(tmp_path / "cal.db"))
    tid = db.create_timer(title="Client A", timer_type="work", hourly_rate=100.0, currency="ILS")
    view = tv.TimerView(db)
    card = view._cards[tid]
    card.tick()
    assert card._cached_sessions == []
    # The phone renames it and starts a session, straight into the DB.
    db.update_timer(tid, title="Client B")
    start = (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=5)).isoformat()
    db.create_timer_session(tid, start_time=start)
    view._reload_timers()
    assert view._cards[tid] is card                      # same card, not rebuilt
    assert card._timer["title"] == "Client B"
    assert len(card._cached_sessions) == 1


def test_an_existing_counter_card_takes_the_phones_presses(qapp, tmp_path):
    db = CalendarDB(str(tmp_path / "cal.db"))
    cid = db.create_counter(title="Cups")
    view = tv.TimerView(db)
    card = view._counter_cards[cid]
    before = card.current_count()
    db.create_counter_press(cid)
    view._reload_counters()
    assert view._counter_cards[cid] is card
    assert card.current_count() == before + 1
