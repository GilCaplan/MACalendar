"""One-time pairing codes.

A code is issued only to a caller on the server itself (``/pair/start`` is
loopback-only), lives for ``pairing.code_minutes``, and is gone the moment it
is redeemed — a QR photographed over someone's shoulder is worth nothing once
the phone it was shown to has used it.

Held in the API process's memory, deliberately: a restart forgets every
outstanding code, which costs a person one fresh QR and costs an attacker
everything. Eight characters from an alphabet with no look-alikes (no 0/O,
1/I/L), so it can also be read aloud or typed if a camera is not to hand.
"""

from __future__ import annotations

import secrets
import threading
import time

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LENGTH = 8

_lock = threading.Lock()
_codes: dict[str, float] = {}            # code -> expiry (epoch seconds)


def _normal(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def issue(ttl_s: float = 600.0, now: float | None = None) -> str:
    """A fresh code, valid for ``ttl_s`` seconds."""
    now = time.time() if now is None else now
    code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    with _lock:
        for c in [c for c, exp in _codes.items() if exp <= now]:
            del _codes[c]
        _codes[code] = now + ttl_s
    return code


def redeem(code: str, now: float | None = None) -> bool:
    """True once for a live code; False for an unknown, used or expired one."""
    now = time.time() if now is None else now
    with _lock:
        exp = _codes.pop(_normal(code), None)
    return exp is not None and exp > now


def pretty(code: str) -> str:
    """``ABCD-EFGH`` — for reading it off a screen."""
    c = _normal(code)
    return f"{c[:4]}-{c[4:]}" if len(c) == LENGTH else c
