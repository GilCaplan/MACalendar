"""A long think on the Mac must not look like a dead Mac on the phone.

Jude's answer is five model calls, and behind a busy Ollama — a board running
on the Mac — its first line can take minutes. The phone's stream timeout is an
INACTIVITY timeout, so silence that long read as "the Mac was unreachable" and
armed the shared backoff, while /jude/status answered fine (Gil, 2026-09-22).
The proxy now emits a keepalive line whenever the upstream has been silent for
`KEEPALIVE_S`; the phone ignores the line and the connection stays warm.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from flask import Flask

from assistant.integrations import process, proxy


def _slow_sse_server(delay: float):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"          # the connection closing is the end of the stream

        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(n)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            time.sleep(delay)                   # the model is busy elsewhere
            self.wfile.write(b'data: {"type": "token", "text": "hi"}\n\n')
            self.wfile.write(b'data: {"type": "done"}\n\n')
            self.wfile.flush()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _stream_lines(monkeypatch, url, keepalive: float) -> list:
    monkeypatch.setattr(proxy, "KEEPALIVE_S", keepalive)
    monkeypatch.setattr(process, "ensure_running", lambda integ: url)
    integ = SimpleNamespace(name="jude", before_request=lambda: None)
    app = Flask(__name__)
    with app.test_request_context("/jude/chat", method="POST"):
        resp = proxy.stream(integ, "/api/chat", {"prompt": "x"})
        body = "".join(part.decode() if isinstance(part, bytes) else part for part in resp.response)
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def test_a_silent_upstream_gets_keepalives_and_the_answer_still_arrives_whole(monkeypatch):
    srv, url = _slow_sse_server(delay=0.45)
    try:
        lines = _stream_lines(monkeypatch, url, keepalive=0.1)
    finally:
        srv.shutdown(); srv.server_close()
    kinds = [x["type"] for x in lines]
    assert kinds[0] == "keepalive", kinds
    assert kinds.count("keepalive") >= 2, kinds
    assert kinds[-2:] == ["token", "done"], kinds


def test_a_prompt_upstream_gets_no_keepalive(monkeypatch):
    srv, url = _slow_sse_server(delay=0.0)
    try:
        lines = _stream_lines(monkeypatch, url, keepalive=5.0)
    finally:
        srv.shutdown(); srv.server_close()
    assert [x["type"] for x in lines] == ["token", "done"]


def test_an_upstream_that_dies_says_so_on_the_stream(monkeypatch):
    lines = _stream_lines(monkeypatch, "http://127.0.0.1:9", keepalive=5.0)   # nothing listens on 9
    assert lines and lines[-1]["type"] == "error" and lines[-1]["message"]
