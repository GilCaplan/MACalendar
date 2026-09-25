# FastRule

**`PLAN.md` is the restructure plan (2026-09-09)** — what to change, in what
order, and the rules that keep this folder from becoming convoluted. This file is
how it works today.

**The ATOMIC-ITEM EXECUTOR.** Given one atomic item — a single event or task —
it produces the object, in about 50 ms, with no model. The deep system is the
**ATOMIZER**: it splits until items are atomic and then hands each one back
here. Gil's framing: *"the deep system's main idea is breaking down to atomic
items so the FastRule can then create the right event/task per item."*

FastRule is not a pipeline stage of its own. It is the thing `generate` reaches
for first, and it is the whole of the fast track: when it is confident on a
complete input, its answer commits instantly.

---

## 0 · Where this stage stands (2026-09-10)

**The restructure LANDED.** `objects.py` is gone; the stage is what Gil's box
says it is.

    IN    List[Item]   everything segmentation and decompose_validate worked out
    OUT   the objects the software accepts
    ELSE  a flag — a DEFER for LLMJudge, or "this is not an object" for the user

```
    List[Item] ──► build(item) per item
                     1. COPY item.slots onto the object — all eight values
                     2. read the ACTION WORDS for operation · title ·
                        attendees · target
                     3. one of three results, always:

                          Built        an object, committable
                          Defer        LLMJudge answers it, from the partial
                          NotAnObject  nothing to build — FLAGGED to the user
```

**`build_all` is TOTAL.** Every Item gets a result; nothing falls out of the
list. `NotAnObject` exists because the absence used to be silent: an item
segmentation tagged `other` was set to `intent=None`, and the execute loop
skips an empty intent before it looks at anything else, so the speaker was told
**nothing at all** — indistinguishable from success. Gil, 2026-09-10: *"those
you don't create an object, you can just flag to the user for this item it's not
an object. This in itself can be a type of object."*

**It does not redo what the upstream did.** Six of the ten fields an object
needs were decided before this stage ran. What is genuinely left is the
OPERATION, the TITLE, the PEOPLE and the TARGET, and that is all it reads for.
What that removed:

| removed | why |
|---|---|
| the whole fast track, re-run per item | the item is atomic BY CONTRACT — segmentation already split it |
| the date/time, re-read from `item.spoken()` | `decompose_validate` resolved them; B1 measured it right on **573/573** of the rows this stage was deferring |
| event-vs-task, re-decided | segmentation's `tag` decided it |
| the model, called from here | it lives in `llmjudge/rescue.py` now — and since **B5 (2026-09-10)** this stage does not even CALL it: the DEFER is written onto the item and LLMJudge, already the next stage, picks it up at its own entry. *"If there's an issue it tells LLMVerify"* — a hand-off, not a call |

**This stage no longer calls the model at all — not directly and not
transitively**, which is a checkable fact:
`test_the_count_of_model_calling_stages_is_current` went from five stages to
four, and `stage.py` no longer imports `llmjudge` in any path.

### The score (2026-09-10, `experiments/stage_board.py`, 600 atomic train rows)

**Measured on SOUND INPUT ONLY** — Gil's rule: *"if it receives bad input the
output should be the same; the question then becomes what stage failed and
where, and to flag in the relevant md file."* 104 of the 600 rows arrived
already broken and are attributed upstream, not scored here.

    operation right      95.0%
    title right          67.2%     <- the binding constraint
    correct-on-handled   66.9%
    handled              63.9%     (the converter BUILT 83.5%; the rest is the
                                    commit policy withholding target-taking ops)

---

## 1 · The organizing idea

Every judgement is the same tiered decision — **rules when confident, a tiny
model when they cannot be, DEFER when neither is sure** — applied three times:

```
   text ──► parse ──► Atomicity ──► Gatekeeper ──► Scorer ──► commit
                     (one or many?)  (must this      (confident   or
                                      NOT execute?)   enough?)    DEFER
                                          │
                                          └─ lives in llmjudge/gatekeeper.py
                                             since 2026-09-09; called from here
```

