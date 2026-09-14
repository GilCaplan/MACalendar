# Checkpoint sweep — run status (started 2026-09-11 09:57 EDT)

**Read this first if you are picking the experiment up.** It is running
unattended; Gil is away until ~2026-09-13.

## What is being measured, and why

Five system states, the SAME rows, TODAY's scorer, one machine. `loop_log.csv`
is 21 readings taken under three harnesses with two declared comparability
boundaries, so its trajectory cannot be read end to end. This answers the
question the log cannot — and because every point is taken with one
instrument, there are no eras to reconcile.

    pre-engine-v2              the old brain, before the engine rewrite
    fast-lane-pre-integration  FastRule sandbox, pre-integration
    fastrule-v1                before the FastRule v2 restructure
    decompose-validate-v1      resolver wired into the live path
    main                       today

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

## What is running right now

    scripts/checkpoint_sweep.py --test          the sealed board (pass 1, then pass 2)
    scripts/sweep_monitor.py                    archives every 10 min
    MACalendar-checkpoints/_sweepwork/finish_experiment.sh
                                                waits for the sealed board, THEN
                                                runs the personas board

`finish_experiment.sh` is nohup'd and waits on the `### SWEEP COMPLETE ###`
marker, so it never starts a second model job beside the first — one machine,
one Ollama, which CLAUDE.md forbids doubling up on and which was violated once
already on 2026-09-11 (see CONTAMINATION.md).

## Where the data is

    dataset/runs/checkpoint-sweep-pass1/        sealed board, 5 checkpoints
    dataset/runs/checkpoint-sweep-pass2/        the error-bar pass
    dataset/runs/checkpoint-sweep-personas/     personas board
    <each>/manifest.json                        COMMITTED — identity record
    <each>/<tag>/engine_run.db                  gitignored, local-only

The sandboxes themselves live under the session scratchpad on /private/tmp and
are NOT durable. **The archive is the record** — it is snapshotted from live
databases every 10 minutes with sqlite `.backup`, so a lost scratchpad costs at
most the last 10 minutes, not the run.

## Results so far

| checkpoint | raw | adj | complex | p50 | parse paths |
|---|---|---|---|---|---|
| pre-engine-v2 | **79.0** | 78.7 | 54.4 | 53.2 s | llm 300 (100%) |

Old brain: flat at ~92% on simple and medium, falls to 54.4% on complex;
compound families 50-63%. Every row a full model call. Garbage titles 0%.

### PERSONAS 300 — complete 2026-09-14

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

The personas half uses `checkpoint_sweep._score_personas(db, rows)` instead —
score_db derives expectations from three compound buckets and 65 persona rows
want (2 events, 1 task), which no bucket expresses. Same PREDICATE, exact
expectations. That is what makes a combined number honest: combine as
`ok = rate x n` per half and sum, which needs no row detail — the sealed half
is `--test`, where the rule is aggregates only.

## Known caveats to carry into the report

- **pre-engine-v2 latency, ids 131-150** contaminated by a second model job
  (see CONTAMINATION.md in the run's scratch dir). Quantified: p50 53.1 -> 52.1 s,
  p95 84.3 -> 79.6 s excluding them. Accuracy untouched. Report both.
- **The live API was left running**, so any command Gil gave during the sweep
  inflates that window's latency. Accuracy unaffected.
- **6 reads of the sealed 300.** Deliberate one-off for a retrospective, NOT a
  precedent — no test result may drive what to improve. Bank this in RESULTS.md
  when the board lands.
- `result.json` records `wall_s` as 0 for a finished checkpoint — a reporting
  bug in the sweep, not the measurement. Row data and timings are intact. Fix
  after the run.
