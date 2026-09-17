"""Jude's wiring: the environment its server gets, and the routes clients call.

The environment tests are the important half. Jude is started as a child
process we do not control and do not edit, so the environment IS the entire
mechanism by which it obeys this project's two rules — local-only models, and
the ollama gate. A regression here is silent: Jude keeps working, it just stops
being ours.
"""

from __future__ import annotations

import os
import pathlib

import pytest
from flask import Flask

from assistant.jude.integration import CLOUD_KEYS, ROLES, JudeIntegration


@pytest.fixture
def jude(monkeypatch, tmp_path):
    """A Jude pointed at a plausible checkout, with the gate on a scratch port."""
    checkout = tmp_path / "JudeTheJudaicChatBot"
    (checkout / "backend").mkdir(parents=True)
    (checkout / "backend" / "main.py").write_text("")
    monkeypatch.setenv("MACALENDAR_JUDE_PATH", str(checkout))
    return JudeIntegration()


@pytest.fixture(autouse=True)
def _scratch_gate(monkeypatch):
    """Never start the gate on the configured port during tests — a suite that
    bound 11435 would collide with the running assistant's own gate."""
    import socket

    from assistant.integrations import ollama_gate
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    started = {}

    def fake_start(p, upstream, priority=None):
        started["args"] = (p, upstream, priority)
        return f"http://127.0.0.1:{port}"

    monkeypatch.setattr(ollama_gate, "start", fake_start)
    monkeypatch.setattr(ollama_gate, "is_running", lambda p: True)
    return started


# ---------------------------------------------------------------------------
# The environment is the whole mechanism
# ---------------------------------------------------------------------------

def test_every_role_is_pinned_to_local_ollama(jude):
    """Jude defaults to Gemini -> LLMod -> ollama. Missing a single role sends
    that stage's traffic to someone else's server."""
    env = jude.environment()
    for role in ROLES:
        assert env[f"{role}_PROVIDER"] == "ollama", f"{role} not pinned"
        assert env[f"{role}_MODEL"] == jude.model()
    assert len(ROLES) == 5, "Jude has five roles; pin all of them"


def test_cloud_keys_are_blanked(jude):
    """Belt and braces behind the per-role pin: a stray .env in the checkout
    must not be able to build a cascade."""
    env = jude.environment()
    for key in CLOUD_KEYS:
        assert env[key] == "", f"{key} survived into the child"


def test_ollama_host_points_at_the_gate_not_at_ollama(jude):
    """The fifth door. If this points at 11434, Jude's five calls per question
    are arbitrated by nothing — see integrations/ollama_gate.py."""
    from assistant.config import load_config
    env = jude.environment()
    assert env["OLLAMA_HOST"] != load_config().ollama.base_url.rstrip("/")
    assert env["MACALENDAR_OLLAMA_GATE"] == env["OLLAMA_HOST"]
    assert env["MACALENDAR_OLLAMA_UPSTREAM"]


def test_gate_runs_at_background_priority_by_default(jude, _scratch_gate):
    """`hold()` is asymmetric: two LIVE callers do not arbitrate at all, so a
    live Jude would RACE voice commands instead of yielding to them."""
    jude.environment()
    _port, _upstream, priority = _scratch_gate["args"]
    assert priority == "background"


def test_shim_is_prepended_to_pythonpath(jude):
    """Jude hardcodes ollama's address for its ChromaDB embedding function, so
    OLLAMA_HOST alone leaves the retrieval path ungated."""
    env = jude.environment()
    first = env["PYTHONPATH"].split(os.pathsep)[0]
    assert os.path.isfile(os.path.join(first, "sitecustomize.py"))


def test_shim_directory_holds_nothing_that_could_shadow(jude):
    """PYTHONPATH goes to the FRONT of the child's sys.path, so any other
    importable module in here would shadow Jude's own module of that name."""
    env = jude.environment()
    shim = env["PYTHONPATH"].split(os.pathsep)[0]
    entries = [f for f in os.listdir(shim) if f != "__pycache__"]
    assert entries == ["sitecustomize.py"], f"shim dir has extras: {entries}"


def test_allow_cloud_hands_the_environment_back_but_keeps_the_gate(jude, monkeypatch):
    """A deliberate, named choice. Arbitration is about this machine's ollama
    rather than about privacy, so the gate survives it."""
    real = jude.config()
    stub = type("C", (), {k: getattr(real, k) for k in
                          ("enabled", "path", "port", "autostart", "model",
                           "gate_port", "priority")})()
    stub.allow_cloud = True
    monkeypatch.setattr(jude, "config", lambda: stub)

    env = jude.environment()
    # Its own cascade is back: nothing is pinned and no key is blanked.
    assert "ROUTER_PROVIDER" not in env or env["ROUTER_PROVIDER"] != "ollama"
    assert not any(env.get(k) == "" for k in CLOUD_KEYS if k in os.environ)
    # But it is still behind the gate.
    assert env["OLLAMA_HOST"] == env["MACALENDAR_OLLAMA_GATE"]
    assert env["PYTHONPATH"].split(os.pathsep)[0].endswith("shim")


