"""TWO CLASSIFIERS — event category and task tags — on labels the rules did NOT write.

    python -m assistant.engine.label.experiments.classifier_board
    python -m assistant.engine.label.experiments.classifier_board --tiers

## What changed, and why the earlier numbers were worthless

The first version of this board trained on the FastRule 7,200, whose category
gold is computed BY CALLING `categories.classify()`. Training on that can only
distill the keyword table: a decision tree scored **exactly 100%**, and every
model still lost to the rules on real data (events 71.4% vs 50%).

**The dataset is now generated FROM the label** (`../datasets/generate.py`): a
row's class is what it was generated AS, never what a matcher says about it.
The ground truth is independent of the incumbent, which is the only way a model
can be shown to BEAT it rather than approximate it.

## The split is by SUBJECT, not by row

Splitting rows puts "gym session on tuesday" in train and "gym session at 7" in
test, and every model scores ~100% by remembering the noun. **The test half uses
subjects the training half never saw** — 57 held-out subjects against 156
trained ones, overlap 0, asserted on every run.

That is the question that decides whether a model is worth shipping:
`tagging.KEYWORDS["Groceries"]` is 179 hand-typed words and gets "zucchini"
because somebody typed it. **On unseen vocabulary the keyword rules score by
luck, and a model that has learned the semantic neighbourhood does not.** The
old dataset could not ask this — it had 8 novel-vocabulary rows in 1,179.

## Three evaluations, and the last one outranks the others

    NOVEL VOCABULARY   held-out subjects. The headline.
    REAL USAGE         the live ~/.assistant_tools DB, read-only, never
                       committed. Small and unforgiving; CLAUDE.md says real
                       usage outranks every benchmark.
    RULES, everywhere  the incumbent scored on the identical rows. A model that
                       does not beat this row is not worth shipping.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import tempfile

_S = pathlib.Path(tempfile.mkdtemp(prefix="clf_board_"))
for _v, _n in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
               ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
               ("TRACE_BUS", "trace_bus.jsonl")):
    os.environ[f"MACALENDAR_{_v}"] = str(_S / _n)
os.environ["MACALENDAR_NO_WARMUP"] = "1"
# BACKGROUND traffic: this yields the model to the live assistant between
# every call (assistant/model_protocol.py). Without it a board and a voice
# command are indistinguishable to ollama, and a trivial live call measured
# 2.0s -> 42.5s -> 43.9s behind a running board (2026-09-10).
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
for _t in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_t, "1")

STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE.parent / "fastrule" / "datasets" / "fastrule_7200.jsonl"
REAL_DB = pathlib.Path(os.path.expanduser("~/.assistant_tools/calendar.db"))

#: The two-tier hierarchy, for the flat-vs-tiered comparison. Grouped by what
#: the categories SHARE, not alphabetically: an obligation, a body thing, a
#: people thing, an observance/food thing, a logistics thing.
TIERS = {
    "obligation": ["Work", "Study", "Meeting"],
    "observance": ["Prayer", "Shabbat Meal", "Meal"],
    "people":     ["Social", "Family"],
    "body":       ["Fitness", "Health"],
    "logistics":  ["Errand", "Travel", "Personal"],
}
_TIER_OF = {c: t for t, cs in TIERS.items() for c in cs}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", (s or "").lower()) if len(w) > 2}


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load_events():
    """(texts, labels, splits) from the class-conditional set."""
    rows = [json.loads(l) for l in (STAGE / "datasets" / "event_categories.jsonl").open()]
    return ([r["text"] for r in rows], [r["label"] for r in rows],
            [r["split"] for r in rows], [r["subject"] for r in rows])


def load_tasks():
    rows = [json.loads(l) for l in (STAGE / "datasets" / "task_tags.jsonl").open()]
    return ([r["text"] for r in rows], [r["labels"] for r in rows],
            [r["split"] for r in rows], [r["subject"] for r in rows])


def load_real():
    """Real titles + labels, read-only, never persisted. None when absent."""
    if not REAL_DB.exists():
        return None, None
    import sqlite3
    conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    events = [(t, c) for t, c in
              conn.execute("SELECT title, category FROM events "
                           "WHERE title <> '' AND category IS NOT NULL AND category <> ''")]
    todos = []
    for t, tags in conn.execute("SELECT title, tags FROM todos WHERE title <> ''"):
        try:
            vals = json.loads(tags) if tags else []
        except Exception:
            vals = [x.strip() for x in (tags or "").split(",") if x.strip()]
        if vals:
            todos.append((t, vals))
    conn.close()
    return events, todos


def _vectoriser():
    """Word 1-2 grams UNION character 3-5 grams.

    The char half is the whole point: it is what lets an unseen word be scored
    by its shape rather than looked up, which is the only mechanism by which a
    model can beat an enumerated keyword list on vocabulary nobody typed in.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion
    return FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True,
                                 min_df=1, lowercase=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                 sublinear_tf=True, min_df=2, lowercase=True)),
    ])


