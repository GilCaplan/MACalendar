"""Move today's single-user data into the admin's folder — and back.

    python -m scripts.migrate_users --dry-run
    python -m scripts.migrate_users --apply --admin gil          # asks for a password
    python -m scripts.migrate_users --rollback

Before this, every personal store sits at the top of `~/.assistant_tools`.
After it, the same files sit in `~/.assistant_tools/users/<admin>/`, the
registry names one admin (Gil), and — because `policy.require_login` is false
— every process nobody logged into acts as that admin, so the assistant reads
exactly the data it read before, from its new place.

The order is the safety:
  1. refuse while the calendar window, the API or the HUD is running — a
     window that does not reload would go on writing the OLD path;
  2. refuse if `users.json` already exists (migrated already);
  3. copy the WHOLE directory to `<dir>.backup-<ts>` first;
  4. snapshot what is there (row counts of every table, md5 of every file);
  5. write the registry with the admin, then MOVE each personal file (a rename
     on one filesystem: atomic per file);
  6. snapshot the moved files and compare — any difference rolls back on the
     spot and exits non-zero;
  7. write `users/<admin>/MIGRATED.json` (when, what, the backup's path).

Rollback refuses once another user or a share exists: moving the admin's files
back would orphan theirs.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time

from assistant.users import paths, registry

#: The personal stores, by file name, relative to the store directory. SQLite
#: sidecars ride with their database.
PERSONAL = ["calendar.db", "nlu_memory.db", "vocab.json", "categories.json",
            "lexicon.json", "label_feedback.jsonl", "models", "trace_bus.jsonl",
            "llm_calls.jsonl", "observance_exceptions.json", "google_token.json",
            "msal_token_cache.json"]
_SIDECARS = ("-wal", "-shm", "-journal")
#: What the running stack looks like to `pgrep -f` (the launcher's patterns).
_STACK = ("-m assistant\\.main( |$)", "assistant\\.api", "assistant\\.thinking_hud")


class MigrationError(RuntimeError):
    pass


def _files(root: str) -> list[str]:
    out = []
    for name in PERSONAL:
        for n in [name] + ([name + s for s in _SIDECARS] if name.endswith(".db") else []):
            if os.path.exists(os.path.join(root, n)):
                out.append(n)
    return out


def _md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(base: str) -> dict:
    """What a store directory holds, in a form two moments can be compared by:
    per-table row counts for the databases, md5 for everything else."""
    snap: dict = {}
    for name in _files(base):
        p = os.path.join(base, name)
        if os.path.isdir(p):
            snap[name] = {os.path.relpath(os.path.join(d, f), p): _md5(os.path.join(d, f))
                          for d, _, fs in os.walk(p) for f in fs}
        elif name.endswith(".db"):
            with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as c:
                tables = [r[0] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                snap[name] = {t: c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                              for t in sorted(tables)}
        elif not name.endswith(_SIDECARS):
            snap[name] = _md5(p)
    return snap


def stack_running() -> list[str]:
    """Which parts of the assistant are running — the migration waits for none."""
    alive = []
    for pat in _STACK:
        r = subprocess.run(["pgrep", "-f", "--", pat], capture_output=True, text=True)
        if r.stdout.strip():
            alive.append(pat)
    return alive


def plan(root: "str | None" = None) -> dict:
    """What `apply` would do, touching nothing."""
    root = root or paths.root()
    return {"root": root, "already_migrated": registry.exists(),
            "move": _files(root),
            "legacy": sorted(n for n in os.listdir(root) if ".bak" in n or ".backup" in n)
            if os.path.isdir(root) else [],
            "stack_running": stack_running()}


def apply(admin_username: str, password: str, display_name: str = "",
          check_stack: bool = True) -> dict:
    root = paths.root()
    if registry.exists():
        raise MigrationError(f"already migrated: {paths.registry_path()} exists")
    if check_stack:
        alive = stack_running()
        if alive:
            raise MigrationError("quit the calendar window, the API and the HUD first "
                                 f"(still running: {', '.join(alive)})")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{root.rstrip(os.sep)}.backup-{stamp}"
    shutil.copytree(root, backup, symlinks=True)
    before = snapshot(root)

    uid = registry.create_user(admin_username, password, display_name=display_name,
                               role="admin")
    dest = paths.user_dir(uid)
    moved: list[str] = []
    try:
        for name in _files(root):
            os.rename(os.path.join(root, name), os.path.join(dest, name))
            moved.append(name)
        legacy = os.path.join(root, "legacy")
        for n in sorted(os.listdir(root)):
            if (".bak" in n or ".backup" in n) and os.path.isfile(os.path.join(root, n)):
                os.makedirs(legacy, exist_ok=True)
                os.rename(os.path.join(root, n), os.path.join(legacy, n))
        after = snapshot(dest)
        if after != before:
            diff = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            raise MigrationError(f"moved data does not match what was there: {diff}")
    except BaseException:
        _undo(root, dest, moved)
        raise
    record = {"migrated_at": time.time(), "admin": uid, "backup": backup,
              "moved": moved, "snapshot": before}
    with open(os.path.join(dest, "MIGRATED.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return record


def _undo(root: str, dest: str, moved: list[str]) -> None:
    for name in reversed(moved):
        src = os.path.join(dest, name)
        if os.path.exists(src):
            os.rename(src, os.path.join(root, name))
    for f in (paths.registry_path(),):
        if os.path.exists(f):
            os.remove(f)
    shutil.rmtree(os.path.join(root, "users"), ignore_errors=True)


def rollback(check_stack: bool = True) -> list[str]:
    """Put the admin's files back where they were before `apply`."""
    root = paths.root()
    if not registry.exists():
        raise MigrationError("not migrated: there is no user registry")
    if check_stack:
        alive = stack_running()
        if alive:
            raise MigrationError(f"quit the running assistant first ({', '.join(alive)})")
    data = registry.load()
    if len(data["users"]) > 1 or data["shares"]:
        raise MigrationError("other users or shares exist — their data would be orphaned")
    uid = registry.admin_id(data)
    dest = paths.user_dir(uid)
    back = []
    for name in _files(dest):
        target = os.path.join(root, name)
        if os.path.exists(target):
            raise MigrationError(f"{target} exists — refusing to overwrite it")
        os.rename(os.path.join(dest, name), target)
        back.append(name)
    legacy = os.path.join(root, "legacy")
    if os.path.isdir(legacy):
        for n in os.listdir(legacy):
            os.rename(os.path.join(legacy, n), os.path.join(root, n))
        os.rmdir(legacy)
    for var, default in (("MACALENDAR_SESSIONS", "sessions.json"),
                         ("MACALENDAR_SESSION_FILE", "session.json")):
        p = os.environ.get(var) or os.path.join(root, default)
        if os.path.exists(p):
            os.remove(p)
    os.remove(paths.registry_path())
    shutil.rmtree(os.path.join(root, "users"), ignore_errors=True)
    return back
