"""Prompt experiments for LLMSeg, scored against the ONE thing that matters.

The gate study (`gate_sizing.py`) found the ceiling, not a routing problem: on
159 cached rows LLMSeg fixes 6 and breaks 16, so even an oracle gate is worth
+3.8%. Routing cannot rescue that. The prompt has to make the model produce
more correct answers before where-to-call-it is an interesting question.

THE HYPOTHESIS UNDER TEST
-------------------------
FastSeg is excellent at COPYING (0 invention violations, 96.2% item precision)
and weaker at CUTTING (88.7% item-count). An 8B is the other way round —
DialogUSR measured a 28-point gap between a model's cut and copy accuracy on
exactly this task shape. The current V3 prompt asks the model to do BOTH, so
its copying mistakes (dropping "remind" in 12 of 37 rejections) throw away its
cutting wins.

    P1  v3-full      re-emit the whole decomposition        (today's prompt)
    P2  boundaries   return ONLY where to cut; FastSeg copies
    P3  count        return ONLY how many items there are
    P4  v3-surgical  v3 + "the proposal is usually right"

P2 and P3 never let the model touch the words at all, so no-loss and
no-invention violations are impossible by construction; FastSeg re-derives
action/time/tag from the model's boundaries. If the hypothesis is right, P2
keeps the 6 fixes and loses far fewer than 16.

    python -m assistant.engine.segmentation.experiments.prompt_lab --variants boundaries count
    python -m assistant.engine.segmentation.experiments.prompt_lab --limit 40      # a quick look

ONE llama job at a time. Answers are cached per (variant, text) so a killed
run is never wasted.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_S = "/tmp/seg_prompt_lab"
os.makedirs(_S, exist_ok=True)
for k, v in dict(MACALENDAR_DB=f"{_S}/c.db", MACALENDAR_MEMORY_DB=f"{_S}/m.db",
                 MACALENDAR_VOCAB=f"{_S}/v.json", MACALENDAR_CATEGORIES=f"{_S}/g.json",
                 MACALENDAR_TRACE_BUS=f"{_S}/t.jsonl",
                 MACALENDAR_NO_WARMUP="1",
                 MACALENDAR_LLM_PRIORITY="background").items():
    os.environ.setdefault(k, v)

from assistant.engine.segmentation.llmseg import llmseg
from assistant.engine.segmentation.experiments import score as sc              # noqa: E402
from assistant.engine.segmentation.fastseg.fastseg import (fastseg, assign_times,  # noqa: E402
                                    tag as fs_tag, _tidy)
from assistant.engine.segmentation.experiments.run_board import (assign_splits,          # noqa: E402
                                      stratified_sample)

_CACHE = os.path.join(_HERE, "experiments", "runs", "prompt_lab_cache.jsonl")


def _cache_load() -> dict:
    out = {}
    try:
        with open(_CACHE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                out[(rec["variant"], rec["text"])] = rec["raw"]
    except OSError:
        pass
    return out


def _cache_put(variant: str, text: str, raw: str) -> None:
    with open(_CACHE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"variant": variant, "text": text, "raw": raw}) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# ---------------------------------------------------------------------------
# P2 / P3 — the model only says WHERE to cut. FastSeg does every other job.
# ---------------------------------------------------------------------------

_BOUNDARY_PROMPT = """Split this command into the separate things the speaker asked for.

COMMAND: {text}

An "ask" is ONE independent thing to do. Split ONLY between separate asks.
Do NOT split:
  - two people joined by "and"   ("meeting with Sam and Alex" = ONE)
  - two verbs sharing one object ("wash and fold the laundry" = ONE)
  - two things bought together   ("buy milk and eggs" = ONE)
  - a time range                 ("from 3 to 4pm" = ONE)
Do split:
  - separate activities, even without a verb
    ("gym at 7 and dinner at 9" = TWO)

Copy each piece EXACTLY as it appears in the command, changing nothing and
leaving out nothing except the joining word. Output a JSON list of the pieces
and nothing else.

