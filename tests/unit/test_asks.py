"""`assistant/intent/asks.py` — the ask gate the cut refuses a split on.

Every pinned case here was a real cut refusal: `every_part_is_an_ask` rejects
the WHOLE split when one part fails, so a wrong "not an ask" merges a
three-ask command back into one item.
"""
from assistant.intent.asks import is_an_ask, every_part_is_an_ask


def test_an_imperative_opening_with_do_is_an_ask():
    # "do" was read as the auxiliary of a tag question, so "i need to
    # schedule a haircut, change the air filter, and do the laundry" could
    # never be cut: the third part failed the gate and the split was refused.
    assert is_an_ask("do the laundry")
    assert is_an_ask("do the laundry the 3rd")
    assert every_part_is_an_ask(["schedule a haircut", "change the air filter",
                                 "do the laundry"])


def test_a_tag_question_is_still_not_an_ask():
    for tail in ("does that seem right", "is that ok", "do you have that",
                 "right?", "okay", "sound good"):
        assert not is_an_ask(tail), tail


def test_a_closer_is_still_not_an_ask():
    assert not is_an_ask("done and dusted")
    assert not is_an_ask("that's it")
