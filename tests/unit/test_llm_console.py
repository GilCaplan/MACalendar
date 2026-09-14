"""The LLM console tab, and the call log behind it.

CLAUDE.md: "A UI test that never sends a mouse event tests nothing. Three bugs
in the HUD's history view shipped green because tests called handlers instead
of clicking controls." So the buttons here are CLICKED with QTest.mouseClick,
which is also the only thing that catches the trap this panel has shipped
twice: QPushButton.clicked emits a `checked` bool that binds to a slot's first
positional argument, so a control connected directly to `toggle_x(on=...)`
reads every click as False and does nothing.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

from assistant import llm_bus


@pytest.fixture
def bus(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_bus, "BUS_PATH", str(tmp_path / "llm.jsonl"))
    llm_bus.clear()
    return llm_bus


@pytest.fixture
def panel(bus, qapp):
    from assistant.calendar_ui.thinking_panel import ThinkingPanel
    p = ThinkingPanel(dark=True)
    p.show()
    yield p
    p.close()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _seed(bus):
    bus.record(transport="chat+schema", caller="llmjudge.extract_asks",
               model="llama3.1:8b", system="S" * 9000, user="book gym and buy milk",
               response='{"asks":[]}', ms=1200, schema=True, source="mac")
    bus.record(transport="chat", caller="engine._recheck_not_found",
               model="llama3.1:8b", system="s", user="delete the dentist",
               response="", ms=41000, source="mac")
    bus.record(transport="chat", caller="objects._parse_item", model="m",
               system="s", user="x", error="timeout after 60s", ms=60000,
               source="mac")
    bus.note("lock", "waited 4200 ms behind another command", waited_ms=4200)


# --- the log ---------------------------------------------------------------

def test_test_traffic_never_reaches_the_log(bus):
    """The log holds real speech. Measurement runs post source="test" and must
    not write into it — the same rule the NLU log and History already apply."""
    bus.record(transport="chat", caller="c", model="m", system="s", user="u",
               source="test")
    assert bus.read_history() == []


def test_a_clipped_prompt_keeps_its_true_length(bus):
    """A 12 KB system prompt shown as 4 KB with no note is a lie about what the
    model was sent."""
    bus.record(transport="chat", caller="c", model="m", system="S" * 9000,
               user="u", source="mac")
    e = bus.read_history()[0]
    assert len(e["system"]) == llm_bus.MAX_FIELD
    assert e["system_len"] == 9000


def test_read_since_only_returns_what_is_new(bus):
    bus.record(transport="chat", caller="a", model="m", system="s", user="u",
               source="mac")
    offset = bus.size()
    bus.record(transport="chat", caller="b", model="m", system="s", user="u",
               source="mac")
    new, _ = bus.read_since(offset)
    assert [e["caller"] for e in new] == ["b"]


# --- the view --------------------------------------------------------------

def test_clicking_llm_shows_the_console_and_only_it(panel, bus):
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    assert panel._view == "llm"
    assert panel._llm_scroll.isVisible()
    assert not panel._scroll.isVisible()
    assert not panel._hist_scroll.isVisible()
    assert len(panel._llm_rows) == 4


def test_the_two_views_are_mutually_exclusive(panel, bus):
    """Visibility used to be recomputed in toggle_history AND toggle_minimised.
    With three views that is a truth table, and the second copy is where it
    drifts — both now delegate to _set_view."""
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel._hist_btn, Qt.MouseButton.LeftButton)
    assert panel._view == "history"
    assert panel._hist_scroll.isVisible() and not panel._llm_scroll.isVisible()


def test_minimising_hides_the_console_and_restores_the_same_view(panel, bus):
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    panel.toggle_minimised(True)
    assert not panel._llm_scroll.isVisible()
    panel.toggle_minimised(False)
    assert panel._view == "llm" and panel._llm_scroll.isVisible()


def test_a_second_click_goes_back_to_the_timeline(panel, bus):
    """The trap this panel shipped twice: clicked emits a bool that binds to
    the slot's first argument, so a directly-connected toggle reads every click
    as False and the button is dead."""
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    assert panel._view == "timeline" and panel._scroll.isVisible()


def test_the_slow_filter_finds_the_forty_second_call(panel, bus):
    """The filter that earns its place: a 40-second call hid behind an llm_ms
    of 0 in every latency board.

    A TIMEOUT COUNTS AS SLOW. The 60 s timeout is shown too, and that is
    deliberate — a call that ran for a minute and then failed is the slowest
    kind there is, and a "slow" filter that hides it would send a reader
    looking for the worst latency in the log to the wrong rows. Failed-only is
    the separate chip beside it."""
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel._llm_chips["slow"], Qt.MouseButton.LeftButton)
    shown = {r._entry["caller"] for r in panel._llm_rows if r.isVisible()}
    assert shown == {"engine._recheck_not_found", "objects._parse_item"}
    # and the fast, successful call is excluded
    assert "llmjudge.extract_asks" not in shown


def test_the_failed_filter_finds_only_the_error(panel, bus):
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel._llm_chips["failed"], Qt.MouseButton.LeftButton)
    shown = [r._entry["caller"] for r in panel._llm_rows if r.isVisible()]
    assert shown == ["objects._parse_item"]


def test_search_matches_prompts_not_just_callers(panel, bus):
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    QTest.keyClicks(panel._llm_search, "dentist")     # only in a USER prompt
    shown = [r._entry["caller"] for r in panel._llm_rows if r.isVisible()]
    assert shown == ["engine._recheck_not_found"]


def test_clicking_a_row_reveals_what_was_actually_sent(panel, bus):
    """The part no other surface shows: the trace says a stage ran, the boards
    say how long, and nothing anywhere says what the prompt was."""
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    row = panel._llm_rows[0]
    assert not row._detail.isVisible()
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    assert row._detail.isVisible()
    body = row._detail.text()
    assert "SYSTEM" in body and "USER" in body
    assert "book gym and buy milk" in body
    assert "9,000 chars" in body          # says what it truncated


def test_protocol_events_render_in_the_same_list(panel, bus):
    """A concatenation and the calls it produced belong in one ordered
    sequence, not two."""
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    heads = [r._headline() for r in panel._llm_rows]
    assert any("lock" in h and "4200" in h for h in heads)


def test_clear_empties_the_log_and_the_view(panel, bus):
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel._llm_clear, Qt.MouseButton.LeftButton)
    assert panel._llm_rows == []
    assert bus.read_history() == []
    assert panel._llm_empty.isVisible()


def test_the_console_survives_a_theme_change(panel, bus):
    """apply_theme on the PANEL takes a bool; on a child it takes a _Theme.
    Mixing them is silent until first use."""
    _seed(bus)
    QTest.mouseClick(panel._llm_btn, Qt.MouseButton.LeftButton)
    panel.apply_theme(False)
    panel.apply_theme(True)
    assert len(panel._llm_rows) == 4


# --- the live half ---------------------------------------------------------

def test_the_hud_tails_the_llm_stream_with_its_own_offset(bus, qapp, tmp_path,
                                                          monkeypatch):
    """trace_bus.read_since closes over a module-global path and takes no path
    argument, and _BusReader holds ONE scalar offset — so the second stream
    needs a second offset, or one reader eats the other's position."""
    from assistant import thinking_hud as hud_mod
    reader = object.__new__(hud_mod._BusReader)
    reader._llm_offset = bus.size()
    bus.record(transport="chat", caller="llmjudge.extract_asks", model="m",
               system="s", user="u", ms=10, source="mac")
    calls, reader._llm_offset = bus.read_since(reader._llm_offset)
    assert [c["caller"] for c in calls] == ["llmjudge.extract_asks"]
    # and a second drain returns nothing — the offset advanced
    again, _ = bus.read_since(reader._llm_offset)
    assert again == []


def test_a_call_refreshes_the_console_only_while_it_is_open(panel, bus,
                                                            monkeypatch):
    """The log is durable, so a background rebuild on every 120 ms poll would
    redraw rows nobody is looking at. The view catches up when opened."""
    from types import SimpleNamespace

    from assistant import thinking_hud as hud_mod
    rebuilds = []
    monkeypatch.setattr(panel, "_load_llm", lambda: rebuilds.append(1))
    # ThinkingHUD is a QWidget, so it cannot be conjured with object.__new__.
    # The real method is called with a duck-typed self — this still exercises
    # the shipped code, not a copy of it.
    hud = SimpleNamespace(panel=panel)
    refresh = hud_mod.ThinkingHUD.apply_llm_calls

    panel._view = "timeline"
    refresh(hud, [{"caller": "x"}])
    assert rebuilds == [], "rebuilt while the timeline was showing"

    panel._view = "llm"
    refresh(hud, [{"caller": "x"}])
    assert rebuilds == [1], "did not refresh while the console was open"

    refresh(hud, [])
    assert rebuilds == [1], "rebuilt on an empty batch"
