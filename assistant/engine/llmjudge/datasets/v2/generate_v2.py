"""Build the v2 judge set — commands by grammar, cases by planting.

    python -m assistant.engine.llmjudge.datasets.v2.generate_v2
    python -m assistant.engine.llmjudge.datasets.v2.generate_v2 --commands-only

Writes `commands_v2.jsonl` (~5,000 utterances) and `judge_cases_v2.jsonl`
(~10,000 object-level cases) beside this file. `README.md` is the reference and
`verify_v2.py` is the gate; this docstring is the contract.

## THE GOLD IS BY CONSTRUCTION — never a model's opinion, never hand-written

The generator chooses the ask before it chooses the words. A command is
composed out of one to four ASKS, each of which fixes its own action, kind,
subject, day, clock and cadence; the words are then rendered from that choice.
So the gold is not a judgement about a sentence — it is the recipe the sentence
was built from, exact in the way `dataset/personas/`'s gold is exact ("the
generator chose the filler that became `slots.title`").

Three consequences, each a way this could have gone wrong:

1. **No model is in this pipeline and none may be added.** `PLAN.md` §7.2: a
   model labelling what a model will be judged on is circular, and free-form
   LLM gold is what the dropped real-speech set was.
2. **The gold is voice-independent.** One command is rendered SEVEN times —
   plain plus the six persona habits — and the seven share one gold. Three
   separate random streams are what buy that: `rng_gold` draws the ASK (same
   for all seven), `rng_words` draws the FRAME (per voice), `rng_damage` draws
   the DAMAGE (same for all seven, so an operation that moves the gold moves it
   identically). `tests/unit/test_llmjudge_dataset_v2.py` pins it.
3. **Damage does not move the gold, except where the operation IS a gold
   change** — a recogniser that mangles the subject, a speaker who names only
   the kind, a retraction that cancels an ask. Those are declared in
   `damage.GOLD_CHANGING` and in the operation's own docstring, nowhere else.

## Why this set exists at all

`PLAN.md` §7.1: the stage's 1,800-case set is six synthetic defects over
FastRule's template corpus, a deterministic judge already catches all six at
ceiling, and real speech fails on classes the six do not contain. This set
carries those classes — disfluent and recogniser-damaged wording, a subject the
words held and the reader dropped, merged asks, a wrong kind, a wrong operation
— and says plainly which of them today's taxonomy has NO finding for
(`expect: null` with `defect: true`), because that is the measurement §7 asks
for rather than a number to celebrate.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import os
import pathlib
import random
import sys
import tempfile
import time
from dataclasses import dataclass, field

from assistant.engine.llmjudge.datasets.v2 import banks, damage, voices

#: THE CLOCK the set was generated at, and the one any board MUST replay it
#: at — a property of the DATA, not of a run (`datasets/generate.py` carries
#: the same constant for the same reason). 2026-09-22 is a TUESDAY, which
#: matters: a family naming "on tuesday" resolves to today, and one naming
#: "tomorrow … on tuesday" is exactly the cycle-36 conflict.
CLOCK = _dt.datetime(2026, 9, 22, 10, 0)

SEED = 17

HERE = pathlib.Path(__file__).resolve().parent
COMMANDS = HERE / "commands_v2.jsonl"
CASES = HERE / "judge_cases_v2.jsonl"

# ---------------------------------------------------------------------------
# 1 · THE GRAMMAR OF ASKS
# ---------------------------------------------------------------------------

#: One ask shape. `when` says which temporal fields it carries; `subject` says
#: where its identity comes from — a thing being named (`event`/`task`), a
#: record being pointed at (`target_*`), an anaphor, or nothing (a query).
#:
#: These twenty-one are the brief's four axes crossed: one to four asks,
#: event / to-do / query / update / delete, a clock in every spoken form, a
#: cadence from each of the four, and the anaphoric edit. Nothing here is a
#: phrasing — a phrasing is a VOICE.
SHAPES = {
    "ce_dt":      dict(action="create_event", kind="event", subject="event",
                       date=True, clock=True),
    "ce_d":       dict(action="create_event", kind="event", subject="event",
                       date=True),
    "ce_t":       dict(action="create_event", kind="event", subject="event",
                       clock=True),
    "ce_bare":    dict(action="create_event", kind="event", subject="event"),
    "ce_range":   dict(action="create_event", kind="event", subject="event",
                       date=True, clock=True, end=True),
    "ce_recur":   dict(action="create_event", kind="event", subject="event",
                       recur="plain", clock=True),
    "ce_recur_d": dict(action="create_event", kind="event", subject="event",
                       recur="weekdays", clock=True),
    "ce_recur_y": dict(action="create_event", kind="event", subject="event",
                       recur="yearly"),
    "ct":         dict(action="create_todo", kind="task", subject="task"),
    "ct_d":       dict(action="create_todo", kind="task", subject="task",
                       date=True),
    "ct_dt":      dict(action="create_todo", kind="task", subject="task",
                       date=True, clock=True),
    "q_day":      dict(action="query_schedule", kind="event", subject=None,
                       date=True),
    "q_todo":     dict(action="query_todos", kind="task", subject=None),
    "ue_clock":   dict(action="update_event", kind="event",
                       subject="target_event", clock=True),
    "ue_day":     dict(action="update_event", kind="event",
                       subject="target_event", date=True),
    "de":         dict(action="delete_event", kind="event",
                       subject="target_event"),
    "de_day":     dict(action="delete_event", kind="event",
                       subject="target_event", date=True),
    "dt":         dict(action="delete_todo", kind="task", subject="target_task"),
    "comp":       dict(action="complete_todo", kind="task",
                       subject="target_task"),
    "anaph_u":    dict(action="update_event", kind="event", subject="anaphor",
                       clock=True),
    "anaph_d":    dict(action="delete_event", kind="event", subject="anaphor"),
}

_FRAME_KEY = {"create_event": "create_event", "create_todo": "create_todo",
              "query_schedule": "query_schedule", "query_todos": "query_todos",
              "update_event": "update_event", "delete_event": "delete_event",
              "delete_todo": "delete_todo", "complete_todo": "complete_todo"}

#: THE JOINERS. The first four are clause-level: two asks, two clauses, the
#: seam the speaker put between them. The last two are SUBJECT-level, and that
#: is not an inconsistency — it is where DEVQA Q43 was ruled:
#:
#:   comma_list_and   "an event for dentist, haircut and gym"   -> N asks
#:                    (Gil, 2026-09-20: a calendar create over a list of things
#:                    is several events; `findings.COORDINATED_SUBJECT`)
#:   comma_run_plain  "TA, office hour, meeting"                -> ONE ask
#:                    (DEVQA Q43, 2026-09-22: a comma run with no conjunction
#:                    is NOT a list; it is dictation, and it stays one event)
JOINERS = {
    "and": " and ",
    "also": ". Also, ",
    "comma_then": ", then ",
    "and_then": " and then ",
    "comma_list_and": None,
    "comma_run_plain": None,
}

#: The seams `findings.UNSPLIT_SUBJECT` is DEFINED by — "and then", ". Also,",
#: "; then". A merge that uses one of these is a defect today's taxonomy has a
#: name for; a merge on a plain "and" is one it does not.
SEAM_JOINERS = ("also", "and_then", "comma_then")


@dataclass
class Command:
    """One utterance under construction: its gold asks and the clauses that say
    them. The text is always `render()` — nothing writes it directly."""
    family: str
    grammar: tuple
    joiner: str
    voice: str
    asks: list = field(default_factory=list)
    clauses: list = field(default_factory=list)
    head: list = field(default_factory=list)
    tail: list = field(default_factory=list)
    applied: list = field(default_factory=list)
    repeated_clause: bool = False

    def clause_for(self, ask):
        """The clause this ask is said in. A `comma_list_and` family says N
        asks in ONE clause, so the extra asks are found through `also_asks`
        rather than by id — a damage operation aimed at the third thing in a
        list must still land somewhere."""
        for c in self.clauses:
            if c["ask"] == ask["ask_id"] or ask["ask_id"] in (c.get("also_asks") or ()):
                return c
        return None

    def render_clause(self, clause) -> str:
        body = clause["text"]
        time = clause.get("time") or ""
        if time:
            body = f"{time}, {body}" if clause.get("time_first") else f"{body} {time}"
        out = " ".join(x for x in (clause.get("prefix", ""), body) if x)
        return out + clause.get("suffix", "")

    def render(self) -> str:
        sep = JOINERS.get(self.joiner) or " and "
        parts = [self.render_clause(c) for c in self.clauses]
        text = parts[0]
        for p in parts[1:]:
            stripped = text.rstrip()
            text = stripped + (" " if stripped.endswith((".", "?", "!"))
                               else sep) + p.lstrip()
        if self.head:
            text = " ".join(self.head) + " " + text
        if self.tail:
            text = text.rstrip()
            if not text.endswith((".", "?", "!")):
                text += ","
            text += " " + " ".join(self.tail)
        return " ".join(text.split())


# ---------------------------------------------------------------------------
# 2 · THE FAMILIES — a grammar skeleton plus a joiner, and the SPLIT UNIT
# ---------------------------------------------------------------------------

#: Shape pairs, triples and quads. Chosen to cross the five operations with
#: each other rather than to be exhaustive: an event beside a to-do, a query
#: beside a create, a delete beside a create, an anaphoric edit beside a
#: create — the shapes real commands actually mix.
_PAIRS = [
    ("ce_dt", "ct"), ("ce_dt", "ct_d"), ("ce_dt", "ce_dt"), ("ce_d", "ce_t"),
    ("ct", "ct"), ("ce_dt", "q_day"), ("q_day", "ce_dt"), ("ce_dt", "de"),
    ("de", "ce_dt"), ("ce_dt", "ue_clock"), ("ct_dt", "comp"),
    ("ce_recur", "ct"), ("ce_dt", "anaph_u"), ("ce_dt", "dt"),
    ("ce_range", "ct_d"), ("ce_recur_d", "ce_dt"), ("ct_d", "q_todo"),
    ("ue_day", "ct"), ("ce_t", "ct_dt"), ("ce_bare", "ce_dt"),
    ("ce_dt", "anaph_d"), ("ce_recur_y", "ct"), ("de_day", "ce_d"),
    ("ce_dt", "comp"), ("ct", "ue_clock"),
]
_TRIPLES = [
    ("ce_dt", "ct", "ce_dt"), ("ce_dt", "ce_dt", "ct"), ("ct", "ct", "ct"),
    ("ce_dt", "q_day", "ct"), ("ce_dt", "ct_d", "de"), ("ce_d", "ce_t", "ct"),
    ("ce_recur", "ce_dt", "ct"), ("ce_dt", "ue_clock", "ct"),
    ("ct_dt", "ce_dt", "comp"), ("ce_dt", "ct", "anaph_u"),
]
_QUADS = [
    ("ce_dt", "ce_dt", "ce_dt", "ce_dt"), ("ce_dt", "ct", "ce_dt", "ct"),
    ("ce_dt", "ct_d", "de", "q_day"), ("ce_d", "ce_t", "ct", "ct_d"),
    ("ce_dt", "ce_recur", "ct", "comp"),
]


def families() -> list:
    """Every family in the catalog: `(shapes, joiner, list_n)`.

    A family is the SPLIT UNIT (`engine/TRAIN_TEST_SPLIT_CONVENTION.md`): every
    row generated from it goes entirely to one side, so a skeleton in the test
    half was never seen in training. Voices and damage operations are NOT part
    of the family — they must appear on both sides, or the halves stop being
    comparable.
    """
    out = [((s,), "single", None) for s in SHAPES]
    for pair in _PAIRS:
        out += [(pair, j, None) for j in ("and", "also", "comma_then", "and_then")]
    for t in _TRIPLES:
        out += [(t, j, None) for j in ("and", "also", "comma_then", "and_then")]
    for q in _QUADS:
        out += [(q, j, None) for j in ("and", "also", "and_then")]
    for n in (2, 3, 4):
        out += [((s,), "comma_list_and", n) for s in ("ce_dt", "ce_d", "ct")]
    for n in (2, 3):
        out += [((s,), "comma_run_plain", n) for s in ("ce_dt", "ce_d")]
    return out


def family_id(shapes: tuple, joiner: str, list_n) -> str:
    return "+".join(shapes) + f"__{joiner}" + (f"x{list_n}" if list_n else "")


def split_of(fam: str, shapes: tuple, joiner: str, seed: int = SEED) -> str:
    """Halve the families by a stable hash, stratified by (how many asks, the
    first action, subject-level or not) so neither side loses a slice. The
    hash is of the family NAME, so the assignment is a pure function of the
    catalog and survives a regeneration — `PYTHONHASHSEED` cannot move it."""
    bucket = (f"{len(shapes)}:{SHAPES[shapes[0]]['action']}:"
              f"{joiner in ('comma_list_and', 'comma_run_plain')}")
    h = hashlib.md5(f"{seed}|{bucket}|{fam}".encode()).hexdigest()
    return "train" if int(h[:8], 16) % 2 == 0 else "test"


# ---------------------------------------------------------------------------
# 3 · COMPOSING ONE COMMAND
# ---------------------------------------------------------------------------

def _clock_for(rng, voice, family_form: str) -> tuple:
    """(clock, form, phrase) — the VALUE from the grammar, the FORM from the
    voice where it has a habit and from the family otherwise.

    The rng is consumed exactly once, before any form is tried, so the seven
    voices draw the same clock value and differ only in how they say it.
    """
    clock = banks.CLOCKS[rng.randrange(len(banks.CLOCKS))]
    for form in tuple(voice.clock_forms) + (family_form,) + voices.CLOCK_FORMS:
        phrase = voices.render_clock(clock, form)
        if phrase:
            return clock, form, phrase
    raise AssertionError(f"no renderable clock form for {clock['value']}")


def _ask(idx: int, shape_id: str, rng, voice, family_form: str) -> dict:
    """One gold ask, plus the words that say it in this voice.

    Every random draw here is from `rng_gold`, and the voice only RENDERS what
    was drawn, which is what keeps the gold identical across the seven.
    """
    sh = SHAPES[shape_id]
    ask = {"ask_id": idx, "shape": shape_id, "action": sh["action"],
           "kind": sh["kind"], "title": None, "intended_title": None,
           "anaphor": None, "date_phrase": None, "clock": None,
           "end_clock": None, "recurrence": None, "recur_days": [],
           "date_deliberate": False, "subject_said": None, "date_said": None,
           "clock_form": None, "clock_phrase": None, "time_said": ""}

    if sh["subject"] in ("event", "target_event"):
        core = banks.EVENT_SUBJECTS[rng.randrange(len(banks.EVENT_SUBJECTS))]
        ask["title"] = core
        ask["subject_said"] = voices.subject_for(voice, "the " + core)
    elif sh["subject"] in ("task", "target_task"):
        core = banks.TASK_SUBJECTS[rng.randrange(len(banks.TASK_SUBJECTS))]
        ask["title"] = core
        ask["subject_said"] = core
    elif sh["subject"] == "anaphor":
        ask["anaphor"] = banks.ANAPHORS[rng.randrange(len(banks.ANAPHORS))]
        ask["subject_said"] = ask["anaphor"]

    parts = []
    if sh.get("recur"):
        pool = [r for r in banks.RECURRENCES
                if (sh["recur"] == "weekdays" and len(r["days"]) > 1)
                or (sh["recur"] == "yearly" and r["cadence"] == "yearly")
                or (sh["recur"] == "plain"
                    and r["cadence"] in ("daily", "weekly", "monthly"))]
        rec = pool[rng.randrange(len(pool))]
        ask["recurrence"] = rec["cadence"]
        ask["recur_days"] = list(rec["days"])
        ask["date_said"] = voices.date_phrase_for(voice, rec["phrase"])
        parts.append(ask["date_said"])
    elif sh.get("date"):
        phrase, deliberate = banks.DATE_PHRASES[
            rng.randrange(len(banks.DATE_PHRASES))]
        ask["date_phrase"] = phrase
        ask["date_deliberate"] = deliberate
        ask["date_said"] = voices.date_phrase_for(voice, phrase)
        parts.append(ask["date_said"])

    if sh.get("clock"):
        clock, form, phrase = _clock_for(rng, voice, family_form)
        ask["clock"] = clock["value"]
        ask["clock_form"] = form
        ask["clock_phrase"] = phrase
        parts.append(phrase)
        if sh.get("end"):
            later = [c for c in banks.CLOCKS if c["value"] > clock["value"]]
            if later:
                end = later[rng.randrange(len(later))]
                ask["end_clock"] = end["value"]
                endp = (voices.render_clock(end, form)
                        or voices.render_clock(end, "colon"))
                parts.append("to " + endp.split(" ", 1)[1])
    ask["time_said"] = " ".join(p for p in parts if p)
    return ask


def _frame(voice, ask, rng) -> str:
    """The ACTION WORDS for this ask, in this voice — the item's `text`. Never
    the time: `Item.time` carries the time reference as spoken, and
    `decompose_validate` resolves THAT (`engine/state.py`, `stage.resolve_
    values`). An item whose text swallows its own time resolves nothing."""
    sh = SHAPES[ask["shape"]]
    key = _FRAME_KEY[ask["action"]]
    if sh["subject"] == "anaphor":
        key = "update_anaphor" if ask["action"] == "update_event" else "delete_anaphor"
    frames = voice.frames[key]
    tpl = frames[rng.randrange(len(frames))]
    return tpl.format(s=ask["subject_said"]) if "{s}" in tpl else tpl


def _compose_clauses(cmd: Command, rng, voice) -> None:
    for ask in cmd.asks:
        cmd.clauses.append({"ask": ask["ask_id"], "prefix": "",
                            "tpl": None, "text": _frame(voice, ask, rng),
                            "time": ask["time_said"],
                            "time_first": rng.random() < 0.18, "suffix": ""})


def _compose_list(cmd: Command, rng, voice) -> None:
    """"an event for A, B and C" — ONE frame, N gold asks.

    Gil, 2026-09-20: a calendar create over a LIST of things is several events,
    and `findings.COORDINATED_SUBJECT` exists to rewrite exactly this. So the
    gold is N asks sharing one day and one clock; a reader that keeps the list
    as one title has under-split, and the gold says so.
    """
    first = cmd.asks[0]
    for other in cmd.asks[1:]:                 # one frame, one when, N things
        for k in ("date_phrase", "date_said", "date_deliberate", "clock",
                  "clock_form", "clock_phrase", "end_clock", "recurrence",
                  "recur_days", "time_said"):
            other[k] = first[k]
    heads = [a["subject_said"] for a in cmd.asks]
    run = ", ".join(heads[:-1]) + " and " + heads[-1]
    frames = voice.frames[_FRAME_KEY[first["action"]]]
    tpl = frames[rng.randrange(len(frames))]
    cmd.clauses.append({
        "ask": first["ask_id"], "prefix": "", "tpl": tpl,
        "text": tpl.format(s=run) if "{s}" in tpl else tpl,
        "time": first["time_said"], "time_first": rng.random() < 0.18,
        "suffix": "", "also_asks": [a["ask_id"] for a in cmd.asks[1:]]})


def _compose_run(cmd: Command, rng, voice, n: int) -> None:
    """"TA, office hour, meeting" — one frame, ONE gold ask (DEVQA Q43).

    A comma run with NO conjunction is not a list; it is the speaker saying one
    thing several ways, and it stays one event. The gold title is the first
    phrase — the subject — and the restatements ride along as acceptable
    alternatives, which is the shape the real-usage board's own hand-authored
    gold uses (`title_has` is a list of what would do).
    """
    ask = cmd.asks[0]
    parts = [ask["subject_said"]]
    restate = banks.RESTATEMENTS.get(ask["title"])
    if restate:
        parts.append(restate)
    parts.append(banks.KIND_WORDS["event" if ask["kind"] == "event"
                                  else "task"][rng.randrange(3)])
    parts = parts[:max(2, n)]
    ask["title_alternatives"] = list(parts)
    ask["subject_said"] = ", ".join(parts)
    frames = voice.frames[_FRAME_KEY[ask["action"]]]
    tpl = frames[rng.randrange(len(frames))]
    cmd.clauses.append({
        "ask": ask["ask_id"], "prefix": "", "tpl": tpl,
        "text": tpl.format(s=ask["subject_said"]) if "{s}" in tpl else tpl,
        "time": ask["time_said"], "time_first": False, "suffix": ""})


#: How many damage operations each variant carries. **Variant 0 is always
#: CLEAN SPEECH** — a set with no undamaged rows cannot say what the damage
#: cost, which is the same reason half the object-level cases are untouched.
_VARIANT_OPS = (0, 1, 1, 2)


def _damage_plan(rng, variants: int, ops: list) -> list:
    """Which operations each variant carries, drawn once per FAMILY.

    The chosen ops are then ordered **gold-changers first**, and that is not
    cosmetic. A noise operation rewrites the clause the subject sits in — a
    stutter doubles a word inside it — and the recogniser operations look the
    subject up as a contiguous string. Run in the other order they fail on the
    voices whose frame happens to put the stutter inside the subject and
    succeed on the rest, and the seven renderings of one command stop sharing
    one gold. Five utterances diverged exactly this way before the sort.
    """
    plan = []
    for v in range(variants):
        pool = list(ops)
        rng.shuffle(pool)
        chosen = pool[:_VARIANT_OPS[v % len(_VARIANT_OPS)]]
        plan.append(sorted(chosen, key=lambda o: o not in damage.GOLD_CHANGING))
    return plan


def build_commands(seed: int = SEED, variants: int = 4,
                   limit_families: int = 0) -> list:
    """The command-level rows. PURE — no engine import, no model, no clock
    read — which is what lets the unit tests run the whole catalog in a second
    and what makes the output byte-identical on a re-run.
    """
    fams = families()
    if limit_families:
        fams = fams[:limit_families]
    op_names = sorted(damage.OPERATIONS)
    rows, n = [], 0
    for shapes, joiner, list_n in fams:
        fam = family_id(shapes, joiner, list_n)
        split = split_of(fam, shapes, joiner, seed)
        plan = _damage_plan(random.Random(f"{seed}|plan|{fam}"), variants,
                            op_names)
        for variant in range(variants):
            form = voices.CLOCK_FORMS[
                random.Random(f"{seed}|form|{fam}|{variant}")
                .randrange(len(voices.CLOCK_FORMS))]
            for voice in voices.VOICES:
                rng_gold = random.Random(f"{seed}|{fam}|{variant}")
                rng_words = random.Random(f"{seed}|{fam}|{variant}|{voice.id}")
                rng_damage = random.Random(f"{seed}|{fam}|{variant}|damage")
                cmd = Command(family=fam, grammar=shapes, joiner=joiner,
                              voice=voice.id)
                n_asks = (list_n if joiner == "comma_list_and"
                          else 1 if joiner == "comma_run_plain" else len(shapes))
                seq = ([shapes[0]] * n_asks if joiner in ("comma_list_and",
                                                          "comma_run_plain")
                       else list(shapes))
                cmd.asks = [_ask(i + 1, s, rng_gold, voice, form)
                            for i, s in enumerate(seq)]
                if joiner == "comma_list_and":
                    _compose_list(cmd, rng_words, voice)
                elif joiner == "comma_run_plain":
                    _compose_run(cmd, rng_words, voice, list_n or 2)
                else:
                    _compose_clauses(cmd, rng_words, voice)
                clean_text = voices.finish(voice, cmd.render())
                for op_name in plan[variant]:
                    if damage.OPERATIONS[op_name](cmd, rng_damage):
                        cmd.applied.append(op_name)
                n += 1
                rows.append(_row(cmd, voice, split, joiner, list_n, variant, n,
                                 voices.finish(voice, cmd.render()), clean_text))
    return rows


def _item_words(cmd: Command, ask: dict) -> dict:
    """The gold ITEM for one ask — the words segmentation should hand FastRule.

    For a `comma_list_and` family that is NOT the whole clause: the gold is N
    events, so each ask's item carries the frame with ITS OWN thing in it,
    which is what the loop's rewrite ("one clause per thing") would produce.
    """
    clause = cmd.clause_for(ask)
    if clause is None:
        clause = cmd.clauses[0]
    if clause.get("also_asks"):
        tpl = clause.get("tpl") or "{s}"
        text = tpl.format(s=ask["subject_said"]) if "{s}" in tpl else tpl
    else:
        text = " ".join(x for x in (clause.get("prefix", ""), clause["text"])
                        if x)
    return {"text": " ".join(text.split()),
            "time": " ".join((clause.get("time") or "").split()),
            "kind": ask["kind"]}


def _row(cmd: Command, voice, split: str, joiner: str, list_n, variant: int,
         n: int, text: str, clean_text: str) -> dict:
    asks = []
    for a in cmd.asks:
        asks.append({
            "ask_id": a["ask_id"], "shape": a["shape"], "action": a["action"],
            "kind": a["kind"], "title": a["title"],
            "intended_title": a["intended_title"],
            "title_alternatives": a.get("title_alternatives"),
            "anaphor": a["anaphor"], "date_phrase": a["date_phrase"],
            "clock": a["clock"], "end_clock": a["end_clock"],
            "recurrence": a["recurrence"], "recur_days": a["recur_days"],
            "bare_kind": bool(a.get("bare_kind")),
            "wrong_weekday": a.get("wrong_weekday"),
            "said": {"subject": a["subject_said"], "date": a["date_said"],
                     "clock_form": a["clock_form"],
                     "clock_phrase": a["clock_phrase"]},
            "item": _item_words(cmd, a),
        })
    actions = {a["action"] for a in cmd.asks}
    return {
        "id": f"v2c-{n:06d}",
        "utterance": f"{cmd.family}#v{variant}",
        "family": cmd.family,
        "grammar": list(cmd.grammar),
        "joiner": joiner + (f"x{list_n}" if list_n else ""),
        "split": split,
        "voice": voice.id,
        "damage": list(cmd.applied),
        "text": text,
        # WHAT THE SPEAKER WOULD HAVE SAID undamaged — null when nothing was
        # done to this row, rather than a second copy of `text` on half the set.
        "clean_text": clean_text if clean_text != text else None,
        "n_asks": len(cmd.asks),
        "asks": asks,
        "expect": {
            "events": sum(1 for a in cmd.asks if a["kind"] == "event"
                          and a["action"].startswith("create")),
            "tasks": sum(1 for a in cmd.asks if a["kind"] == "task"
                         and a["action"].startswith("create")),
            "action": list(actions)[0] if len(actions) == 1 else "mixed",
            "atomic": len(cmd.asks) == 1,
        },
        "retracted_clause": cmd.repeated_clause,
    }


# ---------------------------------------------------------------------------
# 4 · THE OBJECT-LEVEL CASES
# ---------------------------------------------------------------------------

def scratch_env() -> None:
    """Every store redirected BEFORE `assistant` is imported. `~/.assistant_
    tools/` holds the real calendar, the hand-curated vocabulary and the
    command memory; a generator has no business in any of it, and the paths
    are read at import time so a fixture would be too late."""
    s = pathlib.Path(tempfile.mkdtemp(prefix="judge_v2_"))
    for var, name in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
                      ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
                      ("TRACE_BUS", "trace_bus.jsonl"), ("MODELS", "models"),
                      ("LABEL_FEEDBACK", "feedback.jsonl"),
                      ("MODEL_LOCK", "model.lock"), ("DEVICE_SECRET", "secret"),
                      ("DEVICES", "devices.json"), ("LEXICON", "lexicon.json"),
                      ("CHECKPOINTS", "checkpoints"), ("UI_STATE", "ui.ini"),
                      ("LOCATION", "location.json")):
        os.environ[f"MACALENDAR_{var}"] = str(s / name)
    os.environ["MACALENDAR_NO_WARMUP"] = "1"
    os.environ["MACALENDAR_LLM_DISABLED"] = "1"
    os.environ["MACALENDAR_OBSERVANCE"] = "0"
    # Background traffic: it yields ollama to the live assistant even though
    # this generator makes no model call at all (`priority()` defaults to LIVE,
    # and a job that forgets is invisible to every other check).
    os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
    for t in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(t, "1")


def build_cases(rows: list, seed: int = SEED, progress: bool = False) -> tuple:
    """Plant one defect per command, on objects the REAL converter built.

    Returns `(cases, clock_forms_seen, clock_forms_right, deferred)`.

    The case is a RECIPE, never a serialised intent: it stores the gold items
    and the plant, and a board rebuilds the object with `fastrule.build` so
    that what is judged is what production would produce. The converter runs
    HERE anyway, for two reasons v1 paid for: to know which plants are possible
    at all (a dropped clock on an object that resolved none changes nothing,
    and the board scores the miss against the judge), and to prove the plant
    CHANGES the rendered object before the case is written.
    """
    from freezegun import freeze_time
    from assistant.engine import llm as _llm
    from assistant.engine.decompose_validate import stage as _dv
    from assistant.engine.fastrule.build import Built, build_all
    from assistant.engine.state import EngineState, Item
    from assistant.engine.llmjudge.datasets.v2 import mutations

    # spaCy's pipeline must be built OUTSIDE the frozen clock — building it
    # under freezegun raises, and every row would then resolve nothing.
    _llm.get_rule_parser().analyze("book gym tomorrow at 7am", current_view="month")

    rng = random.Random(f"{seed}|cases")
    cases = []
    used = {"train": collections.Counter(), "test": collections.Counter()}
    seen, right = collections.Counter(), collections.Counter()
    deferred = collections.Counter()
    # THE REAL CLOCK, captured before freezegun patches the module. Inside
    # `freeze_time` every clock in `time` returns the same instant, so a
    # progress line computed with `time.time()` divides by zero and prints a
    # rate of 500,000,000 rows a second — which is what the first run did.
    real_time = time.time
    t0 = real_time()
    with freeze_time(CLOCK):
        for n, row in enumerate(rows, 1):
            items = [Item(id=f"item_{a['ask_id']}", kind=a["item"]["kind"],
                          text=a["item"]["text"], time=a["item"]["time"] or None)
                     for a in row["asks"]]
            st = EngineState(raw_text=row["text"], text=row["text"],
                             source="test")
            st.items = items
            try:
                _dv.resolve_values(st, CLOCK.date())
            except Exception:
                pass
            results = build_all(items)
            built = [(it, r) for it, r in zip(items, results)
                     if isinstance(r, Built)]
            for it, r, a in zip(items, results, row["asks"]):
                if not isinstance(r, Built):
                    deferred[a["action"]] += 1
                if a["clock"]:
                    seen[a["said"]["clock_form"]] += 1
                    if (it.slots or {}).get("start_time") == a["clock"]:
                        right[a["said"]["clock_form"]] += 1
            if built:
                clean = mutations.make_case(row, items, results, built,
                                            "clean", rng)
                if clean is not None:
                    cases.append(clean)
                # THE LEAST-USED APPLICABLE PLANT FIRST, per split, and the
                # next one when it will not take. Picking at random leaves the
                # rarest mutation with a rate that is noise; picking only the
                # least-used STARVES — a mutation that is applicable but never
                # effective stays at its count, is chosen every time, fails
                # every time, and the set comes out 92% clean. Measured on the
                # first 24-family run: 20 planted cases out of 672 commands.
                # A COMMAND CARRIES A SECOND PLANT ONLY WHEN IT BUILT THREE OR
                # MORE OBJECTS. Two cases from one sentence are not
                # independent — a confidence interval on the pair belongs on
                # the COMMAND, not the case, and the README says so beside the
                # counts — so the second plant is spent where it buys the most:
                # the compound rows, which are the only place `dropped_ask` and
                # `merged_asks` can be planted at all.
                want = 2 if len(built) >= 3 else 1
                for name in sorted(mutations.applicable(row, items, results,
                                                        built),
                                   key=lambda m: (used[row["split"]][m], m)):
                    if name == "clean":
                        continue
                    case = mutations.make_case(row, items, results, built,
                                               name, rng)
                    if case is not None:
                        used[row["split"]][name] += 1
                        cases.append(case)
                        want -= 1
                        if want == 0:
                            break
            if progress and n % 500 == 0:
                el = max(real_time() - t0, 1e-6)
                rate = n / el
                print(f"    {n}/{len(rows)} commands · {rate:.0f}/s · "
                      f"eta {(len(rows) - n) / rate:5.0f}s · "
                      f"{len(cases)} cases", flush=True)
    return cases, seen, right, deferred


# ---------------------------------------------------------------------------
# 5 · main
# ---------------------------------------------------------------------------

def write_jsonl(path: pathlib.Path, rows: list) -> None:
    """One row per line, keys sorted, separators compact — a dataset that ships
    in the repository pays for every space it writes twice over (this set is
    ~19,000 rows), and sorted keys are what make a regeneration a no-op in
    `git diff` when nothing actually changed."""
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", type=int, default=4,
                    help="renderings per (family, voice); variant 0 is clean")
    ap.add_argument("--limit-families", type=int, default=0)
    ap.add_argument("--commands-only", action="store_true")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()

    scratch_env()
    t0 = time.time()
    print("· composing commands …", flush=True)
    rows = build_commands(a.seed, a.variants, a.limit_families)
    fams = {r["family"] for r in rows}
    print(f"  {len(rows)} commands · {len(fams)} families · "
          f"{len({r['text'] for r in rows})} distinct texts · "
          f"{time.time() - t0:.1f}s", flush=True)
    write_jsonl(COMMANDS, rows)
    print(f"  -> {COMMANDS}", flush=True)
    if a.commands_only:
        return 0

    print("· planting cases (the real converter runs on every command) …",
          flush=True)
    cases, seen, right, deferred = build_cases(rows, a.seed, progress=True)
    write_jsonl(CASES, cases)
    print(f"  {len(cases)} cases -> {CASES}", flush=True)

    per = collections.Counter((c["split"], c["mutation"]) for c in cases)
    print("\n  mutation                  train    test")
    for m in sorted({m for _s, m in per}):
        print(f"    {m:<22}{per[('train', m)]:>7}{per[('test', m)]:>8}")
    print("\n  how the engine READ each spoken clock form (resolved == gold).")
    print("  A DIAGNOSTIC, never a gold source: a form the reader loses is a "
          "case, not a\n  data defect, and the gold is not moved to agree "
          "with it.")
    for form, n in seen.most_common():
        print(f"    {form:<14}{right[form]:>6}/{n:<6} "
              f"{100.0 * right[form] / max(n, 1):5.1f}%")
    if deferred:
        print("\n  asks the converter DEFERRED (no object, so no case):")
        for act, n in deferred.most_common():
            print(f"    {act:<18}{n:>6}")
    print(f"\n  total {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
