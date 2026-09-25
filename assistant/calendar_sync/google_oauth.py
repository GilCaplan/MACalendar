"""Google OAuth 2.0 for the Calendar sync — authorization code + PKCE.

Google's device flow does not allow Calendar scopes, so both surfaces use the
authorization-code flow with PKCE, each with the OAuth client Google makes for
that kind of app:

* **Mac** — a "Desktop app" client (its JSON, with a client secret Google
  documents as not secret for installed apps). The brain listens once on
  `127.0.0.1:<ephemeral port>`, the browser on the Mac is sent there after
  sign-in, and the brain exchanges the code itself.
* **iPhone** — an "iOS" client (no secret), redirect
  `com.googleusercontent.apps.<id>:/oauth2redirect`. The phone opens the URL in
  `ASWebAuthenticationSession`, catches the redirect, and posts the code back;
  the brain holds the PKCE verifier and does the exchange.

Either way the TOKENS live only on the Mac (`MACALENDAR_GOOGLE_TOKEN`, default
`~/.assistant_tools/google_token.json`, mode 0600) together with the client
that issued them — a refresh token can only be refreshed by its own client.

Plain `requests` rather than google-auth / google-api-python-client: three
POSTs do not justify two dependencies, and every call here is easy to mock.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from assistant.exceptions import AuthError, AuthExpiredError

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# calendar.events: read and write events, nothing else about the account.
# openid + email: only so the Settings row can say WHICH account is connected.
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/calendar.events"]

_DEFAULT_TOKEN_PATH = "~/.assistant_tools/google_token.json"
_EXPIRY_SKEW_S = 60


def token_path() -> str:
    return os.path.expanduser(os.environ.get("MACALENDAR_GOOGLE_TOKEN") or _DEFAULT_TOKEN_PATH)


def client_secret_path(cfg) -> str:
    """Where the Desktop client JSON lives. MACALENDAR_GOOGLE_CLIENT_SECRET
    overrides it so a test can never read (or write) the real one."""
    return os.path.expanduser(os.environ.get("MACALENDAR_GOOGLE_CLIENT_SECRET")
                              or cfg.client_secret_path)


@dataclass(frozen=True)
class OAuthClient:
    kind: str                    # "desktop" | "ios"
    client_id: str
    client_secret: str = ""


def desktop_client(cfg) -> Optional[OAuthClient]:
    """The Desktop client from its downloaded JSON, or None when absent/invalid."""
    path = client_secret_path(cfg)
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return parse_client_json(data)


def parse_client_json(data) -> Optional[OAuthClient]:
    """Google's client JSON is {"installed": {...}} for a Desktop client
    ({"web": {...}} for a web one, which cannot use a loopback redirect)."""
    if not isinstance(data, dict):
        return None
    block = data.get("installed")
    if not isinstance(block, dict):
        return None
    cid = str(block.get("client_id") or "").strip()
    if not cid:
        return None
    return OAuthClient("desktop", cid, str(block.get("client_secret") or ""))


def ios_client(cfg) -> Optional[OAuthClient]:
    cid = (cfg.ios_client_id or "").strip()
    return OAuthClient("ios", cid) if cid else None


def ios_redirect(client_id: str) -> tuple[str, str]:
    """(callback scheme, redirect uri) Google assigns an iOS client: the client
    id reversed, e.g. com.googleusercontent.apps.1234-abc:/oauth2redirect."""
    prefix = client_id.removesuffix(".apps.googleusercontent.com")
    scheme = f"com.googleusercontent.apps.{prefix}"
    return scheme, f"{scheme}:/oauth2redirect"


def make_pkce() -> tuple[str, str]:
    """(verifier, S256 challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(client: OAuthClient, redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # offline + consent: always hand back a refresh token, including on a
        # reconnect (Google otherwise only sends one the first time).
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def email_from_id_token(id_token: str) -> str:
    """The `email` claim of an ID token. Not verified: it came straight from
    Google's token endpoint over TLS and only labels the Settings row."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return str(json.loads(base64.urlsafe_b64decode(payload)).get("email") or "")
    except Exception:
        return ""


def _token_error(resp: requests.Response) -> tuple[str, str]:
    try:
        body = resp.json()
        return str(body.get("error") or ""), str(body.get("error_description") or "")
    except ValueError:
        return "", resp.text[:200]


def exchange_code(client: OAuthClient, code: str, verifier: str, redirect_uri: str,
                  session=None) -> dict:
    """Trade an authorization code for tokens. Returns the stored token dict."""
    http = session or requests
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    if client.client_secret:
        data["client_secret"] = client.client_secret
    resp = http.post(TOKEN_URL, data=data, timeout=30)
    if not resp.ok:
        err, desc = _token_error(resp)
        raise AuthError(f"Google refused the sign-in: {err} {desc}".strip())
    body = resp.json()
    if not body.get("refresh_token"):
        raise AuthError(
            "Google returned no refresh token. Remove MACalendar at "
            "myaccount.google.com/permissions and connect again.")
    return {
        "client_kind": client.kind,
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "refresh_token": body["refresh_token"],
        "access_token": body.get("access_token", ""),
        "expires_at": time.time() + float(body.get("expires_in") or 0),
        "scope": body.get("scope", ""),
        "account": email_from_id_token(body.get("id_token", "")),
    }


# ---------------------------------------------------------------------------
# Token store
# ---------------------------------------------------------------------------

def load_token() -> Optional[dict]:
    try:
        with open(token_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("refresh_token") else None
    except (OSError, ValueError):
        return None


def save_token(token: dict) -> None:
    path = token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(token, f)
    os.replace(tmp, path)


def delete_token() -> None:
    try:
        os.remove(token_path())
    except FileNotFoundError:
        pass


def revoke(token: dict, session=None) -> None:
    """Best effort: tell Google to forget the grant. Disconnect proceeds
    whether or not this reaches it."""
    http = session or requests
    try:
        http.post(REVOKE_URL, data={"token": token.get("refresh_token", "")}, timeout=10)
    except Exception as e:  # noqa: BLE001 — offline disconnect still disconnects
        logger.info("Google revoke failed (disconnecting anyway): %s", e)


class GoogleAuth:
    """Hands out a valid access token, refreshing it with the stored refresh
    token (and the client that issued it) when it is about to expire."""

    def __init__(self, token: Optional[dict] = None, session=None) -> None:
        self._token = token if token is not None else load_token()
        self._http = session or requests
        self._lock = threading.Lock()

    @property
    def token(self) -> Optional[dict]:
        return self._token

    def get_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            tok = self._token
            if not tok:
                raise AuthExpiredError("Google is not connected.")
            fresh = tok.get("access_token") and time.time() < float(tok.get("expires_at") or 0) - _EXPIRY_SKEW_S
            if fresh and not force_refresh:
                return tok["access_token"]
            data = {
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
                "client_id": tok.get("client_id", ""),
            }
            if tok.get("client_secret"):
                data["client_secret"] = tok["client_secret"]
            resp = self._http.post(TOKEN_URL, data=data, timeout=30)
            if not resp.ok:
                err, desc = _token_error(resp)
                if err in ("invalid_grant", "unauthorized_client", "invalid_client"):
                    # Revoked, expired (a "Testing" app's tokens die after 7
                    # days) or the client was deleted: only a new sign-in helps.
                    raise AuthExpiredError(f"Google sign-in expired — reconnect ({err}).")
                raise AuthError(f"Google token refresh failed: {resp.status_code} {err} {desc}".strip())
            body = resp.json()
            tok = {**tok,
                   "access_token": body.get("access_token", ""),
                   "expires_at": time.time() + float(body.get("expires_in") or 0)}
            if body.get("refresh_token"):
                tok["refresh_token"] = body["refresh_token"]
            self._token = tok
            save_token(tok)
            return tok["access_token"]


# ---------------------------------------------------------------------------
# Loopback receiver (Mac sign-in)
# ---------------------------------------------------------------------------

_DONE_PAGE = (b"<!doctype html><meta charset=utf-8><title>MACalendar</title>"
              b"<body style='font-family:-apple-system,sans-serif;padding:3em'>"
              b"<h2>%s</h2><p>You can close this tab and go back to MACalendar.</p>")


class LoopbackReceiver:
    """A one-shot HTTP listener on 127.0.0.1 that catches Google's redirect.

    `on_result(code, state, error)` is called once, from the listener thread;
    the listener then shuts itself down. It also gives up after `timeout_s`.
    """

    def __init__(self, on_result: Callable[[str, str, str], None], timeout_s: float = 600) -> None:
        self._on_result = on_result
        self._fired = threading.Event()
        receiver = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — http.server's naming
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                code = (qs.get("code") or [""])[0]
                state = (qs.get("state") or [""])[0]
                error = (qs.get("error") or [""])[0]
                if not code and not error:
                    self.send_response(404)
                    self.end_headers()
                    return
                ok = bool(code)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_DONE_PAGE % (b"Connected." if ok else b"Sign-in was cancelled."))
                receiver._fire(code, state, error)

            def log_message(self, *args):  # keep the brain's log clean
                pass

        self._server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self.redirect_uri = f"http://127.0.0.1:{self.port}/"
        self._timeout_s = timeout_s

    def _fire(self, code: str, state: str, error: str) -> None:
        if self._fired.is_set():
            return
        self._fired.set()
        try:
            self._on_result(code, state, error)
        finally:
            threading.Thread(target=self._stop, daemon=True).start()

    def _stop(self) -> None:
        self._server.shutdown()        # returns once serve_forever has exited
        self._server.server_close()

    def start(self) -> None:
        threading.Thread(target=self._server.serve_forever, daemon=True,
                         name="google-oauth-loopback").start()

        def _expire() -> None:
            if not self._fired.wait(self._timeout_s):
                self._fire("", "", "timeout")
        threading.Thread(target=_expire, daemon=True, name="google-oauth-timeout").start()

    def close(self) -> None:
        """Stop listening without a result (a superseded or cancelled flow).
        Only valid after `start()` — shutdown waits on serve_forever."""
        if not self._fired.is_set():
            self._fired.set()
            threading.Thread(target=self._stop, daemon=True).start()