| unit | question | on failure |
|---|---|---|
| **parse** | Normalizer + Router + SlotFiller | — |
| **Atomicity** | one item, or several? | rules **or** model, both unconditional |
| **Gatekeeper** | is this a reading that must not execute as stated? | veto |
| **Scorer** | threshold + missing slots | DEFER |

> **§1 and §2 describe the FRONT DOOR** (`fastrule.py` + `fast_track.py`),
> which is unchanged. They are NOT a description of `build` — the converter has
> no Atomicity test, no Gatekeeper and no Scorer, because an Item arriving at it
> is atomic by contract and the commit decision is the stage's, not its.

**`Gatekeeper` no longer lives in this folder** (2026-09-09, Gil). Its code —
the class, the two store lookups and the three gate regexes — moved to
`llmjudge/gatekeeper.py`, along with the model half of `_parse_item` and its
three guards (`llmjudge/llm_fallback.py`). The step still runs exactly here and
at exactly this point in the order: the port was a MOVE with an import
redirect, and the product-shape board was identical either side of it. What
changes it into prompt CONTEXT rather than a veto is phase B —
`llmjudge/PLAN.md` §1.1, not yet done.

The reason-class contract (`REFUSAL` / `STRUCTURE` / `INCAPACITY` and
`reason_class()`) deliberately stayed: the DEFER is this stage's *product*, and
that is the vocabulary it is written in.

Atomicity answers *only* whether the item is atomic; what routing does about a
compound is `run`'s business. v1 had the two fused, and the fusion cost the
layer half its recall.

---

## 2 · The verdict is a contract, not a suggestion

When FastRule declines, `reason_class()` says what the deep track **owes** it.
This is the part most easily got wrong, and it has been got wrong:

| class | reasons | what the deep track owes |
|---|---|---|
| **REFUSAL** | generic-target, rename-misroute, interrogative-create | A *correct* reading that must not execute as stated. The LLM may **resolve** it (anaphora → a real title); it must **never overturn** it by handing back the same empty target. |
| **STRUCTURE** | the compound gates, list-title | More than one item — split further. (`list-title`, 2026-09-20: one calendar create over three or more listed things; the judge rewrites it one clause per thing.) |
| **INCAPACITY** | below-threshold, missing-slots, skip | The LLM takes over, and receives FastRule's **partial parse** rather than starting cold. |

**REFUSAL was a real bug.** The per-item path re-implemented the commit test
with the gates omitted, and re-committed what the front door had vetoed.

**A deferral never wastes the work.** `state.fastrule_verdict` carries the
reason, its class and the confidence forward, and `segment` uses it as both
evidence and prompt grounding.

**And FastRule is DETERMINISTIC** — a loop-back on unchanged text cannot get a
new answer, so `state.asked_fastrule` sends it straight to the model instead.

---

## 3 · History

This file **is** FastRule. v1 is retired (2026-09-07); its code is at
`retired/fastrule-v1/` and the last commit that ran it is tagged `fastrule-v1`.

The switch was an **identical-behaviour port**: every regex and check came over
unchanged, and a diff harness proved **7,200 / 7,200 verdicts identical** before
v1 was stood down. The deltas the new structure exists *for* — pre-parse
atomicity, split-and-recurse, calibrated Scorer signals, slot-specs-as-data —
land as later measured batches, not as part of the port.

---

## 4 · The dataset — `datasets/`

**8,400 rows** (6,000 train / 2,400 test; the file keeps its historical name `fastrule_7200.jsonl`), generated from the banks in `datasets/banks/`:

| bank | what it holds |
|---|---|
| `complex_patterns.json` | 374 templates (53 of them train-only growth) with `atomic`, item counts, and **named slots** |
| `simple_patterns.json` | single-item shapes |
| `fillers.json` | slot values — invented names only, no personal vocabulary |
| `categories_fixture.json` | category assignment fixture |

