"""Board D scores a generic target the way Gil ruled it (DEVQA Q38).

The corpus records the literal referring phrase as the title — "that
appointment" — because that is what was said, and the scorer demanded an
object carrying it. The engine refuses such a target on purpose ("a title
that names nothing is refused, everywhere"; "deleting is destructive"), so
23 of the seeded baseline's 127 wrong rows were the engine obeying the ruling,
and the loop's one FIXED row was the model round handing back
`delete_event "that one"` — the thing the front door had vetoed.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def _correct():
    """`board_d` is a SCRIPT with an env block at import — it redirects every
    store to a scratch dir, sets the model priority and seed, and turns
    OBSERVANCE OFF for the process. Imported bare into the suite it turned
    Shabbat off for eighteen later tests (2026-09-22). So the import happens
    under a saved-and-restored environment, and only the scorer leaves."""
    saved = dict(os.environ)
    os.environ.setdefault("BOARD_D_SCRATCH",
                          os.path.join(os.environ.get("TMPDIR", "/tmp"), "board_d_scorer_test"))
    try:
        from assistant.engine.llmjudge.experiments.board_d import _correct as fn
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return fn


def _row(action, title, generic=False, **slots):
    s = {"title": title, **slots}
    if generic:
        s["generic_target"] = True
    return {"expect": {"action": action, "slots": s}}


def test_a_refusal_is_right_on_a_generic_target(_correct):
    row = _row("delete_event", "that appointment", generic=True)
    assert _correct((), row)
    assert _correct(None, row)


def test_an_object_carrying_the_generic_phrase_is_wrong(_correct):
    row = _row("delete_event", "that appointment", generic=True)
    assert not _correct((("delete_event", "that appointment"),), row)
    assert not _correct((("delete_event", "that one"),), _row("delete_event", "that one", generic=True))


def test_a_resolved_target_is_right_on_a_generic_row(_correct):
    """FastRule's contract: the LLM may RESOLVE an anaphor to a real title; it
    must never overturn the refusal by handing back the same empty target."""
    row = _row("delete_event", "that appointment", generic=True)
    assert _correct((("delete_event", "dentist"),), row)
    assert not _correct((("create_event", "dentist"),), row)      # wrong action stays wrong


def test_ordinary_rows_are_scored_as_before(_correct):
    row = _row("delete_event", "dentist appointment")
    assert not _correct((), row)
    assert _correct((("delete_event", "dentist appointment"),), row)
    assert not _correct((("delete_event", "haircut"),), row)
    assert not _correct((("create_event", "dentist appointment"),), row)
