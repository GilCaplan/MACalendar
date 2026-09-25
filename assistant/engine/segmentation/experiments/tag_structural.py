"""Does a STRUCTURAL classifier beat the hand rules `fastseg.tag()` now carries?

    python -m assistant.engine.segmentation.experiments.tag_structural

`tag_head.py` already asked this question once, for `assistant.intent.
classifier.KindFeatures` — 18 engineered signals (clock/date presence,
"remind X to", occasion-nouns, "with NAME", list-words, ...) fitted with the
project's one `LogisticModel`. It lost, standalone (80.4%), margin-gated
(81.2%), and as a one-way veto over `event` (80.1%), against the shipped
tagger's 87.5% at the time (now higher — see ARCHITECTURE.md §0b).

That is not "ML doesn't work here" — it is "keyword-PRESENCE features don't
carry enough information". `KindFeatures`' `with\\s+[a-z]+` fires identically
on "meeting WITH SAM" and "wash the dishes WITH a sponge"; it cannot tell a
verb's actual OBJECT from an unrelated word that happens to appear after a
shared preposition. Every hand rule ARCHITECTURE.md §0b documents (16 of
them, all measured, zero regressions) reads the DEPENDENCY PARSE instead:
which token is actually the verb's object, whether "before" is transitive,
what family the head verb resolves to. This file asks whether a model fit
over THAT feature space — structural, not lexical-presence — closes the gap,
using the exact same measurement discipline as `tag_head.py`: scored on gold
items (never FastSeg's own cut, so a segmentation error is never charged to
the tagger), three slices (all rows, rows not in FastRule's fitting data,
hand-written rows alone — the strictest, since generated rows share template
skeletons with the ones the underlying signals were tuned against), and
k-fold WITHIN TRAIN only — sealed is never read here, not even aggregates,
because this is hypothesis-formation, not a milestone check.
"""
from __future__ import annotations

import collections
import glob
import json
import math
import os
import random
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from assistant.common.scratch_env import scratch_env  # noqa: E402

scratch_env("ts_", keep=("LOCATION", "MODELS", "LABEL_FEEDBACK", "HEARTBEATS",
                         "HUD_STATE", "DEVICE_SECRET", "DEVICES"))

from assistant.engine.segmentation.experiments import run_board as RB          # noqa: E402
# NAMED imports, not `import ... as FS` — `fastseg/__init__.py` re-exports the
# `fastseg()` FUNCTION under the package's own name, which shadows the
# submodule on attribute access; importing names directly sidesteps that.
from assistant.engine.segmentation.fastseg.fastseg import (                    # noqa: E402
    _PREAMBLE, _CALENDAR_VERBS, _TASK_VERBS, _STATED_CLOCK, _VAGUE_TIME_HEDGE,
    _TIME_BLOCKING, _DUE_DATE_EDIT, _NUDGE_IDIOM, _ANCHORED_TO_EVENT,
    find_time_refs, tag as shipped_tag)
from assistant.intent import coordination as CO                                # noqa: E402
from assistant.intent.coordination import _REMINDER_LEAD_RE                    # noqa: E402
from assistant.intent.classifier import Featurizer, LogisticModel              # noqa: E402
from assistant.intent.rule_parser import _CALENDAR_SIGNALS, _TODO_SIGNALS      # noqa: E402
from assistant.engine.segmentation.fastseg.kind import (                      # noqa: E402
    _enforce_pinned_kinds, _kind_of)


# ---------------------------------------------------------------------------
# Structural features — dependency-parse-derived, not keyword presence
# ---------------------------------------------------------------------------

def _root(doc):
    return next((t for t in doc if t.dep_ == "ROOT"), None)


def _head_verb_family(action: str) -> str:
    """Same head-of-action read `_lexicon_kind` uses, but returning WHICH
    lexicon rather than a verdict — the model gets to weigh it, not obey it."""
    words = [w.strip(".!?,") for w in action.lower().split()]
    while words and words[0] in _PREAMBLE:            # noqa: SLF001
        words.pop(0)
    for word in words[:2]:
        if word in _CALENDAR_VERBS:                   # noqa: SLF001
            return "calendar"
        if word in _TASK_VERBS:                        # noqa: SLF001
            return "task"
    return "neither"


