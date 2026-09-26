"""Unit tests for RuleBasedParser — no LLM, no DB required.

All 7 spec cases plus edge cases.
Expected dates are computed relative to real today so no datetime mocking needed.
ContextMemory is reset by the autouse fixture in conftest.py.
"""
from __future__ import annotations

import datetime

import pytest

from assistant.intent.rule_parser import (
    RULE_THRESHOLD,
    RuleBasedParser,
    RuleParserSkip,
)
from assistant.intent.context import context_memory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tomorrow() -> str:
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parser(isolated_registry):
    """RuleBasedParser with all real actions registered.

    isolated_registry clears global_registry during the test, so we re-populate
    it manually from the already-imported action classes.
    """
    from assistant.actions.calendar.action import (
        CreateEventAction, UpdateEventAction, DeleteEventAction, QueryScheduleAction
    )
    from assistant.actions.todo.action import (
        CreateTodoAction, CompleteTodoAction, DeleteTodoAction, UpdateTodoAction,
        QueryTodoAction, AddSubtaskAction, CompleteSubtaskAction, DeleteSubtaskAction,
    )
    from assistant.actions.clarify import ClarifyAction

    for cls in [
        CreateEventAction, UpdateEventAction, DeleteEventAction, QueryScheduleAction,
        CreateTodoAction, CompleteTodoAction, DeleteTodoAction, UpdateTodoAction,
        QueryTodoAction, AddSubtaskAction, CompleteSubtaskAction, DeleteSubtaskAction,
        ClarifyAction,
    ]:
        isolated_registry._actions[cls.action_name] = cls

    return RuleBasedParser(isolated_registry)


# ---------------------------------------------------------------------------
# Spec test case 1: create_event fast path
# ---------------------------------------------------------------------------

def test_schedule_meeting_tomorrow_at_3pm(parser):
    """'Schedule a meeting tomorrow at 3 PM' → create_event, fast path."""
    result = parser.analyze("Schedule a meeting tomorrow at 3 PM", current_view="month")

    assert result.confidence >= RULE_THRESHOLD
    assert not result.missing_slots
    assert len(result.intents) == 1

    action_name, intent = result.intents[0]
    assert action_name == "create_event"
    assert intent.date == _tomorrow()
    assert intent.start_time == "15:00"
    assert "meeting" in intent.title.lower()


# ---------------------------------------------------------------------------
# Spec test case 2: update_event with anaphora
# ---------------------------------------------------------------------------

def test_move_it_to_friday_resolves_anaphora(parser):
    """'Move it to Friday' → update_event; match_title resolved from memory."""
    context_memory.update_event(42, "dentist", "2026-04-01")

    result = parser.analyze("Move it to Friday", current_view="month")

    # Anaphora penalty → correct partial handoff (< threshold)
    assert "update_event" in result.raw_slots
    assert result.raw_slots["update_event"].get("match_title") == "dentist"


# ---------------------------------------------------------------------------
# Spec test case 3: delete_todo
# ---------------------------------------------------------------------------

def test_delete_grocery_list(parser):
    """'Delete my grocery list' → delete_todo."""
    result = parser.analyze("Delete my grocery list", current_view="todo")

    assert "delete_todo" in result.raw_slots
    slots = result.raw_slots["delete_todo"]
    assert "grocery" in slots.get("match_title", "").lower()


# ---------------------------------------------------------------------------
# Spec test case 4: query_schedule fast path
# ---------------------------------------------------------------------------

def test_what_do_i_have_today(parser):
    """'What do I have today' → query_schedule, fast path."""
    result = parser.analyze("What do I have today", current_view="month")

    assert result.confidence >= RULE_THRESHOLD
    assert not result.missing_slots
    assert len(result.intents) == 1

    action_name, intent = result.intents[0]
    assert action_name == "query_schedule"
    assert intent.scope == "today"


# ---------------------------------------------------------------------------
# Spec test case 5: create_todo bare verb
# ---------------------------------------------------------------------------

def test_call_mom(parser):
    """'Call mom' → an EVENT at 09:00, fast path (DEVQA Q47, Gil 2026-09-24:
    "call mum is an event at a default time like 9"). It was a to-do until then."""
    result = parser.analyze("Call mom", current_view="month")

    assert result.confidence >= RULE_THRESHOLD
    assert not result.missing_slots

    action_name, intent = result.intents[0]
    assert action_name == "create_event"
    assert "mom" in intent.title.lower() and intent.start_time == "09:00"


# ---------------------------------------------------------------------------
# Spec test case 6: create_todo with due_date
# ---------------------------------------------------------------------------

def test_buy_milk_tomorrow(parser):
    """'Buy milk tomorrow' → create_todo with due_date."""
    result = parser.analyze("Buy milk tomorrow", current_view="month")

    assert result.confidence >= RULE_THRESHOLD
    assert not result.missing_slots

    action_name, intent = result.intents[0]
    assert action_name == "create_todo"
    assert intent.due_date == _tomorrow()
    assert "milk" in intent.titles[0].lower()


# ---------------------------------------------------------------------------
# Spec test case 7: update_event with time range
# ---------------------------------------------------------------------------

def test_reschedule_meeting_with_time_range(parser):
    """'Reschedule my meeting with John from 3 pm to 5 pm' → update_event."""
    result = parser.analyze(
        "Reschedule my meeting with John from 3 pm to 5 pm",
        current_view="month",
    )

    assert "update_event" in result.raw_slots
    slots = result.raw_slots["update_event"]
    assert slots.get("new_start_time") == "15:00"
    assert slots.get("new_end_time") == "17:00"


# ---------------------------------------------------------------------------
# Complexity gate
# ---------------------------------------------------------------------------

def test_a_four_way_compound_is_refused(parser):
    """Was "more than 12 content words → skip". That word-count gate was
    REMOVED (2026-09-07): length is not evidence of multiplicity, and it
    fired before the atomicity layer could speak. This sentence is still
    refused — but now because it genuinely IS four requests, which is the
    reason that generalises.
    """
    # 13+ distinct semantic words: schedule, meeting, John, remind, buy, milk,
    # call, dentist, add, gym, session, tomorrow, noon
    long = (
        "I want to schedule a meeting with John and also remind me to buy milk "
        "and then call the dentist and furthermore please add a gym session tomorrow at noon"
    )
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    res = FastRule(RULE_THRESHOLD).run(long)
    assert not res.committed, "a four-part command must not fast-commit"


# ---------------------------------------------------------------------------
# Query scope variants
# ---------------------------------------------------------------------------

def test_query_schedule_week(parser):
    """'What's on my schedule this week' → query_schedule scope=week."""
    result = parser.analyze("What's on my schedule this week", current_view="month")

    assert result.confidence >= RULE_THRESHOLD
    _, intent = result.intents[0]
    assert intent.scope == "week"


