"""The learned labellers' n-gram half, as data, so the phone can run them.

    export(kind, cfg) -> dict | None      served at GET /labels/model/<kind>
    ngram_proba(payload, title) -> list   the reference inference over it

The phone cannot run either artefact as it stands: each is a pickled sklearn
pipeline, and the half that answers on the Mac reads the title's
nomic-embed-text vector from ollama. What it CAN run is the n-gram half — two
TF-IDF vectorisers and a logistic regression, which is a tokeniser, a
dictionary lookup and a dot product. So that half ships as data and
`LabelModel.swift` is the arithmetic, the same split `/tags/rules` and
`TagClassifier.swift` made for the keyword rules: what syncs is the data, what
ships in the app is the maths, and a retrain reaches the phone without a
reinstall.

**The phone is the Mac with ollama down.** Without the vector, the Mac answers
from this same n-gram pipeline and holds it to the fallback bar
(`LabelModel.ngram_bar`); the payload carries that bar rather than letting the
phone pick one. It carries the user's switches too (`labels.model_event` /
`model_task` / `model_first`), so the stacking on the phone is `tags_for` and
`category_for`'s, and switching the model off on the Mac switches it off there.

**It is whichever tier the Mac would load** — this user's personal model when
one has been fitted from their corrections, else the committed base.

**The format is checked, not assumed.** `_block` refuses a vectoriser whose
settings the phone's tokeniser does not reproduce (a different token pattern,
accent stripping, binary counts…), so a retrain that changes one fails loudly
in `test_label_export.py` instead of serving numbers the phone computes wrongly.
`ngram_proba` below is the reference the Swift port and the test both answer
to: it reads nothing but the payload.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re

import numpy as np

KINDS = ("event", "task")

#: Bumped when the payload's SHAPE changes; the phone ignores a format it
#: does not know and keeps the rules-only answer.
FORMAT = 1

#: sklearn's default token pattern — the only one the phone implements.
_TOKEN_PATTERN = r"(?u)\b\w\w+\b"
_TOKEN = re.compile(_TOKEN_PATTERN)

_CACHE: dict = {}


class UnsupportedModel(ValueError):
    """A fitted pipeline the phone's port could not reproduce exactly."""


def _f32(a) -> str:
    return base64.b64encode(np.asarray(a, dtype="<f4").tobytes()).decode("ascii")


def _block(name: str, vec) -> dict:
    """One vectoriser as data. Only the settings the phone reproduces pass."""
    p = vec.get_params()
    analyzer = p["analyzer"]
    ok = (analyzer in ("word", "char_wb") and p["lowercase"] and p["strip_accents"] is None
          and p["preprocessor"] is None and p["tokenizer"] is None and p["stop_words"] is None
          and (analyzer != "word" or p["token_pattern"] == _TOKEN_PATTERN)
          and p["use_idf"] and p["norm"] == "l2" and not p["binary"] and p["sublinear_tf"])
    if not ok:
        raise UnsupportedModel(f"{name}: vectoriser settings the phone does not implement: {p}")
    terms = [None] * len(vec.vocabulary_)
    for term, i in vec.vocabulary_.items():
        terms[i] = term
    return {"name": name, "analyzer": analyzer, "ngram": list(p["ngram_range"]),
            "terms": terms, "idf": list(vec.idf_)}


def _model_part(model) -> dict:
    """Everything that comes from the artefact. Cached per artefact file."""
    pipe = model.pipeline
    feat, clf = pipe.named_steps["feat"], pipe.named_steps["clf"]
    blocks = [_block(n, v) for n, v in feat.transformer_list]
    idf = [x for b in blocks for x in b.pop("idf")]
    if model.kind == "event":
        classes = [str(c) for c in clf.classes_]
        coef, intercept, link = np.asarray(clf.coef_), np.asarray(clf.intercept_), "softmax"
        if coef.shape[0] != len(classes):
            raise UnsupportedModel(f"event: {coef.shape[0]} weight rows for {len(classes)} classes")
    else:
        classes = [str(c) for c in model.classes]
        ests = clf.estimators_
        if any(not hasattr(e, "coef_") for e in ests):
            raise UnsupportedModel("task: a one-vs-rest column was constant at fit time")
        coef = np.vstack([np.asarray(e.coef_).reshape(1, -1) for e in ests])
        intercept = np.array([float(np.asarray(e.intercept_).ravel()[0]) for e in ests])
        link = "sigmoid"
    if coef.shape[1] != len(idf):
        raise UnsupportedModel(f"{model.kind}: {coef.shape[1]} weights for {len(idf)} features")
    part = {
        "format": FORMAT,
        "kind": model.kind,
        "tier": model.meta.get("tier", ""),
        "trained_at": model.meta.get("trained_at"),
        "link": link,
        "classes": classes,
        "bar": float(model.ngram_bar()),
        "blocks": blocks,
        "idf": _f32(idf),
        "coef": _f32(coef.ravel()),
        "intercept": [float(x) for x in intercept],
    }
    part["model_rev"] = hashlib.sha1(json.dumps(part, sort_keys=True).encode()).hexdigest()[:12]
    return part


