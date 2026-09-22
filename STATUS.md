# STATUS — where we are

> Naming note (2026-09-08): `crosscheck.py` is now
> `assistant/engine/llmjudge/llmjudge.py` and `generate.py` is
> `assistant/engine/fastrule/objects.py`. Older entries in other docs use the
> old names; the chain is in `assistant/engine/ARCHITECTURE.md`.

**One-screen reference. A fresh conversation reads this first, then CLAUDE.md.**
Keep it current and short; details live in the files it points to.

_Updated 2026-09-20 — the "In flight" section is current; the sections below
it were rewritten against the code on 2026-09-14 and still hold. Every claim
cites a file, a commit or a run._

**2026-09-15 — `engine-component-folders` merged (row 91, TASKS.md).** 34
commits, unmerged since `46f7967` (Phase A), are in: FastRule restructured into
`build.py`/`fast_track.py` (the "CONVERTER" design — `build(item) -> BuildResult`,
no model, no opinion about committing), LLMJudge's stage-isolation work
(`rewrite.py`, `verdict.py`, `rescue.py`, `findings.py`, `render.py`), and
Label's two learned classifiers. The branch's own numbers, carried forward
because HEAD had no equivalent measurement:

    LLMJudge sealed board (623 cases, test half):  catch 97.5%  ·  false-flag 2.3%
    LLMJudge train half (753 cases):               catch 99.5%  ·  false-flag 2.0%
    Label, novel vocabulary:  event 49.1% vs rules 33.0%  ·  tasks 46.8% vs 38.3%
    Label, real usage:        tasks 95.7% exact-set vs rules 88.6% (macro F1 41.1->49.6)
    Label, persona spread:    rules 28.5 pt  ·  model 10.4 pt

Label's classifiers ship **OFF by default** — tasks are ready to enable, events
are not (real-usage gold is only 14 rows, 4 of them test traffic; the authored
vocabulary doesn't cover Gil's Hebrew/Jewish terms and named people). Full design
and cycle logs: `assistant/engine/llmjudge/PLAN.md` §6 + `experiments/RESULTS.md`,
`assistant/engine/label/ARCHITECTURE.md` + `experiments/RESULTS.md`.

**One real regression found and ported in with the merge, now fixed and
tested**: a two-item fast-path command gave both items the whole transcript
as their text instead of just their own words — found comparing the branch's
replacement code against what HEAD's own 50 commits had fixed in the file
the branch deletes, `fastrule/objects.py`. Ported `_fast_item_words` into
`fastrule/fast_track.py`, wired into `fast_propose`, 4/4 tests green
(`test_engine_llmjudge.py`).

**A second suspected regression turned out not to be one.** `asked_fastrule`
(keyed on an item's text alone instead of `spoken()`, colliding "gym at 7"
with "gym at 9") protected a per-item FastRule recheck inside the OLD
`objects.py::_parse_item` — "FastRule first, the LLM for what it can't",
re-asked per item. That whole mechanism is GONE on purpose in the 2026-09-10
restructure (`fastrule/stage.py`'s own docstring: "the whole fast track,
re-run per item... on an item already atomic BY CONTRACT" is exactly what was
removed); a deferred item now goes straight to the model
(`llmjudge/rescue.py::_ask_the_model`), so there is no redundant FastRule call
left for a memo to guard against. `state.asked_fastrule` is still a field on
`EngineState` (frozen contract) but confirmed by grep to have no reader or
writer anywhere in the codebase — dead, not broken. `test_engine_generate.py`'s
test for it removed, with the same finding recorded there.

**Also found and fixed while verifying these**: `fastrule/stage.py`'s `_flag()`
tagged trace steps `fastrule_result=kind` but the review panel
(`thinking_panel.py`) reads `data["outcome"]` — two independently-written
pieces of the merge that never agreed on a key name, so a flagged item
(`not_an_ask` / `bad_item`) reached the trace but the panel could never draw
it. Fixed by also writing `outcome=kind`; `test_panel_agreement.py` and
`test_thinking_hud.py` (both had to be repointed off the deleted
`fastrule.objects` too) confirm it end to end.

## In flight: the improvement loop, resumed 2026-09-20

