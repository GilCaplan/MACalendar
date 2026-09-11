# DEVQA — async questions for Gil

Instead of interrupting with prompts, questions live here; answer inline
whenever (a one-liner under the question is enough). I may edit or withdraw a
question if the data resolves it first, and I keep the list SHORT on purpose —
if it ever grows past a handful, the newest ones can wait. Answered items move
to the log below so decisions stay findable.

## Open

*(nothing open — Q13 ruled 2026-09-11.)*

## Answered (log)

- 2026-09-11 — **Q13 (fast commit on a compound)**: the carve-out is FINE —
  Gil: *"Q13 seems like that is fine."* `_parse_covers_the_compound` STAYS:
  when the rule parser has itself read every ask (intent count >= ask-joiners
  + 1) FastRule commits, even though layer 0 called the row non-atomic. Layer
  0 keeps reporting "compound" honestly — that is its board, and it is the one
  that improved — while ROUTING is allowed to act on a complete answer. The
  cost of the alternative is what decided it: deferring all 129 such commits
  would throw away 103 correct answers into a ~35 s deep pass, and lose them
  ENTIRELY when Ollama is down ("book gym on tuesday at 7am and remind me to
  buy milk" produces nothing on the deep track with the model unreachable,
  where fast produced both records). So `fastrule_shape`'s non-atomic defer
  rate stays ~78.2% rather than 95.6%, and that gap is a known, chosen
  reading of the board rather than a defect to chase. **Do not "fix" the
  defer rate by deleting the carve-out.**

- 2026-09-07 — **Q9 (interrogative creates)**: "should i add yoga to my
  calendar tomorrow?" must neither auto-create nor be silently dropped — pop a
  confirmation showing the parsed proposal; YES creates it, NO discards it and
  the memory record marks it declined. → *Implemented:* the confirm-create
  gate (`parse: "confirm_create"` + `proposal`, `POST /voice/confirm`, Mac
  Add/No box, iOS alert) — FEATURES.md and ENGINE.md carry the detail.

- 2026-09-06 — **Q2 shipped without needing an answer**: the observance
  checkbox is in the Mac settings dialog (243d99f), persisted via
  config_store — and building it exposed that `observance.enabled` was
  silently DROPPED by pydantic (`ObservanceConfig` never declared the
  field), so the yaml flag never reached `is_enabled()`; only the env
  override worked. Field declared + pinned by test.
- 2026-09-06 — **Q3 withdrawn** (API key): the model sims ran through Claude
  Code subagent workers, no key needed; the experiment is closed on partial
  data (llama beat both drop-ins — `dataset/MODEL_COMPARISON.md`).
- 2026-09-05 — **Old-brain comparison**: Gil doesn't care about it; the
  questions that matter are "is the new system better, and can it get
  better?" → answered in chat (yes / yes); vs-old numbers stay incidental.
- 2026-09-05 — **Invention vs missing**: balance both, F1-style. →
  *Implemented:* item-level micro precision/recall/F1 in the harness
  (`_prf`), reported per run + by complexity + untuned sub-slice.
- 2026-09-05 — **Overfitting the subset**: authorized to resample a fresh
  same-size slice and mark it in the log. → Standing policy in the protocol.

- 2026-09-05 — **Shabbat gating in tests**: turn off via a user-controllable
  flag; replays must simulate each row's recorded timestamp. → *Implemented:*
  `observance.enabled` + `MACALENDAR_OBSERVANCE` env override standing down
  both gates; the harness freezes each replay at the row's `ts` (freezegun).
- 2026-09-05 — **Separate task lists**: no — lists stay Today/General plus
  tags. → Queue #6 closed; "create a new list" dataset rows are accepted
  convention losses.
- 2026-09-05 — **Merging**: fold the loop branch into `main` every few
  graduated cycles. → Standing policy in ITERATION_PROTOCOL.md; first merge
  done (@ a425ca2).
- 2026-09-04 — **Date-only occasion reminders**: calendar events. → Cycle 2.

## Answered log

**Q16 (2026-09-11, Gil): a trailing deadline is shared ONLY when it is
EXPLICIT.** "submit the grades and prepare the slides **by friday**" — the
marker ("by", "before", "due") scopes friday over every TASK in the utterance.
A bare trailing date shares nothing, and events never share at all: an event's
date belongs to that event. Gil: *"if explicit add, otherwise don't, for
tasks"* — and *"this should be what decompose_validate does, fixing the dates
if possible from item type."* So it is a DATE rule keyed on `item.kind`, in the
stage that already resolves dates, not a segmentation change. The asymmetry
that prompted the question (segment shares only an OPENING date, never a
trailing one) stays exactly as it is; this adds the explicit-marker case on
top of it, downstream.

