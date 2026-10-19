"""Archive and delete on the phone's Timer tab happen at the tap.

Gil, 2026-10-19: "Archive on timer tab either slow or not working when i press
on a timer". The swipe action awaited the Mac's PATCH and then a full reload
before anything moved — seconds over the tailnet — and with the Mac away the
write was queued but the cache was never touched, so the row did not move at
all. Read off the Swift source, like the other iOS checks (no Swift target in
CI).
"""

from __future__ import annotations

from tests.unit._ios_sources import ios_source

VIEW = ios_source("TimerView.swift")
STORE = ios_source("LocalStore.swift")


def _func(src: str, sig: str) -> str:
    return src.split(sig, 1)[1].split("\n    }\n", 1)[0]


def test_the_swipe_changes_the_screen_and_the_cache_before_the_mac_answers():
    for kind, setter, remover in (("timer", "setTimerArchived", "removeTimer"),
                                  ("counter", "setCounterArchived", "removeCounter")):
        body = _func(VIEW, f"private func change({kind} id: Int")
        task = body.index("Task {")
        assert body.index(f"LocalStore.shared.{setter}") < task, kind
        assert body.index(f"LocalStore.shared.{remover}") < task, kind
        assert body.index("applyPending(") < task, kind          # the list moves at once
    # the swipe actions go through it, not straight to the Mac
    assert "change(timer: t.id, .archived(t.archived != 1))" in VIEW
    assert "change(counter: c.id, .archived(c.archived != 1))" in VIEW
    assert "await api.updateTimer(t.id, [\"archived\"" not in VIEW


def test_a_reload_before_the_mac_answers_does_not_bring_the_row_back():
    load = _func(VIEW, "private func load() async {")
    assert "applyPending(freshTimers, pendingTimers" in load
    assert "applyPending(freshCounters, pendingCounters" in load


def test_the_cache_can_archive_and_remove():
    for fn in ("setTimerArchived", "setCounterArchived", "removeTimer", "removeCounter"):
        assert f"func {fn}(" in STORE and "persist()" in _func(STORE, f"func {fn}(")
