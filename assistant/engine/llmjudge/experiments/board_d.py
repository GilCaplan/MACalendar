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

from assistant.checkpoint import Checkpoint
from assistant.common.scratch_env import scratch_env

# SEEDED: a measurement is reproducible or it is not a measurement. Two runs
# of this board at one commit differed on 22 of 1,200 rows before this line
# (2026-09-22), all of them the rescue's unseeded parse — more rows than the
# two arms disagree on. `model_protocol.seed_options()`; live traffic unset.
_S = pathlib.Path(scratch_env(
    "board_d_", seed=17, observance=False,
    dir=os.environ.get("BOARD_D_SCRATCH"),
    keep=("LOCATION", "HEARTBEATS", "HUD_STATE", "DEVICE_SECRET", "DEVICES")))
# the LLM console's call log — 2,400 board calls a run were landing in the
# live console's stream (2026-09-22)
os.environ["MACALENDAR_LLM_BUS"] = str(_S / "llm_calls.jsonl")

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
    slots = row["expect"].get("slots") or {}
    want_title = _content(slots.get("title"))
    if slots.get("generic_target"):
        # A GENERIC TARGET IS RIGHT WHEN REFUSED (DEVQA Q38, 2026-09-21: "a
        # title that names nothing is refused, everywhere"; and CLAUDE.md:
        # deleting is destructive — when the engine cannot identify what to
        # delete, empty slots are the right answer). The corpus records the
        # literal phrase as the title ("that appointment") because that is
        # what was SAID, and until 2026-09-22 this scorer demanded an object
        # carrying it — 23 of the seeded baseline's 127 wrong rows were the
        # engine doing what Gil ruled, and the loop's one "fixed" row was the
        # model round handing back `delete_event "that one"`, the very thing
        # the front door had vetoed. So: nothing built is right; an object
        # with the right action whose title is NOT the generic phrase is right
        # too (the LLM may RESOLVE an anaphor — FastRule's contract); an
        # object carrying the phrase is wrong, and a wrong action is wrong.
        if not outcome:
            return True
        return any(a == want_action and not (want_title & _content(t))
                   for a, t in outcome)
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
    # FRESH BY DEFAULT (2026-09-22): the real-usage board served a four-day-old
    # cache through `Checkpoint`'s resume-by-default and nobody noticed. Resume
    # is for a crash mid-run at the SAME commit, opted into by flag.
    ap.add_argument("--resume", action="store_true",
                    help="resume the checkpoint of a run that died mid-way at this commit")
    ap.add_argument("--fresh", action="store_true", help="(the default now; kept for old notes)")
    ap.add_argument("--split", choices=("train", "test"), default="train",
                    help="test prints AGGREGATES ONLY and never a row (the sealed rule)")
    a = ap.parse_args()
    if a.split == "test":
        a.show = 0
        if a.checkpoint == "board_d":
            a.checkpoint = "board_d_test"

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
    rows = [r for r in rows if r["split"] == a.split
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

    import time as _time

    def _run_one(row) -> "tuple":
        """(outcome, re-entries, milliseconds) — the extra two are what v2
        breaks the net down by: how often the loop RAN, and what it cost."""
        st = EngineState(raw_text=row["text"], text=row["text"], source="test")
        t0 = _time.time()
        try:
            eng.parse(st, cfg)
            eng.judge(st, cfg)
        except Exception:
            return None, 0, int((_time.time() - t0) * 1000)
        reentries = sum((getattr(st, "retries", None) or {}).values())
        # H6 (PLAN §7.5): did the MODEL round of the rewrite fire on this row?
        # The attempt ledger lives in the state's fixes, rule `rewrite_model`.
        model_round = any(getattr(f, "rule", "") == "rewrite_model"
                          for f in (getattr(st, "fixes", None) or []))
        return _outcome(st), reentries + (1000 if model_round else 0), int((_time.time() - t0) * 1000)

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
                    resume=a.resume)
    print(f"  replay: {'resuming the checkpoint' if a.resume else 'fresh — every row through the current code'}",
          flush=True)
    results = {"off": {}, "on": {}}
    extra = {}                                   # rid -> (reentries_on, ms_off, ms_on)
    # `tick=True` (2026-09-22): a frozen clock froze `time.time()` too, and v2's
    # per-arm latency read 0.0 s on every row. The real-usage board makes the
    # same call for the same reason; the dates the rows resolve against still
    # sit on CLOCK's day.
    with freeze_time(CLOCK, tick=True):
        for r in rows:
            rid = str(r["id"])
            cached = ck.get(rid) if ck.has(rid) else None
            if cached is not None:
                results["off"][rid] = _as_outcome(cached.get("off"))
                results["on"][rid] = _as_outcome(cached.get("on"))
                extra[rid] = (cached.get("reentries", 0), cached.get("ms_off", 0),
                              cached.get("ms_on", 0), bool(cached.get("model_round")))
                continue
            _set_arm(False)
            off, _, ms_off = _run_one(r)
            _set_arm(True)
            on, packed, ms_on = _run_one(r)
            reentries, model_round = packed % 1000, packed >= 1000
            results["off"][rid] = off
            results["on"][rid] = on
            extra[rid] = (reentries, ms_off, ms_on, model_round)
            # On disk BEFORE the next row starts: a kill costs this row only.
            ck.record(rid, {"off": _as_json(off), "on": _as_json(on),
                            "reentries": reentries, "model_round": model_round,
                            "ms_off": ms_off, "ms_on": ms_on, "text": r["text"][:120]})
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
    # v2 (2026-09-22): the net, BROKEN DOWN — by family, by atomic vs compound,
    # by how many re-entries the loop spent, and by whether the two arms
    # DISAGREED at all — plus what each arm cost. A net of 0 over everything
    # can hide +5 on compounds and −5 on atomic rows.
    def _pct(k, m):
        return f"{100.0 * k / m:.1f}%" if m else "—"
    by = {"family": collections.defaultdict(lambda: [0, 0, 0, 0]),
          "shape": collections.defaultdict(lambda: [0, 0, 0, 0]),
          "reentries": collections.defaultdict(lambda: [0, 0, 0, 0]),
          "model_round": collections.defaultdict(lambda: [0, 0, 0, 0])}
    disagreed = 0
    lat = {"off": [], "on": []}
    for r in rows:
        rid = str(r["id"])
        off, on = results["off"].get(rid), results["on"].get(rid)
        ok_off, ok_on = _correct(off, r), _correct(on, r)
        re_n, ms_off, ms_on, model_round = extra.get(rid, (0, 0, 0, False))
        lat["off"].append(ms_off); lat["on"].append(ms_on)
        if off != on:
            disagreed += 1
        keys = {"family": r.get("family", "?"),
                "shape": "atomic" if (r["expect"].get("atomic") is True) else "compound",
                "reentries": str(min(re_n, 3)),
                "model_round": "model round fired" if model_round else "no model round"}
        for k, v in keys.items():
            c = by[k][v]
            c[0] += 1; c[1] += ok_off; c[2] += ok_on
            c[3] += (1 if (ok_on and not ok_off) else -1 if (ok_off and not ok_on) else 0)
    def _p(xs, q):
        xs = sorted(xs)
        return (xs[min(len(xs) - 1, int(len(xs) * q))] / 1000.0) if xs else 0.0
    print(f"\nBOARD D v2 — the judge's loop, connected. {n} rows, {a.split.upper()} half.\n")
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
    print(f"  arms DISAGREED on           {disagreed} rows ({_pct(disagreed, n)}) — the only rows the loop can move")
    print(f"  latency p50 / p95  loop OFF {_p(lat['off'], .5):.1f}s / {_p(lat['off'], .95):.1f}s"
          f"   loop ON {_p(lat['on'], .5):.1f}s / {_p(lat['on'], .95):.1f}s\n")
    for k, label in (("shape", "by shape"), ("reentries", "by re-entries the loop spent (ON arm)"),
                     ("model_round", "by whether the rewrite's MODEL round fired (H6)"),
                     ("family", "by family (top 12 by n)")):
        print(f"  {label}:")
        items = sorted(by[k].items(), key=lambda kv: -kv[1][0])
        if k == "family":
            items = items[:12]
        for v, (m, ok_off, ok_on, net) in items:
            print(f"     {v:28s} n={m:5d}  off {_pct(ok_off, m):>6}  on {_pct(ok_on, m):>6}  net {net:+d}")
        print()
    record = {
        "split": a.split, "n": n, "off_pct": round(100.0 * n_off / n, 1) if n else None,
        "on_pct": round(100.0 * n_on / n, 1) if n else None,
        "fixed": len(fixed), "broke": len(broken), "changed_same": changed_same,
        "disagreed": disagreed, "net": len(fixed) - len(broken),
        "latency_s": {"off_p50": _p(lat["off"], .5), "off_p95": _p(lat["off"], .95),
                      "on_p50": _p(lat["on"], .5), "on_p95": _p(lat["on"], .95)},
        "by": {k: {v: {"n": c[0], "off": c[1], "on": c[2], "net": c[3]} for v, c in d.items()}
               for k, d in by.items()},
    }
    out_dir = pathlib.Path(__file__).resolve().parent / "runs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"board_d_{a.split}_{n}_{_time.strftime('%Y%m%dT%H%M')}.json"
    out_path.write_text(json.dumps(record, indent=1))
    print(f"  record: {out_path}\n")

    for label, rowset in (("FIXED", fixed), ("BROKE", broken)):
        for r, off, on in rowset[:a.show]:
            print(f"    [{label}] “{r['text'][:56]}”")
            print(f"        off: {off}")
            print(f"        on : {on}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
