"""'Open at login' — start the server with the computer, on each platform.

    macOS    ~/Library/LaunchAgents/com.macalendar.server.plist
             (opens the MACalendar Server app when it is installed, so the
             process keeps that app's Desktop permission; else runs Python)
    Linux    ~/.config/autostart/macalendar-server.desktop
    Windows  <Startup folder>/MACalendar Server.bat

Off until the person ticks it. ``home`` is a parameter so a test writes into
a scratch directory, never the real one.
"""

from __future__ import annotations

import os
import platform
import plistlib
import sys
from pathlib import Path

from assistant.host.supervisor import ROOT

LABEL = "com.macalendar.server"


def _mac_app() -> Path:
    """The Server app in the folder the installer put the apps in (Q71)."""
    from assistant.host import role
    return role.apps_dir() / "MACalendar Server.app"


def _file(home: Path, system: str) -> Path:
    if system == "Darwin":
        return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / \
            "Startup" / "MACalendar Server.bat"
    return home / ".config" / "autostart" / "macalendar-server.desktop"


def is_enabled(home: Path | None = None, system: str | None = None) -> bool:
    return _file(home or Path.home(), system or platform.system()).exists()


def enable(home: Path | None = None, system: str | None = None,
           app: Path | None = None) -> Path:
    home, system = home or Path.home(), system or platform.system()
    app = app or _mac_app()
    path = _file(home, system)
    path.parent.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    if system == "Darwin":
        args = (["/usr/bin/open", "-a", str(app)] if app.exists()
                else [py, "-m", "assistant.host"])
        path.write_bytes(plistlib.dumps({
            "Label": LABEL, "ProgramArguments": args, "RunAtLoad": True,
            "WorkingDirectory": str(ROOT)}))
    elif system == "Windows":
        pyw = Path(py).with_name("pythonw.exe")
        runner = pyw if pyw.exists() else Path(py)
        path.write_text(f'@echo off\r\ncd /d "{ROOT}"\r\nstart "" "{runner}" -m assistant.host\r\n')
    else:
        path.write_text("[Desktop Entry]\nType=Application\nName=MACalendar Server\n"
                        f"Exec={py} -m assistant.host\nPath={ROOT}\n"
                        "X-GNOME-Autostart-enabled=true\n")
    return path


def disable(home: Path | None = None, system: str | None = None) -> None:
    path = _file(home or Path.home(), system or platform.system())
    if path.exists():
        path.unlink()
