"""Words that already spell a vocabulary phrase are left alone.

2026-10-31: "cycle to Tel Aviv" came back "cycle to Tal Aviva". The city was
itself in the list, spelled right, and two shorter entries took it apart: one
had learned the alias "tel", the other sounded like "Aviv". The corrector
skipped a span that already matched an entry but never CLAIMED it, so entries
that ran after it could still rewrite its pieces. The names below are made up;
the shape is the one that happened.
"""
from __future__ import annotations

import pytest

from assistant.stt.vocab import VocabStore


@pytest.fixture
def store(tmp_path):
    s = VocabStore(str(tmp_path / "vocab.json"))
    s.add_word("Tel Aviv")
    s.add_word("Talma")
    s.add_alias("tel", "Talma")        # learned from a correction once
    s.add_word("Avivo")                # close enough to "Aviv" to match it alone
    return s


def test_a_phrase_that_is_an_entry_is_not_taken_apart(store):
    fixed, corrections = store.correct("tomorrow night cycle to Tel Aviv", learn=False)
    assert fixed == "tomorrow night cycle to Tel Aviv"
    assert corrections == []


def test_its_words_on_their_own_are_still_corrected(store):
    assert store.correct("lunch with tel", learn=False)[0] == "lunch with Talma"
    assert store.correct("call aviv about it", learn=False)[0] == "call Avivo about it"


def test_a_longer_entry_can_still_take_the_phrase_in(tmp_path):
    """Claims are made as each length's turn comes, so an entry LONGER than
    the phrase has already had its chance at a window that contains it."""
    s = VocabStore(str(tmp_path / "vocab.json"))
    s.add_word("Tel Aviv")
    s.add_word("Tel Aviv University")
    assert s.correct("exam at Tel Aviv universty", learn=False)[0] == "exam at Tel Aviv University"


def test_a_shared_list_leaves_the_speakers_own_phrase_alone(tmp_path, store):
    """`keep`: another person's list runs after the speaker's and must not
    rewrite what the speaker's list has settled."""
    other = VocabStore(str(tmp_path / "other.json"))
    other.add_word("Telma")
    other.add_alias("tel", "Telma")
    fixed, _ = other.correct("cycle to Tel Aviv", learn=False, read_only=True,
                             keep=[e.word for e in store.entries])
    assert fixed == "cycle to Tel Aviv"
