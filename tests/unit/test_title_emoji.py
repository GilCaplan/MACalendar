"""TASKS 51 — emoji in titles (`engine/label/title_emoji.py`).

A wrong emoji shows on every screen a row is drawn on, so most of these pin
the NEGATIVE side: a word with two senses fires only in the one with the
emoji. The cases are the ones Gil named, plus every wrong sense the board
found (`label/experiments/title_emoji_board.py`, 2026-10-01).
"""
from __future__ import annotations

import pytest

from assistant.engine.label.title_emoji import decorate, has_emoji, strip


@pytest.mark.parametrize("title, want", [
    ("walk my dog", "walk my dog 🐕"),
    ("date with Noa", "date 💕 with Noa"),
    ("read a book", "read a book 📚"),
    ("book club", "book club 📚"),
    ("go for a run", "go for a run 🏃"),
    ("train to Haifa", "train 🚆 to Haifa"),
    ("dentist appointment", "dentist 🦷 appointment"),
    ("shiur at shul", "shiur 📜 at shul 🕍"),
    ("dry cleaning", "dry cleaning 👔"),
    ("lunch date", "lunch 🥪 date 💕"),
])
def test_a_word_that_clearly_names_one_gets_it(title, want):
    assert decorate(title, 2) == want


@pytest.mark.parametrize("title, never", [
    # Gil's own list
    ("eat a date", "💕"), ("due date for the essay form", "💕"), ("save the date", "💕"),
    ("update the doc", "💕"),
    # verbs that look like nouns
    ("book a table", "📚"), ("book flights", "📚"), ("run errands", "🏃"), ("run the numbers", "🏃"),
    ("train for the marathon", "🚆"), ("call it a day", "📞"), ("vet the proposal", "🐾"),
    ("clean and jerk session", "🧹"),
    # the board's wrong senses, 2026-10-01
    ("the interview date", "💕"), ("bottle bank", "🏦"), ("bank holiday", "🏦"), ("cling film", "🎬"),
    ("meter reading", "📚"), ("training delivery", "📦"), ("the deck", "📊"), ("shopping trip", "🧳"),
    ("third party review", "🎉"), ("car pool", "🏊"), ("wipe my calendar clean", "🧹"),
    ("apple store visit", "🍎"), ("eye exam", "📝"),
])
def test_the_other_sense_stays_plain(title, never):
    assert never not in decorate(title, 2)


def test_count_none_one_two():
    assert decorate("birthday party for Dana", 0) == "birthday party for Dana"
    assert decorate("birthday party for Dana", 1) == "birthday 🎂 party for Dana"
    assert decorate("birthday party for Dana", 2) == "birthday 🎂 party 🎉 for Dana"


def test_never_on_a_title_that_has_one_and_never_twice():
    assert decorate("walk my dog 🐕", 2) == "walk my dog 🐕"
    assert decorate("🇮🇱 trip", 2) == "🇮🇱 trip"
    assert decorate("dog and puppy", 2) == "dog 🐕 and puppy"


def test_strip_gives_back_the_words():
    assert strip("date 💕 with Noa") == "date with Noa"
    assert strip("gym 🏋️") == "gym"
    assert not has_emoji(strip("pub 🍺 garden 🌱"))


# -- wired in ----------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    from assistant import db as db_module
    from assistant.db import CalendarDB
    real = CalendarDB(path=str(tmp_path / "emoji.db"))
    monkeypatch.setattr(db_module, "get_db", lambda *a, **k: real)
    return real


def _cfg(sample_config, n):
    from assistant.config import TitleEmojiConfig
    c = sample_config.model_copy()
    c.title_emoji = TitleEmojiConfig(count=n)
    return c


def test_off_by_default(db, sample_config):
    from assistant.actions.todo.action import CreateTodoAction
    from assistant.actions.todo.intent import CreateTodoIntent
    CreateTodoAction().execute(CreateTodoIntent(titles=["walk my dog"]), sample_config)
    assert [t["title"] for t in db.get_todos()] == ["walk my dog"]


