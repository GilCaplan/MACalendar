"""What happens to commands given while the assistant could not answer.

Gil, 2026-09-10: *"have it able to deal with when devices off and queue the
messages locally and talking with the server and other interesting scenarios
that could happen."*

Two queues exist and they are not the same queue:

    the PHONE's   `LocalStore` — the command never reached the Mac at all
    the SERVER's  `pending`    — it arrived, but the model was unreachable

This file is the second one, because it is the one with the ordering,
batching and identity rules. Every scenario here is a thing that can actually
happen to somebody's commands: a flat battery, a tunnel, ollama restarting,
two people in a house, a command nothing can parse.
"""
from __future__ import annotations

import time

import pytest

from assistant.api.server import retry_pending_once


class _Mem:
    """The pending queue, with the real semantics: `pending()` returns live
    rows oldest-first, `bump` increments attempts, `resolve` retires a row."""

    def __init__(self, rows):
        self.rows = rows
        self.resolved: list = []

    def pending(self):
        return [r for r in self.rows if r.get("status", "pending") == "pending"]

    def resolve_pending(self, rid, status, result=""):
        for r in self.rows:
            if r["id"] == rid:
                r["status"] = status
                r["attempts"] = r.get("attempts", 0) + 1
        self.resolved.append((rid, status))

    def bump_pending(self, rid):
        for r in self.rows:
            if r["id"] == rid:
                r["attempts"] = r.get("attempts", 0) + 1


def _row(rid, text, *, device="phone-A", source="ios", attempts=0, ts=None):
    return {"id": rid, "transcript": text, "source": source, "device": device,
            "attempts": attempts, "ts": ts if ts is not None else float(rid),
            "status": "pending"}


def _runner(seen, fail_containing=None):
    def _run(text, **kw):
        seen.append(text)
        if fail_containing and fail_containing in text:
            return {"parse": "error", "message": "could not parse"}
        return {"parse": "fast", "message": "ok"}
    return _run


# ---------------------------------------------------------------------------
# The battery died mid-sentence, and came back
# ---------------------------------------------------------------------------

def test_a_backlog_from_one_device_is_answered_in_the_order_it_was_spoken():
    """Order is not cosmetic here: "book gym at 7" then "actually cancel that"
    means something the reverse does not."""
    rows = [_row(3, "cancel that", ts=300), _row(1, "book gym at 7", ts=100),
            _row(2, "and add milk", ts=200)]
    seen: list = []
    retry_pending_once(_runner(seen), _Mem(rows), 300)
    assert len(seen) == 1                       # one device, one batch
    i_gym, i_milk, i_cancel = (seen[0].index(w) for w in ("gym", "milk", "cancel"))
    assert i_gym < i_milk < i_cancel


def test_a_whole_backlog_is_retired_in_one_pass_when_it_parses():
    rows = [_row(i, t) for i, t in enumerate(("buy milk", "book gym", "call Sam"), 1)]
    mem = _Mem(rows)
    retry_pending_once(_runner([]), mem, 300)
    assert {s for _, s in mem.resolved} == {"done"}
    assert mem.pending() == []


# ---------------------------------------------------------------------------
# One command nobody can parse, sitting in the middle of four good ones
# ---------------------------------------------------------------------------

def test_one_unparseable_command_does_not_take_its_batch_mates_down():
    """THE DEFECT THIS FILE WAS WRITTEN FOR.

    A batch is all-or-nothing: `parse == "error"` bumps EVERY row in it. With
    permanent batching, one bad command meant five collective failures and four
    good commands marked `failed` having never been tried on their own. The
    user loses commands they gave, because of a command they also gave.
    """
    rows = [_row(1, "buy milk"), _row(2, "qqq zzz"), _row(3, "book gym")]
    mem = _Mem(rows)
    seen: list = []
    run = _runner(seen, fail_containing="qqq")

    retry_pending_once(run, mem, 300)           # pass 1: batched, all fail
    assert all(r["attempts"] == 1 for r in rows)

    seen.clear()
    retry_pending_once(run, mem, 300)           # pass 2: individual
    assert len(seen) == 3, "a failed batch was retried as a batch again"
    assert {r["id"] for r in mem.pending()} == {2}, (
        "the good commands were not rescued from the poison one")
    assert dict(mem.resolved).get(1) == "done" and dict(mem.resolved).get(3) == "done"


def test_a_command_nothing_can_parse_is_given_up_on_alone():
    """It must still stop eventually — a row retried forever is a queue that
    never drains — but it must take nothing with it."""
    rows = [_row(1, "qqq zzz", attempts=5), _row(2, "buy milk")]
    mem = _Mem(rows)
    seen: list = []
    retry_pending_once(_runner(seen, fail_containing="qqq"), mem, 300)
    assert ("qqq zzz" not in " ".join(seen)), "a given-up row was run again"
    assert dict(mem.resolved).get(1) == "failed"
    assert "milk" in " ".join(seen)


# ---------------------------------------------------------------------------
# Two people in one house
# ---------------------------------------------------------------------------

def test_two_phones_coming_back_at_once_are_two_conversations():
    rows = [_row(1, "book gym at 7", device="phone-A"),
            _row(2, "cancel my dentist", device="phone-B"),
            _row(3, "buy milk", device="phone-A")]
    seen: list = []
    assert retry_pending_once(_runner(seen), _Mem(rows), 300) == 2
    gym = next(t for t in seen if "gym" in t)
    assert "milk" in gym and "dentist" not in gym


