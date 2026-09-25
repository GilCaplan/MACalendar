"""Sweep the vocabulary corrector's thresholds and print the trade.

    python -m scripts.vocab_threshold_sweep
    python -m scripts.vocab_threshold_sweep --terms 200 --relax 0.25 0.35 0.45

Gil, 2026-09-19: *"can finetune the threshold on what we decide so it fires
more fairly."* This is the instrument that says what "fairly" costs.

TWO NUMBERS, AND THEY PULL APART.

    REPAIRED   of the damaged sentences, how many came back exactly right
    WRONG      of the CLEAN sentences, how many the corrector edited anyway

The second one is the one to watch. A missed repair leaves the speaker's words
alone and they can see the bad title; a wrong rewrite changes what they said
and they never find out. So this prints them side by side and never blends
them into an F-score, which would let a rule buy hits with silent damage.

THE VOCABULARY IS SIZED TO THE REAL ONE. Gil's hand-curated list is ~162 words.
Loading all 1,794 bench terms at once would make the phonetic path's
"bucket of one" guard fail far more often than it does in life, so the sweep
samples `--terms` (default 200) and scores only their cases. Deterministic —
the sample is the first N in corpus order, no RNG (scripts cannot use one).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

_T = tempfile.mkdtemp(prefix="vocab_sweep_")
for _v in ("DB", "MEMORY_DB", "VOCAB", "CATEGORIES", "TRACE_BUS", "MODELS",
           "LABEL_FEEDBACK", "DEVICE_SECRET", "DEVICES",
           "CHECKPOINTS", "LEXICON", "UI_STATE", "LOCATION"):
    os.environ[f"MACALENDAR_{_v}"] = os.path.join(_T, _v.lower())
os.environ["MACALENDAR_NO_WARMUP"] = "1"
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", type=int, default=200,
                    help="vocabulary size, matched to the real one (~162)")
    ap.add_argument("--thresholds", type=float, nargs="*",
                    default=[0.90, 0.86, 0.82, 0.78, 0.74, 0.70])
    ap.add_argument("--relax", type=float, nargs="*", default=[0.25])
    a = ap.parse_args()

    from scripts.vocab_repair_bench import in_sentence, real_pairs
    from assistant.stt import vocab as V

    cases = in_sentence(0)
    terms, chosen = [], set()
    for row in cases:                      # first N distinct terms, in order
        if row["term"] not in chosen:
            chosen.add(row["term"])
            terms.append(row["term"])
        if len(terms) >= a.terms:
            break
    cases = [r for r in cases if r["term"] in chosen]
    real = real_pairs()

    print(f"vocabulary {len(terms)} terms · {len(cases)} damaged sentences "
          f"· {len(cases)} clean sentences · {len(real)} real pairs")
    print()
    print(f"{'thr':>5} {'relax':>6} | {'REPAIRED':>9} {'missed':>7} "
          f"| {'WRONG on clean':>15} | {'real pairs':>11}")
    print("-" * 74)

    base_relax = V.PHONETIC_RELAXATION
    for relax in a.relax:
        for thr in a.thresholds:
            V.PHONETIC_RELAXATION = relax
            store = V.VocabStore()
            for t in terms:
                store.add_word(t)
            store.threshold = thr

            repaired = sum(
                1 for r in cases
                if store.correct(r["damaged"])[0].strip().lower()
                == r["clean"].strip().lower())
            wrong = sum(
                1 for r in cases
                if store.correct(r["clean"])[0].strip().lower()
                != r["clean"].strip().lower())
            # The real pairs, scored as bare phrases — the primary number.
            hit = 0
            for got, want in real:
                s2 = V.VocabStore()
                s2.add_word(want)
                s2.threshold = thr
                if s2.correct(got)[0].strip().lower() == want.strip().lower():
                    hit += 1
            n = len(cases) or 1
            print(f"{thr:5.2f} {relax:6.2f} | {repaired:6} {100*repaired/n:5.1f}%"
                  f" {n-repaired:7} | {wrong:6} {100*wrong/n:7.1f}% "
                  f"| {hit:4}/{len(real)}")
    V.PHONETIC_RELAXATION = base_relax
    print()
    print("REPAIRED high is good. WRONG is the cost, and it is silent — the")
    print("speaker never sees the words they said being changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
