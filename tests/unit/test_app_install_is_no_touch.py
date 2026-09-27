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
    # `rm -rf "$out"` (the bundle being rebuilt) or a file INSIDE it — the
    # stock Assets.car, see the icon test below. Nothing else, anywhere.
    for path in SCRIPTS:
        for line in _code(path).splitlines():
            if re.search(r"\brm\b|\bmv\b", line):
                assert re.search(r'\brm -r?f "\$out(/[^"$]*)?"', line) \
                    and not re.search(r"\bmv\b", line), f"{path.name}: {line.strip()}"


def test_an_install_goes_only_into_the_one_apps_folder():
    for path in SCRIPTS:
        code = _code(path)
        assert "$HOME/Desktop/" not in code, path.name
        for target in re.findall(r'build(?:_all_into)?\s+"(/Applications/[^"]*)"', code):
            assert target.startswith(("/Applications/MACalendar APPs", "/Applications/$FOLDER")), \
                (path.name, target)


def test_a_bundle_wears_its_own_icon_not_the_stock_applet_catalog():
    """osacompile ships the stock applet asset catalog (Assets.car) and sets
    CFBundleIconName=applet. On current macOS a named catalog icon wins over
    CFBundleIconFile, so copying our icns over applet.icns changed nothing:
    every app showed the grey script scroll (found on Tahoe, 2026-09-27).
    Each script must drop both after copying the icon and before re-sealing,
    and must check afterwards that they are gone."""
    for path in SCRIPTS:
        code = _code(path)
        cp = code.index("/Contents/Resources/applet.icns")
        seal = code.index("codesign --force")
        delete_key = code.find("Delete :CFBundleIconName")
        drop_car = code.find('rm -f "$out/Contents/Resources/Assets.car"')
        assert delete_key != -1, f"{path.name} leaves CFBundleIconName on the stock catalog"
        assert drop_car != -1, f"{path.name} leaves the stock Assets.car in the bundle"
        assert cp < delete_key < seal and cp < drop_car < seal, \
            f"{path.name}: strip the stock icon after copying the icns and before re-sealing"
        guard = code[seal:]
        assert "Print :CFBundleIconName" in guard and "Assets.car" in guard, \
            f"{path.name}: verify after sealing that the stock icon is gone"
