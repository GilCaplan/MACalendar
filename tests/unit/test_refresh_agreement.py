"""The `refresh` signal is a CONTRACT between three codebases, so pin it.

`state.refresh` is how a committed row becomes a visible row: the engine names
which surface it wrote to, and each client reloads that surface. If the engine
ever emitted a word a client does not branch on, nothing would break, nothing
would log, and the row would simply not appear until something else triggered a
reload — the worst shape of bug, indistinguishable from "the command didn't
work".

Nothing else checks this. `_commit` is Python, the Mac reads it in Python, and
iOS reads it in Swift; no type system spans the three. This file does, the same
way `test_panel_agreement.py` ties the engine to the panel.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
IOS = ROOT / "MACalendar-iOS" / "MACalendar-iOS"

#: The complete vocabulary `_commit` can produce. "" means nothing was written
#: and no client should reload.
REFRESH_VALUES = {"events", "todos", "both", ""}


def test_the_engine_emits_only_these_words():
    """Read the orchestrator rather than trusting the constant above."""
    src = (ROOT / "assistant" / "engine" / "__init__.py").read_text()
    body = src[src.index("def _commit("):src.index("def _loop_target(")]
    emitted = set(re.findall(r'state\.refresh = "([a-z]*)"', body))
    emitted |= set(re.findall(r'refresh_set\.add\("([a-z]+)"\)', body))
    assert emitted <= REFRESH_VALUES, (
        f"_commit emits {emitted - REFRESH_VALUES}, which no client branches on")
    assert {"events", "todos", "both"} <= emitted | {"both"}, (
        "_commit no longer names the surfaces it wrote to")


def test_ios_branches_on_every_word_the_engine_can_send():
    """iOS is PRECISE — it reloads only the surface that changed — which means
    a word it does not know is silently ignored. That precision is what makes
    this test necessary."""
    swift = "\n".join((IOS / "Views" / p).read_text()
                      for p in ("ContentView.swift", "TasksView.swift"))
    handled = set(re.findall(r'refresh == "([a-z]+)"', swift))
    missing = {"events", "todos", "both"} - handled
    assert not missing, (
        f"iOS never reloads for {sorted(missing)} — a row written to that "
        f"surface would not appear until something else triggered a reload")


def test_the_mac_reloads_on_any_refresh():
    """The Mac is COARSE by choice: any refresh reloads both surfaces. Wasteful
    and safe — the failure mode iOS has (an unknown word ignored) cannot happen
    here. Pinned so a future 'optimisation' to branch on the value has to come
    with the same agreement check iOS needs."""
    pipeline = (ROOT / "assistant" / "pipeline.py").read_text()
    assert re.search(r'if\s+\w+\.get\("refresh"\)', pipeline), (
        "the Mac pipeline no longer reacts to the engine's refresh field")
    window = (ROOT / "assistant" / "calendar_ui" / "window.py").read_text()
    block = window[window.index("if status == STATUS_REFRESH:"):]
    block = block[:block.index("elif")]
    assert "refresh_calendar()" in block and "refresh_todos()" in block, (
        "the Mac's refresh no longer reloads both surfaces")


def test_a_command_that_wrote_nothing_asks_for_no_reload():
    """The empty string is a real value and means 'do not reload'. A query
    ('what's on tomorrow?') writes nothing, and reloading on it would flicker
    both views for no reason."""
    from assistant.engine.state import EngineState
    assert EngineState(raw_text="x").refresh == ""
