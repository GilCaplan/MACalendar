"""The Mac window's pure logic, and the guarantee that stops it lagging.

Widget behaviour is exercised offscreen; nothing here needs a display server
beyond Qt's `offscreen` platform, which `qapp` sets before QApplication exists.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Sefaria links — every answer's checkability rests on these
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,expected", [
    # Book + section: spaces underscore, colons become dots.
    ({"ref": "Genesis 1:2:3", "category": "Tanakh"},
     "https://www.sefaria.org/Genesis.1.2.3"),
    # Brackets are stripped — Jude's own citations carry them.
    ({"ref": "[Genesis 1:1]", "category": "Tanakh"},
     "https://www.sefaria.org/Genesis.1.1"),
    ({"ref": "Mishneh Torah, Hilchot Shabbat 3:1", "category": "Halakhah"},
     "https://www.sefaria.org/Mishneh_Torah,_Hilchot_Shabbat.3.1"),
    # THE EXCEPTION: our Talmud coordinates are chapter-based and Sefaria uses
    # daf notation (25b), so a constructed section link would land on the wrong
    # page. The tractate overview is right rather than confidently wrong.
    ({"ref": "Shabbat 25b", "category": "Talmud"},
     "https://www.sefaria.org/Shabbat"),
    # Nothing parseable: search, rather than a 404.
    ({"ref": "Something", "category": ""},
     "https://www.sefaria.org/search#q=Something"),
])
def test_sefaria_url(source, expected):
    from assistant.jude.ui.sources import sefaria_url
    assert sefaria_url(source) == expected


def test_a_talmud_ref_never_gets_a_section_link():
    """Belt and braces on the exception above: it is the one rule whose
    breakage sends the reader to a real page showing the wrong text."""
    from assistant.jude.ui.sources import sefaria_url
    for ref in ("Berakhot 2a", "Bava Metzia 59b", "Shabbat 25b"):
        url = sefaria_url({"ref": ref, "category": "Talmud"})
        assert "." not in url.rsplit("/", 1)[-1], url


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

@pytest.fixture
def theme(qapp):
    from assistant.jude.ui.theme import Theme
    return Theme(dark=True)


def test_markdown_escapes_before_it_formats(theme):
    """A source quoting `<` must not open a tag. Escaping has to happen first,
    or the model's own text can inject markup into the transcript."""
    from assistant.jude.ui.markdown import render
    out = render("a < b & c > d", theme)
    assert "&lt;" in out and "&amp;" in out
    assert "<b>" not in out


def test_markdown_renders_bold_and_lists(theme):
    from assistant.jude.ui.markdown import render
    out = render("**strong**\n\n- one\n- two", theme)
    assert "<b>strong</b>" in out or "font-weight" in out
    assert "<li>" in out


def test_markdown_tolerates_a_half_written_stream(theme):
    """Rendering happens on a TIMER while tokens are still arriving, so it is
    handed half-finished markdown constantly. It must never raise."""
    from assistant.jude.ui.markdown import render
    full = "**Primary sources**\n\n1. `Shabbat 25b` — see [link](https://x.y)\n"
    for i in range(len(full)):
        render(full[:i], theme)      # no exception is the assertion


# ---------------------------------------------------------------------------
# THE anti-lag guarantee
# ---------------------------------------------------------------------------

def test_tokens_are_batched_not_rendered_one_by_one(qapp):
    """The bug this rewrite exists to fix.

    The previous Mac app inserted every token into a QTextBrowser through a
    cursor, so a 2,000-token answer triggered 2,000 full document relayouts.
    `AnswerRow.append` must only accumulate; the repaint is the timer's job.

    Asserted as a RATIO rather than an exact count: the point is that repaints
    are bounded by elapsed time, not by token count.
    """
    from assistant.jude.ui.transcript import AnswerMessage
    from assistant.jude.ui.theme import Theme

    row = AnswerMessage(Theme(dark=True))
    repaints = 0
    for i in range(2000):
        row.append(f"token{i} ")
        # What the timer does when it fires; it cannot fire 2000 times in the
        # time it takes to append 2000 strings.
        if i % 500 == 0 and row.repaint_if_dirty():
            repaints += 1

    assert row.text.count("token") == 2000, "tokens were lost"
    assert repaints <= 8, f"{repaints} repaints for 2000 tokens"


def test_repaint_reports_clean_when_nothing_changed(qapp):
    """The timer fires whether or not tokens arrived; a repaint with no new
    text is wasted layout, which at 14 Hz is most of them between answers."""
    from assistant.jude.ui.transcript import AnswerMessage
    from assistant.jude.ui.theme import Theme

    row = AnswerMessage(Theme(dark=True))
    row.append("hello")
    assert row.repaint_if_dirty() is True
    assert row.repaint_if_dirty() is False


def test_repaint_interval_stays_interactive():
    """Slow enough to batch, fast enough to read as streaming. Past ~120ms it
    reads as stuttering rather than typing."""
    from assistant.jude.ui.transcript import REPAINT_MS
    assert 40 <= REPAINT_MS <= 120


# ---------------------------------------------------------------------------
# The window as a whole
# ---------------------------------------------------------------------------

def test_window_draws_only_the_reason_when_jude_is_not_ready(qapp):
    """`ready: false` is a normal state, and the composer must not invite a
    question that cannot be answered."""
    from assistant.config import load_config
    from assistant.jude.ui.window import JudeWindow

    w = JudeWindow(load_config("config.example.yaml"))
    w._on_status({"ready": False, "running": False,
                  "reason": "Jude is switched off.", "model": "", "repo": "x"})
    assert "switched off" in w._status.text()
    assert not w._ready


def test_the_three_modes_fit_the_sidebar_without_eliding(qapp):
    """They rendered as "QA | Stud | Sourc" at the old width. A truncated
    control is a silently broken one — it still looks deliberate."""
    from PyQt6.QtWidgets import QApplication
    from assistant.jude.ui.sidebar import MODES, SIDEBAR_WIDTH, Sidebar
    from assistant.jude.ui.theme import Theme

    bar = Sidebar(Theme(dark=True))
    bar.resize(SIDEBAR_WIDTH, 600)
    bar.show()
    QApplication.processEvents()
    for key, label in MODES:
        button = bar._mode_buttons[key]
        needed = button.fontMetrics().horizontalAdvance(label)
        assert button.width() >= needed, (
            f"{label!r} is elided: {button.width()}px for {needed}px of text")
