"""`assistant/common/scratch_env.py` — the one scratch preamble, pinned.

Fifty-six boards used to hand-roll this block (CLAUDE.md, "Personal data lives
outside the repo"); this is what proves the replacement actually does the same
job: every store lands inside the returned dir, the model lock is never
touched, and importing the module costs nothing — it must not drag in the
store-reading modules it exists to run BEFORE.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from assistant.common.scratch_env import STORES, scratch_env


@pytest.fixture(autouse=True)
def _restore_environ():
    """Every test here calls `scratch_env` FOR REAL — that is the point, it is
    the function's own contract to hard-set `os.environ`. Left unrestored,
    that leaks into every test that runs after this file in the same session:
    `test_board_d_scorer.py` documents exactly this hazard for `board_d.py`'s
    own env block, and this helper is no different just because it lives in
    one place now."""
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_every_store_lands_inside_the_returned_dir():
    scratch = scratch_env("test_scratch_env_")
    for var, _name in STORES.values():
        got = os.environ[var]
        assert got.startswith(scratch + os.sep), (var, got, scratch)


def test_it_declares_no_warmup_and_background_priority():
    scratch_env("test_scratch_env_")
    assert os.environ["MACALENDAR_NO_WARMUP"] == "1"
    assert os.environ["MACALENDAR_LLM_PRIORITY"] == "background"


def test_it_never_touches_the_model_lock():
    before = os.environ.get("MACALENDAR_MODEL_LOCK")
    scratch_env("test_scratch_env_")
    assert os.environ.get("MACALENDAR_MODEL_LOCK") == before


def test_it_never_touches_checkpoints_by_default():
    before = os.environ.get("MACALENDAR_CHECKPOINTS")
    scratch_env("test_scratch_env_")
    assert os.environ.get("MACALENDAR_CHECKPOINTS") == before


def test_keep_leaves_a_named_store_untouched():
    before = os.environ.get("MACALENDAR_MEMORY_DB")
    scratch_env("test_scratch_env_", keep=("MEMORY_DB",))
    assert os.environ.get("MACALENDAR_MEMORY_DB") == before


def test_extra_is_applied_last():
    scratch = scratch_env("test_scratch_env_", extra={"MACALENDAR_LEXICON": "sentinel"})
    assert os.environ["MACALENDAR_LEXICON"] == "sentinel"
    assert scratch  # the dir is still returned


def test_seed_and_observance_are_opt_in():
    # Plain call sets neither — a board that never asks for a seed or an
    # observance override must not get one just by calling this helper.
    os.environ.pop("MACALENDAR_LLM_SEED", None)
    os.environ.pop("MACALENDAR_OBSERVANCE", None)
    scratch_env("test_scratch_env_")
    assert "MACALENDAR_LLM_SEED" not in os.environ
    assert "MACALENDAR_OBSERVANCE" not in os.environ

    scratch_env("test_scratch_env_", seed=17, observance=False)
    assert os.environ["MACALENDAR_LLM_SEED"] == "17"
    assert os.environ["MACALENDAR_OBSERVANCE"] == "0"


def test_dir_reuses_an_existing_directory(tmp_path):
    target = tmp_path / "resume_me"
    got = scratch_env("test_scratch_env_", dir=str(target))
    assert got == str(target)
    assert target.is_dir()


def test_importing_it_pulls_in_no_store_reading_module():
    """The whole point: half the callers exist to redirect a store BEFORE
    `assistant.db` / `assistant.intent.memory` / `assistant.stt.vocab` are
    imported. If importing the helper itself dragged one of those in first,
    every caller built on it would already be too late."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys\n"
         "import assistant.common.scratch_env\n"
         "leaked = [m for m in ('assistant.db', 'assistant.intent.memory', "
         "'assistant.stt.vocab') if m in sys.modules]\n"
         "print(','.join(leaked))\n"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", (
        f"importing assistant.common.scratch_env also imported: {out.stdout.strip()}")
