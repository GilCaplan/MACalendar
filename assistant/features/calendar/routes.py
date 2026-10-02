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
| `GET/POST /events/<id>/todo` | the to-do linked to it; POST files one (linked) |
| `GET /search` | substring search over events and tasks |
| `GET/POST /categories` | the colour classes, each with an optional default length and chain gap; `DELETE /categories/<name>` |
| `GET /event_defaults` | the default event length and chain gap, resolved for a category or a title (DEVQA Q51) |
| `POST /categories/classify` `POST /categories/recolor` | classify one title; re-colour everything |
| `GET /categories/rules` | the category classifier as data, for the phone to run offline |
| `GET /holidays` | the Hebrew calendar over a range |
| `GET /sync/bootstrap` | a cold client's whole first screen in one round trip (incl. Shabbat/yom tov windows) |

No `url_prefix`: every path above is already absolute, and a prefix would move
all of them.

`/sync/bootstrap` is the one route that reaches across features — it aggregates
tasks' `tag_rules()` and timer's `_timer_out`/`_counter_out` rather than
re-deriving them, which is what keeps it "a READ aggregate over the same
helpers the individual routes use" and not a second way into the database.
"""

from __future__ import annotations

import datetime

from assistant.users import sharing
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
    """Every category. A category's `default_minutes` / `chain_gap_minutes` is
    present only when it overrides the global; `defaults` carries the global
    pair so an editor can say what an empty field means."""
    from assistant import event_defaults
    from assistant.actions.calendar import categories as _cat
    return jsonify({"categories": _cat.all_categories(),
                    "defaults": _global_event_defaults(event_defaults)})


@blueprint.post("/categories")
def categories_upsert():
    """{"name": "Volunteering", "color": "#…", "alt": "#…", "keywords": [...], "add_keywords": [...],
        "default_minutes": 90 | null, "chain_gap_minutes": 15 | null}

    The two minute fields (DEVQA Q51) are touched only when the body NAMES
    them: a number sets the category's own value, null clears it back to the
    global setting, and leaving the key out keeps what is stored — so a client
    that only edits colours never wipes them."""
    from assistant.actions.calendar import categories as _cat
    body = request.get_json(silent=True) or {}
    durations = {k: body[k] for k in _cat.DURATION_FIELDS if k in body}
    try:
        return jsonify(_cat.upsert(str(body.get("name", "")), body.get("color"), body.get("alt"),
                                   body.get("keywords"), body.get("add_keywords"), **durations))
    except ValueError as e:
        return jsonify({"error": str(e), "code": 400}), 400


def _global_event_defaults(event_defaults) -> dict:
    """The global pair as the app resolves it (config.yaml, else built-in)."""
    return {"event_length_minutes": event_defaults.length_minutes(None),
            "chain_gap_minutes": event_defaults.gap_minutes(None)}


@blueprint.get("/event_defaults")
def event_defaults_resolved():
    """The default length and chain gap, RESOLVED, for `?category=` or for
    `?title=` (classified the way the engine classifies it). Neither: the
    global pair.

    A read only. The global values are written with `PATCH /config`
    (`{"events": {...}}`) like every other shared setting, and a category's
    with `POST /categories`. This answers what a client cannot work out on its
    own: the number the ENGINE would use for a title it cannot classify
    itself (the phone's new-event sheet)."""
    from assistant import event_defaults
    category = (request.args.get("category") or "").strip() or None
    title = request.args.get("title")
    if category is None and title:
        category = event_defaults.category_of(title)
    return jsonify({
        "category": category,
        "length_minutes": event_defaults.length_minutes(category),
        "gap_minutes": event_defaults.gap_minutes(category),
        **_global_event_defaults(event_defaults),
    })


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


@blueprint.get("/categories/rules")
def category_rules():
    """The event-category classifier as data, so a client can run it offline.

    `categories.classify` only runs where the database is, so an event made
    on the phone with the Mac away had no category and no colour until the
    queued create replayed. The phone carries a port of the scorer
    (`CategoryClassifier.swift`); this hands it the table it reads — the
    categories IN ORDER (a tie goes to the first, as `classify` breaks it),
    their colours for `pick_color`, and the person names its last rule reads
    — the same split as `/tags/rules`. `rev` changes whenever any of it does.
    """
    import hashlib
    import json as _json

    from assistant.actions.calendar import categories as _cat
    payload = {
        "categories": [{"name": c["name"], "color": c["color"], "alt": c.get("alt", c["color"]),
                        "keywords": list(c.get("keywords", []))}
                       for c in _cat.all_categories()],
        "people": _cat.people_words(),
    }
    payload["rev"] = hashlib.sha1(
        _json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return jsonify(payload)


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
    year = request.args.get("year")
    month = request.args.get("month")
    date_str = request.args.get("date")
    week_start_str = request.args.get("week_start")

    try:
        if date_str:
            day = datetime.date.fromisoformat(date_str)
            fetch = lambda db: db.get_events_for_day(day)
        elif week_start_str:
            week = datetime.date.fromisoformat(week_start_str)
            fetch = lambda db: db.get_events_for_week(week)
        elif year and month:
            y, m = int(year), int(month)
            fetch = lambda db: db.get_events_for_month(y, m)
        else:
            # Default: today
            fetch = lambda db: db.get_events_for_day(datetime.date.today())
        # every calendar this viewer can see — their own, anyone sharing with
        # them, and (the admin) anyone toggled into his view (DEVQA Q65)
        rows = sharing.gather(fetch, sort_key=sharing.event_order)
    except ValueError as e:
        return jsonify({"error": str(e), "code": 400}), 400

    from assistant.engine.label.title_icons import attach
    from assistant.notify import annotate
    return jsonify(attach(annotate(rows)))


@blueprint.get("/events/<int:event_id>")
def event_get(event_id: int):
    db, rid = sharing.for_request(event_id)
    row = db.get_event(rid)
    if row is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    from assistant.engine.label.title_icons import attach
    from assistant.notify import annotate
    return jsonify(sharing.present(attach(annotate([row]))[0]))


@blueprint.get("/events/<int:event_id>.ics")
def event_ics(event_id: int):
    """Share/export one event as an .ics file (import's symmetric half)."""
    from assistant.ics_export import event_to_ics, filename_for
    db, rid = sharing.for_request(event_id)
    row = db.get_event(rid)
    if row is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    resp = current_app.response_class(event_to_ics(row), mimetype="text/calendar")
    resp.headers["Content-Disposition"] = \
        f'attachment; filename="{filename_for(row)}"'
    return resp


@blueprint.get("/events/<int:event_id>/todo")
def event_linked_todo(event_id: int):
    """The to-do that is this event, or `{"todo": null}`."""
    db, rid = sharing.for_request(event_id)
    if db.get_event(rid) is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    return jsonify({"todo": sharing.present(db.linked_todo(rid))})


@blueprint.post("/events/<int:event_id>/todo")
def event_add_todo(event_id: int):
    """Also put this event on the to-do list, linked. Returns the existing
    linked to-do if it already has one."""
    db, rid = sharing.for_request(event_id, edit=True)
    todo_id = db.create_linked_todo(rid)
    if todo_id is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    return jsonify({"todo": sharing.present(db.get_todo(todo_id))}), 201


@blueprint.get("/search")
def search():
    """Substring search over events and tasks for the toolbar/search UIs."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"error": "q must be at least 2 characters",
                        "code": 400}), 400
    from assistant.engine.label.title_icons import attach
    return jsonify({"events": attach(sharing.gather(lambda db: db.search_events(q),
                                                    sort_key=sharing.event_order)),
                    "todos": attach(sharing.gather(lambda db: db.search_todos(q)))})


@blueprint.post("/events")
def event_create():
    """Create an event — in the viewer's calendar, or `owner_id`'s when they
    may edit it (the editor's owner picker, DEVQA Q65)."""
    body = request.get_json(silent=True) or {}
    with sharing.creating_for(body.pop("owner_id", None)):
        payload, status = create_event_from_body(body)
        if isinstance(payload, dict) and "id" in payload:
            payload["id"] = sharing.public_id(payload["id"])
    return jsonify(payload), status


@blueprint.patch("/events/<int:event_id>")
def event_update(event_id: int):
    data = request.get_json(silent=True) or {}
    db, rid = sharing.for_request(event_id, edit=True)
    event = db.get_event(rid)
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
                        "code": 409, "current": sharing.present(event)}), 409

    db.update_event(rid, **data)
    if data.get("recurrence"):
        db.promote_to_series(rid)
    return jsonify({"id": event_id})


@blueprint.delete("/events/<int:event_id>")
def event_delete(event_id: int):
    db, rid = sharing.for_request(event_id, edit=True)
    event = db.get_event(rid)
    if event is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    if db.is_event_locked(event):
        return jsonify({"error": "Event is read-only (synced source)", "code": 403}), 403
    db.delete_event(rid)
    return jsonify({"deleted": event_id})


# ------------------------------------------------------------------
# A SERIES, as one thing
#
# `db` has had the whole vocabulary for a long time — `series_id` on every
# instance ("NULL = not recurring; shared by all instances"), `update_series`
# which propagates and RE-GENERATES the future slots when the cadence or the
# end date moves, `delete_series_from`, and the re-rooting that keeps a series
# editable after you delete its first instance. None of it was reachable over
# HTTP, so the phone could edit ONE instance and nothing else: change the end
# date there and the other rows carried on regardless.
#
# Gil, 2026-09-18: "recurring events are all linked to each other, so if in
# event i change the end date for repetition it updates accordingly, or if i
# extend it. And an option to choose in what interval."
# ------------------------------------------------------------------

def _series_id_of(event: dict) -> "int | None":
    """The id every instance of this series shares, or None if it is a one-off.

    The ROOT instance carries `series_id == id`; `db.create_event` back-fills
    that after inserting the first row. A row with a recurrence but no
    `series_id` yet has not been promoted, and its own id is what the series
    will be keyed on.
    """
    if event.get("series_id"):
        return int(event["series_id"])
    return int(event["id"]) if event.get("recurrence") else None


@blueprint.get("/events/<int:event_id>/series")
def series_get(event_id: int):
    """Every instance of the series this event belongs to, plus its rule."""
    db, rid = sharing.for_request(event_id)
    event = db.get_event(rid)
    if event is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    series_id = _series_id_of(event)
    if series_id is None:
        return jsonify({"series_id": None, "recurrence": "",
                        "instances": [sharing.present(event)]})
    instances = sharing.present(db.get_series_events(series_id))
    return jsonify({
        "series_id": sharing.public_id(series_id),
        "recurrence": event.get("recurrence") or "",
        "recurrence_end": event.get("recurrence_end") or "",
        "recur_days": event.get("recur_days") or "",
        "count": len(instances),
        "instances": instances,
    })


@blueprint.patch("/events/<int:event_id>/series")
def series_update(event_id: int):
    """Edit the SERIES through one of its instances.

    Body is the same field names `PATCH /events/<id>` takes. `recurrence`
    ("daily" | "weekly" | "monthly" | "yearly") and `recurrence_end` (ISO date,
    "" for no end) are the two that change the SHAPE — `db.update_series`
    deletes the instances after this one and regenerates them, so extending an
    end date grows the series and shortening it trims. The end date is
    INCLUSIVE — the series' last possible day — and one before this event is a
    400, since trimming from here could not reach the instances between.

    A one-off is PROMOTED when the body names a recurrence, so "make this
    repeat weekly" is the same request as "change the cadence".
    """
    data = request.get_json(silent=True) or {}
    db, rid = sharing.for_request(event_id, edit=True)
    event = db.get_event(rid)
    if event is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    if db.is_event_locked(event):
        return jsonify({"error": "Event is read-only (synced source)", "code": 403}), 403

    base = str(data.pop("base_updated_at", "") or "")
    if base and str(event.get("updated_at") or "") not in ("", base):
        return jsonify({"error": "Event changed on the Mac since you edited it",
                        "code": 409, "current": sharing.present(event)}), 409

    cadence = str(data.get("recurrence", event.get("recurrence") or "")).strip()
    if cadence and cadence not in ("daily", "weekly", "monthly", "yearly"):
        return jsonify({"error": f"recurrence must be daily|weekly|monthly|yearly, "
                                 f"not {cadence!r}", "code": 400}), 400

    series_id = _series_id_of(event)
    if series_id is None:
        # A one-off being made to repeat: write the rule onto the row, then let
        # the existing promotion build the instances.
        if not cadence:
            return jsonify({"error": "This event does not repeat; send a "
                                     "`recurrence` to make it", "code": 400}), 400
        db.update_event(rid, **data)
        db.promote_to_series(rid)
        series_id = _series_id_of(db.get_event(rid) or event) or rid
    else:
        try:
            db.update_series(series_id, rid, **data)
        except ValueError as e:       # an end date before this event, or not a date
            return jsonify({"error": str(e), "code": 400}), 400

    instances = sharing.present(db.get_series_events(series_id))
    return jsonify({"series_id": sharing.public_id(series_id), "count": len(instances),
                    "instances": instances})


@blueprint.delete("/events/<int:event_id>/series")
def series_delete(event_id: int):
    """Delete the whole series, or `?scope=future` for this one and later.

    `scope=future` is the one people actually want when a weekly thing stops:
    the instances already gone by are a record of what happened.
    """
    db, rid = sharing.for_request(event_id, edit=True)
    event = db.get_event(rid)
    if event is None:
        return jsonify({"error": "Event not found", "code": 404}), 404
    if db.is_event_locked(event):
        return jsonify({"error": "Event is read-only (synced source)", "code": 403}), 403
    series_id = _series_id_of(event)
    if series_id is None:
        db.delete_event(rid)
        return jsonify({"deleted": 1, "series_id": None})
    if request.args.get("scope") == "future":
        removed = db.delete_series_from(series_id, str(event.get("date") or ""))
    else:
        removed = db.delete_series(series_id)
    return jsonify({"deleted": removed, "series_id": sharing.public_id(series_id)})


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

    events = sharing.gather(
        lambda d: [e for y, m in months for e in d.get_events_for_month(y, m)],
        sort_key=sharing.event_order)

    start = datetime.date(months[0][0], months[0][1], 1)
    last_y, last_m = months[-1]
    end = (datetime.date(last_y + last_m // 12, last_m % 12 + 1, 1)
           - datetime.timedelta(days=1))

    from assistant.occasions.feed import banners as _occasion_banners
    from assistant.occasions.feed import countdowns as _countdowns
    from assistant.occasions.feed import shown_holidays as _shown_holidays
    return jsonify({
        "token": change_token(),
        "server_time": datetime.datetime.now().astimezone().isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "events": annotate(events),
        "todos": sharing.gather(lambda d: d.get_todos(list_name=None, include_completed=False)),
        "tags": db.get_tags(),
        "tag_rules": tag_rules().get_json(),
        "category_rules": category_rules().get_json(),
        "categories": _cat.all_categories(),
        "holidays": [
            {
                "name_en": h.name_en,
                "name_he": h.name_he,
                "category": h.category,
                "gregorian_erev_start": h.gregorian_erev_start.isoformat(),
                "gregorian_end": h.gregorian_end.isoformat(),
            }
            for h in _shown_holidays(enumerate_holidays(start, end, israel=israel))
        ],
        # Occasions (Q73): every banner in the window — the person's own and
        # the calendars switched on — and the countdowns still ahead, so the
        # phone draws them with the Mac away.
        "occasions": _occasion_banners(start, end),
        "countdowns": _countdowns(),
        # When Shabbat / yom tov begins and ends over the same span, to the
        # second, so the calendars' yellow lines survive the Mac being away
        # (the same payload as GET /observance/windows).
        "holy_windows": _holy_windows(start, end, israel),
        "timers": [_timer_out(db, t) for t in db.get_timers()],
        "counters": [_counter_out(db, c) for c in db.get_counters()],
    })


def _holy_windows(start: datetime.date, end: datetime.date, israel: bool) -> "dict | None":
    """The windows for the bootstrap, or None if observance cannot be computed.

    None rather than a 500: a bootstrap is the phone's whole first screen, and
    losing it over the one part that is optional would be the wrong trade.
    """
    try:
        from assistant.observance import holy_windows_payload
        return holy_windows_payload(start, end, israel=israel)
    except Exception:                       # pragma: no cover - defensive
        return None


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

    # Settings ▸ Occasions ▸ which Jewish holidays show (display only).
    from assistant.occasions.feed import shown_holidays
    holidays = shown_holidays(enumerate_holidays(start, end, israel=israel))
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
