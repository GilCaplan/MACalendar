"""assistant/common — the shared helpers hold exactly what their copies held."""
from __future__ import annotations

from assistant.common import wordlists as W


def test_weekdays_are_date_weekday_order():
    assert W.WEEKDAY_INDEX == {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                               "friday": 4, "saturday": 5, "sunday": 6}
    assert W.WEEKDAYS == tuple(W.WEEKDAY_INDEX)


def test_weekday_abbreviations_are_the_ones_the_copies_carried():
    assert W.WEEKDAY_ABBR_INDEX == {**W.WEEKDAY_INDEX, "mon": 0, "tue": 1, "tues": 1, "wed": 2,
                                    "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}


def test_months_one_based_with_abbreviations_and_sept():
    assert W.MONTH_INDEX["january"] == 1 and W.MONTH_INDEX["december"] == 12 and len(W.MONTH_INDEX) == 12
    assert W.MONTH_ABBR_INDEX["oct"] == 10 and W.MONTH_ABBR_INDEX["sept"] == 9 and W.MONTH_ABBR_INDEX["may"] == 5
    assert len(W.MONTH_ABBR_INDEX) == 12 + 11 + 1        # "may" is its own abbreviation


def test_clock_arithmetic_and_the_two_edge_policies():
    from assistant.common.timeutil import clamp_day, to_hhmm, to_minutes, wrap_day
    assert to_minutes("14:30") == 870 and to_minutes("09:05:59") == 545
    assert to_hhmm(870) == "14:30" and to_hhmm(0) == "00:00"
    assert to_hhmm(wrap_day(23 * 60 + 30 + 60)) == "00:30"      # the next day's clock
    assert to_hhmm(clamp_day(23 * 60 + 30 + 60)) == "23:59"     # the day's last minute


def test_jsonl_tail_reads_what_was_added_and_survives_a_torn_line(tmp_path):
    from assistant.common.jsonl import tail
    p = tmp_path / "bus.jsonl"
    p.write_text('{"a": 1}\n\n{"b": 2}\n{"torn": ')
    got, off = tail(str(p), 0)
    assert got == [{"a": 1}, {"b": 2}]
    with open(p, "a") as f:
        f.write('\n{"c": 3}\n')
    more, off2 = tail(str(p), off)
    assert more == [{"c": 3}] and off2 > off
    p.write_text("")                                  # trimmed: restart from its end
    assert tail(str(p), off2) == ([], 0)


def test_title_similarity_separates_a_cut_word_from_a_wrong_name():
    from assistant.common.similarity import token_prf
    assert token_prf("annual checkup", "annual checkup") == (1.0, 1.0, 1.0)
    p, r, f = token_prf("annual checkup", "checkup")         # truncated: all built words belong
    assert p == 1.0 and r == 0.5 and round(f, 3) == 0.667
    p, r, _ = token_prf("dentist", "i have the dentist")     # leaked in: all gold words kept
    assert r == 1.0 and p == 0.25
    assert token_prf("annual checkup", "gym") == (0.0, 0.0, 0.0)
    assert token_prf("", "") == (1.0, 1.0, 1.0) and token_prf("x", "")[2] == 0.0
