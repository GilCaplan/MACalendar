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

## Run 2 — 2026-09-18, after four fixes

Same board, same 1,548 groups, plus the new multi-ask arm.

| boundary | run 1 | run 2 |
|---|---|---|
| segmentation | 16.0% | **13.8%** |
| decompose_validate | 9.1% | **6.3%** |
| fastrule (stage) | 7.9% | **4.8%** |
| front door | 68.7% | **50.3%** |

**Correctness by position — the gap is what closed.**

| position | run 1 | run 2 |
|---|---|---|
| `end` (control) | 55.8% | 56.7% |
| `front` | 50.9% | **55.4%** |
| `front,` | 49.8% | **55.0%** |
| end→`front,` GAP | **6.0 pt** | **1.7 pt** |

That last row is the result. The engine did not just get better; it got
better *in a way that no longer depends on where the speaker put the time*.

**What produced it**, each measured on its own board before being banked:

1. `_grow_stranded` — the recogniser's span excludes the preposition that
   introduced it, so blanking left "at␣␣␣" at position 0 where `_FRAME_LEAD`
   is anchored. Front door 72.4% → 46.5% on the 300-row slice.
2. `_kind_of`'s fall-through consults `_REMIND_TO_VERB_RE` — a damaged frame
   ("remind mitt to") is still a task. realspeech kind 94.2% → 95.1%.
3. `clause_boundaries` discounts an EDGE date on the head side, as it always
   did on the conjunct side — gated on the positive serial-verb signature so
   it cannot collapse a real second ask. segmentation 16.0% → 14.2%, and
   **dv and fastrule improved because they inherit less**.
4. A dropped, action-less span now leaves its resolved date behind. 20 of 23
   reachable variants, no board movement — banked because the rows it touches
   were silently wrong, not because a number moved.

**The multi-ask arm did its job.** Fix 3's first shape collapsed
"by tonight schedule a meeting with Quinn and buy groceries" into one ask; the
arm and a baseline comparison caught it, and the positive-evidence guard was
added before anything was committed.

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

## Run 3 — 2026-09-19, the TITLE axis, and a guard for the front-door fix

**The question widened.** Position asks whether moving the time changes the
answer; the title axis asks whether the title's CONTENT does. Gil's framing:
*"invariant to where the time / title are located in the prompt."*

### decompose_validate, isolated — a probe, not yet a board

**Dataset**: the stage's own train split (2,004 rows), every distinct time
phrase held fixed (1,477) and the title swapped through 115 titles — the 85
bank titles (47 event + 38 task) plus 30 adversarial titles in nine trigger
classes (evening word, digit, duration, bound word, day word, cadence word,
relative word, lead word, part of day). **169,855 pairs**, each compared with
the time phrase alone.

| shape | result |
|---|---|
| time separate, title as context/action — the live deep-path shape | the five time fields moved in **0 undesigned pairs**. Designed couplings only: evening words flip a bare 7/8 (726), a duration in the action sets the end (2,649), a count read from the action (7,385 — 100% of digit titles, "chapter 5 review" → 5) |
| title INSIDE the time string, title after time | **7.4%** of bank pairs move — a range followed by any words loses both clocks. Not a live shape: segmentation separates the two, and the fast path hands the stage a title alone |
| title inside the string, title before time | 0.2% of bank pairs |

**What it means.** The stage is title-invariant bar its three written
conventions. The stage's nine boards could not have shown this either way:
the title banks carry no digit, no duration and two evening words; board B
grounds any digit in the item's words; the gold's `resolve_time` applies the
same evening-word rule as the code. The greedy count is filed (0 identifier
numbers, 1 address in 2,699 mineable real utterances).

### The front door — where the title DID change the answer

Nine live commands with a time-like word in the title, through
`FastRule.run` + `run_objects` with every store in a temp dir:

| before | after |
|---|---|
| "book morning pages tomorrow at 7am" → 08:00–12:00, title "pages" | 07:00, "morning pages" |
| "book night shift handover tomorrow at 2pm" → 20:00–23:59, "shift handover" | 14:00, "night shift handover" |
| "book walk through the slides tomorrow at 3pm" → TODAY, bound tomorrow, "walk" | tomorrow 15:00, no bound, "walk through the slides" |
| "book monday standup tomorrow at 9am" → MONDAY | tomorrow |
| 4 of 9 wrong | 0 of 9 (one convention split left: "at 7" → 19:00, DEVQA Q28) |

Three precedence rules in `rule_parser._extract_temporal`, each boarded alone
on the FastRule product-shape board (`fastrule/experiments/RESULTS.md` cycle
24, commits `46506f3` `ec7849c` `0c16b83`): every headline flat, 9 rows
gained a right clock, 0 worse.

### The guard — this board, before and after, same HEAD otherwise

| boundary | before | after |
|---|---|---|
| segmentation | 13.8% | 13.8% |
| decompose_validate | 6.3% | 6.3% |
| fastrule | 4.8% | 4.8% |
| front door | 49.4% | 49.4% |
| correctness end / front / front, | 56.7 / 55.4 / 55.0 | 56.7 / 55.4 / 55.0 |
| multi-ask arm, end / front / front, right | 77.2 / 64.0 / 66.0 | same |

Byte-identical, as predicted: these are CONTENT rules and the 7,200 set's
titles carry no such words. (The front door reads 49.4% on this HEAD against
run 2's 50.3% — commits between the two runs, not this change; the before
column above is the honest baseline, taken the same day.)

---

## Run 4 — 2026-09-20, after the segmentation implementation fixes

Same board, same 1,548 groups, HEAD after the nine segmentation commits of
2026-09-20 (`segmentation/experiments/RESULTS.md`). The front door does not
call segmentation, and it did not move.

| boundary | run 3 | run 4 |
|---|---|---|
| segmentation | 13.8% | **13.2%** |
| decompose_validate | 6.3% | **5.7%** |
| fastrule | 4.8% | **4.3%** |
| front door | 49.4% | 49.4% |
| correctness `end` / `front` / `front,` | 56.7 / 55.4 / 55.0 | 56.7 / 55.4 / **55.5** |
| multi-ask arm, UNDER-split end / front / `front,` | 50 / 81 / 68 | **47 / 79 / 66** (over unchanged 7 / 9 / 16) |

The `front,` gain is the fronted-date guard (a comma after a leading date no
longer cuts "wash and fold" in two); the rest is the cut finding seams it
used to miss at every position, which is why decompose_validate and fastrule
inherit less again. Still degrading UP the chain: the per-item design holds.

## Not yet measured

- **Title CONTENT is probed, not boarded** (run 3). If it is needed again, a `--title` arm on `scripts/dv_invariance.py` is the shape.
- **Title position.** The gold hands over the `(text, time)` split for free;
  isolating sub-parts of the title (`with Dana`, `at the office`) would need a
  detector, which reintroduces the circularity this board was built to avoid.
  Deferred deliberately — see `dataset/METRICS.md` Level 4b.
- **Whether fixing segmentation's 16.0% moves the front door at all.** It
  should not: the front door does not call segmentation.
