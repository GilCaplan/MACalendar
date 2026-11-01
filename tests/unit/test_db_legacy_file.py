"""A calendar file written before the per-area split opens and reads unchanged.

`tests/fixtures/db/legacy_calendar.db` was written by the single-file
CalendarDB (main d2bc2ae1, 2026-10-30), with data in all 22 tables, and
`legacy_calendar.rows.json` is every row it held. Today's code must open a
copy, run its migrations, and still hold every one of those rows,
value for value. That is the guarantee that Gil's real calendar.db survives
the move without a conversion step (Gil: "make sure previous data can be
moved properly").
"""
import json
import shutil
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "db"


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / "calendar.db"
    shutil.copy(FIX / "legacy_calendar.db", path)
    return path


def _dump(path):
    import sys
    sys.path.insert(0, str(FIX))
    from build_legacy_db import dump
    return dump(path)


def test_every_row_written_before_the_split_reads_back_unchanged(legacy):
    from assistant.db import CalendarDB
    before = json.loads((FIX / "legacy_calendar.rows.json").read_text())
    CalendarDB(str(legacy))                       # opens and migrates
    after = _dump(legacy)
    assert set(before) <= set(after), f"tables lost: {set(before) - set(after)}"
    for table, rows in before.items():
        assert len(after[table]) == len(rows), f"{table}: {len(rows)} rows became {len(after[table])}"
        for old, new in zip(rows, after[table]):
            changed = {k: (v, new.get(k)) for k, v in old.items() if json.loads(json.dumps(new.get(k), default=str)) != v}
            assert not changed, f"{table} row {old.get('id')}: {changed}"


def test_opening_it_twice_changes_nothing(legacy):
    from assistant.db import CalendarDB
    CalendarDB(str(legacy))
    first = _dump(legacy)
    CalendarDB(str(legacy))
    assert _dump(legacy) == first


def test_the_store_reads_the_old_file_through_its_own_calls(legacy):
    import datetime

    from assistant.db import CalendarDB
    db = CalendarDB(str(legacy))
    day = datetime.date(2026, 10, 30)
    titles = {e["title"] for e in db.get_events_for_day(day)}
    assert {"Dentist", "Run"} <= titles
    assert any(t["title"] == "Buy milk" for t in db.get_todos())
    milk = next(t for t in db.get_todos() if t["title"] == "Buy milk")
    assert milk["client_token"] == "tok-1" and milk["tags"] == ["errands"]
    assert db.get_timers() and db.get_counters() and db.get_courses()
    presses = db.get_counter_presses(db.get_counters()[0]["id"])
    assert sorted(presses, key=lambda p: p["pressed_at"])[1].get("amount") == 5.0


def test_the_old_file_is_stamped_with_the_schema_and_gains_the_tag_table(legacy):
    import sqlite3

    from assistant.db import SCHEMA_VERSION, CalendarDB
    with sqlite3.connect(legacy) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 0     # never stamped
    CalendarDB(str(legacy))
    with sqlite3.connect(legacy) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        cols = {r[1] for r in c.execute("PRAGMA table_info(tag_suggestion_state)")}
    assert cols == {"name", "status", "ts", "hidden"}


def test_a_file_from_newer_code_is_opened_with_a_warning_not_rewritten(legacy, caplog):
    import logging
    import sqlite3

    from assistant.db import SCHEMA_VERSION, CalendarDB
    with sqlite3.connect(legacy) as c:
        c.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with caplog.at_level(logging.WARNING, logger="assistant.db.base"):
        CalendarDB(str(legacy))
    assert any("written by newer code" in r.message for r in caplog.records)
    with sqlite3.connect(legacy) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION + 1


def test_the_mac_checker_passes_the_old_file_and_never_writes_it(capsys):
    """`python -m assistant.db.verify` is what the Mac session runs on the
    real calendar.db before restarting the apps; it must work on a copy."""
    import hashlib

    from assistant.db import verify
    src = FIX / "legacy_calendar.db"
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    assert verify.main([str(src)]) == 0
    assert "OK: every row reads back unchanged" in capsys.readouterr().out
    assert hashlib.sha256(src.read_bytes()).hexdigest() == digest   # the original untouched


def test_the_checker_names_what_was_lost():
    from assistant.db.verify import compare
    before = {"events": [{"id": 1, "title": "Dentist"}], "todos": [{"id": 1}]}
    after = {"events": [{"id": 1, "title": "Dentist!"}]}
    assert compare(before, after) == ["events row 1: title changed",
                                      "todos: table missing after opening"]


def test_the_checker_does_not_cry_wolf_at_the_stores_own_rewrites():
    """Opening a file folds Running/Gym into Fitness, moves legacy linked
    to-dos onto linked_event_id, and seeds the built-in tags into an empty
    palette. Each happens on purpose on every open; reporting one as a loss
    would block a healthy rollout (2026-10-30 review)."""
    from assistant.db.verify import compare
    before = {"events": [{"id": 1, "category": "Gym", "title": "Lift"}],
              "todos": [{"id": 1, "source": "linked_event", "source_event_id": 4,
                         "linked_event_id": None}],
              "todo_tags": []}
    after = {"events": [{"id": 1, "category": "Fitness", "title": "Lift"}],
             "todos": [{"id": 1, "source": "manual", "source_event_id": None,
                        "linked_event_id": 4}],
             "todo_tags": [{"name": "work"}, {"name": "home"}]}
    assert compare(before, after) == []
    after["events"][0]["title"] = "Lift!"                 # a real change still shows
    assert compare(before, after) == ["events row 1: title changed"]


def test_the_checker_lets_a_backfill_queue_writes_for_the_hub():
    """Schema 3 backfills `payout_id` on old counter presses, and the sync
    triggers queue each write for the PC hub as they would any other. The
    checker read the grown outbox as a loss and said NOT OK on a healthy
    calendar (2026-11-02). Growth is expected; a queued row that changed or
    vanished is still a loss."""
    from assistant.db.verify import compare
    queued = {"seq": 1, "tbl": "events", "rid": 3, "op": "u"}
    before = {"_sync_log": [queued]}
    after = {"_sync_log": [queued, {"seq": 2, "tbl": "counter_presses", "rid": 7, "op": "u"}]}
    assert compare(before, after) == []
    assert compare(before, {"_sync_log": []}) == ["_sync_log: 1 rows became 0"]
    assert compare(before, {"_sync_log": [{**queued, "rid": 4}]}) == ["_sync_log row ?: rid changed"]
