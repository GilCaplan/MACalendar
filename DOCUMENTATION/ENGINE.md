# The Engine — stage contracts

> **`assistant/engine/ARCHITECTURE.md` is the map** — the chain as a diagram,
> each stage as a black box, and what is wired versus inert. This file is the
> contract reference underneath it: what each stage READS and WRITES.
>
> Re-cut 2026-09-08 with the rewire. The boxes are now
> `ingest → segmentation → decompose_validate → fastrule → llmjudge →
> commit(+label)`; `decompose` and `validate` share a folder, the object-making
> box is FastRule, and `label` runs inside commit.

> **Stage isolation (2026-09-07 → 2026-09-20):** each stage was proven on its
> own dataset before the system was measured end-to-end — see
> `DOCUMENTATION/STAGE_ISOLATION_PLAN.md`. The whole-chain loop resumed on
> 2026-09-20 (CLAUDE.md); a stage-internal change is still boarded on its own
> stage first. The contracts below are unchanged.
> FastRule v1 retired 2026-09-07 (`retired/fastrule-v1/`, tag
> `fastrule-v1`); `engine/fastrule/fastrule.py` is the Q11 structure — Atomicity
> (layer 0) and Scorer as objects, with `Gatekeeper` imported from
> `llmjudge/gatekeeper.py`, where it moved on 2026-09-09.

> **Object layer (Q7, merged 2026-09-07, behavior-identical confirmed):**
> the orchestrator is now classes — `Engine` (entry; transcript gate, track
> selection, commit, bookkeeping; `run_transcript()` is a thin shim over it),
> the Engine's stage list (the ordered re-runnable Stage list + the crosscheck loop) and
> `Stage` (a named, late-bound handle on a stage module's frozen entry —
> late-bound so monkeypatched stages still reach the engine;
> `engine/component.py`). **Every stage contract below is unchanged** — the
> classes wrap the same modules this document specifies.

This is the document you open when a stage needs fixing. It defines what each
stage of the deep track receives and must hand on. **These contracts are
frozen**: they were designed once, before implementation, and do not change at
any point of development. Fixing a weak stage means improving its internals
toward the best version of itself — inside its own module, against its own
tests — never reshaping `EngineState`, touching the orchestrator, or another
stage. `tests/unit/test_engine_contracts.py` enforces every claim on this
page; if it goes red you are changing a contract, not fixing a stage.

## The shape

```
text ─▶ 0 ingest              ingest/coalesce.py (server's pending loop) + the run lock
     ─▶ 1 transcript          ingest/repair.py   spoken noise, frames, vocabulary, the gate
     ─▶   FRONT DOOR          fastrule/fast_track.py::fast_propose — confident? commit now
     ─▶ 2 segment             segmentation/      split into typed items (+ relation)
     ─▶ 3 decompose_validate  decompose_validate/stage.py::run — kind router, decompose,
                                                 tidy, resolve + check values
     ─▶ 5 fastrule            fastrule/stage.py → build.py — items → objects (no model;
                                                 DEFERs go to 6), then
                              decompose_validate run_objects — field-level named rules
     ─▶ 6 llmjudge            llmjudge/          rescue DEFERs (model), check (no model),
                                                 loop-back with X1'
     ─▶   commit + 7 label    orchestrator + label/label.py
```

A command the FRONT DOOR is confident about never runs the deep track: when
`fastrule/fast_track.py::fast_propose` finds FastRule confident about the whole
input (≥ `RULE_THRESHOLD`, no gate fired), items are built straight from its
intents, `run_objects` applies the field rules, the answer is committed
instantly, and LLMJudge's check runs behind it (`_start_background_verify`).
Everything else runs the deep track. `parse_path` says which happened:
`"fast"` or `"deep"` (plus `"error"`, `"ignored"`, `"needs_edit"`,
`"confirm_create"`).

Stages exchange **only** the `EngineState` (`assistant/engine/state.py`) and
each exposes exactly one public entry point, `run(state, cfg) -> state`
(decompose_validate additionally `run_objects`; the fastrule folder additionally
holds the front door, `fast_track.fast_propose`). No stage imports another
stage's internals. `decompose_validate` also exports named *readers*
(`text_helpers.at_times` / `spoken_times` / `end_is_exclusive` /
`is_placeholder_title`, `targeting.relative_dates`,
`object_rules.is_interrogative_create`…) — shared vocabulary other stages may
call, never a channel to mutate state through.

