"""The learned labellers — event category and task tags — and how they ship.

    LabelModel.load("event") -> predict(title) -> (label, confidence) | None
    LabelModel.load("task")  -> predict_tags(title) -> ([tags], confidence) | None

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


class LabelModel:
    """A fitted classifier plus the metadata needed to trust it."""

    __slots__ = ("kind", "pipeline", "classes", "meta")

    def __init__(self, kind: str, pipeline, classes, meta: dict) -> None:
        self.kind = kind            # "event" | "task"
        self.pipeline = pipeline
        self.classes = list(classes)
        self.meta = dict(meta)      # trained_at, n_rows, board numbers, version

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
            m = cls(kind, blob["pipeline"], blob["classes"], blob.get("meta", {}))
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
                     "meta": self.meta}, p)
        return p

    # -- prediction ---------------------------------------------------------

    def predict(self, text: str) -> "tuple[str, float] | None":
        """Single-label. `(label, confidence)`, or None when not confident."""
        if not (text or "").strip():
            return None
        try:
            proba = self.pipeline.predict_proba([text])[0]
        except Exception:
            return None
        best = max(range(len(proba)), key=lambda i: proba[i])
        conf = float(proba[best])
        if conf < MIN_CONFIDENCE.get(self.kind, 0.4):
            return None
        return str(self.pipeline.classes_[best]), conf

    def predict_tags(self, text: str) -> "tuple[list, float] | None":
        """Multi-label. Every tag over the bar, plus the weakest one's score.

        A task can be Groceries AND Errands, so this is one-vs-rest and the
        answer is a SET. Returning the argmax alone would silently drop the
        second tag, which is the behaviour `suggest_tags` already avoids.
        """
        if not (text or "").strip():
            return None
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
        out = _train.train_base(kind, verbose=False)
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
    if rule_answer and rule_answer != "Personal":
        return rule_answer, "rule"
    model = _cached("event")
    if model is None:
        return rule_answer, "rule"
    got = model.predict(title)
    if got is None:
        return rule_answer, "rule"
    return got[0], "model"


def tags_for(title: str, rule_answer: list, cfg) -> "tuple[list, str]":
    """`(tags, who decided)` — the shipped task path. Same stacking: the rules'
    tags stand when they fired at all, and the model only fills a blank."""
    if not enabled(cfg, "task"):
        return list(rule_answer), "rule"
    if rule_answer:
        return list(rule_answer), "rule"
    model = _cached("task")
    if model is None:
        return [], "rule"
    got = model.predict_tags(title)
    if got is None:
        return [], "rule"
    return got[0], "model"
