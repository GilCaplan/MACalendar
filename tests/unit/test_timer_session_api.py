"""POST /timers/<id>/sessions — logging time you forgot to start the timer for.

The Mac's Timer tab has always had "Log past time…"; the phone had no way to
add a session at all (only to view and delete them), so a forgotten timer was
simply lost time. These tests cover the endpoint that closes that gap.
"""
from __future__ import annotations

import datetime

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    # The singleton is _db_instance; assigning _db._db just made a stray
    # attribute and left get_db() handing back the session-wide database.
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _timer(client) -> int:
    r = client.post("/timers", json={"title": "Thesis", "hourly_rate": 60, "currency": "ILS"})
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()["id"]


def test_logs_a_finished_past_session(client):
    tid = _timer(client)
    now = datetime.datetime.now().astimezone()
    start = (now - datetime.timedelta(hours=2)).isoformat()

    r = client.post(f"/timers/{tid}/sessions",
                    json={"start_time": start, "end_time": now.isoformat(), "title": "forgot to start"})

    assert r.status_code == 201
    body = r.get_json()
    assert body["title"] == "forgot to start"
    assert body["running"] is False
    assert body["seconds"] == pytest.approx(7200, abs=2)


def test_session_shows_up_in_the_list(client):
    tid = _timer(client)
    now = datetime.datetime.now().astimezone()
    client.post(f"/timers/{tid}/sessions",
                json={"start_time": (now - datetime.timedelta(minutes=30)).isoformat(),
                      "end_time": now.isoformat()})

    sessions = client.get(f"/timers/{tid}/sessions").get_json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["seconds"] == pytest.approx(1800, abs=2)


def test_end_time_may_be_omitted_for_a_still_running_session(client):
    tid = _timer(client)
    start = (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=5)).isoformat()

    body = client.post(f"/timers/{tid}/sessions", json={"start_time": start}).get_json()

    assert body["running"] is True
    assert not body["end_time"]


def test_start_time_is_required(client):
    tid = _timer(client)
    r = client.post(f"/timers/{tid}/sessions", json={})
    assert r.status_code == 400
    assert "start_time" in r.get_json()["error"]


# ---------------------------------------------------------------------------
# Auto-stop ("stop a session that has run too long")
# ---------------------------------------------------------------------------

def test_auto_stop_is_settable_without_touching_anything_else(client):
    """The row menus on both platforms set it with one PATCH.

    It used to be reachable only from inside the edit dialog, which meant
    resending the title, rate, currency and colour to change one number.
    """
    tid = client.post("/timers", json={"title": "Netivim", "hourly_rate": 70,
                                       "currency": "ILS"}).get_json()["id"]

    def timer():
        return [t for t in client.get("/timers").get_json()["timers"] if t["id"] == tid][0]

    assert timer().get("max_session_minutes") == 0        # off by default

    for minutes in (30, 120, 480, 0):
        assert client.patch(f"/timers/{tid}", json={"max_session_minutes": minutes}).status_code == 200
        assert timer()["max_session_minutes"] == minutes

    # …and nothing else moved
    assert timer()["title"] == "Netivim"
    assert timer()["hourly_rate"] == 70


@pytest.mark.parametrize("minutes,shown", [
    (0, "0 min"), (30, "30 min"), (45, "45 min"),
    (60, "1 h"), (120, "2 h"), (150, "2 h 30 min"), (480, "8 h"),
])
def test_the_menu_label_reads_like_a_person_wrote_it(minutes, shown):
    # Mirrored by AutoStop.format in MACalendar-iOS/Views/TimerView.swift.
    pytest.importorskip("PyQt6.QtWidgets")
    from assistant.calendar_ui.timer_view import _fmt_minutes
    assert _fmt_minutes(minutes) == shown


