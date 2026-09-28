"""The HUD's command graph: one command as asks → who decided → what each became.

Gil, 2026-09-28: *"in the HUD can you add a more interactive viz option as
well, like a graph, but also that doesn't get too cluttered"*.

Two halves, tested apart: `build_graph` reads a trace into lanes with no
screen, and the view is driven through REAL mouse events — `QTest.mouseClick`
on the header button and on the painted nodes — because three HUD bugs once
shipped green under tests that called handlers instead of clicking.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPointF, Qt                           # noqa: E402
from PyQt6.QtTest import QTest                                 # noqa: E402
from PyQt6.QtWidgets import QApplication                       # noqa: E402

from assistant.calendar_ui import command_graph as cg          # noqa: E402
from assistant.calendar_ui import thinking_panel               # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ fixtures

def _deep():
    steps = [
        {"stage": "stt", "title": "Heard", "detail": "dentist friday at 3pm and buy milk, and also open my list",
         "ms": 900, "ok": True},
        {"stage": "vocab", "title": "Vocabulary", "detail": "No corrections needed", "ms": 40, "ok": True},
        {"stage": "rule", "title": "Rule parser", "detail": "(0.00) compound — deep track", "ms": 30, "ok": True},
        {"stage": "rule", "title": "Split into commands", "detail": "3 item(s)", "ms": 12, "ok": True},
        {"stage": "rule", "title": "Built the objects", "detail": "1 of 3 converted; 1 to the model",
         "ms": 210, "ok": True},
        {"stage": "llm", "title": "Read part 2", "detail": "ollama", "ms": 4100, "ok": True},
        {"stage": "verify", "title": "Cross-check", "detail": "every field traced", "ms": 9, "ok": True},
        {"stage": "execute", "title": "Create Event", "detail": "Created event 'dentist' Fri 3 PM.", "ok": True},
        {"stage": "execute", "title": "Create Todo", "detail": "Added 'milk' to Today.", "ok": True},
        {"stage": "done", "title": "Done", "detail": "deep path · 4.6 s total", "ok": True,
         "data": {"path": "deep"}},
    ]
    bounds = [
        {"label": "X1", "value": "dentist friday at 3pm and buy milk, and also open my list"},
        {"label": "X2", "value": "(clipped)", "parts": [
            {"kind": "event", "text": "dentist friday at 3pm", "time": "friday at 3pm"},
            {"kind": "task", "text": "buy milk", "time": ""},
            {"kind": "other", "text": "open my list", "time": ""}]},
        {"label": "X3", "value": "(clipped)", "parts": [
            {"text": "dentist", "when": {"date": "2026-10-02", "start_time": "15:00"}},
            {"text": "buy milk", "when": {}}, {"text": "open my list", "when": {}}]},
        {"label": "X4", "value": "(clipped)", "parts": [
            {"text": "dentist friday at 3pm", "kind": "event", "action": "create_event",
             "title": "dentist", "date": "2026-10-02", "start_time": "15:00", "line": "create event · title=dentist"},
            {"text": "buy milk", "kind": "task", "action": "create_todo", "title": "milk", "line": "create todo"},
            {"text": "open my list", "kind": "other", "action": "", "title": "", "line": "",
             "junk": "managing lists isn't something I do"}]},
    ]
    return steps, bounds, {"message": "Booked it.", "actions": ["create_event", "create_todo"]}


# ------------------------------------------------------------------ reading

def test_each_ask_is_a_lane_ending_in_what_it_became():
    steps, bounds, result = _deep()
    g = cg.build_graph(steps, bounds, result)
    assert [ln.text for ln in g.lanes] == ["dentist friday at 3pm", "buy milk", "open my list"]
    assert [ln.action for ln in g.lanes] == ["create_event", "create_todo", ""]
    assert g.lanes[2].junk                               # thrown out, and says why
    assert g.lanes[0].outcome.endswith("15:00")
    assert g.lanes[0].resolved == {"date": "2026-10-02", "start_time": "15:00"}
    # what was written lands on the lane that made it, in order
    assert "dentist" in g.lanes[0].outcome_detail and "milk" in g.lanes[1].outcome_detail
    assert g.path == "deep" and g.check_ok is True


def test_the_ask_the_model_read_is_marked_and_only_that_one():
    g = cg.build_graph(*_deep())
    assert [ln.decided_by for ln in g.lanes] == ["rules", "model", "rules"]
    assert g.lanes[1].decided_ms == 4100
    # the rule parser's time is the whole command's — not any one ask's
    assert g.lanes[0].decided_ms == 0


def test_an_older_trace_without_parts_still_draws_from_its_display_strings():
    """History holds traces from before `parts` existed; they must still draw."""
    bounds = [
        {"label": "X2", "value": "(event) dentist · friday at 3pm | (task) buy milk"},
        {"label": "X4", "value": "create event · title=dentist · date=2026-10-02 · start_time=15:00"
                                 " | create todo · titles=milk"},
    ]
    g = cg.build_graph([], bounds, {})
    assert [(ln.text, ln.kind, ln.time) for ln in g.lanes] == [
        ("dentist", "event", "friday at 3pm"), ("buy milk", "task", "")]
    assert [ln.action for ln in g.lanes] == ["create_event", "create_todo"]


def test_the_fast_path_is_one_lane_the_rules_read_whole():
    steps = [
        {"stage": "vocab", "title": "Vocabulary", "detail": "AMC ← ACM", "ok": True,
         "data": {"transcript": "movie tomorrow at 10:30 at the AMC"}},
        {"stage": "rule", "title": "Rule parser", "detail": "Confident (0.85)", "ms": 111, "ok": True},
        {"stage": "verify", "title": "Cross-check", "detail": "start_time = 10:30 — nothing in the words said it",
         "ok": False},
        {"stage": "done", "title": "Fast answer", "detail": "rules answered in 2.2 s", "ok": True,
         "data": {"path": "fast"}},
    ]
    bounds = [{"label": "X4", "value": "create event · title=movie at the amc · date=2026-10-02"}]
    g = cg.build_graph(steps, bounds, {}, heard="movie tomorrow at 10:30 at the ACM")
    assert g.path == "fast" and len(g.lanes) == 1
    assert g.lanes[0].decided_ms == 111                  # one ask: the time IS its own
    assert g.fixes == "AMC ← ACM" and g.heard != g.repaired
    assert g.check_ok is False
    assert cg.unsupported(g.check) == "start_time wasn't in the words"


def test_a_loop_back_is_counted_and_the_second_pass_is_the_one_drawn():
    first = {"label": "X2", "value": "", "parts": [{"kind": "event", "text": "a b c", "time": ""}]}
    second = {"label": "X2", "value": "", "parts": [{"kind": "event", "text": "a", "time": ""},
                                                     {"kind": "event", "text": "b", "time": ""}]}
    steps = [{"stage": "verify", "title": "Looping back", "detail": "", "ok": False}]
    g = cg.build_graph(steps, [first, second], {})
    assert g.loops == 1 and [ln.text for ln in g.lanes] == ["a", "b"]


def test_a_trace_with_no_boundaries_draws_one_lane_per_object_written():
    steps = [{"stage": "execute", "title": "Create Todo", "detail": "Added 'milk'.", "ok": True}]
    g = cg.build_graph(steps, [], {})
    assert [ln.action for ln in g.lanes] == ["create_todo"]


def test_an_ask_the_model_built_after_x4_takes_its_object_from_what_was_written():
    """X4 is published before the rescue's model call, so it says "nothing
    built" for an ask the model then built — the execute step is the truth."""
    bounds = [{"label": "X2", "value": "", "parts": [{"kind": "event", "text": "kingdom at one", "time": ""}]},
              {"label": "X4", "value": "nothing built", "parts": [
                  {"text": "kingdom at one", "kind": "event", "action": "", "title": "", "line": ""}]}]
    steps = [{"stage": "llm", "title": "Read part 1", "ms": 64000, "ok": True},
             {"stage": "execute", "title": "Create Event",
              "detail": "Created event 'Kingdom' on Friday, Sep 25, 2026 from 1 PM to 2 PM.", "ok": True}]
    (lane,) = cg.build_graph(steps, bounds, {}).lanes
    assert lane.action == "create_event" and lane.decided_by == "model"
    assert lane.outcome == "Fri 25 Sep 1 PM"


