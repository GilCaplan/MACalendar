"""TASKS 51 — icons beside titles (`engine/label/title_icons.py`).

A wrong icon shows on every screen a row is drawn on, so most of these pin
the NEGATIVE side: a word with two senses fires only in the one with the
icon. The cases are the ones Gil named, plus every wrong sense the board
found (`label/experiments/title_emoji_board.py`, 2026-10-01).

Since 2026-10-01 (*"i dont want emojis, rather custom made graphics"*) the
title is never written to: the views draw these drawings beside it, and the
API serves them as `icons`.
"""
from __future__ import annotations

import pathlib

import pytest

from assistant.engine.label.title_icons import has_emoji, icons, strip

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("title, want", [
    ("walk my dog", ["dog"]),
    ("date with Noa", ["heart"]),
    ("read a book", ["books"]),
    ("book club", ["books"]),
    ("go for a run", ["run"]),
    ("train to Haifa", ["train"]),
    ("dentist appointment", ["tooth"]),
    ("shiur at shul", ["scroll", "synagogue"]),
    ("dry cleaning", ["shirt"]),
    ("lunch date", ["sandwich", "heart"]),
])
def test_a_word_that_clearly_names_one_gets_it(title, want):
    assert icons(title, 2) == want


@pytest.mark.parametrize("title, never", [
    # Gil's own list
    ("eat a date", "heart"), ("due date for the essay form", "heart"), ("save the date", "heart"),
    ("update the doc", "heart"),
    # verbs that look like nouns
    ("book a table", "books"), ("book flights", "books"), ("run errands", "run"), ("run the numbers", "run"),
    ("train for the marathon", "train"), ("call it a day", "handset"), ("vet the proposal", "paw"),
    ("clean and jerk session", "broom"),
    # the board's wrong senses, 2026-10-01
    ("the interview date", "heart"), ("bottle bank", "institution"), ("bank holiday", "institution"),
    ("cling film", "movie"), ("meter reading", "books"), ("training delivery", "package"),
    ("the deck", "chart_bars"), ("shopping trip", "suitcase"), ("third party review", "celebrate"),
    ("car pool", "swim"), ("wipe my calendar clean", "broom"), ("apple store visit", "apple"),
    ("eye exam", "memo"),
])
def test_the_other_sense_stays_plain(title, never):
    assert never not in icons(title, 2)


def test_count_none_one_two():
    assert icons("birthday party for Dana", 0) == []
    assert icons("birthday party for Dana", 1) == ["cake"]
    assert icons("birthday party for Dana", 2) == ["cake", "celebrate"]


def test_one_icon_once_and_an_old_emoji_title_still_reads():
    assert icons("dog and puppy", 2) == ["dog"]
    assert icons("walk my dog 🐕", 2) == ["dog"]          # a row saved before the drawings


def test_strip_gives_back_the_words():
    assert strip("date 💕 with Noa") == "date with Noa"
    assert strip("gym 🏋️") == "gym"
    assert not has_emoji(strip("pub 🍺 garden 🌱"))


def test_every_icon_is_drawn_on_both_platforms():
    """A lexicon entry naming a drawing MACalendar does not have would draw
    nothing on the Mac and a blank on the phone."""
    from assistant.engine.label.title_icons import GROUP_ICONS, LEXICON
    for name in {e.icon for e in LEXICON} | set(GROUP_ICONS.values()):
        assert (ROOT / "assistant/calendar_ui/icons" / f"{name}.svg").exists(), name
        assert (ROOT / "MACalendar-iOS/MACalendar-iOS/Assets.xcassets/Icons"
                / f"{name}.imageset" / f"{name}.svg").exists(), name


# -- wired in ----------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    from assistant import db as db_module
    from assistant.db import CalendarDB
    real = CalendarDB(path=str(tmp_path / "icons.db"))
    monkeypatch.setattr(db_module, "get_db", lambda *a, **k: real)
    return real


def _cfg(sample_config, n, **kinds):
    from assistant.config import TitleEmojiConfig
    c = sample_config.model_copy()
    c.title_emoji = TitleEmojiConfig(count=n, **kinds)
    return c


def test_the_title_is_stored_as_words(db, sample_config):
    """The old component wrote "buy milk 🥛" into the row — which then went to
    Google, to the duplicate check and to every classifier. Now nothing does."""
    from assistant.actions.todo.action import CreateTodoAction
    from assistant.actions.todo.intent import CreateTodoIntent
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.calendar.intent import CalendarIntent
    CreateTodoAction().execute(CreateTodoIntent(titles=["buy milk"]), _cfg(sample_config, 2))
    row = db.get_todos()[0]
    assert row["title"] == "buy milk" and row["tags"] == ["Groceries"]
    intent = CalendarIntent(title="dinner with Noa", date="2026-10-08", start_time="19:00", end_time="20:00")
    CreateEventAction().execute(intent, _cfg(sample_config, 2))
    again = CreateEventAction().execute(intent, _cfg(sample_config, 2))
    rows = db.get_events_for_day(__import__("datetime").date(2026, 10, 8))
    assert [r["title"] for r in rows] == ["dinner with Noa"]
    assert "didn't add it again" in again


