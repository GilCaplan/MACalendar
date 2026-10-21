"""Jude's history is kept on our side, and a follow-up reuses the chat's sources.

The bug (2026-10-20): History opened onto an empty page. Jude saves a turn
only when it wrote the answer and its stream ran to the end, so a
clarification, a "sources" request (how the phone asks when it writes the
answer itself) or a stream cut short left a chat with a title and no messages
— and a follow-up then had no conversation to follow. `history.py` records
every turn as it passes `/jude/chat`; `followup.py` answers a follow-up from
the sources already found instead of searching again.
"""
from __future__ import annotations

import json

import pytest
from flask import Flask, Response

from assistant.jude import followup, routes
from assistant.jude.history import JudeHistory

SOURCES = [{"ref": "Berakhot 2a", "en_text": "From when may one recite the Shema in the evening?"},
           {"ref": "Berakhot 2b", "en_text": "From when the kohanim enter to eat their teruma."}]


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = str(tmp_path / "jude_chats.db")
    monkeypatch.setenv("MACALENDAR_JUDE_CHATS", path)
    return JudeHistory(path)


@pytest.fixture
def client(store):
    app = Flask(__name__)
    app.register_blueprint(routes.blueprint)
    return app.test_client()


def _ndjson(*events):
    return Response((json.dumps(e) + "\n" for e in events), mimetype="application/x-ndjson")


def _events(resp):
    return [json.loads(line) for line in resp.get_data(as_text=True).splitlines() if line.strip()]


class _FakeJude:
    def model(self):
        return "test-model"


# -- the store ---------------------------------------------------------------

