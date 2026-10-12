"""`scripts/flashcards_english.py`: export the cards lacking English, take
them back translated, keep every review (Gil, 2026-10-12)."""

from __future__ import annotations

import json
import pathlib

import pytest

from assistant.features.flashcards.store import FlashcardStore
from scripts import flashcards_english as fe

HE = [{"type": "basic", "front": "שאלה אחת", "back": "תשובה"},
      {"type": "mc", "question": "איזה?", "choices": ["א", "ב"], "answer": "א"}]
EN = [{"type": "basic", "front": "one question", "back": "answer"}]


@pytest.fixture
def store(tmp_path):
    return FlashcardStore(str(tmp_path / "flashcards.db"))


def test_export_translate_apply_keeps_progress(store, tmp_path):
    he = store.import_doc({"subject": "S", "set": "Hebrew", "lang": "he", "cards": HE})[0]["set_id"]
    store.import_doc({"subject": "S", "set": "English", "cards": EN})
    first = store.get_set(he)["cards"][0]["id"]
    store.review(first, "", 3)

    out = tmp_path / "out" / "to-translate.json"
    n = fe.export(store, out)
    assert n == {"sets": 1, "cards": 2, "to_translate": 2}          # the English set is skipped
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "en" in data["instructions"]
    cards = data["sets"][0]["cards"]
    cards[0]["en"] = {"front": "First question", "back": "Answer"}
    cards[1]["en"] = {"question": "Which?", "choices": ["A", "B"], "answer": "A"}
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    [f] = fe.apply(store, out)
    assert pathlib.Path(f).parent == pathlib.Path(store.inbox_dir)
    store.import_inbox()
    got = store.get_set(he)["cards"]
    assert got[0]["en"]["front"] == "First question" and got[1]["en"]["choices"] == ["A", "B"]
    assert got[0]["progress"][""]["reps"] == 1                     # the review survived
    assert fe.export(store, out)["to_translate"] == 0


def test_a_changed_card_is_refused_before_it_costs_progress(store, tmp_path):
    store.import_doc({"subject": "S", "set": "Hebrew", "lang": "he", "cards": HE})
    out = tmp_path / "t.json"
    fe.export(store, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    data["sets"][0]["cards"][0]["back"] = "Answer"                  # translated IN PLACE
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="changed, not only translated"):
        fe.apply(store, out)
    assert not list(pathlib.Path(store.inbox_dir).glob("*.json"))


def test_the_export_never_lands_in_the_public_repo(store):
    with pytest.raises(SystemExit, match="inside the repository"):
        fe.export(store, fe.ROOT / "flashcards-english.json")
