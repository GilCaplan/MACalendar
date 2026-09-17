"""Calendar — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class CalendarFeature(Feature):
    """The month/week/day grid. Pinned: an assistant with no calendar is nothing."""

    name = "calendar"
    label = "Calendar"
    icon = "calendar"
    order = 0
    pinned = True
    default_visible = True
