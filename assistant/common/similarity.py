"""How close two short texts are, word by word — for SCORING, never for deciding.

Gil, 2026-09-25: *"title should be a similarity rather than binary score."* An
exact-match line scores "checkup" for "annual checkup" the same as "gym" for
"annual checkup", so a cycle that fixes truncation and one that fixes a wrong
name read alike. Word-overlap precision / recall / F1 (the SQuAD answer
metric) keeps the difference, and its two halves name the defect:

  precision  how much of what was BUILT belongs    — low when words leak in
             ("i have the dentist", "dentist with dana")
  recall     how much of the GOLD made it          — low when words are cut
             ("checkup" for "annual checkup")

Words are lowercased runs of letters, digits and apostrophes, compared as
sets. Nothing in the engine may branch on this: it is an instrument.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9']+")


def words(text) -> set:
    return set(_WORD.findall(str(text or "").lower()))


def token_prf(gold, built) -> "tuple[float, float, float]":
    """(precision, recall, F1) of `built`'s words against `gold`'s. Two empty
    texts agree completely; one empty and one not share nothing."""
    g, b = words(gold), words(built)
    if not g and not b:
        return 1.0, 1.0, 1.0
    common = len(g & b)
    if not common:
        return 0.0, 0.0, 0.0
    p, r = common / len(b), common / len(g)
    return p, r, 2 * p * r / (p + r)
