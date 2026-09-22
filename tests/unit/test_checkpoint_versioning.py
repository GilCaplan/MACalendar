"""A checkpoint has no idea what CODE produced its cached rows — `has()`/
`get()` are a bare id lookup. `board_d_overnight.jsonl` (2026-09-11) read
back as an ordinary cache hit on 2026-09-15 and was actually scored against
`objects.py`, the FastRule module a same-day merge had already retired —
three thousand rows of a system that no longer existed, presented as a
measurement of the one running. This is the fix: stamp the git commit a
checkpoint was recorded under, and warn loudly (never silently) on a
mismatch when it is resumed.
"""
from __future__ import annotations

import json

import pytest

import assistant.checkpoint as ckmod
from assistant.checkpoint import Checkpoint


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(ckmod, "CHECKPOINT_DIR", tmp_path)
    monkeypatch.setattr(ckmod, "_git_dirty", lambda: False)
    return tmp_path


def _stamp(monkeypatch, head):
    monkeypatch.setattr(ckmod, "_git_head", lambda: head)


def test_a_fresh_checkpoint_is_stamped_with_the_current_commit(scratch, monkeypatch):
    _stamp(monkeypatch, "abc123")
    Checkpoint("t").record("a", 1)
    rows = [json.loads(l) for l in (scratch / "t.jsonl").read_text().splitlines() if l.strip()]
    assert {k: v for k, v in rows[0].items() if k != "started"} == {"git_head": "abc123", "git_dirty": False}


def test_resuming_at_the_same_commit_is_silent(scratch, monkeypatch, capsys):
    _stamp(monkeypatch, "abc123")
    Checkpoint("t").record("a", 1)
    capsys.readouterr()

    Checkpoint("t")
    out = capsys.readouterr().out
    assert "WARNING" not in out


def test_resuming_at_a_different_commit_warns_loudly(scratch, monkeypatch, capsys):
    _stamp(monkeypatch, "abc123")
    Checkpoint("t").record("a", 1)
    capsys.readouterr()

    _stamp(monkeypatch, "def456")
    Checkpoint("t")
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "abc123"[:10] in out
    assert "def456"[:10] in out


def test_a_mismatch_warns_but_does_not_refuse_to_resume(scratch, monkeypatch):
    """This project flags, it does not block — the same rule that lets a
    command commit with an honest note instead of being silently refused."""
    _stamp(monkeypatch, "abc123")
    Checkpoint("t").record("a", 1)

    _stamp(monkeypatch, "def456")
    resumed = Checkpoint("t")
    assert resumed.has("a")
    assert resumed.get("a") == 1


def test_an_old_checkpoint_with_no_stamp_is_left_alone(scratch, monkeypatch, capsys):
    """A file written before this feature existed has no meta line at all —
    it must resume exactly as it always did, with nothing retrofitted and no
    warning fabricated from an absence."""
    (scratch / "t.jsonl").write_text('{"k": "a", "v": 1}\n')
    _stamp(monkeypatch, "abc123")

    resumed = Checkpoint("t")
    out = capsys.readouterr().out
    assert "WARNING" not in out
    assert resumed.has("a")


def test_no_git_available_degrades_to_no_stamp_and_no_crash(scratch, monkeypatch):
    """A checkpoint must work in a stray sandbox with no `git` on PATH exactly
    as well as it does in the repo — this is bookkeeping, not the measurement."""
    _stamp(monkeypatch, None)
    monkeypatch.setattr(ckmod, "_git_dirty", lambda: None)

    ck = Checkpoint("t")
    ck.record("a", 1)                       # must not raise
    rows = [json.loads(l) for l in (scratch / "t.jsonl").read_text().splitlines() if l.strip()]
    assert [{k: v for k, v in r.items() if k != "t"} for r in rows] == [{"k": "a", "v": 1}]     # no stamp line when head is unknown
