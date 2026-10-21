"""Jude's conversations, kept on OUR side: `jude_chats.db`.

Jude keeps its own `chat_history.json`, and it was not enough to rely on. It
saves a turn only when IT wrote an answer and the stream ran to the end — so a
clarification, a "sources" request (which is how the phone asks when it writes
the answer itself), or a stream cut short all left a chat with a title and no
messages. History then opened onto an empty page, and a follow-up had no
conversation to follow (Gil, 2026-10-20: "it doesn't allow me to go back and
see the results and chat").

So every turn is recorded HERE as it passes through `/jude/chat`, whatever
wrote the answer, and both clients read history from here — Jude's own file is
the fallback for chats from before this store existed. We never edit Jude
(`assistant/integrations/CONVENTION.md`); this is the integration keeping its
own record of what it proxied.

One SQLite file per user (`jude_chats.db`, override `MACALENDAR_JUDE_CHATS`),
resolved like every personal store — it lives in `~/.assistant_tools`, never
in the checkout. What you asked Jude is yours.

    chats  id (Jude's chat id) · title · mode · created_at · updated_at
    turns  chat_id · question · answer · sources (JSON) · mode · kind · by

`kind` is "answer", "clarification", "followup" (answered from the chat's
own sources, no new search — `followup.py`) or "incomplete" (the stream ended
in an error or the client left before `done`: shown in History, never fed to
a follow-up as if it were finished); `by` is "mac" or "phone".

A chat Jude already kept is ADOPTED — its messages copied in — before the
first new turn lands in it (`adopt`), or History would show only the turns
recorded since. A deleted chat is remembered in `hidden`, so a copy Jude
failed to forget cannot come back through the fallback.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from contextlib import contextmanager

DEFAULT_PATH = os.path.expanduser("~/.assistant_tools/jude_chats.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    mode        TEXT NOT NULL DEFAULT 'qa',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    question    TEXT NOT NULL DEFAULT '',
    answer      TEXT NOT NULL DEFAULT '',
    sources     TEXT NOT NULL DEFAULT '[]',
    mode        TEXT NOT NULL DEFAULT 'qa',
    kind        TEXT NOT NULL DEFAULT 'answer',
    by          TEXT NOT NULL DEFAULT 'mac',
    extra       TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_by_chat ON turns(chat_id, id);
CREATE TABLE IF NOT EXISTS hidden (
    id          TEXT PRIMARY KEY,
    deleted_at  TEXT NOT NULL
);
"""

#: The kinds a follow-up may be shown as earlier conversation.
ANSWERED = ("answer", "followup")

