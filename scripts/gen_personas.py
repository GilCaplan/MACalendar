#!/usr/bin/env python3
"""Generate the PERSONA test sets — one synthetic user per speech community.

WHY THIS EXISTS
---------------
The engine's three trained classifiers (atomicity / operation / kind, in
`assistant/intent/classifier.py`) decide STRUCTURE: how many asks there are,
which verb class, event or task. The standing claim is that a user's personal
vocabulary lives in SLOTS (titles, places, names) and therefore cannot move
them — so the engine should work as well for someone whose words and phrasing
habits are nothing like its author's. That claim was spot-checked on ten
hand-written phrases and never measured.

This builds the measurement. Six personas, each with its own filler banks
(names, places, activities, item nouns, recurring commitments) AND its own
phrasing style (terse fragments vs. polite paragraphs vs. calqued syntax),
scored by `scripts/persona_board.py`. If quality is flat across personas the
claim survives; if it is not, we have tuned to one dialect without knowing.

THE DESIGN THAT MAKES THE COMPARISON MEAN ANYTHING
--------------------------------------------------
`dataset/personas/structures.json` is a SHARED STRUCTURE CATALOG: 33 asks
defined by their GRAMMAR (how many asks, which action, which slots), not by
their words. Every persona realises EVERY structure in its own voice. So on a
structure-matched slice the composition is identical across personas by
construction, and any spread in the metrics is attributable to vocabulary and
phrasing alone — not to one persona happening to have been given more
compounds.

Personas ALSO carry a `mix` (relative weights per structure), because a parent
really does create more tasks than a consultant does. The board therefore
reports both: the persona's natural mix (product-realistic) and the
structure-matched macro-average (the clean comparison).

GROUND TRUTH IS BY CONSTRUCTION, never hand-labelled: this script chose the
filler that became `slots.title`, and the structure declares
action/atomic/events/tasks once. Same row schema as `assistant/engine/fastrule/datasets/` so the
same scorers can read it.

TEST-ONLY, ALWAYS. Every row is `split: "test"`. These rows are never used to
fit, tune, or select anything — see dataset/personas/PERSONAS.md.

NO REAL PERSONAL DATA. Every name and place is invented, and `--leak-check`
(on by default) reads the author's real `~/.assistant_tools/vocab.json`
read-only and fails the build if any word of it (>= 5 chars, word-boundary —
the same standard as `tests/unit/test_artifact_claims.py`'s leak test) appears
in a generated row. Genuinely general words are declared, with a reason, in
`dataset/personas/allowed_words.txt`.

Usage:
    python -m scripts.gen_personas              # generate + verify + write
    python -m scripts.gen_personas --no-write   # same, without writing
    python -m scripts.gen_personas --tier all   # 10k + 40k supersets (still test-only)
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse the FastRule generator's slot machinery rather than reimplementing it:
# placeholder -> (bank, semantic slot key) is the contract that makes these
# rows readable by the same scorers, and one copy of it is the only safe
# number of copies. (Read-only import; this script never writes there.)
from assistant.engine.fastrule.datasets.generate import (      # noqa: E402
    family_capacity,
    family_tokens,
    placeholder_info,
    resolve_slots,
    stable_int,
    validate_family,
)

PERSONA_DIR = ROOT / "dataset" / "personas"
BANKS = PERSONA_DIR / "banks"
OUT = PERSONA_DIR / "personas.jsonl"
ALLOWED_WORDS = PERSONA_DIR / "allowed_words.txt"

#: Changing this reseeds every row. Don't, without regenerating and noting it.
SEED = "personas-v1"

#: rows per persona — big enough for a stable read (a 1-row flip is 0.24 pt),
#: small enough that the whole set replays through FastRule in seconds.
ROWS_PER_PERSONA = 420
MIN_ROWS_PER_FAMILY = 4

PERSONAS = [
    "observant_student",
    "household_parent",
    "freelance_consultant",
    "retiree",
    "uni_student",
    "esl_speaker",
]

# --- the ablation (--ablation) -------------------------------------------
# The persona board shows THAT quality varies. It cannot say whether the cause
# is the WORDS or the WAY OF SPEAKING, because a persona changes both at once.
# This splits them. A persona's banks divide into:
#
#   CONTENT   what the person talks about — names, activities, things.
#             This is "vocabulary" in the sense the multi-user claim uses it:
#             material that ends up inside a SLOT.
#   STYLE     how they say it — the templates, plus the temporal expressions
#             and disfluencies, which are habits rather than subject matter.
#
# Two blocks, each holding one half fixed against the control persona:
#   vocab:<p>   control's STYLE + <p>'s CONTENT   -> spread = vocabulary alone
#   phrase:<p>  <p>'s STYLE + control's CONTENT   -> spread = phrasing alone
CONTENT_BANKS = ("names", "event_titles", "task_titles", "items", "occasions", "quotable")
ABLATION_CONTROL = "observant_student"
ROWS_PER_ABLATION_CELL = 210
ABLATION_OUT = PERSONA_DIR / "personas_ablation.jsonl"

VOCAB_PATH = pathlib.Path(os.path.expanduser("~/.assistant_tools/vocab.json"))


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_json(path: pathlib.Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def semantic_keys(tokens) -> set:
    """The ground-truth slot keys a token list produces. Cosmetic tokens
    (`{filler}`) map to None and are dropped — a persona may sprinkle as many
    disfluencies as its voice calls for without changing what the row means."""
    keys = set()
    for tok in tokens:
        _, semantic, _ = placeholder_info(tok)
        if semantic is not None:
            keys.add(semantic)
    return keys


def build_families(structures, personas):
    """One family per (persona, structure, template variant).

    Validates, per family, that the persona's wording produces EXACTLY the
    structure's ground-truth slot keys. That check is what keeps the personas
    comparable: a persona that quietly dropped the date from `ce_datetime`
    would be scored on an easier row than everyone else.
    """
    fams = []
    for pid, p in personas.items():
        templates = p["templates"]
        mix = p.get("mix", {})
        missing = [s["id"] for s in structures if s["id"] not in templates]
        if missing:
            raise ValueError(f"{pid}: no template for structure(s) {missing}")
        extra = [k for k in templates if k not in {s["id"] for s in structures}]
        if extra:
            raise ValueError(f"{pid}: template(s) for unknown structure(s) {extra}")
        for s in structures:
            want = semantic_keys(s["tokens"])
            variants = templates[s["id"]]
            if isinstance(variants, str):
                variants = [variants]
            for i, tpl in enumerate(variants):
                got = semantic_keys(family_tokens(tpl))
                if got != want:
                    raise ValueError(
                        f"{pid}/{s['id']} variant {i}: template produces slots "
                        f"{sorted(got)} but the structure declares {sorted(want)}\n"
                        f"    {tpl}")
                fams.append({
                    "persona": pid,
                    "structure": s["id"],
                    "variant": i,
                    "family": f"{pid}:{s['id']}:{i}",
                    "template": tpl,
                    "tier": s["tier"],
                    "action": s["action"],
                    "atomic": s["atomic"],
                    "events": s["events"],
                    "tasks": s["tasks"],
                    "op_gold": s.get("op_gold"),
                    "kind_gold": s.get("kind_gold"),
                    "fixed_slots": s.get("fixed_slots", {}),
                    "flags": s.get("flags", {}),
                    "weight": float(mix.get(s["id"], 1.0)) / len(variants),
                })
    return fams


# ---------------------------------------------------------------------------
# quota allocation (deterministic, weight-aware, capacity-capped)
# ---------------------------------------------------------------------------

def allocate(fams, fillers: dict, total: int) -> dict:
    """Rows per family for ONE persona: weight-proportional, floored at
    MIN_ROWS_PER_FAMILY, capped at each family's combinatorial capacity, and
    fixed up to sum exactly `total`. Every tie is broken by a stable hash of
    the family name, so the result never depends on dict order or PYTHONHASHSEED.
    """
    order = sorted(fams, key=lambda f: (stable_int(SEED, "alloc", f["family"]), f["family"]))
    caps = {f["family"]: family_capacity(f, fillers) for f in order}
    W = sum(f["weight"] for f in order) or 1.0
    q = {}
    for f in order:
        want = int(round(f["weight"] / W * total))
        q[f["family"]] = max(MIN_ROWS_PER_FAMILY, min(want, caps[f["family"]]))

    def total_now():
        return sum(q.values())

    guard = 0
    while total_now() > total and guard < 100000:
        guard += 1
        # take from whoever is furthest above its fair share
        cand = [f for f in order if q[f["family"]] > MIN_ROWS_PER_FAMILY]
        if not cand:
            break
        f = max(cand, key=lambda f: (q[f["family"]] / max(f["weight"], 1e-9), f["family"]))
        q[f["family"]] -= 1
    while total_now() < total and guard < 200000:
        guard += 1
        cand = [f for f in order if q[f["family"]] < caps[f["family"]]]
        if not cand:
            raise ValueError(
                f"persona capacity {sum(caps.values())} cannot reach {total} rows "
                f"— widen a filler bank")
        f = min(cand, key=lambda f: (q[f["family"]] / max(f["weight"], 1e-9), f["family"]))
        q[f["family"]] += 1
    if total_now() != total:
        raise ValueError(f"allocation did not converge: {total_now()} != {total}")
    return q


# ---------------------------------------------------------------------------
# row generation
# ---------------------------------------------------------------------------

def gen_rows(fam, quota: int, fillers: dict, seen: set):
    """`quota` unique rows for one family. Its RNG stream is seeded from the
    family name alone, so adding or removing a persona — or a structure —
    cannot change any other family's rows."""
    tokens = family_tokens(fam["template"])
    validate_family(fam, fillers)
    banks = {}
    for tok in tokens:
        bank_key, _, _ = placeholder_info(tok)
        if bank_key not in fillers:
            raise ValueError(f"{fam['family']}: no bank '{bank_key}'")
        banks[tok] = fillers[bank_key]

    rng = random.Random(f"{SEED}:{fam['family']}")
    out, combos, attempts = [], set(), 0
    while len(out) < quota and attempts < max(400, quota * 80):
        attempts += 1
        combo = tuple(rng.choice(banks[t]) for t in tokens) if tokens else ()
        if combo in combos:
            continue
        combos.add(combo)
        values = dict(zip(tokens, combo))
        text = re.sub(r"\s+", " ", fam["template"].format(**values).strip())
        if text in seen:
            continue
        seen.add(text)
        out.append((text, resolve_slots(fam, values, tokens)))
    if len(out) < quota:
        raise ValueError(
            f"{fam['family']} produced {len(out)}/{quota} unique rows — widen its banks")
    return out