**ENGINE CYCLES RUN AGAIN** (Gil, 2026-09-20, DEVQA Q31), ending the
2026-09-07 stage-isolation pause. The day's sequence, all on dev-100 (the
same 100 stratified train rows; `dataset/RESULTS.md` has every row read):

    run 22  74%  the checkpoint — 26 misses read from X1→X4 boundaries, a plan of eight items
    run 24  76%  the loop-back's model round (two tiers: code, then the model writes X1'; DEVQA Q30)
    run 25  83%  plan items 1–3: the kind tagger, FastSeg's hard seams, four fast-path holes
    run 26  85%  two tagger/converter residues — deep path 62 → 76%, item F1 75 → 87, failures 26 → 15

Every one of those was boarded alone on its stage first and moved the stage
board by nothing or two rows: the misses were seams no stage corpus holds,
which is why the pause ended. The queue is `DOCUMENTATION/TASKS.md` ("THE
CHECKPOINT'S QUEUE"): item 4 (the judge's exhaustion path commits a
subject-less object) is next; items 5–7 follow; item 8 is three rulings for
Gil (the untimed event's default, what "start a new list" creates, whether an
offset or a recurrence on "remind me to" makes an event) that gate 5 of the 15
remaining rows. Real usage (`weekly_review`) still outranks every board.

_(The stray `scripts.sweep_monitor` process this section used to warn about is
gone — checked 2026-09-20, none running, the manifest clean.)_

## Read the retrospective — nothing else points at it

`DOCUMENTATION/experiments/checkpoints/` holds `RUN_STATUS.md` (the boards, the
caveats, the per-voice spread) and `RECOMMENDATIONS.md` (what they say to fix).
**A repo-wide `git grep` for either filename returns ZERO hits** — no tracker,
no doc, no CLAUDE.md path reaches them, so the retrospective is invisible from
the read order every session follows. That is why its three findings sat
unnoticed. This paragraph is the link; keep it until TASKS.md carries one too.

## The state

- **The brain is `assistant/engine/`** (frozen stage contracts), LIVE in
  production since 2026-09-04 (merge `bce502e`). `DOCUMENTATION/ENGINE.md` is the
  contract reference; `assistant/engine/ARCHITECTURE.md` is the map.
- The old brain is archived at `retired/old-brain-v1/` (tag `pre-engine-v2`), and
  `fastrule-v1`, `decompose-validate-v1` and `fast-lane-pre-integration` are tags
  too — which is what made the checkpoint sweep possible. Rollback:
  `git reset --hard 4c61f82`, then relaunch.

## The last measurements

The first two are **retrospective only** — every row in both is `split:"test"`,
and no test result (not a number, not a slice, not a surprising delta) may decide
what to improve; a hypothesis comes from training-pool failures and is measured
there. The third, real usage, is the one that may direct work.

**SEALED 300 · count-correctness · `dataset/inputs/test_split.json`, fingerprint
`6dc8c8674e39:300`** (`dataset/RESULTS.md:1547-1655`, sweep 2026-09-12):
pre-engine-v2 **79.0** · fastrule-v1 **79.7** · fast-lane-pre-integration 77.3 ·
decompose-validate-v1 75.3 · **main 77.3** · one-shot-llm 66.0 — seven sealed
reads spent, a deliberate one-off for a retrospective and **not a precedent**.
**The error bar was measured for the first time by running `main` twice: 0.6 pt
(77.3 / 76.7).** What it means:
across the whole rebuild count-correctness did not improve — main is 1.7 pt below
the old brain and 2.4 below `fastrule-v1`, both outside the bar. What improved is
latency (p50 53.2 → 40.2 s, p95 84.4 → 52.6) and the fast path. On the SAME 300
rows, split by where main routes them: the 130 it sends FAST go 88.5% → **93.1%**;
the 170 it sends DEEP go 72.9% → **65.3%**.

**PERSONAS 300 · count-correctness · stratified from
`dataset/personas/personas.jsonl`, fingerprint `1a3064b09c1c:300`**
(`checkpoints/RUN_STATUS.md:140-199`, `c7f1b11`): pre-engine-v2 72.3 ·
decompose-validate-v1 79.7 · **fastrule-v1 80.0** · fast-lane-pre-integration 79.0
· main 79.3 · one-shot-llm 50.3; p50 **14.4 s → 6.4 s** (main vs the old brain).
What it means: the sealed board's shape reappears on rows it shares nothing with
— main +5/+7 on simple, **−8 on complex** — and the headline hides a robustness
regression. **The mean rose and the per-voice spread WIDENED, 18 pt → 30 pt**:
observant_student 62 → 92, uni_student 66 → 62, household_parent 76 → 72. Two
voices are worse than the brain they replaced.

