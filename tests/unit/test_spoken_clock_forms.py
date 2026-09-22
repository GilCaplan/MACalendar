"""Spoken clock forms the recogniser writes oddly — read the same on both tracks.

Cycle 35 (real usage, 2026-09-22): six of the real-usage board's eight
remaining generic-title failures lost a stated time to one of four shapes —
a compact clock ("910am", "230PM", and after a preposition a bare "830" /
"1040"), a dotted meridiem at the end of the sentence ("for 5 p.m."), and
"this coming thursday" landing a week late on the fast path. The deep
resolver and the fast parser each read them now, and this file pins that they
agree, and that a count in the same digits is never a clock.
"""
from __future__ import annotations

import datetime

import pytest

from assistant.engine.decompose_validate import resolve as R
from assistant.intent import rule_parser as RP

ANCHOR = datetime.datetime(2026, 8, 26, 11, 1)          # a Wednesday
TODAY = ANCHOR.date()


@pytest.mark.parametrize("said, start", [
    ("at 910am", "09:10"),
    ("at 230PM", "14:30"),
    ("at 1040", "10:40"),
    ("for 830, to go to daven pre-shacharit", "08:30"),   # shacharit is the morning
    ("for 830", "20:30"),                                 # bare 8 reads PM here, as "at 8" does
    ("for 1 p.m.", "13:00"),                              # the dotted meridiem at the end
    ("for 5 p.m. execute", "17:00"),
    ("at 8 a.m.", "08:00"),
    ("at 2000", "20:00"),
])
def test_the_deep_resolver_reads_the_form(said, start):
    assert R.resolve(said, ANCHOR, f"dentist {said}", action="dentist")["start_time"] == start


def test_the_deep_resolver_reads_a_compact_range():
    got = R.resolve("from 1030 to 1130", ANCHOR, "x", action="x")
    assert (got["start_time"], got["end_time"]) == ("10:30", "11:30")


@pytest.mark.parametrize("said", ["for 200 people", "buy 3 apples", "at 1899", "room 1040 booking"])
def test_a_count_in_the_same_digits_is_never_a_clock_on_the_deep_path(said):
    assert R.resolve(said, ANCHOR, said, action=said)["start_time"] is None


@pytest.mark.parametrize("said, start", [
    ("dentist at 910am tomorrow", "09:10"),
    ("dentist at 230PM tomorrow", "14:30"),
    ("meeting at 1040 on monday", "10:40"),
    ("call for 1 p.m. on sunday", "13:00"),
])
def test_the_fast_parser_reads_the_form(said, start):
    assert RP._extract_temporal(said, TODAY)["start_time"] == start


@pytest.mark.parametrize("said", ["dinner for 200 people tomorrow", "order 3 apples"])
def test_a_count_is_never_a_clock_on_the_fast_path(said):
    assert RP._extract_temporal(said, TODAY)["start_time"] is None


def test_this_coming_thursday_is_the_soonest_thursday_on_both_tracks():
    # Said on Wednesday 2026-08-26: the soonest Thursday is tomorrow, not the
    # one after. The recogniser read "coming" as "next".
    assert RP._extract_temporal("visit tal this coming thursday at 1 p.m.", TODAY)["date"] == "2026-08-27"
    assert RP._extract_temporal("office hour this coming sunday at 1pm", TODAY)["date"] == "2026-08-30"
    assert R.resolve("this coming thursday at 1 p.m.", ANCHOR, "x", action="x")["date"][:10] == "2026-08-27"


def test_the_compact_clock_is_blocked_from_the_title_on_the_fast_path():
    got = RP._extract_temporal("meeting at 1040 on monday", TODAY)
    assert any("1040" in "meeting at 1040 on monday"[a:b] for a, b in got["spans"])


def test_a_dotted_meridiem_at_the_end_counts_as_a_stated_clock():
    # `_CLOCK_MENTION_RE` decides whether a to-do with a clock is really an event.
    assert RP._CLOCK_MENTION_RE.search("walk the dog at 5 p.m.")
    assert RP._CLOCK_MENTION_RE.search("walk the dog at 910am")
    assert not RP._CLOCK_MENTION_RE.search("walk the dog at 5pmx")


# --- segmentation: the phrase has to be SEEN before either resolver reads it ---

import importlib

FS = importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")   # the package exports a function of the same name


@pytest.mark.parametrize("said, phrase", [
    ("Set a meeting on this coming Sunday for 1 p.m. TA, Office Hour", "for 1 p.m."),
    ("Sunday, set for 830, to go to Doven, pre-Shacharit", "for 830"),
    ("set a meeting for me tomorrow at 11 a.m. and also set meeting", "at 11 a.m."),
    ("please make a meeting for me at 1040 on monday the 13th", "at 1040"),
    ("set an appointment for tomorrow morning on tuesday at 910am", "at 910am"),
])
def test_segmentation_takes_the_whole_clock_phrase_out_of_the_action(said, phrase):
    # Before cycle 35 "at 11 a.m." matched only "at 11" and left "a.m." in the
    # action — the origin of the real-usage title 'meeting a.m'.
    clocks = [r.text for r in FS.find_time_refs(said) if r.kind == "clock"]
    assert phrase in clocks, clocks


@pytest.mark.parametrize("said", ["dinner for 200 people tomorrow", "for 2 hours tomorrow"])
def test_segmentation_never_takes_a_count_or_a_duration_as_a_clock(said):
    assert not [r for r in FS.find_time_refs(said) if r.kind == "clock"]
