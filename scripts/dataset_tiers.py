"""Size TIERS for the judge, persona and real-speech sets — one place that says
where a tier lives, whether it is current, and how to build it.

Gil, 2026-10-01: *"a lot of the datasets seem really small, they should be at
least 40k with enough variation in the data"* and *"you can have different
level of the same dataset as well, sometimes can let user choose."*

    base   the committed file, byte-identical to what every recorded number
           was measured on. THE DEFAULT EVERYWHERE.
    10k    base + new material, at least 10,000 rows (v2: 10,000 COMMANDS)
    40k    base + more new material, at least 40,000 rows (v2: 40,000 COMMANDS)

A larger tier is a SUPERSET of a smaller one: the committed base file's bytes
come first, unchanged, then the grown rows, and every 10k row is in the 40k
file. So no row changes its split, its id or its gold between tiers, and a
number read on base is a number about the first rows of every tier.

Grown tiers go to a gitignored `tiers/` folder next to the base file — they are
multi-MB and deterministic by seed, so the generator is the artefact, not the
files. A loader asks `resolve(name, tier)` for a path: base is always there;
a CHEAP tier (no engine import — commands, personas, real speech) is built on
demand in seconds; a tier whose build runs the converter (the two judge-case
sets) is never built behind a board's back — `resolve` stops and prints the
command, because that build is minutes to an hour.

**Choosing one.** These sets are mostly SCORED WITH THE ENGINE, and the
per-row cost is the board's, not the file's: a deterministic board reads 40k
in minutes, a board that calls the model reads it in many hours (a 40k
model-run board is an overnight job at ~1-3 s a row). So:

    smoke    base   — what every recorded number used; seconds to minutes
    iterate  10k    — a change's own board; ~4-8x base
    confirm  40k    — a deterministic board's confirmation run, or a
                      model board only when the slice is worth a night
"""
from __future__ import annotations

import importlib
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

TIERS = ("base", "10k", "40k")
GROWN = ("10k", "40k")
#: The floor each grown tier is built to. For the v2 pair the count is of
#: COMMANDS and the case file is whatever those commands plant (~2.1x).
TARGET = {"10k": 10_000, "40k": 40_000}

#: name -> (base file, generator command, builder "module:function" or None).
#: A builder is listed only where building is cheap enough to do on demand.
SETS = {
    "judge_v1": (
        "assistant/engine/llmjudge/datasets/judge_cases.jsonl",
        "python -m assistant.engine.llmjudge.datasets.generate --tier {tier}",
        None),
    "commands_v2": (
        "assistant/engine/llmjudge/datasets/v2/commands_v2.jsonl",
        "python -m assistant.engine.llmjudge.datasets.v2.generate_v2 "
        "--tier {tier} --commands-only",
        "assistant.engine.llmjudge.datasets.v2.generate_v2:write_command_tier"),
    "judge_v2": (
        "assistant/engine/llmjudge/datasets/v2/judge_cases_v2.jsonl",
        "python -m assistant.engine.llmjudge.datasets.v2.generate_v2 --tier {tier}",
        None),
    "personas": (
        "dataset/personas/personas.jsonl",
        "python -m scripts.gen_personas --tier {tier}",
        "scripts.gen_personas:write_tier"),
    "personas_ablation": (
        "dataset/personas/personas_ablation.jsonl",
        "python -m scripts.gen_personas --ablation --tier {tier}",
        "scripts.gen_personas:write_ablation_tier"),
    "realspeech": (
        "dataset/realspeech/realspeech_1200.jsonl",
        "python -m scripts.gen_realspeech --tier {tier}",
        "scripts.gen_realspeech:write_tier"),
}


def check_tier(tier: str) -> str:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r} — one of {', '.join(TIERS)}")
    return tier


def tier_path(base: "pathlib.Path | str", tier: str) -> pathlib.Path:
    """`x/name.jsonl` -> `x/tiers/name.<tier>.jsonl`; base -> itself."""
    base = pathlib.Path(base)
    if check_tier(tier) == "base":
        return base
    return base.parent / "tiers" / f"{base.stem}.{tier}{base.suffix}"


def is_fresh(base: "pathlib.Path | str", tier: str) -> bool:
    """A grown tier is current only if it still STARTS with the base file's
    bytes. A base regeneration therefore makes every tier stale by itself,
    with no stamp to forget to update."""
    path = tier_path(base, tier)
    if tier == "base":
        return path.exists()
    if not path.exists():
        return False
    want = pathlib.Path(base).read_bytes()
    with path.open("rb") as fh:
        return fh.read(len(want)) == want


def write_tier(base: "pathlib.Path | str", tier: str, grown: list,
               dumps=None) -> pathlib.Path:
    """Write `tier` as the base file's bytes VERBATIM, then one line per grown
    row. Written to a temporary name and renamed, so a killed build never
    leaves a half file that `is_fresh` would accept."""
    base = pathlib.Path(base)
    out = tier_path(base, tier)
    out.parent.mkdir(parents=True, exist_ok=True)
    dumps = dumps or (lambda r: json.dumps(r, sort_keys=True))
    tmp = out.with_suffix(out.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(base.read_bytes())
        for r in grown:
            fh.write((dumps(r) + "\n").encode("utf-8"))
    os.replace(tmp, out)
    return out


def command(name: str, tier: str) -> str:
    return SETS[name][1].format(tier=tier)


def resolve(name: str, tier: str = "base", build: bool = True) -> pathlib.Path:
    """The path a loader should read for set `name` at `tier`.

    Base is returned as-is. A grown tier that is missing or stale is built
    here when its builder is cheap; otherwise this stops with the command that
    builds it — a judge-case tier runs the converter over every new command,
    and that is not something to start silently from inside a board.
    """
    rel, cmd, builder = SETS[name]
    base = ROOT / rel
    if check_tier(tier) == "base" or is_fresh(base, tier):
        return tier_path(base, tier)
    if build and builder:
        mod, fn = builder.split(":")
        print(f"· {name} tier {tier} is missing or stale — building it "
              f"({command(name, tier)})", flush=True)
        getattr(importlib.import_module(mod), fn)(tier)
        if is_fresh(base, tier):
            return tier_path(base, tier)
    raise SystemExit(
        f"{name}: the {tier} tier is not built (or is stale against base).\n"
        f"  build it with:  {command(name, tier)}")


def load(name: str, tier: str = "base") -> list:
    path = resolve(name, tier)
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def add_argument(ap, flag: str = "--data-tier") -> None:
    """The one flag every loader takes. `--data-tier`, not `--tier`, because
    several of these rows already carry a `tier` FIELD (FastRule's
    simple/complex) and a board filtering on it must not read as this."""
    ap.add_argument(flag, choices=TIERS, default="base",
                    help="dataset size tier: base (committed; the default and "
                         "what every recorded number used), 10k, or 40k "
                         "(gitignored, built on demand where cheap). See "
                         "scripts/dataset_tiers.py for which fits smoke / "
                         "iterate / confirm.")