**REAL USAGE · flag rate · `scripts/weekly_review.py`, week to 2026-09-09**
(`DOCUMENTATION/WEEKLY_REVIEW.md`, `2bdb5e5`): **11 of 23 real commands flagged
wrong or corrected — 48%**; accuracy on reviewed 48% (10/21); test traffic
excluded. This instrument **outranks the other two** — it is the only one
measuring real speech. It supersedes the "50% on 20 commands" this file used to
quote. It is a DIFFERENT INSTRUMENT from the boards above (share of real commands
Gil marked wrong, vs count-correctness on constructed prompts), so the gap is
real and large but is not a subtraction and must not be quoted as one.

**SEALED 300 · milestone · 2026-09-22** (`dataset/RESULTS.md`, aggregates
only): count-correct **73% raw / 75% adjusted** (was 83% on 2026-09-07,
77.3% at the 09-12 sweep; error bar 0.6 pt), item P/R/F1 84.7 / 69.7 /
76.5 (was 85.2), field quality **92.0%** (was 88.9%), fast path **95%** on
124 rows at 77 ms p50, deep path **57%** on 177 rows, complex tier 42%. The
month's constructed-board work raised fields and precision and LOWERED
count-correctness on the deep path; dev-100 did not predict it. Not a
hypothesis source; the next training-pool work reads dev-fast-250.

**REAL USAGE · the replay board · `scripts/real_usage_board.py`, 2026-09-22
run 4** (`DOCUMENTATION/experiments/real_usage/RESULTS.md`): Gil's 75
reviewed commands replayed through the current engine on their own clocks.
Corrected tier, every reachable field right **20.0% (n=15)**, item count
right **73.3%**; `date` 82.4%, `start_time` 62.5%; approved rows reproduced
64.7% (11/17); generic-title rows right or acceptable under Q41 **90.5%
(19/21)** after cycles 35–39 (was 52.4% at the start of the day). dev-100
77% count-correct, precision 92.2, recall 76.3, F1 83.5, field quality 88.4%
(cycle 39's bare-kind commits: recall +5.3, field quality −3.1; cycle 40's
passed-clock rule: −1 where the pool's gold predates the ruling). **Every earlier run of this
board since 2026-09-18 served a checkpoint cache**, so the "moved nothing" of
09-21 was never measured — the board replays fresh now, and CLAUDE.md carries
the rule. Cycles 35 (the spoken clock forms), 36 (a stated day beats a
weekday), 37 (disfluent speech), 38 (a comma run needs a conjunction, Q43)
39 (a bare kind commits, Q42) and 40 (a passed clock means tomorrow) moved
this board and no stage board beyond two gold rows that predate the ruling.

## Open decisions — Gil's, not mine

**RESOLVED 2026-09-15** — `engine-component-folders` was merged (row 91,
TASKS.md; commit `9701f59`), not rebased or abandoned. This section used to
carry it as open; it wasn't, by the time this same file's own top section
recorded the merge. Left here as the correction rather than silently deleted.

1. **The fast-path fence vs. the retrospective.** The fence stands. It is Gil's,
   so it is quoted verbatim:
   > **Backlog — user-gated, do not start unprompted:** add fast-rule-parser
   > rules mined from the user's real data + the dataset. Only on Gil's explicit
   > say-so, and only after the deep track is improved — not on my own
   > initiative.
   The retrospective measures the deep track at 65.3% against the fast path's
   93.1% on the same 170 sealed rows and names raising fast-path coverage the
   highest-leverage lever available (`checkpoints/RECOMMENDATIONS.md:34-39`). The
   fence forbids starting the thing the evidence points at. **Unresolved, and not
   mine to resolve** — recorded so it is in front of Gil rather than settled by
   silence.

## Rulings that were only ever spoken (written down 2026-09-14)

- **The real-speech dataset is DROPPED.** Gil: *"dont do the real speech dataset
  then."* The built artefacts stay on disk (`dataset/realspeech/` — 1,200 rows,
  generator, board, `REALSPEECH.md`); what is dropped is further work on it. It
  is no longer "the fix" for the real-usage gap, which is what this file called
  it and what nothing in the repo recorded until now. `dataset/RESULTS.md` has
  since banked the ruling and marked the open cycle's *realspeech faithful/test*
  baseline history rather than a live one — no cycle registers a prediction
  against that board again.
