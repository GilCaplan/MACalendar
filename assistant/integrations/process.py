"""Starting somebody else's server, and knowing when it is actually up.

One supervisor per integration, keyed by name. Everything here is about the
three ways starting a child process lies to you:

- **"It started" is not "it is answering."** `Popen` returns immediately; a
  FastAPI app loading a multi-gigabyte index answers ninety seconds later. So
  we wait on the PORT, not on the spawn.
- **"It isn't answering yet" is not "it failed."** While waiting we watch for
  the process DYING, so a crash is reported as a crash (with its log path) and
  a slow start is reported as a slow start. Saying "it failed" about something
  that is still loading is the bug this exists to prevent.
- **"It is listening" is not "we started it."** A server that was already up
  when we found it belongs to someone else — a developer running it by hand —
  and `stop()` leaves it alone rather than killing their session.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time

logger = logging.getLogger(__name__)

#: name -> Popen, for the children THIS process started.
_children: "dict[str, subprocess.Popen]" = {}
_locks: "dict[str, threading.Lock]" = {}
_locks_guard = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def is_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    """Something is accepting connections there.

    A socket probe rather than an HTTP GET: this is called from status
    endpoints and from UI polls, so it must be cheap and must never block.
    """
    if not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def interpreter_for(root: str) -> str:
    """The Python that should run this checkout.

    ITS OWN venv when it has one. An integration has its own dependencies —
    Jude needs chromadb, fastapi and the ollama client, none of which this
    project depends on or should start depending on. Falling back to ours is a
    convenience for a shared environment, and when that is wrong the failure
    is an ImportError in the child's log, which names itself.
    """
    venv = os.path.join(root, ".venv", "bin", "python")
    return venv if os.path.isfile(venv) else sys.executable


def ensure_running(integration) -> str:
    """Make sure the integration is answering, and return its base URL.

    Raises `IntegrationUnavailable` with a sentence worth showing to a person.
    """
    from assistant.integrations.base import IntegrationUnavailable

    label, name = integration.label, integration.name
    if not integration.enabled():
        raise IntegrationUnavailable(
            f"{label} is switched off. Set {name}.enabled: true in config.yaml "
            f"once you have a checkout of {integration.repo}.")

    port = integration.port()
    if is_listening(port):
        return base_url(port)

    root = integration.root()
    if root is None:
        raise IntegrationUnavailable(
            f"I can't find {label}. It is a separate repository — clone it "
            f"({integration.repo}) and point {name}.path at it, or set "
            f"{integration.env_path_var}.")

    if not integration.autostart():
        raise IntegrationUnavailable(
            f"{label} isn't running on port {port}, and {name}.autostart is "
            f"off — start it yourself in {root}.")

    with _lock_for(name):
        # Another thread may have started it while we queued for the lock.
        if is_listening(port):
            return base_url(port)
        _spawn(integration, root, port)

    log_path = os.path.join(root, "server.log")
    deadline = time.monotonic() + integration.start_timeout_s
    while time.monotonic() < deadline:
        if is_listening(port):
            return base_url(port)
        child = _children.get(name)
        if child is not None and child.poll() is not None:
            raise IntegrationUnavailable(
                f"{label}'s server exited while starting (code "
                f"{child.returncode}). Its log is {log_path}.")
        time.sleep(0.4)
    raise IntegrationUnavailable(
        f"{label} didn't answer within {integration.start_timeout_s}s. "
        f"Try again, or check {log_path}.")


def _spawn(integration, root: str, port: int) -> None:
    python = interpreter_for(root)
    cmd = integration.command(python)
    log_path = os.path.join(root, "server.log")
    logger.info("Starting %s: %s (cwd=%s, log=%s)",
                integration.label, " ".join(cmd), root, log_path)
    try:
        log = open(log_path, "a", buffering=1)
    except OSError:
        log = subprocess.DEVNULL
    _children[integration.name] = subprocess.Popen(
        cmd, cwd=root, stdout=log, stderr=log,
        env=integration.environment(),
        # Bound to loopback by the command itself, on purpose: clients reach it
        # through THIS project's API, so its own port never has to leave the
        # machine — and a tailnet-wide server with no auth would be a hole.
    )


def stop(name: str) -> None:
    """Stop a child THIS process started; leave anyone else's alone."""
    with _lock_for(name):
        child = _children.pop(name, None)
        if child is None or child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()


def stop_all() -> None:
    for name in list(_children):
        stop(name)


def base_url(port: int, host: str = "127.0.0.1") -> str:
    return f"http://{host}:{port}"
