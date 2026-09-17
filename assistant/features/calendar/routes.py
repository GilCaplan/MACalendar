"""Calendar's HTTP surface: `/events*`, `/search`, `/categories`, `/holidays`, `/sync/bootstrap`.

A Flask blueprint rather than lines in `server.py`, per
`assistant/features/CONVENTION.md`: a surface owns a folder, declares itself
once to a registry, ships its own routes, and the generic layer never learns
its name. CLAUDE.md's rule for `server.py` is that it stays HTTP plumbing —
routes, request shapes, CRUD — and the feature's CRUD belongs with the feature.

| route | what |
|---|---|
| `GET/POST /events` | the month/week/day reads, and create |
| `GET/PATCH/DELETE /events/<id>` | one event; `GET /events/<id>.ics` exports it |
| `GET /search` | substring search over events and tasks |
| `GET/POST /categories` | the colour classes; `DELETE /categories/<name>` |
| `POST /categories/classify` `POST /categories/recolor` | classify one title; re-colour everything |
| `GET /holidays` | the Hebrew calendar over a range |
| `GET /sync/bootstrap` | a cold client's whole first screen in one round trip |

No `url_prefix`: every path above is already absolute, and a prefix would move
all of them.

`/sync/bootstrap` is the one route that reaches across features — it aggregates
tasks' `tag_rules()` and timer's `_timer_out`/`_counter_out` rather than
re-deriving them, which is what keeps it "a READ aggregate over the same
helpers the individual routes use" and not a second way into the database.
"""

from __future__ import annotations

import datetime

from flask import Blueprint, current_app, jsonify, request

from assistant.api.server import change_token, create_event_from_body
from assistant.features.tasks.routes import tag_rules
from assistant.features.timer.routes import _counter_out, _timer_out

blueprint = Blueprint("calendar", __name__)


def get_db():
    """Resolved through `assistant.api.server` at CALL time, never bound at
    import. server.py re-exports `assistant.db.get_db`, and a test that swaps
    it there — `tests/integration/test_api_server.py`'s `app_client` fixture —
    has to reach the feature blueprints too. A blueprint holding its own early
    binding would quietly read the REAL ~/.assistant_tools/calendar.db while
    the test watched a temp one."""
    from assistant.api import server
    return server.get_db()


# ------------------------------------------------------------------
# Event categories (colours)
# ------------------------------------------------------------------

@blueprint.get("/categories")
def categories_list():
    from assistant.actions.calendar import categories as _cat
    return jsonify({"categories": _cat.all_categories()})


@blueprint.post("/categories")
def categories_upsert():
    """{"name": "Volunteering", "color": "#…", "alt": "#…", "keywords": [...], "add_keywords": [...]}"""
    from assistant.actions.calendar import categories as _cat
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(_cat.upsert(str(body.get("name", "")), body.get("color"), body.get("alt"),
                                   body.get("keywords"), body.get("add_keywords")))
    except ValueError as e:
        return jsonify({"error": str(e), "code": 400}), 400


@blueprint.delete("/categories/<path:name>")
def categories_delete(name: str):
    from assistant.actions.calendar import categories as _cat
    if not _cat.remove(name):
        return jsonify({"error": "Not found (Personal cannot be removed)", "code": 404}), 404
    return jsonify({"ok": True})


@blueprint.post("/categories/classify")
def categories_classify():
    from assistant.actions.calendar import categories as _cat
    b = request.get_json(silent=True) or {}
    cat = _cat.classify(b.get("title", ""), b.get("attendees"), b.get("location", ""), b.get("description", ""))
    color, alt = _cat.color_for(cat)
    return jsonify({"category": cat, "color": color, "alt": alt})


@blueprint.post("/categories/recolor")
def categories_recolor():
    """Apply categories/colours to existing events. ?force=1 re-does everything."""
    n = get_db().recategorise_all(force=request.args.get("force") == "1")
    return jsonify({"updated": n})


# ------------------------------------------------------------------
# Events
# ------------------------------------------------------------------

@blueprint.get("/events")
def events_list():
    db = get_db()
    year = request.args.get("year")
    month = request.args.get("month")
    date_str = request.args.get("date")
    week_start_str = request.args.get("week_start")

    try:
        if date_str:
            rows = db.get_events_for_day(datetime.date.fromisoformat(date_str))
        elif week_start_str:
            rows = db.get_events_for_week(datetime.date.fromisoformat(week_start_str))
        elif year and month:
            rows = db.get_events_for_month(int(year), int(month))
        else:
            # Default: today
            rows = db.get_events_for_day(datetime.date.today())
    except ValueError as e:
        return jsonify({"error": str(e), "code": 400}), 400

    from assistant.notify import annotate
    return jsonify(annotate(rows))


@blueprint.get("/events/<int:event_id>")
def event_get(event_id: int):
    db = get_db()
    row = db.get_event(event_id)
    if row is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    from assistant.notify import annotate
    return jsonify(annotate([row])[0])


@blueprint.get("/events/<int:event_id>.ics")
def event_ics(event_id: int):
    """Share/export one event as an .ics file (import's symmetric half)."""
    from assistant.ics_export import event_to_ics, filename_for
    db = get_db()
    row = db.get_event(event_id)
    if row is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    resp = current_app.response_class(event_to_ics(row), mimetype="text/calendar")
    resp.headers["Content-Disposition"] = \
        f'attachment; filename="{filename_for(row)}"'
    return resp


