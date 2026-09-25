"""The Q51 sequence/chain dataset: deterministic, family-split, decoys single.

The generator is `assistant/engine/segmentation/datasets/sequence/generate.py`;
it writes `sequence.jsonl` (segmentation) and `chain.jsonl`
(decompose_validate) from one construction. These tests pin the properties the
boards rely on: a rebuild is byte-identical (and matches what is committed), no
family straddles the split, a decoy is ONE item, and a damaged row carries
exactly its clean twin's gold.
"""
from __future__ import annotations

import collections
import json

import pytest

from assistant.engine.segmentation.datasets.sequence import generate as G


@pytest.fixture(scope="module")
def built():
    return G.build()


def test_generator_is_deterministic(built):
    again = G.build()
    assert G._dump(built[0]) == G._dump(again[0])
    assert G._dump(built[1]) == G._dump(again[1])


def test_committed_files_are_current(built):
    assert G.OUT_SEQ.read_text() == G._dump(built[0]), \
        "sequence.jsonl is stale — rerun the generator"
    assert G.OUT_CHAIN.read_text() == G._dump(built[1]), \
        "chain.jsonl is stale — rerun the generator"


def test_no_family_on_both_sides(built):
    sides = collections.defaultdict(set)
    for r in built[0]:
        sides[r["family"]].add(r["split"])
    assert all(len(s) == 1 for s in sides.values())
    assert {"train", "test"} == {s for v in sides.values() for s in v}


def test_decoys_have_exactly_one_item(built):
    seq, chain = built
    decoys = [r for r in seq if r["decoy"]]
    assert decoys
    assert all(len(r["gold"]) == 1 and r["gold"][0]["relation"] is None for r in decoys)
    assert all(len(r["gold"]) == 1 for r in chain if r["decoy"])


def test_the_two_files_hold_the_same_rows(built):
    seq, chain = built
    assert [r["id"] for r in seq] == [r["id"] for r in chain]
    for s, c in zip(seq, chain):
        assert s["text"] == c["text"] and s["split"] == c["split"]
        assert [g["action"] for g in s["gold"]] == [g["action"] for g in c["gold"]]


def test_damaged_rows_carry_their_clean_twins_gold(built):
    seq = {r["id"]: r for r in built[0]}
    damaged = [r for r in seq.values() if r["damage"]]
    assert damaged
    for r in damaged:
        twin = seq[r["twin"]]
        assert twin["family"] == r["family"] and not twin["damage"]
        assert twin["text"] != r["text"]
        assert json.dumps(twin["gold"]) == json.dumps(r["gold"])


def test_q51_worked_examples_resolve_as_ruled():
    """The rule, on the dataset's own resolver: a chain beats a meal hour, a
    stated clock wins and the chain continues from it."""
    chain = [json.loads(l) for l in G.OUT_CHAIN.read_text().splitlines()]
    reset = [r for r in chain if r["family"] == "s4_clock_resets"]
    assert reset
    for r in reset:
        g = r["gold"]
        assert g[1]["start_time"] == g[0]["end_time"]          # chained off the first
        assert g[3]["start_time"] == g[2]["end_time"]          # chained off the stated clock
        assert g[1]["chained"] and not g[2]["chained"]
