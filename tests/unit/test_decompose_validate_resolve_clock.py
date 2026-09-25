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


def test_a_bare_period_clock_with_no_am_pm_is_read_too():
    """Gil's call, 2026-09-15: a bare "H.MM" (a spoken 24-hour time like
    "14.30") is read the same way a bare "H:MM" already is, without
    requiring am/pm. Mirrors fastseg's matching bare-clock pattern exactly,
    including the >=9 vs bare-hour-PM-bias split."""
    assert resolve_clock("14.30") == "14:30"      # >=9: taken as 24-hour
    assert resolve_clock("meeting at 14.30") == "14:30"
    assert resolve_clock("5.30") == "17:30"        # <9: the PM-bias heuristic


def test_a_bare_decimal_number_is_now_read_as_a_clock_by_design():
    """The accepted trade for the fix above: without am/pm or a colon to
    disambiguate, "$11.15" and "11.15" are the same shape, and there is no
    general way to tell a price from a time. `resolve_clock` itself does not
    range-check the minute — "9.99" comes back as the syntactically-shaped
    but nonsensical "09:99" — but nothing crashes over it:
    `decompose_validate._resolve_onto_intent` and FastRule's own
    construction both already catch a validator refusing a value and leave
    it be rather than propagate the exception (the SAME safety net cycles
    18/19 rely on for a model's bad guess). The cost is a silently dropped
    price, not a crash."""
    assert resolve_clock("that movie was $11.15") == "11:15"
    # 2026-09-22 (Gil: "invalid clock should be handled by validate_decompose"):
    # the reader itself refuses a minute over 59 or an hour over 23 now, so a
    # price that is not even clock-shaped is dropped HERE, not left for the
    # validator downstream. "9.99" is no reading at all.
    assert resolve_clock("it's 9.99 for the ticket") is None

    from assistant.actions.calendar.intent import CalendarIntent
    import pytest
    with pytest.raises(Exception, match="out of range"):
        CalendarIntent(title="x", start_time="09:99")


def test_the_colon_form_is_unaffected():
    assert resolve_clock("11:15 AM") == "11:15"
    assert resolve_clock("9:05pm") == "21:05"


def test_a_range_is_read_to_its_end_clock_not_to_the_end_of_the_sentence():
    """"between 2 and 4 this afternoon" read its end as "4 this afternoon",
    the range failed, and the afternoon WINDOW replaced it (12:00-17:00);
    "from 6 to 8 tonight" became 18:00-19:00 (2026-09-25). The words after
    the end clock still set the half of the day."""
    import datetime as dt
    from assistant.engine.decompose_validate import resolve as R
    day = dt.date(2026, 9, 9)
    for said, want in [("between 2 and 4 this afternoon", ("14:00", "16:00")),
                       ("from 6 to 8 tonight", ("18:00", "20:00")),
                       ("from 9 to 11 tomorrow morning", ("09:00", "11:00")),
                       ("from 10 to noon on friday", ("10:00", "12:00")),
                       ("from 3 to 4pm", ("15:00", "16:00"))]:
        v = R.resolve(said, day, said, action=said)
        assert (v["start_time"], v["end_time"]) == want, said
