"""What should the ONE model call be worth? Four readings of the same answer.

    python -m assistant.engine.llmjudge.experiments.quote_variants --source handcrafted
    python -m assistant.engine.llmjudge.experiments.quote_variants --source generated -n 150
    python -m assistant.engine.llmjudge.experiments.quote_variants --source generated --no-model

Gil, 2026-09-10: *"the question is also once you decide on the deterministic
part where would a llm be useful if we had to use only one llm call in the
llmjudge round."*

## The finding this board exists to price

The handcrafted board measured the shipped judge with and without the model and
the two columns were IDENTICAL, row for row, on all 32 cases — the call bought
nothing and cost nothing. Dumping what the model actually answered says why, and
it is not that the model is silent:

    title 'meeting groceries'   from "book a meeting with Sage…"  -> "meeting with Sage"
    title 'gym membership'      from "book gym session on tuesday" -> "gym session"
    title 'pick up the parcel'  from "pick up the prescription…"   -> "pick up the prescription"
    title 'dentist bill'        from "dentist appointment next…"   -> "dentist appointment"
    title 'milk bottles'        from "add milk to my shopping list" -> "milk bottles"

The model is not doing the copying task. It quotes the words behind the title
the object SHOULD have had (rows 1-4) or echoes the wrong title back as its own
evidence (row 5). Every one of those is a non-`none` answer, and `verdict.py`
asks the answer exactly one question — *is it `none`?* — so every one is
accepted.

**The evidence is in the answer and nothing reads it.** "groceries" is not in
the quote and not in the command; "bottles" is in the quote and the quote is not
in the command. This stage's founding rule is that the model EXTRACTS and
deterministic code JUDGES, and on this call the second half was never written.

## The four readings

    V0  shipped     flag only when the model answers `none`
    V1  + fabricated quote     the quote itself uses words nobody said
    V2  title grounded         every title word must be in the TRANSCRIPT
                               (`_grounded_title` semantics — NEEDS NO MODEL)
    V3  V1 + quote-widened V2  a title word in neither the quote nor the words

V2 is on the board because it is the null hypothesis with teeth: if the strict
deterministic test catches the same rows at the same price, the honest
conclusion is that the call should be DELETED, not repaired. Cycle 2 rejected
V2 once already — it flagged "gym session" produced from "gym saturday" — so the
question is whether the quote buys back that headroom, which is what V3 asks.

Reported as the usual PAIR. A stricter subject test is trivially better at
catching and trivially worse at accepting, and only both numbers separate them.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import tempfile
import time

_S = pathlib.Path(os.environ.get("JUDGE_BOARD_SCRATCH",
                                 tempfile.mkdtemp(prefix="quote_variants_")))
_S.mkdir(parents=True, exist_ok=True)
for _v, _n in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
               ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
               ("TRACE_BUS", "trace_bus.jsonl")):
    os.environ[f"MACALENDAR_{_v}"] = str(_S / _n)
os.environ["MACALENDAR_NO_WARMUP"] = "1"
os.environ["MACALENDAR_OBSERVANCE"] = "0"
for _t in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_t, "1")

STAGE = pathlib.Path(__file__).resolve().parents[1]
HAND = STAGE / "datasets" / "handcrafted.jsonl"
GEN = STAGE / "datasets" / "judge_cases.jsonl"

VARIANTS = ("V0", "V1", "V2", "V3")


def _words(text: str, stop) -> list:
    from assistant.engine.llmjudge.verdict import tokens
    return [w for w in tokens(text) if len(w) > 2 and w not in stop]


def _spoken_in(word: str, haystack: str) -> bool:
    """The project's four-character prefix stemming, applied one word at a time."""
    from assistant.engine.llmjudge.verdict import tokens
    stem = word[:4]
    return any(tk.startswith(stem) or word.startswith(tk[:4])
               for tk in tokens(haystack) if len(tk) > 2)


def extra_flag(variant: str, title: str, quote, raw: str, stop) -> bool:
    """Does this reading of the model's answer add a finding the code did not?

    `quote` is the model's words for this field: a string, None for `none`, or
    ABSENT (the sentinel) when it never answered. Absent stays "no opinion" in
    every variant — a long list is where an 8B runs out of attention, and
    reading silence as invention would charge the model's stamina to the object.
    """
    t_words = _words(title, stop)
    if not t_words:
        return False
    if variant == "V0":
        return False                       # `none` is handled by verdict.py
    if variant == "V2":
        return any(not _spoken_in(w, raw) for w in t_words)
    if quote is _ABSENT or quote is None:
        return False                       # nothing to read
    fabricated = any(not _spoken_in(w, raw) for w in _words(quote, stop))
    if variant == "V1":
        return fabricated
    return fabricated or any(
        not _spoken_in(w, raw) and not _spoken_in(w, quote) for w in t_words)


_ABSENT = object()


