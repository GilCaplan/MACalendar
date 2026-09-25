"""Small helpers every sync provider shares: timestamps and the local zone."""

from __future__ import annotations

import datetime
import re

_ISO_TS_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})?$"
)


def parse_iso(ts: str) -> datetime.datetime | None:
    """Parse an ISO-8601 timestamp from either side of a sync.

    Local `_utcnow_iso()` writes a "+00:00" offset with 6-digit microseconds;
    Graph's `lastModifiedDateTime` uses "Z" with up to 7 fractional digits and
    Google's `updated` uses "Z" with 3. Comparing these as raw strings is not
    reliable — the differing suffix can make a chronologically newer stamp
    sort as "smaller" once two share a whole-second prefix. So both sides are
    normalised to aware `datetime`s (UTC when no offset is given).
    """
    if not ts:
        return None
    m = _ISO_TS_RE.match(ts)
    if not m:
        return None
    frac = (m.group("frac") or "").ljust(6, "0")[:6]  # pad/truncate to microseconds
    offset = m.group("offset") or "+00:00"
    if offset == "Z":
        offset = "+00:00"
    try:
        return datetime.datetime.fromisoformat(f"{m.group('base')}.{frac}{offset}")
    except ValueError:
        return None


def local_timezone_name() -> str:
    """The Mac's IANA zone ("Asia/Jerusalem"), which both Graph and Google
    accept as an event's `timeZone`."""
    from assistant.actions.calendar.handler import get_local_timezone
    return get_local_timezone()
