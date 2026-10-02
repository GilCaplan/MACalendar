"""SIZE TIERS of segmentation's generated corpus and trap sets (Gil,
2026-10-01: "they should be at least 40k with enough variation in the data …
you can have different level of the same dataset as well").

    python -m assistant.engine.segmentation.experiments.generate --tier 10k
    python -m assistant.engine.segmentation.experiments.generate --tier 40k
    python -m assistant.engine.segmentation.experiments.generate --tier grown --traps

    set                  base (committed)   tiers (gitignored, datasets/tiers/)
    generated.jsonl      1,549              generated_10k.jsonl (>= 10,000), generated_40k.jsonl (>= 40,000)
    split_traps.jsonl    75                 split_traps_grown.jsonl   (honest ceiling, see TRAPS)
    nosplit_traps.jsonl  87                 nosplit_traps_grown.jsonl (honest ceiling, see TRAPS)

`run_board --tier 10k|40k` reads the generated tier plus the GROWN traps;
`--tier base` (the default) reads the three committed files exactly as before.
A missing tier file is built on demand.

THE BASE IS THE COMMITTED FILE, VERBATIM. `generated.jsonl` is NOT what the
generator writes today: since it was written, FastRule's bank gained 47
families and the file's gold was relabelled by rulings (Q47/Q50 by
`intent/encounter.py`, and 30 query items the generator now tags `event`).
So every tier starts with the committed lines byte for byte, and grows from
three sources whose gold is computed exactly as the base's was:

1. MORE RENDERS of a base family — only when the generator plus the ruling
   relabel (`relabel`) reproduces EVERY committed row of that family exactly.
   A family where they disagree cannot say which gold its new rows should
   carry, so it is not grown (reported, never guessed).
2. FastRule's NEWER complex families (in the bank, not in the committed file),
   through the same generator and relabel. FastRule's `force_split: "test"`
   families are left out, so no FastRule test family is ADDED (the committed
   base already holds some, and they are grown like the rest).
3. NEW FAMILIES written for this stage (`banks/tier_patterns.json`):
   * COMPOSED families — 2 to 4 single-ask CLAUSES joined by and / then /
     and then / , then / and also / , also / plus / as well as / commas. The
     clauses are FastRule's single-ask templates (train side only: no
     `force_split: "test"` family, nothing with a literal time word outside a
     slot, nothing that already holds a joiner) plus 40 hand-written clauses (199 kept).
     The gold is `derive()` on the composed template; a composition is kept
     only when every derived item's action equals its clause's own derived
     action (so the cut is exactly the clauses) — otherwise it is dropped.
   * 29 whole templates: decoys whose "and" must NOT split (salt and pepper,
     "the food and wine festival", "lunch with A and B", "print and sign",
     "buy X, Y and Z"), and multi-ask shapes in new wordings.
   Subject words widen with `banks/tier_fillers.json` (hand-written, generic:
   48 event titles, 40 to-dos, 20 items, 25 names, and four new action-only
   banks). Dates and times are NOT extended: decompose_validate shares these
   families and normalises dates/times from a closed hand-written table.

Every tier row passes the generator's own `validate()` (the invariant, the
self-contradicting-time check, the bank's count) and the ruling relabel.
Rows carry no `split`, exactly like the base rows: `run_board.assign_splits`
stamps it by a SHA-1 of the family (40% of families to test), so a new
family's side is decided by the same rule as an old one's.

SUPERSETS. Every tier family is drawn once at the cap (`CAP` rows), deduplicated
against the base and each other in one fixed order; a tier takes the first `q`
rows of every family, `q` the smallest that reaches the tier's size. 10k is the
per-family prefix of 40k.

TRAPS. The trap files are hand-written sentences with hand-written gold, and
their conventions are NOT derive()'s ("book the physio at 8 and the team sync
at 11" distributes the verb: "book the team sync"). 40,000 genuine traps
cannot be written by hand here, and generating them with derive() would quietly
change their conventions. So the trap tier is `grown`: the committed rows
plus TRAP TEMPLATES (`banks/trap_templates.json`) — each a hand-written
sentence shape with its gold written by hand in the trap file's own
conventions, slots filled from generic banks. The ceiling is the number of
distinct trap templates times the rows they can honestly carry (`TRAP_CAP`);
it is reported, not padded to 40k.
"""
from __future__ import annotations

