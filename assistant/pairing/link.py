"""The ``macalendar://pair`` link a QR code carries, and the QR itself.

    macalendar://pair?u=<url>&u=<url>…&c=<code>&n=<server name>[&k=<api key>]

``u`` repeats, best first. ``k`` is present only when the server has an API
key: a phone without it would be paired and then refused on every request,
and the QR is shown only on the server's own screen. The iPhone's Camera
recognises the scheme and offers "Open in MACalendar" — no in-app scanner,
no camera permission.
"""

from __future__ import annotations

from urllib.parse import urlencode

SCHEME = "macalendar"


def pair_link(urls: list[str], code: str, name: str, key: str = "") -> str:
    q = [("u", u) for u in urls] + [("c", code), ("n", name)]
    if key:
        q.append(("k", key))
    return f"{SCHEME}://pair?" + urlencode(q)


def qr_matrix(text: str) -> list[list[bool]]:
    """The QR's modules, True = dark, quiet zone included — for painting with
    whatever the caller draws with (Qt here), so no image library is needed."""
    import segno
    qr = segno.make(text, error="m", micro=False)
    return [[bool(v) for v in row] for row in qr.matrix_iter(scale=1, border=2)]
