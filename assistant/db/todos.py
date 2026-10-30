"""To-dos, their tags and subtasks, and the calendar-to-to-do sync."""

from __future__ import annotations

import datetime
import json
import sqlite3
from typing import List, Optional

from assistant.db.common import _memory_feedback, _utcnow_iso


class TodosMixin:
    """To-dos, their tags and subtasks, and the calendar-to-to-do sync."""

    @staticmethod
    def _decode_tags(row: dict) -> dict:
        """Turn the JSON `tags` column into a Python list (in place)."""
        raw = row.get("tags")
        if isinstance(raw, str):
            try:
                wren = json.loads(raw or "[]")
            except ValueError:
                wren = []
            row["tags"] = [str(t) for t in wren] if isinstance(wren, list) else []
        elif raw is None:
            row["tags"] = []
        return row

    @staticmethod
    def _encode_tags(tags) -> str:
        """Normalise a tags value (list / JSON string / comma string) to JSON."""
        if isinstance(tags, str):
            try:
                parsed = json.loads(tags)
                if isinstance(parsed, list):
                    tags = parsed
                else:
                    tags = [tags]
            except ValueError:
                tags = [t for t in tags.split(",")]
        seen: List[str] = []
        for t in tags or []:
            t = str(t).strip()
            if t and t not in seen:
                seen.append(t)
        return json.dumps(seen)

    def search_todos(self, q: str, limit: int = 50) -> List[dict]:
        """Substring match over title/notes; open tasks first, then done."""
        like = f"%{q}%"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM todos WHERE title LIKE ? OR notes LIKE ? "
                "ORDER BY completed, position LIMIT ?",
                (like, like, limit)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Todos: Create
    # ------------------------------------------------------------------

    def _infer_tags(self, title: str) -> List[str]:
        """Tags for a task nobody chose tags for.

        Events have had this since the beginning: `create_event_from_dict` runs
        the classifier itself, so an event is labelled no matter which surface
        made it. Tasks put the same job on every CALLER instead, and the callers
        disagreed — the API and the GUI's quick-add both remembered to infer,
        while calendar sync, the workout planner and the coursework view did
        not, so whether a task got a tag depended on where it came from rather
        than on what it said.

        `None` means "nobody chose"; an empty list means "chosen to be none" —
        which the todo list's Untagged filter relies on, so the two must stay
        distinguishable and only `None` may be filled in here.

        `auto_tags` — the keyword rules, then the learned tagger behind them,
        the same labeller voice and `POST /todos` use, as the event side has
        its model inside `auto_category_and_color`.
        """
        try:
            from assistant.actions.todo.tagging import auto_tags
            try:
                from assistant.config import load_config as _lc
                cfg = _lc("config.yaml")
            except Exception:  # no config: the rules alone, as with labels off
                cfg = None
            return auto_tags(title, [r["name"] for r in self.get_tags()], cfg)
        except Exception:      # labelling is never worth failing a create over
            return []

    def create_todo(
        self,
        title: str,
        list_name: str = "today",
        priority: str = "none",
        due_date: str = "",
        notes: str = "",
        source: str = "manual",
        source_event_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
        quantity: int = 1,
        client_token: str = "",
    ) -> int:
        """Insert a new todo item. Returns the new row id.

        `client_token` is a creation idempotency key (see `_TODO_MIGRATIONS`).
        When a non-empty token has already been stored, the existing row's id is
        returned and nothing is inserted — a replayed create is a no-op rather
        than a second copy of the task.
        """
        token = (client_token or "").strip()
        if token:
            existing = self.get_todo_by_client_token(token)
            if existing is not None:
                return int(existing["id"])
        if tags is None:
            tags = self._infer_tags(title)
        tags_json = self._encode_tags(tags or [])
        new_id: Optional[int] = None
        with self._conn() as conn:
            max_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM todos WHERE list = ?",
                (list_name,),
            ).fetchone()[0]
            try:
                cur = conn.execute(
                    """
                    INSERT INTO todos
                        (title, list, completed, priority, due_date, notes,
                         source, source_event_id, created_at, updated_at, completed_at,
                         position, tags, quantity, client_token)
                    VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                    """,
                    (
                        title,
                        list_name,
                        priority,
                        due_date,
                        notes,
                        source,
                        source_event_id,
                        datetime.datetime.now().isoformat(),
                        _utcnow_iso(),      # a version for clients to quote back
                        max_pos + 1,
                        tags_json,
                        max(1, int(quantity or 1)),
                        token,
                    ),
                )
            except sqlite3.IntegrityError:
                # Two flushes of the same queued create raced past the lookup
                # above; the unique index on client_token is the real referee.
                # Resolve the winner *outside* this connection — reading through
                # a second one while this write transaction is still open can
                # block on the writer's lock.
                if not token:
                    raise
            else:
                new_id = cur.lastrowid
        if new_id is not None:
            return new_id
        existing = self.get_todo_by_client_token(token)
        if existing is None:
            raise sqlite3.IntegrityError(
                "todos.client_token conflict with no matching row")
        return int(existing["id"])

    def find_recent_open_todo(self, title: str, list_name: str,
                              within_seconds: int) -> Optional[dict]:
        """An OPEN todo in `list_name` spelled the same as `title` and created
        less than `within_seconds` ago, or None.

        The content fingerprint behind the token-less half of create
        idempotency. `client_token` is the precise key and is preferred wherever
        a client can mint one; this is the fallback for callers that send none,
        where the only identity a replay carries is what it says. Comparison is
        on case- and whitespace-normalised titles, so "Buy  Groceries" matches
        "buy groceries". Completed rows never match: ticking a task off and
        asking for it again is a new ask, not a replay.
        """
        if within_seconds <= 0:
            return None
        key = " ".join((title or "").split()).lower()
        if not key:
            return None
        cutoff = (datetime.datetime.now()
                  - datetime.timedelta(seconds=within_seconds)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM todos
                 WHERE list = ? AND completed = 0 AND created_at >= ?
                 ORDER BY created_at DESC
                """,
                (list_name, cutoff),
            ).fetchall()
        # Normalising in Python, not SQL: `lower(trim(...))` would still call
        # "buy  groceries" and "buy groceries" different tasks.
        for row in rows:
            if " ".join((row["title"] or "").split()).lower() == key:
                return dict(row)
        return None

    def get_todo_by_client_token(self, client_token: str) -> Optional[dict]:
        """The todo a client already created under this idempotency key, if any."""
        token = (client_token or "").strip()
        if not token:
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM todos WHERE client_token = ?", (token,)
            ).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Todos: Read
    # ------------------------------------------------------------------

    def get_todos(
        self,
        list_name: Optional[str] = None,
        include_completed: bool = False,
        tag: Optional[str] = None,
    ) -> List[dict]:
        """Return todos, optionally filtered by list, completion state and/or tag.

        `tag` matches todos whose JSON tag list contains that name (case-insensitive).
        Pass tag="" / None for no tag filter; tag="__untagged__" for todos with no tags.
        """
        query = "SELECT * FROM todos"
        conditions: List[str] = []
        params: List = []
        if list_name is not None:
            conditions.append("list = ?")
            params.append(list_name)
        if not include_completed:
            conditions.append("completed = 0")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY completed ASC, position ASC, created_at ASC"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        todos = [self._decode_tags(dict(r)) for r in rows]
        if tag:
            if tag == "__untagged__":
                todos = [t for t in todos if not t["tags"]]
            else:
                want = tag.strip().lower()
                todos = [t for t in todos if any(x.lower() == want for x in t["tags"])]
        return todos

    def get_todo(self, todo_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        return self._decode_tags(dict(row)) if row else None

    def get_todos_by_source(
        self, source: str, source_event_id: Optional[int] = None
    ) -> List[dict]:
        if source_event_id is not None:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM todos WHERE source = ? AND source_event_id = ?",
                    (source, source_event_id),
                ).fetchall()
        else:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM todos WHERE source = ?", (source,)
                ).fetchall()
        return [self._decode_tags(dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Todos: Update
    # ------------------------------------------------------------------

    def update_todo(self, todo_id: int, **fields) -> None:
        _memory_feedback("todo", todo_id, "corrected", {k: v for k, v in fields.items() if k in ("title", "list_name", "tags")})
        allowed = {"title", "list", "completed", "priority", "due_date", "notes", "completed_at", "attachments", "tags", "quantity"}
        if "list_name" in fields and "list" not in fields:   # API clients send list_name
            fields["list"] = fields.pop("list_name")
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "tags" in updates:
            updates["tags"] = self._encode_tags(updates["tags"])
        if "quantity" in updates:
            try:
                updates["quantity"] = max(1, int(updates["quantity"]))
            except (TypeError, ValueError):
                del updates["quantity"]
        if str(updates.get("completed", "")).lower() in ("1", "true") \
                and self.roll_series_todo(todo_id):
            # a repeating to-do (Q61) moves to its next date instead
            updates.pop("completed")
            updates.pop("completed_at", None)
        if not updates:
            return
        with self._conn() as conn:
            # Same rule as events: a renamed task gets a label from its new
            # words — but only if it has none. An existing tag was chosen (by
            # the user, or by the classifier on a title they kept), and
            # replacing it on every edit would undo that silently. This is what
            # leaves calendar-sync tasks untagged: sync renames them through
            # here and never passes tags.
            if "title" in updates and "tags" not in updates:
                row = conn.execute("SELECT tags FROM todos WHERE id = ?", (todo_id,)).fetchone()
                if row is not None and not self._decode_tags({"tags": row[0]})["tags"]:
                    inferred = self._infer_tags(updates["title"])
                    if inferred:
                        updates["tags"] = self._encode_tags(inferred)
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [_utcnow_iso(), todo_id]
            conn.execute(f"UPDATE todos SET {set_clause}, updated_at = ? WHERE id = ?", values)
            linked = conn.execute("SELECT linked_event_id FROM todos WHERE id = ?",
                                  (todo_id,)).fetchone()
        carry = {}
        if "title" in updates:
            carry["title"] = updates["title"]
        if updates.get("due_date"):          # cleared means "no deadline", not "move"
            carry["date"] = updates["due_date"]
        if carry and linked and linked[0] is not None:
            self.update_event(linked[0], **carry)

    def toggle_todo_complete(self, todo_id: int) -> bool:
        """Flip completed flag; update completed_at. Returns new completed state."""
        todo = self.get_todo(todo_id)
        if todo is None:
            return False
        new_state = 0 if todo["completed"] else 1
        completed_at = datetime.datetime.now().isoformat() if new_state else ""
        self.update_todo(todo_id, completed=new_state, completed_at=completed_at)
        # read back: a repeating to-do (Q61) rolls on instead of completing
        return bool((self.get_todo(todo_id) or {}).get("completed"))

    # ------------------------------------------------------------------
    # Todos: Delete
    # ------------------------------------------------------------------

    def delete_todo(self, todo_id: int) -> None:
        _memory_feedback("todo", todo_id, "rejected")
        with self._conn() as conn:
            conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))

    def delete_todos_by_source(self, source: str) -> int:
        """Delete all todos with the given source. Returns count deleted."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM todos WHERE source = ?", (source,))
            return cur.rowcount

    def delete_completed_todos(self, list_name: Optional[str] = None) -> int:
        """Delete all completed todos, optionally filtered by list. Returns count deleted."""
        with self._conn() as conn:
            if list_name:
                cur = conn.execute(
                    "DELETE FROM todos WHERE completed = 1 AND list = ?", (list_name,)
                )
            else:
                cur = conn.execute("DELETE FROM todos WHERE completed = 1")
            return cur.rowcount

    def reorder_todos(self, list_name: str, ids: List[int]) -> None:
        """Update position of todos in list_name to match the given id order."""
        with self._conn() as conn:
            for pos, todo_id in enumerate(ids):
                conn.execute(
                    "UPDATE todos SET position = ? WHERE id = ? AND list = ?",
                    (pos, todo_id, list_name),
                )

    def todo_titles(self) -> List[str]:
        """Every to-do's title (non-empty), for mining the user's own words."""
        with self._conn() as conn:
            return [r[0] for r in conn.execute("SELECT title FROM todos") if r[0]]

    def has_todos(self) -> bool:
        """Is there any to-do at all? A cheap existence check, not a match."""
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM todos LIMIT 1").fetchone() is not None

    def todo_titles_and_tags(self) -> List[dict]:
        """Every to-do's title and its tags (decoded), for tag discovery."""
        with self._conn() as conn:
            rows = conn.execute("SELECT title, tags FROM todos").fetchall()
        out = []
        for r in rows:
            try:
                tags = json.loads(r["tags"] or "[]")
            except json.JSONDecodeError:
                tags = []
            out.append({"title": r["title"] or "", "tags": tags})
        return out

    # ------------------------------------------------------------------
    # Tag suggestions: what the discovery popup asked and was told
    # (rules in actions/todo/tag_discovery.py; this is only the record)
    # ------------------------------------------------------------------

    def tag_suggestion(self, name: str) -> Optional[dict]:
        """The record for one name: {name, status, ts, hidden}, or None."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tag_suggestion_state WHERE name = ?",
                               (name,)).fetchone()
        return dict(row) if row else None

    def record_tag_suggestion(self, name: str, status: str, ts: str,
                              keep_status: bool = False) -> None:
        """Write a verdict (or an ask stamp). `keep_status` updates only the
        time of a name already recorded, leaving its status as it was."""
        on_conflict = ("ts = excluded.ts" if keep_status
                       else "status = excluded.status, ts = excluded.ts")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO tag_suggestion_state (name, status, ts) VALUES (?, ?, ?) "
                f"ON CONFLICT(name) DO UPDATE SET {on_conflict}", (name, status, ts))

    def hide_tag_suggestion(self, name: str, hidden: bool) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE tag_suggestion_state SET hidden = ? WHERE name = ?",
                         (1 if hidden else 0, name))

    def tag_suggestions(self, exclude: str = "") -> List[dict]:
        """Every record except `exclude`, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, status, ts, hidden FROM tag_suggestion_state "
                "WHERE name != ? ORDER BY ts DESC", (exclude,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Todo tags: CRUD
    # ------------------------------------------------------------------

    def get_tags(self) -> List[dict]:
        """All known tags (built-in first, then user-created, alphabetical)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM todo_tags ORDER BY builtin DESC, name COLLATE NOCASE ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def create_tag(self, name: str, color: str = "") -> Optional[dict]:
        """Add a user tag. Returns the row (existing one if the name is taken)."""
        name = (name or "").strip()
        if not name:
            return None
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT * FROM todo_tags WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if existing:
                return dict(existing)
            conn.execute(
                "INSERT INTO todo_tags (name, color, builtin, created_at) VALUES (?, ?, 0, ?)",
                (name, color, datetime.datetime.now().isoformat()),
            )
            return dict(conn.execute("SELECT * FROM todo_tags WHERE name = ?", (name,)).fetchone())

    def delete_tag(self, name: str) -> None:
        """Remove a tag from the palette and strip it from every todo."""
        with self._conn() as conn:
            conn.execute("DELETE FROM todo_tags WHERE name = ?", (name,))
            rows = conn.execute("SELECT id, tags FROM todos WHERE tags LIKE ?", (f"%{name}%",)).fetchall()
            for r in rows:
                tags = self._decode_tags({"tags": r["tags"]})["tags"]
                kept = [t for t in tags if t.lower() != name.lower()]
                if len(kept) != len(tags):
                    conn.execute("UPDATE todos SET tags = ? WHERE id = ?", (json.dumps(kept), r["id"]))

    def set_todo_tags(self, todo_id: int, tags: List[str]) -> None:
        self._note_label_change("todo", todo_id, {"tags": tags})
        self.update_todo(todo_id, tags=tags)

    # ------------------------------------------------------------------
    # Subtasks: CRUD
    # ------------------------------------------------------------------

    def get_subtasks(self, todo_id: int) -> List[dict]:
        """Return all subtasks for a todo, ordered by position then created_at."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM subtasks WHERE todo_id = ? ORDER BY position ASC, created_at ASC",
                (todo_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def create_subtask(self, todo_id: int, title: str) -> int:
        """Insert a new subtask. Returns the new row id."""
        with self._conn() as conn:
            max_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM subtasks WHERE todo_id = ?",
                (todo_id,),
            ).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO subtasks (todo_id, title, completed, position, created_at) VALUES (?, ?, 0, ?, ?)",
                (todo_id, title, max_pos + 1, datetime.datetime.now().isoformat()),
            )
            return cur.lastrowid

    def update_subtask(self, subtask_id: int, **fields) -> None:
        allowed = {"title", "completed", "position"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [subtask_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE subtasks SET {set_clause} WHERE id = ?", values)

    def delete_subtask(self, subtask_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))

    def delete_subtasks_for_todo(self, todo_id: int) -> None:
        """Delete all subtasks belonging to a todo. Call before delete_todo()."""
        with self._conn() as conn:
            conn.execute("DELETE FROM subtasks WHERE todo_id = ?", (todo_id,))

    def reorder_subtasks(self, todo_id: int, ids: List[int]) -> None:
        """Update position of subtasks to match the given id order."""
        with self._conn() as conn:
            for pos, subtask_id in enumerate(ids):
                conn.execute(
                    "UPDATE subtasks SET position = ? WHERE id = ? AND todo_id = ?",
                    (pos, subtask_id, todo_id),
                )

    # ------------------------------------------------------------------
    # Todos: Calendar Sync
    # ------------------------------------------------------------------

    def sync_calendar_to_todos(self, list_name: str = "today") -> int:
        """
        Pull calendar events into the todos table with source='calendar_sync'.
        Upserts by source_event_id so manually completed synced tasks keep
        their completion state across re-syncs.
        Returns the count of todos created or updated.
        """
        today = datetime.date.today()
        if list_name == "general":
            events = self.get_events_for_week(today)
        else:
            events = self.get_events_for_day(today)

        # Build lookup of existing synced todos: source_event_id → row
        existing: dict[int, dict] = {}
        for row in self.get_todos_by_source("calendar_sync"):
            if row["source_event_id"] is not None:
                existing[row["source_event_id"]] = row

        # Remove synced todos whose source event no longer exists
        incoming_ids = {ev["id"] for ev in events}
        for ev_id, row in existing.items():
            if ev_id not in incoming_ids:
                self.delete_todo(row["id"])

        count = 0
        for ev in events:
            if ev["id"] in existing:
                # Update title (event may have been renamed) but keep completion state
                self.update_todo(existing[ev["id"]]["id"], title=ev["title"])
            else:
                self.create_todo(
                    title=ev["title"],
                    list_name=list_name,
                    source="calendar_sync",
                    source_event_id=ev["id"],
                )
            count += 1
        return count
