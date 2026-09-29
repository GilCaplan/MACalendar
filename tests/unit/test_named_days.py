"""Days named instead of dated (assistant/named_days.py, 2026-09-29).

Gil: *"The engine can deal with given hebrew dates and other built in
events?"* — probed the same day, five of eight such commands were booked on
the wrong day without a word. Expected dates below are Hebrew dates converted
by pyluach DIRECTLY (``HebrewDate(y, m, d)``), not through the holiday table
the reader uses, so a table mistake cannot agree with itself.
"""

import datetime

import pytest
from pyluach import dates as _hd

from assistant import named_days as nd

TODAY = datetime.date(2026, 9, 29)          # 18 Tishrei 5787, mid-Sukkot (Israel)
ALL = set(nd.FAMILIES)


def heb(y, m, d):
    return _hd.HebrewDate(y, m, d).to_pydate()


def found(text, **kw):
    kw.setdefault("families", ALL)
    kw.setdefault("israel", True)
    return nd.find(text, TODAY, **kw)


@pytest.mark.parametrize("text,want", [
    ("dentist on 12 Adar at 3pm", heb(5787, 13, 12)),          # a leap year: Adar II
    ("lunch on the 15th of Nisan", heb(5787, 1, 15)),
    ("call on Tishrei 10, 5788", heb(5788, 7, 10)),
    ("lunch with Avi on 5 Tishrei", heb(5788, 7, 5)),          # this year's has passed
    ("dinner on erev Pesach at 7pm", heb(5787, 1, 14)),
    ("family meal on Purim at 1pm", heb(5787, 13, 14)),
    ("meeting the day after Yom Kippur", heb(5788, 7, 11)),
    ("call mom on the first night of Chanukah", heb(5787, 9, 24)),
    ("on the last day of Chanukah", heb(5787, 10, 2)),
    ("shiur on Rosh Chodesh Kislev at 8pm", heb(5787, 8, 30)),  # Cheshvan has a 30th
    ("hike on chol hamoed pesach", heb(5787, 1, 16)),
    ("dinner on erev shabbat", datetime.date(2026, 10, 2)),
    ("movie motzei shabbat at 9", datetime.date(2026, 10, 3)),
    ("brunch on Easter", datetime.date(2027, 3, 28)),
    ("on Pesach 2028", heb(5788, 1, 15)),
])
def test_named_days_resolve_to_the_right_date(text, want):
    got = found(text)
    assert got is not None, text
    assert got.date == want, (text, got)


def test_a_holiday_that_lasts_is_a_range_and_one_under_way_starts_today():
    got = found("trip over Sukkot")
    assert got.date == TODAY and got.days > 1
    assert found("on Pesach").days == 7                       # Israel


def test_the_evening_word_stays_for_the_clock_reader():
    got = found("call mom on the first night of Chanukah")
    t = "call mom on the first night of Chanukah"
    claimed = "".join(t[a:b] for a, b in got.spans)
    assert "night" not in claimed


@pytest.mark.parametrize("text", [
    "Cook food for Shabbat at 3pm today",        # real usage: a purpose, not a day
    "add pastries to the Christmas list",
    "plan the Purim party tomorrow at 5pm",
    "on the Purim party",
    "call Sivan 5 minutes before",
    "meet with Adar 3 tomorrow",
    "buy Dana's birthday present tomorrow",
    "seder at grandma's on Monday",
])
def test_a_holiday_used_as_a_name_is_not_a_date(text):
    assert found(text) is None


def test_a_family_switched_off_reads_nothing():
    assert found("dinner on erev Pesach", families={"christian"}) is None
    assert found("brunch on Easter", families={"jewish"}) is None
    assert found("dentist on 12 Adar", families={"mine"}) is None


def test_own_occasions_are_read_by_name(tmp_path, monkeypatch):
    from assistant.occasions import store
    monkeypatch.setattr(store, "PATH", tmp_path / "occ.json")
    store.add({"kind": "birthday", "title": "Dana", "calendar": "gregorian",
               "month": 3, "day": 3})
    store.add({"kind": "yahrzeit", "title": "Grandpa Moshe", "calendar": "hebrew",
               "month": 12, "day": 12})
    assert found("dinner on Dana's birthday at 8pm").date == datetime.date(2027, 3, 3)
    assert found("visit on grandpa Moshe's yahrzeit").date == heb(5787, 12, 12)  # Adar I
    assert found("dinner on Tal's birthday") is None                            # not stored
    assert found("dinner on Dana's birthday", families={"jewish"}) is None


def test_the_resolver_mode_reads_a_leading_name_and_still_guards_the_sentence():
    # resolve_date gets an item's time words — or, on the fast track, the
    # whole sentence, so the guards still apply there
    assert found("rosh chodesh kislev at 8pm", whole=True).date == heb(5787, 8, 30)
    assert found("erev pesach", whole=True).date == heb(5787, 1, 14)
    assert found("Cook food for Shabbat at 3pm today", whole=True) is None
    assert found("plan the Purim party tomorrow at 5pm", whole=True) is None


