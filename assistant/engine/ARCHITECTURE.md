# The engine

The brain. Every device — the Mac GUI and the iPhone — POSTs text to
`assistant.api`, which hands it here. This file is the map: each stage is a
**black box** with an input and an output, and each has its own
`ARCHITECTURE.md` for what happens inside.

---

## The chain

`X_i` is the output of the previous stage and the input to the next.

```
                                            ┌──────────────────────────────────┐
                                            │   X1' = rewrite(X4), up to 3×    │
                                            ▼                                  │
  audio          ┌───────────┐       ┌──────────────┐      ┌──────────────────┐│
  transcript ─X0►│ Ingest    │──X1──►│ Segmentation │──X2─►│ decompose_       ││
                 │ & fix     │       │              │      │ validate         ││
                 └───────────┘       └──────────────┘      └──────────────────┘│
                                                                    │          │
                                                                    X3         │
                                                                    ▼          │
                 ┌───────────┐       ┌──────────────┐      ┌──────────────────┐│
                 │  COMMIT   │◄──────│  LLMJudge    │◄─X4──│    FastRule      ││
                 │  + label  │       │              │──────┴──────────────────┘│
                 └───────────┘       └──────────────┘                          │
                       ▲                     └─────────────────────────────────┘
                       │  confident? commit immediately
                       └──────────────────────── FastRule
```

- **FastRule confident → COMMIT immediately.** This is the FAST TRACK, the
  front door (`fastrule/fast_track.py::fast_propose`): FastRule reads the WHOLE
  command before any Item exists, and `Engine.run` tries it first. LLMJudge
  still runs afterwards, in the background (`_start_background_verify`): it
  can rename a placeholder title and, only under `self_check_apply`, remove a
  row it finds `not_an_ask`; otherwise its notes are advisory. It does not
  re-parse or re-commit.
- **If LLMJudge is not satisfied** on the deep track, it rewrites the utterance
  into `X1'` — a string in X1's format — and re-enters at Segmentation, bounded
  at 3 rounds (`llmjudge.MAX_REENTRIES`). The loop runs BEFORE the final
  commit: the objects the judge passed are frozen and re-appended, not
  re-parsed (`Engine.parse(frozen=…)`), and on a live command the ones the
  rules built and the judge passes are already written by `_commit_ready`.

> The table under *Status* says exactly which parts are live today and which
> one is wired but inert. A diagram of a system that does not exist is how
> documentation starts lying.

---

## The stages, as black boxes

| stage | in | out | folder |
|---|---|---|---|
| **Ingest & fix** | `X0` the raw transcript(s) | `X1` one repaired command string | `ingest/` |
| **Segmentation** | `X1` a command | `X2` `[(action, time, tag), …]` | `segmentation/` |
| **decompose_validate** | `X2` = (items, X1) — items **and** the fixed transcript | `X3` items, COMPLETE: every field an object needs, resolved and traceable | `decompose_validate/` |
| **FastRule** | `X3` complete items — no transcript | `X4` calendar / to-do objects ready to write | `fastrule/` |
| **LLMJudge** | `X4` objects + the raw text | approve, or `X1'` a rewritten command | `llmjudge/` |
| **COMMIT + label** | approved objects | rows in the DB, categorised | `label/` + the orchestrator |

**Ingest & fix** — everything between "what Whisper wrote" and "words worth
parsing": several queued recordings coalesce into one input, the personal
vocabulary repairs what it is confident about, false starts are dropped and
never remembered.

**Segmentation** — the separate things the speaker asked for. `action` is the
words minus the time, `time` is the time reference **as spoken** (never
resolved), `tag` is `event | task | review | other` (`other` = not calendar
work; a list-management request carries its reason in `slots["junk"]`, DEVQA
Q52). Each item after the first also carries `relation` — WHY the cut was made
there (`sequence`, `list`, `sentence`, `envelope`, …; DEVQA Q51).

