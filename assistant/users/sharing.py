"""Whose rows a viewer sees, who may change them, and how their ids stay apart.

DEVQA Q65 (2026-09-28): a user shares their WHOLE calendar and to-dos with a
person, VIEW or EDIT; the admin sees and edits everything, and puts a user's
calendar into his own view with a toggle that is off until he turns it on.

**Ids.** Each user's calendar is its own SQLite file, so two people both have
an event 7. Rows the viewer does NOT own are published with
`(owner.seq << 32) | row_id`; the viewer's OWN rows keep their raw ids, so a
single-user install — and every client model that treats `id` as identity —
is unchanged. JSON integers up to 2**53 round-trip through Swift's `Int` and
Python's `int`; seq < 2**21 leaves that headroom.

**Acting as the owner.** A read or write by id runs under `users.bind(owner)`
(`as_owner`), so everything the write sets off lands in the OWNER's stores —
the auto-label reads their categories, and an edit to a voice-created row
records its feedback in their command memory, not the editor's.

**The engine never reads through here.** A voice command acts on the
speaker's own calendar only (`get_db()` under their binding): a spoken
"delete the meeting" can never reach a row someone shared, even with edit.

Before the users migration (no registry) every function is a pass-through, so
the routes behave exactly as they did.
"""
from __future__ import annotations

import contextlib
from typing import Any, Callable, Iterable

from assistant import users
from assistant.users import registry

SHIFT = 32
_ROW_MASK = (1 << SHIFT) - 1
#: Fields that hold another row's id IN THE SAME FILE — namespaced with the row.
ID_FIELDS = ("id", "series_id", "linked_event_id", "linked_todo_id", "event_id", "todo_id")


def _get_db():
    """The calendar accessor the ROUTES use: `server.get_db` when the API is
    loaded (a test swaps it for a fixture DB, and the features' own routes go
    through it for that reason), else `assistant.db.get_db` (the Mac window)."""
    import sys
    server = sys.modules.get("assistant.api.server")
    if server is not None:
        return server.get_db()
    from assistant.db import get_db
    return get_db()


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


def active() -> bool:
    """Are there users? (No registry: every function here passes through.)"""
    return registry.exists() and users.current() is not None


def visible_owners(viewer: str) -> list[str]:
    """The viewer's own calendar, then everyone who shares with them — or,
    for the admin, everyone his "show in my calendar" switch says: it covers
    people sharing with him too (on until he turns it off), so it is the one
    control over whose calendars fill his views."""
    out = [viewer]
    me = registry.get(viewer) or {}
    if me.get("role") == "admin":
        for uid in registry.user_ids():
            if uid != viewer and registry.admin_shows(viewer, uid):
                out.append(uid)
    else:
        for s in registry.shares_in(viewer):
            if s["owner"] not in out:
                out.append(s["owner"])
    active_ids = set(registry.user_ids())
    return [o for o in out if o == viewer or o in active_ids]


def can_view(viewer: str, owner: str) -> bool:
    if viewer == owner:
        return True
    if (registry.get(viewer) or {}).get("role") == "admin":
        return True
    return registry.share_level(owner, viewer) is not None


def can_edit(viewer: str, owner: str) -> bool:
    if viewer == owner:
        return True
    if (registry.get(viewer) or {}).get("role") == "admin":
        return True
    return registry.share_level(owner, viewer) == "edit"


def _seq(uid: str) -> int:
    return int(registry.load()["users"][uid]["seq"])


def encode(row_id: "int | None", owner: str, viewer: str) -> "int | None":
    if row_id in (None, "") or owner == viewer:
        return row_id
    return (_seq(owner) << SHIFT) | (int(row_id) & _ROW_MASK)


def decode(any_id: int) -> "tuple[str | None, int]":
    """(owner, row id) — owner None for a plain id, which is the viewer's own."""
    any_id = int(any_id)
    if any_id <= _ROW_MASK:
        return None, any_id
    seq = any_id >> SHIFT
    for uid, u in registry.load()["users"].items():
        if int(u.get("seq", 0)) == seq:
            return uid, any_id & _ROW_MASK
    raise NotFound(f"no user owns id {any_id}")


def decorate(row: dict, owner: str, viewer: str) -> dict:
    """A row as the viewer receives it: who owns it, may they change it, and —
    for a row that is not theirs — namespaced ids. The row keeps its OWN colour
    (its category's); the owner's travels as `owner_color` and the views draw
    it as the card's edge (Gil, 2026-09-28 — a stack of one person's events in
    one colour read as a single block)."""
    r = dict(row)
    u = registry.get(owner) or {}
    shared = owner != viewer
    r.update(owner_id=owner, owner_name=u.get("display_name", ""),
             owner_color=u.get("color", ""), shared=shared,
             can_edit=can_edit(viewer, owner))
    if shared:
        for k in ID_FIELDS:
            if r.get(k) not in (None, "", 0):
                r[k] = encode(r[k], owner, viewer)
    return r


def gather(fetch: Callable[[Any], Iterable[dict]],
           sort_key: "Callable[[dict], Any] | None" = None) -> list[dict]:
    """`fetch(db)` over every calendar the viewer can see, merged."""
    if not active():
        return list(fetch(_get_db()))
    viewer = users.current()
    out: list[dict] = []
    for owner in visible_owners(viewer):
        with users.bind(owner):
            rows = list(fetch(_get_db()))
        out.extend(decorate(r, owner, viewer) for r in rows)
    if sort_key is not None:
        out.sort(key=sort_key)
    return out


