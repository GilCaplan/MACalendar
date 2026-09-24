"""The event-or-to-do router — "basic rules, otherwise model" (DEVQA Q47).

`assistant/engine/decompose_validate/kind_router.py`. The contract pinned here:
a rule that fired is never overturned; only an item on the tagger's catch-all
("default") path reaches the model; the model is sklearn, loaded lazily, and a
missing artefact leaves the tagger's answer standing.
"""
from __future__ import annotations

import types

import pytest

from assistant.engine.decompose_validate import kind_router as KR
from assistant.engine.segmentation.fastseg import fastseg as FS_mod  # noqa: F401
from assistant.engine.state import EngineState, Item


def _cfg(on=True):
    return types.SimpleNamespace(engine=types.SimpleNamespace(kind_router=on))


@pytest.mark.parametrize("text,time,want", [
    ("remind me to feed the cat", "at 14:00", "event"),       # Q26: a clock
    ("call Mom", "", "event"),                                # Q47: an encounter
    ("remind me to call Morgan", "tomorrow", "event"),        # Q47
    ("email Dana the report", "", "task"),                    # written, not an encounter
    ("buy milk", "", "task"),
    ("add eggs to my shopping list", "", "task"),             # a named to-do list
    ("remind me to water the garden", "this evening", "task"),  # Q47(A): a part of the day
    ("book standup", "this afternoon", "event"),              # Q27: the verb decides
])
def test_a_rule_that_fired_decides(text, time, want):
    kind, why = KR.route(text, time)
    assert why.startswith("rule:"), why
    assert kind == want


def test_only_the_catch_all_path_reaches_the_model():
    kind, path = KR._fs().tag_path("make a note to replace the notebook", "")
    assert (kind, path) == ("event", "default")
    got, why = KR.route("make a note to replace the notebook", "")
    assert why.startswith("model:")
    assert got == "task"


def test_tag_path_names_a_reader_and_agrees_with_tag():
    FS = KR._fs()
    for text, time in (("book gym", "tomorrow at 7am"), ("buy milk", ""),
                       ("what do i have tomorrow", ""), ("dentist appointment", "friday"),
                       ("turn on the lights", ""), ("see mom", "sunday")):
        kind, path = FS.tag_path(text, time)
        assert kind == FS.tag(text, time)
        assert path


def test_a_missing_artefact_leaves_the_tagger_standing(tmp_path, monkeypatch):
    monkeypatch.setattr(KR, "MODEL_PATH", tmp_path / "absent.joblib")
    KR.reset()
    try:
        kind, why = KR.route("need to photograph the receipts", "")
        assert (kind, why) == ("event", "tagger:no-model")
    finally:
        KR.reset()


def test_an_artefact_from_another_feature_layout_is_refused(tmp_path):
    import joblib
    p = tmp_path / "old.joblib"
    joblib.dump({"model": None, "heads": {}, "feature_version": -1}, p)
    assert KR.load(p) is None
    KR.reset()


def test_the_shipped_artefact_is_sklearn_and_matches_the_features():
    blob = KR.load()
    assert blob is not None, "models/kind_router.joblib must ship with the repo"
    assert blob["feature_version"] == KR.FEATURE_VERSION
    X = KR.vectorise([("buy milk", "", "task")], blob["heads"])
    assert X.shape[1] == len(KR.feature_names(blob["heads"]))
    assert type(blob["model"]).__module__.startswith("sklearn")


def _state(text, time, kind):
    st = EngineState(raw_text=text, text=text, source="test")
    st.items = [Item(id="item_1", kind=kind, text=text, time=time or None)]
    return st


def test_run_moves_a_catch_all_event_and_records_the_fix():
    st = _state("make a note to replace the notebook", "", "event")
    KR.run(st, _cfg())
    assert st.items[0].kind == "task"
    assert [f.rule for f in st.fixes] == ["kind_router"]


def test_run_leaves_a_kind_the_tagger_did_not_give():
    # an item whose kind came from elsewhere (a model segmenter, a rewrite) is
    # not the tagger's reading of these words, so the router does not revisit it
    st = _state("make a note to replace the notebook", "", "task")
    KR.run(st, _cfg())
    assert st.items[0].kind == "task" and not st.fixes


def test_run_can_be_switched_off():
    st = _state("make a note to replace the notebook", "", "event")
    KR.run(st, _cfg(on=False))
    assert st.items[0].kind == "event" and not st.fixes


def test_the_stage_settles_the_kind_before_decompose_reads_it():
    from assistant.engine.decompose_validate import stage
    st = _state("make a note to replace the notebook", "", "event")
    stage.run(st, _cfg())
    assert all(it.kind == "task" for it in st.items)
