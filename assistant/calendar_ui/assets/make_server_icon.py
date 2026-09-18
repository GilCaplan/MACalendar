"""Draw the API server's app icon.

    python assistant/calendar_ui/assets/make_server_icon.py

Generated rather than committed as a binary nobody can edit — the same reason
and the same shape as `make_hud_icon.py`, which this is modelled on.

## The glyph

The server is the BRAIN'S FRONT DOOR: `assistant.api` receives every command,
from the Mac and from the phone over Tailscale, and hands it to the engine. So
the glyph is two stacked bars — the machine — with a signal arc rising off it:
something other devices connect TO.

Not a calendar (MACalendar's), not a card of stage rows (the HUD's), not a book
(Jude's). Readable at 32 px, which the arc guarantees: it is the one shape that
breaks the rectangle's outline, and the eye finds it before it resolves the
bars.

## The hue

MACalendar is blue, the HUD amber, Jude indigo→violet. Green is the one family
left that is not adjacent to any of them, and it is also the colour every
status light in the world uses for "up" — which is the single fact you want
from this icon at a glance.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from PIL import Image, ImageDraw

SIZE = 1024
TOP = "#1f8f5f"          # a deep green
BOTTOM = "#0d5c3c"
BAR = "#eaf7f0"          # near-white, so the machine reads at any size
ARC = "#7ef0b0"          # the signal, the one bright element

HERE = os.path.dirname(os.path.abspath(__file__))
PNG = os.path.join(HERE, "server_icon.png")
ICNS = os.path.join(HERE, "server_icon.icns")


def _hex(value: str) -> tuple:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _gradient() -> Image.Image:
    top, bottom = _hex(TOP), _hex(BOTTOM)
    img = Image.new("RGB", (SIZE, SIZE))
    d = ImageDraw.Draw(img)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        d.line([(0, y), (SIZE, y)],
               fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def _squircle_mask() -> Image.Image:
    """macOS rounds app icons itself, but only for the ones it draws — a
    generated icns keeps whatever corners it was given."""
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (SIZE - 1, SIZE - 1)], radius=int(SIZE * 0.225), fill=255)
    return mask


def _draw(d: ImageDraw.ImageDraw) -> None:
    def px(v: float) -> int:
        return int(SIZE * v)

    # Two stacked bars: the machine.
    left, right = px(0.24), px(0.76)
    height = px(0.115)
    radius = px(0.03)
    for top in (px(0.50), px(0.665)):
        d.rounded_rectangle([(left, top), (right, top + height)],
                            radius=radius, fill=BAR)
        # One lit indicator per bar, at the left, where a real one sits.
        cy = top + height // 2
        r = px(0.018)
        d.ellipse([(left + px(0.05) - r, cy - r), (left + px(0.05) + r, cy + r)],
                  fill=ARC)

    # The signal arc rising off the machine — three bands, widening upward.
    cx = px(0.50)
    base = px(0.47)
    for i, (rad, width) in enumerate(((px(0.10), px(0.028)),
                                      (px(0.175), px(0.026)),
                                      (px(0.25), px(0.024)))):
        box = [(cx - rad, base - rad), (cx + rad, base + rad)]
        # Fading outward: the nearest band is the brightest, so the shape still
        # reads when the outer ones disappear at 32 px.
        alpha = 255 - i * 55
        d.arc(box, start=210, end=330, fill=ARC + f"{alpha:02x}", width=width)


def build_png(out_path: str = PNG) -> str:
    img = _gradient().convert("RGBA")
    img.putalpha(_squircle_mask())
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    _draw(ImageDraw.Draw(layer))
    img = Image.alpha_composite(img, layer)
    img.save(out_path)
    return out_path


def build_icns(png_path: str = PNG, out_path: str = ICNS) -> str:
    src = Image.open(png_path)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "server.iconset")
        os.makedirs(iconset)
        for px, name in ((16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
                         (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
                         (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
                         (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
                         (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")):
            src.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out_path],
                       check=True)
    return out_path


if __name__ == "__main__":
    print("wrote", build_png())
    print("wrote", build_icns())
