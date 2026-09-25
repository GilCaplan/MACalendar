"""Build the LLMJudge isolation set — the cases, not the objects.

    python -m assistant.engine.llmjudge.datasets.generate

Writes `judge_cases.jsonl` beside this file. **A generator lives in the folder
whose data it generates** (CLAUDE.md, 2026-09-10) — four of these rotted at once
by living somewhere else, and the survivor was the one still in `scripts/`.

## Where the labels come from, and why they are free

Judging is a task with no natural ground truth: you cannot label "was this
object right" without already knowing the right object. FastRule's 7,200 does
know — every row carries the gold action, the gold item and the gold slots — so
a case is built by taking a row the converter gets RIGHT and then **planting a
known defect in it**. The label is the defect, and it is exact by construction.

## Why planting, rather than mining real failures

A set mined from the engine's actual output is dominated by objects that are
CORRECT, because most of them are. On such a set a judge that says "fine" to
everything scores about 90%, and the number would be read as success. Planting
fixes the class balance and, more importantly, makes the metric a PAIR:

    catch rate       flagged / planted        — on the mutated cases
    false-flag rate  flagged / clean          — on the untouched ones

Neither is meaningful alone. Always-accept wins the second; always-reject wins
the first. `experiments/judge_board.py` reports both, per mutation.

## The rows are RECIPES, not objects

Each row stores the gold Item and the mutation to apply — never a serialised
intent. The board rebuilds the object with the real converter
(`fastrule.build`), exactly as `stage_board.py --input gold` does, so the thing
being judged is the thing production would produce and not a fixture that drifts
away from it.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import random
import re

from assistant.common.scratch_env import scratch_env

#: THE CLOCK the cases were generated at, and the one any board MUST replay
#: them at. It lives here because it is a property of the DATA, not of a run: a
#: case whose plant depends on "the day after tomorrow" resolving to a clock
#: time is only valid at the moment it was resolved. `judge_board.py` imports
#: it rather than keeping its own.
CLOCK = _dt.datetime(2026, 9, 9, 10, 0)

HERE = pathlib.Path(__file__).resolve().parent
# In datasets/, parents[1] is the STAGE folder — the CLAUDE.md `ROOT = parents[1]`
# trap, which means the repo root before the per-stage move and the stage after.
STAGE = HERE.parent
SOURCE = STAGE.parent / "fastrule" / "datasets" / "fastrule_7200.jsonl"
OUT = HERE / "judge_cases.jsonl"

#: Titles to plant as fabrications. Deliberately ordinary calendar nouns — a
#: nonsense string would be caught by any check at all, and would measure
#: nothing. The plant is only used when none of its words appear in the row's
#: own text, so "invented" always means invented for that row.
#:
#: **The choice ROTATES.** The first version took the first candidate that fit,
#: which meant "physiotherapy" won 269 times out of 269 — so the board was
#: measuring whether the judge catches one specific token, not whether it
#: catches fabrications. Found 2026-09-10 when Gil asked what the score meant.
_FABRICATIONS = ("physiotherapy", "budget review", "team standup",
                 "car service", "piano lesson", "board meeting",
                 "dermatology referral", "quarterly audit", "violin practice",
                 "boiler inspection", "tax filing", "orthodontist checkup")

#: NEAR-MISS plants: a title that SHARES a word with the transcript but names
#: the wrong thing. These are the hard case and the set had none of them — every
#: fabrication had zero word overlap, and `names_nothing_spoken` fires on zero
#: word overlap, so the check and the test agreed BY CONSTRUCTION rather than on
#: merit. A near miss is where the model's answer actually decides the outcome.
#:
#: Built by keeping the row's own verb and replacing its subject noun, which is
#: exactly the shape of the real defect: "buy groceries" produced from
#: "buy milk".
_NEAR_MISS_NOUNS = ("groceries", "paperwork", "batteries", "prescription",
                    "insurance", "textbooks")

#: What the program calls a calendar entry when it has no name for one. The
#: measured defect: "Create an event now to go out for a run" committed an event
#: titled `event` at confidence 1.00, and the user got an event called "event".
_GENERIC = {"event": "Event", "task": "Reminder", "review": "Event"}

#: RE-CUT 2026-09-10 with the stage. `missing` and `not_asked`-as-`extra` are
#: gone: both were defined by an ask list this stage no longer builds. What
#: replaces the second is `unrelated_object` — an object NOTHING in the words
#: supports, which is a per-object question and a stronger test.
MUTATIONS = (
    ("clean", None),
    ("generic_title", "ungrounded_subject"),
    ("invented_title", "ungrounded_subject"),
    ("near_miss_title", "ungrounded_subject"),
    ("dropped_date", "unsupported_field"),
    ("dropped_time", "unsupported_field"),
    ("unrelated_object", "not_an_ask"),
)


def _words(text: str) -> set:
    return set(re.findall(r"[a-z']+", (text or "").casefold()))


def _fabrication_for(text: str, rng: "random.Random | None" = None) -> "str | None":
    """A title whose every word is absent from this row's text.

    Shuffled per row rather than scanned in order: taking the first fit made one
    noun win every time, and a board with one plant word measures that word.
    """
    have = _words(text)
    pool = list(_FABRICATIONS)
    (rng or random.Random(0)).shuffle(pool)
    for cand in pool:
        if not (_words(cand) & have):
            return cand
    return None


def _near_miss_for(title: str, text: str, rng: "random.Random") -> "str | None":
    """The row's own leading word, plus a subject noun nobody said.

    "buy milk" -> "buy groceries". The verb is real and the subject is not,
    which is the shape the zero-overlap test CANNOT see: it shares a word, so
    only the subject-noun stop list or the model's own answer can catch it.
    """
    # The shared word must be a CONTENT word, or the plant is not a near miss:
    # "the textbooks" shares only an article, which the subject test already
    # treats as no overlap, so it would be caught for the wrong reason and
    # measure nothing.
    from assistant.engine.llmjudge.verdict import _TITLE_STOP
    head = [w for w in re.findall(r"[a-z']+", (title or "").lower())
            if len(w) > 2 and w not in _TITLE_STOP]
    if not head:
        return None
    have = _words(text)
    pool = list(_NEAR_MISS_NOUNS)
    rng.shuffle(pool)
    for noun in pool:
        if noun not in have:
            return f"{head[0]} {noun}"
    return None


def _applicable(row: dict, resolved: set, rng: random.Random) -> "list[tuple[str, str | None]]":
    """Which mutations this row can carry.

    A mutation that cannot be planted honestly is skipped rather than
    approximated. `resolved` is what `decompose_validate` ACTUALLY produced for
    this item, and it is why this function needs the resolver rather than the
    row alone: "client call the day after tomorrow, all day" carries a time
    PHRASE but resolves no clock, so planting `dropped_time` on it removes
    nothing, the object is unchanged, and the board scores a miss against a
    defect that was never planted. Found on the first board run, 2026-09-10.
    """
    slots = row["expect"].get("slots") or {}
    title = slots.get("title") or (slots.get("titles") or [""])[0]
    out = [("clean", None)]
    if title:
        out.append(("generic_title", "ungrounded_subject"))
        if _fabrication_for(row["text"], rng):
            out.append(("invented_title", "ungrounded_subject"))
        if _near_miss_for(title, row["text"], rng):
            out.append(("near_miss_title", "ungrounded_subject"))
    # A SLOT MUTATION IS ONLY PLANTABLE WHERE THE ACTION CARRIES THAT SLOT.
    #
    # `delete_todo` and `complete_todo` map no date; `query_schedule` maps no
    # clock. Removing a slot the object never reads changes nothing the check
    # can see, so the board scored it a MISS and the deterministic slot check
    # looked like 92% when it is exactly 100% on everything answerable — 6
    # unanswerable plants, 6 misses, the same rows (verify.py, 2026-09-10).
    from assistant.engine.llmjudge.render import SLOT_BACKED
    carries = set((SLOT_BACKED.get(row["expect"].get("action", "")) or {}).values())
    if "date" in resolved and "date" in carries:
        out.append(("dropped_date", "unsupported_field"))
    if "start_time" in resolved and "start_time" in carries:
        out.append(("dropped_time", "unsupported_field"))
    if _fabrication_for(row["text"], rng):
        out.append(("unrelated_object", "not_an_ask"))
    return out


def _resolve(rows: list) -> dict:
    """`{row id: the value keys decompose_validate really resolved}`.

    Deterministic and model-free — the resolver is spaCy plus the date
    recogniser — but it must run at `CLOCK`, because that is when the cases
    claim to have been resolved.
    """
    scratch_env("judgegen_", keep=("LOCATION", "MODELS", "LABEL_FEEDBACK",
                                   "HEARTBEATS", "HUD_STATE", "DEVICE_SECRET",
                                   "DEVICES"))

    from freezegun import freeze_time
    from assistant.engine import llm as _llm
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.state import EngineState, Item

    # Warm spaCy OUTSIDE the frozen clock — building its pipeline under
    # freezegun raises, and every row would then resolve nothing.
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    out: dict = {}
    with freeze_time(CLOCK):
        for r in rows:
            gi = r["expect"]["item"]
            it = Item(id="item_1", kind=gi.get("kind") or "event",
                      text=gi.get("text") or r["text"], time=gi.get("time"))
            st = EngineState(raw_text=r["text"], text=r["text"], source="test")
            st.items = [it]
            try:
                _dv.resolve_values(st, CLOCK.date())
            except Exception:
                pass
            out[r["id"]] = {k for k, v in (it.slots or {}).items()
                            if v not in (None, "", [], {})}
    return out


def build(limit_per_split: int = 900, seed: int = 17) -> list:
    rows = [json.loads(l) for l in SOURCE.open()]
    rows = [r for r in rows
            if r["expect"].get("atomic", True)
            and r["expect"].get("action") not in ("propose", "mixed")
            and (r["expect"].get("item") or {}).get("text")]

    by_split: dict = {"train": [], "test": []}
    rng = random.Random(seed)
    rng.shuffle(rows)
    for r in rows:
        split = r.get("split", "train")
        if split not in by_split or len(by_split[split]) >= limit_per_split:
            continue
        by_split[split].append(r)

    resolved = _resolve([r for chosen in by_split.values() for r in chosen])

    cases = []
    for split, chosen in by_split.items():
        for r in chosen:
            options = _applicable(r, resolved.get(r["id"], set()), rng)
            # ONE mutation per source row, chosen round-robin by a seeded
            # shuffle. Emitting every mutation of every row would correlate the
            # cases — the same sentence seven times — and a board whose rows are
            # not independent reports a confidence interval it has not earned.
            # HALF THE ROWS ARE CLEAN. Cycle 4's sealed read put the false-flag
            # rate on ELEVEN clean cases — a number wide enough to be useless,
            # and it is the one most likely to block shipping. Planting on every
            # row was free; measuring the cost of the catch was not.
            if rng.random() < 0.5:
                name, expect = "clean", None
            else:
                planted = [o for o in options if o[0] != "clean"]
                name, expect = planted[rng.randrange(len(planted))] if planted \
                    else ("clean", None)
            cases.append({
                "id": f"{r['id']}#{name}",
                "split": split,
                "text": r["text"],
                "item": r["expect"]["item"],
                "gold_action": r["expect"].get("action", ""),
                "tier": r.get("tier", ""),
                "mutation": name,
                "expect": expect,
                "plant_title": (
                    _fabrication_for(r["text"], random.Random(hash(r["id"]) & 0xffff))
                    if name in ("invented_title", "unrelated_object")
                    else _near_miss_for(
                        (r["expect"].get("slots") or {}).get("title")
                        or ((r["expect"].get("slots") or {}).get("titles") or [""])[0],
                        r["text"], random.Random(hash(r["id"]) & 0xffff))
                    if name == "near_miss_title" else None),
                "generic_title": (_GENERIC.get(r["expect"]["item"].get("kind", "event"),
                                               "Event")
                                  if name == "generic_title" else None),
            })
    cases.sort(key=lambda c: c["id"])
    return cases


def main() -> int:
    cases = build()
    with OUT.open("w") as fh:
        for c in cases:
            fh.write(json.dumps(c, sort_keys=True) + "\n")
    counts: dict = {}
    for c in cases:
        counts.setdefault(c["split"], {}).setdefault(c["mutation"], 0)
        counts[c["split"]][c["mutation"]] += 1
    print(f"{len(cases)} cases -> {OUT}")
    for split in sorted(counts):
        total = sum(counts[split].values())
        detail = "  ".join(f"{k} {v}" for k, v in sorted(counts[split].items()))
        print(f"  {split:5s} {total:5d}   {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
