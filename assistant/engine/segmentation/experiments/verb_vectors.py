"""Can word vectors place a verb the lexicons have never seen? Measured
BEFORE anything is wired in — the dependency (`en_core_web_md`, ~40 MB,
offline once downloaded) only earns its place if the numbers here do.

    python -m assistant.engine.segmentation.experiments.verb_vectors

THE PROBLEM THIS TESTS. Every TAG and CUT mechanism in this stage bottoms out
in "is this word in a hand-written list" — `_TASK_VERBS`/`_CALENDAR_VERBS`
(fastseg.py) and `INTENT_MAP` (rule_parser.py). The adversarial test (§0c)
showed that is exactly what fails on real speech: "draft", "prep",
"finalize", "carve out", "poke me" were all unknown until someone typed
them in, and typing them in is the overfitting the user does not want.
`en_core_web_sm` carries NO word vectors (`(0, 0)`), so nothing in the
system can currently ask "is this verb LIKE 'prepare'?".

THE IDEA. Keep `sm` for parsing (every parse-dependent mechanism stays
byte-identical); load `md` for its VECTORS ONLY. The prototypes are the
EXISTING lexicons themselves — nothing new is hand-written — and a word
outside them is placed by cosine similarity to its nearest prototype, with
an abstention threshold below which it stays unknown, exactly as today.

THREE QUESTIONS, in order of how much rides on each:
  1. TAG — task or event? Held-out verbs labelled by hand, scored against
     `_TASK_VERBS` ∪ `_CALENDAR_VERBS` as prototypes. The binary question
     `_lexicon_kind` answers.
  2. ROUTING — which `INTENT_MAP` family? Finer, and what
     `_verb_intent_family` / FastRule's router would consume.
  3. SEPARATION — does a NON-verb ("milk", "budget", "coffee", "friday",
     "new") stay below threshold? This is the one that decides whether
     vectors may widen `_is_command_verb` at all: that function feeds the
     CUT, and a noun promoted to "command verb" is a false split — the
     expensive failure. If (3) does not separate cleanly, vectors are for
     TAG only, never for CUT.

Held-out words are checked programmatically to be ABSENT from every
lexicon, so nothing below is measuring memorisation. Multi-word verbs
("carve out") are scored on their head token, and the polysemy that buys
("set", "check", "hang") is reported, not hidden.
"""
from __future__ import annotations

import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

for _k, _v in (("MACALENDAR_DB", "/tmp/vv.db"), ("MACALENDAR_MEMORY_DB", "/tmp/vv_m.db"),
               ("MACALENDAR_VOCAB", "/tmp/vv_v.json"),
               ("MACALENDAR_CATEGORIES", "/tmp/vv_c.json"),
               ("MACALENDAR_TRACE_BUS", "/tmp/vv_bus.jsonl"),
               ("MACALENDAR_NO_WARMUP", "1"), ("OMP_NUM_THREADS", "1"),
               ("MACALENDAR_LLM_PRIORITY", "background")):
    os.environ.setdefault(_k, _v)

from assistant.engine.segmentation.fastseg.fastseg import (                    # noqa: E402
    _CALENDAR_VERBS, _TASK_VERBS)
from assistant.intent.rule_parser import INTENT_MAP                            # noqa: E402

# ---------------------------------------------------------------------------
# Held-out words — hand-labelled, and asserted absent from every lexicon
# ---------------------------------------------------------------------------

#: (word, tag label, INTENT_MAP family label)
HELD_OUT = [
    # to-do verbs
    ("compile", "task", "create_todo"), ("assemble", "task", "create_todo"),
    ("tidy", "task", "create_todo"), ("mend", "task", "create_todo"),
    ("fetch", "task", "create_todo"), ("mail", "task", "create_todo"),
    ("iron", "task", "create_todo"), ("mow", "task", "create_todo"),
    ("declutter", "task", "create_todo"), ("fax", "task", "create_todo"),
    ("ship", "task", "create_todo"), ("scrub", "task", "create_todo"),
    ("defrost", "task", "create_todo"), ("photocopy", "task", "create_todo"),
    ("bake", "task", "create_todo"), ("outline", "task", "create_todo"),
    ("rinse", "task", "create_todo"), ("carve", "task", "create_todo"),
    # calendar verbs
    ("attend", "event", "create_event"), ("host", "event", "create_event"),
    ("convene", "event", "create_event"), ("rehearse", "event", "create_event"),
    ("celebrate", "event", "create_event"), ("dine", "event", "create_event"),
    ("brunch", "event", "create_event"), ("meet", "event", "create_event"),
    # update / delete / complete
    ("defer", "event", "update_event"), ("bump", "event", "update_event"),
    ("ditch", "task", "delete_todo"), ("axe", "task", "delete_todo"),
    ("nix", "task", "delete_todo"), ("discard", "task", "delete_todo"),
    ("forget", "task", "delete_todo"), ("conclude", "task", "complete_todo"),
    ("wrap", "task", "complete_todo"),
]

#: Things that are NOT command verbs and must stay below any threshold
#: that `_is_command_verb` would use — the CUT's false-positive budget.
NOT_VERBS = ["milk", "dentist", "budget", "presentation", "garage", "laptop",
             "coffee", "dinner", "meeting", "karen", "friday", "tomorrow",
             "morning", "new", "quick", "leaky", "the", "and", "about",
             "before", "eight", "groceries", "passport", "kitchen"]


def _families() -> "dict[str, set]":
    fam: dict[str, set] = {}
    for (verb, _q), intent in INTENT_MAP.items():
        fam.setdefault(intent, set()).add(verb)
    return fam


