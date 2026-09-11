"""The learned labellers: the anti-poisoning rule, the stacking, and the gate.

These three are the load-bearing parts of the personal-retraining pipeline
(Gil, 2026-09-10). Each one has a failure mode that is SILENT if it regresses —
a poisoned label set, a model overruling a confident rule, a retrain that
quietly got worse — so each one is pinned.
"""
from __future__ import annotations

import json
import pathlib

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A scratch feedback file. Never the real one — it holds the user's own
    corrections and `conftest` does not redirect it (it is new)."""
    from assistant.engine.label import feedback as fb
    p = tmp_path / "fb.jsonl"
    monkeypatch.setattr(fb, "FEEDBACK_PATH", p)
    return fb


# --- the rule that makes the whole pipeline safe ---------------------------

def test_an_untouched_label_is_never_gold(store):
    """SILENCE IS NOT AGREEMENT. A label the system assigned and the user never
    objected to is not evidence they agreed — most people never look at a
    category. Training on it teaches the model its own output, which is the
    exact circularity this workstream exists to escape."""
    store.record_category("gym session", None, "Fitness", origin=store.ASSIGNED)
    store.record_category("dentist", None, "Health", origin=store.ASSIGNED)
    assert store.gold("event") == []
    assert store.counts("event") == {"total": 2, "gold": 0,
                                     "correction": 0, "explicit": 0, "assigned": 2}


def test_a_correction_is_gold_and_so_is_an_explicit_pick(store):
    store.record_category("shool", "Personal", "Prayer", origin=store.CORRECTION)
    store.record_category("Walk Mark", None, "Family", origin=store.EXPLICIT)
    assert sorted(store.gold("event")) == [("Walk Mark", "Family"),
                                           ("shool", "Prayer")]


def test_a_non_change_teaches_nothing(store):
    """Re-saving an event without touching its category is not a correction."""
    store.record_category("gym", "Fitness", "Fitness", origin=store.CORRECTION)
    assert store.gold("event") == []


def test_the_latest_correction_wins(store):
    """A user who corrects the same title twice has changed their mind. Keeping
    both would teach the model to be uncertain about a case they are now sure
    of."""
    store.record_category("shool", "Personal", "Social", origin=store.CORRECTION)
    store.record_category("shool", "Social", "Prayer", origin=store.CORRECTION)
    assert store.gold("event") == [("shool", "Prayer")]


def test_retraining_triggers_on_GOLD_not_on_items(store):
    """Fifty tasks nobody corrected teach nothing, so counting items would
    retrain on no new information."""
    for i in range(50):
        store.record_category(f"thing {i}", None, "Personal", origin=store.ASSIGNED)
    assert not store.should_retrain("event")
    for i in range(store.RETRAIN_EVERY["event"]):
        store.record_category(f"real {i}", "Personal", "Fitness",
                              origin=store.CORRECTION)
    assert store.should_retrain("event")


def test_tags_gold_is_a_set_and_order_does_not_matter(store):
    store.record_tags("zucchini", [], ["Groceries"], origin=store.CORRECTION)
    store.record_tags("the parcel", ["Groceries"], ["Errands", "Work"],
                      origin=store.CORRECTION)
    got = dict(store.gold("task"))
    assert got["zucchini"] == ["Groceries"]
    assert got["the parcel"] == ["Errands", "Work"]


# --- stacking: the rules keep what they were confident about ---------------

class _Cfg:
    class labels:
        model_event = True
        model_task = True


def test_a_confident_rule_answer_is_never_overruled(monkeypatch):
    """The rules' measured shape is precision 91.7% / recall 34.9%: nearly
    always right when they fire, rarely firing. Handing their rows to a 63.9%
    model would trade precision for nothing."""
    from assistant.engine.label import model as m
    m.reset()
    monkeypatch.setattr(m, "_cached", lambda kind: pytest.fail(
        "the model must not even be loaded when the rules answered"))
    assert m.category_for("gym session", "Fitness", _Cfg()) == ("Fitness", "rule")


def test_the_model_answers_only_where_the_rules_fell_through(monkeypatch):
    """`Personal` IS the catch-all, so a rule answer of Personal means "no
    opinion" — the one case worth asking a model about."""
    from assistant.engine.label import model as m

    class _M:
        def predict(self, text): return ("Prayer", 0.81)
    m.reset()
    monkeypatch.setattr(m, "_cached", lambda kind: _M())
    assert m.category_for("shool", "Personal", _Cfg()) == ("Prayer", "model")


