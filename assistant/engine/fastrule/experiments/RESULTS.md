# FastRule — the run log

One entry per step. Each states the question BEFORE the run, then actual vs.
expected, then what it means. A score is a pointer, not the point.

**Every number here names three things: the DATASET, the METRIC, and what it
MEANS.** "57.9%" is not a result; "handled 49.7% → 53.5% on the FastRule 7,200
test half (atomic rows) — it now acts on half of the single-item commands
instead of deferring them" is.

## The corpus these numbers are computed over

`assistant/engine/fastrule/datasets/fastrule_7200.jsonl` — **7,200 rows**,
generated from the banks in `datasets/banks/`, gold by construction. Split into
halves; the **test half reports aggregates only and never spawns a hypothesis**.
Mining is train-only. `experiments/fastrule_shape.py` is the primary board.

**Segmentation is frozen (Gil, 2026-09-09), so this is the only usable
instrument** — `scripts/engine_dataset_compare.py` runs the real segmenter and is
dominated by an upstream loss we have agreed not to touch. A whole-engine number
is not evidence about this stage.

---

## Phase A — the port — 2026-09-09 (46f7967)

**Acceptance test: no number moves.** It did not. The product-shape board on the
7,200 train half was byte-identical either side of the port — handled 69.1%,
correct-on-handled 94.2%, deferred 30.9%, dates 91.7%, times 81.1%, invented
4.4%, harm 165/129. That is what separating the move from the restructure buys:
any number that moves in phase B is provably the restructure.

---

## B1 — the converter ceiling — 2026-09-10

**The question (PLAN.md §3).** *"Of the 573 below-threshold deferrals, how many
carry slots the parser failed to read. A number before a refactor. If it is
small, the converter is not the lever and B2 changes shape."*

**Dataset:** FastRule 7,200 **train** half, the 573 atomic rows FastRule defers
with reason `below-threshold` — 58% of all 989 atomic deferrals, the single
largest bucket. **Metric:** of those rows, how many `build()` could construct
correctly, scored piece by piece — operation, title, values.

### The answer: not small. Between 163 and 332 of the 573 rows.

| | rows | of 573 |
|---|---:|---:|
| **buildable — strict** (exact operation, exact title) | **163** | **28.4%** |
| **buildable — strict operation, clean-carve title** | **287** | **50.1%** |
| buildable — family-level operation, substring title | 332 | 57.9% |
| *today, all 573 of these rows DEFER* | 0 | 0.0% |

The three brackets differ only in how forgiving the match is. The middle row is
the defensible one and the reason is a probe limitation worth recording: this
experiment carves the when out of the text with `re.sub` over the gold phrases,
which is a crude stand-in for what segmentation actually hands over, and it
**damages 192 titles while fixing 39**. A clean carve is the real input, so
taking the better of the two title reads brackets it from above; the crude carve
brackets it from below.

### Piece by piece — where the object comes from

| the object needs | on these 573 rows |
|---|---|
| **operation** | route selected **573/573 = 100%**; right (strict) **78.7%**, family-level 90.2% |
| **title** | right (exact) **29.8%**, clean-carve proxy 63.4% |
| **values** — date, time, recurrence | **573/573 = 100%** readable by `decompose_validate.resolve()` |

**The values are 100%.** Every one of the 510 rows carrying a when in gold has
that when resolved correctly by the stage that owns it — while FastRule, reading
the same words, defers. That is PLAN §2's "computed TWICE" claim measured rather
than asserted, and it is the whole argument for the copy.

### The mechanism — why 573 rows sit in this bucket at all

The first cut of this experiment asked the parser for an INTENT and found 93.7%
produced none, which read as a routing collapse. It was not. The parser routes
fine and **withholds the intent when the when is unfilled**:

    rp.analyze("create an event for staff meeting")
        -> conf 0.317, intents [], missing ['date', 'start_time']
    rp.analyze("create an event for staff meeting tomorrow")
        -> conf 1.000, intents ['create_event']

Same sentence, same route, one word of difference. So `below-threshold` is not a
comprehension failure — it is the parser refusing to answer a question that,
after the restructure, **it is no longer being asked**.

**And confidence today is dominated by time-reading.** On the full text these 573
rows spread across the whole confidence range (72 at 0.0, 197 at 0.3, 123 at 0.6,
81 at 0.7). Handed the ask with the when carved off, the distribution collapses
to bimodal — 15 at 0.0, 43 at 0.9, almost nothing between. The mid-range was the
parser's uncertainty **about the time**, which is exactly the signal leaving this
stage. **Consequence for B2/B3: the 0.80 threshold and the Scorer are calibrated
against a signal `build()` will not have**, so neither number carries over. That
is a finding for R2's calibration work, not a detail.

### The title is the binding constraint inside build(), and it fails by time contamination

Operation is at 78.7% strict; title at 29.8%. The failure mode is specific — the
title span swallows the date words the stage should never have been reading:

    "i need to talk to Sage the 3rd about yoga class"   -> title '3rd'
    "book an apointment for flu shot the 21st at 11am"  -> title '21st'
    "create an event for staff meeting the 3rd at 14:00" -> title 'event'
    "block my whole calendar this afternoon for blood test" -> title 'whole calendar'

PLAN §2's "the time is IN THE TITLE" confirmed at scale. It is also the class of
error that copying the slots fixes for free, because the words stop arriving.

Two smaller stops, both real and both already visible in the harm score:

- **wrong operation, 122 rows (21.3%)** — dominated by `mark X as the Y`, read as
  `complete_todo` when the ask is `create_event`. "mark" collides with "mark
  done", and `complete_todo` is a destructive operation the user cannot easily
  undo.
- **kind confusion inside the right family, 66 rows** — the gap between the
  strict 78.7% and the family-level 90.2% is entirely `create_todo` returned for
  `create_event` and back. It is counted as an error here on purpose; the kind
  decision has its own board because it is an error the user sees.

### What it means, and what it decides

**B2 proceeds as written.** The decision rule in PLAN §3 was "if it is small, the
converter is not the lever" — half the largest deferral bucket is not small, and
the values arriving free at 100% is the strongest single number in this run.

**But the win does not come from the copy alone.** Copying values into an object
that has the wrong title is not a rescue, and the title is at 29.8%. So B2 is two
pieces of work, in this order: copy the eight values (mechanical, and it removes
the time contamination that causes much of the title damage), then read the title
from the action words alone. Expect the second to be where the rows actually move.

**Registered for B2:** on these same 573 rows, `build()` should construct a
correct object for **at least 163 (28.4%)** — the strict floor measured with a
damaged carve — and the primary board's atomic handle-rate should rise from
69.1% train. Reported against the same bracket, so the comparison is honest.

---

## B2 — `build()` exists, and writing its tests found two defects — 2026-09-10

**The step (PLAN.md §3).** *"`build(item, *, today)` — COPY all eight slots,
parse only operation / title / attendees / target. Unit-tested ALONE, not yet
wired."*

`assistant/engine/fastrule/build.py`, 32 tests in
`tests/unit/test_fastrule_build.py`, **nothing in the engine points at it yet** —
that is B3. B2 and B3 are separate on purpose: `build()` is a pure function of
`(Item, today)`, so it can be proven from a table before anything calls it, and
a failure afterwards can only be the wiring.

**No number moved, and none should have.** 1349 unit tests pass; the product-
shape board is untouched because the stage still runs its old path. The four
remaining reds are `explorer.html`, deferred by Gil.

### The two defects, both found by a test rather than by reading

