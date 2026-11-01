"""Scrollbars Python owns, for any scroll area whose scrollbar code touches.

`area.verticalScrollBar()` on a plain QScrollArea (or QPlainTextEdit, or any
QAbstractScrollArea) hands back a wrapper for a scrollbar Qt created, and
PyQt keeps that wrapper alive on the area's. When the widget is deleted, Qt
frees the scrollbar and PyQt is never told, so the wrapper is left pointing at
freed memory. The next widget allocated at that address can be handed back as
this "QScrollBar", and the first call on it crashes the process.

That was TASKS 53, the segfault inside `findChildren` that CI hit about one
run in twelve, and one in two by 2026-11-01. It reproduced locally once the
tests deleted each HUD on time, and this fixed it: 0 crashes in 25 runs from
about half. `test_owned_scrollbars.py` holds every caller to it.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractScrollArea, QScrollBar


def own_scrollbars(area: QAbstractScrollArea) -> QAbstractScrollArea:
    """Give `area` scrollbars created from Python, so PyQt tracks their
    lifetime. Returns `area`, to wrap a constructor in place."""
    area.setVerticalScrollBar(QScrollBar(Qt.Orientation.Vertical))
    area.setHorizontalScrollBar(QScrollBar(Qt.Orientation.Horizontal))
    return area