- **The segmentation freeze is PARTIALLY LIFTED.** Gil: *"well segmentation as
  long as the structure remains the same, and just fixing implementations then
  its fine. same for fastrules."* **Implementation** fixes inside
  `assistant/engine/segmentation/` are ALLOWED; **structure and design** changes
  are not. This supersedes the blanket "no edits to that tree at all" gloss the
  docs have carried since 2026-09-09, and it retroactively explains `8fa8e72` and
  `b7687ea` — implementation fixes, therefore permitted. Note
  `segmentation/experiments/RESULTS.md` was last written 2026-09-08 and does not
  cover them: re-measure before quoting that board.
- **DEVQA Q13 is RULED and closed** (`DEVQA.md:11-16`, 2026-09-11): a fast commit
  on a compound the parse fully covers is fine, and `_parse_covers_the_compound`
  stays. This file used to carry it as open for Gil.
- **Standing preference (Gil):** *"i don't really want to make structural changes
  if i don't have to."* Read every proposal against it.

## The queue

`DOCUMENTATION/TASKS.md` is the tracker and carries the order of play at its
bottom — move a row there rather than starting a parallel list;
`dataset/HYPOTHESES.md` is the ranked experiment queue for when cycles resume.

**All four items this section used to list here are FIXED, as of the commits
below it in git log — this section was stale, not the work.** Kept as a record
rather than deleted:

1. ~~`llm_ms` not recorded on the fast path~~ — fixed, row 84, `167119f`.
2. ~~Gate `_recheck_not_found` on candidates existing~~ — fixed, row 85,
   `520b76b`.
3. ~~FastRule's NOW rows never reported (doubled-escape regex)~~ — fixed;
   `fastrule/experiments/fastrule_shape.py:128` now carries the corrected
   pattern and a comment explaining the old defect in place of it.
4. ~~Fast path booked MONTHLY for a YEARLY ask~~ — fixed, row 90, `943ef9a`.

**The queue is `DOCUMENTATION/REAL_SPEECH_PLAN.md` (2026-09-18).** Three
FastRule cycles won +4.2 pt on the corpus while the fast path stands at 12
approved to 24 flagged on Gil's own commands, and the corpus contains none of
the failure classes those 24 show. The plan: build the real-usage board from
`nlu_memory.db` (95 rows, 32 with gold), gate unknown words on the instant
commit through the confirm gate, instrument then cut deep-track latency; the
title extractor and temporal resolver are gated on Gil (DEVQA Q24–Q26). The
FastRule reader-gap cycles continue as the background loop. Engine commits
since `2bc032c` sit on `fastrule-recurrence-bounds`, fast-forwardable.

