"""MACalendar draws no emoji — every picture is a GraphicsLibrary drawing.

Gil, 2026-10-01: *"i dont want emojis, rather custom made graphics, i think
we have on this computer, so find that library can make more of our own"*.
`scripts/sync_icons.py` copies the drawings MACalendar uses out of
`../GraphicsLibrary` into the Mac's `calendar_ui/icons` and the phone's
`Assets.xcassets/Icons`. The library is not on CI, so these read only what
was copied: every name the code draws exists on BOTH platforms, and no
emoji crept back onto a screen.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAC = ROOT / "assistant" / "calendar_ui" / "icons"
IOS = ROOT / "MACalendar-iOS" / "MACalendar-iOS" / "Assets.xcassets" / "Icons"


def _tracked(*globs: str) -> list[pathlib.Path]:
    out = subprocess.run(["git", "ls-files", *globs], cwd=ROOT, capture_output=True, text=True).stdout
    return [ROOT / p for p in out.split()]


def _library_names() -> set[str]:
    lines = (MAC / "LIBRARY.txt").read_text().splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}


def test_every_synced_icon_is_on_both_platforms_as_a_template():
    for name in _library_names():
        assert (MAC / f"{name}.svg").exists(), f"Mac lacks {name} — run python -m scripts.sync_icons"
        folder = IOS / f"{name}.imageset"
        meta = json.loads((folder / "Contents.json").read_text())
        assert meta["properties"]["template-rendering-intent"] == "template", name
        svg = (folder / f"{name}.svg").read_text()
        assert "currentColor" not in svg and 'width="24"' in svg, f"{name}: not the Xcode form"


def test_every_icon_the_python_draws_exists():
    names = set()
    for path in _tracked("assistant/*.py"):
        text = path.read_text(encoding="utf-8")
        names |= set(re.findall(r'icons\.(?:icon|html|pixmap)\(\s*["\'](\w+)["\']', text))
    from assistant.calendar_ui import occasion_ui, settings_dialog, window
    from assistant.jude.ui import sidebar
    names |= set(occasion_ui.ICON.values()) | set(sidebar.MODE_ICONS.values())
    names |= {glyph for _c, glyph in settings_dialog._SECTION_TILES.values()}
    names |= set(window._MIC_ICONS.values()) - {"mic"}       # idle draws its own
    missing = sorted(n for n in names if not (MAC / f"{n}.svg").exists())
    assert not missing, f"drawn but not synced: {missing} — python -m scripts.sync_icons --add …"


def test_every_icon_the_phone_draws_exists():
    names = set()
    for path in _tracked("MACalendar-iOS/MACalendar-iOS/*.swift"):
        text = path.read_text(encoding="utf-8")
        names |= set(re.findall(r'Ico\(\s*"(\w+)"', text))
        names |= set(re.findall(r'label: "[^"]+", icon: "(\w+)"\)', text))   # TitleEmojiKind
    egg = (ROOT / "MACalendar-iOS/MACalendar-iOS/EasterEgg/EggSymbol.swift").read_text()
    picks = egg[egg.index("static let icons"):egg.index("static let symbols")]
    names |= set(re.findall(r'"(\w+)"', picks))
    occ = (ROOT / "MACalendar-iOS/MACalendar-iOS/Features/Calendar/Occasions.swift").read_text()
    block = occ[occ.index("static func icon(_ kind"):]
    block = block[:block.index("}")]
    names |= set(re.findall(r':\s*"(\w+)"', block))
    missing = sorted(n for n in names if not (IOS / f"{n}.imageset").exists())
    assert not missing, f"drawn on the phone but not synced: {missing}"


def test_the_phone_and_the_mac_give_each_kind_the_same_picture():
    from assistant.calendar_ui import occasion_ui
    from assistant.engine.label.title_icons import GROUP_ICONS
    occ = (ROOT / "MACalendar-iOS/MACalendar-iOS/Features/Calendar/Occasions.swift").read_text()
    block = occ[occ.index("static func icon(_ kind"):]
    block = block[:block.index("}")]
    assert dict(re.findall(r'"(\w+)":\s*"(\w+)"', block)) == occasion_ui.ICON
    swift = (ROOT / "MACalendar-iOS/MACalendar-iOS/Views/SettingsView.swift").read_text()
    assert dict(re.findall(r'key: "(\w+)", label: "[^"]+", icon: "(\w+)"', swift)) == GROUP_ICONS


# Pictographs only: typographic marks (✓ ✕ ⌘ ▾ ★ ⚑ ☑ ☐ ⌨ →) are text, and stay.
_TEXT_MARKS = "\u2610\u2611\u2612\u2606\u2605\u263e\u2691\u2690"
_EMOJI = re.compile(f"(?![{_TEXT_MARKS}])[\U0001F000-\U0001FAFF\u2600-\u26FF\u2705\u274C\u2753\u2728\u2B50\u23F0-\u23FA]")
_ALLOWED = (
    "tests/", "retired/", "/experiments/", "/datasets/", "UITests/", "MACalendar-iOS/Tools/",
    "assistant/engine/label/title_icons.py",      # strip(): reads a pre-2026-10-01 title
)


def test_no_emoji_reaches_a_screen():
    """Comments may quote one; a string the app shows may not. The Easter egg
    still DRAWS a saved emoji (a user's old pick), so its parser is exempt by
    construction — it holds none."""
    found = []
    for path in _tracked("assistant/*.py", "mac/*.swift", "MACalendar-iOS/*.swift", "install/*.py"):
        rel = str(path.relative_to(ROOT))
        if any(a in rel for a in _ALLOWED):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0] if rel.endswith(".py") else line.split("//", 1)[0]
            if _EMOJI.search(code) and not code.strip().startswith(('"""', "///", "*")):
                found.append(f"{rel}:{i}: {line.strip()[:90]}")
    assert not found, "emoji on a screen (draw a GraphicsLibrary icon instead):\n" + "\n".join(found)
