"""Does a change find its target on the other list? — the save step's board.

    ./.venv/bin/python -m scripts.cross_store_board [--split train|test] [--limit N]

Every create-free CHANGE row of the FastRule set (update/delete/complete, event
or to-do) is replayed through the whole engine, model-free, against a fresh
scratch store holding the row's gold target on the list its gold names, plus
decoys on BOTH lists. Scored: RIGHT = the seeded target was changed as the
gold asks (deleted, retitled, re-dated, completed); WRONG = any decoy was
touched, or the target was touched on the wrong list. Two arms at one commit:
the other-list lookup (`engine._other_store`) off and on. TEST prints
aggregates only (TRAIN_TEST_SPLIT_CONVENTION).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import tempfile

_S = pathlib.Path(tempfile.mkdtemp(prefix="cross_store_"))
for _v in ("DB", "MEMORY_DB", "VOCAB", "CATEGORIES", "MODELS", "LABEL_FEEDBACK", "MODEL_LOCK",
           "TRACE_BUS", "LLM_BUS", "CHECKPOINTS", "LEXICON", "UI_STATE", "LOCATION",
           "DEVICE_SECRET", "DEVICES"):
    os.environ[f"MACALENDAR_{_v}"] = str(_S / _v.lower())
os.environ["MACALENDAR_NO_WARMUP"] = "1"
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
os.environ["MACALENDAR_LLM_DISABLED"] = "1"
os.environ["MACALENDAR_OBSERVANCE"] = "0"

ROOT = pathlib.Path(__file__).resolve().parents[1]   # scripts/ -> repo root
DATA = ROOT / "assistant/engine/fastrule/datasets/fastrule_7200.jsonl"
DECOY_TODOS = ["water the plants", "renew the passport", "buy birthday candles"]
DECOY_EVENTS = ["team standup", "piano lesson", "yoga class"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train", choices=("train", "test"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--show-wrong", type=int, default=0, help="TRAIN only: print this many decoy-changed rows")
    a = ap.parse_args()

    import datetime as dt
    import assistant.engine as engine
    import assistant.engine.llm as L
    from assistant.db import get_db
    from assistant.actions.calendar.intent import CalendarIntent
    L.is_reachable = lambda cfg=None: True          # the deep track runs; the model door refuses
    engine.run_transcript("walk the dog", source="test")
    db = get_db()
    day = (dt.date.today() + dt.timedelta(days=5)).isoformat()

    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if r.get("split") == a.split
            and (r.get("expect") or {}).get("action", "").split("_")[0] in ("update", "delete", "complete")
            and ((r.get("expect") or {}).get("slots") or {}).get("title")
            and not ((r.get("expect") or {}).get("slots") or {}).get("generic_target")]
    if a.limit:
        rows = rows[:a.limit]

    def reset():
        with db._conn() as conn:
            conn.execute("DELETE FROM events"); conn.execute("DELETE FROM todos")

    def seed(target, store):
        for t in DECOY_TODOS:
            db.create_todo(t, "general")
        for t in DECOY_EVENTS:
            db.create_event(CalendarIntent(title=t, date=day, start_time="09:00"))
        if store == "todo":
            db.create_todo(target, "general")
        else:
            db.create_event(CalendarIntent(title=target, date=day, start_time="15:00"))

    def snapshot():
        with db._conn() as conn:
            ev = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("select id, title, date, start_time from events")}
            td = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("select id, title, due_date, completed from todos")}
        return ev, td

    def score(row, before, after):
        e = row["expect"]; target = e["slots"]["title"].lower()
        store = "todo" if e["action"].endswith("todo") else "event"
        (ev0, td0), (ev1, td1) = before, after
        def changed(d0, d1):
            return {i for i in set(d0) | set(d1) if d0.get(i) != d1.get(i)}
        ch_ev, ch_td = changed(ev0, ev1), changed(td0, td1)
        def is_target(d, i):
            return (d.get(i) or ("",))[0].lower() == target
        tgt_ev = {i for i in ch_ev if is_target(ev0, i) or is_target(ev1, i)}
        tgt_td = {i for i in ch_td if is_target(td0, i) or is_target(td1, i)}
        decoys = (ch_ev - tgt_ev) | (ch_td - tgt_td)
        # A row that did not exist before was CREATED — a wrong operation, not
        # a wrong target. Only a decoy that existed and was edited or removed
        # is the wrong-target harm.
        edited = {i for i in (ch_ev - tgt_ev) if i in ev0} | {i for i in (ch_td - tgt_td) if i in td0}
        if edited:
            return "WRONG: an existing decoy was edited or deleted"
        if decoys:
            return "WRONG: created instead of changing"
        right_store = tgt_td if store == "todo" else tgt_ev
        if right_store:
            return "right"
        if tgt_ev or tgt_td:
            return "WRONG: other list"
        return "nothing changed"

    results = {"off": collections.Counter(), "on": collections.Counter()}
    flips = collections.Counter(); shown = []; wrong_rows = []
    real_other = engine._other_store
    for row in rows:
        per = {}
        for arm in ("off", "on"):
            engine._other_store = real_other if arm == "on" else (lambda state, item: None)
            reset(); seed(row["expect"]["slots"]["title"], "todo" if row["expect"]["action"].endswith("todo") else "event")
            before = snapshot()
            try:
                engine.run_transcript(row["text"], source="test")
            except Exception:
                pass
            per[arm] = score(row, before, snapshot())
            results[arm][per[arm]] += 1
        if a.show_wrong and a.split == "train" and per["on"].startswith("WRONG") and len(wrong_rows) < a.show_wrong:
            wrong_rows.append((row["text"][:80], row["expect"]["action"], row["expect"]["slots"]["title"], per["on"]))
        if per["off"] != per["on"]:
            flips[(per["off"], per["on"])] += 1
            if a.split == "train" and len(shown) < 12:
                shown.append((row["text"][:70], per["off"], per["on"]))
    engine._other_store = real_other
    n = len(rows)
    print(f"cross-store board — FastRule {a.split.upper()} change rows, n={n}, model-free")
    for arm in ("off", "on"):
        c = results[arm]
        print(f"  lookup {arm:3s}: right {c['right']}/{n} = {100*c['right']/max(n,1):.1f}%   "
              + "   ".join(f"{k}: {v}" for k, v in sorted(c.items()) if k != "right"))
    print("  rows that changed (off -> on):", dict(flips))
    for s in shown:
        print("    ", s)
    for w in wrong_rows:
        print("  WRONG:", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
