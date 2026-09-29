# The phone's offline reader — results

Board: `python -m assistant.offline.experiments.apple_board` — Apple's
on-device model (Foundation Models, ~3B parameters), run on this Mac exactly
as the phone runs it, over the **FastRule set** (`assistant/engine/fastrule/
datasets/fastrule_7200.jsonl`), scored with the FastRule board's own gold
converters at its clock (2026-09-09 10:00). Every row is one checkpoint line
with its wall-clock time. **Latency is the Mac's** (same model, faster chip
than a phone): read it as a floor.

Metrics, once:
- **booked something anyway** — rows that ask to change, delete, complete or
  look something up, where the phone booked a NEW item (it must book nothing).
  The harm line.
- **right number of each kind** — create rows where the phone booked exactly
  the gold's events and to-dos.
- **extra (invented) items** — items booked beyond the gold's count.
- **single-item field lines** — on rows with one expected item: kind; title
  (`reconcile.titles_match`, and word F1); date (where the gold phrase names
  one day); explicit time (`gold._ruled_hhmm`); repeat; the whole item.
- **latency** — per model call, p50/p90/p99.

## Baseline — the reader as first shipped (2026-09-29 08:41–09:31)

TRAIN split, n = 1,200/1,200 scored (0 skipped), seed 7, 280 families. Spec
version as served at the time; no guard, dates from the model.

| line | TRAIN |
|---|---|
| generation errors | 1.8% (21/1200) |
| **booked something on an edit/delete/complete/question** | **66.6% (203/305)** |
| right number of each kind (create rows) | 54.9% (491/895) |
| booked nothing on a create (left to the Mac) | 2.5% (22/895) |
| extra (invented) items | 315 across 895 create rows |
| right kind, single-item | 86.5% (430/497) |
| title matches (word F1) | 98.6% (424/430) (92.7%) |
| **date right** | **46.9% (97/207)** |
| explicit time right | 87.3% (137/157) |
| repeat right | 96.3% (78/81) |
| **whole item right** | **60.0% (298/497)** |
| latency p50 / p90 / p99 / max | 1,861 / 2,308 / 36,526 / 39,411 ms |

