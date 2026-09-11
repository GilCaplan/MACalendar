"""X1' is written FOR three specific stages. These pin what it assumes of them.

`llmjudge/rewrite.py::_REWRITE_SYSTEM` tells the model how to shape a rewrite —
verb first, joined by "and", no definite article, digit times. Those are not
style preferences. Each one was MEASURED against the real chain on 2026-09-10,
and each exists because the alternative demonstrably fails.

**A prompt that instructs a model in downstream behaviour is a claim about that
behaviour.** If segmentation learns to split on full stops, or FastRule stops
tripping over "the", the prompt is teaching the model something false and should
change — and nothing else in the suite would notice. That is what this file is
for; it is the `test_artifact_claims.py` idea applied to a prompt.

Slow-ish: each case runs the real segment (+ decompose_validate) stage. That is
the point — a mock would pin the mock.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("registry_with_real_actions")


def _items(text):
    import assistant.engine as engine
    from assistant.engine.state import EngineState
    cfg = engine.load_config()
    st = EngineState(raw_text=text, text=text, source="test")
    engine._segment.run(st, cfg)
    return st.items


def _built(text):
    import assistant.engine as engine
    from assistant.engine.state import EngineState
    from assistant.engine.fastrule.build import build_all, Built
    cfg = engine.load_config()
    st = EngineState(raw_text=text, text=text, source="test")
    engine._segment.run(st, cfg)
    engine._decompose_validate.run(st, cfg)
    res = build_all(st.items)
    out = []
    for it, r in zip(st.items, res):
        if isinstance(r, Built):
            title = (getattr(r.intent, "title", None)
                     or (getattr(r.intent, "titles", None) or [None])[0])
            out.append((r.action, title, dict(it.slots or {})))
        else:
            out.append((type(r).__name__, None, {}))
    return out


# --- RULE 1 · every ask starts with its verb --------------------------------

def test_a_verbless_ask_is_neither_split_nor_built():
    """The prompt's first rule. Two failures, not one: the splitter merges the
    conjuncts, and FastRule cannot read an operation out of a bare noun."""
    assert len(_items("gym tomorrow at 7 and milk")) == 1, \
        "a verbless conjunct now splits — rule 1 of the rewrite prompt is stale"
    got = _built("dentist appointment next tuesday at 3pm")
    assert got[0][0] == "Defer", \
        "a verbless ask now builds — rule 1 is stale"


def test_verb_initial_asks_split_cleanly():
    items = _items("book gym tomorrow at 7 and add milk to my list")
    assert len(items) == 2, [i.text for i in items]
    items3 = _items("book gym at 7 and add milk to my list and call mum at 6pm")
    assert len(items3) == 3, [i.text for i in items3]


# --- RULE 2 · join with "and", never a full stop or comma -------------------

@pytest.mark.parametrize("joiner,expect", [
    (" and ", 2), (" and then ", 2),
    (". ", 1), (", ", 1),
])
def test_only_and_actually_splits(joiner, expect):
    """The counter-intuitive one, and the reason it is written down: a full stop
    reads as ONE ask, and the merged text even keeps the stray punctuation
    ("book gym . add milk to my list"). A model left to its own instincts writes
    sentences."""
    text = f"book gym tomorrow at 7{joiner}add milk to my list"
    assert len(_items(text)) == expect, text


# --- RULE 3 · no definite article before the subject ------------------------

def test_the_definite_article_corrupts_the_title():
    """"book the dentist next tuesday at three" produced the title
    "the dentist at three" — the time leaked into the subject. Without "the" it
    is clean. FastRule's title accuracy is its binding constraint, so this is
    worth a rule in the prompt."""
    clean = _built("book dentist next tuesday at 3pm")[0][1]
    assert clean and "3" not in clean and clean.strip().lower() == "dentist"


# --- RULE 4 · digit times resolve; worded hours may not ---------------------

def test_a_digit_time_resolves_a_clock():
    slots = _built("book dentist on next tuesday at 3pm")[0][2]
    assert slots.get("start_time") == "15:00", slots


def test_the_grounding_guard_permits_the_digit_the_prompt_asks_for():
    """Rule 4 tells the model to write "3pm" where the speaker said "three".
    The guard must not then reject it — a normalisation of something that WAS
    said is not the invention the guard exists to stop. Without the exemption
    every rewrite that obeyed the prompt would be thrown away."""
    from assistant.engine.llmjudge.rewrite import grounded
    said = "sort out the dentist thing next tuesday at three"
    assert grounded("book dentist on next tuesday at 3pm", said)
    # …and it still blocks a subject nobody said.
    assert not grounded("book physiotherapy on next tuesday at 3pm", said)
