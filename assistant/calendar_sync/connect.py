"""Connecting, disconnecting and describing calendar accounts — from either app.

The brain is the one place that holds tokens and runs the sync; the Mac and
the phone only START a sign-in and SHOW its state. So every flow lives here, in
memory, keyed by an id the client polls:

* **Outlook** — Microsoft's device-code flow. `outlook_start` returns the code
  and https://microsoft.com/devicelogin; a thread here waits for the sign-in to
  finish (MSAL polls Microsoft). Identical on Mac and phone.
* **Google, from the Mac** — PKCE + a loopback listener on 127.0.0.1 (the
  Desktop client). The Mac opens the URL in its browser; the listener catches
  the code and this module exchanges it.
* **Google, from the phone** — PKCE with the iOS client. The phone opens the URL
  in ASWebAuthenticationSession and posts the code to `google_complete`, which
  exchanges it with the verifier it kept.

With no client configured each provider reports `setup_needed` and a hint, and
the start calls raise `SetupNeeded` — the apps show "set-up needed — see steps"
rather than failing.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
from typing import Optional

from assistant.calendar_sync import google_oauth, scheduler
from assistant.db import _utcnow_iso
from assistant.exceptions import AuthError

logger = logging.getLogger(__name__)

GUIDE = "DOCUMENTATION/CALENDAR_SYNC.md"
_FLOW_TTL_S = 15 * 60
PROVIDERS = ("google", "outlook")


class SetupNeeded(Exception):
    """No OAuth client is configured for this provider/surface yet."""


class FlowError(Exception):
    """A complete call that does not match a pending flow."""


_flows: dict[str, dict] = {}
_flows_lock = threading.Lock()


def _new_flow(provider: str, **extra) -> dict:
    flow = {"id": secrets.token_urlsafe(16), "provider": provider, "state": "pending",
            "error": "", "account": "", "created": time.time(), **extra}
    with _flows_lock:
        now = time.time()
        for fid in [k for k, f in _flows.items() if now - f["created"] > _FLOW_TTL_S]:
            _flows.pop(fid, None)
        _flows[flow["id"]] = flow
    return flow


def _public(flow: dict) -> dict:
    keys = ("id", "provider", "state", "error", "account", "user_code",
            "verification_uri", "message", "auth_url", "redirect_uri",
            "callback_scheme", "platform", "expires_in")
    return {k: flow[k] for k in keys if k in flow}


def flow_status(flow_id: str) -> Optional[dict]:
    with _flows_lock:
        flow = _flows.get(flow_id)
    return _public(flow) if flow else None


def _finish(flow: dict, *, error: str = "", account: str = "") -> None:
    flow["state"] = "error" if error else "done"
    flow["error"] = error
    flow["account"] = account
    loop = flow.pop("_receiver", None)
    if loop is not None and error:
        loop.close()


def _ensure_source(db, kind: str, label: str, account: str, color: str) -> dict:
    src = db.get_calendar_source_by_kind(kind)
    if src is None:
        db.create_calendar_source(kind=kind, label=label, color=color, two_way=True)
        src = db.get_calendar_source_by_kind(kind)
    db.update_calendar_source(src["id"], account=account, last_error="", enabled=1)
    return db.get_calendar_source_by_kind(kind)


# ---------------------------------------------------------------------------
# Outlook
# ---------------------------------------------------------------------------

def outlook_start(db, config, auth_factory=None) -> dict:
    if config.microsoft is None or not config.microsoft.client_id:
        raise SetupNeeded("Outlook needs a client id — see " + GUIDE)
    if auth_factory is None:
        from assistant.actions.calendar.auth import MSALAuth as auth_factory
    auth = auth_factory(config.microsoft)
    ms_flow = auth.start_device_flow()
    flow = _new_flow("outlook",
                     user_code=ms_flow.get("user_code", ""),
                     verification_uri=ms_flow.get("verification_uri")
                     or "https://microsoft.com/devicelogin",
                     message=ms_flow.get("message", ""),
                     expires_in=int(ms_flow.get("expires_in") or 900))

    def _wait() -> None:
        try:
            auth.complete_device_flow(ms_flow)      # blocks until signed in or expired
            account = ""
            try:
                account = auth.account_name()
            except Exception:
                pass
            _ensure_source(db, "outlook", "Outlook", account, "#0078d4")
            _finish(flow, account=account)
            scheduler.sync_in_background()
        except Exception as e:  # noqa: BLE001 — surfaced through the flow's status
            _finish(flow, error=str(e))

    threading.Thread(target=_wait, daemon=True, name="outlook-device-flow").start()
    return _public(flow)


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

def google_start(db, config, platform: str = "mac", session=None) -> dict:
    g = config.google_calendar
    if not g.enabled:
        raise SetupNeeded("Google Calendar is switched off (google_calendar.enabled).")
    verifier, challenge = google_oauth.make_pkce()
    state = secrets.token_urlsafe(24)

    if platform == "ios":
        client = google_oauth.ios_client(g)
        if client is None:
            raise SetupNeeded("Signing in from the phone needs an iOS OAuth client id "
                              "(google_calendar.ios_client_id) — see " + GUIDE)
        scheme, redirect = google_oauth.ios_redirect(client.client_id)
        flow = _new_flow("google", platform="ios", callback_scheme=scheme,
                         redirect_uri=redirect, _client=client, _verifier=verifier,
                         _state=state)
        flow["auth_url"] = google_oauth.build_auth_url(client, redirect, state, challenge)
        return _public(flow)

    client = google_oauth.desktop_client(g)
    if client is None:
        raise SetupNeeded("Signing in from the Mac needs the Desktop OAuth client JSON at "
                          f"{google_oauth.client_secret_path(g)} — see " + GUIDE)
    flow = _new_flow("google", platform="mac", _client=client, _verifier=verifier,
                     _state=state)

    def _on_redirect(code: str, got_state: str, error: str) -> None:
        if error or not code:
            _finish(flow, error="Sign-in was cancelled." if error != "timeout"
                    else "Sign-in timed out — try Connect again.")
            return
        try:
            _complete(db, flow, code, got_state, session=session)
        except Exception as e:  # noqa: BLE001
            _finish(flow, error=str(e))

    receiver = google_oauth.LoopbackReceiver(_on_redirect)
    flow["_receiver"] = receiver
    flow["redirect_uri"] = receiver.redirect_uri
    flow["auth_url"] = google_oauth.build_auth_url(client, receiver.redirect_uri, state, challenge)
    receiver.start()
    return _public(flow)


def _complete(db, flow: dict, code: str, got_state: str, session=None) -> dict:
    if flow["state"] != "pending":
        raise FlowError("This sign-in has already finished — start again.")
    if not secrets.compare_digest(got_state or "", flow["_state"]):
        raise FlowError("The sign-in answer does not match this request (state mismatch).")
    try:
        token = google_oauth.exchange_code(flow["_client"], code, flow["_verifier"],
                                           flow["redirect_uri"], session=session)
    except AuthError as e:
        _finish(flow, error=str(e))
        raise
    google_oauth.save_token(token)
    src = _ensure_source(db, "google", "Google Calendar", token.get("account", ""), "#4285f4")
    # A new account must not resume the previous account's cursor.
    db.update_calendar_source(src["id"], sync_token="")
    _finish(flow, account=token.get("account", ""))
    scheduler.sync_in_background()
    return _public(flow)


def google_complete(db, flow_id: str = "", state: str = "", code: str = "",
                    callback_url: str = "", session=None) -> dict:
    """The phone's half: it caught the redirect and hands over the code.
    Accepts the raw callback URL too, so the app need not parse it."""
    if callback_url:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query)
        if (qs.get("error") or [""])[0]:
            err = qs["error"][0]
            flow = _find_google_flow(flow_id, (qs.get("state") or [state])[0])
            if flow:
                _finish(flow, error=f"Google: {err}")
            raise FlowError(f"Google: {err}")
        code = code or (qs.get("code") or [""])[0]
        state = state or (qs.get("state") or [""])[0]
    if not code:
        raise FlowError("No authorization code in the answer.")
    flow = _find_google_flow(flow_id, state)
    if flow is None:
        raise FlowError("No sign-in is waiting for that answer — it may have expired. Start again.")
    return _complete(db, flow, code, state, session=session)


def _find_google_flow(flow_id: str, state: str) -> Optional[dict]:
    with _flows_lock:
        if flow_id and flow_id in _flows:
            return _flows[flow_id]
        for f in _flows.values():
            if f["provider"] == "google" and state and f.get("_state") == state:
                return f
    return None


# ---------------------------------------------------------------------------
# Disconnect, set-up, status
# ---------------------------------------------------------------------------

def disconnect(db, config, provider: str, keep_events: bool = True, session=None) -> dict:
    """Sign out and stop syncing. The synced events are KEPT as plain local
    events by default (deleting is destructive — they may include events you
    mirrored up); `keep_events=False` removes them instead."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    if provider == "google":
        token = google_oauth.load_token()
        if token:
            google_oauth.revoke(token, session=session)
        google_oauth.delete_token()
    elif config.microsoft is not None:
        try:
            from assistant.actions.calendar.auth import MSALAuth
            MSALAuth(config.microsoft).sign_out()
        except Exception as e:  # noqa: BLE001
            logger.info("Outlook sign-out: %s", e)
    changed = db.release_synced_events(provider, keep=keep_events)
    src = db.get_calendar_source_by_kind(provider)
    if src:
        db.delete_calendar_source(src["id"])
    return {"provider": provider, "disconnected": True,
            "events_kept" if keep_events else "events_removed": changed}


