# Real-speech plan — aim the engine at what Gil actually says

_Written 2026-09-18 for the session that picks this up cold. Read `STATUS.md`
and `CLAUDE.md` first; this file assumes both. Every path below was verified
against the tree the day it was written — if one is wrong, the tree moved, so
`git log -- <path>` before assuming the plan is._

## 0 · Why this plan exists, in one paragraph

Three FastRule cycles on 2026-09-17/18 (`fastrule/experiments/RESULTS.md`
cycles 20–22) won +4.2 pt handle-rate on the 7,200-row corpus — real, banked,
and each one a *reader gap* in `assistant/intent/rule_parser.py`. But the corpus
is `generate.py` template text, and on Gil's own commands the fast path stands
at **12 approved to 24 flagged** (all-time, `nlu_memory.db`). Reading the 24:
~9 are STT garbage committed as a title ("Poe Konaight", "WalkMoxDog"), ~5 are
disfluency ("No, I said that", "one moment, bear with me"), one is a stutter
over-split, the rest compounds and "230PM"-style times. **The corpus contains
none of the first three classes**, and the stage that owns them — `ingest` — is
the only stage with no dataset and no board. So: build the instrument that sees
real speech, then fix the largest thing it shows, then cut the latency that
makes every deep command cost 40 s. Corpus cycles continue as a background loop.

## 1 · Ground rules that will bite (all bought this session)

- **Never write to a real store.** Set every `MACALENDAR_*` override
  (`CLAUDE.md` § Personal data) *before* importing `assistant`, including
  `MACALENDAR_MODEL_LOCK`, `MACALENDAR_TRACE_BUS`, `MACALENDAR_UI_STATE`. Post
  `"source": "test"`. Check `md5 ~/.assistant_tools/vocab.json` before and after
  anything you are unsure of.
- **`MACALENDAR_LLM_PRIORITY=background`** in every script's env block.
- **Never name a scratch file after an importable module.** A scratch `attr.py`
  shadowed the `attrs` package (`rich` → `httpx` → `weasel` → spaCy) and hung
  every diagnostic for an hour. When something hangs, reach for
  `faulthandler.dump_traceback_later(25, exit=True)` before guessing.
- **Run diagnostics with `python -u`.** Buffered stdout made a working script
  look hung.
- **The checkout is shared with another live session.** Commit early; their
  `git stash` swept uncommitted engine work once. Recover with
  `git checkout stash@{0} -- <paths>`, never `stash pop`.
- **One change, one measurement, one commit.** Never bundle. Bank in the
  owning stage's `experiments/RESULTS.md` with DATASET · METRIC · SLICE · what
  it MEANS, and **n on every percentage**.
- **Read the rows, not the sample.** Cycle 22's diagnosis came from six rows;
  the nineteen-row population contradicted it and the commit message is wrong
  forever. Diagnose on the population.
- **The sealed 300 and the FastRule test half are never read** except at a
  milestone Gil names.
- **No structural change to the chain.** Stage contracts are frozen
  (`tests/unit/test_engine_contracts.py`). Everything here is inside a module.
- **Implementation fixes inside segmentation and fastrule are allowed; design
  changes are not** (Gil, 2026-09-12). Phase 4 is where that line is closest —
  it is gated on his ruling.

## 2 · Starting state (2026-09-18)

- `main` at `2bc032c`. Engine work on `fastrule-recurrence-bounds`
  (`aa1fac7`, `1d72d1a`, `2c6a29d`) — fast-forwardable, not yet merged.
- FastRule product-shape board, train half, 3,200 atomic rows: handled
  **72.4%**, correct-on-handled 94.1%, date right 93.5% (n=650), DESTRUCTIVE 28,
  half-executed 72, `BOUNDED SERIES` carried an end 75.8% / FIRES FOREVER 5.
  Baseline file: run `python -m assistant.engine.fastrule.experiments.fastrule_shape --split train` (65 s, no model).
- Real usage (`~/.assistant_tools/nlu_memory.db`, `examples`, `source!='test'`):
  **95 commands, 92 reviewed, 16 corrected with `correction_json`, 16 approved,
  41 rejected with no gold.**
- Sealed 300 (retrospective only): fast path 93.1%, deep path 65.3%.
- Deep command: ~33 s of a 37 s total is model time; `llmjudge/rescue.py:241`
  asks the model **serially per item**.