Split into halves; **the test half reports aggregates only and never spawns a
hypothesis**, the same rule as the verification corpus.

> These templates turned out to be worth far more than the board they were
> built for. Because they carry `atomic` and *named* slots, they generate
> **exact segment gold by construction** — 1,554 of Segmentation's 1,694 rows
> come from them. See `../segmentation/ARCHITECTURE.md` §4.

---

## 5 · The evaluation — `experiments/`

Scored against its **product shape**, not against a generic accuracy:

> **defer on non-atomic items, create the right event/task otherwise.**

| metric | |
|---|---|
| **atomic handle-rate** | PRIMARY — how often it acts on a single-item command instead of deferring |
| **correct-on-handled** | PRIMARY — of those, how many are right |
| date / time correctness | |
| invention rate | |
| harm | |
| non-atomic diagnostic split | did it defer for the *right* reason |

`experiments/fastrule_shape.py` is the board. `experiments/fast_sandbox.py` is
the deterministic fast lane — seconds, full-set allowed, selective-classifier
scoring, held-out aggregates only.

**Always name the metric with the number.** "handle rate 49.7% → 53.5% on the
7,200 test half (atomic rows) — it now acts on half of the single-item commands
instead of deferring them" is a result; "53.5" is not.

---

## 6 · Layout

```
fastrule/
    ARCHITECTURE.md   this file
    PLAN.md           the four-phase restructure (A port · B build+wire · C measure · D stop)
    stage.py          THE STAGE. X3 -> X4: List[Item] -> objects, flags the rest
    build.py          THE CONVERTER. build(item) -> Built | Defer | NotAnObject
                      pure: no model, no database, no clock of its own
    fast_track.py     THE FRONT DOOR. fast_propose — the whole-command instant
                      commit. Atomicity belongs here, where no Item exists yet
    fastrule.py       the rule engine behind the front door: Atomicity, Scorer,
                      FastRule, and the DEFER contract
    datasets/         8,400 rows + the banks that generate them
    experiments/      RESULTS.md (the run log) · stage_board.py (THE STAGE's
                      board, attributed) · fastrule_shape.py (the FRONT DOOR's
                      board) · fastrule6k.py · fast_sandbox.py · b1_ceiling.py
                      · b3_live_chain.py
    datasets/         8,400 rows, the banks, and generate.py
```

**Two boards, and they measure DIFFERENT BOXES** — do not compare them:

| board | box | |
|---|---|---|
| `stage_board.py` | `List[Item] -> objects` | THE STAGE. Attributes upstream failures instead of scoring them here |
| `fastrule_shape.py` | `FastRule(0.80).run(text)` | the whole-command FRONT DOOR, unchanged by the restructure |

**The generator lives here now** — `datasets/generate.py`, moved 2026-09-10
(phase C0). It had been the one piece of this stage left in `scripts/` after the
per-stage restructure, and that is exactly why it rotted: it still pointed at the
pre-restructure `dataset/fastrule/banks/` and raised `FileNotFoundError`, so **the
7,200 rows could not be rebuilt or extended** — which is precisely what phase C
needs to do. Regenerating from its new home reproduces the committed dataset
**byte-for-byte**, which is how we know the move changed only the address.

    python -m assistant.engine.fastrule.datasets.generate            # generate + verify
    python -m assistant.engine.fastrule.datasets.generate --no-write  # composition table only

`OBJECTS.md` was removed 2026-09-09. It described the retired `generate` stage
under that stage's name, was referenced by nothing, and carried its own
"Status: not yet dug into" — but the reason it had to go rather than be updated
is that one of its two load-bearing claims had become FALSE: it promised "the
raw transcript travels alongside the structured input, so no stage can drift".
X3 deliberately ends the transcript *before* FastRule, precisely so this stage
has nothing left to re-read. Its other claim (every model call is
schema-constrained) survives in `DOCUMENTATION/ENGINE.md`, where the model now
lives.
