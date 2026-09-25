"""Two-way sync with Google Calendar, modelled on outlook_sync.py.

Pull: `events.list` with a **syncToken** — the first run lists everything from
30 days back and keeps Google's `nextSyncToken` on the `calendar_sources` row;
every later run asks only for what changed since. A 410 (the token expired)
falls back to a full listing, which also reconciles away anything deleted
upstream. Rows are tagged `external_source='google'`, `source='google'`.

Push: rows whose `source` is google and `sync_dirty` is set — edits PATCH the
Google event, rows with no `external_id` yet are CREATED there (an event you
chose to mirror, or every new local event when `mirror_new_events` is on).
Deletes drain Google's own tombstones from `calendar_sync_deletes`, which
`CalendarDB.delete_event()` writes.

Conflict policy: last-write-wins, decided during `pull()` exactly as Outlook's
is — a dirty local row whose `updated_at` (UTC) is at least as new as Google's
`updated` keeps its edit and is pushed; otherwise Google's copy replaces it.
A remote DELETE of an event edited locally since is the one twist: the edit
wins, so the row forgets its dead Google id and is re-created.

Scope (v1), as for Outlook: local recurring series are not pushed — Google's
series arrive expanded into single instances, which ARE editable one by one.
"""

from __future__ import annotations

import datetime
import logging
from zoneinfo import ZoneInfo

from assistant.calendar_sync import google_oauth
from assistant.calendar_sync.common import local_timezone_name, parse_iso
from assistant.calendar_sync.google_client import (
    GoogleAPIError, GoogleCalendarClient, SyncTokenExpired)
from assistant.db import CalendarDB, _utcnow_iso
from assistant.exceptions import AuthError, AuthExpiredError

logger = logging.getLogger(__name__)

EXTERNAL_SOURCE = "google"
DEFAULT_COLOR = "#4285f4"
_FULL_SYNC_PAST_DAYS = 30
ALL_DAY = ("00:00", "23:59")       # the ICS importer's all-day convention


