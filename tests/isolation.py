"""Point every personal store at a scratch directory.

`~/.assistant_tools/` holds the real calendar, the command memory the parser
learns from, the hand-curated vocabulary and the event categories. None of it
is test data, and a script that forgets to say so gets the real thing.

That is not hypothetical: `tests/test_ollama_parser.py` had no isolation at
all, and its `clear_db()` — `DELETE FROM events`, once per scenario — emptied
the real calendar. 657 events.

Import this **first**, before anything from `assistant`: the store paths are
module constants and default arguments, read at import time, so setting them
afterwards is too late.

    from tests.isolation import isolate
    isolate()

    from assistant.db import CalendarDB      # now safe

`assert_isolated()` is the belt to that braces — call it after importing
`assistant` to prove the paths really did land in the scratch directory.
"""

from __future__ import annotations

import os
import tempfile

# The stores, and the environment variable each one honours.
#
# THIS IS THE ONE LIST. `tests/conftest.py` iterates it rather than keeping a
# second copy, and `test_data_isolation` asserts it covers every
# `~/.assistant_tools/` path the app reads — because the same omission has now
# happened three times, each found only by accident:
#
#   MACALENDAR_LOCATION    2026-09-06, when two checkouts' suites raced through
#                          the shared location.json
#   MACALENDAR_TRACE_BUS   "the fifth, and it was missed for a long time" —
#                          test commands published into the HUD's real history
#   MACALENDAR_HEARTBEATS  2026-09-11. heartbeat.py's docstring already SAID
#                          "overridable with MACALENDAR_HEARTBEATS, which the
#                          tests point at a scratch dir". They did not: a
#                          `pytest tests/` run wrote a beat into the real
#                          ~/.assistant_tools/heartbeats/, so `assistant
#                          doctor` read a test's timestamp as a live surface.
#
# A hand-kept list is exactly what kept failing, so the list is now checked.
STORES = {
    "MACALENDAR_DB": "calendar.db",
    "MACALENDAR_MEMORY_DB": "nlu_memory.db",
    "MACALENDAR_VOCAB": "vocab.json",
    "MACALENDAR_CATEGORIES": "categories.json",
    "MACALENDAR_LOCATION": "location.json",
    "MACALENDAR_TRACE_BUS": "trace_bus.jsonl",
    "MACALENDAR_HEARTBEATS": "heartbeats",
    "MACALENDAR_HUD_STATE": "hud_position.json",
}

REAL_DIR = os.path.expanduser("~/.assistant_tools")


def isolate(prefix: str = "macalendar-scratch-") -> str:
    """Send every store to a fresh temp directory. Returns the directory.

    Existing overrides are respected (`setdefault`), so a caller that already
    pointed somewhere specific — the audit harness works from a *copy* of the
    real vocabulary on purpose — keeps its own choice.
    """
    scratch = tempfile.mkdtemp(prefix=prefix)
    for var, name in STORES.items():
        os.environ.setdefault(var, os.path.join(scratch, name))
    return scratch


def assert_isolated() -> None:
    """Raise unless every store points somewhere other than the real one."""
    offenders = []
    for var in STORES:
        path = os.environ.get(var)
        if not path or os.path.realpath(os.path.dirname(path)) == os.path.realpath(REAL_DIR):
            offenders.append(f"{var}={path!r}")
    if offenders:
        raise RuntimeError(
            "Refusing to run against the real personal stores in "
            f"{REAL_DIR}. Not isolated: {', '.join(offenders)}. "
            "Call tests.isolation.isolate() before importing anything from `assistant`."
        )