# ---------------------------------------------------------------------------
# the leak gate
# ---------------------------------------------------------------------------

def read_vocab_words() -> set:
    """The author's real word list, read-only. Same reading as the artifact
    leak test: the settings object's `entries`, lowercased."""
    if not VOCAB_PATH.exists():
        return set()
    try:
        raw = json.loads(VOCAB_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    found = raw.get("entries") if isinstance(raw, dict) else raw
    words = set()
    for entry in (found or []):
        w = entry.get("word") if isinstance(entry, dict) else entry
        if isinstance(w, str) and w.strip():
            words.add(w.strip().lower())
    return words


def allowed_words() -> set:
    if not ALLOWED_WORDS.exists():
        return set()
    return {ln.split("#")[0].strip().lower()
            for ln in ALLOWED_WORDS.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")} - {""}


def leak_check(rows) -> dict:
    """Every author-vocabulary word that survived into a generated row.

    Same standard as tests/unit/test_artifact_claims.py: a word is a leak
    unless declared general, and only words of >= 5 characters are checked
    (shorter entries collide with ordinary English). Returns
    {word: [example row ids]}; empty is the passing state.
    """
    words = read_vocab_words()
    if not words:
        return {}
    ok = allowed_words()
    candidates = sorted(w for w in words - ok if len(w) >= 5)
    if not candidates:
        return {}
    # one pass over the corpus with one alternation, rather than 370 scans
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in candidates) + r")\b")
    hits = defaultdict(list)
    for r in rows:
        for m in pattern.finditer(r["text"].lower()):
            if len(hits[m.group(1)]) < 3:
                hits[m.group(1)].append(r["id"])
    return dict(hits)


