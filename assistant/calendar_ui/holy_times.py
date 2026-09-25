"""The yellow Shabbat / yom tov lines on the Day and Week grids.

Gil, 2026-09-24: *"automatically put a line onwards marking shabbat when it
starts/ends which updates automatically to phone location, important because
the exact minute is important. mark in yellow i think is good."*

A line at candle lighting on the eve, another at tzeit on the last day, each
with a small label, and a very faint yellow wash between them. The minutes come
from `assistant.observance.holy_windows` — the same `candle_lighting` / `tzeit`
the recurring-series skip in `db.py` uses — so the line is exactly where the
calendar starts refusing to book. Nothing here computes a sun time.

**Why read `observance` directly rather than the API.** The GUI runs on the
brain's machine and already reads the Hebrew calendar the same way
(`enumerate_holidays` in `week_view.refresh`). What it must NOT do is use the
module's in-process settings cache: the phone's position is written to
`location.json` by the API process, and this process's cache would never hear
about it. `settings_from_config()` re-reads the file, so a phone that has
travelled moves these lines too — `signature()` is how the views notice.

**Never guessed.** A window whose boundary cannot be computed is absent from
`holy_windows`, so no line is drawn for it.

**Drawn in the observance place's WALL CLOCK, not converted to this Mac's
zone.** Events are stored and drawn as naive local times, and the series skip
compares an event's naive start against candle lighting's wall-clock time at
the observance place. A line converted into the Mac's own zone would sit
somewhere the calendar does NOT start refusing whenever the two zones differ
(found in a simulator whose host clock was New York while the place was
Jerusalem: Shabbat drew at noon). With "Sundown follows this device" on, the
place and the phone are one zone and the question never arises.

Two pieces, because they belong at two different depths:

- `paint_tint()` is called from a column's own `paintEvent`, so the wash sits
  UNDER the event blocks and never dims them.
- `HolyTimesOverlay` is a mouse-transparent child raised ABOVE the blocks, so
  the line and its label read across an event — and a click still lands on the
  event beneath.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import assistant.calendar_ui.styles as _styles

logger = logging.getLogger(__name__)

#: The line and the label pill. A true yellow, not the amber the default
#: accent uses, so it cannot be mistaken for the current-time line — and a
#: deeper one on the light theme, where #FFD60A on white all but disappears.
LINE_COLOR = "#FFD60A"
LINE_COLOR_LIGHT = "#E0B000"


def line_color(dark: bool) -> QColor:
    return QColor(LINE_COLOR if dark else LINE_COLOR_LIGHT)
#: Label text on the yellow pill — dark in both themes, which is what keeps a
#: yellow label legible on a white grid.
LABEL_TEXT = "#1a1a1a"
#: The wash between the two lines. Faint on purpose: it marks the time, it
#: must not read as an event.
TINT_ALPHA_DARK = 20
TINT_ALPHA_LIGHT = 34


@dataclass(frozen=True)
class LocalWindow:
    """A holy window in the observance place's wall-clock time, ready to draw."""

    start: datetime.datetime     # naive, the place's wall clock
    end: datetime.datetime       # naive, the place's wall clock
    start_name: str
    end_name: str

    @property
    def start_label(self) -> str:
        # Truncated: never later than candle lighting.
        return f"{self.start_name} · {self.start:%H:%M}"

    @property
    def end_label(self) -> str:
        # Rounded up: never earlier than nightfall.
        end = self.end
        if end.second or end.microsecond:
            end = end.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        return f"{self.end_name} ends · {end:%H:%M}"


def _local(dt: datetime.datetime) -> datetime.datetime:
    """The place's wall-clock time, naive — the frame events are stored and drawn in."""
    return dt.replace(tzinfo=None)


def windows_for(start: datetime.date, end: datetime.date,
                israel: bool = True) -> List[LocalWindow]:
    """The holy windows touching [start, end], in wall-clock time. Empty on any failure."""
    try:
        from assistant import observance as ob
        settings = ob.settings_from_config()
        return [LocalWindow(_local(w.start), _local(w.end), w.start_name, w.end_name)
                for w in ob.holy_windows(start - datetime.timedelta(days=1),
                                         end + datetime.timedelta(days=1),
                                         settings, israel)]
    except Exception:
        logger.debug("holy windows unavailable; drawing none", exc_info=True)
        return []


