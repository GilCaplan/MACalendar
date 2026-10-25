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


def configured_port() -> int:
    """config.yaml's ``api.port`` — the port every client already reads (the
    calendar, the HUD, Jude's tab), so the Server and the API read it too."""
    try:
        from assistant.config import load_config
        return int(load_config().api.port)
    except Exception:
        return 8080


def listener_pids(port: int) -> list[int]:
    """The processes listening on ``port`` — more than one under --reload,
    where the watcher hands its socket to the child it restarts."""
    if platform.system() == "Windows":
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True).stdout
        return sorted({int(cols[-1]) for cols in (ln.split() for ln in out.splitlines())
                       if len(cols) >= 5 and cols[1].endswith(f":{port}")
                       and cols[3] == "LISTENING"})
    try:
        out = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True).stdout
    except FileNotFoundError:
        return []
    return sorted({int(p) for p in out.split() if p.isdigit()})


def systemd_unit(pid: int, proc: Path = Path("/proc")) -> str | None:
    """The systemd USER service ``pid`` runs under, if any. Such a service
    restarts the API the moment anyone else stops it (Restart=always), so a
    restart has to go through systemctl or it races the old code back in
    (2026-10-24: the update's first restart came back on the old version)."""
    try:
        lines = (proc / str(pid) / "cgroup").read_text().splitlines()
    except OSError:
        return None
    for ln in lines:
        parts = ln.rsplit(":", 1)[-1].split("/")
        if any(p.startswith("user@") for p in parts) and parts[-1].endswith(".service") \
                and not parts[-1].startswith("user@"):
            return parts[-1]
    return None


def pinned_port(unit: str) -> int | None:
    """The ``--port`` a service's command line fixes, if it fixes one."""
    out = subprocess.run(["systemctl", "--user", "show", "-p", "ExecStart", "--value", unit],
                         capture_output=True, text=True).stdout.split()
    for i, word in enumerate(out):
        if word == "--port" and i + 1 < len(out) and out[i + 1].isdigit():
            return int(out[i + 1])
        if word.startswith("--port="):
            return int(word.split("=", 1)[1])
    return None


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

    def __init__(self, port: int | None = None, log_dir: Path | None = None):
        self.port = port if port is not None else configured_port()
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

    def restart_api(self, port: int | None = None) -> str:
        """Restart the brain, on ``port`` if given — asked for by a click on
        the Server's icon, so unlike ``stop`` it restarts an API this app did
        NOT start too: the one a systemd service runs, or a Terminal's.
        Returns how; raises RuntimeError with a sentence for the person."""
        new = port or self.port
        pids = listener_pids(self.port)
        unit = next((u for u in map(systemd_unit, pids) if u), None)
        if unit:
            pinned = pinned_port(unit)
            if pinned is not None and pinned != new:
                raise RuntimeError(
                    f"The brain runs as the service {unit}, which fixes --port {pinned}. "
                    f"Remove --port from its ExecStart (it then reads config.yaml) "
                    f"to move it to {new}.")
            done = subprocess.run(["systemctl", "--user", "restart", unit],
                                  capture_output=True, text=True)
            if done.returncode != 0:
                raise RuntimeError(f"systemctl couldn't restart {unit}: "
                                   f"{(done.stderr or done.stdout).strip()}")
            self.port = new
            return f"restarted {unit}"
        self.stop_api()
        import signal as _signal
        for pid in listener_pids(self.port):    # a Terminal's, or a reloader's child
            try:
                os.kill(pid, _signal.SIGTERM)
            except OSError:
                pass
        import time
        deadline = time.monotonic() + 10
        while port_open(self.port) and time.monotonic() < deadline:
            time.sleep(0.25)
        if port_open(self.port):
            raise RuntimeError(f"The brain on port {self.port} didn't stop.")
        self.port = new
        self.start(api=True)
        return "restarted"

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
