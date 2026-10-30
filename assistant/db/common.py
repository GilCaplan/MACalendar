"""Pieces every area of the store shares: the file's default path, timestamps,
the command-memory hook, and the record of the store's own writes."""

from __future__ import annotations

import datetime
import logging
import os

logger = logging.getLogger(__name__)


DB_PATH = os.path.expanduser("~/.assistant_tools/calendar.db")

def _utcnow_iso() -> str:
    """UTC timestamp for sync bookkeeping — comparable against Graph API timestamps."""
    return datetime.datetime.now(datetime.UTC).isoformat()

def _memory_feedback(record_type: str, record_id: int, feedback: str,
                     changed: dict | None = None) -> None:
    """Implicit NLU feedback: a user edit/delete of a voice-created record.

    Best-effort and silent — the memory layer must never affect DB writes.
    """
    try:
        from assistant.intent.memory import get_memory
        get_memory().feedback_for_record(record_type, record_id, feedback, changed)
    except Exception:
        logger.warning("Could not pass %s feedback on %s %s to the command memory",
                       feedback, record_type, record_id, exc_info=True)

#: path -> the file's mtime right after THIS process last wrote it. The GUI
#: polls the file's mtime to notice writes from the API server (the phone);
#: without this it could not tell its own writes from the phone's, so every
#: note autosave, tick, rename, timer start or counter press reloaded every
#: panel and the calendar a few seconds later — the window flashed under the
#: user's hands (2026-10-21 audit).
_OWN_WRITES: dict[str, float] = {}

def _note_own_write(path: str) -> None:
    try:
        _OWN_WRITES[os.path.abspath(path)] = os.path.getmtime(path)
    except OSError:
        pass

def own_write_mtime(path: str) -> float | None:
    """The mtime this process's own last write left on `path`, if any."""
    return _OWN_WRITES.get(os.path.abspath(path))
