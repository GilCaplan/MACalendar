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


# ---------------------------------------------------------------------------
# The phone declares the same seven
# ---------------------------------------------------------------------------
#
# Structure is declared in CODE on each platform, on purpose — a tab bar built
# from GET /features could not be drawn until the Mac answered, and with the Mac
# asleep it would never be drawn at all. The price of that choice is TWO
# declarations, and the convention's own last rule is "never let registration be
# two lists". These tests are what keeps the price payable: the phone's list may
# live in Swift, but it may not drift.

def _ios_features():
    """Parse `Feature(...)` out of the iOS registry.

    By NAME, not by path (see `_ios_sources`): the file moved into
    `Features/` in the same change that created it.
    """
    import re
    from tests.unit._ios_sources import ios_source

    source = ios_source("FeatureRegistry.swift")
    body = source.split("static let all: [Feature] = [", 1)[1]
    out = {}
    for chunk in body.split("Feature(name:")[1:]:
        name = re.search(r'^\s*"([a-z]+)"', chunk).group(1)
        out[name] = {
            "label": re.search(r'label:\s*"([^"]+)"', chunk).group(1),
            "icon": re.search(r'icon:\s*"([^"]+)"', chunk).group(1),
            "order": int(re.search(r"order:\s*(\d+)", chunk).group(1)),
            "pinned": "pinned: true" in chunk,
            "default_visible": "defaultVisible: false" not in chunk,
        }
    return out


def test_the_ios_registry_declares_the_same_features():
    ios = _ios_features()
    mac = {f.name: f for f in registry.all_features()}
    assert set(ios) == set(mac), "the two clients disagree about which tabs exist"
    for name, declared in ios.items():
        f = mac[name]
        # `name` and `order` are the two that TRAVEL: the name is the URL
        # segment and the config key, and the order is the one both tab bars
        # sort by. A mismatch there is a tab that cannot be switched off from
        # the other machine, or two surfaces in different places.
        assert declared["order"] == f.order, name
        assert declared["label"] == f.label, name
        assert declared["icon"] == f.icon, name
        assert declared["pinned"] == f.pinned, name
        assert declared["default_visible"] == f.default_visible, name


def test_the_phone_never_offers_a_pinned_feature_as_a_toggle():
    """Settings loops over `FeatureRegistry.togglable`, so a pinned feature
    has no switch to flip — the 409 exists for a PATCH from anywhere else."""
    from tests.unit._ios_sources import ios_source

    settings_view = ios_source("SettingsView.swift")
    assert "ForEach(FeatureRegistry.togglable)" in settings_view
    assert "showJudeTab" not in settings_view, "a hand-written tab toggle came back"


def test_the_phone_has_one_bounce_off_for_every_feature():
    """Timer was the optional tab nobody wrote an `onChange` handler for, so
    hiding it while it was on screen left a blank screen with a working tab bar
    under it. One generic rule, not seven."""
    from tests.unit._ios_sources import ios_source

    shell = ios_source("ContentView.swift")
    assert "bounceOffHidden" in shell
    assert "selectedTab" not in shell, "the magic Int tabs came back"


# ---------------------------------------------------------------------------
# explicit vs default — the merge rule, and the bug it exists to stop
# ---------------------------------------------------------------------------

def test_a_default_is_not_reported_as_a_choice(scratch_config):
    """The bug: a phone with Jude switched ON had it switched off by a Mac that
    had never been asked about Jude. `config.yaml` had no `features:` block, so
    `visible: false` was just `default_visible` — and the client, unable to
    tell a choice from a default, adopted it.
    """
    import yaml
    scratch_config.write_text(yaml.dump({"ui": {"show_coursework": False}}))
    assert settings.is_explicit("coursework") is True    # a legacy key IS a choice
    assert settings.is_explicit("jude") is False         # nobody ever said
    assert settings.is_explicit("teach") is False


def test_writing_a_flag_makes_it_explicit(scratch_config):
    assert settings.is_explicit("timer") is False
    settings.set_visible("timer", True)
    assert settings.is_explicit("timer") is True


def test_manifest_carries_explicit_for_every_feature(scratch_config):
    for f in registry.all_features():
        m = f.manifest()
        assert "explicit" in m, f.name
        assert isinstance(m["explicit"], bool)


def test_pinned_features_are_always_explicit():
    """They cannot be changed, so there is no default to fall back to and
    nothing for a client to push up."""
    for f in registry.all_features():
        if f.pinned:
            assert f.manifest()["explicit"] is True, f.name


def test_patching_turns_a_default_into_a_choice(client, scratch_config):
    before = [f for f in client.get("/features").get_json() if f["name"] == "teach"][0]
    assert before["explicit"] is False
    client.patch("/features/teach", json={"visible": False})
    after = [f for f in client.get("/features").get_json() if f["name"] == "teach"][0]
    assert after["explicit"] is True and after["visible"] is False


def test_the_ios_merge_keeps_a_local_choice_over_a_mac_default():
    """Pinned in the Swift source, because it is the half of the rule that
    cannot be checked from Python and is the half that broke."""
    from tests.unit._ios_sources import ios_source
    swift = ios_source("FeatureRegistry.swift")
    assert "manifest.explicit" in swift, (
        "the iOS refresh no longer branches on `explicit` — a Mac default can "
        "again overwrite a switch the user flipped on the phone")
    # And it must push its own value up rather than just keeping it locally,
    # or the two disagree forever and every poll re-does this work.
    assert "setFeatureVisible" in swift



def test_the_visibility_merge_has_no_suspension_point_in_its_critical_section():
    """Reading the map and writing it back must not be separated by an `await`.

    Raised as a possible race: a toggle made while `refresh` was in flight
    being clobbered by the Mac's answer — the switch springing back with no
    explanation. It does not apply, and this is what keeps it that way.

    `FeatureVisibility` is `@MainActor`, so the only way another actor can
    interleave is at a suspension point. The network call happens BEFORE the
    snapshot is taken, and the push-up happens AFTER the commit; between the
    read and the write there is no `await`, so the merge is atomic. Moving the
    fetch between them would reintroduce the race without changing a line that
    looks wrong.
    """
    import re
    from tests.unit._ios_sources import ios_source
    src = ios_source("FeatureRegistry.swift")
    start = src.index("    func refresh(api: APIClient) async {")
    body = src[start:]
    body = body[:body.index("\n    }\n") + 6].split("\n")

    snapshot = next(i for i, l in enumerate(body) if "var updated = map" in l)
    commit = next(i for i, l in enumerate(body) if re.match(r"\s+map = updated", l))
    assert snapshot < commit
    between = [l.strip() for l in body[snapshot:commit + 1] if "await" in l]
    assert not between, (
        "an await sits between reading the visibility map and writing it back: "
        f"{between} — a toggle made during the fetch can now be clobbered")