def test_the_two_platforms_offer_the_same_presets():
    """The Mac menu and the iOS long-press menu must not drift apart."""
    pytest.importorskip("PyQt6.QtWidgets")
    import re
    from pathlib import Path
    from assistant.calendar_ui.timer_view import TimerCard

    swift = (Path(__file__).resolve().parents[2]
             / "MACalendar-iOS/MACalendar-iOS/Views/TimerView.swift").read_text()
    ios = [int(m) for m in re.findall(r'Preset\(label: "[^"]+", minutes: (\d+)\)', swift)]
    mac = [minutes for _label, minutes in TimerCard._AUTO_STOP_PRESETS]
    assert ios == mac, f"iOS presets {ios} != Mac presets {mac}"


# ---------------------------------------------------------------------------
# The live counter — why the phone and the Mac disagreed
#
# `db.create_timer_session` stores `datetime.now().astimezone().isoformat()`,
# which is SIX fractional digits: "2026-09-17T12:08:55.581429+03:00". iOS's
# ISO8601DateFormatter parses exactly three with `.withFractionalSeconds`, and
# rejects the fraction outright without it — so the phone parsed nil for every
# running session the Mac had started. Its live counter read 00:00 beside a
# timer the Mac was counting up, and its total ran backwards, because the total
# subtracts the running session's server-computed length from a live elapsed
# that was zero. It worked only in the one case where the microseconds landed
# on zero and `isoformat` omitted the fraction entirely.
#
# The phone's parser is fixed. These pin the other half: a clock is the wrong
# place to depend on a text format, so the same instants are served as numbers.
# ---------------------------------------------------------------------------

def test_the_stored_stamp_really_is_the_awkward_one(client):
    """If this ever stops being true the epochs below are still correct — but
    the bug this documents would no longer be reproducible, and someone should
    know that before deleting the workaround on the phone."""
    tid = _timer(client)
    client.post(f"/timers/{tid}/start", json={})
    started = client.get(f"/timers/{tid}/sessions").get_json()["sessions"][0]["start_time"]
    fraction = started.partition(".")[2].partition("+")[0].partition("Z")[0]
    assert len(fraction) > 3, f"{started!r} no longer has sub-millisecond digits"


def test_a_running_session_carries_its_start_as_a_number(client):
    tid = _timer(client)
    client.post(f"/timers/{tid}/start", json={})
    running = client.get("/timers").get_json()["timers"][0]["running"]
    assert running["start_epoch"] > 0
    assert running["end_epoch"] is None


def test_the_epoch_is_the_same_instant_as_the_string(client):
    tid = _timer(client)
    now = datetime.datetime.now().astimezone()
    start = now - datetime.timedelta(hours=2)
    client.post(f"/timers/{tid}/sessions",
                json={"start_time": start.isoformat(), "end_time": now.isoformat()})
    s = client.get(f"/timers/{tid}/sessions").get_json()["sessions"][0]
    assert s["start_epoch"] == pytest.approx(start.timestamp(), abs=0.001)
    assert s["end_epoch"] == pytest.approx(now.timestamp(), abs=0.001)
    # …and the pair agrees with the duration the server reports, so a client
    # that uses the numbers reaches the Mac's own answer rather than its own.
    assert s["end_epoch"] - s["start_epoch"] == pytest.approx(s["seconds"], abs=0.1)


def test_a_naive_stamp_is_read_as_local(client):
    """The Mac's "Log past time…" dialog writes Qt's ISODate, which carries no
    offset. The server already read those as local; the epoch must agree."""
    tid = _timer(client)
    naive = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=1)
    client.post(f"/timers/{tid}/sessions", json={"start_time": naive.isoformat()})
    s = client.get(f"/timers/{tid}/sessions").get_json()["sessions"][0]
    assert s["start_epoch"] == pytest.approx(naive.astimezone().timestamp(), abs=1)


def test_the_strings_are_still_served(client):
    """A phone that has not been updated reads `start_time`; adding the numbers
    must not take that away."""
    tid = _timer(client)
    client.post(f"/timers/{tid}/start", json={})
    running = client.get("/timers").get_json()["timers"][0]["running"]
    assert running["start_time"] and running["running"] is True
