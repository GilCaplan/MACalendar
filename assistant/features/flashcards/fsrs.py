"""When a card comes back: FSRS-4.5 with its published default weights.

Picked on the options page (FSRS over SM-2) because it schedules from how
likely you are to remember a card NOW, not from a fixed ease multiplier, so a
card you keep getting right drifts out to months while a lapse costs less than
SM-2's reset to day one.

A card's memory is two numbers: STABILITY (days until recall drops to 90%) and
DIFFICULTY (1..10). Grades are 1 again, 2 hard, 3 good, 4 easy. At the 90%
target the next interval is the stability itself, which is why `interval()` is
a rounding of S.

The phone keeps a copy of this (`Features/Flashcards/FSRS.swift`) so a review
on a train moves the card at once; the Mac's answer replaces it on sync.
`tests/unit/test_flashcards.py` holds the two weight lists equal.
"""

from __future__ import annotations

import math

W = (0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031, 1.6474,
     0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755)
DECAY = -0.5
FACTOR = 19 / 81
#: An AGAIN, or a first look that was not easy, comes back inside the same sitting.
RELEARN_MINUTES = 10
MAX_DAYS = 36500


def _clamp_d(d: float) -> float:
    return min(10.0, max(1.0, d))


def retrievability(elapsed_days: float, stability: float) -> float:
    return (1 + FACTOR * max(0.0, elapsed_days) / stability) ** DECAY


def _init_d(g: int) -> float:
    return _clamp_d(W[4] - (g - 3) * W[5])


def next_state(stability: "float | None", difficulty: "float | None",
               elapsed_days: float, grade: int) -> "tuple[float, float]":
    """(stability, difficulty) after `grade`, from the state before it.
    `stability is None` is a card never reviewed."""
    if grade not in (1, 2, 3, 4):
        raise ValueError(f"grade must be 1..4, not {grade!r}")
    if stability is None or difficulty is None:
        return W[grade - 1], _init_d(grade)
    r = retrievability(elapsed_days, stability)
    d = difficulty - W[6] * (grade - 3)
    d = _clamp_d(W[7] * _init_d(4) + (1 - W[7]) * d)
    if grade == 1:
        s = (W[11] * difficulty ** -W[12] * ((stability + 1) ** W[13] - 1)
             * math.exp(W[14] * (1 - r)))
        s = min(s, stability)
    else:
        hard = W[15] if grade == 2 else 1.0
        easy = W[16] if grade == 4 else 1.0
        s = stability * (1 + math.exp(W[8]) * (11 - difficulty) * stability ** -W[9]
                         * (math.exp(W[10] * (1 - r)) - 1) * hard * easy)
    return max(0.1, s), d


def interval_days(stability: float) -> int:
    """Days to the next review at a 90% recall target (= S at FSRS's constants)."""
    return int(min(MAX_DAYS, max(1, round(stability))))
