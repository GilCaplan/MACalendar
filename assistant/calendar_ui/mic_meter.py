"""The live microphone meter beside the toolbar's mic button.

Gil, 2026-10-09: *"a cool UI that pops up according to the volume of the
audio … to be able to see that the audio is being captured so that I know
that I'm not just talking to the air."* While the pipeline listens, a row of
bars scrolls right to left, one per frame, each as tall as the mic was loud;
the phone draws the same thing in its recording chip (``VoiceButton.swift``,
``ListeningMeter``), with the same scale.

It reads, never writes: ``source()`` returns the latest chunk RMS that
``AudioCapture`` handed the pipeline (``Pipeline.mic_level``). Nothing here
touches the audio thread.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Callable, Optional

from PyQt6.QtCore import QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

#: dBFS shown as an empty bar and as a full one. Room noise sits near the
#: bottom, speech fills most of it — the same span the phone uses.
FLOOR_DB, CEIL_DB = -55.0, -10.0
#: A level above this counts as "sound arrived" (about −41 dBFS).
HEARD = 0.3
#: With nothing above HEARD for this long, the bars turn orange: no sound.
SILENT_AFTER_S = 2.0

BARS = 16
FRAME_MS = 33

_RED = QColor("#ff453a")
_ORANGE = QColor("#ff9f0a")


def to_level(rms: float) -> float:
    """Chunk RMS (0..1) → meter height (0..1) on the FLOOR_DB..CEIL_DB scale."""
    db = 20.0 * math.log10(max(rms, 1e-6))
    return min(1.0, max(0.0, (db - FLOOR_DB) / (CEIL_DB - FLOOR_DB)))


class MicLevelMeter(QWidget):
    """Hidden until ``start(source)``; ``stop()`` hides it again."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("mic_level_meter")
        self.setFixedSize(BARS * 4 + 2, 22)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setToolTip("Microphone level")
        self._source: Optional[Callable[[], float]] = None
        self._levels: deque = deque([0.0] * BARS, maxlen=BARS)
        self._level = 0.0
        self._started = 0.0
        self._heard = False
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    # -- control ---------------------------------------------------------

    def start(self, source: Callable[[], float]) -> None:
        self._source = source
        self._levels = deque([0.0] * BARS, maxlen=BARS)
        self._level = 0.0
        self._started = time.monotonic()
        self._heard = False
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._source = None
        self.hide()

    @property
    def silent(self) -> bool:
        """Listening for a while and nothing louder than the room has arrived."""
        return (not self._heard
                and time.monotonic() - self._started > SILENT_AFTER_S)

    # -- frame -----------------------------------------------------------

    def _tick(self) -> None:
        try:
            target = to_level(float(self._source())) if self._source else 0.0
        except Exception:  # noqa: BLE001 — a meter never takes the window down
            target = 0.0
        # Up at once, down over a few frames: reads as a voice, not flicker.
        self._level = target if target > self._level else self._level * 0.75 + target * 0.25
        if self._level > HEARD:
            self._heard = True
        self._levels.append(self._level)
        self.setToolTip("No sound is reaching the microphone" if self.silent
                        else "Microphone level")
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 — Qt's name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        h = self.height()
        colour = _ORANGE if self.silent else _RED
        for i, v in enumerate(self._levels):
            bar_h = 3.0 + v * (h - 4)
            c = QColor(colour)
            c.setAlphaF(0.45 + 0.55 * v)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(1 + i * 4, (h - bar_h) / 2, 2.5, bar_h), 1.25, 1.25)
        p.end()
