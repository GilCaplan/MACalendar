"""Run the SAME dataset through several tagged checkpoints, scored by TODAY's scorer.

    python -m scripts.checkpoint_sweep --smoke              # 1 row each, ~seconds
    python -m scripts.checkpoint_sweep --test               # the sealed 300
    python -m scripts.checkpoint_sweep --rows 25            # a quick slice

WHY THIS EXISTS. `loop_log.csv` is 21 readings taken under three different
harnesses, with two declared comparability boundaries, so the trajectory cannot
be read end to end — see DATASET.md's `era` section. This sweep answers the
question the log cannot: take five system states, measure them all TODAY, with
one dataset, one scorer and one machine. There are no eras to reconcile because
every point is taken with the same instrument.

## How a checkpoint is run

Each checkpoint is a git worktree at its tag (`scripts/checkpoint_sweep.py
--setup` makes them, under ../MACalendar-checkpoints/). It runs in **its own
subprocess**, over **HTTP via the Flask test client**, and is scored from the
**calendar DB it writes**.

Those three choices are the whole design, and each one removes a class of
breakage found by inspecting the tags:

- **A subprocess per checkpoint.** Old and new `assistant` packages cannot
  share an interpreter; a single process would resolve `assistant.engine` once
  and reuse it for every later checkpoint.
- **The test client, not an import.** `pre-engine-v2` has NO `run_transcript`
  and no `assistant/engine/` at all — parse and execute are interleaved inside
  `server.py`. There is no common function to call. But every checkpoint has
  `create_app()` and `POST /voice/text`, so HTTP is the one contract all five
  share. It also absorbs signature drift for free: `fast-lane-pre-integration`
  predates `supports_confirm`, and an unknown JSON key is ignored where an
  unexpected kwarg would be a TypeError.
- **Scored from the DB.** `score_dataset_run.score_db` opens the run DB
  read-only and scores the OUTPUT, so it has no dependency on engine
  internals. That is what lets today's scorer grade three-week-old code.

## The safety rule

**Nothing here ever touches port 8080 or the real stores.** The test client is
in-process, so there is no socket and no way to reach a running `assistant.api`
— which holds the REAL calendar, and which env overrides do NOT redirect
(CLAUDE.md: a HUD test's Revert put 45 rows in the real Today list exactly this
way). Every store is pointed at a scratch directory, set BEFORE `assistant` is
imported because the paths are read at import time, and `source` is "test".

## Reading the output

Latency is reported as p50 and p95 PER COMPLEXITY TIER, never as a mean: the
engine's own p50/p95 are 12.0 s and 70.4 s, so an average is a number about the
tail. Tiers hold ~100 of the sealed 300, which supports a median comfortably and
a p95 loosely; anything sliced finer than a tier prints n so a reader can
discount it.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKTREES = ROOT.parent / "MACalendar-checkpoints"
OUT = ROOT / "DOCUMENTATION" / "experiments" / "checkpoints"

#: The system states being compared, oldest first. `main` is the live tree.
CHECKPOINTS = [
    ("pre-engine-v2", "the old brain, before the engine rewrite"),
    ("fast-lane-pre-integration", "FastRule sandbox, pre-integration"),
    ("fastrule-v1", "before the FastRule v2 restructure"),
    ("decompose-validate-v1", "resolver wired into the live path"),
    ("main", "today"),
]

# The child runs inside the checkpoint's own tree. It is written out rather
# than passed with -c so a failure has a real traceback with line numbers.
_CHILD = """\
import json, os, pathlib, sqlite3, sys, time

tree, box, rows_path, out_path = sys.argv[1:5]
box = pathlib.Path(box)
stores = box / "stores"

# BEFORE importing assistant: every store is read at import time, so a fixture
# (or an assignment after the import) is too late. tests/conftest.py's rule.
stores.mkdir(parents=True, exist_ok=True)
ENGINE_DB = str(stores / "engine_run.db")
os.environ["MACALENDAR_DB"] = str(stores / "calendar.db")
# THE SCORER'S INPUT IS THE COMMAND MEMORY, not the calendar: score_db reads
# the `examples` table. Pointing MEMORY_DB somewhere else produces a run with
# nothing to score, which looks like a working sweep.
os.environ["MACALENDAR_MEMORY_DB"] = ENGINE_DB
os.environ["MACALENDAR_TRACE_BUS"] = str(stores / "trace_bus.jsonl")
os.environ["MACALENDAR_LOCATION"] = str(stores / "location.json")
os.environ["MACALENDAR_NO_WARMUP"] = "1"
# Observance OFF for replays (Gil, 2026-09-05): the dataset's ground truth has
# no concept of Shabbat, and a Friday replay otherwise penalises a checkpoint
# for CORRECTLY refusing. engine_dataset_compare sets the same flag.
os.environ["MACALENDAR_OBSERVANCE"] = "0"

