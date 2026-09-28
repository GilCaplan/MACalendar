"""Where a user's stores live: `<root>/users/<uid>/<the same file name>`.

`root()` is the directory holding `users.json` (`MACALENDAR_USERS`), so the
scratch redirect `tests/conftest.py` already applies covers every per-user
store too: a test's users live under the test's scratch directory, never under
the real `~/.assistant_tools`.

`resolve(path)` is the whole mechanism. Every personal store keeps its module
constant (tests monkeypatch those, and an unbound process must read exactly
what it always read) and passes it through here at the moment of use:

    no user bound   -> `path`, unchanged
    user bound      -> `user_dir(uid) / basename(path)`

Same type out as in (`str` or `pathlib.Path`), so call sites do not change
shape.
"""
from __future__ import annotations

import os
import pathlib
from typing import TypeVar

P = TypeVar("P", str, pathlib.Path)

DEFAULT_REGISTRY = os.path.expanduser("~/.assistant_tools/users.json")


def registry_path() -> str:
    return os.environ.get("MACALENDAR_USERS") or DEFAULT_REGISTRY


def root() -> str:
    return os.path.dirname(os.path.abspath(registry_path()))


def user_dir(user_id: str) -> str:
    if not user_id or "/" in user_id or user_id.startswith("."):
        raise ValueError(f"not a user id: {user_id!r}")
    return os.path.join(root(), "users", user_id)


def resolve(path: P, user_id: "str | None" = None) -> P:
    """`path` for the bound user (or `user_id`), unchanged when there is none."""
    if user_id is None:
        from assistant import users
        user_id = users.current()
    if not user_id:
        return path
    target = os.path.join(user_dir(user_id), os.path.basename(str(path).rstrip("/")))
    return pathlib.Path(target) if isinstance(path, pathlib.Path) else target


REAL_ROOT = os.path.expanduser("~/.assistant_tools")


def personal_store(name: str, root: str = REAL_ROOT) -> str:
    """Where the ADMIN's real copy of a store is, for a script or board that
    reads the user's own data on purpose (the real-usage board, the audit's
    history replay, the label experiments). Before the users migration that is
    `<root>/<name>`; after it, `<root>/users/<admin>/<name>`.

    Reads `users.json` directly and read-only — not through `registry`, whose
    test guard would refuse the real file — because these callers want the
    REAL tree by definition (they already refuse to write to it)."""
    import json
    reg = os.path.join(root, "users.json")
    try:
        with open(reg, encoding="utf-8") as f:
            data = json.load(f)
        admin = next(uid for uid, u in data.get("users", {}).items()
                     if u.get("role") == "admin")
        return os.path.join(root, "users", admin, name)
    except (OSError, ValueError, StopIteration):
        return os.path.join(root, name)