def test_query_schedule_tomorrow(parser):
    """'What do I have tomorrow' → query_schedule scope=tomorrow."""
    result = parser.analyze("What do I have tomorrow", current_view="month")

    assert result.confidence >= RULE_THRESHOLD
    _, intent = result.intents[0]
    assert intent.scope == "tomorrow"


# ---------------------------------------------------------------------------
# Multi-intent split
# ---------------------------------------------------------------------------

def test_multi_intent_buy_and_call(parser):
    """'Buy milk and call mom' → a to-do and an event (Q47: a call to a person
    is an event)."""
    result = parser.analyze("Buy milk and call mom", current_view="month")

    action_names = [name for name, _ in result.intents]
    assert sorted(action_names) == ["create_event", "create_todo"]


# ---------------------------------------------------------------------------
# STT shorthand expansion
# ---------------------------------------------------------------------------

def test_stt_expansion_tmrw(parser):
    """'Schedule mtg tmrw at 3 PM' expands shorthands correctly."""
    result = parser.analyze("Schedule mtg tmrw at 3 PM", current_view="month")

    assert "create_event" in result.raw_slots
    assert result.raw_slots["create_event"].get("date") == _tomorrow()


# ---------------------------------------------------------------------------
# [TASKS VIEW] prefix stripped
# ---------------------------------------------------------------------------

def test_tasks_view_prefix_stripped(parser):
    """Pipeline's [TASKS VIEW] prefix is removed before parsing."""
    result = parser.analyze("[TASKS VIEW] what tasks do I have today", current_view="todo")

    assert result.confidence >= RULE_THRESHOLD
    action_name = list(result.raw_slots.keys())[0]
    assert action_name in ("query_todos", "query_schedule")


# ---------------------------------------------------------------------------
# Anaphor with no memory → partial result (not a skip)
# ---------------------------------------------------------------------------

def test_anaphora_no_memory_returns_partial(parser):
    """'Move it to Friday' with empty memory → update_event, match_title unresolved."""
    # No memory seeded — context_memory reset by autouse fixture
    result = parser.analyze("Move it to Friday", current_view="month")

    assert "update_event" in result.raw_slots
    # match_title stays as "it" because there's nothing to resolve
    match = result.raw_slots["update_event"].get("match_title", "").lower()
    assert match in ("it", "")


# ---------------------------------------------------------------------------
# parse() raises RuleParserSkip on low-confidence / missing slots
# ---------------------------------------------------------------------------

def test_parse_raises_skip_for_low_confidence(parser):
    """parse() raises RuleParserSkip when confidence < RULE_THRESHOLD or missing slots."""
    # Ambiguous command — no time and no clear target
    try:
        result = parser.analyze("move something", current_view="month")
        if result.confidence < RULE_THRESHOLD or result.missing_slots:
            with pytest.raises(RuleParserSkip):
                parser.parse("move something", current_view="month")
    except RuleParserSkip:
        pass  # complexity gate or no-match → also a valid skip


# ---------------------------------------------------------------------------
# Full create_event fast path via public parse()
# ---------------------------------------------------------------------------

def test_parse_high_confidence_returns_intents(parser):
    """parse() returns intent list directly when fast-path fires."""
    intents = parser.parse("schedule standup tomorrow at 9 AM", current_view="month")
    assert intents[0][0] == "create_event"
    _, intent = intents[0]
    assert intent.start_time == "09:00"
    assert intent.date == _tomorrow()


# ---------------------------------------------------------------------------
# create_event end_time auto-fill
# ---------------------------------------------------------------------------

def test_create_event_end_time_autofilled(parser):
    """When no end time is given, CalendarIntent auto-fills end = start + 1h."""
    result = parser.analyze("Schedule dentist tomorrow at 2 PM", current_view="month")

    assert result.confidence >= RULE_THRESHOLD
    _, intent = result.intents[0]
    assert intent.end_time == "15:00"  # 14:00 + 1h


# ---------------------------------------------------------------------------
# delete_event vs delete_todo disambiguation
# ---------------------------------------------------------------------------

def test_cancel_calendar_event(parser):
    """'Cancel my dentist appointment' → delete_event (calendar signal)."""
    result = parser.analyze("Cancel my dentist appointment", current_view="month")

    assert "delete_event" in result.raw_slots


def test_delete_todo_item(parser):
    """'Delete my grocery task' → delete_todo (todo signal)."""
    result = parser.analyze("Delete my grocery task", current_view="month")

    assert "delete_todo" in result.raw_slots


# ---------------------------------------------------------------------------
# Regression: Bug 2026-04-03 — generic calendar word must not become match_title
# ---------------------------------------------------------------------------

def test_delete_event_by_time_not_generic_title(parser):
    """'can you delete the event at 6pm today' → delete_event with match_start_time=18:00.

    The word 'event' is a generic placeholder and must NOT be used as match_title.
    The time (18:00) and date (today) should be extracted instead.
    """
    today = datetime.date.today().isoformat()
    result = parser.analyze("can you delete the event at 6pm today", current_view="month")

    assert "delete_event" in result.raw_slots
    slots = result.raw_slots["delete_event"]
    # "event" must not be used as match_title
    assert slots.get("match_title", "").lower() != "event"
    # Time and date should be filled
    assert slots.get("match_start_time") == "18:00"
    assert slots.get("match_date") == today
    # Fast path should fire (no missing required slots)
    assert not result.missing_slots
    assert result.confidence >= RULE_THRESHOLD


def test_extend_event_by_start_time(parser):
    """'extend the 1pm event to 3pm' → update_event, match_start_time=13:00, new_end_time=15:00."""
    result = parser.analyze("extend the 1pm event to 3pm", current_view="month")

    assert "update_event" in result.raw_slots
    slots = result.raw_slots["update_event"]
    # Identified by start time, not by generic title "event"
    assert slots.get("match_start_time") == "13:00"
    assert slots.get("match_title", "").lower() != "event"
    # End time changed, start time NOT changed
    assert slots.get("new_end_time") == "15:00"
    assert "new_start_time" not in slots
    # Fast path fires
    assert not result.missing_slots
    assert result.confidence >= RULE_THRESHOLD


def test_lengthen_named_event(parser):
    """'lengthen team sync to 10am' → update_event; 'to 10am' → new_end_time, NOT new_start_time."""
    result = parser.analyze("lengthen team sync to 10am", current_view="month")

    assert "update_event" in result.raw_slots
    slots = result.raw_slots["update_event"]
    # The key semantic: "to 10am" is the new end time, not a reschedule target
    assert slots.get("new_end_time") == "10:00"
    assert "new_start_time" not in slots


def test_delete_event_relative_clause_skips_to_llm(parser):
    """'delete the event you create today on friday' — relative clause → RuleParserSkip.

    Sentences with a relative clause ('you create') are too ambiguous for the
    rule parser and must be routed to the LLM.
    """
    with pytest.raises(RuleParserSkip):
        parser.analyze("delete the event you create today on friday", current_view="month")


