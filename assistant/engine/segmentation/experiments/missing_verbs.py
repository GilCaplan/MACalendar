"""Which command verbs does REAL speech use that no lexicon knows?

    python -m assistant.engine.segmentation.experiments.missing_verbs

The refuted alternatives (§6: keyword head, structural head, word vectors)
all lost to the hand lexicons; the adversarial test (§0c) showed the
lexicons' weakness is COVERAGE, not mechanism. So the honest next step is to
widen them — but from evidence of what people actually say, not from the
generated corpus (whose vocabulary IS the lexicons, so mining it can only
find what is already there).

Three sources, in order of how real they are:

  1. `dataset/inputs/history_3000.json` — HWU-64 (Liu et al., IWSDS 2019,
     CC BY 4.0): 3,000 utterances written by real people for a smart
     assistant, calendar and list domains. Public, so examples may be
     quoted. The sealed 300 in `test_split.json` are EXCLUDED — never mined.
  2. `~/.assistant_tools/nlu_memory.db` — the author's own commands, read
     read-only. Per `dataset/realspeech/REALSPEECH.md`'s privacy rule, no
     utterance is stored, printed or quoted: only LEMMA COUNTS leave this
     function. `source='test'` rows are dropped (scripts, not speech).
  3. `assistant/engine/fastrule/datasets/fastrule_7200.jsonl` train half —
     template-rendered, so its vocabulary is mostly the lexicons' own, but
     it is what FastRule's "router had no entry" deferrals are made of.

A verb counts as a candidate only where it is USED AS AN ASK: the ROOT
with no subject or a first/second-person one, a complement of a framing
verb ("remind me to X", "i need to X"), or a coordinated verb. A verb that
merely appears ("is this week a payday week") does not.

Output is a ranked table: lemma · count per source · sample utterances
(public sources only). Nothing here decides a family — that is done by
hand from the examples, then verified live, exactly as the tips were.
"""
from __future__ import annotations

import collections
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

for _k, _v in (("MACALENDAR_DB", "/tmp/mv.db"), ("MACALENDAR_VOCAB", "/tmp/mv_v.json"),
               ("MACALENDAR_CATEGORIES", "/tmp/mv_c.json"),
               ("MACALENDAR_TRACE_BUS", "/tmp/mv_bus.jsonl"),
               ("MACALENDAR_NO_WARMUP", "1"), ("OMP_NUM_THREADS", "1"),
               ("MACALENDAR_LLM_PRIORITY", "background")):
    os.environ.setdefault(_k, _v)
# NOT MACALENDAR_MEMORY_DB: the real memory is the point, opened read-only.

from assistant.engine.segmentation.fastseg.fastseg import (                    # noqa: E402
    _CALENDAR_VERBS, _PREAMBLE, _TASK_VERBS)
from assistant.intent.rule_parser import INTENT_MAP                            # noqa: E402

KNOWN = set(_TASK_VERBS) | set(_CALENDAR_VERBS) | {v for v, _ in INTENT_MAP}
#: Auxiliaries, modals and framing verbs — never an ask by themselves.
NOT_ASKS = set(_PREAMBLE) | {
    "be", "do", "have", "can", "could", "will", "would", "should", "may",
    "might", "must", "shall", "let", "need", "want", "like", "get", "go",
    "know", "think", "say", "tell", "ask", "mean", "try", "use", "make",
    "take", "give", "put", "keep", "help", "see", "look", "find", "come",
    "seem", "start", "stop", "wonder", "remember", "forget",
}
ASK_SUBJECTS = {"i", "you", "we", "me", "us", "let", "'s", "please"}


