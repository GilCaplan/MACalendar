"""Only the store opens calendar.db.

Before 2026-10-30 the calendar action, tag discovery, offline reconciliation,
vocabulary mining, the importer and the engine each opened the store's
connection and wrote their own SQL. A schema change then had to be found in
eight places, and tag discovery created a table of its own that the store's
migrations never knew about. Each of those is a CalendarDB method now. This
test keeps it that way: a module may call `._conn()` only if it IS a store,
meaning it defines its own `_conn` (the command memory, flashcards and Jude
history are separate files with their own).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2] / "assistant"
SKIP = ("experiments", "datasets", "__pycache__")


def test_no_module_outside_a_store_opens_the_calendar_connection():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP for part in path.parts) or ROOT / "db" in path.parents:
            continue
        text = path.read_text()
        if "._conn()" in text and not re.search(r"^\s*def _conn\(", text, re.M):
            offenders.append(str(path.relative_to(ROOT.parent)))
    assert not offenders, (
        "These open the calendar store's connection directly; add a CalendarDB "
        f"method in assistant/db/<area>.py instead: {offenders}")