def models():
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.decomposition import TruncatedSVD
    from sklearn.pipeline import make_pipeline
    from sklearn.tree import DecisionTreeClassifier
    return [
        ("dummy(most frequent)", DummyClassifier(strategy="most_frequent")),
        ("decision tree", DecisionTreeClassifier(max_depth=40, random_state=0)),
        ("kNN (k=5, cosine)", KNeighborsClassifier(n_neighbors=5, metric="cosine")),
        ("logistic regression", LogisticRegression(max_iter=2000, C=4.0)),
        ("random forest", RandomForestClassifier(n_estimators=300, random_state=0,
                                                 n_jobs=-1)),
        # sklearn's boosted-trees implementation — the XGBoost stand-in.
        #
        # It needs DENSE input, and TF-IDF over text is sparse and very wide
        # (~50k columns). Densifying that is 1.4 GB and pointless; boosted trees
        # are built for dense tabular features, not for a bag of words. So it is
        # given an SVD-reduced view instead, which is the standard pairing and
        # the only honest way to put it on the same board. XGBoost would need
        # exactly the same treatment — this is not a limitation of the stand-in.
        ("hist gradient boosting", make_pipeline(
            TruncatedSVD(n_components=200, random_state=0),
            HistGradientBoostingClassifier(random_state=0))),
    ]


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _report(name: str, y_true, y_pred) -> dict:
    from sklearn.metrics import (accuracy_score, precision_recall_fscore_support)
    acc = accuracy_score(y_true, y_pred)
    p, r, f, _ = precision_recall_fscore_support(
        y_true, y_pred, average="macro", zero_division=0)
    pw, rw, fw, _ = precision_recall_fscore_support(
        y_true, y_pred, average="weighted", zero_division=0)
    return {"name": name, "acc": acc, "P": p, "R": r, "F1": f, "wF1": fw}


def _print_table(title: str, rows: list, note: str = "") -> None:
    print(f"\n  {title}")
    if note:
        print(f"    {note}")
    print(f"    {'model':<24}{'acc':>8}{'macro P':>10}{'macro R':>10}"
          f"{'macro F1':>10}{'wtd F1':>9}")
    for r in sorted(rows, key=lambda x: -x["F1"]):
        print(f"    {r['name']:<24}{r['acc']*100:>7.1f}%{r['P']*100:>9.1f}%"
              f"{r['R']*100:>9.1f}%{r['F1']*100:>9.1f}%{r['wF1']*100:>8.1f}%")


def run_events(args) -> None:
    import numpy as np
    from sklearn.pipeline import Pipeline
    from assistant.actions.calendar import categories as _cat

    texts, labels, splits, subjects = load_events()
    X, y, sp = np.array(texts), np.array(labels), np.array(splits)
    tr, te = np.where(sp == "train")[0], np.where(sp == "test")[0]

    print("\n" + "=" * 78)
    print("EVENT CATEGORY — single-label, generated FROM the label")
    print("=" * 78)
    dist = collections.Counter(y)
    print(f"  {len(X)} rows · {len(dist)} classes · train {len(tr)} / test {len(te)}")
    print("  class balance: " + ", ".join(f"{k} {v}" for k, v in dist.most_common()))
    trs = {subjects[i] for i in tr}
    tes = {subjects[i] for i in te}
    print(f"  SUBJECT overlap train∩test: {len(trs & tes)}  "
          f"({len(trs)} trained subjects, {len(tes)} unseen)")
    assert not (trs & tes), "vocabulary leaked — every number below is inflated"

    rows = [_report("RULES (the incumbent)", y[te], [_cat.classify(t) for t in X[te]])]
    fitted = {}
    for name, clf in models():
        pipe = Pipeline([("feat", _vectoriser()), ("clf", clf)])
        try:
            pipe.fit(X[tr], y[tr])
            fitted[name] = pipe
            rows.append(_report(name, y[te], pipe.predict(X[te])))
        except Exception as e:
            print(f"    {name}: FAILED — {e}")
    _print_table("NOVEL VOCABULARY — test subjects never seen in training", rows,
                 note="The headline. The rules cannot look up a word nobody "
                      "typed into their list.")

    if args.tiers:
        run_tiers(X, y, tr, te)
    _real_events(fitted)



