#!/usr/bin/env python3
"""The REAL-USAGE board — replay Gil's own commands, scored against his verdicts.

    python -m scripts.real_usage_board                 # replay + score + report
    python -m scripts.real_usage_board --limit 10      # a slice, for wiring work
    python -m scripts.real_usage_board --score-only    # re-score the last replay
    python -m scripts.real_usage_board --tier corrected

`DOCUMENTATION/REAL_SPEECH_PLAN.md` Phase 1 is the spec. Why this exists: three
FastRule cycles won +4.2 pt on the 7,200-row corpus while the fast path stands at
12 approved to 24 flagged on Gil's actual commands — and the corpus contains none
of the classes those flags show (STT garbage in a title, disfluency, stutter
over-splits). This is the only non-circular instrument the project has, and it
grows every week on its own.

**Not the dropped dataset.** `dataset/realspeech/` was synthetic and Gil dropped
it. This is `~/.assistant_tools/nlu_memory.db`, the history he actually reviewed.

THREE TIERS, REPORTED SEPARATELY AND NEVER POOLED
-------------------------------------------------
  corrected   he said what the right answer was -> object-correct, per field
  approved    he accepted what the engine did   -> regression only
  rejected    he said it was wrong, no gold      -> did the output CHANGE at all

**The corrected tier's gold is only partly usable, and that is a finding rather
than a flaw here.** `memory.set_feedback` (`intent/memory.py:229`) stores
whatever the client sends, and the review flow sends the record as it stands
AFTER Gil edits it in the UI — so about half these rows carry a title he typed
that the utterance never contained ("Set a meeting for 10 a.m. tomorrow morning"
-> "Date <heart>"). No parser can produce that, and scoring against it would cap
the metric forever and punish the engine for not reading his mind. So each
corrected row is hand-marked `gold_usable` in `taxonomy.jsonl`, the headline is
computed over the usable ones, and BOTH counts are always printed.

THE SANDBOX
-----------
Copied from `scripts/checkpoint_sweep.py`, which is the pattern that survived
contact: `create_app()` + the Flask test client, never a live socket (a POST to
127.0.0.1:8080 is served by the RUNNING assistant and holds the real stores —
`tests/conftest.py` refuses it for that reason). Every store is redirected
before `assistant` is imported, because the paths are read at import time. The
real vocabulary and categories are COPIED IN read-only: the vocabulary repairs
the transcript before anything parses it, so a blank one measures a different
system — and repairing "Conello oil" is precisely what this board is here to
measure. An md5 guard over the real stores runs before and after; if one moved,
the numbers are not trustworthy and the run says so instead of guessing.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
REAL_STORES = pathlib.Path.home() / ".assistant_tools"
OUT_DIR = ROOT / "DOCUMENTATION" / "experiments" / "real_usage"
TAXONOMY = OUT_DIR / "taxonomy.jsonl"
REPLAY_OUT = OUT_DIR / "last_replay.json"

#: The fields a parse can be judged on. `location`/`attendees`/`description`
#: are deliberately OUT: they are the fields Gil most often types by hand after
#: the fact, so scoring them measures his editing, not the engine's reading.
FIELDS = ("title", "date", "start_time", "end_time", "recurrence", "recur_until")

#: The taxonomy's classes. `REAL_SPEECH_PLAN.md` fixes this list; a row whose
#: cause is not here gets `other` and a note, and the list is widened only with
#: a reason written down.
#: Three were added 2026-09-18 on the board's FIRST run, each with a reason:
#: `generic-title` because it is the largest class by a wide margin and folding
#: it into `reader-gap` hid the one finding this board was built to produce;
#: `anaphoric-edit` because "the event you just made" is a capability, not a
#: parse bug; `non-command` because "Execute." alone created an event.
CLASSES = ("generic-title", "disfluency", "stt-garbage", "anaphoric-edit",
           "compound", "stutter-split", "time-format", "non-command",
           "reader-gap", "other")


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def _store_fingerprint() -> dict:
    """md5 of the real DATA stores only.

    Not the logs, heartbeats or model.lock: those change continuously while the
    live stack runs, and a guard that cries leak on every run is a guard nobody
    reads. Lifted from `checkpoint_sweep._store_fingerprint` on purpose — one
    idea, one spelling.
    """
    names = ("calendar.db", "nlu_memory.db", "vocab.json", "categories.json",
             "location.json", "trace_bus.jsonl", "label_feedback.jsonl")
    out = {}
    for name in names:
        p = REAL_STORES / name
        if p.is_file():
            with contextlib.suppress(OSError):
                out[name] = hashlib.md5(p.read_bytes()).hexdigest()
    return out


def _real_contents() -> dict:
    """The real calendar's newest rows, so a fingerprint change can EXPLAIN itself.

    The md5 guard can tell that something moved but not what, and its own
    docstring says a change means "either a genuine leak or the assistant was
    used during the run". The first time it fired here it was the second — Gil
    added two todos by hand while the board ran — and establishing that took
    hand forensics against the live store. So the guard now carries the rows
    with it: a leak shows up as rows whose titles came from the REPLAY, and
    ordinary use shows up as rows that did not.
    """
    out = {"events": [], "todos": []}
    db = REAL_STORES / "calendar.db"
    if not db.is_file():
        return out
    with contextlib.suppress(Exception):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        out["events"] = [f"{r['id']}:{r['title']}" for r in con.execute(
            "SELECT id, title FROM events ORDER BY id DESC LIMIT 12")]
        out["todos"] = [f"{r['id']}:{r['title']}" for r in con.execute(
            "SELECT id, title FROM todos ORDER BY id DESC LIMIT 12")]
        con.close()
    return out


# ---------------------------------------------------------------------------
# Reading the history (read-only, always)
# ---------------------------------------------------------------------------

def load_history() -> list:
    """Every real reviewed command, newest last. Opened `mode=ro` so this cannot
    write to the store that feeds the review flows even by accident."""
    db = REAL_STORES / "nlu_memory.db"
    if not db.is_file():
        raise SystemExit(f"no command history at {db}")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, ts, source, "
        "COALESCE(NULLIF(raw_transcript,''), transcript) AS said, "
        "transcript, parse_path, actions_json, correction_json, feedback, "
        "total_ms, llm_ms "
        "FROM examples WHERE source != 'test' ORDER BY id"
    ).fetchall()
    con.close()
    out = []
    for r in rows:
        tier = {"corrected": "corrected", "approved": "approved",
                "rejected": "rejected"}.get(r["feedback"])
        if tier is None:
            continue                      # feedback 'none'/'skipped': no verdict
        if tier == "corrected" and not (r["correction_json"] or "").strip():
            tier = "rejected"             # marked wrong, no gold recorded
        out.append({
            "id": r["id"], "said": r["said"], "tier": tier, "ts": r["ts"],
            "was_path": r["parse_path"], "was_ms": r["total_ms"],
            "engine_then": _actions_of(r["actions_json"]),
            "gold": _actions_of(r["correction_json"]),
        })
    return out


def _actions_of(blob) -> list:
    """`[{action, parameters}]` out of whatever shape the column holds."""
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        name = item.get("action") or item.get("name") or ""
        params = item.get("parameters") or item.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        entry = {"action": name, "parameters": params}
        # The annotation `memory` stores since 2026-09-22 (`intent/correction.py`);
        # a row from before is annotated on the fly in `score`.
        if isinstance(item.get("reachable"), dict):
            entry["reachable"] = item["reachable"]
        if isinstance(item.get("changed"), list):
            entry["changed"] = item["changed"]
        out.append(entry)
    return out


def load_taxonomy() -> dict:
    """Hand classification, keyed on the VERBATIM transcript.

    Keyed on the text and not the row id so it survives a history rebuild, which
    is the same reason every join against the pool keys on `raw_transcript`.
    """
    marks = {}
    if TAXONOMY.is_file():
        for line in TAXONOMY.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            with contextlib.suppress(ValueError):
                rec = json.loads(line)
                if rec.get("said"):
                    marks[rec["said"]] = rec
    return marks


# ---------------------------------------------------------------------------
# The replay
# ---------------------------------------------------------------------------

def replay(rows: list, scratch: pathlib.Path, resume: bool = False) -> list:
    """Run every row through the real engine in a sandbox. Resumable."""
    stores = scratch / "stores"
    stores.mkdir(parents=True, exist_ok=True)

    # BEFORE importing assistant. The paths are read at import time, so an
    # assignment afterwards is too late — tests/conftest.py's rule.
    os.environ["MACALENDAR_DB"] = str(stores / "calendar.db")
    os.environ["MACALENDAR_MEMORY_DB"] = str(stores / "engine_run.db")
    os.environ["MACALENDAR_TRACE_BUS"] = str(stores / "trace_bus.jsonl")
    os.environ["MACALENDAR_LOCATION"] = str(stores / "location.json")
    os.environ["MACALENDAR_DEVICE_SECRET"] = str(stores / "device_secret")
    os.environ["MACALENDAR_DEVICES"] = str(stores / "devices.json")
    os.environ["MACALENDAR_MODELS"] = str(stores / "models")
    os.environ["MACALENDAR_LABEL_FEEDBACK"] = str(stores / "label_feedback.jsonl")
    os.environ["MACALENDAR_CHECKPOINTS"] = str(stores / "checkpoints")
    os.environ["MACALENDAR_UI_STATE"] = str(stores / "ui_state.ini")
    os.environ["MACALENDAR_NO_WARMUP"] = "1"
    os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
    # Observance OFF, as every other replay does (Gil, 2026-09-05): a Friday
    # replay would otherwise penalise the engine for CORRECTLY refusing to book
    # inside Shabbat, which is not what any of these rows are about.
    os.environ["MACALENDAR_OBSERVANCE"] = "0"

    # The real vocabulary and categories, copied in. Not incidental: the vocab
    # repairs the transcript before anything parses it, and "Conello oil" ->
    # "Canola oil" is exactly the behaviour under test. Copying is a read; the
    # guard still catches a write.
    for var, name in (("MACALENDAR_VOCAB", "vocab.json"),
                      ("MACALENDAR_CATEGORIES", "categories.json")):
        real, dst = REAL_STORES / name, stores / name
        if real.is_file():
            shutil.copyfile(real, dst)
        os.environ[var] = str(dst)

    from assistant.checkpoint import Checkpoint
    from assistant.api.server import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True
    client = app.test_client()

    def created_objects():
        """What this command actually PUT IN THE CALENDAR.

        The reply's `actions` is a list of action NAMES — no parameters — so a
        field-level score cannot come from it. The scratch store is emptied
        before every row, so whatever is in it afterwards is exactly what this
        one command created, which is a stronger reading of "object-correct"
        than anything the reply could carry. Recurrence lives on the SERIES, so
        only the first instance of a series is reported: otherwise a weekly
        event returns fourteen objects and every count comparison is nonsense.
        """
        from assistant.db import get_db
        db = get_db()
        out = []
        with db._conn() as conn:
            seen_series = set()
            for row in conn.execute(
                    "SELECT id, title, date, start_time, end_time, recurrence, "
                    "recurrence_end, series_id FROM events ORDER BY id"):
                sid = row["series_id"]
                if sid is not None:
                    if sid in seen_series:
                        continue
                    seen_series.add(sid)
                out.append({"action": "create_event", "parameters": {
                    "title": row["title"], "date": row["date"],
                    "start_time": row["start_time"], "end_time": row["end_time"],
                    "recurrence": row["recurrence"],
                    "recur_until": row["recurrence_end"]}})
            for row in conn.execute(
                    "SELECT id, title, due_date FROM todos ORDER BY id"):
                out.append({"action": "create_todo", "parameters": {
                    "title": row["title"], "date": row["due_date"]}})
        return out

    def reset_calendar():
        from assistant.db import get_db
        db = get_db()
        assert str(db.path).startswith(str(stores)), \
            "refusing to reset a non-scratch calendar"
        with db._conn() as conn:
            for table in ("events", "todos", "subtasks"):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute("DELETE FROM " + table)

    # WARM THE RULE PARSER OUTSIDE THE FREEZE. freezegun's FakeDatetime breaks
    # spaCy's first load, and in the sweep that made every fast_propose raise on
    # row 1 — all 250 rows silently took the deep track and nobody noticed for
    # weeks. Same trap here.
    with contextlib.suppress(Exception):
        from assistant.engine import llm as _gen
        _rp = _gen.get_rule_parser()
        if _rp is not None:
            _rp.analyze("book gym tomorrow at 7am", current_view="month")

    import datetime as _dt
    from freezegun import freeze_time

    # FRESH BY DEFAULT (2026-09-22). `Checkpoint` resumes by default, and this
    # board resumed EVERY row from a cache recorded at commit 4b47af8 (the
    # first run, 2026-09-18 12:04) on every run since — the 09-21 "IT MOVED
    # NOTHING", the 09-22 "byte-identical fresh replay", and the measured
    # error bar were all the same 75 cached rows read back. The helper prints
    # a warning on a commit mismatch and carries on, which is right for a
    # three-hour board and wrong for a five-minute instrument whose only job
    # is to say whether the code changed anything. `--resume` is for a crash
    # mid-run at the SAME commit, nothing else.
    ck = Checkpoint("real_usage_board", len(rows), resume=resume)
    print(f"  replay: {'resuming the checkpoint' if resume else 'fresh — every row through the current code'}",
          flush=True)

    out, t0 = [], time.time()
    for i, row in enumerate(rows, 1):
        key = str(row["id"])
        if ck.has(key):
            prev = ck.get(key)
            if prev:
                out.append(prev)
                print(f"  [{i}/{len(rows)}] id={key} resumed", flush=True)
                continue
        reset_calendar()
        t = time.time()
        # THE CLOCK IS THE ROW'S OWN. "set a meeting tomorrow at 4pm" recorded on
        # 27 August means 28 August, and replaying it today would resolve it to
        # tomorrow — so every relative date mismatches the stored one and the
        # whole approved tier reads as a regression. It did: 25% before this.
        # `tick=True` so a command that measures its own duration still can.
        when = _dt.datetime.fromtimestamp(row["ts"]) if row.get("ts") else None
        freeze = freeze_time(when, tick=True) if when else contextlib.nullcontext()
        try:
            with freeze:
                r = client.post("/voice/text",
                                json={"transcript": row["said"], "source": "test"})
            payload = r.get_json(silent=True) or {}
            rec = {
                "id": row["id"], "tier": row["tier"], "said": row["said"],
                "status": r.status_code,
                "parse": payload.get("parse"),
                "ms": int((time.time() - t) * 1000),
                "actions": _normalise_actions(payload.get("actions")),
                "created": created_objects(),
                "clock": when.isoformat() if when else None,
                "message": (payload.get("message") or "")[:200],
                "error": None,
            }
        except Exception as exc:                        # noqa: BLE001
            rec = {"id": row["id"], "tier": row["tier"], "said": row["said"],
                   "status": None, "parse": None, "ms": int((time.time() - t) * 1000),
                   "actions": [], "created": [], "message": "",
                   "error": f"{type(exc).__name__}: {exc}"}
        out.append(rec)
        ck.record(key, rec)
        ck.progress()
        rate = (time.time() - t0) / i
        left = rate * (len(rows) - i)
        print(f"  [{i}/{len(rows)}] id={key} {rec['ms']:6d}ms {rec['parse'] or rec['error']}"
              f"   {rate:.1f}s/row  ETA {left/60:.0f}m", flush=True)
    return out


def _normalise_actions(actions) -> list:
    """The reply's `actions` into the same `[{action, parameters}]` shape the
    gold uses, so one comparator serves both."""
    out = []
    for a in actions or []:
        if isinstance(a, str):
            out.append({"action": a, "parameters": {}})
        elif isinstance(a, dict):
            name = a.get("action") or a.get("name") or ""
            params = a.get("parameters") or a.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            # A reply can carry the fields flat rather than nested.
            if not params:
                params = {k: v for k, v in a.items()
                          if k not in ("action", "name", "parameters", "params")}
            out.append({"action": name, "parameters": params})
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _norm(field: str, value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if field == "title":
        s = " ".join(s.lower().split())
    if field in ("start_time", "end_time") and len(s) > 5:
        s = s[:5]                                  # HH:MM:SS -> HH:MM
    if field == "recurrence":
        s = s.lower()
    return s


def _pair(produced: list, gold: list) -> list:
    """Line the two lists up POSITIONALLY, shortest wins, and report the count
    separately. Greedy title matching would flatter a parse that produced the
    right objects in the wrong order, and order is part of being right here."""
    n = min(len(produced), len(gold))
    return [(produced[i], gold[i]) for i in range(n)]


def score(replayed: list, rows: list, taxonomy: dict) -> dict:
    by_id = {r["id"]: r for r in rows}
    res = {
        "corrected": {"n": 0, "usable": 0, "count_ok": 0, "all_ok": 0,
                      "fields": {f: [0, 0] for f in FIELDS}, "rows": [],
                      # the same rows read by hand mark only (the 2026-09-18 headline)
                      "strict_n": 0, "strict_ok": 0},
        "approved": {"n": 0, "same": 0, "rows": []},
        "rejected": {"n": 0, "changed": 0, "rows": []},
        "latency": {},
        "errors": [],
    }
    lat = {}
    for rep in replayed:
        row = by_id.get(rep["id"])
        if row is None:
            continue
        if rep.get("error"):
            res["errors"].append({"id": rep["id"], "error": rep["error"]})
        lat.setdefault(rep.get("parse") or "?", []).append(rep["ms"])
        tier = row["tier"]
        # A gold made only of creates is scored against what reached the store;
        # anything else (update/delete/query) has no created object to compare,
        # so it falls back to the action names the reply reports and the report
        # says which happened.
        gold = row["gold"]
        then = row["engine_then"]
        # The comparison basis is chosen from the REFERENCE, not from the gold:
        # the approved and rejected tiers have no gold, and comparing their
        # stored titles against the reply's parameter-less action list scored
        # every approved row as a regression. That read 37.5% and was entirely
        # this scorer's fault.
        reference = gold if tier == "corrected" else then
        all_creates = bool(reference) and all(
            (g["action"] or "").startswith("create") for g in reference)
        produced = (rep.get("created") or []) if all_creates else rep["actions"]
        mark = taxonomy.get(row["said"], {})

        if tier == "corrected":
            from assistant.intent import correction as _corr
            t = res["corrected"]
            t["n"] += 1
            # A field is scored when the gold VALUE is reachable from the words
            # (`intent/correction.py`: unchanged, or a title whose words were
            # said, or a clock on the spoken grid), or when the row is
            # hand-marked `gold_usable`, which scores every field. Until
            # 2026-09-22 the mark was the only gate and it was per ROW, so a
            # typed title threw away the row's derivable date and clock.
            hand = bool(mark.get("gold_usable", False))
            reach = []
            # RECOMPUTED, never read back from the stored review (2026-09-24):
            # the annotation was written by the rule of its day, and a rule
            # fixed since — an end time now needs words that give an end —
            # must apply to every row alike, or old reviews score by the old
            # rule and new ones by the new.
            for i, g in enumerate(gold):
                base = then[i] if i < len(then) else {}
                reach.append(_corr.reachable_fields(row["said"], base, g))
            count_ok = len(produced) == len(gold)
            per_field, unreachable, scored_any = {}, [], False
            all_ok = count_ok and bool(gold)
            for i, (p, g) in enumerate(_pair(produced, gold)):
                for f in FIELDS:
                    want = _norm(f, (g["parameters"] or {}).get(f))
                    if not want:
                        continue            # gold silent on this field: not scored
                    if not hand and not reach[i].get(f, False):
                        unreachable.append(f)
                        continue            # a value no parse of the words reaches
                    got = _norm(f, (p["parameters"] or {}).get(f))
                    scored_any = True
                    t["fields"][f][1] += 1
                    ok = got == want
                    t["fields"][f][0] += 1 if ok else 0
                    per_field.setdefault(f, []).append(ok)
                    all_ok = all_ok and ok
            if hand:
                t["strict_n"] += 1
                t["strict_ok"] += 1 if all_ok else 0
            if not scored_any and not hand:
                t["rows"].append({"id": rep["id"], "said": row["said"][:70],
                                  "skipped": "no field of the gold is reachable"})
                continue
            t["usable"] += 1
            t["count_ok"] += 1 if count_ok else 0
            t["all_ok"] += 1 if all_ok else 0
            t["rows"].append({
                "id": rep["id"], "said": row["said"][:70], "all_ok": all_ok,
                "scored_on": "created objects" if all_creates else "action names",
                "count": f"{len(produced)}/{len(gold)}",
                "class": mark.get("class", "?"),
                "wrong": [f for f, v in per_field.items() if not all(v)],
                "unreachable": sorted(set(unreachable)),
            })

        elif tier == "approved":
            t = res["approved"]
            t["n"] += 1
            same = _same_shape(produced, then)
            t["same"] += 1 if same else 0
            if not same:
                t["rows"].append({"id": rep["id"], "said": row["said"][:70],
                                  "was": [a["action"] for a in then],
                                  "now": [a["action"] for a in produced]})

        else:
            t = res["rejected"]
            t["n"] += 1
            changed = not _same_shape(produced, then)
            t["changed"] += 1 if changed else 0
            t["rows"].append({"id": rep["id"], "said": row["said"][:70],
                              "changed": changed, "class": mark.get("class", "?"),
                              "was": [a["action"] for a in then],
                              "now": [a["action"] for a in produced]})

    for path, msl in lat.items():
        msl.sort()
        res["latency"][path] = {
            "n": len(msl),
            "p50": msl[len(msl) // 2],
            "p95": msl[min(len(msl) - 1, int(len(msl) * 0.95))],
        }
    return res


def _title_ok(title: str, want) -> "tuple[bool, str]":
    """Right when the title carries one of the subject phrases the words held,
    or — when the words held none (`title_has: null`) — when it is a BARE kind
    word, which Q41 (Gil, 2026-09-22) makes the right answer."""
    from assistant.tips import is_bare_title
    t = " ".join((title or "").lower().split())
    if want is None:
        return is_bare_title(t), "bare"
    return any(w in t for w in want), "said"


def score_reachable(replayed: list, rows: list, taxonomy: dict) -> dict:
    """The generic-title class against REACHABLE gold.

    `reachable` in `taxonomy.jsonl`, hand-authored 2026-09-22 on each row's own
    clock: the subject the WORDS actually held (`title_has`, any of several
    spellings — the vocabulary repairs names), the day and clock they stated, and
    `null` where nothing beyond the kind was said. Two kinds of item, reported
    apart, because they answer different questions: a SAID subject the title must
    carry is the engine's failure when missing; a BARE title where nothing was
    said is right under Q41 and only the hint can improve it. A row with no items
    (`"I need a b-"`) is right when nothing was made.
    """
    from scripts.score_dataset_run import is_garbage_title
    by_id = {r["id"]: r for r in rows}
    blank = lambda: {"n": 0, "title": 0, "clean": 0, "when": 0, "all": 0}
    out = {"n": 0, "count_ok": 0, "all_ok": 0, "said": blank(), "bare": blank(),
           "rows": []}
    for rep in replayed:
        row = by_id.get(rep["id"])
        if row is None:
            continue
        reach = taxonomy.get(row["said"], {}).get("reachable")
        if reach is None:
            continue
        gold = reach["items"]
        produced = rep.get("created") or []
        out["n"] += 1
        count_ok = len(produced) == len(gold)
        out["count_ok"] += 1 if count_ok else 0
        wrong = [] if count_ok else [f"count {len(produced)}/{len(gold)}"]
        row_ok, kinds = count_ok, set()
        for p, g in _pair(produced, gold):
            pp = p["parameters"] or {}
            ok_t, kind = _title_ok(pp.get("title"), g.get("title_has"))
            clean = not is_garbage_title(pp.get("title") or "")
            when = True
            for f in ("date", "start_time", "end_time"):
                want = g.get(f)
                if not want:
                    continue
                wants = want if isinstance(want, list) else [want]
                if _norm(f, pp.get(f)) not in [_norm(f, w) for w in wants]:
                    when = False
                    wrong.append(f)
            if not ok_t:
                wrong.append("title")
            elif not clean:
                wrong.append("title-junk")
            kinds.add(kind)
            b = out[kind]
            b["n"] += 1
            b["title"] += 1 if ok_t else 0
            b["clean"] += 1 if (ok_t and clean) else 0
            b["when"] += 1 if when else 0
            b["all"] += 1 if (ok_t and when) else 0
            row_ok = row_ok and ok_t and when
        if not gold:
            kinds.add("nothing")
        out["all_ok"] += 1 if row_ok else 0
        out["rows"].append({
            "id": rep["id"], "tier": row["tier"], "said": row["said"][:70],
            "all_ok": row_ok, "kind": "/".join(sorted(kinds)), "wrong": wrong,
            "made": [((p["parameters"] or {}).get("title"),
                      (p["parameters"] or {}).get("date"),
                      (p["parameters"] or {}).get("start_time")) for p in produced]})
    return out


def _flatten(acts: list) -> list:
    """One entry per OBJECT. A stored `create_todo` may carry `titles` — several
    to-dos in one action, the fast path's shape — while the replay reports one
    create per to-do. Same outcome, two spellings; compared as one (2026-09-22:
    "buy Dr. Brown and Pepsi" read as a regression against itself)."""
    out = []
    for a in acts:
        p = a.get("parameters") or {}
        if a.get("action") == "create_todo" and isinstance(p.get("titles"), list) and p["titles"]:
            for t in p["titles"]:
                q = {k: v for k, v in p.items() if k != "titles"}
                q["title"] = t
                out.append({"action": a["action"], "parameters": q})
        else:
            out.append(a)
    return out


def _same_shape(a: list, b: list) -> bool:
    """Same actions, same order, same titles+dates. Deliberately not full
    equality: a reply carries fields the stored history never did, and this
    question is only "did the outcome move"."""
    a, b = _flatten(a), _flatten(b)
    if [x["action"] for x in a] != [x["action"] for x in b]:
        return False
    for p, g in zip(a, b):
        if not (p.get("parameters") or {}):
            # The reply's bare action list carries no fields at all (a query,
            # an update — nothing was CREATED to read back), so the action
            # name is all there is to compare. Reading its missing date as a
            # changed date scored every approved query as a regression.
            continue
        for f in ("title", "date"):
            want = _norm(f, (g["parameters"] or {}).get(f))
            if not want:
                # The reference is silent, so it is not evidence — the same rule
                # the corrected tier uses for a gold that omits a field. Without
                # this, a row where the OLD engine recorded no date at all and
                # the current one resolves it correctly scored as a regression.
                continue
            if _norm(f, (p["parameters"] or {}).get(f)) != want:
                return False
    return True


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def pct(k: int, n: int) -> str:
    return f"{100.0 * k / n:.1f}%" if n else "—"


def report(res: dict, rows: list, taxonomy: dict, guard: tuple,
           appeared: "dict | None" = None) -> str:
    before, after = guard
    moved = [k for k in before if before.get(k) != after.get(k)]
    new_rows = [x for v in (appeared or {}).values() for x in v]
    c, a, r = res["corrected"], res["approved"], res["rejected"]
    L = []
    L.append("# Real-usage board\n")
    L.append(f"_Run {time.strftime('%Y-%m-%d %H:%M')}. "
             f"`python -m scripts.real_usage_board`._\n")
    if moved:
        L.append(f"> **A real store changed during the run:** {', '.join(moved)}. "
                 f"Either an override was missed (a leak — distrust everything "
                 f"below) or the assistant was simply used while the board ran.\n")
        if new_rows:
            L.append("> Rows that appeared in the real calendar meanwhile. If any "
                     "of these is a title from the replay list, it IS a leak; if "
                     "they are things Gil typed, it is ordinary use:\n")
            for x in new_rows[:10]:
                L.append(f">   - {x}")
            L.append("")
        else:
            L.append("> No rows appeared in the real calendar, so nothing the board "
                     "created reached it — the change was elsewhere (a log, a "
                     "setting, the command memory the live app writes on every "
                     "command).\n")
    else:
        L.append("> Guard passed: no real store changed during the run.\n")

    L.append("## The headline\n")
    L.append(f"**Corrected tier, every REACHABLE field right: "
             f"{pct(c['all_ok'], c['usable'])} (n={c['usable']} of {c['n']})** — "
             f"a field is scored only where the gold value is one a parse of the "
             f"words could produce (`intent/correction.py`: unchanged, or a title "
             f"whose words were said, or a clock on the five-minute grid); "
             f"{c['n'] - c['usable']} rows have no reachable field at all. Item "
             f"count right on {pct(c['count_ok'], c['usable'])}. Read by hand mark "
             f"alone, as the 2026-09-18 headline was: "
             f"{pct(c['strict_ok'], c['strict_n'])} (n={c['strict_n']}).\n")

    L.append("### Per field, corrected tier\n")
    L.append("| field | right | scored |")
    L.append("|---|---|---|")
    for f in FIELDS:
        ok, n = c["fields"][f]
        L.append(f"| {f} | {pct(ok, n)} | {n} |")
    L.append("")
    L.append("_A field is scored only where the gold states it; a gold silent on "
             "`end_time` is not evidence about `end_time`._\n")
    L.append("_`start_time`/`end_time` read LOW for a reason beyond the parse: on a "
             "row whose gold came from Gil's UI edits, the times were often dragged "
             "by hand too (`3.45 pm` spoken, gold `09:02-09:58`). `gold_usable` is "
             "per ROW, so a row kept for its derivable TITLE brings its hand-set "
             "times along. Treat `title` and `date` as the trustworthy columns and "
             "the clock pair as an upper bound on the damage._\n")

    L.append("## Regression and movement\n")
    L.append(f"- **Approved tier (n={a['n']}):** the replay still produces what he "
             f"accepted on **{pct(a['same'], a['n'])}**. Anything less than 100% is "
             f"a regression against a command he blessed.")
    L.append(f"- **Rejected tier (n={r['n']}):** the output CHANGED on "
             f"**{pct(r['changed'], r['n'])}**. Changed is not fixed — there is no "
             f"gold here — but unchanged is certainly not fixed.\n")

    q = res.get("reachable")
    if q and q["n"]:
        L.append("## Under Q41 — the generic-title class against what the words hold\n")
        L.append("Gil, 2026-09-22 (DEVQA Q41): *\"just make a meeting according to "
                 "other details with bare title is fine.\"* So the largest class is "
                 "re-scored against REACHABLE gold — `reachable` in `taxonomy.jsonl`, "
                 "hand-authored on each row's own clock: the subject the words "
                 "actually held, or a bare title where nothing beyond the kind was "
                 "said, plus the stated day and clock. The tiers above are "
                 "untouched; this is the same rows read under the ruling.\n")
        L.append(f"**Right, or acceptable under Q41: {pct(q['all_ok'], q['n'])} of "
                 f"{q['n']} rows** (item count right on {pct(q['count_ok'], q['n'])}).\n")
        L.append("| items | n | title right | …and no junk in it | day+clock right | title and when |")
        L.append("|---|---|---|---|---|---|")
        for key, label in (("said", "subject was SAID — the title must carry it"),
                           ("bare", "nothing but the kind was said — bare is right")):
            b = q[key]
            if b["n"]:
                L.append(f"| {label} | {b['n']} | {pct(b['title'], b['n'])} | "
                         f"{pct(b['clean'], b['n'])} | {pct(b['when'], b['n'])} | "
                         f"{pct(b['all'], b['n'])} |")
        L.append("")
        L.append("_Per ITEM in the table, per ROW in the bold line. A said subject "
                 "is right when the title CONTAINS the phrase (any spelling the "
                 "vocabulary produces); junk is `score_dataset_run.is_garbage_title`; "
                 "`end_time` is scored only where the words stated one._\n")
        L.append("Rows still wrong under Q41:\n")
        for row in q["rows"]:
            if not row["all_ok"]:
                L.append(f"- id={row['id']} ({row['tier']}, {row['kind']}) wrong: "
                         f"{', '.join(row['wrong']) or '?'} — made {row['made']}")
                L.append(f"  - {row['said']}")
        L.append("")

    L.append("## Failure taxonomy\n")
    counts = {}
    for row in rows:
        m = taxonomy.get(row["said"])
        if m and m.get("class"):
            counts[m["class"]] = counts.get(m["class"], 0) + 1
    total = sum(counts.values())
    if total:
        L.append("| class | rows | share |")
        L.append("|---|---|---|")
        for cls in CLASSES:
            if counts.get(cls):
                L.append(f"| {cls} | {counts[cls]} | {pct(counts[cls], total)} |")
        L.append("")
        L.append(f"_Hand-classified once over {total} non-approved rows, stored in "
                 f"`taxonomy.jsonl` keyed on the verbatim transcript._\n")
    else:
        L.append("_No classification yet — fill `taxonomy.jsonl`._\n")

    # The whole point of the board: say what it means and what to do.
    cls_counts = {}
    for row in rows:
        m = taxonomy.get(row["said"])
        if m and m.get("class"):
            cls_counts[m["class"]] = cls_counts.get(m["class"], 0) + 1
    top = sorted(cls_counts.items(), key=lambda kv: -kv[1])[:1]
    if top:
        name, n = top[0]
        tot = sum(cls_counts.values())
        L.append("## What this run says to do next\n")
        L.append(f"**`{name}` is the largest class at {pct(n, tot)} of {tot} "
                 f"non-approved rows**, and the corrected tier agrees from the other "
                 f"direction: `title` is the worst field by a distance while `date` "
                 f"is comparatively healthy. Read those two together before choosing "
                 f"work — they name the same component.\n")
        L.append("`REAL_SPEECH_PLAN.md` predicted `stt-garbage` + `disfluency` would "
                 "dominate and ordered its phases on that. **They do not**, and the "
                 "plan says in that case to stop and say so rather than build Phase 2 "
                 "anyway. See this file's git history for the correction.\n")
    L.append("## The error bar, measured\n")
    L.append("Two full replays of the same 73 rows on unchanged code, 2026-09-18:\n")
    L.append("| tier | run 1 | run 2 |")
    L.append("|---|---|---|")
    L.append("| corrected, all fields (n=9) | 11.1% | 11.1% |")
    L.append("| corrected, count (n=9) | 77.8% | 77.8% |")
    L.append("| approved, unchanged (n=16) | 43.8% | 43.8% |")
    L.append("| rejected, changed (n=41) | 63.4% | 61.0% |")
    L.append("")
    L.append("**The corrected and approved tiers reproduced exactly; the rejected "
             "tier moved 2.4 pt.** That is the deep track's model output varying "
             "between runs, and it lands only on the rejected tier because that "
             "tier's question is \"did the output change at all\" — the most "
             "sensitive thing one could ask. So: treat a move under ~3 pt on the "
             "rejected tier as noise, and anything on the other two as real. "
             "Re-measure this after any change to the deep track.\n")
    L.append("## Latency, by the path the replay took\n")
    L.append("| parse path | n | p50 | p95 |")
    L.append("|---|---|---|---|")
    for path, v in sorted(res["latency"].items()):
        L.append(f"| {path} | {v['n']} | {v['p50']/1000:.1f}s | {v['p95']/1000:.1f}s |")
    L.append("")

    if res["errors"]:
        L.append(f"## Errors ({len(res['errors'])})\n")
        for e in res["errors"][:10]:
            L.append(f"- id={e['id']}: {e['error']}")
        L.append("")

    L.append("## Why part of the corrected gold cannot be scored\n")
    L.append("`memory.set_feedback` stores whatever the client sends, and the review "
             "flow sends the record as it stands AFTER Gil edits it in the UI. So a "
             "correction is the FINAL STATE of the row, not a corrected reading of "
             "the sentence:\n")
    L.append("    said:  \"Set a meeting for 10 a.m. tomorrow morning\"")
    L.append("    gold:  title \"Date <heart>\", 11:00-15:00\n")
    L.append("No parse produces that, and scoring it would cap this metric forever "
             "and blame the engine for not reading his mind. Since 2026-09-22 the "
             "memory ANNOTATES every correction as it is stored — per action, "
             "which fields changed against the engine's parse and which new "
             "values the words could reach (`assistant/intent/correction.py`, "
             "rules in its docstring) — and this board applies the same rules to "
             "rows stored before then. A field is scored when reachable; a "
             "hand mark `gold_usable` in `taxonomy.jsonl` still scores a whole "
             "row and is what the strict number above reads.\n")

    L.append("## Rows to read\n")
    L.append("### Corrected, still wrong\n")
    for row in c["rows"]:
        if row.get("skipped"):
            continue
        if not row.get("all_ok"):
            unreach = f"; unreachable: {', '.join(row['unreachable'])}" if row.get("unreachable") else ""
            L.append(f"- id={row['id']} [{row['class']}] count {row['count']}, "
                     f"wrong: {', '.join(row['wrong']) or 'count only'}{unreach}")
            L.append(f"  - {row['said']}")
    L.append("")
    L.append("### Approved, no longer reproduced (a regression against a blessed command)\n")
    for row in a["rows"]:
        L.append(f"- id={row['id']} was {row['was']} → now {row['now']}")
        L.append(f"  - {row['said']}")
    L.append("")
    L.append("### Rejected, output unchanged (still wrong the same way)\n")
    for row in r["rows"]:
        if not row["changed"]:
            L.append(f"- id={row['id']} [{row['class']}] {row['was']}")
            L.append(f"  - {row['said']}")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="first N rows, for wiring work")
    ap.add_argument("--tier", choices=("corrected", "approved", "rejected"))
    ap.add_argument("--score-only", action="store_true",
                    help="re-score the stored replay without re-running the engine")
    ap.add_argument("--resume", action="store_true",
                    help="resume the checkpoint of a run that died mid-way AT THIS COMMIT; "
                         "never to skip the replay")
    ap.add_argument("--out", default=str(OUT_DIR / "RESULTS.md"))
    a = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_history()
    if a.tier:
        rows = [r for r in rows if r["tier"] == a.tier]
    if a.limit:
        rows = rows[:a.limit]
    taxonomy = load_taxonomy()

    tiers = {}
    for r in rows:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    print(f"real reviewed commands: {len(rows)}  {tiers}", flush=True)
    print(f"taxonomy entries: {len(taxonomy)}", flush=True)

    before = _store_fingerprint()
    before_rows = _real_contents()
    if a.score_only:
        if not REPLAY_OUT.is_file():
            raise SystemExit("no stored replay; run without --score-only first")
        replayed = json.loads(REPLAY_OUT.read_text())
    else:
        scratch = pathlib.Path(os.environ.get("MACALENDAR_BOARD_SCRATCH")
                               or ("/tmp/real_usage_board"))
        scratch.mkdir(parents=True, exist_ok=True)
        print(f"sandbox: {scratch}", flush=True)
        replayed = replay(rows, scratch, resume=a.resume)
        REPLAY_OUT.write_text(json.dumps(replayed, indent=1))
    after = _store_fingerprint()
    after_rows = _real_contents()

    res = score(replayed, rows, taxonomy)
    res["reachable"] = score_reachable(replayed, rows, taxonomy)
    appeared = {k: [x for x in after_rows[k] if x not in before_rows[k]]
                for k in after_rows}
    text = report(res, rows, taxonomy, (before, after), appeared)
    # Everything after the first `---` line of the existing file is hand-written
    # run HISTORY (run 2 onward) and survives a re-run; the generated report
    # above it is replaced. A 2026-09-21 rebuild lost that history once.
    out_path = pathlib.Path(a.out)
    history = ""
    if out_path.is_file():
        old = out_path.read_text()
        mark = old.find("\n---\n")
        if mark >= 0:
            history = old[mark:]
    out_path.write_text(text + history)

    c = res["corrected"]
    print()
    print(f"CORRECTED  reachable-fields {pct(c['all_ok'], c['usable'])} (n={c['usable']} "
          f"of {c['n']})   count {pct(c['count_ok'], c['usable'])}   "
          f"hand-marked only {pct(c['strict_ok'], c['strict_n'])} (n={c['strict_n']})")
    print(f"APPROVED   unchanged  {pct(res['approved']['same'], res['approved']['n'])} "
          f"(n={res['approved']['n']})")
    print(f"REJECTED   changed    {pct(res['rejected']['changed'], res['rejected']['n'])} "
          f"(n={res['rejected']['n']})")
    q = res["reachable"]
    if q["n"]:
        print(f"Q41        generic-title right/acceptable {pct(q['all_ok'], q['n'])} "
              f"(n={q['n']} rows; said-subject items {q['said']['all']}/{q['said']['n']}, "
              f"bare items {q['bare']['all']}/{q['bare']['n']})")
    moved = [k for k in before if before.get(k) != after.get(k)]
    if moved:
        print(f"GUARD      CHANGED: {', '.join(moved)}")
        for k, v in appeared.items():
            for x in v[:6]:
                print(f"           + real {k}: {x}")
        if not any(appeared.values()):
            print("           (no rows appeared in the real calendar — not the board)")
    else:
        print("GUARD      passed")
    print(f"\nwrote {a.out}")
    return 1 if moved else 0


if __name__ == "__main__":
    raise SystemExit(main())