# ---------------------------------------------------------------------------
# Regression: Bug 2026-04-12 — bare day-of-week + time must resolve to FUTURE
# ---------------------------------------------------------------------------

def _next_weekday(weekday: int) -> str:
    """Return the ISO date of the next occurrence of weekday (Mon=0…Sun=6).

    If today IS that weekday, return today (not +7 days).
    """
    today = datetime.date.today()
    days_ahead = (weekday - today.weekday()) % 7
    return (today + datetime.timedelta(days=days_ahead)).isoformat()


def test_create_event_bare_weekday_with_time_resolves_future(parser):
    """'Schedule a meeting on wednesday at 3pm' → date = upcoming Wednesday, not last Wednesday.

    Regression for bug where Recognizers-Text returned a datetime type and the
    parser blindly took the first (past) value instead of the future one.
    """
    result = parser.analyze("Schedule a meeting on wednesday at 3pm", current_view="month")

    assert "create_event" in result.raw_slots
    date = result.raw_slots["create_event"].get("date")
    assert date is not None
    assert date >= datetime.date.today().isoformat(), (
        f"Expected future/today date, got past date: {date}"
    )
    assert date == _next_weekday(2), f"Expected next Wednesday ({_next_weekday(2)}), got {date}"


def test_update_event_bare_weekday_with_time_resolves_future(parser):
    """'Update the meeting on wednesday at 5:15pm' → match_date = upcoming Wednesday.

    This is the exact scenario that triggered the original bug report.
    """
    result = parser.analyze(
        "update content creation meeting on wednesday at 5:15pm", current_view="month"
    )

    assert "update_event" in result.raw_slots
    slots = result.raw_slots["update_event"]
    # Either match_date or new_date should be the upcoming Wednesday
    date = slots.get("match_date") or slots.get("new_date") or slots.get("date")
    assert date is not None
    assert date >= datetime.date.today().isoformat(), (
        f"Expected future/today date, got past date: {date}"
    )
    assert date == _next_weekday(2), f"Expected next Wednesday ({_next_weekday(2)}), got {date}"


def test_create_event_bare_friday_with_time_resolves_future(parser):
    """'Schedule gym on friday at 7am' → date = upcoming Friday."""
    result = parser.analyze("Schedule gym on friday at 7am", current_view="month")

    assert "create_event" in result.raw_slots
    date = result.raw_slots["create_event"].get("date")
    assert date is not None
    assert date >= datetime.date.today().isoformat(), (
        f"Expected future/today date, got past date: {date}"
    )
    assert date == _next_weekday(4), f"Expected next Friday ({_next_weekday(4)}), got {date}"


# ---------------------------------------------------------------------------
# create_todo: priority extraction
# ---------------------------------------------------------------------------

def test_create_todo_urgent_keyword_sets_high_priority(parser):
    """'Add urgent task: submit report' → create_todo priority=high."""
    result = parser.analyze("Add urgent task submit report", current_view="todo")

    assert "create_todo" in result.raw_slots
    slots = result.raw_slots["create_todo"]
    assert slots.get("priority") == "high", f"Expected high, got {slots.get('priority')}"


def test_create_todo_high_priority_keyword(parser):
    """'Buy milk high priority' → create_todo priority=high."""
    result = parser.analyze("Buy milk high priority", current_view="month")

    assert "create_todo" in result.raw_slots
    slots = result.raw_slots["create_todo"]
    assert slots.get("priority") == "high"


def test_create_todo_medium_priority_keyword(parser):
    """'Add task call dentist medium priority' → create_todo priority=medium."""
    result = parser.analyze("Add task call dentist medium priority", current_view="todo")

    assert "create_todo" in result.raw_slots
    slots = result.raw_slots["create_todo"]
    assert slots.get("priority") == "medium"


def test_create_todo_with_due_date_and_priority(parser):
    """'Buy milk tomorrow urgent' → create_todo with due_date + priority=high."""
    result = parser.analyze("Buy milk tomorrow urgent", current_view="month")

    assert "create_todo" in result.raw_slots
    slots = result.raw_slots["create_todo"]
    assert slots.get("due_date") == _tomorrow()
    assert slots.get("priority") == "high"


# ---------------------------------------------------------------------------
# update_todo: priority, due date, list extraction
# ---------------------------------------------------------------------------

def test_update_todo_set_priority_to_high(parser):
    """'Set grocery priority to high' → update_todo new_priority=high."""
    result = parser.analyze("Set grocery priority to high", current_view="todo")

    assert "update_todo" in result.raw_slots
    slots = result.raw_slots["update_todo"]
    assert slots.get("new_priority") == "high", f"Expected high, got {slots.get('new_priority')}"


def test_update_todo_set_priority_to_medium(parser):
    """'Change grocery task priority to medium' → update_todo new_priority=medium."""
    result = parser.analyze("Change grocery task priority to medium", current_view="todo")

    assert "update_todo" in result.raw_slots
    slots = result.raw_slots["update_todo"]
    assert slots.get("new_priority") == "medium"


def test_update_todo_set_due_date(parser):
    """'Set due date of grocery task to tomorrow' → update_todo new_due_date=tomorrow."""
    result = parser.analyze("Set due date of grocery task to tomorrow", current_view="todo")

    assert "update_todo" in result.raw_slots
    slots = result.raw_slots["update_todo"]
    assert slots.get("new_due_date") == _tomorrow(), (
        f"Expected {_tomorrow()}, got {slots.get('new_due_date')}"
    )


def test_update_todo_move_to_general(parser):
    """'Move grocery task to general list' → update_todo new_list=general."""
    result = parser.analyze("Move grocery task to general list", current_view="todo")

    assert "update_todo" in result.raw_slots
    slots = result.raw_slots["update_todo"]
    assert slots.get("new_list") == "general", f"Expected general, got {slots.get('new_list')}"


# ---------------------------------------------------------------------------
# create_todo: general list keyword
# ---------------------------------------------------------------------------

def test_create_todo_someday_goes_to_general(parser):
    """'Add learn Spanish someday' → create_todo list_name=general."""
    result = parser.analyze("Add learn Spanish someday", current_view="todo")

    assert "create_todo" in result.raw_slots
    slots = result.raw_slots["create_todo"]
    assert slots.get("list_name") == "general"


def test_f9_filler_and_courtesy_never_hide_the_command(parser):
    """209 of 540 simple-tier abstains were leading filler/courtesy blocking
    the ^-anchored routing (measured, F9). The command behind them parses."""
    p = parser
    assert p.analyze("um i need to return the rental car").intents
    assert p.analyze("could you tell me what's on my calendar next week"
                     ).intents[0][0] == "query_schedule"
    assert p.analyze("let's do birthday dinner next monday at 7pm"
                     ).intents[0][0] == "create_event"
    assert p.analyze("book piano lesson for tommorow at 8pm").intents


