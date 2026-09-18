"""Is `decompose_validate` invariant ON ITS OWN?

    python -m scripts.dv_invariance

Gil, 2026-09-18: *"decompose validate is given the whole text, all the
information to create the item. We need to make sure that it's invariant when
it creates the features — because the features by definition are invariant,
but is that actually happening in reality?"*

WHY THIS IS A DIFFERENT EXPERIMENT FROM `invariance_board.py`
------------------------------------------------------------
That board runs the whole chain, so the 9.1% it reports for this stage is
whatever segmentation handed it PLUS whatever this stage adds — and the two
cannot be told apart. Here the ITEM IS HELD CONSTANT: every variant gets a
byte-identical `Item(text=…, time=…)`, built from the dataset's gold
decomposition, and only `state.text` — the surrounding transcript — changes.

So anything that moves is this stage reading the TRANSCRIPT rather than the
item, which is the one thing that can make a per-item resolver
position-dependent. `X2 = (items, X1)`: it is handed the transcript, and
`checks.run` compares the finished items back against it.

A known candidate, and the reason to expect a finding: `_scope_trailing_date`
is position-gated by construction —

    last = refs[-1]
    if (said[last.end:] or "").strip(" \t.!?,"):
        return []          # something follows it: not trailing

— so moving the date off the tail silently stops the rule applying. It needs
two or more items, which is why the atomic-only board never fired it.
"""
from __future__ import annotations

import argparse
import collections
import copy
import datetime as _dt
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

_T = tempfile.mkdtemp(prefix="dv_inv_")
for _v in ("DB", "MEMORY_DB", "VOCAB", "CATEGORIES", "MODELS", "LABEL_FEEDBACK",
           "MODEL_LOCK", "DEVICE_SECRET", "DEVICES", "TRACE_BUS", "LEXICON",
           "CHECKPOINTS", "UI_STATE", "LOCATION"):
    os.environ[f"MACALENDAR_{_v}"] = os.path.join(_T, _v.lower())
os.environ["MACALENDAR_CONFIG"] = os.path.join(_T, "config.yaml")
shutil.copy(ROOT / "config.example.yaml", os.environ["MACALENDAR_CONFIG"])
os.environ["MACALENDAR_NO_WARMUP"] = "1"
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
for _b in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_b, "1")

_CLOCK = _dt.datetime(2026, 9, 9, 10, 0)
_NOT_A_FEATURE = {"built_by"}

_KIND = {"create_event": "event", "update_event": "event", "delete_event": "event",
         "create_todo": "task", "update_todo": "task", "delete_todo": "task",
         "complete_todo": "task", "query_todos": "review",
         "query_schedule": "review"}


def _features(item) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in (item.slots or {}).items()
                        if k not in _NOT_A_FEATURE))



# ---------------------------------------------------------------------------
# ARM 2 — the MULTI-ITEM shape, which is the only one `_scope_trailing_date`
# can fire on. Arm 1 is atomic-only, so it can never reach that rule; the rule
# is position-gated by construction, so it has to be aimed at directly.
#
# The items are CONSTRUCTED here rather than segmented, for the same reason as
# arm 1: the experiment is about this stage reading the transcript, so every
# variant must start from a byte-identical decomposition. Two asks each
# carrying the SAME time string is exactly what `assign_times` produces when it
# distributes a trailing reference — its docstring cites this worked case.
# ---------------------------------------------------------------------------

#: unmarked vs MARKED — Q16 says only a marked deadline scopes over, and only
#: onto tasks, so both kinds have to be tried or the finding is half a finding.
_SHARED_DATES = [("friday", False), ("the 30th", False), ("tomorrow", False),
                 ("by friday", True), ("due friday", True)]


