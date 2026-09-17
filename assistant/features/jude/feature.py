"""Jude — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class JudeFeature(Feature):
    """The Judaic study assistant.

    The one feature that is also an INTEGRATION: this is the TAB, while
    `assistant/jude/` hosts the program behind it. Two different switches, and
    they mean different things — `features.jude` is whether you want the
    surface, `jude.enabled` is whether the program is wired up at all.

    Off by default: it needs a checkout on the Mac, and a tab that can only
    say "not installed" is not a feature.

    Its Mac surface is a SEPARATE WINDOW (`python -m assistant.jude.app`), not
    a panel in the calendar, so `panel()` is None while `mac` is still true in
    spirit — studying a sugya is not something you do inside a calendar."""

    name = "jude"
    label = "Jude"
    icon = "books.vertical"
    order = 60
    pinned = False
    has_mac_panel = False
    default_visible = False
