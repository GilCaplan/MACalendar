"""Connected calendars in the brain: the Google two-way sync, the sign-in
flows both apps start, the periodic loop, and the routes.

EVERY network call here is a fake — `FakeGoogle` stands in for both Google's
token endpoint and the Calendar API — and tests/unit/test_offline.py's rule
holds: the only real socket opened is the loopback listener the Mac sign-in
uses, which is on 127.0.0.1 by design.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
import urllib.parse
import urllib.request

import pytest

from assistant.calendar_sync import connect, google_oauth, google_sync, scheduler
from assistant.calendar_sync.google_client import GoogleCalendarClient
from assistant.config import AppConfig, GoogleCalendarConfig, load_config
from assistant.db import CalendarDB


# ---------------------------------------------------------------------------
# A fake Google: token endpoint + Calendar API events collection
# ---------------------------------------------------------------------------

class Resp:
    def __init__(self, status: int, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.ok = 200 <= status < 300
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def _stamp(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeGoogle:
    """In-memory Google Calendar. `changes` accumulate between sync tokens."""

    def __init__(self):
        self.events: dict[str, dict] = {}
        self.changed: list[str] = []
        self.token_n = 0
        self.expired_tokens: set[str] = set()
        self.calls: list[tuple] = []
        self.next_id = 1
        self.refresh_error = ""
        self.reject_access = False

    # -- server-side edits (what another device would do) --
    def put(self, gid, summary, start, end, when=None, status="confirmed"):
        self.events[gid] = {
            "id": gid, "status": status, "summary": summary,
            "start": {"dateTime": start}, "end": {"dateTime": end},
            "updated": _stamp(when or datetime.datetime.now(datetime.timezone.utc)),
        }
        self.changed.append(gid)

    def cancel(self, gid, when=None):
        ev = self.events[gid]
        ev["status"] = "cancelled"
        ev["updated"] = _stamp(when or datetime.datetime.now(datetime.timezone.utc))
        self.changed.append(gid)

    # -- transport --
    def post(self, url, data=None, timeout=None):
        self.calls.append(("POST", url, data))
        if url == google_oauth.TOKEN_URL:
            if data["grant_type"] == "refresh_token":
                if self.refresh_error:
                    return Resp(400, {"error": self.refresh_error})
                return Resp(200, {"access_token": "fresh", "expires_in": 3600})
            return Resp(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                              "id_token": _id_token("gil@example.com")})
        if url == google_oauth.REVOKE_URL:
            return Resp(200)
        raise AssertionError(f"unexpected POST {url}")

    def request(self, method, url, headers=None, timeout=None, params=None, json=None):
        self.calls.append((method, url, params or json))
        if self.reject_access and headers["Authorization"] != "Bearer fresh":
            return Resp(401)
        path = urllib.parse.urlparse(url).path
        base = "/calendar/v3/calendars/primary/events"
        assert path.startswith(base), path
        gid = urllib.parse.unquote(path[len(base) + 1:]) if len(path) > len(base) else ""
        if method == "GET":
            token = (params or {}).get("syncToken")
            if token in self.expired_tokens:
                return Resp(410, {"error": {"message": "Sync token is no longer valid"}})
            if token:
                items = [self.events[g] for g in dict.fromkeys(self.changed)]
            else:
                items = [e for e in self.events.values() if e["status"] != "cancelled"]
            self.changed = []
            self.token_n += 1
            return Resp(200, {"items": items, "nextSyncToken": f"t{self.token_n}",
                              "summary": "gil@example.com"})
        if method == "POST":
            new = f"new{self.next_id}"
            self.next_id += 1
            self.events[new] = {**json, "id": new, "status": "confirmed",
                                "updated": _stamp(datetime.datetime.now(datetime.timezone.utc))}
            return Resp(200, self.events[new])
        if method == "PATCH":
            if gid not in self.events or self.events[gid]["status"] == "cancelled":
                return Resp(404, {"error": {"message": "Not Found"}})
            self.events[gid].update(json)
            return Resp(200, self.events[gid])
        if method == "DELETE":
            if gid not in self.events:
                return Resp(410)
            self.events[gid]["status"] = "cancelled"
            return Resp(204)
        raise AssertionError(method)


def _id_token(email: str) -> str:
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).rstrip(b"=").decode()
    return f"x.{payload}.y"


@pytest.fixture
def db(tmp_path):
    return CalendarDB(str(tmp_path / "cal.db"))


@pytest.fixture
def config():
    cfg = load_config("config.example.yaml")
    return cfg


@pytest.fixture
def utc(monkeypatch):
    monkeypatch.setattr(google_sync, "local_timezone_name", lambda: "UTC")


@pytest.fixture
def connected(db, utc):
    """A Google source row plus a stored (fresh) token, as after sign-in."""
    google_oauth.save_token({"client_kind": "desktop", "client_id": "cid", "client_secret": "s",
                             "refresh_token": "rt", "access_token": "at",
                             "expires_at": time.time() + 3600, "account": "gil@example.com"})
    db.create_calendar_source(kind="google", label="Google Calendar", two_way=True)
    yield
    google_oauth.delete_token()


def _run(db, config, fake):
    return google_sync.sync_google(db, config, session=fake)


# ---------------------------------------------------------------------------
# Off by default
# ---------------------------------------------------------------------------

def test_google_is_off_by_default_and_never_calls_out(db, config):
    """No client JSON, no iOS id: not configured, status says set-up needed,
    and a sync cycle makes no call at all."""
    assert config.google_calendar == GoogleCalendarConfig()
    assert not google_sync.is_configured(config)
    st = connect.status(db, config)["providers"]["google"]
    assert st["setup_needed"] and not st["connected"] and "CALENDAR_SYNC.md" in st["setup_hint"]
    fake = FakeGoogle()
    out = _run(db, config, fake)
    assert out["ran"] is False and fake.calls == []


def test_the_loop_does_not_start_under_no_warmup(monkeypatch):
    """The suite sets MACALENDAR_NO_WARMUP; building the app must then start
    no sync thread (it would reach for Google from a unit test)."""
    import os
    assert os.environ.get("MACALENDAR_NO_WARMUP") == "1"
    started = []
    monkeypatch.setattr(scheduler, "start_background", lambda: started.append(1) or True)
    from assistant.api.server import create_app
    create_app()
    assert started == []
    assert not any(t.name == scheduler.THREAD_NAME for t in threading.enumerate())


def test_the_loop_starts_with_the_brain(monkeypatch):
    """...and without the flag, the one line in create_app starts it."""
    started = []
    monkeypatch.setattr(scheduler, "start_background", lambda: started.append(1) or True)
    monkeypatch.delenv("MACALENDAR_NO_WARMUP")
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    import assistant.api.server as server
    for name in ("warm_up_components", "start_pending_retry_loop"):
        monkeypatch.setattr(server, name, lambda *a, **k: None)
    monkeypatch.setattr("assistant.notifier.start_notifier_loop", lambda *a, **k: None)
    server.create_app()
    assert started == [1]


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------

def test_first_pull_is_full_and_later_pulls_are_incremental(db, config, connected):
    fake = FakeGoogle()
    fake.put("g1", "Dentist", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z")
    fake.put("g2", "Standup", "2026-10-02T08:00:00+03:00", "2026-10-02T08:15:00+03:00")
    out = _run(db, config, fake)
    assert out["ran"] and out["error"] == "" and out["pulled"] == 2
    rows = {r["external_id"]: r for r in db.get_events_by_external_source("google")}
    assert rows["g1"]["title"] == "Dentist" and rows["g1"]["source"] == "google"
    assert (rows["g2"]["date"], rows["g2"]["start_time"], rows["g2"]["end_time"]) == \
        ("2026-10-02", "05:00", "05:15")                     # converted into the Mac's zone
    first_get = next(c for c in fake.calls if c[0] == "GET")
    assert "timeMin" in first_get[2] and "syncToken" not in first_get[2]
    assert db.get_calendar_source_by_kind("google")["sync_token"] == "t1"

    fake.put("g1", "Dentist (moved)", "2026-10-01T11:00:00Z", "2026-10-01T12:00:00Z")
    fake.cancel("g2")
    fake.calls.clear()
    out = _run(db, config, fake)
    get = next(c for c in fake.calls if c[0] == "GET")
    assert get[2]["syncToken"] == "t1" and "timeMin" not in get[2]
    rows = {r["external_id"]: r for r in db.get_events_by_external_source("google")}
    assert rows["g1"]["title"] == "Dentist (moved)" and rows["g1"]["start_time"] == "11:00"
    assert "g2" not in rows


def test_an_expired_sync_token_falls_back_to_a_full_listing(db, config, connected):
    fake = FakeGoogle()
    fake.put("g1", "Keep", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z")
    fake.put("g2", "Vanishes", "2026-10-01T11:00:00Z", "2026-10-01T12:00:00Z")
    _run(db, config, fake)
    fake.expired_tokens.add("t1")
    del fake.events["g2"]                    # gone upstream with no tombstone we saw
    out = _run(db, config, fake)
    assert out["error"] == ""
    assert [r["external_id"] for r in db.get_events_by_external_source("google")] == ["g1"]


def test_an_all_day_event_uses_the_local_all_day_convention(db, config, connected):
    fake = FakeGoogle()
    fake.events["d"] = {"id": "d", "status": "confirmed", "summary": "Holiday",
                        "start": {"date": "2026-10-05"}, "end": {"date": "2026-10-06"},
                        "updated": _stamp(datetime.datetime.now(datetime.timezone.utc))}
    _run(db, config, fake)
    row = db.get_events_by_external_source("google")[0]
    assert (row["date"], row["start_time"], row["end_time"]) == ("2026-10-05", "00:00", "23:59")


# ---------------------------------------------------------------------------
# Push: create, edit, delete
# ---------------------------------------------------------------------------

def test_a_local_edit_is_pushed_and_a_local_delete_is_pushed(db, config, connected):
    fake = FakeGoogle()
    fake.put("g1", "Gym", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z")
    fake.put("g2", "Call", "2026-10-01T15:00:00Z", "2026-10-01T15:30:00Z")
    _run(db, config, fake)
    rows = {r["external_id"]: r for r in db.get_events_by_external_source("google")}
    db.update_event(rows["g1"]["id"], title="Gym (legs)")
    assert db.get_event(rows["g1"]["id"])["sync_dirty"] == 1
    db.delete_event(rows["g2"]["id"])
    out = _run(db, config, fake)
    assert out["pushed"] == 2 and out["error"] == ""
    assert fake.events["g1"]["summary"] == "Gym (legs)"
    assert fake.events["g2"]["status"] == "cancelled"
    assert db.get_event(rows["g1"]["id"])["sync_dirty"] == 0
    assert db.pop_sync_deletes("google") == []


def test_a_mirrored_local_event_is_created_on_google(db, config, connected):
    fake = FakeGoogle()
    eid = db.create_event_from_dict({"title": "Shiur", "date": "2026-10-03",
                                     "start_time": "20:00", "end_time": "21:00"})
    assert db.mark_for_push(eid, "google")
    out = _run(db, config, fake)
    assert out["pushed"] == 1
    row = db.get_event(eid)
    assert row["external_id"].startswith("new") and row["sync_dirty"] == 0
    created = fake.events[row["external_id"]]
    assert created["summary"] == "Shiur"
    assert created["start"] == {"dateTime": "2026-10-03T20:00:00", "timeZone": "UTC"}


def test_plain_local_events_are_never_pushed_unless_mirroring_is_on(db, config, connected):
    fake = FakeGoogle()
    db.create_event_from_dict({"title": "Private", "date": "2026-10-03",
                               "start_time": "20:00", "end_time": "21:00"})
    _run(db, config, fake)
    assert not any(c[0] == "POST" for c in fake.calls)
    config.google_calendar.mirror_new_events = True
    _run(db, config, fake)
    assert [e["summary"] for e in fake.events.values()] == ["Private"]


def test_deletes_for_one_provider_never_eat_another_providers_tombstones(db):
    db.requeue_sync_delete("outlook", "o1")
    db.requeue_sync_delete("google", "g1")
    assert [t["external_id"] for t in db.pop_sync_deletes("google")] == ["g1"]
    assert [t["external_id"] for t in db.pop_sync_deletes("outlook")] == ["o1"]


# ---------------------------------------------------------------------------
# Conflicts: last write wins
# ---------------------------------------------------------------------------

def test_a_newer_local_edit_beats_an_older_remote_one(db, config, connected):
    fake = FakeGoogle()
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
    fake.put("g1", "Original", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z", when=past)
    _run(db, config, fake)
    eid = db.get_events_by_external_source("google")[0]["id"]
    # Remote edit an hour ago, local edit now: the local one is newer.
    fake.put("g1", "Remote edit", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z",
             when=past + datetime.timedelta(hours=1))
    db.update_event(eid, title="Local edit")
    _run(db, config, fake)
    assert db.get_event(eid)["title"] == "Local edit"
    assert fake.events["g1"]["summary"] == "Local edit"


def test_a_newer_remote_edit_beats_an_older_local_one(db, config, connected):
    fake = FakeGoogle()
    fake.put("g1", "Original", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z")
    _run(db, config, fake)
    eid = db.get_events_by_external_source("google")[0]["id"]
    db.update_event(eid, title="Local edit")
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
    fake.put("g1", "Remote edit", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z", when=future)
    out = _run(db, config, fake)
    row = db.get_event(eid)
    assert row["title"] == "Remote edit" and row["sync_dirty"] == 0
    assert out["pushed"] == 0 and fake.events["g1"]["summary"] == "Remote edit"


def test_a_remote_delete_of_an_event_edited_since_recreates_it(db, config, connected):
    fake = FakeGoogle()
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    fake.put("g1", "Original", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z", when=past)
    _run(db, config, fake)
    eid = db.get_events_by_external_source("google")[0]["id"]
    fake.cancel("g1", when=past + datetime.timedelta(minutes=1))
    db.update_event(eid, title="Still wanted")
    _run(db, config, fake)
    row = db.get_event(eid)
    assert row["external_id"] != "g1" and fake.events[row["external_id"]]["summary"] == "Still wanted"


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def test_a_401_refreshes_the_token_once_and_retries(db, config, connected):
    fake = FakeGoogle()
    fake.reject_access = True
    out = _run(db, config, fake)
    assert out["error"] == ""
    assert google_oauth.load_token()["access_token"] == "fresh"


def test_a_revoked_grant_is_reported_as_reconnect_not_raised(db, config, connected):
    google_oauth.save_token({**google_oauth.load_token(), "expires_at": 0})
    fake = FakeGoogle()
    fake.refresh_error = "invalid_grant"
    out = _run(db, config, fake)
    assert "reconnect" in out["error"]
    assert "reconnect" in db.get_calendar_source_by_kind("google")["last_error"]


# ---------------------------------------------------------------------------
# Sign-in flows (both surfaces)
# ---------------------------------------------------------------------------

def _desktop_json(tmp_path, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"installed": {"client_id": "desk.apps.googleusercontent.com",
                                              "client_secret": "shh"}}))
    monkeypatch.setenv("MACALENDAR_GOOGLE_CLIENT_SECRET", str(path))


def test_mac_sign_in_catches_the_loopback_redirect_and_connects(db, config, tmp_path, monkeypatch):
    _desktop_json(tmp_path, monkeypatch)
    monkeypatch.setattr(scheduler, "sync_in_background", lambda: True)
    fake = FakeGoogle()
    flow = connect.google_start(db, config, platform="mac", session=fake)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(flow["auth_url"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    assert q["redirect_uri"][0].startswith("http://127.0.0.1:")
    # The browser comes back to the loopback listener (a real 127.0.0.1 socket).
    back = f"{flow['redirect_uri']}?code=abc&state={q['state'][0]}"
    with urllib.request.urlopen(back, timeout=5) as r:
        assert b"Connected" in r.read()
    for _ in range(50):
        if connect.flow_status(flow["id"])["state"] != "pending":
            break
        time.sleep(0.05)
    st = connect.flow_status(flow["id"])
    assert st["state"] == "done" and st["account"] == "gil@example.com"
    exchange = next(c for c in fake.calls if c[1] == google_oauth.TOKEN_URL)[2]
    assert exchange["code"] == "abc" and exchange["client_secret"] == "shh" and exchange["code_verifier"]
    assert google_oauth.load_token()["client_kind"] == "desktop"
    src = db.get_calendar_source_by_kind("google")
    assert src["account"] == "gil@example.com" and src["two_way"] == 1
    google_oauth.delete_token()


def test_phone_sign_in_exchanges_the_code_the_phone_posts(db, config, monkeypatch):
    monkeypatch.setattr(scheduler, "sync_in_background", lambda: True)
    config.google_calendar.ios_client_id = "1234-abc.apps.googleusercontent.com"
    fake = FakeGoogle()
    flow = connect.google_start(db, config, platform="ios")
    assert flow["callback_scheme"] == "com.googleusercontent.apps.1234-abc"
    assert flow["redirect_uri"] == "com.googleusercontent.apps.1234-abc:/oauth2redirect"
    state = urllib.parse.parse_qs(urllib.parse.urlparse(flow["auth_url"]).query)["state"][0]
    with pytest.raises(connect.FlowError):
        connect.google_complete(db, flow_id=flow["id"], code="c", state="forged", session=fake)
    done = connect.google_complete(
        db, callback_url=f"{flow['redirect_uri']}?state={state}&code=c0de", session=fake)
    assert done["state"] == "done"
    exchange = next(c for c in fake.calls if c[1] == google_oauth.TOKEN_URL)[2]
    assert "client_secret" not in exchange and exchange["code"] == "c0de"
    assert google_oauth.load_token()["client_kind"] == "ios"
    google_oauth.delete_token()


def test_outlook_device_flow_connects_in_the_background(db, config, monkeypatch):
    from assistant.config import MicrosoftConfig
    monkeypatch.setattr(scheduler, "sync_in_background", lambda: True)
    config.microsoft = MicrosoftConfig(client_id="entra-app")
    release = threading.Event()

    class FakeMSAL:
        def __init__(self, cfg):
            pass

        def start_device_flow(self):
            return {"user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin",
                    "message": "go", "expires_in": 900}

        def complete_device_flow(self, flow):
            release.wait(5)
            return "token"

        def account_name(self):
            return "gil@outlook.com"

    flow = connect.outlook_start(db, config, auth_factory=FakeMSAL)
    assert flow["user_code"] == "ABCD-1234" and flow["state"] == "pending"
    assert connect.status(db, config)["providers"]["outlook"]["pending_flow"]["id"] == flow["id"]
    release.set()
    for _ in range(50):
        if connect.flow_status(flow["id"])["state"] == "done":
            break
        time.sleep(0.05)
    assert connect.flow_status(flow["id"])["account"] == "gil@outlook.com"
    assert db.get_calendar_source_by_kind("outlook")["two_way"] == 1


def test_disconnect_keeps_the_events_as_local_by_default(db, config, connected):
    fake = FakeGoogle()
    fake.put("g1", "Dentist", "2026-10-01T09:00:00Z", "2026-10-01T10:00:00Z")
    _run(db, config, fake)
    eid = db.get_events_by_external_source("google")[0]["id"]
    out = connect.disconnect(db, config, "google", session=fake)
    assert out["events_kept"] == 1
    row = db.get_event(eid)
    assert row["source"] == "local" and row["external_id"] == ""
    assert google_oauth.load_token() is None and db.get_calendar_source_by_kind("google") is None
    assert any(c[1] == google_oauth.REVOKE_URL for c in fake.calls)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    # PUT /setup writes config.yaml: give it a copy, never the suite's shared one.
    cfg = tmp_path / "config.yaml"
    cfg.write_text(open("config.example.yaml").read())
    monkeypatch.setenv("MACALENDAR_CONFIG", str(cfg))
    from assistant.api.server import create_app
    return create_app().test_client()


def test_routes_report_setup_needed_instead_of_failing(client):
    st = client.get("/calendar_sync/status").get_json()
    assert st["providers"]["google"]["setup_needed"] and st["providers"]["outlook"]["setup_needed"]
    r = client.post("/calendar_sync/google/start", json={"platform": "ios"})
    assert r.status_code == 409 and r.get_json()["setup_needed"]
    r = client.post("/calendar_sync/outlook/start")
    assert r.status_code == 409 and r.get_json()["setup_needed"]


def test_setup_routes_store_the_client_ids_and_json(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_GOOGLE_CLIENT_SECRET", str(tmp_path / "desk.json"))
    r = client.put("/calendar_sync/setup", json={"outlook_client_id": "entra-app",
                                                 "google_ios_client_id": "9-x.apps.googleusercontent.com"})
    assert r.status_code == 200
    cfg = load_config()
    assert cfg.microsoft.client_id == "entra-app"
    assert cfg.google_calendar.ios_client_id == "9-x.apps.googleusercontent.com"
    bad = client.post("/calendar_sync/google/client", json={"client_json": '{"web": {}}'})
    assert bad.status_code == 400
    ok = client.post("/calendar_sync/google/client",
                     json={"client_json": json.dumps({"installed": {"client_id": "d", "client_secret": "s"}})})
    assert ok.status_code == 200
    st = client.get("/calendar_sync/status").get_json()["providers"]
    assert st["google"]["setup"] == {"mac": True, "ios": True} and st["outlook"]["configured"]


def test_sync_now_route_runs_the_shared_sync(client):
    body = client.post("/calendar_sync/sync", json={"wait": True}).get_json()
    assert body["finished"] and body["results"]["errors"] == []
    assert client.get("/calendar_sync/status").get_json()["last_run"]["results"] == body["results"]


def test_unknown_flow_and_provider_are_404(client):
    assert client.get("/calendar_sync/flows/nope").status_code == 404
    assert client.post("/calendar_sync/yahoo/disconnect").status_code == 404
