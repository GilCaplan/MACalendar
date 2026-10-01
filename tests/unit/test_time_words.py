"""Words that name a time — one table (Gil, 2026-10-01): *"make it a function
that applies those changes wherever then we can key in a word and time, so
midnight would be 00:00, sunrise when that is which can be calculated or given
for each day, now is now"*, and the list editable in Settings *"only for words
where the time can be hardcoded so not now or midnight, for those can add
words to bind to the key time"*.
"""
from __future__ import annotations

import datetime

import pytest
from freezegun import freeze_time

from assistant.intent import time_words as tw

DAY = datetime.date(2026, 10, 2)          # a Friday
CLOCK = datetime.datetime(2026, 10, 1, 9, 40)


# ── personal entries: a fixed time, or bound ONE WAY to a key time ─────────

@pytest.mark.parametrize("entry,want", [
    ("lunch break = 13:30", ("lunch break", "13:30")),
    ("Lunch  Break=9:05", ("lunch break", "09:05")),
    ("straight away = now", ("straight away", "now")),
    ("first light = sunrise", ("first light", "sunrise")),
    ("mincha = sunset - 20", ("mincha", "sunset-20")),
    ("after shul = nightfall+15", ("after shul", "nightfall+15")),
])
def test_an_entry_is_a_word_and_a_time(entry, want):
    assert tw.parse_entry(entry) == want


@pytest.mark.parametrize("entry", [
    "now = 09:00", "midnight = 23:00", "sunset = 19:00", "noon = 13:00",   # the keys are not editable
    "gym = 25:00", "gym = 10:75", "= 10:00", "gym", "gym = later", "123 = 10:00",
])
def test_a_key_time_cannot_be_redefined_and_nonsense_is_refused(entry):
    assert tw.parse_entry(entry) is None


# ── the built-ins ────────────────────────────────────────────────────────

def test_fixed_and_computed_times():
    from assistant import observance
    assert tw.time_for("party at midnight", DAY) == "00:00"
    assert tw.time_for("lunch at noon", DAY) == "12:00"
    assert tw.time_for("hike at sunrise", DAY) == observance.sunrise(DAY).strftime("%H:%M")
    assert tw.time_for("dinner at sunset", DAY) == observance.sunset(DAY).strftime("%H:%M")
    assert tw.time_for("light at candle lighting", DAY) == observance.candle_lighting(DAY).strftime("%H:%M")
    assert tw.time_for("havdalah at nightfall", DAY) == observance.tzeit(DAY).strftime("%H:%M")
    assert tw.time_for("go now", DAY, now=CLOCK) == "09:40"


@pytest.mark.parametrize("text", ["watch the sunrise", "Sunset Boulevard tour", "the sunset clause",
                                  "buy milk for now", "candle lighting supplies"])
def test_a_name_is_not_a_time(text):
    """A computed word needs "at"/"around"/"about"/"by": read as a time, it
    is lifted out of the title — "watch the"."""
    assert tw.time_for(text, DAY) is None


def test_a_sun_time_follows_its_day():
    assert tw.time_for("at sunset", datetime.date(2026, 6, 20)) != tw.time_for("at sunset", datetime.date(2026, 12, 20))


# ── through the engine ───────────────────────────────────────────────────

@pytest.fixture
def fastrule(isolated_registry):
    from assistant.actions.calendar.action import CreateEventAction
    from assistant.actions.todo.action import CreateTodoAction
    for cls in (CreateEventAction, CreateTodoAction):
        isolated_registry._actions[cls.action_name] = cls
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD
    fr = FastRule(RULE_THRESHOLD)
    fr.run("book gym tomorrow at 7am")      # warm outside the frozen clock
    return fr


@pytest.fixture
def mine():
    """The person's own words, in the scratch lexicon conftest points at."""
    from assistant.intent import lexicon
    lexicon.reset()
    lx = lexicon.get_lexicon()
    for e in ("lunch break = 13:30", "straight away = now", "mincha = sunset-20"):
        assert lx.add("time_words", e)
    yield lx
    for e in lx.added("time_words"):
        lx.remove("time_words", e)
    lexicon.reset()


def _one(fr, text):
    with freeze_time(CLOCK):
        r = fr.run(text)
    assert r.committed, r.reason
    (action, intent), = r.intents
    return action, intent


def test_at_sunset_books_that_days_sunset(fastrule):
    from assistant import observance
    action, i = _one(fastrule, "dinner friday at sunset")
    assert (action, i.title, i.date) == ("create_event", "dinner", "2026-10-02")
    assert i.start_time == observance.sunset(DAY).strftime("%H:%M")


def test_watch_the_sunrise_keeps_its_name(fastrule):
    _, i = _one(fastrule, "watch the sunrise tomorrow at 6am")
    assert (i.title, i.start_time) == ("watch the sunrise", "06:00")


def test_your_own_words(fastrule, mine):
    from assistant import observance
    _, i = _one(fastrule, "walk the dog at lunch break")
    assert (i.title, i.date, i.start_time) == ("walk the dog", "2026-10-01", "13:30")
    _, i = _one(fastrule, "walk the dog straight away")
    assert (i.date, i.start_time) == ("2026-10-01", "09:40"), "bound to now: said bare, never tomorrow"
    _, i = _one(fastrule, "walk the dog friday at mincha")
    ss = datetime.datetime.combine(DAY, observance.sunset(DAY)) - datetime.timedelta(minutes=20)
    assert (i.date, i.start_time) == ("2026-10-02", ss.strftime("%H:%M"))


def test_call_someone_at_a_time_later_today_is_today(fastrule):
    """The encounter rule compared the hour with its 9 AM default whatever
    was said: "call mom at 8pm" at 09:40 was booked for tomorrow."""
    _, i = _one(fastrule, "call mom at 8pm")
    assert (i.date, i.start_time) == ("2026-10-01", "20:00")
    _, i = _one(fastrule, "call mom at 8am")
    assert i.date == "2026-10-02", "a time already gone today is tomorrow's (Q42)"


def test_the_api_explains_a_malformed_time_word():
    from assistant.api.server import create_app
    app = create_app()
    c = app.test_client()
    r = c.post("/lexicon/time_words", json={"word": "now = 9:00"})
    assert r.status_code == 400 and "word = time" in r.get_json()["error"]
    r = c.post("/lexicon/time_words", json={"word": "gym time = 06:45"})
    assert r.status_code == 200 and "gym time = 06:45" in r.get_json()["words"]
    c.delete("/lexicon/time_words/gym time = 06:45")
