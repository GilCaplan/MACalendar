"""THE EVENT FALLBACK BAR — where should the n-gram model stop guessing?

    python -m assistant.engine.label.experiments.event_fallback_bar

**Stage: label · `model.predict`, the n-gram fallback for EVENTS.** The n-gram
pipeline answers an event's category only when the embedding vector cannot be
had — ollama down on the Mac, and ALWAYS on the phone (`LabelModel.swift` has no
vector). Its bar was `MIN_CONFIDENCE["event"] = 0.35`, never measured as a
fallback; the to-do one was (2026-09-24, 0.40 -> 0.90). A 2026-09-30 probe on 8
real titles it filled found 5 wrong, 4 of them at 0.35-0.39 (TASKS 42).

**What it reads.** Only the titles the keyword rules leave on the catch-all
(`Personal` — "no opinion"), because those are the only ones the model ever
answers (`model.category_for`). For each bar: RIGHT (the model's label is the
gold, or it abstains on a gold `Personal`), WRONG (it labelled, and not the
gold — a wrong colour on the calendar), and ABSTAINED on a real category (the
rules' `Personal` stands: a miss, but a quiet one).

**Data.** The model is fitted on the generated TRAIN split alone, exactly as
`train._fit_event` builds the shipped base. Scored on:

- generated TEST (`event_categories.jsonl` split=test, vocabulary the fit never
  saw), rule-blank rows;
- `real_event_gold.jsonl` — real titles, hand-labelled, rule-blank rows.

The category rules are the committed DEFAULTS (the user's own edits are not
read), so the run is identical on every machine and touches no store.
"""
from __future__ import annotations

import collections
import json
import pathlib

BARS = (0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90)
DATA = pathlib.Path(__file__).resolve().parents[1] / "datasets"


def _rows(name):
    return [json.loads(l) for l in (DATA / name).open() if l.strip()]


def main() -> int:
    from assistant.actions.calendar import categories as _cat
    from assistant.engine.label import train as _train

    # defaults only — never the user's category file
    _cat._categories_path = lambda: str(DATA / "__no_user_categories__.json")
    _cat._cache = None

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-tier", default="base", choices=("base", "20k", "40k"),
                    help="size of the generated event set (default base)")
    a = ap.parse_args()
    from assistant.engine.label.datasets.generate import load_rows
    gen = load_rows("event", a.data_tier)
    tr = [(r["text"], r["label"]) for r in gen if r["split"] == "train"]
    pipe, _classes = _train._fit_event(tr, [1.0] * len(tr))

    sets = {
        "generated TEST": [(r["text"], r["label"]) for r in gen if r["split"] == "test"],
        "real gold": [(r["text"], r["label"]) for r in _rows("real_event_gold.jsonl")],
    }
    print("\nEVENT FALLBACK BAR — label stage, n-gram fallback (TRAIN-fitted)\n")
    out = {}
    for name, rows in sets.items():
        blank = [(t, g) for t, g in rows if _cat.classify(t) == "Personal"]
        P = pipe.predict_proba([t for t, _ in blank])
        cls = list(pipe.classes_)
        distinct = len({t for t, _ in blank})
        gold_personal = sum(1 for _, g in blank if g == "Personal")
        print(f"{name}: {len(blank)} rule-blank of {len(rows)} rows "
              f"({distinct} distinct titles; gold Personal on {gold_personal})")
        print(f"  {'bar':>5}  {'labelled':>8}  {'right':>6}  {'WRONG':>6}  "
              f"{'quiet miss':>10}  {'precision':>9}  {'net vs no-fallback':>18}")
        base_right = gold_personal          # no fallback: every row stays Personal
        res = {}
        for bar in BARS:
            right = wrong = miss = labelled = 0
            for (t, g), p in zip(blank, P):
                i = int(p.argmax())
                if p[i] >= bar and cls[i] != "Personal":
                    labelled += 1
                    if cls[i] == g:
                        right += 1
                    else:
                        wrong += 1
                else:
                    if g == "Personal":
                        right += 1
                    else:
                        miss += 1
            hit = sum(1 for (t, g), p in zip(blank, P)
                      if p.max() >= bar and cls[int(p.argmax())] != "Personal"
                      and cls[int(p.argmax())] == g)
            precision = hit / labelled if labelled else float("nan")
            res[bar] = {"labelled": labelled, "right": right, "wrong": wrong,
                        "quiet_miss": miss, "precision": precision}
            print(f"  {bar:>5.2f}  {labelled:>8}  {right:>6}  {wrong:>6}  {miss:>10}  "
                  f"{precision*100:>8.1f}%  {right - base_right:>+18}")
        print(f"  no fallback: right {base_right}, WRONG 0, quiet miss {len(blank) - base_right}\n")
        out[name] = {"n_blank": len(blank), "n_rows": len(rows), "distinct": distinct,
                     "bars": res}
    path = pathlib.Path(__file__).resolve().parent / "runs"
    path.mkdir(exist_ok=True)
    import time
    stamp = time.strftime("%Y%m%dT%H%M")
    (path / f"event_fallback_bar_{stamp}.json").write_text(json.dumps(out, indent=1))
    print(f"record: runs/event_fallback_bar_{stamp}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
