"""FastSeg: a clock said with a number word (2026-09-24)."""
import pytest


# ---------------------------------------------------------------------------
# A clock said with a NUMBER WORD (2026-09-24). "ten past nine in the morning"
# read as 09:00 (the longer "nine in the morning" won), and "at seven pm",
# "at eleven.", "at four on saturday" found no clock at all — a real command,
# "tomorrow at one …", was saved with "nothing in the words said it".
# ---------------------------------------------------------------------------

import importlib as _il

_FS = _il.import_module("assistant.engine.segmentation.fastseg.fastseg")


@pytest.mark.parametrize("said,time_has", [
    ("on tuesday at ten past nine in the morning", "ten past nine in the morning"),
    ("dinner at seven pm", "at seven pm"),
    ("dinner at eight p.m. tomorrow", "at eight p.m."),
    ("meet at eleven.", "at eleven"),
    ("haircut at four on saturday", "at four"),
    ("lunch at one tomorrow", "at one"),
    ("remind me at nine to call", "at nine"),
])
def test_a_number_word_clock_is_a_time(said, time_has):
    (item,) = _FS.fastseg(said)
    assert time_has in item["time"]
    assert time_has.split()[-1].strip(".") not in item["action"].split()


@pytest.mark.parametrize("said", [
    "add scan at twelve weeks", "at one point i need to call mom", "i am at one with nature",
])
def test_a_number_word_that_is_not_a_clock_stays_a_word(said):
    refs = [r.kind for r in _FS.find_time_refs(said)]
    assert "clock" not in refs


@pytest.mark.parametrize("said,action", [
    ("dinner at 8 p.m.", "dinner"), ("dinner at eight p.m.", "dinner"),
    ("call mom at 11 a.m.", "call mom"),
])
def test_a_meridiem_ending_the_command_leaves_the_title(said, action):
    """The cut trims the final "." off the last piece, so the clock ran one
    character past it and was read as an EDGE reference — right time, never
    stripped from the title ('dinner at 8 p.m')."""
    (item,) = _FS.fastseg(said)
    assert item["action"] == action
