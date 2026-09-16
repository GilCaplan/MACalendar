"""Personal data has leaked into git history once already — never again,
silently or otherwise.

`DOCUMENTATION/NLU_TRACKING.md` (every voice transcript, auto-appended) was
tracked and pushed to this project's PUBLIC GitHub repo before anyone added
it to `.gitignore` (2026-09-15 audit): five commits, friends' names, personal
schedule detail, all still live in history on every branch. Ruled acceptable
to leave as historical rather than rewrite a public repo's shared history —
but the SAME class of miss was found a second time in the same sitting:
`DOCUMENTATION/WEEKLY_REVIEW.md` (`scripts/weekly_review.py`'s own
recommended `--out` path) was not gitignored AT ALL and was tracked, right
now, with real names and personal context quoted directly in its "Marked
wrong / corrected" section.

This test is the guard: every file this project's own code auto-writes real
transcripts into must be BOTH gitignored and untracked, checked against the
real repo rather than a synthetic fixture — the same property `test_offline.py`
tests for network calls, and for the same reason: a rule that is not enforced
holds only until someone doesn't notice it broke.

Nothing here reads a byte of any file's CONTENT — only whether the path is
ignored and whether git currently tracks it — so this test cannot itself
leak anything, in local output or in CI logs.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Every repo-relative path this project's own code auto-writes real user
#: transcripts into. Keep this in sync with `assistant/pipeline.py`'s
#: `_append_nlu_log` / `_append_scenario_bug` hardcoded paths and
#: `scripts/weekly_review.py`'s documented `--out` default — a new one of
#: these that isn't added here is exactly the miss this test exists to catch.
PERSONAL_DATA_PATHS = (
    "DOCUMENTATION/NLU_TRACKING.md",
    "DOCUMENTATION/SCENARIO_BUG.md",
    "DOCUMENTATION/WEEKLY_REVIEW.md",
)


def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=_REPO_ROOT,
                          capture_output=True, text=True, timeout=10)


@pytest.fixture(scope="module")
def in_git_repo():
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout — nothing to check")


@pytest.mark.parametrize("path", PERSONAL_DATA_PATHS)
def test_personal_data_path_is_gitignored(in_git_repo, path):
    result = _git("check-ignore", "-q", path)
    assert result.returncode == 0, (
        f"{path} is NOT in .gitignore — a file this project auto-writes real "
        f"voice transcripts into must be ignored before it is ever created, "
        f"not after someone notices it got committed.")


@pytest.mark.parametrize("path", PERSONAL_DATA_PATHS)
def test_personal_data_path_is_not_tracked(in_git_repo, path):
    tracked = _git("ls-files", "--error-unmatch", path)
    assert tracked.returncode != 0, (
        f"{path} is TRACKED BY GIT RIGHT NOW. This project's repo is public "
        f"on GitHub — committing this file publishes whatever real transcript "
        f"content it holds. Run `git rm --cached {path}` (the file itself is "
        f"untouched on disk) and confirm it's in .gitignore before committing "
        f"anything else.")
