"""The personal lexicon — the word lists Gil can extend from Settings.

Gil, 2026-09-18, after "Can you shorten the event at 2pm walk Jada to be 15
minutes" did nothing because one hand-typed verb list had never learned the word
"shorten": *"in the settings we should have a section where these are all listed
out and linked to what's in the code and can be dynamically updated ... so that
it can be fine-tuned to how he speaks"*.

Two properties carry the whole design, and both are tested here: a declaration
must point at real code (that is the "linked to" half), and an edit may only ever
WIDEN what the engine understands (that is what makes it safe to ship).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from assistant.intent import lexicon as lx


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    """A scratch store per test. `conftest.py` already points MACALENDAR_LEXICON
    at the scratch dir; this isolates the tests from each other on top."""
    path = tmp_path / "lexicon.json"
    monkeypatch.setattr(lx, "LEXICON_PATH", str(path))
    lx.reset()
    yield path
    lx.reset()


# --- the contract with the code ------------------------------------------

def test_every_declaration_points_at_code_that_exists():
    """The settings screen shows the built-in words as FACT, read out of the
    module that uses them. A renamed constant would make it show an empty list
    and quietly tell Gil the engine knows no such words."""
    for name, entry in lx.LEXICONS.items():
        words = entry.built_in()
        assert words, (
            f"{name}: {entry.module}.{entry.attr} resolved to nothing — either "
            f"it was renamed, or it is not a word list")


def test_a_declaration_describes_itself_for_the_screen():
    for name, entry in lx.LEXICONS.items():
        assert entry.label and entry.why, f"{name} has no human description"
        assert entry.module and entry.attr


# --- the safety property --------------------------------------------------

def test_an_edit_can_only_ever_WIDEN_what_the_engine_knows():
    """No edit may take a word away from the engine. A person tuning their own
    phrasing must not be able to break a command that used to work, which is why
    `effective()` is a union and a built-in has no removal path at all."""
    store = lx.get_lexicon()
    for name, entry in lx.LEXICONS.items():
        built = entry.built_in()
        store.add(name, "zzz-made-up-word")
        effective = store.effective(name)
        assert built <= effective, f"{name}: a built-in word was lost"
        assert "zzz-made-up-word" in effective
        # ...and removing the person's own word leaves the built-ins intact
        store.remove(name, "zzz-made-up-word")
        assert built <= store.effective(name)


def test_a_built_in_cannot_be_removed(fresh_store):
    store = lx.get_lexicon()
    built = sorted(lx.LEXICONS["extend_verbs"].built_in())
    assert store.remove("extend_verbs", built[0]) is False
    assert built[0] in store.effective("extend_verbs")


def test_adding_a_word_the_code_already_has_stores_nothing(fresh_store):
    store = lx.get_lexicon()
    assert store.add("extend_verbs", "shorten") is False
    assert "shorten" not in store.added("extend_verbs")


def test_a_corrupt_store_never_stops_a_parse(fresh_store):
    """`~/.assistant_tools` is hand-editable by design. A broken file must
    degrade to the built-ins, not raise inside a voice command."""
    fresh_store.write_text("{ this is not json")
    lx.reset()
    assert lx.effective("extend_verbs") == lx.LEXICONS["extend_verbs"].built_in()


def test_an_unknown_lexicon_is_refused_not_invented(fresh_store):
    store = lx.get_lexicon()
    assert store.add("not_a_real_list", "word") is False
    assert store.effective("not_a_real_list") == frozenset()


# --- and it actually reaches the engine ----------------------------------

def test_a_word_added_here_changes_how_a_command_parses(fresh_store):
    """The point of the whole feature: add the verb you use, and the engine
    starts reading it. "squeeze" is not in `_EXTEND_VERBS`."""
    from assistant.intent import rule_parser as rp
    rp._ensure_nlp(); rp._ensure_dt()

    class _NoRegistry:
        def get(self, _name):
            return None

    parser = rp.RuleBasedParser(_NoRegistry())
    said = "squeeze the event at 2pm standup to be 15 minutes"

    before = parser.analyze(said).raw_slots.get("update_event", {})
    assert before.get("new_end_time") is None, \
        "premise changed: 'squeeze' is already a known verb"

    lx.get_lexicon().add("extend_verbs", "squeeze")
    after = parser.analyze(said).raw_slots.get("update_event", {})
    assert after.get("new_end_time") == "14:15", \
        f"the added verb did not reach the parser: {after}"


def test_the_store_round_trips_through_json(fresh_store):
    store = lx.get_lexicon()
    store.add("extend_verbs", "squeeze")
    store.add("extend_verbs", "pad out")
    on_disk = json.loads(pathlib.Path(fresh_store).read_text())
    assert on_disk["extend_verbs"] == ["pad out", "squeeze"]
