"""What does a STRICTER subject test cost on titles the real chain produced?

    python -m assistant.engine.llmjudge.experiments.title_falseflag           # 3000
    python -m assistant.engine.llmjudge.experiments.title_falseflag -n 0      # all 8,749

The one number the isolation board cannot give. Its clean cases carry GOLD
titles converted straight from the gold item, so of course every word of them is
in the transcript — the false-flag column there is measuring the generator, not
the judge. A false-flag rate is only honest against titles the SYSTEM built,
with all of segmentation's and FastRule's own liberties in them.

So this runs the real chain — segmentation -> decompose_validate -> FastRule —
over thousands of utterances from three corpora, throws the labels away, and
asks one question of every title that comes out:

    how often would this subject test complain about what the system
    actually builds?

No ground truth is needed and none is used: a flag on a chain-produced title is
counted as a COST whether or not the title was any good. That is deliberately
pessimistic, and pessimistic is the right direction for a number whose job is to
veto a change.

## The three tests, and why the third exists

    ZERO-OVERLAP   `names_nothing_spoken` — the shipped test. Flags a title
                   with NO word in the transcript.
    EVERY-WORD     `_grounded_title` semantics. Flags a title with ANY word
                   the transcript never said. Cycle 2 rejected this on one
                   anecdote ("gym session" from "gym saturday"); this is the
                   measurement that anecdote never had.
    HEAD-WORD      every word EXCEPT the last must be spoken — the near miss
                   this project actually generates is "shared head + invented
                   tail", so this is EVERY-WORD with the tail forgiven, and
                   it is here to show whether the strictness is doing real
                   work or just catching the generator.

Personas are deliberately EXCLUDED. `dataset/personas/PERSONAS.md`: no persona
row may direct a change, and this number's whole purpose is to direct one.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import random
import re
import tempfile
import time

_S = pathlib.Path(os.environ.get("JUDGE_BOARD_SCRATCH",
                                 tempfile.mkdtemp(prefix="title_ff_")))
_S.mkdir(parents=True, exist_ok=True)
for _v, _n in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
               ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
               ("TRACE_BUS", "trace_bus.jsonl")):
    os.environ[f"MACALENDAR_{_v}"] = str(_S / _n)
os.environ["MACALENDAR_NO_WARMUP"] = "1"
# BACKGROUND traffic: this yields the model to the live assistant between
# every call (assistant/model_protocol.py). Without it a board and a voice
# command are indistinguishable to ollama, and a trivial live call measured
# 2.0s -> 42.5s -> 43.9s behind a running board (2026-09-10).
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
os.environ["MACALENDAR_OBSERVANCE"] = "0"
for _t in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_t, "1")

ROOT = pathlib.Path(__file__).resolve().parents[4]
CORPORA = (
    ("realspeech", ROOT / "dataset/realspeech/realspeech_1200.jsonl"),
    ("fastrule", ROOT / "assistant/engine/fastrule/datasets/fastrule_7200.jsonl"),
    ("segmentation", ROOT / "assistant/engine/segmentation/datasets/generated.jsonl"),
)


def _load(n: int, seed: int) -> list:
    rows = []
    for name, path in CORPORA:
        if not path.exists():
            print(f"  (missing: {path})")
            continue
        for line in path.open():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("split") == "test":
                continue              # the sealed halves stay sealed
            rows.append((name, d.get("text") or ""))
    rows = [r for r in rows if r[1].strip()]
    random.Random(seed).shuffle(rows)
    return rows[:n] if n else rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3000, help="0 = every row")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args()

    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine import segmentation as _seg
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.fastrule.build import Built, build_all
    from assistant.engine.llmjudge import render, verdict
    from assistant.engine.llmjudge.gatekeeper import _GENERIC_TARGET_RE
    from assistant.engine.state import EngineState

    stop = verdict._TITLE_STOP
    cfg = engine.load_config()
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    def words(t):
        # `verdict.tokens`, so this board reads a string the same way the judge
        # does — including the quote-mark strip. A board with its own tokeniser
        # measures its own tokeniser.
        return [w for w in verdict.tokens(t) if len(w) > 2 and w not in stop]

    def spoken(w, raw):
        stem = w[:4]
        return any(tk.startswith(stem) or w.startswith(tk[:4])
                   for tk in verdict.tokens(raw) if len(tk) > 2)

    def zero_overlap(title, raw):
        return verdict.names_nothing_spoken(title, raw)

    def every_word(title, raw):
        ws = words(title)
        return bool(ws) and any(not spoken(w, raw) for w in ws)

    def head_word(title, raw):
        ws = words(title)
        return len(ws) > 1 and any(not spoken(w, raw) for w in ws[:-1])

    TESTS = (("ZERO-OVERLAP", zero_overlap), ("EVERY-WORD", every_word),
             ("HEAD-WORD", head_word))

    rows = _load(a.n, a.seed)
    print(f"\n  {len(rows)} utterances · running the real chain "
          f"(segmentation → decompose_validate → FastRule)…")

    fired = {name: 0 for name, _ in TESTS}
    examples = {name: [] for name, _ in TESTS}
    per_corpus = collections.defaultdict(lambda: collections.Counter())
    titles_n = 0
    generic_n = 0
    t0 = time.time()

    for corpus, text in rows:
        st = EngineState(raw_text=text, text=text, source="test")
        try:
            _seg.run(st, cfg)
            _dv.run(st, cfg)
        except Exception:
            continue
        items = list(st.items or [])
        if not items:
            continue
        try:
            built = build_all(items)
        except Exception:
            continue
        for item, res in zip(items, built):
            if not isinstance(res, Built):
                continue
            for cl in render.claims(res.action, res.intent, item.slots):
                if not (cl.needs_model and verdict._IDENTITY.match(cl.label)):
                    continue
                title = (cl.raw or "").strip()
                if not title:
                    continue
                # A generic title is already flagged by a test nobody is
                # proposing to change, so counting it here would credit every
                # variant with a catch it does not make.
                if _GENERIC_TARGET_RE.match(title):
                    generic_n += 1
                    continue
                titles_n += 1
                for name, fn in TESTS:
                    if fn(title, text):
                        fired[name] += 1
                        per_corpus[corpus][name] += 1
                        if len(examples[name]) < 60:
                            examples[name].append((corpus, text, title))
                per_corpus[corpus]["_titles"] += 1

    elapsed = time.time() - t0
    print(f"\nTITLE FALSE-FLAG BOARD — {len(rows)} utterances → {titles_n} "
          f"chain-produced titles · {elapsed:.0f}s")
    print(f"  ({generic_n} generic titles excluded — already caught by a test "
          f"nothing here changes)\n")
    print(f"  {'test':<16}{'fired':>8}{'rate':>10}   what it flags")
    blurb = {"ZERO-OVERLAP": "no word of the title was said (SHIPPED)",
             "EVERY-WORD": "any word of the title was not said",
             "HEAD-WORD": "any word but the last was not said"}
    for name, _ in TESTS:
        rate = 100.0 * fired[name] / titles_n if titles_n else 0.0
        print(f"  {name:<16}{fired[name]:>8}{rate:>9.1f}%   {blurb[name]}")

    print(f"\n  {'corpus':<16}{'titles':>8}" +
          "".join(f"{n.split('-')[0]:>14}" for n, _ in TESTS))
    for corpus in sorted(per_corpus):
        c = per_corpus[corpus]
        t = c["_titles"] or 1
        print(f"  {corpus:<16}{c['_titles']:>8}" +
              "".join(f"{100.0 * c[n] / t:>13.1f}%" for n, _ in TESTS))

    if a.show:
        print("\n  What EVERY-WORD complains about (the cost, in the system's "
              "own words):")
        seen = set()
        for corpus, text, title in examples["EVERY-WORD"]:
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            print(f"    “{text[:60]}”\n        title {title!r}")
            if len(seen) >= a.show:
                break
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
