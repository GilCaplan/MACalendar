"""SIZE TIERS of decompose_validate's generated set (Gil, 2026-10-01: "they
should be at least 40k with enough variation in the data … you can have
different level of the same dataset as well").

    python -m assistant.engine.decompose_validate.datasets.generate --tier 10k
    python -m assistant.engine.decompose_validate.datasets.generate --tier 40k

    tier   rows       where
    base   2,884      datasets/generated.jsonl (committed)
    10k    >= 10,000  datasets/tiers/generated_10k.jsonl (gitignored)
    40k    >= 40,000  datasets/tiers/generated_40k.jsonl (gitignored)

`eval_metrics/run_board --tier 10k|40k` reads a tier (built on demand when
missing); `--tier base` (default) reads the committed file as before.

THE BASE IS THE COMMITTED FILE, VERBATIM. Like segmentation's, the committed
`generated.jsonl` is not what the generator writes today (FastRule's bank grew
48 families since; 183 rows' gold differs from a regeneration). Every tier
starts with the committed lines byte for byte, then adds rows whose gold is
computed by THIS STAGE'S OWN generator code (`generate._gold_item` over
`segmentation.derive`, normalised by the hand-written `normalization.py`):

1. MORE RENDERS of a base family — only a family whose every committed row the
   generator reproduces exactly (text, anchor and gold); the others are not
   grown, and are reported.
2. FastRule's NEWER complex families (in the bank, not in the committed file;
   `force_split: "test"` ones left out). By the generator's own rule they are
   ORIGINAL-bank families, so TRAIN.
3. Segmentation's tier families (`segmentation/datasets/tiers.py`): its 29
   hand-written templates and its COMPOSED 2–4-ask families, shared on purpose
   so the two stages agree by construction about where an item's boundaries
   are (the reason this generator reuses segmentation's derivation at all).
   These are GROWN families: split 60/40 stratified by nuance with this
   generator's own `stratified_split`, run over the tier families alone so no
   existing family's side can move.

Tier rows are drawn over all 16 `GROWN_ANCHORS` (leap day, year end, a
Friday, …), never repeat a text already in the set, and refuse a filler that
does not normalise (the generator's rule: never guess). Dates and times come
only from the closed banks `normalization.py` covers; subject words widen with
segmentation's `banks/tier_fillers.json` (generic, hand-written).

SUPERSETS: every tier family is drawn once at `CAP` rows; a tier takes the
first `q` rows of every family. 10k is the per-family prefix of 40k.
"""
from __future__ import annotations

import collections
import json
import random
from pathlib import Path

from assistant.engine.decompose_validate.datasets import generate as DV
from assistant.engine.segmentation.datasets import tiers as SEGT

HERE = Path(__file__).resolve().parent
BASE = HERE / "generated.jsonl"
TIER_DIR = HERE / "tiers"
TIERS = {"base": 0, "10k": 10_000, "40k": 40_000}
TIER_SEED = "dv-generated-tiers-v1"
CAP = 40


def tier_path(tier: str) -> Path:
    return BASE if tier == "base" else TIER_DIR / f"generated_{tier}.jsonl"


def _banks():
    """(original banks, grown banks), each widened with the tier subject banks."""
    base_banks = json.load(open(Path(DV._BANKS) / "fillers.json"))
    grown = dict(base_banks)
    grown.update({k: v for k, v in json.load(open(Path(DV._GROWN) / "grown_fillers.json")).items()
                  if not k.startswith("_")})
    extra = {k: v for k, v in json.loads((SEGT.BANKS / "tier_fillers.json").read_text()).items()
             if not k.startswith("_")}

    def widen(b):
        b = {k: (list(v) if isinstance(v, list) else v) for k, v in b.items()}
        for k, v in extra.items():
            b[k] = b.get(k, []) + [x for x in v if x not in b.get(k, [])]
        return b
    return widen(base_banks), widen(grown)


def render_family(t: dict, banks: dict, cap: int, seen: set, split: str) -> "list[dict]":
    """`generate._emit`'s loop for one family, on the tier anchors and seed,
    never re-emitting a text in `seen` (lower-cased, shared)."""
    spec = DV.SEG.derive(t)
    if spec is None or t["action"] == "propose":
        return []
    rng = random.Random(f"{TIER_SEED}:{t['family']}")
    rows = []
    for n in range(cap * 6):
        if len(rows) >= cap:
            break
        anchor = DV.GROWN_ANCHORS[n % len(DV.GROWN_ANCHORS)]
        binding = DV.SEG._bind(t["template"], banks, rng)
        if not binding and DV._SLOT.search(t["template"]):
            break
        text = DV.SEG._fill(t["template"], binding)
        if text.lower() in seen or SEGT._DOUBLED_PREP.search(text):
            continue
        gold = [DV._gold_item(s, binding, anchor, text) for s in spec]
        if any(g is None for g in gold) or any(DV._incoherent(g) for g in gold):
            continue
        seen.add(text.lower())
        rows.append({"id": f"dv_{t['family']}_t{n}", "text": text,
                     "today": anchor.isoformat(), "gold": gold,
                     "traps": [t.get("nuance", "composed")], "family": t["family"],
                     "source": "generated", "split": split})
    return rows


