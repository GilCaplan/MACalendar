"""The judge on the v2 set — the pair, per plant, per voice, per damage, and the blind plants apart.

    python -m assistant.engine.llmjudge.experiments.judge_board_v2                # train, every case
    python -m assistant.engine.llmjudge.experiments.judge_board_v2 --split test   # aggregates only

`datasets/v2/judge_cases_v2.jsonl` (README there): a gold object per ask
built by the real converter, one defect planted per case, plus clean cases.
Three things this board does that `judge_board.py` (v1) does not, each because
the set can carry it:

- **A wrong finding TYPE is a miss.** The agent's probe found the judge
  answering `not_an_ask` where `ungrounded_subject` was due — that routes to
  the panel instead of the rewrite, so it is not a catch. The wrong types are
  counted and printed.
- **The BLIND plants are reported apart** (`defect` true, `expect` null:
  dropped ask, wrong kind, wrong operation, a clock residue in a title).
  Today's taxonomy has no finding for them, so no rule can fire; the number
  printed is "flagged at all", and it is never pooled with the clean
  false-flag pool or with the typed catch rate.
- **Per voice and per damage operation**, because the whole point of the set
  is that the template corpus had neither.

No model call. The clock is the DATASET's (`generate_v2.CLOCK`), never this
run's. The test half prints aggregates and no row, as every sealed half here.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import sys
import tempfile
import time

_T = tempfile.mkdtemp(prefix="judge_v2_")
for _v in ("DB", "MEMORY_DB", "VOCAB", "CATEGORIES", "TRACE_BUS", "MODELS",
           "LABEL_FEEDBACK", "DEVICE_SECRET", "DEVICES",
           "CHECKPOINTS", "LEXICON", "UI_STATE", "LOCATION"):
    os.environ.setdefault(f"MACALENDAR_{_v}", os.path.join(_T, _v.lower()))
os.environ["MACALENDAR_NO_WARMUP"] = "1"
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
os.environ.setdefault("MACALENDAR_LLM_DISABLED", "1")

STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE / "datasets" / "v2" / "judge_cases_v2.jsonl"


def _pct(k: int, n: int) -> str:
    return f"{100.0 * k / n:.1f}%" if n else "—"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("train", "test"), default="train")
    ap.add_argument("-n", type=int, default=0, help="0 = every case in the split")
    ap.add_argument("--show", type=int, default=8, help="misses to print (train only)")
    a = ap.parse_args()
    if a.split == "test":
        a.show = 0

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.fastrule.build import Built, build_all
    from assistant.engine.llmjudge import render, verdict
    from assistant.engine.llmjudge.datasets.v2 import mutations as _mut
    from assistant.engine.llmjudge.datasets.v2.generate_v2 import CLOCK
    from assistant.engine.state import EngineState, Item

    engine.load_config()
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    cases = [json.loads(l) for l in DATA.open() if l.strip()]
    cases = [c for c in cases if c["split"] == a.split]
    if a.n:
        cases = cases[:a.n]

    typed_planted = collections.Counter()
    typed_caught = collections.Counter()
    wrong_type = collections.defaultdict(collections.Counter)
    blind_planted = collections.Counter()
    blind_flagged = collections.Counter()
    clean_n = clean_flagged = 0
    unbuildable = 0
    by_voice = collections.defaultdict(lambda: [0, 0])       # typed plants: planted, caught
    by_damage = collections.defaultdict(lambda: [0, 0])
    misses: list = []
    t0 = time.time()

    with freeze_time(CLOCK):
        for c in cases:
            items = [Item(id=g["id"], kind=g.get("kind") or "event",
                          text=g.get("text") or c["text"], time=g.get("time"))
                     for g in c["items"]]
            st = EngineState(raw_text=c["text"], text=c["text"], source="test")
            st.items = items
            try:
                _dv.resolve_values(st, CLOCK.date())
            except Exception:
                pass
            results = build_all(items)
            if not any(isinstance(r, Built) for r in results):
                unbuildable += 1
                continue
            baseline = set()
            for it, r in zip(items, results):
                if isinstance(r, Built):
                    baseline |= {f"{cl.label} = {cl.rendered} — nothing in the words said it"
                                 for cl in render.unsupported_by_slots(r.action, r.intent, it.slots)}
            st.items = _mut.apply(c, items, results)
            produced = verdict.collect(st)
            found = [f for f in verdict.judge(st, produced) if f.detail not in baseline]
            want, target = c.get("expect"), c.get("expect_item")
            on_target = [f for f in found if not target or f.item_id == target]

            if not c.get("defect"):
                clean_n += 1
                if found:
                    clean_flagged += 1
                    if len(misses) < 60:
                        misses.append(("FALSE FLAG", c, [f.type for f in found], found[0].detail))
                continue
            if want is None:
                blind_planted[c["mutation"]] += 1
                if on_target:
                    blind_flagged[c["mutation"]] += 1
                continue
            typed_planted[c["mutation"]] += 1
            keys = [("voice", c.get("voice") or "plain")] + \
                   [("damage", d) for d in (c.get("damage") or ["clean speech"])]
            hit = [f for f in on_target if f.type == want]
            for kind, k in keys:
                (by_voice if kind == "voice" else by_damage)[k][0] += 1
            if hit:
                typed_caught[c["mutation"]] += 1
                for kind, k in keys:
                    (by_voice if kind == "voice" else by_damage)[k][1] += 1
            else:
                for f in on_target:
                    wrong_type[c["mutation"]][f.type] += 1
                if len(misses) < 60:
                    misses.append(("MISS", c, [f.type for f in on_target],
                                   on_target[0].detail if on_target else "no finding"))

    elapsed = time.time() - t0
    n_scored = sum(typed_planted.values()) + sum(blind_planted.values()) + clean_n
    print(f"\nLLMJUDGE BOARD v2 — {a.split.upper()} half, {n_scored} cases scored "
          f"({unbuildable} skipped: nothing built) · {elapsed:.0f}s\n")
    print(f"  TYPED PLANTS — caught means the EXPECTED finding on the expected item")
    print(f"  {'mutation':<26}{'planted':>8}{'caught':>8}{'catch rate':>12}   wrong type instead")
    for m in sorted(typed_planted):
        wt = ", ".join(f"{t}×{k}" for t, k in wrong_type[m].most_common(3)) or "—"
        print(f"  {m:<26}{typed_planted[m]:>8}{typed_caught[m]:>8}"
              f"{_pct(typed_caught[m], typed_planted[m]):>12}   {wt}")
    tp, tc = sum(typed_planted.values()), sum(typed_caught.values())
    print(f"  {'ALL TYPED':<26}{tp:>8}{tc:>8}{_pct(tc, tp):>12}")
    print(f"\n  false-flag rate   {clean_flagged}/{clean_n} = {_pct(clean_flagged, clean_n)}  "
          f"(clean objects the judge complained about)\n")
    print("  BLIND PLANTS — no finding type exists for these; 'flagged' is any finding on the item, reported apart")
    for m in sorted(blind_planted):
        print(f"  {m:<26}{blind_planted[m]:>8}{blind_flagged[m]:>8}{_pct(blind_flagged[m], blind_planted[m]):>12}")
    print("\n  TYPED catch rate by VOICE")
    for v, (p, k) in sorted(by_voice.items(), key=lambda kv: -kv[1][0]):
        print(f"     {v:<24} n={p:5d}  {_pct(k, p):>7}")
    print("  TYPED catch rate by DAMAGE operation")
    for d, (p, k) in sorted(by_damage.items(), key=lambda kv: -kv[1][0]):
        print(f"     {d:<24} n={p:5d}  {_pct(k, p):>7}")
    record = {
        "split": a.split, "cases": n_scored, "unbuildable": unbuildable,
        "typed": {m: {"planted": typed_planted[m], "caught": typed_caught[m],
                      "wrong_type": dict(wrong_type[m])} for m in typed_planted},
        "typed_total": {"planted": tp, "caught": tc},
        "false_flag": {"flagged": clean_flagged, "clean": clean_n},
        "blind": {m: {"planted": blind_planted[m], "flagged": blind_flagged[m]} for m in blind_planted},
        "by_voice": {v: {"planted": p, "caught": k} for v, (p, k) in by_voice.items()},
        "by_damage": {d: {"planted": p, "caught": k} for d, (p, k) in by_damage.items()},
        "elapsed_s": round(elapsed, 1),
    }
    out_dir = pathlib.Path(__file__).resolve().parent / "runs"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"judge_v2_{a.split}_{n_scored}_{time.strftime('%Y%m%dT%H%M')}.json"
    out.write_text(json.dumps(record, indent=1))
    print(f"\n  record: {out}")
    if a.show and misses:
        print("\n  Misses and false flags (train only):")
        for label, c, types, detail in misses[:a.show]:
            print(f"    [{label}] {c['mutation']:<24} “{c['text'][:64]}”")
            print(f"        wanted {c.get('expect')} on {c.get('expect_item')} · got {types} · {detail[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