Example: "gym at 7 and dinner at 9"
["gym at 7", "dinner at 9"]"""

_COUNT_PROMPT = """How many separate things does this command ask for?

COMMAND: {text}

Two people joined by "and" is ONE thing. Two verbs sharing one object is ONE
thing. Two items bought together is ONE thing. A time range is ONE thing.
Two separate activities are TWO things, even if the second has no verb.

Output only a single digit and nothing else."""

_SURGICAL_EXTRA = """
IMPORTANT: the proposal above is usually CORRECT. Change it only where you are
certain it is wrong. Never delete a word the speaker said - "remind me to buy
milk" keeps "remind me to". If you are unsure, output the proposal unchanged."""


# ---------------------------------------------------------------------------
# P5 — word-index boundaries. `boundaries` (P2) asked the model to COPY each
# piece verbatim and still came back with 4 NO-INVENTION violations that
# should have been impossible if the copy were exact — proof that an 8B
# retyping a span is not reliable even when told "copy exactly, change
# nothing". `count` (P3) never lets the model add a split, only collapse
# FastSeg's own pieces, so it structurally cannot fix an under-split, which
# is the larger of the two error modes (108 rows vs 47).
#
# This asks for neither. The model sees the command with every WORD numbered
# and outputs only the indices where a new item starts — integers, not text.
# `_pieces_from_boundaries` then slices the ORIGINAL string at those exact
# character offsets, so a piece is byte-identical to a substring of what was
# said: no-invention and no-loss are true by construction, not by
# instruction, and the model can both split an under-cut proposal and merge
# an over-cut one from the same output shape.
#
# REFUTED on the first 20-row pilot (2026-09-16), worse than every prior
# variant: item-count 85.0% -> 15.0%, fixes 0 / breaks 12. The raw replies
# were not close-but-wrong arithmetic — "i need to sync up with Jordan next
# monday" (one ask, 9 words) came back [1, 7], splitting mid-phrase with no
# relationship to the sentence's structure, on a clearly single-ask row. An
# 8B does not reliably track an absolute position in a numbered list long
# enough to use it as a real constraint — this is a DIFFERENT failure mode
# than P2's copying problem, not the same one restated, so it rules out
# absolute-index schemes generally, not just this prompt's wording.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# P6 — mark the CANDIDATE joins inline, ask a local true/false per mark. P5's
# failure was absolute position tracking over the WHOLE sentence; this asks
# nothing about position at all. Every joiner word ("and", "then", "as well
# as", ...) is a candidate split, numbered in place with a <N> marker right
# where it sits in the text the model already has to read — so answering
# "does a new ask start after <2>?" is a LOCAL judgement about the words
# either side of a mark it can see, not a lookup into a list. Usually 1-2
# marks per sentence, never the whole word count. Still copies nothing and
# invents nothing: accepted marks become cut points at the joiner's own
# character span, exactly like P5's reconstruction.
#
# `mark` (v1) shipped with the illustrative examples reusing the SAME "<1>"
# placeholder five times in the rules text, above the real marked command.
# On a 20-row pilot it looked flat (fixes 1 / breaks 1); on a 158-row
# trap-stratified read it was net -19 (exact-row 72.8% -> 60.1%), and every
# single failure inspected showed the model answering an EXTRA key that did
# not correspond to any real mark ({"1": false, "2": true} on a ONE-mark
# sentence) — evidence it was counting "<1>" occurrences across the whole
# prompt, not just the command. `interpret()` already ignored the spurious
# key safely (enumerate() over the real candidates only), so this was not a
# scoring bug, but a model primed with a miscounted task is also the one
# getting the REAL mark wrong in every inspected case. `mark2` states the
# count up front ("exactly N marks") and replaces every illustrative "<1>"
# with the word HERE, so the only numbered token in the whole prompt is the
# real command's own marks. Different variant NAME, deliberately — the cache
# is keyed by (variant, text) only, so reusing "mark" would have silently
# replayed v1's answers under a prompt that was never actually sent.
# ---------------------------------------------------------------------------

