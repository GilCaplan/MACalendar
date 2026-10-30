"""Check a real calendar.db against this code, on a COPY.

    python -m assistant.db.verify            # the admin's own calendar.db
    python -m assistant.db.verify PATH       # any calendar file

Run it after pulling a change to the store (the per-area split, 2026-10-30)
and before restarting the apps. It copies the file with SQLite's backup API,
so a running API mid-write cannot hand it a torn copy, and the original is
only ever read. It then opens the copy with this code, which runs the
migrations as a restart would, and compares every row of every table before
and after. Exit status 0 means nothing was lost or changed; 1 lists what was.
A new table or a new column is expected, not a loss.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from contextlib import closing

from assistant.db.schema import _LEGACY_LINK_SOURCE


def _rows(path: str) -> dict[str, list[dict]]:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                for t in tables}


def _expected(table: str, old: dict, column: str, new) -> bool:
    """A change the store makes on purpose every time it opens a file
    (`base.StoreBase`), so finding it is not a loss."""
    if table == "events" and column == "category":
        return old.get("category") in ("Running", "Gym") and new == "Fitness"   # _migrate
    if table == "todos" and column in ("source", "source_event_id", "linked_event_id"):
        return old.get("source") == _LEGACY_LINK_SOURCE                        # _migrate_links
    return False


def compare(before: dict, after: dict) -> list[str]:
    """What the migrated copy lost or changed, one line each. New tables, new
    columns, the built-in tags seeded into an empty palette, and the store's
    own open-time rewrites are expected and not reported."""
    problems = []
    for table, rows in before.items():
        if table not in after:
            problems.append(f"{table}: table missing after opening")
            continue
        now = after[table]
        if table == "todo_tags" and not rows:
            continue                                     # _seed_default_tags
        if len(now) != len(rows):
            problems.append(f"{table}: {len(rows)} rows became {len(now)}")
            continue
        for old, new in zip(rows, now):
            changed = sorted(k for k, v in old.items()
                             if new.get(k) != v and not _expected(table, old, k, new.get(k)))
            if changed:
                problems.append(f"{table} row {old.get('id', '?')}: {', '.join(changed)} changed")
    return problems


def verify(path: str) -> int:
    from assistant.db import SCHEMA_VERSION, CalendarDB

    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, "calendar.db")
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as src, \
                closing(sqlite3.connect(copy)) as dst:
            src.backup(dst)
        before = _rows(copy)
        CalendarDB(copy)                          # migrations, as a restart would run them
        after = _rows(copy)
    problems = compare(before, after)
    n = sum(len(v) for v in before.values())
    print(f"{path}: {len(before)} tables, {n} rows checked on a copy "
          f"(schema now {SCHEMA_VERSION}).")
    added = sorted(set(after) - set(before))
    if added:
        print(f"  new tables (expected): {', '.join(added)}")
    for line in problems:
        print(f"  LOST OR CHANGED: {line}")
    print("  OK: every row reads back unchanged." if not problems else
          "  NOT OK: do not restart the apps on this code; keep the old checkout.")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        path = argv[0]
    else:
        from assistant.users.paths import personal_store
        path = personal_store("calendar.db")
    if not os.path.exists(path):
        print(f"No calendar file at {path}")
        return 1
    return verify(path)


if __name__ == "__main__":
    raise SystemExit(main())
