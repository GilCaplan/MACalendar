"""The repo is public: no tracked file may hold a path into one person's machine.

A home-folder path (`/Users/<name>/…`, `/home/<name>/…`) committed into a
setting, a log or a comment leaks who and where, and as CODE it resolves to
nothing on any other machine and says nothing about it. Found 2026-10-11 in
`.claude/settings.json`, three committed sweep logs and a script comment.
Write `~`, a placeholder like `<projects>/`, or resolve the path at run time
(`Path(__file__)`, `Path.home()`, an env override). The real per-user store
ids on this machine are personal for the same reason (checked where they exist;
CI has none, so there it is the path check alone).

`test_no_path_rot` already refuses QUOTED paths in `.py` code; this one reads
every tracked text file, comments and logs included — the 2026-10-11 leaks were
a settings file, logs and a comment, none of which that guard looks at.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Placeholders a doc may use on purpose.
_ALLOWED_NAMES = {"you", "me", "user", "username", "name", "runner", "shared",
                  "<name>", "<someone>", "$user"}
# Not after a word character or a dot, so a URL like hebcal.com/home/1663/ is not a path.
_HOME = re.compile(r"(?<![\w.])(?:/Users|/home)/([A-Za-z0-9._$<>-]+)/")
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".icns", ".ico", ".pdf", ".zip", ".db",
                  ".sqlite", ".ttf", ".otf", ".woff", ".woff2", ".mp3", ".wav", ".m4a"}


def _tracked() -> "list[pathlib.Path]":
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [ROOT / p for p in out.decode().split("\0") if p]


def _real_user_ids() -> "set[str]":
    users = pathlib.Path.home() / ".assistant_tools" / "users"
    return {p.name for p in users.iterdir() if p.is_dir()} if users.is_dir() else set()


def test_no_home_folder_paths_or_user_ids_are_committed():
    ids = _real_user_ids()
    bad = []
    for path in _tracked():
        if path.suffix.lower() in _SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT)
        for n, line in enumerate(text.splitlines(), 1):
            for m in _HOME.finditer(line):
                if m.group(1).lower() not in _ALLOWED_NAMES:
                    bad.append(f"{rel}:{n}: {m.group(0)}")
            bad += [f"{rel}:{n}: this machine's user id {u}" for u in ids if u in line]
    assert not bad, "personal paths committed:\n" + "\n".join(bad[:40])
