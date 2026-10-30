"""Picking an event's category and colour when none was chosen."""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)


#: THE "NO COLOUR CHOSEN" MARKERS — a caller passing one of these is saying
#: *pick a colour from the category*, not *use this colour*.
#:
#: `None` is the canonical one; the rest are legacy. `"#0078d4"` was the app's
#: hardcoded blue back when there was exactly one, and rows and clients still
#: send it.
#:
#: **This set must never be "whatever the UI accent currently is".** That is the
#: bug it was involved in (2026-09-10): `calendar_ui.styles.BLUE` was renamed to
#: the CONFIGURABLE accent — "kept name for call-site compatibility" — and two
#: call sites kept passing it as a default. The accent is not in this set, so
#: `auto_category_and_color` read it as a deliberate user choice and returned it
#: unchanged, `pick_color` never ran, and every voice-created event came out the
#: same amber whatever its category. 11 of 54 real events, from 2026-09-08 on.
#:
#: Adding the accent here would "fix" it and break colour-picking instead: the
#: accent is one of the swatches a user can genuinely choose. The right fix is
#: the one that was made — a caller with no colour to honour passes None.
_AUTO_COLORS = {"#0078d4", "", None}

def _neighbour_colors(conn: sqlite3.Connection, date: str, start_time: str, exclude_id: int | None = None) -> list[str]:
    """Colours of the events immediately before and after on the same day."""
    rows = conn.execute("SELECT id, start_time, color FROM events WHERE date = ? ORDER BY start_time", (date,)).fetchall()
    rows = [r for r in rows if r[0] != exclude_id]
    before = [r for r in rows if r[1] <= (start_time or "")]
    after = [r for r in rows if r[1] > (start_time or "")]
    out = []
    if before: out.append(before[-1][2])
    if after: out.append(after[0][2])
    return [c for c in out if c]

def auto_category_and_color(conn: sqlite3.Connection, title: str, date: str, start_time: str,
                            attendees="", location: str = "", description: str = "",
                            color: str | None = None, category: str | None = None,
                            exclude_id: int | None = None) -> tuple[str, str]:
    """Return (category, colour). A colour the user chose explicitly is kept; otherwise the
    category's colour, switched to its alternate shade if a neighbouring event has it."""
    try:
        from assistant.actions.calendar import categories as _cat
        from assistant.engine.label.title_icons import strip as _words
        title = _words(title)          # labelled by its words, not its emoji (TASKS 51)
        cat = category or _cat.classify(title, attendees, location, description)
        if not category:
            # THE LEARNED LABELLER, STACKED BEHIND THE RULES. It only answers
            # where `classify` fell through to the catch-all, so every row the
            # keyword rules were confident about keeps their measured 91.7%
            # precision. Off unless `labels.model_event` is on; a missing model
            # or an unconfident one falls back silently. See engine/label/model.py.
            try:
                from assistant.config import load_config as _lc
                from assistant.engine.label import model as _lm
                cat, _who = _lm.category_for(title, cat, _lc("config.yaml"))
            except Exception:
                logger.debug("Fitted category model unavailable", exc_info=True)
        if color not in _AUTO_COLORS and not category:
            return cat, color                      # explicit user colour wins
        if color not in _AUTO_COLORS and category:
            return cat, color
        return cat, _cat.pick_color(cat, _neighbour_colors(conn, date, start_time, exclude_id))
    except Exception:
        return category or "", color or "#0078d4"
