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
