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
    assert 1 <= len(TIPS) <= 7
    for headline, body in TIPS:
        assert headline.strip() and body.strip()
        assert len(headline) <= 60
        assert len(body) <= 220
