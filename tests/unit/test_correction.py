"""A stored correction is annotated with what it TELLS us.

`intent/correction.py`: which fields changed against the engine's parse and
which of the new values the words could reach. Both storage paths — the review
view's explicit `set_feedback` and the implicit edit-of-a-record path — carry
the annotation, so the real-usage board can score a corrected row per field
instead of hand-marking whole rows (2026-09-22).
"""
from __future__ import annotations

from assistant.intent import correction as C
from assistant.intent.memory import CommandMemory, FEEDBACK_CORRECTED


THEN = [{"action": "create_event",
         "parameters": {"title": "meeting", "date": "2026-08-27",
                        "start_time": "10:00", "end_time": "11:00"}}]


def _gold(**changes):
    g = {"action": "create_event", "parameters": dict(THEN[0]["parameters"])}
    g["parameters"].update(changes)
    return [g]


def test_an_unchanged_field_is_reachable_and_not_changed():
    got = C.annotate("set a meeting for 10 a.m. tomorrow", THEN, _gold())
    assert got[0]["changed"] == []
    assert all(got[0]["reachable"][f] for f in C.FIELDS)


def test_a_typed_title_is_a_change_the_words_cannot_reach():
    said = "Set a meeting for 10 a.m. tomorrow morning, execute."
    got = C.annotate(said, THEN, _gold(title="Date ❤️", start_time="11:00", end_time="15:00"))
    assert got[0]["changed"] == ["title", "start_time", "end_time"]
    assert got[0]["reachable"]["title"] is False
    # 11:00 and 15:00 sit on the spoken grid, so they stay scoreable even
    # though this speaker moved them by hand — the rule is the grid, said so.
    assert got[0]["reachable"]["start_time"] is True


def test_a_title_made_of_words_that_were_said_is_reachable():
    said = "set a meeting tomorrow at 10 with omri for the project"
    got = C.annotate(said, THEN, _gold(title="Meeting with Omri for the project"))
    assert got[0]["changed"] == ["title"]
    assert got[0]["reachable"]["title"] is True


def test_a_dragged_clock_is_not_reachable_but_a_spoken_one_is():
    assert C.reachable_fields("x", THEN[0], _gold(start_time="09:02")[0])["start_time"] is False
    assert C.reachable_fields("x", THEN[0], _gold(start_time="15:45")[0])["start_time"] is True


def test_a_moved_date_is_a_change_of_plan_not_a_misreading():
    r = C.reachable_fields("set it for tomorrow", THEN[0], _gold(date="2026-08-28")[0])
    assert r["date"] is False


def test_an_action_beyond_what_the_engine_made_is_all_change():
    got = C.annotate("buy milk and eggs", [], [{"action": "create_todo",
                                                "parameters": {"title": "buy eggs"}}])
    assert "action" in got[0]["changed"] and "title" in got[0]["changed"]
    assert got[0]["reachable"]["title"] is True      # the words were said


def test_the_explicit_review_path_stores_the_annotation(tmp_path):
    m = CommandMemory(str(tmp_path / "m.db"))
    ex = m.record(transcript="set a meeting tomorrow at 10 with omri", source="ios",
                  actions=[("create_event", THEN[0]["parameters"])])
    assert m.set_feedback(ex, FEEDBACK_CORRECTED,
                          _gold(title="meeting with omri", start_time="09:02"))
    stored = m.get(ex)["correction"][0]
    assert stored["parameters"]["title"] == "meeting with omri"     # what it stores
    assert stored["changed"] == ["title", "start_time"]              # what it tells
    assert stored["reachable"] == {"title": True, "date": True, "start_time": False,
                                   "end_time": True, "recurrence": True,
                                   "recur_until": True}


def test_the_implicit_edit_path_stores_the_annotation_too(tmp_path):
    m = CommandMemory(str(tmp_path / "m.db"))
    ex = m.record(transcript="set a meeting tomorrow at 10 with omri", source="ios",
                  actions=[("create_event", THEN[0]["parameters"])],
                  records=[("event", 7, "create_event", 0)])
    assert m.feedback_for_record("event", 7, FEEDBACK_CORRECTED,
                                 {"title": "Meeting with Omri", "color": "#fff"}) == ex
    stored = m.get(ex)["correction"][0]
    assert stored["changed"] == ["title"]
    assert stored["reachable"]["title"] is True


def test_a_reader_that_only_wants_action_and_parameters_is_unaffected(tmp_path):
    # The stored correction still starts with what every consumer read before.
    m = CommandMemory(str(tmp_path / "m.db"))
    ex = m.record(transcript="x", actions=[("create_event", THEN[0]["parameters"])])
    m.set_feedback(ex, FEEDBACK_CORRECTED, _gold(title="y"))
    stored = m.get(ex)["correction"][0]
    assert set(stored) >= {"action", "parameters"}


def test_an_end_time_is_reachable_only_when_the_words_give_an_end():
    """2026-09-24: Gil's "walk Jada at 2pm", corrected to end at 14:30, was
    scored reachable because 14:30 sits on the five-minute grid. Nothing in
    the words states a length; the default hour is the honest answer."""
    from assistant.intent.correction import reachable_fields
    then = {"action": "create_event", "parameters": {"start_time": "14:00", "end_time": "15:00"}}
    gold = {"action": "create_event", "parameters": {"start_time": "14:00", "end_time": "14:30"}}
    assert reachable_fields("I need to walk Jada at 2pm today", then, gold)["end_time"] is False
    assert reachable_fields("walk Jada from 2 to 2:30pm", then, gold)["end_time"] is True
    assert reachable_fields("walk Jada at 2pm for 30 minutes", then, gold)["end_time"] is True
    assert reachable_fields("walk Jada at 2pm for half an hour", then, gold)["end_time"] is True