**LLMJudge cycle 17, settled 2026-09-15** (`llmjudge/experiments/RESULTS.md`).
Three Board D runs, in order: 120 rows fresh (NET +1) — 3,648 rows resumed
from a stale checkpoint that turned out to score `objects.py`, the FastRule
module retired by TODAY's `engine-component-folders` merge (`9701f59`), giving
a false NET −7 "liability" reading that is **retracted**, `Checkpoint.has(rid)`
having no code-revision check — then 400 rows fresh against HEAD `c826c83`
(checkpoint literally named after the commit, so this can't repeat), which
supersedes run 1 (same seed, same prefix) and gives **NET +0** (324/400 both
arms, 1 fixed, 1 broke). **Read as settled**: on current HEAD the connected
loop is neither a liability nor a fix, converging to zero as N grew
120→400 — not worth another round without a reason to doubt it. **LLMJudge is
cleared** as the deep track's bottleneck, this time on a number that holds.

**What actually dominates the miss, confirmed across all three runs**: the
malformed-value defect TASKS.md filed 2026-09-10 against `decompose_validate`
— now with two MORE shapes than that filing had (a full ISO datetime, and
bare `"morning"`/`"evening"` reaching `start_time`/`end_time` unresolved) on
top of the original two (empty match_title/match_start_time on deletes;
HH:MM:SS).

**The delete/update-target half of that defect is FIXED (2026-09-15,
llmjudge/experiments/RESULTS.md cycle 18), and it was never
`decompose_validate`'s bug.** Traced one stage at a time rather than
assumed: FastRule's `build()` already resolves the target correctly; the
hand-off that was supposed to give the model that answer as a head start
(`Defer.partial`, designed for exactly this) was dead code —
`rescue.py`'s `_Verdict.partial` hardcoded to `None`, nothing in
`assistant/engine/` ever setting it. Two fixes, each tested and measured
separately per Gil's standing rule
([[feedback_test_measure_each_change]]): the hint is now wired through
(`fastrule/build.py`, `fastrule/stage.py`, `llmjudge/rescue.py`), and a
deterministic fallback reuses FastRule's own build when the model still
fails after being given it. Measured on the real population (884 rows, the
full update/delete/complete pool, not a board subsample): raw model failure
rate is 0.4% (much lower than the ~40-60% the hand-picked adversarial rows
suggested), 94.4% → 94.7% after the fallback, both of the 2 recovered rows
correct. Full unit suite green throughout (1655 passed).

**The time-resolution half IS fixed — this paragraph said otherwise for two
days and named it "the queue's lead item", which is how a session picks up work
that is already done.** `assistant/intent/parser.py::_normalize_time_fields`
extracts the HH:MM prefix an ISO datetime or an HH:MM:SS both carry and drops
anything else (a bare `"morning"`, a relative `"by an hour"`) rather than losing
the whole object to pydantic over a field `decompose_validate` re-resolves
anyway. Measured on 1,963 rows (`llmjudge/experiments/RESULTS.md` cycle 19):
**79.9% → 88.6%**, with 91.4% of the 187 rows that would have raised now fully
correct. Cycle 18's lesson held — it was not `decompose_validate`'s fix to make.

**The `daterange` branch is RULED AND SHIPPED (2026-09-17, cycle 21).** Gil
chose ask-don't-guess: the day is read and OFFERED through the existing
confirm-create gate, from the fast parse with no model call; an update or
delete with a range date refuses outright rather than acting on a day nobody
said. Handle-rate 68.2% → **72.9%** across cycles 20+21 on the FastRule train
half (3,200 atomic rows), DESTRUCTIVE errors **33 → 28**, harm flat at 170,
half-executed unchanged. **The queue's lead item is now the 50 recurrence-
BOUNDARY rows**, which need no ruling — until/through is already settled.
The paragraph below is what this said while it was blocked.

**(Superseded — kept as the record of the blocker.)**

**The queue's lead item is now the `daterange` branch, and it is BLOCKED on a
ruling from Gil** (filed in TASKS.md, 2026-09-17). `_extract_temporal` handles
the timex types `datetime`, `date`, `time` and `timerange` and has none for
**`daterange`**, so `"next week"`, `"this weekend"`, `"in two weeks"` and
`"by friday"` have their date silently dropped — 605 rows of the FastRule
7,200 train half (12.6%), of which 263 are one-off atomic writes worth a
**+6.3 pt** handle-rate ceiling. The ruling needed is what date a range phrase
MEANS as an item's own date; the FastRule board excludes these rows from its
date metric for precisely that reason, so the fix cannot be scored until the
convention is picked.

**The bare-ordinal half of the same defect is FIXED** (cycle 20, 2026-09-17):
`"the 15th"` resolved nothing while `"on the 15th"` worked, so a task was
created with no due date on the Today list at a confidence high enough to
commit instantly. FastRule product-shape board, train half, 3,200 atomic rows:
**handle-rate 68.2% → 70.4%, date correctness 91.3% → 93.0% over 100 MORE
scored rows**, zero new destructive errors, half-executed unchanged at 72.

**App stream — `app-features` IS MERGED (2026-09-17).** It is no longer a
pending branch: `main` carries it. The stream's rule still holds (app work in the
`../MACalendar-app` worktree, merged between cycles, never during a run), but do
not read "app-features" anywhere as unmerged work. The 2026-09-06 approved queue
was already shipped (.ics share, search + jump-to-date, duplicate event, ISO week
numbers, Timer CSV, agenda view, observance checkbox, iOS `/heartbeat`).