**1 · The copy has to go INTO the constructor, or events end before they begin.**
`CalendarIntent.fill_defaults` is a pydantic `model_validator(mode="after")`: the
moment the object exists it stamps `date = today`, `start_time = <the current
hour>`, and `end_time = start + 1h`. So the obvious shape — construct the object,
then assign the copied values — is wrong in a way that is invisible until you look
at the third field:

    CalendarIntent(title="gym")        -> date=today, start=07:00, end=08:00
    intent.start_time = "11:00"        -> start=11:00, end=08:00   <- three hours
                                                                      BEFORE it starts

`end_time` was derived from a default start that no longer exists. Handing the
values to the constructor instead lets the validators derive from the truth.

**2 · The predecessor's quantity copy has never fired.** `_apply_slots` guards it
with `hasattr(item.intent, "quantity")` — and the field on `CreateTodoIntent` is
`quantities`. The attribute does not exist, so the branch is False on every row it
could ever run on. PLAN §2b credits the old eleven-line function with copying *two
of eight* values; it was really copying **one** (`reminder_minutes`, whose
`hasattr` does hold).

`quantity` also turns out to be the one value that must land **after**
construction, for the opposite reason to the first defect:
`CreateTodoIntent.fold_quantities` recomputes `quantities` from the TITLES
unconditionally — *"filled by the validator below, never by the model"* — so a
count passed to the constructor is discarded on the way in. It has to be written
over the validator's answer, not through it.

### A third finding, recorded rather than fixed

**`fill_defaults` is where the board's "INVENTED a time" rows are actually made.**
An item with no when at all still comes out dated today at the current hour — not
because any regex guessed, but because the intent class fills itself in. That is
shared with every other producer of these objects (the LLM path included), so
changing it would move numbers across the whole engine and is not this stage's
call. It is named here so the next person reading `INVENTED a time 4.4%` looks in
the right place. `test_an_empty_slot_is_not_copied_over_nothing` pins the real
division of responsibility rather than a purity this stage does not have.

### Two decisions inside `build()` that B1 paid for

- **Segmentation's `kind` beats the parser's route** on event-vs-task. B1 measured
  66 rows of `create_todo`/`create_event` confusion — the whole gap between the
  strict 78.7% operation accuracy and the family-level 90.2%. The upstream tag was
  read from more evidence and this stage has no better information.
- **`complete` has no event form.** When the verb says complete and the kind says
  event, the kind wins and the operation falls back to update. This is B1's
  `mark X as the Y` collision: 122 wrong-operation rows, dominated by that shape
  routing to `complete_todo` when the ask was `create_event` — on a destructive
  operation the user cannot easily undo.

**Registered for B3:** the wiring's acceptance test is the shape at every
boundary, not a score — `test_engine_contracts.py`, `test_engine_flow.py`,
`test_panel_agreement.py`, and `scripts/engine_pipeline_check.py`. The board is
re-run after it, and against B1's floor: **at least 163 of the 573** (28.4%).

---

## B3 — wired into the engine, and it is load-bearing — 2026-09-10

**The step (PLAN.md §3).** *"WIRE IT INTO THE ENGINE — the five touch-points.
'Once initial working implementation is done, fix wiring to the engine.' A
converter nothing calls is not a working stage."*

**B3's acceptance test is the wiring's own, not a score**, and it passes:
`test_engine_contracts.py`, `test_engine_flow.py`, `test_panel_agreement.py`
green, and `scripts/engine_pipeline_check.py` reports *"every stage boundary
matched its contract"*. 1350 unit tests pass. **The front-door product-shape
board is byte-identical** — handled 69.1%, correct-on-handled 94.2%, harm
165/129 — which is exactly right: `build()` is wired into the PER-ITEM path,
and that board measures the whole-command fast track.

### Is it actually doing anything? 600 atomic train rows through the real chain

`experiments/b3_live_chain.py` — segmentation → decompose_validate → `build()`,
no LLM anywhere in the path. Not phase C's board; this answers one question,
because a converter that defers everything is wired but not working.

| | | |
|---|---:|---|
| **BUILT** | **83.5%** | 501 of 600 |
| deferred | 16.5% | 99 — kind-conflict 46, skip 27, generic-title 14, generic-target 12 |
| of those built — **operation right** | **90.8%** | |
| of those built — **title right** | **55.5%** | |
| both | 54.3% | |

**And the values are finally being copied.** Per built row: `date` 90.8%,
`start_time` 36.1%, `recurrence` 12.4%, `end_time` 8.6%, `recur_days` 4.0%,
`recur_until` 3.2%, `reminder_minutes` 2.0%, `quantity` 1.4%. All eight, from
`item.slots`. The predecessor copied one (B2 — the other of its two branches
could never fire).

**B1's prediction holds exactly.** The title is the binding constraint — 55.5%
against 90.8% for the operation — which is what B1 said the rows would turn on,
and it is where the next batch goes. The failure classes are legible:

    "book workshop with Morgan for next monday"   -> title 'morgan'
    "schedule conference call with Jesse tomorrow" -> title 'jesse'
    "reschedule the call with Casey and Emerson"  -> title 'casey'
    "i finished water the garden"                 -> title 'water'

The first three are one class: **`with <name>` hands back the attendee as the
title.** That is a rule, not a long tail.

### The measurement trap this run walked into first

The first pass reported **build 0.0%, deferred 100%, every reason `skip`** — a
convincing-looking disaster. It was the instrument. `fastrule_shape.py` carries
the line `fr.run(...)  # warm outside the frozen clock`; this harness did not,
so spaCy's pipeline was first built *under* `freeze_time`, `analyze()` raised,
and `build()` turned that into a `skip` DEFER. **A stage that converts an
infrastructure failure into its ordinary "I couldn't read this" answer reads as
a model result.** Recorded because the same shape will recur: the harness now
warms the parser first, and says why.

### Two defects the wiring exposed, and the rule that came out of them

Wiring `build()` in front of the tuned path turned two tests red immediately —
which is what B2/B3 being separate steps is for.

1. **`build()` read `title` and `titles` but not `match_title`.** Every
   target-taking operation carries its target in that third field, so
   `"set a reminder note for three o'clock"` fell through to the fallback and
   made the WHOLE UTTERANCE the target — an update aimed at a record called
   *"a reminder note for three o'clock"*.
2. **Re-kinding a target-taking operation invents a target.**
   `"set reminder for three o'clock"` routes to `update_todo`; `item.kind` says
   event; the first cut dutifully produced `update_event` aimed at a record
   called *"three o'clock"*.

**The rule that resolves it: `item.kind` may re-kind a CREATE or a QUERY, never
an UPDATE, DELETE or COMPLETE.** A create needs a title, so moving it between
the calendar and the task list changes only where the new record lands. A
target-taking operation names an EXISTING record, and the kind decides which
STORE is searched for it — a different, destructive action. When the route's
store and the kind disagree there is no way to choose, so it DEFERs with a new
reason, **`kind-conflict`** (an INCAPACITY: nothing is wrong with the reading,
there are simply two of them). It is 46 of the 99 deferrals — the largest
bucket, and it is doing real work: `"can you mark tomorrow as my birthday"` is
B1's destructive `mark X as the Y` shape, now refused instead of completing
somebody's todo.

### One restriction, deliberately at the wiring rather than in `build()`

`objects.run` accepts a `Built` **only for creates and queries**; everything
else falls through to the existing path. Knowing whether a target names a real
record needs a store lookup, and `build()` is pure by design —
`_names_something_real` left with Gatekeeper in phase A. Committing one
unchecked is the expensive direction: the board weights a wrong delete at 4 and
a wrong update or complete at 2, against 1 for a create.

It lives at the wiring because **PLAN §2c says a commit decision is not
`build()`'s job**. `build()` can construct all nine actions and is unit-tested
doing so; what the stage will COMMIT is a separate question with a separate
owner. Phase C's board decides whether to lift it.