import collections
import hashlib
import json
import random
import re
from pathlib import Path

from assistant.engine.segmentation.experiments import generate as SEG
from assistant.intent.encounter import _WRITTEN, is_encounter, is_role_call, names_the_list

HERE = Path(__file__).resolve().parent
BANKS = HERE / "banks"
TIER_DIR = HERE / "tiers"
FASTRULE_BANKS = Path(SEG._BANKS)

TIERS = {"base": 0, "10k": 10_000, "40k": 40_000}
TIER_SEED = "seg-generated-tiers-v1"
#: rows per tier family at most (a base family's 6 committed rows not counted)
CAP = 40
#: composed families drawn
N_COMPOSED = 1300
TRAP_CAP = 30

BASE_FILES = {"generated": HERE / "generated.jsonl",
              "split_traps": HERE / "split_traps.jsonl",
              "nosplit_traps": HERE / "nosplit_traps.jsonl"}


def tier_path(name: str, tier: str) -> Path:
    if tier == "base":
        return BASE_FILES[name]
    if name != "generated":
        tier = "grown"
    return TIER_DIR / f"{name}_{tier}.jsonl"


# ---------------------------------------------------------------------------
# The ruling relabel the committed file carries (Q47 / Q50)
# ---------------------------------------------------------------------------

_QUESTION = re.compile(r"\bwhat(?:'s| is| do)\b|\bcheck what\b|\bdo i have\b", re.I)
_CREATE_VERB = re.compile(r"\b(?:add|book|put|schedule|create|set up|pencil|mark|remove|"
                          r"delete|move|cancel)\b", re.I)
#: a preposition the template wrote in front of a filler that brings its own
#: ("delay X by by 15 minutes", "move X to in two days") — FastRule bank
#: renders the tiers refuse rather than copy
_DOUBLED_PREP = re.compile(r"\b(?:by|to|at|on|for) (?:by|to|at|on|for|in)\b", re.I)


def relabel(items: "list[dict]") -> "list[dict]":
    """The rulings the committed corpus was relabelled by, applied by rule:

    * Q50 — a live call to a ROLE ("call the plumber") is an event;
    * Q47 — an encounter with a person ("call Dana and Avery") is an event;
    * Q47 — a WRITTEN message ("remind me to email Robin about the session")
      is a to-do, unless a stated clock makes it an event (Q26).
    Each relabelled item carries `ruled`, as the committed rows do."""
    out = []
    for it in items:
        it = dict(it)
        act = it["action"]
        if it["tag"] == "event" and _QUESTION.search(act) and not _CREATE_VERB.search(act):
            # a QUESTION about the calendar is a review even when it names the
            # calendar: the committed corpus reads "what's on my calendar this
            # weekend" as review (30 items), where today's generator, checking
            # the destination first, says event. No `ruled` mark: the
            # committed rows carry none for it.
            it["tag"] = "review"
        elif it["tag"] == "task" and not names_the_list(act):
            if is_role_call(act):
                it["tag"], it["ruled"] = "event", "Q50"
            elif is_encounter(act):
                it["tag"], it["ruled"] = "event", "Q47"
        elif (it["tag"] == "event" and _WRITTEN.search(act)
              and re.match(r"^(?:remind me to|i need to|i have to|don't forget to)\s+"
                           r"(?:email|e-mail|text|message|write to|send|ping|dm)\b", act, re.I)
              and not SEG.states_a_clock(it["time"])):
            it["tag"], it["ruled"] = "task", "Q47"
        out.append(it)
    return out


# ---------------------------------------------------------------------------
# Banks
# ---------------------------------------------------------------------------

def _load(p: Path):
    return json.loads(p.read_text())


def tier_banks() -> dict:
    """FastRule's filler pools with the tier additions appended (copies)."""
    banks = _load(FASTRULE_BANKS / "fillers.json")
    extra = {k: v for k, v in _load(BANKS / "tier_fillers.json").items() if not k.startswith("_")}
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in banks.items()}
    for k, v in extra.items():
        out[k] = out.get(k, []) + [x for x in v if x not in out.get(k, [])]
    return out


