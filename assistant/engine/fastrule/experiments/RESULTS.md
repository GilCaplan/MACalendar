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