# ---------------------------------------------------------------------------
# size tiers — base / 10k / 40k (Gil, 2026-10-01)
# ---------------------------------------------------------------------------
#
# *"a lot of the datasets seem really small, they should be at least 40k with
# enough variation in the data."* The committed 2,520 rows (and the 2,520
# ablation rows) are the `base` tier; a grown tier is base's BYTES followed by
# grown rows (`scripts/dataset_tiers.py`). STILL TEST-ONLY: every grown row is
# `split: "test"`, exactly like base — the size tiers make the persona board
# able to carry a claim per structure, they do not make it something to fit on.
#
# Where the growth is new rather than more of the same:
#
#   SIX NEW PERSONAS   `banks/tiers/<id>.json` — a ward nurse on shifts, a
#                      small-business owner, a tradesperson, a secondary
#                      teacher, a family caregiver, an amateur musician. Each
#                      has its own content banks AND its own phrasing for
#                      every one of the 33 shared structures, so the
#                      structure-matched comparison still holds across 12.
#   THE BASE SIX, WIDER `banks/tiers/<base id>.json` APPENDS fillers and adds
#                      template VARIANTS in the persona's own voice; a new
#                      variant is a new family (`<id>:<structure>:<k>`).
#
# Every cell (persona, or ablation cell) is filled to the same size at each
# tier, so a per-persona number is always over the same n. A cell's grown
# rows are ordered by their fractional position inside their family, so the
# 10k tier — the first rows of each cell — still holds every structure.

