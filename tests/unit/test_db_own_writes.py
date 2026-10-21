"""The GUI tells its own DB writes from another process's.

The window polls the calendar file's mtime to notice the API server's writes
(the phone). It could not tell those from its own, so every autosave, tick or
timer start reloaded every panel a few seconds later — the window flashed
(2026-10-21 audit). `own_write_mtime` is the mtime this process's last write
left; the poll skips a change that is exactly that.
"""
from __future__ import annotations

import os
import sqlite3
import time

from assistant import db as dbmod
from assistant.db import CalendarDB


def test_a_write_from_this_process_is_recognised(tmp_path):
    db = CalendarDB(str(tmp_path / "cal.db"))
    db.create_timer(title="x")
    assert dbmod.own_write_mtime(db.path) == os.path.getmtime(db.path)


def test_a_read_is_not_a_write(tmp_path):
    db = CalendarDB(str(tmp_path / "cal.db"))
    db.create_timer(title="x")
    before = dbmod.own_write_mtime(db.path)
    time.sleep(0.01)
    db.get_timers()
    assert dbmod.own_write_mtime(db.path) == before


def test_another_processs_write_is_not_ours(tmp_path):
    db = CalendarDB(str(tmp_path / "cal.db"))
    db.create_timer(title="x")
    time.sleep(0.02)
    other = sqlite3.connect(db.path)            # as the API server would
    other.execute("UPDATE timers SET title = 'y'")
    other.commit()
    other.close()
    assert dbmod.own_write_mtime(db.path) != os.path.getmtime(db.path)
