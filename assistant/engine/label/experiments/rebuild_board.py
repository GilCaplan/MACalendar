"""THE LABEL REBUILD BOARD — rules, the shipped model, boosting, embeddings and
Gil's cascade, on IDENTICAL splits.

    python -m assistant.engine.label.experiments.rebuild_board              # all of it
    python -m assistant.engine.label.experiments.rebuild_board --no-embed   # no ollama call
    python -m assistant.engine.label.experiments.rebuild_board --only events|tasks|newtag|palette

Gil, 2026-09-24: *"remake a ML model maybe xgboost is better? think of what
data- train-test and features would be good given the prompt, can have a simple
rule that if has simple words like buy or other things choose category otherwise
go through ML model, pay attentnion to new tags or existing"*.

## What every method is trained on, and what it is scored on

    TRAIN   the generated sets' TRAIN half only (`../datasets/*.jsonl`), the
            same rows the shipped base model was fitted on. Split by SUBJECT:
            a subject never sits on both sides, asserted on every run.
    TEST    (1) the generated TEST half — novel vocabulary, labels by
            construction; (2) REAL rows, deduplicated by normalised title so a
            recurring series counts once. Real rows are EVALUATION ONLY: the
            event gold says so (`../datasets/REAL_GOLD.md`) and the to-do tags
            are partly the classifier's own output (silence is not agreement,
            `../ARCHITECTURE.md`), so nothing real is fitted, tuned or selected
            against. Every threshold and every cascade rule is chosen on the
            TRAIN half.

## Abstention

Every method answers the DEFAULT (event: `Personal`; to-do: no tag) below its
threshold. The threshold is chosen on a subject-grouped 20% validation carve of
TRAIN — the lowest confidence at which the answered rows are >= 90% precise,
the keyword rules' own measured precision — never on a test row.

    acc       accuracy (to-dos: EXACT tag-set match), abstentions included
    mF1       macro F1 (sklearn, over the labels present in gold or prediction)
    cov       coverage — the share of rows the method ANSWERED (rules: a
              non-default answer; a model: confidence >= its threshold)
    cw        confident-and-wrong — answered AND wrong, as a share of all rows.
              The number a user feels: a wrong label has to be undone by hand.

## The environment

Every personal store is pointed at a scratch dir before anything from
`assistant` is imported. `MACALENDAR_MODEL_LOCK` is deliberately NOT scratched:
the embedding calls go through `model_protocol.hold()` as background traffic,
and a private lock would arbitrate against nobody. The real calendar DB is read
with `mode=ro`; the real vocabulary is COPIED into the scratch dir (read-only
on the original) so the keyword rules behave as they do live.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import tempfile

from assistant.common.scratch_env import scratch_env

# OpenMP drives the boosted trees (HGB, XGBoost); BLAS stays pinned as
# elsewhere. Set BEFORE scratch_env so its own thread pin (setdefault) leaves
# this one alone.
os.environ.setdefault("OMP_NUM_THREADS", "4")
_S = pathlib.Path(scratch_env(
    "label_rebuild_", keep=("LOCATION", "HEARTBEATS", "HUD_STATE")))
os.environ["MACALENDAR_CHECKPOINTS"] = str(_S / "checkpoints")
_REAL_VOCAB = pathlib.Path(os.path.expanduser("~/.assistant_tools/vocab.json"))
if _REAL_VOCAB.exists():
    shutil.copyfile(_REAL_VOCAB, _S / "vocab.json")      # a copy; the original is only read

import argparse          # noqa: E402
import collections       # noqa: E402
import json              # noqa: E402
import re                # noqa: E402
import sys               # noqa: E402
import time              # noqa: E402

import numpy as np       # noqa: E402

STAGE = pathlib.Path(__file__).resolve().parents[1]
REAL_DB = pathlib.Path(os.path.expanduser("~/.assistant_tools/calendar.db"))
REAL_FEEDBACK = pathlib.Path(os.path.expanduser("~/.assistant_tools/label_feedback.jsonl"))
EMBED_MODEL = "nomic-embed-text"
EMBED_CACHE = pathlib.Path(tempfile.gettempdir()) / "macalendar_label_embed_cache.jsonl"
DEFAULT_EVENT = "Personal"
#: The precision the abstention threshold and the cascade's rules must reach on
#: TRAIN — the keyword rules' own measured precision (91.7%, task tags) rounded.
TARGET_PRECISION = 0.90
RULE_PRECISION = 0.95          # Gil's cascade: a keyword is kept only at >= 95% ...
RULE_MIN_ROWS = 20             # ... over at least this many train rows ...
RULE_MIN_SUBJECTS = 3          # ... drawn from this many distinct subjects
INCUMBENT_MIN_ROWS = 10        # a hand-written keyword: evidence from 10 train rows


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _log(msg: str) -> None:
    print(f"  {_now()} {msg}", flush=True)


def norm(s: str) -> str:
    s = re.sub(r"[^\w\s'&+-]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load_gen(kind: str):
    name = "event_categories.jsonl" if kind == "event" else "task_tags.jsonl"
    rows = [json.loads(l) for l in (STAGE / "datasets" / name).open() if l.strip()]
    key = "label" if kind == "event" else "labels"
    tr = [r for r in rows if r["split"] == "train"]
    te = [r for r in rows if r["split"] == "test"]
    trs, tes = {r["subject"] for r in tr}, {r["subject"] for r in te}
    assert not (trs & tes), "subject leaked across the split — every number is inflated"
    return ([r["text"] for r in tr], [r[key] for r in tr], [r["subject"] for r in tr],
            [r["text"] for r in te], [r[key] for r in te], [r["subject"] for r in te])


def real_event_sets() -> dict:
    """{name: [(title, label, provenance)]} — every set deduplicated by title."""
    out = {}
    gold = [json.loads(l) for l in (STAGE / "datasets" / "real_event_gold.jsonl").open() if l.strip()]
    seen = {}
    for r in gold:
        seen.setdefault(norm(r["text"]), (r["text"], r["label"], "hand-labelled (Claude), HWU-64 text"))
    out["gold81"] = list(seen.values())
    if REAL_FEEDBACK.exists():
        fb = {}
        for line in REAL_FEEDBACK.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("kind") == "event" and r.get("origin") in ("correction", "explicit"):
                fb[norm(r["text"])] = (r["text"], r["label"], f"Gil's {r['origin']}")
        out["feedback"] = list(fb.values())
    if REAL_DB.exists():
        import sqlite3
        from assistant.actions.calendar import categories as _cat
        conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
        latest = {}
        for t, c, att, loc, desc, upd in conn.execute(
                "SELECT title, category, attendees, location, description, updated_at "
                "FROM events WHERE title <> '' AND category <> '' ORDER BY updated_at"):
            latest[norm(t)] = (t, c, att, loc, desc)
        conn.close()
        rows = []
        for t, c, att, loc, desc in latest.values():
            rule = _cat.classify(t, att, loc or "", desc or "")
            rows.append((t, c, _provenance(c, rule, _stacked_event(t, rule))))
        out["calendar_db"] = rows
    return out


def real_task_rows():
    """[(title, tags, provenance)] from the live to-do list, one per distinct title
    (the most recently updated wins). Untagged rows are not scored: an empty tag
    set there is silence, not an answer."""
    if not REAL_DB.exists():
        return [], []
    import sqlite3
    from assistant.actions.todo import tagging as _tag
    conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    palette = [r[0] for r in conn.execute("SELECT name FROM todo_tags")]
    latest = {}
    for t, tags, upd, created in conn.execute(
            "SELECT title, tags, updated_at, created_at FROM todos WHERE title <> '' "
            "ORDER BY COALESCE(updated_at, created_at)"):
        try:
            vals = json.loads(tags) if tags else []
        except ValueError:
            vals = [x.strip() for x in (tags or "").split(",") if x.strip()]
        latest[norm(t)] = (t.strip(), sorted(vals))
    conn.close()
    rows = []
    for t, tags in latest.values():
        if not tags:
            continue
        rule = sorted(_tag.suggest_tags(t, palette))
        rows.append((t, tags, _provenance(tags, rule, _stacked_task(t, rule))))
    return rows, palette


def _provenance(stored, rule, stacked) -> str:
    """Who could have written this label. Only 'neither' is clean gold: a label
    the rules or the shipped stacked path would write today may be their own
    output read back (silence is not agreement, ../ARCHITECTURE.md)."""
    if stored == rule:
        return "rules-agree (circular)"
    if stored == stacked:
        return "model-agrees (circular)"
    return "neither (hand-set)"


def _stacked_event(title, rule):
    from types import SimpleNamespace
    from assistant.engine.label import model as _lm
    cfg = SimpleNamespace(labels=SimpleNamespace(model_event=True, model_task=True, model_first=False))
    return _lm.category_for(title, rule, cfg)[0]


def _stacked_task(title, rule):
    from types import SimpleNamespace
    from assistant.engine.label import model as _lm
    cfg = SimpleNamespace(labels=SimpleNamespace(model_event=True, model_task=True, model_first=False))
    return sorted(_lm.tags_for(title, rule, cfg)[0])


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

_DAYS = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow|tonight|weekend)"
_STRIP = [
    r"\b(uh|um|erm|so|yeah|please|i think|also|and)\b",
    r"\b(can|could) you\b", r"\bi need\b", r"\bi've got\b", r"\bdon't (let me )?forget\b",
    r"\bremind me (about|to)\b", r"\bmake a note of\b", r"\b(in|on) the (diary|calendar|list)\b",
    r"\bto (the|my) list\b", r"\bon the list\b", r"\bbooked\b", r"\bin for\b",
    rf"\b(on |next |this |the day after )?{_DAYS}\b", r"\bnext (week|month)\b",
    r"\bin two weeks\b", r"\bon the \d+(st|nd|rd|th)\b",
    r"\b(at )?(\d{1,2}(:\d\d)?\s?(am|pm)?|noon|midday)\b", r"\bhalf past \w+\b",
    r"\bquarter to \w+\b", r"\b(in the )?(morning|afternoon|evening)\b",
    r"\bfirst thing\b", r"\blate afternoon\b", r"\bthis evening\b",
    r"^(book|schedule|add|put|set up|pencil in|get|make)\b",
]


def strip_frame(text: str) -> str:
    """The command's frame removed — day, time, filler and the leading command
    verb — leaving what the event or task is ABOUT. The ablation that asks
    whether the frame (including its verb) carries any signal."""
    s = norm(text)
    for _ in range(2):
        for p in _STRIP:
            s = re.sub(p, " ", s).strip()
        s = re.sub(r"\s+", " ", s)
    return s or norm(text)


def tfidf(kind: str):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion
    word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)
    if kind == "word":
        return word
    if kind == "char":
        return char
    return FeatureUnion([("word", word), ("char", char)])


class Embedder:
    """nomic-embed-text through the ONE gate, cached on disk one batch per line
    (flushed and fsynced), so a crash costs the batch in flight and a rerun
    resumes. Cache is keyed by the exact text; the vectors are deterministic."""

    def __init__(self, cache: pathlib.Path, enabled: bool) -> None:
        self.cache = cache
        self.enabled = enabled
        self.vec: dict = {}
        if cache.exists():
            for line in cache.read_text().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("model") == EMBED_MODEL:
                    self.vec[row["t"]] = row["v"]

    def ready(self, texts) -> bool:
        return all(t in self.vec for t in texts)

    def fill(self, texts, batch: int = 64) -> None:
        todo = sorted({t for t in texts if t not in self.vec})
        if not todo:
            return
        if not self.enabled:
            raise RuntimeError("embeddings missing and --no-embed was given")
        import urllib.request
        from assistant import model_protocol
        _log(f"embedding {len(todo)} texts with {EMBED_MODEL} (cache: {self.cache})")
        t0 = time.monotonic()
        with self.cache.open("a") as fh:
            for i in range(0, len(todo), batch):
                chunk = todo[i:i + batch]
                body = json.dumps({"model": EMBED_MODEL, "keep_alive": "2m",
                                   "input": ["classification: " + t for t in chunk]}).encode()
                req = urllib.request.Request("http://127.0.0.1:11434/api/embed", data=body,
                                             headers={"Content-Type": "application/json"})
                with model_protocol.hold():
                    with urllib.request.urlopen(req, timeout=300) as r:
                        got = json.loads(r.read())["embeddings"]
                for t, v in zip(chunk, got):
                    v = [round(float(x), 6) for x in v]
                    self.vec[t] = v
                    fh.write(json.dumps({"model": EMBED_MODEL, "t": t, "v": v}) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
                done = min(i + batch, len(todo))
                if (i // batch) % 20 == 0 or done == len(todo):
                    el = time.monotonic() - t0
                    rate = done / el if el else 0
                    eta = (len(todo) - done) / rate if rate else 0
                    _log(f"embed {done}/{len(todo)} · {rate*60:.0f}/min · eta {eta/60:.1f}m")

    def matrix(self, texts) -> np.ndarray:
        m = np.array([self.vec[t] for t in texts], dtype=np.float32)
        return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)


# ---------------------------------------------------------------------------
# models — each is (features, estimator); every one exposes class probabilities
# ---------------------------------------------------------------------------

def _xgb_available() -> bool:
    try:
        import xgboost  # noqa: F401
        return True
    except Exception:
        return False


def estimator(name: str, n_classes: int, multilabel: bool):
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.decomposition import TruncatedSVD
    from sklearn.pipeline import make_pipeline
    from sklearn.multiclass import OneVsRestClassifier
    if name == "lr":
        est = LogisticRegression(max_iter=2000, C=4.0)
    elif name == "knn":
        est = KNeighborsClassifier(n_neighbors=15, metric="cosine", weights="distance")
    elif name == "hgb_svd":
        est = make_pipeline(TruncatedSVD(n_components=200, random_state=0),
                            HistGradientBoostingClassifier(random_state=0))
    elif name == "hgb":
        est = HistGradientBoostingClassifier(random_state=0)
    elif name == "xgb":
        import xgboost
        est = xgboost.XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.1,
                                    tree_method="hist", subsample=0.9,
                                    colsample_bytree=0.5, random_state=0, n_jobs=8,
                                    eval_metric="logloss" if multilabel else "mlogloss")
    else:
        raise KeyError(name)
    return OneVsRestClassifier(est, n_jobs=1) if multilabel else est


#: (label, feature set, estimator). The first row is the shipped model refitted;
#: the board also loads the COMMITTED artefact and checks they agree.
METHODS = [
    ("LR  word+char (shipped)", "wc", "lr"),
    ("LR  word only", "word", "lr"),
    ("LR  char only", "char", "lr"),
    ("LR  word+char, frame stripped", "wc_strip", "lr"),
    ("HGB SVD(200) of word+char", "wc", "hgb_svd"),
    ("XGB word+char (sparse)", "wc", "xgb"),
    ("LR  embedding", "emb", "lr"),
    ("kNN embedding (k=15)", "emb", "knn"),
    ("HGB embedding", "emb", "hgb"),
    ("XGB embedding", "emb", "xgb"),
    ("LR  word+char+embedding", "wc_emb", "lr"),
]


#: The models also run in the SHIPPED shape — rules first, model on the blanks.
STACK_BEHIND_RULES = ["LR  word+char (shipped)", "LR  embedding", "LR  word+char+embedding",
                      "kNN embedding (k=15)", "XGB word+char (sparse)", "XGB embedding"]


class Featurizer:
    def __init__(self, fs: str, emb: "Embedder | None") -> None:
        self.fs, self.emb, self.vec = fs, emb, None

    def _text(self, texts):
        return [strip_frame(t) for t in texts] if self.fs == "wc_strip" else list(texts)

    def fit(self, texts):
        if self.fs in ("word", "char", "wc", "wc_strip", "wc_emb"):
            self.vec = tfidf({"word": "word", "char": "char"}.get(self.fs, "wc"))
            self.vec.fit(self._text(texts))
        return self

    def transform(self, texts):
        import scipy.sparse as sp
        if self.fs == "emb":
            return self.emb.matrix(texts)
        X = self.vec.transform(self._text(texts))
        if self.fs == "wc_emb":
            X = sp.hstack([X, sp.csr_matrix(self.emb.matrix(texts))]).tocsr()
        return X


def fit_proba(fs, est_name, tr_x, tr_y, emb, multilabel, classes):
    """Fit on (tr_x, tr_y) and return a function texts -> prob matrix over `classes`."""
    feat = Featurizer(fs, emb).fit(tr_x)
    X = feat.transform(tr_x)
    est = estimator(est_name, len(classes), multilabel)
    if multilabel:
        from sklearn.preprocessing import MultiLabelBinarizer
        Y = MultiLabelBinarizer(classes=classes).fit_transform(tr_y)
        est.fit(X, Y)

        def proba(texts):
            return np.asarray(est.predict_proba(feat.transform(texts)))
    else:
        idx = {c: i for i, c in enumerate(classes)}
        y = np.array([idx[c] for c in tr_y])
        est.fit(X, y)
        cols = list(est.classes_)

        def proba(texts):
            p = est.predict_proba(feat.transform(texts))
            out = np.zeros((p.shape[0], len(classes)))
            out[:, cols] = p
            return out
    return proba


# ---------------------------------------------------------------------------
# decisions and scoring
# ---------------------------------------------------------------------------

def decide_event(P, classes, t):
    """argmax, or the default below threshold. Returns (preds, answered mask)."""
    i = P.argmax(1)
    conf = P.max(1)
    ans = conf >= t
    preds = [classes[k] if a else DEFAULT_EVENT for k, a in zip(i, ans)]
    return preds, ans


def decide_task(P, classes, t):
    """Every tag at or over t; below t on all of them, no tag. At t=None the
    model never abstains: tags >= 0.5, else its single best tag."""
    preds, ans = [], []
    for row in P:
        if t is None:
            got = [classes[k] for k in np.where(row >= 0.5)[0]] or [classes[int(row.argmax())]]
        else:
            got = [classes[k] for k in np.where(row >= t)[0]]
        preds.append(sorted(got))
        ans.append(bool(got))
    return preds, np.array(ans)


def score(kind, gold, preds, answered, classes=None) -> dict:
    from sklearn.metrics import f1_score
    n = len(gold)
    if kind == "event":
        right = np.array([g == p for g, p in zip(gold, preds)])
        mf1 = f1_score(gold, preds, average="macro", zero_division=0)
    else:
        from sklearn.preprocessing import MultiLabelBinarizer
        mlb = MultiLabelBinarizer(classes=classes)
        G = mlb.fit_transform(gold)
        Pm = mlb.transform([[x for x in p if x in classes] for p in preds])
        right = np.array([sorted(g) == sorted(p) for g, p in zip(gold, preds)])
        mf1 = f1_score(G, Pm, average="macro", zero_division=0)
    answered = np.asarray(answered, bool)
    return {"right": right.tolist(),
            "n": n, "acc": float(right.mean()) if n else 0.0, "mf1": float(mf1),
            "cov": float(answered.mean()) if n else 0.0,
            "cw": float((answered & ~right).mean()) if n else 0.0}


def pick_threshold(kind, P, gold, classes) -> float:
    """Lowest threshold whose ANSWERED rows reach TARGET_PRECISION on the
    validation carve. If none does, the highest grid value (answers little)."""
    best_t, best_p = 0.5, -1.0
    for t in np.round(np.arange(0.20, 0.96, 0.025), 3):
        if kind == "event":
            preds, ans = decide_event(P, classes, t)
            ok = [g == p for g, p, a in zip(gold, preds, ans) if a]
        else:
            preds, ans = decide_task(P, classes, t)
            ok = [sorted(g) == p for g, p, a in zip(gold, preds, ans) if a]
        if len(ok) < 0.05 * len(gold):
            break
        if np.mean(ok) >= TARGET_PRECISION:
            return float(t)
        if np.mean(ok) > best_p:
            best_t, best_p = float(t), float(np.mean(ok))
    return best_t          # the target was unreachable: the most precise threshold


def grouped_carve(subjects, frac=0.2, seed=0):
    subs = sorted(set(subjects))
    rng = np.random.default_rng(seed)
    rng.shuffle(subs)
    val = set(subs[:max(1, int(len(subs) * frac))])
    tr = [i for i, s in enumerate(subjects) if s not in val]
    va = [i for i, s in enumerate(subjects) if s in val]
    return tr, va


# ---------------------------------------------------------------------------
# rules: the incumbent, and the cascade's high-precision keywords mined on TRAIN
# ---------------------------------------------------------------------------

def rule_event(texts):
    from assistant.actions.calendar import categories as _cat
    preds = [_cat.classify(t) for t in texts]
    return preds, np.array([p != DEFAULT_EVENT for p in preds])


def rule_task(texts, palette):
    from assistant.actions.todo import tagging as _tag
    preds = [sorted(_tag.suggest_tags(t, palette)) for t in texts]
    return preds, np.array([bool(p) for p in preds])


def _grams(text: str) -> set:
    w = norm(text).split()
    return set(w) | {" ".join(w[i:i + 2]) for i in range(len(w) - 1)}


def _has(text: str, kw: str) -> bool:
    return re.search(rf"(?<![\w'-]){re.escape(kw)}(?![\w'-])", norm(text)) is not None


def mine_rules(kind, texts, labels, subjects, candidates=None,
               min_rows=RULE_MIN_ROWS, min_subjects=RULE_MIN_SUBJECTS):
    """Keywords right >= RULE_PRECISION of the time on TRAIN, over at least
    RULE_MIN_ROWS rows and RULE_MIN_SUBJECTS distinct subjects (a word seen in
    one subject is that subject memorised, not a rule).

    `candidates=None` mines every word 1-2 gram; otherwise only the given
    keywords are considered (the incumbent's hand-written lists)."""
    rows = collections.defaultdict(list)
    for i, t in enumerate(texts):
        grams = _grams(t) if candidates is None else {k for k in candidates if _has(t, k)}
        for g in grams:
            rows[g].append(i)
    out = {}
    for g, idx in rows.items():
        if len(idx) < min_rows:
            continue
        if len({subjects[i] for i in idx}) < min_subjects:
            continue
        cnt = collections.Counter()
        for i in idx:
            for lab in ([labels[i]] if kind == "event" else labels[i]):
                cnt[lab] += 1
        lab, hit = cnt.most_common(1)[0]
        prec = hit / len(idx)
        if prec >= RULE_PRECISION:
            out[g] = (lab, prec, len(idx), len({subjects[i] for i in idx}))
    # a longer keyword that says the same thing as a shorter one inside it is redundant
    return dict(sorted(out.items(), key=lambda kv: (-kv[1][2], kv[0])))


def apply_rules(rules, texts):
    """(answer or None) per text. Two keywords pointing at different classes is
    not high precision any more — that text goes to the model."""
    short = {k: v for k, v in rules.items() if len(k.split()) <= 2}
    long_ = {k: v for k, v in rules.items() if len(k.split()) > 2}
    out = []
    for t in texts:
        g = _grams(t)
        labs = {v[0] for k, v in short.items() if k in g}
        labs |= {v[0] for k, v in long_.items() if _has(t, k)}
        out.append(labs.pop() if len(labs) == 1 else None)
    return out


def paired(a_right, b_right):
    """McNemar on two methods' per-row correctness over the SAME rows.

    Returns (b, c, exact two-sided p, n needed). `n needed` is the number of
    distinct titles at which the observed difference would reach p < 0.05 with
    80% power, if the discordance and the gap held at the rates seen here —
    the answer to "how many titles would Gil have to label to tell these apart".
    """
    from math import comb, sqrt
    a, bb = np.asarray(a_right, bool), np.asarray(b_right, bool)
    b = int((a & ~bb).sum())
    c = int((~a & bb).sum())
    k, m = min(b, c), b + c
    pval = min(1.0, 2 * sum(comb(m, i) for i in range(k + 1)) / 2 ** m) if m else 1.0
    n = len(a)
    pd, d = m / n, (c - b) / n
    if d == 0:
        return b, c, pval, "never"
    need = ((1.96 * sqrt(pd) + 0.84 * sqrt(max(pd - d * d, 0))) / abs(d)) ** 2
    return b, c, pval, str(int(np.ceil(need)))


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------

def table(title, rows, note=""):
    print(f"\n  {title}")
    if note:
        for line in note.splitlines():
            print(f"    {line}")
    print(f"    {'method':<44}{'n':>6}{'acc':>8}{'mF1':>7}{'cov':>7}{'cw':>7}")
    for name, r in rows:
        print(f"    {name:<44}{r['n']:>6}{r['acc']*100:>7.1f}%{r['mf1']*100:>7.1f}"
              f"{r['cov']*100:>6.1f}%{r['cw']*100:>6.1f}%")


# ---------------------------------------------------------------------------
# the main comparison, per kind
# ---------------------------------------------------------------------------

def run_kind(kind, emb, use_emb, results):
    multilabel = kind == "task"
    tr_x, tr_y, tr_s, te_x, te_y, te_s = load_gen(kind)
    if kind == "event":
        classes = sorted(set(tr_y))
        real = real_event_sets()
        palette = None
    else:
        classes = sorted({c for labs in tr_y for c in labs})
        rt, palette = real_task_rows()
        real = {"todos": [(t, [x for x in tags if x in classes], p) for t, tags, p in rt
                          if [x for x in tags if x in classes]]}
        results.setdefault("task_real_offpalette", [(t, tags, p) for t, tags, p in rt
                                                    if not [x for x in tags if x in classes]])
    print("\n" + "=" * 86)
    print(f"{kind.upper()} — train {len(tr_x)} rows / {len(set(tr_s))} subjects · "
          f"generated TEST {len(te_x)} rows / {len(set(te_s))} unseen subjects · "
          f"subject overlap 0 (asserted)")
    for name, rows in real.items():
        prov = collections.Counter(p for _, _, p in rows)
        print(f"  real set '{name}': {len(rows)} distinct titles · " +
              ", ".join(f"{k} {v}" for k, v in prov.items()))
    print("=" * 86)

    evals = {"gen_test": (te_x, te_y)}
    for name, rows in real.items():
        evals[f"real:{name}"] = ([t for t, _, _ in rows], [l for _, l, _ in rows])
        clean = [(t, l) for t, l, p in rows if "circular" not in p]
        if name != "gold81" and name != "feedback" and clean:
            evals[f"real:{name}:hand-set"] = ([t for t, _ in clean], [l for _, l in clean])

    all_texts = list(tr_x) + list(te_x) + [t for x, _ in evals.values() for t in x]
    have_emb = use_emb and emb is not None
    if have_emb:
        emb.fill(all_texts)

    # --- the incumbent rules and the committed model ---------------------------
    board = collections.defaultdict(list)      # eval -> [(name, score)]
    probas = {}                                 # method -> {eval: P}
    thresholds = {}
    ship_t = 0.35 if kind == "event" else 0.40
    for ev, (x, y) in evals.items():
        preds, ans = rule_event(x) if kind == "event" else rule_task(x, classes)
        board[ev].append(("RULES (incumbent keyword lists)", score(kind, y, preds, ans, classes)))

    from assistant.engine.label.model import LabelModel
    shipped = LabelModel._read(kind, LabelModel.path_for(kind, "base"))

    # --- fit every method on the validation carve (threshold) and on full train
    va_tr, va_va = grouped_carve(tr_s)
    for label, fs, est in METHODS:
        if ("emb" in fs) and not have_emb:
            continue
        if est == "xgb" and not _xgb_available():
            continue
        t0 = time.monotonic()
        try:
            pv = fit_proba(fs, est, [tr_x[i] for i in va_tr], [tr_y[i] for i in va_tr],
                           emb, multilabel, classes)
            Pv = pv([tr_x[i] for i in va_va])
            thr = pick_threshold(kind, Pv, [tr_y[i] for i in va_va], classes)
            pf = fit_proba(fs, est, tr_x, tr_y, emb, multilabel, classes)
        except Exception as e:                   # one method failing must not lose the board
            _log(f"{label}: FAILED — {type(e).__name__}: {e}")
            continue
        thresholds[label] = thr
        probas[label] = {ev: pf(x) for ev, (x, _) in evals.items()}
        _log(f"fitted {label} in {time.monotonic() - t0:.0f}s · threshold {thr:.3f}")

    # the committed artefact must be the first row, refitted — or the board is
    # not measuring what ships
    if shipped is not None and "LR  word+char (shipped)" in probas:
        x = evals["gen_test"][0]
        if kind == "event":
            a = list(shipped.pipeline.predict(x))
            b, _ = decide_event(probas["LR  word+char (shipped)"]["gen_test"], classes, 0.0)
        else:
            a = [sorted(np.array(classes)[r.astype(bool)]) for r in shipped.pipeline.predict(x)]
            b = [sorted(np.array(classes)[r >= 0.5]) for r in probas["LR  word+char (shipped)"]["gen_test"]]
        agree = float(np.mean([list(p) == list(q) for p, q in zip(a, b)]))
        print(f"\n  committed model vs its refit on the same TRAIN rows: {agree*100:.1f}% "
              f"identical predictions on generated TEST")
        results[f"{kind}_shipped_agree"] = agree

    # --- the cascade's rules, mined on TRAIN only -------------------------------
    mined = mine_rules(kind, tr_x, tr_y, tr_s)
    if kind == "event":
        from assistant.actions.calendar import categories as _cat
        cand = sorted({k.lower() for c in _cat.DEFAULTS for k in c["keywords"]})
    else:
        from assistant.actions.todo import tagging as _tag
        cand = sorted({k.lower() for ks in _tag.KEYWORDS.values() for k in ks})
    # a HAND-WRITTEN keyword is not being discovered, only checked, so the
    # subject-diversity bar (which exists to stop a mined n-gram memorising one
    # subject) does not apply; it needs 10 train rows of evidence instead
    kept_incumbent = mine_rules(kind, tr_x, tr_y, tr_s, candidates=cand,
                                min_rows=INCUMBENT_MIN_ROWS, min_subjects=1)
    results[f"{kind}_rules_mined"] = mined
    results[f"{kind}_rules_incumbent_kept"] = kept_incumbent
    results[f"{kind}_incumbent_candidates"] = len(cand)

    def cascade(rules, model_label, ev, x, abstain=True):
        r = apply_rules(rules, x)
        P = probas[model_label][ev]
        t = thresholds[model_label] if abstain else (0.0 if kind == "event" else None)
        if kind == "event":
            mp, ma = decide_event(P, classes, t)
            preds = [a if a is not None else m for a, m in zip(r, mp)]
        else:
            mp, ma = decide_task(P, classes, t)
            preds = [[a] if a is not None else m for a, m in zip(r, mp)]
        ans = np.array([a is not None or m for a, m in zip(r, ma)])
        fired = np.array([a is not None for a in r])
        return preds, ans, fired

    # --- score everything on every evaluation -----------------------------------
    for ev, (x, y) in evals.items():
        for label in probas:
            P = probas[label][ev]
            dec = decide_event if kind == "event" else decide_task
            p0, a0 = dec(P, classes, 0.0 if kind == "event" else None)
            board[ev].append((f"{label}", score(kind, y, p0, a0, classes)))
            p1, a1 = dec(P, classes, thresholds[label])
            board[ev].append((f"  + abstain @{thresholds[label]:.2f}", score(kind, y, p1, a1, classes)))
        # the shipped STACKED path: incumbent rules first, the shipped model where they
        # fell through, the default where the model is under its shipped threshold
        # ... and the same stacking with each OTHER model behind the rules, at the
        # same shipped threshold: the question "keep the shape, swap the model"
        rp, ra = rule_event(x) if kind == "event" else rule_task(x, classes)
        for base in [m for m in STACK_BEHIND_RULES if m in probas]:
            mp, ma = (decide_event if kind == "event" else decide_task)(probas[base][ev], classes, ship_t)
            sp = [r if a else m for r, a, m in zip(rp, ra, mp)]
            sa = ra | ma
            name = ("STACKED (shipped: rules -> LR @%.2f)" % ship_t
                    if base == "LR  word+char (shipped)" else f"STACKED rules -> {base.strip()}")
            board[ev].append((name, score(kind, y, sp, sa, classes)))
        for mlabel in [m for m in ("LR  word+char (shipped)", "LR  embedding",
                                   "LR  word+char+embedding") if m in probas]:
            for (rname, rules), abst in [(r, a) for r in (("mined kw", mined),
                                                           ("incumbent kw>=95%", kept_incumbent))
                                         for a in (False, True)]:
                cp, ca, fired = cascade(rules, mlabel, ev, x, abstain=abst)
                s = score(kind, y, cp, ca, classes)
                # how many rows the rules answered, and how right they were there
                if fired.any():
                    ok = [(p == g if kind == "event" else sorted(p) == sorted(g))
                          for p, g, f in zip(cp, y, fired) if f]
                    s["rule_rows"], s["rule_acc"] = int(fired.sum()), float(np.mean(ok))
                else:
                    s["rule_rows"], s["rule_acc"] = 0, 0.0
                short = {"LR  word+char (shipped)": "LR w+c", "LR  embedding": "LR emb",
                         "LR  word+char+embedding": "LR w+c+emb"}[mlabel]
                board[ev].append((f"CASCADE {rname} -> {short}" + (" +abst" if abst else ""), s))

    for ev, rows in board.items():
        n_titles = len(set(norm(t) for t in evals[ev][0]))
        note = (f"{ev}: {len(evals[ev][0])} rows, {n_titles} distinct titles"
                + (f", {len(set(te_s))} distinct subjects" if ev == "gen_test" else ""))
        table(f"{kind.upper()} · {ev}", rows, note)
        casc = [(n, r) for n, r in rows if n.startswith("CASCADE")]
        for n, r in casc:
            print(f"      {n:<44} rules answered {r['rule_rows']} rows at "
                  f"{r['rule_acc']*100:.1f}% accuracy")
    # PAIRED against the incumbent on the real sets: which rows flip, is the
    # difference more than noise, and how many titles would separate them
    for ev in [e for e in evals if e.startswith("real:")]:
        rows = dict(board[ev])
        inc = next((r for n, r in board[ev] if n.startswith("STACKED (shipped")), None)
        if inc is None or len(evals[ev][0]) < 20:
            continue
        print(f"\n  PAIRED vs the shipped STACKED path on {ev} "
              f"(b = incumbent right & method wrong, c = the reverse)")
        print(f"    {'method':<44}{'b':>4}{'c':>4}{'exact p':>9}{'n to separate':>15}")
        for name, r in board[ev]:
            if name.startswith("STACKED (shipped") or name.startswith("  +"):
                continue
            b, c, pval, need = paired(inc["right"], r["right"])
            print(f"    {name:<44}{b:>4}{c:>4}{pval:>9.3f}{need:>15}")
            r["paired"] = {"b": b, "c": c, "p": pval, "n_needed": need}

    # the clean real rows are few enough to read one by one
    for ev, (x, y) in evals.items():
        if not (ev.endswith(":hand-set") or ev.endswith(":feedback")):
            continue
        show = [m for m in ("LR  word+char (shipped)", "LR  embedding", "XGB word+char (sparse)")
                if m in probas]
        rp, _ = rule_event(x) if kind == "event" else rule_task(x, classes)
        print(f"\n  {ev} row by row — gold | rules | " + " | ".join(m.strip() for m in show))
        for i, (t, g) in enumerate(zip(x, y)):
            cells = []
            for m in show:
                P = probas[m][ev][i:i + 1]
                if kind == "event":
                    cells.append(decide_event(P, classes, 0.0)[0][0])
                else:
                    cells.append(",".join(decide_task(P, classes, None)[0][0]))
            print(f"    {t[:38]:<40}{str(g):<16}{str(rp[i]):<16}" + "".join(f"{c:<16}" for c in cells))
    results[f"{kind}_board"] = {ev: rows for ev, rows in board.items()}
    results[f"{kind}_thresholds"] = thresholds
    results[f"{kind}_probas"] = probas          # kept in memory for the new-tag pass
    results[f"{kind}_classes"] = classes
    results[f"{kind}_evals"] = evals

    print(f"\n  CASCADE RULES mined on {kind.upper()} TRAIN (>= {RULE_PRECISION:.0%} precise, "
          f">= {RULE_MIN_ROWS} rows, >= {RULE_MIN_SUBJECTS} subjects): {len(mined)} keywords")
    for k, (lab, p, n, ns) in list(mined.items())[:40]:
        print(f"      {k!r:<26} -> {lab:<12} {p*100:5.1f}%  {n:4d} rows  {ns:3d} subjects")
    print(f"  INCUMBENT keywords at >= {RULE_PRECISION:.0%} on TRAIN (>= {INCUMBENT_MIN_ROWS} rows): "
          f"{len(kept_incumbent)} of {len(cand)} "
          f"({sum(1 for k in cand if sum(_has(t, k) for t in tr_x) < INCUMBENT_MIN_ROWS)} "
          f"have too little train evidence to be judged)")
    for k, (lab, p, n, ns) in list(kept_incumbent.items())[:40]:
        print(f"      {k!r:<26} -> {lab:<12} {p*100:5.1f}%  {n:4d} rows  {ns:3d} subjects")

    # Gil's own examples, read directly
    probe = ["buy", "grab", "pick up", "get", "gym", "run", "workout", "book", "call"]
    print(f"\n  Gil's example words on {kind.upper()} TRAIN (rows containing the word -> best class):")
    for w in probe:
        idx = [i for i, t in enumerate(tr_x) if _has(t, w)]
        if not idx:
            print(f"      {w!r:<10} absent from train")
            continue
        c = collections.Counter(l for i in idx for l in ([tr_y[i]] if kind == "event" else tr_y[i]))
        lab, hit = c.most_common(1)[0]
        print(f"      {w!r:<10} {len(idx):4d} rows · {len({tr_s[i] for i in idx}):3d} subjects · "
              f"best {lab} {hit/len(idx)*100:5.1f}%")
    if kind == "task":
        rt = real.get("todos", [])
        for w in ("buy", "pick up", "get"):
            idx = [(t, l) for t, l, _ in rt if _has(t, w)]
            if idx:
                c = collections.Counter(x for _, l in idx for x in l)
                lab, hit = c.most_common(1)[0]
                print(f"      REAL to-dos: {w!r:<8} {len(idx)} distinct titles · best {lab} "
                      f"{hit}/{len(idx)} (probe — real rows are never used to choose a rule)")


# ---------------------------------------------------------------------------
# NEW TAGS — a class with no training rows, known only by name + 3 keywords
# ---------------------------------------------------------------------------

def _new_class_keywords(kind, c):
    if kind == "event":
        from assistant.actions.calendar import categories as _cat
        kws = next(x["keywords"] for x in _cat.DEFAULTS if x["name"] == c)
    else:
        from assistant.actions.todo import tagging as _tag
        kws = _tag.KEYWORDS[c]
    return [k for k in kws if k.lower() != c.lower()][:3]


def run_newtag(kind, emb, use_emb, results):
    """Hold one class out of TRAINING entirely; give the system its name and
    three keywords (the first three of its incumbent list — what a user creating
    it would plausibly type); score recall and precision on that class's TEST rows.

    Methods:
      rules name+3kw   the class's keyword list cut to its name + 3 keywords
      rules name only  what tagging.py does today for a user-created tag
      LR w/o class     the trained model has never heard of it: recall 0 by
                       construction, shown so nobody has to assume it
      cascade          name+3kw keyword rule first, the LR (w/o class) after
      embed proto      title vs "name: kw1, kw2, kw3" by cosine; the class is
                       answered when its prototype is the nearest of all the
                       classes' prototypes by a margin, the margin chosen on
                       the OTHER classes' TRAIN rows (max mean F1) — never on
                       the held-out class
      proto | rules    either of the two fires
    """
    multilabel = kind == "task"
    tr_x, tr_y, tr_s, te_x, te_y, te_s = load_gen(kind)
    if kind == "event":
        classes = sorted(set(tr_y) - {DEFAULT_EVENT})
        allc = sorted(set(tr_y))
    else:
        classes = sorted({c for labs in tr_y for c in labs})
        allc = classes
    has = (lambda y, c: y == c) if kind == "event" else (lambda y, c: c in y)
    if use_emb and emb is not None:
        emb.fill(tr_x + te_x)
    have_emb = use_emb and emb is not None and emb.ready(tr_x + te_x)
    if have_emb:
        Etr, Ete = emb.matrix(tr_x), emb.matrix(te_x)
        proto_txt = {c: f"{c}: " + ", ".join(_new_class_keywords(kind, c)) if c != DEFAULT_EVENT
                     else "personal" for c in allc}
        emb.fill(list(proto_txt.values()))
        PR = emb.matrix([proto_txt[c] for c in allc])
        Str, Ste = Etr @ PR.T, Ete @ PR.T

    def proto_rule(S, ci, m):
        order = np.argsort(-S, axis=1)
        top, second = order[:, 0], order[:, 1]
        margin = S[np.arange(len(S)), top] - S[np.arange(len(S)), second]
        return (top == ci) & (margin >= m)

    out = []
    print("\n" + "=" * 86)
    print(f"NEW {'CATEGORY' if kind == 'event' else 'TAG'} — one class held out of training, "
          f"known by name + 3 keywords")
    print("=" * 86)
    print(f"    {'held out':<14}{'kw given':<34}{'test n':>7}  "
          + "".join(f"{m:>18}" for m in ("rules name+3kw", "rules name only",
                                            "embed proto", "proto|rules")))
    print(f"    {'':<14}{'':<34}{'':>7}  " + "".join(f"{'R / P':>18}" for _ in range(4)))
    for c in classes:
        kws = _new_class_keywords(kind, c)
        keep = [i for i, y in enumerate(tr_y) if not has(y, c)]
        gold = np.array([has(y, c) for y in te_y])
        n_pos = int(gold.sum())
        rp = {}

        def rp_of(pred):
            pred = np.asarray(pred, bool)
            tp = int((pred & gold).sum())
            return (tp / n_pos if n_pos else 0.0, tp / pred.sum() if pred.sum() else 0.0,
                    int(pred.sum()))

        r_kw = np.array([any(_has(t, k) for k in [c.lower()] + [k.lower() for k in kws]) for t in te_x])
        r_nm = np.array([_has(t, c.lower()) for t in te_x])
        rp["rules name+3kw"] = rp_of(r_kw)
        rp["rules name only"] = rp_of(r_nm)
        if have_emb:
            others = [k for k in allc if k != c and k != DEFAULT_EVENT]
            ks = [allc.index(k) for k in others]
            best_m, best_f = 0.0, -1.0
            for m in np.arange(0.0, 0.2, 0.005):
                f1s = []
                for k, ki in zip(others, ks):
                    pr = proto_rule(Str[keep], ki, m)
                    g = np.array([has(tr_y[i], k) for i in keep])
                    tp = (pr & g).sum()
                    p_ = tp / pr.sum() if pr.sum() else 0
                    r_ = tp / g.sum() if g.sum() else 0
                    f1s.append(2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0)
                if np.mean(f1s) > best_f:
                    best_m, best_f = float(m), float(np.mean(f1s))
            pe = proto_rule(Ste, allc.index(c), best_m)
            rp["embed proto"] = rp_of(pe)
            rp["proto|rules"] = rp_of(pe | r_kw)
        row = {"class": c, "keywords": kws, "test_n": n_pos, **{k: v for k, v in rp.items()}}
        out.append(row)
        cells = []
        for m in ("rules name+3kw", "rules name only", "embed proto", "proto|rules"):
            v = rp.get(m)
            cells.append(f"{v[0]*100:6.1f} /{v[1]*100:6.1f}" if v else f"{'—':>13}")
        print(f"    {c:<14}{', '.join(kws)[:32]:<34}{n_pos:>7}  " + "".join(f"{x:>18}" for x in cells))
    if out:
        def mean(m, j):
            vals = [r[m][j] for r in out if m in r]
            return np.mean(vals) * 100 if vals else float("nan")
        print(f"    {'MEAN':<14}{'':<34}{'':>7}  " + "".join(
            f"{mean(m, 0):6.1f} /{mean(m, 1):6.1f}".rjust(18)
            for m in ("rules name+3kw", "rules name only", "embed proto", "proto|rules")))
    print("    LR / HGB / XGB trained without the class: recall 0.0 on every row above, "
          "by construction —\n    a closed-set classifier cannot name a class it was never "
          "fitted on. Gil's cascade\n    (keyword rule first, model after) scores exactly the "
          "'rules name+3kw' column for the new class.")
    results[f"{kind}_newtag"] = out

    # day-one: the whole palette as prototypes, no training rows at all
    if have_emb:
        pred = [allc[i] for i in Ste.argmax(1)]
        if kind == "event":
            acc = float(np.mean([p == g for p, g in zip(pred, te_y)]))
        else:
            acc = float(np.mean([[p] == sorted(g) for p, g in zip(pred, te_y)]))
        print(f"\n    ZERO-SHOT (every class as name+3kw prototypes, nearest wins, no training "
              f"rows): generated TEST acc {acc*100:.1f}% on {len(te_y)} rows")
        results[f"{kind}_zeroshot_acc"] = acc

    # the real custom tag: Wishlist on Gil's list
    if kind == "task":
        off = results.get("task_real_offpalette") or []
        wl = [(t, tags) for t, tags, _ in off if "Wishlist" in tags]
        if wl:
            print(f"\n    REAL new tag 'Wishlist' — {len(wl)} distinct titles on Gil's list "
                  f"(user-created, no keywords, no training rows):")
            nm = sum(_has(t, "wishlist") for t, _ in wl)
            print(f"      rules (name in title): {nm}/{len(wl)} found")
            if use_emb and emb is not None:
                emb.fill([t for t, _ in wl] + ["Wishlist"])
                W = emb.matrix([t for t, _ in wl])
                allp = emb.matrix(["Wishlist"] + [f"{c}: " + ", ".join(_new_class_keywords(kind, c))
                                                  for c in classes])
                S = W @ allp.T
                print(f"      embed proto (name only vs the 4 built-in prototypes): "
                      f"{int((S.argmax(1) == 0).sum())}/{len(wl)} nearest to 'Wishlist'")
                for (t, _), s in zip(wl, S):
                    print(f"        {t[:44]:<46} nearest "
                          f"{(['Wishlist'] + classes)[int(s.argmax())]:<11} sim {s.max():.3f}")


# ---------------------------------------------------------------------------
# THE SHIPPED PATH — the committed artefacts, through model.category_for / tags_for
# ---------------------------------------------------------------------------

def run_shipped(kind, results):
    """The committed base artefact, through the REAL entry points (rules first,
    the embedding head, the n-gram fallback, the live-palette filter), on the
    same rows as the comparison above. Three rows:

      shipped           the artefact as committed, at its TRAIN-chosen threshold
      reproduction      the same artefact at Board 6's stacked thresholds
                        (0.35 / 0.40) — must equal the board's own refit row
      fallback          MACALENDAR_LLM_DISABLED=1, so no vector can be had —
                        must equal the pre-Q46 STACKED (shipped) row
    """
    from types import SimpleNamespace
    from assistant.engine.label import embed as _embed
    from assistant.engine.label import model as _lm
    from assistant.engine.label.model import LabelModel
    _embed.LRU_SIZE = 50000                  # the board warms thousands of titles at once
    art = LabelModel._read(kind, LabelModel.path_for(kind, "base"))
    if art is None or art.embed_head is None:
        print(f"\n  SHIPPED ({kind}): the committed artefact has no embedding head — skipped")
        return
    _lm._CACHE[kind] = art
    cfg = SimpleNamespace(labels=SimpleNamespace(model_event=True, model_task=True, model_first=False),
                          ollama=SimpleNamespace(base_url=None))
    classes = results[f"{kind}_classes"]
    evals = results[f"{kind}_evals"]
    board = results[f"{kind}_board"]
    chosen = art.embed_head.threshold
    ship_t = 0.35 if kind == "event" else 0.40
    ref = ("STACKED rules -> LR  word+char+embedding" if kind == "event"
           else "STACKED rules -> LR  embedding")
    print("\n" + "=" * 86)
    print(f"SHIPPED {kind.upper()} — committed artefact · embedding head threshold {chosen} "
          f"({art.meta.get('embed', {}).get('threshold_rule', '')})")
    print("=" * 86)
    out = {}

    def run(x, y):
        if kind == "event":
            rp, _ = rule_event(x)
            got = [_lm.category_for(t, r, cfg) for t, r in zip(x, rp)]
            preds = [g for g, _ in got]
            ans = np.array([p != DEFAULT_EVENT for p in preds])
        else:
            rp, _ = rule_task(x, classes)
            got = [_lm.tags_for(t, r, cfg) for t, r in zip(x, rp)]
            preds = [sorted(g) for g, _ in got]
            ans = np.array([bool(p) for p in preds])
        src = collections.Counter(w for _, w in got)
        return score(kind, y, preds, ans, classes), src

    for ev, (x, y) in evals.items():
        art.warm(x)
        rows = []
        art.embed_head.threshold = chosen
        s1, src = run(x, y)
        rows.append((f"SHIPPED (rules -> embed head @{chosen})", s1))
        art.embed_head.threshold = ship_t
        s2, _ = run(x, y)
        rows.append((f"reproduction (@{ship_t})", s2))
        art.embed_head.threshold = chosen
        prev = os.environ.get("MACALENDAR_LLM_DISABLED")
        os.environ["MACALENDAR_LLM_DISABLED"] = "1"
        s3, _ = run(x, y)
        if prev is None:
            os.environ.pop("MACALENDAR_LLM_DISABLED", None)
        else:
            os.environ["MACALENDAR_LLM_DISABLED"] = prev
        rows.append(("fallback (embedding disabled)", s3))
        board_ref = dict(board[ev]).get(ref)
        board_inc = next((r for n, r in board[ev] if n.startswith("STACKED (shipped")), None)
        table(f"{kind.upper()} · {ev} · who answered: {dict(src)}", rows)
        if board_ref:
            ok = board_ref["right"] == s2["right"]
            print(f"    reproduction == board row '{ref.strip()}': {ok} "
                  f"({board_ref['acc']*100:.1f}% vs {s2['acc']*100:.1f}%)")
        if board_inc:
            ok = board_inc["right"] == s3["right"]
            print(f"    fallback == pre-Q46 STACKED (shipped): {ok} "
                  f"({board_inc['acc']*100:.1f}% vs {s3['acc']*100:.1f}%)")
            if len(x) >= 20:
                b, c, pv, need = paired(board_inc["right"], s1["right"])
                print(f"    shipped vs pre-Q46 incumbent, paired: {b} lost, {c} gained, "
                      f"exact p {pv:.3f}, n to separate {need}")
        out[ev] = {n: {k: v for k, v in r.items() if k != "right"} for n, r in rows}
    results[f"{kind}_shipped"] = out
    _lm.reset()


# ---------------------------------------------------------------------------
# PALETTE DRIFT — what happens today when a tag or category is renamed/deleted
# ---------------------------------------------------------------------------

def run_palette():
    from types import SimpleNamespace
    from assistant.engine.label import model as _lm
    from assistant.actions.calendar import categories as _cat
    from assistant.actions.todo import tagging as _tag
    cfg = SimpleNamespace(labels=SimpleNamespace(model_event=True, model_task=True, model_first=False))
    print("\n" + "=" * 86)
    print("PALETTE DRIFT — a class the user deleted or renamed, against the saved models")
    print("=" * 86)
    em = _lm._cached("event")
    tm = _lm._cached("task")
    print(f"  saved event model classes ({len(em.classes)}): {', '.join(em.classes)}")
    print(f"  saved task model classes  ({len(tm.classes)}): {', '.join(tm.classes)}")

    # delete 'Travel' in the scratch categories store and run the shipped event path
    _cat.remove("Travel")
    live = [c["name"] for c in _cat.all_categories()]
    t = "flight to rome"
    rule = _cat.classify(t)
    got, who = _lm.category_for(t, rule, cfg)
    print(f"\n  EVENTS: 'Travel' deleted -> palette {len(live)} categories; "
          f"'{t}': rules say {rule!r}, shipped path answers {got!r} ({who})")
    print(f"    colour for {got!r}: {_cat.color_for(got)[0]} "
          f"(Personal is {_cat.color_for('Personal')[0]}) — the label outlives its category")
    # rename Errand -> Chores
    _cat.remove("Errand")
    _cat.upsert("Chores", color="#123456", keywords=["chores"])
    t2 = "drop off the dry cleaning"
    rule2 = _cat.classify(t2)
    got2, who2 = _lm.category_for(t2, rule2, cfg)
    print(f"  EVENTS: 'Errand' renamed 'Chores' -> '{t2}': rules say {rule2!r}, "
          f"shipped path answers {got2!r} ({who2})")

    # tasks: the action's own sequence — suggest_tags over the palette, then tags_for
    palette = ["Coursework", "Groceries", "Work", "Personal"]          # Errands deleted
    t3 = "collect the passport photos"
    rule3 = _tag.suggest_tags(t3, palette)
    got3, who3 = _lm.tags_for(t3, rule3, cfg)
    print(f"\n  TASKS: 'Errands' deleted -> '{t3}': rules say {rule3}, "
          f"shipped path answers {got3} ({who3}) — "
          f"{'NOT in the palette' if set(got3) - set(palette) else 'in the palette'}")
    t4 = "check the new bike light"
    got4 = tm.predict_tags(t4)
    print(f"  TASKS: user-created 'Wishlist' -> '{t4}': the model can only answer "
          f"{tm.classes}; it said {got4}")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embed", action="store_true", help="make no ollama call")
    ap.add_argument("--only", choices=("events", "tasks", "newtag", "palette", "shipped"))
    ap.add_argument("--embed-cache", default=str(EMBED_CACHE))
    ap.add_argument("--out", default=None, help="write the numbers as JSON here")
    a = ap.parse_args()
    use_emb = not a.no_embed
    emb = Embedder(pathlib.Path(a.embed_cache), enabled=use_emb)
    print(f"\nLABEL REBUILD BOARD · {time.strftime('%Y-%m-%d %H:%M:%S')} · "
          f"xgboost {'available' if _xgb_available() else 'NOT available'} · "
          f"embeddings {'on' if use_emb else 'off'} · scratch {_S}")
    try:
        import subprocess
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, cwd=STAGE).stdout.strip()
        print(f"  commit {sha}")
    except Exception:
        sha = ""
    results: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "commit": sha}
    if a.only in (None, "events", "shipped"):
        run_kind("event", emb, use_emb, results)
        if use_emb:
            run_shipped("event", results)
    if a.only in (None, "tasks", "shipped"):
        run_kind("task", emb, use_emb, results)
        if use_emb:
            run_shipped("task", results)
    if a.only in (None, "newtag") and a.only != "shipped":
        run_newtag("event", emb, use_emb, results)
        if "task_real_offpalette" not in results:
            rt, _ = real_task_rows()
            from assistant.actions.todo import tagging as _tag
            trained = {"Coursework", "Errands", "Groceries", "Work"}
            results["task_real_offpalette"] = [(t, tags, p) for t, tags, p in rt
                                               if not [x for x in tags if x in trained]]
        run_newtag("task", emb, use_emb, results)
    if a.only in (None, "palette"):
        run_palette()
    results["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if a.out:
        keep = {k: v for k, v in results.items()
                if not k.endswith(("_probas", "_evals"))}
        for k in [k for k in keep if k.endswith("_board")]:
            keep[k] = {ev: [(n, {x: y for x, y in r.items() if x != "right"}) for n, r in rows]
                       for ev, rows in keep[k].items()}
        pathlib.Path(a.out).write_text(json.dumps(keep, indent=1, default=str))
        print(f"\n  numbers -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