_JOIN_RE = re.compile(r"\b(and then|and also|as well as|and|then|also|plus)\b", re.I)

_MARK_PROMPT = """This command has exactly {n} mark{plural}, written as <1>{more}. Decide,
for EACH mark and only these marks, whether a NEW separate ask begins right
after it:

{marked}

An "ask" is ONE independent thing to do. A mark is TRUE when what follows is
a separate activity. A mark is FALSE when it is still the SAME ask - for
example (these use the word HERE for the join point, never a real mark):
  - two people joined by "and"   ("meeting with Sam HERE Alex" = FALSE)
  - two verbs sharing one object ("wash HERE fold the laundry" = FALSE)
  - two things bought together   ("buy milk HERE eggs" = FALSE)
  - a time range                 ("from 3 HERE 4pm" = FALSE)
A mark is TRUE for a separate activity, even without its own verb
  ("gym at 7 HERE dinner at 9" = TRUE)

Output ONLY a JSON object with EXACTLY {n} key{plural} - "1"{more_keys} - each
mapped to true or false. Output the JSON and nothing else, no explanation,
no code fence."""


def _mark_prompt(marked: str, n_marks: int) -> str:
    more = "".join(f", <{i}>" for i in range(2, n_marks + 1)) if n_marks > 1 else ""
    more_keys = "".join(f', "{i}"' for i in range(2, n_marks + 1)) if n_marks > 1 else ""
    return _MARK_PROMPT.format(marked=marked, n=n_marks,
                               plural="" if n_marks == 1 else "s",
                               more=more, more_keys=more_keys)


def _candidate_joins(text: str) -> "list[tuple[int, int]]":
    return [(m.start(), m.end()) for m in _JOIN_RE.finditer(text)]


def _mark_text(text: str, cands: "list[tuple[int, int]]") -> str:
    marked = text
    for i, (_s, e) in reversed(list(enumerate(cands, 1))):
        marked = marked[:e] + f" <{i}>" + marked[e:]
    return marked


def _pieces_from_marks(text: str, cands: "list[tuple[int, int]]",
                       verdicts: dict) -> "list[str] | None":
    if not isinstance(verdicts, dict):
        return None
    accepted = [(s, e) for i, (s, e) in enumerate(cands, 1)
                if verdicts.get(str(i)) is True]
    if not accepted:
        return [text]
    pieces = []
    prev = 0
    for s, e in accepted:
        pieces.append(text[prev:s].strip(" ,;."))
        prev = e
    pieces.append(text[prev:].strip(" ,;."))
    return [p for p in pieces if p] or None

_INDEX_PROMPT = """Split this command into the separate things the speaker asked for.

COMMAND, word by word:
{numbered}

A parser proposed splitting it into {n_proposed} piece(s):
{proposed_list}
This may be right or wrong.

An "ask" is ONE independent thing to do. Split ONLY between separate asks.
Do NOT split:
  - two people joined by "and"   ("meeting with Sam and Alex" = ONE)
  - two verbs sharing one object ("wash and fold the laundry" = ONE)
  - two things bought together   ("buy milk and eggs" = ONE)
  - a time range                 ("from 3 to 4pm" = ONE)
Do split:
  - separate activities, even without a verb
    ("gym at 7 and dinner at 9" = TWO)

Output ONLY a JSON list of the WORD NUMBERS where a NEW item begins. The
first item always starts at word 0 - never include 0. Only one item ->
output []. Output the JSON and nothing else - no explanation, no code fence.

Example: "gym at 7 and dinner at 9" is word 0:gym 1:at 2:7 3:and 4:dinner 5:at 6:9
-> [4]   (the second item, "dinner at 9", begins at word 4)"""


def _pieces_from_boundaries(text: str, boundaries) -> "list[str] | None":
    """Slice ORIGINAL characters at word offsets — never a model-retyped
    string — so a piece is always an exact substring of what was said."""
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    n = len(spans)
    if n == 0 or not isinstance(boundaries, list):
        return None
    cuts = sorted({b for b in boundaries if isinstance(b, int) and 0 < b < n})
    bounds = [0] + cuts + [n]
    pieces = [text[spans[s][0]:spans[e - 1][1]]
              for s, e in zip(bounds, bounds[1:]) if s < e]
    return pieces or None