# ---------------------------------------------------------------------------
# A BARE ordinal date — "the 30th" with no preposition
#
# Filed 2026-09-17 (TASKS.md): `"renew the passport the 15th"` created the task
# with NO due date, on the Today list, at confidence 0.95 — committed instantly
# and indistinguishable from a task given no date at all. `"ON the 15th"` works,
# because the DateTime recogniser resolves that form and returns NOTHING for the
# bare one, and `_extract_temporal` had no fallback for it. Measured on the
# FastRule 7,200 train half: 174 atomic write rows, 117 of them deferred
# below-threshold for want of the date.
# ---------------------------------------------------------------------------

class TestBareOrdinalDate:
    """`the Nth` is a date in the same this-month-or-next sense as `on the Nth`."""

    @staticmethod
    def _expected(day: int) -> str:
        today = datetime.date.today()
        if day >= today.day:
            return today.replace(day=day).isoformat()
        nxt = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        return nxt.replace(day=day).isoformat()

    def test_a_bare_ordinal_gives_a_todo_its_due_date(self, parser):
        res = parser.analyze("remind me to renew the passport the 15th")
        assert res.intents, "the row must still parse"
        _, intent = res.intents[0]
        assert intent.due_date == self._expected(15)

    def test_the_bare_form_agrees_with_the_on_form(self, parser):
        # (A call to a person is an event since Q47; an errand keeps this a to-do.)
        bare = parser.analyze("remind me to renew the passport the 21st")
        with_on = parser.analyze("remind me to renew the passport on the 21st")
        assert bare.intents and with_on.intents
        assert bare.intents[0][1].due_date == with_on.intents[0][1].due_date

    def test_an_event_gets_the_date_and_keeps_its_time(self, parser):
        res = parser.analyze("book flu shot the 21st at 11am")
        assert res.intents
        _, intent = res.intents[0]
        assert intent.date == self._expected(21)
        assert intent.start_time == "11:00"

    def test_the_date_words_do_not_end_up_in_the_title(self, parser):
        """The recogniser blocks the characters of every date it reads so they
        cannot become the title; this fallback has to do that itself.

        NB the row here is deliberately `"wash the laundry"` and not `"wash AND
        fold the laundry"`: the latter extracts NO title at all, with or without
        a date, which is a separate coordinated-verb defect filed in TASKS.md
        rather than fixed here.
        """
        res = parser.analyze("wash the laundry the 30th")
        assert res.intents
        _, intent = res.intents[0]
        title = " ".join(getattr(intent, "titles", None) or [intent.title]).lower()
        assert "30th" not in title, f"date text leaked into the title: {title!r}"
        assert intent.due_date == self._expected(30)

    # --- the two shapes that are NOT dates, both from the verification pool ---

    def test_an_ordinal_POSITION_is_not_a_date(self, parser):
        """"Remove the 2nd row from the list" — a position in a list, and the
        row it names is not the second of the month."""
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        temporal = rp._extract_temporal("remove the 2nd row from the list",
                                        datetime.date.today())
        assert temporal["date"] is None

    def test_an_ordinal_RECURRENCE_is_not_a_one_off_date(self, parser):
        """"the 15th of every month" is a series; resolving it to one day would
        book a single event and drop the recurrence."""
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        temporal = rp._extract_temporal("remind me at the 15th of every month",
                                        datetime.date.today())
        assert temporal["date"] is None

    def test_an_impossible_day_is_refused_rather_than_guessed(self, parser):
        """"the 99th" is not a day. Nothing is better than something wrong."""
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        temporal = rp._extract_temporal("call Sage the 99th", datetime.date.today())
        assert temporal["date"] is None


# ---------------------------------------------------------------------------
# A SERIES THAT STOPS — "every monday until the end of the month"
#
# `db.create_event` has honoured `recur_until` since it was written, and NOTHING
# in this parser ever set it, so every bounded series became an UNBOUNDED one:
# 81 rows of the FastRule 7,200 train half created a series that fires forever
# where the speaker named an end. A wrong answer that repeats.
#
# The bound also has to come OFF the text before the item's own date is read.
# `_fill_slots` already anchors "every monday" on the soonest Monday, correctly —
# and then the bound's date overwrote it, so "every monday until the end of the
# month" started on a WEDNESDAY. That regression arrived with the 2026-09-17
# daterange work and is what this class pins shut.
#
# Gil's standing ruling governs the arithmetic: "until" EXCLUDES the day it
# names, "through" and "including" KEEP it, and "until the end of <period>" is
# inclusive because it names the final day rather than a boundary past it.
# ---------------------------------------------------------------------------

class TestSeriesBound:

    WED = datetime.date(2026, 9, 9)          # a Wednesday, the boards' clock

    def _temporal(self, text):
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        return rp._extract_temporal(text, self.WED)

    # --- the ruling, case by case ---

    def test_until_excludes_the_day_it_names(self):
        assert self._temporal("every week until today")["recur_until"] == "2026-09-08"

    def test_through_keeps_the_day_it_names(self):
        assert self._temporal("daily through next tuesday")["recur_until"] == "2026-09-15"

    def test_including_keeps_the_day_it_names(self):
        assert self._temporal("every weekend, including next friday")["recur_until"] == "2026-09-18"

    def test_until_the_end_of_a_period_is_inclusive(self):
        """The documented exception: "the end of the month" names the last day,
        so it survives even under "until"."""
        assert self._temporal("every monday until the end of the month")["recur_until"] == "2026-09-30"

    def test_until_a_period_stops_before_it_begins(self):
        """"until next month" is the other reading of the same range — the month
        is the STOP, so the series ends the day before it starts."""
        assert self._temporal("twice a week until next month")["recur_until"] == "2026-09-30"

    # --- what the bound must NOT do ---

    def test_the_bound_is_not_the_series_start_date(self):
        """The regression this closes: the bound's date became the item's own."""
        t = self._temporal("every monday at ten thirty until the end of the month")
        assert t["date"] is None, \
            f"the bound leaked into the item's own date: {t['date']}"

    def test_a_time_after_the_bound_still_survives(self):
        """The recogniser returns "next tuesday at 5 pm" as ONE datetime, so
        masking the whole match lost the event's time."""
        t = self._temporal("book project sync daily through next tuesday at 5 pm")
        assert t["recur_until"] == "2026-09-15"
        assert t["start_time"] == "17:00", "the event's own time was eaten"

    def test_through_as_a_preposition_of_place_is_not_a_bound(self):
        """"a tour through the museum" has no date after the keyword, which is
        the guard — no date, no bound."""
        assert self._temporal("book a tour through the museum")["recur_until"] is None

    def test_no_bound_keyword_means_no_bound(self):
        assert self._temporal("book gym every monday at 7am")["recur_until"] is None

    # --- and it reaches the intent, which is the point ---

    def test_the_bound_reaches_the_event_intent(self, parser):
        res = parser.analyze("book open house every monday at 10am until the end of the month")
        assert res.intents, "the row must still parse"
        name, intent = res.intents[0]
        assert name == "create_event"
        assert intent.recurrence == "weekly"
        assert intent.recur_until, "db.create_event bounds the series from this field"
        # The series starts on a MONDAY, not on the bound's day.
        assert datetime.date.fromisoformat(intent.date).weekday() == 0


