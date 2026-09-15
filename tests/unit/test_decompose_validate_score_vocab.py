"""TASKS.md row 87: the decompose_validate traceability board's recurrence
vocabulary is hand-maintained (score.py is stdlib-only by design, so it
cannot import the gold's closed table at runtime — see both files' own
comments) and drifted behind it seven times, each one a real recurrence
reported as INVENTED because the check had never heard of that spelling.

This is the enforcement `score.py`'s own comment promises: every phrase the
gold's closed table (`datasets/normalization.py::RECURRENCES`) can actually
produce must be recognised by the board's `RECURRENCE_VOCAB` pattern. A form
added to the gold without a matching board update fails this test instead of
silently manufacturing false "invented" reports on a future run.
"""
from __future__ import annotations

import re

from assistant.engine.decompose_validate.datasets.normalization import RECURRENCES
from assistant.engine.decompose_validate.eval_metrics.score import RECURRENCE_VOCAB


def test_every_gold_recurrence_phrase_is_recognised():
    unrecognised = [phrase for phrase in RECURRENCES
                    if not re.search(RECURRENCE_VOCAB, phrase, re.I)]
    assert not unrecognised, (
        f"RECURRENCES has phrase(s) the board's RECURRENCE_VOCAB does not "
        f"recognise, so a correct recurrence would be reported as invented: "
        f"{unrecognised}. Update RECURRENCE_VOCAB in "
        f"decompose_validate/eval_metrics/score.py to match.")


def test_recurrence_vocab_is_still_independent_of_the_resolver():
    """The other half of the invariant score.py states in its own comment:
    this file must never import `resolve.py`, the code under test — only
    from the GOLD generator. A regression here would make the board agree
    with its own subject by construction, which is worse than no check."""
    import assistant.engine.decompose_validate.eval_metrics.score as score_mod
    src = score_mod.__file__
    with open(src) as f:
        text = f.read()
    assert "decompose_validate.resolve" not in text
    assert "decompose_validate import resolve" not in text
