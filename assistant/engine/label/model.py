"""The learned labellers — event category and task tags — and how they ship.

    LabelModel.load("event") -> predict(title) -> (label, confidence) | None
    LabelModel.load("task")  -> predict_tags(title) -> ([tags], confidence) | None

Each artefact holds TWO classifiers (DEVQA Q46, 2026-09-24): an EMBEDDING HEAD
(`EmbedHead`, reading the title's nomic-embed-text vector through `embed.py`)
that answers whenever the vector can be had, and the n-gram PIPELINE that
shipped before it, which answers whenever it cannot. See ARCHITECTURE.md.

Trained by `train.py`, and stored in TWO places on purpose — this line used to
say "never in the repo", which contradicted `BASE_DIR` below and would have had
someone delete the shipped model:

    assistant/engine/label/models/   the BASE tier — generic, identical for
                                     everyone, COMMITTED, so a new user gets a
                                     model on day one instead of the keyword
                                     rules for ever
    ~/.assistant_tools/models/       the PERSONAL tier — fitted on this user's
                                     own corrections, never in the repo

`experiments/RESULTS.md` carries the numbers that justify shipping them:
on held-out VOCABULARY the event model beats the keyword rules 49.1% to 33.0%
accuracy, and the task model beats them 95.7% to 88.6% exact-set on Gil's own
tagged todos.

## They do NOT replace the rules. They stack behind them.

The measured shapes are complementary, and that is the whole design:

    RULES   macro precision 91.7%, recall 34.9%   (task tags, novel vocabulary)
    MODEL   precision 63.9%,       recall 39.8%

A keyword match is nearly always right when it fires and rarely fires. So the
rules go FIRST and keep their precision; the model answers only where they
abstained; and where the model is not confident either, the answer is the
existing catch-all. That is a selective classifier — the same shape FastRule's
front door already uses — and it is strictly better than either component alone.

Replacing the rules with the model would trade 91.7% precision for 63.9% on
every row the rules already got right, which no accuracy number justifies.

## Abstention is a first-class answer

`predict` returns None below `MIN_CONFIDENCE` rather than guessing. An event
labelled `Personal` because nothing was confident is honest; an event labelled
`Travel` at 0.21 because that was the argmax is not, and it is worse than the
keyword rules it replaced. The threshold is a dial the board sweeps, not a
constant somebody picked.
"""
from __future__ import annotations

import os
import pathlib

import numpy as np

#: TWO TIERS, and the distinction is the whole shape of this (Gil, 2026-09-10:
#: *"this should also be true for other users — i am just one example of a user
#: that automatic retraining happens for"*).
#:
#:   BASE      identical for every user. Fitted from the COMMITTED datasets,
#:             which are authored generic vocabulary and contain nobody's data.
#:             Built once, on first use if it is missing, so a brand-new user
#:             gets a working classifier on day one rather than after they have
#:             corrected twenty-five things.
#:
#:   PERSONAL  base + THIS user's corrections, upweighted and gated. Lives in
#:             the user's own directory, is never shipped, and never leaves the
#:             machine.
#:
#: `load()` prefers personal and falls back to base, so the tiers degrade in the
#: right order: your model, then everyone's model, then the keyword rules.
#: Before this there was one tier and a new user silently got the rules for ever
#: — the model existed only for whoever had run the trainer.
BASE_DIR = pathlib.Path(__file__).resolve().parent / "models"

MODELS_DIR = pathlib.Path(
    os.environ.get("MACALENDAR_MODELS")
    or os.path.expanduser("~/.assistant_tools/models"))

#: Below this the model says nothing and the caller falls back. Swept by
#: `experiments/threshold_sweep.py`; a value nobody swept is an assumption.
MIN_CONFIDENCE = {"event": 0.35, "task": 0.40}