_LITERAL_TIME = re.compile(
    r"\b(?:today|tonight|tomorrow|tommorow|tmrw|morning|afternoon|evening|noon|midnight|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|week|month|"
    r"o'clock|daily|weekly)\b|\d", re.I)


def clause_bank() -> "list[dict]":
    """Single-ask templates the tiers compose: FastRule's (train side) plus
    our own. A clause is kept only when it derives to exactly one item with an
    action, holds no joiner and no literal time word outside a slot."""
    simple = _load(FASTRULE_BANKS / "simple_patterns.json")
    ours = _load(BANKS / "tier_patterns.json")["clauses"]
    out, seen = [], set()
    for t in [dict(x, source="fastrule") for x in simple
              if x.get("force_split") != "test"] + [dict(x, source="tier") for x in ours]:
        tpl = t["template"].strip()
        if tpl in seen or SEG._JOINER.search(tpl) or _LITERAL_TIME.search(
                SEG._ANY_SLOT.sub(" ", tpl)):
            continue
        slots = SEG._ANY_SLOT.findall(tpl)
        if any(s not in SEG._FILL for s in slots) or any(s[-1].isdigit() for s in slots):
            continue
        spec = SEG.derive({"template": tpl, "atomic": True, "action": t["action"]})
        if not spec or len(spec) != 1:
            continue
        seen.add(tpl)
        out.append({"family": t["family"], "action": t["action"], "template": tpl,
                    "spec": spec[0], "source": t["source"]})
    return out


#: (joiner as written, how it is named in the family)
_JOIN2 = [(" and ", "and"), (" then ", "then"), (" and then ", "andthen"),
          (", then ", "commathen"), (" and also ", "andalso"), (", also ", "commaalso"),
          (" plus ", "plus"), (", ", "comma"), (" as well as ", "aswellas"),
          (", and ", "commaand")]
_NUMBERED = {"event_title": 3, "task_title": 3, "item": 3, "date": 3, "time": 3,
             "name": 2, "recurrence": 2, "query_range": 2, "period_time": 2}


def _renumber(clauses: "list[dict]") -> "str | None":
    """Join clauses' templates with numbered slots ({date}, {date2}, …) so the
    composed row binds distinct values; None when a slot would run out."""
    used = collections.Counter()
    parts = []
    for c in clauses:
        def sub(m):
            s = m.group(1)
            used[s] += 1
            k = used[s]
            if k == 1:
                return "{" + s + "}"
            if k > _NUMBERED.get(s, 1):
                raise KeyError(s)
            return "{" + f"{s}{k}" + "}"
        try:
            parts.append(SEG._ANY_SLOT.sub(sub, c["template"]))
        except KeyError:
            return None
    return parts


def _composed_template(clauses, joins) -> "str | None":
    parts = _renumber(clauses)
    if parts is None:
        return None
    out = parts[0]
    for j, p in zip(joins, parts[1:]):
        out += j + p
    return out


