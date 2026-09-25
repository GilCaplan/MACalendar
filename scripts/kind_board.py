"""The KIND decision, measured as its own component.

Segment assigns every item a kind — event / task / review — and
`decompose.run()` then branches ENTIRELY on it: an event gets time-splitting
and lead-time stripping, a task gets list-splitting and quantity extraction.
So one wrong kind costs TWO errors, the label and the decomposition.

It had no board. The atomizer board reports "mis-typed" as one number with no
direction, which cannot tell "tasks read as events" (the suspected failure,
where a reminder with a daypart is promoted to the calendar) from the
opposite. This reports the confusion matrix and slices it by the two
mechanisms under suspicion:

  * NON-CREATE to-do operations — `_TASK_RE` matches only create-shaped
    phrasing, so "cross off buy milk" has nothing to match on.
  * DAYPART-ONLY rows — `_CLOCKISH_RE` counts "tonight"/"this morning" as a
    clock time, which promotes a reminder to an event against the project's
    own Q15 ruling.

    python -m scripts.kind_board                 # train split (mine freely)
    python -m scripts.kind_board --split test    # aggregates only

Train is the default on purpose: direction comes from the training pool, and
the test half reports aggregates without row detail (the leakage rule).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import sys

from assistant.common.scratch_env import scratch_env

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The stores are read at import time, so redirect BEFORE importing assistant.
# NOTE: this reuses a directory INSIDE the checkout across runs (unlike every
# other board's fresh tempdir) — kept as-is rather than changed silently; see
# the migration report.
_SCRATCH = scratch_env("kind_board_", dir=str(ROOT / ".scratch_kind_board"),
                       keep=("LOCATION", "MODELS", "LABEL_FEEDBACK",
                            "HEARTBEATS", "HUD_STATE", "DEVICE_SECRET",
                            "DEVICES"))

sys.path.insert(0, str(ROOT))

#: action -> the kind the item should carry out of segment.
_KIND_OF_ACTION = {
    "create_event": "event", "update_event": "event", "delete_event": "event",
    "create_todo": "task", "update_todo": "task",
    "complete_todo": "task", "delete_todo": "task",
    "query": "review",
}

#: the operations `_TASK_RE` was never written to see
_NON_CREATE_TODO = {"update_todo", "complete_todo", "delete_todo"}

_DAYPART_RE = re.compile(
    r"\b(?:tonight|this morning|this afternoon|this evening|morning|"
    r"afternoon|evening|night)\b", re.I)
#: a REAL clock time — digits, not a part of the day
_REAL_CLOCK_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)\b|\b\d{1,2}:\d{2}\b"
    r"|\bat\s+\d{1,2}\b|\b(?:noon|midday|midnight)\b", re.I)

DATASETS = {
    "fastrule": ROOT / "assistant" / "engine" / "fastrule" / "datasets" / "fastrule_7200.jsonl",
    "personas": ROOT / "dataset" / "personas" / "personas.jsonl",
    "realspeech": ROOT / "dataset" / "realspeech" / "realspeech_1200.jsonl",
}


def _predict(text: str) -> str:
    """Kind, as segment would decide it IN THE PIPELINE.

    **This is a REIMPLEMENTATION of segment's kind path, and it has already
    been ahead of the real one.** When this board was written, `segment.run()`
    called `_kind_of` alone — `_enforce_pinned_kinds` was reachable only from
    `_llm_segments` — while this function called both. So every number it
    reported was the accuracy the deterministic path WOULD have had if it
    applied the pinned conventions, not the accuracy it had. Nothing was
    reporting the real one, and a cycle was predicted against a movement that
    was arithmetically impossible (part 4b).

    They agree as of 59a524e. If `run()`'s kind assignment changes again, this
    must change with it — or better, both should come to call one named reader
    in segment.py, which is the fix this comment is standing in for.


    The cleanup matters and is easy to leave out: transcript (step 1) strips
    spoken noise before segment ever sees the words, and several of the kind
    regexes are `^`-anchored. Feeding raw dataset text here makes "um i need
    to do the laundry" look like a miss that the real pipeline never has, and
    would send this cycle chasing a fault in the wrong stage.

    **IT DRIFTED AGAIN, and this is the fix the comment above was standing in
    for** (2026-09-18). `run()`'s kind assignment DID change: FastSeg became
    the default segmenter and `fastseg.tag()` applies a lexicon correction on
    top of `_kind_of` — deliberately asymmetric, consulted only to talk the
    reader OUT of `event`. This function kept calling `_kind_of` alone, so it
    was scoring a component that has not decided a kind in the live pipeline
    for some time. Measured on the same 2,991 single-item atomic train rows:

        LIVE   fastseg.tag        94.9%   task->event  59 · event->task  91
        THIS   old_seg._kind_of   88.6%   task->event 323 · event->task  15

    Not just 6.3 points pessimistic — it INVERTED the dominant error class.
    Anyone reading this board to pick the next cycle would have gone after
    tasks being promoted to the calendar, which is the smaller half live.

    So it no longer reimplements anything: it asks the live segmenter, which
    cannot drift from itself.
    """
    from assistant.engine.segmentation.llmseg.llmseg import segment
    from assistant.intent.cleanup import strip_spoken_noise

    clean = strip_spoken_noise(text)
    items = segment(clean)["items"]
    # This board scores rows with a SINGLE gold kind; a cut into several pieces
    # is a segmentation disagreement, not a kind one, and the first piece is
    # what the kind path would have been asked about.
    return items[0]["tag"] if items else "event"


def _prf(matrix, cls) -> "tuple[float, float, float, int]":
    tp = matrix[(cls, cls)]
    fp = sum(n for (g, p), n in matrix.items() if p == cls and g != cls)
    fn = sum(n for (g, p), n in matrix.items() if g == cls and p != cls)
    support = tp + fn
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / support if support else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1, support


def run_one(name: str, path: pathlib.Path, split: str, show_rows: bool) -> None:
    if not path.exists():
        print(f"\n{name}: not found at {path}")
        return
    rows = [json.loads(line) for line in path.open() if line.strip()]
    rows = [r for r in rows if r.get("split") == split]

    matrix: collections.Counter = collections.Counter()
    slices: dict = {
        "non-create todo": [0, 0],
        "daypart, no clock time": [0, 0],
        "create todo": [0, 0],
        "create event": [0, 0],
    }
    misses: dict = collections.defaultdict(list)
    n = 0
    for r in rows:
        exp = r.get("expect") or {}
        if not exp.get("atomic"):
            continue                     # kind of a compound is not one label
        action = exp.get("action")
        gold = _KIND_OF_ACTION.get(action)
        if gold is None:
            continue                     # "mixed"/"propose" have no single kind
        text = r["text"]
        pred = _predict(text)
        matrix[(gold, pred)] += 1
        n += 1

        buckets = []
        if action in _NON_CREATE_TODO:
            buckets.append("non-create todo")
        if action == "create_todo":
            buckets.append("create todo")
        if action == "create_event":
            buckets.append("create event")
        if _DAYPART_RE.search(text) and not _REAL_CLOCK_RE.search(text):
            buckets.append("daypart, no clock time")
        for b in buckets:
            slices[b][1] += 1
            if pred == gold:
                slices[b][0] += 1
        if pred != gold:
            misses[(gold, pred)].append(text)

    if not n:
        print(f"\n{name} [{split}]: no scorable rows")
        return

    correct = sum(v for (g, p), v in matrix.items() if g == p)
    print(f"\n=== {name} · {split} · {n} atomic rows with a single gold kind ===")
    print(f"  kind accuracy          {correct}/{n} ({100 * correct / n:.1f}%)")

    print("  per class:")
    for cls in ("event", "task", "review"):
        p_, r_, f_, sup = _prf(matrix, cls)
        print(f"    {cls:8s} P {p_:.3f}  R {r_:.3f}  F1 {f_:.3f}   support {sup}")

    print("  confusion (gold -> predicted), errors only:")
    for (g, p), c in sorted(matrix.items(), key=lambda kv: -kv[1]):
        if g != p:
            print(f"    {g:7s} -> {p:7s}  {c}")

    print("  by slice (the two mechanisms under suspicion):")
    for label, (ok, tot) in slices.items():
        if tot:
            print(f"    {label:24s} {ok}/{tot} ({100 * ok / tot:.1f}%)")

    if show_rows:
        for (g, p), examples in sorted(misses.items(), key=lambda kv: -len(kv[1])):
            print(f"\n  --- gold {g} read as {p} ({len(examples)}) ---")
            for t in examples[:6]:
                print(f"      {t}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train", choices=["train", "test"])
    ap.add_argument("--dataset", default="all", choices=["all", *DATASETS])
    args = ap.parse_args()

    # The leakage rule: the held-back half reports aggregates, never rows.
    show_rows = args.split == "train"
    names = list(DATASETS) if args.dataset == "all" else [args.dataset]
    for name in names:
        run_one(name, DATASETS[name], args.split, show_rows)
    if not show_rows:
        print("\n(test half: aggregates only — no row detail, no mining)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
