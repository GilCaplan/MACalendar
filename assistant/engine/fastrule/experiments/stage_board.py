"""C3 — the STAGE board. Does FastRule do ITS task?

    python -m assistant.engine.fastrule.experiments.stage_board          # converter only, seconds
    python -m assistant.engine.fastrule.experiments.stage_board --llm    # + the rescue (needs Ollama)
    python -m ...stage_board -n 1200

`fastrule_shape.py` measures the FRONT DOOR — `FastRule(threshold).run(TEXT)`,
the whole-command fast track, a different box. **This** board measures the
stage Gil describes: `List[Item]` in, objects the software accepts out.

## The rule this board is built on (Gil, 2026-09-10)

> *"If it receives bad input then the output should be the same — the question
> then becomes what stage failed and where, and to flag in the relevant md file
> to go fix there. Here for FastRule we just need to make the item gets turned
> into an object the system can accept."*

So a wrong answer is NOT automatically FastRule's fault, and scoring it as one
is the expensive mistake: it makes this stage chase losses that happened before
it ran, and it hides the stage that actually failed. **Every row is therefore
audited BEFORE the stage runs**, and each failure is attributed:

    the item never carried the title        -> SEGMENTATION lost it
    the item carried no resolved when       -> DECOMPOSE_VALIDATE missed it
    the item's kind contradicts the gold    -> SEGMENTATION mis-tagged it
    the item had everything, object wrong   -> FASTRULE. ours.

**The headline number is CONVERSION FIDELITY** — correct objects over rows
whose input was sound. That is the only number that judges this stage. The
end-to-end figure is printed beside it for context and is NOT this stage's
score; the gap between them belongs to the stages named in the attribution
table, and that table is what gets written into their md files.

Train half only — it mines. The test half stays sealed.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import random
import re

from assistant.common.scratch_env import scratch_env

_S = pathlib.Path(scratch_env(
    "fastrule_stage_", observance=False,
    dir=os.environ.get("STAGE_BOARD_SCRATCH"),
    keep=("LOCATION", "MODELS", "LABEL_FEEDBACK", "HEARTBEATS", "HUD_STATE",
         "DEVICE_SECRET", "DEVICES")))

# In experiments/, parents[1] is the STAGE folder (the CLAUDE.md ROOT trap).
STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE / "datasets" / "fastrule_7200.jsonl"

_STOP = {"the", "a", "an", "my", "to", "for", "of", "on", "at", "in", "and"}


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split()).strip(" .,'\"")


def _content(s) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", _norm(s)) if w not in _STOP}


def _title_of(intent) -> str:
    for attr in ("title", "match_title"):
        v = getattr(intent, attr, None)
        if v:
            return _norm(v)
    ts = getattr(intent, "titles", None) or []
    return _norm(ts[0]) if ts else ""


#: Gold slot names that mean "the speaker said WHEN".
_WHEN_KEYS = ("time_phrase", "date_phrase", "recurrence", "duration", "lead_time")


def audit_input(item, gold: dict, want_action: str, n_items: int) -> "str | None":
    """What, if anything, was ALREADY wrong when FastRule received this item.

    Returns the stage to blame, or None when the input was sound. Checked
    before the stage runs, so the verdict cannot be contaminated by what the
    stage then did with it.
    """
    if n_items != 1:
        return "segmentation: split an atomic row into %d items" % n_items

    want_t = _content(gold.get("title"))
    if want_t and not want_t <= _content(item.text):
        missing = " ".join(sorted(want_t - _content(item.text)))
        return f"segmentation: the action words lost {missing!r}"

    if item.kind == "other" and want_action:
        # A real ask tagged "not a calendar ask". Zero rows on the current
        # train sample, but the check costs nothing and its absence would show
        # up as FastRule producing nothing, which is the wrong stage to blame.
        return "segmentation: tagged 'other' — not a calendar ask"

    want_kind = ("task" if want_action.endswith("todo")
                 else "event" if want_action.endswith("event") else None)
    if want_kind and item.kind in ("event", "task") and item.kind != want_kind:
        return f"segmentation: tagged {item.kind!r}, gold is {want_kind!r}"

    said_when = any(isinstance(gold.get(k), str) and gold[k].strip()
                    for k in _WHEN_KEYS)
    slots = item.slots or {}
    got_when = any(slots.get(k) for k in
                   ("date", "start_time", "end_time", "recurrence",
                    "recur_days", "recur_until", "reminder_minutes"))
    if said_when and not got_when:
        return "decompose_validate: a when was spoken but no value was resolved"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true",
                    help="run the full stage including the LLMJudge rescue")
    ap.add_argument("--input", choices=("gold", "chain"), default="gold",
                    help="gold = the Item the upstream SHOULD produce (this "
                         "stage ALONE); chain = the real segmenter's output")
    ap.add_argument("-n", type=int, default=int(os.environ.get("N", "600")))
    a = ap.parse_args()

    from freezegun import freeze_time
    import assistant.engine as engine
    from assistant.engine import llm as _llm
    from assistant.engine.fastrule import stage as _stage
    from assistant.engine.fastrule.build import Built, build_all
    from assistant.engine.fastrule.stage import _may_commit
    from assistant.engine.state import EngineState
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.state import Item
    from assistant.engine.fastrule.experiments.fastrule_shape import _CLOCK

    cfg = engine.load_config()
    # Warm the parser OUTSIDE the frozen clock: building spaCy's pipeline under
    # freezegun raises, and the stage turns that into a DEFER -- so the whole
    # run reads "converts nothing" when the truth is "never got a parser".
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if r["split"] == "train"
            and r["expect"].get("atomic", True)
            and r["expect"].get("action") != "propose"]
    random.Random(11).shuffle(rows)
    rows = rows[:a.n]

    n = sound = 0
    handled = correct = 0                     # over SOUND rows — the real score
    op_ok = title_ok = 0
    e2e_correct = e2e_handled = 0             # over all rows — context only
    by_rule = rule_ok = by_model = model_ok = 0
    blame: collections.Counter = collections.Counter()
    withheld: collections.Counter = collections.Counter()
    built_n = [0]
    bad_n = [0]
    bad_faithful = [0]
    defers: collections.Counter = collections.Counter()
    samples = collections.defaultdict(list)

    with freeze_time(_CLOCK):
        for r in rows:
            gold = r["expect"].get("slots") or {}
            want = r["expect"].get("action", "")
            want_t = _norm(gold.get("title"))

            st = EngineState(raw_text=r["text"], text=r["text"], source="test")
            if a.input == "gold":
                # ISOLATION. The Item the upstream SHOULD have produced, built
                # by the generator from its own templates — so no stage's
                # implementation is in the path and this measures FastRule and
                # nothing else. `slots` are resolved from the gold when phrase
                # by decompose_validate's resolver, which is the component that
                # owns that job; its own boards score it separately.
                gi = r["expect"].get("item") or {}
                item = Item(id="item_1", kind=gi.get("kind") or "event",
                            text=gi.get("text") or r["text"],
                            time=gi.get("time"))
                st.items = [item]
                try:
                    _dv.resolve_values(st, _CLOCK.date())
                except Exception:
                    pass
                bad = None
            else:
                try:
                    engine._segment.run(st, cfg)
                    engine._decompose_validate.run(st, cfg)
                except Exception:
                    continue
                if not st.items:
                    blame["segmentation: produced no item at all"] += 1
                    continue
                item = st.items[0]
                bad = audit_input(item, gold, want, len(st.items))
            n += 1

            # --- run the stage ---------------------------------------------
            if a.llm:
                try:
                    _stage.run(st, cfg)
                except Exception:
                    pass
                got_action, got_intent = item.action, item.intent
            else:
                # the CONVERTER's own lane: no model, seconds, deterministic
                res = build_all([item])[0]
                if isinstance(res, Built):
                    built_n[0] += 1
                    if _may_commit(res.action):
                        got_action, got_intent = res.action, res.intent
                        item.slots["built_by"] = "rule"
                    else:
                        # BUILT, but withheld by the commit policy (a target-
                        # taking op needs a store check this stage cannot do).
                        # Counting these as "deferred" hides the converter's
                        # real reach -- the object exists, it is the COMMIT
                        # that is withheld, and in the full stage the model
                        # sees it. The first cut of this board labelled them
                        # "not a calendar ask", which was simply a `getattr`
                        # falling through on a Built that has no `reason`.
                        got_action, got_intent = None, None
                        withheld[res.action] += 1
                elif res is None:
                    got_action, got_intent = None, None
                    defers["not-a-calendar-ask (segmentation tagged it other)"] += 1
                else:
                    got_action, got_intent = None, None
                    defers[res.reason] += 1

            produced = got_intent is not None and got_action not in (None, "unknown")
            o_ok = produced and (got_action == want
                                 or (want == "query" and got_action.startswith("query")))
            t_ok = produced and ((_title_of(got_intent) == want_t) if want_t else True)
            ok = bool(o_ok and t_ok)

            e2e_handled += produced
            e2e_correct += ok

            if bad:
                # GIL, 2026-09-10: "if the input to FastRule was a BAD item and
                # the output was IN ACCORDANCE, then I would mark that in the
                # scoring metric as a SUCCESS."
                #
                # So a broken input is not excused OR punished — it is scored
                # against the item that actually arrived. The reference cannot
                # be the utterance's gold object (the item no longer says
                # that), so it is FAITHFULNESS: an object whose title is drawn
                # from the received item's OWN words, inventing nothing. That
                # is exactly what a correct converter does with words it was
                # handed, and it is the only thing this stage can be held to
                # once the words are already wrong.
                faithful = produced and _content(_title_of(got_intent)) <= _content(item.text)
                blame[bad.split(":")[0] + ": " + bad.split(": ", 1)[1][:52]] += 1
                bad_n[0] += 1
                bad_faithful[0] += bool(faithful)
                if not faithful and len(samples["unfaithful"]) < 8:
                    samples["unfaithful"].append(
                        f"{r['text'][:40]!r}\n           item={item.text[:34]!r} "
                        f"got={got_action}/{_title_of(got_intent)!r}\n           {bad}")
                elif len(samples["upstream"]) < 6:
                    samples["upstream"].append(
                        f"{r['text'][:44]!r}\n           {bad}")
                continue

            # --- SOUND INPUT: this row is FastRule's to answer --------------
            sound += 1
            if not produced:
                if len(samples["not-produced"]) < 6:
                    samples["not-produced"].append(
                        f"{r['text'][:44]!r} item={item.text[:32]!r} want={want}")
                continue
            handled += 1
            op_ok += bool(o_ok)
            title_ok += bool(t_ok)
            correct += ok
            if (item.slots or {}).get("built_by") == "model":
                by_model += 1
                model_ok += ok
            else:
                by_rule += 1
                rule_ok += ok
            if not ok and len(samples["ours"]) < 10:
                samples["ours"].append(
                    f"{r['text'][:44]!r} item={item.text[:30]!r}\n"
                    f"           want={want}/{want_t!r} got={got_action}/"
                    f"{_title_of(got_intent)!r}")

    pc = lambda x, y: f"{100.0*x/y:.1f}%" if y else "—"
    lane = ("FULL STAGE (converter + LLMJudge rescue)" if a.llm
            else "CONVERTER ONLY (no model)")
    src = ("GOLD items — THIS STAGE ALONE" if a.input == "gold"
           else "the real chain's items")
    print(f"FastRule STAGE board — {n} atomic TRAIN rows · {lane}")
    print(f"input: {src}\n")
    if a.input == "chain":
        print(f"INPUT AUDIT   sound input {sound}/{n} = {pc(sound, n)}"
              f"   ({n - sound} arrived already broken)")
        print(f"  of the {bad_n[0]} broken, FAITHFULLY converted anyway "
              f"(counted a SUCCESS): {bad_faithful[0]}  {pc(bad_faithful[0], bad_n[0])}\n")
    total_ok = correct + bad_faithful[0]
    total_rows = sound + bad_n[0]
    if a.input == "chain":
        print(f"THIS STAGE'S SCORE — right on sound input, FAITHFUL on broken")
        print(f"  {total_ok}/{total_rows} = {pc(total_ok, total_rows)}\n")
    print("ON SOUND INPUT" if a.input == "chain" else "THIS STAGE'S SCORE")
    print(f"  HANDLED (an object came out)   {handled:4d}  {pc(handled, sound)}")
    print(f"  CORRECT-ON-HANDLED             {correct:4d}  {pc(correct, handled)}")
    print(f"     operation right             {op_ok:4d}  {pc(op_ok, handled)}")
    print(f"     title right                 {title_ok:4d}  {pc(title_ok, handled)}")
    if by_rule or by_model:
        print(f"\n  who produced it — converter {by_rule} ({pc(rule_ok, by_rule)} right)"
              f" · rescue {by_model} ({pc(model_ok, by_model)} right)")
    print(f"\nEND-TO-END (context, NOT this stage's score)")
    print(f"  handled {e2e_handled}/{n} = {pc(e2e_handled, n)}"
          f"   ·   correct {e2e_correct}/{n} = {pc(e2e_correct, n)}")
    if blame:
        print("\nUPSTREAM FAILURES — flag these in the named stage's md, "
              "do NOT fix them here:")
        for k, v in blame.most_common(10):
            print(f"  {v:4d}  {k}")
    if built_n[0]:
        print(f"\n  THE CONVERTER BUILT AN OBJECT for {built_n[0]} of the "
              f"{n} rows = {pc(built_n[0], n)}")
        if withheld:
            print("     ...of which WITHHELD by the commit policy (a target-taking"
                  " op\n        needs a store check this stage cannot do; the "
                  "model sees these):")
            for k, v in withheld.most_common():
                print(f"       {v:4d}  {k}")
    if defers:
        print("\n  the converter could NOT build, by reason:")
        for k, v in defers.most_common():
            print(f"  {v:4d}  {k}")
    for k, label in (("ours", "OUR failures — sound input, wrong object"),
                     ("not-produced", "sound input, nothing came out"),
                     ("upstream", "upstream examples")):
        if samples.get(k):
            print(f"\n{label}:")
            for s in samples[k]:
                print("    ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
