"""Draw the thinking HUD's app icon.

    python assistant/calendar_ui/assets/make_hud_icon.py

Generated rather than committed as a binary nobody can edit — same reason and
same shape as `assistant/jude/assets/make_icon.py`, which this is modelled on.

## Why this exists at all

`scripts/build_hud_app.sh` used to copy `assistant/app_icon.icns`, so
"MACalendar HUD.app" and "MACalendar.app" were IDENTICAL in the Dock. Two
different apps you are meant to click on for different reasons, wearing the
same face.

## The glyph

The HUD is a small always-on-top card that shows the assistant's chain of
thought STAGE BY STAGE while a command runs (see `thinking_hud.py`: it floats
over whatever you are actually working in, fed by the trace bus). So the glyph
is that card: a stack of stage rows, the top one lit in the project's accent
because it is the stage running now, the ones below it done and dimmer.

Not a calendar (that is MACalendar's), not a book (Jude's), and readable at
32px — which the amber row is what guarantees, since it is the one high-contrast
element and the eye finds it before it resolves anything else.

## The hue

MACalendar is blue, Jude is indigo→violet. Both are cool and adjacent, so a
third in that family would be the one you pick wrong in a hurry. This is
TEAL→DEEP CYAN: still obviously the same family of gradient squircles, but the
only one of the three you could name from across the room.

The accent is `styles.DEFAULT_ACCENT`, taken from the code rather than typed in,
so the lit row is the same amber the HUD itself draws with.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

from assistant.calendar_ui import styles as _styles

SIZE = 1024
SS = 4                      # supersample, then downsample: clean antialiasing
S = SIZE * SS

# Teal -> deep cyan. The third corner of the family; see the module docstring.
TOP = (16, 94, 104)
BOTTOM = (10, 48, 74)

CARD = (243, 245, 246)      # the card itself, very slightly cool white
ROW_DONE = (150, 166, 176)  # a stage that has finished
ACCENT = _styles.DEFAULT_ACCENT


def _hex(value: str) -> tuple:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _gradient() -> Image.Image:
    grad = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        grad.putpixel((0, y), tuple(
            round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)))
    return grad.resize((S, S))


def _squircle_mask() -> Image.Image:
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, S - 1, S - 1), radius=int(0.2246 * S), fill=255)
    return mask


def _draw_card(d: ImageDraw.ImageDraw) -> None:
    """The floating card, with its stages stacked inside it.

    Drawn as a real card with a real edge rather than as bare rows: the HUD's
    whole character is that it is a small window hovering over something else,
    and rows alone would read as a list or a hamburger menu.
    """
    def px(v):
        return v * SS

    # The card.
    d.rounded_rectangle((px(196), px(256), px(828), px(768)),
                        radius=px(56), fill=CARD)

    # Stage rows. The first is LIT — the stage running right now — and the
    # others shorten as they go down so the block reads as a sequence rather
    # than as a paragraph.
    rows = [(0.86, True), (0.70, False), (0.54, False), (0.38, False)]
    x0, top, gap, h = 268, 356, 104, 40
    dot_r = 26
    for i, (frac, lit) in enumerate(rows):
        y = top + i * gap
        colour = _hex(ACCENT) if lit else ROW_DONE
        # The marker: a filled dot for the live stage, a ring for a done one.
        d.ellipse((px(x0 - 8), px(y - dot_r // 2 - 6),
                   px(x0 - 8 + dot_r), px(y - dot_r // 2 - 6 + dot_r)),
                  fill=colour if lit else None,
                  outline=colour, width=px(7) if not lit else 0)
        bar_x = x0 + dot_r + 26
        d.rounded_rectangle(
            (px(bar_x), px(y - h // 4), px(bar_x + int(440 * frac)), px(y + h // 4)),
            radius=px(h // 4), fill=colour)


def build_png(out_path: str) -> str:
    icon = _gradient()
    _draw_card(ImageDraw.Draw(icon))
    icon = icon.convert("RGBA")
    icon.putalpha(_squircle_mask())
    icon = icon.resize((SIZE, SIZE), Image.LANCZOS)
    icon.save(out_path)
    return out_path


def build_icns(png_path: str, out_path: str) -> str:
    src = Image.open(png_path)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "hud.iconset")
        os.makedirs(iconset)
        for base in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = base * scale
                name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
                src.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out_path], check=True)
    return out_path


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    png = build_png(os.path.join(here, "hud_icon.png"))
    print("wrote", png)
    try:
        print("wrote", build_icns(png, os.path.join(here, "hud_icon.icns")))
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"iconutil unavailable ({e}); PNG only", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
