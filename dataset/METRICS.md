# The metrics — organised by what they measure

_Restructured 2026-09-07. There is no longer one flat list: each COMPONENT is
measured at its own granularity, which is the whole point of stage isolation
— the engine's headline can only say THAT something is wrong; a component
measured on its own says WHAT._

**The pattern is the same everywhere** (Gil's framing): recall = "of the
things that should have happened, how many did", precision = "of what we
did, how much was right" — asked at the level of a classifier decision, a
component's job, an item, or a slot. Three metrics deliberately break that
pattern, each because precision/recall cannot express something we care
about: **harm** (errors are not equal), the **knew-vs-accident split**
(measures the mechanism, not the outcome), and **latency**.

## How a number is presented (Gil, 2026-09-22)

Every reported number carries five things, in this order: **dataset · split
· n · metric · the previous version on the same split.**

- **split** is TRAIN or TEST. The sealed 300 (`dataset/inputs/test_split.json`)
  is the TEST set and is called that; each stage's own corpus has its own
  train/test halves (FastRule 7,200, segmentation 1,549, resolver 2,884,
  judge 1,800). Test rows are never read and never pick the next fix.
- **n** is written as scored/total with the skipped count and why ("785
  cases, 115 skipped: the converter declined"). A rate over fewer than ~50
  rows is a probe, and a false-flag rate quotes its clean denominator.
- **comparison** is one table, both splits side by side, same scorer for
  both versions; a re-scored archive says so.

## Definitions, one line each

| metric | one line | where |
|---|---|---|
| count-correct | the command produced the right NUMBER of events and tasks (raw; product-adjusted applies the conventions layer) | engine |
| item precision / recall / F1 | of created items, how many were asked for / of asked-for items, how many exist / their harmonic mean | engine |
| field quality · when-correct | of matched items, are the fields grounded in the words / is the date and clock right where one was said | engine |
| garbage-title rate | a title that is not a title: furniture word, command frame, cut mid-phrase (a bare kind is not garbage since Q42) | engine |
| handle rate · correct-on-handled | of single-item commands, how many FastRule acted on / of those, how many were right | FastRule |
| harm | wrong commits weighted by cost: delete 4 · update or complete 2 · create 1 · query 0 | FastRule |
| invented a time | events given a clock when the speaker named none | FastRule |
| exact-set · exact-row · time assignment | the right set of asks / the right asks with time and tag / each time phrase on the item it belongs to | segmentation |
| all fields exact · invention · lost phrase | every resolved value right / a value the words do not support / a time phrase that reached no value | decompose_validate |
| catch rate · false-flag rate | of planted defects, how many the judge flagged / of clean objects, how many it complained about — always the pair | LLMJudge |
| corrected, every reachable field | of Gil's corrected commands, rows where every field a parse of the words could reach is right | real usage |
| approved reproduced · rejected changed | commands he accepted that still come out the same / commands he rejected whose answer moved at all | real usage |
| generic-title right or acceptable | the title carries the subject the words held, or is a bare kind where nothing else was said, with the day and clock right | real usage |
| error bar | the move between two runs of the same rows on unchanged code: 0.6 pt on the test 300, 0 on dev-100 back to back, ~2.4 pt on the rejected tier | all |

## Level 1 — the ENGINE (`engine_dataset_compare` → `score_dataset_run`)

| metric | question |
|---|---|
| count-correctness (raw + product-adjusted) | did the command produce the right number of events/tasks? |
| item-level precision / recall / F1 | of expected items, how many exist; of created items, how many were asked for |
| missing-half | on a two-part command that failed, WHICH half vanished |
| date-collapse | did two dated things land on one date |
| garbage titles | a title that is not a title: a leaked connective, a program word ("event", "new list", "note of it"), a command frame the verb left behind ("remind of my dentist appointment"), or a cut that ended mid-phrase ("take out the trash. also") — three readings added 2026-09-20 (cycle 28); before that the test was seven joiner words and read 0% while 29% of the checkpoint's rows carried one |
| field quality / when-correct | are the matched items' contents grounded in what was said |
| label-correctness | category accuracy + macro P/R/F1 (events), tag micro-P/R/F1 (tasks) |
| parse path + latency (p50/p95) | which track answered, and how slowly |

## Level 2 — FASTRULE, the atomic-item executor (`assistant/engine/fastrule/experiments/fastrule_shape.py`)

Measured by what it is FOR, not how busy it is. **Primary** (Gil, Q13):

| metric | question |
|---|---|
| **atomic handle-rate** | of single-item commands, how many did it act on (coverage) |
| **correct-on-handled** | of what it acted on, how much was right (precision) |
| date correctness | of committed creates with a resolvable date phrase, how many landed right |
| time correctness | of committed events with an explicit spoken time, how many matched |
| invention rate | events where NO time was said — did it invent one anyway |
| **harm** | severity-weighted cost of wrong commits: delete=4, update/complete=2, create=1, query=0 — because a wrong delete and a wrong title are not the same failure |

**Diagnostic** (non-atomic rows — the engine decides, so no target):
covered (all asks present, acceptable) · **half-executed** (an ask missing —
the real defect) · deferred, split into "knew it was compound" vs "by
accident", because only the first survives as FastRule improves.

## Level 3 — the CLASSIFIERS (`scripts/fit_route_models.py`, `atomicity_board.py`)

Accuracy + per-class precision/recall/F1 + macro-F1 for atomicity,
operation and kind — reported per dataset, and for atomicity as three
separate predictors (rules alone / model alone / the wired layer), because
that is what revealed the layer scoring worse than the model inside it.
Error COUNTS not just rates: a wrong "compound" costs a slow path, a wrong
"atomic" half-executes a command.

## Level 3b — the KIND decision (`scripts/kind_board.py`)

Added 2026-09-08, because the failure was invisible without it. Segment labels
every item event / task / review and `decompose.run()` branches ENTIRELY on
that label, so one wrong kind costs the decomposition as well. The atomizer
board reported "mis-typed" as a single undirected number — which cannot tell
tasks-read-as-events from the reverse, and the failure turned out to be almost
entirely one direction (task recall 0.341 against event recall 0.978).

Reports, per dataset and split: kind accuracy, per-class precision / recall /
F1 with support, the confusion matrix (errors only), and four slices chosen to
test named mechanisms — non-create to-do operations, daypart-without-clock
rows, create-todo and create-event.

Two things it must keep doing, both learned by getting them wrong:

* **it applies the transcript stage's cleanup before predicting.** Several
  kind regexes are `^`-anchored, so feeding raw dataset text invents misses the
  pipeline never has ("um i need to do the laundry"). Leaving it out moved the
  measured baseline by 3 points and would have sent a cycle after the wrong
  stage.
* **the held-back half prints aggregates only.** Row detail is train-only, by
  the leakage rule.

Scores only rows whose gold `action` names a single kind — "mixed" and
"propose" have no one answer and are excluded rather than guessed at.

## Level 4 — SPEAKERS (`scripts/persona_board.py`)

Per-persona boards plus the SPREAD between best and worst — the spread is
the finding. Plus the vocabulary-vs-phrasing ablation, which showed the
engine is tuned to sentence shapes (7–29 pt) and not to vocabulary (0–3 pt).

## Level 4b — POSITION INVARIANCE (`scripts/invariance_board.py`) — CROSS-STAGE

**The one metric that is not about being right — it is about being the SAME.**
Gil, 2026-09-18: *"a very important part of the project is to make sure that
we're invariant to where the time / title are located in the prompt."*

Every row of the FastRule 7,200 set puts the time at the END — all 1,693
train-half rows carrying a gold `(text, time)` split reconstruct exactly as
`text + " " + time`, and not one is in any other order. So every FastRule
number ever printed is an **end-position** measurement, and no board here
could see a parser that only works when the time comes last.

The variants are built from the dataset's OWN gold decomposition, never from
a span detector — that detector is the thing under test, and using it would
make the instrument circular. Generated at run time, never committed.

| metric | question |
|---|---|
| **position-dependent** | of one row's variants, did the answers DISAGREE — the defect |
| solid | they agree, and they are right |
| consistently wrong | they agree, and they are wrong — an accuracy bug, counted apart so it is never read as a position bug |
| correctness by position | action + title vs gold, per position, control = `end` |
| which field moves | item count / action / date / title — a title that drifts with position is a different repair from a date that does |

**Two questions, never collapsed**: AGREEMENT is variant-vs-variant,
CORRECTNESS is variant-vs-gold. A parser wrong in all three positions is
perfectly invariant, which is why "consistently wrong" has its own column.

**Scored at four boundaries with one set of variants**, so a loss of
invariance is attributed to a STAGE instead of inferred from the end of the
chain: `segmentation` (the WORD PARTITION — which words went to `text`, which
to `time`, compared as words because the order differs by construction) ·
`decompose_validate` (the resolved slots) · `fastrule` (the built object) ·
`front_door` (`FastRule.run()` on the raw utterance — the instant path, which
skips the three stages above).

**`front` and `front,` are separate positions on purpose.** The comma is not
decoration: `"the 30th, wash and fold the laundry"` loses the date entirely
while `"the 30th wash and fold the laundry"` resolves it. Emitting only the
comma form would score a PUNCTUATION bug as a POSITION bug and send the fix
to the wrong stage.

**The TITLE axis (2026-09-19).** Position is where the time sits; the second
question is whether the title's CONTENT moves a value. Measured once as a
probe on decompose_validate — every train time phrase held fixed, the title
swapped through the 85 bank titles plus 30 adversarial ones in nine trigger
classes (evening word, digit, duration, bound word, day word, cadence word,
relative word, lead word, part of day), 169,855 pairs — reporting per field
which moves are DESIGNED (the stage's written couplings) and which are not.
The stage read 0 undesigned; the front door did not (`fastrule/experiments/
RESULTS.md` cycle 24). Not yet a script: the probe's numbers are banked in
`DOCUMENTATION/experiments/invariance/RESULTS.md` run 3, and a `--title` arm
on `scripts/dv_invariance.py` is the shape it takes if it is ever needed again.

## Level 5 — REAL USAGE (`scripts/weekly_review.py`) — the outer gate

Flag rate and accuracy on Gil's actual commands, test traffic excluded.
**This one outranks the others**: it is the only instrument measuring real
speech, and it currently disagrees with them sharply (50% vs an 85%
benchmark). A cycle that moves a benchmark while this stays flat has not
helped anybody.

---


`scripts/score_dataset_run.py` scores a `dummy_<N>.db` (or diffs two of
them) without any hand-written ground truth. That's only possible because of
where the ground truth actually comes from — read that before the metric
list, since it's what decides which of these travel to other data and which
don't.

## Where the ground truth comes from

This dataset has no `expect` field the way `scripts/audit_assistant.py`'s
hand-written corpus does. Instead, every "complex" prompt was *built* by
joining two real utterances of a known kind (`fetch_hwu64_sample.py`,
`_compose_complex`) — event+event, task+task, or event+task. That
construction is itself a claim about what should happen: an event+event
compound should produce at least 2 events, whether or not a human ever
wrote that down. "Simple"/"medium" prompts get a weaker version of the same
idea from their source intent (`set`/`createoradd` should create something;
`query`/`remove` should not create something *instead of* querying or
deleting).

**This means about half of these metrics are dataset-specific — they need
`hwu64_sample.json`'s provenance (scenario/intent/complexity per prompt) to
know what "correct" means — and about half are fully general, computed only
from `actions_json`/timing with no provenance at all.** Marked below. The
general ones are the ones actually reusable once real usage exists to score.

## The metrics

**WHICH NUMBER LEADS** (Gil, 2026-09-20, DEVQA Q35): for a GROUNDING or
TITLE cycle, **field quality and item precision lead and count-correctness
follows**. Count-correctness asks *did you produce at least N things*, so a
fabricated object counts as a success and an honest "I couldn't make out what
to create" counts as a failure — it pays for inventing and charges for
admitting. Two cycles running (28, 29) moved it down while every quality
metric moved up, and the rows that moved were exactly that swap. For a
CUT or COUNT cycle it still leads, because there it measures what it names.

| Metric | Deterministic? | Needs provenance? | What it catches |
|---|---|---|---|
| **Count-correctness** (does a compound produce the right minimum event/task count) | Yes | **Yes** — dataset-only | The core one. Directly targets the multi-date and duplicate-task bugs found earlier this session. |
| **event+task missing-half** (which side gets dropped: event, task, both, neither) | Yes | **Yes** — dataset-only | Finer than pass/fail — tells you *what* to fix. Found: 68% of failures drop the event specifically, not a random mix. |
| **Cross-event date collapse** (2+ events in one command landing on the identical date+time) | Yes | No — general | Would catch the exact bug fixed earlier this session, on ANY input with 2+ events, synthetic or real. |
| **Garbage titles** (a title that is not a title: a leaked connective, a program word, a leftover command frame, a cut that ended mid-phrase) | Yes (proxy, not true quality) | No — general | Real defect, found live on first real row inspected. Widened 2026-09-20 (cycle 28): the seven-word test read 0% on runs that carried 29% — see `dataset/RESULTS.md`. |
| **Parse-path distribution, latency percentiles** | Yes | No — general | Standard operational metrics, sliceable by any grouping available (complexity, parse path, whatever). |
| **Correctness by parse path** | Yes | **Yes** — dataset-only | Needs count-correctness as an input. Found: hybrid underperforms both pure rule and pure LLM paths (57% vs 75%/77%) — worth its own investigation. |
| **Determinism** (same prompt, replayed, same action sequence?) | Yes to compute, but confounded | No — general | Real result: 75% raw, ~85% once context-memory-dependent cases (2 of 5 diffs, isolated replay vs in-sequence) are set aside. Needs replaying at the *same sequence position* to measure cleanly, not in isolation. |
| **Title/description "quality"** | No — no ground truth exists | — | Deliberately not built. Would need an LLM-judge model that isn't the system under test (avoids self-grading bias), and the same "prove it can fail before trusting it" discipline the self-check itself has never fully had. Noted as future work, not attempted here. |

## Findings (full 3000-row build, 2026-09-03)

Report: `output/dummy_3000.score.md`. The partial-build numbers held.

- Count-correct: simple 92%, medium 88%, **complex 29%** — overall 70%.
- event+task compounds are the worst compound kind (17% correct) and the
  failure mode is specific: of 275 failures, 229 dropped the event, 20 the
  task, 26 both — 83% are a dropped *event*.
- event+event is barely better (20% correct), and cross-event date collapse
  is only 4% of those rows — the failure mode is mostly something other
  than the bug already fixed.
- Hybrid parse path is the weakest (58% vs rule 74%, llm 78%) across
  951/1372/677 rows respectively.

One data note: every join in the build and scorer is keyed on
`COALESCE(NULLIF(raw_transcript,''), transcript)` — the verbatim input —
because the pipeline can rewrite a transcript before recording it ("Open
calendar.  Set event." is stored as "Open calendar"), and a text join on
the stored form leaves such rows permanently unmatchable (the build's
resume replayed one forever before this was keyed right).

## Reusing this once something goes to production

The general-purpose metrics (date collapse, garbage titles, latency/parse-
path, determinism) need no changes — point `score_db()` at any db with an
`examples` table shaped like this project's command memory (transcript,
actions_json, parse_path, timing) and they compute the same way, real
traffic or synthetic.

The provenance-dependent ones (count-correctness, missing-half, correctness-
by-path) need a stand-in for `hwu64_sample.json` — i.e., *something* that
says what a given real command should produce. For real production traffic
that doesn't exist by construction the way it does here, so this would mean
either: human-labelled review verdicts (the existing `feedback`/
`correction_json` columns in the real command memory already carry some of
this), or restricting these specific metrics to synthetic/constructed test
traffic the way this dataset already is.


## 6 · Label-correctness (added 2026-09-07, Gil)

On MATCHED items only (an unmatched item is layer-1's failure): **events —
category accuracy + macro precision/recall/F1** over classes (single-label;
macro so a rare category's systematic miss stays visible); **tasks — micro
precision/recall/F1 over tag sets** (multi-label; an expected-empty set
counts). Ground truth exists where labels are by construction — the FastRule
6,000 against its canonical `banks/categories_fixture.json`, loaded via
MACALENDAR_CATEGORIES so personal config never enters scoring. The real pool
carries no label ground truth (hand-labeling it is an open ruling for Gil).
Implemented by the FS1 scorer; reported on FS boards like every metric —
named, sliced, never bare.
