"""Timer's HTTP surface: `/timers*`, `/timer_sessions*`, `/counters*`, `/counter_presses*`.

A Flask blueprint rather than lines in `server.py`, per
`assistant/features/CONVENTION.md`: a surface owns a folder, declares itself
once to a registry, ships its own routes, and the generic layer never learns
its name.

| route | what |
|---|---|
| `GET/POST /timers` `PATCH/DELETE /timers/<id>` | the projects being tracked |
| `POST /timers/<id>/start` `POST /timers/<id>/stop` | the clock |
| `GET/POST /timers/<id>/sessions` | history, and logging time after the fact |
| `PATCH/DELETE /timer_sessions/<id>` | fix or drop one session |
| `GET/POST /counters` `PATCH/DELETE /counters/<id>` | the tally counters |
| `POST /counters/<id>/press` `GET /counters/<id>/presses` | count, and the log |
| `DELETE /counter_presses/<id>` | undo one press |
| `POST /counters/<id>/cashout` `GET /counters/<id>/payouts` | bank a cycle; its history |

No `url_prefix`: every path above is already absolute, and a prefix would move
all of them.

`_timer_out` and `_counter_out` are imported by `features/calendar/routes.py`
for `/sync/bootstrap`, which serves the same shapes rather than deriving a
second set.
"""

from __future__ import annotations

import datetime

from flask import Blueprint, jsonify, request

blueprint = Blueprint("timer", __name__)


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
# Timers & counters (shared with the Mac Timer tab; same DB tables)
# ------------------------------------------------------------------

def _dt(iso: str) -> datetime.datetime:
    try:
        d = datetime.datetime.fromisoformat(iso)
    except Exception:
        return datetime.datetime.now().astimezone()
    return d if d.tzinfo else d.astimezone()


def _secs(start: str, end: str | None) -> float:
    e = _dt(end) if end else datetime.datetime.now().astimezone()
    return max(0.0, (e - _dt(start)).total_seconds())


def _session_out(sess: dict) -> dict:
    out = dict(sess)
    out["seconds"] = round(_secs(sess["start_time"], sess.get("end_time")), 1)
    out["running"] = sess.get("end_time") in (None, "")
    # The same instants as unambiguous numbers, beside the strings.
    #
    # `start_time` is what `datetime.now().astimezone().isoformat()` wrote,
    # which is six fractional digits — and iOS's ISO8601DateFormatter parses
    # exactly three, so the phone read nil for every running session the Mac
    # had started and its live counter sat at 00:00 while the Mac counted
    # up. The phone's parser is fixed, but a clock is the wrong place to
    # depend on a string format at all: a client that reads these needs no
    # parser, no timezone rule and no fractional-digit opinion.
    out["start_epoch"] = _dt(sess["start_time"]).timestamp()
    out["end_epoch"] = (_dt(sess["end_time"]).timestamp()
                        if sess.get("end_time") else None)
    return out


def _enforce_max(db, timer: dict, running: dict | None) -> dict | None:
    """Mirror the Mac's auto-stop: a running session past max_session_minutes is closed at the limit."""
    limit = int(timer.get("max_session_minutes") or 0)
    if running and limit > 0:
        cutoff = _dt(running["start_time"]) + datetime.timedelta(minutes=limit)
        if datetime.datetime.now().astimezone() >= cutoff:
            db.stop_timer_session(running["id"], cutoff.isoformat())
            return None
    return running


def _timer_out(db, t: dict) -> dict:
    sessions = db.get_timer_sessions(t["id"])
    running = _enforce_max(db, t, next((x for x in sessions if not x.get("end_time")), None))
    today = datetime.date.today().isoformat()
    total = sum(_secs(x["start_time"], x.get("end_time")) for x in sessions)
    today_s = sum(_secs(x["start_time"], x.get("end_time")) for x in sessions if x["start_time"][:10] == today)
    out = dict(t)
    out["running"] = _session_out(running) if running else None
    out["total_seconds"] = round(total, 1)
    out["today_seconds"] = round(today_s, 1)
    out["session_count"] = len(sessions)
    out["earnings"] = round(total / 3600 * float(t.get("hourly_rate") or 0), 2)
    return out


