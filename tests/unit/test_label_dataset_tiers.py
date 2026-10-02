"""The label datasets' size tiers (2026-10-01): base / 20k / 40k.

Gil: *"they should be at least 40k with enough variation in the data"* and
*"you can have different level of the same dataset as well"*. What this pins:

  * the committed `base` files are what the generator still writes, byte for
    byte — the shipped base model is fitted from them;
  * every tier is a SUPERSET of the one below, rows identical and in order, so
    a number read on 20k is a number on a prefix of 40k;
  * the top tier holds >= 40,000 rows per set, every text distinct, from new
    MATERIAL (frames and subjects no base list holds) rather than the base
    frames refilled, with floors on distinct frames and subjects;
  * the vocabulary split holds: no subject on both sides, and no base row moves
    split;
  * no personal data — no generator reads `~/.assistant_tools`.

Building one tier in memory takes about a second, so the 40k tier is tested
directly rather than behind a slow marker.
"""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib

import pytest

from assistant.engine.label.datasets import generate as G
from assistant.engine.label.datasets import tier_banks as B

#: The committed base files, as of the commit that introduced tiers.
BASE = {"event": (14_692, "709a04052448d88b57342c70093c2969"),
        "task": (3_800, "bef27f5b7d879783eb8319d1437d7a0b")}

#: Diversity floors for the 40k tier — a drop below any of these means the
#: banks shrank or the builder started repeating itself.
FLOORS = {"event": {"frames": 150, "subjects": 1_700, "classes": 14},
          "task": {"frames": 120, "subjects": 600, "classes": 6}}


def _dump(rows) -> bytes:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()


@pytest.fixture(scope="module")
def tiers():
    return {(k, t): G.build_tier(k, t) for k in ("event", "task") for t in G.TIER_ORDER}


@pytest.mark.parametrize("kind", ["event", "task"])
def test_base_is_byte_identical_to_the_committed_file(kind, tiers):
    n, md5 = BASE[kind]
    committed = G.tier_path(kind, "base").read_bytes()
    assert hashlib.md5(committed).hexdigest() == md5, "the committed base file changed"
    rebuilt = _dump(tiers[(kind, "base")])
    assert len(tiers[(kind, "base")]) == n
    assert hashlib.md5(rebuilt).hexdigest() == md5, \
        "the generator no longer reproduces the committed base tier byte for byte"


@pytest.mark.parametrize("kind", ["event", "task"])
def test_each_tier_is_a_superset_of_the_one_below(kind, tiers):
    for lo, hi in zip(G.TIER_ORDER, G.TIER_ORDER[1:]):
        small, big = tiers[(kind, lo)], tiers[(kind, hi)]
        assert len(big) > len(small)
        assert big[:len(small)] == small, f"{hi} does not start with {lo}, unchanged"


@pytest.mark.parametrize("kind", ["event", "task"])
def test_tiers_meet_their_size_and_have_no_duplicate_texts(kind, tiers):
    for tier, minimum in G.TIERS.items():
        rows = tiers[(kind, tier)]
        if minimum is not None:
            assert len(rows) >= minimum, f"{kind} {tier}: {len(rows)} < {minimum}"
        assert len({r["text"] for r in rows}) == len(rows), f"{kind} {tier} has duplicate texts"
    assert len(tiers[(kind, "40k")]) >= 40_000


@pytest.mark.parametrize("kind", ["event", "task"])
def test_top_tier_has_real_variation(kind, tiers):
    rows = tiers[(kind, "40k")]
    s = G.tier_stats(rows, kind)
    f = FLOORS[kind]
    assert s["distinct_frames"] >= f["frames"]
    assert s["distinct_subjects"] >= f["subjects"]
    assert len(s["per_class"]) >= f["classes"]
    # one row per (frame, subject) among the new rows: no template refilled
    pairs = collections.Counter((r["frame"], r["subject"]) for r in rows if "frame" in r)
    assert max(pairs.values()) == 1
    # the subject cap holds on the new rows
    per_subj = collections.Counter(r["subject"] for r in rows if "frame" in r)
    assert max(per_subj.values()) <= G.SUBJECT_CAP[kind]
    # a BASE subject only ever gets a NEW frame
    base_frames = set(G.EVENT_FRAMES if kind == "event" else G.TASK_FRAMES)
    base_subj = {r["subject"] for r in tiers[(kind, "base")]}
    assert not [r for r in rows if "frame" in r and r["subject"] in base_subj
                and r["frame"] in base_frames]
    # balance: no class carries more than twice another's rows
    counts = s["per_class"].values()
    assert max(counts) <= 2 * min(counts), s["per_class"]


