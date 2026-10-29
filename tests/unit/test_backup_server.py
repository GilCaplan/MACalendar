"""The Mac stands in for the PC while the PC is away (DEVQA Q96).

Gil, 2026-10-25: *"when pc is off mac is fine to do"*. The phone switches to
the Mac — a replica that keeps a synced copy of the PC's calendar file — and
back. What it may send there is an allow-list in `APIClient.swift`
(`backupReadWrite` / `backupReadOnly`), because a write to a store that does
NOT replicate (flashcards, Jude, vocabulary, the user registry) would land on
the Mac and never reach the PC. These hold that list to the server's routes
and to what replication actually carries.
"""
from __future__ import annotations

import re

import pytest

from tests.unit._ios_sources import ios_source


def _swift_list(name: str) -> "list[str]":
    src = ios_source("APIClient.swift")
    m = re.search(rf"static let {name} = \[(.*?)\]", src, re.S)
    assert m, f"{name} not found in APIClient.swift"
    return re.findall(r'"(/[^"]*)"', m.group(1))


@pytest.fixture(scope="module")
def prefixes():
    from assistant.api.server import create_app
    app = create_app()
    return {"/" + r.rule.strip("/").split("/")[0] for r in app.url_map.iter_rules()}


def test_every_listed_route_exists(prefixes):
    for p in _swift_list("backupReadWrite") + _swift_list("backupReadOnly"):
        assert p in prefixes, f"{p} is on the phone's backup list but the server has no such route"


#: Routes whose data lives OUTSIDE the replicated calendar file. Writing one on
#: the backup forks it: the Mac's copy changes and the PC's never hears of it.
ONE_MACHINES = {"/flashcards", "/ranker", "/jude", "/vocab", "/lexicon", "/memory", "/labels",
                "/magic", "/users", "/auth", "/admin", "/shares", "/config", "/devices", "/servers",
                "/pair", "/calendar_sources", "/calendar_sync", "/occasions", "/categories",
                "/assistant", "/features"}


def test_nothing_that_stays_on_one_machine_is_written_on_the_backup():
    assert not set(_swift_list("backupReadWrite")) & ONE_MACHINES


def test_the_read_write_routes_write_the_replicated_file(tmp_path, monkeypatch):
    """Each read-write prefix's data is in a table replication carries — not
    excluded, not a store of its own."""
    from assistant.db import CalendarDB
    from assistant.sync import changelog as cl
    db = CalendarDB(str(tmp_path / "cal.db"))
    conn = cl.connect(db.path)
    replicated = set(cl.tables(conn))
    by_prefix = {"/events": "events", "/todos": "todos", "/tags": "todo_tags", "/timers": "timers",
                 "/timer_sessions": "timer_sessions", "/counters": "counters",
                 "/counter_presses": "counter_presses", "/courses": "courses",
                 "/assignments": "assignments", "/workout": "workout_sessions"}
    # The brain, not a table: what it books is events and to-dos, which are above.
    brain = {"/voice", "/offline", "/pending"}
    for p in _swift_list("backupReadWrite"):
        if p in brain:
            continue
        assert p in by_prefix, f"{p}: say which replicated table it writes"
        assert by_prefix[p] in replicated, f"{p} writes {by_prefix[p]}, which does not replicate"


def test_the_phone_hands_back_only_when_the_mac_has_sent_everything():
    src = ios_source("APIClient.swift")
    assert "!(status.ok && status.pending == 0)" in src
    # …and stands a copy in only once it has synced at least once.
    assert "s.isReplica, s.cursor != nil" in src


def test_no_sign_in_goes_to_the_backup():
    """The Mac does not know a session the PC issued; it answers "login
    required", and that answer signs the phone out."""
    src = ios_source("APIClient.swift")
    assert "if !token.isEmpty && !onBackup" in src
    assert 'msg.contains("login required"), !onBackup' in src
