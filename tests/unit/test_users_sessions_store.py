"""sessions.json survives several processes writing it at once.

2026-10-18: every voice command from the Mac came back 401. The GUI, the HUD
and the API all write sessions.json (`resolve()` drops expired sessions and
refreshes `last_seen`), and each saved through ONE shared `sessions.json.tmp`
under a lock that only held within a process. Two saves overlapped, the file
ended in `}}`, it no longer parsed, `_load()` read it as empty — and every
logged-in client's token looked unknown.

Two guards: concurrent writers in separate processes never leave a file that
fails to parse, and a file that does carry stray bytes keeps its logins.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from assistant.users import sessions

REPO = pathlib.Path(__file__).resolve().parents[2]

_WRITER = textwrap.dedent("""
    import sys
    from assistant.users import sessions
    for i in range(int(sys.argv[1])):
        tok = sessions.issue("u_writer", source="test", label=f"w{i}")
        if i % 2:
            sessions.revoke(tok)
""")


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = tmp_path / "sessions.json"
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(p))
    return p


def test_concurrent_writers_in_separate_processes_never_corrupt_the_file(store):
    env = dict(os.environ, MACALENDAR_SESSIONS=str(store), PYTHONPATH=str(REPO))
    procs = [subprocess.Popen([sys.executable, "-c", _WRITER, "150"], cwd=REPO, env=env)
             for _ in range(4)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    data = json.loads(store.read_text(encoding="utf-8"))   # must parse, as written
    # 4 writers x 75 kept sessions each; with the cross-process lock none is lost
    assert len(data) == 300
    leftovers = [n for n in os.listdir(store.parent) if n.endswith(".tmp")]
    assert leftovers == []


def test_a_file_with_stray_bytes_keeps_its_logins(store):
    tok = sessions.issue("u_kept", source="test")
    store.write_text(store.read_text(encoding="utf-8") + "}", encoding="utf-8")
    with pytest.raises(ValueError):
        json.loads(store.read_text(encoding="utf-8"))
    loaded = sessions._load()
    assert sessions._key(tok) in loaded
    assert loaded[sessions._key(tok)]["user_id"] == "u_kept"


def test_an_unreadable_file_reads_as_empty_not_as_an_error(store):
    store.write_text("not json at all", encoding="utf-8")
    assert sessions._load() == {}
