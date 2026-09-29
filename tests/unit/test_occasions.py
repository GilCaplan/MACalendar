"""Occasions (DEVQA Q73): a person's yearly dates and the extra calendars."""
from __future__ import annotations

import datetime

import pytest

from assistant.occasions import calendars, dates, feed, store

D = datetime.date


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PATH", tmp_path / "occasions.json")
    feed._cache.update(at=0.0, cfg=None)


# -- the store ---------------------------------------------------------------------

def test_an_occasion_round_trips():
    got, why = store.add({"kind": "birthday", "title": "Dana", "month": 3, "day": 3, "year": 1996})
    assert got and not why and got["calendar"] == "gregorian"
    got2, _ = store.update(got["id"], {"title": "Dana K"})
    assert got2["title"] == "Dana K" and store.load()[0]["title"] == "Dana K"
    assert store.delete(got["id"]) and store.load() == []


@pytest.mark.parametrize("rec,why", [
    ({"kind": "party", "title": "x", "month": 1, "day": 1}, "kind"),
    ({"kind": "birthday", "title": "", "month": 1, "day": 1}, "name"),
    ({"kind": "birthday", "title": "x", "month": 2, "day": 30}, "not a date"),
    ({"kind": "birthday", "title": "x", "calendar": "hebrew", "month": 14, "day": 1}, "Hebrew"),
    ({"kind": "countdown", "title": "Trip", "month": 5, "day": 1}, "full date"),
])
def test_nonsense_is_refused_in_words(rec, why):
    got, msg = store.add(rec)
    assert got is None and why in msg


# -- when they fall ----------------------------------------------------------------------

def test_a_birthday_counts_the_years():
    rec = {"kind": "birthday", "title": "Dana", "calendar": "gregorian", "month": 3, "day": 3, "year": 1996}
    [b] = dates.occurrences(rec, D(2026, 1, 1), D(2026, 12, 31))
    assert b["date"] == "2026-03-03" and b["title"] == "Dana's 30th birthday"


def test_feb_29_falls_on_feb_28_in_a_common_year():
    rec = {"kind": "birthday", "title": "Leap", "calendar": "gregorian", "month": 2, "day": 29}
    assert [b["date"] for b in dates.occurrences(rec, D(2027, 1, 1), D(2028, 12, 31))] == \
        ["2027-02-28", "2028-02-29"]


def test_a_hebrew_date_moves_on_the_civil_calendar():
    # 15 Shevat (Tu BiShvat): 2026-02-02 and 2027-01-23
    rec = {"kind": "custom", "title": "Tu BiShvat party", "calendar": "hebrew", "month": 11, "day": 15}
    got = [b["date"] for b in dates.occurrences(rec, D(2026, 1, 1), D(2027, 12, 31))]
    assert got == ["2026-02-02", "2027-01-23"]


def test_adar_in_a_leap_year_follows_the_custom_chosen():
    # 5787 is a leap year (two Adars); 5786 is not.
    yahr = {"kind": "yahrzeit", "title": "Grandpa", "calendar": "hebrew", "month": 12, "day": 10,
            "adar": "adar1"}
    bday = dict(yahr, kind="birthday", adar="adar2")
    both = dict(yahr, adar="both")
    rng = (D(2027, 1, 1), D(2027, 12, 31))                    # inside 5787
    from pyluach.dates import HebrewDate
    a1 = HebrewDate(5787, 12, 10).to_pydate().isoformat()
    a2 = HebrewDate(5787, 13, 10).to_pydate().isoformat()
    assert [b["date"] for b in dates.occurrences(yahr, *rng)] == [a1]
    assert [b["date"] for b in dates.occurrences(bday, *rng)] == [a2]
    assert [b["date"] for b in dates.occurrences(both, *rng)] == [a1, a2]


def test_a_30th_the_month_lacks_is_its_last_day():
    rec = {"kind": "yahrzeit", "title": "x", "calendar": "hebrew", "month": 8, "day": 30}
    from pyluach.dates import HebrewDate
    for hy in (5786, 5787):
        want = HebrewDate(hy, 8, 30) if _has_30(hy, 8) else HebrewDate(hy, 8, 29)
        start = HebrewDate(hy, 8, 1).to_pydate()
        got = dates.occurrences(rec, start, start + datetime.timedelta(days=40))
        assert got[0]["date"] == want.to_pydate().isoformat()


def _has_30(hy, m):
    from pyluach.dates import HebrewDate
    try:
        HebrewDate(hy, m, 30)
        return True
    except ValueError:
        return False


def test_titles_read_naturally():
    assert dates.banner_title("anniversary", "Gil & Dana", 5) == "Gil & Dana — 5 years"
    assert dates.banner_title("yahrzeit", "Grandpa", 12) == "Yahrzeit · Grandpa (12)"
    assert dates.ordinal(11) == "11th" and dates.ordinal(22) == "22nd"


