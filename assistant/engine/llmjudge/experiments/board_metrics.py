"""Board D's FULL scoring — more than "was it right" (Gil, 2026-09-25: "need to
look at more scoring metrics not just accuracy").

Board D's headline asks one strict question per row: right action AND right
title for every object. That hides everything a user feels: an object too many
or too few, the right event on the wrong day, a destructive mistake versus a
spurious create, the engine rightly holding back, and what the model cost.
This scores the objects the chain BUILT against the row's gold, with the gold
converters the FastRule board uses (`fastrule/experiments/gold.py`), so a
field reads the same on both boards. The families, each defined once in
dataset/METRICS.md:

  STRUCTURE    count-correct · object precision / recall / F1
  FIELDS       on single-create rows: title word F1 (precision = words
               leaked in, recall = words cut) and exact / contained, date, start,
               series cadence, reminder, invented a time
  COST         harm (delete 4 · update/complete 2 · create 1 · query 0) and
               the destructive errors by action
  RESTRAINT    a question held back rather than booked (Q9) · a vague target
               refused (Q38)
  CONFUSION    wanted action -> produced action, the top pairs
  SPEED        rows that needed a model call · latency p50/p95 with / without

Pure: `score(rows, built)` takes the dataset rows and, per row id, the objects
the chain built plus its latency and model milliseconds; `report(m)` prints.
"""
from __future__ import annotations

import collections
import datetime as _dt
import re

from assistant.common.similarity import token_prf
from assistant.engine.fastrule.experiments import gold as G

CLOCK = _dt.date(2026, 9, 9)            # the date the generated set is anchored on
_CREATES = ("create_event", "create_todo")


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", (s or "").lower()) if len(w) > 1}


def _pc(k: int, n: int) -> str:
    return f"{100.0 * k / n:5.1f}% ({k}/{n})" if n else "   —"


def _pctile(xs: list, q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] / 1000.0 if xs else 0.0


def _pool(row: dict) -> str:
    return "new phrasings" if str(row.get("family", "")).startswith(("s_tr_", "c_tr_")) \
        else "original"


def score(rows: list, built: dict, correct: dict) -> dict:
    """`built[id]` = {"objs": [...], "ms": int, "llm_ms": int};
    `correct[id]` = the headline verdict (action + title) for the row."""
    c = collections.Counter()
    by_pool = collections.defaultdict(collections.Counter)
    confusion = collections.Counter()
    destructive = collections.Counter()
    lat = {"model": [], "none": []}
    for r in rows:
        rid = str(r["id"])
        b = built.get(rid)
        if b is None:
            continue
        e = r["expect"]
        act = e.get("action", "")
        slots = e.get("slots") or {}
        objs = b.get("objs") or []
        made = [o["action"] for o in objs]
        pool = by_pool[_pool(r)]
        pool["rows"] += 1
        pool["correct"] += bool(correct.get(rid))
        c["rows"] += 1
        # --- SPEED
        (lat["model"] if b.get("llm_ms") else lat["none"]).append(b.get("ms", 0))
        c["model_rows"] += bool(b.get("llm_ms"))
        # --- STRUCTURE (creates only: the counts are what gold states)
        if act in _CREATES + ("mixed",):
            want_e, want_t = int(e.get("events") or 0), int(e.get("tasks") or 0)
            got_e, got_t = made.count("create_event"), made.count("create_todo")
            ok = got_e == want_e and got_t == want_t
            c["count_n"] += 1
            c["count_ok"] += ok
            pool["count_n"] += 1
            pool["count_ok"] += ok
            c["obj_expected"] += want_e + want_t
            c["obj_created"] += got_e + got_t
            c["obj_matched"] += min(got_e, want_e) + min(got_t, want_t)
            c["missing"] += max(0, want_e - got_e) + max(0, want_t - got_t)
            c["extra"] += max(0, got_e - want_e) + max(0, got_t - want_t)
        # --- FIELDS on a single create that produced one create of the right kind
        if act in _CREATES and int(e.get("events") or 0) + int(e.get("tasks") or 0) == 1:
            mine = [o for o in objs if o["action"] == act]
            if len(mine) == 1:
                o = mine[0]
                c["field_rows"] += 1
                want_title = slots.get("title") or ""
                if want_title:
                    c["title_n"] += 1
                    c["title_exact"] += _words(o.get("title")) == _words(want_title)
                    # SIMILARITY, not only a yes/no (Gil, 2026-09-25): summed
                    # here, averaged in `report`; per-mille ints keep the
                    # Counter JSON-clean.
                    tp, tr, tf = token_prf(want_title, o.get("title"))
                    c["title_p_milli"] += round(1000 * tp)
                    c["title_r_milli"] += round(1000 * tr)
                    c["title_f_milli"] += round(1000 * tf)
                    c["title_contained"] += bool(_words(want_title)) and (
                        _words(want_title) <= _words(o.get("title"))
                        or _words(o.get("title")) <= _words(want_title))
                dphrase = slots.get("date_phrase") or ""
                want_d = G._phrase_to_date(dphrase, CLOCK) if dphrase else None
                if want_d:
                    c["date_n"] += 1
                    c["date_ok"] += (o.get("date") or o.get("due_date")) == want_d
                if act == "create_event":
                    tp = slots.get("time_phrase") or ""
                    # a spoken RANGE, start AND end ('from 6 to 8'); the
                    # explicit line below never scored a bare one
                    rg = G.ruled_range(tp, r["text"]) if tp else None
                    if rg and rg[0] != G.CONTRADICTORY:
                        c["range_n"] += 1
                        c["range_ok"] += (o.get("start_time"), o.get("end_time")) == rg
                    if tp and G._EXPLICIT_TIME_RE.search(tp):
                        want_t = G._ruled_hhmm(tp, r["text"])
                        if want_t and want_t != G.CONTRADICTORY:
                            c["time_n"] += 1
                            c["time_ok"] += o.get("start_time") == want_t
                    elif not tp:
                        from assistant.actions.calendar.intent import meal_hour
                        from assistant.engine.decompose_validate.resolve import PART_OF_DAY
                        honest = {"00:00", "09:00", meal_hour(o.get("title")) or "00:00"}
                        tl = r["text"].lower()
                        honest |= {w[0] for k, w in PART_OF_DAY.items()
                                   if re.search(rf"\b{re.escape(k)}\b", tl)}
                        c["invent_n"] += 1
                        c["invent"] += bool(o.get("start_time")) and o.get("start_time") not in honest
                    rec = slots.get("recurrence_rounded")
                    if rec:
                        c["rec_n"] += 1
                        c["rec_ok"] += (o.get("recurrence") or "") == rec
                lt = slots.get("lead_time")
                if lt:
                    from assistant.intent import lead_time as _lead
                    _, want_min = _lead.split(f"book the thing and remind me {lt}")
                    if want_min:
                        c["lead_n"] += 1
                        c["lead_ok"] += o.get("reminder_minutes") == want_min
        # --- RESTRAINT
        if act == "propose":
            c["propose_n"] += 1
            c["propose_held"] += not any(a in _CREATES for a in made)
        if slots.get("generic_target"):
            c["generic_n"] += 1
            c["generic_refused"] += not any(a.startswith(("delete", "update", "complete"))
                                            for a in made)
        # --- COST and CONFUSION on rows the headline calls wrong
        if not correct.get(rid):
            wrong = [a for a in made if a != act] or made
            sev = max((G._SEVERITY.get(a, 1) for a in wrong), default=0)
            c["harm"] += sev
            c["wrong"] += 1
            for a in wrong:
                if a.startswith(("delete", "update", "complete")):
                    destructive[a] += 1
            confusion[(act, "+".join(sorted(set(made))) or "nothing")] += 1
    return {"c": c, "by_pool": by_pool, "confusion": confusion,
            "destructive": destructive, "lat": lat}


