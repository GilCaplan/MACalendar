# Checkpoint sweep — run record (2026-09-11 09:57 → 2026-09-14 03:24 EDT)

**Read this first if you are picking the experiment up. It is FINISHED.** Both
boards are measured and archived, the sixth checkpoint was added afterwards and
both boards re-run for it, and nothing is in flight. What is left is
bookkeeping — plus one harness defect (the monitor, below) that the next sweep
must not inherit.

## What is being measured, and why

Six system states, the SAME rows, TODAY's scorer, one machine. `loop_log.csv`
is 21 readings taken under three harnesses with two declared comparability
boundaries, so its trajectory cannot be read end to end. This answers the
question the log cannot — and because every point is taken with one
instrument, there are no eras to reconcile.

    pre-engine-v2              the old brain, before the engine rewrite
    fast-lane-pre-integration  FastRule sandbox, pre-integration
    fastrule-v1                before the FastRule v2 restructure
    decompose-validate-v1      resolver wired into the live path
    main                       today
    one-shot-llm               ADDED 2026-09-13. `main`'s tree with the chain
                               OFF — transcript in, objects out, ONE model call
                               (`checkpoint_sweep.py:78-87` runs the main tree
                               under `MACALENDAR_ONESHOT=1`; the engine is
                               `assistant/engine/LLM_one_shot/`, commit 9481853)

Two boards, 600 clean test rows total:

    SEALED 300    dataset/inputs/test_split.json — count-correctness on
                  constructed compounds. + a second `main` pass for an ERROR
                  BAR (how much the number moves when nothing changes; the
                  LLM is ~75% deterministic run-to-run).
    PERSONAS 300  stratified from dataset/personas/personas.jsonl (2,520 rows,
                  every one split:"test") — robustness across six speaking
                  styles. Chosen because the sealed set took the LAST clean
                  draw from the 3000-pool: ITERATION_PROTOCOL makes the other
                  2,699 rows the training pool, and the pool's "aggregate
                  replays and threshold sweeps had touched all ranks".

## What ran, and when

    09-11 09:57 → 09-12 03:57  checkpoint_sweep.py --test          sealed pass 1, 5 checkpoints
    09-12 03:57 → 06:20        checkpoint_sweep.py --test          pass 2 — the error bar (main again)
    09-12 06:20 → 11:40        finish_experiment.sh → --personas   personas board, FIRST sampler
    09-13 20:11 → 21:11        --test, one-shot only               the 6th checkpoint, sealed
    09-13 21:11 → 22:33        --personas, one-shot only           the 6th checkpoint, first sampler
    09-13 22:38 → 09-14 03:24  --personas, RE-SAMPLED, all six     PERSONAS v2 — the board that stands

Each line is a `sweep-<timestamp>.json` in this folder; the per-run `results[].
rows_fingerprint` is what proves "same rows, one at a time". `finish_experiment.
sh` did its job: it was nohup'd and waited on the `### SWEEP COMPLETE ###`
marker, so it never started a second model job beside the first — one machine,
one Ollama, which CLAUDE.md forbids doubling up on and which was violated once
on 2026-09-11 (see CONTAMINATION.md). `_sweepwork/finish.log` ends
`### EXPERIMENT COMPLETE ### Sat Sep 12 11:40:29 EDT 2026`.

**The monitor never stopped, and that is a harness defect worth fixing before
the next sweep.** `scripts/sweep_monitor.py` is a `while True:` loop
(`:95-106`) whose only exit is `--once`. It has no completion check — it prints
`5/5 done` and sleeps another 600 seconds. The pass-1 monitor was still alive
at **pid 21022 on 2026-09-14, 2 d 21 h after launch** and two days after the
board it was archiving finished, re-snapshotting the same finished databases
every ten minutes. Two real costs:

- `dataset/runs/checkpoint-sweep-pass1/manifest.json` is the only one of the
  six archives still in thin monitor-written form — `rows` + `md5`, no
  fingerprint, no score, no wall — and it reads `checked_at
  2026-09-14T09:10:07`. `sweep_once` rebuilds `state` from scratch each pass
  (`sweep_monitor.py:60`) and overwrites the file wholesale (`:80`), so an
  enrichment written by hand survives at most ten minutes. **Kill the monitor
  first, then enrich.** It is also the manifest the `RESULTS.md` milestone
  table quotes.
- The archived `engine_run.db` / `calendar.db` mtimes under that run are the
  monitor's, not the experiment's, so they cannot be used to date anything.

Fix is small: give the monitor the completion marker it already prints, or run
it under a timeout.

## Where the data is

    dataset/runs/checkpoint-sweep-pass1/         sealed board, 5 checkpoints
    dataset/runs/checkpoint-sweep-pass2/         the error-bar pass (main again)
    dataset/runs/checkpoint-sweep-oneshot-sealed/    one-shot, sealed
    dataset/runs/checkpoint-sweep-personas-v2/   PERSONAS board — the one that stands
    dataset/runs/checkpoint-sweep-personas/      SUPERSEDED first sampler, kept inspectable
    dataset/runs/checkpoint-sweep-oneshot-personas/  one-shot on that first sampler
    <each>/manifest.json                         COMMITTED — identity record
    <each>/<tag>/engine_run.db                   gitignored, local-only

