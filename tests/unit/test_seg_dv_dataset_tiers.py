"""Size tiers of segmentation's and decompose_validate's generated sets.

Gil, 2026-10-01: "they should be at least 40k with enough variation in the
data … you can have different level of the same dataset as well". Each set has
a `base` tier (the committed file, which must never move), and larger tiers
that are SUPERSETS of it, written to gitignored `tiers/` folders:

    sequence.jsonl / chain.jsonl    base 3,580  -> 10k, 40k   (sequence/tiers.py)
    segmentation generated.jsonl    base 1,549  -> 10k, 40k   (datasets/tiers.py)
    split_traps / nosplit_traps     base 75/87  -> grown (an honest ceiling)
    decompose_validate generated    base 2,884  -> 10k, 40k   (dv datasets/tiers.py)

The default run pins the base files byte for byte and checks a SMOKE draw of
every tier source (a few dozen families each, seconds). Building the full 10k
and 40k tiers takes ~15–45 s per set, so those checks run only with
`MACALENDAR_TIER_TESTS=1`:

    MACALENDAR_TIER_TESTS=1 ./.venv/bin/python -m pytest tests/unit/test_seg_dv_dataset_tiers.py
"""
from __future__ import annotations

import collections
import hashlib
import json
import os

import pytest

from assistant.engine.decompose_validate.datasets import tiers as DVT
from assistant.engine.segmentation.datasets import tiers as SGT
from assistant.engine.segmentation.datasets.sequence import generate as SQ
from assistant.engine.segmentation.datasets.sequence import tiers as SQT
from assistant.engine.segmentation.experiments.run_board import assign_splits

FULL = os.environ.get("MACALENDAR_TIER_TESTS") == "1"
full_only = pytest.mark.skipif(not FULL, reason="full tier build (~2 min); set MACALENDAR_TIER_TESTS=1")

#: the committed base files — (rows, md5). A tier change must never move these.
BASE = {
    SGT.BASE_FILES["generated"]: (1549, "c0213d57656504bd068328e51b7c1364"),
    SGT.BASE_FILES["split_traps"]: (75, "1018015ae6e8e4d01b7f4856fcb15007"),
    SGT.BASE_FILES["nosplit_traps"]: (87, "c4b466326c7f23fe2a5fc00f4d9ab429"),
    SQ.OUT_SEQ: (3580, "5fc3f772be3a0b4dea12636c4a1c87e0"),
    SQ.OUT_CHAIN: (3580, "462cea7a651381015a8f096b8c9f0a9f"),
    DVT.BASE: (2884, "ce4fcebbcb831d0de8ec7b3cd23e3f64"),
}


@pytest.mark.parametrize("path", list(BASE), ids=lambda p: p.name)
def test_base_tier_is_the_committed_file_unchanged(path):
    rows, md5 = BASE[path]
    data = path.read_bytes()
    assert data.count(b"\n") == rows
    assert hashlib.md5(data).hexdigest() == md5, f"{path.name} moved — the base tier must not"


def test_sequence_base_build_is_still_byte_identical():
    seq, chain = SQ.build()
    assert SQ._dump(seq) == SQ.OUT_SEQ.read_text()
    assert SQ._dump(chain) == SQ.OUT_CHAIN.read_text()


def test_tier_folders_are_gitignored():
    ignore = (SGT.HERE.parents[3] / ".gitignore").read_text()
    for d in ("assistant/engine/segmentation/datasets/tiers/",
              "assistant/engine/segmentation/datasets/sequence/tiers/",
              "assistant/engine/decompose_validate/datasets/tiers/",
              "assistant/engine/decompose_validate/datasets/chain/tiers/"):
        assert d in ignore


# ---------------------------------------------------------------------------
# SMOKE draws — every source of every tier, a few dozen families each
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seq_smoke():
    return SQT.draw_all(max_families=90)


