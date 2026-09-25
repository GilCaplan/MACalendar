"""How long an event lasts when nobody said, and how far apart chained events sit.

DEVQA Q51 (Gil, 2026-09-25): *"a default thing in the settings … what between
chained events what that gap could be … and what the default length of an
event is … or according to the category, each category to have its default
length."* One module so the engine (`CalendarIntent.fill_defaults`, the
chain in `decompose_validate`) and both apps read the same two numbers.

Resolution order for each: the CATEGORY's own value, if it has one → the
global setting → the built-in default. The settings UI and the category
fields live with the settings and categories surfaces; this is only the read.
"""
from __future__ import annotations

#: The defaults before anyone touches a setting: an hour long, back to back.
DEFAULT_LENGTH_MINUTES = 60
DEFAULT_GAP_MINUTES = 0


def length_minutes(category: "str | None" = None) -> int:
    """Minutes an event lasts when its end was not said."""
    return _read("default_minutes", "event_length_minutes", DEFAULT_LENGTH_MINUTES, category)


def gap_minutes(category: "str | None" = None) -> int:
    """Minutes between the end of one chained event and the start of the next."""
    return _read("chain_gap_minutes", "chain_gap_minutes", DEFAULT_GAP_MINUTES, category)


def category_of(title: str) -> "str | None":
    """The category the label stage's rules would give this title, or None."""
    try:
        from assistant.actions.calendar import categories
        return categories.classify(title) or None
    except Exception:
        return None


def _read(cat_key: str, cfg_key: str, default: int, category: "str | None") -> int:
    if category:
        try:
            from assistant.actions.calendar import categories
            c = categories.get(category) or {}
            if c.get(cat_key) is not None:
                return max(0, int(c[cat_key]))
        except Exception:
            pass
    value = _config_value(cfg_key)
    return default if value is None else value


_cfg_cache: dict = {}


def _config_value(key: str) -> "int | None":
    """`events.<key>` from config.yaml, re-read only when the file changes."""
    import os
    path = os.environ.get("MACALENDAR_CONFIG", "config.yaml")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _cfg_cache.get("mtime") != mtime:
        try:
            from assistant.config import load_config
            _cfg_cache.update(mtime=mtime, cfg=load_config(path))
        except Exception:
            _cfg_cache.update(mtime=mtime, cfg=None)
    events = getattr(_cfg_cache.get("cfg"), "events", None)
    value = getattr(events, key, None) if events is not None else None
    try:
        return None if value is None else max(0, int(value))
    except (TypeError, ValueError):
        return None
