"""Pre-event notification policy — the single brain both clients read.

Computes, per event row, WHEN a reminder should fire (`notify_at`) and why
it won't (`notify_suppressed_reason`). The server embeds the answers in
every event payload; the phone schedules local notifications from its cache
of those payloads; the Mac notifier thread fires the same times. Neither
client re-derives policy.

Resolution chain for the lead time (first hit wins):
    event.reminder_minutes  0 → none ("I said no reminder on this one")
                            N → N minutes before start
    category lead           0 → the whole category is MUTED (Gil's rule:
                                a category can opt out of notifications)
                            N → N
    global default          0 → opt-in only (ships as 0), N → N

Quiet windows (observance): evaluated on the FIRE time, sundown-bounded via
candle_lighting/tzeit — never date-only. An event itself inside Shabbat/yom
tov gets no reminder (reason recorded, announced at creation — never
silent). A reminder that lands inside the window for an event AFTER it is
clamped to tzeit + motzei_buffer_minutes. Fasts don't suppress — a reminder
is not a booking. Fail open: no solar data ⇒ notify normally, same
philosophy as the series skip.
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

logger = logging.getLogger(__name__)

#: How many consecutive holy days a window scan will walk (2-day chag +
#: adjacent Shabbat is the realistic maximum).
_MAX_RUN = 4


# --------------------------------------------------------------------------
# Lead-time resolution
# --------------------------------------------------------------------------

def resolve_lead(event: dict, cfg) -> "tuple[Optional[int], str]":
    """(minutes, source) — minutes None means 'no reminder', and source says
    which rung of the chain decided (event_off / event / category_muted /
    category / default / default_off)."""
    ev = event.get("reminder_minutes")
    if ev is not None:
        return (None, "event_off") if int(ev) == 0 else (int(ev), "event")
    leads = getattr(cfg, "category_leads", None) or {}
    cat = event.get("category") or ""
    if cat in leads:
        n = int(leads[cat])
        return (None, "category_muted") if n == 0 else (n, "category")
    d = int(getattr(cfg, "default_lead_minutes", 0) or 0)
    return (None, "default_off") if d == 0 else (d, "default")


# --------------------------------------------------------------------------
# Quiet windows
# --------------------------------------------------------------------------

def _holy(d: datetime.date) -> bool:
    from assistant import observance as ob
    return ob.is_shabbat(d) or ob.is_yom_tov(d)


def _window_end(d: datetime.date) -> "Optional[datetime.datetime]":
    """End (tzeit of the last consecutive holy day) of the window containing
    holy day `d`; None when solar data is unavailable (fail open)."""
    from assistant import observance as ob
    last = d
    for _ in range(_MAX_RUN):
        nxt = last + datetime.timedelta(days=1)
        if not _holy(nxt):
            break
        last = nxt
    t = ob.tzeit(last)
    return datetime.datetime.combine(last, t) if t else None


def quiet_window_end(moment: datetime.datetime) -> "Optional[datetime.datetime]":
    """When `moment` falls inside a Shabbat/yom-tov window, the window's end;
    else None. Sundown-bounded: erev evenings count from candle lighting,
    the last day releases at tzeit. Any missing solar datum ⇒ None."""
    from assistant import observance as ob
    try:
        d = moment.date()
        if _holy(d):
            end = _window_end(d)
            if end is None:
                return None                       # fail open
            return end if moment < end else None
        nxt = d + datetime.timedelta(days=1)
        if _holy(nxt):
            cl = ob.candle_lighting(d)
            if cl is not None and moment.time() >= cl:
                return _window_end(nxt)
        return None
    except Exception:                              # fail open, like the series skip
        logger.warning("observance unavailable for %s; notifying normally", moment)
        return None


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------

def notify_verdict(event: dict, cfg) -> "tuple[Optional[str], Optional[str]]":
    """(notify_at ISO local datetime | None, suppressed_reason | None)."""
    if not getattr(cfg, "enabled", True):
        return None, None
    if not getattr(cfg, "pre_event", False):
        # The day panel replaced these (Gil, 2026-09-11: the panel "and not
        # when something is about to pop up"). Dormant, not deleted — see
        # NotificationsConfig.pre_event.
        return None, None
    lead, _src = resolve_lead(event, cfg)
    if lead is None or not event.get("start_time") or not event.get("date"):
        return None, None
    try:
        start = datetime.datetime.combine(
            datetime.date.fromisoformat(event["date"]),
            datetime.time(*[int(x) for x in event["start_time"].split(":")[:2]]))
    except (ValueError, TypeError):
        return None, None
    fire = start - datetime.timedelta(minutes=lead)

    if getattr(cfg, "respect_observance", True):
        from assistant import observance as ob
        if ob.is_enabled():
            start_end = quiet_window_end(start)
            if start_end is not None:
                # The event itself is inside the window (Shabbat lunch):
                # no reminder, and the reason travels with the payload.
                d = start.date()
                name = ob.yom_tov_name(d) if ob.is_yom_tov(d) else ""
                return None, (f"yom_tov:{name}" if name else "shabbat")
            fire_end = quiet_window_end(fire)
            if fire_end is not None:
                # Motzei event whose lead lands inside the window: clamp to
                # after havdala plus the configured buffer.
                buf = ob.current_settings().motzei_buffer_minutes
                fire = fire_end + datetime.timedelta(minutes=buf)
                if fire >= start:
                    return None, "clamped_past_start"
    return fire.isoformat(timespec="minutes"), None


def annotate(rows: "list[dict]", cfg=None) -> "list[dict]":
    """Add reminder_minutes/notify_at/notify_suppressed_reason to event
    payloads — the serialization hook GET /events* runs every row through."""
    if cfg is None:
        from assistant.config import load_config
        cfg = load_config().notifications
    for r in rows:
        at, why = notify_verdict(r, cfg)
        r["notify_at"] = at
        r["notify_suppressed_reason"] = why
        r.setdefault("reminder_minutes", None)
    return rows


# --------------------------------------------------------------------------
# THE DAY PANEL — one summary of today, instead of a stream of imminent things
# --------------------------------------------------------------------------
#
# Gil, 2026-09-11: "I want it to be more of a panel that nicely shows what i
# have today and not when something is about to pop up… it's on or off and it
# shows in a nice manner the event calendar and tasks for today."
#
# Same division of labour as the pre-event half above, and for the same
# reason: the server decides, the clients render. That now includes the
# WORDING — `build_digest` returns the finished title and body as well as the
# rows, so the phone's notification, the Mac's banner and anything added later
# say the same thing. A client that formats its own would drift the moment one
# of them learned about all-day events and the other did not.

#: Sort key for an event with no clock: all-day rows lead the day.
_ALL_DAY = "00:00"


def digest_time(cfg) -> "Optional[datetime.time]":
    """The configured local fire time, or None if it is unreadable.

    Unreadable rather than invalid-and-crash: this is read on a daemon
    thread, and a typo in config.yaml must not take the notifier down.
    """
    raw = (getattr(cfg, "digest_time", None) or "").strip()
    try:
        hh, mm = (int(x) for x in raw.split(":")[:2])
        return datetime.time(hh, mm)
    except (ValueError, TypeError):
        logger.warning("notifications.digest_time is not HH:MM (%r); "
                       "the day panel will not fire", raw)
        return None


def digest_verdict(day: datetime.date, cfg) -> "tuple[Optional[str], Optional[str]]":
    """(fires_at ISO local datetime | None, suppressed_reason | None).

    Suppressed inside a Shabbat / yom tov window, on the same ruling that
    governs pre-event reminders (DEVQA Q6, 2026-09-11: no reminders for
    events inside them) — a 07:00 panel on Shabbat morning is a notification
    on Shabbat whatever it is summarising. Fails OPEN, like every other
    observance decision here: no solar data means it fires.
    """
    if not getattr(cfg, "enabled", True) or not getattr(cfg, "daily_digest", True):
        return None, None
    at = digest_time(cfg)
    if at is None:
        return None, None
    fire = datetime.datetime.combine(day, at)

    if getattr(cfg, "respect_observance", True):
        from assistant import observance as ob
        if ob.is_enabled() and quiet_window_end(fire) is not None:
            name = ob.yom_tov_name(day) if ob.is_yom_tov(day) else ""
            return None, (f"yom_tov:{name}" if name else "shabbat")
    return fire.isoformat(timespec="minutes"), None


def _clock(value: "Optional[str]") -> str:
    """"14:30" -> "2:30 PM"; anything unparseable stays as it came."""
    try:
        hh, mm = (int(x) for x in str(value).split(":")[:2])
        return datetime.time(hh, mm).strftime("%-I:%M %p")
    except (ValueError, TypeError):
        return str(value or "")


def digest_lines(events: "list[dict]", todos: "list[dict]") -> "tuple[list[str], list[str]]":
    """(event lines, task lines) — the day, in the order it happens.

    All-day rows first, then by clock, because that is the order the day is
    lived in rather than the order the table returns.
    """
    ordered = sorted(events, key=lambda e: (e.get("start_time") or _ALL_DAY))
    ev = []
    for e in ordered:
        title = (e.get("title") or "Untitled").strip()
        start = e.get("start_time")
        ev.append(f"{_clock(start)}  {title}" if start else f"All day  {title}")
    td = [(t.get("title") or "Untitled").strip() for t in todos]
    return ev, td


def build_digest(day: datetime.date, cfg, db=None) -> dict:
    """The whole day panel: when it fires, what it says, and the rows behind it.

    `db` is injectable so a caller inside the API can pass the one it already
    holds — and so tests never reach for the real calendar.
    """
    if db is None:
        from assistant.db import get_db
        db = get_db()

    fires_at, suppressed = digest_verdict(day, cfg)
    events = list(db.get_events_for_day(day) or [])
    # A DATED task belongs to its due date. An UNDATED one is "outstanding",
    # which is a today concept — carrying it onto every future day made
    # `?date=` a week out claim three tasks that are not that day's business.
    today = datetime.date.today()
    todos = [t for t in (db.get_todos(list_name=None, include_completed=False) or [])
             if (t.get("due_date") or "") == day.isoformat()
             or (not t.get("due_date") and day == today)]

    ev_lines, td_lines = digest_lines(events, todos)
    heading = day.strftime("%A %-d %B")

    # The COUNT belongs in the title, where a notification shows it without
    # being opened; the detail belongs in the body. "Nothing on" is a real
    # answer and reads better than an empty panel.
    if ev_lines or td_lines:
        parts = []
        if ev_lines:
            parts.append(f"{len(ev_lines)} event" + ("s" if len(ev_lines) != 1 else ""))
        if td_lines:
            parts.append(f"{len(td_lines)} task" + ("s" if len(td_lines) != 1 else ""))
        title = f"{heading} — " + " · ".join(parts)
    else:
        title = f"{heading} — nothing on"

    body = "\n".join(ev_lines + (["—"] if ev_lines and td_lines else []) + td_lines)

    return {
        "date": day.isoformat(),
        "enabled": bool(getattr(cfg, "enabled", True)
                        and getattr(cfg, "daily_digest", True)),
        "fires_at": fires_at,
        "suppressed_reason": suppressed,
        "title": title,
        "body": body,
        "events": [{"id": e.get("id"), "title": e.get("title"),
                    "start_time": e.get("start_time"),
                    "end_time": e.get("end_time"),
                    "category": e.get("category")} for e in
                   sorted(events, key=lambda e: (e.get("start_time") or _ALL_DAY))],
        "tasks": [{"id": t.get("id"), "title": t.get("title"),
                   "list_name": t.get("list_name"),
                   "tags": t.get("tags")} for t in todos],
    }
