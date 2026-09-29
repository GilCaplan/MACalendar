"""Where this server can be reached — worked out, never typed.

Read off the machine's own network interfaces (``ifaddr``: no packet is sent,
no lookup is made). Tailscale's addresses sit in 100.64.0.0/10, so they are
told apart from the Wi-Fi ones by address alone, and they come FIRST: a
Tailscale address reaches the Mac from anywhere, a Wi-Fi one only at home.
The ``tailscale`` CLI is a fallback for a setup whose interface is not visible.
"""

from __future__ import annotations

import ipaddress
import platform
import socket
import subprocess

_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")

#: Where the `tailscale` CLI lives when PATH does not say. The MACalendar
#: Server app runs through `do shell script`, whose PATH is the bare
#: /usr/bin:/bin:… — so "Tailscale IP not found" was logged from the app while
#: the same Mac, started from Terminal, found it (2026-09-28).
_TAILSCALE_CANDIDATES = ("tailscale", "/opt/homebrew/bin/tailscale",
                         "/usr/local/bin/tailscale",
                         "/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def tailscale_ip() -> str | None:
    """The Tailscale IPv4 address from the CLI, or None if it isn't running."""
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


def interface_ips() -> list[tuple[str, str]]:
    """``(ip, kind)`` for every usable IPv4 address, kind ``tailscale`` or ``lan``.

    Loopback and link-local (169.254, a cable with no DHCP) are left out:
    nothing else can reach them.
    """
    try:
        import ifaddr
    except ImportError:                      # the Python-only fallback
        return []
    out: list[tuple[str, str]] = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if not isinstance(ip.ip, str):   # IPv6 comes as a tuple
                continue
            try:
                a = ipaddress.ip_address(ip.ip)
            except ValueError:
                continue
            if a.is_loopback or a.is_link_local:
                continue
            if a in _TAILSCALE_NET:
                out.append((ip.ip, "tailscale"))
            elif a.is_private:
                out.append((ip.ip, "lan"))
    return out


def candidate_urls(port: int, ips: list[tuple[str, str]] | None = None,
                   ask_cli: bool = True) -> list[str]:
    """Every base URL a device could try, best first: Tailscale, then Wi-Fi."""
    ips = interface_ips() if ips is None else ips
    ts = [ip for ip, kind in ips if kind == "tailscale"]
    if not ts and ask_cli:
        found = tailscale_ip()
        ts = [found] if found else []
    lan = [ip for ip, kind in ips if kind == "lan"]
    out: list[str] = []
    for ip in ts + lan:
        url = f"http://{ip}:{port}"
        if url not in out:
            out.append(url)
    return out


def server_name() -> str:
    """The name a person knows this machine by ("Gil's MacBook Pro").

    macOS keeps it as the ComputerName; elsewhere the host name is the best
    there is. Never empty — it is what the phone lists and what the QR says.
    """
    if platform.system() == "Darwin":
        try:
            got = subprocess.run(["scutil", "--get", "ComputerName"],
                                 capture_output=True, text=True, timeout=2)
            if got.returncode == 0 and got.stdout.strip():
                return got.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    host = socket.gethostname() or platform.node() or "MACalendar server"
    return host.removesuffix(".local")
