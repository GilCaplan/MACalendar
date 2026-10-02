"""SIZE TIERS of the sequence/chain dataset (Gil, 2026-10-01: "a lot of the
datasets seem really small, they should be at least 40k with enough variation
in the data … you can have different level of the same dataset as well").

    python -m assistant.engine.segmentation.datasets.sequence.generate --tier 10k
    python -m assistant.engine.segmentation.datasets.sequence.generate --tier 40k

    tier   rows       where
    base   3,580      sequence/sequence.jsonl + chain/chain.jsonl (committed)
    10k    >= 10,000  sequence/tiers/sequence_10k.jsonl + chain/tiers/chain_10k.jsonl
    40k    >= 40,000  sequence/tiers/sequence_40k.jsonl + chain/tiers/chain_40k.jsonl

The tier files are gitignored and rebuilt deterministically on demand (the
boards do it for you when a tier file is missing).

SUPERSETS, BY CONSTRUCTION. Every tier file starts with the base rows,
byte-identical and in order; then the tier families' rows. All tier families
are drawn ONCE at the cap (`CAP` groups each), deduplicated against the base
texts and each other in one fixed order; a tier then takes the FIRST `q` groups
of every family, with `q` the smallest that reaches the tier's size. So the
10k tier is the 40k tier's per-family prefix — every family, fewer rows each —
and never a different draw.

WHAT IS NEW — real variation, not copies of the base families:

* STRUCTURAL families (`N_STRUCT`), each a distinct skeleton never used by a
  base family (checked by signature): 2 to 5 parts drawn from the part classes
  (event, meal, person encounter, role call, to-do, "remind me to"), clocks on
  any subset of parts, ranges, stated durations before or after the clock, a
  leading day (with/without comma), a day inside the first part, a new day
  partway through, trailing "afterwards / after that / afterward", lead-time
  tails, the six styles (plain, filler, hedge, polite, sentence case,
  "first …"), and joiners from every bank — base and new — mixed in one command.
  A shape that the gold rules cannot honour (a part chained to an untimed to-do,
  "followed by <verb>", "and after <noun>") is refused before it is drawn.
* NEW JOINER BANKS: following that · thereafter · once finished · once I'm done ·
  after I'm done · when done · then after that · directly after that ·
  immediately after that · then lastly · and then right after that ·
  following which (sequence); ". Also," / ". And" (sentence); as well as ·
  ", and also" (list). Each new joiner has a forced-TRAIN sweep family, so the
  test half never holds a joiner train has never seen.
* NEW CLOSED TABLES (tier rows only): 36 more spoken clocks ("at quarter past
  nine", "at 17:30", "at four thirty"), 10 ranges, 7 durations, 13 day phrases
  (avoiding Rosh Hashana, Yom Kippur, Sukkot and Fridays), 5 lead-time tails,
  5 enumerations, new openers.
* NEW SUBJECT BANKS, hand-written and generic (no personal vocabulary is read):
  48 event titles, 40 to-dos, 25 first names, 8 role calls, more encounter and
  meal shapes, 8 more named events for "right after <named>".
* NEW DAMAGE operations (12) on tier families — "an then", "thats", "finaly",
  "folowing", "ones that's done", "then um", "after after that" … — each a
  clean/damaged PAIR with identical gold, exactly as the base damage families.
* NEW DECOYS (13 kinds) — sequence- or list-looking words that are not seams:
  "the first aid course", "a follow up with", "followed up on", "the after
  party", "next door", "next week's", a book title with "and then", "before and
  after photos", "the first draft", "the next steps", "after school club",
  "plus one", "salt and pepper".
* "RIGHT AFTER <named>" families in new shapes.

THE SPLIT follows the base rule, applied to the tier families on their own
(`generate.stratified_split`, 80/20 within each bucket over a stable hash), so
no base family's side can move. Tier buckets are named `t…` and never share a
name with a base bucket.

THE GOLD is computed by the same code as the base rows (`generate.draw_family`
→ `build_family_row` / the decoy builder), from the same rules.
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from assistant.engine.segmentation.datasets.sequence import generate as G

TIERS = {"base": 0, "10k": 10_000, "40k": 40_000}
TIER_SEED = "sequence-q51-tiers-v1"
#: groups per tier family at most (a damaged family's group is a PAIR)
CAP = 40
N_STRUCT = 1150

SEQ_TIER_DIR = G.HERE / "tiers"
CHAIN_TIER_DIR = G.OUT_CHAIN.parent / "tiers"


def paths(tier: str) -> "tuple[Path, Path]":
    if tier == "base":
        return G.OUT_SEQ, G.OUT_CHAIN
    return SEQ_TIER_DIR / f"sequence_{tier}.jsonl", CHAIN_TIER_DIR / f"chain_{tier}.jsonl"


# ---------------------------------------------------------------------------
# Tables — the base tables plus tier-only additions
# ---------------------------------------------------------------------------

EXTRA_CLOCKS = {
    "at 7:15am": 435, "at 7:45am": 465, "at 8:15am": 495, "at 8:45am": 525,
    "at quarter past nine": 555, "at 9:45": 585, "at 10:15": 615,
    "at quarter to eleven": 645, "at 11:30": 690, "at 11:45am": 705,
    "at 12:15": 735, "at 1:15": 795, "at 1:45pm": 825, "at 2:15": 855,
    "at half past two": 870, "at 2:45": 885, "at 3:15": 915, "at 3:30": 930,
    "at quarter past four": 975, "at 4:45": 1005, "at 5:15": 1035,
    "at 5:45pm": 1065, "at 6:15pm": 1095, "at 7:15pm": 1155, "at 7:45pm": 1185,
    "at 8:15pm": 1215, "at 13:30": 810, "at 15:00": 900, "at 17:30": 1050,
    "at 18:00": 1080, "at 19:30": 1170, "at eleven": 660, "at three": 900,
    "at four thirty": 990, "at five": 1020, "at two thirty": 870,
}
EXTRA_RANGES = {
    "from 7am to 8am": (420, 480), "from 9am to noon": (540, 720),
    "from 10 to 11": (600, 660), "from noon to 1:30": (720, 810),
    "from 2:30 to 4": (870, 960), "from 6pm to 7:30pm": (1080, 1170),
    "between 10 and 11:30": (600, 690), "from 3 till 5": (900, 1020),
    "from 1pm until 2pm": (780, 840), "from 4:30 to 6": (990, 1080),
}
EXTRA_DURATIONS = {
    "for 15 minutes": 15, "for 40 minutes": 40, "for two and a half hours": 150,
    "for 75 minutes": 75, "for 25 minutes": 25, "for 4 hours": 240,
    "for ten minutes": 10,
}
#: from the Wednesday anchor 2026-09-09. No Friday (Shabbat and Erev Rosh
#: Hashana evenings), nothing in 11–13 Sep, 20–21 Sep or from 25 Sep.
EXTRA_DAYS = {
    "on the 14th": "2026-09-14", "on the 22nd": "2026-09-22",
    "on the 23rd": "2026-09-23", "on the 24th": "2026-09-24",
    "on tuesday the 15th": "2026-09-15", "on thursday the 17th": "2026-09-17",
    "a week from today": "2026-09-16", "in five days": "2026-09-14",
    "on september 22nd": "2026-09-22", "this thursday": "2026-09-10",
    "this coming monday": "2026-09-14", "on monday the 14th": "2026-09-14",
    "on the 22nd of september": "2026-09-22",
}
EXTRA_LEADS = ["and remind me 5 minutes before", "and ping me 20 minutes before",
               ", remind me 45 minutes before", "and nudge me an hour before",
               "and give me a heads up 30 minutes before"]
EXTRA_ENUMS = [("at 9:30", "11:30", 570, 690), ("at 10", "3", 600, 900),
               ("at 11", "4", 660, 960), ("at 9", "1", 540, 780),
               ("at 2", "5", 840, 1020)]
EXTRA_J = {
    # sequence
    "following_that": ([", following that, ", ". Following that, "], "sequence"),
    "thereafter": ([", thereafter ", " and thereafter "], "sequence"),
    "once_finished": ([", once finished, ", " and once finished "], "sequence"),
    "once_im_done": ([", once i'm done, ", " and once i'm done "], "sequence"),
    "after_im_done": ([", after i'm done, ", " and after i'm done with that "], "sequence"),
    "when_done": ([", when done, ", " and when done "], "sequence"),
    "then_after_that": ([", then after that ", " then after that, "], "sequence"),
    "directly_after": ([", directly after that ", " and directly after that "], "sequence"),
    "immediately_after": ([", immediately after that ", " and immediately after that "], "sequence"),
    "then_lastly": ([", then lastly ", " and lastly ", ", lastly "], "sequence"),
    "and_then_right_after": ([" and then right after that ", ", then right after that "], "sequence"),
    "following_which": ([", following which ", " following which "], "sequence"),
    # sentence
    "sentence_also": ([". Also, ", ". And "], "sentence"),
    # list
    "as_well_as": ([" as well as "], "list"),
    "and_also_comma": ([", and also "], "list"),
}
NEW_JOINERS = list(EXTRA_J)
TABLES = {
    "clocks": {**G.CLOCKS, **EXTRA_CLOCKS},
    "ranges": {**G.RANGES, **EXTRA_RANGES},
    "durations": {**G.DURATIONS, **EXTRA_DURATIONS},
    "days": {**G.DAYS, **EXTRA_DAYS},
    "leads": G.LEADS + EXTRA_LEADS,
    "enums": G.ENUMS + EXTRA_ENUMS,
    "J": {**G.J, **EXTRA_J},
    "fillers": G.FILLER_OPENERS + ["so um ", "right so ", "ok ", "alright so "],
    "hedges": G.HEDGES + ["i suppose ", "i'd say ", "perhaps "],
    "polite": G.POLITE + ["would you put ", "can you please put ", "please add "],
    "first": ["first ", "first of all ", "first off, "],
}

# ---------------------------------------------------------------------------
# Subject banks — hand-written, generic, tier rows only
# ---------------------------------------------------------------------------

EXTRA_EVENTS = [
    "choir rehearsal", "pottery class", "spin class", "pilates", "a massage",
    "the open day", "a site visit", "the board meeting", "office hours",
    "the lab session", "the seminar", "the recital", "swim practice",
    "football practice", "the car inspection", "a dental cleaning",
    "the physics lecture", "a code review", "the sprint planning",
    "the design review", "a tutoring session", "the book fair", "a photo shoot",
    "the art class", "a driving lesson", "the climbing session",
    "a chess club meeting", "the debate practice", "a guitar lesson",
    "the quarterly review", "a mortgage appointment", "the bank appointment",
    "a skin check", "a hearing test", "the karate class", "the language exchange",
    "a volunteer shift", "the community meeting", "a museum visit",
    "the farmers market", "a bike repair appointment", "the gallery opening",
    "a cooking class", "the study group", "the team offsite",
    "a vaccination appointment", "the school assembly", "a hackathon kickoff",
]
EXTRA_TASKS = [
    "pay the gas bill", "renew the car insurance", "order printer ink",
    "fix the bike tyre", "file the receipts", "clean the fridge",
    "defrost the freezer", "sort the recycling", "iron the shirts",
    "polish the shoes", "hang the curtains", "assemble the bookshelf",
    "descale the kettle", "replace the smoke alarm battery",
    "update the budget spreadsheet", "cancel the gym membership",
    "pay the parking fine", "register for the course", "fill in the tax form",
    "renew the library card", "sharpen the kitchen knives", "clear out the inbox",
    "mow the lawn", "rake the leaves", "wipe down the counters",
    "empty the dishwasher", "change the bed sheets", "top up the travel card",
    "check the tyre pressure", "print the tickets", "label the boxes",
    "sweep the patio", "clean the windows", "reply to the survey",
    "update the phone software", "order a birthday card", "wrap the present",
    "return the parcel", "pick up the prescription", "sort out the paperwork",
]
EXTRA_NAMES = ["Ben", "Chloe", "Daniel", "Emma", "Grace", "Hannah", "Isaac",
               "Jack", "Kate", "Leo", "Mia", "Nathan", "Olivia", "Paul", "Rachel",
               "Sophie", "Tom", "Victor", "Zoe", "Ella", "Max", "Lucy", "Oscar",
               "Ruby", "Henry"]
EXTRA_P = ["a call with {n}", "tennis with {n}", "a run with {n}", "see {n}",
           "visit {n}", "meet up with {n}", "a chat with {n}"]
EXTRA_PN = ["a call with {n}", "tennis with {n}", "a run with {n}", "a chat with {n}",
            "a study session with {n}"]
EXTRA_R = ["call the garage", "phone the school office", "call the council",
           "ring the pharmacy", "call the landlord", "phone the travel agent",
           "call the mechanic", "call the locksmith"]
EXTRA_MEALS = {"M_morning": ["an early breakfast", "breakfast with the team"],
               "M_midday": ["lunch with the team", "a lunch meeting", "a late lunch"],
               "M_evening": ["dinner with friends", "supper with the family", "a dinner party"]}
EXTRA_N = [("the piano lesson", "piano"), ("the budget meeting", "the budget meeting"),
           ("spin class", "spin class"), ("the lecture", "the lecture"),
           ("choir practice", "choir"), ("the swim session", "the swim session"),
           ("the seminar", "the seminar"), ("the recital", "the recital")]

#: words a title must never carry: a seam word would make the gold's cut a
#: lie, a time word would belong in `time`, a meal word triggers Q32's hour.
_FORBIDDEN = re.compile(
    r"\b(?:and|then|next|after|afterwards?|first|followed|following|plus|also|once|when|"
    r"done|finally|lastly|later|before|until|morning|evening|night|tonight|today|"
    r"tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|breakfast|"
    r"brunch|lunch|dinner|supper)\b", re.I)


def _check_banks() -> None:
    for t in EXTRA_EVENTS + EXTRA_TASKS:
        assert not _FORBIDDEN.search(t), f"tier title carries a rule word: {t!r}"
    from assistant.intent.encounter import is_role_call
    for r in EXTRA_R:
        assert is_role_call(r), r


def pools() -> dict:
    """The base pools plus the tier banks (base pools are never mutated)."""
    _check_banks()
    p = G._pools(json.loads(G.FILLERS.read_text()))
    p = {k: list(v) for k, v in p.items()}
    p["E"] += [e for e in EXTRA_EVENTS if e not in p["E"]]
    p["T"] += [t for t in EXTRA_TASKS if t not in p["T"]]
    p["names"] += [n for n in EXTRA_NAMES if n not in p["names"]]
    p["P"] += EXTRA_P
    p["Pn"] += EXTRA_PN
    p["R"] += EXTRA_R
    for k, v in EXTRA_MEALS.items():
        p[k] += v
    p["N"] += EXTRA_N
    return p


# ---------------------------------------------------------------------------
# Decoys new to the tiers — ONE item each; a sequence/list word that is no seam
# ---------------------------------------------------------------------------

TIER_DECOYS = ["first_aid", "follow_up", "followed_up", "after_party", "next_door",
               "next_weeks", "book_title", "before_and_after", "first_draft",
               "next_steps", "after_school", "plus_one", "fixed_pair"]
_BOOKS = ["And Then There Were None", "Then She Was Gone", "After the Fall",
          "Next of Kin", "First and Last", "Before and After", "Ever After",
          "The Day After"]
_DAY_WORDS = ["tomorrow", "on monday", "on the 16th", "on the 14th", "on the 22nd",
              "this thursday", "a week from today", "on tuesday the 15th"]


def decoy_row(kind, pools_, rng, tables=None):
    T = tables or TABLES
    days, clocks = T["days"], T["clocks"]
    name = rng.choice(pools_["names"])
    cw, cm = rng.choice([(w, v) for w, v in clocks.items() if 9 * 60 <= v <= 18 * 60])
    dw = rng.choice(_DAY_WORDS)
    iso = days[dw]
    today = G.TODAY
    if kind == "first_aid":
        return (f"book the first aid course {dw} {cw}", "book the first aid course",
                f"{dw} {cw}", "event", "event", iso, cm)
    if kind == "follow_up":
        return (f"schedule a follow up with {name} {cw}", f"schedule a follow up with {name}",
                f"today {cw}", "event", "event", today, cm)
    if kind == "followed_up":
        thing = rng.choice(["quote", "invoice", "booking", "application", "survey", "refund"])
        return (f"remind me to check that {name} followed up on the {thing} {dw}",
                f"remind me to check that {name} followed up on the {thing}",
                dw, "task", "task", iso, None)
    if kind == "after_party":
        return (f"book the after party {dw} {cw}", "book the after party",
                f"{dw} {cw}", "event", "event", iso, cm)
    if kind == "next_door":
        pet = rng.choice(["cat", "dog", "fish", "rabbit", "plants", "chickens"])
        return (f"feed the {pet} next door {dw}", f"feed the {pet} next door",
                dw, "task", "task", iso, None)
    if kind == "next_weeks":
        ev = rng.choice(["team meeting", "workshop", "staff meeting", "board meeting",
                         "seminar", "study group", "book club"])
        return (f"plan next week's {ev} {cw}", f"plan next week's {ev}",
                f"today {cw}", "event", "event", today, cm)
    if kind == "book_title":
        bt = rng.choice(_BOOKS)
        return (f"remind me to finish reading {bt} {dw}", f"remind me to finish reading {bt}",
                dw, "task", "task", iso, None)
    if kind == "before_and_after":
        room = rng.choice(["kitchen", "bathroom", "garden", "garage", "hallway", "spare room"])
        return (f"take before and after photos of the {room} {dw}",
                f"take before and after photos of the {room}", dw, "task", "task", iso, None)
    if kind == "first_draft":
        doc = rng.choice(["report", "essay", "proposal", "newsletter", "grant application",
                          "cover letter", "speech"])
        return (f"finish the first draft of the {doc} {dw}", f"finish the first draft of the {doc}",
                dw, "task", "task", iso, None)
    if kind == "next_steps":
        ev = rng.choice(["team meeting", "workshop", "client call", "project sync",
                         "retrospective", "design review", "board meeting"])
        return (f"write up the next steps from the {ev} {dw}",
                f"write up the next steps from the {ev}", dw, "task", "task", iso, None)
    if kind == "after_school":
        cw, cm = rng.choice([(w, v) for w, v in clocks.items() if 15 * 60 <= v <= 18 * 60])
        return (f"pick up the kids from the after school club {dw} {cw}",
                "pick up the kids from the after school club", f"{dw} {cw}",
                "event", "event", iso, cm)
    if kind == "plus_one":
        ev = rng.choice(["wedding", "gala", "launch party", "reunion", "fundraiser",
                         "awards night"])
        return (f"rsvp for me plus one to the {ev} {dw}", f"rsvp for me plus one to the {ev}",
                dw, "task", "task", iso, None)
    if kind == "fixed_pair":
        pair = rng.choice(["salt and pepper", "fish and chips", "bread and butter",
                           "shampoo and conditioner", "nuts and bolts", "pen and paper",
                           "milk and cookies", "needle and thread"])
        verb = rng.choice(["buy", "pick up", "order", "get"])
        return (f"{verb} {pair} {dw}", f"{verb} {pair}", dw, "task", "task", iso, None)
    raise ValueError(kind)


# ---------------------------------------------------------------------------
# Tier families
# ---------------------------------------------------------------------------

P_ = G.P_
_VERB_NEXT = {"then_after", "and_after"}
_NOUN_NEXT = {"followed", "as_well_as"}
_LAST_ONLY = {"then_finally", "then_lastly"}
_SEQ = [k for k, (_l, kind) in TABLES["J"].items() if kind == "sequence"
        and k not in ("trail", "anchor", "later", "after_meal")]
_LIST = ["and", "comma", "also", "plus", "as_well_as", "and_also_comma"]
_SENT = ["sentence", "sentence_also"]


def signature(parts, joiners, opts) -> tuple:
    return (tuple((p["c"], p["clock"], p["dur"], p["day"] and p["daypos"], p["anchor"],
                   p["trail"]) for p in parts),
            tuple(joiners), opts.get("style"), opts.get("lead_day"),
            bool(opts.get("lead_tail")), opts.get("title"), opts.get("damage"))


def _valid(parts, joiners, opts) -> bool:
    """Refuse a shape the gold rules cannot honour BEFORE drawing it."""
    J = TABLES["J"]
    kinds = []                       # "event" | "task" per part (no enumerations here)
    for k, p in enumerate(parts):
        clocked = p["clock"] is not None
        rel = None
        if k:
            j = joiners[k - 1]
            rel = "sequence" if p["trail"] or p["anchor"] is not None else J[j][1]
            if j in _VERB_NEXT and p["c"] not in ("T", "TR", "R"):
                return False
            if j in _NOUN_NEXT and (p["c"] not in ("E", "M", "Pn") or opts.get("title") == "book"):
                return False
            if j in _LAST_ONLY and k != len(parts) - 1:
                return False
            if p["trail"] and j != "trail":
                return False
            if j == "trail" and not p["trail"]:
                return False
        new_day = bool(p["day"]) and k > 0
        chained = rel == "sequence" and not clocked and not new_day
        if chained:
            to = p["anchor"] if p["anchor"] is not None else k - 1
            if kinds[to] != "event":
                return False
        kinds.append("task" if p["c"] in ("T", "TR") and not clocked and not chained else "event")
    if opts.get("style") == "first" and J[joiners[0]][1] != "sequence":
        return False
    if opts.get("style") == "polite" and parts[0]["c"] not in ("E", "M", "Pn"):
        return False
    return True


def _random_family(rng):
    n = rng.choices([2, 3, 4, 5], weights=[30, 35, 22, 13])[0]
    classes = rng.choices(["E", "M", "P", "Pn", "R", "T", "TR"],
                          weights=[30, 15, 10, 6, 7, 18, 8], k=n)
    parts = []
    for k, c in enumerate(classes):
        clock = None
        if rng.random() < (0.75 if k == 0 else 0.25):
            clock = "r" if c == "E" and rng.random() < 0.15 else "c"
        if k == 0 and c == "E" and n <= 3 and rng.random() < 0.05:
            clock = "enum"
        dur = rng.choice(["pre", "post"]) if c in ("E", "P") and clock != "r" \
            and clock != "enum" and rng.random() < 0.15 else None
        if dur == "pre" and clock is None:
            dur = "post"
        parts.append(P_(c, clock, dur=dur))
    opts = {}
    r = rng.random()
    if r < 0.18:
        opts["lead_day"] = rng.choice([True, True, "nocomma"])
    elif r < 0.30:
        parts[0]["day"], parts[0]["daypos"] = "own", rng.choice(["mid", "post", "pre"])
    elif r < 0.40 and n >= 3:
        k = rng.randrange(1, n)
        parts[k]["day"], parts[k]["daypos"] = "own", "pre"
    joiners = []
    for k in range(1, n):
        x = rng.random()
        if k == n - 1 and n >= 3 and x < 0.12:
            joiners.append(rng.choice(["then_finally", "then_lastly"]))
        elif x < 0.72:
            joiners.append(rng.choice([j for j in _SEQ if j not in _LAST_ONLY]))
        elif x < 0.88:
            joiners.append(rng.choice(_LIST))
        else:
            joiners.append(rng.choice(_SENT))
    last = parts[-1]
    if n >= 2 and last["c"] in ("E", "M") and last["clock"] is None and rng.random() < 0.08:
        last["trail"] = rng.choice(["afterwards", "after that", "afterward"])
        joiners[-1] = "trail"
    s = rng.random()
    opts["style"] = (None if s < 0.55 else "filler" if s < 0.65 else "hedge" if s < 0.73
                     else "polite" if s < 0.81 else "caps" if s < 0.90 else "first")
    if opts["style"] is None:
        del opts["style"]
    if rng.random() < 0.08:
        opts["lead_tail"] = True
    if rng.random() < 0.2:
        opts["title"] = "book"
    return parts, joiners, opts


def _bucket(parts, joiners) -> str:
    kinds = {TABLES["J"][j][1] for j in joiners}
    mix = "seq" if kinds == {"sequence"} else "list" if "sequence" not in kinds else "mixed"
    return f"t{len(parts)}_{mix}"


#: tier damage families: (parts, joiners, operation, opts)
_DAMAGE = [
    ([P_("E", "c"), P_("M"), P_("E")], ["and_then", "then"], "misspelt_and_then", {}),
    ([P_("T", "c"), P_("T")], ["and_then"], "misspelt_and_then", {}),
    ([P_("E", "c"), P_("P")], ["and_then_right_after"], "misspelt_and_then", {}),
    ([P_("E", "c"), P_("M")], ["once_im_done"], "dropped_apostrophe", {}),
    ([P_("T", "c"), P_("E")], ["after_im_done"], "dropped_apostrophe", {}),
    ([P_("E", "c"), P_("T")], ["once_thats_done"], "dropped_apostrophe", {}),
    ([P_("P", "c"), P_("E")], ["when_thats_done"], "dropped_apostrophe", {}),
    ([P_("E", "c"), P_("E"), P_("M")], ["then", "then_finally"], "misspelt_finally", {}),
    ([P_("T", "c"), P_("E"), P_("E"), P_("M")], ["then", "next", "then_finally"], "misspelt_finally", {}),
    ([P_("E", "c"), P_("P"), P_("M")], ["then", "then_lastly"], "misspelt_lastly", {}),
    ([P_("E", "c"), P_("M")], ["following_that"], "misspelt_following", {}),
    ([P_("R", "c"), P_("E")], ["following_which"], "misspelt_following", {}),
    ([P_("E", "c"), P_("T")], ["subsequently"], "misspelt_subsequently", {}),
    ([P_("M", "c"), P_("E")], ["afterward"], "misspelt_afterward", {}),
    ([P_("E", "c"), P_("M")], ["once_done"], "misspelt_once", {}),
    ([P_("E", "c"), P_("T")], ["once_finished"], "misspelt_once", {}),
    ([P_("E", "c"), P_("E")], ["when_finished"], "misspelt_when", {}),
    ([P_("T", "c"), P_("T")], ["when_done"], "misspelt_when", {}),
    ([P_("E", "c"), P_("M"), P_("E")], ["then", "then"], "filler_in_joiner", {}),
    ([P_("P", "c"), P_("R")], ["then"], "filler_in_joiner", {}),
    ([P_("E", "c"), P_("TR")], ["after_that"], "stutter_after_that", {}),
    ([P_("E", "c"), P_("E"), P_("M")], ["then_after_that", "then"], "stutter_after_that", {}),
    ([P_("E", "c"), P_("M")], ["thereafter"], "misspelt_thereafter", {}),
    ([P_("E", "c"), P_("M"), P_("P")], ["followed", "then"], "misspelt_followed", {}),
    ([P_("M", "c"), P_("E"), P_("M")], ["afterwards", "then"], "misspelt_afterwards", {}),
    ([P_("E", "c"), P_("T"), P_("E")], ["directly_after", "then"], "misspelt_then", {}),
    ([P_("E", "c"), P_("M"), P_("E")], ["then", "after_that"], "misspelt_after_that", {"style": "hedge"}),
    ([P_("E", "c"), P_("E"), P_("M"), P_("P")], ["then", "then", "then"], "split_word", {}),
    ([P_("T", "c"), P_("R")], ["then"], "doubled_joiner", {"style": "filler"}),
    ([P_("E", "c"), P_("M"), P_("E")], ["following_that", "then_after_that"], "missing_comma", {}),
    ([P_("E", "c"), P_("P"), P_("M")], ["immediately_after", "once_finished"], "missing_comma", {}),
    ([P_("E", "c"), P_("T")], ["then"], "title_typo", {"lead_day": True}),
    ([P_("T", "c"), P_("E"), P_("M")], ["and_then", "then"], "title_typo", {}),
    ([P_("E", "c"), P_("E")], ["next"], "misspelt_next", {"style": "first"}),
]

#: "right after <named>" in new shapes: (parts, joiners, opts)
_ANCHOR = [
    ([P_("N", "c"), P_("E", "c"), P_("T", anchor=0)], ["also", "anchor"], {}),
    ([P_("N", "c"), P_("M", "c"), P_("R", anchor=0)], ["and", "anchor"], {}),
    ([P_("N", "c"), P_("E", "c"), P_("Pn", anchor=0)], ["sentence", "anchor"], {"style": "caps"}),
    ([P_("E", "c"), P_("N", "c"), P_("TR", anchor=1)], ["and", "anchor"], {}),
    ([P_("N", "c"), P_("E", "c"), P_("M", "c"), P_("P", anchor=0)], ["comma", "and", "anchor"], {}),
    ([P_("N", "c"), P_("E", "c"), P_("E", anchor=0)], ["and", "anchor"], {"lead_day": True}),
    ([P_("N", "c"), P_("P", "c"), P_("T", anchor=0)], ["plus", "anchor"], {"style": "filler"}),
    ([P_("E", "c"), P_("N", "c"), P_("E", anchor=1)], ["as_well_as", "anchor"], {}),
]


def tier_families() -> list:
    """Every tier family, in its fixed draw order."""
    base_sigs = {signature(f[2], f[3], f[4]) for f in G.all_families() if f[2]}
    out, sigs = [], set(base_sigs)

    def add(name, bucket, parts, joiners, opts):
        sig = signature(parts, joiners, opts)
        if sig in sigs:
            return
        sigs.add(sig)
        out.append((name, bucket, parts, joiners, opts))

    # 1. one forced-TRAIN sweep family per NEW joiner (every joiner seen in train)
    for i, j in enumerate(NEW_JOINERS):
        nxt = P_("M") if j in _NOUN_NEXT else P_("T") if j in _VERB_NEXT else P_("E")
        if TABLES["J"][j][1] != "sequence":
            nxt = P_("M", "c")
        add(f"tjw_{j}", "t_sweep", [P_("E", "c"), nxt], [j], {"force_split": "train"})
    # 2. damage pairs
    for i, (parts, joiners, dmg, opts) in enumerate(_DAMAGE):
        add(f"tdmg_{i:02d}_{dmg}", "t_damage", [dict(p) for p in parts], joiners,
            dict(opts, damage=dmg))
    # 3. decoys
    for k in TIER_DECOYS:
        out.append((f"td_{k}", "t_decoy", None, None, {"decoy": k}))
    # 4. anchors
    for i, (parts, joiners, opts) in enumerate(_ANCHOR):
        add(f"tanc_{i:02d}", "t_anchor", [dict(p) for p in parts], joiners, opts)
    # 5. structural families
    rng = random.Random(G._stable(TIER_SEED, "families"))
    made, tries = 0, 0
    while made < N_STRUCT and tries < N_STRUCT * 200:
        tries += 1
        parts, joiners, opts = _random_family(rng)
        if not _valid(parts, joiners, opts):
            continue
        before = len(out)
        add(f"ts_{made:04d}", _bucket(parts, joiners), parts, joiners, opts)
        if len(out) > before:
            made += 1
    return out


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def draw_all(max_families: "int | None" = None):
    """Base rows + every tier family drawn at the cap, in one fixed order.
    Returns (base_seq, base_chain, [(family, groups)]). `max_families` draws
    only the first N tier families (a quick smoke for the tests; the split is
    still computed over all of them, so no family changes side)."""
    base_seq, base_chain = G.build()
    fams = tier_families()
    names = [f[0] for f in fams]
    assert len(names) == len(set(names))
    assert not set(names) & {f[0] for f in G.all_families()}
    split_of = G.stratified_split(fams)
    if max_families:
        fams = fams[:max_families]
    p = pools()
    seen = {r["text"].lower() for r in base_seq}
    drawn = []
    for fam in fams:
        groups, _tries = G.draw_family(fam, p, CAP, seen, split_of[fam[0]], TABLES)
        if groups:
            drawn.append((fam, groups))
    return base_seq, base_chain, drawn


def quota(n_base: int, drawn, target: int) -> int:
    """The smallest per-family group count that brings the tier to `target`."""
    if target <= n_base:
        return 0
    for q in range(1, CAP + 1):
        n = n_base + sum(len(g) for _f, gs in drawn for g in gs[:q])
        if n >= target:
            return q
    raise ValueError(f"the tier families cannot reach {target} rows (cap {CAP})")


def build_tier(tier: str, _cache: dict = {}):
    if tier not in TIERS:
        raise SystemExit(f"unknown tier {tier!r}; choose from {list(TIERS)}")
    if "drawn" not in _cache:
        _cache["drawn"] = draw_all()
    base_seq, base_chain, drawn = _cache["drawn"]
    if tier == "base":
        return base_seq, base_chain
    q = quota(len(base_seq), drawn, TIERS[tier])
    seq, chain = list(base_seq), list(base_chain)
    for _fam, groups in drawn:
        for group in groups[:q]:
            for s, c in group:
                seq.append(s)
                chain.append(c)
    sides = defaultdict(set)
    for r in seq:
        sides[r["family"]].add(r["split"])
    assert not [f for f, s in sides.items() if len(s) > 1], "a family on both sides"
    return seq, chain


def write_tier(tier: str) -> "tuple[Path, Path]":
    seq, chain = build_tier(tier)
    ps, pc = paths(tier)
    ps.parent.mkdir(parents=True, exist_ok=True)
    pc.parent.mkdir(parents=True, exist_ok=True)
    ps.write_text(G._dump(seq))
    pc.write_text(G._dump(chain))
    return ps, pc


def ensure(tier: str, which: str = "seq") -> Path:
    """The tier file a board should read, built on demand when missing."""
    ps, pc = paths(tier)
    want = ps if which == "seq" else pc
    if not want.exists():
        print(f"[tier {tier}] {want.name} missing — building it (deterministic, ~30 s)…",
              flush=True)
        write_tier(tier)
    return want


def stats(rows) -> dict:
    fam_side = {r["family"]: r["split"] for r in rows}
    return {"rows": len(rows), "texts": len({r["text"].lower() for r in rows}),
            "families": len(fam_side), "skeletons": len({r["skeleton"] for r in rows}),
            "train_rows": sum(r["split"] == "train" for r in rows),
            "test_rows": sum(r["split"] == "test" for r in rows),
            "train_families": sum(s == "train" for s in fam_side.values()),
            "test_families": sum(s == "test" for s in fam_side.values()),
            "decoys": sum(r["decoy"] for r in rows),
            "damaged": sum(bool(r["damage"]) for r in rows),
            "ambiguous": sum(r["ambiguous"] for r in rows),
            "parts": dict(sorted(Counter(len(r["gold"]) for r in rows).items()))}
