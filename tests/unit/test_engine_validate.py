"""Step 4 — one test per named rule. The rules are survivors of real bugs;
each test carries its row number so the story is findable.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

import assistant.engine.llm as engine_llm
import assistant.engine.decompose_validate.stage as validate
from assistant.engine import load_config
from assistant.engine.state import EngineState, Item


@pytest.fixture
def cfg():
    return load_config()


def _state(text, items):
    st = EngineState(raw_text=text, text=text)
    st.items = items
    return st


def _event_intent(**kw):
    base = dict(title="x", date=None, start_time=None, end_time=None,
                recurrence=None, recur_until=None, description="")
    base.update(kw)
    return SimpleNamespace(**base)


def _item(action, intent, id="item_1", kind="event", text=""):
    return Item(id=id, kind=kind, text=text, action=action, intent=intent)


def _rules_applied(st):
    return [f.rule for f in st.fixes]


# --- text repair (run pass) -------------------------------------------------

def test_text_repair_collapses_stutters_for_free(cfg, monkeypatch):
    monkeypatch.setattr(engine_llm, "call_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM")))
    st = _state("x", [Item(id="item_1", kind="event", text="book the the meeting tomorrow")])
    validate.run(st, cfg)
    assert st.items[0].text == "book the meeting tomorrow"
    assert "text_repair" in _rules_applied(st)


def test_text_repair_llm_only_for_genuinely_mangled(cfg, monkeypatch):
    monkeypatch.setattr(engine_llm, "call_json",
                        lambda *a, **k: ({"text": "book squash tomorrow"}, 3))
    st = _state("x", [Item(id="item_1", kind="event", text="book squa- book squash tomorrow")])
    validate.run(st, cfg)
    assert st.items[0].text == "book squash tomorrow"


def test_text_repair_rejects_a_rewrite_that_grew(cfg, monkeypatch):
    monkeypatch.setattr(engine_llm, "call_json",
                        lambda *a, **k: ({"text": "book squash tomorrow at nine with David maybe"}, 3))
    st = _state("x", [Item(id="item_1", kind="event", text="book squa- tomorrow")])
    validate.run(st, cfg)
    assert st.items[0].text == "book squa- tomorrow"   # invention refused


# --- past_date_bump (row 29) ------------------------------------------------

def test_past_date_bump_recent_weekday_rolls_a_week(cfg):
    past = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    it = _item("create_event", _event_intent(date=past))
    st = _state("meeting", [it])
    validate.run_objects(st, cfg)
    bumped = dt.date.fromisoformat(it.intent.date)
    assert bumped >= dt.date.today()
    assert bumped.weekday() == dt.date.fromisoformat(past).weekday()


def test_past_date_bump_old_calendar_day_moves_a_year(cfg):
    it = _item("create_event", _event_intent(date="2026-01-15"))
    st = _state("meeting on January 15", [it])
    validate.run_objects(st, cfg)
    assert it.intent.date == "2027-01-15"


# --- until_exclusive (row 53) ----------------------------------------------

def test_until_excludes_the_day_it_names(cfg):
    it = _item("create_event", _event_intent(
        date="2026-10-01", recurrence="daily", recur_until="2026-10-06"))
    st = _state("every day at 7pm until Oct 6", [it])
    validate.run_objects(st, cfg)
    assert it.intent.recur_until == "2026-10-05"


def test_through_keeps_the_day_it_names(cfg):
    it = _item("create_event", _event_intent(
        date="2026-10-01", recurrence="daily", recur_until="2026-10-06"))
    st = _state("every day at 7pm through Oct 6", [it])
    validate.run_objects(st, cfg)
    assert it.intent.recur_until == "2026-10-06"


# --- weekly_start_day (row 53) ----------------------------------------------

def test_weekly_series_anchors_on_the_named_day(cfg):
    wrong_day = dt.date.today()
    while wrong_day.weekday() == 6:        # any date that is not a Sunday
        wrong_day += dt.timedelta(days=1)
    it = _item("create_event", _event_intent(
        date=wrong_day.isoformat(), recurrence="weekly"))
    st = _state("standup every sunday at 9am", [it])
    validate.run_objects(st, cfg)
    assert dt.date.fromisoformat(it.intent.date).weekday() == 6


# --- at_time_is_start --------------------------------------------------------

def test_at_time_is_a_start_not_an_end(cfg):
    it = _item("create_event", _event_intent(
        title="dinner with Danny", start_time="18:00", end_time="20:00"))
    st = _state("dinner with Danny at 8 pm", [it])
    validate.run_objects(st, cfg)
    assert it.intent.start_time == "20:00"
    assert it.intent.end_time == "21:00"


# --- morning_title_guard (row 41 family) ------------------------------------

def test_shacharit_is_a_morning_event(cfg):
    it = _item("create_event", _event_intent(
        title="Shacharit", start_time="18:30", end_time="19:30"))
    st = _state("Shacharit at 6:30", [it])
    validate.run_objects(st, cfg)
    assert it.intent.start_time == "06:30"


# --- bare_hour_pm ------------------------------------------------------------

def test_bare_evening_hour_reads_pm(cfg):
    it = _item("create_event", _event_intent(
        title="Kems", date="2026-09-10", start_time="04:00"))
    st = _state("Kems tomorrow at 4", [it])
    validate.run_objects(st, cfg)
    assert it.intent.start_time == "16:00"


def test_explicit_am_is_left_alone(cfg):
    it = _item("create_event", _event_intent(
        title="gym", date="2026-09-10", start_time="07:00"))
    st = _state("book gym tomorrow at 7am", [it])
    validate.run_objects(st, cfg)
    assert it.intent.start_time == "07:00"


# --- junk_event_drop ---------------------------------------------------------

def test_generic_event_beside_real_todos_is_dropped(cfg):
    ev = _item("create_event", _event_intent(title="reminder"), id="item_1")
    td = _item("create_todo", SimpleNamespace(title="buy milk", due_date=None),
               id="item_2", kind="task")
    st = _state("remind me to buy milk", [ev, td])
    validate.run_objects(st, cfg)
    assert ev.intent is None                 # dropped as parser noise
    assert td.intent is not None


# --- max_duration_cap (engine-built events only, config: engine.max_event_hours) --

def test_a_construction_over_the_cap_is_clipped_from_the_end(cfg):
    it = _item("create_event", _event_intent(
        title="offsite", date="2026-09-10", start_time="09:00", end_time="20:00"))
    st = _state("book offsite tomorrow 9am to 8pm", [it])
    validate.run_objects(st, cfg)
    assert it.intent.start_time == "09:00"     # the start the speaker gave stays
    assert it.intent.end_time == "13:00"       # clipped to the default 4-hour cap
    assert "max_duration_cap" in _rules_applied(st)


def test_a_construction_at_or_under_the_cap_is_left_alone(cfg):
    it = _item("create_event", _event_intent(
        title="workshop", date="2026-09-10", start_time="09:00", end_time="12:00"))
    st = _state("book workshop tomorrow 9 to 12", [it])
    validate.run_objects(st, cfg)
    assert it.intent.end_time == "12:00"
    assert "max_duration_cap" not in _rules_applied(st)


def test_the_cap_is_configurable(cfg):
    cfg.engine.max_event_hours = 2.0
    it = _item("create_event", _event_intent(
        title="offsite", date="2026-09-10", start_time="09:00", end_time="13:00"))
    st = _state("book offsite tomorrow 9am to 1pm", [it])
    validate.run_objects(st, cfg)
    assert it.intent.end_time == "11:00"


def test_an_unresolved_end_before_start_is_not_this_rules_to_fix(cfg):
    # end <= start is a wraparound `end_after_start` (checks.py) left flagged,
    # not a long construction — clipping it would be a guess, not a fix.
    it = _item("create_event", _event_intent(
        title="party", date="2026-09-10", start_time="23:00", end_time="01:00"))
    st = _state("party tomorrow at 11pm until 1am", [it])
    validate.run_objects(st, cfg)
    assert "max_duration_cap" not in _rules_applied(st)


def test_an_all_day_event_is_not_clipped(cfg):
    """00:00-23:59 is the whole-day block, not a 24-hour construction: it was
    clipped to 00:00-04:00 on every fast-path "all day" (2026-09-26)."""
    it = _item("create_event", _event_intent(
        title="moving day", date="2026-09-10", start_time="00:00", end_time="23:59"))
    st = _state("block out tomorrow for moving day, all day", [it])
    validate.run_objects(st, cfg)
    assert (it.intent.start_time, it.intent.end_time) == ("00:00", "23:59")
    assert "max_duration_cap" not in _rules_applied(st)


# --- quiet_hours_flag (engine-built events only, config: engine.quiet_hours_start/_end) --

def test_a_start_time_inside_quiet_hours_is_flagged_not_changed(cfg):
    it = _item("create_event", _event_intent(
        title="flight", date="2026-09-10", start_time="05:00", end_time="06:00"))
    st = _state("book flight tomorrow at 5am", [it])
    validate.run_objects(st, cfg)
    assert it.intent.start_time == "05:00"    # a flag, never a clip
    assert it.intent.end_time == "06:00"
    assert "flag:quiet_hours" in _rules_applied(st)
    assert any(f.startswith("quiet_hours:") for f in it.slots["flags"])


def test_a_time_outside_quiet_hours_is_not_flagged(cfg):
    """FAILED ONE DAY IN SEVEN until 2026-09-18, and not for its own reason.

    `run_objects` re-resolves the date from the item's own WORDS, so the
    hard-coded `date=` above is overwritten by whatever "tomorrow" means when the
    suite runs. On a Friday that is Shabbat, the observance rule adds a flag, and
    this test asserted `"flags" not in it.slots` — so a test about QUIET HOURS
    went red over an observance flag that was entirely correct.

    Frozen to a Wednesday: "tomorrow" is then a Thursday whatever the real date,
    and the strong assertion (nothing flagged at all) can stay.
    """
    from freezegun import freeze_time
    with freeze_time("2026-09-09"):              # a Wednesday
        it = _item("create_event", _event_intent(
            title="gym", date="2026-09-10", start_time="09:00", end_time="10:00"))
        st = _state("book gym tomorrow at 9", [it])
        validate.run_objects(st, cfg)
    assert "flag:quiet_hours" not in _rules_applied(st)
    assert "flags" not in it.slots


def test_only_the_endpoint_that_falls_in_the_window_is_named(cfg):
    # 22:00-23:30: the start is a normal evening hour, only the end dips into
    # the default 23:00-06:00 window.
    it = _item("create_event", _event_intent(
        title="party", date="2026-09-10", start_time="22:00", end_time="23:30"))
    st = _state("party tomorrow 10pm to 11:30pm", [it])
    validate.run_objects(st, cfg)
    reason = next(f for f in it.slots["flags"] if f.startswith("quiet_hours:"))
    assert "end" in reason and "start" not in reason


def test_the_window_boundary_is_start_inclusive_end_exclusive(cfg):
    it = _item("create_event", _event_intent(
        title="checkin", date="2026-09-10", start_time="23:00", end_time="23:59"))
    st = _state("checkin tomorrow at exactly 11pm", [it])
    validate.run_objects(st, cfg)
    assert "flag:quiet_hours" in _rules_applied(st)     # 23:00 is inside (start of window)


def test_the_quiet_hours_window_is_configurable(cfg):
    cfg.engine.quiet_hours_start = "12:00"
    cfg.engine.quiet_hours_end = "13:00"
    it = _item("create_event", _event_intent(
        title="lunch", date="2026-09-10", start_time="12:30", end_time="13:00"))
    st = _state("book lunch tomorrow at 12:30", [it])
    validate.run_objects(st, cfg)
    assert "flag:quiet_hours" in _rules_applied(st)


def test_a_zero_width_window_never_flags(cfg):
    cfg.engine.quiet_hours_start = "23:00"
    cfg.engine.quiet_hours_end = "23:00"
    it = _item("create_event", _event_intent(
        title="party", date="2026-09-10", start_time="23:00", end_time="23:59"))
    st = _state("party tomorrow at 11pm", [it])
    validate.run_objects(st, cfg)
    assert "flag:quiet_hours" not in _rules_applied(st)


def test_update_event_is_never_flagged_by_quiet_hours(cfg):
    # Only create_event is wired to this rule (object_rules.py's own scope,
    # matching every other engine-only rule here) — an update landing at 3am
    # is the speaker moving their OWN existing event, not a new construction.
    it = _item("update_event", _event_intent(
        title="dentist", match_title="dentist", start_time="03:00", end_time="04:00"),
        kind="event")
    st = _state("move dentist to 3am", [it])
    validate.run_objects(st, cfg)
    assert "flag:quiet_hours" not in _rules_applied(st)


# --- due_date_pin ------------------------------------------------------------

def test_due_next_monday_is_deterministic(cfg):
    it = _item("create_todo", SimpleNamespace(title="pay rent", due_date="2026-01-01"),
               kind="task")
    st = _state("pay rent due next monday", [it])
    validate.run_objects(st, cfg)
    got = dt.date.fromisoformat(it.intent.due_date)
    assert got.weekday() == 0 and got > dt.date.today()


# --- cadence_round_and_announce (rows 53/64 family) --------------------------

def test_unsupported_cadence_is_announced_not_silent(cfg):
    it = _item("create_event", _event_intent(
        title="pilates", date="2026-09-08", recurrence="weekly"))
    st = _state("pilates every other tuesday at 6pm", [it])
    validate.run_objects(st, cfg)
    assert any("every other week" in m for m in st.messages)


# --- observance gate (engine rule — AI-created events only) ------------------

def _next_saturday() -> dt.date:
    d = dt.date.today() + dt.timedelta(days=1)
    while d.weekday() != 5:
        d += dt.timedelta(days=1)
    return d


def test_shabbat_meal_is_allowed(cfg):
    it = _item("create_event", _event_intent(
        title="Shabbat lunch", date=_next_saturday().isoformat(), start_time="12:00"))
    st = _state("shabbat lunch", [it])
    validate.run_objects(st, cfg)
    assert it.blocked is None


def test_shabbat_davening_is_allowed(cfg):
    it = _item("create_event", _event_intent(
        title="Shacharit at shul", date=_next_saturday().isoformat(), start_time="08:30"))
    st = _state("shacharit", [it])
    validate.run_objects(st, cfg)
    assert it.blocked is None


def test_shabbat_gym_is_flagged_with_a_reason(cfg):
    """FLAGGED, not refused (Gil, 2026-09-08).

    A blocked item is a command that silently did nothing; a flagged one is
    committed with a note the speaker can see and act on. What must NOT change is
    that the reason names Shabbat — the point was never to be quiet about it.
    """
    it = _item("create_event", _event_intent(
        title="gym session", date=_next_saturday().isoformat(), start_time="10:00"))
    st = _state("gym on saturday morning", [it])
    validate.run_objects(st, cfg)
    assert it.blocked is None, "a flag must not block the item"
    flags = (it.slots or {}).get("flags") or []
    assert any("Shabbat" in f for f in flags), flags
    assert any(f.rule == "flag:observance" for f in st.fixes)


def test_motzei_shabbat_is_fine(cfg):
    it = _item("create_event", _event_intent(
        title="movie night", date=_next_saturday().isoformat(), start_time="22:30"))
    st = _state("movie saturday night", [it])
    validate.run_objects(st, cfg)
    assert it.blocked is None


def test_a_series_is_left_to_db_level_skipping(cfg):
    it = _item("create_event", _event_intent(
        title="gym", date=_next_saturday().isoformat(), start_time="10:00",
        recurrence="weekly"))
    st = _state("gym every saturday", [it])
    validate.run_objects(st, cfg)
    assert it.blocked is None


# --- move_time_fill (run 9: "updated successfully" while changing nothing) ---

def _upd_intent(**kw):
    base = dict(match_title="meeting", match_date=None, match_start_time=None,
                new_title=None, new_date=None, new_start_time=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_move_time_fill_takes_the_other_spoken_time(cfg):
    it = _item("update_event", _upd_intent(match_start_time="13:00"))
    st = _state("move my 1pm meeting tomorrow to 3pm", [it])
    validate.run_objects(st, cfg)
    assert it.intent.new_start_time == "15:00"
    assert "move_time_fill" in [f.rule for f in st.fixes]


def test_move_time_fill_is_minute_aware(cfg):
    """"from 9:30 to 9" — same hour, different minutes — must fill 09:00."""
    it = _item("update_event", _upd_intent(match_start_time="09:30"))
    st = _state("meeting with Guri moved from 9:30 to 9 on wednesday", [it])
    validate.run_objects(st, cfg)
    assert it.intent.new_start_time == "09:00"


def test_move_time_fill_reads_from_to_over_the_model(cfg):
    """Run 10: the parser filed "from 9:30" as the DESTINATION. The explicit
    from/to words override whatever the model filled, both sides."""
    it = _item("update_event", _upd_intent(new_date="2026-09-09",
                                           new_start_time="09:30"))
    st = _state("meeting with Guri moved from 9:30 to 9 on wednesday", [it])
    validate.run_objects(st, cfg)
    assert it.intent.match_start_time == "09:30"
    assert it.intent.new_start_time == "09:00"


def test_move_time_fill_to_phrase_beats_a_wrong_fill(cfg):
    it = _item("update_event", _upd_intent(match_start_time="13:00",
                                           new_start_time="16:00"))
    st = _state("move my 1pm meeting to 3pm", [it])
    validate.run_objects(st, cfg)
    assert it.intent.new_start_time == "15:00"   # the spoken "to 3pm" wins


def test_move_time_fill_sets_the_match_from_the_other_time(cfg):
    it = _item("update_event", _upd_intent())
    st = _state("move my 1pm meeting tomorrow to 3pm", [it])
    validate.run_objects(st, cfg)
    assert it.intent.match_start_time == "13:00"
    assert it.intent.new_start_time == "15:00"


# --- guards from the real-utterance triage (2026-09-03) ----------------------

def test_a_remove_instruction_becomes_the_delete_it_says(cfg):
    it = _item("create_todo", SimpleNamespace(title="remove table from furniture",
                                              due_date=None), kind="task")
    st = _state("remove 'table' from furniture", [it])
    validate.run_objects(st, cfg)
    assert it.action == "delete_todo"
    assert it.intent.match_title == "table"
    assert "create_from_remove_guard" in [f.rule for f in st.fixes]


def test_a_create_frame_keeps_a_remove_verb_in_the_title(cfg):
    """Cycle 45 (2026-09-22): "remind me to cancel the subscription" is a to-do
    called 'cancel the subscription'. The guard above turned it into a DELETE
    of 'the subscription' because it read the title and never the frame."""
    for words in ("remind me to cancel the subscription",
                  "hey remind me to cancel the subscription",
                  "add cancel the subscription to my list",
                  "set a reminder to delete old photos"):
        title = words.split(" to ", 1)[-1].replace(" to my list", "") if not words.startswith("add") \
            else "cancel the subscription"
        it = _item("create_todo", SimpleNamespace(title=title, titles=[title], due_date=None),
                   kind="task", text=words)
        st = _state(words, [it])
        validate.run_objects(st, cfg)
        assert it.action == "create_todo", (words, it.action)
        assert "create_from_remove_guard" not in _rules_applied(st), words


def test_a_question_item_never_creates(cfg):
    q = _item("query_schedule", SimpleNamespace(), id="item_1-1", kind="review",
              text="On the day project one is due, does my daughter have a recital?")
    junk = _item("create_todo", SimpleNamespace(title="project one", due_date=None),
                 id="item_1-2", kind="task",
                 text="On the day project one is due, does my daughter have a recital?")
    st = _state("On the day project one is due, does my daughter have a recital?",
                [q, junk])
    validate.run_objects(st, cfg)
    assert junk.intent is None
    assert q.intent is not None


def test_a_booking_next_to_a_question_survives(cfg):
    ev = _item("create_event", _event_intent(title="gym", date="2026-09-08",
                                             start_time="07:00"),
               id="item_1", text="book gym tuesday at 7am")
    q = _item("query_schedule", SimpleNamespace(), id="item_2", kind="review",
              text="what do I have on friday?")
    st = _state("book gym tuesday at 7am and what do I have on friday?", [ev, q])
    validate.run_objects(st, cfg)
    assert ev.intent is not None


def test_from_less_removes_become_deletes(cfg):
    it = _item("create_todo", SimpleNamespace(title="get rid of this list",
                                              due_date=None), kind="task")
    st = _state("get rid of this list", [it])
    validate.run_objects(st, cfg)
    assert it.action == "delete_todo"


def test_a_misheard_erase_still_guards(cfg):
    it = _item("create_event", _event_intent(title="earse the next birthday event"))
    st = _state("Please earse the next birthday event", [it])
    validate.run_objects(st, cfg)
    assert it.action == "delete_todo" or it.intent is None


def test_an_imperative_query_creates_nothing(cfg):
    it = _item("create_event", _event_intent(title="Reminder: meeting"),
               text="give me the reminders")
    st = _state("give me the reminders", [it])
    validate.run_objects(st, cfg)
    assert it.intent is None


def test_open_a_new_list_is_not_a_query(cfg):
    it = _item("create_todo", SimpleNamespace(title="new list", due_date=None),
               kind="task", text="Open up a new list")
    st = _state("Open up a new list", [it])
    validate.run_objects(st, cfg)
    assert it.intent is not None


def test_stray_quotes_are_shed_before_parsing(cfg, monkeypatch):
    monkeypatch.setattr(engine_llm, "call_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM")))
    st = _state("x", [Item(id="item_1", kind="event", text="add 'christmas' to calendar")])
    validate.run(st, cfg)
    assert st.items[0].text == "add christmas to calendar"


def test_a_value_fix_names_the_field_not_the_whole_command():
    """The note lands in the review panel, so it is written for a reader.

    It used to be `f"{item.text!r}: {said or spoken!r}"` — and on the fast path
    `item.text` IS the whole transcript, so every fix repeated the entire
    command TWICE. Two of them filled the card with a wall of quoted text, which
    is what a screenshot of the real panel showed. `before → after` already
    carries the values; what the reader cannot otherwise see is which field
    moved.
    """
    from assistant.engine import load_config
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.state import EngineState, Item
    from assistant.actions.calendar.intent import CalendarIntent

    text = "book gym tomorrow at 7 and remind me to buy milk"
    st = EngineState(raw_text=text, text=text)
    it = Item(id="item_1", kind="event", text=text,
              action="create_event",
              intent=CalendarIntent(title="gym", date="2026-09-11",
                                    start_time="19:00", end_time="20:00"))
    st.items = [it]
    _dv.run_objects(st, load_config())

    notes = [f.note for f in st.fixes if f.rule == "resolve_from_own_words"]
    for n in notes:
        assert text not in n, f"the note repeats the whole command: {n!r}"
        assert len(n) < 24, f"a note this long is a wall, not a label: {n!r}"


def test_a_new_list_goes_to_general_on_the_deep_path_too():
    """Gil, 2026-09-20 (DEVQA Q33): a new list is a to-do in GENERAL. The
    fast path reads it off its own frame; the deep path takes the list name
    from the model, which answers "today" — so "Make a new list of dog
    breeds" landed on Today whenever the command was compound enough to go
    deep, and the ruling held on one track only."""
    import assistant.engine as engine
    from assistant.engine.state import EngineState
    from assistant.intent import rule_parser as RP
    from freezegun import freeze_time

    RP._ensure_nlp(); RP._ensure_dt()
    cfg = engine.load_config()
    with freeze_time("2026-09-09 10:00:00"):
        st = EngineState(raw_text="Make a new list of dog breeds. Also, Create a new list, please",
                         text="Make a new list of dog breeds. Also, Create a new list, please")
        engine.Engine().parse(st, cfg)
        lists = [getattr(i.intent, "list_name", None) for i in st.items
                 if i.intent is not None and i.action == "create_todo"]
        assert lists and all(v == "general" for v in lists), lists
        # an item FOR an existing list is not the making of one
        st2 = EngineState(raw_text="add milk to my list", text="add milk to my list")
        engine.Engine().parse(st2, cfg)
        assert [getattr(i.intent, "list_name", None) for i in st2.items
                if i.intent is not None] == ["today"]