def report(m: dict) -> None:
    c = m["c"]
    p = c["obj_matched"] / c["obj_created"] if c["obj_created"] else 0.0
    r = c["obj_matched"] / c["obj_expected"] if c["obj_expected"] else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    print("  FULL SCORING (the ON arm, as shipped) — dataset/METRICS.md defines each line")
    print(f"  STRUCTURE   count-correct          {_pc(c['count_ok'], c['count_n'])}")
    print(f"              objects  P {100*p:5.1f}%  R {100*r:5.1f}%  F1 {100*f1:5.1f}%"
          f"   (created {c['obj_created']}, asked {c['obj_expected']}; "
          f"missing {c['missing']}, extra {c['extra']})")
    print(f"  FIELDS      single-create rows     n={c['field_rows']}")
    if c["title_n"]:
        tn = c["title_n"] * 10.0
        print(f"              title word F1          {c['title_f_milli'] / tn:5.1f}%  "
              f"(precision {c['title_p_milli'] / tn:.1f}% — words leaked in · "
              f"recall {c['title_r_milli'] / tn:.1f}% — words cut; n={c['title_n']})")
    print(f"              title exact            {_pc(c['title_exact'], c['title_n'])}")
    print(f"              title contained        {_pc(c['title_contained'], c['title_n'])}")
    print(f"              date right             {_pc(c['date_ok'], c['date_n'])}")
    print(f"              start time right       {_pc(c['time_ok'], c['time_n'])}")
    print(f"              range right, start+end {_pc(c['range_ok'], c['range_n'])}")
    print(f"              series cadence right   {_pc(c['rec_ok'], c['rec_n'])}")
    print(f"              reminder right         {_pc(c['lead_ok'], c['lead_n'])}")
    print(f"              invented a time        {_pc(c['invent'], c['invent_n'])}")
    print(f"  COST        harm {c['harm']} over {c['wrong']} wrong rows · destructive: "
          + (" · ".join(f"{a} {n}" for a, n in m['destructive'].most_common()) or "none"))
    print(f"  RESTRAINT   question held back     {_pc(c['propose_held'], c['propose_n'])}")
    print(f"              vague target refused   {_pc(c['generic_refused'], c['generic_n'])}")
    print(f"  SPEED       needed a model call    {_pc(c['model_rows'], c['rows'])}")
    lat = m["lat"]
    print(f"              latency p50/p95  with model {_pctile(lat['model'], .5):.1f}s / "
          f"{_pctile(lat['model'], .95):.1f}s   without {_pctile(lat['none'], .5):.2f}s / "
          f"{_pctile(lat['none'], .95):.2f}s")
    print("  BY POOL     (compare runs on the SAME pool)")
    for pool, pc in sorted(m["by_pool"].items()):
        print(f"              {pool:15s} correct {_pc(pc['correct'], pc['rows'])} · "
              f"count-correct {_pc(pc['count_ok'], pc['count_n'])}")
    if m["confusion"]:
        print("  CONFUSION   wanted -> produced, on wrong rows (top 8)")
        for (want, got), n in m["confusion"].most_common(8):
            print(f"              {n:4d}  {want:14s} -> {got}")


def as_record(m: dict) -> dict:
    """The JSON the run record keeps."""
    return {"counts": dict(m["c"]),
            "by_pool": {k: dict(v) for k, v in m["by_pool"].items()},
            "destructive": dict(m["destructive"]),
            "confusion": {f"{a} -> {b}": n for (a, b), n in m["confusion"].most_common(20)}}
