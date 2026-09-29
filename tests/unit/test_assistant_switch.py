"""Settings ▸ Assistant ▸ Assistant on (Gil, 2026-09-29: "an option to turn
assistant i.e engine off so it can't be used"). Off: no command reaches the
engine, from any client; everything else works."""
from __future__ import annotations

import pytest

import assistant.api.server as server
from assistant.api import assistant_switch


@pytest.fixture
def client():
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(assistant_switch, "enabled", lambda: False)


def test_on_by_default():
    from assistant.config import EngineConfig
    assert EngineConfig().enabled is True


@pytest.mark.parametrize("path", sorted(assistant_switch.ENGINE_ROUTES))
def test_off_refuses_every_command_route(client, off, path):
    r = client.post(path, json={"text": "lunch tomorrow at 1", "source": "test"})
    assert r.status_code == 503
    body = r.get_json()
    assert body["assistant_off"] is True and "Settings ▸ Assistant" in body["error"]


def test_off_leaves_the_calendar_working(client, off):
    assert client.get("/events?date=2026-09-29").status_code == 200
    assert client.get("/todos").status_code == 200
    assert client.get("/health").get_json()["assistant"] is False


def test_the_switch_is_read_and_written_over_http(client, monkeypatch):
    written = []
    monkeypatch.setattr("assistant.config_store.set_values",
                        lambda upd, *a, **k: written.append(upd) or True)
    assert client.get("/assistant").get_json() == {"enabled": True}
    assert client.put("/assistant", json={"enabled": False}).status_code == 200
    assert written == [{"engine": {"enabled": False}}]
    assert client.put("/assistant", json={"enabled": "no"}).status_code == 400


def test_another_machine_needs_the_admin_once_there_are_users(client, monkeypatch):
    from assistant.users import registry
    monkeypatch.setattr(registry, "exists", lambda: True)
    r = client.put("/assistant", json={"enabled": False},
                   environ_base={"REMOTE_ADDR": "100.64.0.7"})
    assert r.status_code == 401


def test_the_mac_mic_does_not_open_while_off(monkeypatch):
    from assistant import pipeline as P
    from assistant.config import load_config
    cfg = load_config()
    cfg.engine.enabled = False
    monkeypatch.setattr("assistant.config.load_config", lambda *a, **k: cfg)
    pipe = P.Pipeline.__new__(P.Pipeline)
    import threading
    pipe._trigger_lock = threading.Lock()
    pipe._busy = threading.Event()
    said = []
    pipe._set_status = lambda status, msg="": said.append((status, msg))
    pipe.trigger()
    assert said == [(P.STATUS_ERROR, "The assistant is off — Settings ▸ Assistant")]
