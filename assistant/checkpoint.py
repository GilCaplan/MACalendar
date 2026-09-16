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

_REPO_DIR = pathlib.Path(__file__).resolve().parent


def _git_head() -> "str | None":
    """The commit this process's code is actually running, or None outside a
    git checkout. Best-effort: a checkpoint must work in a stray sandbox with
    no `git` on PATH exactly as well as it does in the repo."""
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5, cwd=_REPO_DIR)
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        return None


def _git_dirty() -> "bool | None":
    """Whether the working tree differs from HEAD, or None if that can't be
    answered. A dirty tree means even a HEAD match doesn't prove the code
    that produced this checkpoint is the code running now."""
    try:
        import subprocess
        out = subprocess.run(["git", "diff", "--quiet", "HEAD"],
                             capture_output=True, timeout=5, cwd=_REPO_DIR)
        return out.returncode != 0 if out.returncode in (0, 1) else None
    except Exception:
        return None


class Checkpoint:
    """One long run's completed units, on disk, resumable."""

    def __init__(self, name: str, total: "int | None" = None, every: int = 25,
                 resume: bool = True) -> None:
        self.name = name
        self.total = total
        self.every = max(1, every)
        self.path = CHECKPOINT_DIR / f"{name}.jsonl"
        self._done: dict = {}
        self._meta: "dict | None" = None
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

        # THE STAMP, AND THE CHECK IT EXISTS FOR. `has()`/`get()` are a bare id
        # lookup with no idea what CODE produced the cached row — a checkpoint
        # from before a code change reads back as an ordinary cache hit
        # (`board_d_overnight.jsonl`, scored 2026-09-15 against the FastRule
        # module a same-day merge had already retired). A mismatch does not
        # refuse the resume — this project flags, it does not block — but it
        # must not be possible to miss.
        head = _git_head()
        if self._meta is not None:
            prior = self._meta.get("git_head")
            if prior and head and prior != head:
                print(f"  [checkpoint] WARNING — {name} was recorded at "
                      f"commit {prior[:10]}, HEAD is now {head[:10]}. These "
                      f"cached rows may describe code that no longer exists. "
                      f"Resume only if you have checked the diff between "
                      f"them; --fresh to discard and start over.")
        elif not self._done and head is not None:
            # A genuinely new checkpoint (nothing loaded — no prior run, no
            # pre-stamp era file to leave alone) gets the stamp so the NEXT
            # resume, whenever that is, can make this check.
            self._write_meta({"git_head": head, "git_dirty": _git_dirty()})

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
                    elif "git_head" in row and self._meta is None:
                        # The stamp line, if this file has one — always
                        # written first, but found wherever it is rather than
                        # assumed to be line 1, since old-format files being
                        # read by new code have no such promise.
                        self._meta = row
        except OSError:
            pass

    def _write_meta(self, meta: dict) -> None:
        if self._fh is None:
            return
        try:
            self._fh.write(json.dumps(meta) + "\n")
            self._fh.flush()
            os.fsync(self._fh.fileno())
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