class EmbedHead:
    """The EMBEDDING classifier that sits beside the n-gram pipeline (DEVQA Q46).

    events  logistic regression on word 1-2 grams + char 3-5 grams + the
            nomic-embed-text vector of the title (label Board 6's best stacked
            event row)
    tasks   one-vs-rest logistic regression on the vector alone

    `threshold` was chosen on the TRAIN half (`train._fit_embed`), never on a
    test row, and is recorded in the artefact's meta beside how it was chosen.
    The n-gram pipeline is kept whole: it answers whenever the vector cannot be
    had, exactly as it did before this head existed.
    """

    def __init__(self, kind: str, clf, classes, threshold: float, vec=None) -> None:
        self.kind = kind
        self.clf = clf
        self.classes = list(classes)
        self.threshold = float(threshold)
        self.vec = vec              # the n-gram vectoriser for events; None for tasks

    def features(self, texts, E):
        if self.vec is None:
            return np.asarray(E)
        import scipy.sparse as sp
        return sp.hstack([self.vec.transform(list(texts)), sp.csr_matrix(np.asarray(E))]).tocsr()

    def proba(self, texts, E) -> "np.ndarray":
        """Probabilities over `self.classes`, one row per text."""
        P = np.asarray(self.clf.predict_proba(self.features(texts, E)))
        if self.kind == "event":
            out = np.zeros((P.shape[0], len(self.classes)))
            out[:, [int(c) for c in self.clf.classes_]] = P
            return out
        return P


class LabelModel:
    """A fitted classifier plus the metadata needed to trust it."""

    __slots__ = ("kind", "pipeline", "classes", "meta", "embed_head", "last_source")

    def __init__(self, kind: str, pipeline, classes, meta: dict,
                 embed_head: "EmbedHead | None" = None) -> None:
        self.kind = kind            # "event" | "task"
        self.pipeline = pipeline
        self.classes = list(classes)
        self.meta = dict(meta)      # trained_at, n_rows, board numbers, version
        self.embed_head = embed_head   # None: an artefact from before Q46, n-grams only
        self.last_source = None        # "embed" | "ngram" — which head answered last

    # -- loading ------------------------------------------------------------

    @classmethod
    def path_for(cls, kind: str, tier: str = "personal") -> pathlib.Path:
        root = MODELS_DIR if tier == "personal" else BASE_DIR
        return root / f"{kind}_label.joblib"

    @classmethod
    def _read(cls, kind: str, path: pathlib.Path) -> "LabelModel | None":
        if not path.exists():
            return None
        try:
            import joblib
            blob = joblib.load(path)
            m = cls(kind, blob["pipeline"], blob["classes"], blob.get("meta", {}),
                    blob.get("embed"))
            m.meta.setdefault("tier", "personal")
            return m
        except Exception:
            return None            # corrupt or version-skewed: fall back a tier

    @classmethod
    def load(cls, kind: str) -> "LabelModel | None":
        """This user's model, else everyone's, else None.

        The order matters and is the point of having two tiers: a user who has
        corrected things gets a model fitted on their words; a user who has
        corrected nothing still gets a working classifier instead of waiting
        twenty-five corrections for one to exist. None — meaning fall back to
        the keyword rules — is reached only when neither tier is present, which
        on a healthy install means the base was never built.

        A missing model is never an error and never logs: it is the ordinary
        state before first use, and the caller's fallback IS today's behaviour.
        """
        return (cls._read(kind, cls.path_for(kind, "personal"))
                or cls._read(kind, cls.path_for(kind, "base")))

    def save(self, tier: str = "personal") -> pathlib.Path:
        """Write the artefact. `tier="base"` writes the shipped, user-agnostic
        one; anything else writes this user's."""
        import joblib
        p = self.path_for(self.kind, tier)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.meta["tier"] = tier
        joblib.dump({"pipeline": self.pipeline, "classes": self.classes,
                     "embed": self.embed_head,
                     "meta": self.meta}, p)
        return p

    # -- prediction ---------------------------------------------------------

    def _embedded(self, text: str, base_url: "str | None"):
        """The embedding head's probabilities for one title, or None when the
        vector cannot be had (disabled, ollama down or slow) or the head fails.
        None sends the caller to the n-gram pipeline, exactly as before Q46."""
        if self.embed_head is None:
            return None
        from assistant.engine.label import embed as _embed
        v = _embed.vector(text, base_url=base_url)
        if v is None:
            return None
        try:
            return self.embed_head.proba([text], v[None, :])[0]
        except Exception:
            return None

    def warm(self, texts, base_url: "str | None" = None) -> None:
        """Embed many titles in ONE batched call, filling the in-process cache,
        so a caller about to `predict` each of them (the teach queue) does not
        pay one round trip per title."""
        if self.embed_head is None:
            return
        from assistant.engine.label import embed as _embed
        _embed.vectors([t for t in texts if (t or "").strip()], base_url=base_url)

    def predict(self, text: str, base_url: "str | None" = None) -> "tuple[str, float] | None":
        """Single-label. `(label, confidence)`, or None when not confident.

        The embedding head answers when its vector can be had — and when it
        ABSTAINS, that is the answer (the rules stand); the n-gram pipeline is
        the fallback for a missing vector, not a second opinion."""
        if not (text or "").strip():
            return None
        P = self._embedded(text, base_url)
        if P is not None:
            self.last_source = "embed"
            best = int(np.argmax(P))
            conf = float(P[best])
            if conf < self.embed_head.threshold:
                return None
            return str(self.embed_head.classes[best]), conf
        self.last_source = "ngram"
        try:
            proba = self.pipeline.predict_proba([text])[0]
        except Exception:
            return None
        best = max(range(len(proba)), key=lambda i: proba[i])
        conf = float(proba[best])
        if conf < MIN_CONFIDENCE.get(self.kind, 0.4):
            return None
        return str(self.pipeline.classes_[best]), conf

    def predict_tags(self, text: str, base_url: "str | None" = None) -> "tuple[list, float] | None":
        """Multi-label. Every tag over the bar, plus the weakest one's score.

        A task can be Groceries AND Errands, so this is one-vs-rest and the
        answer is a SET. Returning the argmax alone would silently drop the
        second tag, which is the behaviour `suggest_tags` already avoids.
        """
        if not (text or "").strip():
            return None
        P = self._embedded(text, base_url)
        if P is not None:
            self.last_source = "embed"
            bar = self.embed_head.threshold
            picked = [(self.embed_head.classes[i], float(sc)) for i, sc in enumerate(P) if sc >= bar]
            if not picked:
                return None
            return [name for name, _ in picked], min(sc for _, sc in picked)
        self.last_source = "ngram"
        bar = MIN_CONFIDENCE.get(self.kind, 0.4)
        try:
            scores = []
            for i, est in enumerate(self.pipeline.named_steps["clf"].estimators_):
                feats = self.pipeline.named_steps["feat"].transform([text])
                scores.append(float(est.predict_proba(feats)[0][1]))
        except Exception:
            return None
        picked = [(self.classes[i], sc) for i, sc in enumerate(scores) if sc >= bar]
        if not picked:
            return None
        return [name for name, _ in picked], min(sc for _, sc in picked)


