"""Reaching an integration on the client's behalf.

Clients never talk to an integration directly. They call THIS API — one host,
one `X-API-Key`, one tailnet hop — and it forwards to loopback. Three reasons,
and they apply to every integration, not just Jude:

- the phone keeps one address and learns nothing new when an app is added;
- the integration's own port never has to leave the machine, which matters
  because it almost certainly has no authentication of its own;
- the streaming shape is normalised ONCE, here, instead of in every client.

## SSE in, NDJSON out

An integration that streams will almost certainly speak Server-Sent Events,
because that is what a browser consumes. Every client in this project already
renders NDJSON — that is what `/voice/stream` is — so translating in the server
beats writing a second wire format into the Mac app and the iOS app and then
keeping them in step. One `data:` frame becomes one JSON line; event types pass
through untouched.
"""

from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)


def call(integration, path: str, method: str = "GET", payload: "dict | None" = None,
         timeout: int = 30):
    """One plain proxied call, as a Flask response. Never raises.

    A 503 carries the integration's own sentence about why it cannot answer —
    the one a client shows the user — rather than a status code they would have
    to translate.
    """
    from flask import jsonify

    from assistant.integrations import process
    from assistant.integrations.base import IntegrationUnavailable

    try:
        base = process.ensure_running(integration)
    except IntegrationUnavailable as e:
        return jsonify({"error": str(e), "code": 503}), 503

    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    try:
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8") or "null"
        return jsonify(json.loads(body))
    except Exception as e:                    # noqa: BLE001
        logger.warning("%s %s %s failed: %s", integration.name, method, path, e)
        return jsonify({"error": str(e), "code": 502}), 502


def stream(integration, path: str, payload: dict, timeout: int = 900):
    """POST to a streaming SSE endpoint; stream NDJSON back to the client.

    Starting the integration happens BEFORE the response begins, not inside the
    generator: a client that receives a 503 with a sentence in it can say
    something useful, while one whose stream opens and then dies cannot.
    """
    from flask import Response, jsonify, stream_with_context

    from assistant.integrations import process
    from assistant.integrations.base import IntegrationUnavailable

    try:
        base = process.ensure_running(integration)
    except IntegrationUnavailable as e:
        return jsonify({"error": str(e), "code": 503}), 503

    def generate():
        req = urllib.request.Request(
            base + path, method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if not line.startswith("data:"):
                        continue          # SSE blank separators and comments
                    yield line[5:].strip() + "\n"
        except Exception as e:            # noqa: BLE001 - the stream must say why
            logger.warning("%s stream failed: %s", integration.name, e)
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        # X-Accel-Buffering: a reverse proxy that buffers turns a token stream
        # into one blob at the end, which is indistinguishable from a hang.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
