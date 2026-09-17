"""Which features you have switched off — the one piece of shared state.

Stored in `config.yaml` under `features:`, a plain `name -> bool` map. The Mac
reads it directly; the phone reads it over `GET /features` and caches it, so
the tab bar still draws on a train.

## Why one map and not three flags

There were three systems: iOS `UserDefaults` (`showCourseworkTab`), the Mac's
`ui.show_coursework`, and `jude.enabled` in a third block again — with no
mapping between them, no key at all for Teach, and an iOS comment admitting
*"mirrors the Mac's config.yaml but isn't synced from it"*. So "show tab X"
meant three different things and hiding a tab on the phone left it showing on
the Mac.

A map keyed by feature name means adding a feature adds no config schema, and
the key is the same string the API, the registry and both clients already use.

## Legacy keys are READ, once, and then stop mattering

`ui.show_coursework`, `ui.show_workout` and `ui.show_timer` are still honoured
as the initial value when `features:` has no entry for that name, so nobody's
existing config.yaml silently turns three tabs back on. The first write moves
it into `features:` and the old key is ignored from then on.
"""

from __future__ import annotations

import os
import threading

import yaml

_lock = threading.Lock()

#: Old `ui:` keys, read only when `features:` has nothing to say about a name.
_LEGACY_UI_KEYS = {
    "coursework": "show_coursework",
    "workout": "show_workout",
    "timer": "show_timer",
}


def config_path() -> str:
    """The repo's config.yaml, resolved absolutely.

    NOT relative to the working directory: the assistant is launched from
    Finder, where the working directory is not something to depend on — the
    same reason `Integration.root()` resolves against the repo.
    """
    override = os.environ.get("MACALENDAR_CONFIG")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    here = os.path.dirname(os.path.abspath(__file__))       # assistant/features
    return os.path.normpath(os.path.join(here, "..", "..", "config.yaml"))


def _read() -> dict:
    try:
        with open(config_path()) as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        # A missing or unreadable config must not blank the tab bar: every
        # feature falls back to its own default, which is "visible" for all
        # but Jude.
        return {}


def is_visible(name: str, default: bool = True) -> bool:
    data = _read()
    features = data.get("features")
    if isinstance(features, dict) and name in features:
        return bool(features[name])
    legacy = _LEGACY_UI_KEYS.get(name)
    if legacy:
        ui = data.get("ui")
        if isinstance(ui, dict) and legacy in ui:
            return bool(ui[legacy])
    return default


def is_explicit(name: str) -> bool:
    """Has anyone actually CHOSEN this feature's visibility?

    The distinction is load-bearing, and its absence was a real bug. A client
    refreshing from `GET /features` cannot otherwise tell "the Mac says off"
    from "the Mac has no opinion and is quoting the default back at you" — so
    a phone that had Jude switched ON had it switched off again by a Mac that
    had never been asked about Jude at all. Its own config.yaml had no
    `features:` block; `visible: false` was just `default_visible`.

    Explicit means the `features:` map has the key, or the legacy `ui.show_*`
    key it migrated from is present. Anything else is a default, and a default
    must never overwrite somebody's choice.
    """
    data = _read()
    features = data.get("features")
    if isinstance(features, dict) and name in features:
        return True
    legacy = _LEGACY_UI_KEYS.get(name)
    ui = data.get("ui")
    return bool(legacy and isinstance(ui, dict) and legacy in ui)


def set_visible(name: str, on: bool) -> None:
    """Write one flag, preserving everything else in the file.

    Read-modify-write under a lock, and the whole document is rewritten from
    what was just read — the same shape `PATCH /config` uses. A partial write
    here would corrupt the file the assistant boots from.
    """
    with _lock:
        data = _read()
        features = data.get("features")
        if not isinstance(features, dict):
            features = {}
        features[name] = bool(on)
        data["features"] = features
        path = config_path()
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False)
        os.replace(tmp, path)      # atomic: never a half-written config
