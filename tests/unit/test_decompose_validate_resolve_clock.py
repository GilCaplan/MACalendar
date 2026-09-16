"""resolve_clock — one item's time words -> "HH:MM".

Narrow, function-level tests for the clock-reading branch of `resolve.py`;
the stage-level splitting/merging behaviour lives in
`test_engine_decompose.py`.
"""
from __future__ import annotations

from assistant.engine.decompose_validate.resolve import resolve_clock


def test_a_period_separated_clock_reads_the_whole_number():
    """Real live usage, 2026-09-15: "11.15 AM" resolved to 15:00, not 11:15
    — the am/pm branch only accepted a COLON between hour and minute, so
    starting the match at "11" failed (next char is "." not ":" or "am"),
    and it matched "15 AM" instead, reading a hard-coded zero-minute 15:00.
    A period is the international way of writing the same separator and
    must be read the same way as a colon here."""
    assert resolve_clock("11.15 AM") == "11:15"
    assert resolve_clock("11.15am") == "11:15"
    assert resolve_clock("9.05pm") == "21:05"
    assert resolve_clock("movie tomorrow at 11.15 AM") == "11:15"


def test_a_bare_decimal_number_is_not_read_as_a_clock():
    """The period form requires am/pm right after it. Without that guard, an
    ordinary decimal or price would be misread as a time nobody said."""
    assert resolve_clock("that movie was $11.15") is None
    assert resolve_clock("it's 9.99 for the ticket") is None


def test_the_colon_form_is_unaffected():
    assert resolve_clock("11:15 AM") == "11:15"
    assert resolve_clock("9:05pm") == "21:05"
