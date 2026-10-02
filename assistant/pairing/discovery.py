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
#: A model helper (DEVQA Q70) announces itself under its own type, so a phone
#: never lists a machine that only lends its model.
HELPER_SERVICE = "_macalendar-llm._tcp.local."   # a service name is <= 15 bytes
TXT_VERSION = "1"
_REFRESH_S = 60.0


def txt(urls: list[str], name: str, extra: dict | None = None) -> dict[str, str]:
    """The TXT record. One DNS-SD string holds at most 255 bytes, so URLs are
    kept whole and dropped from the END (the least preferred) until it fits."""
    kept: list[str] = []
    for u in urls:
        if len("urls=" + ",".join(kept + [u])) > 250:
            break
        kept.append(u)
    return dict({"v": TXT_VERSION, "name": name[:60], "urls": ",".join(kept)}, **(extra or {}))


class Advertiser:
    """One registration, kept current. ``close()`` withdraws it."""

    def __init__(self, port: int, name: str | None = None, service: str = SERVICE,
                 extra: dict | None = None):
        from zeroconf import IPVersion, Zeroconf
        self.port = port
        self.service = service
        self.extra = extra or {}
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
            self.service, f"{self.name}.{self.service}",
            addresses=[socket.inet_aton(ip) for ip in lan],
            port=self.port, properties=txt(urls, self.name, self.extra),
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
        logger.info("Announced on the local network as %r (%s)",
                    self._info.name.removesuffix("." + self.service),
                    info.properties.get(b"urls", b"").decode() or "no addresses")

    def _loop(self) -> None:
        while not self._stop.wait(_REFRESH_S):
            try:
                self._refresh()
            except Exception as exc:           # a network change mid-update
                logger.debug("mDNS refresh failed: %s", exc)

    def close(self) -> None:
        """Withdraw the announcement. Idempotent: ``stop()`` and the atexit
        hook both call it, and a second unregister on a closed Zeroconf
        leaves an un-awaited coroutine behind."""
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            if self._info is not None:
                self._zc.unregister_service(self._info)
            self._zc.close()
        except Exception:
            pass


def advertise(port: int, service: str = SERVICE, extra: dict | None = None) -> Advertiser | None:
    """Start announcing; None (logged) if the network or zeroconf says no.
    Never raises: a server that cannot be FOUND can still be reached by QR or
    by typing its address, so this must not stop it starting."""
    try:
        adv = Advertiser(port, service=service, extra=extra)
    except Exception as exc:
        logger.warning("Not announcing on the local network (%s) — it can still "
                       "be reached by its address.", exc)
        return None
    atexit.register(adv.close)
    return adv


def browse(service: str, timeout: float = 2.0) -> list[dict]:
    """``[{name, urls, os, …TXT}]`` announced under ``service`` right now.
    A short, one-off look (the primary's Servers page asks when it opens)."""
    import time as _t
    from zeroconf import IPVersion, ServiceBrowser, Zeroconf
    found: dict[str, dict] = {}
    zc = Zeroconf(ip_version=IPVersion.V4Only)

    class _L:
        def add_service(self, z, type_, name):
            info = z.get_service_info(type_, name, timeout=1500)
            if info is None:
                return
            props = {k.decode(): (v or b"").decode() for k, v in info.properties.items()}
            urls = [u for u in props.get("urls", "").split(",") if u]
            if urls:
                found[name] = dict(props, name=props.get("name") or name.split(".")[0],
                                   urls=urls)

        update_service = add_service

        def remove_service(self, z, type_, name):
            found.pop(name, None)

    ServiceBrowser(zc, service, _L())
    _t.sleep(timeout)
    zc.close()
    return list(found.values())
