"""The FastRule set's SIZE TIERS (Gil, 2026-10-01: "at least 40k with enough
variation"; "different level of the same dataset ... let user choose").

`assistant/engine/fastrule/datasets/growth.py` grows the committed 8,700-row
base into 20k / 40k / 80k supersets from new hand-written constructions. What
these tests hold it to:

  * BASE IS UNTOUCHED — the committed file's row count and content hash, and a
    regeneration reproduces it byte for byte (it is the 20k file's prefix).
  * SUPERSET — each tier's file begins with the smaller tier's bytes.
  * VARIATION — no duplicate text, a floor on distinct families, a cap on any
    one family's share, every growth row carrying the base set's gold fields.
  * THE SPLIT — the base test families are exactly what they were, no growth
    row joins one, and no family or construction sits on both sides.

Generating the 20k tier takes ~25 s (base is ~13 s of it), so it is built once
per module. The 40k and 80k tiers take ~50 s and ~90 s: those tests run only
with MACALENDAR_SLOW_TIERS=1.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
from collections import Counter, defaultdict

import pytest

from assistant.engine.fastrule.datasets import tiers

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE_ROWS = 8_700
#: md5 of the committed fastrule_7200.jsonl. A deliberate regeneration of base
#: moves this — and is a change to the board of record, so it should be loud.
BASE_MD5 = "29f3d9c1a8ad4ea79e561c5e5b7ee4ac"

SLOW = os.environ.get("MACALENDAR_SLOW_TIERS") == "1"
slow = pytest.mark.skipif(not SLOW, reason="40k/80k generation is slow; set MACALENDAR_SLOW_TIERS=1")

GOLD_KEYS = {"id", "text", "split", "tier", "family", "expect"}
EXPECT_KEYS = {"events", "tasks", "action", "atomic", "slots", "item"}


def _build(size: str, out: pathlib.Path) -> bytes:
    env = dict(os.environ, MACALENDAR_LLM_PRIORITY="background")
    subprocess.run([sys.executable, "-m", "assistant.engine.fastrule.datasets.generate",
                    "--size", size, "--out", str(out)],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    return out.read_bytes()


@pytest.fixture(scope="module")
def tier_bytes(tmp_path_factory):
    cache: dict[str, bytes] = {}

    def get(size: str) -> bytes:
        if size not in cache:
            cache[size] = _build(size, tmp_path_factory.mktemp("tiers") / f"{size}.jsonl")
        return cache[size]
    return get


def _rows(blob: bytes) -> list[dict]:
    return [json.loads(line) for line in blob.decode("utf-8").splitlines() if line.strip()]


def _base_bytes() -> bytes:
    return tiers.path("base").read_bytes()


# --------------------------------------------------------------------------
# no generation needed
# --------------------------------------------------------------------------

def test_base_file_is_unchanged():
    blob = _base_bytes()
    assert len(blob.splitlines()) == BASE_ROWS
    assert hashlib.md5(blob).hexdigest() == BASE_MD5


def test_size_menu():
    assert tiers.SIZES[0] == "base" and tiers.path("base").name == "fastrule_7200.jsonl"
    assert max(tiers.SIZES_ROWS.values()) >= 40_000
    assert tiers.SIZES_ROWS["40k"] >= 40_000
    rows = list(tiers.SIZES_ROWS.values())
    assert rows == sorted(rows), "sizes must grow in superset order"
    for size in tiers.SIZES[1:]:
        assert tiers.path(size).parent.name == "tiers"


def test_tier_files_are_gitignored():
    ignore = (ROOT / ".gitignore").read_text()
    assert "assistant/engine/fastrule/datasets/tiers/" in ignore


# --------------------------------------------------------------------------
# the 20k tier (built once, ~25 s)
# --------------------------------------------------------------------------

def _check_tier(size: str, blob: bytes, family_floor: int) -> None:
    rows = _rows(blob)
    assert len(rows) == tiers.SIZES_ROWS[size]
    texts = [r["text"] for r in rows]
    assert len(set(texts)) == len(texts), "duplicate texts"
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids), "duplicate ids"

    fams = Counter(r["family"] for r in rows)
    assert len(fams) >= family_floor, f"only {len(fams)} distinct families"
    growth = rows[BASE_ROWS:]
    gfams = Counter(r["family"] for r in growth)
    # no growth family is a big denominator: none over 0.5% of its tier
    assert max(gfams.values()) <= 0.005 * len(rows), gfams.most_common(1)

    for r in growth:
        assert GOLD_KEYS <= set(r), r["id"]
        e = r["expect"]
        assert EXPECT_KEYS <= set(e), r["id"]
        assert {"text", "time", "kind"} <= set(e["item"]), r["id"]
        for i in range(1, e["events"] + 1):
            assert ("category" if i == 1 else f"category_{i}") in e["slots"], r["id"]
        for i in range(1, e["tasks"] + 1):
            assert ("tags" if i == 1 else f"tags_{i}") in e["slots"], r["id"]
        if e["events"] or e["tasks"]:
            assert e["slots"].get("title"), r["id"]

    # the split: every family and every construction on ONE side
    side = defaultdict(set)
    for r in rows:
        side[r["family"]].add(r["split"])
    assert not [f for f, s in side.items() if len(s) > 1]
    cons = defaultdict(set)
    for r in growth:
        for part in r["construction"].split("+"):
            cons[part].add(r["split"])
    assert not [c for c, s in cons.items() if len(s) > 1]

    # base test families: exactly as committed, and no growth row joins one
    base_rows = _rows(_base_bytes())
    base_test = {r["family"] for r in base_rows if r["split"] == "test"}
    assert {r["family"] for r in rows[:BASE_ROWS] if r["split"] == "test"} == base_test
    assert not {r["family"] for r in growth} & {r["family"] for r in base_rows}

    # growth is ~80/20 by rows, as each level is built
    split = Counter(r["split"] for r in growth)
    assert abs(split["test"] / len(growth) - 0.2) < 0.005


def test_20k_starts_with_base_byte_for_byte(tier_bytes):
    """Also proves a raw regeneration reproduces the committed base exactly —
    it did NOT before 2026-10-01: with a users.json in ~/.assistant_tools the
    category fixture path was re-rooted into the admin's folder and 240 rows
    came out with default categories."""
    base = _base_bytes()
    blob = tier_bytes("20k")
    assert blob[:len(base)] == base


def test_20k_tier(tier_bytes):
    _check_tier("20k", tier_bytes("20k"), family_floor=619 + 800)


# --------------------------------------------------------------------------
# the top tiers (opt-in)
# --------------------------------------------------------------------------

@slow
def test_40k_tier_is_a_superset_and_varied(tier_bytes):
    blob = tier_bytes("40k")
    assert blob.startswith(tier_bytes("20k"))
    assert len(blob.splitlines()) >= 40_000
    _check_tier("40k", blob, family_floor=619 + 2_300)


@slow
def test_80k_tier_is_a_superset(tier_bytes):
    blob = tier_bytes("80k")
    assert blob.startswith(tier_bytes("40k"))
    _check_tier("80k", blob, family_floor=619 + 2_300)
