"""Google Calendar API v3 — the five calls the sync needs, over `requests`."""

from __future__ import annotations

import urllib.parse
import requests

from assistant.calendar_sync.google_oauth import GoogleAuth
from assistant.exceptions import AssistantError, AuthExpiredError

BASE_URL = "https://www.googleapis.com/calendar/v3"
_PAGE_SIZE = 250
#: A safety cap, not a limit anyone should hit: 50 pages is 12,500 events.
MAX_PAGES = 50


class GoogleAPIError(AssistantError):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class SyncTokenExpired(GoogleAPIError):
    """410 Gone: the incremental cursor is no longer valid — do a full sync."""


class GoogleCalendarClient:
    def __init__(self, auth: GoogleAuth, calendar_id: str = "primary", session=None) -> None:
        self.auth = auth
        self.calendar_id = calendar_id or "primary"
        self._http = session or requests.Session()

    def _events_url(self, event_id: str = "") -> str:
        cal = urllib.parse.quote(self.calendar_id, safe="")
        url = f"{BASE_URL}/calendars/{cal}/events"
        return f"{url}/{urllib.parse.quote(event_id, safe='')}" if event_id else url

    def _send(self, method: str, url: str, **kw) -> requests.Response:
        """One request, retried ONCE with a refreshed token on a 401."""
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self.auth.get_token(force_refresh=attempt == 1)}"}
            resp = self._http.request(method, url, headers=headers, timeout=30, **kw)
            if resp.status_code != 401:
                return resp
        raise AuthExpiredError("Google rejected the access token twice — reconnect.")

    @staticmethod
    def _check(resp: requests.Response) -> None:
        if resp.ok:
            return
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            detail = resp.text
        if resp.status_code == 410:
            raise SyncTokenExpired(f"Google 410: {detail}", 410)
        raise GoogleAPIError(f"Google Calendar {resp.status_code}: {detail}", resp.status_code)

    def list_changes(self, sync_token: str = "", time_min: str = "") -> tuple[list, str, str]:
        """Every page of events.list. Returns (items, next_sync_token, summary).

        With *sync_token*: only what changed since it (deletions included, as
        status "cancelled"). Without: a full listing from *time_min*.
        `singleEvents` expands recurring series into instances — the local
        calendar has no model for Google's recurrence rules — and must match
        between the full and the incremental requests, so it is always on.
        next_sync_token is "" if the page cap was hit before the last page.
        """
        params: dict = {"singleEvents": "true", "maxResults": str(_PAGE_SIZE)}
        if sync_token:
            params["syncToken"] = sync_token
        elif time_min:
            params["timeMin"] = time_min
        items: list = []
        summary = ""
        for _ in range(MAX_PAGES):
            resp = self._send("GET", self._events_url(), params=params)
            self._check(resp)
            body = resp.json()
            summary = summary or body.get("summary", "")
            items.extend(body.get("items", []))
            page = body.get("nextPageToken")
            if not page:
                return items, body.get("nextSyncToken", ""), summary
            params = {**params, "pageToken": page}
        return items, "", summary

    def insert(self, payload: dict) -> dict:
        resp = self._send("POST", self._events_url(), json=payload)
        self._check(resp)
        return resp.json()

    def patch(self, event_id: str, payload: dict) -> dict:
        resp = self._send("PATCH", self._events_url(event_id), json=payload)
        self._check(resp)
        return resp.json()

    def delete(self, event_id: str) -> None:
        """404/410 (already gone) count as success, so a retried delete after
        an unconfirmed first attempt does not raise."""
        resp = self._send("DELETE", self._events_url(event_id))
        if resp.status_code in (404, 410):
            return
        self._check(resp)
