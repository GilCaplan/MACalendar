"""List management is thrown out as junk, with the reason kept (DEVQA Q52)."""
from __future__ import annotations

import pytest

from assistant.intent.junk import LIST_MANAGEMENT, junk_reason


@pytest.mark.parametrize("words", [
    "Delete To Do List", "get rid of a list", "Get rid of the list, Google.",
    "Remove list from the database.", "Create a new list", "I want you to create a list for me",
    "What list do I have", "What do my lists look like?", "save the new list",
    "open grocery list", "Give me the names of my lists", "destroy this list",
])
def test_list_management_is_junk(words):
    assert junk_reason(words) == LIST_MANAGEMENT


@pytest.mark.parametrize("words", [
    "add water to my Kroger list",            # something ON a list: a to-do
    "Make a new list for school supplies",    # named for its contents (Q33)
    "Create a list of books to be ordered",
    "start a new list of dog breeds",
    "Read shopping list items.",              # reading a list: a to-do query
    "remove apple from the list",
    "put carrots on my list",
])
def test_everything_else_is_not(words):
    assert junk_reason(words) is None


def test_the_front_door_defers_it_and_segmentation_marks_why():
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    import types
    from assistant.engine import segmentation as S
    from assistant.engine.state import EngineState
    assert FastRule(RULE_THRESHOLD).run("open grocery list").reason == "junk"
    st = EngineState(raw_text="x", text="create a new list, and then put walk the dog on my to do list",
                     source="test")
    S.run(st, types.SimpleNamespace(engine=types.SimpleNamespace()))
    assert st.items[0].kind == "other" and st.items[0].slots["junk"] == LIST_MANAGEMENT
    assert st.items[1].kind == "task"
