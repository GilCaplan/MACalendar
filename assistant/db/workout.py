"""Workout exercises, templates, plans and sessions."""

from __future__ import annotations

import datetime
import sqlite3
import uuid
from typing import List, Optional


class WorkoutMixin:
    """Workout exercises, templates, plans and sessions."""

    # ------------------------------------------------------------------
    # Workout: Exercises
    # ------------------------------------------------------------------

    def create_workout_exercise(self, id: str, name: str, created_at: Optional[str] = None) -> str:
        """Insert a new exercise with a client-generated UUID. Idempotent on id
        (INSERT OR IGNORE) so a retried offline-sync POST is safe to resend."""
        now = created_at or datetime.datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO workout_exercises (id, name, created_at) VALUES (?, ?, ?)",
                (id, name, now),
            )
        return id

    def get_workout_exercises(self) -> List[dict]:
        """Return all exercises, alphabetical (used for search-or-create autocomplete)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM workout_exercises ORDER BY name COLLATE NOCASE ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_workout_exercise(self, exercise_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workout_exercises WHERE id = ?", (exercise_id,)
            ).fetchone()
        return dict(row) if row else None

    def find_workout_exercise_by_name(self, name: str) -> Optional[dict]:
        """Case-insensitive exact name match — used to reuse an existing exercise
        instead of creating a duplicate."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workout_exercises WHERE name = ? COLLATE NOCASE LIMIT 1",
                (name,),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Workout: Templates (+ nested blocks/sets)
    # ------------------------------------------------------------------

    def _insert_workout_template_blocks(self, conn: sqlite3.Connection, template_id: str, blocks: list) -> None:
        """Insert a template's blocks and their nested sets. Caller owns the transaction."""
        for idx, block in enumerate(blocks):
            conn.execute(
                """
                INSERT INTO workout_template_blocks
                    (id, template_id, order_index, kind, exercise_id, rest_between_sets_override,
                     exercise_id_a, exercise_id_b, rest_after_round)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    block["id"], template_id, idx, block["kind"],
                    block.get("exercise_id"), block.get("rest_between_sets_override"),
                    block.get("exercise_id_a"), block.get("exercise_id_b"),
                    block.get("rest_after_round"),
                ),
            )
            for side, sets_key in (("single", "sets"), ("a", "sets_a"), ("b", "sets_b")):
                for set_idx, s in enumerate(block.get(sets_key) or []):
                    conn.execute(
                        """
                        INSERT INTO workout_template_sets
                            (id, block_id, side, set_index, type, target_reps, weight_kg,
                             target_seconds, note, distance_m, target_pace_sec_per_km)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            s["id"], block["id"], side, set_idx, s["type"],
                            s.get("target_reps"), s.get("weight_kg"), s.get("target_seconds"),
                            s.get("note") or "",
                            s.get("distance_m"), s.get("target_pace_sec_per_km"),
                        ),
                    )

    def _delete_workout_template_children(self, conn: sqlite3.Connection, template_id: str) -> None:
        block_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM workout_template_blocks WHERE template_id = ?", (template_id,)
            ).fetchall()
        ]
        for block_id in block_ids:
            conn.execute("DELETE FROM workout_template_sets WHERE block_id = ?", (block_id,))
        conn.execute("DELETE FROM workout_template_blocks WHERE template_id = ?", (template_id,))

    def _hydrate_workout_template(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        template = dict(row)
        block_rows = conn.execute(
            "SELECT * FROM workout_template_blocks WHERE template_id = ? ORDER BY order_index ASC",
            (template["id"],),
        ).fetchall()
        blocks = []
        for b in block_rows:
            b = dict(b)
            set_rows = conn.execute(
                "SELECT * FROM workout_template_sets WHERE block_id = ? ORDER BY set_index ASC",
                (b["id"],),
            ).fetchall()
            sets, sets_a, sets_b = [], [], []
            for s in set_rows:
                s = dict(s)
                side = s.pop("side")
                s.pop("block_id", None)
                s.pop("set_index", None)
                (sets_a if side == "a" else sets_b if side == "b" else sets).append(s)
            blocks.append({
                "id": b["id"],
                "kind": b["kind"],
                "exercise_id": b["exercise_id"],
                "sets": sets,
                "rest_between_sets_override": b["rest_between_sets_override"],
                "exercise_id_a": b["exercise_id_a"],
                "exercise_id_b": b["exercise_id_b"],
                "sets_a": sets_a,
                "sets_b": sets_b,
                "rest_after_round": b["rest_after_round"],
            })
        template["blocks"] = blocks
        return template

    def create_workout_template(self, template: dict) -> str:
        """Insert a full nested template (id, name, blocks[+sets], ...) transactionally.
        `template["id"]` is the client-generated UUID."""
        template_id = template["id"]
        now = template.get("created_at") or datetime.datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workout_templates
                    (id, name, default_rest_between_sets, default_rest_between_exercises,
                     created_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id, template["name"],
                    template.get("default_rest_between_sets", 90),
                    template.get("default_rest_between_exercises", 120),
                    now, template.get("status", "saved"),
                ),
            )
            self._insert_workout_template_blocks(conn, template_id, template.get("blocks") or [])
        return template_id

    def get_workout_templates(self, include_drafts: bool = False) -> List[dict]:
        """Return templates newest-first. Drafts (status='draft', pending review after
        AI generation) are excluded unless include_drafts=True."""
        where = "" if include_drafts else "WHERE status != 'draft'"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM workout_templates {where} ORDER BY created_at DESC"
            ).fetchall()
            return [self._hydrate_workout_template(conn, r) for r in rows]

    def get_workout_template(self, template_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workout_templates WHERE id = ?", (template_id,)
            ).fetchone()
            if row is None:
                return None
            return self._hydrate_workout_template(conn, row)

    def replace_workout_template(self, template_id: str, template: dict) -> None:
        """Replace-whole-template semantics: update scalar fields, delete+recreate
        all blocks/sets. Simpler than diffing a nested structure and matches how
        the client always has the full current template in memory anyway."""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE workout_templates
                SET name = ?, default_rest_between_sets = ?, default_rest_between_exercises = ?,
                    status = ?
                WHERE id = ?
                """,
                (
                    template.get("name"),
                    template.get("default_rest_between_sets", 90),
                    template.get("default_rest_between_exercises", 120),
                    template.get("status", "saved"),
                    template_id,
                ),
            )
            self._delete_workout_template_children(conn, template_id)
            self._insert_workout_template_blocks(conn, template_id, template.get("blocks") or [])

    def delete_workout_template(self, template_id: str) -> None:
        with self._conn() as conn:
            self._delete_workout_template_children(conn, template_id)
            conn.execute("DELETE FROM workout_templates WHERE id = ?", (template_id,))

    def approve_workout_template(self, template_id: str) -> None:
        """Flip a draft (from AI generation) to 'saved' — the client called /approve
        after the user reviewed it. No-op if already saved or not found."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE workout_templates SET status = 'saved' WHERE id = ?", (template_id,)
            )

    # ------------------------------------------------------------------
    # Workout: Plans (a dated block of sessions)
    # ------------------------------------------------------------------

    _PLAN_ITEM_FIELDS = (
        "date", "start_time", "end_time", "kind", "discipline", "title", "detail",
        "distance_km", "template_id", "event_id", "window_label", "observance_note",
        "session_id",
    )

    def create_workout_plan(self, plan: dict) -> str:
        """Insert a plan and its items. Items may carry no event_id yet — the
        scheduler materialises calendar events in a second pass and links them
        back with `set_plan_item_event`."""
        plan_id = plan.get("id") or str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workout_plans (id, name, goal, start_date, end_date, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id, plan["name"], plan.get("goal") or "",
                    plan["start_date"], plan["end_date"],
                    plan.get("created_at") or now, plan.get("status") or "active",
                ),
            )
            self._insert_plan_items(conn, plan_id, plan.get("items") or [])
        return plan_id

    def _insert_plan_items(self, conn: sqlite3.Connection, plan_id: str, items: list) -> None:
        now = datetime.datetime.now().isoformat()
        for item in items:
            cols = ", ".join(self._PLAN_ITEM_FIELDS)
            marks = ", ".join("?" for _ in self._PLAN_ITEM_FIELDS)
            values = [item.get(f) for f in self._PLAN_ITEM_FIELDS]
            # Text columns are NOT NULL with '' defaults; None would violate them.
            for i, f in enumerate(self._PLAN_ITEM_FIELDS):
                if f in ("start_time", "end_time", "detail", "window_label",
                         "observance_note", "discipline") and values[i] is None:
                    values[i] = "" if f != "discipline" else "run"
            conn.execute(
                f"INSERT INTO workout_plan_items (id, plan_id, {cols}, created_at) "
                f"VALUES (?, ?, {marks}, ?)",
                [item.get("id") or str(uuid.uuid4()), plan_id, *values,
                 item.get("created_at") or now],
            )

    def get_workout_plans(self, status: Optional[str] = None) -> List[dict]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM workout_plans WHERE status = ? ORDER BY start_date DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workout_plans ORDER BY start_date DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_workout_plan(self, plan_id: str) -> Optional[dict]:
        """A plan with its items attached, ordered by date then start time."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workout_plans WHERE id = ?", (plan_id,)
            ).fetchone()
            if row is None:
                return None
            plan = dict(row)
            plan["items"] = [dict(r) for r in conn.execute(
                "SELECT * FROM workout_plan_items WHERE plan_id = ? "
                "ORDER BY date ASC, start_time ASC",
                (plan_id,),
            ).fetchall()]
            return plan

    def get_workout_plan_items(
        self, start_date: str = "", end_date: str = "", plan_id: str = ""
    ) -> List[dict]:
        """Items in a date range — what the calendar's day/week views ask for."""
        clauses, params = [], []
        if start_date:
            clauses.append("date >= ?"); params.append(start_date)
        if end_date:
            clauses.append("date <= ?"); params.append(end_date)
        if plan_id:
            clauses.append("plan_id = ?"); params.append(plan_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM workout_plan_items {where} ORDER BY date ASC, start_time ASC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_workout_plan_item(self, item_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workout_plan_items WHERE id = ?", (item_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_workout_plan_item(self, item_id: str, **fields) -> None:
        allowed = {f: v for f, v in fields.items() if f in self._PLAN_ITEM_FIELDS}
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE workout_plan_items SET {sets} WHERE id = ?",
                [*allowed.values(), item_id],
            )

    def set_plan_item_event(self, item_id: str, event_id: Optional[int]) -> None:
        """Link a plan item to the calendar event it was materialised into."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE workout_plan_items SET event_id = ? WHERE id = ?",
                (event_id, item_id),
            )

    def delete_workout_plan(self, plan_id: str, delete_events: bool = True) -> int:
        """Remove a plan and its items. Unless told otherwise, the calendar
        events the plan created go with it — leaving them behind is how a
        re-plan ends up with two of every session."""
        removed = 0
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT event_id FROM workout_plan_items WHERE plan_id = ? AND event_id IS NOT NULL",
                (plan_id,),
            ).fetchall()
            if delete_events:
                for r in rows:
                    conn.execute("DELETE FROM events WHERE id = ?", (r[0],))
                    removed += 1
            conn.execute("DELETE FROM workout_plan_items WHERE plan_id = ?", (plan_id,))
            conn.execute("DELETE FROM workout_plans WHERE id = ?", (plan_id,))
        return removed

    # ------------------------------------------------------------------
    # Workout: Sessions (+ nested set logs)
    # ------------------------------------------------------------------

    def _insert_workout_set_logs(self, conn: sqlite3.Connection, session_id: str, set_logs: list) -> None:
        for log in set_logs:
            conn.execute(
                """
                INSERT INTO workout_set_logs
                    (id, session_id, exercise_id, set_index, type, actual_reps, actual_seconds,
                     actual_weight_kg, completed_at, skipped)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log["id"], session_id, log["exercise_id"], log.get("set_index", 0),
                    log["type"], log.get("actual_reps"), log.get("actual_seconds"),
                    log.get("actual_weight_kg"), log.get("completed_at"),
                    int(bool(log.get("skipped", False))),
                ),
            )

    def _hydrate_workout_session(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        session = dict(row)
        log_rows = conn.execute(
            "SELECT * FROM workout_set_logs WHERE session_id = ? ORDER BY rowid ASC",
            (session["id"],),
        ).fetchall()
        set_logs = []
        for r in log_rows:
            log = dict(r)
            log.pop("session_id", None)
            log["skipped"] = bool(log["skipped"])
            set_logs.append(log)
        session["set_logs"] = set_logs
        return session

    def create_workout_session(self, session: dict) -> str:
        """Insert a full nested session (id, startedAt, ..., setLogs[]) transactionally.
        Sessions are normally posted once already-finished on the client."""
        session_id = session["id"]
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workout_sessions (id, template_id, started_at, ended_at, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id, session.get("template_id"), session["started_at"],
                    session.get("ended_at"), session.get("notes") or "",
                ),
            )
            self._insert_workout_set_logs(conn, session_id, session.get("set_logs") or [])
        return session_id

    def get_workout_sessions(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[dict]:
        """Return sessions most-recent-first, optionally filtered by started_at range
        and/or capped with limit."""
        query = "SELECT * FROM workout_sessions"
        conditions: List[str] = []
        params: List = []
        if start_date:
            conditions.append("started_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("started_at <= ?")
            params.append(end_date)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY started_at DESC"
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._hydrate_workout_session(conn, r) for r in rows]

    def get_workout_session(self, session_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workout_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            return self._hydrate_workout_session(conn, row)

    def update_workout_session(self, session_id: str, **fields) -> None:
        """Patch allowed scalar fields; if 'set_logs' is present, delete+recreate
        the child rows (post-hoc edits to logged sets)."""
        allowed = {"template_id", "started_at", "ended_at", "notes"}
        set_logs = fields.pop("set_logs", None)
        updates = {k: v for k, v in fields.items() if k in allowed}
        with self._conn() as conn:
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE workout_sessions SET {set_clause} WHERE id = ?",
                    (*updates.values(), session_id),
                )
            if set_logs is not None:
                conn.execute("DELETE FROM workout_set_logs WHERE session_id = ?", (session_id,))
                self._insert_workout_set_logs(conn, session_id, set_logs)

    def delete_workout_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM workout_set_logs WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM workout_sessions WHERE id = ?", (session_id,))
