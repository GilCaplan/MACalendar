"""BOARD D — connected. Does the judge's correction pay for itself?

    python -m assistant.engine.llmjudge.experiments.board_d -n 120

`PLAN.md` §5 has said since 2026-09-09 that **this board has never run**. Every
number this stage has is ISOLATED — gold items, converted by the real converter,
mutated in known ways — and an isolated board cannot tell you whether the stage
helps the system it sits in. A stage with a good isolated board and a negative
net here is a liability.

## The question, and why it is narrower than it sounds

The judge does not decide what commits. It writes findings; the orchestrator
routes them. So there is exactly ONE way it changes an outcome:

    ungrounded_subject -> rewrite the failed ask into X1' -> re-enter at segment

`unsupported_field` commits with a notice and `not_an_ask` flags to the panel;
neither changes a row. And job 0 — answering FastRule's DEFERs — runs in both
arms because it is not judging, it is the model doing the parse FastRule
declined.

**So Board D is an A/B on the LOOP**, and the metric is the project's own:
rows FIXED minus rows BROKEN.

## Both arms run the real chain on real gold

Rows come from the FastRule 7,200, which carries the expected action and title,
so a row is scored against ground truth rather than against agreement with an
older system. The chain is segment → decompose_validate → fastrule → llmjudge,
exactly as the orchestrator wires it; only `rewrite_for_retry` is stubbed out in
the OFF arm.

Train half only. The test half stays sealed.
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

from assistant.checkpoint import Checkpoint

_S = pathlib.Path(os.environ.get("BOARD_D_SCRATCH",
                                 tempfile.mkdtemp(prefix="board_d_")))
_S.mkdir(parents=True, exist_ok=True)
for _v, _n in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
               ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
               ("TRACE_BUS", "trace_bus.jsonl"), ("MODELS", "models"),
               ("LABEL_FEEDBACK", "fb.jsonl")):
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

STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE.parent / "fastrule" / "datasets" / "fastrule_7200.jsonl"

_STOP = {"the", "a", "an", "my", "to", "for", "of", "on", "at", "in", "and"}


def _content(s) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", str(s or "").lower())
            if w not in _STOP}


def _as_json(outcome):
    """An outcome is a tuple of tuples; JSON has only lists. Round-tripping it
    explicitly keeps a resumed row byte-identical to a fresh one, rather than
    comparing a tuple against a list and silently scoring every resumed row as
    "changed"."""
    return None if outcome is None else [list(x) for x in outcome]


def _as_outcome(blob):
    return None if blob is None else tuple(tuple(x) for x in blob)


def _outcome(state) -> tuple:
    """What the chain produced, as a comparable shape: the actions it would
    commit and the titles they carry."""
    out = []
    for it in state.items:
        if it.intent is None or not it.action or it.blocked:
            continue
        title = (getattr(it.intent, "title", None)
                 or (getattr(it.intent, "titles", None) or [""])[0]
                 or getattr(it.intent, "match_title", "") or "")
        out.append((it.action, " ".join(str(title).lower().split())))
    return tuple(sorted(out))


def _correct(outcome, row) -> bool:
    """Does the outcome match the row's gold action AND name the gold title?

    Deliberately strict on BOTH: a right action with a wrong title is the defect
    this stage exists to catch, so scoring the action alone would make the judge
    look irrelevant by construction.
    """
    want_action = row["expect"].get("action", "")
    want_title = _content((row["expect"].get("slots") or {}).get("title"))
    if not outcome:
        return False
    actions = {a for a, _ in outcome}
    if want_action not in actions:
        return False
    if not want_title:
        return True
    return any(want_title & _content(t) for _a, t in outcome)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=int(os.environ.get("N", "120")))
    ap.add_argument("--show", type=int, default=8)
    ap.add_argument("--checkpoint", default="board_d",
                    help="checkpoint name; a second CONFIGURATION needs a "
                         "second name, or its rows merge into this board")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore any existing checkpoint and start over")
    a = ap.parse_args()

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine.llmjudge import rewrite as _rw
    from assistant.engine.state import EngineState
    from assistant.engine.llmjudge.datasets.generate import CLOCK

    cfg = engine.load_config()
    try:
        _llm.call_json(cfg, "Reply with JSON.", "ping",
                       {"type": "object", "properties": {"ok": {"type": "string"}},
                        "required": ["ok"]})
    except Exception as e:
        print(f"\nABORT — the model is not reachable: {type(e).__name__}: {e}")
        return 2
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if r["split"] == "train"
            and r["expect"].get("action", "").startswith(("create", "update",
                                                          "delete", "complete"))]
    random.Random(31).shuffle(rows)
    rows = rows[:a.n]

    eng = engine.Engine()
    real_rewrite = _rw.rewrite_for_retry
    import assistant.engine.llmjudge.llmjudge as _lj

    def _set_arm(on: bool) -> None:
        fn = real_rewrite if on else (lambda state, cfg: None)
        _rw.rewrite_for_retry = fn
        _lj.rewrite_for_retry = fn
        engine._crosscheck.rewrite_for_retry = fn

    def _run_one(row) -> "tuple | None":
        st = EngineState(raw_text=row["text"], text=row["text"], source="test")
        try:
            eng.parse(st, cfg)
            eng.judge(st, cfg)
        except Exception:
            return None
        return _outcome(st)

    # INTERLEAVED, one row at a time through BOTH arms (2026-09-10).
    #
    # This used to run arm "off" over every row and only then start arm "on",
    # which meant a run killed at 90% yielded NOTHING comparable — and the first
    # attempt at this board was killed at 3h32m with exactly that result.
    # Per-row pairing means an interrupted run is a complete board over fewer
    # rows, which is a usable measurement rather than a wasted afternoon.
    #
    # It also removes a confound the split version carried: the two arms ran
    # hours apart, so any drift in the model server sat between them.
    ck = Checkpoint(a.checkpoint, total=len(rows), every=25,
                    resume=not a.fresh)
    results = {"off": {}, "on": {}}
    with freeze_time(CLOCK):
        for r in rows:
            rid = str(r["id"])
            cached = ck.get(rid) if ck.has(rid) else None
            if cached is not None:
                results["off"][rid] = _as_outcome(cached.get("off"))
                results["on"][rid] = _as_outcome(cached.get("on"))
                continue
            _set_arm(False)
            off = _run_one(r)
            _set_arm(True)
            on = _run_one(r)
            results["off"][rid] = off
            results["on"][rid] = on
            # On disk BEFORE the next row starts: a kill costs this row only.
            ck.record(rid, {"off": _as_json(off), "on": _as_json(on),
                            "text": r["text"][:120]})
    ck.finish()

    _rw.rewrite_for_retry = real_rewrite

    fixed, broken, changed_same = [], [], 0
    n_off = n_on = 0
    for r in rows:
        # `str(r["id"])`: checkpoint keys are JSON object keys, which are
        # strings. Looking up the raw id would miss every row and score the
        # whole board as "the loop changed nothing" — a silent zero.
        rid = str(r["id"])
        off, on = results["off"].get(rid), results["on"].get(rid)
        ok_off, ok_on = _correct(off, r), _correct(on, r)
        n_off += ok_off
        n_on += ok_on
        if off == on:
            continue
        if ok_on and not ok_off:
            fixed.append((r, off, on))
        elif ok_off and not ok_on:
            broken.append((r, off, on))
        else:
            changed_same += 1

    n = len(rows)
    print(f"\nBOARD D — the judge's loop, connected. {n} rows, train half.\n")
    print(f"  correct with the loop OFF   {n_off}/{n} = {100.0*n_off/n:.1f}%")
    print(f"  correct with the loop ON    {n_on}/{n} = {100.0*n_on/n:.1f}%")
    print()
    print(f"  rows the loop FIXED         {len(fixed)}")
    print(f"  rows the loop BROKE         {len(broken)}")
    print(f"  changed, no better or worse {changed_same}")
    print(f"  NET                         {len(fixed) - len(broken):+d} rows")
    print()
    print("  Net is the number that decides. A stage with a good isolated board")
    print("  and a negative net here is a liability, however well it scores alone.\n")

    for label, rowset in (("FIXED", fixed), ("BROKE", broken)):
        for r, off, on in rowset[:a.show]:
            print(f"    [{label}] “{r['text'][:56]}”")
            print(f"        off: {off}")
            print(f"        on : {on}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