## The state contract

| Field | Written by | Read by | Meaning |
|---|---|---|---|
| `raw_text`, `source`, `current_view`, `supports_edit`, `supports_confirm`, `mode` | ingest | all | read-only after ingest; `mode` is `foreground` or `background` (fast-track verify pass) |
| `device` | ingest | `model_protocol.stream_key` | **CONTRACT EXTENSION, 2026-09-10 (Gil).** WHICH client, where `source` is only what KIND. Every iPhone reports `source="ios"`, so the pending queue treated the whole tailnet as one stream and concatenated two phones' queued commands into a single utterance. Client-supplied and opaque — a grouping key, never parsed. Empty when the client sends none, which degrades to source-only grouping: a Mac still never merges with a phone. Read-only after ingest. |
| `text` | transcript | all later | the working transcript (stop words stripped, vocab applied) |
| `corrections` | transcript | response | vocab fixes, client shape |
| `needs_edit` | transcript | orchestrator | doubtful words; non-empty ⇒ the gate fired, nothing executes |
| `item.slots["confirm_create"]` | decompose_validate (object pass), or the front door for a range date / bare 7–8 | orchestrator | an interrogative create; the intent SURVIVES to be offered, nothing executes |
| `ignored` | transcript | orchestrator | false start: not parsed, not executed, **not remembered** |
| `items` | segment (create), decompose_validate (kind, split, values in `slots`), fastrule (`action` + `intent`, or a DEFER / flag in `slots`), llmjudge's rescue (the deferred ones) | every later stage, commit, label | the item tree; ids `item_1`, `item_1-2`, `r1_item_1` on a loop round |
| `item.relation` | segment | decompose_validate (the chain) | **CONTRACT EXTENSION, 2026-09-25 (Gil, DEVQA Q51).** How the item relates to the one before it — the reason segmentation cut there: `{"to", "kind", "words"}`, kind one of `sequence` (followed by / then / after that), `list` (and / comma), `sentence`, `envelope`, `same_span` (an enumeration), `adjacent`, `unknown`. None on the first item. Read off the words between the two items' verbatim spans, so it describes whatever cut them. decompose_validate chains an untimed `sequence` part after the one before it. |
| `item.blocked` | decompose_validate, fastrule (a `bad_item` / `not_an_ask` flag), the orchestrator (`_block_unresolved_subjects`) | commit | refusal reason; a blocked item is reported, never silently dropped. The observance gate FLAGS (`slots["flags"]`) rather than blocks since 2026-09-08 |
| `item.intent = None` after object-making | decompose_validate (drop rules) | commit | dropped as parser noise; traced, not messaged |
| `fastrule_verdict` | the front door (`fast_propose`, on a decline) | — (no stage reads it today) | why FastRule declined — reason, class, confidence, actions — carried forward for the deep track. `asked_fastrule` is declared beside it and nothing writes or reads it |
| `executed`, `messages`, `refresh` | commit | label, llmjudge, response | what actually ran, per item |
| `findings`, `retries`, `mistakes` | llmjudge | orchestrator | mismatches, loop-back budget, context for retried stages |
| `fixes` | any stage via `state.add_fix` | trace, audit | every named-rule correction |
| `trace`, `parse_path`, `llm_ms`, `rule_confidence`, `memory_id`, `verify_token`, `pending_id` | orchestrator + stages as noted | response | bookkeeping |

## The stages

## One ollama, many callers

`assistant/model_protocol.py` is the single answer to *who gets the model next*
and *whose words may be spoken in one breath* — they are the same question,
because identity decides both.

    stream_key(source, device)   the identity a request belongs to
    may_merge(a, b)              same DEVICE only; never across devices
    hold()                       the cross-process gate around one model call

**Merge or queue.** Commands from the same device may be coalesced into
`("a")and("b")` — one person's backlog, one parse. Commands from different
devices are never concatenated; they queue. Two iPhones are two people.

