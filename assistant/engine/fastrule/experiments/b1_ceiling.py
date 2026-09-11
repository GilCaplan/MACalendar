"""B1 — the ceiling on what the CONVERTER restructure can rescue.

    python -m assistant.engine.fastrule.experiments.b1_ceiling

Run for PLAN.md §3 step B1, banked in experiments/RESULTS.md (2026-09-10).
Train half only: it mines, so it may never see the test rows.

Measured against what build() ACTUALLY does.

B1a/B1b asked the parser for an INTENT and counted the rows that produced
none. That measured the wrong thing, and the reason is the finding:

    rp.analyze("create an event for staff meeting")
        -> conf 0.317, intents [], missing ['date','start_time']
    rp.analyze("create an event for staff meeting tomorrow")
        -> conf 1.0,   intents ['create_event']

The parser ROUTES fine. It withholds the intent when the when is unfilled —
so on a fragment whose when is meant to arrive separately, "no intent" is the
parser honouring its contract, not failing to understand the ask. Asking it
for an intent is asking the question build() will not ask.

What build() does instead (PLAN §2d): take the ROUTE and the TITLE from the
action words, and COPY the values from item.slots. So that is what this
scores, per row:

    operation   the route the parser selected      (rr.raw_slots' key)
    title       what it read from the ASK ALONE    (the when carved off)
    values      decompose_validate's resolve()     (measured, not assumed)
"""
import collections
import json
import os
import pathlib
import re
import tempfile

_SCRATCH = pathlib.Path(os.environ.get(
    "B1_SCRATCH", tempfile.mkdtemp(prefix="fastrule_b1_")))
_SCRATCH.mkdir(parents=True, exist_ok=True)
for _v, _n in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
               ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
               ("TRACE_BUS", "trace_bus.jsonl")):
    os.environ[f"MACALENDAR_{_v}"] = str(_SCRATCH / _n)
os.environ["MACALENDAR_NO_WARMUP"] = "1"
# BACKGROUND traffic: this yields the model to the live assistant between
# every call (assistant/model_protocol.py). Without it a board and a voice
# command are indistinguishable to ollama, and a trivial live call measured
# 2.0s -> 42.5s -> 43.9s behind a running board (2026-09-10).
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
os.environ["MACALENDAR_OBSERVANCE"] = "0"

# THE `ROOT` TRAP (CLAUDE.md): in experiments/, parents[1] is the STAGE folder,
# not the repo root. The dataset lives in the stage folder, so it hangs off
# STAGE; nothing here needs the repo root, and a hardcoded absolute path is
# what made fast_sandbox.py runnable in exactly one checkout.
STAGE = pathlib.Path(__file__).resolve().parents[1]
DATA = STAGE / "datasets" / "fastrule_7200.jsonl"
from assistant.engine.fastrule.experiments.fastrule_shape import _CLOCK  # noqa: E402

_WHEN = ("time_phrase", "time_phrase_2", "time_phrase_3",
         "date_phrase", "date_phrase_2", "date_phrase_3",
         "recurrence", "duration", "lead_time")


def _norm(s):
    return " ".join(str(s or "").lower().split()).strip(" .,'\"")


