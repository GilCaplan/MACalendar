"""The change log every replicated table writes into, by trigger.

One mechanism serves both roles (ARCHITECTURE.md):

- on the HUB it is the feed replicas pull from — `seq` is the cursor, and
  `origin` says which replica a change came from so it is not sent back;
- on a REPLICA it is the outbox — every local write lands here until the hub
  has acknowledged it.

Triggers, not wrappers around `CalendarDB`'s 49 write methods: a trigger sees
every write to the file — the window, the voice engine, a series regenerated,
a cascade — from any process, and a method added next month is covered on
the day it is written. The log is STATE-based: a row says "(table, id)
changed", and whoever reads it reads the row as it is NOW (gone = deleted).
"""
from __future__ import annotations

import sqlite3

LOG = "_sync_log"
STATE = "_sync_state"

#: Per machine, never replicated: calendar-account sign-ins and their delete
#: ledger (each server would import the same Google events twice), and the
#: reminders this machine has already shown.
EXCLUDED = frozenset({"calendar_sources", "calendar_sync_deletes", "reminder_log"})

#: Integer ids other rows point at: when a replica's new row must take another
#: id (the hub gave that one to the phone meanwhile), these columns follow it.
FKS: dict[str, list[tuple[str, str]]] = {
    "events": [("events", "series_id"), ("todos", "source_event_id"),
               ("todos", "linked_event_id"), ("assignments", "calendar_event_id"),
               ("workout_plan_items", "event_id"), ("reminder_log", "event_id")],
    "todos": [("subtasks", "todo_id")],
    "timers": [("timer_sessions", "timer_id")],
    "courses": [("assignments", "course_id")],
    "counters": [("counter_presses", "counter_id"), ("counter_payouts", "counter_id")],
}


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def tables(conn: sqlite3.Connection) -> dict[str, str]:
    """Every replicated table → its primary-key column."""
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if name.startswith(("sqlite_", "_sync")) or name in EXCLUDED:
            continue
        pks = [r["name"] for r in conn.execute(f"PRAGMA table_info({name})") if r["pk"]]
        if len(pks) == 1:
            out[name] = pks[0]
    return out


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def install(conn: sqlite3.Connection) -> None:
    """Create the log, the state row and the triggers. Idempotent, so it runs
    on every start: a table added by a later release gets its triggers then."""
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {LOG} (
        seq    INTEGER PRIMARY KEY AUTOINCREMENT,
        tbl    TEXT NOT NULL,
        rid    NOT NULL,
        op     TEXT NOT NULL,          -- i insert, u update, d delete
        origin TEXT NOT NULL DEFAULT '',
        at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx{LOG}_row ON {LOG}(tbl, rid)")
    # mute=1 while a replica applies what it pulled (so it is not pushed back);
    # origin = the replica whose push the hub is applying. Both are set and
    # reset inside ONE write transaction, so no other connection ever sees them.
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {STATE} (
        k      INTEGER PRIMARY KEY CHECK (k = 1),
        mute   INTEGER NOT NULL DEFAULT 0,
        origin TEXT NOT NULL DEFAULT '',
        cursor INTEGER)""")
    conn.execute(f"INSERT OR IGNORE INTO {STATE}(k) VALUES (1)")
    when = f"WHEN (SELECT mute FROM {STATE}) = 0"
    origin = f"(SELECT origin FROM {STATE})"
    for t, pk in tables(conn).items():
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS _sync_{t}_i AFTER INSERT ON {t} {when}
            BEGIN INSERT INTO {LOG}(tbl, rid, op, origin) VALUES ('{t}', NEW.{pk}, 'i', {origin}); END""")
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS _sync_{t}_u AFTER UPDATE ON {t} {when}
            BEGIN
              INSERT INTO {LOG}(tbl, rid, op, origin)
                SELECT '{t}', OLD.{pk}, 'd', {origin} WHERE OLD.{pk} IS NOT NEW.{pk};
              INSERT INTO {LOG}(tbl, rid, op, origin) VALUES ('{t}', NEW.{pk}, 'u', {origin});
            END""")
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS _sync_{t}_d AFTER DELETE ON {t} {when}
            BEGIN INSERT INTO {LOG}(tbl, rid, op, origin) VALUES ('{t}', OLD.{pk}, 'd', {origin}); END""")


def row(conn: sqlite3.Connection, table: str, pk: str, rid) -> dict | None:
    r = conn.execute(f"SELECT * FROM {table} WHERE {pk} = ?", (rid,)).fetchone()
    return dict(r) if r else None


def upsert(conn: sqlite3.Connection, table: str, pk: str, data: dict) -> None:
    """Write `data` as the row, keeping only the columns this file has (the
    two machines may be a release apart)."""
    have = set(columns(conn, table))
    cols = [c for c in data if c in have]
    if pk not in cols:
        raise ValueError(f"{table}: row has no {pk}")
    sets = ", ".join(f"{c} = excluded.{c}" for c in cols if c != pk)
    conflict = f"DO UPDATE SET {sets}" if sets else "DO NOTHING"
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                 f"ON CONFLICT({pk}) {conflict}", [data[c] for c in cols])


def renumber(conn: sqlite3.Connection, table: str, pk: str, old, new) -> None:
    """Move row `old` to id `new`, and every row pointing at it with it."""
    conn.execute(f"UPDATE {table} SET {pk} = ? WHERE {pk} = ?", (new, old))
    have = {name for name in tables(conn)} | set(EXCLUDED)
    for child, col in FKS.get(table, []):
        if child in have and col in columns(conn, child):
            conn.execute(f"UPDATE {child} SET {col} = ? WHERE {col} = ?", (new, old))
    conn.execute(f"UPDATE {LOG} SET rid = ? WHERE tbl = ? AND rid = ? AND origin = ''", (new, table, old))


def free_id(conn: sqlite3.Connection, table: str, pk: str) -> int:
    (top,) = conn.execute(f"SELECT COALESCE(MAX({pk}), 0) FROM {table}").fetchone()
    return int(top) + 1
