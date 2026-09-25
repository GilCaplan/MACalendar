"""HOW should X1' be built? Five ways, measured against each other.

    python -m assistant.engine.llmjudge.experiments.x1_variants -n 120

Gil, 2026-09-10: *"test different versions of my idea and decide what's best…
the llmjudge is how can we fix the prompt to send back in a more deterministic
way."*

"More deterministic" makes the interesting question **how little model** X1' can
be built with, not how to word a better prompt. So the variants run from "the
model writes it" to "code writes it and the model never sees it":

    A  residue + LLM repair     the finished spans are cut, a model repairs the rest
    B  residue, raw             the leftovers, tidied, sent as they are. NO MODEL.
    C  failed spoken()          the failed items' own action+time, joined by "and"
    D  failed spans             the failed items' verbatim spans, joined by "and"
    E  residue + reshape        the leftovers, put into the shape the parser wants
                                by CODE — verb-first check, "and" joins, no "the",
                                digit times. NO MODEL.

## What is scored, and why it isolates the right thing

Each row is a real multi-ask command. Its FIRST object is treated as succeeded
and the rest as failed — so every variant faces the same job: carry the failed
asks forward and leave the finished one behind.

    recovered   the failed ask's title comes back out of a re-parse of X1'
    leaked      the FINISHED ask came back too — a double commit if committed
    empty       the variant produced nothing to retry

This deliberately does NOT go through the judge's findings. Cycle 9 showed those
are the ceiling on how OFTEN the loop fires; this board asks a different
question — given that it fires, which construction recovers the row. Mixing them
would hide both.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re

from assistant.common.scratch_env import scratch_env

scratch_env("x1_variants_", observance=False,
           keep=("LOCATION", "HEARTBEATS", "HUD_STATE", "DEVICE_SECRET", "DEVICES"))

STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE.parent / "fastrule" / "datasets" / "fastrule_7200.jsonl"

_STOP = {"the", "a", "an", "my", "to", "for", "of", "on", "at", "in", "and"}


def _content(s) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", str(s or "").lower())
            if w not in _STOP}


def _tidy(text: str) -> str:
    """Close the seams a removal leaves — the same cleanup `rewrite.residue`
    does, kept here so every variant is tidied identically and the comparison
    is about the CONSTRUCTION rather than about who cleaned up better."""
    text = re.sub(r"\s+", " ", text or "").strip(" ,.;")
    text = re.sub(r"^(?:and|then|also|plus)\b\s*", "", text, flags=re.I)
    text = re.sub(r"\s*,?\s*\b(?:and|then|also|plus)\b\s*$", "", text, flags=re.I)
    text = re.sub(r"\b(?:and|then)\s+(?:and|then)\b", "and", text, flags=re.I)
    return text.strip(" ,.;")


def _reshape(text: str) -> str:
    """Variant E: put the leftovers into the shape the parser wants, in CODE.

    The four rules are the ones measured on 2026-09-10 against the real chain
    (`tests/unit/test_rewrite_targets_the_parser.py` pins them):

        commas and full stops do NOT split -> make every joiner " and "
        "the" before a subject corrupts the title -> drop a leading article
        a worded hour often resolves no clock -> digitise "at three" -> "at 3pm"

    Rule 1 — every ask needs its own verb — is deliberately NOT attempted here:
    inventing a verb is exactly what the grounding guard exists to stop, and
    code cannot know whether the speaker meant book or cancel. That is the one
    thing only a model can do, and it is what variant A buys.
    """
    text = _tidy(text)
    text = re.sub(r"\s*[,;]\s*|\s*\.\s+", " and ", text)
    text = re.sub(r"\b(?:then|also|plus|as well as)\b", "and", text, flags=re.I)
    text = re.sub(r"\b(?:and\s+){2,}", "and ", text, flags=re.I)
    _WORD_HOUR = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                  "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                  "twelve": 12}

    def _digits(m):
        h = _WORD_HOUR[m.group(2).lower()]
        return f"{m.group(1)}{h}{'am' if h < 8 else 'pm'}"
    text = re.sub(r"\b(at\s+)(" + "|".join(_WORD_HOUR) + r")\b", _digits, text,
                  flags=re.I)
    # A leading article on the whole fragment corrupts the title downstream.
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.I)
    return _tidy(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=int(os.environ.get("N", "120")))
    ap.add_argument("--no-llm", action="store_true",
                    help="skip variant A (the only one that calls a model)")
    a = ap.parse_args()

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine.llmjudge import rewrite as _rw, findings as F
    from assistant.engine.state import EngineState, CheckFinding
    from assistant.engine.llmjudge.datasets.generate import CLOCK

    cfg = engine.load_config()
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")
    use_llm = not a.no_llm
    if use_llm:
        try:
            _llm.call_json(cfg, "Reply with JSON.", "ping",
                           {"type": "object", "properties": {"ok": {"type": "string"}},
                            "required": ["ok"]})
        except Exception as e:
            print(f"  (no model reachable: {e} — running the deterministic four)")
            use_llm = False

    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if r["split"] == "train"]
    random.Random(19).shuffle(rows)

    eng = engine.Engine()
    names = ["A residue+LLM", "B residue raw", "C failed spoken()",
             "D failed spans", "E residue+reshape"]
    if not use_llm:
        names = names[1:]
    stats = {n: {"recovered": 0, "leaked": 0, "empty": 0, "tried": 0} for n in names}
    scored = 0

    with freeze_time(CLOCK):
        for r in rows:
            if scored >= a.n:
                break
            text = r["text"]
            st = EngineState(raw_text=text, text=text, source="test")
            try:
                eng.parse(st, cfg)
            except Exception:
                continue
            objs = [i for i in st.items if i.intent is not None and i.action]
            if len(objs) < 2:
                continue                     # nothing to trim: not this board's case
            scored += 1
            kept, failed = objs[0], objs[1:]
            kept_words = _content(getattr(kept.intent, "title", None)
                                  or (getattr(kept.intent, "titles", None) or [""])[0])
            want = set()
            for it in failed:
                want |= _content(getattr(it.intent, "title", None)
                                 or (getattr(it.intent, "titles", None) or [""])[0])
            st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id=it.id,
                                        detail="d", blamed_stage="fastrule")
                           for it in failed]

            builds = {}
            if use_llm:
                try:
                    builds["A residue+LLM"] = _rw.rewrite_for_retry(st, cfg) or ""
                except Exception:
                    builds["A residue+LLM"] = ""
            builds["B residue raw"] = _rw.residue(st)
            builds["C failed spoken()"] = _tidy(" and ".join(i.spoken() for i in failed))
            builds["D failed spans"] = _tidy(" and ".join(
                dict.fromkeys(i.source or i.text for i in failed)))
            builds["E residue+reshape"] = _reshape(_rw.residue(st))

            for name in names:
                x1 = builds.get(name) or ""
                s = stats[name]
                if not x1.strip():
                    s["empty"] += 1
                    continue
                s["tried"] += 1
                st2 = EngineState(raw_text=text, text=x1, source="test")
                try:
                    eng.parse(st2, cfg)
                except Exception:
                    continue
                got = set()
                for it in st2.items:
                    if it.intent is None or not it.action:
                        continue
                    got |= _content(getattr(it.intent, "title", None)
                                    or (getattr(it.intent, "titles", None) or [""])[0])
                if want and (want & got):
                    s["recovered"] += 1
                if kept_words and (kept_words & got):
                    s["leaked"] += 1

    print(f"\nX1' CONSTRUCTION — {scored} multi-ask rows, train half"
          f"{'' if use_llm else '  (no model: A skipped)'}\n")
    print(f"  {'variant':<20}{'recovered':>11}{'leaked':>9}{'empty':>8}"
          f"{'net':>8}")
    for name in names:
        s = stats[name]
        net = s["recovered"] - s["leaked"]
        print(f"  {name:<20}{s['recovered']:>11}{s['leaked']:>9}{s['empty']:>8}"
              f"{net:>8}")
    print("\n  recovered = the failed ask came back out of a re-parse of X1'")
    print("  leaked    = the FINISHED ask came back too — a double commit")
    print("  net       = recovered minus leaked. A variant that recovers by")
    print("              carrying everything forward is not solving anything.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
