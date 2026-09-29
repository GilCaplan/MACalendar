"""The server announces itself on the local network (Bonjour / mDNS).

Service ``_macalendar._tcp``; instance name is the machine's own name, so the
phone can list "Gil's MacBook Pro" rather than an address. The TXT record
carries every base URL (``addresses.candidate_urls``, Tailscale first), so the
phone does not have to resolve anything: it tries them in order and keeps the
first that answers — which means a phone that found the Mac at home keeps
reaching it over Tailscale when it leaves.

Started from ``assistant.api.main`` in the process that OWNS the port (the
reloader's watcher, which outlives every reload), never from ``create_app``:
a test that builds the app must not multicast. It re-reads the addresses once
a minute, because a laptop changes Wi-Fi networks under a running server.
"""

from __future__ import annotations

import atexit
import logging
import socket
import threading

from assistant.pairing import addresses

logger = logging.getLogger(__name__)

SERVICE = "_macalendar._tcp.local."
TXT_VERSION = "1"
_REFRESH_S = 60.0


def txt(urls: list[str], name: str) -> dict[str, str]:
    """The TXT record. One DNS-SD string holds at most 255 bytes, so URLs are
    kept whole and dropped from the END (the least preferred) until it fits."""
    kept: list[str] = []
    for u in urls:
        if len("urls=" + ",".join(kept + [u])) > 250:
            break
        kept.append(u)
    return {"v": TXT_VERSION, "name": name[:60], "urls": ",".join(kept)}


class Advertiser:
    """One registration, kept current. ``close()`` withdraws it."""

    def __init__(self, port: int, name: str | None = None):
        from zeroconf import IPVersion, Zeroconf
        self.port = port
        self.name = name or addresses.server_name()
        self._zc = Zeroconf(ip_version=IPVersion.V4Only)
        self._info = None
        self._ips: list[tuple[str, str]] = []
        self._stop = threading.Event()
        self._refresh(first=True)
        threading.Thread(target=self._loop, name="pairing-mdns", daemon=True).start()

    def _build(self, ips):
        from zeroconf import ServiceInfo
        lan = [ip for ip, kind in ips if kind == "lan"]
        urls = addresses.candidate_urls(self.port, ips, ask_cli=False)
        host = socket.gethostname().split(".")[0] or "macalendar"
        return ServiceInfo(
            SERVICE, f"{self.name}.{SERVICE}",
            addresses=[socket.inet_aton(ip) for ip in lan],
            port=self.port, properties=txt(urls, self.name),
            server=f"{host}.local.")

    def _refresh(self, first: bool = False) -> None:
        ips = addresses.interface_ips()
        if not first and ips == self._ips:
            return
        self._ips = ips
        info = self._build(ips)
        if self._info is None:
            self._zc.register_service(info, allow_name_change=True)
        else:
            info.name = self._info.name        # keep a name mDNS may have changed
            self._zc.update_service(info)
        self._info = info
        logger.info("📡 Announced on the local network as %r (%s)",
                    self._info.name.removesuffix("." + SERVICE),
                    info.properties.get(b"urls", b"").decode() or "no addresses")

    def _loop(self) -> None:
        while not self._stop.wait(_REFRESH_S):
            try:
                self._refresh()
            except Exception as exc:           # a network change mid-update
                logger.debug("mDNS refresh failed: %s", exc)

    def close(self) -> None:
        self._stop.set()
        try:
            if self._info is not None:
                self._zc.unregister_service(self._info)
            self._zc.close()
        except Exception:
            pass


def advertise(port: int) -> Advertiser | None:
    """Start announcing; None (logged) if the network or zeroconf says no.
    Never raises: a server that cannot be FOUND can still be reached by QR or
    by typing its address, so this must not stop it starting."""
    try:
        adv = Advertiser(port)
    except Exception as exc:
        logger.warning("Not announcing on the local network (%s) — devices can "
                       "still pair with the QR code.", exc)
        return None
    atexit.register(adv.close)
    return adv