# ---------------------------------------------------------------------------
# The shipped entry points — rules first, model second, catch-all last
# ---------------------------------------------------------------------------

_CACHE: dict = {}


def _cached(kind: str) -> "LabelModel | None":
    """One load per process. `reset()` clears it; tests and the retrainer use
    that rather than reaching into the dict.

    BUILDS THE BASE MODEL IF IT IS MISSING, once, and only when the feature is
    switched on. Without this a brand-new user gets the keyword rules for ever:
    the artefact only ever existed for whoever had run the trainer by hand,
    which made "the model" a property of one machine rather than of the product.

    The build is deterministic — same committed datasets, same seed, same
    result on every machine — so it is a cache-fill, not a training run whose
    outcome anyone needs to check. It takes a few seconds, happens at most once,
    and any failure falls back to the rules rather than surfacing.
    """
    if kind not in _CACHE:
        got = LabelModel.load(kind)
        if got is None:
            got = _build_base(kind)
        _CACHE[kind] = got
    return _CACHE[kind]


def _build_base(kind: str) -> "LabelModel | None":
    """Fit the user-agnostic model from the committed datasets. Never personal:
    `feedback.gold()` is not consulted, so this is identical for every user."""
    try:
        from assistant.engine.label import train as _train
        # n-grams only: a first-use build must not embed ~12,000 rows inside a
        # commit. The committed base artefact carries the embedding head.
        out = _train.train_base(kind, verbose=False, embed=False)
        return LabelModel.load(kind) if out else None
    except Exception:
        return None


