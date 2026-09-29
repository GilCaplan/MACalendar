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

## Users (DEVQA Q65, shipped 2026-09-28)

An admin (`gil`) plus users, each with their own stores under
`~/.assistant_tools/users/<uid>/` (migrated 2026-09-28, backup
`~/.assistant_tools.backup-20260928-151343`). Whole-calendar sharing view/edit,
per-user learning; notifications are only ever your own (Q67). The
**Account tab** (both platforms, same design) is one card or row per person —
both directions of sharing, and for the admin their account controls — then
Tasks, Sign-in (require sign-in, auto sign-out Off / N days), Devices.
"Require sign-in everywhere" is still OFF — Gil's switch. Map:
`DOCUMENTATION/USERS_PLAN.md`. A demo user (`demo`, sharing view with gil)
exists for trying the Account tab and overlaps — delete it from the Account
tab when done.

**Offline reader (DEVQA Q66, 2026-09-28):** away from the Mac, the phone reads
with Apple's on-device model and books creates provisionally; the Mac re-reads
and wins. `assistant/offline/PROTOCOL.md`; agreement at `GET /offline/agreement`.

**Engine improvement is PAUSED (Gil, 2026-09-28)** to gather real-usage data
before the next cycle — no engine cycles until he restarts them.

## The finish line (DEVQA Q64, agreed 2026-09-27)

Done when: **real usage** ≈90% fully right with no destructive error in the
last 100 (≥100 reviewed); **real speech held-out** single-ask ≥95% and
multi-ask ≥80% (answer key aligned to the rulings by rule); **sealed 300**
≥85% adjusted, read once to sign off. Latest (2026-09-28, held-out real
speech n=2,099, key v2): single-ask 91.0%, multi-ask 74.2%; sealed 75%
adjusted (09-22); real usage too thin. Generated boards (FastRule,
Board D) are the fast inner loop, not the finish line.

## Where it stands (2026-09-27)

**As production runs it** — Board D `--product` (ingest, then the front door,
then the deep chain: `dbd5c94b` made the board run ingest first, as
`Engine.run` does), FastRule 7,200 set, 1,200 rows per split, seeded, fresh,
current gold (Q55/Q56/Q61/Q62). Before today's harm cycles (`fcd02957`,
old instrument) against `4d070b41`; records in `llmjudge/experiments/runs/`
(`board_d_{train,test}_1200_20260927T*`). TEST is a milestone read (every few
cycles), never a steering signal:

| metric (`dataset/METRICS.md`) | TRAIN before | TRAIN now | TEST before | TEST now |
|---|---|---|---|---|
| headline correct (action + title) | 93.2% (1118) | **95.1%** (1141) | 79.6% (955) | **80.6%** (967) |
| rows fixed / broken | | 26 / 3 | | 12 / **0** |
| count-correct | 92.7% (852/919) | 93.1% (856/919) | 86.2% (755/876) | same |
| objects F1 (P · R) | 96.0% (97.0 · 95.0) | 96.1% (97.4 · 94.9) | 92.2% (95.9 · 88.8) | same |
| title word F1 · exact | 92.5% · 80.1% | 92.9% · 81.6% | 80.0% · 44.5% | same |
| date · start · range right | 96.0 · 100 · 100% | same | 93.6 · 100 · 100% | same |
| cadence · reminder · invented time | 94.2 · 82.5 · 3.3% | same | 97.8 · 97.0 · 3.2% | same |
| harm (wrong rows) | 139 (82) | **101** (59) | 260 (245) | **241** (233) |
| destructive update_event | 21 | 13 | 25 | 18 |
| vague target refused | 81.4% (35/43) | 79.1% (34/43) | 77.1% (27/35) | same |
| rows needing a model call | 19.5% | 20.3% | 21.2% | 21.7% |
| latency p50 / p95 with a model | 4.4s / 10.3s | 4.3s / 10.3s | 4.2s / 11.7s | 4.0s / 11.5s |

Reading: TEST gained about half of what TRAIN did and broke nothing — the
delete-kind and change-kind fixes transfer; the mutation frame (TRAIN-derived
words only since `4d070b41`; its first version leaked TEST words) mostly does
not. The 3 TRAIN breaks are ingest defects the board never saw before it ran
ingest: a trailing ", done" stripped, "my reminder" passing the generic-target
veto once the hedges are gone, and the repaired "set a reminder to X next week"
read as an event.

