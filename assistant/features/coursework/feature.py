"""Coursework — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class CourseworkFeature(Feature):
    """Courses and assignments — the university tab."""

    name = "coursework"
    label = "Coursework"
    icon = "graduationcap"
    order = 20
    pinned = False
    default_visible = True

    def panel(self):
        # Imported here and not at module scope: the API server builds this
        # registry and has no display, so importing Qt to answer a question
        # about a tab would pull PyQt6 into a headless process.
        from assistant.calendar_ui.coursework_view import CourseworkView
        return CourseworkView

    def blueprint(self):
        from assistant.features.coursework.routes import blueprint
        return blueprint
