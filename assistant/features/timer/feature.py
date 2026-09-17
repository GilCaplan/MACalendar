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

    def panel(self):
        # Imported here and not at module scope: the API server builds this
        # registry and has no display, so importing Qt to answer a question
        # about a tab would pull PyQt6 into a headless process.
        from assistant.calendar_ui.timer_view import TimerView
        return TimerView

    def blueprint(self):
        from assistant.features.timer.routes import blueprint
        return blueprint
