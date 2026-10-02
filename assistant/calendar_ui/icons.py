"""Tiny SVG icon loader for the shared "moody dev-tool" glyph set.

Icons live as hand-authored SVGs in `calendar_ui/icons/*.svg`, drawn on a
24x24 grid and colored with `currentColor` so a single file can be tinted
to match the active theme/accent. This module swaps `currentColor` for a
concrete hex color, rasterizes with QSvgRenderer, and caches the result
per (name, color, size) so repeated lookups (e.g. rebuilding a list every
refresh) don't re-parse/re-render the SVG.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")

_pixmap_cache: dict[tuple, QPixmap] = {}
_icon_cache: dict[tuple, QIcon] = {}


def _default_color() -> str:
    """Current UI text color, so an untinted icon matches surrounding text."""
    from assistant.calendar_ui import styles
    return styles.D_GRAY_DARK if styles._dark else styles.GRAY_DARK


def _load_svg(name: str, color: str) -> bytes:
    path = os.path.join(_ICONS_DIR, f"{name}.svg")
    with open(path, "r", encoding="utf-8") as f:
        svg = f.read()
    return svg.replace("currentColor", color).encode("utf-8")


_DPR = 2          # drawn at twice the size asked, so a Retina screen gets crisp lines


def exists(name: str) -> bool:
    return os.path.exists(os.path.join(_ICONS_DIR, f"{name}.svg"))


def pixmap(name: str, color: str | None = None, size: int = 16) -> QPixmap:
    """Rasterize an icon to a QPixmap (for QLabel icons, composite rows, …),
    `size` logical px at a device pixel ratio of 2."""
    color = color or _default_color()
    key = (name, color, size)
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached
    renderer = QSvgRenderer(QByteArray(_load_svg(name, color)))
    out = QPixmap(QSize(size * _DPR, size * _DPR))
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    renderer.render(painter)
    painter.end()
    out.setDevicePixelRatio(_DPR)
    _pixmap_cache[key] = out
    return out


def draw_row(painter: QPainter, x: float, rect, names, color: str, size: int) -> float:
    """Paint `names` left to right from `x`, centred in `rect`'s height; the x
    after the last one (plus a gap), or `x` itself when there are none. What
    a hand-painted row (a month pill, a week block) puts before its title."""
    y = rect.top() + (rect.height() - size) / 2
    for name in names or ():
        if not exists(name):
            continue
        painter.drawPixmap(int(x), int(round(y)), pixmap(name, color, size))
        x += size + 3
    return x


def html(name: str, color: str | None = None, size: int = 14) -> str:
    """`<img>` markup for an icon inside a QLabel's rich text — for a label
    that is a sentence with a picture in it ("[pin] Room 4"). Written once to
    a cache folder as a PNG plus its @2x, which Qt's rich text picks on a
    Retina screen; `""` for a name the folder does not have."""
    if not exists(name):
        return ""
    import tempfile
    color = color or _default_color()
    folder = os.path.join(tempfile.gettempdir(), "macalendar-icons")
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, f"{name}-{color.lstrip('#')}-{size}")
    if not os.path.exists(base + "@2x.png"):
        pm = pixmap(name, color, size)
        pm.save(base + "@2x.png")
        pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                  Qt.TransformationMode.SmoothTransformation).save(base + ".png")
    return f'<img src="{base}.png" width="{size}" height="{size}" style="vertical-align: middle">'



def icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    """Load `icons/<name>.svg`, tinted `color` (default: current text color)."""
    color = color or _default_color()
    key = (name, color, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    result = QIcon(pixmap(name, color, size))
    _icon_cache[key] = result
    return result
