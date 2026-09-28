"""The Mac apps' entry points (2026-09-28): one server per Mac, Tailscale found
from an app's bare PATH, and Jude's module actually runnable."""
from __future__ import annotations

import http.server
import json
import socket
import threading

from assistant import api


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(body: dict) -> "tuple[http.server.HTTPServer, int]":
    port = _free_port()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def test_a_free_port_is_free():
    assert api._already_running(_free_port()) is None


def test_our_own_server_on_the_port_is_recognised():
    srv, port = _serve({"status": "ok", "db": "/x/calendar.db"})
    try:
        assert api._already_running(port) == "ours"
    finally:
        srv.shutdown()


def test_someone_elses_program_on_the_port_is_not_ours():
    srv, port = _serve({"hello": "world"})
    try:
        assert api._already_running(port) == "other"
    finally:
        srv.shutdown()


def test_tailscale_is_looked_for_where_homebrew_puts_it():
    assert "/opt/homebrew/bin/tailscale" in api._TAILSCALE_CANDIDATES


def test_jude_is_runnable_as_a_module():
    import importlib.util
    assert importlib.util.find_spec("assistant.jude.__main__") is not None