def build(variant: str, text: str, proposal):
    if variant == "v4-full":
        return llmseg.build_prompt(text, proposal)
    if variant == "boundaries":
        return _BOUNDARY_PROMPT.format(text=text)
    if variant == "count":
        return _COUNT_PROMPT.format(text=text)
    if variant == "word-index":
        numbered = " ".join(f"{i}:{w}" for i, w in enumerate(text.split()))
        proposed_list = "\n".join(
            f"  {i + 1}. {it['action']} ({it['time']})" for i, it in enumerate(proposal)
        ) or "  (none)"
        return _INDEX_PROMPT.format(numbered=numbered, n_proposed=len(proposal),
                                    proposed_list=proposed_list)
    if variant == "mark2":
        cands = _candidate_joins(text)
        return _mark_prompt(_mark_text(text, cands), len(cands))
    base = llmseg.build_prompt(text, proposal)
    if variant == "v4-surgical":
        return base.replace("Output the CORRECT decomposition",
                            _SURGICAL_EXTRA + "\n\nOutput the CORRECT decomposition")
    return base


def _items_from_pieces(text: str, pieces: "list[str]"):
    """FastSeg's own phases 2 and 3 over someone else's cut."""
    pieces = [p for p in (q.strip() for q in pieces) if p]
    if not pieces:
        return None
    out = []
    for action, time_str in assign_times(text, pieces):
        action = _tidy(action)
        if not action:
            continue
        out.append({"action": action, "time": time_str,
                    "tag": fs_tag(action, time_str)})
    return out or None