def test_the_api_serves_each_rows_icons(db, sample_config, monkeypatch):
    """The phone draws what the Mac draws without its own copy of the lexicon."""
    from assistant.engine.label.title_icons import attach
    rows = [{"title": "walk my dog"}, {"title": "buy milk"}, {"title": "pay rent"}]
    assert [r["icons"] for r in attach(rows, _cfg(sample_config, 2, food=False))] == \
        [["dog"], [], ["money"]]
    assert [r["icons"] for r in attach(rows, _cfg(sample_config, 0))] == [[], [], []]


def test_the_setting_is_validated_on_patch(tmp_path, monkeypatch):
    import importlib
    import yaml
    target = tmp_path / "config.yaml"
    target.write_text("theme: dark\n")
    monkeypatch.setenv("MACALENDAR_CONFIG", str(target))
    import assistant.api.server as server
    importlib.reload(server)
    app = server.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.patch("/config", json={"title_emoji": {"count": 3}}).status_code == 400
    assert c.patch("/config", json={"title_emoji": {"count": True}}).status_code == 400
    assert c.patch("/config", json={"title_emoji": {"count": 2}}).status_code == 200
    assert yaml.safe_load(target.read_text())["title_emoji"] == {"count": 2}


# -- which kinds (Gil, 2026-10-01: "allow user to decide for which categories") --

def test_a_kind_switched_off_draws_nothing_for_its_words():
    from assistant.engine.label.title_icons import GROUPS
    title = "walk my dog and buy milk"
    assert icons(title, 2, set(GROUPS)) == ["dog", "milk"]
    assert icons(title, 2, set(GROUPS) - {"food"}) == ["dog"]
    assert icons(title, 2, set()) == []


def test_every_word_belongs_to_a_kind_that_can_be_switched():
    from assistant.engine.label.title_icons import GROUP_ICONS, GROUPS, LEXICON
    assert {e.group for e in LEXICON} == set(GROUPS) == set(GROUP_ICONS)


def test_the_kinds_are_one_list_in_config_the_engine_and_the_phone():
    import re
    from assistant.config import TitleEmojiConfig
    from assistant.engine.label.title_icons import GROUPS
    assert set(TitleEmojiConfig.model_fields) - {"count"} == set(GROUPS)
    swift = (ROOT / "MACalendar-iOS/MACalendar-iOS/Views/SettingsView.swift").read_text()
    block = swift[swift.index("struct TitleEmojiKind"):swift.index("struct TitleEmojiKindsView")]
    assert re.findall(r'key: "(\w+)"', block) == list(GROUPS)


def test_patch_takes_a_kind_switch_and_refuses_anything_else(tmp_path, monkeypatch):
    import importlib
    import yaml
    target = tmp_path / "config.yaml"
    target.write_text("theme: dark\n")
    monkeypatch.setenv("MACALENDAR_CONFIG", str(target))
    import assistant.api.server as server
    importlib.reload(server)
    app = server.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.patch("/config", json={"title_emoji": {"food": False}}).status_code == 200
    assert c.patch("/config", json={"title_emoji": {"pets": False}}).status_code == 400
    assert c.patch("/config", json={"title_emoji": {"food": "no"}}).status_code == 400
    assert yaml.safe_load(target.read_text())["title_emoji"] == {"food": False}


@pytest.mark.parametrize("title,want", [
    ("Gym / Calisthenics", ["dumbbell", "bicep"]),
    ("Easy 5 km + strides", ["run"]),
    ("threshold run 3x8 min", ["run"]),
    ("speed run on the track", ["run"]),
])
def test_a_training_plans_own_words(title, want):
    """The calendar's top activities on 2026-10-01 — calisthenics and a running
    plan's run kinds — had none; on the 11,700 corpus rows the additions
    change nothing (no false positives)."""
    assert icons(title, 2) == want


# -- the phone's copy (DEVQA Q85: a phone with no Mac works icons out itself) --

def test_the_phones_lexicon_is_generated_from_this_one():
    from scripts.gen_title_icons_swift import OUT, render
    assert OUT.read_text() == render(), "stale: python -m scripts.gen_title_icons_swift"


@pytest.mark.skipif(__import__("platform").system() != "Darwin" or not __import__("shutil").which("swiftc"),
                    reason="needs swiftc")
def test_the_phone_draws_what_the_mac_draws(tmp_path):
    """The Swift matcher and the Python one, on every distinct title the
    label stage's real-titles corpus and the stress set hold."""
    import subprocess
    ios = ROOT / "MACalendar-iOS"
    exe = tmp_path / "title_icons_cli"
    subprocess.run(["swiftc", "-parse-as-library", str(ios / "MACalendar-iOS/Engine/TitleIcons.swift"),
                    str(ios / "MACalendar-iOS/Engine/TitleIconsData.swift"), str(ios / "Tools/title_icons_cli.swift"),
                    "-o", str(exe)], check=True, capture_output=True)
    from assistant.engine.label.experiments.title_emoji_board import _commands, _generated
    titles = sorted({t.strip().replace("\n", " ") for t in _commands() + _generated() if t and t.strip()})
    out = subprocess.run([str(exe)], input="\n".join(titles) + "\n", capture_output=True, text=True, check=True)
    swift = out.stdout.split("\n")[:len(titles)]
    differ = [(t, s, icons(t, 2)) for t, s in zip(titles, swift) if s.split(",") != (icons(t, 2) or [""])]
    assert len(titles) > 4000
    assert not differ, f"{len(differ)} of {len(titles)} differ, e.g. {differ[:5]}"