# ---------------------------------------------------------------------------
# THE SUBTRACTIVE TITLE (Gil approved the design change 2026-09-18)
#
# `_extract_title` used to pick ONE noun chunk, so "set a meeting tomorrow at 2
# o'clock meeting with omri for project" was titled "meeting". Corpus: title
# exactly-right 41.8% against right-OR-A-SUBSTRING 85.6% — 44 points of pure
# truncation. Real speech: the largest failure class outright, 42% of 50
# reviewed commands.
#
# Subtractive: every reader that already claimed words gives them up — temporal
# spans, the cadence phrase, the series bound, the destination, the stop keyword,
# the imperative shell — and the title is what is left.
# ---------------------------------------------------------------------------

class TestSubtractiveTitle:

    WED = datetime.date(2026, 9, 9)

    def _title(self, text):
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        temporal = rp._extract_temporal(text, self.WED)
        return rp._subtractive_title(text, temporal.get("spans") or [])

    # --- what the old reader threw away ---

    def test_a_generic_head_keeps_the_words_that_name_it(self):
        assert self._title("set a meeting tomorrow at 2 o'clock meeting with omri "
                           "for project") == "meeting with omri for project"

    def test_with_whom_is_kept_not_replaced(self):
        """The bug in the obvious fix: drop the generic head and "meeting with
        ora" becomes the bare "with ora"."""
        assert self._title("set tomorrow a meeting with ora at 5pm") == "meeting with ora"

    def test_a_named_thing_outranks_a_generic_head(self):
        t = self._title("Movie today at 4.30pm at the Lincoln AMC Theatre. Execute.")
        assert t.lower() == "movie at the lincoln amc theatre"

    def test_a_verb_the_speaker_said_survives(self):
        """"walk Mark's dog", not "dog" — the old reader took the noun chunk."""
        assert self._title("Set for today to walk Mark's dog at 2.30pm, execute.") \
            == "walk Mark's dog"

    # --- the stranded-word rules, which are most of the work ---

    def test_a_trailing_preposition_whose_object_was_blanked_goes(self):
        assert self._title("set a meeting tomorrow on tuesday at 6pm with etai") \
            == "meeting with etai"

    def test_a_leading_preposition_whose_object_SURVIVED_stays(self):
        """"at the Lincoln AMC" is part of the title; treating that `at` as
        stranded produced "Movie the Lincoln AMC Theatre"."""
        assert "at the" in self._title(
            "Movie today at 4.30pm at the Lincoln AMC Theatre.").lower()

    def test_the_cadence_word_is_not_part_of_the_title(self):
        assert self._title("book open house every monday at ten thirty") == "open house"

    def test_annual_before_a_noun_stays_in_the_title(self):
        """Subtraction removes what the temporal reader took, faithfully — so
        when the recogniser claimed "annual" as a yearly SET, "book annual
        checkup monthly at 8:30pm" titled itself "checkup" (27 rows of the
        FastRule train half). The reader now leaves "annual" before a noun
        unclaimed (2026-09-25); a yearly series is read from "annually" /
        "every year" / "yearly", never from this span, so the cadence is
        untouched.
        """
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        text = "book annual checkup monthly at 8:30pm"
        spans = rp._extract_temporal(text, self.WED)["spans"]
        assert not any(text[a:b] == "annual" for a, b in spans)
        assert self._title(text) == "annual checkup"

    def test_the_stop_keyword_and_destination_go(self):
        assert self._title("put sales call on my calendar tomorrow, execute") \
            == "sales call"

    # --- the two guards, each bought with a measured regression ---

    def test_a_framing_verb_that_is_not_at_the_front_is_still_removed(self):
        """"next week on monday on the 13th create event to ta class" titled
        itself "create event to ta class" — against a row Gil had APPROVED as
        "TA Class"."""
        t = self._title("next week on monday on the 13th create event to ta class")
        assert "create event" not in t.lower(), t
        assert "ta class" in t.lower(), t

    def test_at_the_front_the_entry_word_is_kept(self):
        """The same pattern firing at position 0 removed the head and left
        "with Harper" — 1.6 pt of corpus title exactness, measured."""
        assert self._title("schedule a meeting with Harper next month at 9:15") \
            == "meeting with Harper"

    def test_a_runaway_title_hands_back_to_the_chunk_reader(self):
        """Subtraction that leaves a sentence has copied it, not understood it.
        Over the word cap it returns empty so `_extract_title` falls through."""
        rambling = ("Sarah Mindel, on my calendar, on the 10th of September, to "
                    "email professor for causal infant projects peeling the project")
        assert self._title(rambling) == ""

    # --- and the one that matters most ---

    def test_subtraction_is_for_NAMING_never_for_FINDING(self, parser):
        """`_extract_title` also supplies `match_title`, the NEEDLE for a record
        that already exists — and a richer phrase is a worse needle. Turned on
        for updates and deletes, the corpus board's `update_todo` DESTRUCTIVE
        errors went from 1 to 27 in a single run."""
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        text = "delete the meeting with ora tomorrow"
        doc = rp._NLP(text)
        temporal = rp._extract_temporal(text, self.WED)
        spans = temporal.get("spans") or []
        naming = rp._extract_title(doc[:], spans, subtractive=True)
        finding = rp._extract_title(doc[:], spans, subtractive=False)
        assert naming != finding, \
            "a target must not be read the same way as a new thing's name"
        assert finding and len(finding.split()) <= len(naming.split())


# ---------------------------------------------------------------------------
# A STATED CLOCK OR DAY BEATS A TITLE WORD (2026-09-19)
#
# Found by the title-invariance probe on the front door: a title carrying a
# time-like word changed the event's clock or day, although the sentence stated
# both outright. Three precedence defects in `_extract_temporal`, none of them
# about where the time sits:
#
#   "book morning pages tomorrow at 7am"           -> 08:00  (the daypart window
#                                                     came first and the stated
#                                                     7am was refused)
#   "book walk through the slides tomorrow at 3pm" -> TODAY  ("through" opened a
#                                                     series bound on a date three
#                                                     words away, eating the day)
#   "book monday standup tomorrow at 9am"          -> MONDAY (the first date in
#                                                     the string won over the one
#                                                     that carries the clock)
#
# The convention is decompose_validate's, already written down: a stated clock
# always wins, and a window applies only when nothing states one. The same rule
# here, so the two tracks cannot disagree about it. And a reading that loses
# gives its words back to the title -- "morning pages" is the thing's name.
# ---------------------------------------------------------------------------

