"""THE RELATION BOARD — does segmentation cut a sequence and say WHY it cut?

    ./.venv/bin/python -m assistant.engine.segmentation.experiments.relation_board                 # TRAIN
    ./.venv/bin/python -m assistant.engine.segmentation.experiments.relation_board --show 20       # + failing rows
    ./.venv/bin/python -m assistant.engine.segmentation.experiments.relation_board --split test    # aggregates only

DEVQA Q51 (Gil, 2026-09-25): segmentation splits on sequence words and hands
decompose_validate the RELATIONSHIP between the parts, `Item.relation` —
`{"to": <item id>, "kind": sequence|list|sentence|envelope|same_span|adjacent|
unknown, "words": …}`, None on the first item. This board runs the STAGE
(`assistant.engine.segmentation.run` on an `EngineState`, no model) over
`datasets/sequence/sequence.jsonl` and reads four things, never one number:

    CUT        right item count · exact-set (actions) · exact-row (+ time, tag)
    FIELDS     per matched item: action boundary, time, tag
    RELATION   per matched item after the first: the KIND, overall, per kind,
               per joiner, with n; and whether `to` points at the right item
    DECOYS     sequence-looking words that must NOT split: "no false split"

`ambiguous` rows are never scored. Damaged rows (`damage` set — a misspelt
joiner, a split word, a missing comma, a typo'd title) are a SLICE beside the
clean one; each has a clean twin in the same family, so the pair says what
the damage costs.

The matching and field checks are `experiments/score.py`'s (`match_items`,
`field_hits`, `as_item`), so an item matches here exactly when it matches on
the stage's own board.

TEST prints aggregates only — no row, no family name — and `--show` is
refused on it (engine/TRAIN_TEST_SPLIT_CONVENTION.md).
"""
from __future__ import annotations

import os

from assistant.common.scratch_env import scratch_env

_S = scratch_env("relation_board_",
                 extra={"MACALENDAR_LLM_DISABLED": "1"})  # deterministic: no model door opens
for _v in ("LLM_BUS", "CHECKPOINTS", "LEXICON", "UI_STATE"):
    os.environ[f"MACALENDAR_{_v}"] = os.path.join(_S, _v.lower())

import argparse  # noqa: E402
import collections  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from assistant.engine.segmentation.experiments import score as SC  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "datasets" / "sequence" / "sequence.jsonl"
KINDS = ("sequence", "list", "sentence", "same_span", "envelope", "adjacent", "unknown")


def _pc(a: int, n: int) -> str:
    return f"{100 * a / n:5.1f}% ({a}/{n})" if n else "    —  (0/0)"


def predict(text: str) -> list:
    """The STAGE, not the component: envelope, FastSeg, (LLMSeg off), relate."""
    from assistant.engine import segmentation as SEG
    from assistant.engine.state import EngineState

    st = EngineState(raw_text=text, text=text, source="test")
    SEG.run(st, None)
    out = []
    for it in st.items:
        rel = getattr(it, "relation", None)
        out.append({"id": it.id, "action": it.text or "", "time": it.time or "",
                    "tag": it.kind, "relation": rel if isinstance(rel, dict) else None})
    return out


def score_row(row: dict, pred: list) -> dict:
    gold = [SC.as_item(g) for g in row["gold"]]
    pitems = [SC.as_item(p) for p in pred]
    pairs, miss_g, miss_p = SC.match_items(gold, pitems)
    g2p = {gi: pi for gi, pi, _s in pairs}
    p2g = {pi: gi for gi, pi, _s in pairs}
    pid_index = {p["id"]: i for i, p in enumerate(pred)}
    fields = {}
    for gi, pi in g2p.items():
        fields[gi] = SC.field_hits(gold[gi], pitems[pi])
    count_ok = len(pred) == len(gold)
    set_ok = count_ok and not miss_g and not miss_p and all(f[0] for f in fields.values())
    row_ok = set_ok and all(f[1] and f[2] for f in fields.values())
    rels = []             # (gold kind, pred kind, to_ok, joiner) per matched item after the first
    first_clean = None
    for gi, g in enumerate(row["gold"]):
        grel = g.get("relation")
        if gi not in g2p:
            if grel:
                rels.append((grel["kind"], "(unmatched)", False, grel.get("joiner"), False))
            continue
        prel = pred[g2p[gi]]["relation"]
        if not grel:
            first_clean = prel is None
            continue
        pkind = (prel or {}).get("kind") or "(none)"
        to_ok = False
        if prel and prel.get("to") in pid_index:
            to_ok = p2g.get(pid_index[prel["to"]]) == grel["to_index"]
        rels.append((grel["kind"], pkind, to_ok, grel.get("joiner"), True))
    return {"count_ok": count_ok, "over": len(pred) > len(gold), "under": len(pred) < len(gold),
            "set_ok": set_ok, "row_ok": row_ok, "fields": fields, "n_gold": len(gold),
            "rels": rels, "first_clean": first_clean}