def test_unread_flags_a_named_day_in_date_position_only(monkeypatch):
    monkeypatch.setattr(nd, "enabled", lambda: ALL)
    assert nd.unread("dinner on the Purim party", TODAY)
    assert nd.unread("dinner on erev Pesach", TODAY) is None     # it was read
    assert nd.unread("cook for Shabbat", TODAY) is None          # not date position
    monkeypatch.setattr(nd, "enabled", lambda: {"christian"})
    assert nd.unread("dinner on the Purim party", TODAY) is None # switched off


def test_find_all_reads_both_days_of_a_two_ask_command():
    got = nd.find_all("dinner on erev shabbat at 8pm and dentist on 12 Adar at 3pm", TODAY)
    assert [n.name for n in got] == ["erev shabbat", "12 Adar"]


# -- where the engine uses it -------------------------------------------------------


def test_the_rule_parser_takes_the_named_day_and_masks_its_words():
    from assistant.intent.rule_parser import _extract_temporal
    t = _extract_temporal("dinner on erev Pesach at 7pm", datetime.date.today())
    assert t["_named_day"] == "erev Pesach"
    assert t["start_time"] == "19:00"
    assert datetime.date.fromisoformat(t["date"]).weekday() in range(7)


def test_a_named_day_the_parser_cannot_place_is_left_to_the_deep_track():
    from assistant.engine.llm import get_rule_parser
    from assistant.intent.rule_parser import RuleParserSkip
    with pytest.raises(RuleParserSkip, match="named day"):
        get_rule_parser().analyze("book dinner on the Purim party at 7pm")


def test_segmentation_keeps_the_named_day_as_the_items_time():
    from assistant.engine.segmentation.fastseg.fastseg import find_time_refs
    refs = [(r.kind, r.text) for r in find_time_refs("dentist on 12 Adar at 3pm")]
    assert ("date", "on 12 Adar") in refs


def test_decompose_validate_resolves_the_named_day():
    from assistant.engine.decompose_validate.resolve import resolve_date
    got = resolve_date("on erev pesach at 7pm", datetime.date.today())
    assert got and datetime.date.fromisoformat(got) >= datetime.date.today()


def test_a_series_can_end_on_a_named_day():
    from assistant.intent.rule_parser import _series_bound
    iso, _, _ = _series_bound("gym every monday until Pesach", TODAY)
    pesach = found("on Pesach").date
    assert iso == (pesach - datetime.timedelta(days=1)).isoformat()   # until: exclusive


def test_the_models_title_loses_the_days_name_not_the_event():
    from assistant.engine.llmjudge.llm_fallback import _minus_named_day

    class It:
        time = "on erev shabbat at 8pm"
    assert _minus_named_day("Shabbat Dinner on erev shabbat", It()) == "Dinner"
    It.time = "at 8pm"
    assert _minus_named_day("Shabbat Dinner", It()) == ""


# -- the settings, the words ------------------------------------------------------------


def test_every_family_has_a_switch_and_all_default_on():
    from assistant.config import OccasionsConfig
    assert set(OccasionsConfig().by_name) == set(nd.FAMILIES)
    assert all(OccasionsConfig().by_name.values())


def test_the_hebrew_months_pack_has_no_word_short_enough_to_rewrite_english():
    from assistant.stt.vocab_onboarding import PRESETS
    pack = next(p for p in PRESETS if p["id"] == "hebrew_months")
    assert all(len(w) >= 4 for w in pack["words"])            # "Av" is one slip from "of"
    assert {"Adar", "Kislev", "Tishrei", "Cheshvan"} <= set(pack["words"])


def test_pretag_makes_known_words_nouns():
    from assistant.intent import rule_parser as rp
    rp._ensure_nlp()
    doc = rp._NLP("shiur on rosh chodesh kislev at 8pm")
    assert doc[0].pos_ == "NOUN"


def test_pretag_reads_the_users_vocabulary(monkeypatch):
    from assistant.intent import pretag, rule_parser as rp
    rp._ensure_nlp()
    monkeypatch.setattr(pretag, "_vocab_words", lambda: frozenset({"zorblat"}))
    doc = rp._NLP("zorblat tomorrow at 5pm")
    assert doc[0].pos_ in ("NOUN", "PROPN")


def test_pretag_loads_a_real_vocabulary_file(tmp_path, monkeypatch):
    # the loader swallows errors (no vocabulary is no reason to fail a parse),
    # so a broken read shows up only as an EMPTY list — pin that it is not
    import json
    from assistant.intent import pretag
    from assistant.stt import vocab as v
    f = tmp_path / "vocab.json"
    f.write_text(json.dumps({"entries": [{"word": "Zorblat", "aliases": []},
                                         {"word": "Table", "aliases": []}]}))
    monkeypatch.setattr(v, "get_vocab", lambda: v.VocabStore(str(f)))
    pretag._cache.clear()
    got = pretag._vocab_words()
    assert "zorblat" in got
    assert "table" not in got or not v._english()        # real English stays out