def test_sequence_tier_rows_are_new_valid_and_split_by_family(seq_smoke):
    base_seq, base_chain, drawn = seq_smoke
    base_texts = {r["text"].lower() for r in base_seq}
    base_fams = {r["family"] for r in base_seq}
    rows = [(s, c) for _f, groups in drawn for g in groups for s, c in g]
    assert len(rows) > 1500
    texts = [s["text"].lower() for s, _c in rows]
    assert len(texts) == len(set(texts)), "a tier text repeats"
    assert not set(texts) & base_texts, "a tier row copies a base text"
    sides = collections.defaultdict(set)
    for s, c in rows:
        assert s["family"] not in base_fams
        assert s["id"] == c["id"] and s["text"] == c["text"] and s["split"] == c["split"]
        assert s["gold"] and len(s["gold"]) == len(c["gold"])
        for g in s["gold"]:
            assert {"action", "time", "tag", "relation"} <= set(g) and g["action"]
        for g in c["gold"]:
            assert {"kind", "date", "start_time", "end_time", "linked_todo", "chained", "role"} <= set(g)
        if s["decoy"]:
            assert len(s["gold"]) == 1 and s["gold"][0]["relation"] is None
        sides[s["family"]].add(s["split"])
    assert all(len(v) == 1 for v in sides.values())
    by_id = {s["id"]: s for s, _c in rows}
    damaged = [s for s, _c in rows if s["damage"]]
    assert damaged
    for s in damaged:
        twin = by_id[s["twin"]]
        assert json.dumps(twin["gold"]) == json.dumps(s["gold"]) and twin["text"] != s["text"]


def test_every_new_joiner_has_a_train_family():
    fams = SQT.tier_families()
    split = SQ.stratified_split(fams)
    for j in SQT.NEW_JOINERS:
        assert any(split[f[0]] == "train" and f[3] and j in f[3] for f in fams), j


def test_sequence_tier_family_and_skeleton_floor():
    fams = SQT.tier_families()
    assert len(fams) >= 1200                       # structural + sweep + damage + decoy + anchor
    base_sigs = {SQT.signature(f[2], f[3], f[4]) for f in SQ.all_families() if f[2]}
    assert not [f for f in fams if f[2] and SQT.signature(f[2], f[3], f[4]) in base_sigs]


@pytest.fixture(scope="module")
def gen_smoke():
    return SGT.draw_all_generated(max_per_source=12)


def test_generated_tier_rows_validate_and_carry_the_ruling_relabel(gen_smoke):
    base_lines, drawn, report = gen_smoke
    base_rows = [json.loads(line) for line in base_lines]
    base_texts = {r["text"].lower() for r in base_rows}
    rows = [r for _f, rs in drawn for r in rs]
    assert report["grown_base_families"] and report["composed"] and report["own_patterns"]
    texts = [r["text"].lower() for r in rows]
    assert len(texts) == len(set(texts)) and not set(texts) & base_texts
    for r in rows:
        assert set(r) == {"id", "text", "gold", "traps", "source", "family", "atomic"}
        for g in r["gold"]:
            assert g["tag"] in ("event", "task", "review") and g["action"] and g["time"]
        assert SGT.relabel(r["gold"]) == r["gold"], "relabel is idempotent on emitted gold"
    stamped = assign_splits([dict(r) for r in rows])
    sides = collections.defaultdict(set)
    for r in stamped:
        sides[r["family"]].add(r["split"])
    assert all(len(v) == 1 for v in sides.values())


def test_relabel_reproduces_the_committed_gold_for_almost_every_family():
    base = [json.loads(line) for line in SGT.BASE_FILES["generated"].read_text().splitlines()]
    agree, disagree = SGT.agreeing_families(base)
    assert len(agree) >= 255 and len(disagree) <= 4   # 257 / 2 when written (2026-10-02)


def test_composed_families_cut_exactly_at_their_clauses():
    fams = SGT.composed_families()
    assert len(fams) >= 1200
    assert len({f["template"] for f in fams}) == len(fams)
    assert collections.Counter(len(f["clauses"]) for f in fams).keys() >= {2, 3, 4}


@pytest.mark.parametrize("name", ["split_traps", "nosplit_traps"])
def test_grown_trap_tier_is_a_superset_with_hand_written_gold(name):
    lines = SGT.build_traps(name, "grown")
    base = SGT.BASE_FILES[name].read_text().splitlines(keepends=True)
    assert lines[:len(base)] == base
    rows = [json.loads(line) for line in lines]
    assert len(rows) >= len(base) + 25 * len(SGT.trap_templates(name))
    texts = [r["text"].lower() for r in rows]
    assert len(texts) == len(set(texts))
    new = rows[len(base):]
    assert len({r["family"] for r in new}) == len(SGT.trap_templates(name)) >= 29
    sides = collections.defaultdict(set)
    for r in rows:
        sides[r["family"]].add(r["split"])
        assert r["gold"] and all({"action", "time", "tag"} <= set(g) for g in r["gold"])
    assert all(len(v) == 1 for v in sides.values())
    assert {"train", "test"} <= {r["split"] for r in new}