def _strip_when(text, gold):
    out = text
    for k in _WHEN:
        v = gold.get(k)
        if isinstance(v, str) and v.strip():
            out = re.sub(re.escape(v), " ", out, flags=re.I)
    out = re.sub(r"\b(?:at|on|in|for|by|from|until|till|through|starting|every)\s*$",
                 " ", out.strip(), flags=re.I)
    out = re.sub(r"\s+(?:at|on|in|by|from)\s+(?=$|[,.])", " ", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip(" ,.")


def _route_and_title(rr):
    """The two things build() keeps from the parse."""
    raw = getattr(rr, "raw_slots", None) or {}
    if not raw:
        return None, ""
    route = next(iter(raw))
    slots = raw[route] or {}
    t = slots.get("title") or ""
    if not t:
        ts = slots.get("titles") or []
        t = ts[0] if ts else ""
    return route, _norm(t)


def main() -> int:
    from freezegun import freeze_time
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD, RuleParserSkip
    from assistant.engine import llm as _objects
    from assistant.engine.decompose_validate import resolve as _resolve

    fr = FastRule(RULE_THRESHOLD)
    fr.run("book gym tomorrow at 7am")
    rp = _objects.get_rule_parser()

    rows = [json.loads(l) for l in DATA.open()]
    rows = [r for r in rows if r["split"] == "train"]

    n = 0
    C = collections.Counter()
    stop = collections.Counter()
    samples = collections.defaultdict(list)
    title_src = collections.Counter()

    with freeze_time(_CLOCK):
        for r in rows:
            e = r["expect"]
            if e.get("action") == "propose" or not e.get("atomic", True):
                continue
            res = fr.run(r["text"])
            if res and res.committed:
                continue
            if (res.reason or "").split(":")[0] != "below-threshold":
                continue
            n += 1
            gold = e.get("slots", {}) or {}
            want = e.get("action", "")
            want_t = _norm(gold.get("title"))

            # --- the route, as the parser already selected it on the full text
            route_full, title_full = _route_and_title(res.rule_result)

            # --- the title, read from the ask with the when carved off
            ask = _strip_when(r["text"], gold)
            try:
                rb = rp.analyze(ask, current_view="month")
                route_ask, title_ask = _route_and_title(rb)
            except (RuleParserSkip, Exception):
                route_ask, title_ask = None, ""

            route = route_ask or route_full
            # STRICT: create_todo is not create_event. The family-level match
            # ("create" == "create") counts a kind confusion as a success, and
            # the kind decision has its own board precisely because it is a
            # real error the user sees.
            o_ok = bool(route) and route == want
            o_loose = bool(route) and (route == want
                                       or route.split("_")[0] == want.split("_")[0])

            # the better of the two title reads — build() gets the ask, but the
            # full-text read is what exists today; report which one wins
            t_ask = bool(want_t) and bool(title_ask) and want_t == title_ask
            t_ask_loose = bool(want_t) and bool(title_ask) and (
                want_t == title_ask or want_t in title_ask or title_ask in want_t)
            t_full = bool(want_t) and bool(title_full) and (
                want_t == title_full or want_t in title_full or title_full in want_t)
            if t_ask and not t_full:
                title_src["ask only — carving the when FIXED it"] += 1
            elif t_full and not t_ask:
                title_src["full text only — carving the when BROKE it"] += 1
            elif t_ask and t_full:
                title_src["both"] += 1
            else:
                title_src["neither"] += 1

            # --- the values: does the stage that owns them read them?
            when = {k: gold[k] for k in _WHEN if isinstance(gold.get(k), str)}
            v_ok = True
            if when:
                v = _resolve.resolve(" ".join(when.values()), _CLOCK.date(),
                                     r["text"], action=r["text"])
                v_ok = any(v.get(k) for k in ("date", "start_time", "end_time",
                                              "recurrence", "recur_days", "recur_until"))

            # A CLEAN carve is what segmentation actually hands over; this
            # probe's re.sub() is a crude stand-in for it and demonstrably
            # damages some titles (see the "carving BROKE it" line). Taking
            # the better of the two reads brackets what a clean carve reaches.
            t_best = t_ask or t_full
            C["title_best"] += t_best
            C["buildable_best"] += (o_ok and t_best and v_ok)
            C["op_loose"] += o_loose
            C["title_loose"] += t_ask_loose
            C["buildable_loose"] += (o_loose and t_ask_loose and v_ok)
            C["route_known"] += bool(route)
            C["op_right"] += o_ok
            C["title_right"] += t_ask
            C["values_ok"] += v_ok
            buildable = o_ok and t_ask and v_ok
            C["buildable"] += buildable

            if buildable:
                stop["BUILDABLE"] += 1
                key = "BUILDABLE"
            elif not route:
                key = "no route at all"
            elif not o_ok:
                key = "wrong operation"
            elif not t_ask:
                key = "wrong title"
            else:
                key = "values unreadable"
            stop[key] += 0 if buildable else 1
            if len(samples[key]) < 6:
                samples[key].append(
                    f"{r['text'][:50]!r}\n           ask={ask[:36]!r} want={want}/{want_t!r} "
                    f"route={route} title={title_ask!r}(ask) {title_full!r}(full)")

    pc = lambda a, b: f"{100.0*a/b:.1f}%" if b else "—"
    print("B1c — the ceiling, scored the way build() works\n")
    print(f"below-threshold atomic deferrals   {n}   (TRAIN half)\n")
    print("EACH PIECE OF THE OBJECT, on those rows:")
    print(f"  route selected at all            {C['route_known']:4d}  {pc(C['route_known'], n)}")
    print(f"  OPERATION right  STRICT          {C['op_right']:4d}  {pc(C['op_right'], n)}")
    print(f"                   family-level     {C['op_loose']:4d}  {pc(C['op_loose'], n)}   (counts create_todo as create_event)")
    print(f"  TITLE right      STRICT (exact)   {C['title_right']:4d}  {pc(C['title_right'], n)}")
    print(f"                   substring        {C['title_loose']:4d}  {pc(C['title_loose'], n)}   ('taylor' for 'talk to taylor')")
    print(f"                   best of the two   {C['title_best']:4d}  {pc(C['title_best'], n)}   (clean-carve proxy)")
    print(f"  VALUES readable upstream         {C['values_ok']:4d}  {pc(C['values_ok'], n)}\n")
    print(f"  ALL THREE -> buildable  STRICT   {C['buildable']:4d}  {pc(C['buildable'], n)}")
    print(f"     strict op + clean-carve title {C['buildable_best']:4d}  {pc(C['buildable_best'], n)}   <- the defensible ceiling")
    print(f"                          generous {C['buildable_loose']:4d}  {pc(C['buildable_loose'], n)}")
    print(f"     (today these 573 rows all DEFER: 0.0%)\n")
    print("  where the rest stop:")
    for k, v in stop.most_common():
        if v:
            print(f"     {v:4d}  {pc(v, n):>6}  {k}")
    print("\n  what carving the when did to the TITLE read:")
    for k, v in title_src.most_common():
        print(f"     {v:4d}  {pc(v, n):>6}  {k}")
    for k in ("BUILDABLE", "wrong title", "wrong operation", "no route at all"):
        if samples.get(k):
            print(f"\n  {k}:")
            for s in samples[k]:
                print(f"     {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