def test_an_unconfident_model_abstains_to_the_rules(monkeypatch):
    """Abstention is an answer. Labelling an event Travel at 0.21 because that
    was the argmax is worse than the catch-all it replaced."""
    from assistant.engine.label import model as m

    class _M:
        def predict(self, text): return None
    m.reset()
    monkeypatch.setattr(m, "_cached", lambda kind: _M())
    assert m.category_for("mystery", "Personal", _Cfg()) == ("Personal", "rule")


def test_everything_is_off_by_default():
    """A learned labeller changes what lands on the user's calendar, so it
    ships behind a flag with today's behaviour as the default."""
    from assistant.engine.label import model as m

    class _Off:
        labels = None
    assert m.category_for("shool", "Personal", _Off()) == ("Personal", "rule")
    assert m.tags_for("zucchini", [], _Off()) == ([], "rule")


def test_no_model_at_EITHER_tier_falls_back_to_the_rules(monkeypatch, tmp_path):
    """Reached only when the base was never built — a broken install, not a
    fresh one. It must stay silent and behave exactly like today."""
    from assistant.engine.label import model as m
    monkeypatch.setattr(m, "MODELS_DIR", tmp_path / "no-personal")
    monkeypatch.setattr(m, "BASE_DIR", tmp_path / "no-base")
    m.reset()
    assert m.LabelModel.load("event") is None
    monkeypatch.setattr(m, "_build_base", lambda kind: None)
    assert m.category_for("shool", "Personal", _Cfg()) == ("Personal", "rule")


# --- the promotion gate ----------------------------------------------------