def run_tiers(titles, labels, tr, te) -> None:
    """FLAT vs TWO-TIER: broad class first, then the specific one inside it."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    def _pipe():
        return Pipeline([("feat", _vectoriser()),
                         ("clf", LogisticRegression(max_iter=2000, C=4.0))])

    tiers = np.array([_TIER_OF.get(c, "logistics") for c in labels])
    flat = _pipe().fit(titles[tr], labels[tr])
    flat_pred = flat.predict(titles[te])

    t1 = _pipe().fit(titles[tr], tiers[tr])
    t1_pred = t1.predict(titles[te])
    t2: dict = {}
    for tier in sorted(set(tiers[tr])):
        idx = np.where(tiers[tr] == tier)[0]
        if len(set(labels[tr][idx])) < 2:
            t2[tier] = labels[tr][idx][0]          # only one leaf: constant
            continue
        t2[tier] = _pipe().fit(titles[tr][idx], labels[tr][idx])
    tiered_pred = []
    for title, tier in zip(titles[te], t1_pred):
        leaf = t2.get(tier)
        tiered_pred.append(leaf if isinstance(leaf, str) else leaf.predict([title])[0])

    rows = [_report("FLAT (13-way, logreg)", labels[te], flat_pred),
            _report("TIERED (5 → leaf)", labels[te], tiered_pred)]
    _print_table("FLAT vs TWO-TIER, same model and features both sides", rows)
    tier_acc = float((t1_pred == tiers[te]).mean())
    print(f"    tier-1 (5-way) accuracy on its own: {tier_acc*100:.1f}% — this is "
          f"the tiered path's CEILING;\n    a leaf can only be right when its "
          f"branch was.")


def _real_events(fitted: dict) -> None:
    """Real titles, labelled by hand. The only non-circular evidence there is.

    The LIVE DB is deliberately not scored here any more. Board 2 established
    that its 14 rows cannot adjudicate anything — four are test traffic, one is
    the generic-title bug, and dog-walking carries three different labels — so
    the rules "won" it by answering Personal against a mostly-Personal set.
    `../datasets/REAL_GOLD.md` records what replaced it and who labelled it.
    """
    import json as _json
    import numpy as np
    from assistant.actions.calendar import categories as _cat

    path = STAGE / "datasets" / "real_event_gold.jsonl"
    if not path.exists():
        print("\n  REAL USAGE: no hand-labelled gold — section skipped.")
        return
    rows = [_json.loads(l) for l in path.open() if l.strip()]
    rt = np.array([r["text"] for r in rows])
    ry = np.array([r["label"] for r in rows])
    present = sorted(set(ry))

    print(f"\n  REAL USAGE — {len(rows)} real titles from the utterance pool, "
          f"labelled by hand")
    print(f"    {len(present)} of 13 categories present: {', '.join(present)}")
    print(f"    labelled by Claude, not by the user — see datasets/REAL_GOLD.md. "
          f"EVALUATION ONLY,\n    never trained on: a set fitted against cannot "
          f"answer the question it exists for.")

    rule_pred = [_cat.classify(t) for t in rt]
    rrows = [_report("RULES (the incumbent)", ry, rule_pred)]
    for name, pipe in fitted.items():
        try:
            rrows.append(_report(name, ry, pipe.predict(rt)))
        except Exception:
            pass

    # THE SHIPPED PATH, which is neither column above.
    #
    # `model.category_for` runs the rules FIRST and asks the model only where
    # they fell through to the catch-all. Scoring the two components separately
    # measures two things nobody runs; this measures what a user would actually
    # get, and it is the only row on this board that should decide whether the
    # feature is worth enabling.
    best = max((r for r in rrows if r["name"] != "RULES (the incumbent)"),
               key=lambda r: r["F1"], default=None)
    if best and best["name"] in fitted:
        pipe = fitted[best["name"]]
        stacked = []
        for title, rule_answer in zip(rt, rule_pred):
            if rule_answer and rule_answer != "Personal":
                stacked.append(rule_answer)          # the rules were confident
                continue
            try:
                proba = pipe.predict_proba([title])[0]
                i = max(range(len(proba)), key=lambda k: proba[k])
                stacked.append(str(pipe.classes_[i]) if proba[i] >= 0.35
                               else rule_answer)      # unconfident -> abstain
            except Exception:
                stacked.append(rule_answer)
        rrows.append(_report(f"STACKED (shipped: rules + {best['name']})",
                             ry, stacked))
    _print_table(f"REAL USAGE ({len(rows)} titles) — labels the rules did not write",
                 rrows, note="81 rows: a few points here is noise. It is still "
                             "the only non-circular real evidence.")


# ---------------------------------------------------------------------------
# task tags — a DIFFERENT problem shape
# ---------------------------------------------------------------------------

def run_tasks(args) -> None:
    """MULTI-LABEL, and that changes every metric.

    `suggest_tags` returns a LIST — a task can be Groceries and Errands at once
    — so this is one-vs-rest over the tag palette, and accuracy means EXACT SET
    match, which is a harsh and honest number. Macro F1 over the labels is the
    one to read, because the palette is imbalanced.
    """
    import numpy as np
    from sklearn.metrics import f1_score, precision_recall_fscore_support
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import MultiLabelBinarizer
    from assistant.actions.todo import tagging as _tag

    texts, labels, splits, subjects = load_tasks()
    palette = sorted(_tag.KEYWORDS)
    X, sp = np.array(texts), np.array(splits)
    mlb = MultiLabelBinarizer(classes=palette)
    Y = mlb.fit_transform(labels)
    tr, te = np.where(sp == "train")[0], np.where(sp == "test")[0]

    print("\n" + "=" * 78)
    print(f"TASK TAGS — MULTI-label, {len(palette)} tags: {', '.join(palette)}")
    print("=" * 78)
    print(f"  {len(X)} rows · train {len(tr)} / test {len(te)}")
    print("  tag balance: " + ", ".join(
        f"{p} {int(Y[:, i].sum())}" for i, p in enumerate(palette)))
    trs = {subjects[i] for i in tr}
    tes = {subjects[i] for i in te}
    print(f"  SUBJECT overlap train∩test: {len(trs & tes)}  "
          f"({len(trs)} trained, {len(tes)} unseen)")
    assert not (trs & tes), "vocabulary leaked"

    def score(name, pred, truth):
        exact = float((pred == truth).all(axis=1).mean())
        pr, rc, f, _ = precision_recall_fscore_support(
            truth, pred, average="macro", zero_division=0)
        return {"name": name, "acc": exact, "P": pr, "R": rc, "F1": f,
                "wF1": f1_score(truth, pred, average="weighted", zero_division=0)}

    rows = [score("RULES (the incumbent)",
                  mlb.transform([_tag.suggest_tags(t, palette) for t in X[te]]),
                  Y[te])]
    fitted = {}
    for name, clf in models():
        if name.startswith("dummy"):
            continue
        try:
            pipe = Pipeline([("feat", _vectoriser()),
                             ("clf", OneVsRestClassifier(clf, n_jobs=1))])
            pipe.fit(X[tr], Y[tr])
            fitted[name] = pipe
            rows.append(score(name, pipe.predict(X[te]), Y[te]))
        except Exception as e:
            print(f"    {name}: FAILED — {e}")
    _print_table("NOVEL VOCABULARY — test subjects never seen in training", rows,
                 note="`acc` is EXACT SET match.")

    _real_tasks(fitted, mlb, palette, score)


def _real_tasks(fitted, mlb, palette, score) -> None:
    import numpy as np
    from assistant.actions.todo import tagging as _tag

    _, todos = load_real()
    if not todos:
        print("\n  REAL USAGE (tasks): nothing tagged in the live DB — skipped.")
        return
    keep = [(t, [v for v in tags if v in palette]) for t, tags in todos]
    keep = [(t, tags) for t, tags in keep if tags]
    print(f"\n  REAL USAGE — {len(todos)} tagged todos, {len(keep)} using a tag "
          f"the model knows")
    if len(keep) < 10:
        print("    too few scoreable rows for a board.")
        return
    rt = np.array([t for t, _ in keep])
    RY = mlb.transform([tags for _, tags in keep])
    rows = [score("RULES (the incumbent)",
                  mlb.transform([_tag.suggest_tags(t, palette) for t in rt]), RY)]
    for name, pipe in fitted.items():
        try:
            rows.append(score(name, pipe.predict(rt), RY))
        except Exception:
            pass
    _print_table(f"REAL USAGE ({len(keep)} todos) — the only rows nobody generated",
                 rows, note="These tags came off Gil's own list.")



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", action="store_true",
                    help="also run the flat-vs-two-tier comparison")
    ap.add_argument("--events-only", action="store_true")
    ap.add_argument("--tasks-only", action="store_true")
    a = ap.parse_args()

    if not a.tasks_only:
        run_events(a)
    if not a.events_only:
        run_tasks(a)

    print("\n" + "-" * 78)
    print("XGBoost / LightGBM are NOT installed, and installing either needs the")
    print("network — which this project deliberately never touches (test_offline.py")
    print("fails the build if it does). `hist gradient boosting` above is sklearn's")
    print("implementation of the same algorithm and is the honest stand-in. Adding")
    print("the real xgboost is a deliberate one-off network exception — Gil's call.")
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
