"""Who the assistant is working for, right now.

Gil, 2026-09-28: an admin plus other users, each with their own calendar,
to-dos and everything the assistant learns about them. The plan
(`DOCUMENTATION/USERS_PLAN.md`) found eighteen personal stores whose paths are
module constants read at import, and six process-wide singletons over them —
so the user cannot travel as an argument without reshaping every call site,
and must not travel through `EngineState`, whose contract is frozen.

It travels the way request PRIORITY already does (`model_protocol.serving`):
a `ContextVar`, set per request by the API and per process by the GUI and HUD.
Every store asks `current()` and resolves its path through `paths.resolve`.

    current()                 the bound user, else the process default, else
                              — once `users.json` exists and login is not yet
                              required — the admin; else None
    bind(uid)                 context manager: this request / this loop tick
    set_process_default(uid)  GUI, HUD, notifier: one user for the process
    thread(target, …)         a Thread that keeps the caller's user

**None means "no users yet"**: before the migration there is no registry, no
one is bound, and every store resolves to exactly the path it always had. That
is the compat contract every existing test relies on, and what lets this ship
before anything visible does.
"""
from __future__ import annotations

import contextlib
import contextvars
import threading
from typing import Any, Callable

_current: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "macalendar_user", default=None)
_process_default: "str | None" = None


def current() -> "str | None":
    """The user every personal store resolves to, or None (the legacy tree)."""
    uid = _current.get()
    if uid:
        return uid
    if _process_default:
        return _process_default
    from assistant.users import registry
    return registry.implicit_user()


@contextlib.contextmanager
def bind(user_id: "str | None"):
    """Everything under this block reads and writes `user_id`'s stores."""
    token = _current.set(user_id or None)
    try:
        yield
    finally:
        _current.reset(token)


def set_process_default(user_id: "str | None") -> None:
    """One user for the whole process — the GUI's logged-in user, the HUD's."""
    global _process_default
    _process_default = user_id or None


def thread(*, target: Callable[..., Any], args: tuple = (),
           kwargs: "dict | None" = None, **thread_kw: Any) -> threading.Thread:
    """`threading.Thread(target=…, args=…, daemon=…)` that runs `target` as
    the CALLER's user — same keywords, so a call site converts one-for-one.

    A new thread starts with a fresh context, so without this the engine's
    background self-check would write to whoever the process default is —
    another user's memory — rather than to the speaker's."""
    ctx = contextvars.copy_context()
    kw = dict(kwargs or {})
    return threading.Thread(target=lambda: ctx.run(target, *args, **kw), **thread_kw)


def each_user() -> "list[str | None]":
    """Every active user, for a loop that serves them all (the pending retry,
    later the sync and the notifier) — or `[None]` before there are users,
    which runs the loop once over the legacy stores, as always."""
    from assistant.users import registry
    if not registry.exists():
        return [None]
    return registry.user_ids() or [None]