class TestStatedTimeBeatsTitleWords:

    WED = datetime.date(2026, 9, 9)

    def _temporal(self, text):
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        return rp._extract_temporal(text, self.WED)

    def _title(self, text):
        from assistant.intent import rule_parser as rp
        return rp._subtractive_title(text, self._temporal(text).get("spans") or [])

    # --- A · a daypart window defers to a stated clock ---

    def test_a_stated_clock_beats_a_daypart_that_came_first(self):
        t = self._temporal("book morning pages tomorrow at 7am")
        assert t["start_time"] == "07:00", t
        assert t["end_time"] is None, "the window's end must not survive the window"
        assert t["date"] == "2026-09-10"

    def test_the_losing_daypart_gives_its_word_back_to_the_title(self):
        assert self._title("book morning pages tomorrow at 7am") == "morning pages"

    def test_night_is_the_same_rule(self):
        t = self._temporal("book night shift handover tomorrow at 2pm")
        assert t["start_time"] == "14:00", t
        assert self._title("book night shift handover tomorrow at 2pm") == "night shift handover"

    def test_a_daypart_alone_still_names_its_window(self):
        """Nothing states a clock, so the window is the answer -- unchanged."""
        t = self._temporal("book a run in the afternoon")
        assert t["start_time"] == "12:00", t
        assert t["end_time"] is not None

    def test_a_daypart_right_after_the_clock_is_its_meridiem(self):
        """The recogniser merges "at 6 in the evening" into one reading in every
        natural sentence; it SPLITS only when a daypart already opened the
        reading ("this morning at 6" + "in the evening") — the 7,200 set's own
        template shape, nine train rows. Then the second reading says WHICH six:
        not a window (no end at 20:00) and not a title word."""
        t = self._temporal("book tennis lesson this morning at 6 in the evening")
        assert t["start_time"] == "18:00", t
        assert t["end_time"] is None
        assert self._title("book tennis lesson this morning at 6 in the evening") == "tennis lesson"

    def test_in_the_morning_after_the_clock_keeps_it_am(self):
        t = self._temporal("schedule doctor's appointment this morning at 9 in the morning")
        assert t["start_time"] == "09:00" and t["end_time"] is None, t
        assert self._title("schedule doctor's appointment this morning at 9 in the morning") == "doctor's appointment"


# ---------------------------------------------------------------------------
# A STATED CLOCK OR DAY BEATS A TITLE WORD (2026-09-19)
#
# Found by the title-invariance probe on the front door: a title carrying a
# time-like word changed the event's clock or day, although the sentence stated
# both outright. Three precedence defects in `_extract_temporal`, none of them
# about where the time sits:
#
#   "book morning pages tomorrow at 7am"           -> 08:00  (the daypart window
#                                                     came first and the stated
#                                                     7am was refused)
#   "book walk through the slides tomorrow at 3pm" -> TODAY  ("through" opened a
#                                                     series bound on a date three
#                                                     words away, eating the day)
#   "book monday standup tomorrow at 9am"          -> MONDAY (the first date in
#                                                     the string won over the one
#                                                     that carries the clock)
#
# The convention is decompose_validate's, already written down: a stated clock
# always wins, and a window applies only when nothing states one. The same rule
# here, so the two tracks cannot disagree about it. And a reading that loses
# gives its words back to the title -- "morning pages" is the thing's name.
# ---------------------------------------------------------------------------

class TestStatedTimeBeatsTitleWords:

    WED = datetime.date(2026, 9, 9)

    def _temporal(self, text):
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        return rp._extract_temporal(text, self.WED)

    def _title(self, text):
        from assistant.intent import rule_parser as rp
        return rp._subtractive_title(text, self._temporal(text).get("spans") or [])

    # --- A · a daypart window defers to a stated clock ---

    def test_a_stated_clock_beats_a_daypart_that_came_first(self):
        t = self._temporal("book morning pages tomorrow at 7am")
        assert t["start_time"] == "07:00", t
        assert t["end_time"] is None, "the window's end must not survive the window"
        assert t["date"] == "2026-09-10"

    def test_the_losing_daypart_gives_its_word_back_to_the_title(self):
        assert self._title("book morning pages tomorrow at 7am") == "morning pages"

    def test_night_is_the_same_rule(self):
        t = self._temporal("book night shift handover tomorrow at 2pm")
        assert t["start_time"] == "14:00", t
        assert self._title("book night shift handover tomorrow at 2pm") == "night shift handover"

    def test_a_daypart_alone_still_names_its_window(self):
        """Nothing states a clock, so the window is the answer -- unchanged."""
        t = self._temporal("book a run in the afternoon")
        assert t["start_time"] == "12:00", t
        assert t["end_time"] is not None

    def test_a_daypart_right_after_the_clock_is_its_meridiem(self):
        """The recogniser merges "at 6 in the evening" into one reading in every
        natural sentence; it SPLITS only when a daypart already opened the
        reading ("this morning at 6" + "in the evening") — the 7,200 set's own
        template shape, nine train rows. Then the second reading says WHICH six:
        not a window (no end at 20:00) and not a title word."""
        t = self._temporal("book tennis lesson this morning at 6 in the evening")
        assert t["start_time"] == "18:00", t
        assert t["end_time"] is None
        assert self._title("book tennis lesson this morning at 6 in the evening") == "tennis lesson"

    def test_in_the_morning_after_the_clock_keeps_it_am(self):
        t = self._temporal("schedule doctor's appointment this morning at 9 in the morning")
        assert t["start_time"] == "09:00" and t["end_time"] is None, t
        assert self._title("schedule doctor's appointment this morning at 9 in the morning") == "doctor's appointment"

    # --- B · a series bound needs its date right after the keyword ---

    def test_through_far_from_its_date_is_not_a_bound(self):
        t = self._temporal("book walk through the slides tomorrow at 3pm")
        assert t["recur_until"] is None, t
        assert t["date"] == "2026-09-10", "the day was eaten by a bound nobody named"
        assert t["start_time"] == "15:00"

    def test_the_words_a_false_bound_took_are_the_title(self):
        assert self._title("book walk through the slides tomorrow at 3pm") == "walk through the slides"

    def test_up_to_far_from_its_date_is_not_a_bound(self):
        t = self._temporal("read up to chapter four tomorrow at 3pm")
        assert t["recur_until"] is None and t["date"] == "2026-09-10", t

    def test_a_bound_right_after_its_keyword_still_binds(self):
        assert self._temporal("every monday until the end of the month")["recur_until"] == "2026-09-30"
        assert self._temporal("daily through next tuesday")["recur_until"] == "2026-09-15"


