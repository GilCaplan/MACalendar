"""Pairing routes — HTTP only.

    POST /pair/start      (the server's own screen only) → a code, the
                          addresses, and the macalendar://pair link to show
    POST /devices/pair    {code, source, label} → {device_id, token, label,
                          server}: enrolment, with the one-time code as proof
"""

from __future__ import annotations

import logging

from flask import jsonify, request

from assistant.pairing import addresses, codes, link

logger = logging.getLogger(__name__)

LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})


def is_local() -> bool:
    """Is this request from the server's own machine?"""
    return (request.remote_addr or "") in LOOPBACK


def _err(msg: str, code: int):
    return jsonify({"error": msg, "code": code}), code


def register(app) -> None:
    @app.post("/pair/start")
    def pair_start():
        """A fresh one-time code and the link a QR code shows.

        Loopback only: whoever holds a code can enrol a device, so a code is
        handed to nobody who is not already on this machine."""
        if not is_local():
            return _err("a pairing code is issued only on the server itself", 403)
        from assistant.config import load_config
        cfg = load_config()
        minutes = max(1, int(cfg.pairing.code_minutes))
        port = int(request.environ.get("SERVER_PORT") or 8080)
        code = codes.issue(minutes * 60)
        urls = addresses.candidate_urls(port)
        name = addresses.server_name()
        return jsonify({
            "code": code, "pretty": codes.pretty(code), "expires_in": minutes * 60,
            "urls": urls, "name": name,
            "link": link.pair_link(urls, code, name, cfg.api.key or ""),
        })

    @app.post("/devices/pair")
    def devices_pair():
        """Enrol a device that shows a live one-time code."""
        from assistant import model_protocol as _mp
        body = request.get_json(silent=True) or {}
        src = (body.get("source") or "").strip().lower()
        if src not in ("ios", "mac"):
            return _err("source must be ios|mac", 400)
        if not codes.redeem(str(body.get("code") or "")):
            return _err("that pairing code has expired or was already used — "
                        "show a new one on the server", 403)
        got = _mp.enroll(src, (body.get("label") or "").strip())
        if not got.get("token"):
            return _err("device secret unavailable", 503)
        logger.info("Paired %s device %s (%s)", src, got["device_id"], got["label"])
        return jsonify(dict(got, server=addresses.server_name()))
