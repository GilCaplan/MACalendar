"""Event category classifier + neighbour-aware colour."""

import datetime

import pytest

from assistant.actions.calendar import categories as cat


@pytest.fixture(autouse=True)
def _isolated_categories(tmp_path, monkeypatch):
    monkeypatch.setattr(cat, "CATEGORIES_PATH", str(tmp_path / "categories.json"))
    cat._cache = None; cat._mtime = -1.0
    yield
    cat._cache = None; cat._mtime = -1.0


@pytest.mark.parametrize("title,expected", [
    ("Shacharit", "Prayer"),
    ("Mincha at shul", "Prayer"),
    ("Dentist appointment", "Health"),
    ("gym", "Fitness"),
    ("Lunch with Tal", "Social"),
    ("Netivim zoom", "Work"),
    ("NLP lecture", "Study"),
    ("Bagrut prep with Rei", "Study"),
    ("Flight to NYC", "Travel"),
    ("pick up package", "Errand"),
    ("Relax", "Personal"),
    ("", "Personal"),
])
def test_classify(title, expected):
    assert cat.classify(title) == expected


def test_attendees_alone_lean_social():
    assert cat.classify("Sync", attendees=["Ravid"]) == "Meeting"     # real keyword beats "with"
    assert cat.classify("Catch up", attendees="Noa") == "Meeting"


def test_user_category_add_edit_remove():
    c = cat.upsert("Volunteering", color="#112233", alt="#445566", keywords=["soup kitchen", "volunteer"])
    assert c["name"] == "Volunteering" and c["color"] == "#112233"
    assert cat.classify("Volunteer shift at the soup kitchen") == "Volunteering"
    cat.upsert("Volunteering", add_keywords=["Leket"])
    assert "leket" in cat.get("Volunteering")["keywords"]
    assert cat.remove("Volunteering")
    assert cat.get("Volunteering") is None
    assert cat.classify("volunteer") == "Personal"


def test_personal_cannot_be_removed_and_bad_color_rejected():
    assert not cat.remove("Personal")
    with pytest.raises(ValueError):
        cat.upsert("X", color="red")


def test_pick_color_avoids_neighbours():
    primary, alt = cat.color_for("Social")
    assert cat.pick_color("Social", []) == primary
    assert cat.pick_color("Social", [primary]) == alt
    third = cat.pick_color("Social", [primary, alt])
    assert third not in (primary, alt) and third.startswith("#") and len(third) == 7


def test_db_assigns_category_and_alternating_colours(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    from assistant.db import CalendarDB
    db = CalendarDB()
    day = "2026-08-27"
    db.create_event_from_dict({"title": "Lunch with Tal", "date": day, "start_time": "12:00", "end_time": "13:00"})
    db.create_event_from_dict({"title": "Coffee with Noa", "date": day, "start_time": "13:00", "end_time": "14:00"})
    db.create_event_from_dict({"title": "Dentist", "date": day, "start_time": "16:00", "end_time": "17:00", "color": "#123456"})
    ev = {e["title"]: e for e in db.get_events_for_day(datetime.date(2026, 8, 27))}
    social, social_alt = cat.color_for("Social")
    assert ev["Lunch with Tal"]["category"] == "Social" and ev["Lunch with Tal"]["color"] == social
    assert ev["Coffee with Noa"]["color"] == social_alt            # neighbour had the primary
    assert ev["Dentist"]["category"] == "Health" and ev["Dentist"]["color"] == "#123456"   # explicit colour kept
    assert db.recategorise_all(force=False) == 0                    # nothing left on defaults
    assert db.recategorise_all(force=True) == 3
    ev = {e["title"]: e for e in db.get_events_for_day(datetime.date(2026, 8, 27))}
    assert ev["Dentist"]["color"] == cat.color_for("Health")[0]


# ---------------------------------------------------------------------------
# THE COLOUR SENTINEL (2026-09-10) — a caller with no colour choice must not
# claim one, or the category colour never applies.
# ---------------------------------------------------------------------------

def test_a_voice_created_event_gets_its_category_colour(tmp_path, monkeypatch):
    """The measured defect: `actions/calendar/action.py` passed
    `styles.BLUE`, which stopped meaning "the default blue" when the accent
    became configurable. `auto_category_and_color` read it as a deliberate
    choice, `pick_color` never ran, and 11 of 54 real events came out the same
    amber across four different categories."""
    from assistant.actions.calendar.intent import CalendarIntent
    from assistant.db import CalendarDB
    from assistant.actions.calendar import categories as _cat

    db = CalendarDB(str(tmp_path / "c.db"))
    gym = db.create_event(CalendarIntent(title="gym session", date="2026-09-14",
                                         start_time="07:00"))
    work = db.create_event(CalendarIntent(title="standup with the team",
                                          date="2026-09-14", start_time="09:00"))
    gym_row, work_row = db.get_event(gym), db.get_event(work)

    # each one wears ITS OWN category's colour…
    assert gym_row["color"] == _cat.color_for(gym_row["category"])[0]
    assert work_row["color"] == _cat.color_for(work_row["category"])[0]
    # …and two different categories are not the same colour.
    assert gym_row["category"] != work_row["category"]
    assert gym_row["color"] != work_row["color"]


def test_an_explicit_colour_is_still_honoured(tmp_path):
    """The fix must not break colour PICKING: a user who chose a swatch keeps
    it, even when it happens to equal the UI accent."""
    from assistant.actions.calendar.intent import CalendarIntent
    from assistant.db import CalendarDB

    db = CalendarDB(str(tmp_path / "c.db"))
    eid = db.create_event(CalendarIntent(title="gym", date="2026-09-14",
                                         start_time="07:00"), color="#f5a524")
    assert db.get_event(eid)["color"] == "#f5a524"


def test_adjacent_events_never_share_a_colour(tmp_path):
    """The stated invariant, checked end to end rather than on `pick_color`
    alone — the neighbour lookup is a query, and the query is the part that can
    be wrong."""
    from assistant.actions.calendar.intent import CalendarIntent
    from assistant.db import CalendarDB

    db = CalendarDB(str(tmp_path / "c.db"))
    a = db.create_event(CalendarIntent(title="gym session", date="2026-09-14",
                                       start_time="07:00"))
    b = db.create_event(CalendarIntent(title="gym session", date="2026-09-14",
                                       start_time="09:00"))
    assert db.get_event(a)["color"] != db.get_event(b)["color"]


def test_every_instance_of_a_series_carries_the_category(tmp_path):
    """Instance 1 was categorised and instances 2..n were not: the expansion
    INSERT omitted the column entirely. An uncategorised instance falls through
    `color_for()` to Personal's colour and is invisible to every per-category
    setting — reminder leads, notification rules, filters."""
    from assistant.actions.calendar.intent import CalendarIntent
    from assistant.db import CalendarDB

    db = CalendarDB(str(tmp_path / "c.db"))
    first = db.create_event(CalendarIntent(
        title="gym session", date="2026-09-14", start_time="07:00",
        recurrence="weekly", recur_until="2026-10-19"))
    want = db.get_event(first)["category"]
    assert want

    with db._conn() as conn:
        rows = conn.execute(
            "SELECT category, color FROM events WHERE series_id = ? OR id = ?",
            (first, first)).fetchall()
    assert len(rows) > 1, "the series did not expand"
    assert all((r[0] or "") == want for r in rows), [r[0] for r in rows]
    assert all(r[1] for r in rows), "an instance was written with no colour"
