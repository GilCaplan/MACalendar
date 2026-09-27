"""Exception days: the Shabbat / yom tov rule is OFF on a date the user lists
(Gil, 2026-09-26: "a way to give specific days as an exception"). Chol
hamoed was never restricted — it is an ordinary day for events."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

SHABBAT = dt.date(2026, 10, 10)          # a plain Shabbat
CHOL = dt.date(2026, 9, 29)              # chol hamoed Sukkot


@pytest.fixture
def ob():
    from assistant import observance
    observance.set_exception_dates([])
    yield observance
    observance.set_exception_dates([])


def _verdict(date, start="10:00", title="gym session"):
    from assistant.engine.decompose_validate.observance_gate import _observance_verdict
    return _observance_verdict(SimpleNamespace(title=title, description="", date=date.isoformat(),
                                               start_time=start, recurrence=None), None)


def test_an_exception_day_switches_the_rule_off_for_that_date(ob):
    from assistant.db import _skip_for_observance
    assert _verdict(SHABBAT) and _skip_for_observance(SHABBAT, "10:00", "gym session")
    ob.set_exception_dates([SHABBAT.isoformat()])
    assert _verdict(SHABBAT) is None
    assert not _skip_for_observance(SHABBAT, "10:00", "gym session")
    # the evening before belongs to the same holy window
    assert not _skip_for_observance(SHABBAT - dt.timedelta(days=1), "20:30", "gym session")


def test_chol_hamoed_is_an_ordinary_day(ob):
    from assistant.db import _skip_for_observance
    assert ob.is_chol_hamoed(CHOL) and not ob.is_yom_tov(CHOL)
    assert _verdict(CHOL) is None and not _skip_for_observance(CHOL, "10:00", "gym session")


def test_the_exceptions_route_round_trips_and_refuses_junk(ob):
    from assistant.api.server import create_app
    c = create_app().test_client()
    assert c.put("/observance/exceptions", json={"dates": ["2026-10-10", "2026-10-03"]}).get_json() \
        == {"dates": ["2026-10-03", "2026-10-10"]}
    assert c.get("/observance/exceptions").get_json() == {"dates": ["2026-10-03", "2026-10-10"]}
    assert c.put("/observance/exceptions", json={"dates": ["next friday"]}).status_code == 400
    assert c.get("/observance/exceptions").get_json()["dates"] == ["2026-10-03", "2026-10-10"]


# ── the switch over PATCH /config (the phone's toggle) ─────────────────


@pytest.fixture
def scratch_config(tmp_path, monkeypatch):
    """A scratch config.yaml, a copy of the example — never the repo's own."""
    import os
    import shutil
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = tmp_path / "config.yaml"
    shutil.copyfile(os.path.join(repo, "config.example.yaml"), cfg)
    monkeypatch.setenv("MACALENDAR_CONFIG", str(cfg))
    return cfg


def test_patch_config_writes_the_observance_switch_and_get_serves_it(scratch_config):
    import yaml
    from assistant.api.server import create_app
    from assistant.config import load_config
    c = create_app().test_client()
    assert c.get("/config").get_json()["observance"] == {"enabled": True}

    r = c.patch("/config", json={"observance": {"enabled": False}})
    assert r.status_code == 200, r.get_json()
    text = scratch_config.read_text()
    assert yaml.safe_load(text)["observance"]["enabled"] is False
    # a text edit, not a re-dump: the section's notes and its place survive
    assert "Shabbat/yom tov/fast gating" in text
    assert yaml.safe_load(text)["observance"]["timezone"] == "Asia/Jerusalem"
    assert load_config().observance.enabled is False
    assert c.get("/config").get_json()["observance"] == {"enabled": False}


@pytest.mark.parametrize("body", [
    {"enabled": "false"},
    {"enabled": 0},
    {"latitude": 0.0},
    {"enabled": False, "timezone": "UTC"},
    {},
    [False],
])
def test_patch_config_refuses_anything_but_the_switch(scratch_config, body):
    from assistant.api.server import create_app
    before = scratch_config.read_text()
    r = create_app().test_client().patch("/config", json={"observance": body})
    assert r.status_code == 400
    assert scratch_config.read_text() == before, "a refused PATCH still wrote the file"