def _has_propn_argument(doc, root) -> float:
    """Does the ROOT verb's own OBJECT — direct, or the object of a
    preposition it governs — carry a capitalised proper noun?

    "meeting WITH SAM", "meet QUINN", "email ROBIN about X" all reduce to
    this ONE structural check instead of a separate rule per verb: the
    ARGUMENT is a named entity, not what kind of preposition introduced it.
    Reliable where a keyword-presence regex is not, because it requires the
    dependency relation to actually hold — "wash the dishes with a sponge"
    has "with" too, but "sponge" is never the verb's argument.
    """
    if root is None:
        return 0.0
    for child in root.children:
        if child.dep_ in ("dobj", "obj", "dative") and child.pos_ == "PROPN":
            return 1.0
        if child.dep_ == "prep":
            for gc in child.children:
                if gc.dep_ == "pobj" and gc.pos_ == "PROPN":
                    return 1.0
    return 0.0


def _before_transitivity(action: str) -> "tuple[float, float]":
    """(is_intransitive_lead, is_transitive_anchor) — reuses the exact
    idiom-recognition `_lead_has_no_object`/`_ANCHORED_TO_EVENT` already
    validated in fastseg.py (16-fix session, §0b), read here as TWO features
    instead of a hard veto/promotion, so the model decides how much they
    matter relative to everything else instead of firing unconditionally."""
    if _ANCHORED_TO_EVENT.search(action):              # noqa: SLF001
        return 0.0, 1.0
    if _REMINDER_LEAD_RE.match(action.strip()):
        return 1.0, 0.0
    return 0.0, 0.0


def _own_infrastructure(action: str) -> float:
    """"block off TIME to X", "flip the DUE DATE on X", "give me a NUDGE" —
    the action is about the speaker's OWN reminder/task machinery, not an
    external thing. One shared primitive behind three of §0b's idioms."""
    low = action.lower()
    return 1.0 if (_TIME_BLOCKING.search(action) or _DUE_DATE_EDIT.match(action)  # noqa: SLF001
                   or _NUDGE_IDIOM.match(action) or "nudge" in low) else 0.0


class KindStructuralFeatures(Featurizer):
    """Event/task/review signals read off the DEPENDENCY PARSE and the
    stage's own time-reference extractor, not off raw-string keyword
    presence — see the module docstring for why that distinction is the
    whole experiment."""

    names = ["bias", "head-calendar", "head-task", "head-neither",
             "engine-event", "engine-task", "engine-review",
             "has-clock", "has-date-only", "bare-today",
             "propn-argument", "before-intransitive", "before-transitive",
             "own-infrastructure", "todo-destination", "calendar-destination",
             "vague-hedge", "recurrence", "long"]

    def extract(self, action_time) -> "list[float]":
        action, time_str = action_time
        doc = CO.parsed(action) if " " in action else None
        root = _root(doc) if doc is not None else None

        fam = _head_verb_family(action)
        kind = _enforce_pinned_kinds(_kind_of(action), action)

        t = (time_str or "").strip().lower()
        has_clock = 1.0 if _STATED_CLOCK.search(t) else 0.0           # noqa: SLF001
        bare_today = 1.0 if t in ("", "today") else 0.0
        has_date_only = 1.0 if (not bare_today and not has_clock) else 0.0

        propn_arg = _has_propn_argument(doc, root) if doc is not None else 0.0
        before_intrans, before_trans = _before_transitivity(action)

        low = action.lower()
        words = set(low.split())
        todo_dest = 1.0 if (words & _TODO_SIGNALS) else 0.0
        cal_dest = 1.0 if (words & _CALENDAR_SIGNALS) else 0.0
        vague = 1.0 if _VAGUE_TIME_HEDGE.search(action) else 0.0       # noqa: SLF001
        recur = 1.0 if (doc is not None and any(
            r.kind == "recurrence" for r in find_time_refs(action))) else 0.0

        return [
            1.0,
            1.0 if fam == "calendar" else 0.0,
            1.0 if fam == "task" else 0.0,
            1.0 if fam == "neither" else 0.0,
            1.0 if kind == "event" else 0.0,
            1.0 if kind == "task" else 0.0,
            1.0 if kind == "review" else 0.0,
            has_clock, has_date_only, bare_today,
            propn_arg, before_intrans, before_trans,
            _own_infrastructure(action), todo_dest, cal_dest,
            vague, recur,
            1.0 if len(action.split()) > 9 else 0.0,
        ]


# ---------------------------------------------------------------------------
# Harness — mirrors tag_head.py's methodology exactly
# ---------------------------------------------------------------------------

def _rows():
    rows = []
    for p in glob.glob(os.path.join(_HERE, "datasets", "*.jsonl")):
        for line in open(p):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return [r for r in RB.assign_splits(rows) if r.get("split") != "test"]


def _fitting_texts() -> set:
    out = set()
    path = os.path.join(_ROOT, "assistant", "engine", "fastrule", "datasets",
                        "fastrule_7200.jsonl")
    try:
        for line in open(path):
            r = json.loads(line)
            if r.get("split") == "train":
                out.add(r["text"].strip().lower())
    except OSError:
        pass
    return out


