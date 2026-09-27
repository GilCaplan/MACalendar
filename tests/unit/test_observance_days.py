"""The per-day switch, "keep engine events off this day" (DEVQA Q60).

Gil, 2026-09-26: every day has one — on by default for Shabbat and yom tov,
off for chol hamoed and ordinary days — and any date can be flipped either
way. On a day kept off an engine-made one-off is still added WITH A NOTE and a
series skips it; on a day not kept off the engine books as on any day.

Sukkot 2026 in Israel is the worked case: yom tov Sat 26 Sep, chol hamoed Sun
27 Sep to Fri 2 Oct, Shmini Atzeret Sat 3 Oct. Every store is in tmp_path.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from types import SimpleNamespace

import pytest

from assistant import observance as ob

YOM_TOV = dt.date(2026, 9, 26)           # Shabbat and first day of Sukkot
CHOL = dt.date(2026, 9, 29)              # Tue, chol hamoed
CHOL_MON = dt.date(2026, 9, 28)
SHMINI = dt.date(2026, 10, 3)            # Shabbat and Shmini Atzeret
SHABBAT = dt.date(2026, 10, 10)
ORDINARY = dt.date(2026, 10, 13)         # a Tuesday
YOM_KIPPUR = dt.date(2026, 9, 21)
TZOM_GEDALIA = dt.date(2026, 9, 14)


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "observance_exceptions.json"
    monkeypatch.setattr(ob, "EXCEPTIONS_PATH", str(path))
    monkeypatch.delenv("MACALENDAR_OBSERVANCE", raising=False)
    ob._exc_cache.clear()
    yield path
    ob._exc_cache.clear()


def _verdict(date, start="10:00", title="gym session"):
    from assistant.engine.decompose_validate.observance_gate import _observance_verdict
    return _observance_verdict(SimpleNamespace(title=title, description="", date=date.isoformat(),
                                               start_time=start, recurrence=None), None)


@pytest.fixture
def db(tmp_path):
    from assistant.db import CalendarDB
    return CalendarDB(str(tmp_path / "c.db"))


def _series_days(db, start, end, title="gym session", time="10:00"):
    root = db.create_event_from_dict({
        "title": title, "date": start.isoformat(), "start_time": time,
        "end_time": "11:00", "recurrence": "daily", "recurrence_end": end.isoformat(),
    })
    return sorted(dt.date.fromisoformat(e["date"]) for e in db.get_series_events(root))


# ── what kind of day, and its default ──────────────────────────────────


@pytest.mark.parametrize("date, kind, kept_off", [
    (YOM_TOV, "yom_tov", True),
    (dt.date(2026, 9, 27), "chol_hamoed", False),
    (CHOL, "chol_hamoed", False),
    (dt.date(2026, 10, 2), "chol_hamoed", False),       # Hoshana Rabbah
    (SHMINI, "yom_tov", True),
    (SHABBAT, "shabbat", True),
    (YOM_KIPPUR, "yom_tov", True),
    (TZOM_GEDALIA, "fast", False),
    (ORDINARY, "ordinary", False),
])
def test_each_kind_of_day_has_its_default(store, date, kind, kept_off):
    assert ob.day_kind(date) == kind
    assert ob.default_kept_off(date) is kept_off
    assert ob.kept_off(date) is kept_off
    assert ob.engine_allowed(date) is not kept_off


def test_names_come_from_the_server_and_respect_the_diaspora_schedule(store):
    assert ob.day_name(SHMINI) == "Shabbat · Shmini Atzeres"
    assert ob.day_name(CHOL) == "Chol hamoed Succos"
    assert ob.day_name(ORDINARY) == ""
    # The second day of Sukkot is yom tov outside Israel and chol hamoed in it.
    sun = dt.date(2026, 9, 27)
    assert ob.day_kind(sun, israel=True) == "chol_hamoed"
    assert ob.day_kind(sun, israel=False) == "yom_tov"


def test_the_switch_label_and_defaults_live_in_one_place():
    assert ob.SWITCH_LABEL == "Keep engine events off this day"
    assert ob.DEFAULT_KEPT_OFF == {"shabbat": True, "yom_tov": True, "chol_hamoed": False,
                                   "fast": False, "ordinary": False}


# ── the rules: a yom tov allowed, a chol hamoed day kept off ───────────


def test_an_allowed_yom_tov_books_with_no_note_and_a_series_keeps_it(store, db):
    from assistant.db import _skip_for_observance
    assert _verdict(YOM_TOV) and _skip_for_observance(YOM_TOV, "10:00", "gym session")
    ob.set_day_override(YOM_TOV, False)
    assert ob.day_override(YOM_TOV) == "allow" and not ob.kept_off(YOM_TOV)
    assert _verdict(YOM_TOV) is None
    assert not _skip_for_observance(YOM_TOV, "10:00", "gym session")
    # its eve belongs to the same holy window
    assert _verdict(YOM_TOV - dt.timedelta(days=1), "20:30") is None
    days = _series_days(db, dt.date(2026, 9, 24), CHOL_MON)
    assert YOM_TOV in days and dt.date(2026, 9, 25) in days


def test_a_chol_hamoed_day_kept_off_gets_the_note_and_a_series_skips_it(store, db):
    from assistant.db import _skip_for_observance
    assert _verdict(CHOL) is None and not _skip_for_observance(CHOL, "10:00", "gym session")
    ob.set_day_override(CHOL, True)
    note = _verdict(CHOL)
    assert note == "you set Tue 29 Sep to keep engine events off"
    # the whole calendar day, not sundown-bounded, and no meal exemption
    assert _verdict(CHOL, "00:30") and _verdict(CHOL, "23:30")
    assert _verdict(CHOL, "13:00", title="lunch with Dan")
    assert _skip_for_observance(CHOL, "10:00", "gym session")
    assert _skip_for_observance(CHOL, "13:00", "lunch")
    # the evening before is an ordinary evening
    assert _verdict(CHOL_MON, "21:00") is None
    days = _series_days(db, dt.date(2026, 9, 27), dt.date(2026, 10, 1))
    assert CHOL not in days
    assert CHOL_MON in days and dt.date(2026, 9, 30) in days


def test_a_series_starting_on_a_kept_off_day_still_skips_shabbat(store, db):
    """The anchor exception is for a series put ON Shabbat, not for one that
    starts on a weekday the user happened to keep off."""
    ob.set_day_override(dt.date(2026, 10, 6), True)
    days = _series_days(db, dt.date(2026, 10, 6), dt.date(2026, 10, 12))
    assert SHABBAT not in days
    assert dt.date(2026, 10, 7) in days


def test_a_series_anchored_on_shabbat_still_skips_a_day_kept_off(store, db):
    ob.set_day_override(dt.date(2026, 10, 12), True)
    days = _series_days(db, SHABBAT, dt.date(2026, 10, 14), title="Shabbat shiur")
    assert SHABBAT in days
    assert dt.date(2026, 10, 12) not in days and dt.date(2026, 10, 13) in days


def test_a_fast_meal_is_still_flagged_unless_the_day_is_allowed(store):
    # Tzom Gedalia is not kept off by default; a meal before it ends still is.
    assert _verdict(TZOM_GEDALIA) is None
    assert _verdict(TZOM_GEDALIA, "13:00", "lunch")
    # Yom Kippur allowed: the rule is off for it, the fast check included.
    assert _verdict(YOM_KIPPUR, "13:00", "lunch")
    ob.set_day_override(YOM_KIPPUR, False)
    assert _verdict(YOM_KIPPUR, "13:00", "lunch") is None


def test_the_global_switch_off_means_no_gating_whatever_the_days_say(store, monkeypatch):
    from assistant.db import _skip_for_observance
    ob.set_day_override(CHOL, True)
    monkeypatch.setenv("MACALENDAR_OBSERVANCE", "0")
    assert _verdict(CHOL) is None and _verdict(SHABBAT) is None
    assert not _skip_for_observance(CHOL, "10:00", "gym session")


# ── the store ──────────────────────────────────────────────────────────


def test_the_q59_store_still_reads_as_allow(store):
    store.write_text(json.dumps({"dates": ["2026-10-10", "2026-09-26"]}))
    assert ob.day_overrides() == {SHABBAT: "allow", YOM_TOV: "allow"}
    assert ob.is_exception(SHABBAT) and not ob.kept_off(SHABBAT)
    assert _verdict(SHABBAT) is None
    # the next write is in the new shape, and keeps them
    ob.set_day_override(CHOL, True)
    assert json.loads(store.read_text()) == {"allow": ["2026-09-26", "2026-10-10"],
                                             "keep_off": ["2026-09-29"]}


def test_an_override_equal_to_the_default_is_simply_removed(store):
    ob.set_day_override(SHABBAT, True)           # Shabbat is kept off anyway
    ob.set_day_override(ORDINARY, False)         # an ordinary day is open anyway
    assert ob.day_overrides() == {}
    ob.set_day_override(CHOL, True)
    ob.set_day_override(CHOL, None)
    assert ob.day_overrides() == {}


def test_junk_is_refused_before_writing(store):
    with pytest.raises(ValueError):
        ob.set_day_override("next friday", True)
    with pytest.raises(ValueError):
        ob.set_day_override(CHOL, "yes")
    with pytest.raises(ValueError):
        ob.set_day_overrides({CHOL: "block"})
    assert not store.exists()


def test_the_week_widens_over_sukkot_and_pesach():
    assert ob.week_span(dt.date(2026, 9, 29)) == (YOM_TOV, SHMINI, "Sukkot")
    assert ob.week_span(dt.date(2026, 9, 23)) == (dt.date(2026, 9, 20), SHMINI, "Sukkot")
    assert ob.week_span(dt.date(2026, 10, 14)) == (dt.date(2026, 10, 11),
                                                  dt.date(2026, 10, 17), "")
    start, end, fest = ob.week_span(dt.date(2027, 4, 25))
    assert (start, end, fest) == (dt.date(2027, 4, 22), dt.date(2027, 5, 1), "Pesach")


# ── the routes ─────────────────────────────────────────────────────────


@pytest.fixture
def client(store):
    from assistant.api.server import create_app
    return create_app().test_client()


def test_days_route_round_trips_and_resets(client, store):
    r = client.get("/observance/days?start=2026-09-26&end=2026-10-03")
    body = r.get_json()
    assert r.status_code == 200 and body["label"] == ob.SWITCH_LABEL
    assert [d["date"] for d in body["days"]][0] == "2026-09-26" and len(body["days"]) == 8
    tue = next(d for d in body["days"] if d["date"] == "2026-09-29")
    assert tue == {"date": "2026-09-29", "weekday": "Tue", "kind": "chol_hamoed",
                   "name": "Chol hamoed Succos", "default_kept_off": False,
                   "kept_off": False, "override": None}

    row = client.put("/observance/days", json={"date": "2026-09-29", "kept_off": True}).get_json()
    assert row["kept_off"] is True and row["override"] == "keep_off"
    row = client.put("/observance/days", json={"date": "2026-10-03", "kept_off": False}).get_json()
    assert row["kept_off"] is False and row["override"] == "allow"
    listed = client.get("/observance/overrides").get_json()["days"]
    assert [(d["date"], d["override"]) for d in listed] == [
        ("2026-09-29", "keep_off"), ("2026-10-03", "allow")]
    # the Q59 route maps onto allow
    assert client.get("/observance/exceptions").get_json() == {"dates": ["2026-10-03"]}

    row = client.put("/observance/days", json={"date": "2026-09-29", "kept_off": None}).get_json()
    assert row["kept_off"] is False and row["override"] is None
    assert json.loads(store.read_text()) == {"allow": ["2026-10-03"], "keep_off": []}


@pytest.mark.parametrize("body", [
    {"date": "next friday", "kept_off": True},
    {"date": "2026-09-29", "kept_off": "yes"},
    {"date": "2026-09-29", "kept_off": 1},
    {"date": "2026-09-29"},
    {"kept_off": True},
    ["2026-09-29"],
])
def test_days_route_refuses_junk_before_writing(client, store, body):
    r = client.put("/observance/days", json=body)
    assert r.status_code == 400
    assert not store.exists(), "a refused PUT still wrote the store"


@pytest.mark.parametrize("query", [
    "", "?start=2026-09-26", "?start=2026-10-03&end=2026-09-26",
    "?start=2026-01-01&end=2026-12-31", "?start=tomorrow&end=2026-10-01",
])
def test_days_route_refuses_a_bad_span(client, query):
    assert client.get(f"/observance/days{query}").status_code == 400


def test_week_route_widens_over_sukkot(client):
    body = client.get("/observance/week?today=2026-09-29").get_json()
    assert (body["start"], body["end"], body["festival"]) == ("2026-09-26", "2026-10-03", "Sukkot")
    assert [d["kept_off"] for d in body["days"]] == [True] + [False] * 6 + [True]
    plain = client.get("/observance/week?today=2026-10-14").get_json()
    assert (plain["start"], plain["end"], plain["festival"]) == ("2026-10-11", "2026-10-17", None)
    assert client.get("/observance/week?today=soon").status_code == 400


def test_the_real_store_is_never_touched(client):
    real = os.path.expanduser("~/.assistant_tools/observance_exceptions.json")
    before = os.path.getmtime(real) if os.path.exists(real) else None
    client.put("/observance/days", json={"date": "2026-09-29", "kept_off": True})
    after = os.path.getmtime(real) if os.path.exists(real) else None
    assert before == after
    assert os.environ["MACALENDAR_OBSERVANCE_EXCEPTIONS"] != real
