"""The default event length and chain gap (DEVQA Q51, 2026-09-25).

Gil: *"a default thing in the settings … what between chained events what that
gap could be … and what the default length of an event is … or according to
the category, each category to have its default length."*

`assistant/event_defaults.py` is the one read the engine and both apps use.
Each value resolves CATEGORY -> GLOBAL (config.yaml `events:`) -> BUILT-IN
(60 / 0). This file pins that order, the store that carries the per-category
fields, the routes that read and write both levels, and the one engine choke
point that consumes the length (`CalendarIntent.fill_defaults`).

Every store here is a scratch file: `MACALENDAR_CONFIG` is pointed at a
tmp_path copy of config.example.yaml and the categories module at a tmp json,
so nothing reaches config.yaml or ~/.assistant_tools.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest
import yaml

from assistant import event_defaults
from assistant.actions.calendar import categories as cat

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _scratch(tmp_path, monkeypatch):
    """A scratch config.yaml (a copy of the example, so AppConfig loads) and a
    scratch categories.json, and both caches emptied either side."""
    cfg = tmp_path / "config.yaml"
    shutil.copyfile(os.path.join(_REPO, "config.example.yaml"), cfg)
    monkeypatch.setenv("MACALENDAR_CONFIG", str(cfg))
    monkeypatch.setattr(cat, "CATEGORIES_PATH", str(tmp_path / "categories.json"))
    cat._cache = None
    cat._mtime = -1.0
    event_defaults._cfg_cache.clear()
    yield cfg
    cat._cache = None
    cat._mtime = -1.0
    event_defaults._cfg_cache.clear()


def _set_events(cfg, **values) -> None:
    data = yaml.safe_load(cfg.read_text()) or {}
    if values:
        data["events"] = values
    else:
        data.pop("events", None)
    cfg.write_text(yaml.safe_dump(data))
    # The cache is keyed on mtime; two writes inside one timestamp tick would
    # look unchanged, so move the clock on explicitly.
    st = os.stat(cfg)
    os.utime(cfg, (st.st_atime, st.st_mtime + 1))


# ---------------------------------------------------------------------------
# Resolution order: category -> global -> built-in
# ---------------------------------------------------------------------------

def test_builtin_defaults_when_nothing_is_set(_scratch):
    _set_events(_scratch)                       # no events: section at all
    assert event_defaults.length_minutes() == 60
    assert event_defaults.gap_minutes() == 0
    assert event_defaults.length_minutes("Fitness") == 60
    assert event_defaults.gap_minutes("Fitness") == 0


def test_the_example_config_ships_the_builtin_values(_scratch):
    """config.example.yaml mirrors the setting with the same values the code
    defaults to, so copying it changes nothing."""
    data = yaml.safe_load(open(os.path.join(_REPO, "config.example.yaml")))
    assert data["events"] == {"event_length_minutes": 60, "chain_gap_minutes": 0}
    assert event_defaults.length_minutes() == 60


def test_global_setting_beats_the_builtin(_scratch):
    _set_events(_scratch, event_length_minutes=45, chain_gap_minutes=15)
    assert event_defaults.length_minutes() == 45
    assert event_defaults.gap_minutes() == 15
    # A category with no value of its own follows the global.
    assert event_defaults.length_minutes("Work") == 45
    assert event_defaults.gap_minutes("Work") == 15


def test_category_value_beats_the_global(_scratch):
    _set_events(_scratch, event_length_minutes=45, chain_gap_minutes=15)
    cat.upsert("Fitness", default_minutes=90, chain_gap_minutes=30)
    assert event_defaults.length_minutes("Fitness") == 90
    assert event_defaults.gap_minutes("Fitness") == 30
    assert event_defaults.length_minutes("fitness") == 90     # names are case-blind
    # ...and only for that category.
    assert event_defaults.length_minutes("Study") == 45


def test_a_category_can_override_one_field_and_inherit_the_other(_scratch):
    _set_events(_scratch, event_length_minutes=45, chain_gap_minutes=15)
    cat.upsert("Meal", default_minutes=30)
    assert event_defaults.length_minutes("Meal") == 30
    assert event_defaults.gap_minutes("Meal") == 15


def test_an_unknown_category_follows_the_global(_scratch):
    _set_events(_scratch, event_length_minutes=50)
    assert event_defaults.length_minutes("No Such Category") == 50


def test_a_new_setting_is_read_without_a_restart(_scratch):
    _set_events(_scratch, event_length_minutes=45)
    assert event_defaults.length_minutes() == 45
    _set_events(_scratch, event_length_minutes=75)
    assert event_defaults.length_minutes() == 75


def test_config_path_is_the_repo_file_not_the_working_directory(monkeypatch, tmp_path):
    """It used to open a bare "config.yaml" — right only when the process ran
    from the repo root. Anything else (a script, a LaunchAgent) read nothing
    and silently used 60 / 0."""
    monkeypatch.delenv("MACALENDAR_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert event_defaults.config_path() == os.path.join(_REPO, "config.yaml")


def test_config_path_honours_the_override(_scratch):
    assert event_defaults.config_path() == str(_scratch)


def test_a_bad_value_in_the_file_is_clamped_not_fatal(_scratch):
    _set_events(_scratch, event_length_minutes="lots", chain_gap_minutes=-5)
    assert event_defaults.length_minutes() == 60
    assert event_defaults.gap_minutes() == 0


def test_the_app_config_carries_the_section(_scratch):
    from assistant.config import load_config
    _set_events(_scratch, event_length_minutes=40, chain_gap_minutes=10)
    events = load_config(str(_scratch)).events
    assert (events.event_length_minutes, events.chain_gap_minutes) == (40, 10)


def test_category_of_uses_the_label_rules(_scratch):
    assert event_defaults.category_of("gym") == "Fitness"
    assert event_defaults.category_of("dentist appointment") == "Health"


# ---------------------------------------------------------------------------
# The categories store carries the two fields without disturbing the rest
# ---------------------------------------------------------------------------

def test_upsert_sets_and_clears_the_fields(_scratch):
    c = cat.upsert("Fitness", default_minutes=90, chain_gap_minutes=10)
    assert c["default_minutes"] == 90 and c["chain_gap_minutes"] == 10
    # Leaving an argument out keeps what is stored.
    cat.upsert("Fitness", color="#112233")
    c = cat.get("Fitness")
    assert c["default_minutes"] == 90 and c["color"] == "#112233"
    # None clears it back to the global.
    cat.upsert("Fitness", default_minutes=None)
    c = cat.get("Fitness")
    assert "default_minutes" not in c and c["chain_gap_minutes"] == 10


def test_fields_survive_alongside_keywords_colours_and_removed(_scratch):
    cat.upsert("Volunteering", color="#112233", alt="#445566", keywords=["soup kitchen"])
    assert cat.remove("Travel")
    cat.upsert("Volunteering", default_minutes=120)
    cat.upsert("Work", chain_gap_minutes=5)

    stored = json.load(open(cat.CATEGORIES_PATH))
    assert "Travel" in stored["removed"], "the removed list was lost"
    vol = cat.get("Volunteering")
    assert vol["keywords"] == ["soup kitchen"] and vol["color"] == "#112233"
    assert vol["default_minutes"] == 120 and vol.get("custom") is True
    work = cat.get("Work")
    assert work["chain_gap_minutes"] == 5
    assert "standup" in work["keywords"], "a built-in's keywords were dropped"
    assert cat.get("Travel") is None
    assert cat.classify("volunteer shift at the soup kitchen") == "Volunteering"


@pytest.mark.parametrize("field,value", [
    ("default_minutes", 0),          # zero length would read as "no end said"
    ("default_minutes", 2000),
    ("default_minutes", "ninety"),
    ("default_minutes", True),
    ("default_minutes", 12.5),
    ("chain_gap_minutes", -1),
])
def test_upsert_refuses_bad_minutes_and_writes_nothing(_scratch, field, value):
    with pytest.raises(ValueError):
        cat.upsert("Fitness", **{field: value})
    assert not os.path.exists(cat.CATEGORIES_PATH)


def test_a_hand_edited_out_of_range_value_reads_as_absent(_scratch):
    with open(cat.CATEGORIES_PATH, "w") as f:
        json.dump({"categories": [{"name": "Work", "default_minutes": -3}], "removed": []}, f)
    cat._cache = None
    assert "default_minutes" not in cat.get("Work")
    assert event_defaults.length_minutes("Work") == 60


# ---------------------------------------------------------------------------
# The engine choke point: CalendarIntent.fill_defaults
# ---------------------------------------------------------------------------

def _intent(**kw):
    from assistant.actions.calendar.intent import CalendarIntent
    return CalendarIntent(**kw)


def test_fill_defaults_uses_an_hour_out_of_the_box(_scratch):
    _set_events(_scratch)
    assert _intent(title="Relax", date="2026-10-01", start_time="10:00").end_time == "11:00"


def test_fill_defaults_uses_the_global_length(_scratch):
    _set_events(_scratch, event_length_minutes=45)
    assert _intent(title="Relax", date="2026-10-01", start_time="10:00").end_time == "10:45"


def test_fill_defaults_uses_the_titles_category_length(_scratch):
    _set_events(_scratch, event_length_minutes=45)
    cat.upsert("Fitness", default_minutes=90)
    assert _intent(title="gym", date="2026-10-01", start_time="07:00").end_time == "08:30"
    # A title of another category still gets the global.
    assert _intent(title="Relax", date="2026-10-01", start_time="07:00").end_time == "07:45"


def test_fill_defaults_keeps_a_said_end(_scratch):
    _set_events(_scratch, event_length_minutes=45)
    got = _intent(title="Relax", date="2026-10-01", start_time="10:00", end_time="12:00")
    assert got.end_time == "12:00"


def test_fill_defaults_still_treats_end_equal_start_as_missing(_scratch):
    _set_events(_scratch, event_length_minutes=30)
    got = _intent(title="Relax", date="2026-10-01", start_time="10:00", end_time="10:00")
    assert got.end_time == "10:30"


def test_fill_defaults_still_caps_at_2359(_scratch):
    _set_events(_scratch, event_length_minutes=120)
    got = _intent(title="Relax", date="2026-10-01", start_time="23:00")
    assert got.end_time == "23:59"


def test_the_judge_reads_the_same_length_as_a_default_not_a_claim(_scratch):
    """`llmjudge.render._is_derived_end` drops a defaulted end from the
    claims. It hard-coded an hour, so a 90-minute setting would have made every
    defaulted end look invented."""
    from assistant.engine.llmjudge.render import _is_derived_end
    _set_events(_scratch, event_length_minutes=90)
    intent = _intent(title="Relax", date="2026-10-01", start_time="10:00")
    assert intent.end_time == "11:30"
    assert _is_derived_end("end_time", intent)
    said = _intent(title="Relax", date="2026-10-01", start_time="10:00", end_time="11:00")
    assert not _is_derived_end("end_time", said)


# ---------------------------------------------------------------------------
# The routes (Flask test client — never a live port)
# ---------------------------------------------------------------------------

@pytest.fixture
def client(_scratch):
    from assistant.api.server import create_app
    return create_app().test_client()


def test_get_config_serves_the_events_section(client, _scratch):
    _set_events(_scratch, event_length_minutes=50, chain_gap_minutes=5)
    body = client.get("/config").get_json()
    assert body["events"] == {"event_length_minutes": 50, "chain_gap_minutes": 5}


def test_patch_config_writes_the_events_section_and_keeps_comments(client, _scratch):
    before = _scratch.read_text()
    # Put a comment in to prove the write is a text edit, not a re-dump.
    _scratch.write_text("# my notes\n" + before)
    r = client.patch("/config", json={"events": {"event_length_minutes": 40,
                                                 "chain_gap_minutes": 10}})
    assert r.status_code == 200, r.get_json()
    text = _scratch.read_text()
    assert "# my notes" in text
    assert yaml.safe_load(text)["events"] == {"event_length_minutes": 40, "chain_gap_minutes": 10}
    assert event_defaults.length_minutes() == 40
    assert event_defaults.gap_minutes() == 10


@pytest.mark.parametrize("events", [
    {"event_length_minutes": 0},
    {"event_length_minutes": "90"},
    {"event_length_minutes": True},
    {"chain_gap_minutes": -5},
    {"chain_gap_minutes": 99999},
    {"not_a_setting": 5},
    [60, 0],
])
def test_patch_config_refuses_a_bad_events_value(client, _scratch, events):
    before = _scratch.read_text()
    r = client.patch("/config", json={"events": events})
    assert r.status_code == 400
    assert _scratch.read_text() == before, "a refused PATCH still wrote the file"


def test_get_categories_carries_the_fields_and_the_globals(client, _scratch):
    _set_events(_scratch, event_length_minutes=45, chain_gap_minutes=15)
    cat.upsert("Fitness", default_minutes=90)
    body = client.get("/categories").get_json()
    fitness = next(c for c in body["categories"] if c["name"] == "Fitness")
    assert fitness["default_minutes"] == 90 and "chain_gap_minutes" not in fitness
    assert body["defaults"] == {"event_length_minutes": 45, "chain_gap_minutes": 15}


def test_post_categories_sets_clears_and_leaves_alone(client, _scratch):
    r = client.post("/categories", json={"name": "Fitness", "default_minutes": 90,
                                         "chain_gap_minutes": 10})
    assert r.status_code == 200 and r.get_json()["default_minutes"] == 90
    # A body that does not name the fields leaves them alone.
    client.post("/categories", json={"name": "Fitness", "color": "#123456"})
    assert cat.get("Fitness")["default_minutes"] == 90
    # null clears one back to the global.
    r = client.post("/categories", json={"name": "Fitness", "default_minutes": None})
    got = r.get_json()
    assert "default_minutes" not in got and got["chain_gap_minutes"] == 10


def test_post_categories_refuses_a_bad_minute_value(client, _scratch):
    r = client.post("/categories", json={"name": "Fitness", "default_minutes": -10})
    assert r.status_code == 400
    assert "default_minutes" not in cat.get("Fitness")


def test_event_defaults_route_resolves_by_category_and_by_title(client, _scratch):
    _set_events(_scratch, event_length_minutes=45, chain_gap_minutes=15)
    cat.upsert("Fitness", default_minutes=90, chain_gap_minutes=0)

    body = client.get("/event_defaults").get_json()
    assert (body["length_minutes"], body["gap_minutes"]) == (45, 15)
    assert body["category"] is None

    body = client.get("/event_defaults?category=Fitness").get_json()
    assert (body["length_minutes"], body["gap_minutes"]) == (90, 0)

    body = client.get("/event_defaults?title=gym%20workout").get_json()
    assert body["category"] == "Fitness"
    assert body["length_minutes"] == 90
    assert body["event_length_minutes"] == 45     # the global rides along
