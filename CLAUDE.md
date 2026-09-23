# Working on this project

Short version of the things that are easy to get wrong here. **Read `STATUS.md`
first** — it is the one-screen "where we are" and points everywhere else. The
architecture lives in `DOCUMENTATION/SYSTEM.md`; the engine's stage contracts
in `DOCUMENTATION/ENGINE.md`; the dataset and how we improve against it in
`dataset/DATASET.md`; this file is the workflow.

**Keep this file lean.** It is the always-loaded rulebook, not a changelog —
every line earns its place by preventing a mistake that has or would happen.
When you add a rule, cut or tighten an older one; when a rule stops applying
(a retired feature), delete it. Detail belongs in the doc a rule points to,
not here.

## The shape of it

**`assistant.api` is the brain's front door, and `assistant.engine` is the
brain.** The API server receives every command, wherever it came from, and
hands it to the engine — which parses, executes and checks it. Four processes
run on the Mac, started by `Launch Calendar.command`:

    ollama serve                     the model, localhost:11434
    python -m assistant.api          THE BRAIN, 0.0.0.0:8080 (--tailscale)
    python -m assistant.thinking_hud the floating card, reads trace_bus.jsonl
    python -m assistant.main         the calendar GUI

**Both the GUI and the iPhone are clients of the API.** The GUI records audio,
posts the transcript to `127.0.0.1:8080/voice/text`, and renders the answer;
the phone does the same over Tailscale. `source` — `"mac"` or `"ios"` — is the
only difference between them, and it only labels the trace, the vocabulary
corrections and the command memory.

Two rules keep this true, each bought with real drift:

- **Do not add parsing or execution to `pipeline.py`.** The GUI used to have
  its own copy of the whole pipeline, the two drifted, and every fix had to be
  written twice or the surfaces disagreed. If a behaviour needs to exist on
  the Mac, it belongs in the engine, where the phone gets it too.
- **Do not add parsing or execution to `server.py` either.** That is where the
  old brain accumulated ~800 lines of interleaved heuristics that took a
  rewrite to untangle. `server.py` is HTTP: routes, request shapes, CRUD. The
  brain is `assistant/engine/`.

The HUD is a fourth process and talks to nothing: it tails
`~/.assistant_tools/trace_bus.jsonl`, which the engine appends to. That is what
lets it float over a full-screen app with the calendar closed, and it is the
durable record the card's History view reads back.

`confirmation_level` no longer has any effect — the dialog belonged between
parse and execute, and both now happen in a process with no screen. The GUI
warns at startup if it is above 0.

## Working on the engine

`assistant/engine/` is the chain, one BOX per stage folder:

    X0 -> ingest -X1-> segmentation -X2-> decompose_validate -X3-> fastrule
       -X4-> llmjudge -> commit(+label)

with a fast track that commits a confident rule parse instantly and lets the
judge check behind it. **`assistant/engine/ARCHITECTURE.md` is the map** — the
chain, each stage as a black box, and what is wired versus inert. Open it first;
`DOCUMENTATION/ENGINE.md` is the per-stage contract reference underneath it.

**Ingest has TWO AIMS and a fix belongs to exactly one** (Gil, 2026-09-20):
*"a. to fix deterministically bad transcribe wording b. finetuned list of
vocabulary from user to fix."* Generic damage — stop words, stutters, fillers,
and the COMMAND FRAMES routing depends on — is (a) and is fixed the same way
for everybody. Names, places and shorthand are (b). Putting one on the other's
shelf is a bug: "remind me to" taught as a per-user alias on "rewind" rewrote
"rewind the video to the start" for that user and helped nobody else.
`assistant/engine/ingest/ARCHITECTURE.md` has the worked case.

**LLMSeg is wired and deliberately INERT** (`MACALENDAR_LLMSEG`) — do not read
its presence as working behaviour.

**The judge's loop-back is LIVE** (since 2026-09-10; this said "still a stub"
until then and the stale line would have you dismiss a loop bug as impossible).
`rewrite_for_retry` builds X1' in TWO TIERS (Gil, 2026-09-20: *"the whole
point of the loop is that the llm sends a fix if relevant as X1'"*): first
the failed asks in the speaker's own words, deterministically; then, when that
has nothing NEW to say — the string was already tried, or the finding is an
`unsplit_subject`, which no trim can split — the MODEL writes X1' as a list of asks,
shown every earlier attempt and the judge's complaint about each, and code
joins the list as the ingest envelope `("a")and("b")`. Both tiers pass the
same grounding guard and fail closed. Three consequences:

- It re-enters Segmentation with DIFFERENT text, which is the whole point: a
  deterministic segmenter given the same string returns the same items — and
  the deterministic tier given the same failure writes the same X1', which is
  why the model tier exists.
- **It fires on three findings, all about the SUBJECT**: `ungrounded_subject`
  (a wrong subject), `coordinated_subject` (one event whose words list three
  or more things, rewritten one clause per thing) and `unsplit_subject` (one
  object whose own words still hold an ask seam — "and then", ". Also,"). The
  judge still makes NO model call and does not re-derive how many asks the
  command held; the seam reading is one object's own words.
