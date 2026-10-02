"""Copy the icons MACalendar draws out of the shared GraphicsLibrary.

    python -m scripts.sync_icons                 # re-copy every icon in the manifest
    python -m scripts.sync_icons --add dog cat   # add names to the manifest, then copy
    python -m scripts.sync_icons --check         # exit 1 if a copy differs from the library

MACalendar draws no emoji (Gil, 2026-10-01: *"i dont want emojis, rather
custom made graphics"*). Every picture is a line icon from
`../GraphicsLibrary` — 24x24, `currentColor`, one stroke weight — so the
calendar, the phone and the Easter egg read as one set. New drawings are made
THERE (its `tools/add_icons.py` + `tools/preview.py`), never here, so the next
project finds them too.

`assistant/calendar_ui/icons/LIBRARY.txt` lists the names taken from the
library; the other SVGs in that folder are MACalendar's own and are never
touched. Each name lands in two places:

- the Mac: `assistant/calendar_ui/icons/<name>.svg`, as-is
  (`calendar_ui.icons` swaps `currentColor` for the theme's ink);
- the phone: `Assets.xcassets/Icons/<name>.imageset`, a TEMPLATE image with
  vector data kept, so SwiftUI tints it like text. Xcode's SVG reader is not a
  browser: the copy gets a concrete black and a plain 24x24 size, and loses
  the inline `style` the web needs.

The library is not on CI, so the build's check (`test_icons.py`) reads only
what was copied: every name the code draws exists on both platforms.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = Path(os.environ.get("GRAPHICS_LIBRARY", ROOT.parent / "GraphicsLibrary"))
MAC = ROOT / "assistant" / "calendar_ui" / "icons"
MANIFEST = MAC / "LIBRARY.txt"
IOS = ROOT / "MACalendar-iOS" / "MACalendar-iOS" / "Assets.xcassets" / "Icons"

_HEADER = ("# Icons copied from ../GraphicsLibrary by scripts/sync_icons.py — one name per line.\n"
           "# Draw new ones in the library, then `python -m scripts.sync_icons --add <name>`.\n")


def manifest() -> list[str]:
    if not MANIFEST.exists():
        return []
    return sorted({ln.strip() for ln in MANIFEST.read_text().splitlines()
                   if ln.strip() and not ln.startswith("#")})


def for_xcode(svg: str) -> str:
    """The library's web-ready SVG as Xcode's asset compiler wants it."""
    svg = re.sub(r'\s(style|aria-hidden|class)="[^"]*"', "", svg)
    svg = svg.replace('width="1em"', 'width="24"').replace('height="1em"', 'height="24"')
    return svg.replace("currentColor", "#000000")


def _imageset(name: str) -> dict:
    return {"images": [{"filename": f"{name}.svg", "idiom": "universal"}],
            "info": {"author": "xcode", "version": 1},
            "properties": {"preserves-vector-representation": True,
                           "template-rendering-intent": "template"}}


def expected(name: str) -> dict[Path, str]:
    """Every file `name` should have, and its exact contents."""
    svg = (LIB / "icons" / f"{name}.svg").read_text()
    folder = IOS / f"{name}.imageset"
    return {MAC / f"{name}.svg": svg,
            folder / f"{name}.svg": for_xcode(svg),
            folder / "Contents.json": json.dumps(_imageset(name), indent=2) + "\n"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--add", nargs="+", default=[], metavar="NAME")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if not (LIB / "library.json").exists():
        print(f"no GraphicsLibrary at {LIB} (set GRAPHICS_LIBRARY)", file=sys.stderr)
        return 2
    lib = json.loads((LIB / "library.json").read_text())
    names = sorted(set(manifest()) | set(args.add))
    missing = [n for n in names if n not in lib]
    if missing:
        print(f"not in the library: {missing}", file=sys.stderr)
        return 2
    own = {p.stem for p in MAC.glob("*.svg")} - set(manifest())
    clash = [n for n in args.add if n in own]
    if clash:
        print(f"MACalendar already has its own icon named {clash}; pick another name", file=sys.stderr)
        return 2

    stale = []
    for name in names:
        for path, text in expected(name).items():
            if not path.exists() or path.read_text() != text:
                stale.append(path)
                if not args.check:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
    if args.check:
        for p in stale:
            print("differs:", p.relative_to(ROOT))
        return 1 if stale else 0

    IOS.mkdir(parents=True, exist_ok=True)
    (IOS / "Contents.json").write_text(json.dumps(
        {"info": {"author": "xcode", "version": 1}, "properties": {"provides-namespace": True}},
        indent=2) + "\n")
    MANIFEST.write_text(_HEADER + "".join(n + "\n" for n in names))
    print(f"{len(names)} icons; {len(stale)} file(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
