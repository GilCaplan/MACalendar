"""The user's own labels — collected passively, and the ONE rule that makes it safe.

    record_category(title, was, now, origin)   an event's category changed
    record_tags(title, was, now, origin)       a task's tags changed
    gold(kind) -> [(text, label), …]           what may be trained on
    should_retrain(kind) -> bool               enough NEW gold since last fit

Gil's design, 2026-09-10: *"per user, an automatic pipeline in the background
that adds data the user inputs with his own wording and tags, and every so often
when a predefined number of tasks/events are added the model is retrained with
the original data and the new data."*

It is the right instinct and it fixes the measured gap: the shipped training set
is authored generic-calendar vocabulary, and the user's calendar is their own
words, their own people, their own life. Nothing else closes that.

## THE RULE THAT MAKES IT SAFE, and it is not optional

**Silence is not agreement.** A label the SYSTEM assigned and the user never
touched is not evidence the user agreed with it — most people never look at a
category. Training on it teaches the model its own output, which is precisely
the circularity this whole workstream exists to escape:
`fastrule/datasets/generate.py` computes its category gold by calling
`categories.classify()`, and that is why a decision tree scored exactly 100% on
the first board and meant nothing.

Feed model output back in as gold and the same trap returns, but INVISIBLY —
the labels agree with the predictions by construction, so every board looks
fine while the model amplifies its own bias.

So exactly two things are gold, and both require a human act:

    CORRECTION      the user CHANGED an assigned label   <- the best signal
                    there is: a labelled error, which is the one thing no
                    amount of synthetic data can manufacture
    EXPLICIT PICK   the user CHOSE a label themselves

And one thing is never gold, however tempting:

    UNTOUCHED       the system labelled it; nobody objected

`origin` carries which, it is recorded on every row, and `gold()` filters on it.
A caller cannot opt out by passing the wrong value, because the two write
helpers are the only way in and each stamps its own.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

#: Outside the repo, like every other personal store, and env-overridable so
#: tests and boards never touch the real one (CLAUDE.md).
FEEDBACK_PATH = pathlib.Path(
    os.environ.get("MACALENDAR_LABEL_FEEDBACK")
    or os.path.expanduser("~/.assistant_tools/label_feedback.jsonl"))

#: How many NEW gold rows since the last fit before retraining is worth it.
#: Counted in GOLD, not in items: fifty tasks nobody corrected teach nothing,
#: and triggering on item count would retrain on no new information.
RETRAIN_EVERY = {"event": 25, "task": 25}

#: The two origins that are gold, and the one that is not.
CORRECTION = "correction"      # the user changed an assigned label
EXPLICIT = "explicit"          # the user chose it themselves
ASSIGNED = "assigned"          # the system chose it; recorded, NEVER trained on

_GOLD_ORIGINS = (CORRECTION, EXPLICIT)


def _append(row: dict) -> None:
    try:
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_PATH.open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:
        pass          # collecting training data must never break a user action


def record_category(title: str, was: "str | None", now: str,
                    origin: str = CORRECTION) -> None:
    """An event's category was set by a person.

    `was` is kept even though nothing trains on it: knowing what the system had
    guessed is how the retrainer's report can say WHICH confusions the user is
    actually correcting, which is the most useful thing this file will ever
    hold.
    """
    if not (title or "").strip() or not (now or "").strip():
        return
    if was is not None and str(was).strip() == str(now).strip():
        return          # not a change; nothing was taught
    _append({"kind": "event", "text": title.strip(), "was": was,
             "label": now.strip(), "origin": origin, "ts": time.time()})


def record_tags(title: str, was: "list | None", now: list,
                origin: str = CORRECTION) -> None:
    """A task's tags were set by a person."""
    if not (title or "").strip():
        return
    new = sorted({str(t).strip() for t in (now or []) if str(t).strip()})
    old = sorted({str(t).strip() for t in (was or []) if str(t).strip()})
    if not new or new == old:
        return
    _append({"kind": "task", "text": title.strip(), "was": old,
             "label": new, "origin": origin, "ts": time.time()})


def _rows() -> list:
    if not FEEDBACK_PATH.exists():
        return []
    out = []
    try:
        for line in FEEDBACK_PATH.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue          # one bad line must not lose the file
    except Exception:
        return []
    return out


def gold_with_time(kind: str) -> list:
    """`[(ts, text, label), …]` oldest first — the shape the trainer's
    time-ordered split needs. Same filtering as `gold()`."""
    latest: dict = {}
    for r in _rows():
        if r.get("kind") != kind or r.get("origin") not in _GOLD_ORIGINS:
            continue
        text = (r.get("text") or "").strip()
        if text and r.get("label"):
            latest[text.lower()] = (float(r.get("ts") or 0), text, r["label"])
    return sorted(latest.values(), key=lambda x: x[0])


def gold(kind: str) -> list:
    """`[(text, label), …]` — only what a human actually decided.

    Deduplicated on text with the LATEST label winning: a user who corrects the
    same title twice has changed their mind, and the newer answer is the one
    they meant. Training on both would teach the classifier to be uncertain
    about a case the user is now sure of.
    """
    latest: dict = {}
    for r in _rows():
        if r.get("kind") != kind or r.get("origin") not in _GOLD_ORIGINS:
            continue
        text = (r.get("text") or "").strip()
        if text:
            latest[text.lower()] = (text, r.get("label"))
    return [v for v in latest.values() if v[1]]


def counts(kind: str) -> dict:
    """What the store holds, for the retrainer's report and for `assistant
    doctor`. `assigned` is shown precisely because it is NOT trained on —
    a number nobody can see is a rule nobody can check."""
    rows = [r for r in _rows() if r.get("kind") == kind]
    by = {"correction": 0, "explicit": 0, "assigned": 0}
    for r in rows:
        by[r.get("origin", "assigned")] = by.get(r.get("origin", "assigned"), 0) + 1
    return {"total": len(rows), "gold": len(gold(kind)), **by}


def _marker(kind: str) -> pathlib.Path:
    return FEEDBACK_PATH.parent / f".last_fit_{kind}"


def mark_trained(kind: str, n_gold: int) -> None:
    try:
        _marker(kind).write_text(str(n_gold))
    except Exception:
        pass


def should_retrain(kind: str) -> bool:
    """Enough NEW gold since the last fit to be worth refitting."""
    try:
        last = int(_marker(kind).read_text().strip())
    except Exception:
        last = 0
    return (len(gold(kind)) - last) >= RETRAIN_EVERY.get(kind, 25)
