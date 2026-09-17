"""A board that points at a moved file breaks only when you next run it.

CLAUDE.md: *"a path in an experiment or generator rots silently, and only
breaks when you next run it"* — four were found pointing at pre-restructure
locations, and the fourth turned up a month after the first three, because
**finding some of these is not finding all of them**. They all survived so long
because every one is a manual step whose OUTPUT is committed: the stale
`.jsonl` kept working while the script that makes it could not run at all.

So the finding-them part stops being manual here. Three guards:

  1. every board, generator and experiment still LOADS;
  2. no path constant inside it points at a file that is not there;
  3. nothing carries a hardcoded path to one person's laptop — two boards and
     the loop's own comparison script each had one, written as a temporary
     fallback that outlived the thing it was waiting for.

**The audit runs in a SUBPROCESS, and that is not an implementation detail.**
These modules set `MACALENDAR_*` at import time, before importing `assistant`,
because that is the only moment the personal-store paths can be redirected
(CLAUDE.md). Importing them inside pytest therefore rewrites the environment
for every test that follows: the first cut of this file did exactly that, and
`fast_sandbox`'s `MACALENDAR_OBSERVANCE=0` turned seventeen observance tests
red. One child process, one JSON report, no leakage.

`git check-ignore` is what keeps guard 2 honest: `dataset/baseline/` and
`~/.assistant_tools/` are legitimately absent in a fresh checkout, and a test
that demanded them would be switched off within a week.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Everything runnable that reads data off disk.
GLOBS = ("assistant/engine/*/experiments/*.py",
         "assistant/engine/*/eval_metrics/*.py",
         "assistant/engine/*/datasets/*.py",
         "scripts/*.py")

#: Imports that need something this repo does not require.
OPTIONAL = {"scripts.plot_loop": "matplotlib"}

#: Boards with all their work at module level — importing one RUNS it, so a
#: clean import IS a clean run, and a failure here is a board nobody can use.
RUNS_ON_IMPORT = {"assistant.engine.decompose_validate.eval_metrics.end_to_end"}


def modules() -> "list[str]":
    out = []
    for glob in GLOBS:
        for p in sorted(REPO.glob(glob)):
            if p.name != "__init__.py":
                out.append(str(p.relative_to(REPO))[:-3].replace("/", "."))
    return out


def _ignored(path) -> bool:
    """Gitignored paths may be absent — they are local by design.

    Asked BOTH ways: `.gitignore` writes a directory rule as `dataset/baseline/`
    with the trailing slash, and `check-ignore` on the bare `dataset/baseline`
    does not match it. That one character decides whether this test is useful
    or fails on every fresh clone.
    """
    return any(subprocess.run(["git", "check-ignore", "-q", p],
                              cwd=REPO).returncode == 0
               for p in (str(path), str(path) + "/"))


def audit() -> dict:
    """Import every board and stat its path constants. Runs as a CHILD."""
    import importlib

    failures, missing = [], []
    for mod in modules():
        if mod in OPTIONAL:
            try:
                importlib.import_module(OPTIONAL[mod])
            except ImportError:
                continue                     # optional dep absent: not rot
        try:
            m = importlib.import_module(mod)
        except Exception as exc:
            failures.append(f"{mod}: {type(exc).__name__}: {exc}")
            continue
        if mod in RUNS_ON_IMPORT:
            continue                         # importing it was the run

        for name in dir(m):
            if name.startswith("__"):
                continue
            value = getattr(m, name, None)
            if isinstance(value, dict):
                found = list(value.values())
            elif isinstance(value, (list, tuple, set)):
                found = list(value)
            else:
                found = [value]
            for c in found:
                # Typed Paths only: a bare str is usually a fragment, and
                # guessing which strings are paths produced false alarms.
                if not isinstance(c, pathlib.Path) or not c.is_absolute():
                    continue
                if REPO not in c.parents:
                    continue                 # a local store, not ours
                if c.exists() or _ignored(c):
                    continue
                missing.append(f"{mod}.{name} -> {c.relative_to(REPO)}")
    return {"failures": failures, "missing": missing}


def _run_audit() -> dict:
    # NO extra argv. A board that runs on import reads `sys.argv` — passing
    # "--audit" made `end_to_end` take it as a dataset split, match zero rows
    # and die dividing by zero, which read as a broken board for a while.
    done = subprocess.run([sys.executable, __file__], cwd=REPO,
                          capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, f"the audit child died:\n{done.stderr[-2000:]}"
    return json.loads(done.stdout)


def test_every_board_still_loads():
    """A module that cannot import is a board nobody can run — and for the
    ones whose work is at module level, cannot run either."""
    failures = _run_audit()["failures"]
    assert not failures, "boards that no longer load:\n  " + "\n  ".join(failures)


def test_no_board_points_at_a_file_that_is_not_there():
    """The check that would have caught all four at once.

    It walks dicts and sequences too: `kind_board` keeps its datasets in a
    dict, and a top-level-attributes-only sweep missed it.
    """
    missing = _run_audit()["missing"]
    assert not missing, (
        "boards pointing at files that are not there:\n  "
        + "\n  ".join(missing)
        + "\n\nA stage folder's datasets moved under assistant/engine/<stage>/"
          " — and mind the trap CLAUDE.md names: `parents[1]` was the repo root"
          " before that move and is the STAGE folder after it, so a path that"
          " merely looks wrong may be right and vice versa.")


def test_nothing_hardcodes_a_path_to_somebody_else_s_machine():
    """`/Users/<someone>/…` in a checked-in file resolves to nothing anywhere
    else, and says nothing when it doesn't."""
    listed = subprocess.run(["git", "ls-files", "-z", "*.py"], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout
    quoted = re.compile(r"[\"'](/Users/[^\"'\n]+|/home/(?!user\b)[^\"'\n]+)[\"']")
    comment = re.compile(r"^\s*#")
    offenders = []
    for rel in filter(None, listed.split("\0")):
        if rel.startswith("retired/"):
            continue                          # kept as it was, on purpose
        for line in (REPO / rel).read_text(encoding="utf-8",
                                           errors="replace").splitlines():
            if comment.match(line):
                continue                      # a comment naming what it warns of
            offenders += [f"{rel}: {h}" for h in quoted.findall(line)]

    assert not offenders, (
        "hardcoded absolute paths to a specific machine:\n  "
        + "\n  ".join(offenders))


if __name__ == "__main__":            # the child: import everything, report JSON
    import contextlib
    import io
    import os

    # Run by PATH, so sys.path[0] is tests/unit/, not the repo — and with the
    # repo absent, `assistant` resolves through the venv's editable install to
    # whichever checkout was `pip install -e`'d. In a WORKTREE that is the
    # OTHER checkout: every board loaded from there, the first of the thirteen
    # that `sys.path.insert(0, _ROOT)` put THAT root first, and `scripts.*`
    # followed it. The audit then reported the neighbouring branch's rot as
    # this one's — found 2026-09-17 when main's copy of a generator "went
    # missing" that had only been moved on the other branch. This checkout
    # goes first, ahead of the editable finder.
    sys.path.insert(0, str(REPO))

    # A board whose work is at module level PRINTS that work as it imports, so
    # the report has to be the only thing on stdout. Their output is swallowed;
    # a traceback still reaches stderr, where the parent shows it.
    _noise = io.StringIO()
    with contextlib.redirect_stdout(_noise):
        _report = audit()
    os.write(1, (json.dumps(_report) + "\n").encode())
