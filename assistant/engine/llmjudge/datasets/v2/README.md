# The v2 judge set — commands by grammar, damaged by observed operations

**What it is.** ~5,300 spoken commands with exact gold, and ~11,000
object-level cases planted from them, built for the measurement `PLAN.md` §7.2
asks for. The v1 set (`../judge_cases.jsonl`, 1,800 cases, six synthetic
defects over FastRule's template corpus) is not retired by this and is not
replaced by it: it is a different instrument, and the deterministic judge is at
ceiling on it. This set exists because of §7.1 —

> Real speech fails on classes the six defects do not contain: disfluent
> titles, recogniser garbage, a subject the words held and the reader dropped,
> merged asks, a wrong kind or operation. The stage is blind to them **by
> construction, not by implementation**.

So the set carries those classes, and says plainly which of them today's
finding taxonomy has no name for.

---

## WHICH HALF OF THIS IS REAL — read this before quoting a number

The honesty `scripts/vocab_repair_bench.py` puts at the top of itself, because
this set is built the same way and the same caveat binds it:

* **The damage OPERATIONS are observed, not invented.** The six `stt_*` ones
  are not even re-implemented — they are the functions
  `scripts/vocab_repair_bench.py` carries, imported, and that file records each
  as a shape present in the observed corpus. The ten speech ones are derived
  from the CLASSES in `DOCUMENTATION/experiments/real_usage/taxonomy.jsonl`
  (`disfluency`, `generic-title`, `stt-garbage`, `stutter-split`,
  `anaphoric-edit`), and each operation's docstring names the rows its shape
  was read off.
* **The TERMS are invented.** Every subject, name and restatement in
  `banks.py` is made up — generic activity nouns, loanwords and ordinary
  compounds — and **no real transcript is copied into the data**. A docstring
  may name a row id and the marker words a class is defined by ("sorry, i
  mean", "no, i said that"); it never reproduces what was said.
* **The VOICES borrow habits, not rows.** `dataset/personas/` is TEST-ONLY
  FOREVER, banks included. Nothing here is copied from `personas.jsonl`,
  `banks/` or `structures.json`; what is borrowed is the one-line habit each
  persona is defined by in `PERSONAS.md`'s own table, and the frames were
  written fresh against those lines. The persona board stays a clean
  instrument: it scores phrasings this set does not contain.

So this is a **stress set**, not a real-usage one. The 75 real rows the
real-usage board scores stay the primary instrument for "does this reach real
speech" (`PLAN.md` §7.4's outer gate). Never sum the two.

---

## How the gold is built — BY CONSTRUCTION, never a model's opinion

The generator chooses the ask before it chooses the words:

    a GRAMMAR of asks          21 ask shapes: create / to-do / query / update /
                               delete / complete, with a day, a clock, a
                               cadence, a time range or an anaphoric target
        |
        v
    a FAMILY                   one to four ask shapes + a joiner. The family is
                               the SPLIT UNIT and the thing a phrasing belongs
                               to.
        |
        v
    SEVEN VOICES               plain + the six persona habits. The voice fixes
                               the frame, the clock's spoken form and the
                               punctuation/article habit — and NOTHING ELSE, so
                               the seven renderings share one gold.
        |
        v
    DAMAGE                     0, 1 or 2 named operations per row. Variant 0 of
                               every family is always CLEAN SPEECH.
        |
        v
    the COMMAND row            text + the ask list (action, kind, title, day
                               phrase, clock, cadence, recur days, anaphor) +
                               the gold ITEMS segmentation should produce.

`PLAN.md` §7.2 is explicit that a model may not label this: *"a model labelling
what a model will be judged on is circular, and free-form LLM gold is what the
dropped real-speech set was."* There is no model call anywhere in the pipeline
— `MACALENDAR_LLM_DISABLED=1` is set by the generator itself — and nothing in
the gold is hand-written.

### The gold does not move with the voice, and rarely with the damage

Three separate random streams buy the first half: `rng_gold` draws the ask
(one per family+variant, so all seven voices draw the same), `rng_words` draws
the frame (per voice), `rng_damage` draws the damage (per family+variant).
`tests/unit/test_llmjudge_dataset_v2.py` pins it on every row.

**Three kinds of operation DEFINE a gold change** (eight of the sixteen), and
they are declared in `damage.GOLD_CHANGING`, stated in the operation's own
docstring, and nowhere else:

| operation | what moves, and why |
|---|---|
| the six `stt_*` | the gold TITLE becomes the damaged form; the clean one is kept as `intended_title`. This is `assistant/intent/correction.py`'s rule verbatim — a title the recogniser mangled "is the recogniser's failure and the vocabulary owns it, not the parser" — and the alternative is a gold value nothing in the words can reach. |
| `bare_kind_title` | the gold TITLE becomes the bare kind word, per DEVQA Q41/Q42: *a bare 'meeting' with the day and the clock COMMITS.* No `intended_title` is claimed, because none was said. |
| `retraction` | the repeated ask is **not** in the gold. The clause is in the words; the retraction cancels it. Real usage id=223 made four items for two by reading the marker as filler. |

Everything else adds noise around a gold that does not move.

### Two rulings the grammar is built on

* **DEVQA Q43 (2026-09-22): a comma run with no conjunction is NOT a list.**
  The `comma_run_plain` families say one subject several ways — "…, the
  dentist, meeting" — and the gold is **ONE ask**, with the restatements
  carried as `title_alternatives` (the shape the real-usage board's own
  hand-authored gold uses). A unit test pins this, because a generator that
  quietly made it three would teach the judge the opposite of what was ruled.
* **Gil, 2026-09-20: a calendar create over a LIST of things is several
  events.** The `comma_list_and` families are one frame, one day, one clock
  and N things, and the gold is N asks — which is what
  `findings.COORDINATED_SUBJECT` exists to rewrite.

### Gold that follows a ruling (2026-09-24)

`ct_dt` ("remind me to X <day> at <clock>") was written as a to-do. **Q25/Q26
make it an event**: *"reminding me to do something at a specific time counts
as an event."* The kind board (`decompose_validate/experiments/RESULTS.md`)
found this set charging the engine for obeying that ruling.

`generate_v2.RULED_SHAPES` now writes the ruled gold. The words, frame,
subject bank, damage, ids and split are all still read off the shape as
declared, so no text moves. Each ruled ask carries `ruled: "Q26"`. The change
covers 364 asks in 364 commands (224 train, 140 test): `action`, `kind`,
`item.kind`, and the command's `events`/`tasks` and, for 140 of them, its
`action`.

No v2 to-do subject names a person, so Q47 (an encounter is an event) moves
nothing here. "call the chiropractor" is not an encounter under
`intent/encounter.py`.

**The cases were moved by `rule_cases`, not rebuilt.** A rebuild at HEAD also
moves plants on about 4,700 cases, because the converter changed after cycle 42
and `build_cases` spends one rng stream and one plant quota across the whole
set. That is a separate instrument change. `--rule-cases` moves only the 805
cases on ruled commands:

- each ruled item's kind is updated;
- a `wrong_kind` / `wrong_operation` plant is re-flipped from the ruled
  action. The old flip of create_todo gave create_event, which is now simply
  right.

On a fresh build `rule_cases` is a no-op, which was checked.

---

## The object-level cases

Each case is a **recipe, not a serialised intent** (v1's rule, kept): it
carries the gold items and one plant, and a board rebuilds the object with the
real converter (`assistant/engine/fastrule/build.py`) before applying it, so
what is judged is what production would produce. `mutations.apply(case, items,
results)` is the plant, and it lives here so the board and the generator use
one copy of it.

Generation runs the converter on every command anyway, for two reasons v1 paid
for: to know which plants are POSSIBLE (a dropped clock on an object that
resolved none changes nothing, and the board scores the miss against the
judge), and to prove each plant CHANGES the rendered object before the case is
written. An ineffective plant is dropped and the next mutation is tried.

| mutation | expected finding | what it is |
|---|---|---|
| `clean` | — | untouched; the false-flag denominator |
| `generic_title` | `ungrounded_subject` | an event titled "Event" |
| `invented_title` | `ungrounded_subject` | the cycle-7 fabrication |
| `near_miss_title` | `ungrounded_subject` | "buy groceries" from "buy milk" |
| `subject_dropped_for_kind` | `ungrounded_subject` | Q42's other half: a bare kind over words that DID name the thing |
| `dropped_date` | `unsupported_field` | a date the words never gave |
| `dropped_time` | `unsupported_field` | a clock the words never gave |
| `unrelated_object` | `not_an_ask` | an object nobody asked for |
| `merged_asks` | `unsplit_subject` (seam) · `coordinated_subject` (a list of 3 EVENT subjects) · **—** (a plain "and") | two asks the cut left together — the WORDS are merged, not only the titles. The list is the asks' gold `said.subject`, events only, three or more (18 train / 0 test — a thin n, said so on the board); a row that cannot supply that is a plain merge, never a wrong expectation (cycle 42, 2026-09-22: the plant used to list the converter's titles, so a task's verb phrase, a member still wearing its frame, or a pair of three was expected to read as a noun list — 55 of 73 list rows) |
| `dropped_ask` | **—** | an ask with nothing built for it |
| `wrong_kind` | **—** | an event built for a to-do, or the reverse |
| `wrong_operation` | **—** | a create for a change, within one store |
| `clock_residue_title` | **—** | "meeting a.m" as a title |

**A dash is not an oversight.** `expect: null` with `defect: true` means the
defect is real and **today's taxonomy has no finding type for it** — the ask
diff that could see a dropped ask was removed on 2026-09-10, and nothing reads
the kind, the operation, or a clock inside a title. Those cases are their own
column, and a board must never pool them with the clean rows: a clean row is
the false-flag denominator, and counting a planted defect there would reward
the judge for missing it.

### Three things a board built on this must do

1. **Take the baseline from the CLEAN TWIN, not by recomputing.** Every
   command that produced an object has a `#clean` case in the file. An
   unmutated object legitimately carries findings (an all-day ask resolves no
   clock and pydantic stamps one), and v1's board subtracted only the slot
   findings; here the twin gives the whole baseline for free.
2. **Count a wrong TYPE as a miss, not a catch.** The type decides the route
   (`findings.ROUTE`): `ungrounded_subject` is rewritten and re-entered,
   `not_an_ask` goes to the review panel and is never retried. A fabricated
   title reported as `not_an_ask` is a routing error worth seeing.
3. **Put the confidence interval on the COMMAND, not the case.** A command
   contributes a clean case and one plant — two when it built three or more
   objects — and those cases are the same sentence. They are not independent.

---

## The split — by FAMILY, half and half

`assistant/engine/TRAIN_TEST_SPLIT_CONVENTION.md` is the rule and this set
follows the general half of it: the split unit is the **pattern family** (the
ask skeleton plus its joiner), assigned by a stable MD5 of the family name,
stratified by (how many asks · the first action · subject-level joiner or not).
Every row of a family goes entirely to one side, so a skeleton in the test half
was never trained on, and the assignment is a pure function of the catalog —
`PYTHONHASHSEED` cannot move it and a regeneration reproduces it exactly.

**Voices and damage operations are NOT part of the family.** All seven voices
and all sixteen operations appear on both sides, and `verify_v2.py` refuses the
set otherwise: if one half is missing an operation, the difference between the
halves is not a generalisation gap.

**The test half is sealed the same way every other test half in this project
is.** Aggregates only, no row detail, never mined for a fix, and the
`--i-know-this-is-train-only` discipline applies to anything built on it.

---

## Diversity — the deliverable, not the row count

Pasted from `verify_v2.py`, which prints it on every run. *"1,000 rows from 26
templates is 26 examples with a big denominator"* (Gil, 2026-09-19), so these
are the numbers that say what the set can carry.

```text
V2 JUDGE SET — 5292 commands · 11187 cases

  DIVERSITY (the deliverable — a row count is not one)

                                 train    test   total
    rows                          2520    2772    5292
    distinct command texts        2486    2743    5229
    families (the split unit)       90      99     189
    grammars (ask skeletons)        49      50      61
    joiners                          9       9      10
    voices                           7       7       7
    damage operations               16      16      16
    ask shapes                      21      21      21
    actions                          8       8       8
    spoken clock forms              11      11      11
    distinct subjects              209     229     311
    date phrases                    14      14      14
    cadences                         4       4       4
    cases                         5385    5802   11187
    mutations                       13      13      13

  ROWS PER SPLIT
    train                         2520 commands    5385 cases
    test                          2772 commands    5802 cases

  ASKS PER COMMAND
    1 ask(s)                       700
    2 ask(s)                      2884
    3 ask(s)                      1204
    4 ask(s)                       504

  DAMAGE OPERATIONS (rows carrying each, by split)
    bare_kind_title                133     133 · defines a gold change
    clock_residue_title            126     168
    hold_on_chatter                133     231
    leading_filler                 210     119
    one_word_swap                  105     222
    retraction                     182     189 · defines a gold change
    stated_day_wrong_weekday        70      56
    stt_boundary_shift             168     147 · defines a gold change
    stt_compound_join              196     196 · defines a gold change
    stt_letter_corrupt             112     133 · defines a gold change
    stt_sound_swap                 105     147 · defines a gold change
    stt_syllable_split             119     182 · defines a gold change
    stt_word_mash                  196     140 · defines a gold change
    stutter_repeat                 161     182
    trailing_interjection          147     133
    wake_word_tail                 168     161
    (undamaged speech)             714     847

  VOICES (rows, by split)
    plain                          360     396
    observant_student              360     396
    household_parent               360     396
    freelance_consultant           360     396
    retiree                        360     396
    uni_student                    360     396
    esl_speaker                    360     396

  MUTATIONS (cases, by split) — `expect` is the finding type the defect should
  produce; a dash means TODAY'S TAXONOMY HAS NO NAME for it, which is the
  measurement, not an omission.
    clean                         2347    2628   —
    clock_residue_title            248     264   —
    dropped_ask                    252     261   —
    dropped_date                   254     266   unsupported_field
    dropped_time                   254     264   unsupported_field
    generic_title                  254     266   ungrounded_subject
    invented_title                 254     266   ungrounded_subject
    merged_asks                    252     260   coordinated_subject / unsplit_subject
    near_miss_title                254     266   ungrounded_subject
    subject_dropped_for_kind       254     266   ungrounded_subject
    unrelated_object               254     265   not_an_ask
    wrong_kind                     254     265   —
    wrong_operation                254     265   —

    planted, with a finding type     4000
    planted, BLIND to the taxonomy   2212
    clean (the false-flag pool)      4975

  recogniser damage that still leaves the intended title reachable: 33/1750
```

---

## Regenerating

    # the whole set: ~8 minutes, most of it the converter and spaCy
    python -m assistant.engine.llmjudge.datasets.v2.generate_v2

    # the commands alone, in under three seconds — no engine import at all
    python -m assistant.engine.llmjudge.datasets.v2.generate_v2 --commands-only

    # the commands, then the COMMITTED cases moved with the rulings, not rebuilt
    python -m assistant.engine.llmjudge.datasets.v2.generate_v2 --rule-cases

    # the gate. It REFUSES the set (exit 1) and names what is wrong
    python -m assistant.engine.llmjudge.datasets.v2.verify_v2

    # the invariants, including determinism under the seed
    ./.venv/bin/python -m pytest tests/unit/test_llmjudge_dataset_v2.py

Deterministic under `SEED = 17`: a regeneration is byte-identical, so a `git
diff` on these files means a generator change and nothing else. The generator
redirects every store to a scratch directory and sets
`MACALENDAR_LLM_DISABLED=1`, `MACALENDAR_NO_WARMUP=1` and
`MACALENDAR_LLM_PRIORITY=background` itself — it never touches
`~/.assistant_tools/` and never posts to the live API.

`CLOCK = 2026-09-22 10:00` is a property of the DATA, not of a run: a case
whose plant depends on what resolved is only valid at the moment it was
resolved. **Any board MUST replay this set under that clock** (import it from
`generate_v2`, the way `judge_board.py` imports v1's). It is a Tuesday, which
is deliberate — a family naming "on tuesday" resolves to today, and one naming
"tomorrow … on tuesday" is the cycle-36 conflict.

### The layout

    generate_v2.py   the grammar, the families, the split, the case planting
    banks.py         the invented terms, the day phrases, the clock values
    voices.py        the seven voices and the eleven spoken clock forms
    damage.py        the sixteen named operations, each with its provenance
    mutations.py     the thirteen plants, and `apply()` — the board uses this
    verify_v2.py     the five refusals and the diversity printout
    commands_v2.jsonl   one command per line
    judge_cases_v2.jsonl one case per line

### Row schemas

A command row carries `id`, `family`, `grammar`, `joiner`, `split`, `voice`,
`damage` (the operations that applied), `text` (what the recogniser handed
over), `clean_text` (the undamaged sentence, or null when nothing was done),
`n_asks`, `expect` (events / tasks / action / atomic, FastRule's own schema)
and `asks` — each with its gold fields, its `said` rendering detail and its
`item` (`text` = the action words, `time` = the time reference as spoken,
which is the shape `decompose_validate.resolve_values` reads; an item whose
text swallowed its own time resolves nothing).

A case row carries `id`, `command_id`, `split`, `family`, `grammar`, `joiner`,
`voice`, `damage`, `n_asks`, `text`, `items`, `mutation`, `defect`, `expect`,
`expect_item` and `plant`.

---

## What this set does NOT do

* It is **not a real-usage instrument**. Generated speech with observed damage
  is a stress test; `scripts/weekly_review.py` and the real-usage board remain
  the only measurements of real speech, and they outrank this one.
* It does **not** measure the loop. A finding rewrites the command and
  re-enters segmentation, and only a connected board (Board D) sees what that
  costs or buys. `PLAN.md` §7.3 orders Board D v2 first for exactly this
  reason.
* It does **not** contain a judgement about what the engine should do with a
  clock form it currently misreads. `generate_v2` prints how the engine READ
  each spoken form as a diagnostic beside the counts — on this generation,
  `twentyfour` at 81.0% (914/1,128 asks) and `compact_bare` at 81.8%
  (216/264), everything else at 99–100% — and **the gold is never moved to
  agree with it**. A form the reader loses is a case, not a data defect.
