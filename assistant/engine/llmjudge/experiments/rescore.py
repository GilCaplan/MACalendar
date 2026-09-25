"""Score a Board D run that ALREADY HAPPENED — no model, no chain, seconds.

    python -m assistant.engine.llmjudge.experiments.rescore board_d
    python -m assistant.engine.llmjudge.experiments.rescore board_d_c45 board_d_q47b board_d

Gil, 2026-09-25: *"We save checkpoints so why compute from 0, can just
calculate metric scores on existing results."* A Board D run is an hour of
model calls; a new METRIC is arithmetic over what those calls produced, and
every row is already on disk in the run's checkpoint. So a metric is added by
rescoring, and the board is re-RUN only when the CODE changed — which is the
other half of the rule: a rescore measures the commit the checkpoint recorded
(printed first), never the tree you have now.

What a checkpoint can answer depends on when it was written:

  * since 2026-09-25 each row keeps the ON arm's objects WITH their fields
    (`objs_on`) and its model milliseconds — every line of `board_metrics`;
  * before that, only (action, title) per arm plus latency — the headline,
    loop net, structure, title exactness, harm, restraint and confusion. The
    field and model-call lines print "not recorded" rather than a zero that
    would read as a measurement.

A row whose text no longer matches the dataset (the corpus was regenerated
since) is SKIPPED and counted, never scored against gold it was not run on.
"""
from __future__ import annotations

import argparse
import json
import pathlib

from assistant.checkpoint import CHECKPOINT_DIR
from assistant.engine.llmjudge.experiments import board_d as D
from assistant.engine.llmjudge.experiments import board_metrics as BM

#: the counters a legacy checkpoint cannot fill — zeroed so they print "—".
#: The title lines stay: the (action, title) pairs are exactly what they need.
_FIELDS = ("date_n", "date_ok", "time_n", "time_ok", "rec_n", "rec_ok", "lead_n", "lead_ok",
           "invent_n", "invent", "model_rows")


def _load(name: str) -> "tuple[dict, dict]":
    path = pathlib.Path(name)
    if not path.suffix:
        path = CHECKPOINT_DIR / f"{name}.jsonl"
    meta, rows = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        blob = json.loads(line)
        if "k" in blob:
            rows[str(blob["k"])] = blob["v"]
        elif not meta:
            meta = blob
    return meta, rows


def rescore(name: str, only: "set | None" = None) -> dict:
    meta, ck = _load(name)
    if only is not None:
        ck = {k: v for k, v in ck.items() if k in only}
    data = {str(r["id"]): r for r in map(json.loads, D.DATA.open(encoding="utf-8"))}
    rows, stale = [], 0
    for rid, v in ck.items():
        r = data.get(rid)
        if r is None or (v.get("text") and not r["text"].startswith(v["text"][:120])):
            stale += 1
            continue
        rows.append(r)
    on = {str(r["id"]): D._as_outcome(ck[str(r["id"])].get("on")) for r in rows}
    off = {str(r["id"]): D._as_outcome(ck[str(r["id"])].get("off")) for r in rows}
    full = all(ck[str(r["id"])].get("objs_on") is not None for r in rows)
    built = {}
    for r in rows:
        v = ck[str(r["id"])]
        objs = v.get("objs_on")
        if objs is None:                        # legacy: rebuild what the pairs hold
            objs = [{"action": a, "title": t} for a, t in (on[str(r["id"])] or ())]
        built[str(r["id"])] = {"objs": objs, "ms": v.get("ms_on", 0),
                               "llm_ms": v.get("llm_ms_on", 0)}
    correct = {rid: D._correct(on[rid], data[rid]) for rid in on}
    n_off = sum(D._correct(off[rid], data[rid]) for rid in off)
    fixed = sum(1 for rid in on if correct[rid] and not D._correct(off[rid], data[rid]))
    broke = sum(1 for rid in on if not correct[rid] and D._correct(off[rid], data[rid]))
    m = BM.score(rows, built, correct)
    if not full:
        for f in _FIELDS:
            m["c"][f] = 0
        m["c"]["rows"] = 0                      # the model-call line's denominator
        m["lat"] = {"model": [], "none": [b["ms"] for b in built.values()]}

    n = len(rows)
    print(f"\n=== {name}  ·  commit {str(meta.get('git_head'))[:8]}"
          f"{' (dirty)' if meta.get('git_dirty') else ''}  ·  started {meta.get('started', '?')}")
    print(f"  rows scored {n} of {len(ck)} recorded · {stale} skipped (text no longer in the dataset)"
          f" · {'full objects' if full else 'LEGACY: action+title only — fields and model split not recorded'}")
    if n:
        print(f"  headline correct  loop ON {100.0 * sum(correct.values()) / n:.1f}% "
              f"({sum(correct.values())}/{n}) · OFF {100.0 * n_off / n:.1f}% · "
              f"net {fixed - broke:+d} (fixed {fixed}, broke {broke})")
    BM.report(m)
    return {"name": name, "meta": meta, "n": n, "stale": stale, "full": full,
            "metrics": BM.as_record(m)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("checkpoints", nargs="+", help="checkpoint names or .jsonl paths")
    ap.add_argument("--common", action="store_true",
                    help="score only the rows EVERY named checkpoint recorded — two runs "
                         "drawn on different samples are otherwise not comparable")
    a = ap.parse_args()
    only = None
    if a.common:
        only = set.intersection(*(set(_load(n)[1]) for n in a.checkpoints))
        print(f"  --common: {len(only)} rows recorded by all {len(a.checkpoints)} runs")
    for name in a.checkpoints:
        rescore(name, only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
