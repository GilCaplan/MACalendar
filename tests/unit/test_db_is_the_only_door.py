"""Only the store opens calendar.db.

Before 2026-10-30 the calendar action, tag discovery, offline reconciliation,
vocabulary mining, the importer, the engine and the doctor each opened the
calendar file and wrote their own SQL. A schema change then had to be found
in all of them, and tag discovery created a table of its own that the
store's migrations never knew about. Each of those is a CalendarDB method
now. This test keeps it that way: outside `assistant/db/`, a module may open
a SQLite connection only if it is listed below, with the reason.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2] / "assistant"
SKIP = ("experiments", "datasets", "__pycache__")

#: Modules that open SQLite themselves, and why that is not the calendar
#: store's business.
ALLOWED = {
    # Separate stores, each its own file with its own schema and _conn().
    "assistant/intent/memory.py": "the command memory (memory.db)",
    "assistant/features/flashcards/store.py": "the flashcard decks (their own file)",
    "assistant/jude/history.py": "Jude's chat history (its own file)",
    # Replication copies rows of every table without knowing their schema.
    "assistant/sync/changelog.py": "sync: the change log and triggers",
    "assistant/sync/replica.py": "sync: applying the hub's rows",
    "assistant/sync/routes.py": "sync: serving the change log",
    # Whole-file tools.
    "assistant/users/migrate.py": "moving each user's files into users/<uid>/",
    "assistant/calendar_ui/importer.py": "reading ANOTHER app's calendar file to import from",
}

OPENS = re.compile(r"sqlite3\.connect\(|\._conn\(\)|\bcl\.connect\(")


def test_no_module_outside_the_store_opens_a_database_unless_listed():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP for part in path.parts) or ROOT / "db" in path.parents:
            continue
        rel = str(path.relative_to(ROOT.parent))
        if OPENS.search(path.read_text()) and rel not in ALLOWED:
            offenders.append(rel)
    assert not offenders, (
        "These open a database themselves. For calendar data, add a CalendarDB "
        "method in assistant/db/<area>.py; for a new store of its own, list it "
        f"in ALLOWED with the reason: {offenders}")


def test_the_allowlist_has_no_stale_entries():
    for rel in ALLOWED:
        path = ROOT.parent / rel
        assert path.exists() and OPENS.search(path.read_text()), (
            f"{rel} no longer opens a database; drop it from ALLOWED")