def composed_families() -> "list[dict]":
    bank = clause_bank()
    rng = random.Random(f"{TIER_SEED}:compose")
    out, sigs, tries = [], set(), 0
    while len(out) < N_COMPOSED and tries < N_COMPOSED * 50:
        tries += 1
        n = rng.choices([2, 3, 4], weights=[55, 30, 15])[0]
        clauses = rng.sample(bank, n)
        if n == 2:
            joins = [rng.choice(_JOIN2)]
        else:
            style = rng.random()
            if style < 0.4:                       # a list: commas, then a final joiner
                last = rng.choice([(", and ", "commaand"), (" and ", "and"), (", then ", "commathen"),
                                   (" and then ", "andthen"), (", plus ", "commaplus")])
                joins = [(", ", "comma")] * (n - 2) + [last]
            elif style < 0.7:                     # the same joiner throughout
                joins = [rng.choice(_JOIN2[:7])] * (n - 1)
            else:                                 # mixed
                joins = [rng.choice(_JOIN2) for _ in range(n - 1)]
        sig = (tuple(c["template"] for c in clauses), tuple(j for j, _ in joins))
        if sig in sigs:
            continue
        tpl = _composed_template(clauses, [j for j, _ in joins])
        if tpl is None:
            continue
        t = {"template": tpl, "atomic": False, "action": "mixed", "events": None, "tasks": None}
        spec = SEG.derive(t)
        if not spec or len(spec) != n:
            continue
        # the cut is exactly the clauses: each item's action is its clause's own
        want = [SEG._fill(c["spec"]["action"], {}) for c in clauses]
        got = [re.sub(r"\{(\w+?)\d\}", r"{\1}", s["action"]) for s in spec]
        if got != want:
            continue
        # An EDGE time scoping onto another clause (the spec's leading /
        # trailing rule) is only honest between two CREATES: "pencil in X
        # tomorrow and buy milk" can share a day, but "i finished X and move
        # Y to 11am" must not hand "to 11am" to the finished task, and a
        # question's range ("what's on this week") is not a time for a create.
        parts = _renumber(clauses)
        own = [SEG.derive({"template": p, "atomic": True, "action": c["action"]})[0]["time"]
               for p, c in zip(parts, clauses)]
        creates = [c["action"] in ("create_event", "create_todo") for c in clauses]
        bad_scope = False
        for i, (s, o) in enumerate(zip(spec, own)):
            if s["time"] == o:
                continue
            # the source is the first clause (leading) or the last (trailing);
            # both must be creates, conservatively, as must the receiver
            if not (creates[i] and creates[0] and creates[-1]) or "query_range" in s["time"]:
                bad_scope = True
                break
        if bad_scope:
            continue
        sigs.add(sig)
        name = "tc_" + hashlib.sha1(repr(sig).encode()).hexdigest()[:10]
        out.append(dict(t, family=name, nuance=f"composed_{n}ask",
                        joiners=[k for _, k in joins],
                        clauses=[c["family"] for c in clauses]))
    return out


# ---------------------------------------------------------------------------
# Rendering — the generator's own loop, plus the relabel
# ---------------------------------------------------------------------------

def render_family(t: dict, banks: dict, cap: int, seen: set, start: int = 0) -> "list[dict]":
    """Up to `cap` validated rows of one template, never a text in `seen`
    (lower-cased, shared, updated in place). Same steps as `generate.build`:
    bind, fill, derive's gold, Q26/Q61, validate; then the ruling relabel."""
    spec = SEG.derive(t)
    if spec is None:
        return []
    rng = random.Random(f"{TIER_SEED}:{t['family']}")
    rows = []
    for n in range(cap * 6):
        if len(rows) >= cap:
            break
        binding = SEG._bind(t["template"], banks, rng)
        if not binding and SEG._ANY_SLOT.search(t["template"]):
            break
        text = SEG._fill(t["template"], binding)
        if text.lower() in seen or _DOUBLED_PREP.search(text):
            continue
        items = [{"action": SEG._fill(s["action"], binding),
                  "time": SEG._fill(s["time"], binding), "tag": s["tag"]} for s in spec]
        for it in items:
            it["tag"] = SEG.q61_tag(SEG.q26_tag(it["tag"], it["time"]), it["time"])
        if SEG.validate(text, items, t):
            continue
        seen.add(text.lower())
        rows.append({"id": f"gen_{t['family']}_t{start + n}", "text": text,
                     "gold": relabel(items), "traps": [t.get("nuance", "composed")],
                     "source": "generated", "family": t["family"], "atomic": t["atomic"]})
    return rows


def agreeing_families(base_rows: "list[dict]") -> "tuple[set, dict]":
    """Base families whose EVERY committed row the generator + relabel
    reproduces exactly — the only base families it is honest to grow."""
    regen, _dropped = SEG.build()
    by_id = {r["id"]: r for r in regen}
    ok, bad = collections.defaultdict(lambda: True), collections.Counter()
    for r in base_rows:
        g = by_id.get(r["id"])
        same = bool(g) and g["text"] == r["text"] and relabel(g["gold"]) == r["gold"]
        ok[r["family"]] = ok[r["family"]] and same
        if not same:
            bad[r["family"]] += 1
    return {f for f, v in ok.items() if v}, dict(bad)


