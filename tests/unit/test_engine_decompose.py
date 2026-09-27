"""Step 3 — decomposition: several things, or one thing × N."""

from __future__ import annotations

import pytest

import assistant.engine.decompose_validate.decompose as decompose
import assistant.engine.llm as engine_llm
from assistant.engine import load_config
from assistant.engine.state import EngineState, Item


@pytest.fixture
def cfg():
    return load_config()


def _run(items, cfg) -> EngineState:
    st = EngineState(raw_text="", text="")
    st.items = items
    return decompose.run(st, cfg)


def _event(text, id="item_1"):
    return Item(id=id, kind="event", text=text)


def _task(text, id="item_1"):
    return Item(id=id, kind="task", text=text)


# --- times are SEGMENTATION's to split (2026-09-26) ------------------------
# decompose used to split "walk the dog at 9am and 2:30pm" itself, by regex and
# by asking the model; segmentation's bounded enumeration does it now, so an
# event reaching decompose is ONE event and decompose never asks the model.

def test_decompose_leaves_a_two_time_event_alone_and_asks_no_model(cfg, monkeypatch):
    monkeypatch.setattr(engine_llm, "call_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM")))
    for text in ("walk the dog at 9am and 2:30pm",
                 "take Saba to physio at 10am and later on at 4:30pm today",
                 "lunch from 12:00 to 1:00 and bring the laptop",
                 "meeting with Tal and Ravid tomorrow at 3pm"):
        st = _run([_event(text)], cfg)
        assert len(st.items) == 1, text


def test_segmentation_splits_one_activity_at_several_times(cfg):
    from assistant.engine import segmentation
    for text, times in [
            ("walk the dog at 9am and 2:30pm", ["at 9am", "at 2:30pm"]),
            ("walk the dog at 6 in the evening and 7am", ["at 6 in the evening", "at 7am"]),
            ("water the plants at 9 in the morning and at 8 o'clock", ["at 9 in the morning", "at 8 o'clock"])]:
        st = EngineState(raw_text=text, text=text, source="test")
        segmentation.run(st, cfg)
        assert [i.text for i in st.items] == [st.items[0].text] * len(times), text
        assert all(t in i.time for t, i in zip(times, st.items)), (text, [i.time for i in st.items])


# --- task lists and quantities ---------------------------------------------

def test_task_list_splits_with_verb_handed_down(cfg):
    st = _run([_task("buy chicken and rice")], cfg)
    assert [it.text for it in st.items] == ["buy chicken", "buy rice"]
    assert [it.id for it in st.items] == ["item_1-1", "item_1-2"]


def test_idiom_is_one_task(cfg):
    st = _run([_task("buy fish and chips")], cfg)
    assert len(st.items) == 1


def test_quantity_is_one_task_with_units(cfg):
    st = _run([_task("buy 5 apples")], cfg)
    assert len(st.items) == 1
    assert st.items[0].slots["quantity"] == 5
    assert "5" not in st.items[0].text


def test_depth_is_bounded_to_one_split(cfg):
    """A sub-item is never split again: ids go one level deep."""
    st = _run([_task("buy chicken and rice and pasta")], cfg)
    assert all(it.id.count("-") <= 1 for it in st.items)


# --- reminder-clause stripping (cycle 8, notifications phase 3) -----------

def test_inline_reminder_clause_lands_in_slots():
    from assistant.engine.decompose_validate.decompose import _strip_reminder_clause
    from assistant.engine.state import Item
    it = Item(id="item_1", kind="event",
              text="book gym tomorrow at 6:30 and give me a heads-up half an hour before")
    _strip_reminder_clause(it)
    assert it.slots["reminder_minutes"] == 30
    assert it.text == "book gym tomorrow at 6:30"


def test_with_a_reminder_noun_form():
    from assistant.engine.decompose_validate.decompose import _strip_reminder_clause
    from assistant.engine.state import Item
    it = Item(id="item_1", kind="event",
              text="meeting with Dana Monday 9am with a 15 minute reminder")
    _strip_reminder_clause(it)
    assert it.slots["reminder_minutes"] == 15
    assert it.text == "meeting with Dana Monday 9am"


def test_leading_alert_me_hours_form():
    from assistant.engine.decompose_validate.decompose import _strip_reminder_clause
    from assistant.engine.state import Item
    it = Item(id="item_1", kind="event",
              text="Alert me 2 hours before my meeting on Tuesday with client")
    _strip_reminder_clause(it)
    assert it.slots["reminder_minutes"] == 120


def test_until_through_sentences_never_touched():
    # The whole reason the strip lives in decompose: a bare surviving
    # "before" would read as a recurrence-end marker in validate.
    from assistant.engine.decompose_validate.decompose import _strip_reminder_clause
    from assistant.engine.state import Item
    for txt in ("run daily until the end of September",
                "shiur weekly through October 3rd",
                "gym every monday until December"):
        it = Item(id="item_1", kind="event", text=txt)
        _strip_reminder_clause(it)
        assert "reminder_minutes" not in it.slots and it.text == txt


def test_bare_reminder_command_left_for_the_fallback():
    from assistant.engine.decompose_validate.decompose import _strip_reminder_clause
    from assistant.engine.state import Item
    it = Item(id="item_1", kind="event", text="remind me 30 minutes before")
    _strip_reminder_clause(it)
    assert "reminder_minutes" not in it.slots


def test_leading_courtesy_prefix_cleaned_after_strip():
    # C8 regression: "please remind me 1 hour before the meeting..." left
    # "please the meeting..." - a verbless mangle the LLM misread.
    from assistant.engine.decompose_validate.decompose import _strip_reminder_clause
    from assistant.engine.state import Item
    it = Item(id="item_1", kind="event",
              text="please remind me 1 hour before the meeting I hace tomorrow")
    _strip_reminder_clause(it)
    assert it.slots["reminder_minutes"] == 60
    assert it.text == "the meeting I hace tomorrow"


def test_a_list_split_is_one_errand_with_several_things(cfg):
    """Decompose splits a to-do only when every part reads "<errand verb> <a
    short thing>" (2026-09-26): 253 splits on the FastRule 7,200 train half
    were mostly remarks, times and weekdays cut at a comma."""
    st = _run([_task("buy 2 eggs, stamps, and protein bars")], cfg)
    assert [i.text for i in st.items] == ["buy eggs", "buy stamps", "buy protein bars"]
    assert st.items[0].slots.get("quantity") == 2          # the count is a slot, as for "buy 5 apples"
    for text in ("mark submit the report as done, finally got to it",
                 "remove change the air filter from my list, i already handled it",
                 "print the boarding pass every tuesday and thursday at around lunchtime",
                 "block out to back up the laptop, all day the 30th",
                 "send me an alert and hour before my next appointment"):
        assert len(_run([_task(text)], cfg).items) == 1, text
