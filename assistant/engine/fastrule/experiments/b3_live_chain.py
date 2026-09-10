"""B3 — is the wiring load-bearing? Run the REAL chain and count.

    python -m assistant.engine.fastrule.experiments.b3_live_chain      # 600 rows
    B3_N=3200 python -m assistant.engine.fastrule.experiments.b3_live_chain

Train half only: it mines. Banked in experiments/RESULTS.md (2026-09-10).

This is NOT phase C's board -- it scores `build()` at its position in the chain,
not the stage's committed output (the wiring commits creates and queries only,
and a DEFER still falls through to the old path). C3 rewrites the primary board
properly. This exists because a converter that defers everything is wired but
not working, and that needed answering before B3 could be called done.

Not phase C's board (that rebuilds the instrument properly). This answers one
question: with `build()` wired in, how often does it actually produce the
object, and how often does it hand the item on? A converter that defers
everything is wired but not working.

Deterministic stages only -- no LLM anywhere in the path.
"""
import collections, json, os, pathlib, random, sys

import tempfile
S = pathlib.Path(os.environ.get("B3_SCRATCH",
                                tempfile.mkdtemp(prefix="fastrule_b3_")))
S.mkdir(parents=True, exist_ok=True)
for v, n in (("DB","c.db"),("MEMORY_DB","m.db"),("VOCAB","v.json"),
             ("CATEGORIES","cat.json"),("TRACE_BUS","t.jsonl")):
    os.environ[f"MACALENDAR_{v}"] = str(S/n)
os.environ["MACALENDAR_NO_WARMUP"] = "1"
os.environ["MACALENDAR_OBSERVANCE"] = "0"

# In experiments/, parents[1] is the STAGE folder (the CLAUDE.md ROOT trap).
STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE / "datasets" / "fastrule_7200.jsonl"

import assistant.engine as engine
from assistant.engine.state import EngineState
from assistant.engine.fastrule.build import Built, Defer, build
from assistant.engine.fastrule.experiments.fastrule_shape import _CLOCK
from freezegun import freeze_time

N = int(os.environ.get("B3_N", "600"))


def main():
    cfg = engine.load_config()
    # WARM THE PARSER OUTSIDE THE FROZEN CLOCK. fastrule_shape.py carries the
    # same line for the same reason: building spaCy's pipeline under freezegun
    # raises, and build() turns that into a `skip` DEFER -- so the whole run
    # reads "defers everything" when the truth is "never got a parser".
    from assistant.engine.fastrule import objects as _g
    _g._get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if r["split"] == "train"
            and r["expect"].get("atomic", True)
            and r["expect"].get("action") != "propose"]
    random.Random(11).shuffle(rows)
    rows = rows[:N]

    built = deferred = op_ok = title_ok = both = 0
    reasons = collections.Counter()
    copied = collections.Counter()
    samples = collections.defaultdict(list)

    with freeze_time(_CLOCK):
        for r in rows:
            st = EngineState(raw_text=r["text"], text=r["text"], source="test")
            try:
                engine._segment.run(st, cfg)
                engine._decompose_validate.run(st, cfg)
            except Exception:
                continue
            if not st.items:
                continue
            it = st.items[0]
            res = build(it)
            want = r["expect"].get("action", "")
            want_t = " ".join(str((r["expect"].get("slots") or {}).get("title") or "").lower().split())
            if isinstance(res, Built):
                built += 1
                for c in res.copied:
                    copied[c] += 1
                # The gold's action for a read-only row is the bare "query";
                # the registry's are query_schedule / query_todos. Scoring
                # those unequal counts a right answer wrong -- the board's own
                # scorer special-cases it the same way.
                o = (res.action == want
                     or (want == "query" and res.action.startswith("query")))
                got_t = (getattr(res.intent, "title", None)
                         or (getattr(res.intent, "titles", []) or [""])[0]
                         or getattr(res.intent, "match_title", "") or "")
                got_t = " ".join(str(got_t).lower().split())
                t_ok = (got_t == want_t) if want_t else (want == "query")
                op_ok += o; title_ok += t_ok; both += (o and t_ok)
                key = "right" if (o and t_ok) else ("wrong-title" if o else "wrong-op")
                if len(samples[key]) < 6:
                    samples[key].append(
                        f"{r['text'][:44]!r} want={want}/{want_t!r} got={res.action}/{got_t!r}")
            else:
                deferred += 1
                reasons[res.reason] += 1
                if len(samples["deferred"]) < 6:
                    samples["deferred"].append(f"[{res.reason}] {r['text'][:48]!r}")

    n = built + deferred
    pc = lambda a, b: f"{100.0*a/b:.1f}%" if b else "—"
    print(f"B3 — build() in the REAL chain, {n} atomic TRAIN rows "
          f"(segmentation -> decompose_validate -> build)\n")
    print(f"  BUILT                {built:4d}  {pc(built, n)}")
    print(f"  DEFERRED             {deferred:4d}  {pc(deferred, n)}\n")
    print(f"  of those built — operation right   {op_ok:4d}  {pc(op_ok, built)}")
    print(f"                   title right       {title_ok:4d}  {pc(title_ok, built)}")
    print(f"                   BOTH              {both:4d}  {pc(both, built)}\n")
    print("  values copied from item.slots (the job the stage exists for):")
    for k, v in copied.most_common():
        print(f"     {v:4d}  {pc(v, built):>6}  {k}")
    print("\n  defer reasons:")
    for k, v in reasons.most_common():
        print(f"     {v:4d}  {k}")
    for k in ("right", "wrong-title", "wrong-op", "deferred"):
        if samples.get(k):
            print(f"\n  {k}:")
            for s in samples[k]:
                print("    ", s)


main()
