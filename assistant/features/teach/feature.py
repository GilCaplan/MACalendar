"""Teach — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class TeachFeature(Feature):
    """The labelling game, which is where the classifier's only non-circular
    training data comes from.

    iOS ONLY — `panel()` returns None. That is a real asymmetry rather than an
    oversight, and the manifest reports it so a client need not guess."""

    name = "teach"
    label = "Teach"
    icon = "brain.head.profile"
    order = 50
    pinned = False
    default_visible = True
