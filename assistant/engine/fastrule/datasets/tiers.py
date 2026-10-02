"""Which SIZE of the FastRule set a board reads (Gil, 2026-10-01: *"you can
have different level of the same dataset as well, sometimes can let user
choose"*).

    base   8,700 rows   fastrule_7200.jsonl — committed, the board of record
    20k   20,000 rows   base + growth level 1 (new constructions)
    40k   40,000 rows   20k + growth level 2 (more new constructions)
    80k   80,000 rows   40k + growth level 3 (deeper: more rows per growth family)

Every tier is a strict SUPERSET of the one before it: its first lines ARE the
smaller tier, byte for byte. Only base is committed; the others are a pure
function of `generate.py` + `banks/` and are written to `datasets/tiers/`
(gitignored) — `ensure()` builds a missing one on demand.

NOT the row field `tier` (simple / complex), which every size carries too.
A board's flag for this is `--size`, so the two never share a name.

    from assistant.engine.fastrule.datasets import tiers
    tiers.add_argument(ap)                  # --size base|20k|40k|80k, default base
    rows = tiers.load(a.size)               # builds the file first if it is missing
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE / "fastrule_7200.jsonl"
TIER_DIR = HERE / "tiers"

#: size name -> total rows. The order is the superset order.
SIZES_ROWS = {"base": 8_700, "20k": 20_000, "40k": 40_000, "80k": 80_000}
SIZES = tuple(SIZES_ROWS)


def path(size: str = "base") -> pathlib.Path:
    if size not in SIZES_ROWS:
        raise ValueError(f"unknown size {size!r}; one of {SIZES}")
    return BASE if size == "base" else TIER_DIR / f"fastrule_{size}.jsonl"


def build_command(size: str) -> str:
    return f"python -m assistant.engine.fastrule.datasets.generate --size {size}"


def ensure(size: str = "base") -> pathlib.Path:
    """The file for `size`, generating it first when it is missing.

    In a subprocess: the generator points MACALENDAR_CATEGORIES (and the user
    registry) at its own fixture/scratch, and a board must not inherit that."""
    p = path(size)
    if p.exists():
        return p
    print(f"[fastrule tiers] {p.name} is missing — building it: {build_command(size)}",
          file=sys.stderr)
    root = HERE.parents[3]
    subprocess.run([sys.executable, "-m", "assistant.engine.fastrule.datasets.generate",
                    "--size", size], cwd=root, check=True, stdout=subprocess.DEVNULL)
    if not p.exists():
        raise FileNotFoundError(f"{p} was not written; build it with: {build_command(size)}")
    return p


def load(size: str = "base", split: "str | None" = None) -> list[dict]:
    rows = [json.loads(line) for line in ensure(size).open(encoding="utf-8") if line.strip()]
    return [r for r in rows if split is None or r["split"] == split]


def add_argument(ap) -> None:
    ap.add_argument("--size", choices=SIZES, default="base",
                    help="FastRule set size tier: base (8,700, committed — the board of "
                         "record), 20k, 40k or 80k (supersets of base, generated on "
                         "demand into datasets/tiers/). Default base.")