**The Live Activity is the day's AGENDA, not a countdown** — Gil chose between
the two designs after seeing both rendered side by side (*"Option A is against
what i want"*). The card shows today's remaining events with the running one lit;
`Text(timerInterval:)` and `ProgressView(timerInterval:)` are gone. Any doc that
still describes a countdown, a "to go" label or an "elapsed" label is describing
the rejected design. With it came three behaviours Gil asked for: **a cleared
card stays cleared** until **06:00**, it has **its own Settings toggle** (shared
with the Mac through `notifications.agenda_card`, so the two screens cannot
disagree), and its rows are **Liquid Glass** on iOS 26.

**Phase 5 moved.** `BGAppRefreshTask` + `UIBackgroundModes: fetch` are now
REGISTERED (`LiveActivityManager.registerBackgroundRefresh`,
`com.macalendar.app.agenda-refresh`) — the line above that said "zero hits
anywhere under `MACalendar-iOS/`" is no longer true. What is left of phase 5 is
using that wake to roll the card BETWEEN events while the phone is locked, plus
the "remind me even when the calendar is closed" toggle Gil ruled in on
2026-09-06, and snooze, which is the one item with no ruling at all: keep or kill
is Gil's.

**`jude-status-wording` is retired, not merged.** Its one commit patched
`APIClient.swift`, and the Feature-convention refactor (`1beebe9`) moved that
code to `Features/Jude/JudeClient.swift` — so the branch could only ever conflict
against a file that no longer holds what it fixes. The BUG was still live, so the
fix was re-applied where the code actually lives. Delete the branch; there is
nothing in it `main` does not now have.

## Stage isolation — the plan of record

`DOCUMENTATION/STAGE_ISOLATION_PLAN.md` (Gil, 2026-09-07). Order: (1) FastRule's
dataset and metrics right — defer on non-atomic, create otherwise
(`assistant/engine/fastrule/datasets/`, 7,200 rows, scored by
`fastrule/experiments/fastrule_shape.py`); (2) every other stage tested in
isolation on its OWN dataset, own train–test split, no leakage; (3) rebuild from
proven parts and measure connected. `ingest` is the only stage with neither
`datasets/` nor `experiments/` — on either branch — and it is first in the chain,
so everything it gets wrong is charged to every stage below it.

## When cycles resume

The protocol is `dataset/DATASET.md` +
`DOCUMENTATION/experiments/ITERATION_PROTOCOL.md` (smallest rich-enough subset,
one component's implementation per cycle, compare actual vs expected in
`RESULTS.md`, and a cycle ends by starting the next one). One warning to carry
into it, from `RECOMMENDATIONS.md:48-54`: **more cycles against dev-fast-250 is
what NOT to do** — four of the last five moved less than the noise floor, and the
personas board shows why (the rebuild delivered phrasing robustness the sealed
board cannot see, because every sealed row is one voice).

**Two lessons this project keeps re-teaching, worth reading before starting:**

- **Fixing a stage exposes the next one.** The splitter made the kind decision
  the ceiling; the kind fix then surfaced tearing in `_split_tasks`. Expect the
  measurement after a win to look worse somewhere, and check downstream first.
- **Look at the rows, not the headline.** Both of those first cuts passed on the
  top-line number and were caught only by reading the failures.

## Shipped since the last STATUS (2026-09-13/14, branch `claude/codebase-ai-system-review-o2p8xu`, pushed)

- `003330b` — **the engine streams every run to the trace bus.** In the bus's
  whole 8-day history there was not one `begin` line: `on_step` was hooked only
  when a caller passed `trace_run`, and zero of 47 Swift files pass one — so a
  phone command published nothing for its entire 4–40 s and then appeared,
  already finished, in one line. This is what makes the HUD's live chain work.
- `9db46f6` + `b7687ea` — **the LLM console**: a third panel view logging every
  Ollama call with its caller, via `assistant/llm_bus.py`. `9481853` — a parallel
  **one-shot LLM engine** (`assistant/engine/LLM_one_shot/`, 245 lines):
  transcript in, objects out, one model call. It is the floor on both boards
  above, not a contender.
- `8c6c3f4` — **the HUD launcher works.** PlistBuddy edits after `osacompile`
  broke the ad-hoc seal, so the bundle had no stable identity and macOS would not
  list it in Privacy ▸ Files and Folders — it could not be granted the Desktop
  access this project needs. Plus `--show`: the card opened invisible.
- `117dd69` — **labelling moved into the store**: `create_todo` infers when
  `tags is None`, `update_todo`/`update_event` relabel on rename. A task's tags
  used to depend on which surface created it.
- `2322f9a`..`1c1cb25` — the checkpoint sweep harness, each run sandboxed behind a
  guard that fails if any real store moved. `c7f1b11` — the personas board.

## Working notes

- Two Claude sessions share this project's checkouts; re-read a `main`-checkout
  file immediately before editing (uncommitted work has no git net). The working
  tree is dirty as of this writing — check `git status` before assuming HEAD is
  what is on disk.
- Never run an audit/replay beside another model-loading job (spaCy/torch
  segfault). RAM is near full — LLM replays are serial, one Ollama job at a time.
- The API reloads itself; the calendar GUI and the thinking HUD do not. The phone
  needs a reinstall.