---

## Phase 1 — the real-usage board  (build this first; everything else is judged on it)

**Goal.** A repeatable, sandboxed replay of Gil's real commands with his own
verdicts as gold, so that direction comes from real failures and every later
change is scored on real speech. This is **not** the synthetic
`dataset/realspeech/` Gil dropped ("dont do the real speech dataset") — it is
the history that already exists and grows every week.

**Deliverable.** `scripts/real_usage_board.py` and
`DOCUMENTATION/experiments/real_usage/RESULTS.md`, plus one line in
`scripts/weekly_review.py`'s "What to do with this" pointing at it.

**Input.** A read-only copy of `nlu_memory.db` (`sqlite3` URI
`file:...?mode=ro`, or copy the file to the scratch dir first). Rows where
`source != 'test'`. Key on `COALESCE(NULLIF(raw_transcript,''), transcript)` —
CLAUDE.md: every join against the pool keys on the verbatim input.

**Gold, three tiers — report them separately, never pooled:**

| tier | rows | gold | metric |
|---|---|---|---|
| corrected | 16 | `correction_json` (the actions Gil said were right) | object-correct: action, title, date, start/end, recurrence, recur_until — per field and all-fields |
| approved | 16 | `actions_json` (what the engine did, and he accepted) | regression only: the replay must still produce it |
| rejected | 41 | none | flag proxy: does the replay produce the SAME wrong output? (unchanged wrong ≠ progress) |

Headline is **corrected-tier all-fields-correct, n=16**. Say n=16 every time.
It is small; it is also the only non-circular number this project has.

**Sandbox.** Copy `scripts/checkpoint_sweep.py`'s pattern exactly:
`create_app()` + Flask test client + `POST /voice/text` (never a live socket —
`tests/conftest.py` refuses loopback:8080 for a reason); scratch stores via the
env overrides; `reset_calendar()` (`checkpoint_sweep.py:149`) before each row;
**the md5 guard on the real stores** (`:474–492`, asserted at `:813`) — copy it,
and fail the whole run if any real store moved. Checkpoint with
`assistant/checkpoint.py` (`Checkpoint(name, total)`, `has()/record()`), one row
per line, fsynced, resumable, with a rate+ETA line — Board D's lesson.

**Caveat to build in.** `reset_calendar()` empties the store, so every
update/delete meets an empty calendar and `TargetNotFound` fires. For the
corrected tier, seed the scratch store from `example_records` (the rows the
command actually touched) where the correction references an existing record;
otherwise score update/delete on *target text* (`match_title`, `match_date`)
rather than on execution. Say which in the report.

**Failure taxonomy — classify every non-correct row by hand ONCE, store it in
`DOCUMENTATION/experiments/real_usage/taxonomy.jsonl` keyed on the verbatim
transcript, and report the breakdown every run:**

    stt-garbage      a non-word or misheard name reached a title/target
    disfluency       retraction, filler, false start survived into the parse
    stutter-split    repeated words produced an extra item
    time-format      "230PM", "8.30am", "11.15 AM tomorrow" misread
    compound         right items, wrong count or wrong pairing
    reader-gap       a corpus-style gap (date/cadence/bound/title) — the FastRule loop's kind
    other

The breakdown, not the headline, is what picks Phase 2's target. Expect
`stt-garbage` + `disfluency` to dominate; if they do not, **stop and say so
before building Phase 2** — the plan's premise would be wrong.

> **THEY DO NOT. Measured 2026-09-18, the board's first run** (n=50 non-approved
> rows, `experiments/real_usage/RESULTS.md`):
>
>     generic-title   21  42%      <- the largest, by a distance
>     disfluency       8  16%
>     stt-garbage      6  12%
>     anaphoric-edit   5  10%
>     other            5  10%
>     compound         3   6%
>
> The corrected tier agrees from the other direction: **`title` 33.3% right
> (n=18) against `date` 78.6% (n=14)**. And the approved tier shows the title
> extractor has REGRESSED on commands Gil blessed — `"Movie at Lincoln AMC"` is
> now `"lincoln"`, `"mark's dog"` is now `"dog"`.
>
> **So the phase order below is wrong.** Phase 2 (unknown words) addresses 12%;
> Phase 4a (the title extractor) addresses 42%, is the worst field, and is
> actively regressing. 4a is the highest-value work available and it is the one
> gated on a ruling — **DEVQA Q26**. Phase 3 (latency) is unaffected and can run
> in parallel. `generic-title`, `anaphoric-edit` and `non-command` were added to
> the taxonomy on that run, each with a reason recorded in `taxonomy.jsonl`.

