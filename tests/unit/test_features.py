"""The Feature convention: declaration, visibility, and the two routes.

A Feature is one of THIS assistant's surfaces (a tab on the phone, a panel on
the Mac). It is not an `assistant/integrations/` Integration, which hosts
somebody else's program — `test_integrations.py` covers that one.
"""

from __future__ import annotations

import os
import pathlib

import pytest
import yaml
from flask import Flask

from assistant.features import registry, settings
from assistant.features.base import Feature


@pytest.fixture
def scratch_config(tmp_path, monkeypatch):
    """A config.yaml of our own, with a couple of unrelated settings in it so
    a clobbering write is visible."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({
        "ui": {"show_coursework": False, "font_month": 11},
        "ollama": {"model": "llama3.1:8b"},
    }))
    monkeypatch.setenv("MACALENDAR_CONFIG", str(path))
    return path


@pytest.fixture
def client():
    app = Flask(__name__)
    registry.register(app)
    return app.test_client()


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------

def test_every_feature_declares_the_whole_contract():
    for f in registry.all_features():
        assert f.name and f.name == f.name.lower(), f
        assert f.label and f.icon, f.name
        assert isinstance(f.pinned, bool) and isinstance(f.default_visible, bool)


def test_names_and_orders_are_unique():
    features = registry.all_features()
    names = [f.name for f in features]
    assert len(names) == len(set(names)), names
    orders = [f.order for f in features]
    assert orders == sorted(orders), "all_features() must return display order"
    assert len(orders) == len(set(orders)), "two features claim the same slot"


def test_orders_are_sparse_so_inserting_one_renumbers_nothing():
    """Sequential orders mean adding a feature between two others rewrites
    every one after it — the kind of churn that makes people append instead."""
    orders = sorted(f.order for f in registry.all_features())
    gaps = [b - a for a, b in zip(orders, orders[1:])]
    assert all(g >= 5 for g in gaps), orders


def test_each_feature_owns_a_folder():
    """CONVENTION.md's rule. A feature declared but not foldered is the first
    step back towards everything living in server.py."""
    root = pathlib.Path("assistant/features")
    for f in registry.all_features():
        assert (root / f.name / "feature.py").is_file(), f.name


def test_manifest_shape_is_identical_for_every_feature():
    """One shape means a client that can draw one can draw the next."""
    shapes = {frozenset(f.manifest()) for f in registry.all_features()}
    assert len(shapes) == 1, shapes


def test_blueprint_is_declared_not_duck_typed():
    """A misspelled `blueprint` would otherwise register NO routes and still
    start cleanly — the bug this convention inherited from the integrations one.
    """
    assert hasattr(Feature, "blueprint")
    assert Feature.blueprint(object.__new__(registry.get("tasks").__class__)) is None


# ---------------------------------------------------------------------------
# Pinned
# ---------------------------------------------------------------------------

def test_calendar_and_tasks_are_pinned():
    """What the app IS. A switch that empties the app is not a feature."""
    assert registry.get("calendar").pinned
    assert registry.get("tasks").pinned


def test_a_pinned_feature_is_always_visible_whatever_the_config_says(scratch_config):
    scratch_config.write_text(yaml.dump({"features": {"calendar": False}}))
    assert registry.get("calendar").visible() is True


def test_hiding_a_pinned_feature_raises_with_a_sentence(scratch_config):
    with pytest.raises(ValueError) as e:
        registry.get("tasks").set_visible(False)
    assert "can't be hidden" in str(e.value)


# ---------------------------------------------------------------------------
# Visibility, and the migration off three separate systems
# ---------------------------------------------------------------------------

def test_legacy_ui_keys_are_honoured_when_features_is_absent(scratch_config):
    """Nobody's existing config.yaml may silently turn three tabs back on."""
    assert settings.is_visible("coursework", True) is False
    assert settings.is_visible("workout", True) is True     # absent -> default


def test_features_block_wins_over_the_legacy_key(scratch_config):
    data = yaml.safe_load(scratch_config.read_text())
    data["features"] = {"coursework": True}
    scratch_config.write_text(yaml.dump(data))
    assert settings.is_visible("coursework", False) is True


def test_a_write_preserves_every_other_setting(scratch_config):
    """It rewrites the WHOLE document, so a bug here costs the config the
    assistant boots from, not just the flag under test."""
    settings.set_visible("timer", False)
    data = yaml.safe_load(scratch_config.read_text())
    assert data["features"]["timer"] is False
    assert data["ollama"]["model"] == "llama3.1:8b"
    assert data["ui"]["font_month"] == 11


def test_unknown_feature_falls_back_to_its_default(scratch_config):
    assert settings.is_visible("nonexistent", True) is True
    assert settings.is_visible("nonexistent", False) is False


def test_an_unreadable_config_does_not_blank_the_tab_bar(monkeypatch, tmp_path):
    """Every feature falls back to its own default rather than vanishing."""
    monkeypatch.setenv("MACALENDAR_CONFIG", str(tmp_path / "does-not-exist.yaml"))
    assert settings.is_visible("timer", True) is True


def test_jude_is_the_one_feature_that_ships_off():
    """It needs a checkout on the Mac, and a tab that can only say
    "not installed" is not a feature."""
    off = [f.name for f in registry.all_features() if not f.default_visible]
    assert off == ["jude"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def test_get_features_lists_everything_in_order(client):
    got = client.get("/features").get_json()
    assert [f["name"] for f in got] == [f.name for f in registry.all_features()]


def test_patch_round_trips(client, scratch_config):
    assert client.patch("/features/timer", json={"visible": False}
                        ).get_json()["visible"] is False
    assert client.patch("/features/timer", json={"visible": True}
                        ).get_json()["visible"] is True


def test_patch_a_pinned_feature_is_409_with_the_reason(client, scratch_config):
    r = client.patch("/features/calendar", json={"visible": False})
    assert r.status_code == 409
    assert "can't be hidden" in r.get_json()["error"]


def test_patch_unknown_is_404_and_missing_body_is_400(client):
    assert client.patch("/features/nope", json={"visible": True}).status_code == 404
    assert client.patch("/features/timer", json={}).status_code == 400


# ---------------------------------------------------------------------------
# The two conventions must not be confused
# ---------------------------------------------------------------------------

def test_a_feature_is_not_an_integration():
    """Tasks has no checkout, no port and no subprocess. Inheriting those would
    mean five methods returning None to satisfy a base class describing
    something it isn't."""
    from assistant.integrations.base import Integration
    for f in registry.all_features():
        assert not isinstance(f, Integration), f.name
        for absent in ("root", "command", "port", "start_timeout_s"):
            assert not hasattr(f, absent), f"{f.name} grew an Integration's {absent}"


def test_jude_is_both_a_feature_and_an_integration():
    """The one surface that is both, and they mean different things:
    `features.jude` is whether you want the tab, `jude.enabled` is whether the
    program behind it is wired up at all."""
    from assistant.integrations import registry as integrations
    assert registry.get("jude") is not None
    assert integrations.get("jude") is not None
    assert registry.get("jude") is not integrations.get("jude")