**TEST milestone 2 (2026-09-27)**, `4d070b41` -> `d8aecf26` (three TRAIN
cycles: the bare-kind veto, the rescue's to-do narrowing, Q63), same gold:

| TEST line | before | after |
|---|---|---|
| Board D headline | 80.6% | **82.1%** (18 fixed / **0 broken**) |
| Board D count-correct · objects F1 | 86.2% · 92.2% | 87.1% · **93.9%** (extra 42 -> 24) |
| Board D harm (wrong rows) | 241 (233) | **221** (215) |
| Board D vague target refused | 77.1% | 80.0% (28/35) |
| Board D title exact · word F1 | 44.5% · 80.0% | 43.9% · 79.8% (**worse**) |
| segmentation exact-row | 83.5% (551/660) | **85.5%** (564/660) |
| relation · dv · chain | | identical |
| FastRule harm | 168 | 165 |
| FastRule non-atomic HALF-EXECUTED | 26 | **38 (worse)** |

The half-executed rise has no TRAIN counterpart (61 -> 61). From aggregates
only: "deferred by accident" fell 8.8 -> 6.7% — no-time multi-ask commands
that used to defer for a missing event date now commit as to-dos, and some of
TEST's phrasings drop an ask. Next: grow TRAIN multi-ask no-time phrasings so
the shape can be fixed from TRAIN (never from the TEST rows).

**TEST milestone 3 — the generalisation check (2026-09-27)**, `d8aecf26` ->
`85b08b76`, six TRAIN cycles (semicolon, compound noun / "i have to", deep
delete/complete frames, "is now at", polite "put X in my calendar", the
second train-only pool). Gil asked for it: *"careful that we are managing to
generalize on patterns and not just finetune to very specific examples."*

| instrument | result |
|---|---|
| Board D TEST (same 1,200 rows) | headline 82.1 -> 82.6% (**6 fixed / 0 broken**); harm 221 -> 209; destructive update_event 18 -> 12; count-correct 87.1 -> 87.9%; objects F1 93.9 -> 94.2% |
| FastRule shape TEST | correct-on-handled 83.7 -> 84.1% |
| segmentation, relation, dv, chain TEST | identical |
| **real speech** (fast_sandbox, 2,699 non-sealed utterances) | **identical** (94.4%, 1,078/1,142 committed) |

Reading: the STRUCTURAL fixes transfer (destructive update_event on TEST 18 ->
12 — the compound-noun and speaker-obligation readings); the TEMPLATE-shaped
ones (the deep delete frame, 6 of its 7 TRAIN fixes one family; the polite
openers; "is now at") show little on TEST and nothing on real speech, whose
utterances do not contain those templates at all. Rows fixed on TRAIN across
the six cycles came from few families each. Rule from here
(memory: generalise-not-templates): a fix needs its trigger in ≥3 TRAIN
families or in real speech, structural readings before word lists, and every
cycle reports rows AND distinct families.

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

Rulings **Q49–Q62** (top of `DEVQA.md`) — sequences (Q51), a role call is an
event + a linked to-do (Q50), list management is junk (Q52), one time reader
(Q53); on 2026-09-26: the 4-hour cap is only for ends the engine made (Q54),
errand verbs (Q55) and the person (Q56) stay in titles, a series with no end
gets a per-cadence default end (Q57), the fast-path fence is retired with
conditions (Q58), and every day has a "keep engine events off" switch (Q59,
Q60). On 2026-09-27: a to-do that repeats is an event series with ONE rolling
linked to-do (Q61, `cf74dec3`), and "buy A and B" is two to-dos (Q62,
`d3facf4c`). All built. On 2026-09-28: users, login and sharing (Q65), the phone's offline
reader (Q66), and overlaps / shared colours / own-only notifications / to-dos
grouped by person (Q67); plus the Account tab on both platforms, the phone's
Settings regrouped and the Mac window cleaned up (FEATURES.md). On 2026-09-29:
the phone's offline reader measured on Apple's model with the guard and dates
in code (Q68, `assistant/offline/experiments/RESULTS.md`), and the server as a
menu-bar app that devices join by QR or Wi-Fi without typing (Q69), model
helpers on other computers and a one-file installer for macOS / Linux / Windows
(Q70; INSTALL.md has the automatic, AI-agent and by-hand paths). Numbers per
cycle:
`assistant/engine/fastrule/experiments/RESULTS.md`,
`assistant/engine/llmjudge/experiments/RESULTS.md`, and the commit messages.

## Next

**App side (while the engine is paused):** `DOCUMENTATION/TASKS.md` rows
28–33 — require sign-in (Gil's switch), remove the demo user, look at the Mac
clean-up in light mode, read the offline reader's agreement after a week.

**Engine, when Gil resumes it:**

1. **Align the real-speech answer key to the rulings, by rule.** The dev
   failures are triaged (2026-09-28, `dataset/inputs/dev_triage_d8b3e81d.json`,
   `dataset/RESULTS.md` TRIAGE): of 93, **47 key out of date** (Q38, Q52,
   questions labelled `set`, Q47), **36 engine**, 10 unanswerable. Re-keyed,
   dev would read single 96.4% / multi 88.0% — unconfirmed until the K rules
   are encoded in `audit_dataset_conventions.py` and the held-out range read.
   Engine priority from it: the 4 mutations from non-destructive commands
   and the vocabulary rewriting "earse".
   **Held-out read under key v2 (2026-09-28, n=2,099, `dataset/RESULTS.md`):
   single-ask 91.0% (target ≥95%), multi-ask 74.2% (target ≥80%) — neither
   met.** Single-ask's gap is the engine's (the key moved it 0.1 pt).
2. **Multi-ask commands on real speech** (event + to-do 29%, two to-dos 60%,
   two events 71%; dev range n=182), fixes mined from the dev range with ≥3
   distinct phrasings each, verdict on the held-out range.
3. **Real usage**: re-read the board once there is new reviewed usage (needs
   Gil's reviews in the HUD / phone) — the reason for the pause.
4. **Sealed 300 (TEST)** milestone read, aggregates only.
5. **Train phrasing growth** for the FastRule title-precision gap (train
   91.6% vs test 71.8%).
6. Small queue in `DOCUMENTATION/TASKS.md` 19–27.

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
- `pytest tests/` is the whole suite (what CI runs); the integration folder
  talks to the real model when Ollama is up (`tests/integration/conftest.py`).
  `python -m assistant.cli doctor` checks the running stack.
- One model-loading job at a time; never edit files under `assistant/` while a
  board replays them.
- `git status` before assuming HEAD is what is on disk.
