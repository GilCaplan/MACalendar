"""Everything this app knows about HTTP.

It talks to the MACalendar API — `127.0.0.1:<port>/jude/*` — and never to
Jude's own port, even though both are on this machine. Talking to Jude directly
is the obvious shortcut and it is exactly what the bridge exists to prevent:
the phone goes through `/jude/*` and gets the proxy's NDJSON, and a Mac window
that speaks Jude's own SSE instead is a second client of a second protocol,
which drifts the week after it is written.

Every call runs on a worker thread and comes back through a signal. A local
model answers in 30-90 seconds and an unreachable API costs the whole socket
timeout; either one on the GUI thread is a frozen window, which reads as a
crash and is what people report instead of the real fault.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# The chat stream's ceiling is generous because the first question after a cold
# start is what loads a ~2 GB index; the short one is for the CRUD calls, where
# waiting that long would only mean something is already wrong.
STREAM_TIMEOUT = 900
CALL_TIMEOUT = 30


def api_base(config) -> str:
    port = os.environ.get("MACALENDAR_API_PORT") or str(
        getattr(getattr(config, "api", None), "port", 8080))
    return f"http://127.0.0.1:{port}"


def api_headers(config) -> dict:
    headers = {"Content-Type": "application/json"}
    key = getattr(getattr(config, "api", None), "key", None)
    if key:
        headers["X-API-Key"] = key
    return headers


def build_request(config, method: str, path: str, body=None):
    return urllib.request.Request(
        api_base(config) + path, method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=api_headers(config))


def explain(config, exc: Exception) -> str:
    """The sentence to show a person when a call fails.

    The API answers 503 with an `error` field holding a sentence written for a
    human — "Jude isn't installed at …", "Jude is switched off in config.yaml"
    — precisely so that no client has to invent one from a status code. Showing
    "HTTP 503" throws that away and tells the reader nothing they can act on,
    so the body is read on the error path for exactly this.
    """
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = (json.loads(exc.read().decode("utf-8", "replace")) or {}).get("error")
        except Exception:                      # noqa: BLE001 - a body we cannot read
            detail = None
        return detail or f"The assistant answered {exc.code}."
    return (f"Couldn't reach the assistant on {api_base(config)} — "
            f"is it running? ({exc})")


def request(config, method: str, path: str, body=None, timeout: int = CALL_TIMEOUT):
    """One plain call. Blocking — callers are on a worker thread."""
    with urllib.request.urlopen(build_request(config, method, path, body),
                                timeout=timeout) as response:
        raw = response.read().decode("utf-8", "replace").strip()
    return json.loads(raw) if raw else None


class _Call(QObject):
    ok = pyqtSignal(object)
    failed = pyqtSignal(str)


def call_async(parent, config, method: str, path: str, on_ok, on_error=None,
               body=None, timeout: int = CALL_TIMEOUT):
    """Run one API call off the GUI thread and deliver the result on it.

    The carrier is parented to `parent` for lifetime, not tidiness: a QObject
    nobody references is collected while its thread is still running, and the
    signal then arrives at a deleted C++ object and takes the process with it.
    It deletes itself once it has delivered, so a long session does not leave a
    carrier per call hanging off the window.
    """
    call = _Call(parent)
    call.ok.connect(on_ok)
    if on_error is not None:
        call.failed.connect(on_error)
    call.ok.connect(lambda *_: call.deleteLater())
    call.failed.connect(lambda *_: call.deleteLater())

    def work() -> None:
        try:
            call.ok.emit(request(config, method, path, body, timeout))
        except Exception as exc:               # noqa: BLE001 - reported, never raised
            logger.info("jude %s %s failed: %s", method, path, exc)
            call.failed.emit(explain(config, exc))

    threading.Thread(target=work, daemon=True,
                     name=f"jude-{method.lower()}").start()
    return call