**decompose_validate** — takes the items **and the transcript** (`X2`).
First the kind router settles event-or-to-do for any item no tagger rule
decided (`kind_router.py`, a learned sklearn model, no ollama; DEVQA Q47).
`decompose` RESOLVES — the date and clock times from the item's own `time`,
recurrence and its bound, quantity, lead time — and chains a sequence's
untimed parts after the one before (`chain.py`, DEVQA Q51). Splitting is
segmentation's job, but `decompose.py` still carries two narrow backstops: two
clock times joined by "and" become two events (with a self-skipping model call
for wordier phrasings), and a to-do list splits via `intent/list_split.py`
when every part is an ask. `validate` then compares the completed items
back against the transcript, fixes what it can deterministically, and **FLAGS**
what it cannot.

**Flags, never blocks** (Gil, 2026-09-08). A blocked item is a command that
silently did nothing; a flagged one is committed with a note the speaker can
see and act on. The stage's job is to be honest about doubt, not to withhold.

X3 is therefore **complete, and honest about what it could not settle** —
FastRule receives items with nothing left to re-read, which is why the
transcript stops here. Every field must be TRACEABLE to the words: an
unsupported date is an invention, and the board counts them.

`decompose_validate/ARCHITECTURE.md` is the stage's own reference — the X3
field list, the conventions, the boards and what they have caught.

**FastRule** — turns items into objects that can be written, and **calls no
model at all** (2026-09-10). It COPIES the values `decompose_validate` already
resolved and reads only what is genuinely left: the operation, the title, the
people, the target. Every item gets one of three answers — the object, a
**BadItem** (it arrived damaged; this stage reports rather than repairs), or a
**NotAnObject** (segmentation tagged it `other`; not calendar work). Anything it
cannot decide becomes a DEFER left ON THE ITEM for LLMJudge, and the DEFER is a
contract: `REFUSAL` must not be overturned, `STRUCTURE` means split further,
`INCAPACITY` hands over its partial parse rather than starting cold.

**LLMJudge** — two jobs since 2026-09-10. First it **answers FastRule's
DEFERs** (`llmjudge/rescue.py`): this is where the model lives now, parsing
what FastRule could not, and it picks the DEFERs off the items at its own entry
rather than being called forward. Then the last check before anything is
trusted — and **the check makes no model call** (the extraction and the
per-field quoting were retired 2026-09-10, `retired/llmjudge-grounding-call/`).
`llmjudge/verdict.py` judges each object on its own, deterministically: a
temporal field `decompose_validate` never resolved, a generic subject, a
title with no word in the transcript, a title that is a list of things, an
object whose words still hold an ask seam. When a finding earns a loop,
`llmjudge/rewrite.py` writes `X1'` in two tiers: the failed asks in the
speaker's own words first, and only when that has nothing new to say, the
model writes it as a list of asks. Both tiers fail closed on the same
grounding guard.

The temporal fields are decided WITHOUT it: `CalendarIntent` stamps a date and a
clock the moment an object exists, so `item.slots` — what `decompose_validate`
actually resolved — is the only honest record of whether the words gave one.
A finding's ROUTE is then a property of its TYPE (`llmjudge/findings.py`), not
an opinion: three types earn a rewrite round (`ungrounded_subject`,
`coordinated_subject`, `unsplit_subject`), one commits with a notice
(`unsupported_field`), one goes to the review panel (`not_an_ask`).

**COMMIT + label** — the only place that writes to the DB. Category and colour
for events, tags for tasks; adjacent events never share a colour. On a live
command it also writes EARLY: whatever the rules built and the judge passed is
saved just before the first model call (DEVQA Q48, `Engine._commit_ready`), so a
long command's first events appear in about two seconds. And a change whose
target is not on the list it named looks on the other one before saying "I
couldn't find it" (`_other_store`), matching the whole title first and refusing
a tie between two different titles.

---

## Component vs Stage