def test_the_gate_refuses_a_model_that_forgot_general_english(tmp_path, monkeypatch):
    """An automatic pipeline that can silently get worse is worse than no
    pipeline, because nobody is watching it. The generic set is the regression
    floor; a drop past the tolerance means the fit has been pulled so far toward
    one person's vocabulary that it has stopped being a general classifier."""
    from assistant.engine.label import train as T
    from assistant.engine.label import feedback as fb
    from assistant.engine.label.model import LabelModel
    import assistant.engine.label.model as M

    monkeypatch.setattr(M, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(fb, "FEEDBACK_PATH", tmp_path / "fb.jsonl")

    good = {"generic": {"acc": 0.49, "macro_f1": 0.50}, "personal": None}
    bad = {"generic": {"acc": 0.20, "macro_f1": 0.20}, "personal": None}
    calls = {"n": 0}

    def _fake_eval(pipe, kind, gte, pte, classes):
        calls["n"] += 1
        return bad if calls["n"] == 1 else good      # new model first, then incumbent

    monkeypatch.setattr(T, "_evaluate", _fake_eval)
    monkeypatch.setattr(T, "_load", lambda kind: ([("x", "Work")], [("y", "Work")]))
    monkeypatch.setattr(T, "_fit_event", lambda rows, w: (object(), ["Work"]))
    monkeypatch.setattr(LabelModel, "load",
                        classmethod(lambda cls, kind: cls(kind, object(), ["Work"], {})))

    out = T.train("event", force=True, verbose=False)
    assert out["promoted"] is False
    assert "forgetting general English" in out["why"]
    assert not (tmp_path / "event_label.joblib").exists()   # nothing was written


def test_the_gate_refuses_a_model_that_got_worse_on_the_user(tmp_path, monkeypatch):
    """The personal set is the PROMOTION criterion — the generic one only stops
    catastrophe. A retrain that holds general English but regresses on the
    user's own corrections is not an improvement to ship."""
    from assistant.engine.label import train as T
    from assistant.engine.label import feedback as fb
    from assistant.engine.label.model import LabelModel
    import assistant.engine.label.model as M

    monkeypatch.setattr(M, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(fb, "FEEDBACK_PATH", tmp_path / "fb.jsonl")

    new = {"generic": {"acc": .49, "macro_f1": .50}, "personal": {"acc": .4, "macro_f1": .40}}
    old = {"generic": {"acc": .49, "macro_f1": .50}, "personal": {"acc": .6, "macro_f1": .60}}
    calls = {"n": 0}

    def _fake_eval(pipe, kind, gte, pte, classes):
        calls["n"] += 1
        return new if calls["n"] == 1 else old

    monkeypatch.setattr(T, "_evaluate", _fake_eval)
    monkeypatch.setattr(T, "_load", lambda kind: ([("x", "Work")], [("y", "Work")]))
    monkeypatch.setattr(T, "_fit_event", lambda rows, w: (object(), ["Work"]))
    monkeypatch.setattr(LabelModel, "load",
                        classmethod(lambda cls, kind: cls(kind, object(), ["Work"], {})))

    out = T.train("event", force=True, verbose=False)
    assert out["promoted"] is False
    assert "personal macro F1" in out["why"]


def test_the_personal_split_is_by_TIME_not_random(store, monkeypatch):
    """Corrections arrive in BURSTS — a user fixes five grocery items in one
    sitting. A random split puts near-duplicates on both sides and every
    retrain scores as a win. Holding out the most RECENT slice also asks the
    deployment question: will this help tomorrow?"""
    from assistant.engine.label import train as T
    import time as _t

    base = _t.time()
    for i in range(80):
        store.record_category(f"item {i}", "Personal", "Fitness",
                              origin=store.CORRECTION)
    # rewrite timestamps so ordering is unambiguous
    rows = [json.loads(l) for l in store.FEEDBACK_PATH.read_text().splitlines()]
    for i, r in enumerate(rows):
        r["ts"] = base + i
    store.FEEDBACK_PATH.write_text("\n".join(json.dumps(r) for r in rows))

    tr, ev, how = T._personal_split("event")
    assert "time-ordered" in how
    assert len(ev) == 20 and len(tr) == 60
    # the held-out rows are the LAST ones recorded, not a random sample
    assert [t for t, _ in ev] == [f"item {i}" for i in range(60, 80)]


def test_a_tiny_personal_set_is_cross_validated_not_held_out(store):
    """25% of 25 rows is 6 rows, and a 6-row test set is a coin toss."""
    from assistant.engine.label import train as T
    for i in range(20):
        store.record_category(f"x{i}", "Personal", "Fitness", origin=store.CORRECTION)
    tr, ev, how = T._personal_split("event")
    assert "too few to hold out" in how and len(tr) == 20


def test_below_ten_corrections_the_personal_set_cannot_judge(store):
    """Promotion falls back to "do not regress on generic" — promoting on six
    rows of personal signal is promoting on noise."""
    from assistant.engine.label import train as T
    for i in range(5):
        store.record_category(f"x{i}", "Personal", "Fitness", origin=store.CORRECTION)
    tr, ev, how = T._personal_split("event")
    assert ev == [] and how == "too few to judge"


# --- two tiers: the model is the PRODUCT's, the fine-tune is the USER's -----

def test_a_brand_new_user_gets_the_base_model_not_the_rules(tmp_path, monkeypatch):
    """Gil, 2026-09-10: *"this should also be true for other users — i am just
    one example."* Before the base tier existed, `load()` returned None for
    anyone who had not run the trainer by hand, so a new user silently got the
    keyword rules FOR EVER and "the model" was a property of one machine rather
    than of the product."""
    from assistant.engine.label.model import LabelModel
    import assistant.engine.label.model as m

    monkeypatch.setattr(m, "MODELS_DIR", tmp_path / "nobody-has-corrected-anything")
    m.reset()
    got = LabelModel.load("event")
    assert got is not None, "a fresh user must still get the shipped model"
    assert got.meta.get("tier") == "base"
    assert got.meta.get("n_personal", 0) == 0, "the base tier is user-agnostic"


def test_a_personal_model_takes_precedence_over_the_base(tmp_path, monkeypatch):
    """The tiers degrade in the right order: your model, then everyone's model,
    then the rules."""
    from assistant.engine.label.model import LabelModel
    import assistant.engine.label.model as m

    monkeypatch.setattr(m, "MODELS_DIR", tmp_path)
    m.reset()
    LabelModel("event", object(), ["Work"], {"marker": "mine"}).save(tier="personal")
    got = LabelModel.load("event")
    assert got.meta.get("marker") == "mine"
    assert got.meta.get("tier") == "personal"


def test_the_base_model_contains_no_personal_data(tmp_path, monkeypatch):
    """It is fitted from the COMMITTED datasets alone — `feedback.gold()` is
    never consulted — so it is identical on every machine and safe to ship."""
    from assistant.engine.label import feedback as fb
    from assistant.engine.label import train as T

    monkeypatch.setattr(fb, "FEEDBACK_PATH", tmp_path / "fb.jsonl")
    fb.record_category("shool", "Personal", "Prayer", origin=fb.CORRECTION)
    assert fb.gold("event"), "the correction was recorded"

    calls = {"gold": 0}
    monkeypatch.setattr(fb, "gold", lambda kind: calls.__setitem__("gold", 1) or [])
    monkeypatch.setattr(T, "_fit_event", lambda rows, w: (object(), ["Work"]))
    monkeypatch.setattr(T, "_score_event", lambda p, te: {"acc": 1.0, "macro_f1": 1.0})
    monkeypatch.setattr(T, "_load", lambda kind: ([("x", "Work")], [("y", "Work")]))
    from assistant.engine.label.model import LabelModel
    monkeypatch.setattr(LabelModel, "save", lambda self, tier="personal": tmp_path / "x")

    T.train_base("event", verbose=False)
    assert calls["gold"] == 0, "train_base must never read personal corrections"


# --- the labelling game's endpoints -----------------------------------------

def test_the_queue_asks_the_HARD_rows_first(monkeypatch, tmp_path):
    """A tap on a row the rules already had right teaches nothing, so those are
    never shown. Order: rules-punted-and-model-unsure, then rules-vs-model
    disagreement, then cheap confirmations."""
    import assistant.api.server as server
    from assistant.engine.label import feedback as fb
    monkeypatch.setattr(fb, "FEEDBACK_PATH", tmp_path / "fb.jsonl")

    rows = [{"id": 1, "title": "gym session"},        # rules confident -> skipped
            {"id": 2, "title": "zzz unknowable"},     # punted + unsure -> first
            {"id": 3, "title": "quiet time"}]         # punted, model sure -> last

    class _DB:
        def search_events(self, q, limit=0): return rows
    monkeypatch.setattr(server, "get_db", lambda: _DB())

    from assistant.actions.calendar import categories as cat
    monkeypatch.setattr(cat, "classify", lambda t, *a, **k:
                        "Fitness" if "gym" in t else "Personal")

    class _M:
        def predict(self, text):
            if "zzz" in text:
                return None                      # unsure
            if "gym" in text:
                return ("Fitness", 0.9)          # AGREES with the rules
            return ("Study", 0.9)
    from assistant.engine.label.model import LabelModel
    monkeypatch.setattr(LabelModel, "load", classmethod(lambda cls, kind: _M()))

    app = server.create_app()
    with app.test_client() as c:
        got = c.get("/labels/next?kind=event&n=10").get_json()
    texts = [i["text"] for i in got["items"]]
    # The rules answered it AND the model agrees — nothing to learn, so it is
    # never offered. A DISAGREEMENT would be offered even here, at rank 1.
    assert "gym session" not in texts, "a row both already agreed on was offered"
    assert texts[0] == "zzz unknowable", texts


def test_a_recorded_answer_is_gold_and_never_touches_the_calendar(monkeypatch, tmp_path):
    """The label being LEARNED and the label on an existing row are different
    things. Conflating them would let this screen quietly rewrite the calendar."""
    import assistant.api.server as server
    from assistant.engine.label import feedback as fb
    monkeypatch.setattr(fb, "FEEDBACK_PATH", tmp_path / "fb.jsonl")

    class _DB:
        def update_event(self, *a, **k): pytest.fail("the game wrote to an event")
        def search_events(self, q, limit=0): return []
    monkeypatch.setattr(server, "get_db", lambda: _DB())

    app = server.create_app()
    with app.test_client() as c:
        out = c.post("/labels", json={"kind": "event", "text": "shool",
                                      "label": "Prayer", "current": "Personal"}).get_json()
    assert out["ok"] and out["counts"]["explicit"] == 1
    assert fb.gold("event") == [("shool", "Prayer")]


def test_an_answer_with_no_label_is_refused(monkeypatch, tmp_path):
    import assistant.api.server as server
    from assistant.engine.label import feedback as fb
    monkeypatch.setattr(fb, "FEEDBACK_PATH", tmp_path / "fb.jsonl")
    app = server.create_app()
    with app.test_client() as c:
        assert c.post("/labels", json={"kind": "event", "text": "x"}).status_code == 400
        assert c.post("/labels", json={"kind": "event", "label": "Work"}).status_code == 400