TIER_BANKS = BANKS / "tiers"
TIER_PERSONAS = ["shift_nurse", "small_business_owner", "tradesperson",
                 "secondary_teacher", "family_caregiver", "amateur_musician"]


def _extend(base: list, extra: list) -> list:
    return list(base) + [x for x in extra if x not in base]


def load_world(tier: bool = False) -> tuple:
    """`(catalog, personas, fillers_of, ids)` — the base world, or with
    `tier=True` the base six widened by their tier extensions plus the six
    tier personas. The base path reads exactly what `main()` always read."""
    catalog = load_json(PERSONA_DIR / "structures.json")["structures"]
    common = load_json(BANKS / "common.json")["fillers"]
    ids = list(PERSONAS) + (TIER_PERSONAS if tier else [])
    personas, fillers_of = {}, {}
    for pid in ids:
        path = (TIER_BANKS if pid in TIER_PERSONAS else BANKS) / f"{pid}.json"
        p = load_json(path)
        if p["persona"]["id"] != pid:
            raise ValueError(f"{pid}.json declares id {p['persona']['id']!r}")
        if tier and pid in PERSONAS:
            ext = load_json(TIER_BANKS / f"{pid}.json")
            for k, v in ext.get("fillers", {}).items():
                p["fillers"][k] = _extend(p["fillers"].get(k, common.get(k, [])), v)
            for st, extra in ext.get("templates", {}).items():
                have = p["templates"][st]
                have = [have] if isinstance(have, str) else list(have)
                p["templates"][st] = _extend(have, extra)
        personas[pid] = p
        merged = dict(common)
        merged.update(p["fillers"])
        fillers_of[pid] = merged
    return catalog, personas, fillers_of, ids


