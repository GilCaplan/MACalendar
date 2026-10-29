"""The machine's IANA timezone, for Outlook / Graph payloads.

This file held `CalendarHandler`, the old push-to-Outlook path; nothing has
constructed it since calendar sync moved to `assistant/calendar_sync/`
(removed 2026-10-29). The timezone helper is what its callers still use.
"""

import os


def get_local_timezone() -> str:
    """Return the local IANA timezone string (e.g. "America/New_York").

    `str(datetime.now().astimezone().tzinfo)` only yields a bare abbreviation
    like "IDT"/"PDT" on macOS, not a zone name — Microsoft Graph rejects that
    as an event's `timeZone` value. Resolving the actual symlink target of
    `/etc/localtime` (which macOS always keeps pointed at the current zone)
    gives the real IANA name Graph expects.
    """
    try:
        path = os.path.realpath("/etc/localtime")
        if "/zoneinfo/" in path:
            return path.split("/zoneinfo/")[-1]
    except Exception:
        pass
    return "UTC"
