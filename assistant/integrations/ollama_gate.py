"""The lock an integration cannot forget to take.

## The fifth door

`assistant/model_protocol.py` exists because four processes on this Mac share
one ollama: measured while a board ran, a trivial five-token call took 2.0s,
then 42.5s, then 43.9s, none of it inference. Every caller in THIS repository
goes through `model_protocol.hold()`, and a test reads the tree to prove there
is no fourth door.

An integration is a fifth door, and it is one we cannot put a lock on from the
inside — it is somebody else's repository, with its own venv, and we do not
edit it. Jude alone makes five model calls per question (router, filter,
summary, synthesis, tools) plus an embedding per retrieval, none of them
arbitrated. That is not a small leak; synthesis is a 30-90 second call.

So the lock goes OUTSIDE the process, in front of ollama, where it cannot be
forgotten: a proxy that speaks ollama's own HTTP API, takes `hold()` around
each call, and forwards. The integration is pointed at it with `OLLAMA_HOST`
and needs to know nothing.

## Why BACKGROUND is the default priority

`hold()` is asymmetric on purpose — LIVE waits 50ms and then goes ANYWAY,
BACKGROUND blocks and releases between every call. Two LIVE callers therefore
do not arbitrate against each other at all; they race, deliberately, because
they are both the user.

Which means marking an integration LIVE would restore exactly the contention
this gate exists to remove: a voice command arriving during a 90-second
synthesis would wait 50ms, give up, and run a second inference alongside it,
making both slow. BACKGROUND makes the integration YIELD — the voice command
gets the model to itself, and the integration resumes a moment later.

That trade is nearly free in one direction and decisive in the other. An
integration's answer is tens of seconds of inference, so a few hundred
milliseconds of yielding is imperceptible; a voice command is the user waiting
on a nine-second round trip, where queueing behind a synthesis is the whole
difference between "instant" and "broken". `<name>.priority: live` in
config.yaml overrides it for an integration that really is the foreground.

## What is gated, and what is not

Only the endpoints that GENERATE or EMBED — those are the ones that occupy the
model. `/api/tags`, `/api/ps` and `/api/version` are metadata, they are polled
by status UIs, and gating them would make a status poll wait behind a
synthesis for no reason at all.
"""

from __future__ import annotations

import logging
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from assistant import model_protocol

logger = logging.getLogger(__name__)

#: Ollama endpoints that occupy the model. Everything else is metadata and is
#: forwarded ungated so a status poll never waits behind an inference.
GATED_PATHS = (
    "/api/generate",
    "/api/chat",
    "/api/embeddings",
    "/api/embed",
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
)

#: Hop-by-hop headers that must not be forwarded (RFC 7230 §6.1). Forwarding
#: `Connection` or `Transfer-Encoding` makes the client and the proxy disagree
#: about framing, which shows up as a stream that truncates mid-answer.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
})

_servers: "dict[int, ThreadingHTTPServer]" = {}
_lock = threading.Lock()