def _zone(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return datetime.timezone.utc


def google_event_to_dict(ev: dict, tz_name: str, color: str = DEFAULT_COLOR) -> dict | None:
    """A Google event as the local row's fields, in the Mac's own zone.
    None when it has no usable start."""
    start = ev.get("start") or {}
    end = ev.get("end") or {}
    if start.get("date") and not start.get("dateTime"):
        date, (start_time, end_time) = start["date"], ALL_DAY
    elif start.get("dateTime"):
        tz = _zone(tz_name)
        try:
            s = datetime.datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
            e = datetime.datetime.fromisoformat((end.get("dateTime") or start["dateTime"]).replace("Z", "+00:00"))
        except ValueError:
            return None
        if s.tzinfo is None:
            s = s.replace(tzinfo=_zone(start.get("timeZone") or tz_name))
        if e.tzinfo is None:
            e = e.replace(tzinfo=_zone(end.get("timeZone") or tz_name))
        s, e = s.astimezone(tz), e.astimezone(tz)
        date, start_time = s.date().isoformat(), s.strftime("%H:%M")
        # One date per row: an event running past midnight ends at 23:59.
        end_time = e.strftime("%H:%M") if e.date() == s.date() else "23:59"
    else:
        return None
    attendees = ", ".join(a.get("email", "") for a in (ev.get("attendees") or [])
                          if a.get("email") and not a.get("self"))
    return {
        "title": ev.get("summary") or "(No title)",
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "location": ev.get("location", ""),
        "description": ev.get("description", ""),
        "attendees": attendees,
        "color": color,
    }


def local_event_to_payload(event: dict, tz_name: str, patch: bool = False) -> dict:
    """The local row as a Google event body. A PATCH also clears the other
    form of start/end, or an event switched between all-day and timed would
    carry both and be refused."""
    date = event["date"]
    payload: dict = {
        "summary": event.get("title") or "(No title)",
        "location": event.get("location") or "",
        "description": event.get("description") or "",
    }
    if (event.get("start_time"), event.get("end_time")) == ALL_DAY:
        nxt = (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat()
        payload["start"] = {"date": date}
        payload["end"] = {"date": nxt}
        if patch:
            for k in ("start", "end"):
                payload[k].update({"dateTime": None, "timeZone": None})
    else:
        start_t = event.get("start_time") or "00:00"
        end_t = event.get("end_time") or start_t
        end_date = date
        if end_t <= start_t:        # an end at or before the start is the next day
            end_date = (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat()
        payload["start"] = {"dateTime": f"{date}T{start_t}:00", "timeZone": tz_name}
        payload["end"] = {"dateTime": f"{end_date}T{end_t}:00", "timeZone": tz_name}
        if patch:
            for k in ("start", "end"):
                payload[k]["date"] = None
    return payload


def pull(db: CalendarDB, client: GoogleCalendarClient, source: dict, tz_name: str) -> dict:
    """Apply Google's changes locally. Returns {"pulled", "removed", "full"}."""
    color = source.get("color") or DEFAULT_COLOR
    sync_token = source.get("sync_token") or ""
    full = not sync_token
    try:
        items, next_token, summary = client.list_changes(sync_token=sync_token) if sync_token \
            else client.list_changes(time_min=_full_sync_start())
    except SyncTokenExpired:
        full = True
        items, next_token, summary = client.list_changes(time_min=_full_sync_start())

    local_by_id = {r["external_id"]: r for r in db.get_events_by_external_source(EXTERNAL_SOURCE)
                   if r.get("external_id")}
    pulled = removed = 0
    seen: list[str] = []
    for ev in items:
        gid = ev.get("id")
        if not gid:
            continue
        local = local_by_id.get(gid)
        local_newer = False
        if local and local.get("sync_dirty"):
            remote_t = parse_iso(ev.get("updated", ""))
            local_t = parse_iso(local.get("updated_at", ""))
            local_newer = bool(remote_t and local_t and local_t >= remote_t)

        if ev.get("status") == "cancelled":
            if local and local_newer:
                db.detach_from_remote(local["id"])      # the edit wins: re-create it
            elif local:
                removed += db.delete_external_event(EXTERNAL_SOURCE, gid)
            continue

        seen.append(gid)
        if local_newer:
            continue                                    # pushed below, this same run
        fields = google_event_to_dict(ev, tz_name, color)
        if fields is None:
            continue
        event_id = db.upsert_external_event(EXTERNAL_SOURCE, gid, fields)
        if local and local.get("sync_dirty"):
            db.clear_sync_dirty(event_id)               # Google's copy won
        pulled += 1

    if full and next_token:
        # A complete listing: anything we hold that Google no longer has is
        # gone upstream — except rows with local work still to push.
        keep = set(seen)
        keep.update(r["external_id"] for r in db.get_events_by_external_source(EXTERNAL_SOURCE)
                    if r.get("sync_dirty"))
        removed += db.delete_events_not_in(EXTERNAL_SOURCE, sorted(keep))

    updates = {"sync_token": next_token}
    if summary and not source.get("account"):
        updates["account"] = summary           # the primary calendar is named for the address
    db.update_calendar_source(source["id"], **updates)
    return {"pulled": pulled, "removed": removed, "full": full}


def _full_sync_start() -> str:
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=_FULL_SYNC_PAST_DAYS)
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def push(db: CalendarDB, client: GoogleCalendarClient, tz_name: str) -> int:
    """Create/PATCH dirty rows on Google and drain its tombstones."""
    pushed = 0
    for event in db.get_dirty_synced_events(EXTERNAL_SOURCE):
        stamp = event.get("updated_at")
        try:
            if event.get("external_id"):
                try:
                    client.patch(event["external_id"], local_event_to_payload(event, tz_name, patch=True))
                    db.clear_sync_dirty(event["id"], if_updated_at=stamp)
                except GoogleAPIError as e:
                    if e.status not in (404, 410):
                        raise
                    # Deleted on Google between our pull and this push: the
                    # local edit is newer, so it comes back as a new event.
                    created = client.insert(local_event_to_payload(event, tz_name))
                    db.set_event_external_id(event["id"], EXTERNAL_SOURCE, created["id"])
            else:
                created = client.insert(local_event_to_payload(event, tz_name))
                db.set_event_external_id(event["id"], EXTERNAL_SOURCE, created["id"])
            pushed += 1
        except GoogleAPIError as e:
            logger.warning("Google push of event %s failed — retrying next cycle: %s", event["id"], e)
    for tomb in db.pop_sync_deletes(EXTERNAL_SOURCE):
        try:
            client.delete(tomb["external_id"])
            pushed += 1
        except (GoogleAPIError, AuthError) as e:
            db.requeue_sync_delete(EXTERNAL_SOURCE, tomb["external_id"])
            if isinstance(e, AuthExpiredError):
                raise
    return pushed


def is_configured(cfg) -> bool:
    """Credentials exist for at least one sign-in surface."""
    g = cfg.google_calendar
    return bool(g.enabled and (google_oauth.desktop_client(g) or google_oauth.ios_client(g)))


def sync_google(db: CalendarDB, config, session=None) -> dict:
    """One full Google cycle — pull then push. Never raises.
    Returns {"pulled", "pushed", "removed", "error", "ran"}."""
    out: dict = {"pulled": 0, "pushed": 0, "removed": 0, "error": "", "ran": False}
    source = db.get_calendar_source_by_kind("google")
    if source is None or not source["enabled"] or not config.google_calendar.enabled:
        return out
    token = google_oauth.load_token()
    if token is None:
        out["error"] = "Google: not signed in — connect again."
        db.update_calendar_source(source["id"], last_error=out["error"])
        return out
    out["ran"] = True
    tz_name = local_timezone_name()
    try:
        client = GoogleCalendarClient(google_oauth.GoogleAuth(token, session=session),
                                      config.google_calendar.calendar_id, session=session)
        if config.google_calendar.mirror_new_events:
            db.mark_new_local_events_for_push(EXTERNAL_SOURCE, source.get("created_at", ""))
        got = pull(db, client, source, tz_name)
        out["pulled"], out["removed"] = got["pulled"], got["removed"]
        if source.get("two_way"):
            out["pushed"] = push(db, client, tz_name)
        db.update_calendar_source(source["id"], last_synced=_utcnow_iso(), last_error="")
    except AuthExpiredError as e:
        out["error"] = f"Google: {e}"
    except Exception as e:  # noqa: BLE001 — a sync failure is reported, never raised
        logger.exception("Google sync failed")
        out["error"] = f"Google sync: {e}"
    if out["error"]:
        db.update_calendar_source(source["id"], last_error=out["error"])
    return out
