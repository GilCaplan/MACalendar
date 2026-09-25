"""A Board D run is rescored from its checkpoint, never re-run for a new metric.

Gil, 2026-09-25: *"We save checkpoints so why compute from 0, can just
calculate metric scores on existing results."* Three things make a rescore
honest: it names the commit the rows were produced by, it skips a row whose
text is no longer in the dataset instead of scoring it against gold it was not
run on, and a legacy checkpoint's missing fields print as not recorded rather
than as a zero.
"""
from __future__ import annotations

import json
import os

import pytest


@pytest.fixture(scope="module")
def R():
    """`rescore` imports `board_d`, a script with an env block — imported under
    a saved-and-restored environment (see `test_board_d_scorer.py`)."""
    saved = dict(os.environ)
    os.environ.setdefault("BOARD_D_SCRATCH",
                          os.path.join(os.environ.get("TMPDIR", "/tmp"), "board_d_rescore_test"))
    try:
        from assistant.engine.llmjudge.experiments import rescore as mod
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return mod


def _one_create_event(R):
    for line in R.D.DATA.open(encoding="utf-8"):
        r = json.loads(line)
        e = r["expect"]
        if e.get("action") == "create_event" and int(e.get("events") or 0) == 1 \
                and (e.get("slots") or {}).get("title"):
            return r
    raise AssertionError("no single create_event row in the FastRule set")


def _write(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"git_head": "abc12345", "git_dirty": False,
                             "started": "2026-09-25 10:00:00"}) + "\n")
        for k, v in rows:
            fh.write(json.dumps({"k": k, "v": v, "t": "2026-09-25 10:00:01"}) + "\n")


def test_full_checkpoint_is_scored_and_a_stale_row_skipped(R, tmp_path, capsys):
    r = _one_create_event(R)
    title = r["expect"]["slots"]["title"]
    pair = [["create_event", title.lower()]]
    obj = {"action": "create_event", "title": title, "date": None, "due_date": None,
           "start_time": None, "end_time": None, "recurrence": None, "reminder_minutes": None}
    path = tmp_path / "run.jsonl"
    _write(path, [
        (str(r["id"]), {"off": pair, "on": pair, "text": r["text"], "ms_on": 9,
                        "objs_on": [obj], "llm_ms_on": 0}),
        (str(r["id"]) + "-gone", {"off": [], "on": [], "text": "no such row"}),
    ])
    got = R.rescore(str(path))
    out = capsys.readouterr().out
    assert got["n"] == 1 and got["stale"] == 1 and got["full"]
    assert "abc12345" in out
    assert got["metrics"]["counts"]["title_exact"] == 1


def test_a_legacy_checkpoint_says_what_it_cannot_score(R, tmp_path, capsys):
    r = _one_create_event(R)
    pair = [["create_event", r["expect"]["slots"]["title"].lower()]]
    path = tmp_path / "legacy.jsonl"
    _write(path, [(str(r["id"]), {"off": pair, "on": pair, "text": r["text"], "ms_on": 9})])
    got = R.rescore(str(path))
    out = capsys.readouterr().out
    c = got["metrics"]["counts"]
    assert not got["full"] and "LEGACY" in out
    assert c["title_n"] == 1                       # the pairs carry the title
    assert c.get("date_n", 0) == 0 and c.get("time_n", 0) == 0 and c.get("rows", 0) == 0
