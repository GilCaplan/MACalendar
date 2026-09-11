"""Long runs must show progress and survive dying. Both, or neither counts.

    ck = Checkpoint("board_d", total=8000)
    for key, work in jobs:
        if ck.has(key):
            continue                      # done in an earlier attempt
        ck.record(key, run(work))
    ck.finish()

## Why this exists (Gil, 2026-09-10)

Board D ran for three and a half hours and printed NOTHING until the end. Two
things went wrong with that, and the second is the expensive one:

1. **Progress was unobservable.** `ps` said the process was alive at 0.0% CPU,
   which is what a slow ollama call looks like AND what a hang looks like. There
   was no way to tell them apart, so "is it working?" could not be answered —
   only guessed at from the rate its stderr happened to grow.
2. **A crash at 90% would have cost the whole run.** Three hours of model calls,
   nothing on disk, nothing to resume from. Board D also runs one ARM fully
   before starting the other, so dying late would not even have left a usable
   half.

A measurement you cannot watch and cannot resume is a measurement you will be
reluctant to run — which is how a board ends up never having been run at all,
which is exactly what Board D's own docstring said about itself for two days.

## What it guarantees

* **Every completed unit is on disk before the next one starts.** Appended and
  flushed per line, so `kill -9` loses at most the row in flight.
* **Re-running resumes.** `has()` is answered from the file, so an interrupted
  run picks up where it stopped instead of redoing hours of model calls.
* **Progress is visible without reading the code.** A line every `every` units
  with a rate and an ETA, so "is it working?" is answered by looking.

## What it deliberately does NOT do

No locking, no concurrent writers: one run, one file. Two runs of the same
experiment want two names, because merging their rows would silently mix two
configurations into one board — the same reason a stage's dataset is never
edited to suit another stage.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

#: THE REAL CLOCK — the one `freezegun` cannot reach.
#:
#: Every board here runs inside `freeze_time(CLOCK)` so that a case depending on
#: "the day after tomorrow" resolves identically every run. freezegun patches
#: far more than `time.time`: `monotonic`, `perf_counter` and `datetime` all
#: return the frozen instant, and **binding the function object at import does
#: not escape it** — the first attempt at this fix did exactly that and the
#: meter still read "eta 1249741750m · 0/min · 29814215m elapsed", because
#: `monotonic()` was handing back epoch-scale seconds from the frozen date while
#: the start time was a real boot-relative one.
#:
#: `time.clock_gettime(CLOCK_MONOTONIC)` goes straight to the OS and is
#: unpatched (measured, not assumed). Wall-clock progress belongs to the
#: operator watching a five-hour run, and must not be subject to the
#: experiment's own reproducibility fiction.
def _now() -> float:
    try:
        return time.clock_gettime(time.CLOCK_MONOTONIC)
    except (AttributeError, OSError):       # not POSIX
        return time.monotonic()

#: Run artefacts, not personal data and not repo content — they are the
#: by-product of a measurement and belong beside the other things this project
#: keeps outside the tree. Overridable like every other store; `conftest.py`
#: points it at scratch so a suite never resumes a real run.
CHECKPOINT_DIR = pathlib.Path(
    os.environ.get("MACALENDAR_CHECKPOINTS")
    or (pathlib.Path.home() / ".assistant_tools" / "checkpoints"))


class Checkpoint:
    """One long run's completed units, on disk, resumable."""

    def __init__(self, name: str, total: "int | None" = None, every: int = 25,
                 resume: bool = True) -> None:
        self.name = name
        self.total = total
        self.every = max(1, every)
        self.path = CHECKPOINT_DIR / f"{name}.jsonl"
        self._done: dict = {}
        self._t0 = _now()
        self._since_print = 0
        self._fh = None

        if not resume:
            try:
                self.path.unlink()
            except OSError:
                pass
        self._load()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")
        except OSError:
            # A checkpoint that cannot be written must not stop the run — the
            # measurement is the point and this is bookkeeping. It degrades to
            # the old behaviour, loudly.
            print(f"  [checkpoint] cannot write {self.path} — running without one")
        #: Units reclaimed from disk. They cost no time THIS run, so counting
        #: them in the rate makes a resumed job look enormously fast and hands
        #: back an ETA far shorter than the truth — Board D resumed 111 rows and
        #: reported "eta 27m" for what was really a three-hour run. An ETA you
        #: cannot trust is worse than none, because you plan around it.
        self._resumed = len(self._done)
        if self._done:
            print(f"  [checkpoint] resuming {name}: {self._resumed} unit(s) "
                  f"already done")

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        # A TORN LAST LINE is expected, not corruption: the
                        # process died mid-write. Everything before it is good,
                        # which is the whole point of appending one unit at a
                        # time.
                        continue
                    if "k" in row:
                        self._done[row["k"]] = row.get("v")
        except OSError:
            pass

    def has(self, key: str) -> bool:
        return str(key) in self._done

    def get(self, key: str):
        return self._done.get(str(key))

    def record(self, key: str, value=None) -> None:
        """One unit finished. On disk before the next one starts."""
        k = str(key)
        self._done[k] = value
        if self._fh is not None:
            try:
                self._fh.write(json.dumps({"k": k, "v": value}) + "\n")
                self._fh.flush()
                os.fsync(self._fh.fileno())
            except OSError:
                pass
        self._since_print += 1
        if self._since_print >= self.every:
            self._since_print = 0
            self.progress()

    def progress(self) -> None:
        n = len(self._done)
        did = n - self._resumed            # work actually done THIS run
        el = max(_now() - self._t0, 1e-6)
        rate = did / el
        line = f"  [{self.name}] {n}"
        if self.total:
            line += f"/{self.total} ({100.0 * n / self.total:.0f}%)"
            if rate > 0:
                line += f" · eta {((self.total - n) / rate) / 60:.0f}m"
        if self._resumed:
            line += f" · {self._resumed} resumed"
        line += f" · {rate*60:.0f}/min · {el/60:.0f}m elapsed"
        print(line, flush=True)

    def finish(self) -> None:
        self.progress()
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    @property
    def results(self) -> dict:
        return dict(self._done)