#: How many earlier turns a follow-up is shown. Enough to resolve "it" and
#: "that opinion"; few enough that a long chat does not crowd out the sources.
WINDOW = 6


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class JudeHistory:
    def __init__(self, path: "str | None" = None) -> None:
        if path is None:
            from assistant.users import paths as _paths
            path = _paths.resolve(os.environ.get("MACALENDAR_JUDE_CHATS") or DEFAULT_PATH)
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
            # `extra` came a day after the table: a clarification's options
            # are {label, prompt} pairs, and the prompt is what a tap asks.
            cols = {r["name"] for r in c.execute("PRAGMA table_info(turns)")}
            if "extra" not in cols:
                c.execute("ALTER TABLE turns ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- writing -------------------------------------------------------------

    def record(self, chat_id: str, question: str, answer: str = "", *,
               sources: "list | None" = None, mode: str = "qa",
               kind: str = "answer", by: str = "mac", extra: "dict | None" = None) -> int:
        """One turn. Creates the chat on its first turn, titled by the question."""
        if not chat_id:
            raise ValueError("a turn needs the chat it belongs to")
        now = _now()
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO chats (id, title, mode, created_at, updated_at) "
                      "VALUES (?, ?, ?, ?, ?)", (chat_id, question.strip()[:55], mode, now, now))
            c.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
            cur = c.execute(
                "INSERT INTO turns (chat_id, question, answer, sources, mode, kind, by, extra, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, question, answer, json.dumps(sources or [], ensure_ascii=False),
                 mode, kind, by, json.dumps(extra or {}, ensure_ascii=False), now))
            return int(cur.lastrowid)

    def fill_answer(self, chat_id: str, question: str, answer: str, by: str = "phone", *,
                    sources: "list | None" = None, mode: str = "qa", kind: str = "answer") -> bool:
        """The answer a client wrote ITSELF, onto the turn that fetched its sources.

        The phone asks the Mac for sources only and writes the answer with its
        own model, so the turn recorded in passing has sources and no answer.
        The latest unanswered turn with that question gets it; failing that
        (the stream was never recorded) a new turn is made so nothing is lost.
        """
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM turns WHERE chat_id = ? AND question = ? AND answer = '' "
                "ORDER BY id DESC LIMIT 1", (chat_id, question)).fetchone()
            if row:
                # The row was recorded as a "sources" request; what was ASKED
                # is the mode the phone answered in.
                c.execute("UPDATE turns SET answer = ?, by = ?, mode = ?, kind = ? WHERE id = ?",
                          (answer, by, mode, kind, row["id"]))
                c.execute("UPDATE chats SET updated_at = ?, mode = CASE WHEN mode = 'sources' "
                          "THEN ? ELSE mode END WHERE id = ?", (_now(), mode, chat_id))
                return True
        # Never seen by the Mac (a follow-up the phone answered from the
        # sources it already had): keep it whole, sources and all.
        self.record(chat_id, question, answer, sources=sources, mode=mode, kind=kind, by=by)
        return False

    def delete(self, chat_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            c.execute("INSERT OR REPLACE INTO hidden (id, deleted_at) VALUES (?, ?)", (chat_id, _now()))

    def is_hidden(self, chat_id: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM hidden WHERE id = ?", (chat_id,)).fetchone() is not None

    def hidden_ids(self) -> set:
        with self._conn() as c:
            return {r["id"] for r in c.execute("SELECT id FROM hidden")}

    def adopt(self, chat_id: str, messages: list, *, title: str = "", mode: str = "qa",
              created_at: str = "") -> int:
        """Copy a chat Jude kept into this store, once, before it gains a new turn.

        `messages` is Jude's `/history` shape. A chat already here, or deleted
        here, is left alone. One transaction — a crash halfway must not leave
        half a chat that `has()` then treats as the whole one — keeping Jude's
        title and creation time rather than stamping it as made now. Returns
        how many turns were copied.
        """
        if not chat_id or self.has(chat_id) or self.is_hidden(chat_id):
            return 0
        rows, pending = [], None
        for m in messages or []:
            if not isinstance(m, dict):
                continue
            if m.get("role") == "user":
                if pending is not None:
                    rows.append((pending, "", [], "incomplete"))
                pending = str(m.get("content") or "")
            else:
                rows.append((pending or "", str(m.get("content") or ""), m.get("sources") or [], "answer"))
                pending = None
        if pending is not None:
            rows.append((pending, "", [], "incomplete"))
        if not rows:
            return 0
        when = created_at or _now()
        name = (title or rows[0][0]).strip()[:55]
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO chats (id, title, mode, created_at, updated_at) "
                      "VALUES (?, ?, ?, ?, ?)", (chat_id, name, mode, when, when))
            c.executemany(
                "INSERT INTO turns (chat_id, question, answer, sources, mode, kind, by, extra, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'mac', '{}', ?)",
                [(chat_id, q, a, json.dumps(src, ensure_ascii=False), mode, k, when) for q, a, src, k in rows])
        return len(rows)

    def changed_since(self, since: str = "") -> list:
        """Every chat updated after `since` (ISO time; "" = all), with its
        messages — what the phone's copy needs to catch up in one call."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM chats WHERE updated_at > ? ORDER BY updated_at",
                             (since or "",)).fetchall()
        return [{"id": r["id"], "title": r["title"], "mode": r["mode"], "created_at": r["created_at"],
                 "updated_at": r["updated_at"], "messages": self.messages(r["id"])} for r in rows]

    # -- reading -------------------------------------------------------------

    def chats(self) -> list:
        """Newest first, in Jude's own `/api/chats` shape so a client cannot tell."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM chats ORDER BY updated_at DESC").fetchall()
        return [{"id": r["id"], "title": r["title"], "mode": r["mode"],
                 "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]

    def has(self, chat_id: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM turns WHERE chat_id = ? LIMIT 1",
                             (chat_id,)).fetchone() is not None

    def turns(self, chat_id: str) -> list:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM turns WHERE chat_id = ? ORDER BY id",
                             (chat_id,)).fetchall()
        return [dict(r, sources=json.loads(r["sources"] or "[]"),
                     extra=json.loads(r["extra"] or "{}")) for r in rows]

    def messages(self, chat_id: str) -> list:
        """Jude's `/history` shape — user and assistant alternating, oldest first.

        An assistant message carries `kind` and `by` as well; clients that do
        not know them ignore them.
        """
        out = []
        for t in self.turns(chat_id):
            if t["question"]:
                out.append({"role": "user", "content": t["question"]})
            msg = {"role": "assistant", "content": t["answer"], "sources": t["sources"],
                   "kind": t["kind"], "by": t["by"], "mode": t["mode"]}
            if t["extra"].get("clarification"):
                msg["clarification"] = t["extra"]["clarification"]
            out.append(msg)
        return out

    def last_sources(self, chat_id: str) -> list:
        """The sources the conversation is about — the latest turn that found any."""
        with self._conn() as c:
            for r in c.execute("SELECT sources FROM turns WHERE chat_id = ? ORDER BY id DESC",
                               (chat_id,)):
                s = json.loads(r["sources"] or "[]")
                if s:
                    return s
        return []

    def latest_kind(self, chat_id: str) -> str:
        with self._conn() as c:
            r = c.execute("SELECT kind FROM turns WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                          (chat_id,)).fetchone()
        return r["kind"] if r else ""

    def window(self, chat_id: str, n: int = WINDOW) -> list:
        """The last `n` finished answers, oldest first — what a follow-up is shown.
        A clarification or a cut-off answer is not something to follow up on."""
        answered = [t for t in self.turns(chat_id) if t["answer"] and t["kind"] in ANSWERED]
        return answered[-n:]
