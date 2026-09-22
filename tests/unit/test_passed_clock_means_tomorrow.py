"""Q42, rules 2 and 3 (Gil, 2026-09-22): a clock with no day word is today
unless it has already passed, then tomorrow — on both tracks — and a compact
clock keeps its meaning in every spacing the recogniser produces.

Gil, verbatim: *"at 5pm today if no date or day given, default is
today/tomorrow whichever is closer to 5pm like if 5pm passed then we are
referring to tomorrow"*. A NAMED day is never touched; that is the past-date
bump's job and a different question.
"""
from __future__ import annotations

import datetime
import importlib
from types import SimpleNamespace

import pytest
from freezegun import freeze_time

from assistant.engine.decompose_validate import object_rules as OR
from assistant.engine.decompose_validate import resolve as R
from assistant.engine.state import EngineState, Item
from assistant.intent import rule_parser as RP

FS = importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")


def _item(text, time):
    return Item(id="item_1", kind="event", text=text, time=time)


def _state():
    return EngineState(raw_text="x", source="test")


# --- deep path: the validate rule -------------------------------------------

def test_a_clock_already_past_rolls_to_tomorrow():
    now = datetime.datetime(2026, 9, 22, 18, 0)
    intent = SimpleNamespace(date="2026-09-22", start_time="17:00")
    st = _state()
    OR._rule_passed_clock_means_tomorrow(st, _item("add an event", "for 5 p.m."), intent, now)
    assert intent.date == "2026-09-23"
    assert any(f.rule == "passed_clock_tomorrow" for f in st.fixes)


def test_a_clock_still_to_come_stays_today():
    now = datetime.datetime(2026, 9, 22, 13, 28)
    intent = SimpleNamespace(date="2026-09-22", start_time="17:00")
    OR._rule_passed_clock_means_tomorrow(_state(), _item("add an event", "for 5 p.m."), intent, now)
    assert intent.date == "2026-09-22"


@pytest.mark.parametrize("time_words", ["today at 5 p.m.", "tomorrow at 5pm", "on friday at 5",
                                        "on the 3rd at 5pm", "every day at 5pm"])
def test_a_named_day_is_never_touched(time_words):
    now = datetime.datetime(2026, 9, 22, 18, 0)
    intent = SimpleNamespace(date="2026-09-22", start_time="17:00")
    OR._rule_passed_clock_means_tomorrow(_state(), _item("meeting", time_words), intent, now)
    assert intent.date == "2026-09-22"


# --- fast path: the SPEC floor, end to end ------------------------------------

def _warm():
    from assistant.engine import llm as _llm
    rp = _llm.get_rule_parser()
    if rp is not None:
        rp.analyze("book gym tomorrow at 7am", current_view="month")


def test_the_fast_path_floors_a_passed_clock_to_tomorrow(registry_with_real_actions):
    import assistant.engine as engine
    _warm()                                       # spaCy before the clock freezes
    with freeze_time("2026-09-22 18:00:00", tick=True):
        out = engine.run_transcript("add an event for 5 p.m.", source="test")
    assert out["actions"] == ["create_event"], out["message"]
    assert "Sep 23" in out["message"], out["message"]


def test_the_fast_path_keeps_a_coming_clock_today(registry_with_real_actions):
    import assistant.engine as engine
    _warm()
    with freeze_time("2026-09-22 13:28:00", tick=True):
        out = engine.run_transcript("add an event for 5 p.m.", source="test")
    assert out["actions"] == ["create_event"], out["message"]
    assert "Sep 22" in out["message"], out["message"]


# --- rule 3: the spaced compact clock on all three readers --------------------

ANCHOR = datetime.datetime(2026, 8, 26, 11, 1)


@pytest.mark.parametrize("said, start", [("at 9 10 am", "09:10"), ("at 2 30 pm", "14:30"),
                                         ("at 910am", "09:10")])
def test_the_spaced_compact_clock_reads_the_same_everywhere(said, start):
    assert R.resolve(said, ANCHOR, f"dentist {said}", action="dentist")["start_time"] == start
    assert RP._extract_temporal(f"dentist {said} tomorrow", ANCHOR.date())["start_time"] == start
    clocks = [r.text for r in FS.find_time_refs(f"dentist {said} tomorrow") if r.kind == "clock"]
    assert said in clocks, clocks
