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

    def panel(self):
        # Imported here and not at module scope: the API server builds this
        # registry and has no display, so importing Qt to answer a question
        # about a tab would pull PyQt6 into a headless process.
        from assistant.calendar_ui.workout_view import WorkoutView
        return WorkoutView

    def blueprint(self):
        from assistant.features.workout.routes import blueprint
        return blueprint