def draw_all_generated(max_per_source: "int | None" = None):
    """(base lines, [(family name, rows)], report) — every tier family at the
    cap. `max_per_source` stops each of the four sources after N families (a
    quick smoke for the tests)."""
    def full(key):
        return bool(max_per_source) and report[key] >= max_per_source

    base_lines = BASE_FILES["generated"].read_text().splitlines(keepends=True)
    base_rows = [json.loads(line) for line in base_lines]
    banks = tier_banks()
    seen = {r["text"].lower() for r in base_rows}
    agree, disagree = agreeing_families(base_rows)
    complex_ = _load(FASTRULE_BANKS / "complex_patterns.json")
    base_fams = {r["family"] for r in base_rows}
    drawn, report = [], {"grown_base_families": 0, "not_grown_base_families": sorted(disagree),
                         "new_fastrule_families": 0, "own_patterns": 0, "composed": 0}
    # 1. more renders of agreeing base families
    for t in complex_:
        if full("grown_base_families"):
            break
        if t["family"] in agree:
            rows = render_family(t, banks, CAP, seen)
            if rows:
                drawn.append((t["family"], rows))
                report["grown_base_families"] += 1
    # 2. FastRule's newer families (not in the committed file), test side excluded
    for t in complex_:
        if full("new_fastrule_families"):
            break
        if (t["family"] not in base_fams and t["action"] not in SEG._EXCLUDE_ACTIONS
                and t.get("force_split") != "test"):
            rows = render_family(t, banks, CAP, seen)
            if rows:
                drawn.append((t["family"], rows))
                report["new_fastrule_families"] += 1
    # 3. our own whole templates, then the composed families
    for t in _load(BANKS / "tier_patterns.json")["patterns"]:
        if full("own_patterns"):
            break
        rows = render_family(t, banks, CAP, seen)
        if rows:
            drawn.append((t["family"], rows))
            report["own_patterns"] += 1
    for t in composed_families():
        if full("composed"):
            break
        rows = render_family(t, banks, CAP, seen)
        if rows:
            drawn.append((t["family"], rows))
            report["composed"] += 1
    return base_lines, drawn, report


def quota(n_base: int, drawn, target: int, cap: int) -> int:
    if target <= n_base:
        return 0
    for q in range(1, cap + 1):
        if n_base + sum(min(q, len(rows)) for _f, rows in drawn) >= target:
            return q
    raise ValueError(f"tier families cannot reach {target} rows (cap {cap})")


_CACHE: dict = {}


def build_generated(tier: str) -> "list[str]":
    """The tier's lines: the committed lines verbatim, then the tier rows."""
    if tier not in TIERS:
        raise SystemExit(f"unknown tier {tier!r}; choose from {list(TIERS)}")
    if "gen" not in _CACHE:
        _CACHE["gen"] = draw_all_generated()
    base_lines, drawn, _report = _CACHE["gen"]
    if tier == "base":
        return list(base_lines)
    q = quota(len(base_lines), drawn, TIERS[tier], CAP)
    return list(base_lines) + [json.dumps(r) + "\n" for _f, rows in drawn for r in rows[:q]]


# ---------------------------------------------------------------------------
# Traps: hand-written trap TEMPLATES with hand-written gold
# ---------------------------------------------------------------------------

def trap_templates(name: str) -> "list[dict]":
    return _load(BANKS / "trap_templates.json")[name]


def trap_banks() -> dict:
    return _load(BANKS / "trap_templates.json")["banks"]


_TRAP_SLOT = re.compile(r"\{([A-Z]+[a-z]*)(\d?)\}")


def _fill_trap(t: dict, banks: dict, rng) -> "tuple[str, list[dict]]":
    """Bind each slot once per row (a numbered slot draws a value distinct from
    its base's), then fill the text and the hand-written gold alike."""
    binding, used = {}, {}
    for base, num in dict.fromkeys(_TRAP_SLOT.findall(t["text"])):
        pool = [v for v in banks[base] if v not in used.setdefault(base, set())]
        value = rng.choice(pool)
        used[base].add(value)
        binding[base + num] = value

    def fill(s: str) -> str:
        return re.sub(r"\s{2,}", " ",
                      _TRAP_SLOT.sub(lambda m: binding[m.group(1) + m.group(2)], s)).strip()
    gold = [{"action": fill(a), "time": fill(tm), "tag": tag} for a, tm, tag in t["gold"]]
    return fill(t["text"]), gold


