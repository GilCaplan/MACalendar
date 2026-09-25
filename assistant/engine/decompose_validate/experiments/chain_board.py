"""THE CHAIN BOARD — does decompose_validate chain a sequence's times?

    ./.venv/bin/python -m assistant.engine.decompose_validate.experiments.chain_board                # TRAIN
    ./.venv/bin/python -m assistant.engine.decompose_validate.experiments.chain_board --show 20      # + failing items
    ./.venv/bin/python -m assistant.engine.decompose_validate.experiments.chain_board --split test   # aggregates only

DEVQA Q51 (Gil, 2026-09-25): a sequence part with no clock of its own starts
when the one before it ENDS; the chain beats a meal's default hour; a stated
clock wins and the chain continues from it; a sequence part inherits the date
of the one it follows; a to-do in a chain becomes an event plus a linked
to-do. `datasets/chain/chain.jsonl` carries that gold, built by construction
(`segmentation/datasets/sequence/generate.py`), against a FIXED anchor,
2026-09-09 06:00 (a Wednesday).

WHAT RUNS: segmentation's stage, then this stage's TEXT pass
(`stage.run`: kind router, decompose, tidy, `resolve_values`), on an
`EngineState`, under a frozen clock, with every model door shut
(`MACALENDAR_LLM_DISABLED=1`) and the stores, the config and the categories
redirected to scratch — so the event length is the built-in 60 minutes and
the chain gap the built-in 0, whatever the machine's config.yaml says.

WHAT IS READ per item: `item.kind`, and `item.slots` date / start_time /
end_time — falling back to `item.intent`'s fields when an intent exists — and
`linked_todo` from `item.slots["linked_todo"]` or an intent attribute of that
name (absent = false). A role call's gold is `null` there — Q50's companion
to-do is the executor's, not this stage's — and is not scored.

AS BUILT. Today an untimed event leaves this stage with no start: the object
layer (`CalendarIntent.fill_defaults`) gives it a meal's hour or 09:00 and an
hour's length later. The board prints a second start/end line with exactly
that completion applied to the stage's output, so "the stage left it for the
object" and "the value is wrong" can be told apart. The headline is the
stage's own reading.

Items are matched to gold by segmentation's matcher (`score.match_items`, action
overlap); an unmatched gold item is wrong on every field. `ambiguous` rows are
never scored; decoys, damaged rows and the one `rollover` family are slices of
their own, and the headline is the clean, non-rollover structural rows.

TEST prints aggregates only — no row, no family name.
"""
from __future__ import annotations

import os
import tempfile

_S = tempfile.mkdtemp(prefix="chain_board_")
for _v in ("DB", "MEMORY_DB", "VOCAB", "CATEGORIES", "MODELS", "LABEL_FEEDBACK",
           "TRACE_BUS", "LLM_BUS", "CHECKPOINTS", "LEXICON", "UI_STATE", "LOCATION",
           "DEVICE_SECRET", "DEVICES", "HEARTBEATS", "HUD_STATE"):
    os.environ[f"MACALENDAR_{_v}"] = os.path.join(_S, _v.lower())
# A config file that does not exist: `event_defaults` then reads the built-in
# 60-minute length and 0-minute gap, which is what the gold is built on.
os.environ["MACALENDAR_CONFIG"] = os.path.join(_S, "no_config.yaml")
os.environ["MACALENDAR_NO_WARMUP"] = "1"
os.environ["MACALENDAR_LLM_PRIORITY"] = "background"
os.environ["MACALENDAR_LLM_DISABLED"] = "1"

import argparse  # noqa: E402
import collections  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from assistant.engine.segmentation.experiments import score as SC  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "datasets" / "chain" / "chain.jsonl"
FIELDS = ("kind", "date", "start_time", "end_time", "linked_todo")


def _pc(a: int, n: int) -> str:
    return f"{100 * a / n:5.1f}% ({a}/{n})" if n else "    —  (0/0)"


def _linked(item) -> bool:
    slots = item.slots or {}
    if slots.get("linked_todo"):
        return True
    intent = getattr(item, "intent", None)
    return bool(getattr(intent, "linked_todo", False)) if intent is not None else False


def _value(item, field):
    slots = item.slots or {}
    if slots.get(field) is not None:
        return slots[field]
    intent = getattr(item, "intent", None)
    if intent is None:
        return None
    name = "due_date" if field == "date" and not hasattr(intent, "date") else field
    return getattr(intent, name, None)


