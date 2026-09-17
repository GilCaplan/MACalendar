"""Tasks — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class TasksFeature(Feature):
    """The task list. Pinned for the same reason as the calendar.

    The Mac still calls its widget TodoView and its mode string "todo"; the
    name here is what both clients and the API use."""

    name = "tasks"
    label = "Tasks"
    icon = "checklist"
    order = 10
    pinned = True
    default_visible = True

    def panel(self):
        # Imported here and not at module scope: the API server builds this
        # registry and has no display, so importing Qt to answer a question
        # about a tab would pull PyQt6 into a headless process.
        from assistant.calendar_ui.todo_view import TodoView
        return TodoView

    def blueprint(self):
        from assistant.features.tasks.routes import blueprint
        return blueprint