def board(rows: list, show: int, test: bool) -> None:
    scored = [r for r in rows if not r["ambiguous"] and not r["decoy"]]
    decoys = [r for r in rows if r["decoy"] and not r["ambiguous"]]
    n_amb = sum(r["ambiguous"] for r in rows)
    t0 = time.time()
    res = {}
    for i, r in enumerate(scored + decoys):
        res[r["id"]] = (score_row(r, p := predict(r["text"])), p)
        if (i + 1) % 500 == 0:
            el = time.time() - t0
            print(f"  … {i + 1}/{len(scored) + len(decoys)} rows · {el:.0f}s", flush=True)

    def block(title, rs):
        if not rs:
            return
        R = [res[r["id"]][0] for r in rs]
        n = len(R)
        items = sum(x["n_gold"] for x in R)
        matched = sum(len(x["fields"]) for x in R)
        fa = sum(f[0] for x in R for f in x["fields"].values())
        ft = sum(f[1] for x in R for f in x["fields"].values())
        fg = sum(f[2] for x in R for f in x["fields"].values())
        rel_m = [t for x in R for t in x["rels"] if t[4]]
        rel_all = [t for x in R for t in x["rels"]]
        print(f"\n{title}  —  {n} rows, {items} gold items")
        print(f"  CUT     right item count   {_pc(sum(x['count_ok'] for x in R), n)}"
              f"   over {sum(x['over'] for x in R)} · under {sum(x['under'] for x in R)}")
        print(f"          exact-set (actions){_pc(sum(x['set_ok'] for x in R), n)}")
        print(f"          exact-row (+time,tag){_pc(sum(x['row_ok'] for x in R), n)}")
        print(f"  FIELDS  items matched      {_pc(matched, items)}")
        print(f"          action boundary    {_pc(fa, matched)}")
        print(f"          time               {_pc(ft, matched)}")
        print(f"          tag                {_pc(fg, matched)}")
        print(f"  RELATION kind, matched items after the first  {_pc(sum(t[0] == t[1] for t in rel_m), len(rel_m))}")
        print(f"          kind, ALL gold items after the first    {_pc(sum(t[0] == t[1] for t in rel_all), len(rel_all))}")
        print(f"          `to` points at the right item          {_pc(sum(t[2] for t in rel_m), len(rel_m))}")
        fc = [x["first_clean"] for x in R if x["first_clean"] is not None]
        print(f"          first item carries no relation          {_pc(sum(fc), len(fc))}")
        return rel_m

    print(f"\n{'=' * 78}\nRELATION BOARD · segmentation STAGE over sequence.jsonl · "
          f"{'TEST — aggregates only' if test else 'TRAIN'}\n"
          f"{len(rows)} rows: {len(scored)} scored · {len(decoys)} decoys · {n_amb} ambiguous (never scored)\n"
          f"{'=' * 78}")
    rel_m = block("ALL SCORED ROWS", scored)
    block("CLEAN rows", [r for r in scored if not r["damage"]])
    block("DAMAGED rows (misspelt joiner / split word / missing comma / title typo)",
          [r for r in scored if r["damage"]])

    if rel_m:
        print("\n  RELATION KIND per gold kind (matched items), with where the misses went:")
        by = collections.defaultdict(collections.Counter)
        for g, p, _to, _j, _m in rel_m:
            by[g][p] += 1
        for g in KINDS:
            if g in by:
                c = by[g]
                tot = sum(c.values())
                miss = ", ".join(f"{k} {v}" for k, v in c.most_common() if k != g)
                print(f"     {g:10s} {_pc(c[g], tot):>20}   {('→ ' + miss) if miss else ''}")
        print("\n  RELATION KIND per joiner (matched items after the first):")
        byj = collections.defaultdict(list)
        for g, p, _to, j, _m in rel_m:
            byj[j].append(g == p)
        for j in sorted(byj, key=lambda k: (sum(byj[k]) / len(byj[k]), k)):
            print(f"     {j or '(none)':24s} {_pc(sum(byj[j]), len(byj[j]))}")

    dm = [r for r in scored if r["damage"]]
    if dm:
        print("\n  DAMAGE, per operation — count right · relation kind right (matched), damaged vs its clean twins:")
        twins = {r["id"]: r for r in scored}
        by = collections.defaultdict(list)
        for r in dm:
            by[r["damage"]].append(r)
        for d in sorted(by):
            dr = [res[r["id"]][0] for r in by[d]]
            cr = [res[twins[r["twin"]]["id"]][0] for r in by[d] if r["twin"] in twins]
            def rk(R):
                t = [x for y in R for x in y["rels"] if x[4]]
                return _pc(sum(x[0] == x[1] for x in t), len(t))
            print(f"     {d:22s} damaged: count {_pc(sum(x['count_ok'] for x in dr), len(dr))} · kind {rk(dr)}"
                  f"   | clean twin: count {_pc(sum(x['count_ok'] for x in cr), len(cr))} · kind {rk(cr)}")

    if decoys:
        D = [res[r["id"]] for r in decoys]
        ok = sum(len(p) == 1 for _x, p in D)
        print(f"\nDECOYS  —  no false split   {_pc(ok, len(D))}")
        if not test:
            byk = collections.defaultdict(list)
            for r in decoys:
                byk[r["family"]].append(len(res[r["id"]][1]) == 1)
            for f in sorted(byk):
                print(f"     {f:28s} {_pc(sum(byk[f]), len(byk[f]))}")

    if test:
        return
    # per-family worst (TRAIN only): exact-row, then relation kind
    fam = collections.defaultdict(list)
    for r in scored:
        fam[r["family"]].append(res[r["id"]][0])
    worst = []
    for f, R in fam.items():
        t = [x for y in R for x in y["rels"] if x[4]]
        worst.append((sum(x["row_ok"] for x in R) / len(R),
                      (sum(x[0] == x[1] for x in t) / len(t)) if t else 1.0, f, len(R)))
    worst.sort()
    print("\n  WORST FAMILIES (TRAIN) — exact-row · relation kind:")
    for er, rk, f, n in worst[:12]:
        print(f"     {f:34s} exact-row {100 * er:5.1f}% · relation kind {100 * rk:5.1f}%  (n={n})")
    if show:
        print(f"\n--- failing rows (first {show}) ---")
        k = 0
        for r in scored + decoys:
            x, p = res[r["id"]]
            bad = (not x["row_ok"]) or any(t[0] != t[1] for t in x["rels"])
            if r["decoy"]:
                bad = len(p) != 1
            if not bad:
                continue
            k += 1
            print(f"\n[{r['family']}{' · ' + r['damage'] if r['damage'] else ''}] {r['text']}")
            for g in r["gold"]:
                rel = g["relation"]
                print(f"   gold  {g['action']!r} | {g['time']!r} | {g['tag']} | "
                      f"{rel['kind'] + '→' + str(rel['to_index']) if rel else '-'}")
            for q in p:
                rel = q["relation"]
                print(f"   pred  {q['action']!r} | {q['time']!r} | {q['tag']} | "
                      f"{(rel or {}).get('kind', '-')}{'→' + str(rel.get('to')) if rel else ''}")
            if k >= show:
                break


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("train", "test"), default="train")
    ap.add_argument("--show", type=int, default=0, help="TRAIN only: print N failing rows")
    ap.add_argument("--family", default="", help="TRAIN only: one family")
    a = ap.parse_args()
    if a.split == "test" and (a.show or a.family):
        raise SystemExit("--show/--family read rows; the TEST half prints aggregates only")
    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if r["split"] == a.split]
    if a.family:
        rows = [r for r in rows if r["family"] == a.family]
    board(rows, a.show, a.split == "test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