def test_junk_input_never_raises():
    cg.build_graph([None, "x", {"stage": "llm"}], [{"label": "X4", "parts": [{}]}], None)


def test_the_engine_publishes_parts_beside_each_display_string(monkeypatch):
    """`parts` is every item, built or not, so part i is item i."""
    from assistant.engine import boundary
    from assistant.engine.llmjudge import render
    monkeypatch.setattr(render, "render_line", lambda a, i, s: f"{a} line")
    got = []
    trace = SimpleNamespace(boundary=lambda label, value, detail, parts=None: got.append((label, parts)))
    items = [SimpleNamespace(kind="event", text="dentist", time="fri 3pm", intent=object(),
                             action="create_event", slots={"title": "dentist", "date": "2026-10-02"}),
             SimpleNamespace(kind="other", text="open my list", time="", intent=None, action=None,
                             slots={"junk": "managing lists"})]
    state = SimpleNamespace(trace=trace, items=items, text="x")
    boundary.emit("segment", state)
    boundary.emit("fastrule", state)
    (l2, p2), (l4, p4) = got
    assert l2 == "X2" and [p["text"] for p in p2] == ["dentist", "open my list"]
    assert l4 == "X4" and len(p4) == 2
    assert p4[0]["action"] == "create_event" and p4[0]["date"] == "2026-10-02"
    assert p4[1]["action"] == "" and p4[1]["junk"] == "managing lists"


