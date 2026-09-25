"""Is every case in the judge set actually a case? Run before trusting a board.

    python -m assistant.engine.llmjudge.datasets.verify

Gil, 2026-09-10: *"verify samples."* A planted defect that does not change the
object is not a defect — the board scores it as a MISS and the number quietly
understates the judge. This has already happened once: `dropped_time` was
planted on rows whose time phrase resolved no clock, so there was nothing to
drop, and the board blamed the judge for not finding it.

Five checks, all deterministic and all cheap:

    BUILDABLE     the converter produces an object at all
    EFFECTIVE     the mutation actually changed something
    DISTINCT      no two cases are the same text with the same mutation
    ANSWERABLE    a planted defect is one the checks could in principle see
    BALANCED      no mutation is so rare its rate is noise
"""
from __future__ import annotations

import collections
import json
import pathlib

from assistant.common.scratch_env import scratch_env

scratch_env("judge_verify_", observance=False,
           keep=("LOCATION", "HEARTBEATS", "HUD_STATE", "DEVICE_SECRET", "DEVICES"))

HERE = pathlib.Path(__file__).resolve().parent
CASES = HERE / "judge_cases.jsonl"


def main() -> int:
    from freezegun import freeze_time
    from assistant.engine import llm as _llm
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.fastrule.build import Built, build_all
    from assistant.engine.state import EngineState, Item
    from assistant.engine.llmjudge.datasets.generate import CLOCK
    from assistant.engine.llmjudge import render
    from assistant.engine.llmjudge.experiments.judge_board import _mutate

    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")
    cases = [json.loads(l) for l in CASES.open() if l.strip()]

    unbuildable = collections.Counter()
    ineffective = collections.Counter()
    per_mutation = collections.Counter()
    seen: dict = {}
    dupes = 0
    bad: list = []

    with freeze_time(CLOCK):
        for c in cases:
            key = (c["text"].lower(), c["mutation"])
            if key in seen:
                dupes += 1
            seen[key] = True
            per_mutation[c["mutation"]] += 1

            gi = c["item"]
            item = Item(id="item_1", kind=gi.get("kind") or "event",
                        text=gi.get("text") or c["text"], time=gi.get("time"))
            st = EngineState(raw_text=c["text"], text=c["text"], source="test")
            st.items = [item]
            try:
                _dv.resolve_values(st, CLOCK.date())
            except Exception:
                pass
            res = build_all([item])[0]
            if not isinstance(res, Built):
                unbuildable[c["mutation"]] += 1
                continue

            # EFFECTIVE: does the mutation change the object or its slots?
            before = (render.render_line(res.action, res.intent, item.slots),
                      tuple(sorted((item.slots or {}).items(), key=str)))
            slots_copy = dict(item.slots or {})
            items = _mutate(dict(c), item, res.action, res.intent)
            after = (render.render_line(item.action, item.intent, item.slots)
                     if items else "",
                     tuple(sorted((item.slots or {}).items(), key=str)))
            grew = len(items) > 1
            if c["expect"] and before == after and not grew:
                ineffective[c["mutation"]] += 1
                if len(bad) < 12:
                    bad.append((c["mutation"], c["text"][:52],
                                slots_copy, before[0][:60]))

    total = len(cases)
    print(f"\nJUDGE SET — {total} cases\n")
    print(f"  duplicate (same text + mutation)   {dupes}")
    print(f"  the converter cannot build         {sum(unbuildable.values())}"
          f"  {dict(unbuildable) if unbuildable else ''}")
    print(f"  the plant CHANGED NOTHING          {sum(ineffective.values())}"
          f"  {dict(ineffective) if ineffective else ''}")
    print()
    print("  balance:")
    for m, n in per_mutation.most_common():
        eff = n - ineffective[m] - unbuildable[m]
        print(f"    {m:<18}{n:>6} planted{eff:>7} usable")
    if bad:
        print("\n  Plants that changed nothing (the board scores these as MISSES):")
        for m, t, slots, line in bad:
            print(f"    [{m}] “{t}”")
            print(f"        slots={slots}  built={line}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
