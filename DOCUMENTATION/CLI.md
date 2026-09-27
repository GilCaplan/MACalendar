# The `assistant` CLI — infrastructure health

`python -m assistant.cli` (console script: **`assistant-cli`** — plain
`assistant` is the GUI, `assistant.main:main`). It is an
**infrastructure health harness, not a quality harness** — it never asks "is
the assistant smart / accurate". It answers one question: **is every layer of
the stack wired and healthy, so the infrastructure is correctly in place?**
(Quality is measured separately — `dataset/DATASET.md`.)

    assistant doctor              # check every layer, green/red summary
    assistant check <layer>       # one layer: llm | storage | engine | panel | macos | external
    assistant check engine --deep # …and name the per-stage gate (see below)
    assistant say "<command>"     # diagnostic: run one command, show the chain of thought
    assistant say "…" --source ios   # mac | ios | test (default test)
    assistant endpoints           # list the whole API surface

Each line is `✔` healthy · `✘` broken/not-running · `•` degraded/unverifiable ·
`ℹ` informational. `doctor` exits non-zero if any layer is `✘`.

`say` is a **client**, not a second brain: it POSTs to `/voice/text` on the
running API (`assistant/cli.py:408 cmd_say`) and renders the `trace` that comes back,
so it needs the stack up and it exercises exactly the path the GUI and the
phone do. It defaults to `--source test`, which is what keeps a diagnostic out
of the command memory and out of the HUD's History.

## The six layers

| # | Layer | What "healthy" means | How it's checked |
|---|---|---|---|
| 1 | **llm** | the model the API talks to is reachable | Ollama: `/api/tags` + model pulled; cloud: api key present. Plus the local spaCy grammar model loads. (STT is exercised only on a real `/voice` audio call, so it's noted, not asserted.) |
| 2 | **storage** | the databases and trace log are connected + writable | open calendar.db read-only (events/todos tables), memory.db present, trace-log dir writable |
| 3 | **engine** | each stage of THIS engine version is wired, and the live path answers | every stage module imports; `CHAINS[BRAIN_VERSION]` is defined; a live read-only probe returns `brain=BRAIN_VERSION` with a coherent trace. `--deep` points at the per-stage gate |
| 4 | **panel** | the thinking HUD is running and beating | the HUD's heartbeat is fresh (< 30s); trace log readable |
| 5 | **macos** | the calendar GUI is beating; hosted-calendar sync valid if configured | the GUI's heartbeat is fresh; Microsoft Graph auth if a hosted calendar is set (else local-only, informational) |
| 6 | **external** | the phone / other clients have checked in; API reachable to them | per-client `/heartbeat` last-seen; Tailscale address present |

## Heartbeats — how the disconnected surfaces become checkable

The HUD, the GUI and the phone are separate processes/devices that expose
nothing to probe. Each emits a lightweight beat (`assistant/heartbeat.py`):
the HUD and GUI write a timestamped status file under
`~/.assistant_tools/heartbeats/`; a device POSTs `/heartbeat`. The doctor reads
"last seen" to tell *connected and healthy* from *maybe running*. A surface
that isn't up reports `✘` — that is correct, not a bug: launch it (or the whole
stack via `Launch Calendar.command`) and it goes green.

_iOS posts its beat — that half is **done** (2026-09-14 check)._
`APIClient.heartbeat()` (`MACalendar-iOS/MACalendar-iOS/API/APIClient.swift:273`)
POSTs `{"source": "ios", "device": …}` and is fired on every foreground
transition (`Views/ContentView.swift:330`), deliberately off the sync path and
fire-and-forget, because being away from the Mac is a phone's normal state
rather than an error. Layer 6 still reports "no client checked in yet" on a Mac
the phone has never reached — that is an empty `~/.assistant_tools/heartbeats/`,
not an unwritten client. The string the check prints in that case
(`assistant/cli.py:363`) still reads *"iOS app posts it once updated"*: stale
prose inside a working check, not a missing feature.

## The engine layer is version-tied — update it when the engine changes

Layer 3 reads `assistant/trace.BRAIN_VERSION` and the stage list, so it is
**specific to the current engine design**. If the pipeline is redesigned:

1. bump `BRAIN_VERSION` and update `CHAINS` (same as the review panel — see
   CLAUDE.md "The review panel is downstream of the pipeline");
2. update the stage list in `cli.check_engine` if stages were added/renamed.

`tests/unit/test_cli.py` guards that `check_engine`'s stage list matches the
engine's real stages, so a redesign that forgets to update the doctor fails the
build — the same discipline as `test_panel_agreement`.

## `--deep` points at a gate — fixed as of 2026-09-26

`check engine --deep` does not run the per-stage gate itself. It prints
*"deep per-stage firing: run `python -m scripts.engine_stage_check --stage
all`"* (`assistant/cli.py:304`), and the live probe above says the
same (`:289`). CLAUDE.md presents that script as the working way to re-verify
one stage in isolation.

**The 2026-09-14 stage-name and `ImportError` drift is fixed.**
`scripts/engine_stage_check.py`'s `STAGES` dict now keys on the engine's real
seven-stage names (`transcript`, `segment`, `decompose_validate`, `fastrule`,
`llmjudge`, plus pre-rewire names kept as aliases so old invocations still
resolve), and its `llmjudge` case imports `assistant.engine.llmjudge.llmjudge`
correctly — no more `from assistant.engine.llmjudge import crosscheck`.
`ingest` and `commit` are explicitly listed as `UNCOVERED_STAGES` (checked by
`assistant-cli check engine`'s wiring layer instead) rather than silently
missing.

**A second, newer break in the same file is fixed too (2026-09-26).**
`_cases_segment` imported `assistant.engine.segmentation.old_seg` — but
`old_seg` was retired 2026-09-20 and moved to `retired/segmentation-old-seg/`,
so that import raised `ModuleNotFoundError` as soon as `--stage segment` or
`--stage all` reached it, and FastSeg (the live segmenter since 2026-09-08)
had no case in this file at all. It now imports `assistant.engine.segmentation`
(FastSeg's own entry point, `run(state, cfg)`) instead, so `--stage segment`
exercises the live stage. This was the same "survivor is the copy in
`scripts/`" trap CLAUDE.md records — `assistant/cli.py`'s own `ENGINE_STAGES`
had already been updated for the old_seg retirement (a comment there says so
explicitly) while this script's copy lagged.

**Why the earlier defect survived as long as it did.** The identical drift
inside `assistant.cli` was found and fixed on 2026-09-13 (`c82d5f8`, *"The
doctor was checking a chain the engine stopped running"*). The `scripts/`
copy lagged because `tests/unit/test_cli.py` guards `cli.ENGINE_STAGES` against
the engine's real stages and knows nothing about this file — the same reason
the old_seg import is not caught today.

**The real stage list.** `assistant/engine/state.py:26-34` is authoritative —
seven stages, in order:

    ingest · transcript · segment · decompose_validate · fastrule · llmjudge · commit

`transcript` is the repair half of ingest and stays its own Stage;
`commit` writes and labels in one step (`assistant/engine/__init__.py`, `Engine.judge`/`_commit`)
and owns no folder, so `label/` is covered under it.

`cli.ENGINE_STAGES` (`assistant/cli.py:218-247`) is the worked example to copy
from, and its shape is the lesson: it keeps `(stage name, module)` **pairs**,
because a folder name is not an import path — `decompose_validate/` contributes
six modules to the list and `segmentation/` contributes three. It no longer
imports `old_seg` at all (retired 2026-09-20); only the live FastSeg segmenter
is verified today.