def agreeing_families(base_rows) -> "tuple[set, list]":
    regen, _dropped = DV.build()
    by_id = {r["id"]: r for r in regen}
    ok = collections.defaultdict(lambda: True)
    for r in base_rows:
        g = by_id.get(r["id"])
        ok[r["family"]] = ok[r["family"]] and g == r
    return {f for f, v in ok.items() if v}, sorted(f for f, v in ok.items() if not v)


def draw_all(max_per_source: "int | None" = None):
    """(base lines, [(family, rows)], report); `max_per_source` stops each source
    after N families (a quick smoke for the tests)."""
    def full(key):
        return bool(max_per_source) and report[key] >= max_per_source

    base_lines = BASE.read_text().splitlines(keepends=True)
    base_rows = [json.loads(line) for line in base_lines]
    base_split = {r["family"]: r["split"] for r in base_rows}
    orig_banks, grown_banks = _banks()
    seen = {r["text"].lower() for r in base_rows}
    agree, disagree = agreeing_families(base_rows)
    complex_ = json.load(open(Path(DV._BANKS) / "complex_patterns.json"))
    grown_t = json.load(open(Path(DV._GROWN) / "grown_patterns.json"))
    drawn = []
    report = {"grown_base_families": 0, "not_grown_base_families": disagree,
              "new_fastrule_families": 0, "seg_tier_families": 0}
    for t in complex_ + grown_t:
        if full("grown_base_families"):
            break
        if t["family"] in agree:
            banks = grown_banks if t in grown_t else orig_banks
            rows = render_family(t, banks, CAP, seen, base_split[t["family"]])
            if rows:
                drawn.append((t["family"], rows))
                report["grown_base_families"] += 1
    for t in complex_:
        if full("new_fastrule_families"):
            break
        if t["family"] not in base_split and t.get("force_split") != "test":
            rows = render_family(t, orig_banks, CAP, seen, "train")
            if rows:
                drawn.append((t["family"], rows))
                report["new_fastrule_families"] += 1
    seg_families = (json.loads((SEGT.BANKS / "tier_patterns.json").read_text())["patterns"]
                    + SEGT.composed_families())
    clash = {t["family"] for t in seg_families} & ({t["family"] for t in complex_ + grown_t})
    assert not clash, f"a tier family reuses a bank family's name: {sorted(clash)[:5]}"
    split_of = DV.stratified_split(seg_families, 20260908)
    for t in seg_families:
        if full("seg_tier_families"):
            break
        rows = render_family(t, grown_banks, CAP, seen, split_of[t["family"]])
        if rows:
            drawn.append((t["family"], rows))
            report["seg_tier_families"] += 1
    return base_lines, drawn, report


_CACHE: dict = {}


def build_tier(tier: str) -> "list[str]":
    if tier not in TIERS:
        raise SystemExit(f"unknown tier {tier!r}; choose from {list(TIERS)}")
    if "dv" not in _CACHE:
        _CACHE["dv"] = draw_all()
    base_lines, drawn, _report = _CACHE["dv"]
    if tier == "base":
        return list(base_lines)
    q = SEGT.quota(len(base_lines), drawn, TIERS[tier], CAP)
    lines = list(base_lines) + [json.dumps(r) + "\n" for _f, rows in drawn for r in rows[:q]]
    sides = collections.defaultdict(set)
    for line in lines:
        r = json.loads(line)
        sides[r["family"]].add(r["split"])
    assert not [f for f, s in sides.items() if len(s) > 1], "a family on both sides"
    return lines


def write_tier(tier: str) -> Path:
    if tier == "base":
        raise SystemExit("the base tier is the committed file; it is never rewritten here")
    p = tier_path(tier)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(build_tier(tier)))
    return p


def ensure(tier: str) -> Path:
    p = tier_path(tier)
    if not p.exists():
        print(f"[tier {tier}] {p.name} missing — building it (deterministic)…", flush=True)
        write_tier(tier)
    return p


def stats(lines) -> dict:
    rows = [json.loads(line) for line in lines]
    fam_side = {r["family"]: r["split"] for r in rows}
    return {"rows": len(rows), "texts": len({r["text"].lower() for r in rows}),
            "text_anchor_pairs": len({(r["text"], r["today"]) for r in rows}),
            "families": len(fam_side),
            "train_rows": sum(r["split"] == "train" for r in rows),
            "test_rows": sum(r["split"] == "test" for r in rows),
            "train_families": sum(s == "train" for s in fam_side.values()),
            "test_families": sum(s == "test" for s in fam_side.values()),
            "items": sum(len(r["gold"]) for r in rows),
            "anchors": len({r["today"] for r in rows}),
            "asks": dict(sorted(collections.Counter(len(r["gold"]) for r in rows).items()))}