- The judge cannot detect an ask with nothing built for it — that needed the
  ask diff Gil removed — so an under-split with no seam is segmentation's to
  fix, on segmentation's board.

**And LLMJudge makes no model call at all** (2026-09-10, Gil approved): it was
57% of the system's Ollama traffic and changed no outcome. `retired/llmjudge-
grounding-call/` has the module and the ledger. `llmjudge/rescue.py` still calls
one — that is job 0, parsing what FastRule DEFERRED, which is the model doing a
parse rather than judging one.

**Each STAGE owns a FOLDER, and everything about it lives there** (Gil,
2026-09-08): its code, the datasets used to improve it, the experiments run
against it, and an `ARCHITECTURE.md` explaining all four.

    ingest/  segmentation/  decompose_validate/  fastrule/  llmjudge/  label/
    state.py  component.py  llm.py  __init__.py

Three things this shape is bought with:

- **A folder name is not an import path.** `decompose_validate/` holds two
  stage modules; `segmentation/` holds four packages. `cli.check_engine` keeps
  `(folder, module)` pairs for exactly this reason.
- **`Stage` vs `Component`.** A **Stage** is a box in the chain:
  `run(state, cfg) -> state`, ordered, trace-visible, owns a folder. A
  **Component** is any runnable unit. `Stage ⊂ Component`, so the pieces INSIDE
  a stage folder — `FastSeg`, `LLMSeg`, `Atomicity`, `Gatekeeper`, `Scorer` —
  are Components that are not Stages. Swapping a piece is invisible to the
  trace; changing the chain's shape is not, and needs the panel procedure below.
- **The datasets moved with their stages.** `dataset/` still holds the
  cross-stage verification corpus; the FastRule and Segmentation sets are now
  under `assistant/engine/<stage>/datasets/`.
- **Stage I/O contracts are frozen.** `tests/unit/test_engine_contracts.py`
  pins them. Fix a weak stage inside its own module, against its own tests —
  never by reshaping `EngineState`, editing the orchestrator, or reaching into
  another stage. If the contract itself seems wrong, that is a design change:
  take it to TASKS.md, don't slip it into a fix.
- Each stage has its own test file (`test_engine_<stage>.py`) and its own
  trace step; the audit reports per-stage lines. A weak stage is found by its
  line, not by staring at the headline number.
- `scripts/engine_stage_check.py --stage <name>` re-verifies one stage in
  isolation against the real local LLM (Ollama-guarded, scratch stores,
  `source: "test"`).
- Deterministic-first everywhere: a stage may only call the LLM when its
  deterministic reading found nothing, and every LLM call is
  schema-constrained and grounded on the raw transcript.

## The review panel is downstream of the pipeline

The thinking panel and the iOS timeline draw a command's chain of thought from
its trace — so **the panel is downstream of the pipeline's shape, and a
revamp that does not update it draws the old system's chain for the new one.**
`assistant/trace.py` holds the single source of truth: `BRAIN_VERSION` (the
key the panel matches its render format to, stamped on every response and
trace-bus payload) and `CHAINS` (the ordered `(stage, label)` spec per version
that matches the explorer diagram).

When you change the pipeline's shape — add, rename or remove a stage; change
the order; split or merge steps — do all of these in the same change:

1. **Bump `BRAIN_VERSION`** so an old trace still renders in its old format.
2. **Update `CHAINS`** with the new version's chain, and any new stage's icon
   in `thinking_panel._STAGE_ICONS` (ship the `.svg`).
3. **Update the panel render** (`thinking_panel.py` + iOS `ThinkingView`) and
   the explorer diagram, per `DOCUMENTATION/ENGINE.md`'s render section.

**If you miss it, the build catches you.** `tests/unit/test_panel_agreement.py`
ties the engine's stage set, the panel's icons and `CHAINS` together and goes
red naming what to update; `test_engine_flow.py` pins that the version is
stamped on every command. Treat a red there like a red artifact-claim: it is
the panel telling you it no longer matches the machine.

## It never touches the internet

Whisper runs on the GPU from a cached model, the LLM is Ollama on localhost,
spaCy and the date recogniser are local, `pyluach` and `astral` are pure
Python, and the database is a file. `tests/unit/test_offline.py` blocks every
non-loopback socket and fails the build if that stops being true — it already
regressed once, when `mlx_whisper` was resolving its model against
huggingface.co on every start.

The exception is the phone reaching the Mac over Tailscale, which is a link
between two of your own machines rather than a dependency on a service.

## Personal data lives outside the repo

`~/.assistant_tools/` holds the calendar DB, the command memory, the personal
vocabulary and the event categories. **None of it is test data.** The
vocabulary is hand-curated and the command memory feeds the review flows, so
writing junk into either quietly degrades the assistant.

Every store honours an environment override, and `tests/conftest.py` points
all four at a scratch directory *before* importing anything from `assistant`
(the paths are read at import time, so a fixture is too late):

    MACALENDAR_DB  MACALENDAR_MEMORY_DB  MACALENDAR_VOCAB  MACALENDAR_CATEGORIES

**Three more joined them on 2026-09-10**, redirected by `conftest.py` alongside
the rest:

    MACALENDAR_MODELS          the user's fitted label models
    MACALENDAR_LABEL_FEEDBACK  the corrections they are fitted on
    MACALENDAR_MODEL_LOCK      the cross-process gate on ollama
    MACALENDAR_DEVICE_SECRET   the HMAC key device tokens are signed with
    MACALENDAR_DEVICES         the enrolment registry

The feedback file is the one to be careful with: it holds the user's own
CORRECTIONS, which are the only non-circular label source this project has, so
junk written into it trains the shipped classifier on junk.

The lock matters for the opposite reason: a suite that `flock`s the REAL one
makes the running assistant wait on the test run.

## One ollama, many callers: `assistant/model_protocol.py`

Four processes on this Mac share one ollama, and so does every phone on the
tailnet. Until 2026-09-10 nothing arbitrated it — measured while a board ran, a
trivial five-token call took **2.0s, then 42.5s, then 43.9s**, none of it
inference. Two rules, one module, because they are the same rule:

- **Identity is the DEVICE, and it is ISSUED not asserted.** `source` is
  `mac|ios|test` — a category — and every iPhone reports `ios`, so the pending
  queue merged two phones' commands into one utterance. Clients now enrol
  (`POST /devices/enroll`) and get an id plus an HMAC token; `EngineState.device`
  is what they CLAIMED and `EngineState.stream` is what the server CONCLUDED.
  **Same device may merge** into `("a")and("b")`; **different devices never
  merge**. An unverified claim is not refused, it is ISOLATED —
  `ios:untrusted:…` — so spoofing an id buys a queue of your own and touches
  nobody's backlog. Same for a revoked device, which is what makes a leaked
  token survivable.
- **Live traffic never waits for a board, and a real device never waits for a
  test.** Priority is per REQUEST (`model_protocol.serving(source)`), because
  the API server is one process serving the phone, the Mac and any test curl —
  an env var describes a process and could not express that. Anything driving
  the engine programmatically also sets `MACALENDAR_LLM_PRIORITY=background` in
  its env block; a test enforces this, because `priority()` defaults to LIVE
  and a board that forgets is invisible to every other check.
- **Bytes are not text.** The device secret is random bytes and was being
  `.strip()`ed on read — 4.61% of keys came back short, failed a length check
  and were silently regenerated, un-enrolling every device at once. It surfaced
  as a 1-in-20 flaky test.

Every call that generates or loads goes through `model_protocol.hold()`, and a
test reads the tree to prove there is no fourth door — `llmseg` has its own
socket, so a gate placed only in the parser would have had a silent hole.

## Two conventions, and they are not the same one

**`assistant/features/` is OUR OWN surfaces** — Calendar, Tasks, Coursework,
Workout, Timer, Teach, Jude-the-tab. **`assistant/integrations/` is somebody
else's PROGRAM** — its own repo, its own server, its own process. A tab has no
checkout, no port and no subprocess, so making one an `Integration` means five
methods returning `None` to satisfy a base class describing something it isn't.
A test pins the distinction. Jude is the only thing that is both, and its two
switches differ: `features.jude` is whether you want the tab, `jude.enabled` is
whether the program behind it is wired up.

They share one idea: **a surface owns a FOLDER, declares itself ONCE to a
registry, ships its own ROUTES, and the generic layer never learns its name.**

Adding a tab used to mean three hand-synced lists on iOS and five wiring sites
in `window.py`, and they had already drifted — Timer had no bounce-off handler,
so hiding it left a blank screen, and `window.py`'s DB-change poll reloaded
Tasks and Timer while **Coursework and Workout went stale until restart**.
`assistant/features/CONVENTION.md` is how to add one; the Mac contract is
`calendar_ui/feature_panel.py` (`reload` / `apply_theme` / `apply_ui_config`,
and `reload` is the verb — two panels called it `refresh` and were the only
ones the window ever refreshed).

**Visibility is ONE map**, `features:` in config.yaml, served by
`GET /features`. It replaced three systems that did not talk to each other.
Structure stays declared in code on each platform and only the on/off switch
travels, because a tab bar built from a server response cannot be drawn on a
train.

## Hosting another program: `assistant/integrations/`

An **integration** is an external app — its own repository, its own deps, its
own server — that this assistant starts, gates and proxies **without vendoring
it and without editing it**. Jude (`assistant/jude/`) is the first;
`assistant/integrations/CONVENTION.md` is how to add the second, and
`assistant/jude/ARCHITECTURE.md` is the worked example.

Everything about one lives in ITS OWN FOLDER — integration, routes, Mac app,
icon, build script, architecture doc — the same rule the engine's stages
follow. `server.py` gets ONE line (`registry.register(app)`); the ~120 lines of
Jude proxying that used to sit in the middle of it are `jude/routes.py` now.
An integration's routes are HTTP plumbing: they do not parse and do not
execute, so the brain is never reachable through one.

**An integration that touches ollama is a FIFTH DOOR**, and you cannot lock it
from the inside because it is somebody else's code. So the lock goes in front
of ollama: `integrations/ollama_gate.py` takes `model_protocol.hold()` around
every generating call, and the child is pointed at it with `OLLAMA_HOST`. Two
things this was bought with:

- **`OLLAMA_HOST` is not enough — grep the child for `11434` first.** Jude
  hardcodes the address for its ChromaDB embedding function, so the gate had a
  hole in the retrieval path, and a gate with a hole reads as covered. Since we
  do not edit the child, the patch rides in as `integrations/shim/
  sitecustomize.py` on its `PYTHONPATH`.
- **Default the priority to `background`.** `hold()` is asymmetric — live waits
  50ms then goes ANYWAY — so two live callers do not arbitrate at all. An
  integration marked live RACES your voice commands instead of queueing behind
  them, which is the contention the gate exists to remove.

Set them in any script that exercises the engine. If you are unsure whether
something wrote to the real files, check: `md5 ~/.assistant_tools/vocab.json`
before and after.

**An HTTP request to the live API ignores all of them.** The overrides redirect
what *this* process opens; a POST to `127.0.0.1:8080` is served by the running
`assistant.api`, which holds the real stores. That is how a HUD test's
`QTest.mouseClick` on Revert put 45 "buy groceries" rows in the real Today list
— the widget's own handler re-POSTs from a daemon thread. `tests/conftest.py`
now refuses loopback:API-port on both `requests` and `urllib`; use the Flask
test client instead.

**`MACALENDAR_TRACE_BUS` is the fifth**, and it was missed for a long time.
`trace_bus.jsonl` is the durable log the thinking card's History reads back,
so a script that leaves it alone publishes its commands into the record of
what you actually asked the assistant. Anything driving the API
programmatically should also post `"source": "test"`, which the History
filters out by default.

## Testing

    pytest tests/unit                 # fast, no model needed
    pytest tests/integration          # needs Ollama; skips without it
    pytest tests/                     # what CI runs

**Use the project venv — `./.venv/bin/python -m pytest`.** A bare `python` may
be a pyenv shim without `astral`, `pytest` or spaCy, and the suite then reports
collection errors and phantom failures that look like real regressions. This
cost a wrong "15 tests were already failing" reading on 2026-09-09; the same
suite was 1336-green on the venv.

**CI runs on push and PR** (re-enabled 2026-09-11). Three things the workflow
does that a Mac with Ollama never needs, so don't strip them: removing the
runner's Chrome apt list (it failed `apt-get update` before pytest started),
installing `wamerican` (`vocab._english()` reads `/usr/share/dict/words`, and
a MISSING list turns the "never rewrite a real English word" guard off
*silently*), and copying `config.example.yaml` to the gitignored `config.yaml`.

Integration tests must skip when Ollama is not running — copy the `pytestmark`
guard from `tests/integration/test_ollama_intent.py`. CI has no Ollama, so a
test that fails instead of skipping turns the build red.

`conftest.py` sets `MACALENDAR_NO_WARMUP=1`: `create_app()` otherwise spawns a
thread that unzips Whisper and spaCy while the suite runs, and two model loads
on separate threads segfault the interpreter — the same collision the BLAS pin
guards against. The engine reads the same flag before starting any daemon
thread. A test that builds the app wants routes, not models.

## Two work streams, two checkouts

While the improvement loop has a measurement run in flight, its checkout is
**read-only in practice**: a running replay lazily imports some modules at
scoring time, so editing files under it can change a run mid-flight. App
features and cleanups happen in the `../MACalendar-app` worktree (branch
`app-features`), merged with the loop branch and `main` **between cycles**,
never during a run. (Gil, 2026-09-06 — after two suites racing through a
shared personal store surfaced exactly this class of accident.)

## FastRule's verdict is a contract, not a suggestion

`FastRule` is the ATOMIC-ITEM EXECUTOR (one event or task, ~50ms, no model);
the deep system is the ATOMIZER (it splits until items are atomic, then
hands each back). When FastRule declines, `fastrule.reason_class()` says
what the deep track owes it:

- **REFUSAL** (generic-target, rename-misroute, interrogative-create) — a
  correct reading that must not execute as stated. The LLM may **resolve**
  it (anaphora → a real title); it must never overturn it by handing back
  the same empty target. **This was a real bug**: the per-item path
  re-implemented the commit test with the gates omitted and re-committed
  what the front door had vetoed.
- **STRUCTURE** (the compound gates) — more than one item; split further.
- **INCAPACITY** (below-threshold, missing-slots, skip) — the LLM takes over,
  and receives FastRule's partial parse rather than starting cold.

**A deferral never wastes the work** (Gil, 2026-09-07): `state.fastrule_
verdict` carries the reason, its class and the confidence forward, and
segment uses it as both evidence and prompt grounding. **And FastRule is
DETERMINISTIC** — a loop-back on unchanged text cannot get a new answer, so
`state.asked_fastrule` sends it straight to the model instead.

## Where we are working right now (2026-09-22)

**THE LLMJUDGE PROGRAM** (Gil, 2026-09-22: *"automate this process"*) —
`assistant/engine/llmjudge/PLAN.md` §7 is the plan and §7.5 the six model-use
tests; `DOCUMENTATION/TASKS.md` points at it. Order: Board D v2 (fresh by
default, both halves, the net broken down, latency beside it) → the v2
dataset (`llmjudge/datasets/v2/`, gold by grammar, built by a delegated
agent in a worktree, never by a model's opinion) → the rescue drawn as its
own trace step → the shape decisions and the six hypotheses as cycles, one
change per board run, keep or revert on the catch/false-flag pair AND a
latency budget → the real-usage board as the outer gate. **A model call in
this stage is tested only as a coarse two-way question under a condition
whose fire rate is reported** (§7.5); the four refuted uses are negative
controls, not options.

## Where we are working right now (2026-09-20)

**THE IMPROVEMENT LOOP IS RUNNING AGAIN** (Gil, 2026-09-20, DEVQA Q31; it was
paused for stage isolation from 2026-09-07). The working slice is dev-100
(`python -m scripts.engine_dataset_compare --limit 0 --dev100`, ~15 min with
the model), confirmed on dev-fast-250, sealed 300 milestone-only. Runs 22–26
on 2026-09-20 took the same 100 rows from 74% to 85% count-correct
(`dataset/RESULTS.md`), and the reason the pause ended is in those runs:
every fix moved a stage board by nothing or two rows while the whole chain
moved eleven points, because the misses were SEAM defects — the kind tagger
disagreeing with the converter, an under-split multiplied into junk, a
query committed for a create — that no stage corpus contains.

Two rules survive from stage isolation. **A stage-internal change is still
boarded alone on its own stage first** (segmentation `run_board`, FastRule
`fastrule_shape --split train`, the stage board, the atomicity board), because
a whole-chain read cannot say which stage moved; per-stage data lives with its
stage under `assistant/engine/<stage>/datasets/`, never edited to suit another.
And **dev-100 is direction, not proof** (one row = 1 pt, noise ~3 pt): confirm
on dev-fast-250 before banking a win. `DOCUMENTATION/TASKS.md` carries the
queue (items 4–8 of the checkpoint plan; three of them wait on rulings).

**Segmentation: IMPLEMENTATION fixes are allowed, design changes are not**
(Gil, 2026-09-12) — *"as long as the structure remains the same, and just
fixing implementations then it's fine. Same for fastrules."* This narrows the
2026-09-09 freeze, which several docs still quote as "no edits at all"; the
standing preference behind it is *"I don't really want to make structural
changes if I don't have to."*

**The live queue is the checkpoint retrospective, not `TASKS.md` alone** —
`DOCUMENTATION/experiments/checkpoints/` (RECOMMENDATIONS.md, RUN_STATUS.md).
Six system states were measured on two sealed 300-row boards in September;
nothing pointed at that folder, so three of its findings went unnoticed for
weeks. Both boards are `split:"test"`: **retrospective only, and they may
never pick the next thing to work on.**

**The `engine-component-folders` merge is DONE** (verified 2026-09-17: it is
0 commits ahead of HEAD, which is 117 ahead of it). This paragraph
said it was "one decision blocking" — 34 unmerged commits of finished engine
work — for long enough that the note outlived the problem. A blocker that has
quietly cleared is worse than one that never existed: it sends the next person
looking for work that is already in the tree.

## Measuring a change to the assistant

**The verification dataset is the primary evaluation** — `dataset/DATASET.md`
is the full reference (3000 real utterances, subsets, metrics, the recursive
loop). It is a supervised-ML loop: run the engine on a subset, score against
the ground truth, read *which component* failed and *why*, improve that one
component's **implementation** (never the design — big picture and contracts
frozen), rerun.

**Start on the smallest rich-enough slice and upsize only as gains slow — never
the full 3000 as the working loop:**

    python -m scripts.engine_dataset_compare --limit 0 --dev100          # iterate (~25 min)
    python -m scripts.engine_dataset_compare --limit 0 --max-rank 250   # confirm (~80 min)
    python -m scripts.engine_dataset_compare --limit 0 --max-rank 600   # dev-full
    python -m scripts.engine_dataset_compare --limit 0 --test           # SEALED 300 (milestone only)

Since 2026-09-07 the sealed set is the stratified 300 in
`dataset/inputs/test_split.json` (excluded from every run by default); the
other 2,699 rows are free for mining and training. **Test results are never
used to improve the engine** — a --test run reports aggregates only (the
tooling suppresses row detail) and never spawns a hypothesis; direction
comes from training-pool failures alone. Same rule for the FastRule 6000
set's test half.

The deterministic FAST track has its own lane: `python -m
assistant.engine.fastrule.experiments.fast_sandbox` (seconds, full-3000 allowed, selective-classifier
scoring, held-out aggregates only) — rules in ITERATION_PROTOCOL.md.

(`--limit 0` lifts the script's default 150-row cap — without it a rank slice
silently returns only its first 150 rows.)

**Each cycle is a hypothesis:** predict the component you'll change and the
metric+slice you expect to move, then compare actual vs. expected — and note any
novel effects — in `dataset/RESULTS.md`.

**A cycle ends by starting the next one** (Gil, 2026-09-08). Banking the
result IS the report — register the next prediction in the same breath and
keep going. Implementation fixes and cleanups between cycles are fine and do
not need asking. Stop only for a DESIGN decision, or when three cycles running
move nothing past the noise floor (then change the instrument, slice or
dataset — say so plainly rather than grinding). Never stop merely to show a
number. A score is a pointer, not the point:
read the breakdown and the failing rows to understand what it *means*, never
just the number. Full protocol: `DOCUMENTATION/experiments/ITERATION_PROTOCOL.md`.

**Every number needs three things: the DATASET, the METRIC, and what it
MEANS** (Gil, 2026-09-07). "50" or "80" is not a result. "handle rate 49.7%
→ 53.5% on the FastRule 7,200 test half (atomic rows) — it now acts on half
of the single-item commands instead of deferring them" is. Say which data
(FastRule 7,200 train/test · verification pool dev-fast/dev-full · sealed
300), which metric of the six, which slice, and one clause on the
consequence. This applies in chat and in every md file.

**AND N HAS TO BE BIG ENOUGH TO CARRY THE CLAIM** (Gil, 2026-09-19: *"you need
more than 60 examples, like a thousand examples would probably be more
adequate... depending on the task, make sure we have adequate number of data
samples and diversity"*). 50 or 100 rows is a smoke test, not a measurement.
**Aim for ~1,000+**, and scale it to what the change can break:

- a rule that CHANGES THE SPEAKER'S WORDS (vocabulary repair, rewrites) or that
  can commit something wrong — thousands, and the NEGATIVE surface matters more
  than the positive one: run it over every clean corpus you have and count
  false positives, because a wrong rewrite is invisible to the user.
- a rule confined to one stage — the stage's own board, whole, not a slice.
- an exploratory probe — any n, said plainly as a probe, and never banked.

**Diversity, not just count.** 1,000 rows from 26 templates is 26 examples with
a big denominator. Say how many DISTINCT shapes are behind a number — the
vocabulary bench reads "62 distinct pairs from 130 rows" for exactly this
reason. And when a bench is generated rather than observed, say which half is
real: `scripts/vocab_repair_bench.py` carries the damage OPERATIONS from the
observed corpus and invents only the terms, and says so at the top.

**And a REPORT names the SPLIT, the n, and the version it is compared to**
(Gil, 2026-09-22). When presenting a stage's or the system's results, every
number comes with: the dataset; **the split — TRAIN or TEST, and the sealed
300 is called the TEST set**; n as scored/total with the skipped count; the
metric, defined once in `dataset/METRICS.md` §"Definitions"; and the previous
version's reading on the SAME split. A comparison of two versions is one table
with both splits side by side, never train for one and test for the other.
A number that cannot be placed on that grid is a probe, said so, and never
banked.

**Always name the metric with the number.** "70→72" is meaningless in a vacuum;
"count-correct 73.5%→75% on event+task" is a result. Metrics are organised BY COMPONENT, not as one flat list — `dataset/METRICS.md`
is the map. Five levels: the ENGINE board (count-correctness, item P/R/F1,
missing-half, date-collapse, garbage titles, field quality, label-correctness,
parse path + latency); FASTRULE's product-shape board (atomic handle-rate and
correct-on-handled are PRIMARY, plus date/time correctness, invention rate,
harm, and the non-atomic diagnostic split); the CLASSIFIERS (accuracy +
per-class P/R/F1 for atomicity, operation, kind); the PERSONAS (per-speaker
boards and the spread); and REAL USAGE (`weekly_review`), **which outranks the
rest** — it is the only instrument measuring real speech. Each has slices — never report a score without saying
which metric and which slice, in chat and in the md files alike.

The hand-written corpus (`scripts/audit_assistant.py` →
`DOCUMENTATION/ASSISTANT_AUDIT_SUMMARY.md`) is now only a **regression floor**:
a fast smoke that nothing the old brain could do got worse. Not the primary
number.

`scripts/weekly_review.py` reports real usage — the honest instrument once the
engine is live. It reports a **flag rate** and refuses an accuracy below three
approvals; it drops verdicts arriving in bursts (a cleared backlog is not a
judgement).

## A long run must be watchable and resumable

**Checkpoint anything that runs for more than a few minutes** (Gil,
2026-09-10). `assistant/checkpoint.py` is the helper; `Checkpoint(name, total)`
plus `has()` / `record()` is the whole API.

Board D is why. It ran **three and a half hours and printed nothing**, and two
things were wrong with that:

- **Progress was unobservable.** `ps` said alive at 0.0% CPU, which is exactly
  what a slow ollama call looks like AND what a hang looks like. "Is it
  working?" could not be answered, only guessed at from how fast its stderr
  happened to grow.
- **A crash at 90% would have cost everything.** Three hours of model calls,
  nothing on disk. Worse, Board D runs one ARM fully before the other, so dying
  late would not even have left a usable half.

A measurement you cannot watch and cannot resume is one you become reluctant to
start — which is how Board D spent two days with *"this board has never run"*
in its own docstring.

So: **one unit per line, flushed and fsynced before the next begins** (a
`kill -9` costs the row in flight and nothing else), **re-running resumes**, and
**a progress line with a rate and an ETA** so the answer is visible rather than
inferred. `MACALENDAR_CHECKPOINTS` is the store, scratched by `conftest.py` —
a suite that resumed a real run would mix two configurations into one board.

**And a board that RESUMES by default is not measuring the code you changed.**
`Checkpoint` resumes unless told `resume=False`, and it only WARNS on a commit
mismatch. The real-usage board resumed every one of its 75 rows from a cache
recorded at the first run (2026-09-18) on every run for four days — the
2026-09-21 "two days of engine work moved nothing" verdict, the "byte-identical
fresh replay" and the measured error bar were the same cached rows read back,
and the true numbers had moved in both directions. A short board replays
fresh every time; resuming is for a crash mid-run at the SAME commit, opted
into by flag. When a board prints identical numbers twice, check that it ran.

**And a board whose model calls are unseeded is not measuring the change
either.** Two runs of Board D v2 at one commit differed on 22 of 1,200 rows —
the rescue's parse answering "book club" then "club" — more than the 19 rows
its arms disagreed on; seeded, the arms disagree on 3. `MACALENDAR_LLM_SEED`
(`model_protocol.seed_options()`) pins every ollama door for a process; a
board declares it in its env block beside the priority, live traffic never
sets it. Prove a new board deterministic with a same-code double run before
reading its fixed/broke pair.

## Things that have bitten before

- **Don't run the audit and the test suite at once.** Both load spaCy and
  torch, and the combination used to segfault. `tests/conftest.py` pins BLAS
  to one thread, which fixed it, but the audit does not. The same applies to
  any two model-loading jobs side by side.
- **A path or import in an experiment, generator or checker rots silently, and
  only breaks when you next run it.** The per-stage restructure broke four
  boards and generators this way (all four verified healthy 2026-09-11), and
  the 2026-09-08 `crosscheck.py` → `llmjudge/llmjudge.py` rename broke a fifth:
  `scripts/engine_stage_check.py` raised `ImportError` on `--stage all` — while
  this very file called it the working per-stage gate — and was still broken on
  2026-09-14, a day after the identical defect was fixed in `assistant/cli.py`.
  **Finding some of these is not finding all of them**, and the survivors are
  always the copy in `scripts/` rather than in the stage folder that owns it.
  Nothing notices, because these are manual steps whose OUTPUT is committed, so
  the stale `.jsonl` keeps working.
  **Before trusting any board or checker, run it.** Two traps: `ROOT =
  parents[1]` means the repo root under `scripts/` and the STAGE folder inside
  one, so a path that looks wrong may be right; and `assistant.engine.state.
  STAGES` is the authoritative stage list — anything keeping its own copy has
  already drifted.
- **Two docs are GENERATED — never edit them by hand.** The API reference,
  after adding or changing an endpoint: `python scripts/gen_api_reference.py`.
  The code-size breakdown the README links to (`DOCUMENTATION/CODE_SIZE.md`)
  looks after itself — run `python -m scripts.code_stats --install-hook` once
  per checkout and the pre-commit hook rewrites it from the staged index, so
  the figure always describes the commit it ships in. Without the hook,
  `--write` by hand; either way `tests/unit/test_code_size.py` goes red once it
  is more than 2% out. A count typed into a README instead of generated is
  stale by the following week and nobody ever notices.
- **The API reloads itself; nothing else does.** It runs with `--reload`, so
  editing anything under `assistant/` restarts it (tests, scripts and
  DOCUMENTATION are excluded). The **calendar GUI and the thinking HUD do
  not** — restart them by hand, and remember that when a change "has no
  effect". The phone needs a reinstall (`xcrun devicectl device install app`
  is more reliable than Xcode's Run when the device is on Wi-Fi).
- **A UI test that never sends a mouse event tests nothing.** Three bugs in
  the HUD's history view shipped green because tests called handlers instead
  of clicking controls. Use `QTest.mouseClick` / `QTest.keyClicks`, and
  connect `clicked` through a lambda.
- **Deleting is destructive.** When the engine cannot identify what to delete,
  empty slots — which surface as "I couldn't find …" — are the right answer.
  Guessing is not.
- **A ruling in `DEVQA.md` locks a DESIGN, not just an answer — and a
  complaint about a surface is not permission to redesign it.** Gil chose the
  lock-screen card's AGENDA over a countdown on 2026-09-17, with both built and
  rendered side by side (Q23, LOCKED 2026-09-18). The next day a session that
  had not read DEVQA took "remove the elapsed" as a request to patch the
  countdown — and patched a design that had already been replaced on a branch
  it never looked at. Both halves are the lesson: read the ruling, and read the
  complaint against it, because "fix this" often means "this is the wrong
  thing". Before changing a shipped surface, check DEVQA for a ruling and
  `git log --oneline -- <file>` for a rework you are about to fight. Fixing a
  bug INSIDE a locked design is ordinary work; changing its shape needs Gil.

## Recurring events

`recurrence` is only ever `daily`, `weekly`, `monthly` or `yearly` (the fourth
added 2026-09-08: rounding a yearly series to monthly is 12x wrong and fires
eleven times nobody asked for, so it is the one cadence rounding could not
honestly cover). Anything a speaker
says that is not one of those gets rounded to one that is, and the rounding is
announced in the reply rather than done quietly. **A weekly series may name
SEVERAL weekdays** — `recur_days` carries them ("every tuesday and thursday");
that is WHICH days a weekly series lands on, not a fourth cadence — "every other tuesday" became
one event before anyone noticed, and "every weekday" books Shabbat.

**"until" excludes the day it names; "through" and "including" keep it.**
English supports both readings, so the project picks one and applies it
everywhere rather than guessing per sentence. "until the end of September" is
inclusive — that phrase names the final day, not a boundary past it.

A weekly series starts on the soonest weekday the sentence names, not on
whatever date the model returned; it used to put "every sunday and tuesday" on
a Wednesday.

**Series skip Shabbat and yom tov**, bounded by candle lighting and tzeit at
the configured location (`hebrew_calendar` / `observance` settings in
config.yaml — latitude, longitude, timezone), not by midnight. At Israeli
latitudes candle lighting swings well over two hours between September and
December, so a 19:00 Friday event is outside Shabbat in one and inside it in
the other; a date-only rule gets a whole season wrong.

Three exceptions, each with a reason:

- **Meals are allowed** — they are what the day is for. Unless it is a fast,
  where a meal is the one thing that must not be booked; Yom Kippur is both
  and the fast wins.
- **A series anchored on Shabbat keeps it.** A Saturday shiur was put there on
  purpose, and skipping every instance would leave a weekly series with one
  event.
- **Nothing is skipped if observance cannot be computed.** A series quietly
  losing days is worse than one landing where it should not.

The engine adds a fourth rule for what *it* creates (never for manual edits):
a one-off event inside Shabbat / yom tov must be leyning, a meal or davening,
and on a fast day a meal must not be booked before the fast ends. The refusal
is explained in the reply — see the observance gate in `ENGINE.md`.

## The published pages are downstream of the code

`DOCUMENTATION/artifacts/*.html` are the explainers published to public URLs,
and they quote constants from the code. Those drift.
**`tests/unit/test_artifact_claims.py` enforces the agreement**, reading each
value out of the code and asserting the page says the same thing. If you
change a constant a page quotes, that test goes red and names the file to
edit. If you add a claim to a page, add its check.
**A STAGE'S PANEL IS PART OF THE STAGE** (Gil, 2026-09-19). The pages do not
only quote constants — `explorer.html` draws each stage's INTERNALS, step by
step, in prose and in an SVG. So a change to what a stage DOES leaves that
panel wrong even when the chain's shape is untouched and every quoted number
still agrees. The panel procedure above fires on the chain's SHAPE; this fires
on a stage's BEHAVIOUR, and they are different triggers:

> When you add, remove or reorder a step inside a stage, update that stage's
> panel in `explorer.html` IN THE SAME CHANGE — the ordered list, the SVG, and
> the SVG's `aria-label`, which is the only version a screen reader gets.

Ingest is the worked example: two passes were added to the spoken-noise step
and the vocabulary step stopped being single-word, while the page still read
"openers, hedges, self-corrections" and "phonetically matched". Nothing was
factually a wrong NUMBER, so `test_artifact_claims` stayed green and the page
described a stage that no longer existed. `test_artifact_claims` now ties the
cleanup passes to the page by name, so adding a third one goes red.

`DOCUMENTATION/ARTIFACT_BUILDER.md` carries the full table and layering rules,
including: **no personal detail on a published page** (the check treats any
vocabulary word as a leak unless declared in `artifacts/public_words.txt`),
and **a measured number must cite a run that still exists**
(`ASSISTANT_AUDIT_SUMMARY.md`, never the overwritten report).

## Where the plan lives

`DOCUMENTATION/TASKS.md` is the tracker and carries the current order of play
at the bottom — read it before picking up work, and move a row rather than
starting a parallel list. `DOCUMENTATION/FEATURES.md` is the feature catalog
(what/where/how per feature, summary table on top) — **a shipped feature adds
its entry there in the same change.** `DOCUMENTATION/MODELS.md` is the canonical answer to
which models do what. `DOCUMENTATION/ENGINE.md` is the engine's stage-contract
reference. `DOCUMENTATION/ARTIFACT_BUILDER.md` is the brief for the published
explainer pages. `DOCUMENTATION/experiments/checkpoints/` holds the
retrospective and the recommendations queued out of it. `DEVQA.md` is the
decision log — a question answered there is settled; check it before
re-asking AND before changing what it settled.

## Conventions

Commit messages explain what was wrong and how it was found, not just what
changed. Branch rather than committing to `main`. `config.yaml` is gitignored;
mirror any new setting into `config.example.yaml`.

**Retiring a system version:** when a design is replaced, keep the old one in
`retired/<version-name>/` — its distinctive files plus a `README` — and tag the
last commit that ran it (`git tag <version-name>`), so it can be reverted or
compared. The tag is the full-fidelity truth; the folder is the quick
reference. Never just delete a superseded brain.
