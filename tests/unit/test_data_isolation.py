"""No test may touch ~/.assistant_tools.

That directory holds the real calendar, the command memory the parser learns
from, the hand-curated vocabulary and the event categories. A test script with
no isolation once ran `DELETE FROM events` against it and emptied the real
calendar — 657 events, unrecoverable.

Two guards, both checked here: every runnable test script isolates its stores
before importing `assistant`, and `CalendarDB` refuses to open the real file
from a test run even if one doesn't.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Scripts you can run directly that drive the pipeline or the stores. Each must
# call tests.isolation.isolate() before importing anything from `assistant`.
RUNNABLE = [
    "tests/test_ollama_parser.py",
    "tests/test_todo_parser.py",
    "scripts/test_stt.py",
    "scripts/benchmark_models.py",
]
# `scripts/test_pipeline.py` and `scripts/test_ollama.py` were removed on
# 2026-09-11: both imported `OllamaIntentParser`, a class the engine rewrite
# deleted, so both had raised ImportError on their first line for months.


@pytest.mark.parametrize("relpath", RUNNABLE)
def test_every_runnable_script_isolates_before_importing_assistant(relpath):
    path = REPO / relpath
    # A hand-kept list rots the moment a script is renamed or deleted, and the
    # rot reads as a crash in an unrelated test rather than as "fix the list".
    assert path.exists(), (
        f"{relpath} is listed here but no longer exists — delete the entry, "
        "or point it at wherever the script moved."
    )
    src = path.read_text()

    isolate_at = src.find("isolate(")
    assert isolate_at != -1, (
        f"{relpath} never calls tests.isolation.isolate() — it would run "
        "against the real calendar, command memory and vocabulary."
    )
    first_app_import = min(
        [m.start() for m in re.finditer(r"^\s*(?:from|import)\s+assistant\b", src, re.M)]
        or [len(src)]
    )
    assert isolate_at < first_app_import, (
        f"{relpath} imports `assistant` before isolate(). The store paths are "
        "module constants and default arguments read at import time, so "
        "isolating afterwards is too late."
    )


def test_the_audit_harness_isolates_too():
    # It has its own preamble (it works from a *copy* of the real vocabulary on
    # purpose), so it is exempt from the import-order check but not from this.
    src = (REPO / "scripts/audit_assistant.py").read_text()
    for var in ("MACALENDAR_DB", "MACALENDAR_MEMORY_DB", "MACALENDAR_VOCAB"):
        assert var in src, f"audit_assistant.py does not set {var}"


def test_the_suite_itself_is_pointed_at_scratch_files():
    from tests.isolation import REAL_DIR, STORES
    for var in STORES:
        path = os.environ.get(var)
        assert path, f"{var} is not set for this test run"
        assert os.path.realpath(os.path.dirname(path)) != os.path.realpath(REAL_DIR), (
            f"{var} points into the real store directory"
        )


def test_opening_the_real_database_from_a_test_is_refused():
    """The backstop: even with no isolation at all, a test cannot open it."""
    from assistant.db import DB_PATH, CalendarDB

    with pytest.raises(RuntimeError, match="Refusing to open the real calendar"):
        CalendarDB(path=DB_PATH)


def test_the_guard_lets_the_real_app_through():
    """It must only fire under pytest — the app itself opens that file for real."""
    code = (
        "import os, sys; sys.path.insert(0, %r)\n"
        "for v in ('PYTEST_CURRENT_TEST', 'PYTEST_VERSION'):\n"
        "    os.environ.pop(v, None)\n"
        "os.environ.pop('MACALENDAR_DB', None)\n"
        "from assistant.db import CalendarDB, DB_PATH\n"
        "CalendarDB._guard_real_db(DB_PATH)\n"
        "print('allowed')\n" % str(REPO)
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(REPO))
    assert out.returncode == 0, out.stderr
    assert "allowed" in out.stdout


def test_every_personal_store_the_app_reads_is_in_the_isolation_list():
    """The list must cover every `~/.assistant_tools/` path the app can open.

    A hand-kept list was the actual failure mode three times over — the
    device-location store (2026-09-06), the trace bus ("the fifth, and it was
    missed for a long time") and the heartbeats directory (2026-09-11, whose
    own docstring claimed the tests already redirected it). Each was found by
    noticing real data had changed, never by a test.

    The rule this checks is narrow on purpose: a `MACALENDAR_*` variable that
    is read with `~/.assistant_tools/...` as its fallback IS a personal store,
    and must be in STORES. Flags like MACALENDAR_NO_WARMUP have no path and are
    not caught by it.
    """
    from tests.isolation import STORES

    pattern = re.compile(
        r'os\.environ\.get\(\s*"(MACALENDAR_[A-Z_]+)"\s*\)[^\n]*(?:\n[^\n]*)?'
        r'~/\.assistant_tools'
    )
    found: dict[str, str] = {}
    for path in (REPO / "assistant").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for m in pattern.finditer(path.read_text()):
            found.setdefault(m.group(1), str(path.relative_to(REPO)))

    assert found, "found no personal stores at all — the pattern has rotted"
    missing = {v: where for v, where in found.items() if v not in STORES}
    assert not missing, (
        "these personal stores are read by the app but are NOT redirected by "
        f"tests/isolation.py's STORES: {missing}. A test run writes them into "
        f"the real ~/.assistant_tools. Add each to STORES with its filename."
    )
