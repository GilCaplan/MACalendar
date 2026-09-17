"""Jude's bridge — where it is, and what its LLM calls are allowed to do.

Jude is a separate repository (DOCUMENTATION/JUDE.md), so "not installed" is a
normal state, not a failure — and the two things worth pinning are that it
degrades into a sentence rather than a traceback, and that switching it on
cannot quietly put this project on the internet.
"""
from __future__ import annotations

import os

import pytest

from assistant.config import JudeConfig, OllamaConfig
from assistant.jude import bridge


@pytest.fixture
def checkout(tmp_path):
    """A directory shaped like a Jude checkout."""
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text("app = None\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Finding it
# ---------------------------------------------------------------------------

def test_a_missing_checkout_is_simply_none(tmp_path):
    cfg = JudeConfig(enabled=True, path=str(tmp_path / "nowhere"))
    assert bridge.checkout_path(cfg) is None


def test_a_directory_that_is_not_jude_does_not_count(tmp_path):
    """Pointing at the wrong folder should say so here, not fail later with an
    import error from inside uvicorn."""
    (tmp_path / "README.md").write_text("not jude")
    assert bridge.checkout_path(JudeConfig(enabled=True, path=str(tmp_path))) is None


def test_an_absolute_path_is_found(checkout):
    cfg = JudeConfig(enabled=True, path=str(checkout))
    assert bridge.checkout_path(cfg) == str(checkout)


def test_the_environment_override_wins(checkout, monkeypatch, tmp_path):
    monkeypatch.setenv("MACALENDAR_JUDE_PATH", str(checkout))
    cfg = JudeConfig(enabled=True, path=str(tmp_path / "nowhere"))
    assert bridge.checkout_path(cfg) == str(checkout)


def test_a_relative_path_is_relative_to_the_repo_not_the_cwd(monkeypatch, tmp_path):
    """The assistant is launched from Finder, where the working directory is
    not something to depend on."""
    monkeypatch.chdir(tmp_path)
    cfg = JudeConfig(enabled=True, path="../JudeTheJudaicChatBot")
    # Whatever the answer is, it must not have been resolved against tmp_path.
    found = bridge.checkout_path(cfg)
    assert found is None or not found.startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# The protocol — "the llm calls use the same protocol as the assistant"
# ---------------------------------------------------------------------------

ROLES = ("ROUTER", "FILTER", "SUMMARY", "SYNTH", "TOOLS")


def test_every_role_is_pinned_to_local_ollama():
    """Jude's own default is a cloud cascade (Gemini → LLMod → Ollama). This
    project does not touch the internet — test_offline.py fails the build if
    that stops being true — so every role is pinned before it starts."""
    env = bridge.environment(JudeConfig(enabled=True), OllamaConfig())
    for role in ROLES:
        assert env[f"{role}_PROVIDER"] == "ollama", f"{role} could reach a cloud provider"


def test_it_shares_the_assistant_s_model_rather_than_loading_a_second():
    env = bridge.environment(JudeConfig(enabled=True),
                             OllamaConfig(model="llama3.1:8b"))
    for role in ROLES:
        assert env[f"{role}_MODEL"] == "llama3.1:8b"


def test_jude_model_overrides_it_when_asked():
    env = bridge.environment(JudeConfig(enabled=True, model="mistral:7b"),
                             OllamaConfig(model="llama3.1:8b"))
    assert env["SYNTH_MODEL"] == "mistral:7b"


def test_a_stray_cloud_key_in_the_environment_is_blanked(monkeypatch):
    """A .env in the Jude checkout, or an exported key, must not put this
    machine's Torah questions on someone else's server by accident."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyLooksReal")
    monkeypatch.setenv("LLMOD_API_KEY", "sk-also-real")
    env = bridge.environment(JudeConfig(enabled=True), OllamaConfig())
    assert env["GEMINI_API_KEY"] == ""
    assert env["LLMOD_API_KEY"] == ""


def test_it_points_at_the_assistant_s_ollama(monkeypatch):
    env = bridge.environment(JudeConfig(enabled=True),
                             OllamaConfig(base_url="http://localhost:11435"))
    assert env["OLLAMA_HOST"] == "http://localhost:11435"


def test_allow_cloud_hands_jude_back_its_own_environment(monkeypatch):
    """A named, deliberate choice — and from then on the traffic is Jude's."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyLooksReal")
    env = bridge.environment(JudeConfig(enabled=True, allow_cloud=True), OllamaConfig())
    assert env["GEMINI_API_KEY"] == "AIzaSyLooksReal"
    assert "SYNTH_PROVIDER" not in env or env["SYNTH_PROVIDER"] != "ollama"


# ---------------------------------------------------------------------------
# Degrading into a sentence, never a traceback
# ---------------------------------------------------------------------------

def test_switched_off_says_what_to_switch_on(tmp_path):
    st = bridge.status(JudeConfig(enabled=False), OllamaConfig())
    assert st["ready"] is False
    assert "jude.enabled" in st["reason"]
    assert st["repo"] in st["reason"]


def test_not_installed_names_the_repository(tmp_path, monkeypatch):
    monkeypatch.delenv("MACALENDAR_JUDE_PATH", raising=False)
    st = bridge.status(JudeConfig(enabled=True, path=str(tmp_path / "nowhere")),
                       OllamaConfig())
    assert st["installed"] is False and st["ready"] is False
    assert "github.com/GilCaplan/JudeTheJudaicChatBot" in st["reason"]


def test_installed_but_not_running_is_ready_and_says_it_will_start(checkout):
    """It starts on the first question, so "not running" is not "unavailable" —
    it is a note about the first answer taking longer."""
    st = bridge.status(JudeConfig(enabled=True, path=str(checkout), port=1),
                       OllamaConfig())
    assert st["installed"] is True and st["ready"] is True
    assert st["running"] is False
    assert "starts on the first question" in st["reason"]


def test_autostart_off_tells_you_to_start_it_yourself(checkout):
    st = bridge.status(JudeConfig(enabled=True, path=str(checkout), port=1,
                                  autostart=False), OllamaConfig())
    assert str(checkout) in st["reason"]


def test_status_never_raises_however_wrong_the_config():
    for cfg in (JudeConfig(), JudeConfig(enabled=True, path=""),
                JudeConfig(enabled=True, path="/definitely/not/here", port=0)):
        st = bridge.status(cfg, OllamaConfig())
        assert set(st) >= {"enabled", "installed", "running", "ready", "reason"}


@pytest.mark.parametrize("cfg,expected", [
    (JudeConfig(enabled=False), "switched off"),
    (JudeConfig(enabled=True, path="/definitely/not/here"), "can't find Jude"),
])
def test_ensure_running_refuses_with_a_readable_reason(cfg, expected, monkeypatch):
    monkeypatch.delenv("MACALENDAR_JUDE_PATH", raising=False)
    with pytest.raises(bridge.JudeUnavailable) as e:
        bridge.ensure_running(cfg, OllamaConfig())
    assert expected in str(e.value)


def test_it_never_probes_a_port_when_switched_off(monkeypatch):
    """Cheap and quiet: a disabled Jude must not open sockets on every status
    poll from the Mac window and the phone's tab."""
    def boom(*_a, **_k):
        raise AssertionError("probed the port with Jude switched off")

    monkeypatch.setattr(bridge, "is_listening", boom)
    assert bridge.status(JudeConfig(enabled=False), OllamaConfig())["running"] is False


# ---------------------------------------------------------------------------
# The routes, which must be equally undramatic
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_status_is_always_200(client):
    r = client.get("/jude/status")
    assert r.status_code == 200
    assert r.get_json()["ready"] is False        # not configured in the test env


def test_asking_with_jude_off_is_a_503_with_a_sentence(client):
    r = client.post("/jude/chat", json={"prompt": "what is kiddush?"})
    assert r.status_code == 503
    assert "jude.enabled" in r.get_json()["error"]


def test_an_empty_question_is_a_400(client):
    assert client.post("/jude/chat", json={"prompt": "  "}).status_code == 400
