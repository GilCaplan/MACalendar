"""Flashcards — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class FlashcardsFeature(Feature):
    """Subjects of sets of cards, studied one set, several or all at once."""

    name = "flashcards"
    label = "Flashcards"
    icon = "rectangle.on.rectangle.angled"
    mac_icon = "flashcards"
    order = 25          # beside Coursework: both are studying
    pinned = False
    default_visible = True

    def panel(self):
        # Imported lazily: the API server builds this registry with no display.
        from assistant.calendar_ui.flashcards_view import FlashcardsView
        return FlashcardsView

    def blueprint(self):
        from assistant.features.flashcards.routes import blueprint
        return blueprint
