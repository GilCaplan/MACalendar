"""A saved label model answers only with classes the user still has.

Found 2026-09-24 by the label rebuild board: the fitted model's classes are
frozen at training time, so a deleted category (Travel), a renamed one
(Errand -> Chores) or a deleted tag (Errands) kept coming back from it —
breaking tagging.py's promise that a deleted tag never returns.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from assistant.engine.label import model as M


class _Fake:
    def __init__(self, cat=None, tags=None):
        self._cat, self._tags = cat, tags

    def predict(self, title):
        return (self._cat, 0.9) if self._cat else None

    def predict_tags(self, title):
        return (list(self._tags), 0.9) if self._tags else None


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(M, "enabled", lambda cfg, kind: True)
    monkeypatch.setattr(M, "_model_first", lambda cfg: False)
    return SimpleNamespace()


def test_a_deleted_category_from_the_model_falls_back_to_the_rules(on, monkeypatch):
    monkeypatch.setattr(M, "_cached", lambda kind: _Fake(cat="Zeppelin Club"))
    assert M.category_for("flight to rome", "Personal", None) == ("Personal", "rule")


def test_a_live_category_from_the_model_stands(on, monkeypatch):
    from assistant.actions.calendar import categories as C
    live = C.all_categories()[0]["name"]
    monkeypatch.setattr(M, "_cached", lambda kind: _Fake(cat=live))
    assert M.category_for("something", "Personal", None) == (live, "model")


def test_a_deleted_tag_is_dropped_and_a_live_one_kept(on, monkeypatch):
    from assistant.db import get_db
    live = get_db().get_tags()[0]["name"]
    monkeypatch.setattr(M, "_cached", lambda kind: _Fake(tags=["Zeppelin Club", live.lower()]))
    assert M.tags_for("thing", [], None) == ([live], "model")
    monkeypatch.setattr(M, "_cached", lambda kind: _Fake(tags=["Zeppelin Club"]))
    assert M.tags_for("thing", [], None) == ([], "rule")
