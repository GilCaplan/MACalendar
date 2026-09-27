"""The installed apps are NO TOUCH (Gil, 2026-09-26): an install script may
rebuild its own bundle in place, and must never delete or move an app
anywhere else. `scripts/build_apps.sh --install` once removed every "stray"
copy on the Desktop and in /Applications, which is how the Desktop icons
disappeared on 2026-09-18."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = [ROOT / "scripts/build_apps.sh", ROOT / "scripts/build_hud_app.sh",
           ROOT / "assistant/jude/build_app.sh"]


def _code(path):
    return "\n".join(l for l in path.read_text().splitlines()
                     if not l.lstrip().startswith("#"))


def test_an_install_removes_nothing_but_the_bundle_it_rebuilds():
    for path in SCRIPTS:
        for line in _code(path).splitlines():
            if re.search(r"\brm\b|\bmv\b", line):
                assert re.search(r'rm -rf "\$out"', line), f"{path.name}: {line.strip()}"


def test_an_install_goes_only_into_the_one_apps_folder():
    for path in SCRIPTS:
        code = _code(path)
        assert "$HOME/Desktop/" not in code, path.name
        for target in re.findall(r'build(?:_all_into)?\s+"(/Applications/[^"]*)"', code):
            assert target.startswith(("/Applications/MACalendar APPs", "/Applications/$FOLDER")), \
                (path.name, target)
