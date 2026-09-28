"""Centralized cross-session context memory for anaphora resolution.

Replaces the scattered module-level globals (_last_event_id, _last_todo_id, etc.)
previously living in calendar/action.py and todo/action.py. By centralizing here,
the RuleBasedParser can resolve anaphoric references ("it", "that") at parse time
without circular imports into action modules.
"""
from __future__ import annotations

import threading
from typing import Optional


class ContextMemory:
    """Thread-safe Borg singleton holding the most recently touched
    event and todo IDs/titles for anaphoric reference ('it', 'that').

    Uses the Borg pattern (shared state dict) so all instances are the same object.
    """

    #: One shared state PER USER (assistant/users): "it" / "the one I just
    #: made" is the speaker's last event, never another user's. "" is the
    #: state of a process nobody is bound in — today's single shared one.
    _shared_by_user: "dict[str, dict]" = {}
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        from assistant import users
        self.__dict__ = self._shared_by_user.setdefault(users.current() or "", {})

    # --- Event memory ---
    last_event_id: Optional[int] = None
    last_event_title: Optional[str] = None
    last_event_date: Optional[str] = None   # ISO date, for UI navigation

    # --- Todo memory ---
    last_todo_id: Optional[int] = None
    last_todo_title: Optional[str] = None

    def update_event(self, event_id: int, title: str, date: str) -> None:
        with self._lock:
            self.last_event_id = event_id
            self.last_event_title = title
            self.last_event_date = date

    def update_todo(self, todo_id: int, title: str) -> None:
        with self._lock:
            self.last_todo_id = todo_id
            self.last_todo_title = title

    # --- The row an update / delete / complete is about to change ---
    # (kind, id, row-as-it-was). The commit step reads it after each action
    # so a command's review can show what an edit replaced and put back what
    # a delete removed (2026-09-24). `touched_seq` moves on every note, so the
    # commit step can tell THIS action touched something without comparing rows.
    touched: Optional[tuple] = None
    touched_seq: int = 0

    def note_touched(self, kind: str, row: dict) -> None:
        with self._lock:
            self.touched = (kind, int(row["id"]), dict(row))
            self.touched_seq += 1

    def clear_event(self) -> None:
        with self._lock:
            self.last_event_id = None
            self.last_event_title = None
            self.last_event_date = None

    def clear_todo(self) -> None:
        with self._lock:
            self.last_todo_id = None
            self.last_todo_title = None

    def reset(self) -> None:
        """Clear all memory — every user's. Used in tests."""
        with self._lock:
            for state in self._shared_by_user.values():
                state.clear()


class _CurrentUsersMemory:
    """`context_memory`: forwards every read and write to the ContextMemory
    of the user bound RIGHT NOW. A plain module-level ContextMemory would have
    bound its state once, at import, to whoever was current then (nobody)."""

    def __getattr__(self, name):
        return getattr(ContextMemory(), name)

    def __setattr__(self, name, value):
        setattr(ContextMemory(), name, value)


# Module-level handle — import this everywhere
context_memory = _CurrentUsersMemory()
