"""The HANDCRAFTED board — 32 cases written to separate the model from the code.

    python -m assistant.engine.llmjudge.experiments.handcrafted_board            # both
    python -m assistant.engine.llmjudge.experiments.handcrafted_board --det-only # no model

Gil, 2026-09-10: *"for the llm part i think handcraft a few but meaningful
prompts to test the llm judge version with a llm call / then the deterministic
can test also on handcrafted and a bigger set created."*

## Why a hand-written set exists next to a 900-case generated one

The generated set is built by MUTATING a gold item, so every case is a defect
this generator knows how to make. That is the right instrument for a catch rate
and the wrong one for the question the LLM call has to answer, because the
generator cannot write the case that is hardest for code and easiest for a
model: a title that is CORRECT but shares no word with the transcript
("ring my mother" -> "call mom"), and a title that is GROUNDED but amputated
("i need to talk to Quinn" -> "quinn").

Both of those are invisible to every deterministic test in `verdict.py` —
`names_nothing_spoken` says the first is a fabrication and the second is fine,
and it is wrong twice. They are hand-written here because they have to be.

## The object is CONSTRUCTED, not parsed

Each row names the action and the identity field directly, and the board builds
that object with FastRule's own `_new_intent`. Nothing upstream can move the
answer: if the chain would have produced a different title, that is a
segmentation or FastRule result and belongs on their boards, not this one.

The temporal SLOTS still come from the real `decompose_validate` on the real
text, because the slot check is only meaningful against an honest resolution —
except where a row overrides `slots` on purpose, which is how the
`unsupported_field` cases are written.

## Three columns, and the middle one is the whole question

    DET     the deterministic checks alone (grounding=None)
    +LLM    the same, plus the one grounding call
    delta   what that call bought, case by case

A case where both agree costs the call for nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import tempfile
import time

_S = pathlib.Path(os.environ.get("JUDGE_BOARD_SCRATCH",
                                 tempfile.mkdtemp(prefix="handcrafted_")))
_S.mkdir(parents=True, exist_ok=True)
for _v, _n in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
               ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
               ("TRACE_BUS", "trace_bus.jsonl")):
    os.environ[f"MACALENDAR_{_v}"] = str(_S / _n)
os.environ["MACALENDAR_NO_WARMUP"] = "1"
# BACKGROUND traffic: this yields the model to the live assistant between
# every call (assistant/model_protocol.py). Without it a board and a voice
# command are indistinguishable to ollama, and a trivial live call measured
# 2.0s -> 42.5s -> 43.9s behind a running board (2026-09-10).
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
os.environ["MACALENDAR_OBSERVANCE"] = "0"
for _t in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_t, "1")

STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE / "datasets" / "handcrafted.jsonl"


def _object_for(case, _dv, _seg, cfg, _CLOCK, build):
    """The case's object, with honest slots and a constructed intent.

    The WHEN comes through the real chain and the WHAT does not, which is the
    split this board needs. `decompose_validate.resolve_values` resolves from
    `Item.time` — the time reference as SPOKEN, which SEGMENTATION separates
    out — so a board that skips segmentation hands it `time=None` and every
    case comes back with the bare date floor and no clock. That is not a
    conservative approximation: it silently turns every row into "the words
    gave no time", and `unsupported_field` then fires on eight clean cases
    that named a time out loud (measured here, first run, 2026-09-10).
    """
    from assistant.engine.state import EngineState, Item

    action = case["action"]
    kind = "task" if "todo" in action else ("review" if "query" in action else "event")
    st = EngineState(raw_text=case["text"], text=case["text"], source="test")
    try:
        _seg.run(st, cfg)
    except Exception:
        st.items = []
    spoken_time = st.items[0].time if st.items else None
    item = Item(id="item_1", kind=kind, text=case["text"], time=spoken_time)
    st.items = [item]
    try:
        _dv.resolve_values(st, _CLOCK.date())
    except Exception:
        pass
    if "slots" in case:
        item.slots = dict(case["slots"])          # a deliberate override
    values, _ = build._value_kwargs(action, item.slots)

    titles = case.get("titles")
    head = (titles[0] if titles else
            case.get("title") or case.get("match_title") or "")
    intent = build._new_intent(action, head, [], values)
    if titles and getattr(intent, "titles", None) is not None:
        intent.titles = list(titles)
        try:
            intent.quantities = [1] * len(titles)
        except Exception:
            pass
    item.action, item.intent = action, intent
    return st, item


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--det-only", action="store_true",
                    help="skip the model column entirely")
    a = ap.parse_args()

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.fastrule import build
    from assistant.engine import segmentation as _seg
    from assistant.engine.llmjudge import verdict
    from assistant.engine.llmjudge.datasets.generate import CLOCK as _CLOCK

    cfg = engine.load_config()
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    use_llm = False   # the call is retired; the column is kept as history
    if use_llm:
        # The same ABORT the isolation board carries, for the same reason: a
        # board that degrades quietly to "deterministic only" reports a number
        # that looks like a result and is an artefact.
        try:
            _llm.call_json(cfg, "Reply with JSON.", "ping",
                           {"type": "object", "properties": {"ok": {"type": "string"}},
                            "required": ["ok"]})
        except Exception as e:
            print(f"\nABORT — the model is not reachable: {type(e).__name__}: {e}")
            return 2

    cases = [json.loads(l) for l in DATA.open() if l.strip()]
    rows, t0 = [], time.time()

    with freeze_time(_CLOCK):
        for c in cases:
            st, item = _object_for(c, _dv, _seg, cfg, _CLOCK, build)
            produced = verdict.collect(st)

            det = [f.type for f in verdict.judge(st, produced)]
            rows.append((c, det, det))

    elapsed = time.time() - t0

    def score(got, want):
        if want is None:
            return "OK" if not got else "FALSE FLAG"
        return "HIT" if want in got else "MISS"

    print(f"\nHANDCRAFTED JUDGE BOARD — {len(rows)} cases · {elapsed:.0f}s"
          f"{'' if use_llm else ' · DETERMINISTIC ONLY'}\n")
    print(f"  {'id':<9}{'expected':<20}{'DET':<13}{'+LLM':<13}  command")
    for c, det, llm in rows:
        want = c["expect"]
        sd, sl = score(det, want), score(llm, want)
        mark = "  " if sd == sl else ("↑ " if sl in ("HIT", "OK") else "↓ ")
        print(f"  {c['id']:<9}{(want or '(clean)'):<20}{sd:<13}"
              f"{(sl if use_llm else '—'):<13}{mark}“{c['text'][:44]}”")

    print()
    for label, col in (("DET  ", 1), ("+LLM ", 2)):
        if col == 2 and not use_llm:
            continue
        hit = sum(1 for c, d, l in rows
                  if c["expect"] and score((d, l)[col - 1], c["expect"]) == "HIT")
        planted = sum(1 for c, _, _ in rows if c["expect"])
        ff = sum(1 for c, d, l in rows
                 if not c["expect"] and score((d, l)[col - 1], None) == "FALSE FLAG")
        clean = sum(1 for c, _, _ in rows if not c["expect"])
        print(f"  {label} catch {hit}/{planted} = {100.0 * hit / planted:.0f}%"
              f"   ·   false flags {ff}/{clean} = {100.0 * ff / clean:.0f}%")

    if use_llm:
        gained = [c["id"] for c, d, l in rows
                  if score(d, c["expect"]) != "HIT" and score(l, c["expect"]) == "HIT"]
        lost = [c["id"] for c, d, l in rows
                if score(d, c["expect"]) == "OK" and score(l, c["expect"]) == "FALSE FLAG"]
        print(f"\n  the one call BOUGHT   {gained or 'nothing'}")
        print(f"  the one call COST     {lost or 'nothing'}")

    print("\n  Rows where the judge said nothing and something was wrong:")
    for c, det, llm in rows:
        final = llm if use_llm else det
        if c["expect"] and c["expect"] not in final:
            print(f"    {c['id']:<8} “{c['text'][:52]}”")
            print(f"             want {c['expect']:<20} got {final or '[]'}")
            print(f"             {c['why']}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
