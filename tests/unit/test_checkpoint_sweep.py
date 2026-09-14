"""The checkpoint sweep's row loading and its personas scorer.

The sweep costs ~30 hours of machine across two boards, so its scorer is
exactly the kind of thing that must not be discovered broken afterwards.
These tests need no model: the personas scorer reads a run's `examples` table,
so a fabricated table exercises every branch of the predicate in milliseconds.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from scripts import checkpoint_sweep as cs


def _db(tmp_path, rows):
    """A minimal `examples` table — the shape the scorer actually reads."""
    p = tmp_path / "engine_run.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE examples (id INTEGER PRIMARY KEY, ts REAL, "
                  "raw_transcript TEXT, transcript TEXT, parse_path TEXT, "
                  "actions_json TEXT, total_ms INTEGER)")
        for i, (text, actions, path, ms) in enumerate(rows, 1):
            c.execute("INSERT INTO examples VALUES (?,?,?,?,?,?,?)",
                      (i, 0.0, text, text, path, json.dumps(actions), ms))
    return p


def _persona_row(text, events, tasks, tier="simple", persona="retiree"):
    return {"id": f"{persona}:x:{text[:4]}", "text": text, "tier": tier,
            "persona": persona, "family": "f",
            "expect": {"events": events, "tasks": tasks}, "gold": {}, "ts": None}


def _ev(title="gym"):
    return {"action": "create_event", "parameters": {"title": title,
                                                     "date": "2026-09-11",
                                                     "start_time": "07:00"}}


def _todo(*titles):
    return {"action": "create_todo", "parameters": {"titles": list(titles)}}


# --- the predicate ---------------------------------------------------------

def test_exact_match_counts_as_correct(tmp_path):
    db = _db(tmp_path, [("book gym", [_ev()], "fast", 100)])
    out = cs._score_personas(db, [_persona_row("book gym", 1, 0)])
    assert out["overall"]["count_ok_rate"] == 1.0


def test_under_production_fails(tmp_path):
    """The (2,1) case score_db's buckets cannot express: two events were
    asked for and one was made. Shoehorning this into "event+task" would
    have PASSED it, which is why the predicate is reproduced rather than
    the plumbing reused."""
    db = _db(tmp_path, [("two things", [_ev(), _todo("milk")], "deep", 100)])
    out = cs._score_personas(db, [_persona_row("two things", 2, 1)])
    assert out["overall"]["count_ok_rate"] == 0.0


def test_meeting_a_two_event_ask_passes(tmp_path):
    db = _db(tmp_path, [("two things", [_ev("a"), _ev("b"), _todo("milk")],
                         "deep", 100)])
    out = cs._score_personas(db, [_persona_row("two things", 2, 1)])
    assert out["overall"]["count_ok_rate"] == 1.0


def test_a_query_must_create_nothing(tmp_path):
    """656 of the 2,520 rows expect neither an event nor a task — queries,
    deletes, completions. score_db's own reading for query/remove: the claim
    is that nothing was CREATED, not that the delete found its target."""
    db = _db(tmp_path, [("what's on today", [], "fast", 50),
                        ("what's on friday", [_ev()], "deep", 50)])
    out = cs._score_personas(db, [_persona_row("what's on today", 0, 0),
                                  _persona_row("what's on friday", 0, 0)])
    assert out["overall"]["count_ok_rate"] == 0.5


def test_over_production_on_a_creation_still_passes(tmp_path):
    """`>=`, matching score_db's min_events/min_tasks semantics — excess is
    an item-precision question, not a count-correctness one."""
    db = _db(tmp_path, [("book gym", [_ev("a"), _ev("b")], "deep", 100)])
    out = cs._score_personas(db, [_persona_row("book gym", 1, 0)])
    assert out["overall"]["count_ok_rate"] == 1.0


# --- the breakdowns --------------------------------------------------------

def test_rows_the_run_never_reached_are_not_counted(tmp_path):
    """A checkpoint that dies halfway must report n over what it ACTUALLY
    ran, or a truncated run reads as a perfect one."""
    db = _db(tmp_path, [("done", [_ev()], "fast", 10)])
    out = cs._score_personas(db, [_persona_row("done", 1, 0),
                                  _persona_row("never ran", 1, 0)])
    assert out["overall"]["n"] == 1


def test_the_persona_spread_is_broken_out(tmp_path):
    db = _db(tmp_path, [("a", [_ev()], "fast", 10),
                        ("b", [], "deep", 10)])
    rows = [_persona_row("a", 1, 0, persona="retiree"),
            _persona_row("b", 1, 0, persona="uni_student")]
    out = cs._score_personas(db, rows)
    assert out["by_persona"]["retiree"]["count_ok_rate"] == 1.0
    assert out["by_persona"]["uni_student"]["count_ok_rate"] == 0.0


def test_garbage_titles_are_flagged(tmp_path):
    db = _db(tmp_path, [("x", [_todo("then")], "fast", 10)])
    out = cs._score_personas(db, [_persona_row("x", 0, 1)])
    assert out["overall"]["garbage_title_rate"] == 1.0


# --- row loading -----------------------------------------------------------

def test_the_personas_sample_is_stratified():
    """The SPREAD between voices is the finding, so an uneven draw hides it."""
    rows = cs._load_personas(300)
    assert len(rows) == 300
    by_persona = {}
    for r in rows:
        by_persona[r["persona"]] = by_persona.get(r["persona"], 0) + 1
    assert len(by_persona) == 6
    assert set(by_persona.values()) == {50}


def test_the_personas_sample_is_deterministic():
    """Two sweeps must compare the same rows — the data fingerprint asserts
    it, but only if the draw does not move."""
    assert [r["id"] for r in cs._load_personas(60)] == \
           [r["id"] for r in cs._load_personas(60)]


def test_personas_carry_no_timestamp():
    """They are not a history, so there is no recorded moment to freeze to —
    the clock stays live rather than being frozen to an invented one."""
    assert all(r["ts"] is None for r in cs._load_personas(30))


def test_the_personas_draw_is_representative_of_the_full_set():
    """The first sampler bucketed by (persona, tier) and walked each bucket in
    id order. Ids cluster by structure family, so it drew the same few families
    repeatedly: 49% two-event compounds against 6% in the full set, and ZERO
    queries or task-only rows against 42%. Every checkpoint was measured on
    identical rows, so the comparison held — but it was a board about two-event
    compounds wearing the label "six speaking styles".

    A board is only named honestly if its sample looks like the thing it names.
    """
    import collections
    import json
    import pathlib

    full = [json.loads(l) for l in
            pathlib.Path("dataset/personas/personas.jsonl").read_text().splitlines()
            if l.strip()]
    draw = cs._load_personas(300)

    def shape(rows):
        c = collections.Counter(
            (int((r.get("expect") or {}).get("events") or 0),
             int((r.get("expect") or {}).get("tasks") or 0)) for r in rows)
        return {k: v / len(rows) for k, v in c.items()}

    want, got = shape(full), shape(draw)
    for key, share in want.items():
        if share < 0.02:            # a cell that rare cannot be held to a point
            continue
        assert abs(got.get(key, 0) - share) < 0.06, (
            f"ask-shape {key} is {got.get(key, 0):.0%} of the draw but {share:.0%} "
            "of the personas set — the sample is not representative")


def test_every_voice_gets_an_equal_share():
    """The SPREAD between personas is what this board measures — 72.2% for the
    persona who talks like Gil against 33.9% for a terse student. A draw giving
    one voice twice another's rows reports that spread through a sampling
    artefact. The flat round-robin did exactly that: 66 rows for the
    alphabetically-early voices, 33 for the late ones."""
    import collections
    draw = cs._load_personas(300)
    counts = collections.Counter(r["persona"] for r in draw)
    assert len(counts) == 6, f"expected six voices, got {sorted(counts)}"
    assert len(set(counts.values())) == 1, (
        f"voices are unbalanced: {dict(counts)} — the persona spread would be "
        "partly a sampling artefact")


def test_the_draw_spans_every_structure():
    """Structure is what varies the ASK; persona is what varies the VOICE. A
    sample has to span both or it measures neither."""
    import json
    import pathlib
    full = [json.loads(l) for l in
            pathlib.Path("dataset/personas/personas.jsonl").read_text().splitlines()
            if l.strip()]
    all_structures = {r.get("structure") for r in full}
    drawn = {r.get("structure") for r in cs._load_personas(300)}
    assert drawn == all_structures, f"missing structures: {sorted(all_structures - drawn)}"