def test_a_committed_todo_gets_one_and_its_tags_read_the_words(db, sample_config):
    from assistant.actions.todo.action import CreateTodoAction
    from assistant.actions.todo.intent import CreateTodoIntent
    speech = CreateTodoAction().execute(CreateTodoIntent(titles=["buy milk"]), _cfg(sample_config, 1))
    row = db.get_todos()[0]
    assert row["title"] == "buy milk 🥛"
    assert row["tags"] == ["Groceries"]
    assert "🥛" not in speech                     # the reply is spoken


def test_a_committed_event_gets_one_and_is_not_booked_twice(db, sample_config):
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.calendar.intent import CalendarIntent
    intent = CalendarIntent(title="dinner with Noa", date="2026-10-08", start_time="19:00", end_time="20:00")
    CreateEventAction().execute(intent, _cfg(sample_config, 1))
    again = CreateEventAction().execute(intent, _cfg(sample_config, 1))
    rows = db.get_events_for_day(__import__("datetime").date(2026, 10, 8))
    assert [r["title"] for r in rows] == ["dinner 🍽️ with Noa"]
    assert "didn't add it again" in again
    from assistant.actions.calendar import categories
    assert rows[0]["category"] == categories.classify("dinner with Noa")


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

def test_a_kind_switched_off_keeps_its_words_plain():
    from assistant.engine.label.title_emoji import GROUPS
    title = "walk my dog and buy milk"
    assert decorate(title, 2, set(GROUPS)) == "walk my dog 🐕 and buy milk 🥛"
    assert decorate(title, 2, set(GROUPS) - {"food"}) == "walk my dog 🐕 and buy milk"
    assert decorate(title, 2, set()) == title


def test_every_word_belongs_to_a_kind_that_can_be_switched():
    from assistant.engine.label.title_emoji import GROUPS, LEXICON
    assert {e.group for e in LEXICON} == set(GROUPS)


def test_the_kinds_are_one_list_in_config_the_engine_and_the_phone():
    import pathlib
    import re
    from assistant.config import TitleEmojiConfig
    from assistant.engine.label.title_emoji import GROUPS
    assert set(TitleEmojiConfig.model_fields) - {"count"} == set(GROUPS)
    swift = (pathlib.Path(__file__).resolve().parents[2]
             / "MACalendar-iOS/MACalendar-iOS/Views/SettingsView.swift").read_text()
    block = swift[swift.index("struct TitleEmojiKind"):swift.index("struct TitleEmojiKindsView")]
    assert re.findall(r'key: "(\w+)"', block) == list(GROUPS)


def test_the_create_action_honours_the_kinds(db, sample_config):
    from assistant.actions.todo.action import CreateTodoAction
    from assistant.actions.todo.intent import CreateTodoIntent
    from assistant.config import TitleEmojiConfig
    c = sample_config.model_copy()
    c.title_emoji = TitleEmojiConfig(count=2, food=False)
    CreateTodoAction().execute(CreateTodoIntent(titles=["buy milk", "walk the dog"]), c)
    assert sorted(t["title"] for t in db.get_todos()) == ["buy milk", "walk the dog 🐕"]


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
    ("Gym / Calisthenics", "Gym 🏋️ / Calisthenics 🤸"),
    ("Easy 5 km + strides", "Easy 5 km + strides 🏃"),
    ("threshold run 3x8 min", "threshold run 🏃 3x8 min"),
    ("speed run on the track", "speed run 🏃 on the track"),
])
def test_a_training_plans_own_words(title, want):
    """The calendar's top activities on 2026-10-01 — calisthenics and a running
    plan's run kinds — had no emoji; on the 11,700 corpus rows the additions
    change nothing (no false positives)."""
    assert decorate(title, 2) == want

