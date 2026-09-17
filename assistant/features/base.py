"""What it takes to be a feature surface — a tab on the phone, a panel on the Mac.

A FEATURE is one of this assistant's own surfaces: Calendar, Tasks, Coursework,
Workout, Timer, Teach, Jude. It is NOT an `Integration` — that is the convention
for hosting somebody else's PROGRAM (its own repo, its own server, its own
process), and it asks questions a tab cannot answer: where is the checkout, what
command starts it, which port do I wait on. Tasks has no checkout.

The two conventions share one idea and nothing else:

    a surface owns a FOLDER, declares itself ONCE to a REGISTRY,
    ships its own ROUTES, and the generic layer never learns its name.

Jude is the only thing that is both: Jude-the-program is an Integration,
Jude-the-tab is a Feature. They compose rather than compete.

## Structure is declared; only VISIBILITY travels

Which features exist, and their label, icon and order, are declared in CODE on
each platform. Only the on/off switch is shared state, served by
`GET /features` and changed by `PATCH /features/<name>`.

This split is deliberate and it is about the phone working on a train. If the
tab bar were built from the server's list, it could not be drawn until a
request came back — and when the Mac is asleep it would never be drawn at all.
So each platform knows its own surfaces offline, and asks the Mac only which of
them you have switched off.

## Pinned features

`pinned` means the surface cannot be hidden. Calendar and Tasks are what this
app IS; a switch that empties the app is not a feature. It is a declared
exception to a uniform mechanism rather than a special case in the tab bar —
`PATCH /features/calendar {"visible": false}` is refused, and says why.
"""

from __future__ import annotations

from abc import ABC


class Feature(ABC):
    """One surface. Subclass, set the class attributes, done."""

    #: Machine name. The identity everywhere: the config key, the URL segment,
    #: and what each client calls its own tab. Never an integer — the iOS tabs
    #: used magic ints and tag 3 was left as a hole when Settings stopped being
    #: a tab, which taught nobody anything and confused everybody.
    name: str = ""
    #: What a person calls it.
    label: str = ""
    #: SF Symbol name. The Mac panel carries its own icon; this one is the
    #: phone's, because SF Symbols is the vocabulary its tab bar speaks.
    icon: str = ""
    #: Display order in the tab bar. Sparse on purpose, so inserting a feature
    #: between two others does not renumber the rest.
    order: int = 0
    #: Cannot be switched off. See the module docstring.
    pinned: bool = False
    #: Whether a fresh install shows it. Jude is the one that ships off: it
    #: needs a checkout on the Mac, and a tab that can only say "not installed"
    #: is not a feature.
    default_visible: bool = True
    #: Does this feature have a panel in the Mac calendar window?
    #:
    #: A plain flag rather than `panel() is not None`, because `manifest()` is
    #: served by the API — a HEADLESS process — and resolving the panel class
    #: would import PyQt6 into it just to answer a question about a boolean.
    #: Teach is iOS-only; Jude's Mac surface is a separate window, not a panel.
    has_mac_panel: bool = True

    # -- visibility ------------------------------------------------------

    def visible(self) -> bool:
        from assistant.features import settings
        return True if self.pinned else settings.is_visible(
            self.name, self.default_visible)

    def set_visible(self, on: bool) -> None:
        """Raises ValueError for a pinned feature — the caller shows the message."""
        if self.pinned:
            raise ValueError(
                f"{self.label} can't be hidden — it is what this app is for.")
        from assistant.features import settings
        settings.set_visible(self.name, bool(on))

    # -- what it brings --------------------------------------------------

    def blueprint(self):
        """This feature's Flask routes, or None.

        Declared rather than duck-typed, for the same reason `Integration`
        declares it: a misspelled method would otherwise register NO ROUTES
        and still start cleanly, surfacing much later as 404s.
        """
        return None

    def panel(self):
        """The Mac panel CLASS (a `calendar_ui.feature_panel.FeaturePanel`
        subclass), or None.

        Imported LAZILY by the implementation, and called only by the Mac GUI —
        never by the API server, which has no display and no business importing
        Qt. `has_mac_panel` is what the manifest reports.
        """
        return None

    # -- what the clients read -------------------------------------------

    def manifest(self) -> dict:
        """One shape for every feature, so a client that can draw one can draw
        the next without a new code path — the same reason
        `Integration.status()` is a fixed dict."""
        return {
            "name": self.name,
            "label": self.label,
            "icon": self.icon,
            "order": self.order,
            "pinned": self.pinned,
            "visible": self.visible(),
            "mac": self.has_mac_panel,
        }
