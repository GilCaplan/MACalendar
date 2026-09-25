"""The embedding head behind the rules (DEVQA Q46), and the n-gram fallback.

The suite runs with `MACALENDAR_LLM_DISABLED=1`, so every commit-time label in
CI goes down the FALLBACK — these tests pin that it is exactly today's n-gram
answer, that the disabled flag opens no socket, that a failing server costs one
timeout and not one per commit, and that the live-palette filter still applies
to what the embedding head says.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import numpy as np
import pytest

from assistant.engine.label import embed as E
from assistant.engine.label import model as M


@pytest.fixture(autouse=True)
def _fresh():
    E.reset()
    M.reset()
    yield
    E.reset()
    M.reset()


class _Pipe:
    """A stand-in n-gram pipeline: always 'Work' at 0.8."""
    classes_ = np.array(["Travel", "Work"])

    def predict_proba(self, texts):
        return np.array([[0.2, 0.8] for _ in texts])


class _Head(M.EmbedHead):
    """A stand-in embedding head: always 'Travel' at 0.9."""

    def __init__(self, threshold=0.3):
        super().__init__("event", None, ["Travel", "Work"], threshold)

    def proba(self, texts, Ev):
        return np.array([[0.9, 0.1] for _ in texts])


def _model(head=True):
    return M.LabelModel("event", _Pipe(), ["Travel", "Work"], {}, _Head() if head else None)


def _cfg():
    return SimpleNamespace(labels=SimpleNamespace(model_event=True, model_task=True,
                                                  model_first=False))


# --- the client ---------------------------------------------------------------

def test_the_disabled_flag_opens_no_socket(monkeypatch):
    import urllib.request
    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("a socket was opened while disabled"))
    assert E.vector("gym session") is None
    assert E.vectors(["a", "b"]) is None


def test_a_dead_server_costs_one_timeout_not_one_per_commit(monkeypatch):
    """After a failure the door stays shut for COOLDOWN_S."""
    monkeypatch.delenv("MACALENDAR_LLM_DISABLED", raising=False)
    calls = []
    monkeypatch.setattr(E, "_post", lambda texts, url, timeout: calls.append(texts) or None)
    assert E.vector("first") is None
    assert E.vector("second") is None
    assert len(calls) == 1


def test_vectors_are_unit_length_and_cached(monkeypatch):
    monkeypatch.delenv("MACALENDAR_LLM_DISABLED", raising=False)
    calls = []

    def fake(texts, url, timeout):
        calls.append(list(texts))
        return [[3.0, 4.0] for _ in texts]
    monkeypatch.setattr(E, "_post", fake)
    v = E.vector("gym")
    assert np.allclose(v, [0.6, 0.8])
    E.vector("gym")
    assert calls == [["gym"]], "a cached title must not be re-sent"


def test_the_call_inherits_the_callers_priority(monkeypatch):
    """A label for a live command is live traffic: the door must not force a
    priority of its own onto `hold()`."""
    import contextlib
    from assistant import model_protocol
    monkeypatch.delenv("MACALENDAR_LLM_DISABLED", raising=False)
    seen = []

    @contextlib.contextmanager
    def spy(kind=None):
        seen.append(kind)
        yield 0
    monkeypatch.setattr(model_protocol, "hold", spy)
    E._post(["x"], "http://127.0.0.1:9", 0.01)       # nothing listens there: fails fast
    assert seen == [None]


def test_the_embedding_door_is_one_the_door_test_can_see():
    """`test_every_door_to_the_model_goes_through_the_gate` only checks calls whose
    next lines name the server. A door it cannot SEE is a hole that reads as covered."""
    import pathlib
    lines = pathlib.Path(E.__file__).read_text().splitlines()
    CALL = re.compile(r"\.post\(|urlopen\(")
    OLLAMA = re.compile(r"base_url|ENDPOINT|11434")
    doors = [i for i, l in enumerate(lines) if CALL.search(l)
             and OLLAMA.search("\n".join(lines[i:i + 4]))]
    assert doors, "the embedding call is invisible to the door test"
    for i in doors:
        assert "model_protocol.hold()" in "\n".join(lines[max(0, i - 14):i + 4])


# --- the head and its fallback --------------------------------------------------

def test_no_vector_means_the_ngram_model_answers_exactly_as_before(monkeypatch):
    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    m = _model()
    assert m.predict("flight to rome") == ("Work", 0.8)
    assert m.last_source == "ngram"


def test_a_vector_means_the_embedding_head_answers(monkeypatch):
    monkeypatch.setattr(E, "vector", lambda text, base_url=None, timeout=None: np.ones(4))
    m = _model()
    assert m.predict("flight to rome") == ("Travel", 0.9)
    assert m.last_source == "embed"


def test_when_the_head_abstains_the_ngram_model_is_not_asked(monkeypatch):
    """The fallback is for a MISSING vector, not a second opinion: an abstention
    means the rules stand."""
    monkeypatch.setattr(E, "vector", lambda text, base_url=None, timeout=None: np.ones(4))
    m = _model()
    m.embed_head.threshold = 0.95
    assert m.predict("flight to rome") is None


def test_a_head_that_raises_falls_back_to_the_ngram_model(monkeypatch):
    monkeypatch.setattr(E, "vector", lambda text, base_url=None, timeout=None: np.ones(4))

    class _Broken(_Head):
        def proba(self, texts, Ev):
            raise ValueError("shape mismatch")
    m = M.LabelModel("event", _Pipe(), ["Travel", "Work"], {}, _Broken())
    assert m.predict("x") == ("Work", 0.8)


def test_an_artefact_from_before_the_head_still_predicts(monkeypatch):
    monkeypatch.setattr(E, "vector", lambda *a, **k: pytest.fail("no head, no embedding call"))
    assert _model(head=False).predict("x") == ("Work", 0.8)


def test_the_live_palette_filter_applies_to_the_embedding_head(monkeypatch):
    """The head's classes are frozen at training time like the pipeline's; a
    class the user deleted must not come back through it either."""
    monkeypatch.setattr(E, "vector", lambda text, base_url=None, timeout=None: np.ones(4))
    monkeypatch.setattr(M, "_cached", lambda kind: _model())
    monkeypatch.setattr(M, "_live_category", lambda name: name != "Travel")
    assert M.category_for("flight to rome", "Personal", _cfg()) == ("Personal", "rule")
    monkeypatch.setattr(M, "_live_category", lambda name: True)
    assert M.category_for("flight to rome", "Personal", _cfg()) == ("Travel", "model")


def test_task_tags_fall_back_and_filter_the_same_way(monkeypatch):
    class _TPipe:
        named_steps = {"feat": SimpleNamespace(transform=lambda x: x),
                       "clf": SimpleNamespace(estimators_=[
                           SimpleNamespace(predict_proba=lambda f: np.array([[0.1, 0.9]])),
                           SimpleNamespace(predict_proba=lambda f: np.array([[0.9, 0.1]]))])}

    class _THead(M.EmbedHead):
        def __init__(self):
            super().__init__("task", None, ["Errands", "Groceries"], 0.5)

        def proba(self, texts, Ev):
            return np.array([[0.1, 0.9] for _ in texts])

    m = M.LabelModel("task", _TPipe(), ["Errands", "Groceries"], {}, _THead())
    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    assert m.predict_tags("zucchini")[0] == ["Errands"]           # n-gram fallback
    monkeypatch.delenv("MACALENDAR_LLM_DISABLED")
    monkeypatch.setattr(E, "vector", lambda text, base_url=None, timeout=None: np.ones(4))
    assert m.predict_tags("zucchini")[0] == ["Groceries"]         # the head
    monkeypatch.setattr(M, "_cached", lambda kind: m)
    monkeypatch.setattr(M, "_live_tags", lambda names: [])
    assert M.tags_for("zucchini", [], _cfg()) == ([], "rule")


# --- the committed artefacts ----------------------------------------------------

@pytest.mark.parametrize("kind", ["event", "task"])
def test_the_committed_base_carries_an_embedding_head_and_its_threshold(kind):
    art = M.LabelModel._read(kind, M.LabelModel.path_for(kind, "base"))
    assert art is not None and art.embed_head is not None
    meta = art.meta.get("embed") or {}
    assert meta.get("threshold") == art.embed_head.threshold
    assert "TRAIN" in meta.get("threshold_rule", ""), "a threshold must say it was chosen on TRAIN"
    assert art.embed_head.classes == art.classes


def test_the_committed_base_falls_back_cleanly_in_this_suite():
    """The suite is model-free: the real artefact must still answer, from its
    n-gram pipeline, without touching ollama."""
    art = M.LabelModel._read("event", M.LabelModel.path_for("event", "base"))
    got = art.predict("book a flight to rome")
    assert art.last_source == "ngram"
    assert got is None or got[0] in art.classes


def test_a_first_use_build_does_not_embed(monkeypatch):
    """`_build_base` runs inside a commit when no artefact exists; it must not
    embed twelve thousand rows there."""
    from assistant.engine.label import train as T
    seen = {}
    monkeypatch.setattr(T, "train_base", lambda kind, verbose=True, embed=True:
                        seen.setdefault("embed", embed) and None)
    M._build_base("event")
    assert seen == {"embed": False}


def test_the_ngram_fallback_holds_to_its_own_bar_for_todos(monkeypatch):
    """2026-09-24: with ollama down the n-gram fallback tagged "call mom" and
    "pay rent" Groceries (0.63, 0.41). On Gil's real rule-blank titles it was
    confidently wrong 19 times in 29; a to-do now falls back to no tag unless
    the n-gram model is near-certain."""
    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    from assistant.engine.label.model import LabelModel, FALLBACK_MIN_CONFIDENCE
    m = LabelModel.load("task")
    if getattr(m, "embed_head", None) is None:
        import pytest
        pytest.skip("artefact without an embedding head: the n-gram IS the model")
    assert m.predict_tags("call mom") is None
    got = m.predict_tags("buy milk")
    assert got and "Groceries" in got[0] and got[1] >= FALLBACK_MIN_CONFIDENCE["task"]