**Live traffic never waits for a board.** The gate is `fcntl.flock` on a file,
chosen because the kernel releases it when the holder dies — a crashed board
must not wedge the assistant, and a stale-lock reaper would be a second bug.
The asymmetry is the design: LIVE tries for ~50ms then proceeds anyway (so a
command degrades to slow, never to failed), while BACKGROUND blocks and
releases between every call, plus a short yield gap so two boards cannot starve
each other. Declared by `MACALENDAR_LLM_PRIORITY`, defaulting to LIVE so that
forgetting makes a board rude rather than making a user wait.

Every call that generates or loads is inside a `hold()`, and
`tests/unit/test_model_protocol.py` reads the tree to prove it — `llmseg` owns
its own socket, so a gate placed only in `IntentParser` would have had a silent
hole, and a gate with a known hole is worse than none.

### 0 · ingest (`ingest/coalesce.py` + the orchestrator's run lock)
Two halves, both live. **Serialization**: `run_transcript` holds a lock — one
command at a time, FIFO, so concurrent requests cannot race the anaphora
context; the wait shows honestly in the trace total. **Coalescing**:
`ingest/coalesce.py` (`coalesce` / `coalesce_groups`, which the server's
pending loop calls) combines queued inputs into `("…")and("…")`
batches under `engine.coalesce_max_tokens` (a wrapper step 2 splits
deterministically), overflow running sequentially — used by the pending-retry
loop, where server-side inputs genuinely pile up, and only within one stream
(the server groups by `model_protocol.stream_key`); the phone's bracket batching flows through
step 2 as before.

### 1 · transcript (`ingest/repair.py` · trace stage `vocab` · tests `test_engine_flow.py`)
Reads `raw_text`; writes `text`, `corrections`, `needs_edit`, `ignored`.
Stop-word strip → spoken-noise cleanup (`intent/cleanup.strip_spoken_noise`)
→ command-frame and misspelled-command-word repair (`repair_command_frames`) →
trivial-transcript filter (a false start is ignored AND not remembered) →
`apply_vocab` (confident fixes, phonetic matching) → the
confidence gate: doubtful words with `engine.confirm_transcript` on and a
client that declared `supports_edit` become a `needs_edit` response — the
client shows an editor and resubmits with `edited_from`. A changed word is
learned as a vocab alias (`learn_from_edit`); an untouched resubmit counts a
confirmation (`confirm_unchanged`, counters beside the vocab in
`transcript_confirms.json` — never inside the hand-curated vocab), and at 2
confirmations the word is whitelisted and never asked about again. The Mac
sends `supports_edit`, shows the dialog (`ask_transcript_edit`, real-click
tested) and has the Settings toggle; iOS sends it too and answers with
`EditTranscriptionSheet` (`VoiceButton.swift`). *Status: live.*

### 2 · segment (`segmentation/` — envelope → FastSeg → LLMSeg(off) → accept · trace `rule` · tests `test_engine_segment.py`)
Reads `text`; writes fresh `items` (id, kind, text, time, source, and — since
2026-09-25 — `relation`, how each relates to the one before it). Biased to
under-split — a wrong merge gets more chances downstream (decompose and the
judge's loop-back); a wrong split of "meeting with Tal and Ravid" is immediate
garbage. `segmentation/__init__.py::run` is the whole stage:

1. **Envelope** — transport delimiters: the ingest queue's `("a")and("b")`
   wrapper, the phone's `[…][…]` batches, the configured spoken separator.
   None can occur in dictated speech; they are opened before any language is
   read.
2. **FastSeg** (`fastseg/fastseg.py`, deterministic, no model) — CUT, ASSIGN
   TIME (`_TIME_PATTERNS`, longest span first), EXPAND ENUMERATIONS ("the dog
   at 9 and 2:30" → two items), TAG. Splits on sequence words ("followed by",
   "then", "after that"; DEVQA Q51).
3. **LLMSeg** — wired, OFF by default (`MACALENDAR_LLMSEG`); with the flag off
   no model call is made.
4. **ACCEPT** — the invariant guard: a model answer that loses or invents a
   word is reverted to FastSeg's.

Then `relate` writes each item's `relation`, and an `other` item (not calendar
work) carries `slots["junk"]` = the reason when `intent/junk.py` recognises a
list-management request (DEVQA Q52).

The tag (`event | task | review | other`) is FastSeg's `tag` / `tag_path`,
whose first reading is `fastseg/kind.py` (`_kind_of` → `_enforce_pinned_kinds`).
It matters more than it looks: decompose branches ENTIRELY on kind. Since
2026-09-24 an item NO rule decided is handed to decompose_validate's kind
router (`kind_router.py`, a learned sklearn model, no ollama) — the tag stands
whenever a rule fired.

