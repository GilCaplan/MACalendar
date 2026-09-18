# Position invariance — results

**The question** (Gil, 2026-09-18): *"is it invariant to where the time is in
the sentence — beginning, middle or end?"*

**The instrument**: `scripts/invariance_board.py`. Design, metric definitions
and the two-questions rule are in `dataset/METRICS.md` Level 4b. Read that
first; this file is what the board has actually printed.

---

## Run 1 — 2026-09-18, the first measurement

**Dataset**: FastRule 7,200 **train** half · 1,693 source rows (atomic, with a
gold `(text, time)` split) · 4,778 variants · 1,548 groups comparable
(145 rows were control-only: a stranded preposition makes them unpermutable).

### Per boundary — a group is one source row's variants

| boundary | solid | consistently wrong | **POSITION-DEPENDENT** |
|---|---|---|---|
| segmentation | 41.0% | 36.0% | **16.0%** |
| decompose_validate | 45.3% | 37.1% | **9.1%** |
| fastrule (stage) | 45.3% | 38.4% | **7.9%** |
| **front door** | 6.3% | 20.3% | **68.7%** |

### Correctness by position — action + title vs gold

| position | correct | n |
|---|---|---|
| `end` (control — every gold row is written this way) | 55.8% | 1408 |
| `front` (no comma) | 50.9% | 1408 |
| `front,` (comma) | 49.8% | 1408 |
| `middle` | 86.6% | 134 |

### Which field moves, among groups whose built object differs

    135  <item count>      the number of items changed with position
     71  action
     71  date
     62  titles
     60  title
     56  start_time · recurrence · recur_days · recur_until · end_time

---

## What it means

**1 — The prediction was half wrong, and the wrong half matters.**
Before the run I predicted segmentation, decompose_validate and the FastRule
stage would come out near 100% invariant, with only the front door low. The
front door is indeed catastrophic (**68.7% position-dependent**) — but the
deep track is *not* invariant either. **Segmentation loses the word partition
on 1 row in 6.**

**2 — Invariance degrades UP the chain, not down: 16.0% → 9.1% → 7.9%.**
Each stage after segmentation is *less* position-dependent than the one
before it. That is only possible if **neither `decompose_validate` nor the
FastRule stage introduces any position-dependence of its own** — they inherit
segmentation's, and some of it washes out (a partition difference that only
moves title words does not change a resolved date). This is direct evidence
for the architecture's claim that decompose_validate is per-item and
order-blind: *"every resolver takes ONE item's own time"*, and the flat list
pinned by index is *"a bug class, not a bug"*. That design is holding.

So the ownership is exactly where the stage contracts put it:

    segmentation        decides WHICH WORDS belong to which item  <- 16.0%, THE OWNER
    decompose_validate  decides WHAT THOSE WORDS MEAN             <- inherits only
    fastrule (stage)    items -> committable objects              <- inherits only

**3 — The front door is a separate problem, not a worse version of the same
one.** At 68.7% it is not inheriting anything: `fast_track.py` parses the raw
utterance before any Item exists, so it redoes segmentation's boundary job
*and* decompose_validate's feature job in one function, and it is
position-dependent on more than two thirds of rows. It is also the path that
answers most commands.

**4 — A third of rows are consistently wrong.** 36–38% at the deep stages
agree across every position and are still wrong on action+title. That is a
plain accuracy bug and is *not* what this board is for — it is counted in its
own column precisely so it is never read as a position failure.

**5 — The comma is its own bug.** `"the 30th, wash and fold the laundry"`
loses the date (`due_date=None`) while the same words without the comma
resolve it. Found while smoke-testing the board; it is why `front` and
`front,` are separate positions.

---

## Caveats — read before quoting these numbers

- **`middle` (86.6%) is not comparable to the others.** English offers one
  natural mid-sentence slot for a time adverbial — straight after an explicit
  reminder lead-in (*"remind me ON FRIDAY to water the plants"*) — so only 134
  of 1,693 rows produce a middle variant, and they are the simplest rows in
  the set. It is a different population, not a better position.
- **Some `front` variants of QUERY rows are of debatable naturalness.**
  *"the next few days, what's on my calendar"* is odd English, and those rows
  fail hard at the front. The front-position failure rate is therefore a
  slight over-estimate; how much has not been quantified.
- **Correctness here is stricter than FastRule's own board**: exact title
  match after casefold, through the whole deep chain, which is why `end` reads
  55.8% and not the high-70s the product-shape board reports for a different
  metric on a different slice.
- Dates are scored for AGREEMENT only, never correctness — the gold stores a
  date *phrase*, and resolving one to a day carries the ambiguity the
  product-shape board already documents.

---

## Not yet measured

- **Title position.** The gold hands over the `(text, time)` split for free;
  isolating sub-parts of the title (`with Dana`, `at the office`) would need a
  detector, which reintroduces the circularity this board was built to avoid.
  Deferred deliberately — see `dataset/METRICS.md` Level 4b.
- **Whether fixing segmentation's 16.0% moves the front door at all.** It
  should not: the front door does not call segmentation.
