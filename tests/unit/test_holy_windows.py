"""When Shabbat and yom tov begin and end — the windows the yellow lines draw.

Gil, 2026-09-24: *"automatically put a line onwards marking shabbat when it
starts/ends which updates automatically to phone location, important because
the exact minute is important."*

What must hold:

- a window runs from candle lighting on the eve to tzeit on the last day, to
  the SECOND, and consecutive holy days are one window (no line in between);
- it is the SAME instant the recurring-series skip in `db.py` uses — a minute
  before the line books, the minute after is refused — so the line and the
  refusal cannot disagree;
- the minute shown never makes Shabbat look shorter than it is (candle
  lighting truncated, nightfall rounded up);
- where the sun does not set, NOTHING is returned — never a guessed minute;
- the route and the bootstrap serve it, and a phone reporting a new position
  moves the answer.
"""
from __future__ import annotations

import datetime

import pytest

from assistant import observance as ob

JERUSALEM = ob.ObservanceSettings(latitude=31.7683, longitude=35.2137,
                                  timezone="Asia/Jerusalem", city="Jerusalem",
                                  tzeit_depression=8.5, candle_lighting_minutes=18)
LONDON = (51.5074, -0.1278, "Europe/London")

FRI = datetime.date(2026, 9, 4)        # an ordinary Shabbat
SAT = datetime.date(2026, 9, 5)


# ---------------------------------------------------------------------------
# The computation
# ---------------------------------------------------------------------------

def test_an_ordinary_shabbat_runs_from_candle_lighting_to_tzeit_to_the_second():
    [w] = ob.holy_windows(FRI, SAT, JERUSALEM)
    assert w.start_name == w.end_name == "Shabbat"
    assert w.days == (SAT,)
    lit = ob.candle_lighting(FRI, JERUSALEM).replace(microsecond=0)
    night = ob.tzeit(SAT, JERUSALEM).replace(microsecond=0)
    assert w.start.date() == FRI and w.start.timetz().replace(tzinfo=None) == lit
    assert w.end.date() == SAT and w.end.timetz().replace(tzinfo=None) == night
    # Seconds are kept: the line is placed by them.
    assert (w.start.second, w.end.second) == (lit.second, night.second)
    assert w.start.utcoffset() == datetime.timedelta(hours=3)


def test_consecutive_holy_days_are_one_window_with_no_line_in_between():
    # Rosh Hashanah 5789: Thursday and Friday, running straight into Shabbat.
    wins = ob.holy_windows(datetime.date(2028, 9, 18), datetime.date(2028, 9, 25), JERUSALEM)
    [w] = [w for w in wins if w.start.date() == datetime.date(2028, 9, 20)]
    assert w.days == (datetime.date(2028, 9, 21), datetime.date(2028, 9, 22),
                      datetime.date(2028, 9, 23))
    assert (w.start_name, w.end_name) == ("Rosh Hashana", "Shabbat")
    assert w.name == "Rosh Hashana & Shabbat"
    assert not any(x.start.date() == datetime.date(2028, 9, 22) for x in wins)


def test_a_yom_tov_on_shabbat_is_called_by_the_festival():
    [w] = [w for w in ob.holy_windows(datetime.date(2026, 9, 25), datetime.date(2026, 9, 26), JERUSALEM)]
    assert w.start_name == "Succos"


def test_the_diaspora_schedule_adds_the_second_day():
    # Pesach 5787 begins on a Thursday: one day in Israel, two abroad, and
    # abroad the second runs into Shabbat — one three-day window.
    israel = ob.holy_windows(datetime.date(2027, 4, 21), datetime.date(2027, 4, 24), JERUSALEM, israel=True)
    diaspora = ob.holy_windows(datetime.date(2027, 4, 21), datetime.date(2027, 4, 24), JERUSALEM, israel=False)
    assert max(len(w.days) for w in diaspora) > max(len(w.days) for w in israel)


def test_the_window_is_the_instant_the_series_skip_refuses_from(monkeypatch):
    """The line and the calendar's refusal are one instant, not two computations."""
    import assistant.db as db
    monkeypatch.setattr(ob, "current_settings", lambda: JERUSALEM)
    monkeypatch.setenv("MACALENDAR_OBSERVANCE", "1")
    [w] = ob.holy_windows(FRI, SAT, JERUSALEM)

    def at(dt: datetime.datetime) -> str:
        return dt.strftime("%H:%M")

    one = datetime.timedelta(minutes=1)
    # Friday: the minute the line is drawn in is still bookable; the next is not.
    assert not db._skip_for_observance(FRI, at(w.start), "Gym")
    assert db._skip_for_observance(FRI, at(w.start + one), "Gym")
    # Saturday: refused up to the line's minute, bookable from the label's.
    assert db._skip_for_observance(SAT, at(w.end), "Gym")
    assert not db._skip_for_observance(SAT, w.end_label, "Gym")


