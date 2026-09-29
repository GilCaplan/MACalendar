"""The offline guard alone — no model, seconds, the WHOLE split (DEVQA Q68).

The guard (`OfflineGuard.swift`, rules from `spec.guard()`) decides what the
phone leaves for the Mac before any model call. Being code, it can be scored
on every row of a split instead of the model board's 1,200:

    python -m assistant.offline.experiments.guard_board              # TRAIN
    python -m assistant.offline.experiments.guard_board --split test # aggregates only

Two lines, on the FastRule set's gold actions:
  caught      — rows that change, delete, complete or ask, left for the Mac
                (higher is safer)
  false guard — rows that only CREATE, left for the Mac anyway (lower keeps
                the offline reader useful); mixed rows (a create plus an edit
                or a question) are counted apart — leaving those is by design.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATASET = ROOT / "assistant/engine/fastrule/datasets/fastrule_7200.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train", choices=("train", "test"))
    ap.add_argument("--show", type=int, default=0, help="print N misses of each kind (TRAIN only)")
    a = ap.parse_args()
    from assistant.offline import spec
    tmp = Path(tempfile.mkdtemp(prefix="guard-board-"))
    exe = tmp / "guard_check"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(HERE / "guard_check.swift"),
                    str(ROOT / "MACalendar-iOS/MACalendar-iOS/Voice/OfflineGuard.swift"),
                    "-o", str(exe)], check=True)
    (tmp / "guard.json").write_text(json.dumps(spec.guard()))
    rows = [json.loads(l) for l in DATASET.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("split") == a.split]
    feed = "".join(json.dumps({"id": r["id"], "text": r["text"]}) + "\n" for r in rows)
    out = subprocess.run([str(exe), str(tmp / "guard.json")], input=feed, capture_output=True,
                         text=True, check=True).stdout.splitlines()
    leaves = {o["id"]: o["leaves"] for o in map(json.loads, out)}
    c = Counter()
    miss, false = [], []
    for r in rows:
        e = r["expect"]
        act = e.get("action", "")
        creates = act in ("create_event", "create_todo", "mixed") and (
            e.get("events", 0) + e.get("tasks", 0)) > 0
        mixed = creates and (act == "mixed" or not e.get("atomic", True))
        lv = leaves[r["id"]]
        if not creates:
            c["edit_n"] += 1
            c["caught"] += lv
            if not lv:
                miss.append(r)
        elif mixed:
            c["mixed_n"] += 1
            c["mixed_left"] += lv
        else:
            c["create_n"] += 1
            c["false"] += lv
            if lv:
                false.append(r)
    pct = lambda x, n: f"{100 * x / n:5.1f}% ({x}/{n})" if n else "—"  # noqa: E731
    print(f"GUARD — FastRule set, {a.split.upper()}, n={len(rows)} (all rows of the split)")
    print(f"   caught (edit/delete/complete/question left for the Mac)  {pct(c['caught'], c['edit_n'])}")
    print(f"   false guard (a plain create left for the Mac)            {pct(c['false'], c['create_n'])}")
    print(f"   mixed create+edit/question left for the Mac (by design)   {pct(c['mixed_left'], c['mixed_n'])}")
    if a.show and a.split == "train":
        print("\nMISSED (TRAIN):")
        for r in miss[:a.show]:
            print(f"   {r['expect'].get('action')} | {r['text'][:90]}")
        print("\nFALSE GUARDS (TRAIN):")
        for r in false[:a.show]:
            print(f"   {r['text'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
