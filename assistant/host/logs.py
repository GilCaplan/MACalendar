"""The server's log: where it is, the last lines of it, and a terminal on it.

The API writes ``api.log`` itself (``assistant.api.main``), so the log exists
whoever started it — the menu-bar app, the calendar's launcher or a Terminal.
``MACALENDAR_LOGS`` redirects the folder; ``tests/conftest.py`` does.
"""

from __future__ import annotations

import os
import pathlib
import platform
import shlex
import subprocess
from collections import deque

LOG_DIR = pathlib.Path(os.environ.get("MACALENDAR_LOGS")
                       or (pathlib.Path.home() / ".assistant_tools" / "logs"))
API_LOG = "api.log"
HOST_LOG = "host.log"          # the menu-bar app itself (and a helper's gate)


def path(name: str = API_LOG) -> pathlib.Path:
    return LOG_DIR / name


def tail(name: str = API_LOG, lines: int = 200) -> list[str]:
    """The last ``lines`` lines, or [] when there is no log yet."""
    lines = max(1, min(int(lines), 2000))
    try:
        with open(path(name), "r", errors="replace") as f:
            return [l.rstrip("\n") for l in deque(f, maxlen=lines)]
    except OSError:
        return []


def install_file_handler(name: str = API_LOG) -> None:
    """Also write this process's log to ``LOG_DIR/name`` (2 MB × 3)."""
    import logging
    from logging.handlers import RotatingFileHandler
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(path(name), maxBytes=2_000_000, backupCount=3,
                            encoding="utf-8")
    h.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"))
    logging.getLogger().addHandler(h)


def terminal_command(log: pathlib.Path, system: str | None = None) -> list[str]:
    """The command that opens a terminal following ``log`` on this OS."""
    system = system or platform.system()
    if system == "Darwin":
        script = f"tail -n 200 -f {shlex.quote(str(log))}"
        return ["osascript", "-e", 'tell application "Terminal" to activate',
                "-e", f'tell application "Terminal" to do script "{script}"']
    if system == "Windows":
        return ["cmd", "/c", "start", "powershell", "-NoExit", "-Command",
                f"Get-Content -Path '{log}' -Tail 200 -Wait"]
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        if subprocess.run(["which", term], capture_output=True).returncode == 0:
            sep = ["--"] if term == "gnome-terminal" else ["-e"]
            return [term, *sep, "tail", "-n", "200", "-f", str(log)]
    return ["xterm", "-e", "tail", "-n", "200", "-f", str(log)]


def open_terminal(name: str = API_LOG) -> None:
    """Open a real terminal following the log (on the server's own screen)."""
    log = path(name)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.touch(exist_ok=True)
    subprocess.Popen(terminal_command(log))