@blueprint.get("/timers")
def timers_list():
    db = get_db()
    inc = request.args.get("archived") == "1"
    return jsonify({"timers": [_timer_out(db, t) for t in db.get_timers(include_archived=inc)]})


@blueprint.post("/timers")
def timers_create():
    b = request.get_json(silent=True) or {}
    db = get_db()
    tid = db.create_timer(title=str(b.get("title") or "Untitled Timer"), hourly_rate=float(b.get("hourly_rate") or 0),
                          color=str(b.get("color") or "#1a6fc4"), timer_type=str(b.get("timer_type") or "work"),
                          currency=str(b.get("currency") or "ILS"), max_session_minutes=int(b.get("max_session_minutes") or 0))
    t = next(x for x in db.get_timers(include_archived=True) if x["id"] == tid)
    return jsonify(_timer_out(db, t)), 201


@blueprint.patch("/timers/<int:tid>")
def timers_update(tid: int):
    b = request.get_json(silent=True) or {}
    db = get_db()
    db.update_timer(tid, **{k: v for k, v in b.items()})
    t = next((x for x in db.get_timers(include_archived=True) if x["id"] == tid), None)
    if not t:
        return jsonify({"error": "Not found", "code": 404}), 404
    return jsonify(_timer_out(db, t))


@blueprint.delete("/timers/<int:tid>")
def timers_delete(tid: int):
    get_db().delete_timer(tid)
    return jsonify({"ok": True})


@blueprint.post("/timers/<int:tid>/start")
def timers_start(tid: int):
    b = request.get_json(silent=True) or {}
    db = get_db()
    run = db.get_running_session(tid)
    if run:
        return jsonify(_session_out(run))
    sid = db.create_timer_session(tid, title=str(b.get("title") or ""))
    return jsonify(_session_out(next(x for x in db.get_timer_sessions(tid) if x["id"] == sid))), 201


@blueprint.post("/timers/<int:tid>/stop")
def timers_stop(tid: int):
    db = get_db()
    run = db.get_running_session(tid)
    if not run:
        return jsonify({"error": "Not running", "code": 409}), 409
    db.stop_timer_session(run["id"])
    return jsonify(_session_out(next(x for x in db.get_timer_sessions(tid) if x["id"] == run["id"])))


@blueprint.get("/timers/<int:tid>/sessions")
def timers_sessions(tid: int):
    return jsonify({"sessions": [_session_out(x) for x in reversed(get_db().get_timer_sessions(tid))]})


@blueprint.post("/timers/<int:tid>/sessions")
def timers_session_create(tid: int):
    """Log a session that already happened ("I forgot to start the timer").

    The Mac's Timer tab has had this as "Log past time…" since the feature
    landed; this is the same thing for the phone. `start_time` is required,
    `end_time` optional (omit it to create a session that is still running).
    """
    b = request.get_json(silent=True) or {}
    start = str(b.get("start_time") or "").strip()
    if not start:
        return jsonify({"error": "start_time is required", "code": 400}), 400
    db = get_db()
    sid = db.create_timer_session(tid, title=str(b.get("title") or ""), start_time=start)
    end = str(b.get("end_time") or "").strip()
    if end:
        db.update_timer_session(sid, end_time=end)
    session = next((x for x in db.get_timer_sessions(tid) if x["id"] == sid), None)
    if session is None:
        return jsonify({"error": "Not found", "code": 404}), 404
    return jsonify(_session_out(session)), 201


@blueprint.patch("/timer_sessions/<int:sid>")
def timer_session_update(sid: int):
    b = request.get_json(silent=True) or {}
    get_db().update_timer_session(sid, **b)
    return jsonify({"ok": True})