**Q11 (2026-09-11): WITHDRAWN — the question was out of date.**
`FASTRULE2_DESIGN.md` asked permission to build five components. They were
built the same day it was written (4657fe9, 2026-09-07: "Rebuild: one object
per component… v2 wired into the engine"), and the design was then superseded
two days later by `assistant/engine/fastrule/PLAN.md` (2026-09-09), which
reframes FastRule as a CONVERTER rather than a parser and supersedes the v2
component split. Nothing was waiting on an answer. `FASTRULE2_DESIGN.md` now
says so at the top; `fastrule/PLAN.md` is the live plan.

**Q6 (2026-09-11, Gil): NO reminders for events inside Shabbat / yom tov.**
Confirms the shipped default — suppress entirely; no pre-candle digest. The
alternative is closed, not deferred.

**Q15 (2026-09-07, Gil): a DAYPART IS NOT A CLOCK TIME.** "remind me to take
the trash out tonight" is **a task to do in the evening**, not a calendar
event. The pinned reminder convention turns on a real clock time ("remind me
about the dentist tomorrow AT 9AM" = event; "remind me TO <verb>" = task),
but `segment._CLOCKISH_RE` lists `tonight|morning|evening|afternoon`
alongside actual times, so any remind-phrased errand with a vague daypart
became a calendar entry. A daypart is a rough WHEN — it belongs in the
task's due time, not in the decision of what kind of thing this is. This is
the single largest mis-kind driver: **499 of 609** on the FastRule test half,
383 of 418 on the personas. Fixed in sprint cycle B.

**Q14 (2026-09-07, Gil): "buy apples and eggs" is TWO tasks** — same action,
separate items ("buy eggs", "buy apples"). This settles a contradiction the
atomizer board found between our own documents: `decompose.py` and
`list_split.py` split shopping lists; `assistant/engine/fastrule/datasets/DATASET.md` labelled
them one task titled "apples and eggs". The CODE was right. Every over-split
in the FastRule test half was this disagreement and nothing else — so those
were never defects. **The dataset's np_decoy families need relabelling**
(a list of things for one verb = one item PER THING); the genuine
never-split case is a list of PEOPLE or a shared object ("meeting with Tal
and Sam", "wash and fold the laundry").

**Q13 (2026-09-07, Gil): non-atomic behaviour is DIAGNOSTIC, not a target.**
"I just want to see that it succeeds on recognising and executing well on
atomic items, and we can decide what to do with non-atomic which is run
through anyway and pass that to the next stage and let the engine decide."
So: the PRIMARY metrics are atomic handle-rate and correct-on-handled;
FastRule's atomicity call is information handed upward (the REFUSAL /
STRUCTURE / INCAPACITY contract), not a verdict it must get right alone.
The non-atomic bucket is reported as three outcomes — covered (acceptable,
and the only path that survives the LLM being down), half-executed (the real
defect), deferred — with no single "violation" number. `_parse_covers_the_
compound` stays.

**Q12 (2026-09-07, Gil design ruling): the retry loop must CHANGE the input,
and the LLM is the last resort.** Two parts. (a) **Determinism rule:** when
the crosscheck loop-back re-enters an atomic item, FastRule must not be
asked the same question twice — identical text gives an identical verdict by
construction, so a re-run on unchanged text is wasted work. On re-entry,
either the item's text differs from the attempt that failed (the LLM stages
rewrote it) or FastRule is SKIPPED for that item. (b) **Escalation rule:**
after the retry budget (3) is spent on an atomic item, the final attempt
belongs to the LLM — it creates the event/task directly rather than
deferring to a deterministic parser that has already failed on that exact
text. Implementation: per-item attempt fingerprints on EngineState;
generate consults them before calling FastRule. Deferred until the in-flight
sealed run finishes (engine files are read-only during a measurement).

**Q10 (2026-09-07, Gil design ruling): Stage-2 routing becomes TWO tiered
subsystems.** (1) KIND — event vs task; (2) OPERATION — new/edit/remove/
complete/query. Each is rules-first (regex/tables/pinned conventions answer
when confident — trivial cases stay trivial and Gil's rulings stay
sovereign) with a small logistic-regression model as the fallthrough when
rules aren't confident. Action = kind × operation, composed. K1 is the KIND
subsystem's model (proven 99.0/98.5); K3 is the OPERATION subsystem's model
(labels free in dataset B). A rules-vs-model disagreement is an abstain
signal. Implemented in the lane (F-batches), integrated at F15.

**Q9 (2026-09-07): interrogative creates → CONFIRM PROMPT.** "should i add
yoga…?" neither auto-creates nor gets silently dropped: the client pops a
box with the parsed proposal — yes creates it, no discards it. Same
response-contract pattern as the transcript-edit gate (`needs_edit` +
`supports_edit`): the server sends a proposal payload only to clients that
declare `supports_confirm`; older clients keep today's behavior (deep
decides). Dataset's interrogative families relabel to expect a PROPOSAL,
not a create — labels follow product.

**Q8 (2026-09-07): APPROVED — "can try the q8 idea."** A small logistic
regression over hand features for the event-vs-task kind decision, fit
offline on dev labels, deterministic at inference. Ships only if it beats
the regex family in a measured cycle; negative result gets banked too.

**Q7 (2026-09-06): object-based restructure APPROVED — with the acceptance
criterion in Gil's words: "the logic doesn't change at all nor should the
results, should just be cleaner." All three recommendations confirmed:
(1) pure refactor first, cycle 10 separate; (2) `run_transcript` stays as a
shim; (3) shared Component interface. Verification bar: full test suite
green + a behavior-identical confirmation run against the era-2 baseline
before merge.**

**Q1 (2026-09-06): dated "I need to <meet/talk>…" = EVENT.** Implemented same
day: `_NEED_ENCOUNTER_RE` in segment's pinned-kind rules (encounter verbs +
date/clock ⇒ event; errands and undated encounters unchanged) + unit tests.

**Q4 (2026-09-06): Mac reminders with the calendar closed = a notification-
settings OPTION.** Queued in TASKS (app stream): settings toggle first, the
LaunchAgent detach ships behind it, default off.

**Q5 (2026-09-06): default lead time = PER CATEGORY.** Matches the built
mechanism (`resolve_lead`: event override → category lead/mute → fallback);
the per-category leads in notification settings are the primary surface.

**Q6 (2026-09-06): events inside Shabbat/yom tov get NO reminders.** The
shipped suppress-entirely default is confirmed; no digest.
