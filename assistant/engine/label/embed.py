"""The label stage's embedding client — one title in, one unit vector out, or None.

    vector(title)            -> np.ndarray | None     one title, at commit time
    vectors(titles)          -> np.ndarray | None     a batch (training, the teach queue)

`nomic-embed-text` on the local ollama (`/api/embed`). Decided 2026-09-24
(DEVQA Q46) on label Board 6: the embedding is the one feature that moved the
classifiers on vocabulary nobody typed in (+12 to +16 pt), and it runs behind
the keyword rules with today's n-gram model as the fallback.

## Every failure is None, and None means "use the n-gram model"

A label is written at COMMIT time, inside the step that saves the row. A slow
or absent embedding must never delay or fail a commit, so:

    MACALENDAR_LLM_DISABLED=1   None, no socket opened (the suite runs this way,
                                so CI exercises the fallback on every run)
    ollama down / slow / junk   None, and the door stays shut for COOLDOWN_S so a
                                dead server costs one timeout, not one per commit
    anything else               None

## One door, through the gate

The call holds `model_protocol.hold()` like every other door to the model, and
it INHERITS the caller's priority: a label written for a live voice command is
live traffic, one written by a board or the retrainer is background. It is not
seeded — an embedding has no sampling.

## Cached in process

The same title is embedded again whenever it is re-labelled (an edit, a series,
the teach queue), so an LRU keeps the last `LRU_SIZE` vectors.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time

import numpy as np

MODEL = "nomic-embed-text"
#: nomic's task prefix. Training and serving MUST use the same one — a vector
#: embedded with another prefix is from a different space.
PREFIX = "classification: "
DEFAULT_URL = "http://localhost:11434"
#: Set from `ollama.base_url` by the shipped entry points (`model._use_configured_ollama`).
BASE_URL: "str | None" = None
#: One title at commit time. Warm calls measure in tens of milliseconds; this
#: bounds a cold model load, after which the n-gram model answers instead.
TIMEOUT_S = 3.0
#: A batch (training, the teach queue) is allowed longer.
BATCH_TIMEOUT_S = 120.0
#: After a failure, skip the call for this long.
COOLDOWN_S = 30.0
LRU_SIZE = 4096
#: Keep the (small, ~275 MB) model resident between commands, so a label is not
#: a cold load every time the user pauses for five minutes.
KEEP_ALIVE = "30m"

_lock = threading.Lock()
_lru: "collections.OrderedDict[str, np.ndarray]" = collections.OrderedDict()
_down_until = 0.0


def disabled() -> bool:
    return os.environ.get("MACALENDAR_LLM_DISABLED") == "1"


def reset() -> None:
    """Forget the cache and any cooldown (tests)."""
    global _down_until
    with _lock:
        _lru.clear()
        _down_until = 0.0


def _unit(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(a))
    return a / n if n > 0 else a


def _post(texts: "list[str]", base_url: str, timeout: float) -> "list | None":
    """The door. Returns the raw vectors or None; never raises."""
    import urllib.request
    from assistant import model_protocol
    body = json.dumps({"model": MODEL, "keep_alive": KEEP_ALIVE,
                       "input": [PREFIX + t for t in texts]}).encode()
    try:
        with model_protocol.hold():
            with urllib.request.urlopen(urllib.request.Request(
                    f"{base_url}/api/embed", data=body,
                    headers={"Content-Type": "application/json"}), timeout=timeout) as r:
                got = json.loads(r.read()).get("embeddings")
    except Exception as e:
        # SAID, not swallowed (2026-09-24): the kind board saw 14 of ~25
        # batches come back empty and nothing anywhere said why — one failure
        # starts the cool-down below, and every call inside it returns None
        # silently. The cause is logged once per failure.
        import logging
        logging.getLogger(__name__).warning(
            "label embedding call failed (%d title(s)): %s: %s",
            len(texts), type(e).__name__, e)
        return None
    if not isinstance(got, list) or len(got) != len(texts):
        return None
    return got


def vectors(texts, base_url: "str | None" = None,
            timeout: float = BATCH_TIMEOUT_S, batch: int = 64) -> "np.ndarray | None":
    """Unit vectors for `texts`, one row each, or None if ANY could not be had.
    Cached rows are not re-sent."""
    global _down_until
    texts = [str(t) for t in texts]
    if disabled() or not texts:
        return None
    if time.monotonic() < _down_until:
        return None
    url = (base_url or BASE_URL or DEFAULT_URL).rstrip("/")
    with _lock:
        missing = sorted({t for t in texts if t not in _lru})
    for i in range(0, len(missing), batch):
        chunk = missing[i:i + batch]
        got = _post(chunk, url, timeout)
        if got is None and timeout > TIMEOUT_S:
            # A BULK caller (a refit, a board, the teach queue) retries once
            # before giving up: the cool-down exists so a dead server costs a
            # LIVE commit one timeout, not so one hiccup empties a whole
            # training pass.
            time.sleep(1.0)
            got = _post(chunk, url, timeout)
        if got is None:
            _down_until = time.monotonic() + COOLDOWN_S
            return None
        with _lock:
            for t, v in zip(chunk, got):
                _lru[t] = _unit(v)
                _lru.move_to_end(t)
            while len(_lru) > LRU_SIZE:
                _lru.popitem(last=False)
    with _lock:
        try:
            out = [_lru[t] for t in texts]
        except KeyError:            # evicted between the fill and the read
            return None
        for t in texts:
            _lru.move_to_end(t)
    return np.vstack(out)


def vector(text: str, base_url: "str | None" = None,
           timeout: float = TIMEOUT_S) -> "np.ndarray | None":
    """One title's unit vector, or None. The commit-time call."""
    if not (text or "").strip():
        return None
    got = vectors([text], base_url=base_url, timeout=timeout)
    return None if got is None else got[0]


def vectors_cached_on_disk(texts, path, base_url: "str | None" = None) -> "np.ndarray | None":
    """`vectors`, backed by a JSONL cache on disk — the TRAINER's entry point.
    Refitting embeds ~12,000 generated rows; a rerun should not pay that again.
    One batch per line, flushed and fsynced, so a crash costs the batch in flight."""
    import pathlib
    path = pathlib.Path(path)
    have: dict = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("model") == MODEL and row.get("prefix", PREFIX) == PREFIX:
                have[row["t"]] = row["v"]
    todo = sorted({t for t in texts if t not in have})
    if todo:
        if disabled():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        url = (base_url or BASE_URL or DEFAULT_URL).rstrip("/")
        with path.open("a") as fh:
            for i in range(0, len(todo), 64):
                chunk = todo[i:i + 64]
                got = _post(chunk, url, BATCH_TIMEOUT_S)
                if got is None:
                    return None
                for t, v in zip(chunk, got):
                    v = [round(float(x), 6) for x in v]
                    have[t] = v
                    fh.write(json.dumps({"model": MODEL, "prefix": PREFIX, "t": t, "v": v}) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
    return np.vstack([_unit(have[t]) for t in texts])
