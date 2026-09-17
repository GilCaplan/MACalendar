"""Finding Jude, starting Jude, and making its LLM calls ours.

Everything here is deliberately defensive: Jude is an OPTIONAL neighbour. A
missing checkout, a half-installed one, a server that will not start — each is
a normal state that must produce a sentence a person can act on, never a
traceback and never a surface that silently does nothing.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

# The repo Jude lives in, quoted in every "it isn't here" message so the answer
# to "what do I do about it" is in the message rather than in a doc.
JUDE_REPO = "https://github.com/GilCaplan/JudeTheJudaicChatBot"

# How long to wait for `uvicorn` to answer after we start it. Jude loads a
# ChromaDB collection and warms an embedding model on the way up, which on a
# cold page cache is tens of seconds — and the alternative to waiting is
# telling the user it failed while it is still starting.
START_TIMEOUT_SEC = 90

_proc: "subprocess.Popen | None" = None
_lock = threading.Lock()


class JudeUnavailable(RuntimeError):
    """Jude cannot serve this request, and the message says why."""


# ---------------------------------------------------------------------------
# Where it is
# ---------------------------------------------------------------------------

def _repo_root() -> str:
    # assistant/jude/bridge.py → assistant/jude → assistant → the repo
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def checkout_path(cfg) -> "str | None":
    """The Jude checkout's absolute path, or None if there isn't one.

    `MACALENDAR_JUDE_PATH` wins, then `config.jude.path` (relative paths are
    relative to THIS repository, not the working directory — the assistant is
    launched from Finder, where the working directory is not something to
    depend on).

    A directory only counts when it has `backend/main.py` in it: pointing at
    the wrong folder should say "that isn't Jude", not fail later with an
    import error from inside uvicorn.
    """
    raw = os.environ.get("MACALENDAR_JUDE_PATH") or getattr(cfg, "path", "")
    if not raw:
        return None
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(_repo_root(), path))
    return path if os.path.isfile(os.path.join(path, "backend", "main.py")) else None


# ---------------------------------------------------------------------------
# The protocol — what makes Jude's LLM calls this project's LLM calls
# ---------------------------------------------------------------------------

def environment(cfg, ollama_cfg) -> dict:
    """The environment Jude's server is started with.

    Jude resolves a provider per role from env vars (`backend/llm.py`), with a
    cloud cascade — Gemini, then LLMod, then Ollama — as the default. That
    default is wrong here in a way that matters: this project does not touch
    the internet, `tests/unit/test_offline.py` enforces it, and a Judaic study
    question is not a thing to hand to someone else's server by accident.

    So every role is pinned to local Ollama, on `ollama.model` unless
    `jude.model` overrides it, and the keys that would build a cascade are
    blanked in the child's environment — a `.env` sitting in the Jude checkout
    cannot re-enable them, because `_get_fallback_chain` reads the explicit
    per-role provider first.

    `jude.allow_cloud: true` hands all of that back: Jude is then started with
    the environment it would have had on its own, `.env` and all. That is a
    deliberate, named choice, and the traffic is Jude's rather than the
    assistant's.
    """
    env = dict(os.environ)
    if getattr(cfg, "allow_cloud", False):
        return env

    model = (getattr(cfg, "model", "") or "").strip() or ollama_cfg.model
    for role in ("ROUTER", "FILTER", "SUMMARY", "SYNTH", "TOOLS"):
        env[f"{role}_PROVIDER"] = "ollama"
        env[f"{role}_MODEL"] = model
    # Belt and braces: even with the per-role pin above, an empty key is one
    # fewer way for a stray .env to surprise someone reading `ollama ps`.
    for key in ("GEMINI_API_KEY", "LLMOD_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"):
        env[key] = ""
    env["LLM_MODEL"] = model
    # Jude embeds through Ollama regardless of provider; point it at the same
    # instance the assistant uses rather than assuming the default port.
    env["OLLAMA_HOST"] = ollama_cfg.base_url
    return env


# ---------------------------------------------------------------------------
# Is it up?
# ---------------------------------------------------------------------------

def is_listening(port: int, host: str = "127.0.0.1") -> bool:
    """Something is accepting connections on Jude's port.

    A socket probe rather than an HTTP GET: this is called from the status
    endpoint and from a UI poll, and it must be cheap and never block.
    """
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def base_url(cfg) -> str:
    return f"http://127.0.0.1:{int(getattr(cfg, 'port', 8000) or 8000)}"


# ---------------------------------------------------------------------------
# Starting it
# ---------------------------------------------------------------------------

def ensure_running(cfg, ollama_cfg) -> str:
    """Make sure Jude is answering, and return its base URL.

    Raises `JudeUnavailable` with a sentence worth showing to a person:
    disabled, not installed, or it would not start.
    """
    if not getattr(cfg, "enabled", False):
        raise JudeUnavailable(
            "Jude is switched off. Set jude.enabled: true in config.yaml once "
            f"you have a checkout of {JUDE_REPO}.")

    port = int(getattr(cfg, "port", 8000) or 8000)
    if is_listening(port):
        return base_url(cfg)

    path = checkout_path(cfg)
    if path is None:
        raise JudeUnavailable(
            "I can't find Jude. It is a separate repository — clone it next to "
            f"this one ({JUDE_REPO}) and point jude.path at it, or set "
            "MACALENDAR_JUDE_PATH.")

    if not getattr(cfg, "autostart", True):
        raise JudeUnavailable(
            f"Jude isn't running on port {port}, and jude.autostart is off — "
            f"start it yourself with `python run.py --web-only` in {path}.")

    with _lock:
        # Another thread may have started it while we waited for the lock.
        if is_listening(port):
            return base_url(cfg)
        _spawn(cfg, ollama_cfg, path, port)

    deadline = time.monotonic() + START_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if is_listening(port):
            return base_url(cfg)
        if _proc is not None and _proc.poll() is not None:
            raise JudeUnavailable(
                f"Jude's server exited while starting (code {_proc.returncode}). "
                f"Its log is {os.path.join(path, 'server.log')} — the usual cause "
                "is a missing chroma_db/ index; see that repo's README.")
        time.sleep(0.4)
    raise JudeUnavailable(
        f"Jude didn't answer within {START_TIMEOUT_SEC}s. It loads a large "
        f"index on the way up; try again, or check {os.path.join(path, 'server.log')}.")


def _spawn(cfg, ollama_cfg, path: str, port: int) -> None:
    """Start `uvicorn backend.main:app` inside the Jude checkout.

    Its OWN interpreter if it has a venv — Jude needs chromadb, fastapi and
    ollama, which this project does not depend on and must not start depending
    on. Falling back to ours when it has no venv is a convenience for a shared
    environment, and the failure (an ImportError in server.log) names itself.
    """
    global _proc
    import sys

    venv_python = os.path.join(path, ".venv", "bin", "python")
    python = venv_python if os.path.isfile(venv_python) else sys.executable
    cmd = [python, "-m", "uvicorn", "backend.main:app",
           "--host", "127.0.0.1", "--port", str(port)]
    log_path = os.path.join(path, "server.log")
    logger.info("📖 Starting Jude: %s (cwd=%s, log=%s)", " ".join(cmd), path, log_path)
    try:
        log = open(log_path, "a", buffering=1)
    except OSError:
        log = subprocess.DEVNULL
    _proc = subprocess.Popen(
        cmd, cwd=path, stdout=log, stderr=log,
        env=environment(cfg, ollama_cfg),
        # Bound to 127.0.0.1 on purpose: the phone reaches Jude through this
        # project's API on 8080, so Jude's own port never needs to leave the
        # machine — and a tailnet-wide FastAPI with no auth would be a hole.
    )


def stop() -> None:
    """Stop a server this process started. A Jude that was already running
    when we found it is somebody else's, and is left alone."""
    global _proc
    with _lock:
        if _proc is None:
            return
        if _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proc.kill()
        _proc = None


