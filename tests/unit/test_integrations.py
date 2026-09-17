"""The convention itself: discovery, status shape, and the ollama gate.

These test `assistant/integrations/` generically — the machinery any external
app plugs into. Jude-specific behaviour is `test_jude.py`.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.request

import pytest

from assistant import model_protocol
from assistant.integrations import ollama_gate, process
from assistant.integrations.base import Integration, IntegrationUnavailable


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Fake(Integration):
    """A minimal integration, for testing the contract rather than Jude."""
    name = "faker"
    label = "Faker"
    repo = "https://example.invalid/faker"
    marker = os.path.join("server", "main.py")

    def __init__(self, **cfg):
        self._cfg = type("C", (), {
            "enabled": True, "path": "", "port": 0, "autostart": True, **cfg})()

    def config(self):
        return self._cfg

    def command(self, python):
        return [python, "-c", "pass"]


# ---------------------------------------------------------------------------
# status() is what every surface draws from, so its shape is the contract
# ---------------------------------------------------------------------------

def test_status_never_raises_and_always_explains_itself():
    """Every not-ready state must carry a sentence, because a client shows it.

    A blank `reason` with `ready` false leaves a surface with nothing to say,
    which is how "Jude is off" became an empty window.
    """
    for cfg in ({"enabled": False}, {"enabled": True, "path": "/nope"},
                {"enabled": True, "path": ""}):
        st = _Fake(**cfg).status()
        assert st["ready"] is False
        assert st["reason"], f"no reason given for {cfg}"
        assert set(st) >= {"name", "label", "enabled", "installed", "running",
                           "ready", "path", "port", "repo", "reason"}


def test_ready_is_not_running():
    """An integration that autostarts is ready BEFORE it is running.

    Conflating the two makes a client report a healthy integration as broken —
    the first request is what starts it.
    """
    st = _Fake(enabled=True, path="/nope").status()
    assert st["running"] is False
    assert st["reason"]


def test_marker_rejects_a_directory_that_is_not_the_checkout(tmp_path):
    """Pointing `path` at the wrong folder says so, rather than failing later
    with an ImportError from inside somebody else's server."""
    fake = _Fake(path=str(tmp_path))
    assert fake.root() is None

    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "main.py").write_text("")
    assert fake.root() == str(tmp_path)


def test_env_override_beats_config(tmp_path, monkeypatch):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "main.py").write_text("")
    monkeypatch.setenv("MACALENDAR_FAKER_PATH", str(tmp_path))
    assert _Fake(path="/somewhere/else").root() == str(tmp_path)


def test_disabled_integration_refuses_with_a_sentence():
    with pytest.raises(IntegrationUnavailable) as e:
        process.ensure_running(_Fake(enabled=False))
    assert "switched off" in str(e.value)
    assert _Fake.repo in str(e.value)


# ---------------------------------------------------------------------------
# The gate — the reason this layer exists at all
# ---------------------------------------------------------------------------

class _Upstream:
    """A stand-in for ollama that records what reached it."""

    def __init__(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.seen: list = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _reply(self):
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
                outer.seen.append((self.command, self.path,
                                   dict(self.headers)))
                body = json.dumps({"ok": True, "path": self.path}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _reply

        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def upstream():
    u = _Upstream()
    yield u
    u.close()


@pytest.fixture
def gate(upstream):
    port = _free_port()
    url = ollama_gate.start(port, upstream.url, model_protocol.BACKGROUND)
    yield url
    ollama_gate.stop(port)


def _post(url, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_gate_forwards_to_upstream(gate, upstream):
    assert _post(gate + "/api/generate")["ok"] is True
    assert [p for _, p, _ in upstream.seen] == ["/api/generate"]


def test_gate_holds_the_lock_for_generating_calls(gate):
    """The whole point: a gated call waits for the model lock.

    Proven by holding the lock elsewhere and timing the call, because asserting
    that `hold()` was *called* would pass even if the gate held it around
    nothing.
    """
    import fcntl
    fd = os.open(str(model_protocol.LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    released = threading.Event()

    def release():
        time.sleep(1.0)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        released.set()

    threading.Thread(target=release, daemon=True).start()
    t0 = time.monotonic()
    _post(gate + "/api/chat")
    waited = time.monotonic() - t0
    assert released.is_set(), "the gated call finished before the lock was freed"
    assert waited >= 0.9, f"gate did not wait for the lock (took {waited:.2f}s)"


def test_metadata_calls_are_not_gated(gate):
    """`/api/tags` is polled by status UIs. Gating it would make a status poll
    wait behind a 90-second synthesis for no reason at all."""
    import fcntl
    fd = os.open(str(model_protocol.LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        t0 = time.monotonic()
        with urllib.request.urlopen(gate + "/api/tags", timeout=10) as r:
            r.read()
        assert time.monotonic() - t0 < 0.5, "a metadata call waited for the lock"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_every_generating_endpoint_is_in_the_gated_list():
    """Ollama's generating endpoints, native and OpenAI-compatible.

    An integration may use either dialect — Jude's `_get_fallback_chain` builds
    an OpenAI-style client for some providers — so missing `/v1/*` would leave
    a door open for exactly the caller this is meant to catch.
    """
    for path in ("/api/generate", "/api/chat", "/api/embeddings", "/api/embed",
                 "/v1/chat/completions", "/v1/completions", "/v1/embeddings"):
        assert path in ollama_gate.GATED_PATHS


def test_hop_by_hop_headers_are_not_forwarded():
    """Forwarding Content-Length or Transfer-Encoding makes the client and the
    proxy disagree about framing — an answer that truncates at random."""
    for header in ("content-length", "transfer-encoding", "connection"):
        assert header in ollama_gate._HOP_BY_HOP


def test_gate_start_is_idempotent(upstream):
    port = _free_port()
    try:
        a = ollama_gate.start(port, upstream.url)
        b = ollama_gate.start(port, upstream.url)
        assert a == b and ollama_gate.is_running(port)
    finally:
        ollama_gate.stop(port)


# ---------------------------------------------------------------------------
# readiness_problem — "installed" is not "able to answer"
# ---------------------------------------------------------------------------

def test_a_readiness_problem_makes_it_not_ready(tmp_path):
    """Installed and switched on is not the same as able to serve.

    Jude's 2.2 GB index went missing and every surface said "isn't running
    yet" — true, useless, and indistinguishable from a slow start. A client
    drawing a composer on the strength of `ready` would invite a question that
    could not be answered.
    """
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "main.py").write_text("")

    class _Blocked(_Fake):
        def readiness_problem(self):
            return "Its data is missing — restore it with `some command`."

    st = _Blocked(path=str(tmp_path)).status()
    assert st["installed"] is True
    assert st["ready"] is False
    assert "restore it with" in st["reason"]


def test_a_readiness_problem_does_not_mask_a_missing_checkout(tmp_path):
    """A missing checkout is the more basic problem and has the better
    message, so it must win."""
    class _Blocked(_Fake):
        def readiness_problem(self):
            return "data missing"

    st = _Blocked(path="/nope").status()
    assert "isn't installed" in st["reason"]


def test_no_problem_means_the_old_behaviour(tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "main.py").write_text("")
    st = _Fake(path=str(tmp_path)).status()
    assert st["ready"] is True
    assert "isn't running yet" in st["reason"]

