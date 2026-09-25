"""HTTP for connected calendars: start a sign-in, finish one, see status,
disconnect, sync now. Plumbing only — every decision is in `connect.py`,
`scheduler.py` and the provider modules; nothing here parses or executes a
command, so the brain is never reachable through these routes.

    GET  /calendar_sync/status                 everything Settings shows
    POST /calendar_sync/sync                   sync now ({"wait": true} to block)
    POST /calendar_sync/google/start           {"platform": "mac"|"ios"}
    POST /calendar_sync/google/complete        {"flow_id", "code", "state"} or {"callback_url"}
    POST /calendar_sync/outlook/start          device code + URL
    GET  /calendar_sync/flows/<id>             a sign-in's progress
    POST /calendar_sync/<provider>/disconnect  {"keep_events": true}
    POST /calendar_sync/google/client          the Desktop client JSON (Mac set-up)
    PUT  /calendar_sync/setup                  {"outlook_client_id", "google_ios_client_id"}
    POST /calendar_sync/google/mirror          {"event_id"} — push one local event to Google
"""

from __future__ import annotations

from flask import Blueprint, Flask, jsonify, request

from assistant.calendar_sync import connect, scheduler

bp = Blueprint("calendar_sync", __name__, url_prefix="/calendar_sync")


def _db():
    from assistant.db import get_db
    return get_db()


def _cfg():
    from assistant.config import load_config
    return load_config()


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _setup_needed(e: Exception):
    return jsonify({"error": str(e), "setup_needed": True, "guide": connect.GUIDE,
                    "code": 409}), 409


@bp.get("/status")
def status():
    """Everything Settings shows: providers, accounts, last sync, errors, ICS links."""
    return jsonify(connect.status(_db(), _cfg()))


@bp.post("/sync")
def sync():
    """Sync every connected calendar now. {"wait": true} blocks and returns the results."""
    if _body().get("wait"):
        results = scheduler.sync_now()
        if results.get("busy"):
            return jsonify({"started": False, "busy": True}), 202
        return jsonify({"started": True, "finished": True, "results": results})
    started = scheduler.sync_in_background()
    return jsonify({"started": started, "busy": not started}), 202


@bp.post("/google/start")
def google_start():
    """Start a Google sign-in. {"platform": "mac"|"ios"} → auth_url (+ callback_scheme on iOS)."""
    platform = str(_body().get("platform") or "mac")
    if platform not in ("mac", "ios"):
        return jsonify({"error": "platform must be 'mac' or 'ios'", "code": 400}), 400
    try:
        return jsonify(connect.google_start(_db(), _cfg(), platform=platform))
    except connect.SetupNeeded as e:
        return _setup_needed(e)


@bp.post("/google/complete")
def google_complete():
    """Finish a phone Google sign-in: {"flow_id", "callback_url"} or {"code", "state"}."""
    b = _body()
    try:
        flow = connect.google_complete(_db(), flow_id=str(b.get("flow_id") or ""),
                                       state=str(b.get("state") or ""),
                                       code=str(b.get("code") or ""),
                                       callback_url=str(b.get("callback_url") or ""))
    except connect.FlowError as e:
        return jsonify({"error": str(e), "code": 400}), 400
    except Exception as e:  # noqa: BLE001 — Google refused the code
        return jsonify({"error": str(e), "code": 502}), 502
    return jsonify(flow)


@bp.post("/outlook/start")
def outlook_start():
    """Start an Outlook device-code sign-in → user_code + verification_uri."""
    try:
        return jsonify(connect.outlook_start(_db(), _cfg()))
    except connect.SetupNeeded as e:
        return _setup_needed(e)
    except Exception as e:  # noqa: BLE001 — Microsoft unreachable, bad client id
        return jsonify({"error": str(e), "code": 502}), 502


@bp.get("/flows/<flow_id>")
def flow(flow_id: str):
    """A sign-in's progress: pending | done | error."""
    f = connect.flow_status(flow_id)
    if f is None:
        return jsonify({"error": "no such sign-in (it may have expired)", "code": 404}), 404
    return jsonify(f)


@bp.post("/<provider>/disconnect")
def disconnect(provider: str):
    """Sign out of google|outlook. {"keep_events": true} keeps synced events as local."""
    if provider not in connect.PROVIDERS:
        return jsonify({"error": f"unknown provider {provider!r}", "code": 404}), 404
    keep = _body().get("keep_events", True)
    return jsonify(connect.disconnect(_db(), _cfg(), provider, keep_events=bool(keep)))


@bp.post("/google/client")
def google_client():
    """Store the Google Desktop OAuth client JSON: {"client_json": "..."}."""
    b = _body()
    raw = b.get("client_json", b.get("installed") and b)
    if not raw:
        return jsonify({"error": "send the downloaded JSON as client_json", "code": 400}), 400
    try:
        path = connect.save_google_desktop_client(_cfg(), raw)
    except ValueError as e:
        return jsonify({"error": str(e), "code": 400}), 400
    return jsonify({"saved": True, "path": path})


@bp.put("/setup")
def setup():
    """Save client ids to config.yaml: {"outlook_client_id", "google_ios_client_id"}."""
    b = _body()
    outlook = b.get("outlook_client_id")
    ios = b.get("google_ios_client_id")
    if outlook is None and ios is None:
        return jsonify({"error": "nothing to set", "code": 400}), 400
    written = connect.save_client_ids(
        outlook_client_id=None if outlook is None else str(outlook),
        google_ios_client_id=None if ios is None else str(ios))
    return jsonify({"written": written})


@bp.post("/google/mirror")
def google_mirror():
    """Push one plain local event to Google from now on: {"event_id"}."""
    try:
        event_id = int(_body().get("event_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "event_id is required", "code": 400}), 400
    if _db().get_calendar_source_by_kind("google") is None:
        return jsonify({"error": "Google is not connected", "code": 409}), 409
    if not _db().mark_for_push(event_id, "google"):
        return jsonify({"error": "only a plain local, non-recurring event can be mirrored",
                        "code": 409}), 409
    scheduler.sync_in_background()
    return jsonify({"event_id": event_id, "mirrored": True})


def register(app: Flask, background: bool = False) -> None:
    """Mount the routes; with *background*, also start the periodic sync."""
    app.register_blueprint(bp)
    if background:
        scheduler.start_background()