def _hand_cases():
    for c in (json.loads(l) for l in HAND.open() if l.strip()):
        yield c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("handcrafted", "generated"),
                    default="handcrafted")
    ap.add_argument("-n", type=int, default=0, help="0 = all")
    ap.add_argument("--split", choices=("train", "test"), default="train")
    ap.add_argument("--no-model", action="store_true",
                    help="score only the variants that need no call (V0, V2)")
    a = ap.parse_args()

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine import segmentation as _seg
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.fastrule import build
    from assistant.engine.fastrule.build import Built, build_all
    from assistant.engine.llmjudge import evidence, findings as F, render, verdict
    from assistant.engine.llmjudge.datasets.generate import CLOCK as _CLOCK
    from assistant.engine.state import EngineState, Item
    from assistant.engine.llmjudge.experiments.handcrafted_board import _object_for
    from assistant.engine.llmjudge.experiments.judge_board import _mutate, _EXPECT_ITEM

    stop = verdict._TITLE_STOP
    cfg = engine.load_config()
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    use_model = not a.no_model
    if use_model:
        try:
            _llm.call_json(cfg, "Reply with JSON.", "ping",
                           {"type": "object", "properties": {"ok": {"type": "string"}},
                            "required": ["ok"]})
        except Exception as e:
            print(f"\nABORT — the model is not reachable: {type(e).__name__}: {e}")
            return 2
    else:
        print("\n  NO MODEL — only V0 and V2 are scored; V1/V3 read an answer "
              "that was never asked for.\n")

    variants = VARIANTS if use_model else ("V0", "V2")
    planted = collections.Counter()
    caught = {v: collections.Counter() for v in variants}
    clean_n = 0
    flagged = {v: 0 for v in variants}
    examples = {v: [] for v in variants}
    unbuildable = 0
    t0 = time.time()

    if a.source == "handcrafted":
        cases = list(_hand_cases())
    else:
        cases = [json.loads(l) for l in GEN.open() if l.strip()]
        cases = [c for c in cases if c["split"] == a.split]
    if a.n:
        cases = cases[:a.n]

    with freeze_time(_CLOCK):
        for c in cases:
            if a.source == "handcrafted":
                st, item = _object_for(c, _dv, _seg, cfg, _CLOCK, build)
                want, want_item, mutation = c["expect"], "item_1", c["id"].split("-")[0]
                baseline = set()
            else:
                gi = c["item"]
                item = Item(id="item_1", kind=gi.get("kind") or "event",
                            text=gi.get("text") or c["text"], time=gi.get("time"))
                st = EngineState(raw_text=c["text"], text=c["text"], source="test")
                st.items = [item]
                try:
                    _dv.resolve_values(st, _CLOCK.date())
                except Exception:
                    pass
                res = build_all([item])[0]
                if not isinstance(res, Built):
                    unbuildable += 1
                    continue
                baseline = {f"{cl.label} = {cl.rendered} — nothing in the words said it"
                            for cl in render.unsupported_by_slots(
                                res.action, res.intent, item.slots)}
                st.items = _mutate(c, item, res.action, res.intent)
                want, mutation = c["expect"], c["mutation"]
                want_item = _EXPECT_ITEM.get(mutation, "item_1")

            produced = verdict.collect(st)
            det = [f for f in verdict.judge(st, produced, None)
                   if f.detail not in baseline]
            g = {}
            if use_model:
                g = evidence.ground_claims(
                    st, cfg, [(p.oid, p.action, p.intent, p.slots)
                              for p in produced]) or {}

            # The identity claims the DETERMINISTIC pass already cleared — the
            # only place a variant can add anything. A claim the code already
            # flagged is not re-flagged by any of them.
            already = {(f.item_id, f.type) for f in det}
            addable = []
            for p in produced:
                if (p.oid, F.UNGROUNDED_SUBJECT) in already:
                    continue
                for cl in render.claims(p.action, p.intent, p.slots):
                    if cl.needs_model and verdict._IDENTITY.match(cl.label):
                        addable.append((p.oid, cl.label, cl.raw))

            for v in variants:
                extra = [(oid, lbl, raw) for oid, lbl, raw in addable
                         if extra_flag(v, raw, g.get((oid, lbl), _ABSENT),
                                       st.raw_text, stop)]
                types = [f.type for f in det] + [F.UNGROUNDED_SUBJECT] * len(extra)
                ids = ([f.item_id for f in det]
                       + [oid for oid, _, _ in extra])
                if want is None:
                    if types:
                        flagged[v] += 1
                        if len(examples[v]) < 6 and extra:
                            examples[v].append(
                                (c.get("id", c["text"][:40]), extra[0][2],
                                 g.get((extra[0][0], extra[0][1]), _ABSENT)))
                else:
                    hit = any(t == want and i == want_item
                              for t, i in zip(types, ids))
                    if hit:
                        caught[v][mutation] += 1
            if want is None:
                clean_n += 1
            else:
                planted[mutation] += 1

    elapsed = time.time() - t0
    n = sum(planted.values()) + clean_n
    print(f"\nQUOTE-VARIANT BOARD — {a.source}"
          f"{'' if a.source == 'handcrafted' else ' ' + a.split} · {n} cases"
          f"{f' ({unbuildable} skipped)' if unbuildable else ''} · {elapsed:.0f}s\n")

    head = f"  {'mutation':<18}{'planted':>8}" + "".join(f"{v:>9}" for v in variants)
    print(head)
    for m in sorted(planted):
        row = f"  {m:<18}{planted[m]:>8}"
        for v in variants:
            row += f"{100.0 * caught[v][m] / planted[m]:>8.0f}%"
        print(row)
    tot = sum(planted.values())
    if tot:
        row = f"  {'ALL PLANTED':<18}{tot:>8}"
        for v in variants:
            row += f"{100.0 * sum(caught[v].values()) / tot:>8.0f}%"
        print(row)
    if clean_n:
        row = f"\n  {'FALSE FLAGS':<18}{clean_n:>8}"
        for v in variants:
            row += f"{100.0 * flagged[v] / clean_n:>8.1f}%"
        print(row)
        print(f"  {'…as a count':<18}{'':>8}"
              + "".join(f"{flagged[v]:>9}" for v in variants))
    print("\n  Both numbers or neither: V2 is strictly stricter than V0 and will "
          "always win\n  the first column and lose the second. The question is "
          "the exchange rate.\n")

    for v in variants:
        if examples[v]:
            print(f"  {v} over-fired on:")
            for cid, title, quote in examples[v]:
                q = "(absent)" if quote is _ABSENT else repr(quote)
                print(f"    {str(cid):<26} title {title!r}  ·  model quoted {q}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
