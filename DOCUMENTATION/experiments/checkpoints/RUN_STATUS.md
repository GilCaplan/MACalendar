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
