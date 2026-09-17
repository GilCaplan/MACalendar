"""Draw Jude's app icon.

Generated rather than committed as a binary blob nobody can edit: run this and
`jude_icon.png` / `jude_icon.icns` are rebuilt from the shapes below.

    python assistant/jude/assets/make_icon.py

It is deliberately a SIBLING of `assistant/app_icon.icns` — same squircle, same
corner radius, same gradient-behind-a-white-glyph language — so the three
bundles read as one family in the Dock. What differs is the hue (indigo/violet
rather than blue) and the glyph (an open book rather than a calendar), because
two apps from one project should look related and still be told apart at 32px.

Everything is drawn at 4x and downsampled, which is the cheap way to get clean
antialiased diagonals out of Pillow's polygon fill.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

SIZE = 1024
SS = 4                      # supersample factor
S = SIZE * SS

# Indigo -> violet. MACalendar's icon is the blue end of this family; Jude sits
# beside it rather than clashing with it.
TOP = (46, 42, 112)
BOTTOM = (108, 68, 168)

PAGE = (247, 244, 236)      # warm parchment, not pure white
PAGE_SHADE = (222, 216, 200)
RULE = (150, 146, 170)
GOLD = (245, 165, 36)       # the project accent


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


def _draw_book(d: ImageDraw.ImageDraw) -> None:
    """An open book, seen slightly from above.

    Two pages meeting at a spine, with the outer edges lower than the spine so
    it reads as open rather than as a folded sheet. The page-block under each
    side is what stops it looking like two flat triangles at small sizes.
    """
    def px(x, y):
        return (x * SS, y * SS)

    spine_top, spine_bottom = 330, 700
    out_top, out_bottom = 392, 668
    left_x, right_x = 148, 876
    cx = 512

    # The block of pages beneath each leaf: a few pixels of depth, in shade.
    for dy in range(26, 0, -1):
        o = dy * SS
        d.polygon([px(left_x, out_top), px(cx, spine_top), px(cx, spine_bottom),
                   px(left_x, out_bottom)], fill=None)
    d.polygon([(left_x * SS, out_top * SS + 26 * SS), (cx * SS, spine_top * SS + 26 * SS),
               (cx * SS, spine_bottom * SS + 26 * SS), (left_x * SS, out_bottom * SS + 26 * SS)],
              fill=PAGE_SHADE)
    d.polygon([(right_x * SS, out_top * SS + 26 * SS), (cx * SS, spine_top * SS + 26 * SS),
               (cx * SS, spine_bottom * SS + 26 * SS), (right_x * SS, out_bottom * SS + 26 * SS)],
              fill=PAGE_SHADE)

    # The two leaves.
    d.polygon([px(left_x, out_top), px(cx, spine_top),
               px(cx, spine_bottom), px(left_x, out_bottom)], fill=PAGE)
    d.polygon([px(right_x, out_top), px(cx, spine_top),
               px(cx, spine_bottom), px(right_x, out_bottom)], fill=PAGE)

    # The spine: a gold seam, which is the one warm note and the thing that
    # makes the glyph legible when the icon is 32px wide.
    d.polygon([px(cx - 9, spine_top), px(cx + 9, spine_top),
               px(cx + 9, spine_bottom), px(cx - 9, spine_bottom)], fill=GOLD)

    # Lines of text. Shorter as they go down on each page, so it reads as a
    # column of writing rather than a barcode.
    for side in (-1, 1):
        for i, frac in enumerate((0.92, 0.86, 0.80, 0.70, 0.55)):
            y = 420 + i * 52
            inner = cx + side * 44
            outer = cx + side * int(44 + (318 * frac))
            x0, x1 = sorted((inner, outer))
            d.rounded_rectangle(
                (x0 * SS, (y - 8) * SS, x1 * SS, (y + 8) * SS),
                radius=8 * SS, fill=RULE)

    # A ribbon bookmark falling from the spine.
    d.polygon([px(cx - 26, spine_bottom - 6), px(cx + 26, spine_bottom - 6),
               px(cx + 26, 806), px(cx, 770), px(cx - 26, 806)], fill=GOLD)


def build_png(out_path: str) -> str:
    icon = _gradient()
    _draw_book(ImageDraw.Draw(icon))
    icon = icon.convert("RGBA")
    icon.putalpha(_squircle_mask())
    icon = icon.resize((SIZE, SIZE), Image.LANCZOS)
    icon.save(out_path)
    return out_path


def build_icns(png_path: str, out_path: str) -> str:
    """PNG -> .icns via iconutil, which wants a populated .iconset directory."""
    src = Image.open(png_path)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "jude.iconset")
        os.makedirs(iconset)
        for base in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = base * scale
                name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
                src.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out_path],
                       check=True)
    return out_path


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    png = build_png(os.path.join(here, "jude_icon.png"))
    print("wrote", png)
    try:
        print("wrote", build_icns(png, os.path.join(here, "jude_icon.icns")))
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"iconutil unavailable ({e}); PNG only", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