def check_trap_gold(text: str, gold: "list[dict]") -> "list[str]":
    """A template author's slip is caught here rather than shipped: the
    invariant holds, and every tag already follows Q26/Q61 and the relabel."""
    bad = list(SEG.invariant.violations(text, gold))
    for g in gold:
        want = SEG.q61_tag(SEG.q26_tag(g["tag"], g["time"]), g["time"])
        if want != g["tag"]:
            bad.append(f"tag {g['tag']} but Q26/Q61 say {want}: {g}")
    if relabel(gold) != gold:
        bad.append(f"tag disagrees with Q47/Q50: {gold}")
    return bad


def build_traps(name: str, tier: str) -> "list[str]":
    """`name` is split_traps | nosplit_traps; tier base | grown (10k and 40k
    read `grown`: the honest ceiling, see the module docstring)."""
    base_lines = BASE_FILES[name].read_text().splitlines(keepends=True)
    if tier == "base":
        return list(base_lines)
    banks = trap_banks()
    seen = {json.loads(line)["text"].lower() for line in base_lines}
    out = list(base_lines)
    for t in trap_templates(name):
        rng = random.Random(f"{TIER_SEED}:trap:{t['family']}")
        made = 0
        for n in range(TRAP_CAP * 8):
            if made >= TRAP_CAP:
                break
            text, gold = _fill_trap(t, banks, rng)
            if text.lower() in seen:
                continue
            bad = check_trap_gold(text, gold)
            # the enumeration header ("two tasks due …") is dropped by the trap
            # file's own convention; a template names the words it may lose
            allow = set(t.get("allow_loss", []))
            bad = [b for b in bad if not (b.startswith("lost ") and allow and
                                          set(re.findall(r"'([^']+)'", b)) <= allow)]
            if bad:
                raise ValueError(f"trap template {t['family']} renders bad gold: {bad[0]}")
            seen.add(text.lower())
            row = {"id": f"tt-{t['family']}-{n}", "text": text, "gold": gold,
                   "family": t["family"], "traps": t["traps"], "source": "trap_template",
                   "split": trap_split(t["family"]), "disputed": False,
                   "atomic": len(gold) == 1}
            out.append(json.dumps(row) + "\n")
            made += 1
    return out


def trap_split(family: str) -> str:
    """The generated corpus's rule (`run_board.assign_splits`): 40% of families
    to test by a SHA-1 of the family name. Stamped, because the trap files
    carry their split on every row."""
    from assistant.engine.segmentation.experiments.run_board import assign_splits
    return assign_splits([{"family": family}])[0]["split"]


# ---------------------------------------------------------------------------
# Writing and loading
# ---------------------------------------------------------------------------

def write_tier(name: str, tier: str) -> Path:
    lines = build_generated(tier) if name == "generated" else build_traps(name, tier)
    p = tier_path(name, tier)
    if tier == "base":
        raise SystemExit("the base tier is the committed file; it is never rewritten here")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(lines))
    return p


def ensure(name: str, tier: str) -> Path:
    p = tier_path(name, tier)
    if not p.exists():
        print(f"[tier {tier}] {p.name} missing — building it (deterministic)…", flush=True)
        write_tier(name, "grown" if name != "generated" else tier)
    return p


def board_files(tier: str) -> "list[Path]":
    """The three files segmentation's board reads at a tier."""
    if tier == "base":
        return [BASE_FILES[k] for k in ("generated", "nosplit_traps", "split_traps")]
    return [ensure("generated", tier), ensure("nosplit_traps", "grown"),
            ensure("split_traps", "grown")]


def stats(lines: "list[str]") -> dict:
    from assistant.engine.segmentation.experiments.run_board import assign_splits
    rows = assign_splits([json.loads(line) for line in lines])
    fam_side = {r["family"]: r["split"] for r in rows}
    return {"rows": len(rows), "texts": len({r["text"].lower() for r in rows}),
            "families": len(fam_side),
            "train_rows": sum(r["split"] == "train" for r in rows),
            "test_rows": sum(r["split"] == "test" for r in rows),
            "train_families": sum(s == "train" for s in fam_side.values()),
            "test_families": sum(s == "test" for s in fam_side.values()),
            "atomic_rows": sum(bool(r.get("atomic")) for r in rows),
            "asks": dict(sorted(collections.Counter(len(r["gold"]) for r in rows).items()))}
