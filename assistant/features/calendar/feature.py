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

    def panel(self):
        """None, although `has_mac_panel` is True — and the asymmetry is real.

        The calendar's Mac surface is FOUR widgets (month, week, day, agenda)
        plus the mode switcher that moves between them, not one panel sitting
        beside the others in the stack. It is the window's own furniture, so
        `window.py` builds it directly; the registry drives the feature panels
        around it.
        """
        return None

    def blueprint(self):
        from assistant.features.calendar.routes import blueprint
        return blueprint