# vocab and categories are COPIED FROM THE REAL STORES, read-only, exactly as
# engine_dataset_compare does. They are not incidental: the personal
# vocabulary repairs the transcript before anything parses it, so a blank one
# measures a different system. Copying is a read; the guard still catches writes.
import shutil
for var, real, name in (
        ("MACALENDAR_VOCAB", os.path.expanduser("~/.assistant_tools/vocab.json"), "vocab.json"),
        ("MACALENDAR_CATEGORIES", os.path.expanduser("~/.assistant_tools/categories.json"), "categories.json")):
    dst = stores / name
    if os.path.exists(real):
        shutil.copyfile(real, dst)
    os.environ[var] = str(dst)

sys.path.insert(0, tree)

RAW_KEY = "COALESCE(NULLIF(raw_transcript, ''), transcript)"
result = {"tree": tree, "rows": [], "error": None, "engine_db": ENGINE_DB}
try:
    import assistant
    result["assistant_from"] = assistant.__file__
    from assistant.api.server import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True
    client = app.test_client()

    def reset_calendar():
        from assistant.db import get_db
        db = get_db()
        assert str(db.path).startswith(str(stores)), "refusing to reset a non-scratch DB"
        with db._conn() as conn:
            for table in ("events", "todos", "subtasks"):
                try:
                    conn.execute("DELETE FROM " + table)
                except sqlite3.OperationalError:
                    pass

    # WARM THE RULE PARSER OUTSIDE THE FREEZE. freezegun's FakeDatetime breaks
    # class definitions that subclass datetime (metaclass conflict), and the
    # engine builds its rule parser on the FIRST request. Warming inside the
    # first row's freeze made every fast_propose raise, so all 250 rows
    # silently took the deep track — caught on the 2026-09-05 re-baseline.
    try:
        from assistant.engine.fastrule import objects as _gen
        _rp = _gen._get_rule_parser()
        if _rp is not None:
            _rp.analyze("book gym tomorrow at 7am", current_view="month")
    except Exception:
        try:   # pre-engine-v2 has no engine package; warm its own rule parser
            from assistant.intent.rule_parser import RuleBasedParser
        except Exception:
            pass

    import datetime as _dt
    import contextlib
    from freezegun import freeze_time

    rows = json.loads(pathlib.Path(rows_path).read_text())
    for row in rows:
        reset_calendar()
        ts = row.get("ts")
        # tick=True: the clock STARTS at the row's recorded ts and then advances
        # naturally, so dates resolve in the recorded frame while durations stay
        # real instead of freezing to 0.
        frozen = freeze_time(_dt.datetime.fromtimestamp(ts), tick=True) if ts \
            else contextlib.nullcontext()
        t0 = time.perf_counter()
        try:
            with frozen:
                r = client.post("/voice/text",
                                json={"transcript": row["text"], "source": "test"})
            ms = int((time.perf_counter() - t0) * 1000)
            payload = r.get_json(silent=True) or {}
            rec = {"id": row.get("id"), "tier": row.get("tier"),
                   "status": r.status_code, "ms": ms,
                   "parse": payload.get("parse"),
                   "actions": payload.get("actions")}
            if r.status_code != 200:
                rec["body"] = r.get_data(as_text=True)[-500:]
            result["rows"].append(rec)
        except Exception as e:
            result["rows"].append({
                "id": row.get("id"), "tier": row.get("tier"), "status": None,
                "ms": int((time.perf_counter() - t0) * 1000),
                "error": "%s: %s" % (type(e).__name__, e)})

    # tier_rank is experiment-only; the engine's memory schema lacks it. The
    # scorer joins provenance on it, so stamp each replayed row by its text.
    with sqlite3.connect(ENGINE_DB) as c:
        try:
            c.execute("ALTER TABLE examples ADD COLUMN tier_rank INTEGER")
        except sqlite3.OperationalError:
            pass
        stamped = 0
        for row in rows:
            cur = c.execute(
                "UPDATE examples SET tier_rank = ? WHERE " + RAW_KEY + " = ?",
                (row.get("id"), row["text"]))
            stamped += 1 if cur.rowcount else 0
    result["stamped"] = stamped
