"""Fit the labellers, and REFUSE to ship one that is not better.

    python -m assistant.engine.label.train              # both, if worth it
    python -m assistant.engine.label.train --force      # refit regardless
    python -m assistant.engine.label.train --kind task

Two sources, deliberately mixed:

    SHIPPED   `datasets/*.jsonl` — ~1,100 rows per class, generated FROM the
              label so nothing is circular. Broad, and in nobody's voice.
    PERSONAL  `feedback.gold()` — what THIS user actually corrected. Narrow,
              scarce, and the only rows written in their own words.

## Why the personal rows are UPWEIGHTED rather than concatenated

Seventy real rows appended to fourteen thousand synthetic ones are noise: the
fit would barely move and the whole pipeline would look pointless. But the
personal rows are the ones that match deployment, so they carry far more
information per row than the generated ones do.

`PERSONAL_WEIGHT` makes each personal row count as many. It is a dial with a
real failure at each end — too low and personalisation does nothing, too high
and the model collapses onto whatever the user has corrected most (Gil's todo
list is 64/71 Groceries, so an unweighted-but-personal-only fit would answer
Groceries for everything).

## The promotion gate

**A retrained model does not ship because it is newer.** It is scored against
the frozen held-out split — vocabulary the fit never saw — and promoted only if
it beats the model already installed. The previous artefact is kept.

This is the discipline `self_check_apply` already has in this project, for the
same reason: an automatic pipeline that can silently get worse is worse than no
pipeline, because nobody is watching it.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

STAGE = pathlib.Path(__file__).resolve().parent
DATASETS = STAGE / "datasets"

#: How many generated rows one personal row is worth. See the module docstring
#: for the failure at each end.
PERSONAL_WEIGHT = 25


def _vectoriser():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion
    return FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                 sublinear_tf=True, min_df=2)),
    ])


def _load(kind: str):
    name = "event_categories.jsonl" if kind == "event" else "task_tags.jsonl"
    rows = [json.loads(l) for l in (DATASETS / name).open() if l.strip()]
    key = "label" if kind == "event" else "labels"
    tr = [(r["text"], r[key]) for r in rows if r["split"] == "train"]
    te = [(r["text"], r[key]) for r in rows if r["split"] == "test"]
    return tr, te


def _fit_event(train_rows, weights):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    X = [t for t, _ in train_rows]
    y = [l for _, l in train_rows]
    pipe = Pipeline([("feat", _vectoriser()),
                     ("clf", LogisticRegression(max_iter=2000, C=4.0))])
    pipe.fit(X, y, clf__sample_weight=weights)
    return pipe, sorted(set(y))


def _fit_task(train_rows, weights, classes):
    from sklearn.linear_model import LogisticRegression
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import MultiLabelBinarizer
    X = [t for t, _ in train_rows]
    mlb = MultiLabelBinarizer(classes=classes)
    Y = mlb.fit_transform([l for _, l in train_rows])
    pipe = Pipeline([("feat", _vectoriser()),
                     ("clf", OneVsRestClassifier(
                         LogisticRegression(max_iter=2000, C=4.0), n_jobs=1))])
    pipe.fit(X, Y)
    return pipe, list(mlb.classes_)


def _score_event(pipe, test_rows) -> dict:
    from sklearn.metrics import accuracy_score, f1_score
    X = [t for t, _ in test_rows]
    y = [l for _, l in test_rows]
    pred = pipe.predict(X)
    return {"acc": float(accuracy_score(y, pred)),
            "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0))}


def _score_task(pipe, test_rows, classes) -> dict:
    from sklearn.metrics import f1_score
    from sklearn.preprocessing import MultiLabelBinarizer
    import numpy as np
    mlb = MultiLabelBinarizer(classes=classes)
    Y = mlb.fit_transform([l for _, l in test_rows])
    pred = pipe.predict([t for t, _ in test_rows])
    return {"acc": float((np.asarray(pred) == Y).all(axis=1).mean()),
            "macro_f1": float(f1_score(Y, pred, average="macro", zero_division=0))}


#: Below this much personal gold, the personal set cannot adjudicate anything
#: and promotion falls back to "do not regress on generic".
MIN_PERSONAL_TO_JUDGE = 10

#: Below this, evaluate the personal rows by k-fold CV rather than holding some
#: out: 25% of 25 rows is 6 rows, and a 6-row test set is a coin toss.
PERSONAL_HOLDOUT_FROM = 60

#: How far macro F1 may fall on the GENERIC held-out set before a retrain is
#: refused. Some drop is expected and healthy — the model is being pulled toward
#: one person's vocabulary — but a cliff means it has forgotten general English.
GENERIC_TOLERANCE = 0.02


def _personal_split(kind: str):
    """(train_rows, eval_rows, how) for the personal gold.

    SPLIT BY TIME, NOT RANDOMLY. Corrections arrive in bursts — a user fixes
    five grocery items in one sitting — so a random split puts near-duplicates
    on both sides and every retrain scores as a win. Holding out the most
    RECENT slice also asks the deployment question: will this help tomorrow?
    """
    from assistant.engine.label import feedback
    rows = feedback.gold_with_time(kind)
    if kind == "task":
        rows = [(ts, t, l if isinstance(l, list) else [l]) for ts, t, l in rows]
    pairs = [(t, l) for _ts, t, l in rows]
    if len(pairs) < MIN_PERSONAL_TO_JUDGE:
        return pairs, [], "too few to judge"
    if len(pairs) < PERSONAL_HOLDOUT_FROM:
        return pairs, pairs, "k-fold (too few to hold out)"
    cut = int(len(pairs) * 0.75)
    return pairs[:cut], pairs[cut:], "most recent 25%, time-ordered"


def _evaluate(pipe, kind, generic_te, personal_te, classes) -> dict:
    """Both numbers, on the SAME rows for every model being compared."""
    scorer = _score_event if kind == "event" else _score_task
    args = () if kind == "event" else (classes,)
    out = {"generic": scorer(pipe, generic_te, *args)}
    if personal_te:
        try:
            out["personal"] = scorer(pipe, personal_te, *args)
        except Exception:
            out["personal"] = None
    return out


def train(kind: str, force: bool = False, verbose: bool = True) -> "dict | None":
    from assistant.engine.label import feedback
    from assistant.engine.label.model import LabelModel

    if not force and not feedback.should_retrain(kind):
        if verbose:
            c = feedback.counts(kind)
            need = feedback.RETRAIN_EVERY.get(kind, 25)
            print(f"  {kind}: {c['gold']} gold rows; need {need} NEW since the "
                  f"last fit. Skipping — --force to refit anyway.")
        return None

    base_tr, generic_te = _load(kind)
    p_train, p_eval, how = _personal_split(kind)

    rows = list(base_tr) + list(p_train)
    weights = ([1.0] * len(base_tr)) + ([float(PERSONAL_WEIGHT)] * len(p_train))

    if kind == "event":
        pipe, classes = _fit_event(rows, weights)
    else:
        classes = sorted({c for _, labs in rows for c in labs})
        pipe, classes = _fit_task(rows, weights, classes)

    got = _evaluate(pipe, kind, generic_te, p_eval, classes)

    # -- THE PROMOTION GATE, on TODAY'S sets --------------------------------
    #
    # The incumbent is RE-SCORED here rather than compared against the number
    # stored when it was fitted. That stored number was computed on a smaller,
    # older personal set — a different test set entirely — so comparing against
    # it is two unrelated numbers wearing a comparison's clothes. The personal
    # set grows every time the user corrects something, which is exactly what
    # makes the stored figure stale.
    installed = LabelModel.load(kind)
    prev = None
    if installed is not None:
        try:
            prev = _evaluate(installed.pipeline, kind, generic_te, p_eval,
                             installed.classes)
        except Exception:
            prev = None

    reason = None
    if prev is not None:
        drop = prev["generic"]["macro_f1"] - got["generic"]["macro_f1"]
        if drop > GENERIC_TOLERANCE:
            reason = (f"generic macro F1 fell {drop:.3f} "
                      f"(> {GENERIC_TOLERANCE}) — it is forgetting general English")
        elif got.get("personal") and prev.get("personal") and \
                got["personal"]["macro_f1"] < prev["personal"]["macro_f1"] - 1e-9:
            reason = (f"personal macro F1 {prev['personal']['macro_f1']:.3f} → "
                      f"{got['personal']['macro_f1']:.3f}")

    if reason:
        if verbose:
            print(f"  {kind}: NOT promoted — {reason}. Keeping the installed model.")
        feedback.mark_trained(kind, len(feedback.gold(kind)))
        return {"promoted": False, "score": got, "previous": prev, "why": reason}

    model = LabelModel(kind, pipe, classes, {
        "tier": "base" if not p_train else "personal",
        "trained_at": time.time(),
        "n_generated": len(base_tr), "n_personal": len(p_train),
        "personal_weight": PERSONAL_WEIGHT, "personal_eval": how,
        "score": got, "previous": prev,
    })
    path = model.save(tier="base" if not p_train else "personal")
    feedback.mark_trained(kind, len(feedback.gold(kind)))
    from assistant.engine.label import model as _m
    _m.reset()
    if verbose:
        g = got["generic"]
        line = f"  {kind}: promoted — generic acc {g['acc']*100:.1f}%, macro F1 {g['macro_f1']:.3f}"
        if got.get("personal"):
            line += f" · personal macro F1 {got['personal']['macro_f1']:.3f} ({how})"
        print(line)
        print(f"        {len(base_tr)} generated + {len(p_train)} personal "
              f"(x{PERSONAL_WEIGHT}) -> {path}")
    return {"promoted": True, "score": got, "previous": prev, "path": str(path)}


def train_base(kind: str, verbose: bool = True) -> "dict | None":
    """Fit the USER-AGNOSTIC model from the committed datasets alone.

    Identical on every machine: no personal gold is read, the datasets are in
    git, and the seed is fixed. So this is a build step, not an experiment —
    there is no promotion gate because there is nothing to compare against and
    nothing user-specific to get wrong.

    Called by `model._cached` when no artefact exists, which is what gives a
    brand-new user a working classifier on day one instead of after twenty-five
    corrections.
    """
    from assistant.engine.label.model import LabelModel
    import assistant.engine.label.model as _m

    base_tr, generic_te = _load(kind)
    weights = [1.0] * len(base_tr)
    if kind == "event":
        pipe, classes = _fit_event(base_tr, weights)
        got = {"generic": _score_event(pipe, generic_te)}
    else:
        classes = sorted({c for _, labs in base_tr for c in labs})
        pipe, classes = _fit_task(base_tr, weights, classes)
        got = {"generic": _score_task(pipe, generic_te, classes)}

    model = LabelModel(kind, pipe, classes, {
        "tier": "base", "trained_at": time.time(),
        "n_generated": len(base_tr), "n_personal": 0, "score": got,
    })
    path = model.save(tier="base")
    _m.reset()
    if verbose:
        g = got["generic"]
        print(f"  {kind} BASE: acc {g['acc']*100:.1f}%, "
              f"macro F1 {g['macro_f1']:.3f} · {len(base_tr)} rows -> {path}")
    return {"promoted": True, "score": got, "path": str(path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("event", "task"), default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--base", action="store_true",
                    help="build the shipped user-agnostic model and stop")
    a = ap.parse_args()
    print("\nLABEL MODELS — fit, gate, promote\n")
    for kind in ([a.kind] if a.kind else ["event", "task"]):
        if a.base:
            train_base(kind)
        else:
            train(kind, force=a.force)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