The sandboxes themselves live under the session scratchpad on /private/tmp and
are NOT durable. **The archive is the record** — it is snapshotted from live
databases every 10 minutes with sqlite `.backup`, so a lost scratchpad costs at
most the last 10 minutes, not the run.

## SEALED 300 — complete 2026-09-12, one-shot added 2026-09-13

Metric: **count-correctness** — did the command produce the right NUMBER of the
right KINDS of object. `rows_fingerprint 6dc8c8674e39:300` on every row of the
table. Aggregates only: this is `--test` data, where the rule is no row detail.

| checkpoint | raw | adj | complex | p50 | p95 | parse paths | wall |
|---|---|---|---|---|---|---|---|
| pre-engine-v2 | **79.0** | 78.7 | 54.4 | 53.2 s | 84.4 s | llm 300 (100%) | 274m |
| fast-lane-pre-integration | 77.3 | 77.7 | 57.3 | 52.3 s | 103.5 s | deep 300 | 276m |
| **fastrule-v1** | **79.7** | 79.7 | **60.2** | 48.2 s | 84.4 s | deep 300 | 245m |
| decompose-validate-v1 | 75.3 | 76.3 | 47.6 | 41.1 s | 53.6 s | deep 170 · fast 130 | 144m |
| main | 77.3 | 78.3 | 48.5 | **40.2 s** | **52.6 s** | deep 170 · fast 130 | 140m |
| main (2nd pass) | 76.7 | 77.7 | 48.5 | 40.5 s | 53.5 s | deep 170 · fast 130 | 143m |
| one-shot-llm | 66.0 | 67.3 | 36.9 | 5.4 s | 68.8 s | oneshot 300 | 59m |

**THE ERROR BAR, measured for the first time: 0.6 pt** — `main` twice on the
same 300 rows, 77.3 and 76.7. On this slice a gap under ~1 pt is noise.

Old brain: flat at ~92% on simple and medium, falls to 54.4% on complex;
compound families 50-63%. Every row a full model call. Garbage titles 0%, on
every checkpoint including the one-shot.

**Count-correctness did not improve across the rebuild; latency did, and so did
the fast path.** `main` (77.3) sits below the old brain (79.0) and below
`fastrule-v1` (79.7) — both gaps real against 0.6 pt — while p50 fell 53.2 s →
40.2 s. Split by where `main` routes the row, on the SAME 300: the 130 it sends
FAST go 88.5 (fastrule-v1) → **93.1**, and the 170 it sends DEEP go 72.9 →
65.3. That is the finding the whole retrospective turns on, and it is what
`RECOMMENDATIONS.md` is written against.

**The one-shot is the control, and it answers a real question.** Chain off, one
model call: 66.0 raw, 88.7 on simple, 74.0 on medium, **36.9 on complex** — so
the chain buys ~11 pt overall and ~12 pt on complex against the same model on
the same rows, at 2.4x the wall clock. "Just ask the LLM" is not a cheaper
`main`; it is a worse one that is fast. (Full block:
`sweep-20260913T2111.json`, `dataset/runs/checkpoint-sweep-oneshot-sealed/
manifest.json` → `count_ok_rate 0.66`.)

The same five-checkpoint table is banked as the 2026-09-12 milestone in
`dataset/RESULTS.md`, with the matched-row split and the flip counts. Its
"six sealed reads" caveat predates the one-shot and needs the correction
below.

## PERSONAS 300 — complete 2026-09-14

Six checkpoints, `rows_fingerprint 1a3064b09c1c:300` on every one — the same
300 rows, run one at a time. (The earlier `checkpoint-sweep-personas/` run is
SUPERSEDED: `537dcfbc4dbd:300` is the pre-fix sampler, which bucketed by
(persona, tier) and drew 49% two-event compounds against 6% in the real
distribution, with no queries or tasks at all. Use `-v2`.)

Metric: **count-correctness** — did the command produce the right NUMBER of the
right KINDS of object. Garbage-title rate is 0.0% on all six.

| checkpoint | count-ok | simple | complex | p50 | wall |
|---|---|---|---|---|---|
| pre-engine-v2 | 72.3 | 81 | 61 | 14.4 s | 80m |
| decompose-validate-v1 | 79.7 | 84 | 74 | 6.2 s | 31m |
| fastrule-v1 | **80.0** | 78 | **83** | 8.3 s | 54m |
| fast-lane-pre-integration | 79.0 | 76 | **83** | 9.6 s | 62m |
| main | 79.3 | 83 | 75 | **6.4 s** | 31m |
| one-shot-llm | 50.3 | 56 | 43 | 5.5 s | 28m |

The sealed board's shape reappears here on data it shares nothing with:
fastrule-v1 nominally top, main behind it by less than the measured error bar
(0.6 pt), the one-shot far below both. Two things the sealed board could not
show:

**Latency is where main actually won.** 14.4 s → 6.4 s p50 against the old
brain, 2.3x, and 23% under fastrule-v1 at an accuracy gap inside the noise
floor. That is the trade main made, and it is a good one.

**The deep track is still the hole, and it is the same hole.** main is +5 to +7
on simple and **−8 on complex** against fastrule-v1 and fast-lane, both of which
hit 83% there. That is the sealed board's fast +4.6 / deep −7.6 split, measured
again on different rows.

### The spread — what the personas board exists to measure

count-correctness per voice, n=50 each:

| voice | pre-engine-v2 | main | Δ |
|---|---|---|---|
| observant_student | 62 | **92** | **+30** |
| esl_speaker | 80 | 84 | +4 |
| freelance_consultant | 70 | 82 | +12 |
| retiree | 80 | 84 | +4 |
| household_parent | 76 | 72 | **−4** |
| uni_student | 66 | 62 | **−4** |

**The mean rose and the spread widened — 18 pt to 30 pt.** The rebuild moved
one voice enormously and left two slightly worse than the brain it replaced.
`observant_student` is the register the vocabulary, the Hebrew keyword lists and
the observance rules were all built for, so a +30 there is the system working as
designed; `uni_student` at 62% is now the worst voice on main and was NOT the
worst on the old brain. A headline that went 72.3 → 79.3 is hiding a robustness
regression for two speakers.

**This is a retrospective, not a direction.** Every personas row is
`split: "test"`. Per ITERATION_PROTOCOL and CLAUDE.md, no test result — "not a
number, not a slice, not a surprising delta" — may decide what to improve. If
the deep track on complex rows or the two weak voices are to be worked on, the
hypothesis has to come from training-pool failures and be measured there.

## Scoring it

    from scripts import score_dataset_run as sc
    prov = sc.load_provenance(pathlib.Path("dataset/inputs/hwu64_sample.json"))
    sc.score_db(pathlib.Path("dataset/runs/.../engine_run.db"), prov)

The personas half uses `checkpoint_sweep._score_personas(db, rows)` instead
(`checkpoint_sweep.py:532`) — score_db derives expectations from three compound
buckets and 65 persona rows want (2 events, 1 task), which no bucket expresses.
Same PREDICATE, exact expectations. That is what makes a combined number
honest: combine as `ok = rate x n` per half and sum, which needs no row detail
— the sealed half is `--test`, where the rule is aggregates only.

## Known caveats to carry into the report

- **SEVEN reads of the sealed 300**, not six: 5 (pass 1) + 1 (the error-bar
  pass) + 1 (the one-shot, 2026-09-13). `dataset/RESULTS.md`'s milestone
  caveat still says six and predates the seventh. Deliberate one-off for a
  retrospective, NOT a precedent — no test result may drive what to improve.
  (Four pre-flight smokes of 2-12 first-N rows also ran — `sweep-20260911T0941/
  0942/0953.json` and `sweep-20260913T2011.json`; the archive does not record
  which input file a `--rows` slice came from, so they are not counted here
  either way.)
- **pre-engine-v2 latency, ids 131-150** contaminated by a second model job
  (see CONTAMINATION.md in the run's scratch dir). Quantified: p50 53.1 -> 52.1 s,
  p95 84.3 -> 79.6 s excluding them. Accuracy untouched. Report both.
- **The live API was left running**, so any command Gil gave during the sweep
  inflates that window's latency. Accuracy unaffected.
- **The sandbox guard fired on pass 1 AND on personas v2. Both investigated,
  both CLEARED — but it is the same hole each time.** The guard hashes the real
  stores before and after (`checkpoint_sweep.py:469-490`) and exits 2 on any
  change, because a change means *either* a leak *or* that the assistant was
  used during the run. Pass 1: three to-dos Gil created Friday afternoon, none
  in any sealed transcript. Personas v2 (`_sweepwork/personas_v2.log`, exit 2,
  `calendar.db`): four rows written through the live stack at 00:23-00:25 on
  2026-09-14 — events 1996/1997 "Walk Jada", todos 176 "Buy Dad Whiskey
  Present" and 181 "Check Haxaga Projects". None of the four appears in
  `personas.jsonl` or in any of the six sandboxes' `rows.json`, so it is live
  usage, not a leak; the board stands and its numbers are the ones above.
  **Next sweep: stop the live stack, or the guard will keep crying wolf and
  will be ignored the day it is right.**

### Resolved during the run

- **`result.json` carried no `wall_s`** for a finished checkpoint — the parent
  computed the enrichment and kept it in memory, so the DURABLE record had no
  wall time and no scores, and losing the process lost a finished checkpoint's
  timing. Fixed the same evening in `121d443` (13 minutes after this file first
  flagged it): `checkpoint_sweep.py:441-452` writes the enrichment back through
  `_persist()`. Pass 1 was already running under the old module, so its
  archived `result.json` files still lack the field and pass 1's wall times
  live only in `sweep-20260912T0357.json`; every run from pass 2 on persists
  both `wall_s` and the `scored` block (e.g.
  `dataset/runs/checkpoint-sweep-pass2/main/result.json` → `wall_s 8561.1`).