except Exception as e:
    import traceback
    result["error"] = "%s: %s" % (type(e).__name__, e)
    result["traceback"] = traceback.format_exc()

pathlib.Path(out_path).write_text(json.dumps(result, indent=1))
"""


def setup() -> int:
    """Create one detached worktree per tag. Idempotent."""
    WORKTREES.mkdir(parents=True, exist_ok=True)
    for tag, _why in CHECKPOINTS:
        if tag == "main":
            continue
        dest = WORKTREES / tag
        if dest.exists():
            print(f"  {tag:<28} already present")
            continue
        r = subprocess.run(["git", "worktree", "add", "--detach", str(dest), tag],
                           cwd=ROOT, capture_output=True, text=True)
        print(f"  {tag:<28} {'created' if r.returncode == 0 else r.stderr.strip()[:80]}")
    return 0


def _tree_for(tag: str) -> pathlib.Path:
    return ROOT if tag == "main" else WORKTREES / tag


def _provenance() -> dict:
    """text -> {complexity, scenario, intent, ts} from hwu64_sample.json.

    COMPLEXITY IS NOT IN EITHER INPUT FILE. `test_split.json` rows are
    `[text, {rank, scenario, intent}]` and `history_3000.json` rows are
    `{seq, text, ts}`; the tier lives only in the provenance file, joined by
    text (DATASET.md: "provenance: scenario/intent/complexity/compound-kind per
    prompt"). Latency per tier is the point of this sweep, so the join is not
    optional — a sweep that silently reported every row as tier "?" would look
    like it worked.
    """
    src = ROOT / "dataset" / "inputs" / "hwu64_sample.json"
    out = {}
    for d in json.loads(src.read_text()).get("rows", []):
        text = d.get("text")
        if text:
            out[text] = d
    return out


PERSONAS = ROOT / "dataset" / "personas" / "personas.jsonl"


def _load_personas(n: int) -> list:
    """A stratified sample of the personas set — the second, CLEAN test half.

    Why this set and not 300 more HWU rows: ITERATION_PROTOCOL says the other
    2,699 rows of the 3000-pool are the training pool ("mine them, train on
    them, tune against them freely"), and the 3000-pool's "aggregate replays
    and threshold sweeps had touched all ranks" — which is why FastRule needed
    its own data. The sealed 300 took the last clean draw from there. The
    personas set is 2,520 rows with `split: "test"` on every one, ground truth
    BY CONSTRUCTION, and it measures the weakness the project has already
    named: swapping vocabulary moves the classifiers 0-3 pt, swapping PHRASING
    moves them 7-29 pt.

    Stratified over persona x tier so all six voices are represented equally —
    the spread BETWEEN personas is the finding, so an uneven draw would hide it.
    """
    rows = [json.loads(l) for l in PERSONAS.read_text().splitlines() if l.strip()]
    buckets: dict = {}
    for r in rows:
        buckets.setdefault((r["persona"], r.get("tier")), []).append(r)
    for key in buckets:
        buckets[key].sort(key=lambda r: r["id"])      # deterministic, no seed
    out, i = [], 0
    keys = sorted(buckets)
    while len(out) < n and any(len(buckets[k]) > i for k in keys):
        for k in keys:                                 # round-robin the strata
            if len(buckets[k]) > i and len(out) < n:
                out.append(buckets[k][i])
        i += 1
    return [{"id": r["id"], "text": r["text"], "tier": r.get("tier"),
             "persona": r["persona"], "family": r.get("family"),
             "expect": r.get("expect") or {}, "gold": r.get("gold") or {},
             # personas carry no timestamp: they are not a history, so there is
             # no recorded moment to replay them at and the clock stays live.
             "ts": None}
            for r in out]


def _load_rows(args) -> list:
    """The prompts to replay, as [{id, text, tier, ts}]."""
    if getattr(args, "personas", None):
        return _load_personas(args.personas)
    src = (ROOT / "dataset" / "inputs" /
           ("test_split.json" if args.test else "history_3000.json"))
    data = json.loads(src.read_text()).get("rows", [])
    prov = _provenance()

    rows = []
    for i, d in enumerate(data):
        if isinstance(d, (list, tuple)):          # test_split: [text, meta]
            text, meta = d[0], (d[1] if len(d) > 1 else {})
        elif isinstance(d, dict):                 # history_3000: {seq, text, ts}
            text, meta = d.get("text"), d
        else:
            text, meta = str(d), {}
        if not text:
            continue
        p = prov.get(text, {})
        rows.append({
            "id": meta.get("rank") or meta.get("seq") or p.get("tier_rank") or i,
            "text": text,
            "tier": p.get("complexity"),
            "scenario": p.get("scenario") or meta.get("scenario"),
            "intent": p.get("intent") or meta.get("intent"),
            # The loop's harness replays each row FROZEN AT ITS RECORDED ts
            # (CLAUDE.md, the 2026-09-05 measurement epoch). Carried here so
            # the freeze can be applied; see the note in run_checkpoint.
            "ts": p.get("ts") or meta.get("ts"),
        })
    missing = sum(1 for r in rows if not r["tier"])
    if missing:
        print(f"  WARNING: {missing}/{len(rows)} rows have no complexity tier "
              f"(provenance join missed them) — per-tier latency will be partial")
    if args.smoke:
        return rows[:1]
    if args.rows:
        return rows[:args.rows]
    return rows


def run_checkpoint(tag: str, rows: list, scratch_root: pathlib.Path) -> dict:
    tree = _tree_for(tag)
    if not tree.exists():
        return {"tag": tag, "error": f"no worktree at {tree} — run --setup"}

    # ---- the sandbox ------------------------------------------------------
    # One directory per checkpoint, rebuilt from scratch, and it is also the
    # child's CWD. Everything the run can reach is inside it.
    box = scratch_root / tag
    if box.exists():
        shutil.rmtree(box)          # never inherit a previous run's rows
    (box / "stores").mkdir(parents=True)

    # CONFIG IS PINNED PER CHECKPOINT, and this is not cosmetic. `load_config`
    # resolves "config.yaml" then "config.example.yaml" RELATIVE TO CWD. The
    # worktrees have no config.yaml (gitignored), but the live checkout on a
    # real machine DOES — so with cwd set to each tree, `main` would run under
    # the developer's personal settings (their location, observance flags,
    # thresholds) while the other four ran on example defaults. That is a
    # confound in the one checkpoint that matters most.
    #
    # Each checkpoint gets ITS OWN config.example.yaml copied in as
    # config.yaml: schema-compatible with that era's pydantic models (a later
    # example can carry fields older code rejects, and vice versa), and no
    # personal config can leak in. Verified 2026-09-11 that llm_engine
    # "ollama" / model "llama3.1:8b" are identical across all five examples,
    # so the sweep compares SYSTEMS, not models.
    example = tree / "config.example.yaml"
    if example.exists():
        shutil.copy(example, box / "config.yaml")

    (box / "_child.py").write_text(_CHILD)
    (box / "rows.json").write_text(json.dumps(rows))
    out_path = box / "result.json"

    # AN EXPLICIT ENVIRONMENT, not the parent's. Inheriting the caller's shell
    # is how a stray MACALENDAR_* or MACALENDAR_LLM_DISABLED from an earlier
    # experiment silently changes one checkpoint's behaviour and nothing says
    # so. Only what a run legitimately needs is passed through.
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE",
                    "OLLAMA_HOST", "VIRTUAL_ENV", "PYTHONHOME")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"    # no __pycache__ in the worktrees
    # The BLAS pin conftest.py applies for the same reason: spaCy/torch each
    # bring a threading runtime and the combination segfaults.
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[var] = "1"

    t0 = time.perf_counter()
    proc = subprocess.run(
        # The child appends "stores" itself — pass the SANDBOX, not the store
        # dir, or everything lands in <box>/stores/stores and the scorer looks
        # for a database one level above where the run wrote it.
        [sys.executable, str(box / "_child.py"), str(tree), str(box),
         str(box / "rows.json"), str(out_path)],
        cwd=str(box),           # the sandbox, NOT a source tree: pins the config
        env=env,
        capture_output=True, text=True, timeout=None)
    wall = time.perf_counter() - t0

    if not out_path.exists():
        return {"tag": tag, "error": "child wrote no result",
                "stderr": proc.stderr[-1500:], "stdout": proc.stdout[-500:]}
    out = json.loads(out_path.read_text())
    out.update({"tag": tag, "wall_s": round(wall, 1),
                "sandbox": str(box),
                "config": str(example) if example.exists() else None,
                "stderr_tail": proc.stderr[-1500:] if proc.returncode else ""})
    # WRITE THE ENRICHMENT BACK. The child knows what it ran; only the parent
    # knows how long it took and, later, what it scored — and result.json is
    # what sweep_monitor archives. Leaving the enrichment in memory meant the
    # DURABLE RECORD had no wall time and no scores, and the only copy of them
    # was the sweep-*.json the parent writes after ALL checkpoints finish: lose
    # the process and a completed checkpoint's timing was gone with it.
    _persist(out_path, out)
    return out


def _persist(out_path: pathlib.Path, out: dict) -> None:
    """result.json is the archived record — keep it current as facts arrive."""
    try:
        out_path.write_text(json.dumps(out, indent=1))
    except OSError:
        pass


#: The real stores. NOTHING here may change during a sweep — the overrides
#: redirect what a process OPENS, and a single missed one writes junk into a
#: hand-curated vocabulary or the command memory that feeds the review flows.
REAL_STORES = pathlib.Path.home() / ".assistant_tools"


def _store_fingerprint() -> dict:
    """md5 of the real DATA stores, for the before/after guard.

    ONLY the data stores. `~/.assistant_tools` also holds api.log,
    assistant.log, launch.log, heartbeats/ and model.lock, all of which change
    continuously while the live stack runs — hashing those would cry
    SANDBOX LEAK on every sweep and the guard would be ignored within a day.

    A change in one of THESE means either a genuine leak or that the assistant
    was used during the run; both are reasons to distrust the numbers, which
    is why the check reports rather than guesses.
    """
    names = ("calendar.db", "nlu_memory.db", "vocab.json", "categories.json",
             "location.json", "trace_bus.jsonl")
    out = {}
    for name in names:
        p = REAL_STORES / name
        if p.is_file():
            with contextlib.suppress(OSError):
                out[name] = hashlib.md5(p.read_bytes()).hexdigest()
    return out


def _rows_fingerprint(rows: list) -> str:
    """Identity of the exact prompt list every checkpoint was given.

    "Same data" is otherwise an assumption. This makes it a value the report
    asserts on, in the spirit of the run archives' manifest: identity is
    recorded at the time, because inferring it later already put a wrong
    figure in RESULTS.md once.
    """
    h = hashlib.md5()
    for r in rows:
        h.update(f"{r['id']}\x00{r['text']}\x00{r.get('ts')}\n".encode())
    return f"{h.hexdigest()[:12]}:{len(rows)}"


@contextlib.contextmanager
def _one_at_a_time(work: pathlib.Path):
    """Refuse to run beside another sweep.

    The checkpoints run SEQUENTIALLY by construction (a plain loop over
    blocking subprocess calls) — but two sweeps started in two terminals would
    still collide, and they would collide on the worst possible thing: one
    Ollama, one machine, two model-loading jobs side by side, which CLAUDE.md
    records as a segfault and which RAM here cannot take anyway. The lock makes
    "one at a time" enforced rather than merely intended.
    """
    lock = work / ".sweep.lock"
    work.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        raise SystemExit(
            f"A sweep is already running (lock: {lock}, pid {lock.read_text().strip()}).\n"
            "Checkpoints must run one at a time — same machine, same Ollama.\n"
            "If that process is dead, delete the lock.")
    lock.write_text(str(os.getpid()))
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def _score_personas(db_path: pathlib.Path, rows: list) -> dict:
    """Grade a personas run, mirroring score_db's predicate exactly.

    WHY NOT score_db ITSELF. It derives the expectation from a provenance
    `intent` string and its three compound buckets — event+event, task+task,
    event+task. Personas carry EXACT expectations, and 65 of the 2,520 want
    (2 events, 1 task), which no bucket expresses: forcing them into
    "event+task" would pass a row that produced one event when two were asked
    for. So the predicate is reproduced rather than the plumbing reused.

    THE PREDICATE IS THE SAME ONE: did the command create at least the events
    and tasks that were asked for. That is what makes a COMBINED number across
    the two halves honest — same question, two sources of the answer.
    """
    import sqlite3 as _sq
    expect = {r["text"]: r for r in rows}
    with _sq.connect(f"file:{db_path}?mode=ro", uri=True) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(examples)")}
        key = "COALESCE(NULLIF(raw_transcript, ''), transcript)"
        db_rows = c.execute(
            f"SELECT {key}, actions_json, parse_path, total_ms FROM examples"
        ).fetchall()

    from scripts.score_dataset_run import _GARBAGE_TITLES
    scored = []
    for text, actions_json, parse_path, total_ms in db_rows:
        want = expect.get(text)
        if want is None:
            continue
        try:
            actions = json.loads(actions_json or "[]")
        except json.JSONDecodeError:
            actions = []
        n_events = sum(1 for a in actions
                       if a.get("action", "").startswith("create_event"))
        titles = []
        for a in actions:
            if a.get("action", "").startswith("create_todo"):
                titles += [t for t in (a.get("parameters", {}).get("titles") or [])
                           if isinstance(t, str)]
        n_tasks = len(titles)
        ev_titles = [a.get("parameters", {}).get("title", "") for a in actions
                     if a.get("action", "").startswith("create_event")]
        garbage = [t for t in titles + ev_titles
                   if t.strip().lower() in _GARBAGE_TITLES]
        exp = want.get("expect") or {}
        want_e, want_t = int(exp.get("events") or 0), int(exp.get("tasks") or 0)
        if want_e == 0 and want_t == 0:
            # A query, a delete or a completion: the claim is that NOTHING was
            # created. Same reading score_db takes for query/remove — against a
            # fresh scratch DB, whether the delete found its target is not the
            # test, and "I couldn't find that" is the correct answer.
            ok = (n_events + n_tasks) == 0
        else:
            ok = n_events >= want_e and n_tasks >= want_t
        scored.append({"count_ok": ok, "garbage": bool(garbage),
                       "parse_path": parse_path, "total_ms": total_ms or 0,
                       "tier": want.get("tier"), "persona": want.get("persona")})

    def agg(rs: list) -> dict:
        n = len(rs)
        if not n:
            return {"n": 0}
        ms = sorted(r["total_ms"] for r in rs)
        return {
            "n": n,
            "count_ok_rate": sum(1 for r in rs if r["count_ok"]) / n,
            "count_ok_adj_rate": None,   # no conventions layer for personas
            "garbage_title_rate": sum(1 for r in rs if r["garbage"]) / n,
            "event_dates_collapsed_rate": None,
            "total_ms_p50": statistics.median(ms),
            "total_ms_p95": ms[min(len(ms) - 1, int(n * .95))],
            "parse_path": {p_: sum(1 for r in rs if r["parse_path"] == p_)
                           for p_ in sorted({r["parse_path"] for r in rs})},
        }

    personas = sorted({r["persona"] for r in scored})
    return {"overall": agg(scored),
            "by_complexity": {t: agg([r for r in scored if r["tier"] == t])
                              for t in ("simple", "medium", "complex")},
            "by_persona": {p_: agg([r for r in scored if r["persona"] == p_])
                           for p_ in personas},
            "by_compound_kind": {}}


def _score(result: dict, rows: "list | None" = None) -> dict:
    """Grade a checkpoint's run with TODAY's scorer.

    The whole point of the sweep: score_db opens the run DB read-only and
    grades the OUTPUT, so one scorer can grade five system states. Failures
    are recorded, never raised — a checkpoint that cannot be scored must not
    take the other four down with it.
    """
    db = result.get("engine_db")
    if not db or not pathlib.Path(db).exists():
        return {"error": "no engine_run.db — nothing was recorded"}
    try:
        sys.path.insert(0, str(ROOT))
        if rows and any(r.get("expect") for r in rows):
            return {"aggregate": _score_personas(pathlib.Path(db), rows),
                    "half": "personas"}
        from scripts import score_dataset_run as scorer
        prov = scorer.load_provenance(
            ROOT / "dataset" / "inputs" / "hwu64_sample.json")
        scored = scorer.score_db(pathlib.Path(db), prov)
    except Exception as e:
        import traceback
        return {"error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-800:]}
    # Keep the aggregates; per_prompt is large and, on a --test run, is row
    # detail the sealed-set rule says must not be reported.
    out = {k: v for k, v in scored.items() if k != "per_prompt"}
    out["half"] = "sealed"
    return out


def _pct(values: list, q: float):
    if not values:
        return None
    v = sorted(values)
    k = max(0, min(len(v) - 1, int(round(q * (len(v) - 1)))))
    return v[k]


def report(results: list) -> None:
    print("\n" + "=" * 78)
    print("CHECKPOINT SWEEP — same rows, same scorer, same machine, today")
    print("=" * 78)
    prints = {r.get("rows_fingerprint") for r in results if r.get("rows_fingerprint")}
    if len(prints) > 1:
        print(f"\n*** NOT THE SAME DATA — fingerprints differ: {prints} ***")
        print("    The comparison is void. Do not read the board below.\n")
    elif prints:
        print(f"same data across all checkpoints: {prints.pop()}")
    for r in results:
        tag = r.get("tag")
        if r.get("error"):
            print(f"\n{tag:<28} ✗ {r['error']}")
            for line in (r.get("traceback") or r.get("stderr") or "").strip().splitlines()[-6:]:
                print(f"    {line}")
            continue
        rows = r.get("rows", [])
        ok = [x for x in rows if x.get("status") == 200]
        errs = [x for x in rows if x.get("status") != 200]
        print(f"\n{tag:<28} {len(ok)}/{len(rows)} ok · wall {r.get('wall_s')}s")
        print(f"    assistant from: {r.get('assistant_from')}")
        tiers = {}
        for x in ok:
            tiers.setdefault(x.get("tier") or "?", []).append(x["ms"])
        for tier, ms in sorted(tiers.items(), key=lambda kv: str(kv[0])):
            print(f"    {str(tier):<10} n={len(ms):<4} p50 {_pct(ms,.5)}ms  p95 {_pct(ms,.95)}ms")
        paths = {}
        for x in ok:
            paths[x.get("parse")] = paths.get(x.get("parse"), 0) + 1
        if paths:
            print("    parse paths: " + ", ".join(f"{k}={v}" for k, v in sorted(
                paths.items(), key=lambda kv: str(kv[0]))))
        for x in errs[:3]:
            print(f"    ✗ row {x.get('id')}: {x.get('error') or 'HTTP ' + str(x.get('status'))}")
            body = (x.get("body") or "").strip()
            if body:
                for line in body.splitlines()[-4:]:
                    print(f"        {line[:110]}")

        sc = (r.get("scored") or {}).get("aggregate") or {}
        if (r.get("scored") or {}).get("error"):
            print(f"    scoring failed: {r['scored']['error']}")
        elif sc:
            def _pc(block, key):
                v = block.get(key)
                return "-" if v is None else f"{v * 100:.1f}"

            def _line(name, block):
                if not block or not block.get("n"):
                    return f"    {name:<12} n=0"
                return (f"    {name:<12} n={block['n']:<4} "
                        f"raw {_pc(block, 'count_ok_rate'):>5} · "
                        f"adj {_pc(block, 'count_ok_adj_rate'):>5} · "
                        f"garbage {_pc(block, 'garbage_title_rate'):>5} · "
                        f"collapse {_pc(block, 'event_dates_collapsed_rate'):>5} · "
                        f"p50 {block.get('total_ms_p50', '-')}ms "
                        f"p95 {block.get('total_ms_p95', '-')}ms")

            # Every number with the slice it describes — never one headline.
            # The scorer already breaks latency down by tier, which is the
            # comparison that matters: complex rows are both the weak tier and
            # the slow one, and only a per-tier read shows whether a checkpoint
            # bought accuracy with seconds.
            print("    " + "-" * 70)
            print(_line("OVERALL", sc.get("overall", {})))
            for tier in ("simple", "medium", "complex"):
                print(_line(tier, (sc.get("by_complexity") or {}).get(tier, {})))
            for kind in ("event+event", "task+task", "event+task"):
                blk = (sc.get("by_compound_kind") or {}).get(kind, {})
                if blk:
                    print(_line(kind, blk))
            # The SPREAD between personas is the finding, not any one row.
            for who, blk in sorted((sc.get("by_persona") or {}).items()):
                print(_line(who, blk))
            byp = sc.get("by_persona") or {}
            rates = [b["count_ok_rate"] for b in byp.values()
                     if b.get("count_ok_rate") is not None]
            if len(rates) > 1:
                print(f"    persona spread: {min(rates)*100:.1f} – "
                      f"{max(rates)*100:.1f} ({(max(rates)-min(rates))*100:.1f} pt)")
            qmv = (sc.get("overall") or {}).get("query_mutation_violations")
            if qmv:
                print(f"    query-no-mutation violations: {qmv}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--setup", action="store_true", help="create the worktrees and exit")
    ap.add_argument("--smoke", action="store_true", help="one row per checkpoint")
    ap.add_argument("--test", action="store_true", help="the SEALED 300 (milestone only)")
    ap.add_argument("--rows", type=int, help="first N rows")
    ap.add_argument("--personas", type=int, metavar="N",
                    help="N stratified rows from the personas set "
                         "(the second clean test half)")
    ap.add_argument("--checkpoints", help="comma-separated subset of tags")
    ap.add_argument("--keep", action="store_true", help="keep the sandboxes")
    ap.add_argument("--work", help="sandbox root (default: a temp dir; give a "
                                   "stable path to keep sandboxes across runs)")
    args = ap.parse_args()

    if args.setup:
        return setup()

    tags = [t for t, _ in CHECKPOINTS]
    if args.checkpoints:
        want = {s.strip() for s in args.checkpoints.split(",")}
        tags = [t for t in tags if t in want]
    rows = _load_rows(args)

    # ONE prompt list, built once, handed to every checkpoint unchanged.
    fingerprint = _rows_fingerprint(rows)
    print(f"{len(rows)} row(s) × {len(tags)} checkpoint(s), SEQUENTIALLY")
    print(f"  data fingerprint: {fingerprint}")

    scratch_root = (pathlib.Path(args.work) if args.work
                    else pathlib.Path(tempfile.mkdtemp(prefix="checkpoint_sweep_")))

    before = _store_fingerprint()
    results = []
    with _one_at_a_time(scratch_root):
        try:
            # SEQUENTIAL, deliberately. One machine, one Ollama, one model in
            # memory at a time — CLAUDE.md's "never two model-loading jobs side
            # by side". Each subprocess.run blocks until that checkpoint is
            # finished, so the next one starts from a quiet machine and its
            # latency numbers mean something.
            for i, tag in enumerate(tags, 1):
                print(f"  [{i}/{len(tags)}] {tag} …", flush=True)
                r = run_checkpoint(tag, rows, scratch_root)
                r["rows_fingerprint"] = fingerprint
                if not r.get("error"):
                    r["scored"] = _score(r, rows)
                    # Scores are computed by the parent too, so the archived
                    # result.json only carries them if written back here.
                    if r.get("sandbox"):
                        _persist(pathlib.Path(r["sandbox"]) / "result.json", r)
                results.append(r)
            report(results)
            OUT.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M")
            dest = OUT / f"sweep-{stamp}.json"
            dest.write_text(json.dumps(
                {"fingerprint": fingerprint, "sequential": True,
                 "rows": len(rows), "results": results}, indent=1))
            print(f"wrote {dest}")
        finally:
            if args.keep or args.work:
                print(f"sandboxes kept at {scratch_root}")
            else:
                shutil.rmtree(scratch_root, ignore_errors=True)

    # THE GUARD. If any real store moved, the sandbox leaked and every number
    # from this sweep is suspect — say so loudly rather than reporting a board.
    after = _store_fingerprint()
    if before != after:
        changed = sorted(set(before) ^ set(after)) or \
            sorted(k for k in before if before.get(k) != after.get(k))
        print("\n*** SANDBOX LEAK — the real stores changed during this sweep ***")
        print(f"    {REAL_STORES}: {', '.join(changed)}")
        print("    Treat this run's numbers as void and find the missed override.")
        return 2
    if before:
        print(f"sandbox clean — {len(before)} real store(s) unchanged")

    return 0 if all(not r.get("error") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
