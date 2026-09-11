"""The X0→X4 flow strip: the VALUE each stage handed the next.

Gil, 2026-09-10: *"add a cool visualization that X_i with its value moved on to
the next step and option to see in realtime the subcomponents progress."*

**Written because it had NO test at all.** The widget shipped into the panel and
nothing exercised it — which in this project is a known way to ship a bug green:
three defects in the HUD's history view passed because tests called handlers
instead of clicking controls. So every interaction here goes through
`QTest.mouseClick` on the real button, never through `_toggle`.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt                                    # noqa: E402
from PyQt6.QtTest import QTest                                 # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton          # noqa: E402

from assistant.calendar_ui import thinking_panel               # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=(True, False), ids=("dark", "light"))
def strip(qapp, request):
    """Both themes, because the lit/dim test compares against `theme.accent`
    and a widget that reads a colour off the wrong attribute raises INSIDE a Qt
    callback — which aborts the interpreter rather than failing a test. That is
    exactly how `_FlowStrip` took the app down once (`theme.muted`, which does
    not exist on `_Theme`)."""
    theme = thinking_panel._Theme(dark=request.param)
    return thinking_panel._FlowStrip(theme)


def _pill(strip, label) -> QPushButton:
    return strip._pills[label]


def _click(pill) -> None:
    QTest.mouseClick(pill, Qt.MouseButton.LeftButton)


def test_every_boundary_the_engine_publishes_has_a_pill(strip):
    """X0..X4, and the arrows between them.

    The names are the ones `engine/ARCHITECTURE.md` uses in every stage
    contract; a rename on either side must show up here rather than silently
    dropping a pill on the floor (`add_boundary` returns early on an unknown
    label, so a mismatch is INVISIBLE at runtime).
    """
    assert list(strip._pills) == ["X0", "X1", "X2", "X3", "X4"]


def test_a_pill_is_dim_until_its_value_arrives(strip):
    """A dim pill means "this stage did not hand anything on", which is the
    honest way to draw the FAST TRACK — it never produces X2 or X3, and
    lighting them would claim work that did not happen."""
    before = _pill(strip, "X2").styleSheet()
    strip.add_boundary({"label": "X2", "value": "2 items", "detail": "typed items"})
    after = _pill(strip, "X2").styleSheet()
    assert before != after
    assert strip._theme.accent in after and strip._theme.accent not in before
    # X3 was never published: it must still read as not-done.
    assert strip._theme.accent not in _pill(strip, "X3").styleSheet()


def test_clicking_a_pill_opens_its_value_and_clicking_again_closes_it(strip):
    strip.add_boundary({"label": "X1", "value": "book gym tomorrow at 7am",
                        "detail": "one repaired command string"})
    assert strip._detail.isHidden()

    _click(_pill(strip, "X1"))
    assert not strip._detail.isHidden()
    assert "book gym tomorrow at 7am" in strip._detail.text()
    assert "one repaired command string" in strip._detail.text()

    _click(_pill(strip, "X1"))
    assert strip._detail.isHidden()


def test_only_one_value_is_open_at_a_time(strip):
    """The card is a few hundred pixels wide; four open values is a wall."""
    strip.add_boundary({"label": "X1", "value": "the repaired string", "detail": ""})
    strip.add_boundary({"label": "X4", "value": "1 object", "detail": "ready to write"})
    _click(_pill(strip, "X1"))
    _click(_pill(strip, "X4"))
    assert not strip._detail.isHidden()
    assert "1 object" in strip._detail.text()
    assert "the repaired string" not in strip._detail.text()


def test_clicking_a_pill_with_no_value_yet_does_nothing(strip):
    """Mid-command, half the pills are empty. Clicking one must not open an
    empty panel and must not raise — a click handler that raises inside a Qt
    callback ABORTS THE INTERPRETER, which is how `_FlowStrip` took the whole
    app down once already (theme.muted, 2026-09-10)."""
    _click(_pill(strip, "X3"))
    assert strip._detail.isHidden()


def test_a_value_arriving_while_open_refreshes_what_is_shown(strip):
    """Boundaries land AS THEY HAPPEN, so a pill can be open when its own value
    is republished by a loop-back. It must show the new value, not the old."""
    strip.add_boundary({"label": "X2", "value": "1 item", "detail": "typed items"})
    _click(_pill(strip, "X2"))
    assert "1 item" in strip._detail.text()
    strip.add_boundary({"label": "X2", "value": "2 items", "detail": "typed items"})
    assert not strip._detail.isHidden()
    assert "2 items" in strip._detail.text()


def test_x0_is_seeded_from_the_input_because_no_stage_emits_it(strip):
    """Nothing publishes X0 — it is what arrived. Left to the boundary
    mechanism it would stay dim on every command."""
    assert strip._theme.accent not in _pill(strip, "X0").styleSheet()
    strip.seed_input("book gym tomorow")
    assert strip._theme.accent in _pill(strip, "X0").styleSheet()
    _click(_pill(strip, "X0"))
    assert "book gym tomorow" in strip._detail.text()


def test_an_unknown_boundary_label_is_ignored_rather_than_crashing(strip):
    """`Trace` publishes a `verdict` boundary the strip has no pill for, and
    anything added later will arrive here first. Dropping it must be quiet."""
    strip.add_boundary({"label": "verdict", "value": "committed", "detail": ""})
    strip.add_boundary({})
    assert strip._detail.isHidden()


def test_the_pills_are_buttons_not_labels_with_a_patched_event(strip):
    """The recorded rule, pinned. Reassigning `mousePressEvent` on a QLabel
    shadows a C++ virtual from Python and aborted the interpreter when the
    panel was rebuilt under a click. CLAUDE.md: connect `clicked`."""
    for label in ("X0", "X1", "X2", "X3", "X4"):
        assert isinstance(_pill(strip, label), QPushButton)


# ---------------------------------------------------------------------------
# The chain rail's marks
# ---------------------------------------------------------------------------

def test_a_skipped_step_fits_the_mark_it_is_drawn_in(qapp):
    """The tick, the spinner and the skipped mark share ONE 14x14 slot.

    That slot is fixed so swapping between them never resizes the row — which
    means whatever goes in it has to be a single glyph. It briefly held the
    WORD "skipped", centred in fourteen pixels, and rendered as "pp" on every
    step the command did not need. Caught by screenshotting the real widget,
    not by reading it.
    """
    from PyQt6.QtWidgets import QLabel
    theme = thinking_panel._Theme(dark=True)
    rail = thinking_panel._ChainRail("engine-v3", theme)
    rail.finish()                       # everything untouched becomes skipped

    marks = [state.text() for _i, _s, _ic, _t, _tl, _st, state, _sp in rail._rows]
    assert marks, "the rail drew no rows"
    for m in marks:
        assert len(m) <= 1, f"a mark must be one glyph to fit the slot, got {m!r}"

    tips = [state.toolTip() for _i, _s, _ic, _t, _tl, _st, state, _sp in rail._rows
            if state.text() == "–"]
    assert tips and all("skipped" in x for x in tips), (
        "the dash has to say what it means somewhere")