**Acceptance.** Runs end-to-end in one command, resumes after `kill -9`,
guard passes, writes RESULTS.md with all three tiers + taxonomy + latency p50
per parse path, and a second run on unchanged code reproduces the numbers
(that is the error bar — record it).

---

## Phase 2 — an unknown word on the instant commit asks instead of committing

**Goal.** Stop the fast path committing STT garbage as a title in 400 ms. This
targets the taxonomy's expected largest class.

**Where the pieces already are:**
- `assistant/stt/vocab.py` — `get_vocab()`, `apply_vocab()`, `phonetic_key()`,
  `_english()` (reads `/usr/share/dict/words`; **a missing list silently turns
  the real-English-word guard OFF** — CI installs `wamerican` for this).
- `assistant/engine/ingest/repair.py:188 uncertain_words(text)` — already
  computes what ingest is not confident about; today it is advisory only.
- `assistant/engine/llmjudge/gatekeeper.py` `class Gatekeeper` (used by
  `fastrule/fastrule.py`) — the REFUSAL reasons; `fastrule/build.py:581` is
  where `generic-title` is raised.
- The confirm gate: `assistant/engine/__init__.py::_confirm_proposal` is checked
  on **both** the fast and deep branches since 2026-09-17;
  `fastrule/fast_track.py::fast_propose` sets `slots["confirm_create"]` (see the
  range-date code there — copy its two guards: `state.supports_confirm`, single
  item only). `_create_spec` handles **creates only**; flagging an update/delete
  nulls its intent — so a non-create with an unknown target REFUSES (new reason,
  class REFUSAL), exactly as `range-date-target` does.

**Spec.**
1. Define *unknown token*: alphabetic, not in `_english()`, not in the vocab
   (after `apply_vocab`), not a known category/attendee/known name from the
   store, not a number/time/date token, length ≥ 3. Put the predicate in
   `assistant/stt/vocab.py` next to `_english()` so there is one definition.
2. In `fast_propose`, after FastRule commits a **create**: if the title contains
   an unknown token → `slots["confirm_create"] = True`, and put the vocab's best
   phonetic suggestion (if any within the threshold `vocab.py:40` documents)
   into the proposal summary — *"Poker night tonight at 9pm?"*. Trace step on
   the RULE stage saying which word.
3. Non-create with an unknown token in `match_title` → `FastRuleResult(False,
   …, "unknown-target")`, `_REASON_CLASS["unknown-target"] = REFUSAL`. The deep
   track may resolve it; it must not execute it.
4. Config switch `engine.confirm_unknown_words: bool = True` in
   `assistant/config.py`, mirrored in `config.example.yaml`. **Default ON** —
   consistent with Gil's Q22 ruling (ask, don't guess). Log it as **DEVQA Q24**
   so he can veto; do not wait on him to build it.

**Tests.** `tests/unit/test_confirm_create.py` already has the fixtures
(`real_actions`, Flask `client`, the "deep track must RAISE" pattern). Add:
unknown title → `parse: "confirm_create"` with the suggestion in `message`;
known title unchanged; unknown `match_title` on delete → deferred with
`unknown-target`; `_english()` missing → the gate is OFF and a test says so
loudly rather than silently.

