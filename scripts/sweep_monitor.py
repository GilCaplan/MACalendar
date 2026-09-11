"""Watch a checkpoint sweep and ARCHIVE it as it goes.

    python -m scripts.sweep_monitor --work <sandbox root> [--once]

WHY. A sweep is ~30 hours of machine across two boards, and its sandboxes live
under the session scratchpad on /private/tmp — session-scoped, on a volume the
OS cleans. Losing that is losing the run, and a run that has to be repeated is
a run nobody repeats. DATASET.md already says it for the loop's own archives:
"treat dataset/runs/ as part of the machine, not cache."

So this snapshots each checkpoint's databases into dataset/runs/ while the
sweep is still running, and records IDENTITY beside them — the same reason
archive_run.py stamps a manifest at archive time rather than inferring it
later, which had already put a wrong figure in RESULTS.md once.

Safe to run beside the sweep: it only reads databases and writes files. No
model, no spaCy — the one thing that must never run beside a measurement.

A live SQLite file cannot be copied with `cp` — the copy can land mid-write
and come back malformed. `.backup` takes a consistent snapshot of an open
database, which is what makes an in-flight checkpoint archivable at all.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sqlite3
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = ROOT / "dataset" / "runs"


def _md5(p: pathlib.Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot(src: pathlib.Path, dst: pathlib.Path) -> "int | None":
    """Consistent copy of a possibly-live SQLite db. Returns the row count."""
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s:
            dst.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(dst) as d:
                s.backup(d)
        with sqlite3.connect(f"file:{dst}?mode=ro", uri=True) as c:
            return c.execute("SELECT COUNT(*) FROM examples").fetchone()[0]
    except sqlite3.Error:
        return None


def sweep_once(work: pathlib.Path, archive: pathlib.Path) -> dict:
    archive.mkdir(parents=True, exist_ok=True)
    state = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "checkpoints": {}}
    for box in sorted(p for p in work.iterdir() if p.is_dir()):
        tag = box.name
        dest = archive / tag
        entry: dict = {"done": (box / "result.json").exists()}
        db = box / "stores" / "engine_run.db"
        if db.exists():
            n = _snapshot(db, dest / "engine_run.db")
            entry["rows"] = n
            if n is not None:
                entry["md5"] = _md5(dest / "engine_run.db")
        cal = box / "stores" / "calendar.db"
        if cal.exists():
            _snapshot(cal, dest / "calendar.db")
        for name in ("result.json", "rows.json", "config.yaml"):
            f = box / name
            if f.exists():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest / name)
        state["checkpoints"][tag] = entry
    (archive / "manifest.json").write_text(json.dumps(state, indent=1))
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True, help="the sweep's sandbox root")
    ap.add_argument("--archive", help="destination (default: dataset/runs/<work name>)")
    ap.add_argument("--interval", type=int, default=600, help="seconds between snapshots")
    ap.add_argument("--once", action="store_true", help="snapshot once and exit")
    args = ap.parse_args()

    work = pathlib.Path(args.work)
    archive = pathlib.Path(args.archive) if args.archive else \
        ARCHIVE_ROOT / f"checkpoint-sweep-{work.name}"

    while True:
        state = sweep_once(work, archive)
        done = sum(1 for e in state["checkpoints"].values() if e["done"])
        line = " · ".join(
            f"{t}:{e.get('rows', '?')}{'✓' if e['done'] else ''}"
            for t, e in state["checkpoints"].items())
        print(f"[{state['checked_at']}] {done}/{len(state['checkpoints'])} done · {line}",
              flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