def interpret(variant: str, raw: str, text: str, proposal):
    """Model reply -> items, per variant."""
    if variant == "count":
        m = re.search(r"\d+", raw or "")
        if not m:
            return None
        want = max(1, min(6, int(m.group())))
        if want == len(proposal):
            return proposal
        # The model only supplied a COUNT, so the only honest use of it is as
        # a stopping condition on FastSeg's own splitter. It cannot invent a
        # boundary FastSeg could not find; it can decline one it did.
        if want < len(proposal):
            merged = _items_from_pieces(text, [text])
            return merged
        return proposal
    if variant == "boundaries":
        try:
            blob = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
        except Exception:
            return None
        if not isinstance(blob, list) or not blob:
            return None
        return _items_from_pieces(text, [str(x) for x in blob])
    if variant == "word-index":
        try:
            blob = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
        except Exception:
            return None
        pieces = _pieces_from_boundaries(text, blob)
        if not pieces:
            return None
        return _items_from_pieces(text, pieces)
    if variant == "mark2":
        cands = _candidate_joins(text)
        if not cands:
            return proposal            # nothing to ask about; FastSeg stands
        try:
            blob = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        except Exception:
            return None
        pieces = _pieces_from_marks(text, cands, blob)
        if not pieces:
            return None
        return _items_from_pieces(text, pieces)
    return llmseg.parse_items(raw, proposal)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+",
                    default=["boundaries", "count", "v4-full", "v4-surgical"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=300,
                    help="trap-stratified sample size from the TRAIN pool")
    a = ap.parse_args()

    pool = [r for r in assign_splits(
        sc.load_rows(sorted(glob.glob(f"{_HERE}/datasets/*.jsonl"))))
        if r["split"] == "train"]
    # TRAP-STRATIFIED, not proportional. The first prompt slice was
    # proportional and left 13 of 44 traps EMPTY — including serial-verb,
    # two-times-one-activity and name-coordination, which are exactly the
    # shapes most likely to REFUTE a boundaries-only prompt. Measuring a
    # hypothesis on a set that excludes its failure mode is not a measurement.
    rows = stratified_sample(pool, a.sample)
    if a.limit:
        rows = rows[:a.limit]

    def exact(gold, pred):
        return (sc._bag([sc.as_item(g) for g in gold])
                == sc._bag([sc.as_item(p) for p in pred]))

    def counts_ok(gold, pred):
        return len(gold) == len(pred)

    n = len(rows)
    traps = collections.Counter(t for r in rows for t in (r.get("traps") or ["(none)"]))
    pool_traps = collections.Counter(
        t for r in pool for t in (r.get("traps") or ["(none)"]))
    hw = sum(1 for r in rows if r.get("source", "handwritten") == "handwritten")
    fs_ok = {r["text"]: exact(r["gold"], fastseg(r["text"])) for r in rows}
    fs_cut = {r["text"]: counts_ok(r["gold"], fastseg(r["text"])) for r in rows}
    print(f"rows: {n} of {len(pool)} TRAIN   traps {len(traps)}/{len(pool_traps)}"
          f"   hand-written {hw} ({hw / n:.0%})"
          f"   95% CI +/-{1.96 * (0.45 * 0.55 / n) ** 0.5:.1%}")
    print(f"  FastSeg alone   exact-row {sum(fs_ok.values()) / n:6.1%}"
          f"   item-count {sum(fs_cut.values()) / n:6.1%}\n")

    # v3's answers from the segment board are keyed by text and reused, so
    # rerunning it here costs only the rows that slice never covered.
    cache = _cache_load()
    for variant in a.variants:
        ok = fixes = breaks = unusable = skipped = cut_ok = 0
        scored = 0
        secs = 0.0
        for i, r in enumerate(rows, 1):
            text = r["text"]
            if variant == "mark2" and not _candidate_joins(text):
                # Nothing to ask about — `interpret()` would force FastSeg's
                # own answer regardless of what the model said, so asking is
                # pure wasted latency on what is usually most of the corpus.
                final, _why = llmseg.accept(text, fastseg(text), fastseg(text))
                good = exact(r["gold"], final)
                scored += 1
                ok += good
                cut_ok += counts_ok(r["gold"], final)
                continue
            raw = cache.get((variant, text))
            if raw is None:
                t0 = time.perf_counter()
                # A timeout is a hiccup, not a verdict. Retrying once and
                # then SKIPPING the row keeps the run going; the old code
                # `break`-ed and still divided by the full n, which reported
                # boundaries at 1.4% after completing 68 of 294 rows — a
                # number that looks like a catastrophic result and is really
                # an unfinished loop.
                raw = None
                for attempt in (1, 2):
                    try:
                        raw = llmseg.call_model(
                            build(variant, text, fastseg(text)), timeout=240)
                        break
                    except Exception as exc:
                        err = type(exc).__name__
                        if attempt == 2:
                            print(f"    {variant}: {err} on row {i}, skipping",
                                  flush=True)
                if raw is None:
                    skipped += 1
                    continue
                secs += time.perf_counter() - t0
                _cache_put(variant, text, raw)
                cache[(variant, text)] = raw
            items = interpret(variant, raw, text, fastseg(text))
            if items is None:
                unusable += 1
                items = fastseg(text)          # unusable reply -> keep FastSeg
            # The accept guard still applies: a variant may not overwrite a
            # proposal with something that loses or invents words.
            final, _why = llmseg.accept(text, fastseg(text), items)
            good = exact(r["gold"], final)
            scored += 1
            ok += good
            cut_ok += counts_ok(r["gold"], final)
            if good and not fs_ok[text]:
                fixes += 1
            elif fs_ok[text] and not good:
                breaks += 1
            if i % 25 == 0:
                print(f"    …{variant} {i}/{n}", flush=True)
        # Rate over rows actually SCORED, never over the intended n.
        denom = max(1, scored)
        note = "" if scored == n else f"  [INCOMPLETE {scored}/{n}]"
        print(f"  {variant:<14}  exact-row {ok / denom:6.1%}"
              f"   item-count {cut_ok / denom:6.1%}"
              f"   fixes {fixes} / breaks {breaks}"
              f"   unusable {unusable}  skipped {skipped}"
              f"   {secs / denom:.1f}s/row{note}", flush=True)


if __name__ == "__main__":
    main()
