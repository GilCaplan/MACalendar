"""The contract a Mac feature panel keeps.

One base class for the panels that live in the calendar window's stack —
Tasks, Timer, Coursework, Workout. The calendar's own month/week/day/agenda
widgets are NOT panels: they are four views of one feature, and they switch
between themselves rather than sitting beside each other in the tab row.

## What this replaces

Every panel used to be hand-wired into `window.py` in five places — import,
construct, `addWidget`, the toolbar button loop, and the `_set_view` dict —
with the contract enforced by nothing but `hasattr(self, "_todo_view")` guards
in `_apply_theme` and `_apply_ui_config`.

Which produced exactly the bug you would predict. **The reload verb was never
agreed**: `TodoView.refresh()` and `CourseworkView.refresh()`, but
`TimerView.reload()` and `WorkoutView.reload()`. So `window.py`'s refresh path
called `self._todo_view.refresh()` and nothing else — the other three panels
were never refreshed at all, and no guard could notice, because a `hasattr`
check for a method name you are not calling passes trivially.

`reload()` is the verb. Two of the four already used it; the other two keep
`refresh()` as their own name and delegate, so their existing callers are
undisturbed.

## Why this is not an ABC

`abc.ABCMeta` and PyQt6's `sip.wrappertype` are different metaclasses, and
combining them raises `TypeError: metaclass conflict` at class-definition
time. So the contract is a plain base with `NotImplementedError` in it —
enforced when a panel is first reloaded rather than when it is defined, which
is the best Qt allows without a custom metaclass nobody would thank us for.
"""

from __future__ import annotations

import inspect

from PyQt6.QtWidgets import QWidget


class FeaturePanel(QWidget):
    """One feature's panel in the calendar window's stack."""

    #: Matches `assistant/features/<name>/feature.py`. The registry uses it to
    #: tie a panel to its visibility flag and its toolbar button, so it must be
    #: the same string the config, the API and both clients use.
    feature_name: str = ""

    @classmethod
    def create(cls, db, *, config=None, dark: bool = False):
        """Build this panel, passing only the arguments it actually takes.

        The four panels grew different constructors — `TodoView(db, config=…)`,
        `TimerView(db)`, `CourseworkView(db, dark=…, font_size=…)`,
        `WorkoutView(db)` — which is precisely why the window could not build
        them in a loop and hand-wired each one instead.

        Rather than rewrite four large, working files to agree on a signature,
        the window asks for what it can offer and each panel takes what it
        wants. A panel with a genuinely unusual constructor overrides this.
        """
        accepted = inspect.signature(cls.__init__).parameters
        kwargs = {}
        if "config" in accepted:
            kwargs["config"] = config
        if "dark" in accepted:
            kwargs["dark"] = dark
        return cls(db, **kwargs)

    def reload(self) -> None:
        """Re-read this panel's data and redraw.

        THE contract verb. Called when the window refreshes, when the panel is
        shown, and after a voice command changes something underneath it.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement reload()")

    def apply_theme(self, dark: bool) -> None:
        """Restyle for light/dark. A panel with no theming of its own may
        legitimately do nothing, which is why this is not abstract."""

    def apply_ui_config(self, ui) -> None:
        """Font sizes and other UI constants from config."""
