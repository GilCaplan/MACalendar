"""Size tiers for the judge, persona and real-speech sets (2026-10-01).

Gil: *"a lot of the datasets seem really small, they should be at least 40k
with enough variation in the data"* and *"you can have different level of the
same dataset as well, sometimes can let user choose"*. `scripts/dataset_tiers.py`
is the convention; what this file pins, per set:

    BASE UNCHANGED   the committed file's row count and md5 — every recorded
                     number was measured on it, and a grown tier must not be
                     a back door to rewriting it;
    SUPERSET         base bytes first, then grown rows, and every 10k row is a
                     40k row (in order), so no row ever changes id, split or
                     gold between tiers;
    >= 40,000        rows in the top tier (for the v2 pair: COMMANDS; the case
                     file is whatever they plant, ~2x);
    NO DUPLICATES    no repeated text (the ablation dedupes per cell, as base
                     does);
    DIVERSITY        floors on distinct families / grammars / voices /
                     registers / personas — a row count is not variation;
    GOLD             the gold fields every board reads are present;
    SPLIT            no family on both sides, base families keep their split,
                     and every persona row is TEST.

The command, persona and real-speech tiers build in memory in a few seconds, so
their 40k tier is tested directly. The two CASE tiers run the converter over
every grown command (~20 min for v1, ~50 min for v2) and are never built here:
their generator-side prefix property is tested on the sources, and the files
themselves are checked when they are present (skipped otherwise — CI has none).
"""
from __future__ import annotations

import collections
import hashlib
import json

import pytest

from scripts import dataset_tiers as T

#: The committed base files, as of the commit that introduced the tiers.
BASE = {
    "judge_v1": (1_800, "9422893772df6d25a466fe5f0383eb33"),
    "commands_v2": (5_292, "b88af92a1a3f0eeaee39a69e7011ab6c"),
    "judge_v2": (11_187, "605471a877ea48f0b566efbb77f19a78"),
    "personas": (2_520, "787cbba41a5125047ef7034a2652ffcd"),
    "personas_ablation": (2_520, "943c9d77942bda8a09a246691081d5a0"),
    "realspeech": (1_200, "c8121bd93f65883306574f6d31e2396d"),
}


def _base_path(name):
    return T.ROOT / T.SETS[name][0]


def _base_rows(name):
    return [json.loads(l) for l in _base_path(name).open(encoding="utf-8")]


def _on_disk(name, tier):
    path = T.tier_path(_base_path(name), tier)
    if not path.exists():
        pytest.skip(f"{path.name} not built ({T.command(name, tier)})")
    return path


# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BASE))
def test_base_file_is_unchanged(name):
    n, md5 = BASE[name]
    data = _base_path(name).read_bytes()
    assert hashlib.md5(data).hexdigest() == md5, f"{name}: the committed base file changed"
    assert data.count(b"\n") == n


def test_the_v2_generator_still_writes_base_byte_for_byte():
    from assistant.engine.llmjudge.datasets.v2 import generate_v2 as g
    out = "".join(g._dumps(r) + "\n" for r in g.build_commands()).encode()
    assert hashlib.md5(out).hexdigest() == BASE["commands_v2"][1]


def test_the_realspeech_generator_still_writes_base_byte_for_byte():
    from scripts import gen_realspeech as rs
    rows = rs.build(rs.load_json("ask_patterns.json"), rs.load_json("fillers.json"),
                    rs.load_json("speech.json"))
    out = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                  for r in rows).encode()
    assert hashlib.md5(out).hexdigest() == BASE["realspeech"][1]


# ---------------------------------------------------------------------------
# the tier helper
# ---------------------------------------------------------------------------

def test_tier_paths_and_freshness(tmp_path):
    base = tmp_path / "set.jsonl"
    base.write_text('{"a": 1}\n')
    assert T.tier_path(base, "base") == base
    assert T.tier_path(base, "40k") == tmp_path / "tiers" / "set.40k.jsonl"
    assert not T.is_fresh(base, "40k")
    T.write_tier(base, "40k", [{"b": 2}])
    assert T.is_fresh(base, "40k")
    assert T.tier_path(base, "40k").read_text() == '{"a": 1}\n{"b": 2}\n'
    base.write_text('{"a": 9}\n')               # base regenerated -> tier stale
    assert not T.is_fresh(base, "40k")
    with pytest.raises(ValueError):
        T.tier_path(base, "7k")


