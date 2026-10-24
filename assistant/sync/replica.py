"""The replica's half: keep this machine's file in step with the hub.

The file stays the source the window and the engine read and write, so the
Mac works with the hub away. Its triggers queue every local write; `push`
sends them (within a second of the write), `pull` brings the hub's (the
phone's, the PC's) every few seconds. Order matters and is fixed: push, then
pull — a row still waiting to go up is never overwritten by the hub's older
copy of it.

`transport(method, path, body) -> dict` is the only door to the network, so
the tests drive a real hub through Flask's test client.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
from typing import Callable

from assistant.sync import changelog as cl

logger = logging.getLogger(__name__)

Transport = Callable[[str, str, "dict | None"], dict]
BATCH = 500


class Replica:
    def __init__(self, path: str, name: str, transport: Transport):
        self.path = path
        self.name = name
        self.transport = transport

    # ------------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        conn = cl.connect(self.path)
        cl.install(conn)
        return conn

    def cursor(self) -> "int | None":
        conn = self._conn()
        try:
            (c,) = conn.execute(f"SELECT cursor FROM {cl.STATE}").fetchone()
            return c
        finally:
            conn.close()

    def pending(self) -> int:
        conn = self._conn()
        try:
            (n,) = conn.execute(f"SELECT COUNT(DISTINCT tbl || ':' || rid) FROM {cl.LOG} "
                                f"WHERE origin = ''").fetchone()
            return n
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def push(self) -> int:
        """Send what was written here and not yet acknowledged. Returns how many rows."""
        conn = self._conn()
        try:
            tabs = cl.tables(conn)
            rows = conn.execute(
                f"SELECT tbl, rid, MAX(seq) AS seq, MAX(op = 'i') AS new FROM {cl.LOG} "
                f"WHERE origin = '' GROUP BY tbl, rid ORDER BY MIN(seq) LIMIT ?", (BATCH,)).fetchall()
            if not rows:
                return 0
            changes, sent = [], []
            for r in rows:
                sent.append((r["tbl"], r["rid"], r["seq"]))
                if r["tbl"] not in tabs:
                    continue
                data = cl.row(conn, r["tbl"], tabs[r["tbl"]], r["rid"])
                if data is None and r["new"]:
                    continue                    # made and deleted here; the hub never knew
                changes.append({"t": r["tbl"], "id": r["rid"], "row": data, "new": bool(r["new"])})
            reply = self.transport("POST", "/sync/push", {"replica": self.name, "changes": changes}) \
                if changes else {"remap": {}, "rejected": []}
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(f"UPDATE {cl.STATE} SET mute = 1")
                for t, rid, seq in sent:
                    conn.execute(f"DELETE FROM {cl.LOG} WHERE tbl = ? AND rid = ? AND seq <= ? AND origin = ''",
                                 (t, rid, seq))
                for t, moves in (reply.get("remap") or {}).items():
                    for old, new in moves.items():
                        self._move(conn, t, tabs[t], _id(old), new)
                conn.execute(f"UPDATE {cl.STATE} SET mute = 0")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            for rej in reply.get("rejected") or []:
                logger.warning("sync: the hub refused %s %s: %s", rej.get("t"), rej.get("id"), rej.get("error"))
            return len(changes)
        finally:
            conn.close()

    def pull(self) -> int:
        """Bring in the hub's changes. Returns how many rows changed here."""
        n = 0
        while True:
            since = self.cursor()
            q = f"/sync/pull?replica={self.name}" + (f"&since={since}" if since is not None else "")
            reply = self.transport("GET", q, None)
            n += self._apply(reply)
            if not reply.get("more"):
                return n

    def sync(self) -> "tuple[int, int]":
        return self.push(), self.pull()

    # ------------------------------------------------------------------
    def _apply(self, reply: dict) -> int:
        conn = self._conn()
        try:
            tabs = cl.tables(conn)
            pending = {(r["tbl"], r["rid"]): r["new"] for r in conn.execute(
                f"SELECT tbl, rid, MAX(op = 'i') AS new FROM {cl.LOG} WHERE origin = '' GROUP BY tbl, rid")}
            n = 0
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(f"UPDATE {cl.STATE} SET mute = 1")
                if reply.get("snapshot"):
                    incoming = []
                    for t, rows in (reply.get("tables") or {}).items():
                        if t not in tabs:
                            continue
                        pk = tabs[t]
                        keep = {r[pk] for r in rows}
                        for (rid,) in conn.execute(f"SELECT {pk} FROM {t}").fetchall():
                            if rid not in keep and (t, rid) not in pending:
                                conn.execute(f"DELETE FROM {t} WHERE {pk} = ?", (rid,))
                                n += 1
                        incoming += [(t, r[pk], r) for r in rows]
                else:
                    incoming = [(c["t"], c["id"], c["row"]) for c in reply.get("changes") or []
                                if c["t"] in tabs]
                for t, rid, data in incoming:
                    pk = tabs[t]
                    if (t, rid) in pending:
                        if not pending[(t, rid)]:
                            continue            # edited here, not yet pushed: ours goes up next
                        # Created here, and the hub gave the same id to another row.
                        self._move(conn, t, pk, rid, cl.free_id(conn, t, pk) if isinstance(rid, int) else None)
                        pending.pop((t, rid))
                    if data is None:
                        conn.execute(f"DELETE FROM {t} WHERE {pk} = ?", (rid,))
                    else:
                        cl.upsert(conn, t, pk, data)
                    n += 1
                conn.execute(f"UPDATE {cl.STATE} SET mute = 0, cursor = ?", (reply.get("cursor"),))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            return n
        finally:
            conn.close()

    def _move(self, conn: sqlite3.Connection, table: str, pk: str, old, new) -> None:
        """Renumber a row this machine made; whatever already sits at `new`
        (another of our unsent rows) moves out of the way first."""
        if new is None or old == new:
            return
        if cl.row(conn, table, pk, new) is not None:
            self._move(conn, table, pk, new, cl.free_id(conn, table, pk))
        cl.renumber(conn, table, pk, old, new)

    # ------------------------------------------------------------------
    def reconcile_plan(self) -> dict:
        """First sync of a file that already has a life of its own: compare it
        with the hub's and say, per table, what each side has that the other lacks."""
        snap = self.transport("GET", f"/sync/pull?replica={self.name}", None)
        conn = self._conn()
        try:
            tabs = cl.tables(conn)
            plan = {"snapshot": snap, "tables": {}}
            for t, pk in tabs.items():
                hub_rows = {r[pk]: r for r in snap["tables"].get(t, [])}
                tokens = {r.get("client_token"): r[pk] for r in hub_rows.values() if r.get("client_token")}
                same = 0
                push, take, collide, edited = [], [], [], []
                local = {r[pk]: dict(r) for r in conn.execute(f"SELECT * FROM {t}")}
                for rid, mine in local.items():
                    theirs = hub_rows.get(rid)
                    if mine.get("client_token") and tokens.get(mine["client_token"]) not in (None, rid):
                        edited.append(rid)          # one row under two ids: the hub's wins
                    elif theirs is None:
                        push.append(rid)
                    elif _same(mine, theirs):
                        same += 1
                    elif _created(mine) and _created(theirs) and _created(mine) != _created(theirs):
                        collide.append(rid)         # two different rows that took the same id
                    else:
                        edited.append(rid)          # one row, changed on both: the hub's wins
                take = [rid for rid in hub_rows if rid not in local]
                if push or take or collide or edited:
                    plan["tables"][t] = {"same": same, "mac_only": push, "hub_only": take,
                                         "different_rows_same_id": collide, "edited_both": edited}
            return plan
        finally:
            conn.close()

    def reconcile(self, plan: dict, backup: bool = True) -> None:
        """Send what only this machine has (and rows that only share an id),
        then become an exact copy of the hub."""
        if backup:
            shutil.copy2(self.path, self.path + time.strftime(".bak-sync-%Y%m%d-%H%M%S"))
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"DELETE FROM {cl.LOG} WHERE origin = ''")
            for t, p in plan["tables"].items():
                for rid in p["mac_only"] + p["different_rows_same_id"]:
                    conn.execute(f"INSERT INTO {cl.LOG}(tbl, rid, op) VALUES (?, ?, 'i')", (t, rid))
            conn.execute(f"UPDATE {cl.STATE} SET cursor = NULL")
            conn.execute("COMMIT")
        finally:
            conn.close()
        while self.push():
            pass
        # Nothing is pending now, so the snapshot replaces every row it names.
        self.pull()


