"""Jude's bridge — where it is, and what its LLM calls are allowed to do.

Jude is a separate repository (DOCUMENTATION/JUDE.md), so "not installed" is a
normal state, not a failure — and the two things worth pinning are that it
degrades into a sentence rather than a traceback, and that switching it on
cannot quietly put this project on the internet.
"""
from __future__ import annotations

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


# ---------------------------------------------------------------------------
# The proxy, against a Jude that actually answers
#
# Jude streams Server-Sent Events; every client here renders the NDJSON
# /voice/stream uses. The translation happens once, in the server, so this is
# the test that it happens correctly — a fake Jude on a real socket, speaking
# real SSE, read through the real route.
# ---------------------------------------------------------------------------

SSE_SCRIPT = [
    'data: {"type": "stage", "name": "Routing question\\u2026"}\n\n',
    ': a comment line, which SSE allows and NDJSON must not carry\n\n',
    'data: {"type": "meta", "chat_id": "c1", "sources": [{"ref": "Shabbat 21b"}],'
    ' "halachic_label": "Shabbat", "halachic_seder": "Moed"}\n\n',
    'data: {"type": "token", "text": "The "}\n\n',
    'data: {"type": "token", "text": "Gemara "}\n\n',
    'data: {"type": "token", "text": "\\u05e9\\u05d1\\u05ea"}\n\n',   # Hebrew survives
    'data: {"type": "done", "timing": {"total_ms": 12}}\n\n',
]


@pytest.fixture
def fake_jude():
    """A socket that speaks SSE the way Jude's /api/chat does."""
    import http.server
    import json
    import threading

    seen: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):            # noqa: N802 (http.server's name)
            length = int(self.headers.get("Content-Length") or 0)
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(length) or b"{}")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for frame in SSE_SCRIPT:
                self.wfile.write(frame.encode("utf-8"))
                self.wfile.flush()

        def log_message(self, *_a):   # keep pytest output clean
            pass

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            # `bridge.is_listening` probes the port by opening a connection and
            # closing it without saying anything, which makes http.server print
            # a traceback. Expected, and not a failure — swallow it so the only
            # thing in pytest's output is the test result.
            pass

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1], seen
    finally:
        server.shutdown()


@pytest.fixture
def wired(client, checkout, fake_jude, monkeypatch):
    """The API, with Jude 'installed' and already listening on the fake port."""
    port, seen = fake_jude
    import assistant.api.server as srv
    real_load = srv.load_config

    def patched(*a, **k):
        cfg = real_load(*a, **k)
        cfg.jude.enabled = True
        cfg.jude.path = str(checkout)
        cfg.jude.port = port
        return cfg

    monkeypatch.setattr(srv, "load_config", patched)
    return client, seen


def test_sse_becomes_one_json_object_per_line(wired):
    client, _ = wired
    r = client.post("/jude/chat", json={"prompt": "may I carry on shabbat?"})
    assert r.status_code == 200
    assert r.mimetype == "application/x-ndjson"

    import json
    lines = [ln for ln in r.get_data(as_text=True).split("\n") if ln]
    events = [json.loads(ln) for ln in lines]       # every line must parse alone
    assert [e["type"] for e in events] == ["stage", "meta", "token", "token",
                                           "token", "done"]


def test_the_comment_frame_is_dropped(wired):
    """SSE comments and blank separators are not events; a client decoding
    NDJSON line-by-line would choke on them."""
    client, _ = wired
    body = client.post("/jude/chat", json={"prompt": "x"}).get_data(as_text=True)
    assert "a comment line" not in body


def test_the_answer_reassembles_from_its_tokens(wired):
    import json
    client, _ = wired
    body = client.post("/jude/chat", json={"prompt": "x"}).get_data(as_text=True)
    text = "".join(json.loads(ln).get("text", "")
                   for ln in body.split("\n") if ln)
    assert text == "The Gemara שבת", "tokens or Hebrew lost in translation"


def test_the_metadata_a_client_needs_survives(wired):
    import json
    client, _ = wired
    body = client.post("/jude/chat", json={"prompt": "x"}).get_data(as_text=True)
    meta = next(json.loads(ln) for ln in body.split("\n")
                if ln and json.loads(ln)["type"] == "meta")
    assert meta["chat_id"] == "c1"
    assert meta["sources"][0]["ref"] == "Shabbat 21b"
    assert meta["halachic_label"] == "Shabbat" and meta["halachic_seder"] == "Moed"


def test_what_the_request_carries_to_jude(wired):
    client, seen = wired
    client.post("/jude/chat", json={"prompt": "may I carry?", "mode": "study",
                                    "chat_id": "c9"})
    assert seen["path"] == "/api/chat"
    assert seen["body"]["prompt"] == "may I carry?"
    assert seen["body"]["mode"] == "study"
    assert seen["body"]["chat_id"] == "c9"
    # Jude scopes chats by user; everything from here is one user.
    assert seen["body"]["user"] == "macalendar"


def test_defaults_when_the_client_says_only_the_question(wired):
    client, seen = wired
    client.post("/jude/chat", json={"prompt": "hi"})
    assert seen["body"]["mode"] == "qa"
    assert seen["body"]["lang"] == "en"
    assert seen["body"]["chat_id"] is None


def test_status_sees_it_running(wired):
    client, _ = wired
    st = client.get("/jude/status").get_json()
    assert st["ready"] is True and st["running"] is True and st["reason"] == ""


def test_a_jude_that_drops_the_connection_says_so_in_the_stream(client, checkout,
                                                               monkeypatch):
    """The stream must never just stop. A client is waiting for `done`; if the
    generator ends silently it waits for ever, so a failure has to arrive as an
    event of its own."""
    import json
    import socket
    import threading

    # Listening, so `ensure_running` is satisfied — and then it hangs up
    # without ever answering, which is what a Jude that has just died looks
    # like from here.
    srv_sock = socket.socket()
    srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_sock.bind(("127.0.0.1", 0))
    srv_sock.listen(1)
    port = srv_sock.getsockname()[1]

    def serve():
        # A LOOP, not one accept: `ensure_running` probes the port with its own
        # connection first, so a single accept is spent before the request ever
        # arrives — and the request then sits in the backlog until the 600 s
        # timeout, which is a hung test rather than a failing one.
        while True:
            try:
                conn, _ = srv_sock.accept()
                conn.close()
            except OSError:
                return

    threading.Thread(target=serve, daemon=True).start()

    import assistant.api.server as srv_mod
    real_load = srv_mod.load_config

    def patched(*a, **k):
        cfg = real_load(*a, **k)
        cfg.jude.enabled = True
        cfg.jude.path = str(checkout)
        cfg.jude.port = port
        return cfg

    monkeypatch.setattr(srv_mod, "load_config", patched)
    try:
        body = client.post("/jude/chat", json={"prompt": "x"}).get_data(as_text=True)
    finally:
        srv_sock.close()
    events = [json.loads(ln) for ln in body.split("\n") if ln]
    assert events, "the stream produced nothing at all"
    assert events[-1]["type"] == "error", f"stream ended without saying why: {events}"
    assert events[-1]["message"], "an error event with no message is no better"