**Registered for phase C:** C0 first — the dataset generator is still broken
(`FileNotFoundError`, pre-restructure paths), and nothing else in C can happen
until it runs. Then the title batch: `with <name>` is the single largest legible
class in the 44.5% of built rows whose title is wrong.

---

## The title batch — two hypotheses, both REFUTED — 2026-09-10

B1 and B3 both named the title as the binding constraint (55.5% right on built
rows, against 90.8% for the operation), so this batch went after it. **Neither
idea survived contact with the data, and the refutations are the result** —
they redirect the work rather than costing a cycle.

**Dataset:** 1,083 atomic TRAIN rows where `build()` picked a route, through the
real chain. **Metric:** exact title match against the gold title.

### Where the title actually goes wrong (993 built rows)

| class | rows | of built |
|---|---:|---:|
| **TRUNCATED** — a fragment of the real title | 228 | 23.0% |
| unrelated span | 108 | 10.9% |
| OVERLONG — extra words kept | 70 | 7.0% |
| attendee stolen (`with <name>`) | 19 | 1.9% |
| time words in the title | 5 | 0.5% |
| empty | 3 | 0.3% |

Truncation dominates, and it has one shape: **the parser drops the task's own
leading verb.** `"pay the electricity bill"` → `'electricity bill'`,
`"water the garden"` → `'water'`, `"sort and file the paperwork"` →
`'paperwork'`.

### Hypothesis 1 — read the title in-stage instead. REFUTED.

PLAN §2d assigns the title to this stage, and the truncation above is the
parser's span failing, so reading it from the action words ourselves should win.

    title from the PARSER's span     47.8%   <- today
    title read IN-STAGE from words   30.7%   <- the proposal
    either would be right            56.6%   <- the ceiling of choosing well

**Switching wholesale would cost 17 points.** The parser is better than a
verb-stripper at nearly everything; it is worse at exactly one thing.

### Hypothesis 2 — choose by operation. REFUTED.

The two sources fail in complementary ways, and the complementarity *looked*
like it tracked the operation: in-stage wins on plain creates the parser
truncates (`"gotta talk to Alex"` → parser `'alex'`, in-stage
`'talk to alex'`), the parser wins where an operative wrapper survives
stripping (`"extend open house by an hour"`, `"add restock the pantry to my
todo list"`, `"rename flu shot to sales call"`). So: in-stage for a CREATE, the
parser's span otherwise.

    the rule            43.8%      parser alone   47.8%

**Also worse.** The per-operation board says why — the parser beats in-stage
*within every operation*, creates included:

| | n | parser | in-stage |
|---|---:|---:|---:|
| create | 744 | **49.6%** | 43.7% |
| update | 138 | **50.7%** | 4.3% |
| delete | 119 | **47.9%** | 0.8% |
| complete | 79 | **27.8%** | 0.0% |

The complementarity is real but it is not the operation; the operation was a
confound.

### What the two refutations actually establish

**The title gap is not a source-choice problem.** A PERFECT chooser between the
two available sources reaches 56.6% against 47.8% — about nine points, and
`build()` already banks part of that by falling back when the parser's span is
empty. **Both sources are wrong on 43.4% of rows**, and that is the number that
matters: there is no cheap rearrangement of what we already have.

Two of the "neither" rows show the shape of what is left:

    "block my whole calendar today for town hall"  want 'town hall'
        parser 'whole calendar'   in-stage 'my whole calendar for town hall'
    "remind me to return the rental car tommorow"  want 'return the rental car'
        parser 'return the rental car tomorrow'    in-stage '...tommorow'

The first needs a `for <X>` reading neither source attempts. The second is
upstream: segmentation left the MISSPELLED time word in the action words, so
both sources inherit it — and segmentation is frozen.

**So the title needs its own instrument before it needs another rule**, which is
what phase C is for. Per CLAUDE.md: say so plainly rather than grinding a third
variant of a refuted idea.

**Next: C0 — the dataset generator is broken** (`FileNotFoundError` on
pre-restructure paths) and blocks every other step in phase C.

---

## C0 + C2 — the generator runs again, and reproduces the dataset exactly — 2026-09-10

**The blocker (PLAN.md §3).** *"C0 — FIX THE GENERATOR, it is broken today.
Blocker for everything below."* Phase C rebuilds this stage's dataset and
boards; none of it is possible while the dataset cannot be rebuilt.

`scripts/gen_fastrule_dataset.py` still pointed at the pre-restructure
`dataset/fastrule/banks/`, so it raised `FileNotFoundError` on its first bank
load. **Its own docstring already named the new paths** — the prose was updated
in the restructure and the code was not, which is why reading it did not reveal
the bug and running it did.

Moved to `assistant/engine/fastrule/datasets/generate.py`, matching
`decompose_validate/datasets/generate.py`. The two scripts that import its slot
machinery — `gen_personas.py`, `gen_realspeech.py` — follow it.

**C2's assertion passes:**

    before   md5 c387bb6de818f7f36ca9f9f6b2628e82
    after    md5 c387bb6de818f7f36ca9f9f6b2628e82      IDENTICAL

Regeneration reproduces the committed 7,200 rows byte-for-byte, so the move
changed only the address — no row content, no split assignment. C2 gets
re-asserted after C1 adds the gold `item` field, where it does the job it was
actually written for: proving the new field is ADDITIVE, or the train/test split
is void.

**Why it rotted, which is the part worth keeping.** This was the **fourth**
instance of the class CLAUDE.md names, after segmentation's generator, FastRule's
primary board and `fit_route_models.py` — and it survived a sweep that fixed the
other three. The distinguishing feature is not subtle: **it was the only one
still living in `scripts/` rather than in the stage folder that owns it.** All
four are manual steps whose OUTPUT is committed, so a stale `.jsonl` keeps
working and nothing goes red. Moving it is therefore the only one of the four
repairs that also stops it recurring, and CLAUDE.md now says so.

**Next: C1** — teach the generator to emit a gold `item` per row, so the board
can feed `build(item)`. The non-circular route is the generator's own templates:
it composed the sentence from named slots, so it knows which words are the action
and which are the time without any stage's implementation in the path.

---

## THE RESTRUCTURE LANDED — and the stage got its own board — 2026-09-10

Gil: *"if the core structure of FastRule isn't good then fix it. The idea: input
is `List[Item]` and output is objects committable to the software"* … *"it also
shouldn't be redoing what previous components did, it should be focused on its
own task and do that well."*

`objects.py` is gone. It was four things at once and only one of them was the
stage:

| what it was | where it went |
|---|---|
| the per-item loop | `fastrule/stage.py` — **the stage** |
| the whole-command front door | `fastrule/fast_track.py` |
| the LLM fallback + both kind fallbacks | `llmjudge/rescue.py` |
| the registry + both parser accessors | `engine/llm.py` (where a duplicate `_get_parser` already lived — two caches of one object, one reset by `reset()` and one not) |

**The redo is gone.** `_parse_item` re-ran the ENTIRE fast track per item —
Atomicity, Gatekeeper, Scorer — on an item that is atomic by contract, then
handed the model `item.spoken()`, the action words **with the time re-injected**,
so the same date was derived three times in one chain. Now `build` copies the
eight values `decompose_validate` resolved and reads only the four things nobody
upstream decided: operation, title, people, target.

**Checkable consequence:** `test_the_count_of_model_calling_stages_is_current`
went **5 → 4**. This stage is deterministic end to end.

### The new board, and the rule it is built on

