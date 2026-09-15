"""COMMIT + LABEL — does a committed row come out right, and come out at once?

    python -m assistant.engine.label.experiments.label_board
    python -m assistant.engine.label.experiments.label_board -n 800

**No model.** Gold items are converted by the real `fastrule.build` and written
by the real `engine._commit`, so this exercises the production path for the one
step after LLMJudge — the only step that touches the database.

## What CANNOT be measured here, and why saying so matters

The FastRule 7,200 carries a `category` in its gold slots, and it is tempting to
score `classify()` against it. **That number would be circular and must never be
quoted as label accuracy**: `fastrule/datasets/generate.py::classify_event_category`
computes the gold BY CALLING `categories.classify()` on the gold title. Scoring
the classifier against its own output measures nothing.

What the comparison DOES measure, read correctly, is **title fidelity** — gold is
`classify(gold_title)` and production is `classify(produced_title)`, so a
mismatch means the TITLE differed, not that the classifier was wrong. It is
reported under that name and no other.

**True category accuracy needs ground truth this project does not own.** Nothing
in the corpus says what category a human thinks "coffee with Dana" belongs in.
`--review` writes a sample out for hand-labelling, which is the honest way to get
one.

## What CAN be measured, and is

Invariants and coverage — neither needs a labelled corpus:

    colour collisions   adjacent events on a day sharing a colour. The rule is
                        "adjacent events never identical"; this counts breaches.
    uncategorised       a committed event with no category at all
    Personal fallback   the catch-all rate. A classifier that answers "Personal"
                        for everything is not classifying, and this is the only
                        number that notices.
    untagged tasks      the tag equivalent
    refresh             does `state.refresh` name what was actually written —
                        this is the "shows up immediately" signal the clients act on
    readback            is the row retrievable from the DB the instant commit returns
    labels              did the label stage read category/tags back onto the item
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import random
import tempfile
from datetime import date as _date

_S = pathlib.Path(os.environ.get("LABEL_BOARD_SCRATCH",
                                 tempfile.mkdtemp(prefix="label_board_")))
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

# In experiments/, parents[1] is the STAGE folder (the CLAUDE.md ROOT trap).
STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE.parent / "fastrule" / "datasets" / "fastrule_7200.jsonl"

#: `state.refresh` must name every surface the command wrote to, or the client
#: reloads the wrong list and the row does not appear until something else
#: triggers a refresh. THAT is what "shows up immediately" means in code.
_SURFACE = {"event": "events", "todo": "todos"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=int(os.environ.get("N", "400")))
    ap.add_argument("--review", type=str, default="",
                    help="write a hand-labelling sample here (the honest route "
                         "to real category accuracy) and exit")
    a = ap.parse_args()

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.fastrule.build import Built, build_all
    from assistant.engine.state import EngineState, Item
    from assistant.engine.llmjudge.datasets.generate import CLOCK
    from assistant.db import get_db

    cfg = engine.load_config()
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows
            if r["split"] == "train" and r["expect"].get("atomic", True)
            and (r["expect"].get("item") or {}).get("text")
            and str(r["expect"].get("action", "")).startswith("create")]
    random.Random(23).shuffle(rows)
    rows = rows[:a.n]

    db = get_db()
    committed = attempted = 0
    uncategorised = personal = 0
    untagged = tagged = 0
    cat_dist: collections.Counter = collections.Counter()
    tag_dist: collections.Counter = collections.Counter()
    title_agree = title_total = 0
    refresh_wrong: list = []
    readback_fail: list = []
    labels_missing = 0
    day_index: set = set()
    review: list = []

    with freeze_time(CLOCK):
        for r in rows:
            gi = r["expect"]["item"]
            item = Item(id="item_1", kind=gi.get("kind") or "event",
                        text=gi.get("text") or r["text"], time=gi.get("time"))
            st = EngineState(raw_text=r["text"], text=r["text"], source="test")
            st.items = [item]
            try:
                _dv.resolve_values(st, CLOCK.date())
            except Exception:
                pass
            res = build_all([item])[0]
            if not isinstance(res, Built):
                continue
            item.action, item.intent = res.action, res.intent
            attempted += 1

            try:
                engine._commit(st, cfg)
            except Exception as e:            # a commit must not explode
                readback_fail.append((r["text"][:50], f"commit raised: {e}"))
                continue

            wrote = [ex for ex in st.executed if ex.ok and ex.record]
            if not wrote:
                continue
            committed += 1

            # --- the row must be readable THE INSTANT commit returns --------
            surfaces = set()
            for ex in wrote:
                kind, row_id = ex.record[0], ex.record[1]
                surfaces.add(_SURFACE[kind])
                row = db.get_event(row_id) if kind == "event" else db.get_todo(row_id)
                if row is None:
                    readback_fail.append((r["text"][:50], f"{kind} {row_id} not readable"))
                    continue
                if kind == "event":
                    if row.get("date"):
                        day_index.add(row["date"])
                    cat = (row.get("category") or "").strip()
                    if not cat:
                        uncategorised += 1
                    else:
                        cat_dist[cat] += 1
                        if cat == "Personal":
                            personal += 1
                    gold_cat = (r["expect"].get("slots") or {}).get("category")
                    if gold_cat:
                        title_total += 1
                        title_agree += int(cat == gold_cat)
                        if cat != gold_cat and len(review) < 60:
                            review.append({"text": r["text"],
                                           "title": row.get("title"),
                                           "produced": cat, "from_gold_title": gold_cat})
                else:
                    tags = list(row.get("tags") or [])
                    if tags:
                        tagged += 1
                        for t in tags:
                            tag_dist[t] += 1
                    else:
                        untagged += 1

            # --- the refresh signal: what the clients act on ----------------
            want = "both" if len(surfaces) > 1 else (surfaces.pop() if surfaces else "")
            if st.refresh != want:
                refresh_wrong.append((r["text"][:50], f"refresh={st.refresh!r} want={want!r}"))

            if not item.labels:
                labels_missing += 1

    # --- colour collisions: the stated invariant, checked on the real rows ---
    #
    # "adjacent events never share a colour" is the rule `pick_color` exists to
    # keep (`db.auto_category_and_color` hands it the neighbours' colours and it
    # switches to the category's alternate shade). Checked here on what was
    # actually WRITTEN rather than on the function in isolation, because the
    # neighbour lookup is a query and a query is the part that can be wrong.
    collisions: list = []
    adjacent_pairs = 0
    seen_dates = sorted({d for d in day_index})
    for d in seen_dates:
        try:
            y, m, day = (int(x) for x in d.split("-"))
            rows_for_day = db.get_events_for_day(_date(y, m, day))
        except Exception:
            continue
        ordered = sorted(rows_for_day, key=lambda r: (r.get("start_time") or ""))
        for first, second in zip(ordered, ordered[1:]):
            adjacent_pairs += 1
            c1 = (first.get("color") or "").lower()
            c2 = (second.get("color") or "").lower()
            if c1 and c1 == c2:
                collisions.append(
                    f"{d} {first.get('start_time')} “{first.get('title')}” and "
                    f"{second.get('start_time')} “{second.get('title')}” both {c1}")

    print(f"\nCOMMIT + LABEL BOARD — {committed} of {attempted} rows committed "
          f"(train half)\n")
    print("  INVARIANTS")
    print(f"    uncategorised events      {uncategorised}")
    print(f"    adjacent colour clashes   {len(collisions)}"
          f"   (of {adjacent_pairs} adjacent pairs)")
    print(f"    rows not readable at once {len(readback_fail)}")
    print(f"    wrong `refresh` signal    {len(refresh_wrong)}")
    print(f"    items with no labels      {labels_missing}")
    print()
    print("  COVERAGE")
    ev_total = sum(cat_dist.values())
    if ev_total:
        print(f"    events categorised        {ev_total}"
              f"   ·  Personal fallback {100.0 * personal / ev_total:.1f}%")
        print(f"    category spread           "
              + ", ".join(f"{k} {v}" for k, v in cat_dist.most_common(8)))
    if tagged + untagged:
        print(f"    tasks tagged              {tagged}/{tagged + untagged}"
              f" = {100.0 * tagged / (tagged + untagged):.1f}%")
        print(f"    tag spread                "
              + ", ".join(f"{k} {v}" for k, v in tag_dist.most_common(8)))
    print()
    if title_total:
        print(f"  TITLE FIDELITY (not label accuracy — see the module docstring)")
        print(f"    produced title lands in the same category as the gold title:"
              f" {100.0 * title_agree / title_total:.1f}%  ({title_agree}/{title_total})")
        print(f"    A mismatch means the TITLE differed. The gold category is")
        print(f"    `classify(gold_title)`, so this can never score the classifier.")
    print()
    for label, bad in (("readback", readback_fail), ("refresh", refresh_wrong)):
        for text, why in bad[:6]:
            print(f"    [{label}] “{text}” — {why}")
    for clash in collisions[:6]:
        print(f"    [colour] {clash}")

    if a.review:
        pathlib.Path(a.review).write_text(json.dumps(review, indent=1))
        print(f"\n  wrote {len(review)} rows to {a.review} for hand-labelling")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