def _items(rows):
    """Every (action, time, tag) gold triple, flattened."""
    out = []
    for r in rows:
        for g in r["gold"]:
            g = g if isinstance(g, dict) else {"action": g[0], "time": g[1], "tag": g[2]}
            out.append((g["action"], g["time"], g["tag"], r.get("id", "")))
    return out


def _kfold_predictions(items, featurizer_cls, k: int = 5, seed: int = 20260916):
    """Out-of-fold predictions for every item — each item is scored by a
    model that never saw it during fitting, the only honest way to measure a
    classifier on a dataset this small without touching sealed."""
    rng = random.Random(seed)
    idx = list(range(len(items)))
    rng.shuffle(idx)
    folds = [idx[i::k] for i in range(k)]
    preds = [None] * len(items)
    for i in range(k):
        held = set(folds[i])
        train_idx = [j for j in idx if j not in held]
        texts = [(items[j][0], items[j][1]) for j in train_idx]
        labels = [items[j][2] for j in train_idx]
        model = LogisticModel("kind-structural", ("event", "task", "review"),
                              featurizer_cls())
        model.fit(texts, labels)
        for j in folds[i]:
            action, time_str, _, _ = items[j]
            label, margin = model.predict((action, time_str))
            preds[j] = (label, margin)
    return preds


def _shipped(items):
    return [(shipped_tag(a, t), math.inf) for a, t, _, _ in items]


def score(items, preds):
    ok = n = 0
    conf = collections.Counter()
    for (a, t, want, _id), (got, _m) in zip(items, preds):
        n += 1
        ok += got == want
        conf[(want, got)] += 1
    return ok, n, conf


def main() -> None:
    rows = _rows()
    fitted = _fitting_texts()
    all_items = _items(rows)
    slices = {
        f"ALL train items ({len(all_items)})": all_items,
        "hand-written only (cannot be in FastRule)":
            [it for it in all_items
             if next((r for r in rows if r.get("id") == it[3]), {}).get("source") == "handwritten"],
    }

    print("Fitting 5-fold out-of-fold predictions for the structural head...")
    struct_preds_all = _kfold_predictions(all_items, KindStructuralFeatures, k=5)
    shipped_preds_all = _shipped(all_items)

    for label, subset in slices.items():
        keep = [i for i, it in enumerate(all_items) if it in subset]
        print(f"\n{'=' * 74}\n{label}\n{'=' * 74}")
        for name, preds_all in (("A shipped tagger", shipped_preds_all),
                                 ("E structural head (5-fold OOF)", struct_preds_all)):
            sub_items = [all_items[i] for i in keep]
            sub_preds = [preds_all[i] for i in keep]
            ok, n, conf = score(sub_items, sub_preds)
            tr = conf[("task", "task")]
            tn = sum(v for (w, _g), v in conf.items() if w == "task")
            ev = conf[("event", "event")]
            en = sum(v for (w, _g), v in conf.items() if w == "event")
            print(f"  {name:32s} {100*ok/max(1,n):5.1f}%  ({ok}/{n})"
                  f"   task recall {100*tr/max(1,tn):5.1f}%"
                  f"   event recall {100*ev/max(1,en):5.1f}%")

        # confusion for the structural head, this slice
        sub_items = [all_items[i] for i in keep]
        sub_preds = [struct_preds_all[i] for i in keep]
        _ok, _n, conf = score(sub_items, sub_preds)
        print("\n  confusion — structural head (gold -> predicted)")
        for w in ("event", "task", "review"):
            row = "  ".join(f"{g}:{conf[(w, g)]:4d}" for g in ("event", "task", "review"))
            print(f"     {w:8s} {row}")

    # D-style one-way veto over `event`, using the structural head's OOF calls
    print(f"\n{'=' * 74}\nOne-way veto over `event` (D-style), structural head, OOF\n{'=' * 74}")
    for margin_floor in (0.0, 0.5, 1.0, 1.5):
        vetoed = []
        for it, (label, margin) in zip(all_items, struct_preds_all):
            a, t, want, _id = it
            shipped = shipped_tag(a, t)
            if shipped == "event" and label == "task" and margin >= margin_floor:
                vetoed.append("task")
            else:
                vetoed.append(shipped)
        ok = sum(1 for (a, t, want, _id), got in zip(all_items, vetoed) if got == want)
        print(f"  margin>={margin_floor:<4} {100*ok/len(all_items):5.1f}%  ({ok}/{len(all_items)})")


if __name__ == "__main__":
    main()