def _handler_for(upstream: str, priority: str, authorize=None,
                 priority_header: bool = False, extra=None):
    """The proxy handler. The three optional hooks are what a MODEL HELPER
    adds (assistant/host/helper.py, DEVQA Q70) — Jude's gate uses none:

    authorize(headers) -> bool   refuse (401) a caller without a valid token
    priority_header              take the priority from X-MACalendar-Priority,
                                 so a primary's LIVE call stays live here
    extra(handler, method) -> bool   serve the gate's own /gate/* endpoints
    """
    class _GateHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # BaseHTTPRequestHandler logs every request to stderr. This proxy sees
        # one line per token batch; leave it to the module logger instead.
        def log_message(self, fmt, *args):       # noqa: A003
            logger.debug("ollama-gate %s", fmt % args)

        def _relay(self, method: str) -> None:
            if extra is not None and extra(self, method):
                return
            if authorize is not None and not authorize(self.headers):
                self._send_json(401, {"error": "this model helper needs its token"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            path = self.path
            gated = any(path.startswith(p) for p in GATED_PATHS)
            kind = priority
            if priority_header:
                asked = (self.headers.get("X-MACalendar-Priority") or "").strip().lower()
                kind = asked if asked in (model_protocol.LIVE, model_protocol.BACKGROUND) \
                    else model_protocol.BACKGROUND

            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in _HOP_BY_HOP
                       and k.lower() not in ("authorization", "x-macalendar-priority")}
            req = urllib.request.Request(
                upstream + path, data=body, method=method, headers=headers)

            if gated:
                # The hold spans the WHOLE response, because for a streaming
                # generate that IS the call — releasing at the first token
                # would hand the model over mid-answer.
                with model_protocol.hold(kind) as waited_ms:
                    if waited_ms > 250:
                        logger.info("ollama-gate: %s waited %dms for the model",
                                    path, waited_ms)
                    self._forward(req)
            else:
                self._forward(req)

        def _forward(self, req) -> None:
            try:
                with urllib.request.urlopen(req, timeout=900) as upstream_resp:
                    self.send_response(upstream_resp.status)
                    for key, value in upstream_resp.headers.items():
                        if key.lower() not in _HOP_BY_HOP:
                            self.send_header(key, value)
                    # Chunked, because a streamed generate has no length up
                    # front and the caller must see tokens as they arrive.
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self._pump(upstream_resp)
            except urllib.error.HTTPError as e:
                # Ollama's own error, passed through with its body: the
                # integration knows what to do with "model not found", and a
                # rewritten 502 would hide it.
                payload = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type",
                                 e.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:              # noqa: BLE001
                logger.warning("ollama-gate: %s %s failed: %s",
                               req.get_method(), req.full_url, exc)
                self._fail(str(exc))

        def _pump(self, upstream_resp) -> None:
            """Relay the body as it arrives.

            `read1` and not `read`: `read(n)` blocks until it has all n bytes,
            which for a token stream means holding tokens back until enough of
            them pile up. That turns a live stream into a stuttering one, and
            it is the single most common way a streaming proxy ruins the thing
            it is proxying.
            """
            while True:
                chunk = upstream_resp.read1(65536)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        def _send_json(self, code: int, obj) -> None:
            import json
            payload = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _fail(self, message: str) -> None:
            import json
            payload = json.dumps({"error": message}).encode()
            try:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except OSError:
                pass          # client already gave up; nothing to report to

        def do_POST(self):   # noqa: N802 (http.server's name)
            self._relay("POST")

        def do_GET(self):    # noqa: N802
            self._relay("GET")

        def do_DELETE(self):  # noqa: N802
            self._relay("DELETE")

        def do_HEAD(self):   # noqa: N802
            self._relay("HEAD")

    return _GateHandler


def start(port: int, upstream: str, priority: str = model_protocol.BACKGROUND,
          host: str = "127.0.0.1", authorize=None, priority_header: bool = False,
          extra=None) -> str:
    """Start the gate (idempotent) and return the base URL to point a child at.

    Runs in a daemon thread inside whichever process calls this — normally the
    API server, which is already the thing that starts integrations. Daemon so
    it can never keep the assistant alive after the window closes.
    """
    with _lock:
        if port not in _servers:
            if host != "127.0.0.1" and authorize is None:
                # Open to the network without a token is ollama for anyone
                # on the Wi-Fi. Refused, not warned about.
                raise ValueError("a gate beyond this machine needs authorize=")
            handler = _handler_for(upstream.rstrip("/"), priority, authorize,
                                   priority_header, extra)
            server = ThreadingHTTPServer((host, port), handler)
            server.daemon_threads = True
            threading.Thread(target=server.serve_forever, daemon=True,
                             name=f"ollama-gate-{port}").start()
            _servers[port] = server
            logger.info("ollama gate on %s:%d -> %s (priority=%s)",
                        host, port, upstream, priority)
    return f"http://127.0.0.1:{port}"


def stop(port: int) -> None:
    with _lock:
        server = _servers.pop(port, None)
    if server is not None:
        server.shutdown()
        server.server_close()


def is_running(port: int) -> bool:
    return port in _servers
