"""The "how to talk to me" tips are downstream of the engine — enforced.

Every tip in `assistant/tips.py` is a factual claim about how the pipeline
behaves TODAY, verified live when written (see that module's docstring for
exactly how and where). If the engine's pipeline changes enough to bump
`BRAIN_VERSION`, a tip that was true yesterday is not guaranteed true
tomorrow — this is the guard that makes "go re-read the tips" a build
failure rather than a thing someone forgets, the same shape
`test_panel_agreement.py` already holds the thinking panel to.

When this goes red: read every tip in `assistant/tips.py` against the new
engine (live, via `assistant.engine.run_transcript` — the same way they
were verified originally, not by reasoning about the diff), fix or replace
whatever changed, and only then bump `TIPS_BRAIN_VERSION` to match.
"""

from __future__ import annotations

import assistant.trace as trace
from assistant.tips import TIPS, TIPS_BRAIN_VERSION


def test_tips_have_been_reviewed_for_the_current_engine():
    assert TIPS_BRAIN_VERSION == trace.BRAIN_VERSION, (
        f"assistant.trace.BRAIN_VERSION is {trace.BRAIN_VERSION!r} but "
        f"assistant/tips.py's TIPS were last verified against "
        f"{TIPS_BRAIN_VERSION!r}. Re-check every tip live against the new "
        "engine, update whatever changed, then bump TIPS_BRAIN_VERSION."
    )


def test_tips_are_short_and_non_empty():
    # Gil, 2026-09-16: "don't want to overload them with content" — a hard
    # ceiling keeps a future edit from quietly turning this into a manual.
    assert 1 <= len(TIPS) <= 5
    for headline, body in TIPS:
        assert headline.strip() and body.strip()
        assert len(headline) <= 60
        assert len(body) <= 220


def test_how_it_works_is_a_few_one_line_steps():
    # The "how it works" above the tips (Gil, 2026-09-24) is an overview,
    # not a second manual: three or four steps, ONE sentence each, each with
    # one spoken example — and the whole screen still about one phone screen.
    from assistant.tips import STEPS
    assert 3 <= len(STEPS) <= 4
    for text, example in STEPS:
        assert text.strip() and example.strip()
        assert len(text) <= 90 and text.count(". ") == 0, text
        assert len(example) <= 90
        assert "“" in example, f"step has no spoken example: {text!r}"
    words = sum(len(t) + len(e) for t, e in STEPS) + sum(len(h) + len(b) for h, b in TIPS)
    assert words <= 1400, f"{words} characters — that is past one phone screen"


def test_hints_are_short_and_carry_a_reply_shape():
    # The contextual hints are held to the same ceiling as the tips: one
    # line the phone can draw in a card above the mic, not a paragraph.
    from assistant.tips import HINTS, hint, payload
    assert set(HINTS) == {"bare_title", "title_refused"}
    for code, (headline, body) in HINTS.items():
        assert headline.strip() and body.strip()
        assert len(headline) <= 60
        assert len(body) <= 220
        assert hint(code) == {"code": code, "headline": headline, "body": body}
    assert hint("no_such_code") is None
    from assistant.tips import STEPS
    got = payload()
    assert got["brain"] == TIPS_BRAIN_VERSION
    assert got["steps"] == [{"text": t, "example": e} for t, e in STEPS]
    assert [t["headline"] for t in got["tips"]] == [h for h, _ in TIPS]
    assert set(got["hints"]) == set(HINTS)


def test_a_bare_title_is_only_the_kind_of_thing():
    # 'meeting' commits (DEVQA Q41) and earns the hint; a title that names
    # anything at all does not — the hint must never nag a good command.
    from assistant.tips import is_bare_title
    for bare in ["meeting", "Meeting", "a meeting", "an appointment",
                 "the event", "my appointment", "Appointment", "call",
                 "reminder", "meeting."]:
        assert is_bare_title(bare), bare
    for named in ["meeting with sam", "dentist", "lunch", "gym",
                  "walk the dog", "budget meeting", "", "  ", None]:
        assert not is_bare_title(named), named


def test_the_mac_dialog_shows_how_it_works_above_the_tips():
    # One source: the Mac dialog reads `assistant.tips` directly, and must
    # draw every step (numbered, with its example) BEFORE the first tip.
    import pytest
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QLabel
    from assistant.calendar_ui.tips_dialog import TipsDialog
    from assistant.tips import STEPS

    _app = QApplication.instance() or QApplication([])
    dlg = TipsDialog()
    shown = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    at = {text: i for i, text in enumerate(shown)}
    for n, (text, example) in enumerate(STEPS, start=1):
        assert f"{n}. {text}" in at and example in at
    for headline, body in TIPS:
        assert headline in at and body in at
    assert at[f"{len(STEPS)}. {STEPS[-1][0]}"] < at[TIPS[0][0]]
    # Done still closes it — clicked, not called (the button moved out of the
    # scrolling body so it stays in reach when the words scroll).
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QPushButton
    done = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Done")
    dlg.show()
    QTest.mouseClick(done, Qt.MouseButton.LeftButton)
    assert dlg.result() == dlg.DialogCode.Accepted
    dlg.deleteLater()
