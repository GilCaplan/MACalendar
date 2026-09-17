"""Resolved colours for one theme pass, handed down to every child widget.

The same shape (and the same reason) as `thinking_panel._Theme`: QSS cannot
read Python constants, so anything that styles itself needs the values already
resolved for light or dark. It is not imported from there because that class is
private to the trace card and carries stage colours this app has no use for.

No colour is invented here. Everything comes from `calendar_ui.styles`, so
changing the accent in Settings moves Jude too, and the app reads as one system
with the calendar and the thinking card rather than as a guest in its window.
"""

from __future__ import annotations

from assistant.calendar_ui import styles as _styles


class Theme:
    def __init__(self, dark: bool = True) -> None:
        s = _styles
        self.dark = dark
        self.bg = s.D_WHITE if dark else s.WHITE
        self.bg2 = s.D_GRAY_BG if dark else s.GRAY_BG
        self.surface = s.D_GRAY_LIGHT if dark else s.GRAY_LIGHT
        self.border = s.D_GRAY_BORDER if dark else s.GRAY_BORDER
        self.mid = s.D_GRAY_MID if dark else s.GRAY_MID
        self.text = s.D_GRAY_DARK if dark else s.GRAY_DARK
        self.text2 = s.D_GRAY_TEXT if dark else s.GRAY_TEXT
        self.accent = s.get_accent()
        self.on_accent = s.on_color(self.accent)
        self.destructive = s.DESTRUCTIVE_DARK if dark else s.DESTRUCTIVE
        self.mono = s.MONO_FONT
        self.radius_sm = s.RADIUS_SM
        self.radius_md = s.RADIUS_MD
        self.radius_lg = s.RADIUS_LG

    def soft_accent(self) -> str:
        """The accent at low alpha — a tint, for a surface that must read as
        "cited" without competing with the answer text next to it."""
        r, g, b = _styles._hex_to_rgb(self.accent)
        return f"rgba({r},{g},{b},{0.16 if self.dark else 0.13})"