# ---------------------------------------------------------------------------
# What the surfaces ask
# ---------------------------------------------------------------------------

def status(cfg, ollama_cfg) -> dict:
    """Everything a client needs to decide what to draw, and never an error.

    `reason` is empty when `ready` is true, and otherwise is the sentence to
    put on screen.
    """
    enabled = bool(getattr(cfg, "enabled", False))
    port = int(getattr(cfg, "port", 8000) or 8000)
    path = checkout_path(cfg)
    running = is_listening(port) if enabled else False
    model = (getattr(cfg, "model", "") or "").strip() or ollama_cfg.model

    reason = ""
    if not enabled:
        reason = ("Jude is switched off — set jude.enabled: true in config.yaml "
                  f"once you have a checkout of {JUDE_REPO}.")
    elif path is None:
        reason = ("Jude isn't installed here. It is a separate repository: clone "
                  f"{JUDE_REPO} beside this one and point jude.path at it.")
    elif not running:
        reason = ("Jude isn't running yet — it starts on the first question and "
                  "takes a moment to load its index."
                  if getattr(cfg, "autostart", True) else
                  f"Jude isn't running, and autostart is off. Start it in {path}.")

    return {
        "enabled": enabled,
        "installed": path is not None,
        "running": running,
        "ready": enabled and path is not None,
        "path": path or "",
        "port": port,
        "model": model,
        "cloud": bool(getattr(cfg, "allow_cloud", False)),
        "repo": JUDE_REPO,
        "reason": reason,
    }