*Status: live, FastSeg only. Board: `segmentation/experiments/run_board.py`
(`segmentation/ARCHITECTURE.md` §5); `scripts/kind_board.py` for the kind
decision alone. `engine_stage_check --stage segment` still imports the retired
`old_seg` and does not exercise FastSeg.* The interrogative-create reader lives
in the next stage (`object_rules.is_interrogative_create`), read by its confirm
gate.

### 3 · decompose_validate — the text pass (`decompose_validate/stage.py::run` · trace `rule` · tests `test_engine_decompose.py`, `test_engine_kind_router.py`, `test_sequence_chain.py`)
In order: the kind router (above), `decompose.run`, `text_repair.tidy`, then
`resolve_values` — each item's own `time` resolved into `item.slots` (`date`,
`start_time`, `end_time`, `recurrence`, `recur_days`, `recur_until`,
`quantity`, `reminder_minutes`) by `resolve.py`, checked by `checks.py`, and a
SEQUENCE's untimed parts chained after the one before (`chain.py`, DEVQA Q51;
default length and gap are settings, per category).

`decompose.py`: reads `items`; may replace an item with sub-items (`item_N-M`, depth ≤ 2) and
fill `item.slots`. Two times joined by "and" → two events; task lists ride
`intent/list_split.py` (verb handed down, idioms respected); counts ride
`intent/quantity.py` — "buy 5 apples" is ONE task of (apples, 5).

