"""POSITION INVARIANCE — does the engine give the same answer when the time
moves to a different place in the sentence?

    python -m scripts.invariance_board                 # all four boundaries
    python -m scripts.invariance_board --limit 200     # a quick look

Gil, 2026-09-18: *"a very important part of the project is to make sure that
we're invariant to where the time / title are located in the prompt."*

WHY THIS BOARD EXISTS
---------------------
Every row of the FastRule 7,200 set puts the time at the END — all 1,693 of
the train-half rows that carry a gold `(text, time)` split reconstruct exactly
as `text + " " + time`, and NONE are in any other order. So every number that
board has ever printed is an END-POSITION measurement, and it is structurally
blind to a parser that only works when the time comes last. A hand-written
probe found three such failures in seven tries; this replaces the probe with
a number per stage.

THE DATASET IS DERIVED, NOT WRITTEN, AND NOT COMMITTED
------------------------------------------------------
The variants are built from the dataset's OWN gold decomposition — the rows
already store `expect.item.text` (the action words) and `expect.item.time`
(the time words) separately, which is exactly the split `Item.spoken()`
reassembles. So the permutation never consults a span detector, which is the
thing under test; using one would make the instrument circular.

Generated at run time and thrown away. A committed .jsonl of derived rows is
the rot pattern CLAUDE.md warns about: the generator drifts, nothing notices,
and the stale file keeps scoring.

TRAIN HALF ONLY. The sealed 300 are never mined, and a permutation of a
sealed row is still a sealed row.

WHAT IS MEASURED, AND AGAINST WHAT
----------------------------------
Two different questions, and collapsing them is the trap:

    AGREEMENT    variant vs VARIANT — is the answer the SAME?
    CORRECTNESS  variant vs GOLD    — is the answer RIGHT?

A parser that is wrong in all three positions is perfectly invariant. So every
group of variants lands in one of three buckets:

    SOLID               they agree, and they are right
    CONSISTENTLY WRONG  they agree, and they are wrong   <- an accuracy bug,
                        counted separately so it is never mistaken for a
                        position bug
    POSITION-DEPENDENT  they disagree                    <- what this hunts

...and for the position-dependent ones, WHICH FIELD moved, because a title
that drifts with position is a different repair from a date that does.

FOUR BOUNDARIES, ONE SET OF VARIANTS
------------------------------------
The same strings are scored at each place a stage hands work on, so a loss of
invariance is attributed to a STAGE rather than inferred from the end of the
chain:

    segmentation        the WORD PARTITION — which words went to `text`,
                        which to `time`. Compared as words, not as a string,
                        because the order differs by construction.
    decompose_validate  the resolved feature slots (date, clock, recurrence)
    fastrule (stage)    the built committable object
    front door          `FastRule.run()` on the whole raw utterance — the
                        instant path, which skips all three stages above
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import string
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

_T = tempfile.mkdtemp(prefix="invariance_")
for _v in ("DB", "MEMORY_DB", "VOCAB", "CATEGORIES", "MODELS", "LABEL_FEEDBACK",
           "DEVICE_SECRET", "DEVICES", "TRACE_BUS", "LEXICON",
           "CHECKPOINTS", "UI_STATE", "LOCATION"):
    os.environ[f"MACALENDAR_{_v}"] = os.path.join(_T, _v.lower())
os.environ["MACALENDAR_CONFIG"] = os.path.join(_T, "config.yaml")
shutil.copy(ROOT / "config.example.yaml", os.environ["MACALENDAR_CONFIG"])
os.environ["MACALENDAR_NO_WARMUP"] = "1"
# BACKGROUND: this board must never make the live assistant wait on it.
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
for _b in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_b, "1")

DATA = ROOT / "assistant" / "engine" / "fastrule" / "datasets" / "fastrule_7200.jsonl"
_CLOCK = _dt.datetime(2026, 9, 9, 10, 0)

# ---------------------------------------------------------------------------
# Building the variants
# ---------------------------------------------------------------------------

#: A text ending on one of these lost its object to the split ("reschedule the
#: call with Robin and Alex TO" + "christmas day"). Moving the time anywhere
#: else leaves a sentence nobody would utter, so the row is dropped rather than
#: measured — a board scoring malformed English measures the generator.
_STRANDED = re.compile(r"\b(to|for|with|at|on|by|from|in|until|till|through)$",
                       re.IGNORECASE)

#: The one MIDDLE slot English actually offers for a time adverbial: straight
#: after an explicit reminder lead-in. "remind me ON FRIDAY to water the
#: plants" is natural; "*water ON FRIDAY the plants" is not, so rows without
#: this shape get no middle variant instead of an invented one.
_MIDDLE_SLOT = re.compile(r"^((?:can you\s+|please\s+)?remind me)\s+(to|about|that)\s+(.+)$",
                          re.IGNORECASE)


def variants(text: str, time: str) -> "list[tuple[str, str]]":
    """[(position, utterance)] — the control first, then whatever is natural."""
    text, time = text.strip(), time.strip()
    out = [("end", f"{text} {time}")]
    if _STRANDED.search(text):
        return out                       # not permutable; control only
    # BOTH front forms, because the comma is not decoration. Measured while
    # smoke-testing this board: "the 30th, wash and fold the laundry" loses the
    # date entirely (due_date None) while "the 30th wash and fold the laundry"
    # resolves it. Emitting only the comma form would have scored a PUNCTUATION
    # bug as a POSITION bug and sent the fix to the wrong place.
    out.append(("front", f"{time} {text}"))
    out.append(("front,", f"{time}, {text}"))
    m = _MIDDLE_SLOT.match(text)
    if m:
        out.append(("middle", f"{m.group(1)} {time} {m.group(2)} {m.group(3)}"))
    return out


def load_rows(limit: int = 0) -> list:
    """Train-half atomic rows whose gold `(text, time)` rebuilds the utterance."""
    rows = []
    for line in DATA.open():
        r = json.loads(line)
        if r["split"] != "train":
            continue
        e = r["expect"]
        if not e.get("atomic"):
            continue
        it = e.get("item") or {}
        txt, tm = (it.get("text") or "").strip(), (it.get("time") or "").strip()
        if not txt or not tm:
            continue
        if f"{txt} {tm}".lower().split() != r["text"].lower().split():
            continue
        rows.append(r)
        if limit and len(rows) >= limit:
            break
    return rows


# ---------------------------------------------------------------------------
# Reading each boundary into something comparable
# ---------------------------------------------------------------------------

_PUNCT = str.maketrans("", "", string.punctuation)


def _words(s: str) -> tuple:
    """Lower-cased words with punctuation stripped.

    The comma the FRONT variant needs would otherwise read as a difference,
    which would score the generator's punctuation as a parser failure.
    """
    return tuple(sorted((s or "").lower().translate(_PUNCT).split()))


#: `built_by` records WHICH code path produced the object, not what it decided.
_NOT_A_FEATURE = {"built_by"}


def snapshot(state, fast) -> dict:
    """The four comparable readings for one variant."""
    items = list(state.items or [])
    seg = tuple(sorted((_words(i.text), _words(i.time)) for i in items))
    dv = tuple(sorted(
        (i.id, tuple(sorted((k, str(v)) for k, v in (i.slots or {}).items()
                            if k not in _NOT_A_FEATURE)))
        for i in items))
    fields = ("title", "date", "start_time", "end_time", "recurrence",
              "recur_days", "recur_until", "due_date", "titles")
    stage = tuple(sorted(
        (i.action or "", tuple((f, str(getattr(i.intent, f, None)))
                               for f in fields if hasattr(i.intent, f)))
        for i in items))
    door = ("no-commit",)
    if fast and getattr(fast, "committed", None):
        door = tuple(sorted(
            (n, tuple((f, str(getattr(o, f, None)))
                      for f in fields if hasattr(o, f)))
            for n, o in (fast.intents or [])))
    return {"segmentation": seg, "decompose_validate": dv,
            "fastrule": stage, "front_door": door}


def correctness(state, row) -> "bool | None":
    """Did this variant get the two things gold states unambiguously?

    ACTION and TITLE only. The gold's date lives as a PHRASE ("this coming
    saturday"), and turning one into a day is the other board's job and its
    known ambiguity — so dates are scored here for AGREEMENT, never for
    correctness. Better two fields that mean something than four that need a
    footnote.
    """
    e = row["expect"]
    want_action = e.get("action")
    want_title = (e.get("slots", {}) or {}).get("title")
    if not want_action or not want_title:
        return None
    items = [i for i in (state.items or []) if i.action]
    if len(items) != 1:
        return False
    it = items[0]
    if it.action != want_action:
        return False
    got = getattr(it.intent, "title", None)
    if got is None:
        got = ((getattr(it.intent, "titles", None) or [None]) or [None])[0]
    return (got or "").strip().lower() == want_title.strip().lower()


# ---------------------------------------------------------------------------
# ARM 2 — MULTI-ASK. Without this the board cannot charge for UNDER-splitting.
#
# `load_rows` filters to `atomic: true`, so every gold count in arm 1 is ONE and
# a fix that wrongly MERGES two commands scores as an improvement — the variants
# agree, and agreement is what the board rewards. That blind spot was found by
# an adversarial check of a segmentation fix whose ledger turned out to be 83
# atomic over-splits fixed against 31 genuine two-ask commands collapsed; arm 1
# could see only the first number.
#
# The rows are BUILT here rather than mined, because the corpus has no per-item
# gold for its non-atomic rows: two atomic golds are joined with "and", so the
# expected count is 2 BY CONSTRUCTION and needs no labelling. The shared time is
# then moved exactly as in arm 1.
#
# OVER- and UNDER-splitting are reported SEPARATELY and never summed — the
# FastSeg board already refuses to sum them, for the same reason: they are
# different failures with different costs, and a net figure hides both.
# ---------------------------------------------------------------------------

def multi_ask_rows(rows: list, limit: int = 0) -> list:
    """[(utterance_by_position, expected_items)] built from pairs of gold rows."""
    seeds = []
    for r in rows:
        it = r["expect"]["item"]
        text, time = it["text"].strip(), it["time"].strip()
        if _STRANDED.search(text) or len(text.split()) > 6:
            continue
        seeds.append((text, time))
    out = []
    for i in range(0, len(seeds) - 1, 2):
        (a_text, a_time), (b_text, _) = seeds[i], seeds[i + 1]
        if a_text.lower() == b_text.lower():
            continue
        body = f"{a_text} and {b_text}"
        out.append({
            "expect": 2,
            "forms": {"end": f"{body} {a_time}",
                      "front": f"{a_time} {body}",
                      "front,": f"{a_time}, {body}"},
        })
        if limit and len(out) >= limit:
            break
    return out


def run_multi(rows, cfg, eng, limit: int = 0) -> None:
    from assistant.engine.state import EngineState

    cases = multi_ask_rows(rows, limit)
    print(f"\n[multi-ask] {len(cases)} built two-ask utterances "
          f"(two atomic golds joined; expected count is 2 by construction)")
    per_pos = collections.defaultdict(lambda: collections.Counter())
    for case in cases:
        for pos, utterance in case["forms"].items():
            st = EngineState(raw_text=utterance, text=utterance)
            try:
                for stage in eng.stages:
                    stage.run(st, cfg)
                n = len(st.items or [])
            except Exception:
                per_pos[pos]["error"] += 1
                continue
            if n == case["expect"]:
                per_pos[pos]["right"] += 1
            elif n < case["expect"]:
                per_pos[pos]["UNDER-split"] += 1
            else:
                per_pos[pos]["over-split"] += 1
    print("   item COUNT vs the 2 asks that were joined "
          "(under and over are NEVER summed)")
    for pos in ("end", "front", "front,"):
        c = per_pos[pos]
        tot = sum(c.values()) or 1
        print(f"      {pos:7} right {_pct(c['right'], tot)}"
              f"   UNDER {c['UNDER-split']:4}"
              f"   over {c['over-split']:4}"
              f"   err {c['error']:3}   (n={tot})")


BOUNDARIES = ("segmentation", "decompose_validate", "fastrule", "front_door")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="source rows to use (0 = all)")
    ap.add_argument("--multi-limit", type=int, default=250,
                    help="built two-ask utterances for arm 2 (0 = all)")
    a = ap.parse_args()

    from freezegun import freeze_time
    from assistant.config import load_config
    from assistant.engine import Engine
    from assistant.engine.state import EngineState
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD

    cfg = load_config()
    eng = Engine()
    fr = FastRule(RULE_THRESHOLD)
    fr.run("book gym tomorrow at 7am")        # warm outside the frozen clock

    rows = load_rows(a.limit)
    print(f"[invariance] {len(rows)} source rows "
          f"(FastRule 7,200 TRAIN half, atomic, gold (text,time) split)")

    buckets = {b: collections.Counter() for b in BOUNDARIES}
    by_position = collections.Counter()      # (position, ok) correctness
    by_position_n = collections.Counter()
    field_moves = collections.Counter()
    examples = collections.defaultdict(list)
    variant_shape = collections.Counter()
    total_variants = 0

    with freeze_time(_CLOCK):
        for n, row in enumerate(rows, 1):
            it = row["expect"]["item"]
            vs = variants(it["text"], it["time"])
            variant_shape[len(vs)] += 1
            if len(vs) < 2:
                continue                      # nothing to compare against
            seen, correct = {}, {}
            for pos, utterance in vs:
                st = EngineState(raw_text=utterance, text=utterance)
                try:
                    for stage in eng.stages:
                        stage.run(st, cfg)
                except Exception:
                    seen[pos] = {b: ("ERROR",) for b in BOUNDARIES}
                    correct[pos] = False
                    continue
                try:
                    fast = fr.run(utterance)
                except Exception:
                    fast = None
                seen[pos] = snapshot(st, fast)
                correct[pos] = correctness(st, row)
                total_variants += 1

            for pos, ok in correct.items():
                if ok is not None:
                    by_position_n[pos] += 1
                    by_position[pos] += 1 if ok else 0

            oks = [v for v in correct.values() if v is not None]
            all_right = bool(oks) and all(oks)
            for b in BOUNDARIES:
                answers = {seen[p][b] for p in seen}
                if len(answers) > 1:
                    buckets[b]["position-dependent"] += 1
                    if b == "fastrule" and len(examples["moved"]) < 12:
                        examples["moved"].append(
                            (row["text"], {p: seen[p][b] for p in seen}))
                elif all_right:
                    buckets[b]["solid"] += 1
                elif oks:
                    buckets[b]["consistently-wrong"] += 1
                else:
                    buckets[b]["agree (unscored)"] += 1

            # which FIELD moved, read off the built object
            ans = {p: seen[p]["fastrule"] for p in seen}
            if len({str(v) for v in ans.values()}) > 1:
                base = ans.get("end")
                for p, v in ans.items():
                    if p == "end" or v == base:
                        continue
                    field_moves.update(_diff_fields(base, v))

            if n % 200 == 0:
                print(f"  ... {n}/{len(rows)} rows, {total_variants} variants",
                      flush=True)

    _report(rows, buckets, by_position, by_position_n, field_moves,
            variant_shape, examples, total_variants)
    with freeze_time(_CLOCK):
        run_multi(rows, cfg, eng, a.multi_limit)
    return 0


def _diff_fields(base, other) -> list:
    """Which named fields differ between two `fastrule` snapshots."""
    if not base or not other:
        return ["<item count>"]
    if len(base) != len(other):
        return ["<item count>"]
    out = []
    for (a_action, a_fields), (b_action, b_fields) in zip(base, other):
        if a_action != b_action:
            out.append("action")
        da, db = dict(a_fields), dict(b_fields)
        for k in set(da) | set(db):
            if da.get(k) != db.get(k):
                out.append(k)
    return out or ["<other>"]


def _pct(n, d):
    return f"{100.0 * n / d:5.1f}%" if d else "    —"


def _report(rows, buckets, by_position, by_position_n, field_moves,
            variant_shape, examples, total_variants):
    print()
    print("=" * 68)
    print("POSITION INVARIANCE — the time moved, the meaning did not")
    print("=" * 68)
    print(f"source rows {len(rows)}  ·  variants scored {total_variants}")
    for k in sorted(variant_shape):
        print(f"   {variant_shape[k]:5} rows produced {k} variant(s)")
    print()
    print("PER BOUNDARY  (a group = one source row's variants)")
    print(f"   {'':22}{'solid':>9}{'consist.wrong':>15}{'POSITION-DEP':>14}")
    for b in BOUNDARIES:
        c = buckets[b]
        tot = sum(c.values()) or 1
        print(f"   {b:22}{_pct(c['solid'], tot):>9}"
              f"{_pct(c['consistently-wrong'], tot):>15}"
              f"{_pct(c['position-dependent'], tot):>14}"
              f"   (n={tot})")
    print()
    print("CORRECTNESS BY POSITION  (action + title vs gold)")
    for p in ("end", "front", "front,", "middle"):
        if by_position_n[p]:
            print(f"   time at {p:8} {_pct(by_position[p], by_position_n[p])}"
                  f"   (n={by_position_n[p]})")
    print("   'end' is the control — every gold row is written that way.")
    print()
    if field_moves:
        print("WHICH FIELD MOVES  (among groups whose built object differs)")
        for f, n in field_moves.most_common(10):
            print(f"   {n:5}  {f}")
    if examples["moved"]:
        print()
        print("EXAMPLES — the built object changed with position")
        for text, ans in examples["moved"][:6]:
            print(f"   {text!r}")
            for p, v in ans.items():
                print(f"       {p:6} {str(v)[:120]}")


if __name__ == "__main__":
    sys.exit(main())