`experiments/stage_board.py`. Gil: *"if it receives bad input then the output
should be the same — the question then becomes what stage failed and where, and
to flag in the relevant md file to go fix there."*

So **every row is audited BEFORE the stage runs** and failures are attributed.
Scoring an upstream loss here is the expensive mistake: it makes this stage
chase problems that happened before it ran, and hides the stage that failed.

**600 atomic TRAIN rows · converter lane (no model) · sound input only:**

| | before the title batch | after |
|---|---:|---:|
| operation right | 95.0% | **95.0%** |
| **title right** | 60.9% | **67.2%** |
| correct-on-handled | 60.6% | **66.9%** |
| handled | 63.9% | 63.9% |

The converter BUILT an object for **83.5%** of rows; the gap to `handled`
(63.9%) is the commit policy withholding 115 target-taking operations that need
a store check this stage cannot do. Those go to the model.

**104 of 600 rows arrived already broken** — flagged, not scored:

    39  segmentation: split an atomic row into 2 items
    20  segmentation: tagged 'event', gold is 'task'
    17  segmentation: tagged 'task', gold is 'event'
     6  segmentation: the action words lost a word

### The title batch — REGISTERED, then measured

Earlier two title hypotheses were refuted (reading it in-stage: −17pt; choosing
by operation: −4pt). This one was different because it was mined first.

**Prediction:** title 60.9% → 64–68% on sound input, driven by the
attendee-as-title class; operation unchanged. **Actual: 67.2%, operation 95.0%.**
Inside the range.

**What it was.** The parser returns a bare attendee name as the title on **142 of
the 244** train rows containing `with <Name>`: `"book workshop with Morgan"` →
titled `'morgan'`. A name is never the title of the event that person attends.

**And whether the `with` phrase belongs in the title is settled by the corpus,
not guessed:**

    KEEP it   137 rows   head is an INTERACTION — meeting · call · catch up ·
                         speak · touch base    ("a call with Jesse")
    DROP it   107 rows   head is an event someone attends — workshop, job
                         interview, sales call, moving day

Note the match is on the **whole head**, not a substring: `call` keeps and
`sales call` drops, and treating them alike gets one of the two wrong.

**One word was worth most of a percentage point on its own.** `"a call with
Jesse"` failed the gold `"call with Jesse"` on the leading article, with the rest
of the title already correct. `_LEAD_ARTICLE` strips it. The first cut of this
batch moved the board **+0.3pt** and looked like another refutation; it was the
article, and reading the rows rather than the number is what found it.

### The front door is untouched

`fastrule_shape.py` on the 7,200 train half is **byte-identical** across the
whole restructure — handled 69.1%, correct-on-handled 94.2%, harm 165/129. It
measures a different box (`FastRule(0.80).run(text)`), and the `fast_track` move
was code motion. **Do not compare the two boards.**

### `NotAnObject` — a flag is an outcome

Gil: *"those you don't create an object, you can just flag to the user for this
item it's not an object. This in itself can be a type of object."*

`build_all` is now TOTAL — every Item gets one of three results, and
`NotAnObject` is the third. It exists because the absence was **silent**: an item
segmentation tagged `other` got `intent=None`, and `_commit` skips an empty
intent before it looks at anything else, so the speaker was told nothing at all —
indistinguishable from success. It now lands on `item.blocked` and comes back as
*"I left 'X' alone — …"*.

**The client half is NOT done and is recorded in `DOCUMENTATION/TASKS.md`**: the
thinking panel and the iOS timeline should SHOW a flagged item, and currently
have no place to draw it.

