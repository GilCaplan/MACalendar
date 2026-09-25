"""Ingest's generic repair of misspelled COMMAND words (2026-09-24).

"updat walk the dog on my list" created a task called 'updat walk the dog'
instead of changing it (the cross-store board). Every repaired spelling is a
non-word, so no real word can ever be rewritten.
"""
from __future__ import annotations

import pathlib

import pytest

from assistant.engine.ingest.repair import _WORD_REPAIRS, repair_command_frames


@pytest.mark.parametrize("said,fixed", [
    ("updat walk the dog on my list", "update walk the dog on my list"),
    ("set a remindar to water the garden", "set a reminder to water the garden"),
    ("shedule a haircut", "schedule a haircut"),
    ("Delet the gym", "delete the gym"),
])
def test_a_misspelled_command_word_is_repaired(said, fixed):
    assert repair_command_frames(said).lower() == fixed.lower()


@pytest.mark.parametrize("said", ["the update is done", "schedule the dentist", "cancel the gym"])
def test_real_words_are_never_touched(said):
    assert repair_command_frames(said) == said


def test_every_repaired_spelling_is_a_non_word():
    words = pathlib.Path("/usr/share/dict/words")
    if not words.exists():
        pytest.skip("no system word list")
    real = {w.strip().lower() for w in words.read_text().splitlines()}
    assert not [t for t in _WORD_REPAIRS if t in real]
