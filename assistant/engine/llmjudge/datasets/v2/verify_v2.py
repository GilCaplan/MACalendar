"""Is the v2 set usable? Run this before trusting any board built on it.

    python -m assistant.engine.llmjudge.datasets.v2.verify_v2

**It REFUSES the set** — exit code 1, with the offending rows named — unless
all five hold. Each is a way a generated set can look fine and measure nothing:

    REACHABLE   every gold value can be reached from the command's own words,
                by `assistant/intent/correction.py`'s rules (a title's content
                words are in the words; a clock sits on the five-minute grid
                people speak in; the day phrase was said). A gold value nothing
                in the words supports is one no parser could ever produce, so a
                board built on it measures the dataset, not the engine.
    NO TEXT LEAK    the halves share no command text.
    NO FAMILY LEAK  no family appears in both halves — the split unit is the
                    family, so a skeleton in the test half was never trained on
                    (`engine/TRAIN_TEST_SPLIT_CONVENTION.md`).
    BOTH HALVES CARRY EVERYTHING   every voice and every damage operation
                    appears on both sides. If one half is missing an operation,
                    the two halves are not measuring the same thing and the
                    difference between them is not a generalisation gap.
    EFFECTIVE   every planted case names a mutation, and every clean case
                names none. (`generate_v2` already drops a plant that does not
                change the object; this is the check that it did.)

Then it PRINTS THE DIVERSITY, which is the deliverable rather than the row
count: distinct families, grammars, voices, damage operations, joiners,
mutations and clock forms, per split. 5,000 rows from 30 templates is 30
examples with a big denominator, and this is the printout that says so.
"""
from __future__ import annotations

import collections
import json
import os
import pathlib
import sys

from assistant.common.scratch_env import scratch_env

# Stores redirected before anything from `assistant` is imported: the paths are
# read at import time, and `~/.assistant_tools/` is the real calendar and the
# hand-curated vocabulary.
_T = scratch_env("judge_v2_verify_", keep=("HEARTBEATS", "HUD_STATE"),
                 extra={"MACALENDAR_LLM_DISABLED": "1"})
for _v in ("LEXICON", "CHECKPOINTS", "UI_STATE"):
    os.environ[f"MACALENDAR_{_v}"] = os.path.join(_T, _v.lower())

HERE = pathlib.Path(__file__).resolve().parent
COMMANDS = HERE / "commands_v2.jsonl"
CASES = HERE / "judge_cases_v2.jsonl"


def _load(path: pathlib.Path) -> list:
    if not path.exists():
        print(f"missing: {path} — run generate_v2 first")
        raise SystemExit(2)
    return [json.loads(l) for l in path.open() if l.strip()]


# ---------------------------------------------------------------------------
# REACHABLE — `intent/correction.py`'s rules, applied to a generated gold
# ---------------------------------------------------------------------------

def unreachable(row: dict) -> list:
    """Every gold value in this row that the words cannot reach, as
    `(ask_id, field, value)`.

    The rules are `correction.py`'s, imported rather than restated: a changed
    TITLE is reachable when every content word of it is in the transcript; a
    CLOCK when it sits on the five-minute grid people speak in; a cadence when
    the words carry a cadence word at all. The date rule is this set's own and
    is stricter than the board's: `correction.py` says a changed date is never
    reachable (a day moved after the fact is a schedule change), which is a
    statement about CORRECTIONS. Here the day was SAID, so the test is that its
    content words are in the words — the same test as a title's.
    """
    from assistant.intent import correction

    said = row["text"]
    words = correction._words(said)
    bad = []
    for a in row["asks"]:
        if a["title"]:
            content = correction._content(a["title"])
            if not content or not all(w in words for w in content):
                bad.append((a["ask_id"], "title", a["title"]))
        if a["anaphor"]:
            # BY CONTENT WORDS, not as a substring. A stutter lands inside the
            # phrase — "the one from FROM before" — and the ask is still
            # perfectly reachable; an exact-match test would have called six
            # sound rows broken (2026-09-22).
            content = correction._content(a["anaphor"])
            if not all(w in words for w in content):
                bad.append((a["ask_id"], "anaphor", a["anaphor"]))
        for field in ("clock", "end_clock"):
            if a[field] and not correction._on_spoken_grid(a[field]):
                bad.append((a["ask_id"], field, a[field]))
        if a["date_phrase"]:
            content = correction._content(a["date_phrase"])
            if content and not all(w in words for w in content):
                bad.append((a["ask_id"], "date_phrase", a["date_phrase"]))
        if a["recurrence"] and not correction._CADENCE.search(said):
            bad.append((a["ask_id"], "recurrence", a["recurrence"]))
        for day in a["recur_days"] or []:
            if day not in said.lower():
                bad.append((a["ask_id"], "recur_days", day))
    return bad


