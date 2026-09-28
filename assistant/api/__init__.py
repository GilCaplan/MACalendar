"""Entry point for the iPhone API server.

Usage:
    python -m assistant.api                # binds 127.0.0.1:8080 (local only)
    python -m assistant.api --lan          # binds 0.0.0.0:8080  (same Wi-Fi)
    python -m assistant.api --tailscale    # binds 0.0.0.0:8080 + prints Tailscale IP
    python -m assistant.api --port 8080
    python -m assistant.api --tailscale --reload   # restarts itself on source changes
"""

import argparse
import logging
import os
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
# Colour the log by event kind when a human is watching a terminal (no-op into
# a file or under NO_COLOR). See DOCUMENTATION/LOGGING.md for the legend.
from assistant.api.log_color import install as _install_log_colour  # noqa: E402
_install_log_colour()

logger = logging.getLogger(__name__)


#: Where the `tailscale` CLI lives when PATH does not say. The MACalendar
#: Server app runs this through `do shell script`, whose PATH is the bare
#: /usr/bin:/bin:… — so "Tailscale IP not found" was logged from the app while
#: the same Mac, started from Terminal, found it (2026-09-28).
_TAILSCALE_CANDIDATES = ("tailscale", "/opt/homebrew/bin/tailscale",
                         "/usr/local/bin/tailscale",
                         "/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def _tailscale_ip() -> str | None:
    """Return the Tailscale IPv4 address, or None if Tailscale isn't running."""
    for exe in _TAILSCALE_CANDIDATES:
        try:
            result = subprocess.run([exe, "ip", "-4"],
                                    capture_output=True, text=True, timeout=3)
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            continue
        ip = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if ip and not result.returncode:
            return ip
    return None


def _already_running(port: int) -> "str | None":
    """'ours' if this API already answers on `port`, 'other' if something else
    holds it, None if it is free.

    Clicking the Server app while the server runs used to load a whole second
    copy (models and all, several seconds) only for it to die on "Address
    already in use". Only one may run on this Mac; now the second says so and
    leaves (Gil, 2026-09-28: "should only open one instance on this device")."""
    import json
    import socket
    import urllib.request
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            body = json.loads(r.read().decode() or "{}")
        return "ours" if isinstance(body, dict) and "status" in body and "db" in body else "other"
    except Exception:
        return "other"


def main() -> None:
    parser = argparse.ArgumentParser(description="MACalendar iPhone API server")
    parser.add_argument("--lan", action="store_true", help="Bind to 0.0.0.0 (same Wi-Fi access)")
    parser.add_argument("--tailscale", action="store_true", help="Bind to 0.0.0.0 and print Tailscale IP")
    parser.add_argument("--host", default=None, help="Override bind host explicitly")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--debug", action="store_true",
                        help="Werkzeug debugger AND reloader. Loopback binds only — "
                             "the debugger is a remote shell to anyone who can reach it.")
    parser.add_argument("--reload", action="store_true",
                        help="Restart the server when a source file changes. Safe to use "
                             "with --tailscale: this is the reloader without the debugger.")
    args = parser.parse_args()

    host = args.host or ("0.0.0.0" if (args.lan or args.tailscale) else "127.0.0.1")

    # The Werkzeug debugger executes arbitrary Python from the browser. On
    # 0.0.0.0 that is a shell for anyone on the tailnet, so it is refused
    # rather than warned about. --reload gives the useful half.
    if args.debug and host != "127.0.0.1":
        parser.error(
            f"--debug binds the Werkzeug debugger to {host}, which is a remote shell "
            "for anything that can reach this port. Use --reload for auto-restart, "
            "or --debug without --lan/--tailscale."
        )

    if args.tailscale:
        ts_ip = _tailscale_ip()
        if ts_ip:
            logger.info("Tailscale IP detected: %s", ts_ip)
            logger.info("Set iPhone server URL to: http://%s:%d", ts_ip, args.port)
        else:
            logger.warning(
                "Tailscale IP not found — is Tailscale installed and running? "
                "(brew install tailscale)"
            )

    # One server per Mac. Checked only in the FIRST process: the reloader's own
    # child (WERKZEUG_RUN_MAIN) is the server restarting, and must not find its
    # predecessor's port and quit.
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        running = _already_running(args.port)
        if running == "ours":
            logger.info("MACalendar API is already running on port %d — not starting a "
                        "second one.", args.port)
            raise SystemExit(0)
        if running == "other":
            logger.error("Port %d is held by another program; the MACalendar API cannot "
                         "start there (use --port).", args.port)
            raise SystemExit(1)

    reload = args.reload or args.debug
    if reload:
        # Tells create_app that a process without WERKZEUG_RUN_MAIN is the
        # watcher, not the server, and should skip loading the models.
        os.environ["MACALENDAR_RELOADING"] = "1"

    from assistant.api.server import create_app
    app = create_app()

    logger.info("Starting MACalendar API on http://%s:%d%s",
                host, args.port, "  (auto-reloading on source changes)" if reload else "")
    if reload:
        logger.info(
            "Editing anything under assistant/ restarts this server. A command "
            "already in flight when that happens is lost — its background "
            "self-check thread goes with the process."
        )
    # The reloader watches everything importable under the project, so editing
    # a test or a script restarted the server — and each restart reloads spaCy,
    # the date recogniser and Whisper, which is several seconds and a network
    # round trip for a file the server never imports. Only assistant/ can change
    # how it behaves, so only assistant/ should be able to restart it.
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # assistant/
    project = os.path.dirname(here)
    exclude = [
        os.path.join(project, "tests", "*"),
        os.path.join(project, "scripts", "*"),
        os.path.join(project, "DOCUMENTATION", "*"),
        os.path.join(project, "MACalendar-iOS", "*"),
        os.path.join(project, ".venv", "*"),
        os.path.join(project, ".git", "*"),
    ]

    app.run(host=host, port=args.port, debug=args.debug, use_reloader=reload,
            exclude_patterns=exclude if reload else None)


if __name__ == "__main__":
    main()