def save_google_desktop_client(config, raw) -> str:
    """Store the Desktop client JSON (pasted or picked on the Mac). Returns the
    path written. Raises ValueError if it is not a Desktop client."""
    data = json.loads(raw) if isinstance(raw, str) else raw
    if google_oauth.parse_client_json(data) is None:
        raise ValueError("That is not a Desktop-app OAuth client JSON (it needs an "
                         "\"installed\" block with a client_id). See " + GUIDE)
    path = google_oauth.client_secret_path(config.google_calendar)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)
    return path


def save_client_ids(outlook_client_id: Optional[str] = None,
                    google_ios_client_id: Optional[str] = None) -> list[str]:
    """Write client ids into config.yaml, preserving the rest of the file."""
    from assistant.features import yaml_text
    from assistant.features.settings import config_path
    import yaml

    path = config_path()
    with open(path) as f:
        text = f.read()
    written = []
    if outlook_client_id is not None:
        text = yaml_text.set_nested(text, "microsoft", "client_id", outlook_client_id.strip())
        written.append("microsoft.client_id")
    if google_ios_client_id is not None:
        text = yaml_text.set_nested(text, "google_calendar", "ios_client_id",
                                    google_ios_client_id.strip())
        written.append("google_calendar.ios_client_id")
    yaml.safe_load(text)                      # must still parse, or the brain cannot boot
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)
    return written