@blueprint.delete("/timer_sessions/<int:sid>")
def timer_session_delete(sid: int):
    get_db().delete_timer_session(sid)
    return jsonify({"ok": True})


def _counter_out(db, c: dict) -> dict:
    presses = db.get_counter_presses(c["id"])
    cycle = db.get_counter_cycle_start(c["id"])
    in_cycle = [p for p in presses if not cycle or p["pressed_at"] > cycle]
    today = datetime.date.today().isoformat()
    out = dict(c)
    out["count"] = sum(int(p["delta"]) for p in in_cycle)
    out["total_count"] = sum(int(p["delta"]) for p in presses)
    out["today_count"] = sum(int(p["delta"]) for p in presses if p["pressed_at"][:10] == today)
    out["cycle_started_at"] = cycle
    out["payout"] = round(out["count"] * float(c.get("price_per_unit") or 0), 2)
    return out


@blueprint.get("/counters")
def counters_list():
    db = get_db()
    inc = request.args.get("archived") == "1"
    return jsonify({"counters": [_counter_out(db, c) for c in db.get_counters(include_archived=inc)]})


@blueprint.post("/counters")
def counters_create():
    b = request.get_json(silent=True) or {}
    db = get_db()
    cid = db.create_counter(title=str(b.get("title") or "Untitled Counter"), price_per_unit=float(b.get("price_per_unit") or 0),
                            currency=str(b.get("currency") or "ILS"), color=str(b.get("color") or "#1a6fc4"))
    return jsonify(_counter_out(db, next(x for x in db.get_counters(include_archived=True) if x["id"] == cid))), 201


@blueprint.patch("/counters/<int:cid>")
def counters_update(cid: int):
    b = request.get_json(silent=True) or {}
    db = get_db()
    db.update_counter(cid, **b)
    c = next((x for x in db.get_counters(include_archived=True) if x["id"] == cid), None)
    if not c:
        return jsonify({"error": "Not found", "code": 404}), 404
    return jsonify(_counter_out(db, c))


@blueprint.delete("/counters/<int:cid>")
def counters_delete(cid: int):
    get_db().delete_counter(cid)
    return jsonify({"ok": True})


@blueprint.post("/counters/<int:cid>/press")
def counters_press(cid: int):
    b = request.get_json(silent=True) or {}
    db = get_db()
    db.create_counter_press(cid, delta=int(b.get("delta") or 1), label=str(b.get("label") or ""))
    return jsonify(_counter_out(db, next(x for x in db.get_counters(include_archived=True) if x["id"] == cid)))


@blueprint.get("/counters/<int:cid>/presses")
def counters_presses(cid: int):
    return jsonify({"presses": list(reversed(get_db().get_counter_presses(cid)))})


@blueprint.delete("/counter_presses/<int:pid>")
def counter_press_delete(pid: int):
    get_db().delete_counter_press(pid)
    return jsonify({"ok": True})


@blueprint.post("/counters/<int:cid>/cashout")
def counters_cashout(cid: int):
    b = request.get_json(silent=True) or {}
    db = get_db()
    c = next((x for x in db.get_counters(include_archived=True) if x["id"] == cid), None)
    if not c:
        return jsonify({"error": "Not found", "code": 404}), 404
    info = _counter_out(db, c)
    now = datetime.datetime.now().astimezone().isoformat()
    cycle_start = info["cycle_started_at"] or (db.get_counter_presses(cid) or [{"pressed_at": c["created_at"]}])[0]["pressed_at"]
    amount = b.get("amount")
    amount = float(amount) if amount is not None else info["payout"]
    db.create_counter_payout(cid, cycle_start, now, info["count"], amount, c["currency"], note=str(b.get("note") or ""))
    return jsonify(_counter_out(db, c)), 201


@blueprint.get("/counters/<int:cid>/payouts")
def counters_payouts(cid: int):
    return jsonify({"payouts": get_db().get_counter_payouts(cid)})
