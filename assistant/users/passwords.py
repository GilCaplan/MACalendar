"""Password hashing — stdlib only, offline, never reversible.

Gil chose (2026-09-28) hashed passwords the admin RESETS, over passwords the
admin can read back: a readable password is one a copy of `~/.assistant_tools`
hands to anyone, and people reuse passwords. The admin sets a new one when
needed and is shown it once.

scrypt (RFC 7914) at n=2**14, r=8, p=1: ~16 MB and a few tens of ms per
check — slow enough that a stolen `users.json` is expensive to brute-force,
fast enough that a login does not notice.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

N, R, P, DKLEN = 2 ** 14, 8, 1, 32
MIN_LENGTH = 8
#: No 0/O, 1/l/I: a generated password is read off a screen and typed once.
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          dklen=dklen, maxmem=64 * 1024 * 1024)


def hash_password(password: str, min_length: int = MIN_LENGTH) -> dict:
    """The record stored in `users.json` — no plaintext anywhere in it.

    `min_length` is lowered only by the admin's own command-line override
    (`scripts/set_password.py --allow-short`): Gil chose "123" for his own
    account on 2026-09-28. Every screen keeps the 8-character rule."""
    if len(password or "") < max(1, min_length):
        raise ValueError(f"a password needs at least {min_length} characters")
    salt = os.urandom(16)
    return {"algo": "scrypt", "n": N, "r": R, "p": P, "dklen": DKLEN,
            "salt": _b64(salt), "hash": _b64(_scrypt(password, salt, N, R, P, DKLEN))}


def verify(password: str, record: "dict | None") -> bool:
    """Constant-time check of `password` against a stored record."""
    if not record or record.get("algo") != "scrypt" or not isinstance(password, str):
        return False
    try:
        salt = base64.b64decode(record["salt"])
        want = base64.b64decode(record["hash"])
        got = _scrypt(password, salt, int(record["n"]), int(record["r"]),
                      int(record["p"]), int(record["dklen"]))
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def generate(length: int = 12) -> str:
    """A fresh password for the admin to hand over (shown once)."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
