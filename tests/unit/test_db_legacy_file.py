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