def _cells_for(ids: list, ablation: bool) -> list:
    if ablation:
        return ([(f"vocab:{p}", ABLATION_CONTROL, p) for p in ids]
                + [(f"phrase:{p}", p, ABLATION_CONTROL) for p in ids])
    return [(p, p, p) for p in ids]


def _tier_family_rows(fam, quota: int, fillers: dict, seen: set, stream: str = "") -> list:
    """`gen_rows` on a stream of its own that never raises: a family whose
    combinations run out hands its shortfall back to the caller."""
    tokens = family_tokens(fam["template"])
    validate_family(fam, fillers)
    banks = {tok: fillers[placeholder_info(tok)[0]] for tok in tokens}
    rng = random.Random(f"{SEED}:tier:{fam['family']}:{stream}")
    out, combos, attempts = [], set(), 0
    while len(out) < quota and attempts < max(400, quota * 80):
        attempts += 1
        combo = tuple(rng.choice(banks[t]) for t in tokens) if tokens else ()
        if combo in combos:
            continue
        combos.add(combo)
        values = dict(zip(tokens, combo))
        text = re.sub(r"\s+", " ", fam["template"].format(**values).strip())
        if text in seen:
            continue
        seen.add(text)
        out.append((text, resolve_slots(fam, values, tokens)))
    return out


