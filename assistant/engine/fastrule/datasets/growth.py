"""The FastRule set's SIZE TIERS — growth families beyond the committed base.

Gil, 2026-10-01: *"a lot of the datasets seem really small, they should be at
least 40k with enough variation in the data"* and *"you can have different
level of the same dataset as well, sometimes can let user choose"*.

WHAT GROWS, AND WHY IT IS VARIATION RATHER THAN COPIES
------------------------------------------------------
The base set is 619 hand-written families, ~14 rows each. Growing it by
drawing more rows from those families would be the "big denominator" Gil
warned about — the same skeletons with new fillers. So nothing here touches
a base family. Growth comes from `banks/growth.json`, hand-written like every
other bank, in three authored parts:

  * CONSTRUCTIONS — verb frames, each with `{T}` where its title goes:
    "pencil in {T}", "i've got {T} coming up", "we're running low on {T}",
    "{T} got cancelled, remove it", "move {T} over to" ...
  * ARRANGEMENTS — ways of placing the when around a frame: date-then-clock,
    clock-then-date, fronted ("tomorrow at 5, ..."), a range, a weekday, a
    length, a repeat with a start or an end, a lead time, an attendee, a place,
    all-day ...
  * REGISTERS — how the speaker wraps it: bare, a lead-in ("ok so"), polite
    ("could you please"), a tail (", cheers"), a wake word, a hedge, a filler
    after the first word ("book um ..."), and a FLAT transcript with the
    punctuation gone.

A FAMILY is one construction x one arrangement, with one register chosen per
family by a stable hash; the register's words, the fillers and the times vary
row to row. Two-ask COMPOUNDS (the non-atomic diagnostic) join two atomic
families with a hand-written joiner.

GOLD IS THE BASE SET'S GOLD, COMPUTED THE SAME WAY. Every row goes through
`generate.gen_family_rows` and `generate.finish_rows` — the same slot
resolution, `gold_item`, rulings (Q26/Q47/Q50/Q55/Q56/Q61/Q62/Q63) and
category/tag labels as a committed row. A to-do said with a clock is declared
to `RULED_FAMILIES` exactly as the base's Q26 families are, so it carries
`ruled: "Q26"` the same way.

THE SPLIT IS BY CONSTRUCTION, with the generator's own rule. `stratified_split`
— the base set's family-level 80/20, stratified and hashed on SEED — is run
over the CONSTRUCTIONS (stratum = the construction's group) and over the
joiners. Every family inherits its construction's side, and a compound is only
built from two constructions and a joiner on the same side. So a test
construction is never seen in train in ANY arrangement or register: the test
half measures unseen wording, as the base split does. A guard then drops any
growth family whose skeleton equals a base skeleton, or nearly equals one on
the opposite split, and prints COUNTS ONLY (the base test half is never read
for its words — TRAIN_TEST_SPLIT_CONVENTION.md).

LEVELS, AND THE SUPERSET PROPERTY
---------------------------------
    20k   base + level 1   11,300 rows from ~36% of the growth families (wide)
    40k   20k  + level 2   20,000 rows from the other ~64% (wide)
    80k   40k  + level 3   40,000 more rows from every growth family (deep)

Each level runs after everything before it has claimed its texts, draws its
rows on its families' own RNG streams, is shuffled on its own stream and is
APPENDED — so each tier's file begins with the smaller tier's file, byte for
byte, as base's forced pools did. A family deepened by level 3 continues its
own id counter. Each level is exactly 80/20 train/test by rows.
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter, defaultdict

from assistant.engine.fastrule.datasets import generate as G
from assistant.engine.fastrule.datasets import tiers

BANK = G.BANKS / "growth.json"

#: level -> (mode, rows it adds). Sums with base's 8,700 to tiers.SIZES_ROWS.
LEVELS = {"20k": ("wide", 11_300), "40k": ("wide", 20_000), "80k": ("deep", 40_000)}
LEVEL_ORDER = ("20k", "40k", "80k")
WIDE_SPLIT = 11_300 / (11_300 + 20_000)     # share of growth families in level 1

#: compounds per atomic growth family, per split (base: ~31% of rows compound)
COMPOUND_SHARE = 0.30
#: a family is never asked for more than this share of its distinct renderings
CAPACITY_SHARE = 0.5
#: per level, no family takes more than this many times the level's mean rows
LEVEL_CAP_X = 2.0
#: near-duplicate threshold for the base-skeleton guard (bigram Jaccard)
NEAR_DUP = 0.85

#: placeholder bank -> skeleton class for the base-duplicate guard; a bank not
#: listed is cosmetic (a wrapper's words) and drops out of the skeleton.
_SKEL_CLASS = {
    "event_titles": "E", "g_event_titles": "E", "occasions": "E", "quotable": "E",
    "task_titles": "T", "g_task_titles": "T", "items": "I", "g_items": "I",
    "dates": "D", "weekdays": "D", "uk_dates": "D", "g_dates": "D",
    "query_ranges": "D", "g_query_ranges": "D", "g_prep_dates": "D",
    "times": "C", "clock_times": "C", "uk_times": "C", "g_clock_times": "C",
    "time_ranges": "R", "g_time_ranges": "R",
    "recurrences": "REC", "recurrences_more": "REC", "g_recurrences": "REC",
    "names": "N", "g_names": "N", "lead_times": "L", "g_lead_times": "L",
    "durations": "DUR", "g_lengths": "DUR", "quantities": "Q", "g_places": "P",
    "list_names": "LIST", "generic_targets": "G",
}
_PUNCT = re.compile(r"[,.:;!?]")


def load_bank() -> dict:
    with open(BANK, encoding="utf-8") as f:
        return json.load(f)


def growth_fillers(base_fillers: dict, bank: dict) -> dict:
    """The g_ banks: each one's new values, after its base list when it
    `extends` one. Refuses a key that collides with a base bank or a value
    listed twice (a duplicate would silently double its draw rate)."""
    out = {}
    for key, vals in bank["fillers"].items():
        if key in base_fillers:
            raise ValueError(f"growth bank {key} collides with a base bank")
        ext = bank["extends"].get(key)
        merged = (list(base_fillers[ext]) if ext else []) + list(vals)
        dupes = [v for v, n in Counter(merged).items() if n > 1]
        if dupes:
            raise ValueError(f"growth bank {key} lists {dupes} twice")
        out[key] = merged
    for key, spec in bank.get("derived", {}).items():
        if key in base_fillers or key in out:
            raise ValueError(f"derived growth bank {key} collides")
        out[key] = [v for v in out[spec["from"]] if not v.startswith(tuple(spec["drop_prefixes"]))]
    return out


def _stable_unit(*parts: str) -> float:
    return G.stable_int(G.SEED, *parts) / float(1 << 64)


def _midfill(frame: str) -> str:
    """A filler after the frame's first word ("book um {T}") — only when that
    word is a real word, not a slot."""
    head, _, rest = frame.partition(" ")
    if not rest or head.startswith("{"):
        return frame
    return f"{head} {{g_um}} {rest}"


def _skeleton(template: str) -> tuple:
    def cls(m):
        bank_key, _sem, _base = G.placeholder_info(m.group(1))
        c = _SKEL_CLASS.get(bank_key)
        return f" <{c}> " if c else " "
    s = G.TOKEN_RE.sub(cls, template).lower()
    return tuple(_PUNCT.sub(" ", s).split())


def _bigrams(sk: tuple) -> frozenset:
    seq = ("^",) + sk + ("$",)
    return frozenset(zip(seq, seq[1:]))


# ---------------------------------------------------------------------------
# families
# ---------------------------------------------------------------------------

def _atomic_families(bank: dict, cons_split: dict) -> list[dict]:
    groups, regs = bank["groups"], bank["registers"]
    fams = []
    for c in bank["constructions"]:
        group = groups[c["group"]]
        for a in bank["arrangements"]:
            if c["group"] not in a["groups"]:
                continue
            if a.get("nodet") and c.get("det"):
                continue
            if a.get("qty") and not c.get("qty"):
                continue
            name = f"g_{c['id']}_{a['id']}"
            allowed = [r for r, spec in regs.items()
                       if c["mood"] in spec["moods"]
                       and not (a.get("fronted") and spec.get("prefix"))
                       and not (c.get("needs_slot") and spec["wrap"] == "{X}"
                                and not spec.get("midfill"))]
            reg = allowed[G.stable_int(G.SEED, "growth-register", name) % len(allowed)]
            spec = regs[reg]
            frame = _midfill(c["frame"]) if spec.get("midfill") else c["frame"]
            core = a["shape"].replace("{F}", frame.replace("{T}", a.get("T", group["T"])))
            template = spec["wrap"].replace("{X}", core)
            if spec.get("flat"):
                template = re.sub(r"\s+", " ", _PUNCT.sub(" ", template)).strip()
            action = group["action"]
            fam = {
                "family": name, "construction": c["id"], "arrangement": a["id"],
                "register": reg, "group": c["group"], "kind": group.get("kind"),
                "action": action, "atomic": True,
                "events": 1 if action == "create_event" else 0,
                "tasks": 1 if action == "create_todo" else 0,
                "template": template, "_core": core, "_tier": a["tier"],
                "nuance": a.get("nuance") or f"g_{c['group']}",
                "split": cons_split[c["id"]],
            }
            if a.get("fixed_slots"):
                fam["fixed_slots"] = dict(a["fixed_slots"])
            if a.get("flags"):
                fam["flags"] = dict(a["flags"])
            fam["_clock"] = bool(re.search(r"\{g_(?:clock|range)\}", core))
            fams.append(fam)
    return fams


def _compound_families(bank: dict, atomic: list[dict], joiner_split: dict) -> list[dict]:
    """Two atomic asks and a joiner, all on one split. B is the bare core with
    every slot renumbered ({g_event} -> {g_event2})."""
    out = []
    for split in ("train", "test"):
        pool = sorted((f for f in atomic if f["split"] == split and f["_tier"] == "simple"
                       and f["group"] in ("event", "todo", "shop")),
                      key=lambda f: f["family"])
        joiners = [j for j in bank["joiners"] if joiner_split[j["id"]] == split]
        n_atomic = sum(1 for f in atomic if f["split"] == split)
        want = round(COMPOUND_SHARE * n_atomic)
        rng = random.Random(f"{G.SEED}:growth:compounds:{split}")
        names, attempts = set(), 0
        while len([f for f in out if f["split"] == split]) < want and attempts < want * 50:
            attempts += 1
            a, b, j = rng.choice(pool), rng.choice(pool), rng.choice(joiners)
            if a["construction"] == b["construction"]:
                continue
            name = f"gx_{a['family'][2:]}__{b['construction']}_{b['arrangement']}__{j['id']}"
            if name in names:
                continue
            names.add(name)
            b_core = G.TOKEN_RE.sub(lambda m: "{" + m.group(1) + "2}", b["_core"])
            template = j["wrap"].replace("{A}", a["template"]).replace("{B}", b_core)
            ka, kb = a["kind"], b["kind"]
            fam = {
                "family": name, "construction": f"{a['construction']}+{b['construction']}",
                "arrangement": f"{a['arrangement']}+{b['arrangement']}", "register": a["register"],
                "joiner": j["id"], "group": "compound", "kind": None,
                "atomic": False, "template": template, "_tier": "complex",
                "nuance": "g_compound", "split": split,
                "_parts": (a["construction"], b["construction"], j["id"]),
            }
            if ka == kb == "event":
                fam.update(action="create_event", events=2, tasks=0)
            elif ka == kb == "task":
                fam.update(action="create_todo", events=0, tasks=2)
            else:
                fam.update(action="mixed", events=1, tasks=1,
                           event_label_sources=["title" if ka == "event" else "title_2"],
                           task_label_sources=["title" if ka == "task" else "title_2"])
            q26 = ([("title", None)] if ka == "task" and a["_clock"] else []) + \
                  ([("title_2", None)] if kb == "task" and b["_clock"] else [])
            fam["_q26"] = q26
            out.append(fam)
    return out


def _guard(fams: list[dict], base_families: list[dict]) -> tuple[list[dict], dict]:
    """Drop growth families that are not new constructions: a skeleton EQUAL to
    any base skeleton, or within NEAR_DUP of one on the OPPOSITE split (a train
    family copying a test skeleton would leak it; a test family copying a train
    one would not be unseen). Returns counts only — no base text is printed."""
    base = [(_skeleton(f["template"]), f["split"]) for f in base_families]
    exact = {sk for sk, _ in base}
    by_split = {"train": [_bigrams(sk) for sk, s in base if s == "test"],
                "test": [_bigrams(sk) for sk, s in base if s == "train"]}
    kept, counts = [], Counter()
    for fam in fams:
        sk = _skeleton(fam["template"])
        if sk in exact:
            counts["exact"] += 1
            continue
        bg = _bigrams(sk)
        if any(len(bg & o) / len(bg | o) >= NEAR_DUP for o in by_split[fam["split"]]):
            counts[f"near_{fam['split']}"] += 1
            continue
        kept.append(fam)
    return kept, counts


def build_families(bank: dict, base_families: list[dict], fillers: dict) -> tuple[list[dict], dict]:
    cons_split = G.stratified_split([{"tier": "growth", "action": c["group"], "family": c["id"]}
                                     for c in bank["constructions"]])
    joiner_split = G.stratified_split([{"tier": "growth", "action": "joiner", "family": j["id"]}
                                       for j in bank["joiners"]])
    atomic = _atomic_families(bank, cons_split)
    compound = _compound_families(bank, atomic, joiner_split)
    fams, dropped = _guard(atomic + compound, base_families)
    for fam in fams:
        if fam["family"] in G.RULED_FAMILIES:
            raise ValueError(f"growth family {fam['family']} collides with a ruled base family")
        q26 = fam.get("_q26") if fam["group"] == "compound" else (
            [("title", None)] if fam["group"] == "todo" and fam["_clock"] else [])
        if q26:
            # the base's Q26 families, declared the same way: a to-do said with
            # a clock or a range is an event (DEVQA Q25/Q26)
            G.RULED_FAMILIES[fam["family"]] = ("Q26", q26)
        G._init_family(fam, fam["_tier"], fillers)
        fam["_capacity"] = max(1, int(G.family_capacity(fam, fillers) * CAPACITY_SHARE))
        fam["level"] = "20k" if _stable_unit("growth-level", fam["family"]) < WIDE_SPLIT else "40k"
    info = {"dropped": dict(dropped), "cons_split": cons_split, "joiner_split": joiner_split}
    return fams, info


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def _weighted(total: int, weights: dict) -> dict:
    """Largest-remainder split of `total` by `weights` (deterministic ties)."""
    wsum = sum(weights.values())
    raw = {k: total * w / wsum for k, w in weights.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: (-(raw[k] - out[k]), k))[:total - sum(out.values())]:
        out[k] += 1
    return out


def _fill(fams: list[dict], split: str, target: int, have: dict, level: str,
          fillers: dict, global_seen: set, label_ctx: tuple, cap_left: dict,
          strict: bool = True):
    """`target` rows from `fams`, evenly, each capped at its remaining
    capacity AND at what this level still allows it (`cap_left`, shared by the
    group pass and the spill pass); a family that runs dry (its renderings
    collide with texts already claimed) hands its shortfall to the others in a
    further round."""
    out, remaining = [], target
    caps = {f["family"]: max(0, min(f["_capacity"] - have[f["family"]], cap_left[f["family"]]))
            for f in fams}
    for _round in range(8):
        if remaining == 0:
            break
        live = [f for f in fams if caps[f["family"]] > 0]
        room = sum(caps[f["family"]] for f in live)
        if not room or (strict and room < remaining):
            break
        quotas = G.distribute_quota(min(remaining, room), [f["family"] for f in live], caps)
        for fam in live:
            q = quotas[fam["family"]]
            if not q:
                continue
            got = G.gen_family_rows(fam, q, fillers, global_seen)
            rows = G.finish_rows(fam, got, split, fam["tier"], have[fam["family"]], *label_ctx)
            for r in rows:
                r["level"] = level
                r["construction"] = fam["construction"]
            have[fam["family"]] += len(got)
            cap_left[fam["family"]] -= len(got)
            remaining -= len(got)
            out += rows
            caps[fam["family"]] = 0 if len(got) < q else caps[fam["family"]] - len(got)
    if remaining and strict:
        raise ValueError(f"level {level} {split}: {remaining} rows short — widen the growth banks")
    return out if strict else (out, remaining)


def build(size: str, base_families: list[dict], base_fillers: dict, global_seen: set,
          categories_mod, tagging_mod, task_tag_keywords: dict, verbose: bool = True) -> list[dict]:
    """Every growth row a `size` tier adds on top of base, in file order."""
    if size == "base":
        return []
    bank = load_bank()
    fillers = dict(base_fillers)
    fillers.update(growth_fillers(base_fillers, bank))
    clash = set(bank["recurrence_round"]) & set(G.RECURRENCE_ROUND)
    if clash:
        raise ValueError(f"growth recurrences already rounded by base: {clash}")
    G.RECURRENCE_ROUND.update(bank["recurrence_round"])
    for v in fillers["g_recurrences"]:
        if v not in G.RECURRENCE_ROUND:
            raise ValueError(f"growth recurrence {v!r} has no rounding")

    fams, info = build_families(bank, base_families, fillers)
    label_ctx = (categories_mod, tagging_mod, task_tag_keywords)
    have = {f["family"]: 0 for f in fams}
    levels = LEVEL_ORDER[:LEVEL_ORDER.index(size) + 1]
    rows: list[dict] = []
    for level in levels:
        mode, total = LEVELS[level]
        level_rows = []
        for split, target in (("train", round(total * G.TRAIN_FRAC)),
                              ("test", total - round(total * G.TRAIN_FRAC))):
            pool = [f for f in fams if f["split"] == split and (mode == "deep" or f["level"] == level)]
            # rows by GROUP first, so the 57 event constructions x 20
            # arrangements do not swamp the 14 delete-to-do frames; whatever a
            # group cannot supply is spread over the whole pool after
            by_group = defaultdict(list)
            for f in pool:
                by_group[f["group"]].append(f)
            weights = {g: w for g, w in bank["group_weights"].items() if by_group.get(g)}
            # no family may take more than LEVEL_CAP_X times the level's mean,
            # so a small group's share cannot pile onto its two or three
            # families (it spills to the pool instead)
            cap = math.ceil(LEVEL_CAP_X * target / len(pool))
            cap_left = {f["family"]: cap for f in pool}
            short = 0
            for g, n in _weighted(target, weights).items():
                got, missing = _fill(by_group[g], split, n, have, level, fillers,
                                     global_seen, label_ctx, cap_left, strict=False)
                level_rows += got
                short += missing
            if short:
                level_rows += _fill(pool, split, short, have, level, fillers, global_seen,
                                    label_ctx, cap_left)
        random.Random(f"{G.SEED}:growth:{level}:order").shuffle(level_rows)
        rows += level_rows

    _verify(size, rows, fams)
    if verbose:
        _report(size, rows, fams, info, bank)
    return rows


def _verify(size: str, rows: list[dict], fams: list[dict]) -> None:
    want = tiers.SIZES_ROWS[size] - tiers.SIZES_ROWS["base"]
    assert len(rows) == want, (len(rows), want)
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids), "duplicate growth ids"
    split_of = defaultdict(set)
    for r in rows:
        split_of[r["family"]].add(r["split"])
    leaked = [f for f, s in split_of.items() if len(s) > 1]
    if leaked:
        raise ValueError(f"growth families on both splits: {leaked[:3]}")
    # a construction (or joiner) is on ONE side, atomic or inside a compound
    side = defaultdict(set)
    for f in fams:
        parts = f.get("_parts") or (f["construction"],)
        for p in parts:
            side[p].add(f["split"])
    both = [p for p, s in side.items() if len(s) > 1]
    if both:
        raise ValueError(f"constructions on both splits: {both[:3]}")
    for r in rows:
        e = r["expect"]
        for i in range(1, e["events"] + 1):
            assert ("category" if i == 1 else f"category_{i}") in e["slots"], r["id"]
        for i in range(1, e["tasks"] + 1):
            assert ("tags" if i == 1 else f"tags_{i}") in e["slots"], r["id"]


def _report(size: str, rows: list[dict], fams: list[dict], info: dict, bank: dict) -> None:
    used = {r["family"] for r in rows}
    fam_by = {f["family"]: f for f in fams}
    print(f"\n=== size tier {size}: {len(rows)} growth rows on top of base "
          f"({tiers.SIZES_ROWS[size]} total) ===")
    print(f"base-skeleton guard dropped (counts only): {info['dropped'] or 'none'}")
    for level in LEVEL_ORDER:
        lr = [r for r in rows if r["level"] == level]
        if not lr:
            continue
        sp = Counter(r["split"] for r in lr)
        print(f"  level {level}: {len(lr)} rows  train={sp['train']} test={sp['test']}  "
              f"families={len({r['family'] for r in lr})}")
    sp = Counter(r["split"] for r in rows)
    per_fam = Counter(r["family"] for r in rows)
    cons = {fam_by[f]["construction"] for f in used if fam_by[f]["group"] != "compound"}
    print(f"growth families used: {len(used)} "
          f"(train {len({f for f in used if fam_by[f]['split'] == 'train'})}, "
          f"test {len({f for f in used if fam_by[f]['split'] == 'test'})}); "
          f"constructions {len(cons)}, arrangements "
          f"{len({fam_by[f]['arrangement'] for f in used if fam_by[f]['group'] != 'compound'})}, "
          f"registers {len({fam_by[f]['register'] for f in used})}, "
          f"joiners {len({fam_by[f].get('joiner') for f in used} - {None})}")
    print(f"rows per family: max {max(per_fam.values())}, "
          f"mean {len(rows) / len(per_fam):.1f}; split train={sp['train']} test={sp['test']}")
    print("by action:", dict(Counter(r["expect"]["action"] for r in rows).most_common()))
    print("by group:", dict(Counter(fam_by[r["family"]]["group"] for r in rows).most_common()))
    print("atomic:", dict(Counter(r["expect"]["atomic"] for r in rows)),
          " ruled:", dict(Counter(r["expect"].get("ruled") for r in rows
                                  if r["expect"].get("ruled")).most_common()))