@pytest.mark.parametrize("kind", ["event", "task"])
def test_vocabulary_split_holds_and_no_base_row_moves(kind, tiers):
    base_split = {r["subject"]: r["split"] for r in tiers[(kind, "base")]}
    for tier in G.TIER_ORDER:
        rows = tiers[(kind, tier)]
        tr = {r["subject"] for r in rows if r["split"] == "train"}
        te = {r["subject"] for r in rows if r["split"] == "test"}
        assert not (tr & te), f"{kind} {tier}: subjects on both sides {sorted(tr & te)[:5]}"
        moved = [r["subject"] for r in rows
                 if r["subject"] in base_split and r["split"] != base_split[r["subject"]]]
        assert not moved, f"{kind} {tier}: base subjects changed split {moved[:5]}"
        share = len(te) / (len(tr) + len(te))
        assert 0.2 < share < 0.4, f"{kind} {tier}: test subject share {share:.2f}"


def test_new_banks_are_new_material():
    for old, new in ((G.EVENT_SUBJECTS, B.EVENT_SUBJECTS_EXT),
                     (G.TASK_SUBJECTS, B.TASK_SUBJECTS_EXT)):
        olds = {s for v in old.values() for s in v}
        news = [s for v in new.values() for s in v]
        assert len(news) == len(set(news)), "a new subject is listed twice"
        assert not (set(news) & olds), sorted(set(news) & olds)
    assert not set(B.EVENT_FRAMES_EXT) & set(G.EVENT_FRAMES)
    assert not set(B.TASK_FRAMES_EXT) & set(G.TASK_FRAMES)
    for subj, labels in B.TASK_MULTI_EXT.items():
        homes = [t for t, v in B.TASK_SUBJECTS_EXT.items() if subj in v]
        assert len(homes) == 1 and homes[0] in labels, subj


def test_damage_never_touches_the_subject(tiers):
    for kind in ("event", "task"):
        for r in tiers[(kind, "40k")]:
            assert r["subject"] in r["text"], r


def test_tiers_are_deterministic():
    assert G.build_tier("task", "20k") == G.build_tier("task", "20k")


def test_generator_reads_no_personal_store():
    """The banks are hand-written and generic; nothing reaches for the user's
    stores (the personal vocabulary holds real people and places)."""
    for name in ("generate.py", "tier_banks.py"):
        src = (G.HERE / name).read_text()
        for reach in ("expanduser", "Path.home", "personal_store", "users.paths",
                      "MACALENDAR_VOCAB", "open(os.path"):
            assert reach not in src, f"{name} reaches for {reach}"


def test_load_rows_builds_a_missing_tier_and_rebuilds_a_stale_one(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "TIERS_DIR", tmp_path / "tiers")
    with pytest.raises(FileNotFoundError, match="--tier 20k"):
        G.dataset_path("task", "20k", build=False)
    rows = G.load_rows("task", "20k")
    assert len(rows) >= 20_000
    man = tmp_path / "tiers" / "20k" / "MANIFEST.json"
    m = json.loads(man.read_text())
    m["fingerprint"] = "stale"
    man.write_text(json.dumps(m))
    with pytest.raises(FileNotFoundError):
        G.dataset_path("task", "20k", build=False)
    assert G.load_rows("task", "20k") == rows
    # base is always the committed file, never the tiers folder
    assert G.dataset_path("event", "base") == G.EVENTS_OUT
    with pytest.raises(ValueError):
        G.load_rows("event", "80k")


def test_loaders_default_to_base():
    """Every label loader takes a tier and defaults to the committed base."""
    import inspect
    from assistant.engine.label import train as T
    from assistant.engine.label.experiments import classifier_board, rebuild_board
    for fn in (T._load, T._subjects, T.train, T.train_base,
               classifier_board.load_events, classifier_board.load_tasks):
        assert inspect.signature(fn).parameters["data_tier"].default == "base", fn
    assert rebuild_board.DATA_TIER == "base"
    tr, te = T._load("event")
    assert len(tr) + len(te) == BASE["event"][0]


def test_tier_folder_is_gitignored():
    root = pathlib.Path(__file__).resolve().parents[2]
    assert "assistant/engine/label/datasets/tiers/" in (root / ".gitignore").read_text()