def reset() -> None:
    _CACHE.clear()


def enabled(cfg, kind: str) -> bool:
    """Off unless switched on. A learned labeller changes what lands on the
    user's calendar, so it ships behind a flag and the default is today's
    behaviour — the same caution `self_check_apply` has."""
    section = getattr(cfg, "labels", None)
    return bool(getattr(section, f"model_{kind}", False)) if section else False


def category_for(title: str, rule_answer: str, cfg) -> "tuple[str, str]":
    """`(category, who decided)` — the shipped event path.

    The rules keep every row they were confident about; the model only answers
    where they fell through to the catch-all. `Personal` IS the catch-all, so a
    rule answer of `Personal` means "no opinion" rather than "personal", and it
    is the one case worth asking a model about.
    """
    if not enabled(cfg, "event"):
        return rule_answer, "rule"
    first = _model_first(cfg)
    if not first and rule_answer and rule_answer != "Personal":
        return rule_answer, "rule"
    model = _cached("event")
    if model is None:
        return rule_answer, "rule"
    _use_configured_ollama(cfg)
    got = model.predict(title)
    if got is None:
        return rule_answer, "rule"                  # the model abstained: the rules stand
    if not _live_category(got[0]):
        return rule_answer, "rule"                  # a class the user deleted or renamed
    return got[0], "model"


def tags_for(title: str, rule_answer: list, cfg) -> "tuple[list, str]":
    """`(tags, who decided)` — the shipped task path. Same stacking: the rules'
    tags stand when they fired at all, and the model only fills a blank."""
    if not enabled(cfg, "task"):
        return list(rule_answer), "rule"
    first = _model_first(cfg)
    if not first and rule_answer:
        return list(rule_answer), "rule"
    model = _cached("task")
    if model is None:
        return list(rule_answer), "rule"
    _use_configured_ollama(cfg)
    got = model.predict_tags(title)
    if got is None:
        return list(rule_answer), "rule"           # the model abstained: the rules stand
    live = _live_tags(got[0])
    if not live:
        return list(rule_answer), "rule"           # every tag it named is gone
    return live, "model"


# A SAVED MODEL NEVER SEES THE PALETTE (found 2026-09-24 by the label rebuild
# board). Its classes are frozen at training time, so with Travel deleted
# "flight to rome" was still labelled Travel (and coloured as Personal), with
# Errand renamed to Chores it still answered Errand, and with the Errands tag
# deleted it still wrote ['Errands'] — breaking tagging.py's promise that "a
# tag the user renamed or deleted never comes back". The model's answer now
# counts only if that class is still in the user's palette; otherwise the
# rules, which read the live palette, stand. If the palette cannot be read,
# the answer is kept (a store error must never block a commit).
def _live_category(name: str) -> bool:
    try:
        from assistant.actions.calendar import categories as _cats
        return _cats.get(name) is not None
    except Exception:
        return True


def _live_tags(names: list) -> list:
    try:
        from assistant.db import get_db
        palette = {row["name"].lower(): row["name"] for row in get_db().get_tags()}
    except Exception:
        return list(names)
    return [palette[n.lower()] for n in names if n and n.lower() in palette]


def _use_configured_ollama(cfg) -> None:
    """Point the embedding client at the configured ollama (`ollama.base_url`),
    so the embedding head reaches the same server as every other model call."""
    try:
        url = getattr(getattr(cfg, "ollama", None), "base_url", None)
        if url:
            from assistant.engine.label import embed as _embed
            _embed.BASE_URL = str(url)
    except Exception:
        pass


def _model_first(cfg) -> bool:
    """`labels.model_first` — the model's confident answer wins over the rules
    (Gil, 2026-09-22). The rules keep every row the model abstains on."""
    section = getattr(cfg, "labels", None)
    return bool(getattr(section, "model_first", False)) if section else False