> **`Component`** — any runnable unit: `.run()` in, result out.
> **`Stage`** — a Component that is one of the boxes above:
> `run(state, cfg) -> state`, ordered, trace-visible, and it owns a folder.

`Stage ⊂ Component`. **Every rectangle in the diagram is a Stage.** The parts
*inside* a stage folder are Components that are not Stages:

| Component, not a Stage | in |
|---|---|
| `FastSeg` · `LLMSeg` | `segmentation/` |
| `Atomicity` · `Scorer` | `fastrule/fastrule.py` — behind the FRONT DOOR (`fast_track.py`), not in the converter |
| `Gatekeeper` · the LLM fallback + its three guards · the DEFER consumer | `llmjudge/` — **moved 2026-09-09**; FastRule stopped calling them 2026-09-10 (B5), so the edge is gone as well as the code |
| `Engine` | the whole pipeline as one runnable thing |

Two consequences worth knowing:

- **A folder can hold more than one Stage.** `decompose_validate/` does.
- **Swapping a stage PIECE is invisible to the trace.** Segmentation moved from
  `old_seg` to `FastSeg` without touching `BRAIN_VERSION`, because
  `Stage("segment")` did not change. Renaming a *Stage* is the expensive one.

---

## What is shared, and what is frozen

**`EngineState`** (`state.py`) is the only thing passed between stages. An
`Item` is `(kind, text, time, slots, …)`:

| field | meaning |
|---|---|
| `kind` | `event` \| `task` \| `review` \| `other` — the SURFACE it concerns, not the operation. "cancel the dentist" is `event`; `other` is not calendar work. |
| `text` | the ACTION words. The time is **not** in here. |
| `source` | the VERBATIM span of X1 the item was cut from — what the loop's trim subtracts |
| `time` | the time reference as spoken — never a resolved date |
| `relation` | how the item relates to the one before it (`{"to", "kind", "words"}`, DEVQA Q51); `decompose_validate/chain.py` reads it to chain an untimed part after the one before |
| `spoken()` | action + time reattached — **what anything parsing for a date must use** |

`spoken()` is not a convenience. `FastRule` and the LLM parser both extract the
date from the string handed to them, so passing `text` alone produces events
with no time at all.

**The stage contracts are frozen** and `tests/unit/test_engine_contracts.py`
pins them. Fix a weak stage inside its own folder, against its own tests — never
by reshaping `EngineState` or reaching into another stage. If the contract
itself is wrong, that is a design change: it goes to `TASKS.md` and gets decided,
the way `Item.time` was.

---

## The trace, and why renaming a stage costs something

`trace.py` holds `BRAIN_VERSION` and `CHAINS`; the HUD, the Mac thinking panel
and the iOS `ThinkingView` render a command's chain of thought from it.

`CHAINS` and `thinking_panel._STAGE_ICONS` key off trace **kinds** (`vocab`,
`rule`, `validate`, `llm`, `execute`, `verify`, `done`) — **not stage names**. So
a stage rename needs no new icon. What costs is changing the chain's SHAPE:
bump `BRAIN_VERSION` (an old trace must still render in its old format), add the
new `CHAINS` entry, and update the panel, iOS and the explorer diagram.
`test_panel_agreement.py` goes red until they agree, naming what to fix.

---

## Status — what is wired TODAY

The chain above **is** the code. Verified by `scripts/engine_pipeline_check`,
which asserts the shape at every boundary and runs commands end to end.