**What it means.** The model is good at the WORDS — titles 98.6%, repeats
96.3%, explicit times 87.3% — and bad at the three things the Mac's engine
never asks its model to do: it books a new item for two thirds of the commands
that ask to change or delete something (a second vet appointment for "push
vet appointment to 3:45pm"), it gets fewer than half of the dates right
(arithmetic from "this friday"), and it invents 315 items (copying the
instructions' examples: "buy milk", "email the landlord"). As shipped it would
be worse than no offline reader: the Mac replaces its rows on reconnect, but
until then a third of what it shows is wrong.

**The latency tail is a loop, not slowness.** All 21 generation errors and
every call over 10 s (21 of 1,200) are `exceededContextWindowSize`: on repeat
phrases ("every weekday", "every other week") the model keeps emitting items
until its context window fills, ~37 s each. p50 1.9 s otherwise.

Registered next (DEVQA Q68 step 1), each boarded alone on the same 1,200 rows:
1. **The guard** — the engine's own tables leave edits, deletes, completions
   and questions for the Mac before any model call. Predict: the harm line
   66.6% → near 0 on the guarded families, a few create rows lost to false
   guards ("booked nothing" up from 2.5%).
2. **Dates in code** — the model returns the day words (`when`), `OfflineDates
   .swift` resolves them (parity-tested against `gold._phrase_to_date`).
   Predict: date right 46.9% → most of the way to what the model copies
   correctly; whole item right up with it. Caveat: the board scores dates with
   the same rules the phone now uses, so this line then measures the model's
   choice of words.
3. **A cap on items** (guided generation's maximum count) — predict the 21
   context-window errors and the >10 s tail gone, and fewer invented items.

## Step 1a — the guard (2026-09-29 09:31–10:09)

Same 1,200 TRAIN rows, seed 7; the guard as first written (every
non-create verb of `INTENT_MAP` + the engine's delete/complete frames +
question starts). Model and instructions unchanged.

| line | baseline | **guard v1** |
|---|---|---|
| left for the Mac by the guard (no model call) | — | 28.2% (338/1200) |
| **booked something on an edit/delete/complete/question** | 66.6% (203/305) | **13.4% (41/305)** |
| right number of each kind (create rows) | 54.9% (491/895) | 49.1% (439/895) |
| booked nothing on a create | 2.5% (22/895) | 14.1% (126/895) |
| extra (invented) items | 315 | 268 |
| whole item right, single-item | 60.0% (298/497) | 57.7% (287/497) |
| generation errors | 1.8% (21) | 1.6% (19) |
| latency p50 / p90 / p99 (model calls) | 1,861 / 2,308 / 36,526 ms | 1,891 / 2,278 / 36,456 ms |

**What it means.** Harm fell five-fold (203 → 41 wrong bookings on edits,
deletes and questions). The cost is 104 creates held for the Mac — nearly all
MIXED commands ("cancel dinner and book webinar"), which the guard leaves
whole by design, plus a handful of real false guards ("mark the 30th as the
tax deadline", "moving day" read as *move*). Prediction met on the harm line;
the create-side cost was larger than predicted because of mixed commands.

## The guard alone, refined — `guard_board.py` (no model, whole split, seconds)

Being code, the guard is scored on EVERY row of a split. Three rounds on TRAIN
misses/false guards (general phrasings each seen in several families: "X is
now at", "i already did X", "get rid of", "take X off my calendar", "mark X as
done" vs "mark the 30th as the deadline", one-letter verb slips, wake words,
a question in any clause; "-ing" forms and "chuck"≈"check" no longer match;
delete/scrap/erase/update/edit leading a command count as edits).

| guard | split | n | caught (edit/delete/complete/question) | false guard (plain create) | mixed left (by design) |
|---|---|---|---|---|---|
| v3 | TRAIN | 6,300 | 99.9% (1581/1583) | 0.2% (5/2716) | 23.3% (466/2001) |
| v3 | **TEST** | 2,400 | **73.9% (688/931)** | **5.1% (45/890)** | 17.4% (101/579) |

**What it means.** On TEST — different families, never read — the guard
catches three quarters of the edits and questions and wrongly holds 1 in 20
plain creates. The TRAIN/TEST gap (−26 pt caught, +4.9 pt false) says the
refinements fitted TRAIN's phrasings more than they generalised; TEST rows
were not looked at and will not be (aggregates only). It remains far safer
than no guard (0% caught), and every miss is still re-read by the Mac on
reconnect. Closing the gap needs broader TRAIN phrasing, not TEST mining.

## Step 1b — dates in code (2026-09-29 10:09–10:38)

Same 1,200 TRAIN rows, seed 7, on top of guard **v1** (the refinements were
made after this run compiled — checked: its guard.json has v1's 2 frames).
Schema 2: the model returns `when` (the day words), `OfflineDates.swift`
resolves them.

| line | guard v1 | **+ dates in code** |
|---|---|---|
| **date right** | 47.4% (93/196) | **94.3% (183/194)** |
| extra (invented) items | 268 | **107** |
| generation errors | 1.6% (19) | 0.7% (8) |
| latency p50 / p90 / p99 (model calls) | 1,891 / 2,278 / 36,456 ms | 1,692 / 2,040 / **4,079 ms** |
| booked something on an edit/delete/complete/question | 13.4% (41/305) | 16.4% (50/305) |
| right kind, single-item | 82.9% (412/497) | **60.4% (300/497)** |
| booked nothing on a create | 14.1% (126/895) | 23.6% (211/895) |
| right number of each kind | 49.1% (439/895) | 42.6% (381/895) |
| whole item right, single-item | 57.7% (287/497) | 53.5% (266/497) |

**What it means.** Dates nearly doubled, as predicted (the caveat stands:
the phone now resolves by the same rules the board scores with, so the line
measures the model's choice of day words — which it gets right 94% of the
time). Unpredicted and welcome: invented items fell 60% and the loop tail
mostly vanished (p99 36 s → 4 s) — asking for words instead of an ISO date
seems to steady the model. The COST: an event whose day words the resolver
cannot place is left for the Mac instead of guessed, so 161 event items lost
their date — the "right kind" and "booked nothing" lines. About half of those
name one day ("every sunday", "in three weeks", "christmas day", "this coming
saturday"); the rest are ranges ("next week", "this weekend") that SHOULD wait
for the Mac. The harm line rose 41 → 50 with the same guard: 9 more unguarded edit rows
got a booking — the model's reading changed with the new schema; to read again
once the refined guard is in.

Registered next: guard v3 (on top of this); the item cap; then the resolver
extended to the day words with ONE answer (a repeat's first day, fixed
offsets, named holidays, "this coming X"), ranges still left for the Mac —
predict "right kind" back above 75% and "booked nothing" down toward the
guard's floor.

## Step 1a' — guard v3 on top of dates in code (2026-09-29 10:38–11:08)

Same 1,200 TRAIN rows, seed 7; the refined guard (v3, above) with schema 2.

| line | + dates (guard v1) | **+ guard v3** |
|---|---|---|
| left for the Mac by the guard (no model call) | 28.2% (338/1200) | 34.4% (413/1200) |
| **booked something on an edit/delete/complete/question** | 16.4% (50/305) | **0.3% (1/305)** |
| right number of each kind (create rows) | 42.6% (381/895) | 43.4% (388/895) |
| booked nothing on a create | 23.6% (211/895) | 24.1% (216/895) |
| extra (invented) items | 107 | 100 |
| right kind, single-item | 60.4% (300/497) | 63.2% (314/497) |
| date right | 94.3% (183/194) | 94.6% (194/205) |
| whole item right, single-item | 53.5% (266/497) | 56.3% (280/497) |
| generation errors | 0.7% (8) | 0.7% (8) |
| latency p50 / p90 / p99 (model calls) | 1,692 / 2,040 / 4,079 ms (n≈862) | 1,801 / 2,676 / 34,094 ms (n=787) |

**What it means.** The harm line is gone on TRAIN: one wrong booking in 305
edits, deletes and questions, from 50. It cost almost nothing on creates
(+5 rows held back). The caveat is the one the guard board already showed: these are the
families the guard was refined on, and on TEST it catches 73.9%, not 99.7%.
The p99 jump is a denominator effect, not a regression: the same 8
context-window loops (~35 s each) are 1.0% of 787 model calls but 0.9% of
~862, so the 99th percentile now lands on one — the cap run removes them.

## Step 1c — a cap on items (2026-09-29 11:08–11:35) — REVERTED

Same 1,200 TRAIN rows, seed 7, guard v3 + dates in code, plus
`.maximumCount(6)` on the item list.

| line | guard v3 | **+ cap** |
|---|---|---|
| generation errors (context-window loops) | 0.7% (8) | **0.0% (0)** |
| latency p50 / p90 / p99 / max (model calls, n=787) | 1,801 / 2,676 / 34,094 / 56,349 ms | 1,899 / 2,635 / **4,390 / 6,798 ms** |
| booked something on an edit/delete/complete/question | 0.3% (1/305) | 0.3% (1/305) |
| **extra (invented) items** | 100 | **306** |
| right number of each kind (create rows) | 43.4% (388/895) | **31.5% (282/895)** |
| booked nothing on a create | 24.1% (216/895) | 16.0% (143/895) |
| right kind, single-item | 63.2% (314/497) | 68.6% (341/497) |
| title matches | 98.4% (309/314) | 95.6% (326/341) |
| date right | 94.6% (194/205) | 92.1% (197/214) |
| whole item right, single-item | 56.3% (280/497) | 58.6% (291/497) |

**What it means.** The prediction held on the tail — no loops, p99 34 s →
4.4 s — and failed badly on inventions, which TRIPLED. Row by row: 180 model
rows gained exactly one item, 169 of them a new title, and most of those are
the instructions' own examples copied in ("buy milk", "email the landlord",
"buy groceries"); 25 rows now sit AT the cap, mostly one title repeated six
times. A count bound on the list reads to this model as "make a list". An
invented item is exactly what the phone must not show, so the cap is out.
The loops are bounded by TIME in the app instead (`OfflineReader.timeLimit`,
12 s → the command waits for the Mac): they are ~1% of model calls, and a
normal call takes ~2 s (max 6.8 s here).

Note: the dates-extension run below was compiled WITH the cap (it started
before this was read), so it measures the extension on top of the cap; the
shipped configuration — guard v3 + dates + extension, no cap — is boarded
after it.

## Step 1b' — the resolver's one-answer day words (2026-09-29 11:35–12:06)

Same 1,200 TRAIN rows, seed 7, guard v3 + dates + cap (compiled before the
cap was read; see above). `OfflineDates.swift` now also resolves a repeat's
first day ("every sunday", "every weekday"), fixed offsets ("in three weeks",
"tomorrow week"), named holidays and "this coming X"; ranges ("next week",
"this weekend") still wait for the Mac.

| line | + cap | **+ one-answer day words** |
|---|---|---|
| **right kind, single-item** | 68.6% (341/497) | **85.3% (424/497)** |
| **whole item right, single-item** | 58.6% (291/497) | **75.5% (375/497)** |
| repeat right | 79.6% (39/49) | 94.7% (89/94) |
| booked nothing on a create | 16.0% (143/895) | 13.5% (121/895) |
| right number of each kind (create rows) | 31.5% (282/895) | 35.1% (314/895) |
| date right | 92.1% (197/214) | 92.1% (197/214) |
| booked something on an edit/delete/complete/question | 0.3% (1/305) | 0.3% (1/305) |
| extra (invented) items | 306 | 388 |
| latency p50 / p99 (model calls, n=787) | 1,899 / 4,390 ms | 1,898 / 3,942 ms |

**What it means.** Predicted "right kind back above 75%": it reached 85.3%,
and the whole single item is right three times in four, up 16.9 points —
the events that named their day as a repeat or an offset are no longer held
back for want of a date. Invented items ROSE (306 → 388) for the same reason:
an invented event used to be held back when its day could not be resolved,
and now its day resolves, so it is booked. The resolver did not create them;
it stopped hiding them. With the cap gone the inventions should fall back —
the shipped configuration's run is next.

## The shipped reader (2026-09-29 12:06–12:37) — end of step 1

Same 1,200 TRAIN rows, seed 7: guard v3 + dates in code + the one-answer day
words, no cap — exactly what is installed on the phones. The app also cuts a
reading off at 12 s; on this board 8 of 787 model calls ran past it (all
context-window loops, ~35 s), and in the app those 8 wait for the Mac.

| line | baseline (as first shipped) | guard v3 + dates | **shipped** |
|---|---|---|---|
| **booked something on an edit/delete/complete/question** | 66.6% (203/305) | 0.3% (1/305) | **0.3% (1/305)** |
| right number of each kind (create rows) | 54.9% (491/895) | 43.4% (388/895) | **51.8% (464/895)** |
| booked nothing on a create (left to the Mac) | 2.5% (22/895) | 24.1% (216/895) | 16.9% (151/895) |
| **extra (invented) items** | 315 | 100 | **135** |
| right kind, single-item | 86.5% (430/497) | 63.2% (314/497) | 81.3% (404/497) |
| title matches | 98.6% (424/430) | 98.4% (309/314) | 98.8% (399/404) |
| **date right** | 46.9% (97/207) | 94.6% (194/205) | **94.6% (194/205)** |
| explicit time right | 87.3% (137/157) | 87.4% (90/103) | 87.6% (127/145) |
| repeat right | 96.3% (78/81) | 82.9% (29/35) | 95.4% (83/87) |
| **whole item right, single-item** | 60.0% (298/497) | 56.3% (280/497) | **73.8% (367/497)** |
| latency p50 / p90 (model calls) | 1,861 / 2,308 ms | 1,801 / 2,676 ms | 1,729 / 2,093 ms |
| readings past the app's 12 s limit | 21 | 8 | 8 (→ the Mac) |

**What it means.** Against the reader as first shipped, on the same 1,200
TRAIN rows: wrong bookings on edits, deletes and questions 203 → 1, dates
right 47% → 95%, invented items 315 → 135, and a single item wholly right
60% → 74% — while about one create in six (16.9%) now waits for the Mac
instead of being guessed. The generalisation caveat stands: the guard fits
TRAIN's phrasings (on TEST the model-free guard catches 73.9%, above), so a
TEST read of this configuration is the next measurement, aggregates only.
What is left on TRAIN is the model's own inventions (135) — the target for
step 3, instructions tuned to this model.
