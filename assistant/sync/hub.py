"""The hub's half: hand a replica what changed, take what it changed.

The hub is an ordinary MACalendar server — the phone keeps using its REST
routes, unchanged. Its triggers log every write, the phone's included, and a
replica reads that log; a replica's writes come back through `apply_push`
under the replica's name, so the log can skip them on the way out.
"""
from __future__ import annotations

import json
import sqlite3
import time

from assistant.sync import changelog as cl

PAGE = 2000
#: How long the hub keeps its log. A replica away longer re-reads everything.
KEEP_DAYS = 30
#: Where each replica said it can be reached. `_sync` keeps it out of
#: replication, like the log: it is a fact about this hub's replicas.
REPLICAS = "_sync_replicas"
#: A replica not heard from in this long is not offered as a backup.
REPLICA_FRESH_DAYS = 7


def note_replica(conn: sqlite3.Connection, name: str, urls: list[str]) -> None:
    """Remember where `name` is, from its own pull (DEVQA Q96): a phone asks
    the hub for this while the hub is up, and uses that address while it is
    not. A pull with no addresses (an older replica) leaves the record alone."""
    conn.execute(f"CREATE TABLE IF NOT EXISTS {REPLICAS} ("
                 "name TEXT PRIMARY KEY, urls TEXT NOT NULL, seen REAL NOT NULL)")
    if urls:
        conn.execute(f"INSERT INTO {REPLICAS}(name, urls, seen) VALUES (?, ?, ?) "
                     "ON CONFLICT(name) DO UPDATE SET urls = excluded.urls, seen = excluded.seen",
                     (name, json.dumps(urls), time.time()))


def replicas(conn: sqlite3.Connection, now: float | None = None) -> list[dict]:
    """Replicas heard from lately, most recent first."""
    conn.execute(f"CREATE TABLE IF NOT EXISTS {REPLICAS} ("
                 "name TEXT PRIMARY KEY, urls TEXT NOT NULL, seen REAL NOT NULL)")
    cutoff = (now or time.time()) - REPLICA_FRESH_DAYS * 86400
    return [{"name": r["name"], "urls": json.loads(r["urls"]), "seen": r["seen"]}
            for r in conn.execute(f"SELECT * FROM {REPLICAS} WHERE seen >= ? ORDER BY seen DESC", (cutoff,))]


def pull(conn: sqlite3.Connection, since: int | None, replica: str) -> dict:
    """Changes after `since`, newest state of each row, minus the replica's own.

    `since` None (a first sync) or older than the log reaches → a SNAPSHOT:
    every row of every table, and the cursor to continue from."""
    cl.install(conn)
    (low,) = conn.execute(f"SELECT MIN(seq) FROM {cl.LOG}").fetchone()
    (top,) = conn.execute(f"SELECT COALESCE(MAX(seq), 0) FROM {cl.LOG}").fetchone()
    if since is None or (low is not None and since < low - 1):
        tabs = cl.tables(conn)
        return {"snapshot": True, "cursor": top,
                "tables": {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in tabs}}
    tabs = cl.tables(conn)
    rows = conn.execute(
        f"SELECT tbl, rid, MAX(seq) AS seq FROM {cl.LOG} WHERE seq > ? "
        f"GROUP BY tbl, rid ORDER BY seq LIMIT ?", (since, PAGE)).fetchall()
    changes = []
    for r in rows:
        if r["tbl"] not in tabs:
            continue
        (origin,) = conn.execute(f"SELECT origin FROM {cl.LOG} WHERE seq = ?", (r["seq"],)).fetchone()
        if origin == replica:
            continue                                    # its own change, coming back
        changes.append({"t": r["tbl"], "id": r["rid"],
                        "row": cl.row(conn, r["tbl"], tabs[r["tbl"]], r["rid"])})
    cursor = rows[-1]["seq"] if len(rows) == PAGE else top
    return {"snapshot": False, "cursor": cursor, "changes": changes, "more": len(rows) == PAGE}


def apply_push(conn: sqlite3.Connection, replica: str, changes: list) -> dict:
    """Apply a replica's changes, oldest first, in one transaction.

    A row the replica CREATED (`new`) keeps its id when the hub has no such
    row. If the hub does — the phone took that id in the meantime — the row
    gets a fresh id, and `remap` tells the replica to move its copy. A row the
    hub already holds FROM THIS replica is the same row resent (the reply to
    an earlier push was lost), not a collision."""
    cl.install(conn)
    tabs = cl.tables(conn)
    remap: dict[str, dict] = {}
    rejected = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"UPDATE {cl.STATE} SET origin = ?", (replica,))
        for ch in changes:
            t, rid, data = ch.get("t"), ch.get("id"), ch.get("row")
            if t not in tabs:
                rejected.append({"t": t, "id": rid, "error": "unknown table"})
                continue
            pk = tabs[t]
            if data is None:
                conn.execute(f"DELETE FROM {t} WHERE {pk} = ?", (rid,))
                continue
            data = dict(data)
            for child_col_parent in _parents(t):        # follow ids moved earlier in this push
                col, parent = child_col_parent
                moved = remap.get(parent, {}).get(str(data.get(col)))
                if moved is not None:
                    data[col] = moved
            savepoint = "sp"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                if ch.get("new") and cl.row(conn, t, pk, rid) is not None and not _from(conn, t, rid, replica):
                    if isinstance(rid, int):
                        data[pk] = cl.free_id(conn, t, pk)
                        remap.setdefault(t, {})[str(rid)] = data[pk]
                cl.upsert(conn, t, pk, data)
                conn.execute(f"RELEASE {savepoint}")
            except sqlite3.Error as e:
                conn.execute(f"ROLLBACK TO {savepoint}")
                conn.execute(f"RELEASE {savepoint}")
                rejected.append({"t": t, "id": rid, "error": str(e)})
        conn.execute(f"UPDATE {cl.STATE} SET origin = ''")
        conn.execute(f"DELETE FROM {cl.LOG} WHERE at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)",
                     (f"-{KEEP_DAYS} days",))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"remap": remap, "rejected": rejected}


def _parents(table: str) -> list[tuple[str, str]]:
    """(column, parent table) for every id column of `table` that points at a parent."""
    return [(col, parent) for parent, kids in cl.FKS.items() for child, col in kids if child == table]


def _from(conn: sqlite3.Connection, table: str, rid, replica: str) -> bool:
    r = conn.execute(f"SELECT origin FROM {cl.LOG} WHERE tbl = ? AND rid = ? ORDER BY seq DESC LIMIT 1",
                     (table, rid)).fetchone()
    return bool(r) and r["origin"] == replica
