# STATUS — where we are

**One-screen reference. A fresh conversation reads this first, then CLAUDE.md.**
Keep it current and short; details live in the files it points to. Every number
names its dataset, split, n and metric. _Rewritten 2026-09-26 — the long
narrative it replaced (to 2026-09-20) is in git: `git show 430a1c25:STATUS.md`._

## The system

`assistant.api` is the brain's front door and `assistant/engine/` is the brain
(`assistant/engine/ARCHITECTURE.md` is the map, `DOCUMENTATION/ENGINE.md` the
stage contracts). `Engine.run` tries the **fast track first** — FastRule on the
whole command, no model — and only when it declines runs the deep chain:
ingest → segmentation → decompose_validate → fastrule → llmjudge → commit.
LLMSeg is wired and INERT; the judge makes no model call; the model is called by
`llmjudge/rescue.py` (parsing what FastRule deferred) and the judge's loop-back.

## Where it stands (2026-09-26)

**As production runs it** — Board D `--product` (front door first), FastRule
7,200 set, **TRAIN**, 1,200 rows, seeded, fresh, `299aeb0f`
(`llmjudge/experiments/runs/board_d_train_1200_20260926T0342.json`):

| metric (`dataset/METRICS.md`) | as shipped | deep chain only (`dc884b55`) |
|---|---|---|
| headline correct (action + title) | **92.7%** (1112/1200) | 92.2% |
| count-correct | **92.6%** (851/919) | 91.0% |
| objects F1 | **95.8%** | 95.2% |
| rows needing a model call | **19.6%** | 40.8% |
| harm | 152 | 129 |
| vague target refused | 67.4% (29/43) | 81.4% |

Reading: the fast path now helps the product instead of costing it, at half the
model calls. At `04810fae` the same board read vague target refused **79.1%**
(34/43) and harm **142**, headline unchanged — but its date and latency lines
are void: the run paused ~15 h while the Mac slept and Board D's clock ran on
(fixed, `6a08b0df`). Before the pause, date right read 95.8% (n=192) against
90.0% at `299aeb0f`.

**The fast path alone** — FastRule shape board, FastRule 7,200 set, `04810fae`:

| line | TRAIN (atomic n=4,068) | TEST (atomic n=1,472) |
|---|---|---|
| handled (committed) | 75.2% | 70.5% |
| correct-on-handled | 96.7% | 83.2% |
| harm (wrong commits) | 113 (101) | 176 (174) |
| title word F1 (precision · recall) | 92.1% (91.6 · 96.8), n=2,251 | 78.3% (71.8 · 96.0), n=674 |
| date right | 95.0% (n=1,061) | 93.3% (n=345) |
| explicit time · range · cadence | 99.8% · 100% · 93.1% | 99.5% · 100% · 88.2% |
| invented a time | 0.0% (n=527) | 0.0% (n=137) |

The train/test gap is mostly TITLE PRECISION on unseen phrasings (leaked words:
time residue and unclassified leftovers). The fix is more varied TRAIN
phrasings, never the test rows.

**Real usage** — the only instrument on real speech, and it outranks every
board: last read 2026-09-22 (`DOCUMENTATION/experiments/real_usage/RESULTS.md`,
run 4, 75 reviewed commands). It needs more reviewed usage before it can carry a
claim; nothing since has re-read it.

**SEALED 300 (TEST)** — milestone only, aggregates only: last read 2026-09-22,
count-correct 73% raw / 75% adjusted (`dataset/RESULTS.md`). Never a
hypothesis source.

## What changed this week

Rulings **Q49–Q58** (top of `DEVQA.md`) — sequences (Q51), a role call is an
event + a linked to-do (Q50), list management is junk (Q52), one time reader
(Q53), and on 2026-09-26: the 4-hour cap is only for ends the engine made (Q54),
errand verbs (Q55) and the person (Q56) stay in titles, a series with no end
gets a per-cadence default end (Q57), the fast-path fence is retired with
conditions (Q58). Built: linked to-dos (`FEATURES.md`), sequences and chaining,
event-default settings, `assistant/common/`, the measuring tools (Board D
`--product`, `rescore`, full scoring, title similarity, range / cadence / kind /
target lines). Numbers per cycle: `assistant/engine/fastrule/experiments/RESULTS.md`
and `assistant/engine/llmjudge/experiments/RESULTS.md`.

## Next

1. **Build Q54–Q57** (queued at the end of `DOCUMENTATION/TASKS.md`): the cap
   spares a stated end; relabel the gold for Q55/Q56; the default series end
   and its settings (Mac + iPhone).
2. **Harm on the fast path**: an update/delete aimed at a to-do whose name
   holds a verb ("rename submit the report to …") goes to update_event — on
   BOTH tracks.
3. **Real usage**: re-read the board once there is new reviewed usage.

## Standing rulings worth remembering

- The real-speech dataset is DROPPED (the artefacts stay in `dataset/realspeech/`).
- Segmentation and FastRule: implementation fixes yes, structure no (Gil,
  2026-09-12). Standing preference: *"i don't really want to make structural
  changes if i don't have to."*
- The Live Activity card is the day's AGENDA, not a countdown (DEVQA Q23).
- A measurement must be fresh, seeded, watchable, resumable — and read on every
  metric, not the headline (CLAUDE.md).

## Working notes

- The API reloads itself; the calendar GUI and the thinking HUD do not — restart
  them by hand. The phone needs a reinstall.
- One model-loading job at a time; never edit files under `assistant/` while a
  board replays them.
- `git status` before assuming HEAD is what is on disk.
