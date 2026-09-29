"""How good is the phone's offline reader? Apple's on-device model on the
FastRule set — quality and latency (2026-09-28).

Gil: *"can you measure how good the apple [model] and the latency"*. The phone
reads a command with Apple's on-device foundation model (~3B parameters) only
while the Mac is away (DEVQA Q66, `assistant/offline/PROTOCOL.md`). The SAME
model ships in macOS 26, so this board runs it here, exactly as the phone does
— `afm_reader.swift` builds the same session, prompt and `@Generable` shape;
the instructions are `spec.py`'s, assembled the way `OfflineReader.swift`
assembles them (vocabulary names left out: the set is generic) — and scores
the phone's SANITISED reading with the FastRule board's own gold converters
(`fastrule/experiments/gold.py`), at the board's clock (2026-09-09 10:00).

    python -m assistant.offline.experiments.apple_board            # TRAIN, n=1200, seeded 7
    python -m assistant.offline.experiments.apple_board -n 300 --split train
    python -m assistant.offline.experiments.apple_board --resume   # after a crash, same commit

LATENCY IS THE MAC'S, not the phone's: same model, different chip. An A18
phone is slower than an M-series Mac; read these as a floor.

Every row is one checkpoint line with its wall-clock time (a `kill -9` costs
the row in flight); a progress line prints every 25 rows with rate and ETA.
Fresh by default — resuming is for a crash at the same commit.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATASET = ROOT / "assistant/engine/fastrule/datasets/fastrule_7200.jsonl"
SWIFT = HERE / "afm_reader.swift"
GUARD_SWIFT = ROOT / "MACalendar-iOS/MACalendar-iOS/Voice/OfflineGuard.swift"
DATES_SWIFT = ROOT / "MACalendar-iOS/MACalendar-iOS/Voice/OfflineDates.swift"

_CLOCK = _dt.datetime(2026, 9, 9, 10, 0)          # the FastRule board's clock
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
KINDS = ("event", "todo", "other")
RECS = ("none", "daily", "weekly", "monthly", "yearly")


def instructions() -> str:
    """spec.py's text, assembled exactly as OfflineReader.instructions() does
    (compact sorted-key JSON for the examples, as Swift's JSONEncoder writes)."""
    from assistant.offline import spec
    out = spec.INSTRUCTIONS
    if spec.EXAMPLES:
        out += "\n\nExamples:"
        for ex in spec.EXAMPLES:
            items = json.dumps(ex["items"], sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False)
            out += f"\nToday: {ex['today']}\nSaid: {ex['said']}\nItems: {items}"
    return out


def sanitize(items: list) -> list:
    """OfflineReader.sanitize, line for line: what the phone would BOOK."""
    out = []
    for raw in items or []:
        it = {k: str(raw.get(k) or "") for k in ("kind", "title", "date", "start", "end", "recurrence")}
        it["title"] = it["title"].strip()
        if it["kind"] not in KINDS:
            it["kind"] = "other"
        if it["recurrence"] not in RECS:
            it["recurrence"] = "none"
        if it["date"]:
            try:
                ok = bool(_DAY.match(it["date"])) and _dt.date.fromisoformat(it["date"])
            except ValueError:
                ok = False
            if not ok:
                it["date"] = ""
        if it["start"] and not _HM.match(it["start"]):
            it["start"] = ""
        if it["end"] and not _HM.match(it["end"]):
            it["end"] = ""
        if not it["start"]:
            it["end"] = ""
        if not it["title"]:
            it["kind"] = "other"
        if it["kind"] == "event" and not it["date"]:
            it["kind"] = "other"
        out.append(it)
    return out


def build_reader(out_dir: Path) -> Path:
    exe = out_dir / "afm_reader"
    subprocess.run(["swiftc", "-O", "-parse-as-library", str(SWIFT), str(GUARD_SWIFT),
                    str(DATES_SWIFT), "-o", str(exe)], check=True)
    return exe


def pct(a: int, n: int) -> str:
    return f"{100 * a / n:5.1f}% ({a}/{n})" if n else "   —"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=1200)
    ap.add_argument("--split", default="train", choices=("train", "test"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--no-guard", action="store_true",
                    help="the reader as first shipped: every command goes to the model")
    ap.add_argument("--tag", default="", help="names the run, e.g. 'guard' vs 'baseline'")
    a = ap.parse_args()

    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    pool = [r for r in rows if r.get("split") == a.split]
    random.Random(a.seed).shuffle(pool)
    rows = pool[:a.n]
    from assistant.checkpoint import Checkpoint
    tag = f"_{a.tag}" if a.tag else ""
    ck = Checkpoint(f"apple_board_{a.split}_n{len(rows)}_s{a.seed}{tag}", total=len(rows),
                    resume=a.resume)

    todo = [r for r in rows if not ck.has(r["id"])]
    tmp = Path(tempfile.mkdtemp(prefix="apple-board-"))
    (tmp / "instructions.txt").write_text(instructions())
    from assistant.offline import spec as _spec
    (tmp / "guard.json").write_text(json.dumps(_spec.guard()))
    if todo:
        exe = build_reader(tmp)
        day = f"{_CLOCK:%Y-%m-%d} ({_CLOCK:%A})"
        feed = "".join(json.dumps({"id": r["id"], "text": r["text"], "today": day}) + "\n"
                       for r in todo)
        # The rows go in from a FILE, not a pipe we write while also reading:
        # writing 1,200 rows into the tool's stdin before reading its stdout
        # deadlocked (both pipes full, 0 rows recorded, all night — 2026-09-28).
        (tmp / "rows.jsonl").write_text(feed)
        args = [str(exe), str(tmp / "instructions.txt")]
        if not a.no_guard:
            args.append(str(tmp / "guard.json"))
        proc = subprocess.Popen(args,
                                stdin=open(tmp / "rows.jsonl"), stdout=subprocess.PIPE,
                                text=True, bufsize=1)
        for line in proc.stdout:
            got = json.loads(line)
            if "fatal" in got:
                print("FATAL:", got["fatal"], file=sys.stderr)
                return 3
            ck.record(got["id"], {"items": got.get("items") or [], "ms": got.get("ms"),
                                  "error": got.get("error"), "guarded": bool(got.get("guarded")),
                                  "at": _dt.datetime.now().isoformat(timespec="seconds")})
        proc.wait()
    ck.finish()
    res = ck.results
    return report(rows, res, a)


def report(rows: list, res: dict, a) -> int:
    from assistant.common.similarity import token_prf
    from assistant.engine.fastrule.experiments.gold import (
        _EXPLICIT_TIME_RE, CONTRADICTORY, _phrase_to_date, _ruled_hhmm)
    from assistant.offline.reconcile import titles_match

    lat = [v["ms"] for v in res.values()
           if v and v.get("ms") is not None and not v.get("guarded")]
    guarded = sum(1 for v in res.values() if v and v.get("guarded"))
    errors = sum(1 for v in res.values() if v and v.get("error"))
    c = Counter()
    fams = Counter()
    for r in rows:
        v = res.get(r["id"])
        if not v:
            continue
        fams[r["family"].rsplit("_", 1)[0]] += 1
        e = r["expect"]
        act = e.get("action", "")
        items = sanitize(v["items"])
        booked = [i for i in items if i["kind"] in ("event", "todo")]
        ev = sum(1 for i in booked if i["kind"] == "event")
        td = sum(1 for i in booked if i["kind"] == "todo")
        creates = act in ("create_event", "create_todo", "mixed") and (
            e.get("events", 0) + e.get("tasks", 0)) > 0
        if not creates:
            # an edit, a delete, a question, a proposal: the phone must book NOTHING
            c["non_create_n"] += 1
            c["non_create_booked"] += bool(booked)
            continue
        want_ev, want_td = e.get("events", 0), e.get("tasks", 0)
        c["create_n"] += 1
        c["count_right"] += (ev == want_ev and td == want_td)
        c["booked_nothing"] += not booked
        c["extra_items"] += max(0, (ev + td) - (want_ev + want_td))
        if not e.get("atomic", True) or want_ev + want_td != 1:
            continue
        # one expected item: score its fields
        want_kind = "event" if want_ev else "todo"
        c["single_n"] += 1
        it = next((i for i in booked if i["kind"] == want_kind), None)
        if it is None:
            continue
        c["single_kind"] += 1
        slots = e.get("slots") or {}
        full = True
        gt = slots.get("title") or ""
        if gt:
            c["title_n"] += 1
            ok = titles_match(gt, it["title"])
            c["title_ok"] += ok
            c["title_f1_sum"] += token_prf(gt, it["title"])[2]
            full &= ok
        dp = slots.get("date_phrase") or ""
        want_d = _phrase_to_date(dp, _CLOCK.date()) if dp else None
        if want_d:
            c["date_n"] += 1
            ok = it["date"] == want_d
            c["date_ok"] += ok
            full &= ok
        tp = slots.get("time_phrase") or ""
        if want_kind == "event" and tp and _EXPLICIT_TIME_RE.search(tp):
            want_t = _ruled_hhmm(tp, r["text"])
            if want_t and want_t != CONTRADICTORY:
                c["time_n"] += 1
                ok = it["start"] == want_t
                c["time_ok"] += ok
                full &= ok
        wr = slots.get("recurrence_rounded")
        if wr:
            c["rec_n"] += 1
            ok = it["recurrence"] == wr
            c["rec_ok"] += ok
            full &= ok
        c["full_ok"] += full

    n = len([r for r in rows if r["id"] in res])
    q = sorted(lat)
    p = lambda f: q[min(len(q) - 1, int(f * len(q)))] if q else 0  # noqa: E731
    print(f"\nAPPLE ON-DEVICE MODEL — FastRule set, {a.split.upper()} split, n={n}/{len(rows)} "
          f"scored, seed {a.seed}, clock {_CLOCK:%Y-%m-%d %H:%M}, {len(fams)} families")
    print(f"   generation errors            {pct(errors, n)}")
    print(f"   left for the Mac by the guard {pct(guarded, n)}  (no model call)")
    print("\nSAFETY — rows that ask to change, delete, complete or ask (phone must book nothing)")
    print(f"   booked something anyway      {pct(c['non_create_booked'], c['non_create_n'])}")
    print("\nCREATE ROWS — what the phone would put in your calendar")
    print(f"   right number of each kind    {pct(c['count_right'], c['create_n'])}")
    print(f"   booked nothing (left to Mac) {pct(c['booked_nothing'], c['create_n'])}")
    print(f"   extra (invented) items       {c['extra_items']} across {c['create_n']} rows")
    print("\nSINGLE-ITEM CREATE ROWS — field by field (scored where the gold resolves)")
    print(f"   right kind (event / to-do)   {pct(c['single_kind'], c['single_n'])}")
    print(f"   title matches                {pct(c['title_ok'], c['title_n'])}"
          f"   word F1 {100 * c['title_f1_sum'] / c['title_n']:.1f}%" if c['title_n'] else "")
    print(f"   date right                   {pct(c['date_ok'], c['date_n'])}")
    print(f"   explicit time right          {pct(c['time_ok'], c['time_n'])}")
    print(f"   repeat right                 {pct(c['rec_ok'], c['rec_n'])}")
    print(f"   whole item right             {pct(c['full_ok'], c['single_n'])}")
    if q:
        print(f"\nLATENCY per MODEL call (this Mac; a phone is slower; guarded rows excluded)  n={len(q)}")
        print(f"   p50 {p(0.5)} ms   p90 {p(0.9)} ms   p99 {p(0.99)} ms   "
              f"mean {statistics.mean(q):.0f} ms   max {q[-1]} ms")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
