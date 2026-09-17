"""Workout — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class WorkoutFeature(Feature):
    """Templates, live sessions and history."""

    name = "workout"
    label = "Workout"
    icon = "figure.strengthtraining.traditional"
    order = 30
    pinned = False
    default_visible = True
