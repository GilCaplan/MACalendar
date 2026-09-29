"""Monochrome icons for the toolbar and the sidebar, drawn at one size.

The toolbar mixed an emoji microphone, a text gear and a text sun, each at its
own size, and the sidebar's symbols started their labels at different places
(Gil, 2026-09-29: "these icons are not aligned", "could be more clean"). Each
icon here is drawn into a fixed square in the colour asked for, its INK scaled
to the same size, so a row of them reads as one set.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPen, QPixmap

_DPR = 2


def _canvas(size: int) -> "tuple[QPixmap, QPainter]":
    pm = QPixmap(size * _DPR, size * _DPR)
    pm.setDevicePixelRatio(_DPR)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    return pm, p


def glyph_icon(glyph: str, color: str, size: int = 18, ink: float = 14.0) -> QIcon:
    """`glyph` in `color`, its ink scaled to `ink` px and centred in `size`."""
    pm, p = _canvas(size)
    f = QFont()
    f.setPixelSize(100)
    box = QFontMetricsF(f).tightBoundingRect(glyph)
    if box.width() > 0 and box.height() > 0:
        f.setPixelSize(max(6, int(100 * ink / max(box.width(), box.height()))))
    p.setFont(f)
    p.setPen(QColor(color))
    b = QFontMetricsF(f).tightBoundingRect(glyph)
    p.drawText(QPointF((size - b.width()) / 2 - b.left(), (size - b.height()) / 2 - b.top()), glyph)
    p.end()
    return QIcon(pm)


def mic_icon(color: str, size: int = 18) -> QIcon:
    """A microphone: a capsule, the cradle arc and the stand."""
    pm, p = _canvas(size)
    c = QColor(color)
    s = size / 18.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(6.5 * s, 2 * s, 5 * s, 9 * s), 2.5 * s, 2.5 * s)
    pen = QPen(c, 1.6 * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    arc = QPainterPath()
    arc.arcMoveTo(QRectF(4 * s, 4 * s, 10 * s, 10 * s), 180)
    arc.arcTo(QRectF(4 * s, 4 * s, 10 * s, 10 * s), 180, 180)
    p.drawPath(arc)
    p.drawLine(QPointF(9 * s, 14 * s), QPointF(9 * s, 16 * s))
    p.drawLine(QPointF(6.5 * s, 16 * s), QPointF(11.5 * s, 16 * s))
    p.end()
    return QIcon(pm)