def _id(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def _same(a: dict, b: dict) -> bool:
    return all(a[k] == b[k] for k in a.keys() & b.keys())


def _created(r: dict):
    return r.get("created_at") or r.get("pressed_at") or r.get("start_time")


# ----------------------------------------------------------------------
# The background loop, started by the API server when `sync.hub` is set.
# ----------------------------------------------------------------------

THREAD_NAME = "macalendar-replica-sync"
_started = False
_lock = threading.Lock()
status: dict = {"hub": "", "ok": None, "last_ok": None, "error": "", "pending": 0}


def http_transport(hub: str, api_key: str = "", timeout: float = 10) -> Transport:
    import requests
    base = hub.rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    headers = {"X-API-Key": api_key} if api_key else {}

    def call(method: str, path: str, body: "dict | None") -> dict:
        r = requests.request(method, base + path, json=body, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    return call


def start_background(cfg) -> bool:
    """Run push/pull forever for the calendar this process serves by default.

    Started whether or not `sync.hub` is set: it idles until it is, and the
    config is re-read every tick, so pointing a machine at a hub (or back)
    needs no restart."""
    global _started
    with _lock:
        if _started:
            return False
        _started = True

    def _loop() -> None:
        from assistant.config import load_config
        from assistant.db import get_db
        import socket
        backoff, last_pull = 1.0, 0.0
        while True:
            c = load_config()
            if not c.sync.hub:
                time.sleep(5)
                continue
            rep = Replica(get_db().path, c.sync.replica_name or socket.gethostname(),
                          http_transport(c.sync.hub, c.sync.api_key))
            status["hub"] = c.sync.hub
            try:
                if rep.cursor() is None:
                    # Never synced: do not guess. `python -m assistant.sync reconcile`
                    # shows the merge and makes it; until then nothing moves.
                    status.update(ok=False, error="first sync not done — run `python -m assistant.sync reconcile`")
                    time.sleep(30)
                    continue
                pushed = rep.push() if rep.pending() else 0
                if pushed or time.time() - last_pull >= c.sync.pull_seconds:
                    rep.pull()
                    last_pull = time.time()
                if not status.get("ok"):
                    logger.info("sync: in step with %s", c.sync.hub)
                status.update(ok=True, last_ok=time.time(), error="", pending=rep.pending())
                backoff = 1.0
                time.sleep(1.0)
            except Exception as e:  # noqa: BLE001 — the loop must outlive the hub being away
                if status.get("ok") is not False or status.get("error") != str(e)[:200]:
                    logger.warning("sync: hub %s unreachable (%s) — working from this Mac's copy", c.sync.hub, e)
                status.update(ok=False, error=str(e)[:200])
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    threading.Thread(target=_loop, daemon=True, name=THREAD_NAME).start()
    if cfg.sync.hub:
        logger.info("Replica sync started → %s", cfg.sync.hub)
    return True