def signature() -> str:
    """Changes whenever the windows' minutes would — the phone moved, or config did."""
    try:
        from assistant import observance as ob
        return ob.place_key(ob.settings_from_config())
    except Exception:
        return ""


def enabled(hebrew_config) -> bool:
    """The Settings switch; ON when unset (a config written before it existed)."""
    return bool(getattr(hebrew_config, "show_shabbat_times", True)) if hebrew_config else True


def for_day(windows: Iterable[LocalWindow], date: datetime.date) -> List[LocalWindow]:
    """The windows that overlap *date*'s 24 hours."""
    day0 = datetime.datetime.combine(date, datetime.time())
    day1 = day0 + datetime.timedelta(days=1)
    return [w for w in windows if w.start < day1 and w.end > day0]


def y_for(when: datetime.datetime, date: datetime.date, hour_height: float) -> float:
    """Pixel offset of *when* on *date*'s column, to the second, clamped to the day."""
    day0 = datetime.datetime.combine(date, datetime.time())
    secs = (when - day0).total_seconds()
    secs = max(0.0, min(secs, 24 * 3600.0))
    return secs / 3600.0 * hour_height


def paint_tint(painter: QPainter, date: datetime.date, windows: Iterable[LocalWindow],
               hour_height: float, width: int, dark: bool) -> None:
    """The faint wash between the lines — drawn by the column, under its events."""
    tint = QColor(LINE_COLOR)
    tint.setAlpha(TINT_ALPHA_DARK if dark else TINT_ALPHA_LIGHT)
    for w in for_day(windows, date):
        top = y_for(w.start, date, hour_height)
        bottom = y_for(w.end, date, hour_height)
        if bottom > top:
            painter.fillRect(QRectF(0, top, width, bottom - top), tint)


class HolyTimesOverlay(QWidget):
    """Mouse-transparent layer above the event blocks: the lines and their labels."""

    def __init__(self, date: datetime.date, parent: QWidget, hour_height: int,
                 font_px: int = 10):
        super().__init__(parent)
        self._date = date
        self._hour_height = hour_height
        self._font_px = font_px
        self._windows: List[LocalWindow] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.resize(parent.size())

    # -- state -----------------------------------------------------------
    def set_windows(self, windows: Iterable[LocalWindow]) -> None:
        self._windows = for_day(windows, self._date)
        self.setVisible(bool(self._windows))
        self.update()

    def set_hour_height(self, hour_height: int) -> None:
        self._hour_height = hour_height
        self.update()

    def lines(self) -> List[tuple]:
        """[(y, label, is_start), ...] this overlay draws — what a test asserts against."""
        out = []
        day0 = datetime.datetime.combine(self._date, datetime.time())
        day1 = day0 + datetime.timedelta(days=1)
        for w in self._windows:
            if day0 <= w.start < day1:
                out.append((y_for(w.start, self._date, self._hour_height), w.start_label, True))
            if day0 <= w.end < day1:
                out.append((y_for(w.end, self._date, self._hour_height), w.end_label, False))
        return out

    # -- paint -----------------------------------------------------------
    def paintEvent(self, _event):
        lines = self.lines()
        if not lines:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = bool(getattr(_styles, "_dark", True))
        color = line_color(dark)

        font = QFont(self.font())
        font.setPixelSize(self._font_px)
        font.setBold(True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        pad_x, pill_h = 4, fm.height() + 2

        for y, label, is_start in lines:
            left, right = QPointF(0, y), QPointF(self.width(), y)
            # A dark hairline under the yellow keeps it visible on a white grid
            # and across a yellow-ish event block alike.
            painter.setPen(QPen(QColor(0, 0, 0, 60 if dark else 45), 3))
            painter.drawLine(left, right)
            painter.setPen(QPen(color, 1.6))
            painter.drawLine(left, right)

            text = fm.elidedText(label, Qt.TextElideMode.ElideRight,
                                 max(self.width() - 2 * pad_x - 4, 10))
            pill_w = fm.horizontalAdvance(text) + 2 * pad_x
            # The label sits on the holy side of its line: below a start,
            # above an end — and is pushed back inside the column at the edges.
            top = y + 1 if is_start else y - pill_h - 1
            top = max(0.0, min(top, self.height() - pill_h))
            rect = QRectF(self.width() - pill_w - 2, top, pill_w, pill_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(LABEL_TEXT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
