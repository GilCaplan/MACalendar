"""A command that crashes while its recording was cancelled still reports it.

`Pipeline._run` cleaned up in `finally` and, on the double-tap cancel path,
returned from inside it. A `return` in `finally` discards the exception in
flight, so a crash during a cancelled command vanished (ruff B012,
2026-10-30). The cleanup must still happen, and the error must still surface.
"""
import threading

import pytest


def _bare_pipeline():
    from assistant.pipeline import Pipeline
    p = object.__new__(Pipeline)            # only what _run touches
    p._busy = threading.Event()
    p._trigger_lock = threading.Lock()
    p._recording_cancelled = threading.Event()
    p._queued = None
    return p


def test_a_crash_during_a_cancelled_command_is_not_swallowed():
    p = _bare_pipeline()

    def boom(combine=False):
        raise RuntimeError("the pipeline failed")
    p._run_pipeline = boom
    p._busy.set()
    p._recording_cancelled.set()
    p._queued = "fresh"
    with pytest.raises(RuntimeError, match="the pipeline failed"):
        p._run()
    assert not p._busy.is_set()                # cleanup still ran
    assert not p._recording_cancelled.is_set()
    assert p._queued is None                   # the queued session was dropped, as before


def test_a_cancelled_command_does_not_start_the_queued_one():
    p = _bare_pipeline()
    p._run_pipeline = lambda combine=False: None
    p._recording_cancelled.set()
    p._queued = "fresh"
    p._run()
    assert p._queued is None and not p._busy.is_set()