# -- the computed calendars --------------------------------------------------------------

def test_daf_yomi_is_a_2711_day_cycle_from_berachot_2():
    assert len(calendars._DAF_SEQ) == 2711
    assert calendars.daf_on(D(2020, 1, 5)) == ("Berachot", 2)
    assert calendars.daf_on(D(2020, 1, 5) + datetime.timedelta(days=2710)) == ("Niddah", 73)
    assert calendars.daf_on(D(2020, 1, 5) + datetime.timedelta(days=2711)) == ("Berachot", 2)


def test_parasha_rosh_chodesh_and_omer_land_on_known_dates():
    par = {b["date"]: b["title"] for b in calendars.parasha(D(2026, 9, 1), D(2026, 10, 31))}
    assert par["2026-10-10"] == "Parashat Bereishis" and "2026-09-12" not in par   # Rosh Hashana
    rc = [b["date"] for b in calendars.rosh_chodesh(D(2026, 9, 1), D(2026, 10, 31))]
    assert rc == ["2026-10-11", "2026-10-12"]                  # 30 Tishrei, 1 Cheshvan
    om = calendars.omer(D(2027, 4, 1), D(2027, 6, 30))
    assert om[0] == {"date": "2027-04-23", "title": "Omer · day 1", "source": "jewish"}
    assert om[-1]["title"] == "Omer · day 49" and len(om) == 49


def test_other_calendars():
    assert {b["title"] for b in calendars.christian(D(2027, 3, 1), D(2027, 4, 30))} >= {"Easter Sunday", "Good Friday"}
    assert any(b["title"].startswith("Eid al-Fitr") and b["title"].endswith("(expected)")
               for b in calendars.islamic(D(2027, 1, 1), D(2027, 12, 31)))
    assert any(b["title"] == "Labor Day" for b in calendars.national("US", D(2026, 9, 1), D(2026, 9, 30)))
    assert calendars.national("NOPE", D(2026, 1, 1), D(2026, 12, 31)) == []


# -- the feed ----------------------------------------------------------------------------------

def test_the_feed_has_mine_editable_and_computed_switched(monkeypatch):
    from types import SimpleNamespace
    s = SimpleNamespace(parasha=True, omer=False, rosh_chodesh=False, daf_yomi=False, country="",
                        christian=False, islamic=False, holiday_types=["major"],
                        colors={"birthday": "#ec4899", "jewish": "#d4a72c"})
    monkeypatch.setattr(feed, "settings", lambda: s)
    store.add({"kind": "birthday", "title": "Dana", "month": 10, "day": 10})
    got = feed.banners(D(2026, 10, 1), D(2026, 10, 31), israel=True)
    mine = [b for b in got if b["source"] == "mine"]
    assert mine and mine[0]["editable"] and mine[0]["color"] == "#ec4899" and mine[0]["occasion_id"]
    assert [b for b in got if b["source"] == "jewish"] and all(not b["editable"] for b in got if b["source"] == "jewish")
    assert got[0]["source"] == "mine", "a person's own come first on their day"


def test_countdowns_only_ahead():
    store.add({"kind": "countdown", "title": "Wedding", "month": 12, "day": 1, "year": 2026})
    store.add({"kind": "countdown", "title": "Past", "month": 1, "day": 1, "year": 2020})
    assert feed.countdowns(D(2026, 11, 21)) == [
        {"id": store.load()[0]["id"], "title": "Wedding", "date": "2026-12-01", "days_left": 10}]


def test_hidden_holiday_types_only_affect_the_display(monkeypatch):
    from types import SimpleNamespace
    from assistant.hebrew_calendar import enumerate_holidays
    monkeypatch.setattr(feed, "settings", lambda: SimpleNamespace(holiday_types=["major"]))
    all_ = enumerate_holidays(D(2026, 9, 1), D(2026, 12, 31))
    shown = feed.shown_holidays(all_)
    assert shown and all(h.category == "major" for h in shown) and len(shown) < len(all_)


# -- routes ----------------------------------------------------------------------------------------

@pytest.fixture
def client():
    import assistant.api.server as server
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_the_routes(client):
    r = client.post("/occasions", json={"kind": "anniversary", "title": "Gil & Dana",
                                        "month": 6, "day": 20, "year": 2021})
    assert r.status_code == 201
    oid = r.get_json()["id"]
    assert client.patch(f"/occasions/{oid}", json={"day": 21}).get_json()["day"] == 21
    got = client.get("/occasions/range?start=2026-06-01&end=2026-06-30").get_json()["banners"]
    assert any(b["title"] == "Gil & Dana — 5 years" and b["date"] == "2026-06-21" for b in got)
    assert client.post("/occasions", json={"kind": "x"}).status_code == 400
    assert client.delete(f"/occasions/{oid}").status_code == 200
    assert client.delete(f"/occasions/{oid}").status_code == 404
    assert "occasions" in client.get("/config").get_json()