def event_order(r: dict):
    return (str(r.get("date") or ""), str(r.get("start_time") or ""), str(r.get("title") or ""))


@contextlib.contextmanager
def as_owner(any_id: int, edit: bool = False):
    """(db, row_id, owner) for a request about one row, run AS its owner.

    Raises NotFound for an id that names nobody or someone the viewer may not
    see (a 404, not a 403: whether someone's row exists is not the viewer's
    business), Forbidden for a change the viewer may only look at."""
    if not active():
        yield _get_db(), int(any_id), None
        return
    viewer = users.current()
    owner, rid = decode(any_id)
    owner = owner or viewer
    if not can_view(viewer, owner):
        raise NotFound("not found")
    if edit and not can_edit(viewer, owner):
        raise Forbidden("shared with you to view only")
    with users.bind(owner):
        yield _get_db(), rid, owner


@contextlib.contextmanager
def creating_for(owner_id: "str | None"):
    """Create into `owner_id`'s calendar (the event editor's owner picker), or
    the viewer's own when none is named."""
    viewer = users.current()
    if not owner_id or not active() or owner_id == viewer:
        yield viewer
        return
    if registry.get(owner_id) is None:
        raise NotFound("no such user")
    if not can_edit(viewer, owner_id):
        raise Forbidden("you can't add to that calendar")
    try:                                   # so public_id() knows who is looking
        from flask import g, has_request_context
        if has_request_context():
            g.sharing_viewer = viewer
    except ImportError:
        pass
    with users.bind(owner_id):
        yield owner_id


def change_token_parts() -> list[str]:
    """What `/changes` should hash: every file the viewer can see, plus the
    registry (a new share changes what is visible)."""
    import os
    from assistant.users import paths
    from assistant.db import DB_PATH
    if not active():
        return []
    parts = []
    viewer = users.current()
    for owner in visible_owners(viewer):
        p = paths.resolve(os.environ.get("MACALENDAR_DB") or DB_PATH, owner)
        try:
            st = os.stat(p)
            parts.append(f"{st.st_mtime:.6f}-{st.st_size}")
        except OSError:
            parts.append("0")
    try:
        parts.append(f"{os.stat(paths.registry_path()).st_mtime:.6f}")
    except OSError:
        pass
    return parts


# ------------------------------------------------------------------ in a request
# The routes' way in: one call at the top of a by-id route binds the OWNER for
# the rest of the request (so the route's body stays as it was — `db.update_…`
# on the row id), and `present` turns rows back into the viewer's id space on
# the way out. The binding is undone by users.routes' teardown.

def _viewer() -> "str | None":
    from flask import g
    return getattr(g, "sharing_viewer", None) or users.current()


def for_request(any_id: int, edit: bool = False):
    """(db, row id) for the row `any_id` names, with its owner bound for the
    rest of this request. Raises NotFound / Forbidden (404 / 403)."""
    from flask import g
    if not active():
        return _get_db(), int(any_id)
    viewer = users.current()
    owner, rid = decode(any_id)
    owner = owner or viewer
    if not can_view(viewer, owner):
        raise NotFound("not found")
    if edit and not can_edit(viewer, owner):
        raise Forbidden("shared with you to view only")
    g.sharing_viewer = viewer
    g.sharing_tokens = getattr(g, "sharing_tokens", []) + [users._current.set(owner)]
    return _get_db(), rid


def same_owner_id(any_id: int) -> int:
    """A SECOND id in a request already bound to an owner (link a to-do to an
    event): it must be that owner's row, since links never cross files."""
    if not active():
        return int(any_id)
    owner, rid = decode(any_id)
    if (owner or _viewer()) != users.current():
        raise Forbidden("a to-do and an event can only be linked in one calendar")
    return rid


def public_id(row_id):
    """A row id of the bound owner, as the viewer knows it."""
    if not active():
        return row_id
    return encode(row_id, users.current(), _viewer())


def present(obj):
    """A row (or a list of rows) of the bound owner, as the viewer sees it."""
    if not active() or obj is None:
        return obj
    if isinstance(obj, list):
        return [present(o) for o in obj]
    return decorate(obj, users.current(), _viewer())


def release_request() -> None:
    """Undo `for_request`'s bindings (users.routes teardown), newest first."""
    from flask import g
    for tok in reversed(getattr(g, "sharing_tokens", [])):
        try:
            users._current.reset(tok)
        except (ValueError, RuntimeError):
            pass
    g.sharing_tokens = []


# ------------------------------------------------------------------ notifications

def notify_owners(viewer: str) -> list[str]:
    """Whose items a person is NOTIFIED about: their own, only (Gil,
    2026-09-28: "notifications should only be the main user, not include
    shared events"). A shared calendar is something to LOOK at; it never
    reaches the day panel, a reminder, the lock screen or the widget. This
    replaced an opt-in ("include what others share with me") that Q65 had."""
    return [viewer]


def digest_reader(db):
    """`db` for the day panel of whoever is bound: their own calendar and
    to-dos, never anyone else's (`notify_owners`). Kept as the one place the
    routes ask, so the rule lives here and not in each caller."""
    return db