def predict(text: str) -> list:
    from assistant.engine import segmentation as SEG
    from assistant.engine.decompose_validate import stage as DV
    from assistant.engine.state import EngineState

    st = EngineState(raw_text=text, text=text, source="test")
    SEG.run(st, None)
    DV.run(st, None)
    out = []
    for it in st.items:
        out.append({"action": it.text or "", "kind": it.kind,
                    "date": _value(it, "date"), "start_time": _value(it, "start_time"),
                    "end_time": _value(it, "end_time"), "linked_todo": _linked(it)})
    return out


def as_built(p: dict) -> dict:
    """The object layer's completion of an untimed event, applied to the
    stage's output: a meal's hour or 09:00, and an hour's length."""
    from assistant.actions.calendar.intent import meal_hour

    q = dict(p)
    if q["kind"] != "event":
        return q
    if not q["start_time"]:
        q["start_time"] = meal_hour(q["action"]) or "09:00"
    if not q["end_time"] or q["end_time"] == q["start_time"]:
        h, m = map(int, q["start_time"].split(":"))
        e = h * 60 + m + 60
        q["end_time"] = "23:59" if e >= 24 * 60 else f"{e // 60:02d}:{e % 60:02d}"
    return q


def _all(hits: dict) -> bool:
    """Every SCORED field right; a None hit is a field this board does not score."""
    return all(v is not False for v in hits.values())


def score_row(row, pred):
    gold = row["gold"]
    pairs, miss_g, miss_p = SC.match_items(
        [SC.as_item({"action": g["action"], "time": "", "tag": ""}) for g in gold],
        [SC.as_item({"action": p["action"], "time": "", "tag": ""}) for p in pred])
    g2p = {gi: pi for gi, pi, _s in pairs}
    items = []
    for gi, g in enumerate(gold):
        if gi in g2p:
            p = pred[g2p[gi]]
            b = as_built(p)
            hits = {f: (p[f] == g[f]) if f != "linked_todo" else (bool(p[f]) == bool(g[f]))
                    for f in FIELDS}
            if g["linked_todo"] is None:
                hits["linked_todo"] = None     # Q50's companion: the executor's, not scored here
            # SCORED AS BUILT (2026-09-25): the text pass leaves a clocked item's
            # end empty and the object layer fills it, so scoring the text pass
            # charged every clocked item a wrong end — the headline read 44.8%
            # "all five" on train while the chained slice read 82.4%. What is
            # committed is what is scored; the text pass stays a diagnostic.
            built = {f: p[f] == g[f] for f in ("start_time", "end_time")}
            for f in ("start_time", "end_time"):
                hits[f] = b[f] == g[f]
            items.append({"gi": gi, "matched": True, "hits": hits, "built": built, "pred": p})
        else:
            items.append({"gi": gi, "matched": False,
                          "hits": {f: (None if f == "linked_todo" and g["linked_todo"] is None else False)
                                   for f in FIELDS},
                          "built": {"start_time": False, "end_time": False}, "pred": None})
    row_ok = not miss_p and all(_all(i["hits"]) for i in items)
    return {"items": items, "row_ok": row_ok, "spurious": len(miss_p)}