**Measure.** Phase 1 board (corrected tier all-fields, and the `stt-garbage`
class count — predicted to fall to near zero as *silent* failures, reappearing
as confirmations) **and** the FastRule board (handle-rate will DROP by the
share of corpus titles with unknown tokens — the corpus has names like
"Harper", "Dana"; measure how many, and if it is more than ~1 pt, tighten the
predicate with the store's known names before shipping). DESTRUCTIVE must be
flat or down.

---

## Phase 3 — deep-track latency: instrument, then cut

**Goal.** A deep command costs ~40 s and p50 47 s on real usage; the assistant
*feels* like that number.

**3a — instrument first (do not skip).** `assistant/llm_bus.py::record(...)`
takes `run` and `caller`; the rescue path passes neither — `llm_calls.jsonl` has
**no run id on rescue calls and 301 of the last 554 real calls have caller
`unknown`**, so calls-per-command is currently unknowable. Thread
`state.run_id` and a real caller string through `llmjudge/rescue.py::_ask_the_model`
and every other `hold()` site the tree grep in `test_model_protocol` enumerates.
Then, from the Phase 1 board's run: **calls per deep command (p50/p90), ms per
call, retries per command.** Find the 301 unattributed callers while you are
there — if any are a fifth door to ollama, CLAUDE.md's gate rules apply.

**3b — cut, based on 3a.** Two candidates, pick by the numbers:
- **Batch:** one model call carrying every deferred item with its
  `Defer.partial` hint, schema-constrained, instead of the serial loop at
  `rescue.py:241`. Fewer round-trips; one longer generation.
- **Stream:** commit the items FastRule handled immediately (they already have
  intents) and return the rest as they resolve, through the verify-token
  contract the clients already speak (`_start_background_verify`).
Measure p50/p95 on the Phase 1 board per parse path, plus count-correctness on
the corrected tier — latency must not be bought with accuracy. Ollama serialises
generations internally on this Mac; do not assume parallel requests help.
Measure.

---

## Phase 4 — gated on Gil, do not start without a ruling

**4a — the title extractor as a subtractive design.** `rule_parser.py::_extract_title`
walks `noun_chunks` for the first `dobj`. It fails on "wash and fold the
laundry", on bare object lists (fixed once, `a42a48e`), and on a cadence adverb
right after the title ("book annual checkup **monthly** at 8:30pm" — 13 of 19
bounded-row deferrals, cycle 22 correction). FastRule's own RESULTS calls the
title "the one genuinely ours", 62.9%. The alternative: the title is *what is
left* after every span another reader has claimed is blanked — temporal
(`result["spans"]`), cadence (`recurrence.py`'s own table), the series bound
(cycle 22 already masks it), attendee ("with X"), location, quantity, the
framing verb. Contracts untouched; a change of approach inside one function and
its two callers. **Ask first** — Gil: *"I don't really want to make structural
changes if I don't have to."*

**4b — the temporal resolver.** `_extract_temporal` is 320 lines with readers
bolted on and no record of which reader claimed which span with which
provenance. That is the cause of three bugs introduced this session (the
`_source` conflation, the bound overwriting the anchor, the trailing time
eaten). A resolver of typed readings `(kind, value, span, provenance)` with one
precedence pass and one span-blocking pass would end the class. Inside one
module; still a rewrite. **Ask first**, and sequence it after Phases 1–2 so the
real board can judge whether it earns its risk.

---

## Background loop — FastRule reader gaps, corpus-measured (continue between phases)

Registered in `fastrule/experiments/RESULTS.md` after the cycle-22 correction:
1. **Title on a cadence adverb** — blank the cadence word the way temporal spans
   are blanked; predicted +0.4 pt handle-rate (13 rows). *If Phase 4a is ruled
   in, do it there instead; do not do both.*
2. **Missing cadences** `"every weekend"`, `"once a week"` in
   `assistant/intent/recurrence.py`'s table — predicted +0.2 pt; rounding must
   be **announced** (`recurrence_rounded_from`), never silent.
3. Filed, untouched, in `TASKS.md`: coordinated-verb titles ("wash and fold"),
   the todo-title split branch carrying date words, the `_source` provenance
   conflation at `rule_parser.py` (the 0.95 multiplier fires on every date-only
   command). Each is its own cycle.

---

## Reporting — every number, every time

DATASET · METRIC · SLICE · MEANING, with **n**. "72.4%" is not a result;
"handle-rate 72.4% on the FastRule train half's 3,200 atomic rows — FastRule
acts on 134 more single-item commands than yesterday" is. Actual vs predicted,
and the delta explained, in the owning `RESULTS.md`. A cycle ends by
registering the next one. Stop only for a design decision or when three cycles
move nothing past the error bar — then change the instrument and say so.

## Open for Gil (log answers in `DEVQA.md`)

- **Q24 — unknown-word confirmations, default on?** Built on a switch either
  way; the default follows Q22.
- **Q25 — is the real-usage board the primary direction-setter**, with the
  corpus boards as regression floors? CLAUDE.md already ranks real usage first;
  this asks whether ITERATION_PROTOCOL's "direction from the training pool"
  now means this pool.
- **Q26 — Phase 4a / 4b: allowed?** Both are inside one module; both are
  rewrites.
