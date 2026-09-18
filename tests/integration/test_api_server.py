"""Integration tests for the Flask API server — the "built-in API" the iOS app
(and any external test harness) uses to submit a transcript and get it parsed +
executed without going through a mic at all: `POST /voice/text`.

Real SQLite DB (temp file, real schema/migrations — same CalendarDB class
production uses), real ActionRegistry, real RuleBasedParser. The only things
mocked are `load_config` (avoid requiring a real config.yaml on disk),
`get_db` (point at an isolated temp DB instead of ~/.assistant_tools/calendar.db),
and Pipeline._append_nlu_log/_append_scenario_bug (server.py's _run_transcript
spawns these unconditionally in a background thread on every call — without
mocking them, every test run appends real entries to the git-tracked
DOCUMENTATION/*.md files). No network calls happen for rule-fast-path
transcripts — the background LLM verify thread it spawns fails closed (catches
its own exceptions, defaults to "ok") when Ollama isn't reachable, so it can't
fail these tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import assistant.api.server as server_module
from assistant.db import CalendarDB
from assistant.pipeline import Pipeline


@pytest.fixture(autouse=True)
def no_markdown_writes(monkeypatch):
    """Prevent tests from appending to the real DOCUMENTATION/*.md files.

    server.py's _run_transcript fires these as background threads on every
    call (success or failure) — without this, every test run pollutes the
    git-tracked NLU tracking / scenario bug logs with synthetic test transcripts.
    """
    monkeypatch.setattr(Pipeline, "_append_nlu_log", MagicMock())
    monkeypatch.setattr(Pipeline, "_append_scenario_bug", MagicMock())


def _register_real_actions(isolated_registry) -> None:
    """Populate the (test-cleared) shared ActionRegistry state with the real
    action classes. ActionRegistry uses a Borg shared-state pattern, so any
    ActionRegistry() instance (including the one server.py's _get_registry()
    constructs internally) sees these. Explicit registration, not
    `import assistant.actions.calendar` — that module is only ever imported
    once per process, so its @register decorators won't re-fire on a later
    test after conftest's autouse isolated_registry fixture has cleared state.
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


@pytest.fixture
def app_client(tmp_path, monkeypatch, sample_config, isolated_registry):
    """Flask test client wired to an isolated temp DB and a mocked config."""
    _register_real_actions(isolated_registry)

    db = CalendarDB(path=str(tmp_path / "test_calendar.db"))
    # Two separate bindings need patching: server.py's REST routes call its own
    # top-level `from assistant.db import get_db` import, while every Action's
    # execute() does its own deferred `from assistant.db import get_db` re-import
    # at call time — that resolves against assistant.db.get_db directly, a
    # different binding than server_module.get_db. Miss either one and requests
    # silently read/write the real ~/.assistant_tools/calendar.db instead.
    import assistant.db as db_module
    monkeypatch.setattr(db_module, "get_db", lambda: db)
    monkeypatch.setattr(server_module, "get_db", lambda: db)
    monkeypatch.setattr(server_module, "load_config", lambda *a, **kw: sample_config)
    # The engine reads its own config (it must never import the HTTP layer),
    # so the brain needs the same mock.
    import assistant.engine as engine_module
    monkeypatch.setattr(engine_module, "load_config", lambda: sample_config)

    # Reset module-level lazy singletons so each test gets a clean registry/parser
    # built against the mocked config, rather than reusing state from a prior test.
    #
    # They live in `assistant.engine.llm` — the ONE cache, which is what its
    # `reset()` exists for. This used to poke `fastrule.stage._parser` and
    # `_rule_parser`, which moved there in the per-stage restructure and left
    # this fixture pointing at attributes that no longer exist: 16 integration
    # tests ERRORED at setup, silently, because nothing runs this suite without
    # ollama. The same "a path rots and only breaks when you next run it" class
    # CLAUDE.md already records for the dataset generators.
    import assistant.engine.llm as engine_llm
    monkeypatch.setattr(engine_llm, "_parser", None)
    monkeypatch.setattr(engine_llm, "_rule_parser", None)
    monkeypatch.setattr(engine_llm, "_registry", None)
    monkeypatch.setattr(server_module, "_stt", None)

    app = server_module.create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, db


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_endpoint(app_client):
    client, db = app_client
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["db"] == db.path


# ---------------------------------------------------------------------------
# /voice/text — the text-only "skip STT" entry point
# ---------------------------------------------------------------------------

def test_voice_text_missing_transcript_returns_400(app_client):
    client, _ = app_client
    resp = client.post("/voice/text", json={})
    assert resp.status_code == 400


def test_voice_text_create_todo_rule_fast_path(app_client):
    client, db = app_client
    resp = client.post("/voice/text", json={"transcript": "buy milk"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "create_todo" in data["actions"]
    assert data["parse"] == "fast"
    assert data["refresh"] == "todos"

    todos = db.get_todos(list_name=None, include_completed=True)
    assert any("milk" in t["title"].lower() for t in todos)


@pytest.fixture
def verify_flow(monkeypatch):
    """Let the verify TOKEN be issued without letting a daemon thread run.

    `_start_verify` returns early when `_no_bg()` — and `conftest.py` sets
    `MACALENDAR_NO_WARMUP=1` for the whole suite, because a background model
    load beside a running suite segfaults the interpreter. That flag is
    load-bearing and must not be switched off wholesale.

    So this turns off only the guard, and stubs the WORK the thread would do.
    What is left is exactly what these two tests are about: a token is minted,
    parked in the store, and polls as pending until something resolves it. The
    real background verification is exercised where it belongs, not here.

    (These tests had not run in a long time: the fixture above pointed at
    `fastrule.stage._parser`, which moved in the per-stage restructure, so all
    16 tests in this file ERRORED at setup instead of failing. Nothing noticed,
    because this suite is skipped without ollama.)
    """
    import assistant.engine as engine_module
    monkeypatch.setattr(engine_module, "_no_bg", lambda: False)
    monkeypatch.setattr(engine_module, "_background_verify",
                        lambda state, cfg: None)

def test_voice_text_create_event_rule_fast_path(app_client, sample_config,
                                                verify_flow):
    client, db = app_client
    # The verify token is what this asserts, so ask for it explicitly rather than
    # relying on the default — the background self-check ships off.
    sample_config.verify_fast_path = True
    # `source: "mac"` because the BACKGROUND SELF-CHECK IS SKIPPED FOR
    # TEST TRAFFIC — `_no_bg() or state.source == "test"` — and
    # `/voice/text` defaults an unlabelled caller to "test" (that
    # default changed on purpose, after 328 curl entries became
    # indistinguishable from real phone commands). So a request with no
    # source never gets a verify_token, and this test was asserting a
    # flow it had opted out of. A real client always says who it is.
    resp = client.post("/voice/text",
                       json={"transcript": "schedule a meeting tomorrow at 3pm",
                             "source": "mac"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "create_event" in data["actions"]
    assert data["parse"] == "fast"
    assert data["refresh"] == "events"
    # A verify_token is issued for rule-path results (iOS polls it for corrections).
    assert "verify_token" in data


def test_voice_text_cross_domain_multi_action(app_client):
    """'Delete my grocery list and cancel my dentist appointment' — both actions
    executed and both refresh flags set (regression coverage for the multi-action
    combinatorial work in test_multi_action_scenarios.py, now through the real API).
    """
    client, db = app_client
    # Seed records to delete
    db.create_todo(title="grocery list", list_name="today", priority="none", due_date="", notes="")
    db.create_event_from_dict({
        "title": "dentist appointment", "date": "2026-01-01",
        "start_time": "09:00", "end_time": "10:00",
    })

    resp = client.post("/voice/text", json={
        "transcript": "delete my grocery list and cancel my dentist appointment"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data["actions"]) == {"delete_todo", "delete_event"}
    assert data["refresh"] == "both"


def test_voice_text_unknown_action_returns_message(app_client):
    """A transcript with no matching command shouldn't 500 — just report it couldn't parse."""
    client, _ = app_client
    resp = client.post("/voice/text", json={"transcript": "asdkjhaskjdh unrelated gibberish"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["actions"] == []


# ---------------------------------------------------------------------------
# Background verify token polling
# ---------------------------------------------------------------------------

def test_voice_verify_unknown_token_returns_404(app_client):
    client, _ = app_client
    resp = client.get("/voice/verify/not-a-real-token")
    assert resp.status_code == 404


def test_voice_verify_pending_before_ready(app_client, sample_config,
                                           verify_flow):
    """Immediately after a rule-path response, the verify token exists but the
    background thread almost certainly hasn't finished — poll returns pending.
    """
    client, _ = app_client
    sample_config.verify_fast_path = True      # the flow under test; ships off
    # Labelled "mac" for the same reason as the fast-path test above: test
    # traffic deliberately skips the background self-check, so an unlabelled
    # request is never issued a verify token.
    resp = client.post("/voice/text", json={"transcript": "buy milk",
                                            "source": "mac"})
    token = resp.get_json().get("verify_token")
    assert token is not None
    poll = client.get(f"/voice/verify/{token}")
    assert poll.status_code == 200
    # Either still pending, or (rarely, if the background thread already failed
    # closed due to Ollama being unreachable) already resolved to ok=true.
    body = poll.get_json()
    assert body.get("pending") is True or body.get("ok") is True


# ---------------------------------------------------------------------------
# REST CRUD — events
# ---------------------------------------------------------------------------

def test_events_crud_roundtrip(app_client):
    client, _ = app_client

    create = client.post("/events", json={
        "title": "Standup", "date": "2026-05-01", "start_time": "09:00", "end_time": "09:30",
    })
    assert create.status_code == 201
    event_id = create.get_json()["id"]

    get_resp = client.get(f"/events/{event_id}")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["title"] == "Standup"

    patch = client.patch(f"/events/{event_id}", json={"title": "Renamed Standup"})
    assert patch.status_code == 200
    assert client.get(f"/events/{event_id}").get_json()["title"] == "Renamed Standup"

    delete = client.delete(f"/events/{event_id}")
    assert delete.status_code == 200
    assert client.get(f"/events/{event_id}").status_code == 404


def test_event_create_missing_fields_returns_400(app_client):
    client, _ = app_client
    resp = client.post("/events", json={"title": "Incomplete"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# REST CRUD — todos
# ---------------------------------------------------------------------------

def test_todos_crud_roundtrip(app_client):
    client, _ = app_client

    create = client.post("/todos", json={"title": "Buy flowers"})
    assert create.status_code == 201
    todo_id = create.get_json()["id"]

    listed = client.get("/todos?list=all").get_json()
    assert any(t["id"] == todo_id for t in listed)

    patch = client.patch(f"/todos/{todo_id}", json={"title": "Buy roses"})
    assert patch.status_code == 200
    listed = client.get("/todos?list=all").get_json()
    assert any(t["id"] == todo_id and t["title"] == "Buy roses" for t in listed)

    delete = client.delete(f"/todos/{todo_id}")
    assert delete.status_code == 200
    listed = client.get("/todos?list=all").get_json()
    assert not any(t["id"] == todo_id for t in listed)


def test_todo_create_missing_title_returns_400(app_client):
    client, _ = app_client
    resp = client.post("/todos", json={})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Creation is idempotent — the duplicate-task bug
#
# Gil, 2026-09-06: "a lot of duplicates of 'buy groceries' in the Today todo
# list" — 32 rows, all source='manual', every one of them a separate POST
# /todos in ~/.assistant_tools/launch.log. The endpoint inserted on every
# request, so a create that reached the Mac but whose reply was lost, and a
# queued create flushed twice by overlapping sync passes, each landed as
# another copy. `client_token` is the fix: one token per task the user asked
# for, replayed with every attempt.
# ---------------------------------------------------------------------------

def test_replayed_create_with_same_token_makes_no_duplicate(app_client):
    """The whole bug in one test: POST the identical create twice."""
    client, db = app_client
    body = {"title": "buy groceries", "list_name": "today",
            "tags": ["Groceries"], "client_token": "queued-create-1"}

    first = client.post("/todos", json=body)
    assert first.status_code == 201
    todo_id = first.get_json()["id"]

    replay = client.post("/todos", json=body)
    assert replay.status_code == 200                     # not 201: nothing created
    assert replay.get_json() == {"id": todo_id, "duplicate": True}

    rows = [t for t in db.get_todos(include_completed=True)
            if t["title"] == "buy groceries"]
    assert len(rows) == 1, f"a replayed create duplicated the task: {rows}"


def test_many_replays_of_one_queued_create_stay_one_task(app_client):
    """The shape the real data had: the same create replayed over and over."""
    client, db = app_client
    body = {"title": "buy groceries", "client_token": "queued-create-2"}
    ids = {client.post("/todos", json=body).get_json()["id"] for _ in range(10)}
    assert len(ids) == 1
    assert len([t for t in db.get_todos(include_completed=True)
                if t["title"] == "buy groceries"]) == 1


def test_two_real_asks_are_two_tasks(app_client):
    """Idempotency must not swallow a task the user genuinely asked for twice:
    a different token is a different task, however identical the words."""
    client, db = app_client
    client.post("/todos", json={"title": "buy groceries", "client_token": "ask-a"})
    client.post("/todos", json={"title": "buy groceries", "client_token": "ask-b"})
    assert len([t for t in db.get_todos(include_completed=True)
                if t["title"] == "buy groceries"]) == 2
    # A caller that sends no token gets the content fingerprint instead, and
    # this repeat lands inside its window — so it folds into the newest open
    # row rather than becoming a third copy. That is the 2026-09-07 change:
    # token-less used to mean "always insert", which is how the suite's own
    # HUD revert POST stacked 45 of these in the real Today list.
    tokenless = client.post("/todos", json={"title": "buy groceries"})
    assert tokenless.status_code == 200
    assert tokenless.get_json()["reason"] == "recent-identical"
    assert len([t for t in db.get_todos(include_completed=True)
                if t["title"] == "buy groceries"]) == 2


def test_todo_client_token_is_idempotent_at_the_db_layer(tmp_path):
    """db.create_todo is the seam every surface shares, so it holds the rule
    too — not just the HTTP route above it."""
    db = CalendarDB(path=str(tmp_path / "token_calendar.db"))
    first = db.create_todo("buy groceries", client_token="tok-1")
    again = db.create_todo("buy groceries", client_token="tok-1")
    assert first == again
    assert len(db.get_todos(include_completed=True)) == 1

    # An empty token is "no key given" — never a shared one.
    db.create_todo("buy milk", client_token="")
    db.create_todo("buy milk", client_token="")
    assert len([t for t in db.get_todos(include_completed=True)
                if t["title"] == "buy milk"]) == 2


def test_calendar_sync_stays_idempotent_across_runs(tmp_path):
    """The other suspect, kept honest: re-running the calendar→todos sync must
    still update in place rather than create a second row per event."""
    import datetime

    db = CalendarDB(path=str(tmp_path / "sync_calendar.db"))
    today = datetime.date.today().isoformat()
    db.create_event_from_dict({"title": "Standup", "date": today,
                               "start_time": "09:00", "end_time": "09:30"})
    assert db.sync_calendar_to_todos(list_name="today") == 1
    assert db.sync_calendar_to_todos(list_name="today") == 1
    assert len(db.get_todos_by_source("calendar_sync")) == 1


# ---------------------------------------------------------------------------
# API-key auth
# ---------------------------------------------------------------------------

def test_api_key_enforced_when_configured(tmp_path, monkeypatch, sample_config):
    from assistant.config import ApiConfig
    import assistant.db as db_module

    guarded_config = sample_config.model_copy(update={"api": ApiConfig(key="secret123")})
    db = CalendarDB(path=str(tmp_path / "test_calendar_auth.db"))
    monkeypatch.setattr(db_module, "get_db", lambda: db)
    monkeypatch.setattr(server_module, "get_db", lambda: db)
    monkeypatch.setattr(server_module, "load_config", lambda *a, **kw: guarded_config)
    monkeypatch.setattr(server_module, "_registry", None)
    monkeypatch.setattr(server_module, "_parser", None)
    monkeypatch.setattr(server_module, "_rule_parser", None)
    monkeypatch.setattr(server_module, "_stt", None)

    app = server_module.create_app()
    with app.test_client() as client:
        no_key = client.get("/events")
        assert no_key.status_code == 401

        with_key = client.get("/events", headers={"X-API-Key": "secret123"})
        assert with_key.status_code == 200

        wrong_key = client.get("/events", headers={"X-API-Key": "wrong"})
        assert wrong_key.status_code == 401


def test_review_feed_excludes_probe_traffic(app_client):
    """Health probes record with source='test'; they must never reach the
    phone's review queue (43 identical probes once flooded it)."""
    from assistant.intent.memory import get_memory
    mem = get_memory()
    a = mem.record(transcript="what do I have today", source="test",
                   actions=[("query_schedule", {})], result="ok", success=True)
    b = mem.record(transcript="gym tomorrow 7am", source="mac",
                   actions=[("create_event", {"title": "Gym"})], result="ok", success=True)
    client, _ = app_client
    rows = client.get("/memory/unreviewed").get_json()["examples"]
    ids = {r["id"] for r in rows}
    assert b in ids and a not in ids


# ---------------------------------------------------------------------------
# A SERIES, as one thing (Gil, 2026-09-18)
#
# `db` has carried the whole vocabulary for a long time — `series_id` on every
# instance, `update_series` which propagates AND re-generates the future slots
# when the cadence or the end date moves, `delete_series_from`, and the
# re-rooting that keeps a series editable after its first instance is deleted.
# None of it was reachable over HTTP, so the phone could edit ONE instance and
# nothing else: change the end date there and the other rows carried on.
# ---------------------------------------------------------------------------

def _weekly(client, until=""):
    body = {"title": "gym", "date": "2026-09-21", "start_time": "07:00",
            "end_time": "08:00", "recurrence": "weekly"}
    if until:
        body["recurrence_end"] = until
    r = client.post("/events", json=body)
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()["id"]


def _series(client, eid):
    return client.get(f"/events/{eid}/series").get_json()


def test_the_series_reads_back_as_one_thing(app_client):
    client, _ = app_client
    eid = _weekly(client, until="2026-10-19")
    got = _series(client, eid)
    assert got["series_id"], got
    assert got["recurrence"] == "weekly"
    assert got["count"] >= 2, "a weekly series to mid-October is several rows"
    assert all(i["title"] == "gym" for i in got["instances"])


def test_extending_the_end_date_grows_the_series(app_client):
    client, _ = app_client
    eid = _weekly(client, until="2026-10-05")
    before = _series(client, eid)["count"]
    r = client.patch(f"/events/{eid}/series", json={"recurrence_end": "2026-11-30"})
    assert r.status_code == 200, r.get_json()
    after = r.get_json()["count"]
    assert after > before, f"extending should add instances ({before} -> {after})"


def test_shortening_the_end_date_trims_it(app_client):
    client, _ = app_client
    eid = _weekly(client, until="2026-11-30")
    before = _series(client, eid)["count"]
    after = client.patch(f"/events/{eid}/series",
                         json={"recurrence_end": "2026-10-05"}).get_json()["count"]
    assert after < before, f"shortening should remove instances ({before} -> {after})"


def test_changing_the_interval_regenerates(app_client):
    client, _ = app_client
    eid = _weekly(client, until="2026-11-30")
    weekly = _series(client, eid)["count"]
    daily = client.patch(f"/events/{eid}/series",
                         json={"recurrence": "daily"}).get_json()["count"]
    assert daily > weekly, f"daily is denser than weekly ({weekly} -> {daily})"


def test_a_title_change_reaches_every_instance(app_client):
    client, _ = app_client
    eid = _weekly(client, until="2026-10-19")
    out = client.patch(f"/events/{eid}/series", json={"title": "swimming"}).get_json()
    assert [i["title"] for i in out["instances"]] == ["swimming"] * out["count"]


def test_only_the_four_cadences_are_accepted(app_client):
    client, _ = app_client
    eid = _weekly(client, until="2026-10-19")
    r = client.patch(f"/events/{eid}/series", json={"recurrence": "fortnightly"})
    assert r.status_code == 400
    assert "daily|weekly|monthly|yearly" in r.get_json()["error"]


def test_a_one_off_can_be_made_to_repeat(app_client):
    client, _ = app_client
    eid = client.post("/events", json={"title": "standup", "date": "2026-09-21",
                                       "start_time": "09:00",
                                       "end_time": "09:15"}).get_json()["id"]
    assert _series(client, eid)["series_id"] is None
    out = client.patch(f"/events/{eid}/series",
                       json={"recurrence": "weekly",
                             "recurrence_end": "2026-10-19"}).get_json()
    assert out["series_id"] and out["count"] >= 2, out


def test_a_one_off_with_no_cadence_is_refused_rather_than_guessed(app_client):
    client, _ = app_client
    eid = client.post("/events", json={"title": "dentist", "date": "2026-09-21",
                                       "start_time": "09:00",
                                       "end_time": "10:00"}).get_json()["id"]
    assert client.patch(f"/events/{eid}/series",
                        json={"title": "dentist v2"}).status_code == 400


def test_deleting_from_here_keeps_the_past(app_client):
    client, _ = app_client
    eid = _weekly(client, until="2026-11-30")
    everything = _series(client, eid)
    later = [i for i in everything["instances"] if i["date"] > "2026-10-12"]
    assert later, "need a later instance to delete from"
    client.delete(f"/events/{later[0]['id']}/series?scope=future")
    left = _series(client, eid)
    assert left["count"] < everything["count"]
    assert all(i["date"] < later[0]["date"] for i in left["instances"])


def test_deleting_the_series_removes_all_of_it(app_client):
    client, _ = app_client
    eid = _weekly(client, until="2026-11-30")
    n = _series(client, eid)["count"]
    assert client.delete(f"/events/{eid}/series").get_json()["deleted"] == n
    assert client.get(f"/events/{eid}").status_code == 404
