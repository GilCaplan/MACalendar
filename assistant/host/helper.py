"""A MODEL HELPER: this machine lends its model to a primary (DEVQA Q70).

Runs the same gate every model call on this project goes through
(``integrations/ollama_gate.py`` → ``model_protocol.hold()``), open to the
network on ``PORT`` — but only to a caller holding a token THIS machine
issued. The priority rides in with each call (``X-MACalendar-Priority``), so a
primary's live voice command is live here too, and this machine's own work
queues with it exactly as it would at home.

    GET  /gate/info      open: name, OS, gate version, models + digests, busy
    POST /gate/claim     {code, primary} → {token}: the code shown on THIS
                         machine's screen, typed on the primary once
    POST /gate/release   (token) → forget that primary
    *    /api/…          (token) → ollama, through the gate

Tokens are stored as SHA-256 hashes (``MACALENDAR_HELPER_TOKENS``,
``~/.assistant_tools/helper_tokens.json``): the file never holds a working
credential.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import pathlib
import platform
import secrets
import threading
import time

from assistant import model_protocol
from assistant.integrations import ollama_gate
from assistant.pairing import addresses, codes, discovery

logger = logging.getLogger(__name__)

PORT = 11436
UPSTREAM = "http://127.0.0.1:11434"
GATE_PROTOCOL = 1
TOKENS_PATH = pathlib.Path(os.environ.get("MACALENDAR_HELPER_TOKENS")
                           or (pathlib.Path.home() / ".assistant_tools" / "helper_tokens.json"))
_FAILS_BEFORE_PAUSE, _PAUSE_S = 5, 60.0


def os_name() -> str:
    return {"Darwin": "macOS"}.get(platform.system(), platform.system() or "unknown")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Helper:
    def __init__(self, port: int = PORT, upstream: str = UPSTREAM,
                 tokens_path: pathlib.Path | None = None):
        self.port = port
        self.upstream = upstream
        self.tokens_path = tokens_path or TOKENS_PATH
        self.name = addresses.server_name()
        self.code = codes.fresh()
        self._lock = threading.Lock()
        self._fails = 0
        self._paused_until = 0.0
        self._adv = None

    # -- tokens -------------------------------------------------------------
    def _tokens(self) -> dict:
        try:
            data = json.loads(self.tokens_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_tokens(self, data: dict) -> None:
        self.tokens_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.tokens_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)

    def primaries(self) -> list[dict]:
        """Who may use this machine's model: [{id, primary, at}]."""
        return [dict(v, id=k) for k, v in self._tokens().items()]

    def forget(self, token_hash: str) -> None:
        with self._lock:
            data = self._tokens()
            data.pop(token_hash, None)
            self._save_tokens(data)

    def authorize(self, headers) -> bool:
        auth = headers.get("Authorization") or ""
        if not auth.startswith("Bearer "):
            return False
        return _hash(auth[7:].strip()) in self._tokens()

    def claim(self, code: str, primary: str) -> str | None:
        """Issue a token for the code on this screen; None when it is wrong.
        Five wrong codes pause claiming for a minute."""
        with self._lock:
            now = time.time()
            if now < self._paused_until:
                return None
            if not hmac.compare_digest(
                    "".join(ch for ch in (code or "").upper() if ch.isalnum()), self.code):
                self._fails += 1
                if self._fails >= _FAILS_BEFORE_PAUSE:
                    self._paused_until, self._fails = now + _PAUSE_S, 0
                return None
            self._fails = 0
            token = secrets.token_hex(24)
            data = self._tokens()
            data[_hash(token)] = {"primary": (primary or "a primary")[:64], "at": now}
            self._save_tokens(data)
            self.code = codes.fresh()          # a code works once
            return token

    # -- what it says about itself --------------------------------------------
    def info(self) -> dict:
        import requests
        models = {}
        try:
            tags = requests.get(f"{self.upstream}/api/tags", timeout=1.5).json()
            models = {m.get("name", ""): m.get("digest", "") for m in tags.get("models", [])}
        except Exception:
            pass
        return {"gate": GATE_PROTOCOL, "name": self.name, "os": os_name(),
                "models": models, "busy": model_protocol.local_busy()}

    def _extra(self, handler, method: str) -> bool:
        path = handler.path.split("?", 1)[0]
        if method == "GET" and path == "/gate/info":
            handler._send_json(200, self.info())
            return True
        if method == "POST" and path in ("/gate/claim", "/gate/release"):
            length = int(handler.headers.get("Content-Length") or 0)
            try:
                body = json.loads(handler.rfile.read(length) or b"{}") if length else {}
            except ValueError:
                body = {}
            if path == "/gate/claim":
                token = self.claim(str(body.get("code") or ""), str(body.get("primary") or ""))
                if token is None:
                    handler._send_json(403, {"error": "that code is not the one shown on this "
                                                      "computer (or too many tries — wait a minute)"})
                else:
                    logger.info("🤝 %s may now use this computer's model", body.get("primary"))
                    handler._send_json(200, {"token": token, "name": self.name, "os": os_name()})
                return True
            if not self.authorize(handler.headers):
                handler._send_json(401, {"error": "this model helper needs its token"})
                return True
            self.forget(_hash(handler.headers["Authorization"][7:].strip()))
            handler._send_json(200, {"released": True})
            return True
        return False

    # -- running ----------------------------------------------------------------
    def start(self, announce: bool = True) -> str:
        url = ollama_gate.start(self.port, self.upstream, model_protocol.BACKGROUND,
                                host="0.0.0.0", authorize=self.authorize,
                                priority_header=True, extra=self._extra)
        if announce and not os.environ.get("MACALENDAR_NO_DISCOVERY"):
            self._adv = discovery.advertise(self.port, service=discovery.HELPER_SERVICE,
                                            extra={"os": os_name()})
        logger.info("Lending this computer's model on port %d", self.port)
        return url

    def stop(self) -> None:
        if self._adv is not None:
            self._adv.close()
            self._adv = None
        ollama_gate.stop(self.port)
