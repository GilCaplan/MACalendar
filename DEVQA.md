# DEVQA — async questions for Gil

Instead of interrupting with prompts, questions live here; answer inline
whenever (a one-liner under the question is enough). I may edit or withdraw a
question if the data resolves it first, and I keep the list SHORT on purpose —
if it ever grows past a handful, the newest ones can wait. Answered items move
to the log below so decisions stay findable.

**One Open section, one Answered log.** There used to be two un-nested
"Answered" headings, so Q4 sat in one and Q6 in both and anyone scanning for a
ruling read half the file. Merged 2026-09-14 into a single reverse-chronological
log; nothing was dropped. If you add a second heading, you re-break it.

## Open

Five, added 2026-09-14 after an audit reconciled every planning doc against the
code. The previous text here read *"nothing open"*, which had been false for a
while: three of these were sitting in other documents marked "for Gil" and had
simply never been moved in front of anyone.

**Q24 — unknown-word confirmations: default ON?** `REAL_SPEECH_PLAN.md`
Phase 2. A fast-path title containing a word that is not English, not in the
vocabulary and not a known name ("Poe Konaight") would be OFFERED through the
confirm gate with the vocab's phonetic guess, instead of committed in 400 ms.
Built on `engine.confirm_unknown_words` either way; the default follows Q22
(ask, don't guess). A no here flips the default, nothing else.

**Q25 — is the real-usage board the primary direction-setter?** Phase 1
replays the 95 real commands with Gil's corrections as gold. CLAUDE.md already
ranks real usage above every board; ITERATION_PROTOCOL says direction comes
from "the training pool". This asks whether that pool is now the history —
with the corpus boards as regression floors. It is NOT the synthetic
realspeech dataset that was dropped; it is the data that already exists.

**Q26 — Phase 4: the TITLE EXTRACTOR is ANSWERED (2026-09-20, see the log):
rewrite it properly.** The TEMPORAL RESOLVER half stays open — not started
without a yes. Both inside `rule_parser.py`, contracts untouched.

**Q28 — ANSWERED 2026-09-20, see the log below.** Found 2026-09-19 while
closing the front door's title leak. *"book team meeting tomorrow at 7"* is
**19:00 on the fast path** (`rule_parser._pick_business_hour_time` prefers PM
for 1–7, and `_extract_temporal`'s post-process bumps 1–7 to PM unless a
morning word is present) and **07:00 in `decompose_validate`** (its conventions
table, your ruling of 2026-09-08: *bare hour 1–6 is PM; 7–8 is PM only with
evening words — "gym at 5" is not 5am*). The same sentence gets a different
answer depending on which path routes it, and the deep path's validate never
sees the fast path's value to correct it (on the fast path it receives the
intent's title alone). One ruling — is 7 an evening hour by default, or only
with evening words? — and the losing reader is aligned as an implementation
fix and measured on the FastRule product-shape board's `explicit time right`
line (79.5%, n=527, train). **Answered and built 2026-09-20** — the ask, and
the deep reader aligned to the fast one.

**Q17 — Snooze: keep or kill?** It is the ONE notifications phase-5 item with no
ruling. The phase is the phase-5 row of `DOCUMENTATION/NOTIFICATIONS_PLAN.md`
(*"snooze action"*), and everything else there has an answer — the Live
Activity card shipped, LaunchAgent detachment is Q4, lead times Q5, Shabbat
suppression Q6. Snooze has none, and nothing has been
built against it: `grep -ri snooze` over `assistant/` and `MACalendar-iOS/`
returns zero hits (checked 2026-09-14; the only repo hits are two doc lines and
the intent names in an external-dataset survey). The phase cannot be closed
while it is undecided, so it is a yes/no, not a design question.

**Q18 — where does an enumeration header's COUNT live, and does `other` carry
it?** Raised inside segmentation's own docs, marked "for Gil", never moved here —
so these have not actually been in front of you. **They are one decision, not
two.**

You already ruled the count MATTERS (`segmentation/PLAN.md:482`, 2026-09-09:
*"well the two tasks part is important"*), which reverses the dataset's reading:
for *"two tasks due tomorrow buy groceries and return the book"* the gold drops
`two tasks`, and it should not — a header that says "two" is free supervision for
the item count, which is exactly what the cut is trying to get right. What is
undecided is WHERE it goes, because it belongs to neither item's action:

| option | cost |
|---|---|
| keep it in the first item's action | makes `two tasks due tomorrow buy groceries` a title |
| a new field on `Item` (`count_hint`) | a contract change, and the next stage is built on the current shape |
| its own item with a fourth `tag` value (`other`) | your own idea from the tag-question ruling — and it makes the two questions ONE question |

All three are contract-level, which is why nothing was patched. **5 rows** are
affected, so nothing is urgent — but the `enumeration-header` trap sits at 0.0%
and stays there until this is answered (`PLAN.md:455-505`, `ARCHITECTURE.md:69`).
Note this is a STRUCTURE question, so the 2026-09-14 partial lift of the
segmentation freeze (logged below) does **not** cover it; it needs this ruling
either way.

**Q19 — which layer owns the event-vs-task call?** (Engine audit P10,
`ENGINE_AUDIT.md:518-543`.) Four independent deciders today, re-verified
2026-09-11 and still true on 2026-09-14: `_kind_of` in `old_seg/segment.py`,
`_lexicon_kind` and `tag` in `fastseg.py`, `_kind_for` in `fastrule/objects.py`,
and the learned `KindFeatures` in `intent/classifier.py`.

**The obvious unification is already refuted by measurement**, which is why this
is a decision and not a cleanup: rebuilding `KindFeatures` on segmentation's
"proven" regexes regressed **kind macro-F1 82.6 → 80.5 on the classifier B-set
test half** — the union of both feature sets scored 81.4, also worse — and was
reverted (F13's ACTUAL entry, `dataset/RESULTS.md`). Meaning: the four readers
are not interchangeable, and collapsing them to one costs accuracy. What is
missing is not a merge, it is a statement of which reader is AUTHORITATIVE for
which decision. The live asymmetry: segment's conventions (the reminder rules, the
"calendar invite" rule, the encounter-verb rule) exist only on the deep path, so
FastRule cannot consult them at all.

**Q20 — `engine-component-folders`: merge, rebase, or abandon?** 34 commits of
finished, tested engine work — FastRule phases B and C, LLMJudge's `rewrite.py`
(286 lines, against `return None` on HEAD), Label's two learned classifiers, and
the accessor move into `engine/llm.py`. It diverged at `46f7967` (2026-09-09) and
HEAD has gone its own way since: `git rev-list --left-right --count
HEAD...engine-component-folders` returns `50 34` (checked at `c7f1b11`,
2026-09-14). Both sides touched the same files for different reasons, so this is
a judgement call, not a mechanical merge.

**The disk-failure risk is closed** — it was unpushed when the audit found it,
and has now been pushed: `origin/engine-component-folders` is at `8fac94d`.
What remains open is only what to do with it. Until that is answered the cost is
concrete: anyone told to "start FastRule phase B" writes it a second time and
loses the two real defects the branch's 32 tests already caught.

**Q21 — the fast-path fence vs. the checkpoint retrospective.** STATUS.md's
user-gated backlog bullet fences fast-rule mining: *"add fast-rule-parser rules
mined from the user's real data + the dataset. Only on Gil's explicit say-so,
and only after the deep track is improved."* The retrospective now points
straight at the fenced thing. On the **sealed 300, count-correctness, split by
which path `main` took**: the 130 rows it routes FAST score **93.1%**, the 170
it routes DEEP score **65.3%** (the checkpoint sweep's matched-rows table in
`dataset/RESULTS.md`). The cheap deterministic path is 28 points ahead of the
expensive one, which inverts the premise the fence was written under, and
`RECOMMENDATIONS.md:34-39` calls raising fast-path coverage the highest-leverage
lever available.

Two things constrain the answer rather than settle it, and both should be read
before you rule:

- **Those numbers may not choose the work.** Every row in that table is
  `split:"test"`. The leakage rule binds (`RESULTS.md`, "THE LEAKAGE RULE
  STILL BINDS"): it is a REPORT, not a direction. The legal re-derivation is
  `fastrule-v1` vs `main` on dev-fast-250, which is freely mineable — and that
  re-derivation is the first real cost of saying yes.
- **Half of it may already be permitted.** A yes is mostly threshold and gate
  CALIBRATION, which the 2026-09-14 partial lift below allows as implementation
  work inside FastRule. What the fence names explicitly is MINING new rules from
  your real data. Those are different jobs; say which side calibration falls on.

## Answered (log)

- **2026-09-17 — Q23: the lock-screen card is the day's AGENDA, not a
  countdown** (Gil). Both designs were built, rendered side by side and put in
  front of him rather than argued about; he rejected the countdown outright
  (*"Option A is against what i want"*) and chose the agenda (*"option B where
  it shows day agenda and dynamically has a light over the current event is much
  better"*). `app-features` merged into `main` on that ruling; the countdown's
  `Text(timerInterval:)` / `ProgressView(timerInterval:)` are gone.

  Worth keeping for the next time two branches solve the same complaint: the
  countdown had been PATCHED the same day, on his feedback to remove an
  "elapsed" label — because the agenda rewrite was sitting on an unmerged branch
  and the card on his phone was still the old one. The feedback that looked like
  "fix this design" was probably "this is the wrong design", and only showing him
  both settled it.

  Three behaviours came with the choice, all his words:
  - **A cleared card stays cleared** — *"if i clear it, it shouldn't reappear"*.
    Until 06:00 the next morning.
  - **06:00 respawn** — *"It should respawn everyday at 6am"*. Best-effort:
    `BGAppRefreshTask` is a request, not a timer, and exactness would need an
    APNs push this project will never have. Recorded as a limit, not hidden.
  - **Its own switch** — *"can also make it respawn or shut off with a toggle
    button in the settings"*, and shared with the Mac so the two screens cannot
    disagree.
  - **Look** — *"make sure its doesnt look to ai generated, a liquid glass look
    would be nice"*. Real `.glassEffect` on iOS 26, hand-built material below it.

  **LOCKED, 2026-09-18** (Gil, on seeing the agenda card land on his phone:
  *"Its good make sure in md file it doesnt get changed unless i request"*).
  The card's SHAPE is settled: today's remaining agenda, current event picked
  out by a glow, no countdown. Do not redesign it, do not reintroduce a
  ticking number, and do not "restore" the countdown because a complaint
  about the card sounds like it wants one — this ruling is what a complaint
  should be read against. Only Gil asking reopens it. Fixing a bug in the
  agenda card is not a redesign and needs no permission.

- **2026-09-17 — Q22: a RANGE date is asked about, never guessed** (Gil). What
  should `"book yoga class next week"` mean, when the recogniser hands back a
  span (21–28 Sep) and not a day? Options put to him were: take the soonest day,
  take it uniformly, keep deferring, or ask. He chose **ask** — the day is
  resolved and then OFFERED through the existing confirm-create gate (Q9), from
  the fast parse with no model call.

  Consequences, because this one changed a metric as well as a behaviour: a
  create with a range date no longer commits silently, and an update or delete
  with one does not execute at all (`range-date-target`, a REFUSAL) — acting on
  a day the speaker never said is the destructive guess the project already
  rules out. The FastRule board deliberately EXCLUDES range phrases from its
  date metric ("no single right answer"), which is why this needed a ruling
  before it could be scored at all.

- **2026-09-17 — Q4/Q5/Q6 RE-RULED for notifications** (Gil). All three had
  been answered on 2026-09-06 and two docs still called them blocked; these
  supersede those answers. **Q6 is a reversal**, and of a ruling confirmed
  twice.

  - **Q4 — Mac reminders with the calendar closed: ALWAYS SHOW.** *"Always show
    unless user has it turned off in settings or cleared it on lock screen."*
    The 2026-09-06 answer made this an option defaulting to **off**; the
    default now flips to **on**. Dismissing on the lock screen counts as the
    user clearing it, and is not a reason to re-show. Still unbuilt: it changes
    the launch model (a LaunchAgent, `--reload`, HUD lifetime, shutdown
    ownership), which is why it was opt-in before — now it is on, that work is
    on the critical path rather than behind a switch.

  - **Q5 — default lead time: 0.** The 2026-09-06 answer said "per category",
    which is the MECHANISM (`resolve_lead`: event override → category
    lead/mute → fallback) and is unchanged. What changes is the FALLBACK at the
    end of that chain: 0, i.e. fire at the event's start time. A category with
    its own lead still wins.

  - **Q6 — Shabbat/yom tov suppression: A SETTING, not a rule.** *"This
    filter/block is controlled in settings by toggling on/off."* This
    **reverses** 2026-09-06 and its 2026-09-11 re-confirmation, both of which
    said suppress entirely and called the alternative "closed, not deferred".
    It is now the user's choice, defaulting to suppress (the shipped
    behaviour, so nobody's phone changes under them).

    **Scope: notifications only.** It does NOT touch the engine's observance
    rules — a series still skips Shabbat and yom tov, a one-off inside them
    must still be leyning, a meal or davening, and nothing is skipped when
    observance cannot be computed (CLAUDE.md, "Recurring events"). Those govern
    what is CREATED; this governs whether a reminder for something already
    there is allowed to ring.


- **2026-09-16 — Q14 REVERSED ("buy apples and eggs" is now ONE task).**
  Found while investigating a FastSeg v2 rebuild: `c_npdecoy_buy_two_items`/
  `c_npdecoy_buy_two_party` still gold "buy shampoo and apples" as ONE item,
  directly contradicting Q14 (2026-09-07, below) — which ruled the opposite
  and explicitly said those same families needed relabelling to split. That
  relabelling was never done; the dataset has been sitting in a half-migrated
  state for 9 days, and what looked like "two independently-authored template
  families disagreeing by accident" was actually one incomplete migration.
  Asked directly, twice — the answer changed once Q14's existence and its own
  unfinished relabelling instruction were surfaced, so record BOTH turns
  rather than only the final one: first, unprompted, *"I think its one action
  so should be one action and then the validate_decompose step should handle
  the recurrence (test there and note if need to fix it later)"*; then, shown
  the Q14 conflict directly and asked to choose between finishing Q14 (relabel
  the decoys to split) or reversing it, chose **"Reverse Q14 — one action
  really is one item now."**
  **The ruling, stated plainly: a shared verb applied to a bare, coordinated
  NOUN-PHRASE object list is ONE atomic segmentation item** — "buy shampoo
  and apples", "pick up envelopes and sellotape from the stationers", "buy
  eight sticky notes, apples, and printer paper" — regardless of item count
  (2 or 3+) or whether the objects are generic (groceries) or named
  (calendar entries: "put in the site inspection and the safety briefing").
  If a downstream stage genuinely needs N separate records for N objects,
  that is `decompose_validate`'s job, the same way `_expand_enumerations`
  already treats "walk the dog at 9 and 2:30" as one conceptual ask with
  multiple times, expanded downstream of CUT — not segmentation's.
  **This does NOT touch `wrapper-phrase`** (SPEC.md's own separate,
  already-correct MUST-NOT-SPLIT rule for "add buy milk and buy bread to my
  list" — one verb, one shared destination, already never split) — the two
  traps were independently correct and incorrect respectively; only
  `list-of-things` reverses. **14 rows corrected** across
  `list-of-things-collect`, `list-of-things-source`, `quantity-not-time-
  order`, `quantity-not-time-grab`, `c_threeask_ttt_2`, one `leading-edge-two`
  row, one `as-well-as-plain` row, and two rows already misfiled inside
  `nosplit_traps.jsonl` despite having 2-item gold (`wrapper-phrase-to-my-
  list`/`wrapper-phrase-onto-the-calendar` — a separate, independent
  confirmation this was a real bug, not a judgment call: those rows were
  already living in the "must not split" file with gold that split anyway).
  `SPEC.md`'s trap table and this file both updated in the same change;
  `assistant/engine/segmentation/datasets/*.jsonl` corrected directly, not
  regenerated, since these are hand-authored/hand-curated trap rows.
  FastSeg v1's code is UNCHANGED by this — only the gold moved — so this
  is a pure "how much of the residual gap was actually a gold problem"
  measurement, not a new fix.

- **2026-09-14 — Real-speech dataset: DROPPED.** Gil, verbatim: *"dont do the
  real speech dataset then."* The BUILT ARTEFACTS STAY on disk —
  `dataset/realspeech/realspeech_1200.jsonl` (1,200 rows, 794 KB), `banks/`,
  `REALSPEECH.md` — and what is dropped is FURTHER WORK on it.
  **Recorded here because it was nowhere in the repo**: the 2026-09-14 audit
  went looking for this ruling and found no trace of it anywhere — while the
  **Baseline** line of the open Cycle B prediction in `dataset/RESULTS.md` still
  quotes *"realspeech faithful/test — handled 70.3%, correct-on-handled 85.9%,
  explicit time right 96.2% (n=26), 0 destructive"* as a live baseline. Anyone
  reading RESULTS.md on its own would have picked the work straight back up —
  which is the failure this log exists to prevent.

- **2026-09-14 — Segmentation freeze: PARTIALLY LIFTED.** Gil, verbatim: *"well
  segmentation as long as the structure remains the same, and just fixing
  implementations then its fine. same for fastrules."*

  So: **IMPLEMENTATION fixes inside `assistant/engine/segmentation/` are
  ALLOWED**, and inside FastRule too. **STRUCTURE and DESIGN changes are not** —
  the stage's shape, its I/O contracts, the `Item` tag set, what a cut means.

  **This supersedes the blanket gloss the docs carry.** `TASKS.md` reads *"no
  edits to `assistant/engine/segmentation/` at all while FastRule and LLMJudge
  are the work"* — that is now too strong. The 2026-09-09 quote it rests
  on (*"for now segmentation we leave, I don't want to edit or make changes
  there"*) stands as the DESIGN freeze it always was.

  **It also settles the two "freeze breaches" the audit flagged — they were never
  breaches.** `8fa8e72` (2026-09-11) changed 9 lines of
  `segmentation/fastseg/fastseg.py` as part of three known-wrong-answer fixes, and
  its own commit message banks the check: *"MEASURED, both sides of the
  segmentation change: exact-set 76.6%, right item count 85.3%, item F1 94.6%,
  over-split 46 / under-split 108 rows — IDENTICAL."* `b7687ea` (2026-09-13)
  added 25 lines to `segmentation/llmseg/llmseg.py` wiring it into the new LLM
  call log. Both are implementation; neither moves a contract. **No re-measure is
  owed on the freeze's account** — though `segmentation/experiments/RESULTS.md`
  was last written 2026-09-08, so 8fa8e72's identical board lives only in its
  commit message.

  **What the lift does NOT change:** the ORDER OF WORK. FastRule → LLMJudge → Gil
  decides (`TASKS.md`'s FROZEN note) is a separate ruling and is untouched, so
  `PLAN.md` §0's queue — 3b's under-split compounds, the LLMSeg re-test, §8.3's
  injected date floor, `old_seg`'s retirement, the `other` board — is still
  queued rather than open season. And Q18 above is a STRUCTURE question, outside
  the lift.

- **2026-09-14 — Standing preference (not a question, but it is the tiebreaker):**
  Gil, verbatim: *"i don't really want to make structural changes if i don't have
  to."* When a fix can be made inside a stage's implementation OR as a structural
  change, the implementation is the default and the structural change has to make
  its own case. It is why the segmentation lift above is scoped to
  implementations, and why Q18 and Q19 are parked as decisions rather than picked
  up as work.

- **2026-09-13 — The checkpoint retrospective's fourth recommendation: DROPPED
  as not relevant** (Gil). That was the A/B of the segmentation swap via
  `MACALENDAR_SEGMENTATION`; it is not to be run. **Three recommendations
  survive**, and they are the live queue out of the retrospective
  (`DOCUMENTATION/experiments/checkpoints/RECOMMENDATIONS.md`): the
  not-found-recheck gate, fast-path coverage, and the `llm_ms` recording gap.
  Logged here because that folder is reachable from almost nothing, and the
  ruling would otherwise survive only as a parenthesis inside the file it edits.

- **2026-09-11 — Q13 (fast commit on a compound)**: the carve-out is FINE —
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
  *Re-confirmed by Gil 2026-09-14 and still wired:* `_parse_covers_the_compound`
  is at `assistant/engine/fastrule/fastrule.py:188`, consulted at `:268`.

- **2026-09-19 — Q28 (A PHRASE IS LEARNED FROM A CORRECTION, NOT DERIVED FROM
  HISTORY)**, Gil. He asked first for a hidden two-word vocabulary built
  automatically from the one-word entries — *"looking at the one word finetuned
  vocab add the logical combinations of words"* — then asked the better
  question himself: *"is it worth building it, or allow user to fix two word
  phrases that we aren't sure about and can save those two words as one word?"*

  **BUILT THE DERIVATION FIRST AND MEASURED IT, WHICH IS WHY THE ANSWER IS
  CERTAIN.** Phrases were derived from his own event titles, to-do titles and
  command transcripts (296 strings), keeping only bigrams anchored on a
  vocabulary word — observed, never invented. It produced 33 phrases and
  CANNOT REACH THE MOTIVATING CASE:

      "poker night" appears correctly in the 296 sources:  False

  That is not a gap in the implementation, it is the shape of the idea. The
  derivation learns from transcripts that were ALREADY RIGHT, so a term the
  speech model always mangles never appears correctly in the history to be
  derived from — it is structurally blind to exactly the terms that need it.
  The derivation was reverted rather than shipped alongside; 33 phrases of
  unproven value plus a module is not worth carrying to solve a case it
  provably cannot solve.

  **THE CORRECTION IS THE RIGHT SOURCE** because it is the only one that knows.
  `learn_from_edit` now learns a MULTI-WORD span as ONE term with ONE alias.
  Before, it discarded a correction whose word counts differed — which is the
  commonest shape of boundary damage, "pokernight" (1 word) for "poker night"
  (2) — and learned an equal-count one as SEPARATE aliases, hanging "konaight"
  on the common English word "night" where it could fire on anything. Capped
  at four words a side: a name or a piece of shorthand, not a clause.

  Measured, with the multi-word matching shipped the same day: all four of
  "pokernight", "poe konaight", "bar rista course" and "sue dough coup club"
  are learned from one correction and repaired on the next occurrence —
  including "poe konaight", which nothing else reaches.

- **2026-09-18 — Q27 (A DAYPART DOES NOT DECIDE THE KIND — THE VERB DOES)**,
  Gil, after being shown the corpus evidence against reversing Q15 wholesale.
  Q26 had implied dayparts become events; measuring first showed that would be
  wrong, and Gil agreed.

  **What the corpus actually says.** Bare-daypart atomic rows split 355 EVENT /
  72 TASK — and the split is not about the daypart, which appears identically
  on both sides. It is about the VERB:

      gold EVENT   "schedule birthday dinner this evening"
                   "pencil in doctor's appointment at late afternoon"
                   "book standup this afternoon"   · "mark this evening as the moving day"
      gold TASK    "buy onions and index cards this afternoon"
                   "clean and organize the garage this morning"
                   "add book a flight to my todo list tonight"

  Scheduling verbs (`schedule`, `book`, `pencil in`, `mark…as`) make an event;
  chores and purchases make a task. `fastseg.tag`'s `_CALENDAR_VERBS` /
  `_TASK_VERBS` lexicon already encodes exactly this and already gets **60 of
  72** of the task rows right, so nothing needed building.

  **Three reasons the reversal was refused.** A daypart is a RANGE, not a
  specific time — `PART_OF_DAY` maps `afternoon` to 12:00–17:00, so it fails
  Q26's own "specific time" test. It would have put "buy onions and index
  cards this afternoon" on the calendar as a five-hour block. And it would have
  relabelled 60 rows against their own evidence.

  **So Q15's OUTCOME stands and its REASONING is replaced.** Not "a daypart is
  a task" — that phrasing is what made it look like the largest mis-kind driver
  — but "a daypart does not decide; the verb does". Q26 is untouched: a stated
  CLOCK still makes it an event whatever the phrasing.

- **2026-09-18 — Q26 (WHAT PUTS SOMETHING ON THE CALENDAR)**, Gil, answering a
  restated set after Q25's first narrowing was wrong. **This SUPERSEDES the
  same-day narrowing below and REVERSES Q15's headline ruling.**

  Gil's principle: *"An event is something that you put on the calendar. So
  reminding me to do something at a specific time counts as an event."*

  | the sentence names… | kind | also a task? |
  |---|---|---|
  | a CLOCK ("at 14:00"), any phrasing incl. "remind me to" | **event** | yes, on the day |
  | a RANGE ("from 9 to 2:30") | **event** | — |
  | a DAYPART ("tonight") | **event** at the daypart's time | yes |
  | a bare DAY ("tomorrow"), no clock | **task** | — |
  | no time at all | **task** | — |

  **"Also a task" needs NO parser change and NO second object.** Gil: *"you
  have the auto sync, which would add the feed the cat... the task, which only
  is for today on that day."* `db.sync_calendar_to_todos(list_name="today")`
  already pulls the day's events into the todo list, upserting by
  `source_event_id` so a completion survives a re-sync. It is OFF in Gil's
  config (`todo.sync.auto_sync_on_open: false`) and it fires on GUI OPEN, not
  daily and not on the phone — so what is missing is a schedule, not a feature.
  The parser creates ONE object, the event, exactly as today.

  **Q15 IS REVERSED on dayparts.** It ruled "remind me to take the trash out
  tonight" a TASK and called the opposite reading "the single largest mis-kind
  driver: **499 of 609** on the FastRule test half". Gil now: *"there's a
  daypart, so we can put an event at the designated time that we said that
  tonight counts as."* `resolve.PART_OF_DAY` already carries the mapping
  (`tonight -> 19:00-22:00`), so the value exists; what changes is the KIND.
  **This is a large reversal and must not be implemented blind** — it is the
  biggest single kind rule in the corpus and needs its own measured cycle plus
  a dataset relabel, not a rider on the clock fix.

  **Q15's parenthetical is also wrong** — *"remind me TO <verb>" = task* — and
  with it 32 corpus rows that are gold=task while naming a clock or a range:
  `s_ct_task_with_time` (9, train), `c_recur_12` (12, train), `c_range_ct_1`
  (11, **sealed test half** — to be relabelled BY RULE, never by reading, the
  way `c_recur_7` was).

- **2026-09-18 — Q25 (A STATED CLOCK MAKES IT AN EVENT; a bare day decides
  nothing)**, Gil. *"Anything that has an AM or PM time, like 1 o'clock, 2.30,
  that is for sure an event. You can also make an additional task on top of
  that in parallel, but it's definitely an event. If we're just given a day,
  like on Friday, maybe it's an event, maybe it's a task — it depends on the
  context."*

  Two halves, and the second is as binding as the first: a CLOCK decides, a
  DAY does not. So a kind rule may key on a stated clock time and must not key
  on a bare date alone.

  The project already had this convention for one phrasing — `_ROUTE_OVERRIDES`
  routes "remind me about the dentist at 9am" to the calendar because "the
  clock time is the tell" — and the ruling generalises it. Extended to the
  need-to family the same day (f213ffb), measured 30/30 on the FastRule atomic
  gold with no counterexamples.

  **Measured size of the rest, so nobody over-reads it.** On 2,991 single-item
  atomic train rows the live tagger is 94.9%, and of its 152 kind errors only
  **17 turn on a clock** — 11 events read as tasks despite naming one, and 6
  gold-task rows naming one, which are now GOLD-WRONG under this ruling and
  need relabelling (all six are recurring-with-a-time, e.g. "review the
  contract daily at 8:30pm"). The other 135 have no clock at all and this
  ruling does not reach them.

  **NARROWED THE SAME DAY, because as stated it contradicted Q15** — which is
  also Gil's, and which rules that *"remind me TO <verb>"* is a task. Taken
  literally, Q25 would have overturned it and retired 42 corpus rows across two
  DELIBERATE families (`s_ct_task_with_time` — named for the proposition — and
  `c_recur_7`). Gil, shown the conflict: *"u decide just fix so there arent
  conflicts."*

  **The decision: a stated clock makes it an event, UNLESS the speaker used an
  explicit reminder frame.** "remind me to feed the cat at 14:00" stays a task
  — that phrasing is the speaker ASKING for one, and an explicit request
  outranks an inference. Everything else with a clock is an event, including a
  recurring one, so `c_recur_7`'s 10 clock rows were RELABELLED to
  `create_event` rather than left contradicting a standing ruling. That family
  is train-only, so no sealed row was read or touched.

  **Both tracks got the identical rule, and that was not optional.** The
  segmenter had a clock rule already but only inside its `event` branch, so a
  `task` verdict was never revisited; the front door had none. Giving it to
  only one made them disagree about the same sentence — `fastseg` calling
  "file the taxes every weekday at 3:45pm" an event while `_route_intent`
  returned create_todo — and the product-shape board charged the difference as
  8 wrong commits. With both aligned:

      kind accuracy, fastrule train (3,200)      94.2% -> 94.7%
      kind accuracy, realspeech train (450)      91.3% -> 94.2%
      correct-on-handled, FastRule product-shape 93.9% -> 94.4%
      harm                                       185 -> 173 (153 -> 141 wrong commits)
      handle-rate 78.1% -> 78.0%, DESTRUCTIVE flat at 28

  **The parallel task is NOT built.** Gil allows an event to also produce a
  task; nothing does that today, and it is a product change, not a kind fix.
  Filed, not started.

- **2026-09-18 — Q16 AMENDED: a bare shared DAY scopes over events; only a
  DEADLINE never does**, Gil. Q16 below said *"events never share at all"*, and
  `never` was too strong — it was written against deadlines and it caught plain
  shared days too. Measured with `scripts/dv_invariance.py`:

      "book the dentist at 3pm and the gym at 5pm friday"
          -> the dentist landed on TODAY

  Asked directly: *"should they both be on Friday? The answer is obviously
  yes."* So the rule turns on WHAT IS SHARED, not only on the item's kind — a
  marked deadline ("by friday") scopes over tasks and never onto an event,
  whose date is when it HAPPENS; a bare day ("friday") scopes over events,
  which happen on it, and is still withdrawn from a task.

  **WHERE THE REPORTED BUG ACTUALLY LIVES, which is not where it looks.**
  `_scope_trailing_date` never fires on that sentence: the two asks carry
  DIFFERENT time strings (`'today at 3pm'` vs `'friday at 5pm'`), so the
  "is this a copy of the owner's reference" guard skips it. The dentist gets
  today because **segmentation's `assign_times` distributes a LEADING day to
  every ask but a TRAILING day only to the ask it sits in** — the asymmetry
  Q16's own entry says *"stays exactly as it is"*. Today's ruling supersedes
  that. The `decompose_validate` amendment above is correct and implements the
  ruling, but it has **no measured effect on any board**, because the natural
  sentence never reaches the rule. The fix that changes the answer is in
  `fastseg.assign_times` and is filed in TASKS.md, not done.

- **2026-09-11 — Q16 (a trailing deadline is shared ONLY when it is EXPLICIT)**,
  Gil. "submit the grades and prepare the slides **by friday**" — the marker
  ("by", "before", "due") scopes friday over every TASK in the utterance. A bare
  trailing date shares nothing, and events never share at all: an event's date
  belongs to that event. Gil: *"if explicit add, otherwise don't, for tasks"* —
  and *"this should be what decompose_validate does, fixing the dates if
  possible from item type."* So it is a DATE rule keyed on `item.kind`, in the
  stage that already resolves dates, not a segmentation change. The asymmetry
  that prompted the question (segment shares only an OPENING date, never a
  trailing one) stays exactly as it is; this adds the explicit-marker case on
  top of it, downstream.

- **2026-09-11 — Q11: WITHDRAWN — the question was out of date.**
  `FASTRULE2_DESIGN.md` asked permission to build five components. They were
  built the same day it was written (4657fe9, 2026-09-07: "Rebuild: one object
  per component… v2 wired into the engine"), and the design was then superseded
  two days later by `assistant/engine/fastrule/PLAN.md` (2026-09-09), which
  reframes FastRule as a CONVERTER rather than a parser and supersedes the v2
  component split. Nothing was waiting on an answer. `FASTRULE2_DESIGN.md` now
  says so at the top; `fastrule/PLAN.md` is the live plan.

- **2026-09-11 — Q6 (re-confirmation): NO reminders for events inside Shabbat /
  yom tov**, Gil. Confirms the shipped default — suppress entirely; no
  pre-candle digest. The alternative is closed, not deferred. *(The original
  ruling is the 2026-09-06 Q6 entry below; this is the same answer asked again,
  not a split log.)*

- **2026-09-07 — Q15 (a DAYPART IS NOT A CLOCK TIME)**, Gil. "remind me to take
  the trash out tonight" is **a task to do in the evening**, not a calendar
  event. The pinned reminder convention turns on a real clock time ("remind me
  about the dentist tomorrow AT 9AM" = event; "remind me TO <verb>" = task),
  but `segment._CLOCKISH_RE` lists `tonight|morning|evening|afternoon`
  alongside actual times, so any remind-phrased errand with a vague daypart
  became a calendar entry. A daypart is a rough WHEN — it belongs in the
  task's due time, not in the decision of what kind of thing this is. This is
  the single largest mis-kind driver: **499 of 609** on the FastRule test half,
  383 of 418 on the personas.
  ~~Fixed in sprint cycle B.~~ **That claim is UNSETTLED as of 2026-09-14 and
  should not be trusted either way.** The 2026-09-14 audit called it unbuilt,
  citing `_CLOCKISH_RE` still listing the dayparts — but that regex lives only in
  `old_seg/segment.py:143-145`, and `old_seg` is NOT the live segmenter
  (`segmentation/__init__.py:49` defaults to `fastseg`, old_seg is one env var
  away). In `fastseg` the daypart words are tagged `date`, not time
  (`fastseg.py:96,192`). So the audit's evidence is against a module that does
  not run. Whether the LIVE kind decision still promotes a bare daypart to a
  clock time needs a measured check, which needs a run — **do not schedule a fix
  against this row until someone has measured it.**

- **2026-09-07 — Q14 ("buy apples and eggs" is TWO tasks)**, Gil —
  **REVERSED 2026-09-16, see the top of this log.** Kept verbatim for the
  history: same action, separate items ("buy eggs", "buy apples"). This
  settled a contradiction the atomizer board found between our own
  documents: `decompose.py` and `list_split.py` split shopping lists;
  `assistant/engine/fastrule/datasets/DATASET.md` labelled them one task
  titled "apples and eggs". The CODE was right. Every over-split in the
  FastRule test half was this disagreement and nothing else — so those
  were never defects. **The dataset's np_decoy families need relabelling**
  (a list of things for one verb = one item PER THING); the genuine
  never-split case is a list of PEOPLE or a shared object ("meeting with Tal
  and Sam", "wash and fold the laundry"). **The relabelling was never done,
  and by 2026-09-16 the ruling itself had changed — see the top of this
  log.**

- **2026-09-07 — Q13 (non-atomic behaviour is DIAGNOSTIC, not a target)**, Gil.
  *"I just want to see that it succeeds on recognising and executing well on
  atomic items, and we can decide what to do with non-atomic which is run
  through anyway and pass that to the next stage and let the engine decide."*
  So: the PRIMARY metrics are atomic handle-rate and correct-on-handled;
  FastRule's atomicity call is information handed upward (the REFUSAL /
  STRUCTURE / INCAPACITY contract), not a verdict it must get right alone.
  The non-atomic bucket is reported as three outcomes — covered (acceptable,
  and the only path that survives the LLM being down), half-executed (the real
  defect), deferred — with no single "violation" number. `_parse_covers_the_
  compound` stays. *(Refined on 2026-09-11 — see the top of this log.)*

- **2026-09-07 — Q12 (the retry loop must CHANGE the input, and the LLM is the
  last resort)**, Gil design ruling. Two parts. (a) **Determinism rule:** when
  the crosscheck loop-back re-enters an atomic item, FastRule must not be
  asked the same question twice — identical text gives an identical verdict by
  construction, so a re-run on unchanged text is wasted work. On re-entry,
  either the item's text differs from the attempt that failed (the LLM stages
  rewrote it) or FastRule is SKIPPED for that item. (b) **Escalation rule:**
  after the retry budget (3) is spent on an atomic item, the final attempt
  belongs to the LLM — it creates the event/task directly rather than
  deferring to a deterministic parser that has already failed on that exact
  text. Implementation: per-item attempt fingerprints on EngineState;
  generate consults them before calling FastRule. ~~Deferred until the
  in-flight sealed run finishes (engine files are read-only during a
  measurement).~~
  *State on 2026-09-14:* **(a) is wired** — `state.asked_fastrule`
  (`engine/state.py:189`), consulted at `fastrule/objects.py:282`. **(b) I could
  not confirm.** The field it would need, `state.retries` (`state.py:176`), is
  reported by the 2026-09-14 audit as written and never read.

- **2026-09-07 — Q10 (Stage-2 routing becomes TWO tiered subsystems)**, Gil
  design ruling. (1) KIND — event vs task; (2) OPERATION — new/edit/remove/
  complete/query. Each is rules-first (regex/tables/pinned conventions answer
  when confident — trivial cases stay trivial and Gil's rulings stay
  sovereign) with a small logistic-regression model as the fallthrough when
  rules aren't confident. Action = kind × operation, composed. K1 is the KIND
  subsystem's model (proven 99.0/98.5); K3 is the OPERATION subsystem's model
  (labels free in dataset B). A rules-vs-model disagreement is an abstain
  signal. Implemented in the lane (F-batches), integrated at F15.
  *Related open question:* the KIND half now has four readers — see **Q19**.

- **2026-09-07 — Q9 (interrogative creates → CONFIRM PROMPT).** "should i add
  yoga to my calendar tomorrow?" must neither auto-create nor be silently
  dropped: the client pops a box with the parsed proposal — yes creates it, no
  discards it and the memory record marks it declined. Same response-contract
  pattern as the transcript-edit gate (`needs_edit` + `supports_edit`): the
  server sends a proposal payload only to clients that declare
  `supports_confirm`; older clients keep today's behavior (deep decides). The
  dataset's interrogative families relabel to expect a PROPOSAL, not a create —
  labels follow product. → *Implemented:* the confirm-create gate
  (`parse: "confirm_create"` + `proposal`, `POST /voice/confirm`, Mac Add/No
  box, iOS alert) — FEATURES.md and ENGINE.md carry the detail.

- **2026-09-07 — Q8: APPROVED — "can try the q8 idea."** A small logistic
  regression over hand features for the event-vs-task kind decision, fit
  offline on dev labels, deterministic at inference. Ships only if it beats
  the regex family in a measured cycle; negative result gets banked too.
  *(The negative result was duly banked: F13, kind macro-F1 82.6 → 80.5 on the
  classifier B-set test half — see Q19.)*

- **2026-09-06 — Q7: object-based restructure APPROVED — with the acceptance
  criterion in Gil's words: "the logic doesn't change at all nor should the
  results, should just be cleaner." All three recommendations confirmed:
  (1) pure refactor first, cycle 10 separate; (2) `run_transcript` stays as a
  shim; (3) shared Component interface. Verification bar: full test suite
  green + a behavior-identical confirmation run against the era-2 baseline
  before merge.**

- **2026-09-06 — Q1: dated "I need to <meet/talk>…" = EVENT.** Implemented same
  day: `_NEED_ENCOUNTER_RE` in segment's pinned-kind rules (encounter verbs +
  date/clock ⇒ event; errands and undated encounters unchanged) + unit tests.

- **2026-09-06 — Q4: Mac reminders with the calendar closed = a notification-
  settings OPTION.** Queued in TASKS (app stream): settings toggle first, the
  LaunchAgent detach ships behind it, default off.
  *Still UNBUILT on 2026-09-14, and unblocked since the day it was answered* —
  two docs kept calling it blocked on this very question.
  `calendar_ui/settings_dialog.py:220-266` has exactly four notification
  controls (pre-event enable, default lead, spoken heads-up, observance hold) and
  none is this one; there is no launchd plist for `assistant.api` anywhere in the
  tree. It is LARGE because it changes the launch model (`--reload`, HUD
  lifetime, shutdown ownership), which is exactly why you made it opt-in.

- **2026-09-06 — Q5: default lead time = PER CATEGORY.** Matches the built
  mechanism (`resolve_lead`: event override → category lead/mute → fallback);
  the per-category leads in notification settings are the primary surface.

- **2026-09-06 — Q6: events inside Shabbat/yom tov get NO reminders.** The
  shipped suppress-entirely default is confirmed; no digest. *(Asked and
  answered again on 2026-09-11 — see above.)*

- **2026-09-06 — Q2 shipped without needing an answer**: the observance
  checkbox is in the Mac settings dialog (243d99f), persisted via
  config_store — and building it exposed that `observance.enabled` was
  silently DROPPED by pydantic (`ObservanceConfig` never declared the
  field), so the yaml flag never reached `is_enabled()`; only the env
  override worked. Field declared + pinned by test.

- **2026-09-06 — Q3 withdrawn** (API key): the model sims ran through Claude
  Code subagent workers, no key needed; the experiment is closed on partial
  data (llama beat both drop-ins — `dataset/MODEL_COMPARISON.md`).

- **2026-09-05 — Old-brain comparison**: Gil doesn't care about it; the
  questions that matter are "is the new system better, and can it get
  better?" → answered in chat (yes / yes); vs-old numbers stay incidental.

- **2026-09-05 — Invention vs missing**: balance both, F1-style. →
  *Implemented:* item-level micro precision/recall/F1 in the harness
  (`_prf`), reported per run + by complexity + untuned sub-slice.

- **2026-09-05 — Overfitting the subset**: authorized to resample a fresh
  same-size slice and mark it in the log. → Standing policy in the protocol.

- **2026-09-05 — Shabbat gating in tests**: turn off via a user-controllable
  flag; replays must simulate each row's recorded timestamp. → *Implemented:*
  `observance.enabled` + `MACALENDAR_OBSERVANCE` env override standing down
  both gates; the harness freezes each replay at the row's `ts` (freezegun).

- **2026-09-05 — Separate task lists**: no — lists stay Today/General plus
  tags. → Queue #6 closed; "create a new list" dataset rows are accepted
  convention losses.

- **2026-09-05 — Merging**: fold the loop branch into `main` every few
  graduated cycles. → Standing policy in ITERATION_PROTOCOL.md; first merge
  done (@ a425ca2).

- **2026-09-04 — Date-only occasion reminders**: calendar events. → Cycle 2.

- **2026-09-20 — Q29 (A CALENDAR CREATE OVER A LIST OF THINGS IS SEVERAL
  EVENTS, AND THE DEEP ENGINE REWRITES IT ONE CLAUSE PER THING)**, Gil.
  Asked how the engine handles *"on friday create an event for X, Y and Z"*,
  he was shown the Q14 answer — one event titled with the list — and ruled:
  *"if the decompose_validate fails to split into three items with same date,
  the deep engine should rewrite for example given original — 'on friday
  create an event for dentist, haircut and gym' — it should rewrite something
  like 'on friday create an event for dentist and on friday create an event
  for haircut and on friday create an event for gym', or similar situations
  for other problematic."*

  **What it settles.** Q14 stands for SEGMENTATION — a shared verb over a bare
  noun list is still cut as ONE item, and the segmentation gold is not
  relabelled. The count is corrected downstream: LLMJudge raises
  `coordinated_subject` on one `create_event` whose words list three or more
  things (`coordination.noun_list`), routed REWRITE like `ungrounded_subject`,
  and `rewrite.expand_list` builds X1' by copying the shared time, head and
  tail around each member — every word the speaker's, so the grounding guard
  passes by construction — and the loop re-enters segmentation, which cuts on
  the " and " seams it just wrote. FastRule's `Atomicity` declines the same
  shape as `list-title` (STRUCTURE) so the one-event reading is never
  committed fast. A pair is one thing ("wine and cheese"); attendees
  ("with sam, alex and jordan"), a timed enumeration and a list of verbs are
  not lists of things. To-do lists are untouched: `decompose_validate`
  already multiplies those.

  **Reached, no model call.** From a Wednesday clock, the exemplar yields three
  `create_event` rows dated 2026-09-11 in one round; beside a second ask
  ("… and remind me to call mom") the to-do is frozen and kept.

- **2026-09-20 — Q30 (THE LOOP-BACK HAS TWO TIERS: CODE FIRST, THEN THE MODEL
  WRITES X1')**, Gil. Told that X1' had been built without a model since
  2026-09-10 and that the loop therefore stops after one round on the same
  failure: *"the whole point of the loop is that the llm sends a fix if
  relevant as X1' to iterate on, otherwise commit"* and *"for the first
  iteration fix that's fine, but on the second iteration it will do the same
  thing and there we would need a llm no?"* — with the brief: *"make sure the
  prompt is well thought out and built, the task is well defined, and what we
  already tried is given dynamically as context so the model knows what it's
  trying to fix, also take into what prompt structures the system can deal
  with well (like individual events/tasks separated by 'and' in a clear
  manner, take recurrence also how that is taken into account)."*

  **What it settles.** The 2026-09-10 removal stands for the JUDGE (no model
  call in `verdict`) and for the FIRST rewrite (deterministic). It is reversed
  for the rounds after: when `failed_asks` has nothing new — the string was
  already tried — or cannot help — an `unsplit_subject`, where a trim of the
  object's words drops the other ask — `rewrite.rewrite_with_model` asks the
  model for X1' as a LIST of asks, with the
  transcript, the leftover, the finished asks and every earlier attempt with
  the judge's complaint (kept in the state's own fix ledger, rules `rewrite`
  and `rewrite_model`). The prompt fixes the shape the parser reads: verb
  first, one thing per line, to-do vs calendar framing, time at the end of
  its line as digits, the speaker's recurrence phrase kept exactly and
  attached to one line. Code joins the list as the ingest envelope
  `("a")and("b")`, so segmentation opens the cut before it reads language.
  Both tiers pass the same grounding guard and fail closed; `MAX_REENTRIES`
  stays 3. A new deterministic finding, `unsplit_subject` (one object whose
  own words hold an ask seam), is what carries an under-split to that round.

- **2026-09-20 — Q31 (THE IMPROVEMENT LOOP RESUMES; STAGE ISOLATION IS
  DONE)**, Gil: *"make sure we are working on the auto self improvement loop
  to improve the system now and that md files are up to date."* This lifts
  the 2026-09-07 pause (STAGE_ISOLATION_PLAN.md: *"Engine cycles stay
  PAUSED"*). What the day showed: with every stage board green or moving, the
  whole chain still lost a quarter of its commands (run 22, 74%), and every
  fix that moved it — the kind tagger, the hard seams, the fast path's holes,
  the model round — moved a stage board by nothing or by two rows while
  dev-100 moved eleven points (runs 22 → 26: 74 → 85%). The misses were seam
  and coverage defects the stage corpora do not contain.

  **How the loop runs from here.** dev-100 is the working slice (direction;
  ±3 pt), dev-fast-250 confirms, the sealed 300 is milestone-only. Each cycle
  registers its component, metric and slice in `dataset/RESULTS.md` before
  the change, reads the failing rows after, and starts the next. Stage boards
  remain the GATE for any stage-internal change — a change is boarded alone
  on its own stage before it is read on dev-100 — because a whole-chain read
  cannot say which stage moved. Real usage (`weekly_review`) still outranks
  every board. The three open rulings (Q29's untimed event, the new list, the
  offset/recurrence on "remind me to") are not blocked by this: they gate
  specific rows, not the loop.

- **2026-09-20 — Q32 (A MEAL NAMES ITS OWN HOUR)**, Gil, asked which reading
  an untimed dated event should get: *"have default for breakfast/lunch/dinner
  as 0900/1300/1900 if not given for an event."*

  Breakfast 09:00, lunch and brunch 13:00, dinner and supper 19:00, matched on
  the TITLE at a word boundary so "lunchbox" and "brunching" are not meals. A
  stated clock always wins, and a speaker who asks for the whole day
  ("all day dinner party" — 5 of the 7,200 corpus rows) keeps their block.
  Decided in `rule_parser`'s all-day branch and in `CalendarIntent.
  fill_defaults`, one per track, because once the block is stamped an all-day
  the speaker ASKED for and a bare date we defaulted are the same two values.

  **The board's premise moved with it.** `fastrule_shape`'s "INVENTED a time"
  line read *"nothing was said about a time: 00:00 is the honest answer"* and
  went 3.5% → 5.1% on the 370 untimed events the moment the rule landed. That
  is the instrument measuring the old convention, so it learned the new one in
  the same commit and the board is byte-identical again. **Still open: the
  general untimed event** (a dated "book the dentist on the 26th" is an
  all-day block on the fast path and the clock-of-now on the deep one). The
  ruling covers meals; nothing was said about the rest.

- **2026-09-20 — Q33 (A NEW LIST IS A TO-DO IN GENERAL, NAMED FOR ITS
  CONTENTS)**, Gil. "start a new list of dog breeds" committed `query_todos` —
  a query for a create — until the router stopped reading the bare noun
  "list" as a command; this is what it does instead: a `create_todo` titled
  "dog breeds" on the **general** list, not today, because a list of dog
  breeds is not something to do today. The name ends where the next ask
  begins and courtesy is not a name — "create a new list, please" has nothing
  to call it and gets the generic-title veto rather than a list called
  'please'. An item FOR a list ("add milk to the new list") is not the making
  of one and stays on Today.

- **2026-09-20 — Q28 ANSWERED (A GENUINE 7 OR 8 IS ASKED ABOUT)**, Gil:
  *"Ask the speaker when it is genuinely 7 or 8."* Filed 2026-09-19 when the
  same sentence — "book team meeting tomorrow at 7" — resolved 19:00 on the
  fast path and 07:00 on the deep one.

  **Genuinely ambiguous** means a bare "at 7" or "at 8" with no meridiem and
  nothing around it to settle the half of the day: 86 of the 7,200 corpus
  rows, 4 of the 3,000 real utterances. 1 to 6 is not — "gym at 5" is not 5am
  and that convention has held all year — and "8 o'clock" reads AM on both
  tracks with the gold agreeing, so neither is touched.

  A client that says it can render a prompt is ASKED, on the same terms as a
  range date (`confirm_create`, one item only, because a confirmation holds
  everything): *"Want me to add “team meeting” on Thursday, Sep 10, 2026
  7 PM–8 PM?"* A client that cannot is TOLD: the hour resolves PM — the fast
  path's long-standing reading, so `resolve._bare_hour` was aligned to it and
  the two tracks now agree on every shape — and the reply says *"I read "7" as
  7 PM — say "change it to 7 AM" if you meant the morning."* The losing reader
  being aligned is the half of Q28 that was always going to be an
  implementation fix; the asking is the half that needed the ruling.

- **2026-09-20 — Q34 (THE AUTONOMOUS RUN'S SCOPE)**, Gil: *"I want there to be
  an autonomous run as much as you can until you feel like you can't make more
  significant progress or relevant progress without needing my clarification."*
  Cycles run on `fastrule-title-time-precedence`, one change per board run,
  each committed with its numbers. **Main is never touched** — the merge stays
  Gil's call. The run stops when three cycles move nothing past the noise
  floor, or when a ruling is needed.

- **2026-09-20 — Q26 ANSWERED (THE TITLE EXTRACTOR MAY BE REWRITTEN)**, Gil,
  asked while the remaining junk titles were traced to one place: *"Yes,
  rewrite it properly."* Filed since 2026-09-18 as *"Phase 4: may the title
  extractor and/or the temporal resolver be rewritten? Not started without a
  yes."*

  **The evidence that prompted it.** After cycles 28–30 the junk titles left
  on dev-100 were 14, and every one came from the rule parser's own
  extraction chain rather than the model: 'remind about of all event in
  calenders', 'remind at this time', 'set reminder', 'things', "grocery
  shopping 's to-do list", 'calendar event', 'open calendar' — committed at
  0.95 confidence and better. Two cycles of narrowing frames around the edges
  moved the rate by nothing, because the titles come from a FALLBACK further
  down the chain than either named extractor: instrumenting
  `_todo_titles_from_text` and `_dobj_conjunct_title` on those rows shows
  both returning nothing and a title appearing anyway.

  **Scope.** The extraction chain, not the contracts: what the fast path and
  the deep converter both call to turn an item's words into a name. The
  temporal resolver is NOT included — that half of Q26 stays filed. Rule as
  ever: the 7,200's 6,880 gold titles are the negative surface and a change
  that moves any of them is reverted, the product-shape board runs before
  dev-100, and the sealed half is never read.

- **2026-09-20 — Q35 (FIELD QUALITY AND PRECISION LEAD; COUNT-CORRECTNESS
  FOLLOWS)**, Gil, shown that two cycles running had moved count-correctness
  down while every quality metric moved up, and why: count-correctness asks
  *did you produce at least N things*, so a fabricated object counts as a
  success and an honest *"I couldn't make out what to create"* counts as a
  failure. **It pays for inventing and charges for admitting.**

  From here a grounding or title cycle is judged on **field quality** and
  **item precision**, with count-correctness read as a companion rather than
  the verdict. Cycles 28 and 29 stand as improvements on that reading
  (field quality 87.0 → 87.4, precision 87.9 → 91.4, garbage titles 19% →
  16%) rather than the regressions the old primary made them.
  `dataset/METRICS.md` carries the order.

- **2026-09-20 — Q36 (AN UNTIMED DATED EVENT IS 09:00 ON BOTH TRACKS)**,
  Gil. The non-meal half of Q32: "book the dentist on the 26th" was an
  all-day block on the fast path and the clock-of-now on the deep one, which
  is where most of the judge's `unsupported_field` notices came from. It is
  **09:00** on both tracks now. A stated clock still wins, an explicit "all
  day" still keeps its block, and a meal still takes its own hour (Q32).

- **2026-09-20 — Q37 (A LIST WITH NO NAME IS REFUSED, AND THE GOLD IS
  WRONG)**, Gil: *"Refusing is right, fix the gold."* "Can you please create
  a list for me" and "Create a new list, please" name nothing to call the
  list, and the engine answers *"I couldn't tell what to call it."* The
  dev-100 gold counts those as requiring a creation, which is what made them
  three count-correctness failures; the gold rows are wrong and are marked so
  rather than the behaviour being changed. Creating a to-do called 'list for
  me' is a row the speaker has to find and delete.

- **2026-09-21 — Q38 (A TITLE THAT NAMES NOTHING IS REFUSED, EVERYWHERE)**,
  Gil, shown the trade cycles 32–33 made on dev-100: junk titles 15% → 4%,
  and 8 fewer objects created (80 → 72), each one a command like "create a
  list for me" or "remind me at this time" where the engine now says *"I
  couldn't tell what to call it"*. **Keep refusing.** This generalises Q37
  from nameless lists to every title that names nothing: a row the speaker
  has to find and delete is worse than a sentence saying it could not be
  read. Title work stops here; the loop moves to other failures.

- **2026-09-21 — Q39 (THE REAL-USAGE BOARD COMES BEFORE MORE dev-100 WORK)**,
  Gil. Every one of 2026-09-20's eleven cycles was judged on dev-100 — 100
  HWU-64 utterances — while CLAUDE.md has said all along that real usage
  outranks every board and is the only instrument measuring Gil's own
  speech, and it has never driven a cycle. **Build the real-usage board
  first** (phase 1 of `REAL_SPEECH_PLAN.md`). The risk it addresses is
  concrete: a day of hard optimisation against a public corpus that may not
  sound like the person using it.

- **2026-09-21 — Q28 RE-CONFIRMED WITH THE PHONE DETAIL.** Told that the
  bare-hour prompt fires ONLY on iOS — the one client that sets
  `supports_confirm` — so "remind me about the meeting tomorrow at 7" now
  costs a tap on the phone while the Mac creates it silently: **keep
  asking.** The ambiguity is real and a wrong hour is worse than a tap.

- **2026-09-21 — Q40 (MERGE THE BRANCH)**, Gil: merge
  `fastrule-title-time-precedence` into `main` now. 44 commits — eleven
  engine cycles, four rulings built, and the iOS project repair — with the
  full suite green and every change boarded.

