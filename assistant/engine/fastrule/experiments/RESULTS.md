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