def build_tier_cells(ablation: bool = False, top: str = "40k") -> dict:
    """`{cell label: [grown rows in tier order]}` for the TOP tier."""
    from scripts.dataset_tiers import TARGET
    catalog, personas, fillers_of, ids = load_world(tier=True)
    fams = build_families(catalog, personas)
    cells = _cells_for(ids, ablation)
    base_path = ABLATION_OUT if ablation else OUT
    base_rows = [json.loads(l) for l in base_path.open(encoding="utf-8")]
    base_n = Counter(r["persona"] for r in base_rows)
    per_cell = -(-TARGET[top] // len(cells))
    global_seen = {r["text"] for r in base_rows}
    out = {}
    for label, tpl_owner, content_owner in cells:
        fill = dict(fillers_of[tpl_owner])
        for k in CONTENT_BANKS:
            fill[k] = fillers_of[content_owner][k]
        mine = []
        for f in fams:
            if f["persona"] != tpl_owner:
                continue
            g = dict(f)
            g["persona"] = label
            g["family"] = f"{label}:{f['structure']}:{f['variant']}"
            mine.append(g)
        seen = ({r["text"] for r in base_rows if r["persona"] == label}
                if ablation else global_seen)
        quota = per_cell - base_n.get(label, 0)
        quotas = allocate(mine, fill, quota)
        got = {}
        for f in sorted(mine, key=lambda f: f["family"]):
            got[f["family"]] = _tier_family_rows(f, quotas[f["family"]], fill, seen)
        short = quota - sum(len(v) for v in got.values())
        for f in sorted(mine, key=lambda f: (-family_capacity(f, fill), f["family"])):
            if short <= 0:
                break
            more = _tier_family_rows(f, short, fill, seen, stream="more")
            got[f["family"]] += more
            short -= len(more)
        if short > 0:
            raise ValueError(f"{label}: {short} rows short — widen its tier banks")
        by_fam = {f["family"]: f for f in mine}
        ordered = []
        for fam_id, rows in sorted(got.items()):
            f = by_fam[fam_id]
            for i, (text, slots) in enumerate(rows):
                ordered.append(((i + 0.5) / len(rows), stable_int(SEED, "tier", fam_id, str(i)), {
                    "id": f"{fam_id}-x{i:04d}",
                    "text": text,
                    "persona": label,
                    "split": "test",          # ALWAYS. see PERSONAS.md
                    "tier": f["tier"],
                    "structure": f["structure"],
                    "family": fam_id,
                    "gold": {"operation": f["op_gold"], "kind": f["kind_gold"],
                             "atomicity": "atomic" if f["atomic"] else "compound"},
                    "expect": {"events": f["events"], "tasks": f["tasks"],
                               "action": f["action"], "atomic": f["atomic"],
                               "slots": slots},
                }))
        ordered.sort(key=lambda t: (t[0], t[1]))
        out[label] = [r for _f, _h, r in ordered]
    return out


def tier_rows(tier: str, ablation: bool = False) -> list:
    """The grown rows of `tier`: per cell, the first rows of the 40k build,
    so every 10k row is a 40k row."""
    from scripts.dataset_tiers import GROWN, TARGET
    cells = build_tier_cells(ablation)
    base_path = ABLATION_OUT if ablation else OUT
    base_n = Counter(json.loads(l)["persona"] for l in base_path.open(encoding="utf-8"))
    rows = []
    for label, grown in cells.items():
        want = {t: -(-TARGET[t] // len(cells)) - base_n.get(label, 0) for t in GROWN}
        for i, r in enumerate(grown[:want[tier]]):
            r["grown_in"] = next(t for t in GROWN if i < want[t])
            rows.append(r)
    return rows


def verify_tier(base_rows: list, rows: list, ablation: bool) -> None:
    catalog = load_json(PERSONA_DIR / "structures.json")["structures"]
    allr = base_rows + rows
    assert all(r["split"] == "test" for r in allr), "a persona row is not test-only"
    assert len({r["id"] for r in allr}) == len(allr), "duplicate id"
    if ablation:
        per = defaultdict(list)
        for r in allr:
            per[r["persona"]].append(r["text"])
        assert all(len(set(v)) == len(v) for v in per.values()), "duplicate text in a cell"
    else:
        assert len({r["text"] for r in allr}) == len(allr), "duplicate text"
    cover = defaultdict(set)
    for r in allr:
        cover[r["persona"]].add(r["structure"])
    ids = {s["id"] for s in catalog}
    for label, have in cover.items():
        if have != ids:
            raise ValueError(f"{label} is missing structure(s) {sorted(ids - have)}")


def _write_tier(tier: str, ablation: bool, leak: bool = True):
    from scripts.dataset_tiers import write_tier as _write
    base_path = ABLATION_OUT if ablation else OUT
    base_rows = [json.loads(l) for l in base_path.open(encoding="utf-8")]
    rows = tier_rows(tier, ablation)
    verify_tier(base_rows, rows, ablation)
    if leak:
        leaks = leak_check(rows)
        if leaks:
            raise SystemExit(f"LEAK GATE FAILED on the {tier} tier: {sorted(leaks)} "
                             f"— replace the tier bank word, or declare it in "
                             f"dataset/personas/allowed_words.txt with a reason")
    return _write(base_path, tier, rows,
                  dumps=lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True))


def write_tier(tier: str, leak: bool = True):
    return _write_tier(tier, ablation=False, leak=leak)


def write_ablation_tier(tier: str, leak: bool = True):
    return _write_tier(tier, ablation=True, leak=leak)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-write", action="store_true",
                    help="build and verify in memory, don't write the jsonl")
    ap.add_argument("--no-leak-check", action="store_true",
                    help="skip the vocabulary leak gate (CI has no vocabulary; "
                         "never pass this on the author's machine)")
    ap.add_argument("--ablation", action="store_true",
                    help="write personas_ablation.jsonl instead: 12 cells that hold "
                         "vocabulary or phrasing fixed against the control, so the "
                         "board can say WHICH of the two the spread comes from")
    ap.add_argument("--tier", choices=("base", "10k", "40k", "all"), default="base",
                    help="base (default) rewrites the committed file; 10k / 40k "
                         "write a gitignored, still TEST-ONLY superset under "
                         "tiers/; all = both")
    a = ap.parse_args()

    if a.tier != "base":
        for tier in (("10k", "40k") if a.tier == "all" else (a.tier,)):
            path = _write_tier(tier, a.ablation, leak=not a.no_leak_check)
            rows = [json.loads(l) for l in path.open(encoding="utf-8")]
            per = Counter(r["persona"] for r in rows)
            print(f"{tier}: {len(rows)} rows, {len(per)} cells "
                  f"({min(per.values())}-{max(per.values())} each), "
                  f"{len({r['family'] for r in rows})} families, "
                  f"{len({r['text'] for r in rows})} distinct texts -> {path}")
            print(f"Leak gate: {'SKIPPED' if a.no_leak_check else 'clean'} "
                  f"({len(read_vocab_words())} author words checked)")
        return 0

    catalog = load_json(PERSONA_DIR / "structures.json")["structures"]
    common = load_json(BANKS / "common.json")["fillers"]
    personas, fillers_of = {}, {}
    for pid in PERSONAS:
        p = load_json(BANKS / f"{pid}.json")
        if p["persona"]["id"] != pid:
            raise ValueError(f"{pid}.json declares id {p['persona']['id']!r}")
        personas[pid] = p
        merged = dict(common)
        merged.update(p["fillers"])          # persona keys REPLACE, never append
        fillers_of[pid] = merged

    fams = build_families(catalog, personas)

    # cell = (label, whose TEMPLATES + style banks, whose CONTENT banks)
    if a.ablation:
        cells = ([(f"vocab:{p}", ABLATION_CONTROL, p) for p in PERSONAS]
                 + [(f"phrase:{p}", p, ABLATION_CONTROL) for p in PERSONAS])
        per_cell, out_path = ROWS_PER_ABLATION_CELL, ABLATION_OUT
    else:
        cells = [(p, p, p) for p in PERSONAS]
        per_cell, out_path = ROWS_PER_PERSONA, OUT

    rows = []
    global_seen: set = set()
    for label, tpl_owner, content_owner in cells:
        fill = dict(fillers_of[tpl_owner])
        for k in CONTENT_BANKS:
            fill[k] = fillers_of[content_owner][k]
        mine = []
        for f in fams:
            if f["persona"] != tpl_owner:
                continue
            g = dict(f)
            g["persona"] = label
            g["family"] = f"{label}:{f['structure']}:{f['variant']}"
            mine.append(g)
        # In ablation mode two cells can legitimately produce the same
        # sentence (the control's own cell appears in both blocks), so dedup
        # is per cell there; in normal mode it is global, which is stricter.
        seen = set() if a.ablation else global_seen
        quotas = allocate(mine, fill, per_cell)
        for f in sorted(mine, key=lambda f: f["family"]):
            for i, (text, slots) in enumerate(gen_rows(f, quotas[f["family"]], fill, seen), 1):
                rows.append({
                    "id": f"{f['family']}-{i:03d}",
                    "text": text,
                    "persona": label,
                    "split": "test",          # ALWAYS. see PERSONAS.md
                    "tier": f["tier"],
                    "structure": f["structure"],
                    "family": f["family"],
                    "gold": {"operation": f["op_gold"], "kind": f["kind_gold"],
                             "atomicity": "atomic" if f["atomic"] else "compound"},
                    "expect": {
                        "events": f["events"],
                        "tasks": f["tasks"],
                        "action": f["action"],
                        "atomic": f["atomic"],
                        "slots": slots,
                    },
                })

    # deterministic shuffle so consecutive rows aren't one family's burst
    random.Random(f"{SEED}:order").shuffle(rows)

    # ---- verification -------------------------------------------------
    assert len(rows) == per_cell * len(cells), len(rows)
    labels = [c[0] for c in cells]
    texts = [r["text"] for r in rows]
    if not a.ablation:
        assert len(set(texts)) == len(texts), "duplicate text across the set"
    assert len({r["id"] for r in rows}) == len(rows), "duplicate id"
    assert all(r["split"] == "test" for r in rows), "a persona row is not test-only"
    by_persona = Counter(r["persona"] for r in rows)
    assert set(by_persona) == set(labels) and set(by_persona.values()) == {per_cell}
    # the structure-matched invariant: every cell covers every structure
    cover = defaultdict(set)
    for r in rows:
        cover[r["persona"]].add(r["structure"])
    ids = {s["id"] for s in catalog}
    for label in labels:
        if cover[label] != ids:
            raise ValueError(f"{label} is missing structure(s) {sorted(ids - cover[label])}")

    leaks = {} if a.no_leak_check else leak_check(rows)
    if leaks:
        lines = "\n".join(f"    {w!r}  e.g. {ex}" for w, ex in sorted(leaks.items()))
        raise SystemExit(
            "LEAK GATE FAILED — the author's own vocabulary reached the persona "
            f"data:\n{lines}\n"
            "Replace each with an invented word, or — only if it is genuinely "
            "general English — declare it in dataset/personas/allowed_words.txt "
            "with a reason.")

    # ---- composition table --------------------------------------------
    kind = "ABLATION CELLS" if a.ablation else "PERSONA TEST SETS"
    print(f"{kind} — {len(rows)} rows, {len(cells)} cells x {per_cell}, "
          f"{len(catalog)} shared structures, {len(fams)} families")
    if a.ablation:
        print(f"  vocab:<p>  = {ABLATION_CONTROL}'s phrasing + <p>'s content banks "
              f"({', '.join(CONTENT_BANKS)})")
        print(f"  phrase:<p> = <p>'s phrasing + {ABLATION_CONTROL}'s content banks")
    print(f"Split: test={sum(1 for r in rows if r['split']=='test')} "
          f"(TEST-ONLY by construction — never fitted on)")
    print(f"Unique texts: {len(set(texts))}/{len(rows)}")
    vocab_n = len(read_vocab_words())
    print(f"Leak gate: {'SKIPPED' if a.no_leak_check else 'clean'} "
          f"({vocab_n} author words checked, "
          f"{len(allowed_words())} declared general)")
    print()
    hdr = f"{'':22s}" + "".join(f"{p[-13:]:>15s}" for p in labels)
    print("Rows by action:")
    print(hdr)
    acts = sorted({r["expect"]["action"] for r in rows})
    grid = Counter((r["persona"], r["expect"]["action"]) for r in rows)
    for act in acts:
        print(f"  {act:20s}" + "".join(f"{grid[(p, act)]:>15d}" for p in labels))
    print()
    print("Rows by atomicity (ground truth):")
    print(hdr)
    ag = Counter((r["persona"], r["expect"]["atomic"]) for r in rows)
    for flag, lab in ((True, "atomic"), (False, "compound")):
        print(f"  {lab:20s}" + "".join(f"{ag[(p, flag)]:>15d}" for p in labels))
    print()
    print("Mean words per utterance (the phrasing-style fingerprint):")
    print(hdr)
    wl = defaultdict(list)
    for r in rows:
        wl[r["persona"]].append(len(r["text"].split()))
    print(f"  {'words':20s}" + "".join(
        f"{sum(wl[p])/len(wl[p]):>15.1f}" for p in labels))
    print(f"  {'shortest':20s}" + "".join(f"{min(wl[p]):>15d}" for p in labels))
    print(f"  {'longest':20s}" + "".join(f"{max(wl[p]):>15d}" for p in labels))
    print()
    print("Sample row per cell (structure `and_et`, the same ask in every voice):")
    for lab in labels:
        ex = next(r for r in rows if r["persona"] == lab and r["structure"] == "and_et")
        print(f"  {lab:22s} {ex['text']}")

    if a.no_write:
        print("\n--no-write: nothing written")
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"\nWrote {len(rows)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