def test_a_phone_and_the_laptop_are_two_conversations():
    rows = [_row(1, "book gym at 7", source="ios", device="phone-A"),
            _row(2, "buy milk", source="mac", device="book-1")]
    seen: list = []
    assert retry_pending_once(_runner(seen), _Mem(rows), 300) == 2


def test_one_phones_poison_command_never_touches_another_phones_queue():
    """The batch rule and the identity rule have to hold at the same time."""
    rows = [_row(1, "qqq zzz", device="phone-A"),
            _row(2, "buy milk", device="phone-B")]
    mem = _Mem(rows)
    retry_pending_once(_runner([], fail_containing="qqq"), mem, 300)
    assert dict(mem.resolved).get(2) == "done", "phone B suffered for phone A"
    assert rows[0]["attempts"] == 1


# ---------------------------------------------------------------------------
# The shapes a live queue actually contains
# ---------------------------------------------------------------------------

def test_an_empty_transcript_never_desynchronises_the_batch_map():
    """Rows map to batch positions by INDEX. An empty transcript that
    `coalesce_groups` silently drops would shift every row after it, and the
    wrong command would be marked done."""
    rows = [_row(1, "buy milk"), _row(2, "   "), _row(3, "book gym")]
    mem = _Mem(rows)
    retry_pending_once(_runner([]), mem, 300)
    done = {rid for rid, st in mem.resolved if st == "done"}
    assert done == {1, 3}


def test_rows_written_before_the_device_column_existed_still_flush():
    """A live queue has rows from before the migration: no `device` key at
    all, not an empty one."""
    rows = [{"id": 1, "transcript": "buy milk", "source": "ios",
             "attempts": 0, "ts": 1.0, "status": "pending"}]
    seen: list = []
    assert retry_pending_once(_runner(seen), _Mem(rows), 300) == 1
    assert seen == ["buy milk"]


def test_an_empty_queue_costs_nothing():
    """The daemon wakes every 30s forever. The common case must not parse."""
    seen: list = []
    assert retry_pending_once(_runner(seen), _Mem([]), 300) == 0
    assert seen == []


def test_a_backlog_too_big_for_one_prompt_runs_as_several():
    """The token budget is a real bound — a day of queued commands cannot be
    one prompt, and the overflow must still all run."""
    rows = [_row(i, f"remind me to do thing number {i} tomorrow at nine")
            for i in range(1, 13)]
    seen: list = []
    mem = _Mem(rows)
    assert retry_pending_once(_runner(seen), mem, 60) > 1
    assert {s for _, s in mem.resolved} == {"done"}
    assert len(mem.resolved) == 12


def test_the_flush_attributes_every_batch_to_a_source_the_engine_knows():
    """`EngineState.source` is "mac"|"ios"|"test". A stream key like
    "ios:phone-A" is not one of them, and it is the value `weekly_review.py`
    filters test traffic on."""
    rows = [_row(1, "buy milk", device="phone-A"),
            _row(2, "book gym", device="phone-B")]
    got: list = []

    def _run(text, **kw):
        got.append(kw.get("source"))
        return {"parse": "fast", "message": "ok"}

    retry_pending_once(_run, _Mem(rows), 300)
    assert set(got) == {"ios"}


# ---------------------------------------------------------------------------
# A person waiting beats a sandbox
# ---------------------------------------------------------------------------

def test_a_real_device_is_served_before_a_test_sandbox():
    """Gil, 2026-09-10: *"real device takes precedence over test, so push real
    device to the front of the queue of requests."*

    A flush runs many batches back to back and each holds the engine's run lock
    for a parse. Iterating a dict meant a sandbox's backlog could sit in front
    of a person's — the phone waiting behind a test, which is backwards.
    """
    rows = [
        _row(1, "sandbox command one", source="test", device="", ts=100),
        _row(2, "sandbox command two", source="test", device="", ts=110),
        _row(3, "book gym at 7", source="ios", device="phone-A", ts=200),
        _row(4, "buy milk", source="mac", device="book-1", ts=300),
    ]
    order: list = []

    def _run(text, **kw):
        order.append(kw.get("source"))
        return {"parse": "fast", "message": "ok"}

    retry_pending_once(_run, _Mem(rows), 300)
    assert order[0] in ("ios", "mac") and order[1] in ("ios", "mac"), (
        f"a test sandbox was served before a real device: {order}")
    assert order[-1] == "test"
    # …and the test rows are DELAYED, never dropped: everything runs this pass.
    assert order.count("test") == 1 and len(order) == 3


def test_real_devices_keep_their_own_order_among_themselves():
    """Priority orders the CLASSES, not the people. Two real devices are still
    served oldest-first — inventing a rank between two people would be a guess."""
    rows = [
        _row(1, "buy milk", source="ios", device="phone-B", ts=300),
        _row(2, "book gym", source="ios", device="phone-A", ts=100),
        _row(3, "sandbox", source="test", device="", ts=50),
    ]
    order: list = []

    def _run(text, **kw):
        order.append(text)
        return {"parse": "fast", "message": "ok"}

    retry_pending_once(_run, _Mem(rows), 300)
    assert order.index("book gym") < order.index("buy milk")
    assert order[-1] == "sandbox"