def test_resolve_defaults_to_base_and_never_builds_a_case_tier(monkeypatch, tmp_path):
    assert T.resolve("judge_v2") == _base_path("judge_v2")
    # point the case set at an empty folder: resolve must STOP with the command
    rel = str((tmp_path / "judge_cases_v2.jsonl").relative_to(tmp_path))
    (tmp_path / rel).write_text("{}\n")
    monkeypatch.setattr(T, "ROOT", tmp_path)
    monkeypatch.setitem(T.SETS, "judge_v2", (rel, T.SETS["judge_v2"][1], None))
    with pytest.raises(SystemExit) as e:
        T.resolve("judge_v2", "40k")
    assert "generate_v2 --tier 40k" in str(e.value)


# ---------------------------------------------------------------------------
# v2 commands
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def v2():
    from assistant.engine.llmjudge.datasets.v2 import generate_v2 as g
    return {t: g.build_command_tier(t) for t in T.GROWN}


def test_v2_tiers_are_prefixes_and_reach_their_floor(v2):
    base = _base_rows("commands_v2")
    g10, g40 = v2["10k"], v2["40k"]
    assert g10 == g40[:len(g10)]
    assert len(base) + len(g10) >= 10_000
    assert len(base) + len(g40) >= 40_000
    assert [r["id"] for r in g40] == [f"v2c-{len(base) + i + 1:06d}" for i in range(len(g40))]
    assert {r["grown_in"] for r in g10} == {"10k"}


def test_v2_grown_rows_are_new_text_and_split_by_family(v2):
    base = _base_rows("commands_v2")
    rows = base + v2["40k"]
    grown_texts = [r["text"] for r in v2["40k"]]
    assert len(set(grown_texts)) == len(grown_texts)
    assert not set(grown_texts) & {r["text"] for r in base}
    sides = collections.defaultdict(set)
    for r in rows:
        sides[r["family"]].add(r["split"])
    assert all(len(s) == 1 for s in sides.values()), "a family is on both sides"
    train = {r["text"] for r in rows if r["split"] == "train"}
    assert not train & {r["text"] for r in rows if r["split"] == "test"}


def test_v2_diversity_floors(v2):
    from assistant.engine.llmjudge.datasets.v2 import damage, voices
    rows = _base_rows("commands_v2") + v2["40k"]
    assert len({r["family"] for r in rows}) >= 700
    assert len({"+".join(r["grammar"]) for r in rows}) >= 400
    assert len({r["joiner"] for r in rows}) >= 12
    assert {r["voice"] for r in rows} == {v.id for v in voices.ALL_VOICES}
    assert len({a["title"] for r in rows for a in r["asks"] if a["title"]}) >= 900
    per_family = collections.Counter(r["family"] for r in v2["40k"])
    assert max(per_family.values()) <= 4 * len(voices.ALL_VOICES)    # the cap
    sides = collections.defaultdict(set)
    for r in v2["40k"]:
        sides[r["voice"]].add(r["split"])
        for op in r["damage"]:
            sides[op].add(r["split"])
    for key in list(voices.TIER_VOICE_IDS) + list(damage.OPERATIONS):
        assert sides[key] == {"train", "test"}, key


def test_v2_grown_gold_is_reachable_and_voice_invariant(v2):
    """The two invariants `test_llmjudge_dataset_v2.py` pins on base, on every
    grown row: a gold value the words cannot reach is a dataset defect, and the
    renderings of one command (base voices AND tier voices) share one gold."""
    from assistant.engine.llmjudge.datasets.v2.verify_v2 import unreachable
    bad = [r["id"] for r in v2["40k"] if unreachable(r)]
    assert not bad, bad[:5]

    def gold(r):
        return json.dumps([(a["action"], a["kind"], a["title"], a["intended_title"],
                            a["date_phrase"], a["clock"], a["end_clock"],
                            a["recurrence"], a["recur_days"], a["anaphor"],
                            a["bare_kind"]) for a in r["asks"]])
    by = collections.defaultdict(set)
    for r in _base_rows("commands_v2") + v2["40k"]:
        by[r["utterance"]].add(gold(r))
    moved = [u for u, g in by.items() if len(g) > 1]
    assert not moved, moved[:5]
    for r in v2["40k"]:
        for a in r["asks"]:
            assert {"action", "kind", "item", "said"} <= set(a), r["id"]
            assert a["item"]["text"], r["id"]


def test_v2_command_tier_files_match_the_generator(v2):
    for tier in T.GROWN:
        path = _on_disk("commands_v2", tier)
        assert T.is_fresh(_base_path("commands_v2"), tier)
        grown = path.read_text().splitlines()[BASE["commands_v2"][0]:]
        from assistant.engine.llmjudge.datasets.v2 import generate_v2 as g
        assert grown == [g._dumps(r) for r in v2[tier]], f"{tier} is stale"


