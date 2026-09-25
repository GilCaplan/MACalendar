"""Board D's full scoring: structure, fields, cost, restraint, speed."""
from __future__ import annotations

from assistant.engine.llmjudge.experiments import board_metrics as BM


def _row(i, action, text, events=0, tasks=0, **slots):
    return {"id": i, "family": "s_x", "text": text,
            "expect": {"action": action, "events": events, "tasks": tasks, "slots": slots}}


def _ev(title, date=None, start=None, **kw):
    return {"action": "create_event", "title": title, "date": date, "start_time": start, **kw}


def test_fields_structure_and_restraint():
    rows = [
        _row("a", "create_event", "book dentist tomorrow at 3pm", events=1,
             title="dentist", date_phrase="tomorrow", time_phrase="3pm"),
        _row("b", "create_event", "book gym tomorrow at 7pm", events=1,
             title="gym", date_phrase="tomorrow", time_phrase="7pm"),
        _row("c", "mixed", "book x and buy y", events=1, tasks=1),
        _row("d", "propose", "should i book yoga tomorrow?"),
    ]
    built = {
        "a": {"objs": [_ev("dentist", "2026-09-10", "15:00")], "ms": 50, "llm_ms": 0},
        "b": {"objs": [_ev("gym", "2026-09-10", "07:00")], "ms": 4000, "llm_ms": 3000},
        "c": {"objs": [_ev("x")], "ms": 60, "llm_ms": 0},                   # the to-do went missing
        "d": {"objs": [_ev("yoga")], "ms": 60, "llm_ms": 0},                # booked a question
    }
    m = BM.score(rows, built, {"a": True, "b": False, "c": False, "d": False})
    c = m["c"]
    assert (c["date_ok"], c["date_n"]) == (2, 2)
    assert (c["time_ok"], c["time_n"]) == (1, 2)                           # 7pm read as 07:00
    assert (c["count_ok"], c["count_n"]) == (2, 3) and c["missing"] == 1
    assert (c["propose_held"], c["propose_n"]) == (0, 1)
    assert c["model_rows"] == 1 and c["wrong"] == 3
    BM.report(m)                                                             # prints without error
    assert BM.as_record(m)["counts"]["rows"] == 4


def test_a_destructive_mistake_costs_more():
    rows = [_row("x", "create_event", "book lunch", events=1, title="lunch")]
    built = {"x": {"objs": [{"action": "delete_event", "title": "lunch"}], "ms": 1, "llm_ms": 0}}
    m = BM.score(rows, built, {"x": False})
    assert m["c"]["harm"] == 4 and m["destructive"]["delete_event"] == 1


def test_the_range_gold_follows_the_rulings_not_the_engine():
    from assistant.engine.fastrule.experiments.gold import ruled_range
    assert ruled_range("from 6 to 8", "book yoga from 6 to 8") == ("18:00", "20:00")   # Q28
    assert ruled_range("between 2 and 4", "open house between 2 and 4 this afternoon") \
        == ("14:00", "16:00")
    assert ruled_range("from 6 to 8", "this morning from 6 to 8") == ("06:00", "08:00")
    assert ruled_range("from 9 to 11pm", "x") == ("21:00", "23:00")   # the end lends its half
    assert ruled_range("from 11 to 1", "x") == ("11:00", "13:00")     # a bare end follows the start
    assert ruled_range("between 5 and 6:30", "x") == ("17:00", "18:30")
    assert ruled_range("at 6", "x") is None