@pytest.fixture(scope="module")
def dv_smoke():
    return DVT.draw_all(max_per_source=12)


def test_dv_tier_rows_are_resolved_new_and_split_by_family(dv_smoke):
    base_lines, drawn, report = dv_smoke
    base_rows = [json.loads(line) for line in base_lines]
    base_split = {r["family"]: r["split"] for r in base_rows}
    base_texts = {r["text"].lower() for r in base_rows}
    rows = [r for _f, rs in drawn for r in rs]
    assert report["grown_base_families"] and report["seg_tier_families"]
    texts = [r["text"].lower() for r in rows]
    assert len(texts) == len(set(texts)) and not set(texts) & base_texts
    sides = collections.defaultdict(set)
    for r in rows:
        assert r["family"] not in base_split or base_split[r["family"]] == r["split"]
        assert len({r["today"]} & {a.isoformat() for a in DVT.DV.GROWN_ANCHORS}) == 1
        for g in r["gold"]:
            assert {"kind", "text", "time", "date", "start_time", "end_time", "recurrence"} <= set(g)
            assert g["date"], "every gold item resolves a date (the floor at least)"
        sides[r["family"]].add(r["split"])
    assert all(len(v) == 1 for v in sides.values())


def test_quota_takes_the_smallest_prefix_that_reaches_the_target():
    drawn = [("a", list(range(10))), ("b", list(range(3))), ("c", list(range(10)))]
    assert SGT.quota(100, drawn, 100, 10) == 0
    assert SGT.quota(100, drawn, 103, 10) == 1
    assert SGT.quota(100, drawn, 109, 10) == 3
    assert SGT.quota(100, drawn, 115, 10) == 6
    with pytest.raises(ValueError):
        SGT.quota(100, drawn, 200, 10)


# ---------------------------------------------------------------------------
# FULL tiers (MACALENDAR_TIER_TESTS=1)
# ---------------------------------------------------------------------------

def _check_full(base_lines, small, big, *, floor_families, key=lambda r: r["text"].lower()):
    assert small[:len(base_lines)] == list(base_lines) and big[:len(base_lines)] == list(base_lines)
    assert len(small) >= 10_000 and len(big) >= 40_000
    assert set(small) <= set(big), "10k must be a subset of 40k"
    rows = [json.loads(line) for line in big]
    tier = rows[len(base_lines):]
    keys = [key(r) for r in tier]
    assert len(keys) == len(set(keys))
    assert len({r["family"] for r in rows}) >= floor_families
    return rows


@full_only
def test_full_sequence_tiers():
    s10, c10 = SQT.build_tier("10k")
    s40, c40 = SQT.build_tier("40k")
    base = SQ._dump(SQ.build()[0]).splitlines(keepends=True)
    small = SQ._dump(s10).splitlines(keepends=True)
    big = SQ._dump(s40).splitlines(keepends=True)
    rows = _check_full(base, small, big, floor_families=1300)
    assert len({r["skeleton"] for r in rows}) >= 5000
    sides = collections.defaultdict(set)
    for r in rows:
        sides[r["family"]].add(r["split"])
    assert all(len(v) == 1 for v in sides.values())
    assert [r["id"] for r in s40] == [r["id"] for r in c40]


@full_only
def test_full_generated_tiers():
    base = SGT.BASE_FILES["generated"].read_text().splitlines(keepends=True)
    rows = _check_full(base, SGT.build_generated("10k"), SGT.build_generated("40k"),
                       floor_families=1500)
    assert len({r["text"].lower() for r in rows}) == len(rows)


@full_only
def test_full_dv_tiers():
    base = DVT.BASE.read_text().splitlines(keepends=True)
    rows = _check_full(base, DVT.build_tier("10k"), DVT.build_tier("40k"), floor_families=1550)
    assert len({(r["text"], r["today"]) for r in rows}) == len(rows)
    sides = collections.defaultdict(set)
    for r in rows:
        sides[r["family"]].add(r["split"])
    assert all(len(v) == 1 for v in sides.values())
