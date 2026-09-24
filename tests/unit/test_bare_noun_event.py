"""A bare noun with a day or a clock is an event at the front door (2026-09-24).

"Dentist on the 15th at 4" carried no verb for the router, so it DEFERRED to
the model — right, but seconds later, and "Sorry, I couldn't read this part"
with the model down. Found verifying the tutorial. The rule is narrow on
purpose; each refusal below is a row it got wrong on the FastRule train half
before the guard existed.
"""
from __future__ import annotations

import pytest

from assistant.intent.rule_parser import RuleParserSkip


@pytest.fixture
def rp(registry_with_real_actions):
    from assistant.intent.rule_parser import RuleBasedParser
    return RuleBasedParser(registry_with_real_actions)


def _one(rp, text):
    r = rp.analyze(text, current_view="month")
    assert len(r.intents) == 1, r.intents
    return r.intents[0]


@pytest.mark.parametrize("text,title,clock", [
    ("Dentist on the 15th at 4", "dentist", "16:00"),
    ("Dentist tomorrow at 4", "dentist", "16:00"),
    ("team meeting in three weeks, all day", "team meeting", None),
])
def test_a_bare_noun_with_a_day_or_clock_is_an_event(rp, text, title, clock):
    action, intent = _one(rp, text)
    assert action == "create_event" and intent.title == title
    if clock:
        assert intent.start_time == clock


@pytest.mark.parametrize("text", [
    "birthday dinner from 6 to 8 next monday",       # the day was lost after a range
    "shedule physical therapy for next tuesday at ten thirty",   # a misheard verb
    "vet appointment takes all day march 5th",       # a verb it cannot title around
    "open house between 5 and 6:30 at the end of the month",    # time left in the title
    "milk",                                          # no day, no clock
])
def test_what_the_rule_leaves_to_the_model(rp, text):
    with pytest.raises(RuleParserSkip):
        rp.analyze(text, current_view="month")