def _artefact_path(kind: str):
    from assistant.engine.label.model import LabelModel
    for tier in ("personal", "base"):
        p = LabelModel.path_for(kind, tier)
        if p.exists():
            return p
    return None


def export(kind: str, cfg) -> "dict | None":
    """The payload for `kind`, or None when there is no model to serve.

    Cached on the artefact's path and mtime, so a retrain (a new personal file)
    is served on the next request and nothing else re-reads a 5 MB pickle."""
    if kind not in KINDS:
        return None
    from assistant.engine.label import model as _lm
    path = _artefact_path(kind)
    if path is None:
        _lm._cached(kind)                 # builds the base tier, as first use does
        path = _artefact_path(kind)
        if path is None:
            return None
    key = (kind, str(path), path.stat().st_mtime_ns)
    part = _CACHE.get(key)
    if part is None:
        model = _lm.LabelModel._read(kind, path)
        if model is None:
            return None
        part = _model_part(model)
        if len(_CACHE) > 8:
            _CACHE.clear()
        _CACHE[key] = part
    payload = dict(part)
    payload["enabled"] = _lm.enabled(cfg, kind)
    payload["model_first"] = _lm._model_first(cfg)
    payload["rev"] = hashlib.sha1(
        f"{part['model_rev']}|{payload['enabled']}|{payload['model_first']}".encode()).hexdigest()[:12]
    return payload


# ---------------------------------------------------------------------------
# The reference inference — what LabelModel.swift implements, from the payload
# alone. Kept here so the test can hold BOTH the format and the port to sklearn.
# ---------------------------------------------------------------------------

def _analyze(block: dict, doc: str) -> list:
    doc = doc.lower()
    lo, hi = block["ngram"]
    if block["analyzer"] == "word":
        toks = _TOKEN.findall(doc)
        out = []
        for n in range(lo, hi + 1):
            out += [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]
        return out
    out = []
    for w in doc.split():
        w = f" {w} "
        for n in range(lo, hi + 1):
            offset = 0
            out.append(w[offset:offset + n])
            while offset + n < len(w):
                offset += 1
                out.append(w[offset:offset + n])
            if offset == 0:               # a word shorter than n counts once
                break
    return out


_DECODED: dict = {}


def _decode(payload: dict) -> dict:
    got = _DECODED.get(payload["model_rev"])
    if got is None:
        idf = np.frombuffer(base64.b64decode(payload["idf"]), dtype="<f4").astype(float)
        coef = np.frombuffer(base64.b64decode(payload["coef"]), dtype="<f4").astype(float)
        index, start = [], 0
        for b in payload["blocks"]:
            index.append({t: start + i for i, t in enumerate(b["terms"])})
            start += len(b["terms"])
        got = {"idf": idf, "coef": coef.reshape(len(payload["classes"]), -1), "index": index}
        _DECODED.clear()
        _DECODED[payload["model_rev"]] = got
    return got


def ngram_proba(payload: dict, title: str) -> list:
    """P(class) for one title, over `payload["classes"]`, from the payload alone."""
    d = _decode(payload)
    x: dict = {}
    for b, index in zip(payload["blocks"], d["index"]):
        counts: dict = {}
        for g in _analyze(b, title):
            j = index.get(g)
            if j is not None:
                counts[j] = counts.get(j, 0) + 1
        vals = {j: (1.0 + math.log(c)) * d["idf"][j] for j, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vals.values()))
        if norm > 0:
            x.update({j: v / norm for j, v in vals.items()})
    z = [payload["intercept"][c] + sum(v * d["coef"][c][j] for j, v in x.items())
         for c in range(len(payload["classes"]))]
    if payload["link"] == "softmax":
        m = max(z)
        e = [math.exp(v - m) for v in z]
        s = sum(e)
        return [v / s for v in e]
    return [1.0 / (1.0 + math.exp(-v)) for v in z]
