"""Start and stop what the server needs, and read how it is doing.

Two children: ollama (the model, :11434) and the API (the brain, :8080). Each
is started only when nothing already answers on its port — the launcher, the
Server app and a Terminal may all start pieces of the same stack, and there is
ONE of each per machine (Gil, 2026-09-28). What this process did not start, it
never stops.

No Qt here, so it can be tested and reused without a window.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLLAMA_PORT = 11434

#: A Mac app runs with the bare system PATH (/usr/bin:/bin:…), where neither
#: ollama nor tailscale is found (2026-09-28, the "auto quit" launcher bug).
_EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin")


def widen_path() -> None:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    extra = [p for p in _EXTRA_PATH if p not in parts and os.path.isdir(p)]
    if extra:
        os.environ["PATH"] = os.pathsep.join(parts + extra)


def ollama_path() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama",
                  "/Applications/Ollama.app/Contents/Resources/ollama"]
    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates.append(os.path.join(local, "Programs", "Ollama", "ollama.exe"))
    return next((c for c in candidates if os.path.isfile(c)), None)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _get(url: str, timeout: float = 3.0, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def api_headers() -> dict:
    """The X-API-Key this server expects, when it expects one."""
    from assistant.config import load_config
    key = load_config().api.key
    return {"X-API-Key": key} if key else {}


def model_name() -> str:
    from assistant.config import load_config
    return load_config().ollama.model


def model_ready(name: str | None = None) -> bool | None:
    """Is the assistant's model downloaded? None when ollama is not answering."""
    name = name or model_name()
    try:
        tags = _get(f"http://127.0.0.1:{OLLAMA_PORT}/api/tags")
    except Exception:
        return None
    have = {m.get("name", "") for m in tags.get("models", [])}
    return name in have or (":" not in name and f"{name}:latest" in have)


class Stack:
    """The children this app started, and the log they write to."""

    def __init__(self, port: int = 8080, log_dir: Path | None = None):
        self.port = port
        self.log_dir = log_dir or Path.home() / ".assistant_tools"
        self.started: dict[str, subprocess.Popen] = {}
        self.pull: subprocess.Popen | None = None

    def _log(self, name: str):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        return open(self.log_dir / f"server-{name}.log", "ab")

    def start(self, api: bool = True) -> list[str]:
        """Start whatever is missing. Returns what was started. ``api=False``
        on a model helper: it runs only the model (DEVQA Q70)."""
        widen_path()
        did = []
        exe = ollama_path()
        if exe and not port_open(OLLAMA_PORT) and "ollama" not in self.started:
            self.started["ollama"] = subprocess.Popen(
                [exe, "serve"], stdout=self._log("ollama"), stderr=subprocess.STDOUT)
            did.append("ollama")
        if api and not port_open(self.port) and "api" not in self.started:
            # --reload: editing the assistant restarts it by itself, as the
            # launcher's copy does (CLAUDE.md, "The API reloads itself").
            self.started["api"] = subprocess.Popen(
                [sys.executable, "-m", "assistant.api", "--tailscale",
                 "--port", str(self.port), "--reload"],
                cwd=str(ROOT), stdout=self._log("api"), stderr=subprocess.STDOUT)
            did.append("api")
        return did

    def stop_api(self) -> None:
        """Stop the brain if this app started it (switching to helper)."""
        proc = self.started.pop("api", None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop(self) -> None:
        """Stop only what this app started, API first (it talks to ollama)."""
        for name in ("api", "ollama"):
            proc = self.started.pop(name, None)
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if self.pull and self.pull.poll() is None:
            self.pull.terminate()

    def pull_model(self) -> bool:
        """Download the assistant's model in the background. False if ollama
        is missing or a download is already running."""
        exe = ollama_path()
        if not exe or (self.pull and self.pull.poll() is None):
            return False
        self.pull = subprocess.Popen([exe, "pull", model_name()],
                                     stdout=self._log("model-download"),
                                     stderr=subprocess.STDOUT)
        return True

    def pulling(self) -> bool:
        return bool(self.pull and self.pull.poll() is None)

    def status(self) -> dict:
        """One reading for the menu: is each piece up, where the server can be
        reached, and how many devices have joined."""
        up = port_open(self.port)
        out = {"api": up, "ollama": port_open(OLLAMA_PORT),
               "ollama_installed": ollama_path() is not None,
               "model_ready": None, "urls": [], "devices": None,
               "pulling": self.pulling()}
        if out["ollama"]:
            out["model_ready"] = model_ready()
        if up:
            from assistant.pairing.addresses import candidate_urls
            out["urls"] = candidate_urls(self.port)
            try:
                devs = _get(f"http://127.0.0.1:{self.port}/devices",
                            headers=api_headers()).get("devices", [])
                out["devices"] = sum(1 for d in devs
                                     if not d.get("revoked") and d.get("source") != "test")
            except Exception:
                pass
        return out


def start_pairing(port: int = 8080) -> dict:
    """Ask the running API for a one-time code and the QR link."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/pair/start", data=b"{}",
                                 method="POST",
                                 headers=dict(api_headers(),
                                              **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode() or "{}")
