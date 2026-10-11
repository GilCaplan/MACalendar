"""Ranker — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class RankerFeature(Feature):
    """Rank any table by a recipe, narrowed to the numbers read from a picture."""

    name = "ranker"
    label = "Ranker"
    icon = "list.number"
    order = 45
    pinned = False
    default_visible = True

    def panel(self):
        # Imported lazily: the API server builds this registry with no display.
        from assistant.calendar_ui.ranker_view import RankerView
        return RankerView

    def blueprint(self):
        from assistant.features.ranker.routes import blueprint
        return blueprint