@blueprint.get("/search")
def search():
    """Substring search over events and tasks for the toolbar/search UIs."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"error": "q must be at least 2 characters",
                        "code": 400}), 400
    db = get_db()
    return jsonify({"events": db.search_events(q),
                    "todos": db.search_todos(q)})


@blueprint.post("/events")
def event_create():
    """Create an event."""
    payload, status = create_event_from_body(request.get_json(silent=True) or {})
    return jsonify(payload), status


@blueprint.patch("/events/<int:event_id>")
def event_update(event_id: int):
    data = request.get_json(silent=True) or {}
    db = get_db()
    event = db.get_event(event_id)
    if event is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    if db.is_event_locked(event):
        return jsonify({"error": "Event is read-only (synced source)", "code": 403}), 403

    # Optional optimistic-concurrency check. A client that edited the event
    # while disconnected sends the `updated_at` it was working from; if the
    # event has moved on since (someone changed it on the Mac meanwhile),
    # refuse rather than silently overwriting their work, and hand back what
    # the event looks like now so the client can say so.
    base = str(data.pop("base_updated_at", "") or "")
    if base and str(event.get("updated_at") or "") not in ("", base):
        return jsonify({"error": "Event changed on the Mac since you edited it",
                        "code": 409, "current": event}), 409

    db.update_event(event_id, **data)
    if data.get("recurrence"):
        db.promote_to_series(event_id)
    return jsonify({"id": event_id})


@blueprint.delete("/events/<int:event_id>")
def event_delete(event_id: int):
    db = get_db()
    event = db.get_event(event_id)
    if event is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    if db.is_event_locked(event):
        return jsonify({"error": "Event is read-only (synced source)", "code": 403}), 403
    db.delete_event(event_id)
    return jsonify({"deleted": event_id})


@blueprint.get("/sync/bootstrap")
def sync_bootstrap():
    """Everything a client needs to draw itself, in ONE round trip.

    A cold start used to be eight independent GETs, and the phone paid the
    full timeout on each of them whenever the Mac was away — the app opened
    on an empty calendar for the better part of a minute before falling
    back to a cache it had all along. One request means one timeout, and
    the answer carries the change token, so the client knows immediately
    whether the cache it just drew is already current.

    Window: the named month plus the one either side, which is what the
    month/week/day views can reach without another fetch. Holidays cover
    the same span, so the Hebrew calendar survives offline too — it was
    the one part of the calendar with no cache at all.

    This is a READ aggregate over the same helpers the individual routes
    use; it is not a second way into the database and holds no logic of its
    own (DOCUMENTATION/SYNC_PROTOCOL.md).
    """
    from assistant.actions.calendar import categories as _cat
    from assistant.hebrew_calendar import enumerate_holidays
    from assistant.notify import annotate

    db = get_db()
    today = datetime.date.today()
    try:
        year = int(request.args.get("year") or today.year)
        month = int(request.args.get("month") or today.month)
        first = datetime.date(year, month, 1)
    except ValueError as e:
        return jsonify({"error": str(e), "code": 400}), 400
    israel = request.args.get("israel", "1") not in ("0", "false", "False")

    months = []
    for delta in (-1, 0, 1):
        y, m = divmod((first.year * 12 + first.month - 1) + delta, 12)
        months.append((y, m + 1))

    events: list = []
    for y, m in months:
        events.extend(db.get_events_for_month(y, m))

    start = datetime.date(months[0][0], months[0][1], 1)
    last_y, last_m = months[-1]
    end = (datetime.date(last_y + last_m // 12, last_m % 12 + 1, 1)
           - datetime.timedelta(days=1))

    return jsonify({
        "token": change_token(),
        "server_time": datetime.datetime.now().astimezone().isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "events": annotate(events),
        "todos": db.get_todos(list_name=None, include_completed=False),
        "tags": db.get_tags(),
        "tag_rules": tag_rules().get_json(),
        "categories": _cat.all_categories(),
        "holidays": [
            {
                "name_en": h.name_en,
                "name_he": h.name_he,
                "category": h.category,
                "gregorian_erev_start": h.gregorian_erev_start.isoformat(),
                "gregorian_end": h.gregorian_end.isoformat(),
            }
            for h in enumerate_holidays(start, end, israel=israel)
        ],
        "timers": [_timer_out(db, t) for t in db.get_timers()],
        "counters": [_counter_out(db, c) for c in db.get_counters()],
    })


# ------------------------------------------------------------------
# Hebrew calendar / holidays
# ------------------------------------------------------------------

@blueprint.get("/holidays")
def holidays_list():
    from assistant.hebrew_calendar import enumerate_holidays

    start_str = request.args.get("start")
    end_str = request.args.get("end")
    israel = request.args.get("israel", "1") not in ("0", "false", "False")

    try:
        if start_str and end_str:
            start = datetime.date.fromisoformat(start_str)
            end = datetime.date.fromisoformat(end_str)
        else:
            today = datetime.date.today()
            start = today.replace(day=1)
            end = today + datetime.timedelta(days=60)
    except ValueError as e:
        return jsonify({"error": str(e), "code": 400}), 400

    holidays = enumerate_holidays(start, end, israel=israel)
    return jsonify([
        {
            "name_en": h.name_en,
            "name_he": h.name_he,
            "category": h.category,
            "gregorian_erev_start": h.gregorian_erev_start.isoformat(),
            "gregorian_end": h.gregorian_end.isoformat(),
        }
        for h in holidays
    ])
