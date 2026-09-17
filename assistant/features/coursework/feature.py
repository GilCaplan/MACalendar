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