def board(rows, show, test):
    from freezegun import freeze_time

    anchor = dt.datetime.fromisoformat(rows[0]["anchor"]) if rows else dt.datetime(2026, 9, 9, 6, 0)
    # WARM UP BEFORE FREEZING. freezegun swaps `datetime.date` for a subclass,
    # and a library that defines a date subclass at import time (pydantic.v1,
    # under spaCy) then fails with a metaclass conflict. Everything the two
    # stages import lazily is imported here, on the real clock.
    for warm in ("gym at 9 then lunch and buy milk", "remind me to call the plumber tomorrow"):
        predict(warm)
    frozen = freeze_time(anchor, tick=False)
    frozen.start()
    t0 = time.time()
    res = {}
    todo = [r for r in rows if not r["ambiguous"]]
    try:
        for i, r in enumerate(todo):
            p = predict(r["text"])
            res[r["id"]] = (score_row(r, p), p)
            if (i + 1) % 500 == 0:
                print(f"  … {i + 1}/{len(todo)} rows · {time.time() - t0:.0f}s", flush=True)
    finally:
        frozen.stop()

    def block(title, rs, role_filter=None):
        its = [(r, it) for r in rs for it in res[r["id"]][0]["items"]
               if role_filter is None or role_filter(r["gold"][it["gi"]])]
        if not its:
            return
        n = len(its)
        print(f"\n{title}  —  {len({r['id'] for r, _ in its})} rows, {n} gold items")
        print(f"  items matched       {_pc(sum(it['matched'] for _, it in its), n)}")
        for f in FIELDS:
            sc = [it["hits"][f] for _, it in its if it["hits"][f] is not None]
            print(f"  {f:18s}  {_pc(sum(sc), len(sc))}")
        print(f"  ALL FIVE right      {_pc(sum(_all(it['hits']) for _, it in its), n)}")
        print(f"  text pass: start    {_pc(sum(it['built']['start_time'] for _, it in its), n)}"
              f" · end {_pc(sum(it['built']['end_time'] for _, it in its), n)}")
        if role_filter is None:
            R = [res[r["id"]][0] for r in rs]
            print(f"  rows fully right    {_pc(sum(x['row_ok'] for x in R), len(R))}"
                  f"   spurious items {sum(x['spurious'] for x in R)}")

    head = [r for r in rows if not (r["ambiguous"] or r["decoy"] or r["rollover"] or r["damage"])]
    print(f"\n{'=' * 78}\nCHAIN BOARD · segmentation + decompose_validate (text pass) · anchor "
          f"{anchor:%Y-%m-%d %H:%M %a} · {'TEST — aggregates only' if test else 'TRAIN'}\n"
          f"{len(rows)} rows: {len(head)} headline · {sum(r['decoy'] for r in rows)} decoys · "
          f"{sum(bool(r['damage']) for r in rows)} damaged · {sum(r['rollover'] for r in rows)} rollover · "
          f"{sum(r['ambiguous'] for r in rows)} ambiguous (never scored)\n{'=' * 78}")
    block("HEADLINE — clean structural rows, every item", head)
    block("CHAINED ITEMS ONLY (sequence, no clock of their own)", head, lambda g: g["chained"])
    print("\n  per role (headline rows):")
    roles = collections.Counter(g["role"] for r in head for g in r["gold"])
    for role in sorted(roles):
        its = [it for r in head for it in res[r["id"]][0]["items"] if r["gold"][it["gi"]]["role"] == role]
        print(f"     {role:10s} all five {_pc(sum(_all(i['hits']) for i in its), len(its)):>22}"
              f" · start {_pc(sum(i['hits']['start_time'] for i in its), len(its)):>22}"
              f" · kind {_pc(sum(i['hits']['kind'] for i in its), len(its))}")
    linked = [it for r in head for it in res[r["id"]][0]["items"] if r["gold"][it["gi"]]["linked_todo"]]
    print(f"\n  linked_todo on items whose gold is TRUE   {_pc(sum(i['hits']['linked_todo'] for i in linked), len(linked))}")
    block("DAMAGED rows (their clean twins are in the headline)", [r for r in rows if r["damage"]])
    block("DECOYS (one item each)", [r for r in rows if r["decoy"]])
    block("ROLLOVER (a chain past midnight; gold rolls to the next date)", [r for r in rows if r["rollover"]])

    if test:
        return
    fam = collections.defaultdict(list)
    for r in rows:
        if r["ambiguous"]:
            continue
        fam[r["family"]].extend(_all(it["hits"]) for it in res[r["id"]][0]["items"])
    worst = sorted((sum(v) / len(v), f, len(v)) for f, v in fam.items())
    print("\n  WORST FAMILIES (TRAIN) — items with all five right:")
    for rate, f, n in worst[:12]:
        print(f"     {f:34s} {100 * rate:5.1f}%  (n={n} items)")
    if show:
        print(f"\n--- failing items (first {show}) ---")
        k = 0
        for r in rows:
            if r["ambiguous"]:
                continue
            x, p = res[r["id"]]
            bad = [it for it in x["items"] if not _all(it["hits"])]
            if not bad:
                continue
            k += 1
            print(f"\n[{r['family']}{' · ' + r['damage'] if r['damage'] else ''}] {r['text']}")
            for it in x["items"]:
                g = r["gold"][it["gi"]]
                q = it["pred"] or {}
                mark = "  " if _all(it["hits"]) else "✗ "
                print(f"   {mark}gold {g['action']!r}: {g['kind']} {g['date']} {g['start_time']}-{g['end_time']}"
                      f" linked={g['linked_todo']} ({g['role']})")
                print(f"     pred {q.get('action')!r}: {q.get('kind')} {q.get('date')} "
                      f"{q.get('start_time')}-{q.get('end_time')} linked={q.get('linked_todo')}")
            if k >= show:
                break


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("train", "test"), default="train")
    ap.add_argument("--show", type=int, default=0, help="TRAIN only: print N rows with a wrong item")
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
