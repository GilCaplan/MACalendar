"""`labels.model_first` (Gil, 2026-09-22: "I want the ML models on that instead
of rule based"): a confident model answer wins over the keyword rules; the rules
keep every row the model abstains on. Off, the old stacking holds — the model
only fills a row the rules had no opinion about."""
from __future__ import annotations

from types import SimpleNamespace

from assistant.engine.label import model as M


class _Model:
    def __init__(self, answer):
        self.answer = answer

    def predict(self, title):
        return self.answer

    def predict_tags(self, title):
        return self.answer


def _cfg(event=True, task=True, first=False):
    return SimpleNamespace(labels=SimpleNamespace(model_event=event, model_task=task, model_first=first))


def test_stacked_mode_keeps_a_confident_rule_answer(monkeypatch):
    monkeypatch.setattr(M, "_cached", lambda kind: _Model(("Fitness", 0.9)))
    assert M.category_for("gym", "Work", _cfg()) == ("Work", "rule")
    assert M.category_for("gym", "Personal", _cfg()) == ("Fitness", "model")   # the catch-all is an opening


def test_model_first_lets_a_confident_model_win(monkeypatch):
    monkeypatch.setattr(M, "_cached", lambda kind: _Model(("Fitness", 0.9)))
    assert M.category_for("gym", "Work", _cfg(first=True)) == ("Fitness", "model")


def test_model_first_falls_back_to_the_rules_when_the_model_abstains_or_is_missing(monkeypatch):
    monkeypatch.setattr(M, "_cached", lambda kind: _Model(None))
    assert M.category_for("gym", "Work", _cfg(first=True)) == ("Work", "rule")
    monkeypatch.setattr(M, "_cached", lambda kind: None)
    assert M.category_for("gym", "Work", _cfg(first=True)) == ("Work", "rule")
    assert M.tags_for("buy milk", ["Groceries"], _cfg(first=True)) == (["Groceries"], "rule")


def test_tags_follow_the_same_rule(monkeypatch):
    monkeypatch.setattr(M, "_cached", lambda kind: _Model((["Errands"], 0.8)))
    assert M.tags_for("buy milk", ["Groceries"], _cfg()) == (["Groceries"], "rule")
    assert M.tags_for("buy milk", ["Groceries"], _cfg(first=True)) == (["Errands"], "model")
    assert M.tags_for("buy milk", [], _cfg()) == (["Errands"], "model")


def test_switched_off_means_rules_only(monkeypatch):
    monkeypatch.setattr(M, "_cached", lambda kind: _Model(("Fitness", 0.9)))
    assert M.category_for("gym", "Work", _cfg(event=False, first=True)) == ("Work", "rule")
