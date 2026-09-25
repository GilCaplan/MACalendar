"""STAGE 1 — the ISOLATION board. Does LLMJudge catch what is actually wrong?

    python -m assistant.engine.llmjudge.experiments.judge_board            # train, 120 cases
    python -m assistant.engine.llmjudge.experiments.judge_board -n 300
    python -m assistant.engine.llmjudge.experiments.judge_board --split test   # SEALED

Nothing upstream is in the path: each case is a gold Item, converted by the real
`fastrule.build`, then MUTATED in one known way. So a miss here is this stage's,
and only this stage's.

## The metric is a PAIR, and neither half means anything alone

    catch rate       flagged / planted   — on the mutated cases
    false-flag rate  flagged / clean     — on the untouched ones

A judge that accepts everything scores 0 / 0 and looks harmless; one that rejects
everything scores 100 / 100 and looks vigilant. Both are useless, and only the
pair separates them from a judge that works. Reported per mutation, because the
mutations do not fail together: two of them are caught deterministically from
`item.slots` with no model at all, and pooling those with the model-dependent
ones would hide exactly the number worth knowing.

**COLLATERAL is reported, not scored.** A mutated object legitimately produces
other findings — replacing a title with "Event" also breaks the coverage match,
so a `missing` follows the planted `ungrounded_subject`. That is the machinery
working, not a defect, so it is counted and shown rather than charged against
either rate.

Train half only by default; `--split test` is a sealed read that prints
aggregates and no row detail, the same rule as every other board here.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import time

from assistant.common.scratch_env import scratch_env

# Scratch stores, background priority and the BLAS thread pin (safe to run
# WHILE the test suite runs, which already pins itself) all come from the one
# helper now; see its module header for why each matters.
_S = pathlib.Path(scratch_env(
    "judge_board_", observance=False, dir=os.environ.get("JUDGE_BOARD_SCRATCH"),
    keep=("MODELS", "LABEL_FEEDBACK", "HEARTBEATS", "HUD_STATE",
         "DEVICE_SECRET", "DEVICES", "LOCATION")))

# In experiments/, parents[1] is the STAGE folder (the CLAUDE.md ROOT trap).
STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE / "datasets" / "judge_cases.jsonl"


def _mutate(case: dict, item, action: str, intent):
    """Plant the case's defect. Returns the item list the judge will see.

    Each mutation is the code form of a defect this engine has actually shipped
    or provably can: a generic title (the event called "event"), a fabricated
    title (cycle 7), a value present on the object that `decompose_validate`
    never resolved (the pydantic fill), an object nobody asked for, and an ask
    with nothing built for it.
    """
    from assistant.engine.state import Item

    name = case["mutation"]
    item.action, item.intent = action, intent

    if name == "clean":
        return [item]
    if name in ("generic_title", "invented_title", "near_miss_title"):
        plant = case["generic_title"] if name == "generic_title" else case["plant_title"]
        # PLANT ON WHICHEVER IDENTITY FIELD THE OBJECT ACTUALLY HAS.
        #
        # This used to set `intent.title` unconditionally, which does nothing on
        # a target-taking operation — `update_event`, `delete_todo` and friends
        # carry `match_title`, and `title` is a field they never read. So 92 of
        # the planted title defects were NO-OPS, the board scored every one of
        # them as a MISS, and the deterministic checks looked far worse than
        # they are (`datasets/verify.py`, 2026-09-10).
        #
        # Planting on `match_title` is not a compromise either: a generic TARGET
        # on a mutation is the defect Gatekeeper was built for, so this widens
        # what the set covers rather than working around anything.
        if getattr(intent, "titles", None):
            intent.titles = [plant] + list(intent.titles)[1:]
        elif getattr(intent, "match_title", None) is not None:
            try:
                intent.match_title = plant
            except Exception:
                return [item]
        else:
            try:
                intent.title = plant
            except Exception:
                return [item]
        return [item]
    if name in ("dropped_date", "dropped_time"):
        # The object keeps the value; `item.slots` forgets it ever resolved one.
        # That is exactly the production shape of an invented when — pydantic's
        # `fill_defaults` stamps a date and a clock the moment the object
        # exists, whether or not anybody said either.
        item.slots.pop("date" if name == "dropped_date" else "start_time", None)
        return [item]
    if name == "unrelated_object":
        # An object NOTHING in the words supports — no title, no when. What
        # `extra` used to mean, now asked per-object instead of via an ask list.
        from assistant.actions.calendar.intent import CalendarIntent
        extra = Item(id="item_2", kind="event", text=case["plant_title"],
                     slots={}, action="create_event",
                     intent=CalendarIntent(title=case["plant_title"]))
        return [item, extra]
    return [item]


#: Which object the planted finding should land on. Everything lands on the one
#: object that was corrupted, except `unrelated_object`, which is a SECOND
#: object added beside an untouched one.
_EXPECT_ITEM = {"unrelated_object": "item_2"}


def main() -> int:
    ap = argparse.ArgumentParser()
    # DEFAULT TO THE WHOLE SPLIT when no model is in the path. Gil, 2026-09-10:
    # *"i would check on thousands of rows especially deterministic calls which
    # are quick… llm just test on a few since it is very slow."* The
    # deterministic judge does 900 cases in seconds; capping it at 120 out of
    # habit was throwing away confidence that costs nothing.
    ap.add_argument("-n", type=int, default=int(os.environ.get("N", "0")),
                    help="0 = every case in the split (the default when the "
                         "grounding pass is off)")
    ap.add_argument("--split", choices=("train", "test"), default="train")
    ap.add_argument("--show", type=int, default=6,
                    help="failing rows to print (train only; test prints none)")
    a = ap.parse_args()

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.fastrule.build import Built, build_all
    from assistant.engine.llmjudge import render, verdict
    from assistant.engine.state import EngineState, Item
    # The clock belongs to the DATA, not to this run: a case whose plant depends
    # on "the day after tomorrow" resolving to a clock time is only valid at the
    # moment it was generated. So it is imported from the dataset rather than
    # kept here, where the two could drift apart silently.
    from assistant.engine.llmjudge.datasets.generate import CLOCK as _CLOCK

    cfg = engine.load_config()
    # Warm the rule parser OUTSIDE the frozen clock: building spaCy's pipeline
    # under freezegun raises, and the whole run would then read "converts
    # nothing" when the truth is "never got a parser".
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    # THE MODEL MUST BE THERE, and the board REFUSES to run without it.
    #
    # 2026-09-10: Ollama died mid-session and this board reported a full table
    # in 2 SECONDS — every deterministic check at 100%, `near_miss_title` at
    # 5.3%, and not one model call made. The numbers looked like a result and
    # were an artefact, which is the exact trap CLAUDE.md warns about ("before
    # trusting any board, run it"). A board that degrades quietly is worse than
    # one that crashes: the crash costs a minute, the quiet number costs a
    # decision.
    # NO MODEL PING ANY MORE, and the abort it guarded went with it. The judge
    # makes no model call, so this board cannot silently degrade to
    # "deterministic only" — deterministic only is now the whole of it. The
    # ping stays in the project's memory as the 2026-09-10 lesson: a board
    # reported a full table in 2 SECONDS with Ollama dead and the numbers looked
    # like a result. See `retired/llmjudge-grounding-call/README.md`.

    cases = [json.loads(l) for l in DATA.open() if l.strip()]
    cases = [c for c in cases if c["split"] == a.split]
    limit = a.n or len(cases)
    cases = cases[:limit]

    planted = collections.Counter()      # per mutation: how many were planted
    caught = collections.Counter()       # …and how many the judge found
    collateral = collections.Counter()   # other findings on a mutated case
    clean_n = clean_flagged = 0
    unbuildable = 0
    pre_existing: set = set()            # doubts the object already carried
    misses: list = []
    t0 = time.time()

    with freeze_time(_CLOCK):
        for c in cases:
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
                continue                 # the converter declined; not a judge case

            # THE BASELINE, taken BEFORE the mutation and for free.
            #
            # "clean" does not mean "flawless": an all-day ask resolves to no
            # start_time slot, and `CalendarIntent.fill_defaults` then stamps the
            # current hour — so the object really does assert a 10:00 nobody
            # said, and the judge is RIGHT to say so. Counting that as a false
            # flag would score the judge down for being correct.
            #
            # So every rate here is a DELTA against what the unmutated object
            # already produced. The slot findings are deterministic, so the
            # baseline costs no model call — which is the only reason this is
            # affordable at all.
            baseline = {f"{cl.label} = {cl.rendered} — nothing in the words said it"
                        for cl in render.unsupported_by_slots(
                            res.action, res.intent, item.slots)}
            pre_existing.update(baseline)

            st.items = _mutate(c, item, res.action, res.intent)

            produced = verdict.collect(st)
            found = [f for f in verdict.judge(st, produced)
                     if f.detail not in baseline]

            want = c["expect"]
            if want is None:
                clean_n += 1
                if found:
                    clean_flagged += 1
                    if len(misses) < 40:
                        misses.append(("FALSE FLAG", c, [f.type for f in found],
                                       found[0].detail))
                continue

            planted[c["mutation"]] += 1
            want_item = _EXPECT_ITEM.get(c["mutation"], "item_1")
            hit = [f for f in found if f.type == want
                   and (want_item is None or f.item_id == want_item)]
            if hit:
                caught[c["mutation"]] += 1
                collateral[c["mutation"]] += len(found) - len(hit)
            else:
                if len(misses) < 40:
                    misses.append(("MISS", c, [f.type for f in found],
                                   found[0].detail if found else "(no findings)"))

    elapsed = time.time() - t0
    n_scored = sum(planted.values()) + clean_n
    print(f"\nLLMJUDGE ISOLATION BOARD — {a.split} half, {n_scored} cases "
          f"({unbuildable} skipped: the converter declined) · {elapsed:.0f}s\n")
    print(f"  {'mutation':<16}{'planted':>8}{'caught':>8}{'catch rate':>13}"
          f"{'collateral':>12}")
    for m in sorted(planted):
        rate = 100.0 * caught[m] / planted[m]
        print(f"  {m:<16}{planted[m]:>8}{caught[m]:>8}{rate:>12.1f}%"
              f"{collateral[m]:>12}")
    tot_p, tot_c = sum(planted.values()), sum(caught.values())
    if tot_p:
        print(f"  {'ALL PLANTED':<16}{tot_p:>8}{tot_c:>8}"
              f"{100.0 * tot_c / tot_p:>12.1f}%")
    print()
    if clean_n:
        print(f"  false-flag rate   {clean_flagged}/{clean_n} = "
              f"{100.0 * clean_flagged / clean_n:.1f}%  "
              f"(clean objects the judge complained about)")
    print("\n  Both numbers or neither: always-accept wins the second, "
          "always-reject wins the first.")
    if pre_existing:
        print(f"\n  ({len(pre_existing)} distinct pre-existing doubts were "
              f"subtracted as baseline — objects that already asserted a value\n"
              f"   the words never gave, most of them an all-day ask stamped with "
              f"a clock time.\n   That is a DECOMPOSE_VALIDATE finding, not this "
              f"stage's: see ARCHITECTURE.md.)")
    print()

    if a.split == "train" and a.show and misses:
        print("  Failing rows (train only — the test half never shows detail):")
        for kind, c, types, detail in misses[:a.show]:
            print(f"    [{kind}] {c['mutation']:<15} “{c['text'][:58]}”")
            print(f"        got {types or '[]'} — {detail[:88]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