# ------------------------------------------------------------------ the view

@pytest.fixture(params=(True, False), ids=("dark", "light"))
def panel(qapp, request):
    """Both themes: a colour read off a missing `_Theme` attribute raises inside
    paintEvent, which aborts the interpreter rather than failing a test."""
    p = thinking_panel.ThinkingPanel(dark=request.param)
    steps, bounds, result = _deep()
    p.begin("mac")
    p.set_input("dentist friday at 3pm and buy milk, and also open my list")
    for s in steps:
        p.add_step(s)
    for b in bounds:
        p.add_boundary(b)
    p.finish(result)
    p.show()
    qapp.processEvents()
    yield p
    p.close()


def _click(widget, pos) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPointF(pos).toPoint())
    QApplication.processEvents()


def test_the_graph_button_swaps_the_list_for_the_graph_and_back(panel):
    _click(panel._graph_btn, panel._graph_btn.rect().center())
    assert panel._graph_scroll.isVisible() and not panel._scroll.isVisible()
    assert panel._graph_btn.text() == "List"
    assert len(panel._graph.graph.lanes) == 3
    _click(panel._graph_btn, panel._graph_btn.rect().center())
    assert panel._scroll.isVisible() and not panel._graph_scroll.isVisible()


def test_clicking_a_node_says_what_is_behind_it_and_again_closes_it(panel):
    _click(panel._graph_btn, panel._graph_btn.rect().center())
    g = panel._graph
    g.repaint()
    _click(g, g.node_center("outcome", 2))
    assert panel._graph_detail.isVisible()
    assert "managing lists" in panel._graph_detail.text()
    _click(g, g.node_center("outcome", 2))
    assert not panel._graph_detail.isVisible()
    _click(g, g.node_center("decider", 1))
    assert "model" in panel._graph_detail.text()


def test_hovering_an_ask_lights_its_lane_only(panel, qapp):
    _click(panel._graph_btn, panel._graph_btn.rect().center())
    g = panel._graph
    g.repaint()
    # Away first: a move to where the pointer already is sends no event, and
    # both theme runs put their card at the same place on the screen.
    QTest.mouseMove(g, g.node_center("root").toPoint())
    qapp.processEvents()
    QTest.mouseMove(g, g.node_center("ask", 1).toPoint())
    qapp.processEvents()
    assert g._hover == 1
    QTest.mouseMove(g, g.node_center("ask", 0).toPoint())
    qapp.processEvents()
    assert g._hover == 0


def test_history_comes_back_to_the_graph_when_that_is_where_you_were(panel):
    _click(panel._graph_btn, panel._graph_btn.rect().center())
    panel.toggle_history(True)
    _click(panel._hist_btn, panel._hist_btn.rect().center())          # "Back"
    assert panel._graph_scroll.isVisible()


def test_a_new_command_fills_the_graph_live(panel, qapp):
    _click(panel._graph_btn, panel._graph_btn.rect().center())
    panel.begin("ios")
    assert panel._graph.graph.running and not panel._graph.graph.lanes
    panel.add_boundary({"label": "X2", "value": "", "parts": [{"kind": "task", "text": "buy eggs", "time": ""}]})
    assert [ln.text for ln in panel._graph.graph.lanes] == ["buy eggs"]
    assert panel._graph_scroll.isVisible()                            # the choice sticks
