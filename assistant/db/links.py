"""A to-do and an event linked as one thing (DEVQA Q50, Q61)."""

from __future__ import annotations

import datetime
import sqlite3

from assistant.db.common import _utcnow_iso


class LinksMixin:
    """A to-do and an event linked as one thing (DEVQA Q50, Q61)."""

    # ------------------------------------------------------------------
    # A to-do and an event linked as ONE THING
    # ------------------------------------------------------------------
    #
    # Gil, 2026-09-25: "add a linking feature between todo and events, they can
    # be linked and the same thing". It began that morning as DEVQA Q50 — "call
    # the plumber tomorrow" files an event AND a to-do, linked — and any pair can
    # now be linked from either side, on either app. The link is
    # `todos.linked_event_id`, one to-do per event. What it means, per edit:
    #
    #   rename either           -> both renamed
    #   move the event          -> the to-do's due date follows
    #   re-date the to-do       -> the event moves to that day, same clock
    #   delete the event        -> the to-do goes too (they are one thing)
    #   tick or delete the to-do-> the event stays (the call happened, or you no
    #                              longer need reminding; neither un-books it)
    #   unlink                  -> two independent items again
    #
    # An event that disappears any OTHER way (a sync, a series regeneration)
    # only unlinks — `_migrate_links`' trigger.

    def linked_todo(self, event_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM todos WHERE linked_event_id = ?",
                               (event_id,)).fetchone()
        return self._decode_tags(dict(row)) if row else None

    def linked_todos(self, event_id: int) -> list[dict]:
        todo = self.linked_todo(event_id)
        return [todo] if todo else []

    def link_todo(self, todo_id: int, event_id: int) -> bool:
        """Make `todo_id` and `event_id` one thing. An event has one to-do, so
        whatever was linked to it before is released (kept, unlinked). The
        to-do takes the event's day as its due date. False if either is gone."""
        ev = self.get_event(event_id)
        if ev is None or self.get_todo(todo_id) is None:
            return False
        with self._conn() as conn:
            conn.execute("UPDATE todos SET linked_event_id = NULL, updated_at = ? "
                         "WHERE linked_event_id = ? AND id != ?",
                         (_utcnow_iso(), event_id, todo_id))
            conn.execute("UPDATE todos SET linked_event_id = ?, due_date = ?, updated_at = ? "
                         "WHERE id = ?",
                         (event_id, ev.get("date") or "", _utcnow_iso(), todo_id))
        return True

    def unlink_todo(self, todo_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE todos SET linked_event_id = NULL, updated_at = ? "
                         "WHERE id = ?", (_utcnow_iso(), todo_id))

    def create_linked_todo(self, event_id: int) -> int | None:
        """The to-do that IS `event_id`. Its existing one if it has one; None
        if the event is gone."""
        ev = self.get_event(event_id)
        if ev is None:
            return None
        have = self.linked_todo(event_id)
        if have:
            return int(have["id"])
        today = datetime.date.today().isoformat()
        todo_id = self.create_todo(
            title=ev["title"],
            list_name="today" if (ev.get("date") or today) <= today else "general",
            due_date=ev.get("date") or "",
        )
        self.link_todo(todo_id, event_id)
        return todo_id

    def create_linked_event(self, todo_id: int, date: str = "", start_time: str = "09:00",
                            end_time: str = "") -> int | None:
        """The event that IS `todo_id` — on `date`, else its due date, else
        today; 09:00 unless told otherwise (the Q47 default for an unclocked
        event), an hour long. Its existing one if it has one; None if the
        to-do is gone."""
        todo = self.get_todo(todo_id)
        if todo is None:
            return None
        if todo.get("linked_event_id") and self.get_event(todo["linked_event_id"]):
            return int(todo["linked_event_id"])
        from assistant.actions.calendar.intent import CalendarIntent
        day = date or todo.get("due_date") or datetime.date.today().isoformat()
        if not end_time:
            h, m = (int(x) for x in start_time.split(":")[:2])
            end_time = f"{min(h + 1, 23):02d}:{m:02d}"
        event_id = self.create_event(CalendarIntent(
            title=todo["title"], date=day, start_time=start_time, end_time=end_time))
        self.link_todo(todo_id, event_id)
        return event_id

    # A REPEATING TO-DO (DEVQA Q61, Gil 2026-09-27): the series is the event,
    # and ONE to-do rides with it, linked to the next occurrence — never one
    # copy per date. Ticking it marks that occurrence done and moves the to-do
    # to the one after; deleting that occurrence moves it on the same way; a
    # series edit that regenerates the instances re-links it (`update_series`).
    # Only when the series has nothing left does the to-do complete.

    @staticmethod
    def _next_instance(conn, event_id: int, not_before: str = "") -> sqlite3.Row | None:
        """The series instance after `event_id`, on or after `not_before`."""
        ev = conn.execute("SELECT series_id, date FROM events WHERE id = ?",
                          (event_id,)).fetchone()
        if ev is None or ev["series_id"] is None:
            return None
        return conn.execute(
            "SELECT id, date FROM events WHERE (series_id = ? OR id = ?) AND id != ? "
            "AND date > ? AND date >= ? ORDER BY date, start_time LIMIT 1",
            (ev["series_id"], ev["series_id"], event_id, ev["date"], not_before or "")).fetchone()

    @staticmethod
    def _move_link(conn, todo_id: int, row) -> None:
        today = datetime.date.today().isoformat()
        conn.execute(
            "UPDATE todos SET linked_event_id = ?, due_date = ?, list = ?, completed = 0, "
            "completed_at = '', updated_at = ? WHERE id = ?",
            (row["id"], row["date"], "today" if row["date"] <= today else "general",
             _utcnow_iso(), todo_id))

    def roll_series_todo(self, todo_id: int) -> bool:
        """Tick a to-do linked to a series: move it to the next occurrence from
        today on. False when it is not on a series or the series has ended —
        the caller then completes it as any other to-do."""
        todo = self.get_todo(todo_id)
        event_id = (todo or {}).get("linked_event_id")
        if not event_id:
            return False
        with self._conn() as conn:
            nxt = self._next_instance(conn, int(event_id), datetime.date.today().isoformat())
            if nxt is None:
                return False
            self._move_link(conn, todo_id, nxt)
        return True

    def _follow_event(self, conn, event_id: int, updates: dict) -> None:
        """Carry an event's new title or date onto its linked to-do."""
        carry = {k: updates[k] for k in ("title", "date") if k in updates}
        if not carry:
            return
        cols = {"title": "title", "date": "due_date"}
        set_clause = ", ".join(f"{cols[k]} = ?" for k in carry)
        conn.execute(
            f"UPDATE todos SET {set_clause}, updated_at = ? WHERE linked_event_id = ?",
            list(carry.values()) + [_utcnow_iso(), event_id])
