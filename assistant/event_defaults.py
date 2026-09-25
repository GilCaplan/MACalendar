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


def config_path() -> str:
    """The config.yaml the rest of the app reads and writes.

    `MACALENDAR_CONFIG` first, else the REPO's config.yaml — resolved against
    this file, not the working directory. This used to open a bare
    "config.yaml", which is the right file only when the process happens to
    run from the repo root: the launcher `cd`s there, but a script, a
    LaunchAgent or a test run from anywhere else read no config at all and
    silently fell back to 60 / 0 whatever Settings said. `PATCH /config` and
    `features/settings.py` both resolve it this way.
    """
    import os
    override = os.environ.get("MACALENDAR_CONFIG")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    here = os.path.dirname(os.path.abspath(__file__))           # assistant/
    return os.path.normpath(os.path.join(here, "..", "config.yaml"))


def _config_value(key: str) -> "int | None":
    """`events.<key>` from config.yaml, re-read only when the file changes.

    Only the `events:` section is parsed (through `EventsConfig`, so the
    clamping is the same one the app applies), not the whole `AppConfig`: a
    config that fails validation somewhere unrelated must not take the event
    length down with it. Cached per (path, mtime), so a test or a caller that
    points `MACALENDAR_CONFIG` somewhere else is never served another file's
    answer.
    """
    import os
    path = config_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _cfg_cache.get("key") != (path, mtime):
        events = None
        try:
            import yaml
            from assistant.config import EventsConfig
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            section = data.get("events") if isinstance(data, dict) else None
            if isinstance(section, dict):
                events = EventsConfig(**section).model_dump()
                # Only keys the file actually SETS count as a setting; an
                # absent key falls through to the built-in default.
                events = {k: v for k, v in events.items() if k in section}
        except Exception:
            events = None
        _cfg_cache.update(key=(path, mtime), events=events)
    value = (_cfg_cache.get("events") or {}).get(key)
    try:
        return None if value is None else max(0, int(value))
    except (TypeError, ValueError):
        return None