def _pending_flow(provider: str) -> Optional[dict]:
    with _flows_lock:
        pending = [f for f in _flows.values() if f["provider"] == provider and f["state"] == "pending"]
    return _public(pending[-1]) if pending else None


def status(db, config) -> dict:
    """Everything a Settings screen shows, in one answer."""
    g = config.google_calendar
    desktop = google_oauth.desktop_client(g) is not None
    ios = google_oauth.ios_client(g) is not None
    outlook_ok = config.microsoft is not None and bool(config.microsoft.client_id)

    def provider(kind: str, configured: bool, setup: dict, hint: str) -> dict:
        src = db.get_calendar_source_by_kind(kind)
        return {
            "configured": configured,
            "setup_needed": not configured,
            "setup": setup,
            "setup_hint": "" if configured else hint,
            "connected": src is not None,
            "account": (src or {}).get("account", ""),
            "source_id": (src or {}).get("id"),
            "two_way": bool((src or {}).get("two_way")),
            "last_synced": (src or {}).get("last_synced", ""),
            "last_error": (src or {}).get("last_error", ""),
            "pending_flow": _pending_flow(kind),
        }

    subs = [{k: s.get(k) for k in ("id", "label", "url", "color", "enabled",
                                   "last_synced", "last_error")}
            for s in db.get_calendar_sources() if s["kind"] == "ics_url"]
    return {
        "enabled": config.calendar_sync.enabled,
        "interval_minutes": config.calendar_sync.interval_minutes,
        **scheduler.state(),
        "guide": GUIDE,
        "providers": {
            "google": provider(
                "google", g.enabled and (desktop or ios), {"mac": desktop, "ios": ios},
                "Set-up needed: create a Google Cloud OAuth client — see " + GUIDE),
            "outlook": provider(
                "outlook", outlook_ok, {"mac": outlook_ok, "ios": outlook_ok},
                "Set-up needed: register a free Entra app and add its client id — see " + GUIDE),
        },
        "subscriptions": subs,
        "now": _utcnow_iso(),
    }
