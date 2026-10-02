"""The Mac window's calendar: the logged-in user's own, plus what they may see.

The window and its views hold ONE object they call `self._db` and call the
`CalendarDB` API on it (91 call sites). So sharing reaches the Mac by handing
them this instead of a raw `CalendarDB`:

  reads   `get_events_for_*`, `search_*`, `get_todos` — every calendar the user
          can see (users.sharing.gather), each row carrying its owner's name
          and colour, other people's ids namespaced
  by id   `get_event`, `update_event`, `delete_event`, `toggle_todo_complete`, …
          — routed to the OWNER's file, as the owner, and REFUSED (not raised)
          when the user may only look: an exception escaping a Qt slot aborts
          the whole app, so a refusal returns the method's "nothing happened"
          value and tells the window, which says so in the status bar
  else    straight through to the user's own CalendarDB (tags, timers,
          courses, sources — none of those are shared)

Before the users migration (no registry) `sharing.active()` is false and
every call is simply the plain CalendarDB's. Same logic as the API — the merge
is not written twice (CLAUDE.md: the GUI once had its own pipeline copy).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from assistant import users
from assistant.users import sharing

logger = logging.getLogger(__name__)

#: Reads that merge every visible calendar. name -> sort key (None: keep order)
_MERGED_READS: "dict[str, Any]" = {
    "get_events_for_month": sharing.event_order,
    "get_events_for_week": sharing.event_order,
    "get_events_for_day": sharing.event_order,
    "get_events_between": sharing.event_order,
    "search_events": sharing.event_order,
    "get_todos": None,
    "search_todos": None,
}
#: Methods whose FIRST argument is a row id: the row's owner answers them.
_BY_ID_READ = {"get_event", "get_todo", "get_series_events", "linked_todo",
               "linked_todos", "linked_event"}
_BY_ID_WRITE = {"update_event", "delete_event", "promote_to_series", "update_series",
                "delete_series", "delete_series_from", "create_linked_todo",
                "update_todo", "delete_todo", "toggle_todo_complete", "link_todo",
                "unlink_todo", "create_linked_event", "set_event_color",
                "set_event_category", "move_event"}
#: What "nothing happened" looks like for a refused write, per method.
_REFUSED = {"toggle_todo_complete": False, "link_todo": False}


class MergedCalendar:
    """A CalendarDB-shaped view over the logged-in user's visible calendars."""

    def __init__(self, own, on_refused: "Callable[[str], None] | None" = None) -> None:
        self._own = own
        self._on_refused = on_refused or (lambda msg: logger.info("%s", msg))

    def set_own(self, own) -> None:
        """A different user signed in: every view keeps this object, and it
        now reads their calendar."""
        self._own = own

    # the file the window watches for changes is the user's own
    @property
    def path(self) -> str:
        return self._own.path

    def __getattr__(self, name: str):
        if name in _MERGED_READS:
            return self._merged(name)
        if name in _BY_ID_READ:
            return self._by_id(name, edit=False)
        if name in _BY_ID_WRITE:
            return self._by_id(name, edit=True)
        return getattr(self._own, name)

    # -- reads over every visible calendar -----------------------------------

    def _merged(self, name: str):
        def call(*args, **kwargs):
            if not sharing.active():
                return getattr(self._own, name)(*args, **kwargs)
            return sharing.gather(lambda db: getattr(db, name)(*args, **kwargs),
                                  sort_key=_MERGED_READS[name])
        return call

    # -- one row, by its (possibly namespaced) id ------------------------------

    def _by_id(self, name: str, edit: bool):
        def call(any_id, *args, **kwargs):
            if not sharing.active():
                return getattr(self._own, name)(any_id, *args, **kwargs)
            viewer = users.current()
            try:
                owner, rid = sharing.decode(any_id)
            except sharing.NotFound:
                return None
            owner = owner or viewer
            if owner == viewer:
                return getattr(self._own, name)(rid, *args, **kwargs)
            if not sharing.can_view(viewer, owner):
                return None
            if edit and not sharing.can_edit(viewer, owner):
                from assistant.users import registry
                who = (registry.get(owner) or {}).get("display_name", "its owner")
                self._on_refused(f"{who} shared this with you to view only")
                return _REFUSED.get(name)
            from assistant.db import get_db
            with users.bind(owner):
                out = getattr(get_db(), name)(rid, *args, **kwargs)
                if isinstance(out, dict):
                    return sharing.decorate(out, owner, viewer)
                if isinstance(out, list):
                    return [sharing.decorate(r, owner, viewer) if isinstance(r, dict) else r
                            for r in out]
                return out
        return call


def owner_prefix(row: dict) -> str:
    """"Dana · " before a shared row's title in the views — display only, so an
    edit can never save the prefix into the title."""
    if row.get("shared") and row.get("owner_name"):
        return f"{row['owner_name']} · "
    return ""