# ---------------------------------------------------------------------------
# v2 cases (on disk only)
# ---------------------------------------------------------------------------

def test_v2_case_tiers_on_disk():
    from assistant.engine.llmjudge.datasets.v2 import mutations
    from assistant.engine.llmjudge import findings
    types = {findings.UNGROUNDED_SUBJECT, findings.UNSUPPORTED_FIELD,
             findings.NOT_AN_ASK, findings.COORDINATED_SUBJECT,
             findings.UNSPLIT_SUBJECT}
    by_tier = {}
    for tier in T.GROWN:
        path = _on_disk("judge_v2", tier)
        assert T.is_fresh(_base_path("judge_v2"), tier)
        cases = [json.loads(l) for l in path.open()]
        commands = {r["id"]: r for r in map(json.loads, _on_disk("commands_v2", tier).open())}
        assert len({c["id"] for c in cases}) == len(cases)
        for c in cases[BASE["judge_v2"][0]:]:
            cmd = commands[c["command_id"]]
            assert c["split"] == cmd["split"], c["id"]
            assert c["mutation"] in mutations.EXPECT, c["id"]
            assert c["expect"] is None or c["expect"] in types, c["id"]
            assert c["defect"] == (c["mutation"] != "clean")
            assert c["items"], c["id"]
        by_tier[tier] = cases
    assert len(by_tier["40k"]) >= 40_000
    small = {c["id"]: c for c in by_tier["10k"]}
    big = {c["id"]: c for c in by_tier["40k"]}
    assert all(big.get(k) == v for k, v in small.items()), "10k cases are not 40k cases"
    per = collections.Counter((c["mutation"], c["split"]) for c in by_tier["40k"])
    assert min(per.values()) >= 1_000, "a mutation is thin on one half"


# ---------------------------------------------------------------------------
# v1 cases
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def v1_sources():
    from assistant.engine.llmjudge.datasets import generate as v1
    return v1._tier_sources(_base_rows("judge_v1"), 40_000 - BASE["judge_v1"][0])


def test_v1_sources_are_prefixes_new_and_split_by_family(v1_sources):
    from assistant.engine.llmjudge.datasets import generate as v1
    base = _base_rows("judge_v1")
    small = v1._tier_sources(base, 10_000 - len(base))
    assert small == v1_sources[:len(small)]
    texts = [r["text"] for r in v1_sources]
    assert len(set(texts)) == len(texts)
    assert not set(texts) & {c["text"] for c in base}
    sides = collections.defaultdict(set)
    for r in v1_sources:
        sides[r.get("family") or r["id"]].add(r["split"])
    assert all(len(s) == 1 for s in sides.values())
    grammar = [r for r in v1_sources if r["source"] == "grammar"]
    fams = collections.Counter(r["family"] for r in grammar)
    assert len(fams) >= 600 and max(fams.values()) <= 120
    assert {r["voice"] for r in grammar} >= {"plain", "voice_memo", "academic"}
    for r in v1_sources:
        assert r["expect"]["action"] and r["expect"]["item"]["text"], r["id"]
        assert r["split"] in ("train", "test")


def test_v1_case_tiers_on_disk():
    paths = {t: _on_disk("judge_v1", t) for t in T.GROWN}
    for tier, path in paths.items():
        assert T.is_fresh(_base_path("judge_v1"), tier)
    big = paths["40k"].read_bytes()
    assert big.startswith(paths["10k"].read_bytes()), "10k is not a prefix of 40k"
    cases = [json.loads(l) for l in big.decode().splitlines()]
    assert len(cases) >= 40_000
    assert len({c["id"] for c in cases}) == len(cases)
    assert len({c["text"] for c in cases}) == len(cases)
    for c in cases:
        assert {"item", "gold_action", "mutation", "split", "text"} <= set(c), c["id"]
    assert len({c["mutation"] for c in cases}) == 7


# ---------------------------------------------------------------------------
# real speech
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rs():
    from scripts import gen_realspeech as g
    return {t: g.tier_rows(t) for t in T.GROWN}