def test_a_turn_round_trips_in_judes_history_shape(store):
    store.record("c1", "when is the evening shema", "From tzeit [1].", sources=SOURCES)
    msgs = store.messages("c1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "From tzeit [1]."
    assert msgs[1]["sources"][0]["ref"] == "Berakhot 2a"
    assert store.chats()[0]["title"] == "when is the evening shema"


def test_last_sources_is_the_latest_turn_that_found_any(store):
    store.record("c1", "q1", "a1", sources=SOURCES)
    store.record("c1", "q2", "a2", sources=[])
    assert store.last_sources("c1") == SOURCES


def test_the_phone_fills_the_turn_whose_sources_it_answered_from(store):
    store.record("c1", "q", "", sources=SOURCES, mode="sources")
    assert store.fill_answer("c1", "q", "written on the phone")
    t = store.turns("c1")
    assert len(t) == 1 and t[0]["answer"] == "written on the phone" and t[0]["by"] == "phone"


def test_an_answer_with_no_recorded_turn_is_still_kept(store):
    assert not store.fill_answer("c9", "q", "a")
    assert store.turns("c9")[0]["answer"] == "a"


def test_delete_takes_the_turns_with_it(store):
    store.record("c1", "q", "a")
    store.delete("c1")
    assert store.chats() == [] and store.turns("c1") == []


# -- recording what streams past ------------------------------------------------

def test_a_streamed_answer_is_recorded_when_the_stream_ends(client, store, monkeypatch):
    monkeypatch.setattr(routes.proxy, "stream", lambda i, p, payload, timeout=900: _ndjson(
        {"type": "stage", "name": "Routing question…"},
        {"type": "meta", "chat_id": "c1", "sources": SOURCES, "mode": "qa"},
        {"type": "token", "text": "From "}, {"type": "token", "text": "tzeit [1]."},
        {"type": "done"}))
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    r = client.post("/jude/chat", json={"prompt": "when is the evening shema"})
    assert [e["type"] for e in _events(r)][-1] == "done"     # passed through untouched
    t = store.turns("c1")
    assert t[0]["answer"] == "From tzeit [1]." and t[0]["sources"] == SOURCES


def test_a_clarification_is_kept_so_history_is_not_empty(client, store, monkeypatch):
    """The case that left today's chat with no messages."""
    monkeypatch.setattr(routes.proxy, "stream", lambda i, p, payload, timeout=900: _ndjson(
        {"type": "clarification", "chat_id": "c2", "question": "Which do you mean?",
         "options": ["the halacha", "the reasons"]},
        {"type": "done"}))
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    client.post("/jude/chat", json={"prompt": "shomer negiah"}).get_data()
    t = store.turns("c2")
    assert t[0]["kind"] == "clarification" and "the reasons" in t[0]["answer"]
    # Jude's real shape: {label, prompt}. The prompt is what a tap asks.
    monkeypatch.setattr(routes.proxy, "stream", lambda i, p, payload, timeout=900: _ndjson(
        {"type": "clarification", "chat_id": "c5", "question": "Which?",
         "options": [{"label": "Halacha", "prompt": "What is the halacha of shomer negiah?"}]},
        {"type": "done"}))
    client.post("/jude/chat", json={"prompt": "shomer negiah"}).get_data()
    msg = store.messages("c5")[1]
    assert msg["content"] == "Which?\n- Halacha"
    assert msg["clarification"]["options"][0]["prompt"] == "What is the halacha of shomer negiah?"


def test_history_reads_ours_before_judes(client, store, monkeypatch):
    store.record("c1", "q", "a", sources=SOURCES)
    monkeypatch.setattr(routes.proxy, "call", lambda *a, **k: pytest.fail("asked Jude"))
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    assert client.get("/jude/chats/c1/history").get_json()[1]["content"] == "a"


def test_the_list_merges_judes_older_chats(client, store, monkeypatch):
    from flask import jsonify
    store.record("mine", "q", "a")
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    monkeypatch.setattr(routes, "_jude_running", lambda: True)
    monkeypatch.setattr(routes.proxy, "call", lambda *a, **k: jsonify(
        [{"id": "old", "title": "from before", "created_at": "2026-09-01T00:00:00+00:00"},
         {"id": "mine", "title": "dup", "created_at": "2026-09-01T00:00:00+00:00"}]))
    ids = [c["id"] for c in client.get("/jude/chats").get_json()]
    assert ids == ["mine", "old"]


def test_the_phone_posts_the_answer_it_wrote(client, store):
    store.record("c1", "q", "", sources=SOURCES, mode="sources")
    assert client.post("/jude/chats/c1/answer", json={"question": "q", "answer": "a"}).status_code == 200
    assert store.messages("c1")[1]["content"] == "a"
    assert client.post("/jude/chats/c1/answer", json={"question": "q"}).status_code == 400


# -- a follow-up does not search again ------------------------------------------

def test_a_follow_up_answers_from_the_chats_sources(client, store, monkeypatch):
    store.record("c1", "when is the evening shema", "From tzeit [1].", sources=SOURCES)
    seen = {}

    def fake_ask(msgs, model, source=""):
        seen["msgs"], seen["model"] = msgs, model
        return "Because of the kohanim [2]."

    monkeypatch.setattr(followup, "_ask", fake_ask)
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    monkeypatch.setattr(routes.proxy, "stream", lambda *a, **k: pytest.fail("searched again"))
    r = client.post("/jude/chat", json={"prompt": "why then?", "chat_id": "c1"})
    ev = _events(r)
    assert next(e for e in ev if e["type"] == "meta")["sources"] == SOURCES
    assert "".join(e["text"] for e in ev if e["type"] == "token") == "Because of the kohanim [2]."
    assert ev[-1]["type"] == "done"
    # The model saw the sources, the earlier turn, and the question last.
    assert "Berakhot 2b" in seen["msgs"][0]["content"]
    assert seen["msgs"][1]["content"] == "when is the evening shema"
    assert seen["msgs"][-1]["content"] == "why then?"
    assert seen["model"] == "test-model"
    assert store.turns("c1")[-1]["kind"] == "followup"


def test_search_again_goes_to_jude(client, store, monkeypatch):
    store.record("c1", "q", "a", sources=SOURCES)
    called = {}
    monkeypatch.setattr(routes.proxy, "stream", lambda i, p, payload, timeout=900:
                        (called.update(payload), _ndjson({"type": "done"}))[1])
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    client.post("/jude/chat", json={"prompt": "more", "chat_id": "c1", "search": True}).get_data()
    assert called["chat_id"] == "c1"


def test_a_chat_with_no_sources_goes_to_jude(client, store, monkeypatch):
    store.record("c1", "hi", "hello", sources=[])
    called = {}
    monkeypatch.setattr(routes.proxy, "stream", lambda i, p, payload, timeout=900:
                        (called.update(payload), _ndjson({"type": "done"}))[1])
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    client.post("/jude/chat", json={"prompt": "more", "chat_id": "c1"}).get_data()
    assert called


def test_a_model_failure_is_said_in_the_stream(client, store, monkeypatch):
    store.record("c1", "q", "a", sources=SOURCES)

    def boom(*a, **k):
        raise RuntimeError("ollama is down")

    monkeypatch.setattr(followup, "_ask", boom)
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    ev = _events(client.post("/jude/chat", json={"prompt": "why?", "chat_id": "c1"}))
    assert ev[-1]["type"] == "error" and "ollama is down" in ev[-1]["message"]
    assert len(store.turns("c1")) == 1                     # nothing half-kept


def test_followup_goes_through_the_model_door_and_not_the_brain():
    src = open("assistant/jude/followup.py").read()
    assert "model_protocol.route_post" in src
    for forbidden in ("assistant.engine", "from assistant.pipeline", "requests.post", "11434"):
        assert forbidden not in src


# -- what the review found (2026-10-20) ----------------------------------------

def test_a_stopped_jude_is_not_started_to_list_chats(client, store, monkeypatch):
    """Asking a stopped Jude for its list STARTS it and held History for minutes."""
    store.record("mine", "q", "a")
    monkeypatch.setattr(routes, "_jude_running", lambda: False)
    monkeypatch.setattr(routes.proxy, "call", lambda *a, **k: pytest.fail("started Jude"))
    assert [c["id"] for c in client.get("/jude/chats").get_json()] == ["mine"]


def test_an_old_chat_is_adopted_before_it_gains_a_turn(client, store, monkeypatch):
    """Else History showed only the turns recorded since this store existed."""
    from flask import jsonify
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    monkeypatch.setattr(routes, "_jude_running", lambda: True)
    monkeypatch.setattr(routes.proxy, "call", lambda *a, **k: jsonify([
        {"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1", "sources": SOURCES},
        {"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"}]))
    msgs = client.get("/jude/chats/old/history").get_json()
    assert [m["content"] for m in msgs] == ["q1", "a1", "q2", "a2"]
    # ...and its sources make the next question a follow-up on them.
    assert store.last_sources("old") == SOURCES


def test_a_deleted_chat_stays_deleted_when_jude_still_has_it(client, store, monkeypatch):
    from flask import jsonify
    store.record("c1", "q", "a")
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    monkeypatch.setattr(routes, "_jude_running", lambda: False)
    assert client.delete("/jude/chats/c1").status_code == 200      # Jude away: still gone here
    monkeypatch.setattr(routes, "_jude_running", lambda: True)
    monkeypatch.setattr(routes.proxy, "call", lambda *a, **k: jsonify(
        [{"id": "c1", "title": "q", "created_at": "2026-10-01T00:00:00+00:00"}]))
    assert client.get("/jude/chats").get_json() == []
    assert client.get("/jude/chats/c1/history").get_json() == []


def test_answering_a_clarification_goes_back_to_jude(client, store, monkeypatch):
    """Jude asked the question, so Jude hears the answer — not the old sources."""
    store.record("c1", "topic A", "answer A", sources=SOURCES)
    store.record("c1", "topic B", "Which do you mean?\n- x\n- y", kind="clarification")
    called = {}
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    monkeypatch.setattr(routes.proxy, "stream", lambda i, p, payload, timeout=900:
                        (called.update(payload), _ndjson({"type": "done"}))[1])
    client.post("/jude/chat", json={"prompt": "x", "chat_id": "c1"}).get_data()
    assert called["prompt"] == "x"
    called.clear()
    store.record("c1", "x", "an answer", sources=SOURCES)
    client.post("/jude/chat", json={"prompt": "topic B", "chat_id": "c1",
                                    "skip_clarification": True}).get_data()
    assert called["skip_clarification"] is True


def test_a_clarification_is_never_followed_up_on_as_an_answer(store):
    store.record("c1", "q", "a", sources=SOURCES)
    store.record("c1", "q2", "Which?\n- x", kind="clarification")
    assert [t["question"] for t in store.window("c1")] == ["q"]


def test_a_cut_stream_is_kept_as_incomplete(client, store, monkeypatch):
    monkeypatch.setattr(routes.proxy, "stream", lambda i, p, payload, timeout=900: _ndjson(
        {"type": "meta", "chat_id": "c3", "sources": SOURCES},
        {"type": "token", "text": "half an ans"},
        {"type": "error", "message": "synthesis failed"}))
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    client.post("/jude/chat", json={"prompt": "q"}).get_data()
    t = store.turns("c3")[0]
    assert t["kind"] == "incomplete" and t["answer"] == "half an ans"
    assert store.window("c3") == []


def test_sources_a_tool_fetched_are_kept_with_the_answer(client, store, monkeypatch):
    extra = {"ref": "Shabbat 21b", "en_text": "the miracle of the oil"}
    monkeypatch.setattr(routes.proxy, "stream", lambda i, p, payload, timeout=900: _ndjson(
        {"type": "meta", "chat_id": "c4", "sources": SOURCES},
        {"type": "tool_call", "tool": "lookup", "new_sources": [extra]},
        {"type": "token", "text": "a"}, {"type": "done"}))
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    client.post("/jude/chat", json={"prompt": "q"}).get_data()
    assert store.turns("c4")[0]["sources"] == SOURCES + [extra]


def test_a_follow_up_without_a_source_label_is_live(client, store, monkeypatch):
    """Neither client sent `source`, and `serving("")` meant BACKGROUND —
    a person's follow-up queued behind a board."""
    from assistant import model_protocol
    store.record("c1", "q", "a", sources=SOURCES)
    seen = {}

    def fake_ask(msgs, model, source=""):
        seen["priority"] = model_protocol.priority()
        return "ok"

    monkeypatch.setattr(followup, "_ask", fake_ask)
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    monkeypatch.delenv("MACALENDAR_LLM_PRIORITY", raising=False)
    client.post("/jude/chat", json={"prompt": "why?", "chat_id": "c1"}).get_data()
    assert seen["priority"] == model_protocol.LIVE
    client.post("/jude/chat", json={"prompt": "why?", "chat_id": "c1", "source": "test"}).get_data()
    assert seen["priority"] == model_protocol.BACKGROUND


def test_a_phone_follow_up_is_kept_with_its_sources(client, store):
    r = client.post("/jude/chats/c1/answer", json={
        "question": "why?", "answer": "because [1]", "kind": "followup", "sources": SOURCES})
    assert r.status_code == 200
    t = store.turns("c1")[0]
    assert t["kind"] == "followup" and t["sources"] == SOURCES and t["by"] == "phone"


def test_a_phone_answer_relabels_a_sources_chat(store):
    store.record("c1", "q", "", sources=SOURCES, mode="sources")
    store.fill_answer("c1", "q", "written here", mode="qa")
    assert store.chats()[0]["mode"] == "qa" and store.turns("c1")[0]["mode"] == "qa"


def test_a_store_made_before_extra_gains_the_column(tmp_path):
    """The real store was created a day before `extra` existed."""
    import sqlite3
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
        mode TEXT NOT NULL DEFAULT 'qa', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
        question TEXT NOT NULL DEFAULT '', answer TEXT NOT NULL DEFAULT '',
        sources TEXT NOT NULL DEFAULT '[]', mode TEXT NOT NULL DEFAULT 'qa',
        kind TEXT NOT NULL DEFAULT 'answer', by TEXT NOT NULL DEFAULT 'mac', created_at TEXT NOT NULL);""")
    c.close()
    store = JudeHistory(path)
    store.record("c1", "q", "a")
    assert store.turns("c1")[0]["extra"] == {}


# -- the phone's copy, and answers outliving the phone (2026-10-21) -------------

def test_sync_returns_what_changed_and_what_was_deleted(client, store, monkeypatch):
    monkeypatch.setattr(routes, "_jude_running", lambda: False)
    store.record("c1", "q1", "a1", sources=SOURCES)
    first = client.get("/jude/sync").get_json()
    assert [c["id"] for c in first["chats"]] == ["c1"]
    assert first["chats"][0]["messages"][1]["content"] == "a1"
    # Nothing new since `next`...
    assert client.get(f"/jude/sync?since={first['next']}").get_json()["chats"] == []
    # ...until a turn lands or a chat is deleted.
    store.record("c2", "q2", "a2")
    store.delete("c1")
    later = client.get(f"/jude/sync?since={first['next']}").get_json()
    assert [c["id"] for c in later["chats"]] == ["c2"] and "c1" in later["deleted"]


def test_history_does_not_start_a_stopped_jude(client, store, monkeypatch):
    monkeypatch.setattr(routes, "_jude_running", lambda: False)
    monkeypatch.setattr(routes.proxy, "call", lambda *a, **k: pytest.fail("started Jude"))
    assert client.get("/jude/chats/unknown/history").get_json() == []


def test_adopt_keeps_judes_title_and_time_in_one_go(store):
    n = store.adopt("old", [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}],
                    title="Jude's title", created_at="2026-09-01T00:00:00+00:00")
    assert n == 1
    chat = store.chats()[0]
    assert chat["title"] == "Jude's title" and chat["created_at"].startswith("2026-09-01")


def test_an_answer_the_phone_left_is_finished_and_kept(store, monkeypatch):
    """The phone backgrounds mid-answer: Jude goes on, and History gets ALL of it."""
    import time as _t
    monkeypatch.setattr(routes, "_jude", lambda: _FakeJude())
    resp = routes._recording(_ndjson(
        {"type": "meta", "chat_id": "c6", "sources": SOURCES},
        {"type": "token", "text": "first half, "},
        {"type": "token", "text": "second half"},
        {"type": "done"}), store, "q", "qa", None)
    it = iter(resp.response)
    next(it)                                   # the client reads one line...
    it.close()                                 # ...and leaves
    for _ in range(50):
        if store.turns("c6"):
            break
        _t.sleep(0.02)
    t = store.turns("c6")[0]
    assert t["answer"] == "first half, second half" and t["kind"] == "answer"