def test_marker_is_judes_own_file(jude, tmp_path):
    """A directory only counts as Jude when backend/main.py is in it."""
    assert jude.marker == os.path.join("backend", "main.py")
    assert jude.root() is not None


def test_command_binds_loopback_only(jude):
    """Jude has no auth of its own; a tailnet-wide FastAPI would be a hole."""
    cmd = jude.command("/usr/bin/python3")
    assert "--host" in cmd and cmd[cmd.index("--host") + 1] == "127.0.0.1"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from assistant.jude.routes import blueprint
    app = Flask(__name__)
    app.register_blueprint(blueprint)
    return app.test_client()


def test_status_never_errors_even_with_no_checkout(client):
    r = client.get("/jude/status")
    assert r.status_code == 200
    assert r.get_json()["reason"]


def test_chat_rejects_an_empty_prompt(client):
    assert client.post("/jude/chat", json={"prompt": "   "}).status_code == 400


def test_unavailable_jude_answers_503_with_a_sentence(client):
    """Not a bare status code: the body carries the sentence a client shows."""
    r = client.post("/jude/chat", json={"prompt": "what is shabbat"})
    assert r.status_code == 503
    assert len(r.get_json()["error"]) > 20


def test_topic_requires_a_topic(client):
    assert client.put("/jude/chats/abc/topic", json={}).status_code == 400


@pytest.mark.parametrize("given,expected", [
    (0, 1), (99, 30), (25, 25), ("nonsense", 25), (None, 25)])
def test_top_k_is_clamped(given, expected, monkeypatch):
    """Jude clamps to 1..30 itself; clamping here means a bad client gets a
    sane answer rather than a 422 it has to interpret."""
    from assistant.jude import routes
    captured = {}

    def fake_stream(integration, path, payload, timeout=900):
        captured.update(payload)
        return "", 200

    monkeypatch.setattr(routes.proxy, "stream", fake_stream)
    app = Flask(__name__)
    app.register_blueprint(routes.blueprint)
    app.test_client().post("/jude/chat", json={"prompt": "x", "top_k": given})
    assert captured["top_k"] == expected


@pytest.mark.parametrize("given,expected", [
    ("study", "study"), ("sources", "sources"), ("qa", "qa"), ("wat", "qa")])
def test_mode_is_validated(given, expected, monkeypatch):
    from assistant.jude import routes
    captured = {}
    monkeypatch.setattr(routes.proxy, "stream",
                        lambda i, p, payload, timeout=900: (captured.update(payload), ("", 200))[1])
    app = Flask(__name__)
    app.register_blueprint(routes.blueprint)
    app.test_client().post("/jude/chat", json={"prompt": "x", "mode": given})
    assert captured["mode"] == expected


def test_routes_do_not_parse_or_execute():
    """CLAUDE.md: an integration's routes are HTTP plumbing. Jude must not be
    able to create an event, so the engine has no business being imported here.
    """
    src = open("assistant/jude/routes.py").read()
    for forbidden in ("assistant.engine", "from assistant.pipeline", "EngineState"):
        assert forbidden not in src, f"routes.py reaches into the brain: {forbidden}"


def test_a_missing_index_says_so_with_the_restore_command(jude):  # noqa: D401
    """The blocker that cost an afternoon. `chroma_db/` is 2.2 GB, gitignored
    in Jude's own repository and hosted on Hugging Face, so its absence is a
    normal state for a fresh checkout — and must not read as "starting up"."""
    problem = jude.readiness_problem()
    assert "index is missing" in problem
    assert "snapshot_download" in problem, "the sentence must carry the fix"
    assert "RockyCo/jude-judaic-data" in problem
    assert jude.status()["ready"] is False
    # NB the `reason` here is "switched off": conftest forces that, and the
    # branch order in `Integration.status` is deliberate — a more basic problem
    # has the better message. `test_integrations.py` covers the branch itself.


def test_an_index_present_clears_the_problem(jude):
    """Only the readiness hook is under test here — `ready` also depends on
    `enabled`, which conftest forces off so no test can start Jude's server."""
    (pathlib.Path(jude.root()) / "chroma_db").mkdir()
    assert jude.readiness_problem() == ""
    assert "index is missing" not in jude.status()["reason"]