def multi(limit: int = 0) -> int:
    from freezegun import freeze_time
    from assistant.config import load_config
    from assistant.engine import Engine
    from assistant.engine.state import EngineState, Item
    from scripts.invariance_board import load_rows

    cfg = load_config()
    dv = Engine().stages[1]
    rows = [r for r in load_rows(0)
            if r["expect"].get("action") == "create_todo"]
    texts = [r["expect"]["item"]["text"] for r in rows]
    # distinct, short, and with no time of their own (gold guarantees the last)
    texts = [t for t in dict.fromkeys(texts) if 2 <= len(t.split()) <= 5]
    pairs = [(texts[i], texts[i + 1]) for i in range(0, len(texts) - 1, 2)]
    if limit:
        pairs = pairs[:limit]

    print(f"[dv-invariance --multi] {len(pairs)} task pairs x "
          f"{len(_SHARED_DATES)} shared dates")

    agree = differ = 0
    by_date: collections.Counter = collections.Counter()
    examples: list = []

    with freeze_time(_CLOCK):
        for a_txt, b_txt in pairs:
            for when, marked in _SHARED_DATES:
                forms = {"end":    f"{a_txt} and {b_txt} {when}",
                         "front":  f"{when} {a_txt} and {b_txt}",
                         "front,": f"{when}, {a_txt} and {b_txt}"}
                got = {}
                for pos, utterance in forms.items():
                    st = EngineState(raw_text=utterance, text=utterance)
                    st.items = [
                        Item(id="item_1", kind="task", text=a_txt,
                             time=when, source=utterance),
                        Item(id="item_2", kind="task", text=b_txt,
                             time=when, source=utterance),
                    ]
                    try:
                        dv.run(st, cfg)
                    except Exception as exc:
                        got[pos] = (("ERROR", type(exc).__name__),)
                        continue
                    got[pos] = tuple(_features(i) for i in st.items)
                if len(set(got.values())) == 1:
                    agree += 1
                    continue
                differ += 1
                by_date[f"{when!r} ({'marked' if marked else 'unmarked'})"] += 1
                if len(examples) < 8:
                    examples.append((forms, got))

    tot = agree + differ or 1
    print()
    print("=" * 64)
    print("decompose_validate, ISOLATED — TWO items sharing one date")
    print("=" * 64)
    print(f"   groups compared        {tot}")
    print(f"   features IDENTICAL     {100.0*agree/tot:5.1f}%   ({agree})")
    print(f"   features DIFFER        {100.0*differ/tot:5.1f}%   ({differ})")
    if by_date:
        print("\n   by shared date:")
        for k, v in by_date.most_common():
            print(f"      {v:5}  {k}")
    for forms, got in examples[:4]:
        print(f"\n   {forms['end']!r}")
        for pos, v in got.items():
            print(f"      {pos:6} item1={dict(v[0]) if v and v[0] else v}")
            if v and len(v) > 1:
                print(f"             item2={dict(v[1])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--multi", action="store_true",
                    help="two items sharing one date (arm 2)")
    a = ap.parse_args()
    if a.multi:
        return multi(a.limit)

    from freezegun import freeze_time
    from assistant.config import load_config
    from assistant.engine import Engine
    from assistant.engine.state import EngineState, Item
    from scripts.invariance_board import load_rows, variants

    cfg = load_config()
    dv = Engine().stages[1]
    assert dv.name == "decompose_validate", dv.name

    rows = load_rows(a.limit)
    print(f"[dv-invariance] {len(rows)} source rows · the ITEM is held constant, "
          f"only the transcript moves")

    agree = differ = 0
    field_moves: collections.Counter = collections.Counter()
    examples: list = []

    with freeze_time(_CLOCK):
        for n, row in enumerate(rows, 1):
            gold = row["expect"]["item"]
            kind = _KIND.get(row["expect"].get("action") or "", gold.get("kind") or "event")
            vs = variants(gold["text"], gold["time"])
            if len(vs) < 2:
                continue
            got = {}
            for pos, utterance in vs:
                st = EngineState(raw_text=utterance, text=utterance)
                # IDENTICAL item for every variant — this is the whole point.
                st.items = [Item(id="item_1", kind=kind, text=gold["text"],
                                 time=gold["time"], source=utterance)]
                try:
                    dv.run(st, cfg)
                except Exception as exc:
                    got[pos] = (("ERROR", type(exc).__name__),)
                    continue
                got[pos] = _features(st.items[0]) if st.items else ()
            if len(set(got.values())) == 1:
                agree += 1
                continue
            differ += 1
            base = dict(got.get("end", ()))
            for pos, v in got.items():
                if pos == "end":
                    continue
                d = dict(v)
                for k in set(base) | set(d):
                    if base.get(k) != d.get(k):
                        field_moves[k] += 1
            if len(examples) < 10:
                examples.append((row["text"], got))
            if n % 300 == 0:
                print(f"  ... {n}/{len(rows)}", flush=True)

    tot = agree + differ or 1
    print()
    print("=" * 64)
    print("decompose_validate, ISOLATED — same item, transcript reordered")
    print("=" * 64)
    print(f"   groups compared        {tot}")
    print(f"   features IDENTICAL     {100.0*agree/tot:5.1f}%   ({agree})")
    print(f"   features DIFFER        {100.0*differ/tot:5.1f}%   ({differ})")
    if field_moves:
        print("\n   which feature moved:")
        for k, v in field_moves.most_common(10):
            print(f"      {v:5}  {k}")
    for text, got in examples[:6]:
        print(f"\n   {text!r}")
        for pos, v in got.items():
            print(f"      {pos:6} {dict(v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