def test_realspeech_tiers_are_prefixes_and_pass_the_base_verify(rs):
    from scripts import gen_realspeech as g
    base = _base_rows("realspeech")
    assert rs["10k"] == rs["40k"][:len(rs["10k"])]
    assert len(base) + len(rs["10k"]) == 10_000
    assert len(base) + len(rs["40k"]) == 40_000
    g.verify(base + rs["40k"])          # unique text/id, family split, 5% cap, gold
    split = {r["family"]: r["split"] for r in base}
    for r in rs["40k"]:
        assert split.get(r["family"], r["split"]) == r["split"], r["id"]


def test_realspeech_diversity_and_gold(rs):
    rows = _base_rows("realspeech") + rs["40k"]
    assert len({r["family"] for r in rows}) >= 250
    assert len({r["register"] for r in rows if r.get("register")}) >= 7
    assert len({r["expect"]["action"] for r in rows}) >= 8
    per = collections.Counter(r["family"] for r in rs["40k"])
    # the two no-ask families are the base design (one per side) and hold the
    # measured 4.8% null share between them; every ASK family is capped at 1.5%
    nulls = {f: n for f, n in per.items() if f.startswith("rs_null")}
    assert max(per[f] for f in per if f not in nulls) <= 0.015 * 40_000
    assert max(nulls.values()) <= 0.05 * 40_000
    pools = collections.Counter(r["pool"] for r in rs["40k"])
    assert abs(pools["faithful"] / sum(pools.values()) - 2 / 3) < 0.01
    for r in rs["40k"]:
        assert set(r["expect"]) >= {"events", "tasks", "action", "atomic", "slots"}


# ---------------------------------------------------------------------------
# personas — TEST-ONLY at every size
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def personas():
    from scripts import gen_personas as g
    return {(abl, t): g.tier_rows(t, ablation=abl)
            for abl in (False, True) for t in T.GROWN}


@pytest.mark.parametrize("ablation", [False, True])
def test_persona_tiers_are_supersets_and_test_only(personas, ablation):
    name = "personas_ablation" if ablation else "personas"
    base = _base_rows(name)
    small, big = personas[(ablation, "10k")], personas[(ablation, "40k")]
    by_id = {r["id"]: r for r in big}
    assert all(by_id.get(r["id"], {}).get("text") == r["text"] for r in small)
    assert len(base) + len(small) >= 10_000
    assert len(base) + len(big) >= 40_000
    for rows in (base + small, base + big):
        assert all(r["split"] == "test" for r in rows), "a persona row is not test-only"
        assert len({r["id"] for r in rows}) == len(rows)
        cells = collections.defaultdict(list)
        for r in rows:
            cells[r["persona"]].append(r)
        sizes = {len(v) for v in cells.values()}
        assert len(sizes) == 1, "cells are not the same size"
        structures = {s for r in rows for s in [r["structure"]]}
        assert len(structures) == 33
        for label, rs_ in cells.items():
            assert {r["structure"] for r in rs_} == structures, label
            texts = [r["text"] for r in rs_]
            assert len(set(texts)) == len(texts), label
        if not ablation:
            texts = [r["text"] for r in rows]
            assert len(set(texts)) == len(texts)
    assert len({r["persona"] for r in base + big}) == (24 if ablation else 12)


def test_persona_diversity_and_gold(personas):
    from scripts import gen_personas as g
    rows = _base_rows("personas") + personas[(False, "40k")]
    assert len({r["family"] for r in rows}) >= 500
    per = collections.Counter(r["family"] for r in personas[(False, "40k")])
    assert max(per.values()) <= 300
    for r in personas[(False, "40k")]:
        assert set(r["expect"]) >= {"events", "tasks", "action", "atomic", "slots"}
        assert set(r["gold"]) == {"operation", "kind", "atomicity"}
    # the new personas are new people, not renamed base ones
    _c, persona_banks, _f, ids = g.load_world(tier=True)
    assert len(ids) == 12
    for new in g.TIER_PERSONAS:
        mine = set(persona_banks[new]["fillers"]["event_titles"])
        for old in g.PERSONAS:
            assert not mine & set(persona_banks[old]["fillers"]["event_titles"]), (new, old)


@pytest.mark.parametrize("name,ablation", [("personas", False),
                                           ("personas_ablation", True),
                                           ("realspeech", None)])
def test_cheap_tier_files_on_disk_match_the_generator(name, ablation, personas, rs):
    for tier in T.GROWN:
        path = _on_disk(name, tier)
        assert T.is_fresh(_base_path(name), tier), f"{path.name} is stale"
        grown = path.read_text(encoding="utf-8").splitlines()[BASE[name][0]:]
        rows = rs[tier] if ablation is None else personas[(ablation, tier)]
        assert grown == [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows]