def intended_still_reachable(row: dict) -> int:
    """How many gold titles the recogniser damage did NOT actually hide.

    Reported, never refused: `stt_letter_corrupt` on a two-word subject can
    leave every content word of the intended form still in the words, and that
    is a real (if mild) damage shape rather than a broken row.
    """
    from assistant.intent import correction
    words = correction._words(row["text"])
    n = 0
    for a in row["asks"]:
        if a["intended_title"]:
            content = correction._content(a["intended_title"])
            if content and all(w in words for w in content):
                n += 1
    return n


# ---------------------------------------------------------------------------

def main() -> int:
    rows = _load(COMMANDS)
    cases = _load(CASES)
    fails = []

    # 1 · REACHABLE
    bad_rows = [(r["id"], unreachable(r)) for r in rows]
    bad_rows = [(i, b) for i, b in bad_rows if b]
    if bad_rows:
        fails.append(f"{len(bad_rows)} commands carry a gold value the words "
                     f"cannot reach")

    # 2 · NO TEXT LEAK
    by_split = collections.defaultdict(set)
    for r in rows:
        by_split[r["split"]].add(r["text"])
    shared = by_split["train"] & by_split["test"]
    if shared:
        fails.append(f"{len(shared)} command texts appear in BOTH halves")

    # 3 · NO FAMILY LEAK
    fam_splits = collections.defaultdict(set)
    for r in rows:
        fam_splits[r["family"]].add(r["split"])
    leaked = [f for f, s in fam_splits.items() if len(s) > 1]
    if leaked:
        fails.append(f"{len(leaked)} families appear in BOTH halves: "
                     f"{leaked[:5]}")

    # 4 · BOTH HALVES CARRY EVERYTHING
    voice_splits, op_splits = collections.defaultdict(set), collections.defaultdict(set)
    for r in rows:
        voice_splits[r["voice"]].add(r["split"])
        for d in r["damage"]:
            op_splits[d].add(r["split"])
    from assistant.engine.llmjudge.datasets.v2 import damage as _damage
    from assistant.engine.llmjudge.datasets.v2 import voices as _voices
    for name in _voices.VOICE_IDS:
        if voice_splits.get(name, set()) != {"train", "test"}:
            fails.append(f"voice {name!r} is not in both halves "
                         f"({sorted(voice_splits.get(name, ()))})")
    for name in _damage.OPERATIONS:
        if op_splits.get(name, set()) != {"train", "test"}:
            fails.append(f"damage operation {name!r} is not in both halves "
                         f"({sorted(op_splits.get(name, ()))})")

    # 5 · EFFECTIVE (the plant is named, and a clean case plants nothing)
    for c in cases:
        if c["defect"] and not c.get("plant") and c["mutation"] != "dropped_ask":
            fails.append(f"case {c['id']} says defect but plants nothing")
            break
        if not c["defect"] and c.get("plant"):
            fails.append(f"case {c['id']} says clean but carries a plant")
            break
    known = {r["id"] for r in rows}
    orphans = [c["id"] for c in cases if c["command_id"] not in known]
    if orphans:
        fails.append(f"{len(orphans)} cases name a command that is not in "
                     f"commands_v2.jsonl")

    # ---------------------------------------------------------------- report
    print(f"\nV2 JUDGE SET — {len(rows)} commands · {len(cases)} cases\n")
    print("  DIVERSITY (the deliverable — a row count is not one)\n")
    head = f"    {'':<26}{'train':>8}{'test':>8}{'total':>8}"
    print(head)

    def line(label, key, source=None):
        src = source if source is not None else rows
        tr = {key(r) for r in src if r["split"] == "train"}
        te = {key(r) for r in src if r["split"] == "test"}
        tr.discard(None)
        te.discard(None)
        print(f"    {label:<26}{len(tr):>8}{len(te):>8}{len(tr | te):>8}")

    def multi(label, key, source=None):
        src = source if source is not None else rows
        tr = {v for r in src if r["split"] == "train" for v in key(r)}
        te = {v for r in src if r["split"] == "test" for v in key(r)}
        print(f"    {label:<26}{len(tr):>8}{len(te):>8}{len(tr | te):>8}")

    line("rows", lambda r: r["id"])
    line("distinct command texts", lambda r: r["text"])
    line("families (the split unit)", lambda r: r["family"])
    line("grammars (ask skeletons)", lambda r: "+".join(r["grammar"]))
    line("joiners", lambda r: r["joiner"])
    line("voices", lambda r: r["voice"])
    multi("damage operations", lambda r: r["damage"] or [])
    multi("ask shapes", lambda r: [a["shape"] for a in r["asks"]])
    multi("actions", lambda r: [a["action"] for a in r["asks"]])
    multi("spoken clock forms",
          lambda r: [a["said"]["clock_form"] for a in r["asks"]
                     if a["said"]["clock_form"]])
    multi("distinct subjects", lambda r: [a["title"] for a in r["asks"] if a["title"]])
    multi("date phrases", lambda r: [a["date_phrase"] for a in r["asks"]
                                     if a["date_phrase"]])
    multi("cadences", lambda r: [a["recurrence"] for a in r["asks"]
                                 if a["recurrence"]])
    line("cases", lambda c: c["id"], source=cases)
    line("mutations", lambda c: c["mutation"], source=cases)

    print("\n  ROWS PER SPLIT")
    n_rows = collections.Counter(r["split"] for r in rows)
    n_cases = collections.Counter(c["split"] for c in cases)
    for s in ("train", "test"):
        print(f"    {s:<26}{n_rows[s]:>8} commands{n_cases[s]:>8} cases")

    print("\n  ASKS PER COMMAND")
    for k, v in sorted(collections.Counter(r["n_asks"] for r in rows).items()):
        print(f"    {k} ask(s){v:>26}")

    print("\n  DAMAGE OPERATIONS (rows carrying each, by split)")
    per_op = collections.Counter((d, r["split"]) for r in rows for d in r["damage"])
    for name in sorted(_damage.OPERATIONS):
        gold_changing = " · defines a gold change" if name in _damage.GOLD_CHANGING else ""
        print(f"    {name:<26}{per_op[(name, 'train')]:>8}"
              f"{per_op[(name, 'test')]:>8}{gold_changing}")
    print(f"    {'(undamaged speech)':<26}"
          f"{sum(1 for r in rows if not r['damage'] and r['split'] == 'train'):>8}"
          f"{sum(1 for r in rows if not r['damage'] and r['split'] == 'test'):>8}")

    print("\n  VOICES (rows, by split)")
    per_voice = collections.Counter((r["voice"], r["split"]) for r in rows)
    for name in _voices.VOICE_IDS:
        print(f"    {name:<26}{per_voice[(name, 'train')]:>8}"
              f"{per_voice[(name, 'test')]:>8}")

    print("\n  MUTATIONS (cases, by split) — `expect` is the finding type the "
          "defect should\n  produce; a dash means TODAY'S TAXONOMY HAS NO NAME "
          "for it, which is the\n  measurement, not an omission.")
    per_mut = collections.Counter((c["mutation"], c["split"]) for c in cases)
    expects = collections.defaultdict(set)
    for c in cases:
        expects[c["mutation"]].add(c["expect"])
    for name in sorted(per_mut and {m for m, _s in per_mut}):
        want = sorted(x for x in expects[name] if x) or ["—"]
        print(f"    {name:<26}{per_mut[(name, 'train')]:>8}"
              f"{per_mut[(name, 'test')]:>8}   {' / '.join(want)}")

    blind = sum(1 for c in cases if c["defect"] and c["expect"] is None)
    print(f"\n    planted, with a finding type   "
          f"{sum(1 for c in cases if c['defect'] and c['expect']):>6}")
    print(f"    planted, BLIND to the taxonomy {blind:>6}")
    print(f"    clean (the false-flag pool)    "
          f"{sum(1 for c in cases if not c['defect']):>6}")

    still = sum(intended_still_reachable(r) for r in rows)
    damaged = sum(1 for r in rows for a in r["asks"] if a["intended_title"])
    print(f"\n  recogniser damage that still leaves the intended title "
          f"reachable: {still}/{damaged}")

    if fails:
        print("\n  REFUSED:")
        for f in fails:
            print(f"    ✗ {f}")
        for rid, bad in bad_rows[:8]:
            print(f"      {rid}: {bad}")
        print()
        return 1
    print("\n  ✓ reachable · no text leak · no family leak · both halves carry "
          "every voice\n    and every damage operation · every plant is named"
          "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