def _hwu_rows() -> list[str]:
    with open(os.path.join(_ROOT, "dataset", "inputs", "history_3000.json")) as fh:
        rows = [r["text"] for r in json.load(fh)["rows"]]
    with open(os.path.join(_ROOT, "dataset", "inputs", "test_split.json")) as fh:
        sealed = {r[0] if isinstance(r, list) else r for r in json.load(fh)["rows"]}
    kept = [t for t in rows if t not in sealed]
    # Every sealed text must be present (or the split file drifted from the
    # pool); MORE rows than 300 may go, because one sealed text is duplicated
    # in the pool (2,999 unique of 3,000) and a sealed text is excluded
    # wherever it appears.
    missing = [t for t in sealed if t not in rows]
    assert not missing, f"{len(missing)} sealed rows not found in the pool"
    return kept


def _memory_texts() -> list[str]:
    """The author's real commands, read-only. Returned ONLY to the counter
    below, which reduces them to lemma counts; nothing else sees them."""
    path = os.path.expanduser("~/.assistant_tools/nlu_memory.db")
    if not os.path.exists(path):
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [t for (t,) in con.execute(
            "SELECT transcript FROM examples WHERE source != 'test' AND transcript != ''")]
    finally:
        con.close()


def _fastrule_train_rows() -> list[str]:
    path = os.path.join(_ROOT, "assistant", "engine", "fastrule", "datasets",
                        "fastrule_7200.jsonl")
    out = []
    with open(path) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("split") == "train":
                out.append(r["text"])
    return out


def _ask_verbs(doc):
    """Lemmas of the verbs the utterance ASKS with — see the module docstring."""
    out = []
    for tok in doc:
        if tok.pos_ not in ("VERB", "AUX") and not (tok.i == 0 and tok.pos_ in ("NOUN", "PROPN")):
            continue
        lemma = (tok.lemma_ or tok.text).lower()
        if lemma in NOT_ASKS or len(lemma) < 3 or not lemma.isalpha():
            continue
        if tok.dep_ == "ROOT":
            subj = [c for c in tok.children if c.dep_ in ("nsubj", "nsubjpass")]
            if subj and subj[0].lower_ not in ASK_SUBJECTS:
                continue
            out.append(lemma)
        elif tok.dep_ in ("xcomp", "ccomp", "conj", "advcl", "dep") and tok.pos_ == "VERB":
            out.append(lemma)
        elif tok.i == 0:
            out.append(lemma)
    return out


def main() -> None:
    import spacy
    nlp = spacy.load("en_core_web_sm")
    sources = {
        "hwu64": _hwu_rows(),
        "memory": _memory_texts(),
        "fastrule": _fastrule_train_rows(),
    }
    counts: dict[str, collections.Counter] = {s: collections.Counter() for s in sources}
    examples: dict[str, list] = collections.defaultdict(list)
    for name, texts in sources.items():
        for doc in nlp.pipe(texts, batch_size=64):
            for lemma in set(_ask_verbs(doc)):
                if lemma in KNOWN:
                    continue
                counts[name][lemma] += 1
                if name != "memory" and len(examples[lemma]) < 3:
                    examples[lemma].append(doc.text.strip()[:70])

    total = collections.Counter()
    for c in counts.values():
        total.update(c)
    print(f"sources: hwu64 {len(sources['hwu64'])} rows (sealed excluded) · "
          f"memory {len(sources['memory'])} real rows (counts only) · "
          f"fastrule {len(sources['fastrule'])} train rows")
    print(f"lexicons know {len(KNOWN)} verbs; {len(total)} ask-verb lemmas outside them\n")
    print(f"{'lemma':14s} {'hwu':>4s} {'mem':>4s} {'fr':>4s}   examples (public sources only)")
    print("-" * 100)
    for lemma, _n in total.most_common(60):
        ex = " | ".join(examples[lemma][:2])
        print(f"{lemma:14s} {counts['hwu64'][lemma]:4d} {counts['memory'][lemma]:4d} "
              f"{counts['fastrule'][lemma]:4d}   {ex}")
    mem_only = [(l, n) for l, n in counts["memory"].most_common() if l not in counts["hwu64"]]
    if mem_only:
        print("\nseen ONLY in the author's real commands (counts only, no text):")
        print("  " + ", ".join(f"{l}×{n}" for l, n in mem_only[:30]))


if __name__ == "__main__":
    main()
