"""Courses and their assignments."""

from __future__ import annotations

import datetime
import json
from typing import Optional


class CourseworkMixin:
    """Courses and their assignments."""

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------

    def get_courses(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, number, name, color, partners, position FROM courses ORDER BY position, id"
            ).fetchall()
        return [
            {
                "id": r[0], "number": r[1], "name": r[2], "color": r[3],
                "partners": json.loads(r[4]) if r[4] else [],
                "position": r[5],
            }
            for r in rows
        ]

    def create_course(self, number: str, name: str, color: str, partners: list) -> int:
        now = datetime.datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO courses (number, name, color, partners, created_at) VALUES (?,?,?,?,?)",
                (number, name, color, json.dumps(partners, ensure_ascii=False), now),
            )
            return cur.lastrowid

    def update_course(self, course_id: int, **fields) -> None:
        allowed = {"number", "name", "color", "partners", "position"}
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            updates[k] = json.dumps(v, ensure_ascii=False) if k == "partners" else v
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE courses SET {set_clause} WHERE id = ?",
                (*updates.values(), course_id),
            )

    def delete_course(self, course_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM assignments WHERE course_id = ?", (course_id,))
            conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------

    def get_assignments(self, course_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, course_id, title, due_date, completed, calendar_event_id "
                "FROM assignments WHERE course_id = ? ORDER BY completed, due_date, id",
                (course_id,),
            ).fetchall()
        return [
            {"id": r[0], "course_id": r[1], "title": r[2],
             "due_date": r[3], "completed": r[4], "calendar_event_id": r[5]}
            for r in rows
        ]

    def create_assignment(self, course_id: int, title: str, due_date: str = "") -> int:
        now = datetime.datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO assignments (course_id, title, due_date, created_at) VALUES (?,?,?,?)",
                (course_id, title, due_date, now),
            )
            return cur.lastrowid

    def toggle_assignment(self, assignment_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT completed FROM assignments WHERE id = ?", (assignment_id,)
            ).fetchone()
            if row is None:
                return False
            new_val = 0 if row[0] else 1
            conn.execute("UPDATE assignments SET completed = ? WHERE id = ?", (new_val, assignment_id))
        return bool(new_val)

    def update_assignment(self, assignment_id: int, **fields) -> None:
        allowed = {"title", "due_date", "completed", "calendar_event_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE assignments SET {set_clause} WHERE id = ?",
                (*updates.values(), assignment_id),
            )

    def delete_assignment(self, assignment_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))

    def delete_completed_assignments(self, course_id: Optional[int] = None) -> int:
        """Delete all completed assignments, optionally filtered by course. Returns count deleted."""
        with self._conn() as conn:
            if course_id is not None:
                cur = conn.execute(
                    "DELETE FROM assignments WHERE completed = 1 AND course_id = ?", (course_id,)
                )
            else:
                cur = conn.execute("DELETE FROM assignments WHERE completed = 1")
            return cur.rowcount

    def set_assignment_calendar_event(self, assignment_id: int, event_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE assignments SET calendar_event_id = ? WHERE id = ?",
                (event_id, assignment_id),
            )