**Next:** title 67.2% is still the binding constraint — the remaining classes are
truncation (the parser dropping a task's own leading verb) and segmentation
leaving stray words in the action. And the 115 withheld target-taking builds are
the largest single block of unrealised reach; lifting that needs the store check,
which is LLMJudge's.

---

## Title batch 2 — the container rule, and two measured guesses — 2026-09-10

Same lane as before: 1,200 atomic TRAIN rows, converter only, **sound input
only** (1,018 of 1,200; the other 182 are attributed upstream).

| | start of session | batch 1 | **batch 2** |
|---|---:|---:|---:|
| operation right | 95.0% | 95.5% | **95.5%** |
| **title right** | 60.9% | 67.2% | **69.7%** |
| correct-on-handled | 60.6% | 67.1% | **69.6%** |
| handled | 63.9% | 63.9% | 63.9% |

**Nine points of correctness on the same number of objects.** `handled` is flat
by design — this batch fixed titles and refused inventions in equal measure, and
the pair is reported together precisely so that trade is visible.

### The container rule — the attendee rule's twin

`"create an event for staff meeting"` came back titled `'event'`; `"put a marker
on for the release date"` titled `'marker'`; `"block my whole calendar for blood
test"` titled `'whole calendar'`. In every case the sentence names **the kind of
entry** and then says what it is **for**. 71 train rows are shaped this way.

Both this and the attendee case are the same defect — *a title that names the
container rather than the contents* — and both previously ended as a
`generic-title` DEFER, so fixing them turns a refusal into a correct object
rather than trading one error for another.

### Two guesses, both caught by measuring instead of asserting

**1 · The article strip was too broad, and would have broken 130 rows.**
Batch 1 stripped a leading `a|an|the`. Reading the corpus instead of the rule:

    gold titles starting "a" or "an"        0 of 6,216
    gold titles starting "the"/"my"/"our"   177

So `"the release date"` and `"my whole day"` ARE the titles. Narrowed to `a|an`.
Stripping "the" reads as tidier and is simply wrong here.

**2 · The container rule invented an event, and a test caught it.**
`"can you set an event for me"` has a `for` tail, so the first cut titled the
event `'me'` and built it — exactly the invention
`test_no_grounded_when_stays_unknown` exists to prevent ("a literal ask with no
grounded when stays unknown; a guessed event is worse than none"). Pronouns now
name nothing, alongside the container nouns.

That fix **lowered `handled` 65.1% → 63.9% and raised correct-on-handled 68.3% →
69.6%** — twelve fewer answers, all of them better. That is the direction the
pair is supposed to move when a guess is removed, and it is why neither number
is reported alone.

### THE FULL STAGE, with the model — the rescue wiring verified

`stage_board.py --llm`, **60 rows only** (each deferral is a live model call, so
this is an indicative check that the wiring works, NOT a board):

    HANDLED               94.3%   (converter-only lane: 63.9%)
    correct-on-handled    62.0%
    who produced it       converter 32 rows (65.6% right)
                          rescue    18 rows (55.6% right)

**The rescue path works end to end against a live model**, and it lifts handled
from 63.9% to 94.3% by picking up the target-taking operations the commit policy
withholds. Two caveats, both load-bearing: n = 53 sound rows is far too small to
rank the two producers, and the converter being *ahead* of the model here
(65.6 vs 55.6) is interesting rather than established. A proper --llm board is
worth running once the title work stops moving.

**Next:** title 69.7% is still the constraint. The remaining class is
truncation — the parser dropping a task's own leading verb (`"pay the electricity
bill"` → `'electricity bill'`, `"water the garden"` → `'water'`) — which the
earlier A/B says cannot be fixed by preferring the in-stage read wholesale, so it
needs the same treatment this batch got: mine the shape first, then rule.

---

## PHASE D — where FastRule actually stands, 2026-09-10

The plan's phase D is *"stop and report to Gil"*, and this is the report. **The
decision is Gil's**; this is the state it would be made on.

### Structure — done, with ONE item open that is not ours to close

| | |
|---|---|
| ✅ A · port · B1 ceiling · B2 `build()` · B3 wire · B4 `fast_track` · B6 delete `objects.py` | |
| ✅ C0 generator · C1 gold items · C2 byte-identity · C3 the stage board | |
| ⬜ **B5 — the back-edge** | `stage.py` calls `llmjudge.rescue`, so the stage still reaches the model transitively. **It can only be closed from the LLMJudge side**: `llmjudge` already runs AFTER `fastrule` in the chain, so the fix is for DEFERs to ride `state` and LLMJudge's own `run` to consume them. |
| 🔄 **C4 — iterate** | three batches run; title is still the constraint |

The box is what Gil specified: `List[Item]` in, objects out, three output kinds
(`Built` · `BadItem` · `NotAnObject`), no re-deriving of what the upstream
decided, and a pure converter with no model, no database and no clock.

### The numbers, isolated — 1,200 atomic TRAIN rows, gold items, no model

    operation right      96.1%     <- this part is good
    title right          62.9%     <- this part is not
    correct-on-handled   62.8%
    handled              64.1%

**These are the honest ones.** The chain lane reads ~7 points higher on "sound
input" because that filter is biased — the rows segmentation gets right are the
easier rows. Everything before 2026-09-10 in this file that quotes a
sound-input number is measuring through a frozen upstream and reads high.

### What is left on FastRule, and why two of the three are LLMJudge's

1. **The title, 62.9%** — genuinely ours, and the only one of the three that is.
   The remaining class is truncation (the parser dropping a task's own leading
   verb: `"pay the electricity bill"` → `'electricity bill'`). The A/B already
   refuted fixing it by preferring the in-stage read wholesale, so it needs the
   same treatment the last two batches got: mine the shape, then rule.
2. **The 18% of rows built but WITHHELD** — target-taking operations the commit
   policy refuses because verifying the target needs a store lookup this stage
   deliberately cannot do. That is the single largest block of unrealised reach,
   and **only LLMJudge can unlock it** (`_names_something_real` went there in
   phase A).
3. **The rescue's own quality** — on the one live-model sample (n=60,
   indicative) the converter was right on 65.6% of what it produced and the
   rescue on 55.6%. If that holds at size, the model half is now the weaker
   half, and it is LLMJudge's.

### The read

**Two of the three biggest remaining wins are on the other side of the
boundary**, and the one structural item still open (B5) cannot be closed from
here at all. FastRule's own remaining work is one metric — the title — which has
already had three batches and is into diminishing, mine-first territory.

So the honest recommendation is **yes, move to LLMJudge**, with the title batch
left registered rather than abandoned: it is a real 62.9%, it is this stage's
own, and it should be picked up again once LLMJudge's phase reaches a boundary.

---

## Cycle 20 — the BARE ordinal date (2026-09-17)

**Hypothesis registered before the change:** `_extract_temporal` has no
fallback for a bare `"the Nth"`, so `create_todo`/`create_event` rows carrying
one reach FastRule with no date, fall under `RULE_THRESHOLD` on a missing
slot, and defer. Predicted: **handle-rate up ~3.7 pt at the ceiling, date
correctness up, invented-time and harm flat.**

### How the slice was sized first (step 0)

The recogniser was asked what it actually returns, rather than a phrase list
being written by hand. It resolves `"ON the 15th"` and returns **nothing at
all** for the bare form — so this was never a mis-resolution, it was an absent
one. On the FastRule 7,200 **train half** (leakage rule: the sealed half was
not read):

    atomic date-bearing write rows with a bare "the Nth" and NO date   174
       FastRule handled them anyway                                     57  (32.8%)
       FastRule DEFERRED                                               117  (67.2%)
          below-threshold                                              102
          skip / generic-target / model-compound                        15
    ceiling if every deferral flipped                             +3.7 pt

439 train rows contain a bare `"the Nth"` and **every one of them has a gold
`date_phrase`** — so inside this corpus there is no false-positive risk at all.
The verification pool, which is real English, is where the two counter-shapes
came from, and both are now excluded by the pattern rather than by luck:

    "Remove the 2nd row from the list"        an ordinal POSITION, not a day
    "the 15th of every month"                 a RECURRENCE; one day loses the series

### Result — FastRule product-shape board, TRAIN half, 3,200 atomic rows

| metric | before | after | |
|---|---|---|---|
| **handled (atomic)** | 68.2% | **70.4%** | **+2.2 pt** |
| **correct-on-handled** | 94.1% | **94.2%** | +0.1 |
| resolvable date right | 91.3% (n=543) | **93.0% (n=643)** | +1.7 pt, **n +100** |
| invented a time | 4.5% (n=287) | 4.2% (n=306) | −0.3 |
| below-threshold deferrals | 581 | **501** | −80 |
| harm score | 168 / 129 wrong | 170 / 131 wrong | **+2** |
| DESTRUCTIVE errors | 16·11·5·1 | **16·11·5·1** | **unchanged** |
| non-atomic HALF-EXECUTED | 72 (5.1%) | **72 (5.1%)** | **unchanged** |
| propose defer rate | 52.2% (96 viol) | 51.2% (98 viol) | −1.0 pt |

**What it means.** FastRule now acts on 70.4% of single-item commands instead
of 68.2% — 80 rows that used to be handed to the ~40 s deep track (measured at
65.3% correct on the sealed 300, against the fast path's 93.1%) are now
committed deterministically. **The part that matters more than the headline is
the date metric's DENOMINATOR**: 100 more rows now carry a date the board can
score at all, and accuracy over that larger population went UP (91.3% → 93.0%),
so the newly-committed rows are not being bought with wrong dates.

**Actual vs. expected:** +2.2 pt against a +3.7 pt ceiling. The gap is the 15
rows deferred for `skip`/`generic-target`/`model-compound` — reasons the date
was never going to fix — plus rows that cleared the threshold and then failed
on something else. Predicted direction on every metric; the magnitude came in
at 59% of ceiling, which is the honest read of a ceiling computed by assuming
every deferral flips.

**The cost, stated plainly:** 2 more wrong commits and 2 more `propose`
violations (an interrogative create that should have deferred now clears the
threshold). Both are in the `create` severity bucket — a spurious row, easily
removed. **Zero new destructive errors and half-executed unchanged**, which
were the two guards this change had to clear.

### Next prediction (registered now, per "a cycle ends by starting the next")

**The `daterange` branch — BLOCKED on one ruling, see TASKS.md.**
`_extract_temporal` handles the timex types `datetime`, `date`, `time` and
`timerange` and has **no `daterange` branch**, so `"next week"`, `"this
weekend"`, `"in two weeks"`, `"next month"` and `"by friday"` are dropped the
same way the bare ordinal was. Measured the same way, train half: **605 rows
(12.6%) would be newly reached**, of which **263 are one-off atomic writes**
(ceiling **+6.3 pt** on handle-rate — larger than this cycle's), 50 are
recurrence boundaries (`until`/`through`, where the date belongs in
`date_phrase_2` + `end_inclusive`, NOT the item's own date), 86 are recurring,
70 are queries wanting a span rather than a date, and 171 are non-atomic and
must keep deferring.

**Why it cannot start yet:** this board's date scorer *deliberately excludes*
range phrases — `_phrase_to_date` returns None for them, documented as "no
single right answer". So the instrument cannot see whether a newly-committed
`"next week"` row got the right date, and committing one requires PICKING that
answer, which is a product ruling of the same kind as Q14 and until/through.
Making the fix before the ruling would move handle-rate blind and could buy it
with wrong dates. Recommended default, consistent with two rulings already in
the project (a weekly series starts on the soonest weekday the sentence names;
"until the end of September" is inclusive): **the soonest day in the named
range** — the recogniser's `start` bound.

---

## Cycle 21 — the `daterange` branch, under Gil's "ask, don't guess" ruling (2026-09-17)

**The ruling came first, and it changed the design.** Cycle 20 left this
registered but BLOCKED, because committing `"book yoga class next week"`
requires picking which day a span means. Asked, Gil chose **ask instead of
guessing**: read the day, then OFFER it. So this cycle is not the fix the
previous entry predicted, and its primary metric is not the one that entry
named — recorded here rather than quietly re-scoped.

### What shipped

- `_extract_temporal` reads `daterange` (soonest day in the span; the LAST day
  after `by`/`before`/`no later than`, which name a deadline). An exact date
  anywhere in the span still wins — candidates are applied only after the
  recogniser loop, never inside it.
- **`"in two weeks"` turned out NOT to be a range problem.** The recogniser
  returns it as a `daterange` whose start is badly wrong for the everyday
  reading — `"in a week"` came back as **TOMORROW**, `"in two months"` as one
  month out. Those are durations, so they are arithmetic now. Had the range
  branch simply been trusted, this cycle would have shipped a confidently
  wrong date on a common phrase.
- A **create** is offered via the existing `confirm_create` gate (DEVQA Q9),
  from the fast parse, **with no model call** — milliseconds, not the ~40 s a
  deep-track walk would have cost to ask the same question.
- An **update or delete** with a range date does not execute at all: new
  refusal reason `range-date-target`, classed REFUSAL.

**20 hand-built relative-date phrasings** (mine, a shape not a score): 9/20 →
**19/20** carrying a correct date, rows with no date at all **11 → 1**.

### Result — FastRule product-shape board, TRAIN half, 3,200 atomic rows

Read the two columns as one arc; cycle 20 is the middle one.

| metric | baseline | +ordinal | **+daterange** |
|---|---|---|---|
| **handled (atomic)** | 68.2% | 70.4% | **72.9%** |
| correct-on-handled | 94.1% | 94.2% | **94.1%** |
| resolvable date right | 91.3% (n=543) | 93.0% (n=643) | **93.5% (n=650)** |
| INVENTED a time | 4.5% (n=287) | 4.2% (n=306) | **3.7% (n=352)** |
| below-threshold deferrals | 581 | 501 | **346** |
| harm score | 168 / 129 wrong | 170 / 131 | **170 / 138** |
| DESTRUCTIVE errors | 16·11·5·1 (33) | 16·11·5·1 (33) | **12·11·4·1 (28)** |
| non-atomic HALF-EXECUTED | 72 | 72 | **72** |
| propose violations | 96 | 98 | **100** |

**+4.7 pt of handle-rate across the two cycles** (68.2% → 72.9%), against a
measured 0.6 pt error bar — FastRule reaches a decision on 150 more of the
3,200 single-item commands than it did this morning, and `below-threshold`,
its largest deferral reason, is down from 581 to 346.

**The most important line is DESTRUCTIVE errors, and it went DOWN: 33 → 28.**
Wrong commits ROSE (131 → 138) while the harm score held exactly flat at 170,
because the composition moved out of `complete_todo` (16 → 12) and
`delete_event` (5 → 4) and into `create`, where a mistake is a spurious row
rather than something destroyed. That is the severity weighting doing the job
Gil built it for, and it is `range-date-target` earning its place: 5 fewer
destructive wrong commits, bought with 7 more cheap ones.

**Invented-time rate fell while its denominator grew** (4.5% n=287 → 3.7%
n=352): 65 more events are now reached, and a smaller share of them get a time
nobody asked for.

### Two honest caveats about what this board can and cannot see

1. **The board calls `FastRule.run()` directly, not `fast_propose`.** So a
   create with a range date reads here as **committed**, while in production it
   is OFFERED and nothing is written until the speaker accepts. The
   handle-rate rise means "FastRule now reaches a decision on these rows", not
   "these rows now commit silently". The confirmation path is covered by tests
   (`test_confirm_create.py`), including one that makes the deep track RAISE to
   prove no model is involved — it is not covered by this board.
2. **`range-date-target` is not in the board's `_ATOMICITY_REASONS`**, so a
   NON-atomic row deferring on it is scored as an accidental defer rather than
   a recognised compound. That is why "knew it was compound" reads 68.7% →
   66.3% while total non-atomic deferral is flat (73.6% → 73.5%). A metric
   attribution artifact, not a behaviour change — but the scorer's set is the
   thing that is now slightly wrong, and editing it changes a reported metric,
   so it is left alone and named here.

### Next prediction (registered now)

**The 50 recurrence-BOUNDARY rows** — `"every monday until the end of the
month"`, where the range is a series bound and belongs in `date_phrase_2` +
`end_inclusive` (28 inclusive / 22 exclusive in the train half). Unlike this
cycle these need no new ruling: *"until" excludes the day it names; "through"
and "including" keep it* is already settled, and the gold carries both fields.
Predicted: handle-rate +0.5 to +1.0 pt on the 3,200 atomic rows, with
`recurrence`/`end_inclusive` correctness as the real target and
DESTRUCTIVE errors flat. Smaller than the last two, and the honest reason to
do it is that a series firing past its end date is a wrong answer that repeats.

---

## Cycle 22 — a series that STOPS (2026-09-18)

**Registered prediction (cycle 21):** the recurrence-boundary rows, +0.5 to
+1.0 pt handle-rate, recurrence/`end_inclusive` correctness the real target,
DESTRUCTIVE flat. **Two of those three were wrong, and the reasons are the
finding.**

### What the slice actually is

Cycle 21 called this "the 50 boundary rows". Re-counted properly: `date_phrase_2`
is carried by **490** train rows, but on most of them it is the SECOND ITEM'S
DATE in a compound ("book moving day this morning and also put conference call
on…"), not a bound. The only marker of an actual bound is **`end_inclusive`**,
which 138 train rows carry. 50 was the intersection of "is a bound" and "had an
unread daterange" — a subset, not the family.

### The defect was bigger than a field in the wrong place

`db.create_event` has honoured `recur_until` since it was written. **Nothing in
`rule_parser.py` ever set it** — grep confirms `end_inclusive` has zero hits
anywhere in `assistant/`. So every bounded series was created UNBOUNDED:

    of the 114 bounded rows FastRule committed, recur_until was set on   0
    committed as a series with NO END, firing forever                   81

That is the "wrong answer that repeats" class, and it was invisible because **no
board had a line for it.**

**And cycle 21 had made this family worse.** Its `daterange` reader put the BOUND
into the item's own date, overwriting the correct anchor `_fill_slots` already
computes (`_rec.start_date()` — "every monday starts on the soonest Monday"):

    "every monday ... until the end of the month"  ->  date 2026-09-16, a WEDNESDAY
    "twice a week until next month"               ->  date 2026-10-01, the bound itself
    "every week until today"                      ->  date 2026-09-09, the bound

Cycle 21's board could not see that either: its date metric excludes range
phrases, and these rows have no own-date in the gold to check against.

### The fix

The bound comes OFF the text before anything reads the item's own date (masked
with spaces, so every later character offset stays valid for span-blocking and
title extraction), and is resolved into `recur_until` under Gil's standing
ruling. The two readings of a range genuinely differ, which is most of the work:

    "until next month"           the month is the STOP  -> day before it starts
    "until the end of the month" names the final day    -> the last day of it
    "through next week"          runs to the END of it
    "including next friday"      that day is kept

So an exclusive bound counts back from the range's START and an inclusive one
from its END, and the recogniser's range ends are exclusive — hence a further day
off. A trailing clock time is kept out of the mask: the recogniser returns "next
tuesday at 5 pm" as ONE datetime, and masking the whole match ate the event's own
time.

### Result — FastRule product-shape board, TRAIN half

**A NEW SECTION was added to the board** (`BOUNDED SERIES`), because the old one
could not see any of this. Both columns below are that board; the "before" run is
the same scorer against the unmodified parser, not a reconstruction.

| metric | before | after | |
|---|---|---|---|
| **bounded rows: carried an end** | **0.0%** | **75.8%** | of the committed |
| **...and it was the right day** | — (n=0) | **88.1%** (n=42) | |
| **FIRES FOREVER** | **81** | **5** | a series committed with no end |
| bounded rows committed | 114 | 99 | |
| handled (atomic, 3,200 rows) | 72.9% | **72.4%** | **−0.5 pt** |
| correct-on-handled | 94.1% | 94.1% | flat |
| resolvable date right | 93.5% (n=650) | 93.5% (n=650) | flat |
| harm score | 170 / 138 wrong | **168 / 136** | −2 |
| DESTRUCTIVE errors | 12·11·4·1 | 12·11·4·1 | flat |
| half-executed | 72 | 72 | flat |

**What it means.** 76 of the 81 series that would have fired forever now stop
where the speaker said, and 88.1% of the ones that can be scored stop on exactly
the right day. The cost is 15 rows that used to commit and now defer: they had
been committing with the BOUND as their start date, so they were wrong before and
are merely late now — and 2 of them were wrong commits the harm score has stopped
paying for.

**Actual vs expected:** handle-rate went the wrong way (−0.5 pt against a
predicted +0.5 to +1.0). The prediction assumed the bound was an unused field to
fill; it was a field that had been silently stealing the start date, so fixing it
REMOVES a date some rows were leaning on. Predicting a gain there was the error,
not the fix.

### Why 15 rows now defer, and the next cycle

All 15 lose their date because `recurrence.detect()` returns None for their
cadence — "every other tuesday", "every weekend", "twice a week" — so
`_rec.start_date()` never runs and nothing supplies an anchor. With the bound no
longer available to stand in wrongly, the row has no date at all.

**Next prediction, registered now: `assistant/intent/recurrence.py`'s cadence
reader.** Target: the cadences it misses on the 138 bounded rows and wherever else
they appear. Predicted **handle-rate +0.5 pt or better** (recovering the 15 and
any row that defers for the same reason), `FIRES FOREVER` → 0 or near it, and
`recurrence_rounded` correctness as the guard — CLAUDE.md is explicit that
rounding a cadence is allowed only if it is ANNOUNCED, and "every other tuesday"
rounded to weekly fires twice as often as asked. Same instrument, same slice.

### One process note, because it cost an hour

The diagnostic harness hung, repeatedly, and the cause was a scratch file named
`attr.py`. `rich` (imported by `httpx`, imported by `weasel`, imported by spaCy)
does `import attr` — Python found the scratch file first, executed it, and it
re-entered the spaCy load it was itself waiting on. The board and pytest were
unaffected because they run from the repo root. **Never name a scratch file after
an importable module**; `faulthandler.dump_traceback_later` is what found it,
after three wrong guesses (lock contention, memory pressure, BLAS threads).

**CORRECTED 2026-09-18, same session, before any work started on it.** The
"next prediction" above names the cadence reader and says all 15 deferrals lose
their date because `recurrence.detect()` returns None for "every other tuesday" /
"every weekend" / "twice a week". **Two of those three were wrong, and so was the
dominant cause.** Checked by running `detect()` and then reading the deferred
rows themselves rather than the sample of six I had in front of me:

    every other tuesday  ->  weekly, rounded   (READ, not missed)
    twice a week         ->  weekly, rounded   (READ, not missed)
    every weekend        ->  None              (missed)
    once a week          ->  None              (missed)

Of the 19 bounded rows now deferring below-threshold, the causes are:

    ~13   missing TITLE — "book parent-teacher conference WEEKLY at 3:45pm",
          "book annual checkup MONTHLY at 8:30pm": the cadence word sitting
          right after the title breaks `_extract_title`. The cadence itself is
          read correctly. This is the title extractor — FastRule's own 62.9%,
          already flagged as "mine-first, diminishing" — tripped by one adverb.
      6   cadence None — "every weekend", "once a week" only.

So the registered next cycle is re-aimed: **the title extractor on cadence
adverbs first** (the larger and the simpler: the adverb is a known word from
`recurrence.py`'s own table, so the fix is to blank it the way temporal spans
are blanked), with the two missing cadences as the second, smaller half.
Predicted handle-rate +0.4 pt (13 rows) and +0.2 pt (6 rows) respectively on the
3,200 atomic rows, `FIRES FOREVER` → near 0 across both, DESTRUCTIVE flat.

The commit message for `1d72d1a` carries the wrong diagnosis and cannot be
edited; this note is the correction. The lesson is the one this file keeps
teaching: the sample I read was six rows, the population was nineteen, and the
six happened not to contain the dominant case.

---

## Cycle 23 — the SUBTRACTIVE title (2026-09-18)

**The design change Gil approved** (DEVQA Q26, *"Ok you can try it"*), and the
first cycle picked by the real-usage board rather than by the corpus.

### Why this one and not the registered next cycle

Cycle 22 registered the cadence reader. The real-usage board's first run
(`DOCUMENTATION/experiments/real_usage/RESULTS.md`) put that aside: on Gil's own
commands the largest failure class is **`generic-title`, 21 of 50 reviewed rows
(42%)** — the title stopping at the generic word while "with omri for project"
sat right there in the sentence. So a **title-correctness metric was added to
this board first**, because it had none — it only ever asked whether a title
NAMED NOTHING, which "meeting" passes. It read:

    exactly right              41.8%  (n=1535)
    right or a substring of it  85.6%

**44 points of pure TRUNCATION**, which is the same defect from the other
direction and the number that justified the rewrite.

### What changed

`_extract_title` picked ONE noun chunk (dobj, else pobj, else nearest to root).
It is now **subtractive**: every reader that already claimed words gives them up
— temporal spans, the cadence phrase (`Recurrence.span`, added here), the series
bound, the destination, the stop keyword, the imperative shell — and the title is
what remains. The same move cycle 22 made for one phrase, applied on purpose.

Four rules carry most of the work, each bought with a measured failure:

- **A generic head TAKES a qualifier, it does not lose to one.** Dropping it left
  the bare `"with ora"`; keeping it gives `"meeting with ora"`. A part that does
  NOT open with a preposition is its own thing and outranks the generic head
  (`"event"` + `"movie at the AMC"` → `"movie at the AMC"`).
- **Stranded function words go off the END only.** A leading preposition whose
  object survived still means something (`"at the Lincoln AMC"`); a trailing one
  lost its object to the blanking (`"meeting with ora at"`). Treating them alike
  produced `"Movie the Lincoln AMC Theatre"`.
- **The framing verb is stripped mid-string but not at position 0**, where
  `_FRAME_LEAD` deliberately keeps the entry word. Letting it fire at 0 removed
  the head from `"schedule a meeting with Harper"` and cost **1.6 pt** of corpus
  title exactness, measured.
- **A runaway title hands back to the chunk reader.** Subtraction that leaves a
  sentence has copied it; over 8 words it returns empty. One real row produced 12
  words of transcript.

### THE ONE THAT MATTERS: naming is not finding

`_extract_title` also supplies `match_title` — the NEEDLE for a record that
already exists — and a richer phrase is a WORSE needle. Shipped subtractive for
everything, the board's `update_todo` DESTRUCTIVE errors went **1 → 27** in a
single run. `subtractive=` is now chosen by the action: a create names something
new and wants every word; an update or delete finds an old one and wants the few
that identify it. With that split the destructive line is **unchanged**.

### Result — FastRule product-shape board, TRAIN half, 3,200 atomic rows

| metric | before | after | |
|---|---|---|---|
| **handled (atomic)** | 72.4% | **76.9%** | **+4.5 pt** |
| **correct-on-handled** | 94.1% | **94.4%** | **+0.3** |
| **title exactly right** | 41.8% (n=1535) | **48.5% (n=1677)** | **+6.7 pt** |
| **title right or a substring** | 85.6% | **97.1%** | **+11.5 pt** |
| titles that name nothing | 0.2% (3/1554) | **0.0% (0/1721)** | gone |
| resolvable date right | 93.5% (n=650) | 93.6% (n=716) | flat, larger n |
| bounded: carried an end | 75.8% | 78.2% | +2.4 |
| bounded: right day | 88.1% (n=42) | 89.6% (n=48) | +1.5 |
| INVENTED a time | 3.7% | 3.5% | −0.2 |
| harm score | 168 / 136 wrong | 171 / 139 | +3 |
| **DESTRUCTIVE errors** | 12·11·4·1 | **12·11·4·1** | **flat** |
| half-executed | 72 (5.1%) | 74 (5.3%) | +2 |
| non-atomic covered | 299 (21.4%) | 331 (23.7%) | +32 |

### Result — REAL-USAGE board, the instrument that chose this work

| metric | before | after |
|---|---|---|
| **title right (corrected tier)** | 33.3% (n=18) | **38.9%** |
| start_time / end_time right | 42.9% (n=14) | **50.0%** |
| date right | 78.6% (n=14) | 78.6% |
| all fields right | 11.1% (n=9) | 11.1% |
| approved tier unchanged | 43.8% (n=16) | 43.8% |
| rejected tier changed | 63.4% (n=41) | 75.6% |

**What it means.** The truncation is essentially gone: 97.1% of committed titles
are now the gold or a substring of it, and FastRule acts on 76.9% of single-item
commands against 72.4% this morning. On Gil's own speech `"lincoln"` is now
`"movie at the lincoln amc theatre"` and `"dog"` is `"walk mark dog"` — two rows
he had already approved with better titles than the engine was producing.

**All-fields on the real board did not move (11.1%, n=9)** and that is honest:
every remaining row fails on something other than the title — hand-edited clock
times, item counts on compounds, STT garbage. n=9 means one row is 11 points, so
this number cannot show a 5.6 pt field-level gain at all. The per-field column is
the one to read at this sample size.

### Next prediction (registered)

**`start_time`/`end_time`, on the real board.** They are 50.0% (n=14) and moved
+7.1 pt as a side effect of this change, which suggests time words were being
swept into titles and are now being read where they belong. The corpus agrees
there is room: explicit time right 81.3% (n=481). Predicted: **+3 pt or better on
real-usage times and +1 pt on corpus explicit-time**, with INVENTED-a-time as the
guard (it must not rise — a time invented is worse than a time missed). The
FastRule cadence reader from cycle 22 stays queued behind it: `"every weekend"`
and `"once a week"` are still unread, worth ~6 rows.

### Filed, not fixed

**The temporal reader over-claims, and subtraction makes it visible.** `"book
annual checkup monthly at 8:30pm"` titles itself `"checkup"` because
`_extract_temporal` claims the span of `"annual"` as a date. The old chunk reader
kept the word by accident. Pinned by a test that asserts BOTH the over-claim and
its consequence, so narrowing the recogniser's claim shows up as a change rather
than a surprise.

## Cycle 24 — a stated clock or day beats a title word (2026-09-19)

### Why this one and not the registered next cycle

Gil asked how invariant `decompose_validate` is to the TITLE and the TIME in a
prompt. The stage itself is: position 100% on its isolated board (1,548/1,548,
`scripts/dv_invariance.py`), and a probe holding 1,477 distinct time phrases
fixed while swapping 115 titles (169,855 pairs, train split) moved the time
fields in **0 undesigned pairs**. The leak was on the FRONT DOOR: a nine-command
live probe put a time-like word in the title and FastRule's temporal reader let
it beat the stated clock or day in **4 of 9**. Gil chose the fix over more
measurement (*"Fix the front-door title leak"*), so this cycle went ahead of the
registered start/end prediction below, which stays queued.

### What changed — three precedence rules in `_extract_temporal`, each measured alone

| | defect | rule now | corpus effect |
|---|---|---|---|
| **A** | "book morning pages tomorrow at 7am" booked 08:00–12:00: the daypart window came first in the string and the stated 7am was refused as a second start | a daypart is a WINDOW and is applied only when nothing states a clock — the convention `decompose_validate` already writes down; a window that loses claims no span, so its word stays in the title. **Except directly after a clock**, where it is that clock's MERIDIEM ("this morning at 6 in the evening" is how the recogniser splits nine train rows): claims its span, sets no end, settles am/pm | 9 rows changed, 6 gained the right clock (06:00→18:00, 21:00→09:00), 0 worse |
| **B** | "book walk through the slides tomorrow at 3pm" booked TODAY with a bound of tomorrow: `_series_bound` accepted a date three words after "through" | a bound's date must sit right after its keyword, at most a function word between | 0 rows changed |
| **C** | "book monday standup tomorrow at 9am" booked MONDAY: the first date in the string won | a datetime overrides a date that came from a BARE date reading, never another datetime; the loser keeps its claim on its words (releasing it put "tomorrow" into a pinned title) | 0 rows changed |

Each rule ran the board and an old-vs-new row differential on its own before
the next was applied (`46506f3`, `ec7849c`, `0c16b83`).

### Result — FastRule product-shape board, TRAIN half, 3,200 atomic rows

| metric | before | after | |
|---|---|---|---|
| handled (atomic) | 77.7% | 77.7% | flat |
| correct-on-handled | 94.5% | 94.5% | flat |
| title exactly right | 61.1% (n=1770) | 61.1% | flat |
| explicit time right | 79.5% (n=527) | 79.5% | flat |
| INVENTED a time | 3.5% (n=370) | 3.5% | flat |
| resolvable date right | 91.8% (n=773) | 91.8% | flat |
| harm / DESTRUCTIVE | 159 / 12·4·2 | 159 / 12·4·2 | flat |
| half-executed (non-atomic) | 58 | **57** | −1 |

**What it means.** The corpus has almost none of the shape this fixes — a
title carrying a daypart, a bound word or a weekday next to a stated time —
which is exactly why the invariance probe found it and the board never did.
The evidence is the 14 unit tests (`TestStatedTimeBeatsTitleWords`) and the
live probe: 4 of 9 wrong → 0 of 9. The one corpus effect is the nine
"at 6 in the evening" rows, whose 06:00 was a pre-existing defect the meridiem
rule closes.

**Guard**: `scripts/invariance_board.py` before and after, same HEAD —
byte-identical on every boundary (front door 49.4%, n=1,548) and every
position; content rules, not position rules. Full unit suite 2,078 passed.

### Filed, not fixed

**The two tracks disagree on the bare hour.** "book team meeting tomorrow at
7" is 19:00 on the front door (`_pick_business_hour_time` prefers PM for 1–7,
and the post-process bumps 1–7 unless a morning word is present) and 07:00 in
`decompose_validate` (conventions table: *1–6 is PM; 7–8 is PM only with
evening words*, Gil 2026-09-08). Same sentence, different answer by path. Not
a title leak and not this cycle's; needs a ruling on which convention holds
(DEVQA Q28), then the losing reader is aligned as an implementation fix.

### Next prediction (registered)

Unchanged from cycle 23: `start_time`/`end_time` on the real-usage board,
INVENTED-a-time as the guard. Q28 first if it lands before then, because a
bare-hour change moves that same metric.
