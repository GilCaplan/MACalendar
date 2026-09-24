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

#: THE EMBEDDING HEAD (DEVQA Q46, 2026-09-24). Fitted beside the n-gram
#: pipeline, never instead of it: the pipeline is what answers whenever the
#: title's vector cannot be had. See `_fit_embed`.
EMBED_CACHE_NAME = "label_embed_cache.jsonl"
#: The validation carve the head's threshold is chosen on: this share of the
#: generated TRAIN subjects, held out BY SUBJECT like the test half is.
EMBED_VAL_FRAC = 0.2
EMBED_THRESHOLD_GRID = [round(0.20 + 0.025 * i, 3) for i in range(31)]     # 0.20 … 0.95


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


def _subjects(kind: str) -> dict:
    """text -> subject for the generated TRAIN rows (the carve groups by it)."""
    name = "event_categories.jsonl" if kind == "event" else "task_tags.jsonl"
    try:
        return {r["text"]: r["subject"] for r in
                (json.loads(l) for l in (DATASETS / name).open() if l.strip())
                if r.get("split") == "train"}
    except Exception:
        return {}


def _embed_rows(texts):
    """Vectors for every text, through the disk cache beside the personal models,
    as BACKGROUND traffic — a refit is never a person waiting — or None."""
    from assistant import model_protocol
    from assistant.engine.label import embed as _embed
    from assistant.engine.label import model as _m
    with model_protocol.serving(None):          # no person waiting: background
        return _embed.vectors_cached_on_disk(list(texts), _m.MODELS_DIR / EMBED_CACHE_NAME)