| box | Stage | module |
|---|---|---|
| Ingest & fix | `Stage("transcript")` | `ingest/repair.py` + `ingest/coalesce.py` |
| Segmentation | `Stage("segment")` | `segmentation/` — FastSeg, LLMSeg **off** |
| decompose_validate | `Stage("decompose_validate")` | `decompose_validate/stage.py` → `resolve.py` + `checks.py` |
| FastRule | `Stage("fastrule")` | `fastrule/stage.py` → `fastrule/build.py` (`objects.py` deleted 2026-09-10) |
| LLMJudge | `Stage("llmjudge")` | `llmjudge/llmjudge.py` → `rescue.py` (job 0, the model) + `verdict.py` (the check, no model) + `rewrite.py` (X1') |
| the FAST TRACK (front door) | not a Stage — tried first by `Engine.run` | `fastrule/fast_track.py::fast_propose` |
| COMMIT + label | inside `_commit` | orchestrator + `label/label.py` |

**One thing is wired but deliberately inert**, and it is named rather than
hidden:

| | state |
|---|---|
| **LLMSeg** | off by default (`MACALENDAR_LLMSEG`). Measured net-negative on six measurements — `segmentation/ARCHITECTURE.md` §6. |

> **The loop is LIVE, since 2026-09-10** (merged into `main` 2026-09-15 with
> `engine-component-folders`, TASKS.md row 91) — this used to be the second
> inert item, gated on a stub. `llmjudge/rewrite.py` produces X1' — the failed
> asks only, in the speaker's words, or (tier 2, since 2026-09-20) a list of
> asks the model writes when the deterministic tier has nothing new to say —
> and the orchestrator FREEZES the good objects rather than re-parsing them.
> It still fails CLOSED: a rewrite whose content words are not all in the
> transcript is refused, and no rewrite means no loop. The post-loop re-judge
> is still guarded on `reentries` — it was bought when the judge paid an LLM
> extraction per run; the judge is model-free now, but re-judging an unchanged
> state is still wasted work.
>
> **`resolve.py` was already wired before this merge**, unrelated to the branch
> above (corrected 2026-09-11): `validate.py` was **deleted** with its
> index-pinning date rules on 2026-09-08, and `resolve.py` + `checks.py` became
> authoritative — `run_objects` writes their values onto the built intents, so
> the calendar rows come from them. The branch's own copy of this file still
> described `resolve.py` as unwired, from before that landed on `main`.

**What the loop is FOR, decided 2026-09-09** (Gil) — `llmjudge/PLAN.md` §1.3 has
the detail, and it changes what `rewrite_for_retry` has to produce:

> LLMJudge compares each object against the ORIGINAL text. The **good ones commit
> immediately**; only the failed asks are reworded into `X1'` and sent back to
> segmentation. Five objects with three good and two bad means three commits now and
> a two-ask retry — so `X1'` is a **TRIM of the original, not a re-run of it**.

That makes the trim a correctness requirement rather than an optimisation: the three
committed objects must not appear in `X1'`, or round two creates them again. It also
makes each round a smaller problem than the last, which is why three rounds is
enough.

**Why the loop is gated on a rewrite rather than just re-running.**
Segmentation is deterministic, so re-entering it with the same text returns the
same items — the retry can only spend the budget. Real usage, 2026-09-08: *"Let
an event to go out for a run now"* looped three times to the identical result
and apologised after 30 seconds. So: **no rewrite, no loop.**

Built 2026-09-10, and the gate stayed. Two further conditions now have to hold
before a round is spent: the finding's type must ROUTE to a rewrite (a value the
words never gave cannot be recovered by rewording, so it does not try), and the
rewrite's content words must all already be in the transcript (the first attempt
rewrote from `finding.detail` and segmentation parsed the EXPLANATION).

The one NEW test failure this rewire introduced — the month severed from its
ordinal (`the 20th of November`, `segmentation/ARCHITECTURE.md` §8.2) — has
since been fixed in FastSeg's `_TIME_PATTERNS` (the "MONTH + ORDINAL in the
'of' order" entry).

## Where to read next

| | |
|---|---|
| a stage's internals | `assistant/engine/<stage>/ARCHITECTURE.md` |
| the frozen contracts | `DOCUMENTATION/ENGINE.md` |
| the rewire plan (done; the record of it) | `DOCUMENTATION/ENGINE_REWIRE.md` |
| how components got their folders | `DOCUMENTATION/ENGINE_RESTRUCTURE.md` |
| the workflow rules | `CLAUDE.md` |