# ---------------------------------------------------------------------------
# A STATED CLOCK OR DAY BEATS A TITLE WORD (2026-09-19)
#
# Found by the title-invariance probe on the front door: a title carrying a
# time-like word changed the event's clock or day, although the sentence stated
# both outright. Three precedence defects in `_extract_temporal`, none of them
# about where the time sits:
#
#   "book morning pages tomorrow at 7am"           -> 08:00  (the daypart window
#                                                     came first and the stated
#                                                     7am was refused)
#   "book walk through the slides tomorrow at 3pm" -> TODAY  ("through" opened a
#                                                     series bound on a date three
#                                                     words away, eating the day)
#   "book monday standup tomorrow at 9am"          -> MONDAY (the first date in
#                                                     the string won over the one
#                                                     that carries the clock)
#
# The convention is decompose_validate's, already written down: a stated clock
# always wins, and a window applies only when nothing states one. The same rule
# here, so the two tracks cannot disagree about it. And a reading that loses
# gives its words back to the title -- "morning pages" is the thing's name.
# ---------------------------------------------------------------------------

class TestStatedTimeBeatsTitleWords:

    WED = datetime.date(2026, 9, 9)

    def _temporal(self, text):
        from assistant.intent import rule_parser as rp
        rp._ensure_nlp(); rp._ensure_dt()
        return rp._extract_temporal(text, self.WED)

    def _title(self, text):
        from assistant.intent import rule_parser as rp
        return rp._subtractive_title(text, self._temporal(text).get("spans") or [])

    # --- A · a daypart window defers to a stated clock ---

    def test_a_stated_clock_beats_a_daypart_that_came_first(self):
        t = self._temporal("book morning pages tomorrow at 7am")
        assert t["start_time"] == "07:00", t
        assert t["end_time"] is None, "the window's end must not survive the window"
        assert t["date"] == "2026-09-10"

    def test_the_losing_daypart_gives_its_word_back_to_the_title(self):
        assert self._title("book morning pages tomorrow at 7am") == "morning pages"

    def test_night_is_the_same_rule(self):
        t = self._temporal("book night shift handover tomorrow at 2pm")
        assert t["start_time"] == "14:00", t
        assert self._title("book night shift handover tomorrow at 2pm") == "night shift handover"

    def test_a_daypart_alone_still_names_its_window(self):
        """Nothing states a clock, so the window is the answer -- unchanged."""
        t = self._temporal("book a run in the afternoon")
        assert t["start_time"] == "12:00", t
        assert t["end_time"] is not None

    def test_a_daypart_right_after_the_clock_is_its_meridiem(self):
        """The recogniser merges "at 6 in the evening" into one reading in every
        natural sentence; it SPLITS only when a daypart already opened the
        reading ("this morning at 6" + "in the evening") — the 7,200 set's own
        template shape, nine train rows. Then the second reading says WHICH six:
        not a window (no end at 20:00) and not a title word."""
        t = self._temporal("book tennis lesson this morning at 6 in the evening")
        assert t["start_time"] == "18:00", t
        assert t["end_time"] is None
        assert self._title("book tennis lesson this morning at 6 in the evening") == "tennis lesson"

    def test_in_the_morning_after_the_clock_keeps_it_am(self):
        t = self._temporal("schedule doctor's appointment this morning at 9 in the morning")
        assert t["start_time"] == "09:00" and t["end_time"] is None, t
        assert self._title("schedule doctor's appointment this morning at 9 in the morning") == "doctor's appointment"

    # --- B · a series bound needs its date right after the keyword ---

    def test_through_far_from_its_date_is_not_a_bound(self):
        t = self._temporal("book walk through the slides tomorrow at 3pm")
        assert t["recur_until"] is None, t
        assert t["date"] == "2026-09-10", "the day was eaten by a bound nobody named"
        assert t["start_time"] == "15:00"

    def test_the_words_a_false_bound_took_are_the_title(self):
        assert self._title("book walk through the slides tomorrow at 3pm") == "walk through the slides"

    def test_up_to_far_from_its_date_is_not_a_bound(self):
        t = self._temporal("read up to chapter four tomorrow at 3pm")
        assert t["recur_until"] is None and t["date"] == "2026-09-10", t

    def test_a_bound_right_after_its_keyword_still_binds(self):
        assert self._temporal("every monday until the end of the month")["recur_until"] == "2026-09-30"
        assert self._temporal("daily through next tuesday")["recur_until"] == "2026-09-15"

    # --- C · the date that carries the clock beats a bare date ---

    def test_the_clocked_date_beats_a_bare_weekday_in_the_title(self):
        t = self._temporal("book monday standup tomorrow at 9am")
        assert t["date"] == "2026-09-10", t
        assert t["start_time"] == "09:00"

    def test_the_losing_weekday_is_still_a_date_word(self):
        """A reading that lost precedence keeps its claim on its words. The
        first cut handed the span back so "monday standup" would keep its
        name — and the same release put "tomorrow" into the title of "set a
        meeting tomorrow on tuesday at 6pm with etai". A date word is a date
        word; a truncated name is the lesser harm and the substring metric
        already tolerates it."""
        assert self._title("book monday standup tomorrow at 9am") == "standup"

    def test_a_bare_weekday_still_counts_when_it_is_the_only_day(self):
        t = self._temporal("book friday standup at 9am")
        assert t["date"] == "2026-09-11", t          # the coming Friday
        assert t["start_time"] == "09:00"

    def test_the_control_is_unchanged(self):
        t = self._temporal("book standup tomorrow at 9am")
        assert t["date"] == "2026-09-10" and t["start_time"] == "09:00", t


# ---------------------------------------------------------------------------
# A courtesy tail is not a second intent (2026-09-20)
# ---------------------------------------------------------------------------

class TestCourtesyTail:

    def test_let_x_know_does_not_cost_the_parse_its_confidence(self, parser):
        """The tail split into a second span, routed to nothing, and an
        unroutable span multiplies the confidence by 0.7 — 15 atomic train
        rows deferred at 0.66 on this shape."""
        plain = parser.analyze("extend open house by an hour")
        tailed = parser.analyze("extend open house by an hour and let Avery know")
        assert tailed.dropped_spans == 0
        assert tailed.confidence == plain.confidence
        assert [n for n, _ in tailed.intents] == ["update_event"]
        assert tailed.intents[0][1].match_title == "open house"

    def test_a_tail_with_content_keeps_its_own_span(self, parser):
        """"let Avery know THAT the room moved" carries content of its own."""
        res = parser.analyze("extend open house by an hour and let Avery know that the room moved")
        assert res.dropped_spans >= 1 or len(res.intents) >= 2


