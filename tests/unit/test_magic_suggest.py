"""POST /magic/suggest-words (TASKS 49): the Mac's model suggests words for a
magic-word object when the phone can't. The model call is faked — what is
pinned is the request it makes and the answers the phone relies on."""
from __future__ import annotations

import json

import pytest


class _Resp:
    def __init__(self, words):
        self._words = words

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": json.dumps({"words": self._words})}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_it_asks_the_model_through_the_protocol_and_returns_its_words(client, monkeypatch):
    """The model protocol, all of it: route_post (the gate), the request's
    priority (a phone is live), the seed options, and the call bus."""
    seen, logged = {}, []
    from assistant import llm_bus, model_protocol

    def fake(path, payload, timeout, base_url, session=None):
        seen.update(path=path, payload=payload, priority=model_protocol.priority())
        return _Resp(["hound", "pooch", "labrador"])
    monkeypatch.setattr(model_protocol, "route_post", fake)
    monkeypatch.setattr(model_protocol, "seed_options", lambda: {"seed": 7})
    monkeypatch.setattr(llm_bus, "record", lambda **kw: logged.append(kw))
    r = client.post("/magic/suggest-words",
                    json={"name": "German Shepherd", "existing": ["dog"], "count": 3, "source": "ios"})
    assert seen["priority"] == model_protocol.LIVE
    assert seen["payload"]["options"]["seed"] == 7
    assert logged and logged[0]["caller"] == "magic.suggest_words" and logged[0]["source"] == "ios"
    assert r.status_code == 200
    assert r.get_json() == {"words": ["hound", "pooch", "labrador"], "source": "mac"}
    assert seen["path"] == "/api/chat" and seen["payload"]["format"]["required"] == ["words"]
    user = seen["payload"]["messages"][1]["content"]
    assert "German Shepherd" in user and "dog" in user and "3 more" in user


def test_no_model_is_a_plain_503(client, monkeypatch):
    from assistant import model_protocol

    def down(*a, **k):
        raise ConnectionError("ollama is not running")
    monkeypatch.setattr(model_protocol, "route_post", down)
    r = client.post("/magic/suggest-words", json={"name": "Dragon"})
    assert r.status_code == 503 and "isn't available" in r.get_json()["error"]


def test_a_name_is_required(client):
    assert client.post("/magic/suggest-words", json={}).status_code == 400


def test_a_test_caller_is_background(client, monkeypatch):
    from assistant import model_protocol
    seen = {}

    def fake(path, payload, timeout, base_url, session=None):
        seen["priority"] = model_protocol.priority()
        return _Resp(["wyvern"])
    monkeypatch.setattr(model_protocol, "route_post", fake)
    client.post("/magic/suggest-words", json={"name": "Dragon", "source": "test"})
    assert seen["priority"] == model_protocol.BACKGROUND
