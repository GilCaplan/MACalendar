"""Timer — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class TimerFeature(Feature):
    """Multi-project work tracking, earnings and counters."""

    name = "timer"
    label = "Timer"
    icon = "timer"
    order = 40
    pinned = False
    default_visible = True