**Every list split must survive `intent/asks.is_an_ask`** (2026-09-08).
`list_split` is pure string work and cuts at "and" without being able to tell
a request from the words around one, so it produced items like "wash done"
(from "wash the car, done and dusted"), a task called "pack" (from "pack and
label the boxes"), and tag questions as items. The whole split is refused
rather than the bad piece dropped: those words still belong to the command,
and a merged item is recoverable where deleted words are not. The same reader
serves segment's clause tier, so the two cannot drift.

*Status: live — deterministic shapes plus a self-skipping LLM pass for wordier
double-times (two clock-time mentions required; ranges excluded). Gate:
`engine_stage_check --stage decompose`.*

### 4 · decompose_validate — the object pass (`stage.py::run_objects`; the rules are `object_rules.py` + `targeting.py`, the gate `observance_gate.py` · trace `validate` · tests `test_engine_validate.py`)

*`validate.py`, the ported v1 module, was retired on 2026-09-08; the names below
are the modules that own the same passes now.*
`run_objects` runs after FastRule (and on the fast track), because its rules
need `item.intent` to exist. It writes this stage's resolved values onto the
intents (`_resolve_onto_intent`, and a sequence part's chained times), then
the NAMED rules — for edits `anaphor_guard`, `move_time_fill`; for creates
`create_from_remove_guard`, `impossible_clock`, `past_date_bump`,
`passed_clock_means_tomorrow`, `now_means_now`, `morning_title_guard`,
`junk_event_drop`, `max_duration_cap`, `quiet_hours_flag`; then over all of
them `question_creates_nothing`, `question_mutates_nothing`,
`cadence_round_and_announce` (the `_rule_` prefix is dropped here; `now_means_now`
keeps its name but since 2026-10-01 covers every word that names a time —
`intent/time_words.py`, DEVQA Q82 — not only "now") — and the
**observance gate**: an AI-created one-off event inside Shabbat/yom tov
(sundown-bounded) must be leyning / a meal / davening; on a fast day a meal
must not be booked before the fast ends (Yom Kippur: the fast wins). Since
2026-09-08 the gate FLAGS rather than blocks — the event is written with a
note in `slots["flags"]` the speaker can act on. Manual edits/additions are
never gated; series skipping stays in `db._skip_for_observance`. Allowed on
any computation failure.
Every applied rule lands in `state.fixes` under its name and in the trace.

**The confirm-create gate** (`interrogative_create_asks_first`, Gil's ruling
2026-09-07, DEVQA Q9): an interrogative create — "should i add yoga to my
calendar tomorrow?", "what if i booked town hall for the 3rd?" — must neither
auto-create nor be silently dropped. When the client declared
`supports_confirm` and `engine.confirm_create` is on, the item keeps its
validated intent and gets `slots["confirm_create"]`; the orchestrator turns
that into a `confirm_create` response instead of committing. Only when the
question is the WHOLE command — a confirmation holds everything, so in "book
gym at 7 and should i add yoga?" the question half keeps its pre-ruling
behaviour and the booking runs. Without `supports_confirm` nothing changes,
which is what keeps old clients working.

### 5 · fastrule (`fastrule/stage.py` → `fastrule/build.py` · trace `rule` · tests `test_fastrule_build.py`, `test_engine_generate.py` + integration)

**RESTRUCTURED 2026-09-10.** `objects.py` is gone. The stage is a CONVERTER —
`List[Item]` in, objects out — and it **calls no model**, directly or
transitively. Its contract:

| in | out |
|---|---|
| `X3` items, values already resolved by decompose_validate | `X4` `item.action` + `item.intent` |
| | or a **DEFER** on `item.slots["fastrule_defer"]`, which LLMJudge takes at its own entry |
| | or a **flag**: `item.blocked` + `item.slots["fastrule_result"]` ∈ {`bad_item`, `not_an_ask`} |

`build(item, *, today) -> Built | Defer | BadItem | NotAnObject` is the whole of
it, and it is a PURE function — no model, no database, no clock of its own — so
its board is a table of items and expected objects. It COPIES the eight values
(`date`, `start_time`, `end_time`, `recurrence`, `recur_days`, `recur_until`,
`quantity`, `reminder_minutes`) and re-derives none of them; it reads only the
OPERATION, the TITLE, the PEOPLE and the TARGET. `item.kind` may re-kind a
CREATE or a QUERY, never a target-taking operation — that would change which
STORE is searched for an existing record.

**A BadItem is a SUCCESS, not a failure**: the item arrived damaged and the
stage reports that rather than guessing at words nobody said. Which upstream
stage did the damage is attributed by the board, not by the runtime.

`fastrule/fast_track.py` holds the separate whole-command FRONT DOOR
(`fast_propose`), which is where `Atomicity` belongs — at the front door there
is no Item yet, so "one ask or several?" is the right question there and nowhere
else.

The model half — the fallback, both kind fallbacks, and the kind-primed retry —
lives in `llmjudge/rescue.py`. **`fastrule_shape.py` measures the front door and
`stage_board.py` measures the stage; they are different boxes, do not compare
them.**

#### The front door's classifier (unchanged)

**`FastRule`** (`engine/fastrule/fastrule.py`) is the
deterministic rule parser + its abstention gates + a confidence threshold, as
a self-contained SELECTIVE CLASSIFIER: `FastRule(threshold).run(prompt)`
returns a commit-or-abstain verdict (`.committed`, `.intents`, `.confidence`,
`.reason`). Its gates: junk (a list-management request, DEVQA Q52 —
`intent/junk.py`), strong-compound (two-request wording, and since DEVQA Q51 a
sequence seam), mixed-mode (create+edit/query), list-title (one calendar create over three or more listed
things — several events, Gil 2026-09-20), interrogative-create (a question
producing a create), generic-target (a mutation aimed at a bare noun) — and on
a fragment the compound gates double as the atomicity check.

**Layer 0 — atomicity (F16–F18, 2026-09-07).** "One item or several" is the
call the whole architecture rests on (FastRule executes atomic items; deep
is the atomizer), and it is scored on its own board:
`python -m scripts.atomicity_board` reports accuracy, compound P/R/F1 and
BOTH ERROR KINDS AS COUNTS — said-atomic-but-compound (a half-executed
two-ask command, user-facing) vs said-compound-but-atomic (one slow-path
row) — on two datasets, the generated FastRule 7,200 and the verification
pool's real wordings. Three rules hold it together:

- `Atomicity.judge` is **rules OR model, both unconditional** — a union,
  not a fallback chain. Gating the model behind the parse's intent count
  once cost the layer 110 of its 195 B-test misses.
- **The atomicity ANSWER is not the routing DECISION.** A compound whose
  every ask the parse recovered still commits
  (`_parse_covers_the_compound`, intents ≥ ask-joiners + 1) — deferring it
  discards a complete correct answer, and with no LLM reachable discards
  the command entirely.
- `ATOMIC_MARGIN_FLOOR` is **set by a sweep on both training halves**
  (printed by `scripts.fit_route_models`), never assumed.

Threshold tuned 2026-09-07: `RULE_THRESHOLD = 0.80`
(`intent/rule_parser.py`, whole-command). `fast_propose` (whole input) is the
thin adapter over `FastRule(RULE_THRESHOLD)`. (The per-item path that ran
FastRule and then the model on each fragment, at a 0.60 sub-item bar, went
with `objects.py` on 2026-09-10: the stage is now the converter above, and the
model half is LLMJudge's rescue.) `AssistantError` propagates: the
orchestrator owns offline queueing. An interrogative create never takes the
fast track whatever the rules score it (the `interrogative-create` REFUSAL):
only deep can hold a parse and ask first.

Two deterministic fallbacks close the honest-failure ladder. **They live in
`llmjudge/rescue.py` since 2026-09-10** — they fire only after a model parse
comes back empty, so they belong with the model — and are still pinned in
`test_engine_generate.py`, which now runs both stages the way the orchestrator
does. **task_fallback** (run 12) — a task-kind item
never parses to nothing; the item text IS the task. **event_fallback**
(cycle 5) — an event-kind item that still parses to unknown after the
event-kind retry becomes a default-titled event ONLY when the words
literally contain event/reminder/appointment (that noun is the title) AND
the date recognizer grounds a date or clock time in them; nothing is ever
invented, no match stays unknown.

### commit (orchestrator)
The only place the engine touches the database, via the existing action
classes. Two behaviours added 2026-09-24:
- **Save what is ready** (DEVQA Q48, `Engine._commit_ready`): on the live path,
  just before the first model call, every item that has an intent, is not
  blocked and draws no finding from `verdict.judge` is written through `_commit`
  and marked `slots["committed_early"]`; the end-of-run `_commit` skips those.
  Boards drive parse and judge themselves on a scratch store and never take it.
- **The other list** (`_other_store`): a change or delete whose target is not
  on the list the parse named is retried on the other one (event ↔ to-do) when
  exactly one title matches there, before any not-found message; the title
  matchers try the whole name first, and a tie between two different titles
  matches nothing.

 Two gates stop execution before it, both the same shape: step 1's
`needs_edit` (doubted words) and step 4's `confirm_create` (an interrogative
create, offered as a ready-to-POST `proposal` — the orchestrator only
short-circuits; the reading is the stage's). Blocked items → explained refusal; `unknown` → honest "didn't
understand"; `TargetNotFound` → the not-found message (empty slots are the
right answer for a delete; guessing is not). Records `(kind, row_id, action,
idx)` per item for the command memory and the 24h corrected/rejected hooks.

### 7 · label (`label/label.py`, run INSIDE commit · trace `validate`)
Categories/colours and task tags are applied by the actions themselves
(`categories.py`, `tagging.py`); this stage reads the results back onto
`item.labels` so reply, trace and audit can see them. The two-level hierarchy
(row 58) lands here.

### 6 · llmjudge (`llmjudge/llmjudge.py` · trace `verify` · tests `test_engine_llmjudge.py`, `test_engine_crosscheck.py`, `test_engine_contracts.py` for the router)

**Rebuilt 2026-09-10** (`llmjudge/PLAN.md` §6, Gil). Job 0 answers FastRule's
DEFERs (`rescue.py`); job 1 is the check:

0. **No model in the check.** The two copying questions this section used to
   describe (`extract_asks`, `ground_claims`, in `evidence.py`) are RETIRED:
   the ask diff went on 2026-09-10 and the grounding call the same day
   (`retired/llmjudge-grounding-call/` — 57% of all model traffic, no outcome
   changed). The stage's only model calls now are job 0, `rescue.py` (reading
   what FastRule deferred), and the model tier of `rewrite.py` (writing X1'
   when the deterministic rewrite has nothing new to say).
1. **DECIDE deterministically** (`verdict.py`). The temporal fields never reach
   the model: `CalendarIntent` stamps a date and a clock the moment an object
   exists, so `item.slots` — what decompose_validate really resolved — is the
   only honest record, and `render.unsupported_by_slots` reads it for free.
   Findings: `ungrounded_subject` · `coordinated_subject` · `unsplit_subject`
   · `unsupported_field` · `not_an_ask`. (`missing` and `extra` went with the ask diff on 2026-09-10;
   `wrong_fields` and `format` are GONE: the old `BLAME` map listed both and no
   code path ever constructed either.)
2. **ROUTE by finding TYPE, never by opinion** (`findings.py::ROUTE`, pinned by
   `test_engine_contracts.py`): `ungrounded_subject`, `coordinated_subject` and
   `unsplit_subject` → REWRITE; `unsupported_field` → COMMIT with a notice; `not_an_ask` → the
   review panel. Only the three SUBJECT findings spend a round, because a
   rewrite cannot invent a date nobody said and a re-run cannot un-produce an
   extra.
   `coordinated_subject` (Gil, 2026-09-20) is one calendar event whose words
   list three or more things — "create an event for dentist, haircut and gym"
   — and its X1' is one clause per thing, every word the speaker's: *"on
   friday create an event for dentist and on friday create an event for
   haircut and on friday create an event for gym"*.

Loop-back: `rewrite.py` builds **X1' — the failed asks only, reworded** — in
two tiers (Gil, 2026-09-20). Tier 1 is deterministic: the failed asks in the
speaker's own words, joined by " and ", or one clause per listed thing. Tier 2
is the MODEL, asked only when tier 1 has nothing new (the string was already
tried) or cannot help (an `unsplit_subject`: a trim of one object's words
drops the other ask — measured, the recurrence and the milk gone): it is shown the
transcript, the leftover, the finished asks, and every earlier attempt with the
judge's complaint about it, and it answers a LIST of asks — verb first, one
thing per line, time and recurrence phrase at the end of the line they belong
to — which code joins as the ingest envelope `("a")and("b")` so segmentation
opens the cut before it reads any language. The orchestrator FREEZES the
objects that passed (`engine.parse(frozen=…)`, ids re-prefixed per round)
rather than re-parsing them, so nothing is built twice and `_commit` still runs
exactly once. ≤ `MAX_REENTRIES` (3) per command; **on exhaustion an object whose
subject still NAMES NOTHING is held back, not written** (`engine._block_
unresolved_subjects`, 2026-09-20): the same `_GENERIC_TARGET_RE` the fast
path's REFUSAL uses, so 'event', 'Appointment' and 'this on my calender' are
refused on both tracks instead of one. An object whose subject is SPECIFIC but
unsupported ("Washington, D.C trip") still commits with its notice — a wrong
title is one tap to fix, a missing event is not. Otherwise on exhaustion commit the best
attempt, say so, mark the memory record uncertain. **Both tiers fail CLOSED**:
every content word of X1' must already appear in the transcript (creation
verbs exempt, destructive verbs never), a model line that invents a word
refuses the whole answer, and no honest rewrite means no loop. On the fast track this
stage patches the committed answer — **tiered**: additive fixes silent,
destructive corrections visible with one-tap revert. It owns what used to be
four bolt-ons: the background verify, both placeholder-title fixers, the
not-found second opinion (the last still lives in commit, `_recheck_not_found`
/ `_other_store`, until this stage absorbs it). *Status: live. Foreground:
rescue + deterministic check + loop-back run pre-commit, budget honoured,
exhaustion admitted in the reply. Background (fast track,
`_start_background_verify`, skipped for `source: "test"` and under
`MACALENDAR_NO_WARMUP`, and when `engine.reconcile` is `uncertain` and the rule
confidence ≥ 0.95): verify token issued, placeholder titles renamed (minor —
the one model call on this path, `fix_title_async`), a `not_an_ask` row
reported as major — ADVISORY unless `self_check_apply` is on. (The additive
"missing ask" patch went with the ask diff on 2026-09-10.) Advisory, because the old always-on
verifier measurably proposed far more than it fixed (78 proposals, 0 fixes,
2026-08-28). **One-tap revert (done 2026-09-04):** when a removal *is* applied,
`_remove_extra` captures the row first and the correction carries
`revert: [{kind, body}]` — ready-to-POST `/events`/`/todos` bodies. An applied
change is also echoed to the Mac HUD as a late `verify` step (the foreground
trace's bus listener is still attached), carrying the same specs; the review
panel's `_RevertBar` and the iOS banner re-POST them to undo. Gate:
`engine_stage_check --stage crosscheck`.*

## The response contract (unchanged from the old brain)

`message, actions, refresh ("events"|"todos"|"both"|""), parse, transcript,
original_transcript, corrections, trace, boundaries, uncertain_words, brain,
hint, committed` + optional
`memory_id, verify_token, pending_id, needs_edit`, and for a confirm gate
`proposal` (`[{kind, body, summary}]`, bodies shaped for POST /events and POST
/todos) plus the server-minted `confirm_token`, answered at
`POST /voice/confirm`. Trace stage names stay
`stt/vocab/rule/memory/llm/validate/execute/verify/done/error` — the iOS
timeline and the HUD key off them. LLM offline ⇒ pending queue + honest
message; trivial ⇒ `parse: "ignored"` with nothing recorded.

`hint` (2026-09-22, additive) is `null` or `{code, headline, body}`: one
coaching line the phone draws once per code above the mic — `bare_title`
when a create committed with a title that is only the kind of thing
('meeting'), `title_refused` when an item was held back for naming nothing.
Its own key because `message` is spoken. Words in `assistant/tips.py::HINTS`,
the pick in `engine._hint`, the ruling in DEVQA Q41.

`committed` (2026-09-28, additive) is `[{kind, id, action}]` — the rows this
command wrote, from each successful `ExecutedAction.record`. It exists so a
client can compare a reading of its own with the engine's: the phone's offline
reader resends a command with `offline_reading`, and `assistant/offline/
reconcile.py` reads these rows back to answer `same` / `changed`
(`assistant/offline/PROTOCOL.md`). No stage reads it.

## Config knobs (mirror into config.example.yaml)

`engine.confirm_transcript` (step 1 gate), `engine.confirm_create` (step 4
gate), `engine.reconcile`
(`always|uncertain`, step 6), `engine.fast_track` (`on|off` escape hatch),
`engine.coalesce_max_tokens` (step 0). The routing threshold stays
`RULE_THRESHOLD` in `intent/rule_parser.py`; `rule_confidence` is recorded on
every command so it can finally be calibrated from outcomes (row 57).

## Fixing a stage

1. Reproduce in the stage's own test file, or via
   `scripts/engine_stage_check.py --stage <name>` (Ollama-guarded, scratch
   stores, `source: "test"`).
2. Improve the stage's internals until its tests and stage check pass.
3. Run the audit; read the per-stage lines, not just the headline.
4. If you believe the *contract* is wrong: that is a design change — take it
   to TASKS.md, don't slip it into a fix.

## The thinking panel renders by brain version (merge requirement)

`assistant/trace.py` holds `BRAIN_VERSION` (currently `"engine-v3"`; `"engine-v2"` is kept so older traces render), `CHAINS`
— the single source of truth for how a brain's chain of thought reads, as
ordered `(stage, short-label)` pairs matching the explorer diagram — and
`STAGE_INFO`, the in-depth "what this step is" copy behind each slot's ⓘ,
mirroring the explorer page's per-stage aria-labels. The engine stamps
`BRAIN_VERSION` onto every response (`resp["brain"]`, which iOS reads) and every
trace-bus payload (`result["brain"]`, which the HUD reads), and
`thinking_panel._ResultCard`/`finish` stashes it as `self._brain`.

**Both panels render this chain as a scaffold** (done as of 2026-09-04). A
`_ChainRail` (Mac `thinking_panel.py`) and the mirrored `chainRail` (iOS
`ThinkingView`) draw the `CHAINS[brain]` slots as a compact rail above the live
timeline, naming the version and lighting each slot done / active / skipped as
the live steps arrive (mapped to slots by stage, in order — the two `rule`
slots and any self-skipped stage resolve correctly). Each slot carries an ⓘ
that reveals `STAGE_INFO[brain][label]` as a tooltip (Mac) / popover (iOS). The
raw per-step timeline still shows below, with its real titles and timings — the
rail is the map, the steps the journey.

Keeping it honest: bump `BRAIN_VERSION` whenever the pipeline's shape changes so
an old trace still renders in its old format; add the new slots' `STAGE_INFO`.
`test_panel_agreement` fails the build if a `CHAINS` slot has no `STAGE_INFO`
entry, and `test_stage_info_parity` fails if the iOS Swift copy
(`EngineChain.scaffold`) drifts from the Python source. A future claim-check
can also assert the explorer diagram's step labels equal `CHAINS["engine-v3"]`.
