"""The reply's `hint`: one coaching line the phone shows once, keyed on what
the engine just did (Gil, 2026-09-22, DEVQA Q41 — tips on iOS, and "a meeting
according to the other details with a bare title is fine").

Two codes, both title classes from the real-usage board. The pick is
`assistant.engine._hint`; the words are `assistant.tips.HINTS`. The card the
phone draws is downstream of this key exactly as the panel is downstream of
the trace: a client that does not know the key ignores it.
"""
from __future__ import annotations

from types import SimpleNamespace

import assistant.engine as engine
from assistant.engine.state import EngineState, ExecutedAction, Item


def _state(items, executed=()):
    st = EngineState(raw_text="x", source="test")
    st.items = list(items)
    st.executed = list(executed)
    return st


def _item(id, action=None, title=None, blocked=None, slots=None):
    return Item(id=id, kind="event", text="x", action=action,
                intent=SimpleNamespace(title=title) if title is not None else None,
                blocked=blocked, slots=dict(slots or {}))


# --- the pick, on a hand-built state ---------------------------------------

def test_a_committed_bare_title_earns_the_bare_title_hint():
    st = _state([_item("item_1", "create_event", "meeting")],
                [ExecutedAction("item_1", "create_event", "ok", True)])
    assert engine._hint(st)["code"] == "bare_title"


def test_a_title_that_names_something_earns_nothing():
    st = _state([_item("item_1", "create_event", "meeting with sam")],
                [ExecutedAction("item_1", "create_event", "ok", True)])
    assert engine._hint(st) is None


def test_a_bare_title_that_did_not_commit_earns_nothing():
    # Not executed (a not-found, an error): no event to improve the title of.
    st = _state([_item("item_1", "create_event", "meeting")],
                [ExecutedAction("item_1", "create_event", "no", False)])
    assert engine._hint(st) is None


def test_a_refused_title_earns_the_refused_hint_and_outranks_a_bare_one():
    held = _item("item_1", "create_event", "Appointment",
                 blocked="I couldn't tell what to call it")
    bare = _item("item_2", "create_event", "meeting")
    st = _state([bare, held], [ExecutedAction("item_2", "create_event", "ok", True)])
    assert engine._hint(st)["code"] == "title_refused"


def test_the_fastrule_flags_are_not_title_refusals():
    # "thanks" left alone is not a naming problem — coaching there would be
    # noise, which is the one thing a hint that "does not get in the way"
    # cannot afford.
    for kind in ("not_an_ask", "bad_item"):
        st = _state([_item("item_1", "unknown", blocked="not a calendar ask",
                           slots={"fastrule_result": kind})])
        assert engine._hint(st) is None, kind


def test_a_deferred_item_the_rescue_held_back_is_a_title_refusal():
    st = _state([_item("item_1", "create_event", "date",
                       blocked="I couldn't make out what to create from “…”",
                       slots={"fastrule_result": "deferred"})])
    assert engine._hint(st)["code"] == "title_refused"


# --- end to end, on the fast path (no model) ----------------------------------

def test_a_bare_meeting_commits_and_the_reply_carries_the_hint(registry_with_real_actions):
    # Q41: the event is created with its day and time, not refused — and the
    # reply says, once, how to get a better title next time.
    out = engine.run_transcript("set a meeting for me tomorrow at 4pm", source="test")
    assert out["actions"] == ["create_event"]
    assert out["hint"]["code"] == "bare_title"
    assert out["hint"]["headline"] and out["hint"]["body"]


def test_a_named_meeting_carries_no_hint(registry_with_real_actions):
    out = engine.run_transcript(
        "set a meeting with sam about the budget tomorrow at 4pm", source="test")
    assert out["actions"] == ["create_event"]
    assert out["hint"] is None


def test_a_trivial_reply_carries_no_hint_key_surprise(registry_with_real_actions):
    # The ignored / needs_edit / confirm replies are built elsewhere and do not
    # carry `hint`; the phone treats a missing key as none. Pin the shape so a
    # future edit that starts hinting on an empty command is a deliberate one.
    out = engine.run_transcript("execute", source="test")
    assert out.get("hint") is None