def _head_fit(kind, texts, labels, weights, E, classes):
    """One embedding head, fitted. Events: LR on n-grams + vector. Tasks: OvR LR
    on the vector (personal rows repeated rather than weighted, because the
    one-vs-rest wrapper does not route sample weights)."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from assistant.engine.label.model import EmbedHead
    if kind == "event":
        idx = {c: i for i, c in enumerate(classes)}
        vec = _vectoriser().fit(list(texts))
        head = EmbedHead(kind, LogisticRegression(max_iter=2000, C=4.0), classes, 0.5, vec)
        head.clf.fit(head.features(texts, E), np.array([idx[l] for l in labels]),
                     sample_weight=np.asarray(weights, float))
        return head
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.preprocessing import MultiLabelBinarizer
    reps = [max(1, int(round(w))) for w in weights]
    order = [i for i, r in enumerate(reps) for _ in range(r)]
    Y = MultiLabelBinarizer(classes=classes).fit_transform([labels[i] for i in order])
    head = EmbedHead(kind, OneVsRestClassifier(LogisticRegression(max_iter=2000, C=4.0), n_jobs=1),
                     classes, 0.5)
    head.clf.fit(np.asarray(E)[order], Y)
    return head


def _head_answers(head, texts, E, t):
    """(answer or None) per row at threshold t."""
    import numpy as np
    P = head.proba(texts, E)
    out = []
    for row in P:
        if head.kind == "event":
            k = int(np.argmax(row))
            out.append(head.classes[k] if row[k] >= t else None)
        else:
            got = sorted(head.classes[k] for k in np.where(row >= t)[0])
            out.append(got or None)
    return out


def _fit_embed(kind: str, rows, weights, classes, verbose: bool = False):
    """(EmbedHead, info) — or (None, reason) when the vectors cannot be had.

    THE THRESHOLD IS CHOSEN ON TRAIN. A subject-grouped carve of the generated
    TRAIN rows (EMBED_VAL_FRAC of the subjects; personal rows stay on the fit
    side) is held out, a head is fitted on the rest, and the threshold is the
    one that maximises (right - wrong) over the rows it ANSWERS: the head
    speaks only where it is more often right than wrong, and a row it declines
    goes to the rules' default. That criterion does not reward answering
    everything (the generated sets have no row whose right answer is the
    default, so plain accuracy would), and does not demand a precision unseen
    subjects cannot reach (a 90% bar left events answering 4% of rows,
    label Board 6). Then the head is refitted on all the rows.
    """
    import numpy as np
    texts = [t for t, _ in rows]
    labels = [l for _, l in rows]
    E = _embed_rows(texts)
    if E is None:
        return None, "embeddings unavailable (ollama down or MACALENDAR_LLM_DISABLED)"
    subj = _subjects(kind)
    groups = [subj.get(t) for t in texts]
    pool = sorted({g for g in groups if g})
    rng = np.random.default_rng(0)
    rng.shuffle(pool)
    val_s = set(pool[:int(len(pool) * EMBED_VAL_FRAC)])
    fit_i = [i for i, g in enumerate(groups) if g not in val_s]
    val_i = [i for i, g in enumerate(groups) if g in val_s]
    t_best, curve = 0.5, {}
    if val_i:
        vh = _head_fit(kind, [texts[i] for i in fit_i], [labels[i] for i in fit_i],
                       [weights[i] for i in fit_i], E[fit_i], classes)
        vt = [texts[i] for i in val_i]
        gold = [labels[i] for i in val_i]
        best = None
        for t in EMBED_THRESHOLD_GRID:
            ans = _head_answers(vh, vt, E[val_i], t)
            right = sum(1 for a, g in zip(ans, gold) if a is not None and
                        (a == g if kind == "event" else a == sorted(g)))
            wrong = sum(1 for a in ans if a is not None) - right
            curve[t] = {"answered": (right + wrong) / len(vt), "precision":
                        right / (right + wrong) if right + wrong else 0.0}
            if best is None or right - wrong > best:
                best, t_best = right - wrong, t
    head = _head_fit(kind, texts, labels, weights, E, classes)
    head.threshold = t_best
    info = {"features": "word 1-2 + char 3-5 grams + nomic-embed-text"
                        if kind == "event" else "nomic-embed-text",
            "embed_model": "nomic-embed-text", "threshold": t_best,
            "threshold_rule": "max (right - wrong) over answered rows, "
                              f"subject-grouped {EMBED_VAL_FRAC:.0%} carve of TRAIN",
            "val_rows": len(val_i), "val_at_threshold": curve.get(t_best)}
    if verbose:
        v = curve.get(t_best) or {}
        print(f"        embedding head: threshold {t_best} (TRAIN carve, {len(val_i)} rows: "
              f"answers {v.get('answered', 0)*100:.1f}% at {v.get('precision', 0)*100:.1f}% precision)")
    return head, info


def _score_head(head, kind, test_rows) -> "dict | None":
    """The head alone on the generic TEST half, never abstaining — the number
    that sits beside the n-gram pipeline's in the meta."""
    import numpy as np
    from sklearn.metrics import f1_score
    E = _embed_rows([t for t, _ in test_rows])
    if E is None:
        return None
    texts = [t for t, _ in test_rows]
    P = head.proba(texts, E)
    if kind == "event":
        y = [l for _, l in test_rows]
        pred = [head.classes[int(k)] for k in P.argmax(1)]
        return {"acc": float(np.mean([a == b for a, b in zip(y, pred)])),
                "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0))}
    from sklearn.preprocessing import MultiLabelBinarizer
    mlb = MultiLabelBinarizer(classes=head.classes)
    Y = mlb.fit_transform([l for _, l in test_rows])
    pred = (P >= 0.5).astype(int)
    return {"acc": float((pred == Y).all(axis=1).mean()),
            "macro_f1": float(f1_score(Y, pred, average="macro", zero_division=0))}


def _attach_head(kind, rows, weights, classes, generic_te, ngram_generic, verbose):
    """Fit the embedding head and return (head or None, meta). A head that
    scores BELOW the n-gram pipeline on the generic TEST half is not attached:
    it would be worse than the fallback it sits in front of."""
    head, info = _fit_embed(kind, rows, weights, classes, verbose=verbose)
    if head is None:
        return None, {"embed": None, "embed_why": info}
    got = _score_head(head, kind, generic_te)
    info["generic"] = got
    if got is not None and ngram_generic and got["macro_f1"] < ngram_generic["macro_f1"]:
        return None, {"embed": None, "embed_why": "scored below the n-gram model on "
                      f"generic TEST ({got['macro_f1']:.3f} < {ngram_generic['macro_f1']:.3f})"}
    return head, {"embed": info}


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

    head, head_meta = _attach_head(kind, rows, weights, classes, generic_te,
                                   got.get("generic"), verbose)
    model = LabelModel(kind, pipe, classes, {
        "tier": "base" if not p_train else "personal",
        "trained_at": time.time(),
        "n_generated": len(base_tr), "n_personal": len(p_train),
        "personal_weight": PERSONAL_WEIGHT, "personal_eval": how,
        "score": got, "previous": prev, **head_meta,
    }, head)
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


def train_base(kind: str, verbose: bool = True, embed: bool = True) -> "dict | None":
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

    head, head_meta = (_attach_head(kind, base_tr, weights, classes, generic_te,
                                    got.get("generic"), verbose)
                       if embed else (None, {"embed": None, "embed_why": "not requested"}))
    model = LabelModel(kind, pipe, classes, {
        "tier": "base", "trained_at": time.time(),
        "n_generated": len(base_tr), "n_personal": 0, "score": got, **head_meta,
    }, head)
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
    # a refit is never a person waiting: its embedding calls yield to live traffic
    import os
    os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
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
