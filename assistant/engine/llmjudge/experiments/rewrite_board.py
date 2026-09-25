"""Does X1' actually recover the row? The rewrite's own board.

    python -m assistant.engine.llmjudge.experiments.rewrite_board -n 80
    python -m assistant.engine.llmjudge.experiments.rewrite_board --old-prompt

Board D asks whether the LOOP pays for itself end to end. This asks the narrower
question underneath it, which is the one the prompt can actually be tuned
against: **given a row the chain got wrong, does the reworded X1' get it right
on the second pass?**

Three numbers, and all three are needed:

    produced    of the failing rows, how many yielded an HONEST rewrite at all.
                The guard refuses anything whose content words are not in the
                transcript, so a low number here is the guard working, not the
                prompt failing — and it caps everything below it.
    recovered   of those rewrites, how many then produce the right object.
                THE headline.
    still wrong the rest. A rewrite that parses cleanly into the wrong thing is
                worse than none, because it spends a round to arrive nowhere.

`--old-prompt` restores the pre-2026-09-10 instructions (clause-per-ask, no
shape rules) so the retune can be measured rather than asserted.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re

from assistant.common.scratch_env import scratch_env

scratch_env("rewrite_board_", observance=False,
           keep=("LOCATION", "HEARTBEATS", "HUD_STATE", "DEVICE_SECRET", "DEVICES"))

STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE.parent / "fastrule" / "datasets" / "fastrule_7200.jsonl"

_STOP = {"the", "a", "an", "my", "to", "for", "of", "on", "at", "in", "and"}

#: The instructions as they stood before the 2026-09-10 retune — general
#: principles, no measured shape rules. Kept verbatim so `--old-prompt` is a
#: real comparison and not a paraphrase.
_OLD_PROMPT = """You are rewriting ONE voice command so an assistant can \
read it correctly on a second attempt.

You are given the original command, a list of the parts that were ALREADY
handled, and what went wrong with the rest.

Write a NEW command containing ONLY the parts that were not handled, said more
clearly. Rules, all of them absolute:

- Use the speaker's OWN words. Every meaningful word in your answer must
  already appear in the original command.
- Never add a verb the speaker did not say. Never add a name, a time, a date or
  a place that is not in the original command.
- Do NOT mention the parts that were already handled. Leave them out entirely.
- Do NOT describe the problem, apologise, or explain. Write the command itself.
- Make the separate asks obvious: put each on its own clause joined by "and".

Return JSON: {"command": "..."}"""


def _content(s) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", str(s or "").lower())
            if w not in _STOP}


def _outcome(items):
    out = []
    for it in items:
        if it.intent is None or not it.action or it.blocked:
            continue
        title = (getattr(it.intent, "title", None)
                 or (getattr(it.intent, "titles", None) or [""])[0]
                 or getattr(it.intent, "match_title", "") or "")
        out.append((it.action, " ".join(str(title).lower().split())))
    return out


def _correct(outcome, row) -> bool:
    want_a = row["expect"].get("action", "")
    want_t = _content((row["expect"].get("slots") or {}).get("title"))
    if not outcome:
        return False
    if want_a not in {a for a, _ in outcome}:
        return False
    return not want_t or any(want_t & _content(t) for _a, t in outcome)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=int(os.environ.get("N", "80")))
    ap.add_argument("--old-prompt", action="store_true")
    ap.add_argument("--show", type=int, default=8)
    a = ap.parse_args()

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine.llmjudge import rewrite as _rw
    from assistant.engine.state import EngineState
    from assistant.engine.llmjudge.datasets.generate import CLOCK

    cfg = engine.load_config()
    try:
        _llm.call_json(cfg, "Reply with JSON.", "ping",
                       {"type": "object", "properties": {"ok": {"type": "string"}},
                        "required": ["ok"]})
    except Exception as e:
        print(f"\nABORT — the model is not reachable: {type(e).__name__}: {e}")
        return 2
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    if a.old_prompt:
        _rw._REWRITE_SYSTEM = _OLD_PROMPT

    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if r["split"] == "train"
            and r["expect"].get("action", "").startswith("create")]
    random.Random(77).shuffle(rows)
    rows = rows[:a.n]

    eng = engine.Engine()
    failing = produced = recovered = still_wrong = 0
    samples = []
    no_finding: list = []

    with freeze_time(CLOCK):
        for r in rows:
            st = EngineState(raw_text=r["text"], text=r["text"], source="test")
            try:
                eng.parse(st, cfg)
                eng.llmjudge.run(st, cfg)
            except Exception:
                continue
            if _correct(_outcome(st.items), r):
                continue                       # the chain got it right first time
            failing += 1

            # WHY a failing row yields no rewrite matters more than the count.
            # "no rewritable finding" means the judge did not notice, and no
            # amount of prompt tuning reaches it; "guard refused" means the
            # model wrote something ungrounded, which the prompt CAN fix.
            from assistant.engine.llmjudge import findings as _F
            if not _F.rewritable(st.findings):
                no_finding.append((r["text"], [f.type for f in st.findings],
                                   _outcome(st.items),
                                   (r["expect"].get("slots") or {}).get("title")))
                continue

            try:
                x1 = _rw.rewrite_for_retry(st, cfg)
            except Exception:
                x1 = None
            if not x1:
                continue
            produced += 1

            st2 = EngineState(raw_text=r["text"], text=x1, source="test")
            try:
                eng.parse(st2, cfg)
            except Exception:
                still_wrong += 1
                continue
            got2 = _outcome(st2.items)
            if _correct(got2, r):
                recovered += 1
                if len(samples) < a.show:
                    samples.append(("RECOVERED", r["text"], x1, got2))
            else:
                still_wrong += 1
                if len(samples) < a.show:
                    samples.append(("still wrong", r["text"], x1, got2))

    tag = "OLD prompt" if a.old_prompt else "RETUNED prompt"
    print(f"\nREWRITE BOARD — {tag}. {len(rows)} rows, train half.\n")
    print(f"  rows the chain got WRONG first pass   {failing}")
    print(f"  ...the judge raised NO rewritable finding for  {len(no_finding)}"
          f"  <- unreachable by any prompt")
    if failing:
        print(f"  an honest X1' was produced for       {produced}"
              f"  ({100.0*produced/failing:.0f}% — the rest the guard refused)")
    if produced:
        print(f"  ...of which RECOVERED on pass two    {recovered}"
              f"  ({100.0*recovered/produced:.0f}%)   <- the headline")
        print(f"  ...still wrong                       {still_wrong}")
    print(f"\n  net rows recovered from {len(rows)} scored: {recovered}"
          f"  ({100.0*recovered/max(1,len(rows)):.1f}% of all rows)\n")
    if no_finding:
        print("\n  Rows the judge did not flag (the ceiling on this whole loop):")
        for text, types, got, want in no_finding[:a.show]:
            print(f"    “{text[:56]}”")
            print(f"        findings {types or '[]'} · got {got} · wanted title {want!r}")
    for kind, orig, x1, got in samples:
        print(f"    [{kind}] “{orig[:54]}”")
        print(f"        X1' -> “{x1[:70]}”")
        print(f"        got -> {got}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