class TestATitleMustNameSomething:
    """DEVQA Q26, answered 2026-09-20: rewrite the title extractor properly.

    A create's title is assigned in four places — the subtractive extractor,
    the phrase extractor, the new-list frame, and the noun-chunk fallback with
    the verb put back. A title that named nothing got through whichever one
    the sentence happened to take, so three cycles of fixing them one at a
    time moved the junk-title rate by nothing. The rule is stated once now,
    after every path has run."""

    def test_scaffolding_is_not_a_name(self):
        from assistant.intent.rule_parser import names_something
        for t in ("at this time", "set reminder", "remind me", "things",
                  "about of all event in calenders", "this event",
                  "my list", "it"):
            assert not names_something(t), t

    def test_a_bare_kind_is_a_name(self):
        """Q42 (Gil, 2026-09-22): "appointment", "an event", "the date" commit
        with their details and the phone hints once. An anaphor ("this
        event") and a frame ("set reminder") still name nothing."""
        from assistant.intent.rule_parser import names_something
        for t in ("appointment", "an event", "the date", "the task", "reminder", "Meeting"):
            assert names_something(t), t
        for t in ("this event", "that appointment", "set reminder", "new list", "note of it"):
            assert not names_something(t), t

    def test_date_is_deliberately_left_a_name(self):
        """"Set a calendar event to repeat yearly on this date" keeps 'date'
        and still commits. Adding "date" to the scaffolding costs no gold
        title (measured: 0 of 3,944 — "the interview date" survives on
        'interview') but it refuses **date night**, a real command nobody has
        typed into this corpus yet. A wrong refusal on a real ask is worse
        than one junk title on a garbled one, so the word stays a name."""
        from assistant.intent.rule_parser import names_something
        assert names_something("date night")

    def test_a_real_title_survives(self):
        from assistant.intent.rule_parser import names_something
        for t in ("dentist", "call the dentist", "book club", "buy milk",
                  "dog breeds", "dinner reservations", "all hands meeting",
                  "team standup", "yashas birthday with vinay", "Meeting"):
            assert names_something(t), t

    def test_measured_against_the_gold_before_it_was_written(self):
        """Of the 7,200's 3,944 CREATE gold titles this refuses NONE. The 179
        it would refuse are mutation match-titles ("that appointment", "my
        list"), which a create never produces and this gate never sees."""
        import json
        import pathlib
        from assistant.intent.rule_parser import names_something

        path = pathlib.Path("assistant/engine/fastrule/datasets/fastrule_7200.jsonl")
        creates = []
        for line in path.read_text().splitlines():
            row = json.loads(line)
            expect = row.get("expect") or {}
            if not str(expect.get("action", "")).startswith("create"):
                continue
            slots = expect.get("slots") or {}
            if slots.get("title"):
                creates.append(slots["title"])
            creates += [t for t in (slots.get("titles") or []) if isinstance(t, str)]
        assert len(creates) > 3000, "the gold moved — re-measure before trusting this"
        refused = sorted({t for t in creates if not names_something(t)})
        assert not refused, refused

    def test_the_gate_refuses_rather_than_naming_the_scaffolding(self, parser):
        """The product end: a command whose title is all scaffolding defers to
        the deep track instead of committing 'at this time' at 0.95."""
        for text in ("Remind me at this time.", "i need to set reminder on 15th march",
                     "pls add list of things to buy for pary"):
            res = parser.analyze(text, current_view="month")
            titles = [t for _n, i in res.intents
                      for t in ((getattr(i, "titles", None) or [])
                                + ([getattr(i, "title", None)] if getattr(i, "title", None) else []))]
            assert not titles, (text, titles)


@pytest.mark.parametrize("said,target", [
    ("delete water the garden from my list", "water the garden"),
    ("move team meeting to next friday at 3:45pm", "team meeting"),
    ("mark walk the dog as done", "walk the dog"),
])
def test_a_phrase_read_target_is_not_overwritten_by_the_noun_reader(parser, said, target):
    """2026-09-24, the cross-store board: the phrase rules read the whole name
    and a later noun reader overwrote it ("water", "team") — which tied with
    another item and changed the wrong one."""
    result = parser.analyze(said, current_view="month")
    assert result.intents[0][1].match_title == target


def test_calendar_entry_frames_leave_the_title(registry_with_real_actions):
    """The entry shell, not the name (FastRule 7,200 train, 2026-09-25):
    "put in", "circle … for", "block off the whole day … for", "add X in
    calendar", "to-do:", "gotta remember to"."""
    from assistant.intent.rule_parser import RuleBasedParser
    rp = RuleBasedParser(registry_with_real_actions)
    def title(t):
        i = rp.analyze(t, current_view="month").intents[0][1]
        return getattr(i, "title", None) or (getattr(i, "titles", None) or [""])[0]
    assert title("tonight at 9:15 put in retrospective") == "retrospective"
    assert title("circle in five days on the calendar for the tax deadline") == "the tax deadline"
    assert title("block off the whole day march 5th for wedding rehearsal") == "wedding rehearsal"
    assert title("please to add open house in calendar in five days noon") == "open house"
    assert title("to-do: file the taxes") == "file the taxes"
    assert title("i gotta remember to pay the electricity bill") == "pay the electricity bill"


def test_needing_things_is_an_errand_never_a_removal(registry_with_real_actions):
    """"need 10 trash bags from the shop" went to the classifier, which read
    "from" as remove-from-my-list and committed delete_todo — 8 creates on
    the FastRule 7,200 train half became deletes (2026-09-25)."""
    from assistant.intent.rule_parser import RuleBasedParser
    rp = RuleBasedParser(registry_with_real_actions)
    for text, want in [("need 10 trash bags from the shop", "10 trash bags"),
                       ("i need milk", "milk")]:
        name, intent = rp.analyze(text, current_view="month").intents[0]
        assert name == "create_todo" and intent.titles == [want], text


def test_keeping_a_day_clear_for_something_books_it(registry_with_real_actions):
    """"clear" routed "keep today clear for X" to delete_event — 10 creates
    on the FastRule 7,200 train half became deletes (2026-09-25)."""
    from assistant.intent.rule_parser import RuleBasedParser
    rp = RuleBasedParser(registry_with_real_actions)
    name, intent = rp.analyze("keep today clear for performance review, the whole day",
                              current_view="month").intents[0]
    assert (name, intent.title) == ("create_event", "performance review")


def test_marking_a_day_as_an_occasion_makes_an_entry(registry_with_real_actions):
    """What is marked is a DAY, read by the time finder rather than a word
    list: 12 of these were committed complete_todo on the FastRule 7,200
    train half (2026-09-25). Completions keep their route."""
    from assistant.intent.rule_parser import RuleBasedParser
    rp = RuleBasedParser(registry_with_real_actions)
    route = lambda t: rp.analyze(t, current_view="month").intents[0][0]
    assert route("mark in two days down as the school holiday") == "create_event"
    assert route("mark a week from today down as my birthday") == "create_event"
    assert route("mark buy groceries as done") == "complete_todo"


def test_a_plural_domain_word_is_a_domain_signal(registry_with_real_actions):
    """"from my tasks" carried no signal (the set held only "task"), so 14
    "drop X from my tasks" rows deleted an event (2026-09-25)."""
    from assistant.intent.rule_parser import RuleBasedParser
    rp = RuleBasedParser(registry_with_real_actions)
    assert rp.analyze("drop water the plants from my tasks",
                      current_view="month").intents[0][0] == "delete_todo"
