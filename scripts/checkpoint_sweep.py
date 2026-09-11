"""Run the SAME dataset through several tagged checkpoints, scored by TODAY's scorer.

    python -m scripts.checkpoint_sweep --smoke              # 1 row each, ~seconds
    python -m scripts.checkpoint_sweep --test               # the sealed 300
    python -m scripts.checkpoint_sweep --rows 25            # a quick slice

WHY THIS EXISTS. `loop_log.csv` is 21 readings taken under three different
harnesses, with two declared comparability boundaries, so the trajectory cannot
be read end to end — see DATASET.md's `era` section. This sweep answers the
question the log cannot: take five system states, measure them all TODAY, with
one dataset, one scorer and one machine. There are no eras to reconcile because
every point is taken with the same instrument.

## How a checkpoint is run

Each checkpoint is a git worktree at its tag (`scripts/checkpoint_sweep.py
--setup` makes them, under ../MACalendar-checkpoints/). It runs in **its own
subprocess**, over **HTTP via the Flask test client**, and is scored from the
**calendar DB it writes**.

Those three choices are the whole design, and each one removes a class of
breakage found by inspecting the tags:

- **A subprocess per checkpoint.** Old and new `assistant` packages cannot
  share an interpreter; a single process would resolve `assistant.engine` once
  and reuse it for every later checkpoint.
- **The test client, not an import.** `pre-engine-v2` has NO `run_transcript`
  and no `assistant/engine/` at all — parse and execute are interleaved inside
  `server.py`. There is no common function to call. But every checkpoint has
  `create_app()` and `POST /voice/text`, so HTTP is the one contract all five
  share. It also absorbs signature drift for free: `fast-lane-pre-integration`
  predates `supports_confirm`, and an unknown JSON key is ignored where an
  unexpected kwarg would be a TypeError.
- **Scored from the DB.** `score_dataset_run.score_db` opens the run DB
  read-only and scores the OUTPUT, so it has no dependency on engine
  internals. That is what lets today's scorer grade three-week-old code.

## The safety rule

**Nothing here ever touches port 8080 or the real stores.** The test client is
in-process, so there is no socket and no way to reach a running `assistant.api`
— which holds the REAL calendar, and which env overrides do NOT redirect
(CLAUDE.md: a HUD test's Revert put 45 rows in the real Today list exactly this
way). Every store is pointed at a scratch directory, set BEFORE `assistant` is
imported because the paths are read at import time, and `source` is "test".

## Reading the output

Latency is reported as p50 and p95 PER COMPLEXITY TIER, never as a mean: the
engine's own p50/p95 are 12.0 s and 70.4 s, so an average is a number about the
tail. Tiers hold ~100 of the sealed 300, which supports a median comfortably and
a p95 loosely; anything sliced finer than a tier prints n so a reader can
discount it.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKTREES = ROOT.parent / "MACalendar-checkpoints"
OUT = ROOT / "DOCUMENTATION" / "experiments" / "checkpoints"

#: The system states being compared, oldest first. `main` is the live tree.
CHECKPOINTS = [
    ("pre-engine-v2", "the old brain, before the engine rewrite"),
    ("fast-lane-pre-integration", "FastRule sandbox, pre-integration"),
    ("fastrule-v1", "before the FastRule v2 restructure"),
    ("decompose-validate-v1", "resolver wired into the live path"),
    ("main", "today"),
]

# The child runs inside the checkpoint's own tree. It is written out rather
# than passed with -c so a failure has a real traceback with line numbers.
_CHILD = '''\
import json, os, pathlib, sys, time

tree, scratch, rows_path, out_path = sys.argv[1:5]

# BEFORE importing assistant: every store is read at import time, so a fixture
# (or an assignment after the import) is too late. This is tests/conftest.py's
# rule, and the reason it is a rule.
s = pathlib.Path(scratch)
s.mkdir(parents=True, exist_ok=True)
for var, name in (("MACALENDAR_DB", "calendar.db"),
                  ("MACALENDAR_MEMORY_DB", "nlu_memory.db"),
                  ("MACALENDAR_VOCAB", "vocab.json"),
                  ("MACALENDAR_CATEGORIES", "categories.json"),
                  ("MACALENDAR_LOCATION", "location.json"),
                  ("MACALENDAR_TRACE_BUS", "trace_bus.jsonl")):
    os.environ[var] = str(s / name)
os.environ["MACALENDAR_NO_WARMUP"] = "1"   # no daemon model loads beside the run

sys.path.insert(0, tree)

result = {"tree": tree, "rows": [], "error": None}
try:
    import assistant
    result["assistant_from"] = assistant.__file__
    from assistant.api.server import create_app
    app = create_app()
    # Otherwise Flask converts every failure into an opaque 500 HTML page and
    # the sweep reports "HTTP 500" for a missing model, a missing config and a
    # genuine break in old code alike.
    app.config["PROPAGATE_EXCEPTIONS"] = True
    app.testing = True
    client = app.test_client()

    rows = json.loads(pathlib.Path(rows_path).read_text())
    for row in rows:
        body = {"transcript": row["text"], "source": "test",
                "supports_edit": False, "supports_confirm": False}
        t0 = time.perf_counter()
        try:
            r = client.post("/voice/text", json=body)
            ms = int((time.perf_counter() - t0) * 1000)
            payload = r.get_json(silent=True) or {}
            rec = {
                "id": row.get("id"), "tier": row.get("tier"),
                "status": r.status_code, "ms": ms,
                "parse": payload.get("parse"),
                "actions": payload.get("actions"),
                "message": (payload.get("message") or "")[:200],
            }
            if r.status_code != 200:
                # A bare status code is not a diagnosis. Keep the body so a
                # failing checkpoint says WHY — missing model, missing config,
                # or a genuine break in the old code.
                rec["body"] = r.get_data(as_text=True)[-800:]
            result["rows"].append(rec)
        except Exception as e:
            result["rows"].append({
                "id": row.get("id"), "tier": row.get("tier"),
                "status": None, "ms": int((time.perf_counter() - t0) * 1000),
                "error": f"{type(e).__name__}: {e}",
            })
except Exception as e:
    import traceback
    result["error"] = f"{type(e).__name__}: {e}"
    result["traceback"] = traceback.format_exc()

result["db"] = str(s / "calendar.db")
pathlib.Path(out_path).write_text(json.dumps(result, indent=1))
'''


def setup() -> int:
    """Create one detached worktree per tag. Idempotent."""
    WORKTREES.mkdir(parents=True, exist_ok=True)
    for tag, _why in CHECKPOINTS:
        if tag == "main":
            continue
        dest = WORKTREES / tag
        if dest.exists():
            print(f"  {tag:<28} already present")
            continue
        r = subprocess.run(["git", "worktree", "add", "--detach", str(dest), tag],
                           cwd=ROOT, capture_output=True, text=True)
        print(f"  {tag:<28} {'created' if r.returncode == 0 else r.stderr.strip()[:80]}")
    return 0


def _tree_for(tag: str) -> pathlib.Path:
    return ROOT if tag == "main" else WORKTREES / tag


def _provenance() -> dict:
    """text -> {complexity, scenario, intent, ts} from hwu64_sample.json.

    COMPLEXITY IS NOT IN EITHER INPUT FILE. `test_split.json` rows are
    `[text, {rank, scenario, intent}]` and `history_3000.json` rows are
    `{seq, text, ts}`; the tier lives only in the provenance file, joined by
    text (DATASET.md: "provenance: scenario/intent/complexity/compound-kind per
    prompt"). Latency per tier is the point of this sweep, so the join is not
    optional — a sweep that silently reported every row as tier "?" would look
    like it worked.
    """
    src = ROOT / "dataset" / "inputs" / "hwu64_sample.json"
    out = {}
    for d in json.loads(src.read_text()).get("rows", []):
        text = d.get("text")
        if text:
            out[text] = d
    return out


def _load_rows(args) -> list:
    """The prompts to replay, as [{id, text, tier, ts}]."""
    src = (ROOT / "dataset" / "inputs" /
           ("test_split.json" if args.test else "history_3000.json"))
    data = json.loads(src.read_text()).get("rows", [])
    prov = _provenance()

    rows = []
    for i, d in enumerate(data):
        if isinstance(d, (list, tuple)):          # test_split: [text, meta]
            text, meta = d[0], (d[1] if len(d) > 1 else {})
        elif isinstance(d, dict):                 # history_3000: {seq, text, ts}
            text, meta = d.get("text"), d
        else:
            text, meta = str(d), {}
        if not text:
            continue
        p = prov.get(text, {})
        rows.append({
            "id": meta.get("rank") or meta.get("seq") or p.get("tier_rank") or i,
            "text": text,
            "tier": p.get("complexity"),
            "scenario": p.get("scenario") or meta.get("scenario"),
            "intent": p.get("intent") or meta.get("intent"),
            # The loop's harness replays each row FROZEN AT ITS RECORDED ts
            # (CLAUDE.md, the 2026-09-05 measurement epoch). Carried here so
            # the freeze can be applied; see the note in run_checkpoint.
            "ts": p.get("ts") or meta.get("ts"),
        })
    missing = sum(1 for r in rows if not r["tier"])
    if missing:
        print(f"  WARNING: {missing}/{len(rows)} rows have no complexity tier "
              f"(provenance join missed them) — per-tier latency will be partial")
    if args.smoke:
        return rows[:1]
    if args.rows:
        return rows[:args.rows]
    return rows


def run_checkpoint(tag: str, rows: list, scratch_root: pathlib.Path) -> dict:
    tree = _tree_for(tag)
    if not tree.exists():
        return {"tag": tag, "error": f"no worktree at {tree} — run --setup"}
    scratch = scratch_root / tag
    scratch.mkdir(parents=True, exist_ok=True)
    child = scratch / "_child.py"
    child.write_text(_CHILD)
    rows_path = scratch / "rows.json"
    rows_path.write_text(json.dumps(rows))
    out_path = scratch / "result.json"

    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(child), str(tree), str(scratch),
         str(rows_path), str(out_path)],
        cwd=str(tree),          # never today's root, so `assistant` cannot leak in
        capture_output=True, text=True, timeout=None)
    wall = time.perf_counter() - t0

    if not out_path.exists():
        return {"tag": tag, "error": "child wrote no result",
                "stderr": proc.stderr[-1500:], "stdout": proc.stdout[-500:]}
    out = json.loads(out_path.read_text())
    out.update({"tag": tag, "wall_s": round(wall, 1),
                "stderr_tail": proc.stderr[-1500:] if proc.returncode else ""})
    return out


def _pct(values: list, q: float):
    if not values:
        return None
    v = sorted(values)
    k = max(0, min(len(v) - 1, int(round(q * (len(v) - 1)))))
    return v[k]


def report(results: list) -> None:
    print("\n" + "=" * 78)
    print("CHECKPOINT SWEEP — same rows, same scorer, same machine, today")
    print("=" * 78)
    for r in results:
        tag = r.get("tag")
        if r.get("error"):
            print(f"\n{tag:<28} ✗ {r['error']}")
            for line in (r.get("traceback") or r.get("stderr") or "").strip().splitlines()[-6:]:
                print(f"    {line}")
            continue
        rows = r.get("rows", [])
        ok = [x for x in rows if x.get("status") == 200]
        errs = [x for x in rows if x.get("status") != 200]
        print(f"\n{tag:<28} {len(ok)}/{len(rows)} ok · wall {r.get('wall_s')}s")
        print(f"    assistant from: {r.get('assistant_from')}")
        tiers = {}
        for x in ok:
            tiers.setdefault(x.get("tier") or "?", []).append(x["ms"])
        for tier, ms in sorted(tiers.items(), key=lambda kv: str(kv[0])):
            print(f"    {str(tier):<10} n={len(ms):<4} p50 {_pct(ms,.5)}ms  p95 {_pct(ms,.95)}ms")
        paths = {}
        for x in ok:
            paths[x.get("parse")] = paths.get(x.get("parse"), 0) + 1
        if paths:
            print("    parse paths: " + ", ".join(f"{k}={v}" for k, v in sorted(
                paths.items(), key=lambda kv: str(kv[0]))))
        for x in errs[:3]:
            print(f"    ✗ row {x.get('id')}: {x.get('error') or 'HTTP ' + str(x.get('status'))}")
            body = (x.get("body") or "").strip()
            if body:
                for line in body.splitlines()[-4:]:
                    print(f"        {line[:110]}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--setup", action="store_true", help="create the worktrees and exit")
    ap.add_argument("--smoke", action="store_true", help="one row per checkpoint")
    ap.add_argument("--test", action="store_true", help="the SEALED 300 (milestone only)")
    ap.add_argument("--rows", type=int, help="first N rows")
    ap.add_argument("--checkpoints", help="comma-separated subset of tags")
    ap.add_argument("--keep", action="store_true", help="keep the scratch dirs")
    args = ap.parse_args()

    if args.setup:
        return setup()

    tags = [t for t, _ in CHECKPOINTS]
    if args.checkpoints:
        want = {s.strip() for s in args.checkpoints.split(",")}
        tags = [t for t in tags if t in want]
    rows = _load_rows(args)
    print(f"{len(rows)} row(s) × {len(tags)} checkpoint(s)")

    scratch_root = pathlib.Path(tempfile.mkdtemp(prefix="checkpoint_sweep_"))
    results = []
    try:
        for tag in tags:
            print(f"  running {tag} …", flush=True)
            results.append(run_checkpoint(tag, rows, scratch_root))
        report(results)
        OUT.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M")
        dest = OUT / f"sweep-{stamp}.json"
        dest.write_text(json.dumps(results, indent=1))
        print(f"wrote {dest}")
    finally:
        if args.keep:
            print(f"scratch kept at {scratch_root}")
        else:
            shutil.rmtree(scratch_root, ignore_errors=True)
    return 0 if all(not r.get("error") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