def test_the_labels_never_make_shabbat_shorter_than_it_is():
    [w] = ob.holy_windows(FRI, SAT, JERUSALEM)
    assert w.start.second and w.end.second, "pick a date whose times have seconds"
    assert w.start_label == w.start.strftime("%H:%M")                     # truncated
    assert w.end_label == (w.end + datetime.timedelta(minutes=1)).strftime("%H:%M")  # up


def test_where_the_sun_does_not_set_nothing_is_guessed():
    polar = ob.ObservanceSettings(latitude=78.22, longitude=15.65, timezone="Arctic/Longyearbyen")
    assert ob.holy_windows(datetime.date(2026, 6, 1), datetime.date(2026, 6, 30), polar) == []


def test_a_window_touching_the_range_edge_is_included():
    # Asked only for the Saturday: the window lit on Friday still touches it.
    assert len(ob.holy_windows(SAT, SAT, JERUSALEM)) == 1
    # And only for the Friday: the eve carries the start line.
    assert len(ob.holy_windows(FRI, FRI, JERUSALEM)) == 1
    # A Tuesday has none.
    assert ob.holy_windows(datetime.date(2026, 9, 1), datetime.date(2026, 9, 1), JERUSALEM) == []


def test_the_place_key_moves_with_the_place():
    moved = ob.ObservanceSettings(latitude=LONDON[0], longitude=LONDON[1], timezone=LONDON[2])
    assert ob.place_key(JERUSALEM) != ob.place_key(moved)
    assert ob.place_key(JERUSALEM) == ob.place_key(JERUSALEM)


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    # The reported position lives in its own scratch file for this test: a
    # POST below must not leave London in the suite's shared location store.
    monkeypatch.setattr(ob, "LOCATION_PATH", str(tmp_path / "location.json"))
    ob.reload_settings()
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    yield app.test_client()
    monkeypatch.undo()
    ob.reload_settings()


def test_the_route_serves_the_windows_with_seconds(client):
    body = client.get("/observance/windows?start=2026-09-01&end=2026-09-30").get_json()
    assert body["place_key"] == ob.place_key()
    assert body["start"] == "2026-09-01" and body["end"] == "2026-09-30"
    starts = [w["start"][:10] for w in body["windows"]]
    assert "2026-09-04" in starts                     # erev Shabbat
    w = body["windows"][0]
    assert set(w) >= {"name", "start_name", "end_name", "start", "end",
                      "start_label", "end_label", "days"}
    # ISO with seconds and an offset — the phone places the line by them.
    parsed = datetime.datetime.fromisoformat(w["start"])
    assert parsed.tzinfo is not None
    assert len(w["start"]) == len("2026-09-04T18:41:20+03:00")


@pytest.mark.parametrize("query", ["", "?start=2026-09-01", "?start=x&end=2026-09-02",
                                   "?start=2026-09-10&end=2026-09-01",
                                   "?start=2026-01-01&end=2028-01-01"])
def test_the_route_refuses_a_bad_range(client, query):
    assert client.get(f"/observance/windows{query}").status_code == 400


def test_a_phone_reporting_a_new_position_moves_the_lines(client):
    q = "/observance/windows?start=2026-09-04&end=2026-09-05"
    before = client.get(q).get_json()
    r = client.post("/observance/location", json={
        "latitude": LONDON[0], "longitude": LONDON[1], "timezone": LONDON[2], "city": "London"})
    assert r.status_code == 200
    after = client.get(q).get_json()
    assert after["place"]["source"] == "device"
    assert after["place_key"] != before["place_key"]
    assert after["windows"][0]["start"] != before["windows"][0]["start"]
    assert after["windows"][0]["start"].endswith("+01:00")    # London, BST

    # Forgetting the position goes back to the configured place.
    client.delete("/observance/location")
    assert client.get(q).get_json()["place_key"] == before["place_key"]


def test_the_bootstrap_carries_the_windows_for_its_span(client):
    body = client.get("/sync/bootstrap?year=2026&month=9").get_json()
    holy = body["holy_windows"]
    assert holy["start"] == body["window"]["start"]
    assert holy["end"] == body["window"]["end"]
    assert holy["windows"] == client.get(
        f"/observance/windows?start={holy['start']}&end={holy['end']}").get_json()["windows"]