def _load_vectors():
    import spacy
    try:
        nlp = spacy.load("en_core_web_md",
                         exclude=["tok2vec", "tagger", "parser", "attribute_ruler",
                                  "lemmatizer", "ner"])
    except OSError:
        raise SystemExit("en_core_web_md is not installed — "
                         "`python -m spacy download en_core_web_md` first.")
    if nlp.vocab.vectors.shape[0] == 0:
        raise SystemExit("en_core_web_md loaded but carries no vectors.")
    return nlp.vocab


def _vec(vocab, word: str):
    lex = vocab[word]
    if not lex.has_vector:
        return None
    v = lex.vector
    n = np.linalg.norm(v)
    return v / n if n else None


def _nearest(vocab, word: str, prototypes: "dict[str, set]"):
    """(best_label, best_sim, best_proto, margin) over labelled prototype
    sets, nearest-neighbour cosine. None when the word has no vector."""
    v = _vec(vocab, word)
    if v is None:
        return None
    scored = []
    for label, protos in prototypes.items():
        best_s, best_p = -1.0, None
        for p in protos:
            pv = _vec(vocab, p)
            if pv is None:
                continue
            s = float(v @ pv)
            if s > best_s:
                best_s, best_p = s, p
        scored.append((best_s, label, best_p))
    scored.sort(reverse=True)
    (s1, l1, p1), s2 = scored[0], (scored[1][0] if len(scored) > 1 else -1.0)
    return l1, s1, p1, s1 - s2


def main() -> None:
    vocab = _load_vectors()
    every_lexicon_word = set(_TASK_VERBS) | set(_CALENDAR_VERBS) | {v for v, _ in INTENT_MAP}
    leaked = [w for w, _, _ in HELD_OUT if w in every_lexicon_word]
    assert not leaked, f"held-out words already in a lexicon: {leaked}"

    # ---- 1. TAG: task vs event ------------------------------------------
    tag_protos = {"task": set(_TASK_VERBS), "event": set(_CALENDAR_VERBS)}
    print("=" * 74)
    print("1 · TAG — task vs event, nearest prototype in _TASK_VERBS / _CALENDAR_VERBS")
    print("=" * 74)
    rows = []
    for word, tag, _fam in HELD_OUT:
        r = _nearest(vocab, word, tag_protos)
        if r is None:
            print(f"  {word:12s} OOV")
            continue
        label, sim, proto, margin = r
        ok = label == tag
        rows.append((sim, ok))
        print(f"  {word:12s} -> {label:5s} (via {proto:10s} sim {sim:.2f}, margin {margin:+.2f})"
              f"  {'OK' if ok else 'WRONG: want ' + tag}")
    print()
    for thr in (0.30, 0.40, 0.50, 0.60):
        kept = [ok for sim, ok in rows if sim >= thr]
        acc = 100 * sum(kept) / len(kept) if kept else 0.0
        print(f"  threshold {thr:.2f}: answers {len(kept):2d}/{len(rows)} "
              f"of held-out verbs, {acc:5.1f}% of those right")

    # ---- 2. ROUTING: INTENT_MAP family ----------------------------------
    fam_protos = _families()
    print()
    print("=" * 74)
    print("2 · ROUTING — INTENT_MAP family, nearest prototype per family")
    print("=" * 74)
    rows = []
    for word, _tag, fam in HELD_OUT:
        r = _nearest(vocab, word, fam_protos)
        if r is None:
            continue
        label, sim, proto, margin = r
        ok = label == fam
        rows.append((sim, ok))
        print(f"  {word:12s} -> {label:14s} (via {proto:10s} sim {sim:.2f}, margin {margin:+.2f})"
              f"  {'OK' if ok else 'WRONG: want ' + fam}")
    print()
    for thr in (0.30, 0.40, 0.50, 0.60):
        kept = [ok for sim, ok in rows if sim >= thr]
        acc = 100 * sum(kept) / len(kept) if kept else 0.0
        print(f"  threshold {thr:.2f}: answers {len(kept):2d}/{len(rows)}, {acc:5.1f}% right")

    # ---- 3. SEPARATION: non-verbs must stay below the bar ---------------
    all_protos = {"command": every_lexicon_word}
    print()
    print("=" * 74)
    print("3 · SEPARATION — max similarity of a NON-verb to ANY command verb")
    print("    (the CUT's false-positive budget: `_is_command_verb` feeds the split)")
    print("=" * 74)
    verb_sims = []
    for word, _t, _f in HELD_OUT:
        r = _nearest(vocab, word, all_protos)
        if r:
            verb_sims.append(r[1])
    noun_sims = []
    for word in NOT_VERBS:
        r = _nearest(vocab, word, all_protos)
        if r is None:
            print(f"  {word:12s} OOV")
            continue
        _l, sim, proto, _m = r
        noun_sims.append(sim)
        print(f"  {word:12s} nearest command verb {proto:10s} sim {sim:.2f}")
    print()
    verb_sims.sort()
    noun_sims.sort(reverse=True)
    print(f"  held-out COMMAND verbs: min sim {verb_sims[0]:.2f}, "
          f"median {verb_sims[len(verb_sims)//2]:.2f}")
    print(f"  NON-verbs:              max sim {noun_sims[0]:.2f}, "
          f"median {noun_sims[len(noun_sims)//2]:.2f}")
    for thr in (0.40, 0.50, 0.55, 0.60, 0.65):
        v_pass = sum(1 for s in verb_sims if s >= thr)
        n_pass = sum(1 for s in noun_sims if s >= thr)
        print(f"  threshold {thr:.2f}: {v_pass:2d}/{len(verb_sims)} verbs recognised, "
              f"{n_pass:2d}/{len(noun_sims)} non-verbs WRONGLY recognised")


if __name__ == "__main__":
    main()
