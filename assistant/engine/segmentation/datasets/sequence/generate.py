"""The SEQUENCE dataset — "X followed by Y followed by Z" (DEVQA Q51).

    python -m assistant.engine.segmentation.datasets.sequence.generate          # write both files
    python -m assistant.engine.segmentation.datasets.sequence.generate --check  # rebuild, compare, write nothing

One generator, two files, the SAME rows:

    segmentation/datasets/sequence/sequence.jsonl      the cut + each item's RELATION
    decompose_validate/datasets/chain/chain.jsonl      each item's RESOLVED values

Everything is gold BY CONSTRUCTION. A row is built from a structured
specification — parts, joiners, where the clocks and days sit — and both golds
are computed from that specification by the rules below. Nothing in
`assistant/engine/` is run or imported to decide a gold value, and no model is
asked; a gold that came from the engine would measure nothing.

THE RULES THE GOLD FOLLOWS
--------------------------
Segmentation (`sequence.jsonl`), in the conventions of `../generated.jsonl`
and `../../experiments/SPEC.md`:

* `action` is the item's own words with its time words and the JOINER between
  it and the item before taken out. Fillers, hedges and openers stay in the
  action of the item they sit in, as they do in `generated.jsonl`. A stated
  duration ("for 2 hours") and a "right after <named>" anchor are not time
  references there and stay in the action too.
* `time` is the words as spoken, day first: the item's own day, else a LEADING
  day (which scopes over every item), else the date floor `today`; then its
  clock; then a lead time ("10 minutes before"). An interior day never reaches
  another item (SPEC "interior -> binds to its own item").
* `tag` is what the item's OWN words say: a stated clock or range makes an
  event (Q26), a person encounter or a role call is an event (Q47, Q50), an
  untimed to-do is a task. A to-do that decompose_validate will CHAIN is still
  `task` here — chaining is the next stage's decision, not the cutter's.
* `relation` is null on the first item, else `{to_index, kind}`. The kind is
  read from the words between the two items with the precedence
  sequence > sentence > list (so ". Then" is a sequence and ". Also," a
  sentence). Two readings are NOT between the items and are labelled by
  meaning: a trailing "afterwards" / "after that" ("gym at 9, lunch
  afterwards") is a sequence, and "X right after <named earlier item>" is a
  sequence whose `to_index` is THAT named item. An enumeration ("at 9 and 11")
  is `same_span`.

decompose_validate (`chain.jsonl`), Q51 plus the conventions it builds on,
against the FIXED ANCHOR below:

* A sequence item with no clock of its own starts when the item it follows
  ENDS, plus the gap (0). That end is the stated end (a range), else start +
  stated duration, else start + 60 minutes. The chained item lasts its own
  stated duration, else 60 minutes.
* The chain beats a meal's own hour; a stated clock always wins and the chain
  continues from it.
* An untimed item that is NOT chained resolves the usual way: a meal's own
  hour (breakfast 09:00, lunch/brunch 13:00, dinner/supper 19:00, Q32), else
  09:00 (Q36).
* A sequence part with no day of its own inherits the DATE of the item it
  follows. A list or sentence part keeps today's behaviour: its own day, else
  the leading day, else today; it is never chained.
* A to-do in a sequence with no clock of its own is chained as an EVENT with
  `linked_todo: true`. A to-do outside a sequence stays a to-do (date = its
  day, no clock). A to-do with its own clock is an event (Q25), not linked.
* A role call ("call the plumber") is an event (Q50); its companion to-do is
  Q50's and filed by the executor, so its `linked_todo` gold is `null` — not
  scored by this stage's board. A person encounter ("coffee with Dana",
  "call Dana") is an event, not linked (Q47).
* A NEW DAY partway through with no clock ("…, then on friday lunch") BREAKS
  the chain: a part on another day does not follow the one before it in time,
  so it resolves the usual way (a meal's own hour, else 09:00) on its own day,
  and the parts after it chain from it and inherit its day (decided
  2026-09-25 by the implementing session; family `s3_newday_untimed`).
* Chains stay inside one day and end before midnight (an event ending at
  24:00 is rejected, since the object layer caps it at 23:59), except the one
  family marked `rollover`, where the chained item rolls to the next date.

THE ANCHOR is 2026-09-09 06:00, a Wednesday. 06:00 is before every clock and
every default hour in the data, so Q42's "a clock that has already gone by
means tomorrow" never fires: the date floor is always today, and this dataset
measures the chain rather than that rule.

THE SPLIT is by FAMILY, 80/20, stratified by `bucket` over a stable hash of
the family name (`fastrule/datasets/generate.py`'s mechanism): every bucket
with two or more families has at least one in each half; a singleton stays in
train. The joiner sweep is forced per joiner instead (`_sweep_families`), so
every joiner keeps a train family. `build()` asserts no family is on both
sides.

`ambiguous: true` rows are shapes a reader could take two ways ("a talk
followed by questions", "later", "after lunch", an untimed to-do heading a
chain). They are generated and split like any other family and EXCLUDED from
every score.

WORDING AND DAMAGE (Gil, 2026-09-25: "capture the variety of wording … and
also account for misspellings, because maybe they get fixed, maybe they
don't"). Every sequence joiner is its own bank in `J`, swept by two families
each with events and to-dos on both sides. The DAMAGE families emit PAIRS: a
clean row and a damaged twin (misspelt joiner, split word, doubled joiner,
missing comma, typo'd title) with a different id, the same family and the SAME
gold — the gold is the intended command — tagged `damage: <operation>` and
linked by `twin`.

The filler banks are FastRule's (`fastrule/datasets/banks/fillers.json`,
names, event and task titles), read-only; only the non-forced base pools are
used. The titles are filtered (meal words go to the meal pool, role calls to
the role pool) so a title never carries a rule the family did not ask for.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[5]
FILLERS = REPO / "assistant/engine/fastrule/datasets/banks/fillers.json"
OUT_SEQ = HERE / "sequence.jsonl"
OUT_CHAIN = REPO / "assistant/engine/decompose_validate/datasets/chain/chain.jsonl"

SEED = "sequence-q51-v1"
ANCHOR = "2026-09-09T06:00"          # Wednesday
TODAY = "2026-09-09"
ROWS_PER_FAMILY = 26
DECOY_ROWS = 20
TEST_FRAC = 0.2
DEFAULT_LEN = 60
GAP = 0

# ---------------------------------------------------------------------------
# Closed tables — the gold's own readings, never the resolver's
# ---------------------------------------------------------------------------

#: spoken clock -> minutes after midnight. Bare 1-6 are PM (the bare-hour
#: convention); bare 7 and 8 are never used (Q28 asks about them).
CLOCKS = {
    "at 7am": 420, "at 7:30am": 450, "at 8am": 480, "at 8:30am": 510,
    "at 9": 540, "at 9am": 540, "at nine": 540, "at 9:30": 570,
    "at 10": 600, "at 10am": 600, "at ten": 600, "at 10:30": 630,
    "at ten thirty": 630, "at 11": 660, "at 11am": 660, "at 11:15": 675,
    "at noon": 720, "at 12:30": 750, "at 1": 780, "at 1pm": 780,
    "at 1:30": 810, "at 2": 840, "at 2pm": 840, "at 2:30": 870,
    "at 14:00": 840, "at 3": 900, "at 3pm": 900, "at 3:45pm": 945,
    "at 4": 960, "at 4:30": 990, "at 16:30": 990, "at 5": 1020,
    "at 5pm": 1020, "at 5:30": 1050, "at 6": 1080, "at 6pm": 1080,
    "at half past six": 1110, "at 6:45": 1125, "at 7pm": 1140,
    "at 7:30pm": 1170, "at 8pm": 1200, "at 8:30pm": 1230, "at 9pm": 1260,
}
RANGES = {
    "from 9 to 10:30": (540, 630), "from 9:30 to 11": (570, 660),
    "from 10am to 11:30am": (600, 690), "from 11 to 1": (660, 780),
    "from noon to 1": (720, 780), "from 1 to 3": (780, 900),
    "from 2 to 4": (840, 960), "between 2 and 4": (840, 960),
    "from 3 to 4pm": (900, 960), "from 4 to 5:30": (960, 1050),
    "from 5 to 6:30": (1020, 1110),
}
DURATIONS = {
    "for 2 hours": 120, "for two hours": 120, "for an hour": 60,
    "for 30 minutes": 30, "for half an hour": 30, "for 45 minutes": 45,
    "for 90 minutes": 90, "for an hour and a half": 90, "for 3 hours": 180,
    "for 20 minutes": 20,
}
#: a day phrase -> ISO date, from the Wednesday anchor. Rosh Hashana (11-13
#: Sep 2026 evening to evening) and Yom Kippur (20-21 Sep) are avoided.
DAYS = {
    "tomorrow": "2026-09-10", "on thursday": "2026-09-10",
    "on friday": "2026-09-11", "this friday": "2026-09-11",
    "the day after tomorrow": "2026-09-11", "on monday": "2026-09-14",
    "on tuesday": "2026-09-15", "on the 15th": "2026-09-15",
    "on the 16th": "2026-09-16", "on the 17th": "2026-09-17",
}
LEADS = ["and remind me 10 minutes before", "and remind me an hour before",
         ", remind me 30 minutes before", "and give me a heads up 15 minutes before"]
#: enumerations: two bare clocks after one "at"
ENUMS = [("at 9", "11", 540, 660), ("at 10", "2", 600, 840),
         ("at 9:30", "1", 570, 780), ("at 11", "3", 660, 900),
         ("at 10", "4", 600, 960)]
MEAL_HOURS = (("breakfast", 540), ("brunch", 780), ("lunch", 780),
              ("dinner", 1140), ("supper", 1140))

#: joiner classes: (lexemes, relation kind). Every SEQUENCE bank Gil listed
#: (2026-09-25: "capture the variety of wording that can be used for this
#: sequencing") is its own class, so the boards can report per joiner.
J = {
    # --- sequence ------------------------------------------------------------
    "then": ([" then ", ", then "], "sequence"),
    "and_then": ([" and then ", ", and then "], "sequence"),
    "followed": ([" followed by ", ", followed by "], "sequence"),
    "then_after": ([" then after ", ", then after "], "sequence"),
    "and_then_after_that": ([" and then after that ", ", and then after that, "], "sequence"),
    "after_that": ([", after that ", " and after that ", ". After that, "], "sequence"),
    "right_after_that": ([" and right after that ", ", right after that "], "sequence"),
    "straight_after_that": ([", straight after that ", " and straight after that "], "sequence"),
    "afterwards": ([" and afterwards ", ", afterwards "], "sequence"),
    "afterward": ([" and afterward ", ", afterward "], "sequence"),
    "after_which": ([", after which ", " after which "], "sequence"),
    "next": ([", next ", ". Next, "], "sequence"),
    "and_next": ([" and next ", ", and next "], "sequence"),
    "next_up": ([", next up ", ". Next up, "], "sequence"),
    "and_after": ([" and after ", ", and after "], "sequence"),
    "after_this": ([", after this ", " and after this "], "sequence"),
    "once_thats_done": ([", once that's done, ", " and once that's done "], "sequence"),
    "once_done": ([", once done, ", " and once done, "], "sequence"),
    "when_thats_done": ([", when that's done, ", " and when that's done "], "sequence"),
    "when_im_done": ([", when i'm done, ", ", when i'm done with that, ", " and when i'm done with that "], "sequence"),
    "when_finished": ([", when finished, ", " and when finished "], "sequence"),
    "as_soon_as": ([", as soon as that's done, ", " and as soon as that's done "], "sequence"),
    "subsequently": ([", subsequently ", ". Subsequently, "], "sequence"),
    "sent_then": ([". Then ", "; then ", ". Then, "], "sequence"),
    "then_finally": ([", then finally ", " and finally ", ", finally "], "sequence"),
    "trail": ([", "], "sequence"),      # the marker sits at the end of the NEXT part
    "anchor": ([", and ", ", "], "sequence"),   # "right after <named>" in the next part
    # --- not a sequence --------------------------------------------------------
    "and": ([" and ", ", and "], "list"),
    "comma": ([", "], "list"),
    "also": ([" and also ", ", also "], "list"),
    "plus": ([" plus "], "list"),
    "sentence": ([". ", "; "], "sentence"),
    "enum": ([" and "], "same_span"),
    # --- borderline: a TIME as much as a seam; ambiguous families only ----------
    "later": ([", later ", " and later "], "sequence"),
    "after_meal": ([" and after lunch ", ", after lunch "], "sequence"),
}
#: joiners whose next part must open with a VERB: "and after <noun>" and
#: "then after <noun>" read as a time ("and after lunch"), which is the
#: ambiguous family's shape, not this one's.
VERB_NEXT = {"then_after", "and_after"}
#: and the mirror: "followed by <verb phrase>" is not English, so the part
#: after these is a noun phrase (an event, a meal, "coffee with Dana").
#: A bare " after that " / " next " with no comma is left out of every clean
#: bank for the same reason — "a run after that family dinner" reads as an
#: anchor, not a seam; the missing-comma DAMAGE family is where it belongs.
NOUN_NEXT = {"followed"}

FILLER_OPENERS = ["um so ", "uh ", "okay so ", "so ", "um "]
HEDGES = ["i think ", "i guess ", "probably ", "maybe "]
POLITE = ["could you please put ", "can you add ", "please put ", "hey can you put "]

# ---------------------------------------------------------------------------
# Title pools
# ---------------------------------------------------------------------------

_MEAL_RE = re.compile(r"\b(breakfast|brunch|lunch|dinner|supper)\b")


def _pools(fillers: dict) -> dict:
    ev_skip = {"coffee with a friend", "moving day", "dinner reservation",
               "birthday dinner", "haircut appointment"}
    events = [t for t in fillers["event_titles"]
              if t not in ev_skip and not _MEAL_RE.search(t)]
    events += ["gym", "a run", "physio", "the shiur", "davening", "a haircut"]
    task_skip = {"call the plumber", "schedule a haircut", "book a flight",
                 "confirm the reservation"}
    tasks = [t for t in fillers["task_titles"] if t not in task_skip]
    names = fillers["names"]
    return {
        "E": events,
        "T": tasks,
        "names": names,
        "P": ["coffee with {n}", "meet {n}", "catch up with {n}", "drinks with {n}",
              "call {n}", "a walk with {n}", "training with {n}", "study with {n}"],
        "Pn": ["coffee with {n}", "drinks with {n}", "a walk with {n}",
               "training with {n}", "a meeting with {n}"],
        "R": ["call the plumber", "call the bank", "call the electrician",
              "phone the insurance company", "call the vet", "ring the landlord",
              "call the dentist's office", "call the gas company"],
        "M_morning": ["breakfast", "breakfast with {n}", "a quick breakfast", "brunch with {n}"],
        "M_midday": ["lunch", "lunch with {n}", "a quick lunch", "team lunch", "a working lunch"],
        "M_evening": ["dinner", "dinner with {n}", "family dinner", "supper", "dinner with the kids"],
        # (full title, the short name a later part uses to point back at it)
        "N": [("davening", "davening"), ("the gym", "the gym"),
              ("yoga class", "yoga"), ("the team meeting", "the meeting"),
              ("the dentist appointment", "the dentist"), ("physio", "physio"),
              ("the shiur", "the shiur"), ("the workshop", "the workshop"),
              ("the tennis lesson", "tennis"), ("the school play", "the play")],
    }


def meal_hour(title: str) -> "int | None":
    t = title.lower()
    for word, minutes in MEAL_HOURS:
        if re.search(rf"\b{word}\b", t):
            return minutes
    return None


def hhmm(m: int) -> str:
    m %= 24 * 60
    return f"{m // 60:02d}:{m % 60:02d}"


def add_days(iso: str, n: int) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Family specifications
# ---------------------------------------------------------------------------
# A part is a dict:
#   c      class: E event · M meal · P person encounter · R role call ·
#          T to-do · TR "remind me to" to-do · N named event (anchorable)
#   clock  None | "c" clock | "r" range | "enum" two clocks (-> two items)
#   dur    a stated duration ("pre": before the clock, "post": after it)
#   day    None | "own" (inside the part) — `daypos` "pre" | "mid" | "post"
#   anchor index of the earlier part a "right after <named>" points to
#   trail  "afterwards" | "after that" — a sequence marker at the part's end
# A family is (name, bucket, parts, joiners, opts). `joiners[i]` joins part i
# to part i+1. opts: lead_day, lead_tail, style ("filler" | "hedge" |
# "polite" | "caps"), decoy (a callable row builder), ambiguous, rollover,
# title ("bare" | "book") — E titles only.


def P_(c, clock=None, dur=None, day=None, daypos="mid", anchor=None, trail=None):
    return {"c": c, "clock": clock, "dur": dur, "day": day, "daypos": daypos,
            "anchor": anchor, "trail": trail}


FAMILIES = [
    # ---- two parts -------------------------------------------------------
    ("s2_then_Eclock_meal", "basic", [P_("E", "c"), P_("M")], ["then"], {}),
    ("s2_andthen_Eclock_E", "basic", [P_("E", "c"), P_("E")], ["and_then"], {"title": "book"}),
    ("s2_followed_Eclock_E", "basic", [P_("E", "c"), P_("E")], ["followed"], {}),
    ("s2_afterthat_Eclock_P", "basic", [P_("E", "c"), P_("P")], ["after_that"], {}),
    ("s2_afterwards_Mclock_E", "basic", [P_("M", "c"), P_("E")], ["afterwards"], {}),
    ("s2_rightafterthat_Eclock_P", "basic", [P_("E", "c"), P_("P")], ["right_after_that"], {}),
    ("s2_next_Eclock_E", "basic", [P_("E", "c"), P_("E")], ["next"], {}),
    ("s2_sentthen_Eclock_meal", "basic", [P_("E", "c"), P_("M")], ["sent_then"], {"style": "caps"}),
    ("s2_trail_afterwards", "basic", [P_("E", "c"), P_("M", trail="afterwards")], ["trail"], {}),
    ("s2_trail_afterthat", "basic", [P_("E", "c"), P_("E", trail="after that")], ["trail"], {}),
    ("s2_then_durpost_meal", "duration", [P_("E", "c", dur="post"), P_("M")], ["then"], {}),
    ("s2_followed_durpre_E", "duration", [P_("E", "c", dur="pre"), P_("E")], ["followed"], {}),
    ("s2_then_range_meal", "duration", [P_("E", "r"), P_("M")], ["then"], {}),
    ("s2_afterthat_range_P", "duration", [P_("E", "r"), P_("P")], ["after_that"], {}),
    ("s2_then_chaineddur", "duration", [P_("E", "c"), P_("E", dur="post")], ["then"], {}),
    ("s2_then_untimedmeal_head", "untimed_head", [P_("M"), P_("E")], ["then"], {}),
    ("s2_followed_untimedE_head", "untimed_head", [P_("E"), P_("E")], ["followed"], {}),
    ("s2_then_untimedE_dur_head", "untimed_head", [P_("E", dur="post"), P_("M")], ["then"], {}),
    ("s2_then_untimedP_head", "untimed_head", [P_("P"), P_("E")], ["then"], {}),
    ("s2_then_todoclock_todo", "todo_role", [P_("T", "c"), P_("T")], ["then"], {}),
    ("s2_afterthat_Eclock_remind", "todo_role", [P_("E", "c"), P_("TR")], ["after_that"], {}),
    ("s2_rightafterthat_Eclock_role", "todo_role", [P_("E", "c"), P_("R")], ["right_after_that"], {}),
    ("s2_then_roleclock_todo", "todo_role", [P_("R", "c"), P_("T")], ["then"], {}),
    ("s2_then_Pclock_todo", "todo_role", [P_("P", "c"), P_("T")], ["then"], {}),
    ("s2_leadday_then", "day", [P_("E", "c"), P_("M")], ["then"], {"lead_day": True}),
    ("s2_dayinside_mid_then", "day", [P_("E", "c", day="own", daypos="mid"), P_("M")], ["then"], {}),
    ("s2_dayinside_post_followed", "day", [P_("E", "c", day="own", daypos="post"), P_("E")], ["followed"], {}),
    ("s2_leadday_nocomma_afterthat", "day", [P_("E", "c"), P_("P")], ["after_that"], {"lead_day": "nocomma"}),
    # ---- three parts -----------------------------------------------------
    ("s3_then_then", "basic3", [P_("E", "c"), P_("M"), P_("E")], ["then", "then"], {}),
    ("s3_followed_followed", "basic3", [P_("E", "c"), P_("E"), P_("Pn")], ["followed", "followed"], {}),
    ("s3_andthen_afterthat", "basic3", [P_("E", "c"), P_("P"), P_("E")], ["and_then", "after_that"], {}),
    ("s3_first_then_finally", "basic3", [P_("E", "c"), P_("E"), P_("M")], ["then", "then_finally"], {"style": "first"}),
    ("s3_first_next_then", "basic3", [P_("E", "c"), P_("E"), P_("M")], ["next", "then"], {"style": "first"}),
    ("s3_clock_first_middle", "clocks", [P_("E", "c"), P_("E", "c"), P_("M")], ["then", "then"], {}),
    ("s3_clock_all", "clocks", [P_("E", "c"), P_("M", "c"), P_("E", "c")], ["then", "followed"], {}),
    ("s3_clock_none", "clocks", [P_("E"), P_("E"), P_("M")], ["then", "then"], {}),
    ("s3_clock_middle_only", "clocks", [P_("M"), P_("E", "c"), P_("M")], ["then", "afterwards"], {}),
    ("s3_clock_last_after_chain", "clocks", [P_("E", "c"), P_("M"), P_("E", "c")], ["followed", "then"], {}),
    ("s3_durations_mixed", "duration", [P_("E", "c", dur="post"), P_("E", dur="post"), P_("M")], ["then", "then"], {}),
    ("s3_range_then_then", "duration", [P_("E", "r"), P_("E"), P_("Pn")], ["then", "followed"], {}),
    ("s3_todo_chain", "todo_role", [P_("T", "c"), P_("T"), P_("T")], ["and_then", "then"], {}),
    ("s3_encounter_role", "todo_role", [P_("P", "c"), P_("R"), P_("E")], ["then", "after_that"], {}),
    ("s3_mixed_list_todo_tail", "mixed", [P_("E", "c"), P_("M"), P_("T")], ["then", "and"], {}),
    ("s3_mixed_list_clocked", "mixed", [P_("E", "c"), P_("M"), P_("E", "c")], ["then", "and"], {}),
    ("s3_mixed_list_head", "mixed", [P_("T"), P_("E", "c"), P_("M")], ["and", "then"], {}),
    ("s3_mixed_also_meal", "mixed", [P_("E", "c"), P_("Pn"), P_("M")], ["followed", "also"], {}),
    ("s3_newday_clocked", "day", [P_("E", "c"), P_("M", "c", day="own", daypos="pre"), P_("E")], ["then", "then"], {}),
    ("s3_newday_untimed", "day", [P_("E", "c"), P_("M", day="own", daypos="pre"), P_("E")], ["then", "then"], {}),
    ("s3_leadday_mixed_todo", "day", [P_("E", "c"), P_("E"), P_("T")], ["then", "and"], {"lead_day": True}),
    ("s3_rightafter_named_P", "anchor", [P_("N", "c"), P_("E", "c"), P_("P", anchor=0)], ["and", "anchor"], {}),
    ("s3_rightafter_named_todo", "anchor", [P_("N", "c"), P_("M", "c"), P_("T", anchor=0)], ["comma", "anchor"], {}),
    ("s3_rightafter_prev", "anchor", [P_("E", "c"), P_("N", "c"), P_("P", anchor=1)], ["and", "anchor"], {}),
    ("s3_lead_tail", "style", [P_("E", "c"), P_("M"), P_("E")], ["then", "then"], {"lead_tail": True}),
    ("s3_filler", "style", [P_("E", "c"), P_("M"), P_("E")], ["then", "followed"], {"style": "filler"}),
    ("s3_hedge", "style", [P_("E", "c"), P_("P"), P_("M")], ["then", "then"], {"style": "hedge"}),
    ("s3_polite", "style", [P_("E", "c"), P_("E"), P_("M")], ["then", "then"], {"style": "polite"}),
    ("s3_caps_periods", "style", [P_("E", "c"), P_("M"), P_("E")], ["sent_then", "sent_then"], {"style": "caps"}),
    ("s3_enum_then", "mixed", [P_("E", "enum"), P_("M")], ["then"], {}),
    ("s3_sentence_then", "mixed", [P_("E", "c"), P_("M", "c"), P_("E")], ["sentence", "then"], {"style": "caps"}),
    # ---- four and five parts ---------------------------------------------
    ("s4_clock_resets", "long", [P_("E", "c"), P_("M"), P_("E", "c"), P_("M")], ["then", "and_then", "then"], {}),
    ("s4_first_then_then_finally", "long", [P_("T", "c"), P_("T"), P_("E"), P_("M")], ["then", "then", "then_finally"], {"style": "first"}),
    ("s4_mixed_joiners", "long", [P_("E", "c"), P_("E"), P_("M"), P_("P")], ["followed", "then", "afterwards"], {}),
    ("s4_leadday", "long", [P_("E", "c"), P_("E"), P_("M"), P_("E")], ["then", "after_that", "then"], {"lead_day": True}),
    ("s4_durations", "long", [P_("E", "c", dur="post"), P_("E", dur="post"), P_("M"), P_("E", dur="post")], ["then", "followed", "then"], {}),
    ("s4_todo_mix", "long", [P_("T", "c"), P_("T"), P_("E"), P_("TR")], ["then", "then", "after_that"], {}),
    ("s4_newday_clocked", "long", [P_("E", "c"), P_("M"), P_("E", "c", day="own", daypos="pre"), P_("M")], ["then", "then", "then"], {}),
    ("s5_then_x4", "long", [P_("E", "c"), P_("E"), P_("M"), P_("E"), P_("P")], ["then", "then", "then", "then"], {}),
    ("s5_list_inside_chain", "long", [P_("E", "c"), P_("M"), P_("P", "c"), P_("E"), P_("T")], ["then", "plus", "then", "and"], {}),
    ("s5_all_joiners", "long", [P_("E", "c"), P_("E"), P_("E"), P_("M"), P_("E")], ["followed", "right_after_that", "next", "afterwards"], {}),
    # ---- list controls: split, relation list/sentence, never chained -----
    ("l_and_clocked", "list", [P_("E", "c"), P_("E", "c")], ["and"], {}),
    ("l_comma_also", "list", [P_("E", "c"), P_("M", "c"), P_("E", "c")], ["comma", "also"], {}),
    ("l_meal_untimed", "list", [P_("E", "c"), P_("M")], ["and"], {}),
    ("l_todo", "list", [P_("E", "c"), P_("T")], ["and"], {}),
    ("l_plus_todos", "list", [P_("T"), P_("T")], ["plus"], {}),
    ("l_sentence", "list", [P_("E", "c"), P_("M", "c")], ["sentence"], {"style": "caps"}),
    ("l_leadday_and", "list", [P_("E", "c"), P_("M")], ["and"], {"lead_day": True}),
    # ---- rollover (the one family allowed past midnight) -----------------
    ("x_rollover", "rollover", [P_("E", "late"), P_("P")], ["then"], {"rollover": True}),
    # ---- ambiguous: generated, split, EXCLUDED from every score ----------
    ("amb_followed_by_programme", "ambiguous", None, None, {"ambiguous": "programme"}),
    ("amb_untimed_todo_head", "ambiguous", [P_("T"), P_("T")], ["then"], {"ambiguous": True}),
    ("amb_joiner_later", "ambiguous", [P_("E", "c"), P_("E")], ["later"], {"ambiguous": True}),
    ("amb_joiner_after_meal", "ambiguous", [P_("E", "c"), P_("E")], ["after_meal"], {"ambiguous": True}),
    # ---- decoys: sequence-looking words that must NOT split --------------
    ("d_and_then_well_see", "decoy", None, None, {"decoy": "well_see"}),
    ("d_remind_then", "decoy", None, None, {"decoy": "remind_then"}),
    ("d_until_then", "decoy", None, None, {"decoy": "until_then"}),
    ("d_back_then", "decoy", None, None, {"decoy": "back_then"}),
    ("d_if_free_then", "decoy", None, None, {"decoy": "if_then"}),
    ("d_next_adjective", "decoy", None, None, {"decoy": "next_adj"}),
    ("d_after_that_meeting", "decoy", None, None, {"decoy": "after_that_meeting"}),
    ("d_by_then", "decoy", None, None, {"decoy": "by_then"}),
    ("d_before_then", "decoy", None, None, {"decoy": "before_then"}),
]

#: THE JOINER SWEEP (Gil, 2026-09-25): every sequence bank, with events and
#: to-dos on both sides. Two families per joiner, from four rotating shape
#: pairs. The split is FORCED here rather than hashed per bucket: for about
#: 40% of joiners ONE of the two families is test and the other train, so the
#: test half holds unseen (joiner, shape) pairs while every joiner is still
#: seen in train.
_SWEEP_PAIRS = [
    ([P_("E", "c"), P_("T")], [P_("T", "c"), P_("E")]),
    ([P_("E", "c"), P_("M")], [P_("R", "c"), P_("TR")]),
    ([P_("M", "c"), P_("P")], [P_("T", "c"), P_("T")]),
    ([P_("P", "c"), P_("E", dur="post")], [P_("T", "c"), P_("R")]),
]
_SWEEP_VERB = ([P_("E", "c"), P_("T")], [P_("T", "c"), P_("R")])
_SWEEP_NOUN = ([P_("E", "c"), P_("M")], [P_("T", "c"), P_("Pn")])
SWEEP_JOINERS = [k for k, (_lx, kind) in J.items() if kind == "sequence"
                 and k not in ("trail", "anchor", "later", "after_meal")]


def _sweep_families():
    out = []
    for i, j in enumerate(SWEEP_JOINERS):
        a, b = (_SWEEP_VERB if j in VERB_NEXT else _SWEEP_NOUN if j in NOUN_NEXT
                else _SWEEP_PAIRS[i % len(_SWEEP_PAIRS)])
        h = _stable(SEED, "sweep", j)
        test_side = "a" if (h >> 8) % 2 else "b"
        for side, parts in (("a", a), ("b", b)):
            forced = "test" if (h % 5 < 2 and side == test_side) else "train"
            out.append((f"jw_{j}_{side}", "joiners", [dict(p) for p in parts], [j],
                        {"force_split": forced, "rows": SWEEP_ROWS}))
    return out


#: DAMAGE (Gil, 2026-09-25: "account for misspellings, because maybe they get
#: fixed, maybe they don't"). Each family emits PAIRS: the clean row and its
#: damaged twin, same family, different ids, the SAME gold — the gold is the
#: intended command. `damage` names the operation.
DAMAGE_FAMILIES = [
    ("dmg_followed_E", [P_("E", "c"), P_("M")], ["followed"], "misspelt_followed", {}),
    ("dmg_followed_T3", [P_("T", "c"), P_("E"), P_("T")], ["followed", "and_then"], "misspelt_followed", {}),
    ("dmg_afterwards", [P_("M", "c"), P_("E")], ["afterwards"], "misspelt_afterwards", {}),
    ("dmg_afterwards_trail", [P_("E", "c"), P_("M", trail="afterwards")], ["trail"], "misspelt_afterwards", {}),
    ("dmg_than_E", [P_("E", "c"), P_("P")], ["then"], "misspelt_then", {}),
    ("dmg_than_T", [P_("T", "c"), P_("T")], ["and_then"], "misspelt_then", {}),
    ("dmg_after_that", [P_("E", "c"), P_("TR")], ["after_that"], "misspelt_after_that", {}),
    ("dmg_next", [P_("E", "c"), P_("E"), P_("M")], ["next", "then"], "misspelt_next", {"style": "first"}),
    ("dmg_split_then", [P_("E", "c"), P_("M"), P_("E")], ["then", "then"], "split_word", {}),
    ("dmg_doubled_then", [P_("E", "c"), P_("R")], ["then"], "doubled_joiner", {}),
    ("dmg_missing_comma", [P_("E", "c"), P_("M"), P_("E")], ["then", "after_that"], "missing_comma", {}),
    ("dmg_missing_comma_trail", [P_("E", "c"), P_("M", trail="afterwards")], ["trail"], "missing_comma", {}),
    ("dmg_title_typo", [P_("E", "c"), P_("T")], ["then"], "title_typo", {}),
    ("dmg_title_typo3", [P_("T", "c"), P_("T"), P_("E")], ["and_then", "followed"], "title_typo", {}),
]
DAMAGE_PAIRS = 13
SWEEP_ROWS = 20


def _damage_families():
    return [(name, "damage", parts, joiners, dict(opts, damage=dmg, rows=DAMAGE_PAIRS))
            for name, parts, joiners, dmg, opts in DAMAGE_FAMILIES]


def _typo(word: str, rng) -> str:
    """One light typo in a word of five or more letters: a dropped interior
    letter or two adjacent letters swapped."""
    i = rng.randrange(1, len(word) - 2)
    if rng.random() < 0.5:
        return word[:i] + word[i + 1:]
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def damage(segs, dtype, rng):
    """Apply one damage operation to a rendered row's segments. Returns the new
    segments, or None when the row has nothing this operation can damage."""
    segs = list(segs)
    subs = {
        "misspelt_followed": (r"\bfollowed by\b", ["folowed by", "followd by", "fallowed by"]),
        "misspelt_afterwards": (r"\bafterwards\b", ["afterwords", "after wards"]),
        "misspelt_then": (r"\bthen\b", ["than"]),
        "misspelt_after_that": (r"\bafter that\b", ["after tht", "after dat"]),
        "misspelt_next": (r"\bnext\b", ["nxt"]),
        "split_word": (r"\bthen\b", ["the n"]),
        "doubled_joiner": (r"\bthen\b", ["then then"]),
    }
    joins = [i for i, (t, role, _k) in enumerate(segs) if role == "join"]
    if dtype in subs:
        pat, repl = subs[dtype]
        hits = [i for i in joins if re.search(pat, segs[i][0], re.I)]
        if not hits:
            return None
        i = rng.choice(hits)
        t, role, k = segs[i]
        segs[i] = (re.sub(pat, rng.choice(repl), t, count=1, flags=re.I), role, k)
        return segs
    if dtype == "missing_comma":
        hits = [i for i in joins if re.search(r"[,.;]", segs[i][0])]
        if not hits:
            return None
        for i in hits:
            t, role, k = segs[i]
            segs[i] = (re.sub(r"[,.;]", "", t).lower(), role, k)
        return segs
    if dtype == "title_typo":
        hits = [i for i, (t, role, _k) in enumerate(segs)
                if role == "title" and re.search(r"[a-z]{5,}", t)
                and not _MEAL_RE.search(t)]
        if not hits:
            return None
        i = rng.choice(hits)
        t, role, k = segs[i]
        words = [w for w in re.findall(r"[a-z]{5,}", t)]
        w = rng.choice(words)
        segs[i] = (t.replace(w, _typo(w, rng), 1), role, k)
        return segs
    raise ValueError(dtype)


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------


def _stable(*parts: str) -> int:
    return int(hashlib.sha256(":".join(parts).encode()).hexdigest()[:16], 16)


def _fill(rng, pools, template: str) -> str:
    return template.replace("{n}", rng.choice(pools["names"]))


def _title(rng, pools, part, opts, meal_slot=None) -> str:
    c = part["c"]
    if c == "E":
        t = rng.choice(pools["E"])
        style = opts.get("title", "bare")
        if style == "book" and not t.startswith(("a ", "the ", "gym", "davening")):
            t = rng.choice(["book ", "schedule "]) + t
        return t
    if c == "M":
        return _fill(rng, pools, rng.choice(pools[meal_slot or "M_midday"]))
    if c in ("P", "Pn"):
        return _fill(rng, pools, rng.choice(pools[c]))
    if c == "R":
        return rng.choice(pools["R"])
    if c == "T":
        return rng.choice(pools["T"])
    if c == "TR":
        return "remind me to " + rng.choice(pools["T"])
    raise ValueError(c)


def _meal_slot(minutes: "int | None", rng) -> str:
    if minutes is None:
        return rng.choice(["M_morning", "M_midday", "M_evening"])
    if minutes < 11 * 60:
        return "M_morning"
    if minutes < 16 * 60:
        return "M_midday"
    return "M_evening"


def _clean(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+([,.;])", r"\1", t)


def render(segs) -> str:
    return _clean("".join(t for t, _, _ in segs))


def build_family_row(fam, pools, rng):
    """One row of a structural family, or None when the draw breaks a guard
    (a clock earlier than the item it follows, a chain past midnight, an
    anchor name that is not unique). Rejection keeps the draw honest instead of
    bending the gold to fit it."""
    name, bucket, parts, joiners, opts = fam
    n = len(parts)
    ambiguous = bool(opts.get("ambiguous"))
    lead_day = rng.choice(list(DAYS)) if opts.get("lead_day") else None

    # --- 1. clocks, ranges, durations, days: drawn in increasing order --------
    spec = []
    floor = 7 * 60
    for k, p in enumerate(parts):
        s = dict(p)
        if p["clock"] == "c":
            opts_c = [(w, v) for w, v in CLOCKS.items() if floor <= v <= 20 * 60]
            if not opts_c:
                return None
            s["clock_words"], s["start"] = rng.choice(opts_c)
            floor = s["start"] + 60
        elif p["clock"] == "late":
            s["clock_words"], s["start"] = rng.choice([("at 11pm", 1380), ("at 11:30pm", 1410)])
        elif p["clock"] == "r":
            opts_r = [(w, v) for w, v in RANGES.items() if v[0] >= floor]
            if not opts_r:
                return None
            s["clock_words"], (s["start"], s["end"]) = rng.choice(opts_r)
            floor = s["end"]
        elif p["clock"] == "enum":
            w1, w2, a, b = rng.choice(ENUMS)
            s["clock_words"], s["enum2"], s["start"], s["start2"] = w1, w2, a, b
            floor = b + 60
        if p["dur"]:
            s["dur_words"], s["dur_min"] = rng.choice(list(DURATIONS.items()))
        if p["day"] == "own":
            before = [x["day_iso"] for x in spec if x.get("day_iso")]
            before.append(DAYS[lead_day] if lead_day else TODAY)
            later = list(DAYS) if k == 0 else [d for d in DAYS if DAYS[d] > max(before)]
            if not later:
                return None
            s["day_words"] = rng.choice(later)
            s["day_iso"] = DAYS[s["day_words"]]
        spec.append(s)

    # an enumeration is ONE part and TWO items
    items = []
    for k, s in enumerate(spec):
        items.append({"part": k, "second": False})
        if s.get("clock") == "enum":
            items.append({"part": k, "second": True})

    # --- 2. resolve, item by item ------------------------------------------------
    res, part_item = [], {}
    for idx, it in enumerate(items):
        s = spec[it["part"]]
        if not it["second"]:
            part_item[it["part"]] = idx
        jkey = None
        if it["second"]:
            rel_kind, to, jkey = "same_span", idx - 1, "enum"
        elif idx == 0:
            rel_kind, to = None, None
        else:
            jkey = joiners[it["part"] - 1]
            rel_kind, to = J[jkey][1], idx - 1
            if s.get("anchor") is not None:
                rel_kind, to, jkey = "sequence", part_item[s["anchor"]], "right_after_named"
            if s.get("trail"):
                rel_kind, jkey = "sequence", "trail_" + s["trail"].replace(" ", "_")
        c = s["c"]
        has_clock = s.get("clock") is not None
        own_day = s.get("day_iso")
        # Q51: a sequence part with no CLOCK of its own is chained — unless it
        # names a DIFFERENT DAY ("…, then on friday lunch"): a part on another
        # day does not follow the one before it in time, so it starts fresh
        # (a meal's hour, else 09:00) and the parts after it chain from there.
        new_day = bool(own_day) and to is not None and own_day != res[to]["date"]
        chained = rel_kind == "sequence" and not has_clock and not new_day
        if chained and res[to]["kind"] != "event":
            if not ambiguous:
                return None                      # nothing timed to chain from
            chained = False
        # the DATE
        if own_day:
            date = own_day
        elif rel_kind in ("sequence", "same_span") and to is not None:
            date = res[to]["date"]
        elif lead_day:
            date = DAYS[lead_day]
        else:
            date = TODAY
        # the KIND
        is_todo = c in ("T", "TR")
        if is_todo and chained:
            kind, linked = "event", True         # Q51.3
        elif is_todo and not has_clock:
            kind, linked = "task", False
        elif c == "R":
            # an event (Q50). Its companion to-do is Q50's, filed by the
            # executor, not this stage's chain: None = not scored here
            kind, linked = "event", None
        else:
            kind, linked = "event", False        # a clock (Q25), a person (Q47), an event
        # the TIMES
        start = end = None
        if kind == "event":
            dur = s.get("dur_min") or DEFAULT_LEN
            if it["second"]:
                start, end = s["start2"], s["start2"] + DEFAULT_LEN
            elif has_clock:
                start = s["start"]
                end = s.get("end") or start + dur
            elif chained:
                start = res[to]["end_abs"] + GAP
                end = start + dur
            else:
                # the usual way: a meal's own hour, else 09:00 — the meal word
                # is drawn NOW, because the hour depends on it
                if c == "M":
                    s["title"] = _title(rng, pools, s, opts,
                                        rng.choice(["M_morning", "M_midday", "M_evening"]))
                start = (meal_hour(s["title"]) if c == "M" else None) or 540
                end = start + dur
            if start >= 24 * 60:                 # the chain crossed midnight
                if not opts.get("rollover"):
                    return None
                start, end, date = start - 24 * 60, end - 24 * 60, add_days(date, 1)
            if end >= 24 * 60 and not opts.get("rollover"):
                return None
        res.append({"relation_kind": rel_kind, "to": to, "chained": chained, "joiner": jkey,
                    "kind": kind, "linked": linked, "date": date,
                    "start": start, "end": end,
                    "end_abs": end})
    # guards: a stated clock in a sequence starts no earlier than the item it
    # follows ENDS; any later clock starts no earlier than the one before it
    for r, it in zip(res, items):
        to = r["to"]
        if to is None or r["kind"] != "event" or res[to]["kind"] != "event":
            continue
        if r["date"] != res[to]["date"] or r["relation_kind"] == "same_span":
            continue
        s = spec[it["part"]]
        if s.get("clock") and r["relation_kind"] == "sequence" and r["start"] < res[to]["end"]:
            return None
        if r["start"] < res[to]["start"]:
            return None

    # --- 3. titles, now the hours are known (a meal is named for its hour) -------
    for idx, it in enumerate(items):
        s = spec[it["part"]]
        if it["second"] or "title" in s:
            continue
        if s["c"] == "N":
            s["title"], s["short"] = rng.choice(pools["N"])
        else:
            slot = _meal_slot(res[idx]["start"], rng) if s["c"] == "M" else None
            s["title"] = _title(rng, pools, s, opts, slot)
    for k, s in enumerate(spec):
        if s.get("anchor") is None:
            continue
        head = spec[s["anchor"]]["short"].split()[-1]
        others = [x["title"] for j, x in enumerate(spec) if j != s["anchor"]]
        if any(re.search(rf"\b{re.escape(head)}\b", t) for t in others):
            return None                          # "right after the gym" must name ONE thing
    titles = [s["title"] for s in spec]
    if len(set(titles)) != len(titles):
        return None

    # --- 4. render: segments carry their role, so the gold is read off them ------
    style = opts.get("style")
    segs = []                                     # (text, role, part)
    if lead_day:
        segs.append((lead_day, "time", -1))
        segs.append((" " if opts["lead_day"] == "nocomma" else ", ", "join", -1))
    opener = {"filler": FILLER_OPENERS, "hedge": HEDGES, "polite": POLITE,
              "first": ["first "]}.get(style)
    if opener:
        segs.append((rng.choice(opener), "act", 0))
    joiner_words = []
    for k, s in enumerate(spec):
        if k > 0:
            jw = rng.choice(J[joiners[k - 1]][0])
            joiner_words.append(jw.strip())
            segs.append((jw, "join", k))
        dw = s.get("day_words")
        if dw and s["daypos"] == "pre":
            segs.append((dw + " ", "time", k))
        segs.append((s["title"], "title", k))
        if dw and s["daypos"] == "mid":
            segs.append((" " + dw, "time", k))
        if s.get("dur") == "pre":
            segs.append((" " + s["dur_words"], "act", k))
        if s.get("clock_words"):
            segs.append((" " + s["clock_words"], "time", k))
            if s.get("enum2"):
                segs.append((" and " + s["enum2"], "time", k))
        if s.get("dur") == "post":
            segs.append((" " + s["dur_words"], "act", k))
        if dw and s["daypos"] == "post":
            segs.append((" " + dw, "time", k))
        if s.get("anchor") is not None:
            segs.append((" right after " + spec[s["anchor"]]["short"], "act", k))
        if s.get("trail"):
            segs.append((" " + s["trail"], "join", k))
    lead_words = None
    if opts.get("lead_tail"):
        tail = rng.choice(LEADS)
        m = re.search(r"(\d+ minutes before|an hour before)$", tail)
        lead_words = m.group(1)
        segs.append(((" " if not tail.startswith(",") else "") + tail[:m.start()], "act", n - 1))
        segs.append((lead_words, "time", n - 1))
    if style == "caps":
        segs.append((".", "join", n - 1))
        # sentence case: the first letter, and the first letter after ". "
        out, up = [], True
        for txt, role, k in segs:
            if up and re.search(r"[a-z]", txt):
                i = re.search(r"[a-z]", txt).start()
                txt = txt[:i] + txt[i].upper() + txt[i + 1:]
                up = False
            if re.search(r"\.\s*$", txt):
                up = True
            out.append((txt, role, k))
        segs = out

    text = render(segs)

    # --- 5. gold -------------------------------------------------------------------
    seq_gold, chain_gold = [], []
    for idx, it in enumerate(items):
        k, s, r = it["part"], spec[it["part"]], res[idx]
        action = _clean("".join(t for t, role, pk in segs if role in ("act", "title") and pk == k))
        day = s.get("day_words") or lead_day or "today"
        clock = None
        if s.get("clock_words"):
            clock = s["clock_words"] if not it["second"] else "at " + s["enum2"]
        words = [day] + ([clock] if clock else []) + \
                ([lead_words] if lead_words and k == n - 1 else [])
        tag = "task" if s["c"] in ("T", "TR") and not s.get("clock") else "event"
        rel = None if r["relation_kind"] is None else \
            {"to_index": r["to"], "kind": r["relation_kind"], "joiner": r["joiner"]}
        seq_gold.append({"action": action, "time": " ".join(words), "tag": tag, "relation": rel})
        role = ("head" if idx == 0 else "same_span" if r["relation_kind"] == "same_span"
                else "chained" if r["chained"] else "clocked" if s.get("clock")
                else "task" if r["kind"] == "task" else "untimed")
        chain_gold.append({
            "action": action, "kind": r["kind"], "date": r["date"],
            "start_time": hhmm(r["start"]) if r["start"] is not None else None,
            "end_time": hhmm(r["end"]) if r["end"] is not None else None,
            "linked_todo": r["linked"], "chained": r["chained"], "role": role})

    skeleton = "|".join(
        [f"lead:{opts.get('lead_day') or ''}", f"style:{style or ''}", f"tail:{bool(lead_words)}"]
        + [f"{s['c']}/{s.get('clock') or ''}/{s.get('dur') or ''}/"
           f"{(s['daypos'] if s.get('day') else '')}/{'' if s.get('anchor') is None else s['anchor']}/"
           f"{s.get('trail') or ''}" for s in spec]
        + [f"j:{w.lower()}" for w in joiner_words])
    return text, seq_gold, chain_gold, skeleton, segs


# ---------------------------------------------------------------------------
# Decoys and the ambiguous programme shape — one-item rows
# ---------------------------------------------------------------------------

def build_decoy_row(kind, pools, rng):
    """(text, action, time, tag, kind, date, start) for ONE item. Every decoy
    carries a sequence-looking word that is NOT a seam."""
    name = rng.choice(pools["names"])
    ev = rng.choice([e for e in pools["E"] if not e.startswith(("a ", "the "))])
    task = rng.choice(pools["T"])
    cw, cm = rng.choice([(w, v) for w, v in CLOCKS.items() if 9 * 60 <= v <= 18 * 60])
    dw = rng.choice(["on friday", "tomorrow", "on monday", "on the 16th"])
    if kind == "well_see":
        return (f"meet {name} {cw} and then we'll see", f"meet {name} and then we'll see",
                f"today {cw}", "event", "event", TODAY, cm)
    if kind == "remind_then":
        return (f"remind me to {task} then", f"remind me to {task} then",
                "today", "task", "task", TODAY, None)
    if kind == "until_then":
        return (f"put {ev} {cw}, I'm tied up until then", f"put {ev}, I'm tied up until then",
                f"today {cw}", "event", "event", TODAY, cm)
    if kind == "back_then":
        return (f"coffee with {name} {cw} like back then", f"coffee with {name} like back then",
                f"today {cw}", "event", "event", TODAY, cm)
    if kind == "if_then":
        return (f"book {ev} {dw} {cw} if {name} is free then",
                f"book {ev} if {name} is free then", f"{dw} {cw}", "event", "event", DAYS[dw], cm)
    if kind == "next_adj":
        return (f"schedule the next {ev} {cw}", f"schedule the next {ev}",
                f"today {cw}", "event", "event", TODAY, cm)
    if kind == "after_that_meeting":
        return (f"remind me to {task} after that meeting", f"remind me to {task} after that meeting",
                "today", "task", "task", TODAY, None)
    if kind == "by_then":
        bw = rng.choice(["by friday", "by monday", "by tomorrow"])
        iso = {"by friday": "2026-09-11", "by monday": "2026-09-14", "by tomorrow": "2026-09-10"}[bw]
        return (f"{task} {bw}, it has to be done by then", f"{task}, it has to be done by then",
                bw, "task", "task", iso, None)
    if kind == "before_then":
        return (f"book {ev} {dw} {cw}, I can't make it before then",
                f"book {ev}, I can't make it before then", f"{dw} {cw}", "event", "event", DAYS[dw], cm)
    if kind == "followed_title":
        # "followed by" inside ONE title, with no second thing to do
        prog = rng.choice(["a slideshow followed by drinks", "the ceremony followed by the reception",
                           "the lecture followed by a Q&A", "the talk followed by questions"])
        return (f"book {prog} {dw} {cw}", f"book {prog}", f"{dw} {cw}", "event", "event", DAYS[dw], cm)
    raise ValueError(kind)


# ---------------------------------------------------------------------------
# Split + build
# ---------------------------------------------------------------------------

def stratified_split(families) -> dict:
    """Family -> train|test. A family that declares `force_split` is assigned
    directly (the joiner sweep); every other family is split 80/20 within its
    bucket over a stable hash — a bucket of two or more always has a family on
    each side, a singleton stays in train."""
    split = {f[0]: f[4]["force_split"] for f in families if f[4].get("force_split")}
    by = defaultdict(list)
    for fam in families:
        if not fam[4].get("force_split"):
            by[fam[1]].append(fam[0])
    for bucket, names in by.items():
        order = sorted(names, key=lambda f: _stable(SEED, "split", bucket, f))
        n = len(order)
        test_n = 0 if n == 1 else min(n - 1, max(1, round(TEST_FRAC * n)))
        for f in order[:test_n]:
            split[f] = "test"
        for f in order[test_n:]:
            split[f] = "train"
    return split


def all_families():
    return FAMILIES + _sweep_families() + _damage_families()


def build():
    fillers = json.loads(FILLERS.read_text())
    pools = _pools(fillers)
    families = all_families()
    names = [f[0] for f in families]
    assert len(names) == len(set(names)), "duplicate family name"
    split_of = stratified_split(families)
    seq_rows, chain_rows = [], []
    seen = set()

    def emit(rid, name, bucket, text, skeleton, seq_gold, chain_gold, opts, extra):
        common = {"id": rid, "family": name, "bucket": bucket, "split": split_of[name],
                  "text": text, "skeleton": skeleton,
                  "decoy": bool(opts.get("decoy")),
                  "ambiguous": bool(opts.get("ambiguous")),
                  "rollover": bool(opts.get("rollover")),
                  "damage": None, "twin": None,
                  "joiners": sorted({(g["relation"] or {}).get("joiner") for g in seq_gold} - {None})}
        common.update(extra)
        seq_rows.append(dict(common, gold=seq_gold))
        chain_rows.append(dict(common, anchor=ANCHOR, gold=chain_gold))

    for fam in families:
        name, bucket, parts, joiners, opts = fam
        rng = random.Random(_stable(SEED, "rows", name))
        want = opts.get("rows") or (DECOY_ROWS if opts.get("decoy") else ROWS_PER_FAMILY)
        if opts.get("ambiguous") or opts.get("rollover"):
            want = 12
        got, tries = 0, 0
        while got < want and tries < want * 400:
            tries += 1
            if opts.get("decoy") or opts.get("ambiguous") == "programme":
                kind = opts.get("decoy") or "followed_title"
                text, action, time, tag, dkind, date, start = build_decoy_row(kind, pools, rng)
                seq_gold = [{"action": action, "time": time, "tag": tag, "relation": None}]
                chain_gold = [{"action": action, "kind": dkind, "date": date,
                               "start_time": hhmm(start) if start is not None else None,
                               "end_time": hhmm(start + DEFAULT_LEN) if start is not None else None,
                               "linked_todo": False, "chained": False,
                               "role": "decoy" if opts.get("decoy") else "head"}]
                skeleton, segs = f"decoy:{kind}", None
            else:
                out = build_family_row(fam, pools, rng)
                if out is None:
                    continue
                text, seq_gold, chain_gold, skeleton, segs = out
            dmg = opts.get("damage")
            dtext = None
            if dmg:
                dsegs = damage(segs, dmg, rng)
                if dsegs is None:
                    continue
                dtext = render(dsegs)
                if dtext.lower() == text.lower() or dtext.lower() in seen:
                    continue
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            rid = f"seq_{name}_{got}"
            if dmg:
                seen.add(dtext.lower())
                emit(rid, name, bucket, text, skeleton, seq_gold, chain_gold, opts,
                     {"twin": rid + "_dmg"})
                emit(rid + "_dmg", name, bucket, dtext, skeleton + f"|dmg:{dmg}",
                     json.loads(json.dumps(seq_gold)), json.loads(json.dumps(chain_gold)),
                     opts, {"damage": dmg, "twin": rid})
            else:
                emit(rid, name, bucket, text, skeleton, seq_gold, chain_gold, opts, {})
            got += 1
        if got < want:
            raise ValueError(f"{name}: only {got}/{want} rows after {tries} draws")
    # the split is asserted, not assumed
    fam_split = defaultdict(set)
    for r in seq_rows:
        fam_split[r["family"]].add(r["split"])
    both = [f for f, sp in fam_split.items() if len(sp) > 1]
    assert not both, f"families on both sides: {both}"
    return seq_rows, chain_rows


def _dump(rows) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)


def summary(rows) -> str:
    out = []
    for sp in ("train", "test"):
        rs = [r for r in rows if r["split"] == sp]
        fams = {r["family"] for r in rs}
        sk = {r["skeleton"] for r in rs}
        out.append(f"{sp:5s}: {len(rs):5d} rows · {len(fams):3d} families · {len(sk):4d} distinct skeletons"
                   f" · decoy {sum(r['decoy'] for r in rs)} · ambiguous {sum(r['ambiguous'] for r in rs)}")
    items = [g for r in rows for g in r["gold"]]
    kinds = Counter((g["relation"] or {}).get("kind") for g in items)
    out.append(f"all  : {len(rows)} rows · {len(items)} items · "
               f"{len({r['skeleton'] for r in rows})} distinct skeletons · relation kinds {dict(kinds)}")
    out.append("parts per row: " + str(dict(sorted(Counter(len(r['gold']) for r in rows).items()))))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="rebuild and compare, write nothing")
    a = ap.parse_args()
    seq_rows, chain_rows = build()
    s, c = _dump(seq_rows), _dump(chain_rows)
    if a.check:
        same = OUT_SEQ.exists() and OUT_SEQ.read_text() == s and \
            OUT_CHAIN.exists() and OUT_CHAIN.read_text() == c
        print("up to date" if same else "STALE — regenerate")
        return 0 if same else 1
    OUT_CHAIN.parent.mkdir(parents=True, exist_ok=True)
    OUT_SEQ.write_text(s)
    OUT_CHAIN.write_text(c)
    print(summary(seq_rows))
    print(f"wrote {OUT_SEQ.relative_to(REPO)}\nwrote {OUT_CHAIN.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
