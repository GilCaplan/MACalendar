# Segmentation

**`PLAN.md` is what to do next and in what order** (2026-09-09) — the span
vocabulary is the measured lever, and it carries the rules that keep this folder
from becoming convoluted. This file is how the stage WORKS.

> ### THE GOLD CONFLICT THAT PROMPTED A v2 LOOK — RESOLVED 2026-09-16,
> ### NOT BY A REBUILD
>
> Six implementation fixes this session (§0 below) pushed FastSeg v1 from
> exact-row 68.2%→73.7% train / 67.4%→73.0% sealed with zero new false
> positives, each measured and verified individually. A seventh — object-list
> enumeration expansion, "buy A, B, and C" → 3 tasks — hit what looked like a
> gold-data conflict: an explicit, deliberately-named `c_npdecoy_buy_two_items`
> family protecting "buy shampoo and apples" as ONE item, while other families
> wanted the identical shape to split. `fastseg-v1` was tagged (commit
> `05f7ac1`) as a rollback point and a three-proposal design panel was run for
> a v2 rebuild — but a `fable`-model audit of the panel's own recommendation
> found the real story first: this wasn't two template families disagreeing
> by accident. **DEVQA.md's Q14 (2026-09-07, Gil) had already ruled on this
> exact question** — "buy apples and eggs" is TWO tasks, one per thing — and
> explicitly said the `np_decoy` families needed relabelling to match. That
> relabelling was never done. The dataset had been sitting in a half-migrated
> state for nine days, and rebuilding the cutter would have measured v2
> against a target that was itself wrong.
>
> **Q14 was then REVERSED, not finished** (Gil, 2026-09-16, shown the conflict
> directly — see DEVQA.md's 2026-09-16 entry for the full exchange): a shared
> verb over a bare, NOUN-coordinated object list is now ONE atomic
> segmentation item, regardless of count or whether the objects are generic
> or named. 14 rows corrected across 9 families (`c_threeask_ttt_2`,
> `list-of-things-collect`, `list-of-things-source`, `quantity-not-time-order`,
> `quantity-not-time-grab`, `as-well-as-plain`, `leading-edge-two`, and two
> rows already misfiled inside `nosplit_traps.jsonl` with split gold despite
> living in the "must not split" file — an independent confirmation this was
> a real bug, not just a judgment call). `wrapper-phrase` was untouched — it
> was already correctly "must not split" the whole time, a genuinely
> different, already-settled trap.
>
> **FastSeg v1's CODE did not change for this** — only the gold moved — so the
> resulting gain is a pure measurement of how much of the "residual gap" was
> actually a stale dataset: **+9 rows train, +4 rows sealed, zero code
> changes.** New headline: exact-row 74.6% train / 73.6% sealed (§0's table,
> below, is now this state). A DIFFERENT, genuinely new bug was found and
> filed while testing the downstream consequence of this ruling — a
> bare-imperative multi-object task silently drops every object but the
> first ("buy shampoo and apples" → saved as "buy shampoo") — traced to
> `assistant/intent/rule_parser.py::_extract_title`, nothing to do with
> segmentation at all; see `DOCUMENTATION/TASKS.md`'s 2026-09-16 entry.
>
> **Whether a v2 rebuild is still worth doing is an OPEN question again**,
> now against the corrected numbers rather than a moving target — not
> resolved by this entry. `fastseg-v1` stays tagged at `05f7ac1` as a
> reference point regardless. §3's callout below still has the full design-
> panel record (three proposals, the audit's findings) as institutional
> memory if this is picked up again — none of it was wasted, it just isn't
> this decision's answer by itself.

---

## 0 · Where this stage stands — 2026-09-20

**Train half, 1,051 rows** (`experiments/RESULTS.md`, the two 2026-09-20
entries, have the per-fix ledger): exact-row **90.1%** (947), exact-set
91.1%, the cut **98.4%** right item count, over-split **1** / under-split
**16**, tag **98.8%**, adversarial phrasing 28/31. `old_seg` is retired
(`retired/segmentation-old-seg/`, tag `segmentation-old-seg`); FastSeg is
the stage. **Sealed half, read once at this
milestone, aggregates only (660 rows)**: exact-row 78.2% → **79.7%**, the cut
92.1% → **93.5%**, over-split 22 → **16**, under-split 34 → **27**, tag 92.6% →
**93.6%** — the cut fixes generalise, and the 4.4-pt tag gap between halves is
the honest size of the tagger's vocabulary fit.

What moved it, in two halves. **Gold debt first**: this stage's gold had
never been relabelled for Q26 (a stated clock or range makes an event), so
the tag line had been measuring the ruling, not the tagger — 75 items
relabelled by rule, +3.7 pt exact-row with no code. **Then nine
implementation fixes**, each boarded alone: the ask gate's tag-question
pattern, three guards in the boundary walk (a governed verb is an object, a
modified noun is a thing, a fronted date after a joiner opens a clause), the
walk reusing the one object test, a stated clock that includes ranges and
spoken hours and outranks the time-blocking veto, the courtesy tail and the
"ahead" lead marker, and the tagger's first reading moved out of the retired
`old_seg` into `fastseg/kind.py`. Structure untouched.

### 0-prev · Where this stage stood — 2026-09-16

**Wired and live**: `IMPLEMENTATION = "fastseg"`, LLMSeg off, 0 model calls.
Verified end to end through `engine.run_transcript`, not inferred from the boards.

| | train (1,051 rows) | **SEALED (660 rows)** |
|---|---|---|
| exact-set (actions) | 91.4% (961/1051) | **85.6% (565/660)** |
| exact-row (action+time+tag) | 88.9% (934/1051) | **78.2% (516/660)** |
| **the CUT alone** — right item count | 97.6% | **92.1%** |
| item precision · recall · F1 | 99.7 · 98.4 · 99.1 | **97.6 · 96.6 · 97.1** |
| over-split · under-split | 3 · 22 | **22 · 34** |
| time on a **spoken** time | 98.5% | **96.0%** |
| tag accuracy | 96.0% | **92.6%** |
| A2 — 2 of 3 fields | 98.2% | **96.9%** |
| NO-INVENTION violations | 0 | **0** |
| cost | **0 model calls**, ~3 s for 1,051 rows | same |
| **downstream, end to end** | 85.9% rows fully right *(not re-measured this pass)* | — |

**2026-09-16, second pass — pushed from 74.6%/73.6% to the numbers above,
16 more fixes, same fix-then-measure-then-verify discipline as the six
below** (full account in §0b, right after this table). Over-split fell from
47→4 on train (28→23 sealed) — most of the session's gains were FALSE splits
recovered, not new boundaries found. Sealed moved with the first ~10 fixes
(73.6%→76.4%) and then plateaued while train kept climbing to 87.5% — **not
a generalization failure**: every family the later fixes targeted happens to
sit 100% on the train side of the family-hash split (verified against split
composition, never against sealed's scored content), so there was nothing on
the sealed side for them to move. §0b has the honest accounting, including
one dataset conflict found and left for a ruling rather than fixed.

**The sealed half was read once, at the milestone, aggregates only.** Six
fixes this session, all to `assistant/intent/coordination.py`'s
`_compound_command_verb`/`clause_boundaries`, each measured separately
before the next was attempted: **+66 rows train** (108→42 under-split),
**+47 rows sealed** (95→41). Over-split is UNCHANGED on both halves across
all six (46 train, 28 sealed, confirmed by exact row-id diff each time, not
just the count) — every row gained is a genuine under-split fixed, none is a
new false positive traded in. Sealed test moved as much as or more than
train through the first five; the sixth found no matching rows there either
way (family-split dataset, as with fix 2).

7. **The gold correction (Q14 reversed, not a code change).** A seventh
   implementation attempt — object-list enumeration — surfaced a genuine
   conflict in the dataset's own gold labels rather than an implementation
   gap: some families wanted "buy A, B, and C" as one item, others wanted the
   same shape split one-per-object. Tracing it found DEVQA.md's Q14
   (2026-09-07) had already ruled on this and called for relabelling that
   was never done. Q14 was reversed 2026-09-16 (Gil, shown the conflict
   directly): a shared verb over a bare, NOUN-coordinated object list is now
   ONE atomic item. 14 rows corrected, `assistant/intent/coordination.py`
   **unchanged** — this is a pure measurement of how much of the residual gap
   was a stale label, not a cutter defect. **+9 rows train** (784/1051,
   under-split 42→33), **+4 rows sealed** (486/660, under-split 41→37).
   Over-split ticked up by one on train only (46→47) — expected, not a
   regression: the cutter's own behaviour didn't move, but a row whose gold
   item-count the correction pulled down can now read as "predicted more
   than gold" against the new target. Full detail, the corrected rows by
   family, and both verbatim rulings: DEVQA.md's 2026-09-16 entry.

### 0b · Second pass, same day: 16 fixes, 74.6%→87.5% train / 73.6%→76.4%
### sealed, explicitly steered away from per-sentence patching

Asked to keep pushing toward a 90%/85% stretch target, then redirected mid-
pass (Gil: *"it has to be smarter than just solving rule based 2 cases here,
3 there… we need a better generalization"*) — every fix below was checked
against the FULL corpus's gold labels (both halves, reading label
DISTRIBUTIONS only, never sealed's per-row content) before being written, so
each is a measured, closed-vocabulary MECHANISM covering a construction, not
a memorised sentence. Same discipline as the six above: implemented, board
run, exact row-ID diff to confirm zero regressions, full 1,711-test suite
green, *then* the next one.

**First, an oracle check, because "push until exhausted" needs a ceiling to
push toward.** Among the TRAIN rows where FastSeg's cut already matches gold
1:1, only 80.7% were ALSO exact-row correct at the 74.6% starting point —
meaning a theoretically perfect cut, at that TAG/time/action accuracy, tops
out around 80.7%, not 90%. The gap was never the cut alone; TAG and the
action/time span needed just as much work. (The same check now reads 83.5%
— cut-quality's own ceiling rose too, since several fixes below touch the
cut indirectly.)

1. **A leading "to" survives a coordinated second reminder clause.** "remind
   me to X and TO Y" — gold strips the second clause down to "Y" (the first
   clause keeps its own "remind me to", since that "to" is attached to a verb
   IN that clause). `_tidy()` had no rule for a bare leading "to"; checked
   against all 1,711 gold actions in the corpus — not one starts with "to " —
   so the strip is safe applied everywhere `_tidy` runs, not just at a
   boundary. **+16 train.**
2. **"DURATION before NAMED-EVENT" was being extracted as if it were a bare
   lead time.** "remind me to organize the garage AN HOUR BEFORE SCHOOL PLAY
   at around lunchtime" matched "an hour before" as its own clock-class ref,
   stripped it, and left "school play" an orphaned fragment glued onto the
   action. English "before" is used BOTH transitively (governs a noun:
   "before haircut") and adverbially ("an hour before", full stop, or handed
   off by a to-infinitive/preposition: "before ABOUT annual checkup", "before
   TO submit the report", or a second lead-marker: "before BEFOREHAND",
   "before AHEAD OF conference call" — the generator's own idiom-stacking).
   `_lead_has_no_object` now checks what immediately follows "before" within
   the SAME piece: nothing, or one of {about, for, to, before, beforehand,
   ahead, prior, in advance} → extractable; a bare noun → stays in the
   action, object and all. First attempt regressed 21 rows (blocked every
   "before ABOUT X" case too) before the intransitive-marker set was found;
   caught by the row-ID diff before it was ever measured as a net gain.
   **Net 0 alone** (paired with #3 below on the SAME rows — action/time went
   right, tag was still wrong).
3. **`_kind_of` reads "remind me to ORGANIZE THE GARAGE…" and calls it a
   task before it ever reaches the "before SCHOOL PLAY" clause that actually
   anchors it to a calendar event** — the one-way event→task veto has no
   mechanism for the reverse. Added a narrow, STRUCTURAL mirror (a real
   stated time, day or clock, plus a surviving "before/about NAMED-EVENT"
   clause) — not the blanket bidirectional lexicon override already measured
   worse (87.5%→82.4%, §6 below): this fires on syntax, not a verb list.
   Also removed "remind" from the task-verb veto lexicon (`_lexicon_kind`)
   — a genuinely neutral verb the veto had been treating as task-only.
   **+11 train** (3 from the lexicon change, 8 from the promotion, together
   with #2 above).
4. **A leading preposition can stack.** "schedule therapy session FOR AT the
   end of the month" — the "end of month" pattern's own match starts at
   "the end…"; `_absorb_preposition` hopped left over ONE preposition ("at")
   and stopped, stranding "for". Same fix as `_tidy`'s own dangling-strip
   ("…for on" needs two passes): looped instead of a single hop. **+7 train.**
5. **"AT SOME POINT" names an intention, not an appointment.** "schedule a
   haircut… at some point" — a calendar verb with a vague-time hedge is still
   `task` (6/6 on the corpus, a closed vocabulary: at some point/stage,
   sometime, some time, whenever) whatever the verb says. **+6 train.**
6. **"BLOCK OFF/OUT time TO do X" is reserving your own slot, not scheduling
   with anyone** — `task` 12/12, even though "block" sits in
   `_CALENDAR_VERBS` ("block off the whole day FOR client call", no "to
   VERB", stays `event` correctly, 7/7 — the "to VERB" infinitive is the
   tell). And "INCLUDING <date>" was being read by `_split_verbless_
   conjuncts` as a real leftover object ("schedule client call…, including
   ON THE 15TH" over-split into a garbage "including" item) — it is a
   function word here, same as "and"/"then"/"also" already in `invariant.
   _STOP`, added there. **+17 train** (11 including, 6 time-blocking) and
   over-split dropped 47→35 in the same measurement — the including bug was
   costing a real false split, not just a wrong field.
7. **A person-encounter is always `event`.** "i have to MEET Quinn" (6/6),
   "i need to SYNC UP with Jordan" (6/6) — neither verb is in either lexicon,
   so nothing else here ever routes them away from the engine tagger's
   `task` guess. "about NAMED-EVENT" (no "before" at all — "remind me to
   email Robin ABOUT onboarding session") is the same anchor idiom as #3 one
   hop earlier, folded into the same check; the real-time requirement was
   loosened from "a stated CLOCK" to "a stated time, day or clock" (`meet`/
   `sync up`/`about` rows carry bare dates, no clock). **+23 train.**
8. **"…and remind me DURATION before" is a lead time on the event just
   booked, not a second ask** — the identical idiom `_lexicon_fallback_
   boundaries` already refused to split on, but "remind" is a real VERB
   conjunct here (not a mis-tagged compound), so it never reached that
   fallback; the MAIN walk in `clause_boundaries` had no such guard at all.
   Added one, anchored to the rest of the text the same way the fallback's
   own check is (a genuine third ask still splits). **+17 train, over-split
   35→16 in the same measurement** — a documented, real pre-existing bug
   (flagged earlier this session as "individually small… none justifies its
   own fix") turned out to cost far more than the one row it was first
   diagnosed on, once measured properly instead of estimated.
9. **"GIVE ME A NUDGE (to do X)" is the same reminder framing as "remind
   me"**, just not spelled with a verb `_lexicon_kind` reads (head is "give
   me", in neither lexicon) — `task` 6/6 regardless of what the wrapped verb
   suggests ("…to BOOK A FLIGHT" reads event-ish on its own). **+6 train.**
10. **A double lead-marker** ("10 minutes BEFORE BEFOREHAND") wasn't
    anchored by `_REMINDER_LEAD_RE` (`^…before$` doesn't match "…before
    beforehand$"); extended the same way `_lead_has_no_object` (#2) already
    was. **"GET X ON THE BOOKS"** is the idiom for getting something
    scheduled, `event` 6/6, head verb "get" carrying no signal of its own.
    **+16 train.**
11. **"…and ADD A NOTE" is an elaboration on the task just named, not a
    second ask** (6/6 on the corpus) — there is nothing to note ABOUT in a
    bare "add a note", so nothing for a second item to be ("add a note
    ABOUT X" is unaffected — a real object makes it a real second ask). Same
    non-splitting-tail mechanism as #8, generalised: `_is_reminder_lead_time`
    retired in favour of `_non_splitting_tail`, which both the main walk and
    the lexicon fallback now share (one gate, not two copies to keep in
    sync). **+6 train, over-split 16→4** — the largest single fraction of
    the WHOLE session's over-split reduction (47→4) came from these two
    non-splitting-tail idioms together.
12. **"GIVE ME THE RUNDOWN" asks what's scheduled — `review`, not `event`**
    (6/6; neither word is in either lexicon, so the engine tagger's own
    guess otherwise stands unchallenged). **"CHANGE/FLIP THE DUE DATE on X"**
    is editing a task's own metadata, `task` 12/12 whatever the wrapped
    title X looks like on its own ("…on CONFIRM THE RESERVATION" reads
    event-ish to the tagger; same guard `_lexicon_kind`'s docstring already
    argues for at the single-word level, extended to a two-word closed
    phrase). **+11 train.**

**Full unit suite (1,711 passed) run after every one of the 16** — several
touch `assistant/intent/coordination.py`, shared with FastRule's own compound
gate, so each was checked beyond segmentation's own tests too.

**Found, not fixed — a genuine SPEC/gold conflict, left for a ruling.**
SPEC.md's own `wrapper-phrase` trap row uses "add buy milk and buy bread to
my list" as its canonical MUST-NOT-SPLIT example ("one verb + one destination
over both"), and DEVQA.md's 2026-09-16 Q14 entry explicitly says this exact
sentence was "already correct… already never split." The actual gold row
(`ns-0049`, `nosplit_traps.jsonl`) splits it into two — and two sibling rows
in the same `wrapper-phrase-to-my-list` family (`ns-0050`, `ns-0052`) do too.
This is the identical shape as the Q14 conflict (a documented ruling the
dataset does not actually match), just not caught by that pass's filter —
`has_clause_coordination("add buy milk and buy bread to my list")` is
TRUE here (two real "buy" VERB conjuncts, not a bare noun list), which
correctly excluded it from Q14's fix but says nothing about which reading —
wrapper-phrase's or the row's own gold — is the intended one. Not resolved
here; needs the same kind of explicit ruling Q14 got, not a unilateral code
change either way. 3 rows, `wrapper-phrase-to-my-list`/`-onto-the-calendar`.

**What's left, roughly by size**: the opener/courtesy-stripping families
(`texture`×5, `generic_target_complex`×2, one `extra` — ~44 rows) are a
DATASET issue, not a FastSeg one — `ingest`'s own repair step already strips
"um"/"so"/"can you" before segmentation ever runs in production (SPEC.md:
text is "AFTER step-1 repair"), so these template rows test input that could
never actually reach FastSeg; matching them would mean deliberately
desyncing FastSeg from `ingest`'s real behaviour to satisfy a fixture that
does not model the real pipeline. Two DIFFERENT `advcl`-subordination shapes
("forget X, i'd rather Y", "first X, then let's get Y on the calendar", ~11
rows) remain the same open gap flagged earlier this session — neither the
main walk (`conj`/`dep` only) nor the fallback (`sentence_initial`'s
`_COORD_WORDS` tolerance) sees a clause introduced by a pronoun-contraction
phrase rather than a coordinator word, and widening that tolerance risks
false positives elsewhere; not attempted this pass. Everything else
remaining is ones and twos — individually real, none big enough on its own
to justify a dedicated mechanism at this dataset's current size.

### 0c · The overfitting check — measured, not assumed (Gil: "continuing
### more as is is definitely overfitting")

Two things were tried, in this order, BEFORE touching `fastseg.py` again —
both measured honestly rather than argued for.

**First, could a fitted classifier replace the growing rule pile?**
`experiments/tag_structural.py` retries `tag_head.py`'s already-refuted
question (§6's refuted table) with a genuinely different feature space —
DEPENDENCY-PARSE-derived signals (does the verb's own object carry a PROPN,
is "before" transitive, the engine's own `_kind_of` verdict as an input) in
place of `KindFeatures`' keyword-PRESENCE regexes (`with\s+[a-z]+` cannot
tell "meeting WITH SAM" from "wash dishes WITH a sponge"). It closed most of
the original gap (94.4% 5-fold-OOF vs the rules' 96.9%, both gold-item TAG
accuracy over 1,501 items — up from the original head's 80.4%) but still
lost. **Not a dead end for ML — a dead end at 1,051 rows split three ways
with many idioms at 6–12 examples.** Full account and numbers in §6.

**Second — the real question — do the 16 fixes generalise to phrasing the
generator never produced, or are they fit to its exact words?**
`experiments/adversarial_tag.py` is 31 hand-written sentences, none a
near-paraphrase of any dataset row: different verbs (catch up with / grab
coffee with / poke me / carve out / shift the due date), same underlying
semantic categories §0b's fixes target. First run, before any widening:
**18/31 (58%)** — against 87.5%/77.3% on the actual dataset. Confirmed,
measured overfitting, exactly as predicted: every fix was a closed
VOCABULARY item keyed to whichever exact word the generator's template
banks happened to render (`before`/`about` but not `concerning`/
`regarding`; "give me a nudge" but not "poke me"/"buzz me"; `change`/`flip`
but not `shift`/`push back`; `block off`/`out` but not `carve out`/`set
aside"`) — "verified against the whole corpus" gave false confidence,
because the corpus itself only cycles a handful of PHRASINGS per category.

Widened the mechanisms that were already general (synonym sets on
`_ANCHORED_TO_EVENT`, `_TIME_BLOCKING`, `_DUE_DATE_EDIT`, `_NUDGE_IDIOM`) and
added one genuinely new STRUCTURAL signal — `_has_person_argument`, the one
feature from the refuted classifier worth porting directly: does the verb
govern a capitalised proper noun, directly or through a preposition,
generalising "meet"/"sync up with" to ANY encounter verb ("grab coffee
with", "catch up with", "see") without enumerating them. First version
regressed 13 train rows — "call Dana and Avery" (task, an outreach errand)
was wrongly promoted to `event` for no better reason than the names being
capitalised, and "ping me AHEAD OF conference call" (the anchored idiom) got
swallowed by the newly-widened "ping me" nudge check before it reached the
anchor test. Both caught by the row-ID diff, not anticipated: outreach verbs
(call/email/text/message/notify/write/send/ping) were carved out of the new
structural checks specifically, since "call/email/text SOMEONE" is an
errand regardless of who, while "grab coffee with"/"see"/"catch up with"
SOMEONE is the encounter itself — a real semantic distinction no purely
structural (verb-blind) signal can make on its own.

**Result: adversarial 58%→84% (26/31), zero regression on the real board**
(train 920/1051 unchanged, sealed 504→510/660, +6 — the vocabulary widening
generalised further than any single §0b fix did, since it isn't keyed to
one family's exact template). Full test suite green throughout (1,715
tests).

**2026-09-17 — the three CUT-level gaps got picked up.** `INTENT_MAP`
(`rule_parser.py`, shared with FastRule) had no entry for "finalize"/
"draft"/"prep" at all, so `has_clause_coordination` could not recognise a
second clause built on them; added, plus the same three to `fastseg.py`'s
OWN separate `_TASK_VERBS` (the CUT lexicon and the TAG lexicon are
different tables — fixing one does not fix the other). Chasing "finalize
the budget and text KAREN about the venue" also found a same-family gap in
`_rescued_by_family`: "text" and "finalize" both resolve to `create_todo`,
so the existing family-MISMATCH rescue correctly refused it — but the
hidden verb's own argument being a capitalised PROPER NOUN is the same
"this is a real second ask" evidence `_has_person_argument` already uses
for TAG, ported one stage over as a second rescue path. **26/31→28/31
(90%)**, zero regression on FastSeg (train 920/1051, sealed 510/660
unchanged) and on FastRule's own 7,200-row board (both halves, output
byte-identical before/after — these verbs simply don't occur in either
corpus, which is the whole point of testing against phrasing that isn't in
them). Two artifact pages (`explorer.html`, `internals.html`) quote
`INTENT_MAP`'s verb count and needed updating to 87 — caught by `test_
artifact_claims.py`, not missed.

Three cases in `adversarial_tag.py` remain honestly marked WRONG, not
silently dropped: one base-engine-tagger misfire outside this stage's
remaining scope; "draft the proposal and then call the client at 3", where
item 1 has no time of its own and inherits item 2's trailing "at 3" per
SPEC.md's own edge-distribution rule, which `_STATED_CLOCK`'s veto-
exception cannot distinguish from an item's own stated time; and the
bare-generic-booking idiom ("book a hotel"), which needs a structural
"does the object carry a named modifier" check neither pass built.

**Run `adversarial_tag.py` after any future TAG/CUT change** — it is the
one check in this stage not measuring the dataset, and the corpus-wide
consistency check every fix in this file already passes is not, by itself,
evidence a mechanism generalises past the generator's own phrasing.

### 0d · "Is the structure sound?" — three structural CUT changes vs. word
### vectors, measured head to head (Gil, 2026-09-17: "I don't want this to
### be a purely rule-based algorithm")

The honest phase-by-phase answer: the three-phase shape is sound and
measured; CUT is genuinely structural (it reads the parse); ASSIGN TIME is
regex and *should* be (a closed domain); TAG is where the word-list worry
is real. Two candidate changes were tried, one with no dependency and one
with a ~40 MB one, and measured against each other.

**#2 — CUT: candidate clause heads by argument structure, not by
dependency label.** The walk only visited `conj`/`dep` tokens, so three
shapes were invisible, none of them fixable with a phrase list:

1. **An object carrying a modifier** — "order NEW office supplies". The
   bare-object check read only the very next token and saw an adjective;
   it now skips ADJ/ADV by POS. **+1 train.**
2. **A later sentence's ROOT behind a lead-in** — "…on the 15th. ALONG
   WITH THAT, remind me…". The fallback's sentence-initial test walked back
   over coordinator words only; a token that is `dep_ == "ROOT"` of a
   non-first sentence is now sentence-initial whatever precedes it,
   because everything before a root inside its own sentence is that
   root's dependent. **+6 train** (the whole `c2_joiner2_2` family).
3. **A command clause subordinated to a LATER verb** — "first PREPARE the
   presentation, then let's get…" parses `prepare` as `advcl` of `let`,
   eight tokens on; neither the walk nor `_boundary_at` (which assumes the
   head precedes the conjunct) could see it. New path, `_subordinate_
   first_boundary`, with structural guards: no subject of its own ("when
   YOU get a chance, water the plants" — `get` IS a command verb, so this
   guard is load-bearing), no `mark` ("IF it rains…"), not an infinitival
   purpose ("call the plumber TO fix the sink"), and a real joiner between
   the two. **First version regressed 17 rows** — "check off this reminder,
   IT'S DONE", "move that one to next wednesday, I DON'T REMEMBER THE
   NAME", "book it every month, NO EXCEPTIONS": the same parse shape with
   the main clause a REMARK, not an ask. Caught by the row-ID diff, fixed
   by `_reads_as_an_ask` — tense, negation and part of speech of the head
   (a base-form verb or its complement; never past, negated, or a noun) —
   read off the parse, not a list of remark phrases. **+3 train, 0 lost.**

Net: train exact-row 920→930/1051 (87.5→88.5%), item-count 96.5→97.4%,
under-split 33→23, over-split 4 unchanged; **sealed 510→516/660
(77.3→78.2%), item-count 90.9→92.1%** — these moved sealed where the
family-keyed §0b fixes could not, which is what "structural" buys.
FastRule's atomic numbers are byte-identical on both halves; its
non-atomic diagnostic moved the right way ("knew it was compound"
63.7→66.1%, "by accident" 12.1→9.6% on the test half — the compound gate
now defers *knowingly* more often). 35 tests in `test_coordination.py`.
One shape is still open: "FORGET email the landlord, i'd rather…" — the
path works, but "forget" is in no lexicon at all, so it is not a command
verb. Vocabulary, not structure — which is exactly what #1 was for.

**#1 — word vectors in place of the closed verb lists.** `en_core_web_sm`
carries no vectors (`(0, 0)`), so `en_core_web_md` was installed in the
venv for the experiment only — never added to any requirements file —
and `sm` kept for parsing so every parse-dependent mechanism stayed
byte-identical. `experiments/verb_vectors.py`: the existing lexicons ARE
the prototypes (nothing new hand-written), a held-out verb is placed by
nearest-prototype cosine, 35 held-out verbs asserted absent from every
lexicon, plus 24 non-verbs. **Refuted on all three questions** — §6's
table has the numbers. The decisive one is separation: at every
threshold most NON-verbs ("budget"→`plan` 0.89, "friday"→`mark` 0.78,
"groceries"→`cook` 0.76) read as command verbs — static vectors encode
topic, not part of speech, and `_is_command_verb` feeds the CUT, where a
promoted noun is a false split. Not a threshold problem and not fixable
by a bigger model. TAG alone would drop from 96.9% to ~67–75%. `md`'s
20k-row pruned table also collides unrelated words at exactly 1.00
("mend"=`walk`, "bump"=`walk`); `lg` would fix the collisions but not the
POS-blindness, so it was not requested.

**Verdict: #2 shipped, #1 not adopted.** The stage is less rule-bound than
it looks — CUT reads the parse and now covers three more structural shapes
without a single new phrase — and the remaining word-list dependence (TAG's
lexicons, `INTENT_MAP`) is, on this evidence, cheaper to extend by hand
than to replace with vectors at this model size. `en_core_web_md` is left
installed in the venv so the experiment re-runs; `pip uninstall
en_core_web_md` removes it, nothing else references it.

### 0e · Widening the lexicons from REAL speech, not from the corpus (Gil,
### 2026-09-17: "see what keywords need to be added to lists")

With vectors refuted, hand-extension is the honest route — but mining the
generated corpus for missing verbs would only find the lexicons' own
vocabulary. `experiments/missing_verbs.py` mines three real sources for
verbs USED AS AN ASK (root with no or a 1st/2nd-person subject, a framing
verb's complement, a coordinated verb) that no lexicon knows: HWU-64
(2,699 human-written utterances, the sealed 300 excluded), the author's
command memory (95 real rows, read-only, LEMMA COUNTS ONLY per
REALSPEECH.md's privacy rule), and FastRule's train half. Family came
from FastRule's own gold where it has the verb, from the HWU examples
otherwise — and gold corrected two guesses: **notify/alert → create_event**
(17/17, 15/15 — a reminder OF an event), **talk → create_event** (45/45,
"talk to Taylor" is an encounter). 25 `INTENT_MAP` keys added (87→112;
meet, talk, catch, touch, head, squeeze, pencil, attend, notify, alert,
label·cal, confirm, mail, sign, tick, erase·2, rid·2, place·2, enter·2,
include·2), the encounter verbs to `_CALENDAR_VERBS`, confirm/mail/sign/
tick to `_TASK_VERBS`, "alert" to `_REMINDER_LEAD_RE`.

Three things the measurement found that a word list alone could not:

- **Phrasal verbs are different words.** "sign me UP for the pottery
  class" (`sp-0003`, gold `event`) regressed to `task` the moment "sign"
  (task, 22/22 for "sign the permission slip") joined `_TASK_VERBS`.
  `_lexicon_kind` now looks past an object pronoun for a particle — a
  closed grammatical class, what spaCy tags `prt` — and consults
  `_PHRASAL_KINDS` first (sign up / set up / catch up / meet up → event;
  wrap up / tick off / check off / drop off → task).
- **The fallback never checked for an object.** "meeting with tal and
  MARK tomorrow" split the moment "meeting" (lemma *meet*) became a
  command verb: the families differed (event vs complete_todo) and
  `_lexicon_fallback_boundaries` had a family test but no own-argument
  test, unlike the main walk. `_carries_an_object` ports it, with a
  preposition counting as an argument unless what it introduces is a date.
- **A date is never an object.** The long-filed "lunch with Reese and
  DREW this coming saturday" over-split (§0) was "saturday" hanging off
  `Drew` as `npadvmod` and counting as an argument. `_is_date_argument`
  asks the child ITSELF (a prep whose object opens a date; a temporal
  head not named by a compound — "moving DAY" is an event, not a when).
  The first cut used `_opens_a_date`, a forward scan built for the slot
  after a verb, and pointed at children it read "set up MOVING DAY for
  new year's eve" as three dates; caught by the row-ID diff.

Net vs. §0d's state: train 930→934/1051 (88.5→88.9%), over-split 4→3,
under-split 23→22, zero rows lost; sealed 516→516/660 — it rose to 519
with the vocabulary alone and the object guard gave those back (sealed
over-split 23→22, under-split 37→34); FastRule's sealed half handle-rate
55.6→56.4%, correct-on-handled 70.2→70.5%, half-executed unchanged (21),
"covered" 116→120. Adversarial 28/31 unchanged. The version that scored
higher on sealed (the crude date scan) was NOT kept: it broke a train row
for an explainable reason, and choosing by the sealed number is the one
thing the split rule forbids.

1. **The compound-chain fix.** `_compound_command_verb`'s hidden-verb search
   only checked DIRECT children. spaCy parses a two-word object as a flat
   sibling pair (`book`/`tennis` both children of `lesson`) or a nested chain
   (`book`→compound→`yoga`→compound→`class`) depending on the words; walking
   the chain instead of just direct children, same safety gate (conjunct's
   head must be VERB/AUX/ROOT) unchanged. **+5 train, +7 sealed.**
2. **The family-mismatch rescue.** Some conjuncts' heads genuinely aren't a
   verb — "buy 3 bananas and book car service **appointment**" hangs
   `appointment` off `bananas` (a NOUN), structurally identical to "buy
   apples and water bottles", which the gate correctly refuses. What tells
   them apart: `book`/`buy` name DIFFERENT kinds of thing (`create_event` vs
   `create_todo` in `INTENT_MAP`) while `water`/`buy` name the SAME kind.
   `_rescued_by_family` fires only after the primary gate has said no, and
   only when both sides resolve to a real `INTENT_MAP` family that differs.
   **+11 train, +0 sealed** (shape not present in this family-split half).
3. **The `nmod` chain link.** spaCy tags the SAME hidden-verb relationship
   `compound` ("book yoga class") or `nmod` ("book annual **checkup**")
   unpredictably; `water` in "buy apples and water bottles" checked as
   `compound` in every phrasing tried, never `nmod`, before widening.
   **+1 train, +0 sealed.**
4. **The bare-object extension.** `book eye exam` has no article at all
   (English never says "book AN eye exam"), so "a determiner after a bare
   command verb proves a real object" never fired for it — recurred across
   roughly a third of the remaining under-split families. A bare NOUN/PROPN
   object now counts too, UNLESS it opens a date — the guard that already
   protects "…and MARK **tomorrow**" reused unchanged. **+8 train, +10
   sealed.**
5. **The lexicon fallback — the largest of the five.** Some rows swallow the
   FIRST clause's verb entirely rather than mis-tagging one token: "schedule
   budget review for next week and add water the plants to my list" parses
   `review` as `nsubj` of `add`, so `schedule` gets no `conj`/`dep` tag at
   all and the whole walk above has nothing to visit. `_lexicon_fallback_
   boundaries` (ported from `rule_parser._lexicon_split_points`, FastRule's
   own independently-proven fix for the identical spaCy failure) trusts
   `INTENT_MAP` vocabulary at the two positions speech opens a new ask from
   — sentence-initial, or right after a coordinator — instead of the broken
   syntax. Needed TWO more guards position alone doesn't have: the same
   family-mismatch check as #2 (`water` sits in exactly this position too),
   and `_verb_intent_family` resolving a QUALIFIER-ONLY verb like `add`
   (`INTENT_MAP` has no `(add, None)`, only `(add, "calendar")` and
   `(add, "todo")`) from the clause's own words against `_CALENDAR_SIGNALS`/
   `_TODO_SIGNALS` — the same signal sets `_route_intent` itself resolves a
   verb's domain from — rather than whichever qualified entry the table
   happens to list first. First measurement found a real new false-positive
   class (over-split 46→52): "book webinar sunday at 8:30pm and remind me
   two hours before" IS a genuine family mismatch (event vs todo) but the
   second clause is a LEAD TIME on the event just booked, not a second ask —
   the exact idiom `fastseg.py`'s OWN splitter already knows (`timed()`,
   "20 rows of over-split the moment lead times became visible"), on a
   different code path this fix doesn't share. Added `_is_reminder_lead_time`
   as this module's own copy of that same rule; over-split returned to
   EXACTLY 46/28, confirmed by exact row-id diff. **+35 train, +37 sealed.**
6. **The sentence-boundary exception.** "remind me to X. also remind me to
   Y" is TWO spaCy sentences — the period is strong enough that its
   sentencizer splits there, and the second "remind" gets its own ROOT
   rather than a `conj`/`dep` tag relative to the first, invisible to
   `sentence_initial` (which was still `i == 0`, doc-wide). Extended to
   `tok.sent.start` per-TOKEN'S OWN sentence, tolerant of a leading
   discourse marker ("also", "then") before the verb, same as `i == 0`
   tolerated none. Both sides here are the SAME `INTENT_MAP` family
   (`create_todo`, `create_todo`) — genuinely two separate reminders, not
   NP-coordination — so fix 2's family-mismatch requirement would have
   wrongly blocked it; a real spaCy sentence boundary is punctuation-driven
   evidence a coordinator position never has (English does not put a
   sentence-ending period inside "buy apples and water bottles"), so it is
   now exempted from that check specifically. **+6 train, +0 sealed**
   (shape not present in this family-split half).

Full unit suite (1709 passed) run after each of the six — `coordination.py`
is shared with FastRule's own compound gate, so every one was checked beyond
segmentation's own tests. New direct tests: `tests/unit/test_coordination.py`
(20 cases — no file existed for this module before this session).

**Found and filed, not fixed — genuinely pre-existing, not caused by any of
the six** (confirmed against a stash of the session's earlier state):
"lunch with Reese and **Drew** this coming saturday" over-splits, because
spaCy tags `Drew` as a past-tense VERB (the same word as "draw"), not a
PROPN — a name collision none of the five checks can see, because the POS
tag itself is what's wrong, not the logic reading it. Same class of problem
as the mis-parsed-root bucket below, on NP-coordination's false-positive
side instead of clause-coordination's false-negative side.

**What's still open**, from a systematic breakdown of the 42 remaining
under-split TRAIN rows (2026-09-16, before the gold correction below) — three
shapes, roughly a third each. The third of those three shapes is now
RESOLVED by the Q14 reversal (item 7 above) rather than by a code fix: "buy
eight sticky notes, apples, and printer paper" and "stick eggs and washing
powder on the shopping list" were counted as under-split against gold that
wanted one item per enumerated object — FastSeg was already emitting ONE
item for these (it never had an enumeration-expansion path for bare NOUN
lists to begin with), so once the gold was corrected to match, these rows
became exact matches with no code involved. That accounts for most of the
33-row drop in remaining under-split (42→33); the other two shapes are
unchanged and still open:

- **"and"/"then" with a sane parse, still no boundary found (the largest
  slice).** Several distinct causes bundled under one symptom: an
  intervening ADJECTIVE before a bare object ("order **new** office
  supplies" — the bare-object check only looks at the token immediately
  after the verb); "forget VERB X, i'd rather VERB Y" and "first VERB X,
  then let's get Y on the calendar", both of which subordinate the first
  clause as an `advcl` of a LATER verb rather than giving either one a
  `conj`/`dep` tag or a fresh sentence root, so neither the main walk nor
  either fallback ever sees them; and "along with that," as a joiner, which
  crosses a period and a comma that neither `sentence_initial` nor
  `follows_coord` matches. Each of these is individually small (1-6 rows) —
  none justifies its own fix at this dataset's current size the way the six
  above did.
- **Needs a 2nd or 3rd split, not a 1st.** "book performance review this
  weekend and remind me to prepare the presentation and pack for the trip"
  finds ONE boundary and stops one short. `cut()` already loops to a fixed
  point specifically to catch this, so this is `cut()`'s own iteration
  logic to trace, not `coordination.py`'s.

`clause_boundaries`'s main loop also still only visits tokens with
`dep_ in ("conj", "dep")` — "remind me to change the air filter, then
**book** staff **meeting**" parses `meeting` as `dep="advcl"`, invisible to
the loop AND to the lexicon fallback (which only fires when the walk finds
NOTHING — this row still finds `book` as a stray compound elsewhere, just
not the right one).

### THE BINDING CONSTRAINT IS NOW THE CUT

The span was the lever and it has been spent — time on a spoken time went
73.4% → 91.6%, and A2's most-missed field fell from time (166) to 21. What is left
is the cut, and three readings say so independently:

    1 ask   641 rows (61%)  ->  71.8%      under-split  108 rows
    2 ask   358 rows (34%)  ->  53.9%      over-split    47 rows
    3 ask    52 rows ( 5%)  ->  53.8%

An 18-point gap between single- and multi-ask rows; under-split more than twice
over-split, so the failure is *not cutting* rather than cutting wrongly; and every
worst trap is a compound. **2026-09-16, after all six fixes above:**
`remind_then` 43.8% → 52.1%, `and_compound` 46.4% → 73.8%, `joiner` 46.2% →
84.6%, `texture` 41.7%/48.6%-stale → 50.0% (fixes 5 and 6's fallbacks reached
some `texture` rows too — quoted strings weren't the only thing in that
trap). `joiner` and `and_compound` have moved from the worst traps to
above-average; `remind_then` is now the one furthest behind, worth its own
look next — it wasn't the direct target of any of the six, so its own
movement was collateral from the ones that overlap it.

The oracle ablation bounds it: perfect everything on correctly-cut rows is 84.5%,
so the cut caps the row metric no matter how good the rest gets.

### What is DONE

| | |
|---|---|
| the time-span vocabulary | `PLAN.md` Phase 1 — one table, +13.5 exact-row, +34 end-to-end |
| discourse tails | a trailing confirmation is not part of the command (Gil) |
| the `other` tag | `ITEM_KINDS`' fourth value, which nothing had ever produced |
| the dataset | incoherent gold 15 → 0, duplicates 21 → 0, four missing trap classes added, and the generator un-broken |

### What is OPEN, in the order the boards argue for

1. **The CUT** — `PLAN.md` Phase 3. §8.1's enumeration (`walk the dog at 9 and
   2:30`, still 54 malformed items downstream) plus the under-split compounds.
2. **TAG, stuck at 87.3%.** The logistic head is refuted (§6). The error is
   one-directional — event read as task, 116 of 175 — so it needs a different
   idea rather than a better classifier.
3. **§8.3** — the date floor injected as a literal word, costing two workarounds.
4. **Two contract questions from Gil** — where an enumeration header's count goes,
   and whether `other` should carry it. `PLAN.md` §3c.
5. ~~**`old_seg` retirement**~~ — DONE 2026-09-20: `retired/segmentation-old-seg/`, tag `segmentation-old-seg`; the kind readers live in `fastseg/kind.py`, the interrogative-create reader in `decompose_validate/object_rules.py`.
6. **No board for unusable input.** The `other` work was verified on 11 hand
   probes; the audit's 25 cases are all well-formed commands, so nothing in the
   repo measures this.

---

The engine's second step. It takes one spoken command and returns the separate
things the speaker asked for. Everything downstream — decompose, generate, the
calendar write — operates on what this step decides, so a boundary drawn wrong
here cannot be recovered later.

---

## 1 · The component as a black box

```
        "tomorrow gym at 7 and meeting at 11"
                        |
                        v
        +---------------------------------+
        |          SEGMENTATION           |
        |                                 |
        |   FastSeg  --->  LLMSeg         |
        |      \             /            |
        |       \           /             |
        |        v         v              |
        |          ACCEPT                 |
        +---------------------------------+
                        |
                        v
     [ (gym,     "tomorrow at 7",  event),
       (meeting, "tomorrow at 11", event) ]
```

**Input** — one command as text, already repaired by `ingest`.

**Output** — a list of ITEMs. An item is exactly three strings:

| field | meaning |
|---|---|
| `action` | the item's words with the time reference removed — verb, object, people, places, quantities, everything else kept |
| `time` | the time reference for this item, **copied as spoken** |
| `tag` | `event` \| `task` \| `review` |

Three properties the component guarantees, each enforced by code rather than
by intention:

**CAPTURE, DO NOT RESOLVE.** `time` holds words, never a date, a range or a
clock reading. `"next friday"` stays `"next friday"`. Resolution happens
downstream in `decompose_validate` (`relative_dates` + `_rule_past_date_bump`),
which reads the raw transcript — so `"the 15th"` on the 20th becomes the 15th
of *next* month without Segmentation knowing anything about it.

**THE INVARIANT.** For every item, `tokens(action) ∪ tokens(time)` covers every
content token of that item and contains nothing absent from the input. A token
may appear in two items — that is what a shared modifier is. One definition,
`fastseg/invariant.py`, imported by the runtime guard, the scorer and the
dataset generator. It was three copies once and they drifted: the guard
rejected a correct model answer for defaulting an untimed item to `"today"`,
which is exactly what the spec tells it to do.

**THE TAG NAMES THE SURFACE, NOT THE OPERATION.** `"cancel the dentist"` is
`event` because it concerns the calendar. Whether an item creates, edits or
deletes is decided later.

---

## 2 · FastSeg — the deterministic half

No model. ~3 ms per command, 0 model calls over 1,051 rows. **Five phases**, and
the order is measured rather than chosen: DialogUSR (Findings of EMNLP 2022) reports
Split → (Delete + Complete) beating the reverse by 9 exact-match points.

```
   text
     |
     v
  +--------------------------------------------------------------+
  |  0  CLEAN                                                    |
  |     strip_spoken_noise      "um", "so", false starts         |
  |     strip_discourse_tail    "...does that seem right"        |
  +--------------------------------------------------------------+
     |  clean
     v
  +--------------------------------------------------------------+
  |  1  CUT            -> pieces (SUBSTRINGS of `clean`)         |
  |     loop to a FIXED POINT, max 3 rounds:                     |
  |       a. split_clauses + every_part_is_an_ask                |
  |       b. _split_verbless_conjuncts                           |
  |          both sides timed AND the right side has content      |
  +--------------------------------------------------------------+
     |  pieces
     v                          .-------------------------------.
  +----------------------------|  find_time_refs(clean)         |
  |  2  ASSIGN TIME            |  every pattern, then LONGEST-  |
  |     reads the pieces AND   |  FIRST, non-overlapping, with  |
  |     the ORIGINAL string    |  the preposition absorbed left |
  |                            '-------------------------------'
  |     INTERIOR ref -> its own piece                            |
  |     LEADING     -> fills a SLOT any piece left empty         |
  |     TRAILING    -> only a piece with NO time at all          |
  |     the DATE FLOOR: no day named -> "today"                  |
  |     joined by SLOT CLASS (day, then clock), not by position  |
  +--------------------------------------------------------------+
     |  [(action, time), ...]
     v
  +--------------------------------------------------------------+
  |  3  EXPAND ENUMERATIONS                                      |
  |     one activity at SEVERAL times becomes several items      |
  |     "at 9 and 2:30" -> "at 9" + "at 2:30", action COPIED     |
  +--------------------------------------------------------------+
     |  [(action, time), ...]
     v
  +--------------------------------------------------------------+
  |  4  TAG          event | task | review | other               |
  |     engine reader decides; then ONE-WAY vetoes over `event`  |
  +--------------------------------------------------------------+
     |
     v
   [ {action, time, tag}, ... ]
```

**Why phase 3 is separate from phase 1**, which looks like it should be the cut's
job: `cut` returns SUBSTRINGS and phase 2 maps each one back into `clean` by
position (`_locate`). A synthesised piece — "walk the dog at 2:30", assembled from
words that are not adjacent in the text — has nowhere to be located. On
(action, time) PAIRS that constraint is gone, so the expansion happens after the
mapping and `cut` stays the fixed-point loop it is.

### The time-reference vocabulary — one table, eight kinds

`_TIME_PATTERNS` is the single place a new time expression is taught, and **its
order does not matter**: `find_time_refs` collects every candidate from every
pattern and then takes them longest-first, non-overlapping. So `late afternoon`
beats `afternoon` by being longer rather than by being placed above it. That was
once a docstring claim rather than a property of the code, and it cost 31
content-loss rows before it became one.

| kind | slot | example | why the kind exists |
|---|---|---|---|
| `date` | day | `next friday`, `the 20th of november` | |
| `recurrence` | day | `every tuesday and thursday`, `on sundays` | temporal repetition IS the time (Gil) |
| `deadline` | day | `by friday`, `until next tuesday` | it is what distributes over a whole command |
| `clock` | clock | `at 7am`, `ten thirty`, `9 in the morning` | |
| `range` | clock | `from 3 to 4pm`, `between 2 and 4` | ONE reference, not two ends — otherwise the joiner cuts the range in half |
| `lead` | clock | `15 minutes before`, `an hour ahead` | a reminder offset, and it must NOT make a side look independently timed |
| `enum_clock` | clock | `at 9 and 2:30` | a bounded enumeration, expanded in phase 3 |
| `enum_day` | day | `on tuesday and thursday` | the same, over days |

**The two slot classes are the GOLD's**, not this file's invention:
`experiments/generate.py` has `_DAY_SLOTS` and `_CLOCK_SLOTS`, and it puts
`lead_time` and `time_range` on the clock side. Matching it matters more than it
looks — a `lead` falling to `day` would both collide with a real date and satisfy
the `any(_slot(r) == "day")` test that guards the date floor, switching the floor
off silently.

### Phase 1 — CUT

Delimiters, then the clause parse, **looped to a fixed point** rather than run
once. A fixed point is also the stopping test the literature uses: DisSim
recurses a rule set until no rule fires, ADaPT on executor failure, DecomP on a
size check. None of them trains an "is this atomic?" classifier, and the one
paper that did reports 54–66% on the decision.

A second tier handles what a clause splitter structurally cannot see — the
**verbless conjunct**:

> `set up physical therapy at 9:15 and birthday dinner at midnight`

The second conjunct is a bare noun phrase, so nothing marks it as a clause. The
evidence used instead of a verb: **both sides carry their own time reference,
and the right side has content that is not part of its time.** That second
condition is load-bearing — it is what keeps the decoys whole:

| text | verdict |
|---|---|
| `set up physical therapy at 9:15 and birthday dinner at midnight` | split — `birthday dinner` survives removing its time |
| `walk the dog at 9 and 2:30` | keep — nothing is left on the right |
| `take the tablets at noon and at six` | keep — nothing is left |
| `meeting with Sam and Alex at 8` | keep — the left side carries no time |

### Phase 2 — ASSIGN TIME

Reads the pieces **and** the original string together, because once a command
is cut, a splitter working piece-by-piece can no longer see that a leading
"tomorrow" covers the second piece too.

Time expressions are found longest-first. That used to be a claim in a
docstring rather than a property of the code — the pattern list is grouped by
kind, so bare `today` outranked `a week from today` and stranded "a week from"
in the action. Matches are now collected and taken longest-first so pattern
order cannot silently decide the answer.

**The two edges do not behave the same.** This asymmetry was found by
generating gold from templates, not by reasoning:

> **LEADING** scopes forward over the whole command, per slot class — a day and
> a clock are separate slots, so a leading day still reaches an item that has a
> clock but no day.
>
> **TRAILING** attaches to its own clause, reaching back only to an item with
> no time at all.

| text | times | why |
|---|---|---|
| `tomorrow gym at 7 and meeting at 11` | `tomorrow at 7` · `tomorrow at 11` | leading day, per slot |
| `gym session at 7, tomorrow meeting at 10` | `today at 7` · `tomorrow at 10` | interior — no backscope |
| `submit the grades and prepare the slides by friday` | `by friday` · `by friday` | trailing; item 1 had no time |
| `do i have anything this weekend and book the haircut at 3:45` | `this weekend` · `today at 3:45` | trailing clock stays put |

Distributing per slot class in *both* directions gave the question
`this weekend at 3:45`. The asymmetry also matches English: pre-posed temporal
adverbials scope over the utterance, post-posed ones attach to the nearest
clause.

**The date floor** — the day defaults to `today`, the clock is never invented.
Nothing said → `today`; a clock only → `today at 7`; a day only → `tomorrow`.

### Phase 3 — EXPAND ENUMERATIONS

A **bounded enumeration** of times is SEVERAL items; an **unbounded `every X`** is
ONE item with a recurrence. Gil, 2026-09-08: *"the segmentation is supposed to split
'walk the dog at 9 and 2:30' into two events of walk the dog."*

    walk the dog at 9 and 2:30        ->  walk the dog @ today at 9
                                          walk the dog @ today at 2:30
    gym on tuesday and thursday this week  ->  two events, bounded by "this week"
    gym every tuesday and thursday    ->  ONE event, recurring

The action is **copied, not divided** — which is why the invariant permits a token
in more than one item. The preposition is copied too: "at 9 and 2:30" says `at` once
and means it twice, so a part that lost it gets it back rather than reading
"today 2:30".

**The three decoys survive by their reference TYPE**, not by a special case each:

| | the trailing conjunct is | so |
|---|---|---|
| `walk the dog at 9 and 2:30` | only a TIME (`enum_clock`) | expand |
| `book gym between 2 and 4` | inside ONE `range` reference | untouched |
| `meeting with Sam and Alex at 8` | a NAME, and no time left of the joiner | untouched |
| `buy milk and eggs` | an OBJECT, no time at all | untouched |

That is why the vocabulary work in phase 2 had to land first: once a range is a
single reference, the rule is simply *"two clock-class references, expand"* and the
decoys exclude themselves by counting. Written the other way round it needs a
carve-out per decoy.

### Phase 4 — TAG

`event | task | review | other`. The engine's own reader decides first, so this
module and the tuning experiments cannot disagree about what a review looks like.

**Two rulings the tag reads since 2026-09-24.** DEVQA Q47: an ENCOUNTER with a
person — meeting, seeing, visiting, calling, eating with a named person or a
family word — is an event (09:00 when no clock was said), on any day; the
reader is shared with the front door (`assistant/intent/encounter.py`), and a
written message ("email", "text"), a mention or a named to-do list stays a
to-do. And "add / make / leave / write a note to …" and "note to self" are
to-do frames (`fastseg/kind.py`), though a stated clock still makes an event
(Q25) and an encounter still wins (Q47). The tag is a PROPOSAL:
decompose_validate's kind router lets any rule that fired stand and asks its
small model only on this phase's catch-all path.
Then **every correction is a ONE-WAY VETO over `event`, never into it** — and that
asymmetry, rather than the quality of any single signal, is what makes the phase
work. It has now been measured three times:

| signal | as a verdict (both directions) | as a veto over `event` |
|---|---|---|
| the task-verb lexicon | 82.4% | **87.5%** |
| the logistic `kind` head | 80.4% | 80.1% — refuted either way (§6) |
| `_NOT_CALENDAR` → `other` | never tried; it would swallow tasks | shipped |

**The three vetoes, in order** (`tag()`):

1. **`other`** — not a calendar ask at all (`thanks`, `play some music`,
   `turn on the lights`). A closed vocabulary, because a bare noun phrase is the
   NORMAL way to name an event (`physio`, `standup`) so no shape test can separate
   `physio` from `i love you`. **A stated time overrules the veto**: "turn on the
   lights" is smart-home, "turn on the oven at 6" is a reminder, and the only
   difference is that the speaker scheduled one.
2. **the task-verb lexicon, read at the HEAD VERB** — after skipping the preamble
   (`i need to`, `please`, `um so`). Reading every word let a NOUN decide: "add the
   budget review" and "add a call with Riley" were tagged `task` because `review`
   and `call` are on the list, though the verb is `add`. 56 of 179 errors.
3. **a STATED CLOCK cancels a task verdict** — "walk the dog" is a to-do and "walk
   the dog at 9" is an appointment. Same verb; the speaker named a time. 34 of 179.
   The floor's bare "today" does not count, since the engine wrote it.

Measured on 1,516 gold items: lexicon anywhere **88.6%** → head verb only 89.8% →
+ the clock rule **90.8%**. Live board: **89.7% train, 90.2% sealed**.

The historical measurements that set the shape:
Measured over 1,383 matched items — overriding both ways loses more events than
it gains tasks:

| | accuracy | task recall |
|---|---|---|
| engine tagger alone | 84.7% | 70.7% |
| lexicon overrides everywhere | 82.4% | 78.5% |
| **lexicon only over `event`** | **87.5%** | **89.9%** |

A parser was tried here first and was much worse (65.0%) — see §6.

#### MEASURED AND REFUTED: the logistic `kind` head (2026-09-09)

Run as `experiments/tag_head.py` — **88.7% shipped against 80.4%** for the head,
and worse on every slice including the hand-written rows that cannot be in its
fitting data. It over-predicts `task`, which is precisely the failure the lexicon
experiment below already measured and rejected.

**The lesson generalises past this one arm.** Two independent signals — a task-verb
lexicon and a fitted task/event classifier — both fail the same way on this data,
by calling events tasks. Calendar commands are verb-rooted imperatives, so anything
keyed on the verb leans task; and of 439 items no verb list decides, **349 are
events**. The shipped tagger wins by using the signal only as a ONE-WAY veto, and
that asymmetry is doing the work rather than the signal's quality.

The brief below is kept as the record of what was tried and why.

#### The original candidate (Gil, 2026-09-08)

The engine already carries a trained **event/task classifier** —
`classifier.py`'s `KindFeatures` + `LogisticModel`, weights in
`intent/route_model_weights.json` — and FastRule consults it as a fallthrough
tier. TAG is the same question, so it is worth measuring here instead of a
hand-built reader plus a lexicon override.

**What it would have to beat: 87.5% accuracy / 89.9% task recall** on the 1,383
matched items above. Cheap enough to be worth the test — inference is a
hand-written dot product over a float list, no ML dependency, well inside
FastSeg's 0.002 s/row.

Three things to get right before believing any number it produces:

- **It has two classes; TAG has three.** `kind` is event/task, and `review` is
  absent. The review test is deterministic and deliberately SHARED with LLMSeg
  so the two cannot disagree about what a review looks like — so the shape to
  test is *review pre-check first, then the head decides event vs task*, not a
  three-class head.
- **It was fitted on a different dataset** — `fastrule_7200.jsonl`'s train half.
  Scoring it on segmentation's items is therefore a genuine cross-dataset
  generalisation test, which is a point in its favour, but the two corpora
  overlap in provenance (both are built from the same filler banks), so the
  comparison must be run on segmentation's own held-out half or it will read
  high for the wrong reason.
- **Compare it against the RIGHT baseline.** Not the engine reader alone
  (84.7%) — against reader + lexicon-over-`event` (87.5%), which is what ships.
  Beating the weaker number would be a measurement artifact, and that is exactly
  the mistake the table above exists to prevent.

Not a design change: TAG's contract (`event | task | review`) is unchanged, and
swapping the reader for a Component inside the stage is invisible to the trace.

---

## 3 · LLMSeg — the model half, **OFF BY DEFAULT**

> ### RE-TESTED 2026-09-16 — same verdict, on the CURRENT FastSeg, with the
> ### stale-comparison caveat below now retired
>
> The prior four measurements were taken when FastSeg was 51.5% exact-row;
> it is 64.8-68.2% now, so the 2026-09-09 caveat above was live until this
> pass re-derived the numbers against today's baseline.
>
> **The oracle-gate ceiling collapsed from +3.8% to +0.0%.** `gate_sizing.py`
> replays the cache and asks "how good could ANY gate be, including a
> hindsight-cheating one?" — on 204 fresh TRAIN rows (V4, `use_model=True`,
> current FastSeg as the anchor), LLMSeg fixed **zero** rows and broke 57.
> Every one of the 13 runtime-computable gate features (`has_joiner`,
> `times_exceed_pieces`, sentence length, "remind me"/"on my calendar"
> markers, ...) scored negative or flat — there is no subset, however
> identified, with anything to route TOWARD. A stronger FastSeg did not
> just shrink LLMSeg's upside, as the caveat predicted; it looks to have
> erased it.
>
> **Two new task shapes were tried, neither the four from 2026-09-08.**
> Both let the model intervene only on the CUT (never the tag), scored on
> item-count / exact-set rather than exact-row for that reason:
>
> - **`word-index`** — every word numbered, model outputs the word-indices
>   where a new item starts (integers, not text, so no-loss/no-invention are
>   true by construction). REFUTED harder than anything before it: 20-row
>   pilot, item-count 85.0% -> 15.0%, fixes 0 / breaks 12. Inspecting the raw
>   replies showed why: "i need to sync up with Jordan next monday" (one
>   ask, 9 words) came back `[1, 7]`, splitting mid-phrase with no relation
>   to the sentence. An 8B does not reliably hold an absolute position in a
>   numbered list as a real constraint.
> - **`mark`** — instead of positions, mark only the CANDIDATE joins
>   ("and"/"then"/"as well as"/...) inline and ask a LOCAL true/false per
>   mark ("does a new ask start right after `<2>`?"), reconstructing pieces
>   from the joiner's own character span. A real, different mechanism from
>   `word-index` — no counting, no copying. First version's few-shot
>   examples reused the same `<1>` placeholder five times in the rules text
>   above the real command; on 158 rows every inspected failure showed an
>   EXTRA key with no matching mark (`{"1": false, "2": true}` on a
>   ONE-mark sentence) — the model was counting `<1>` occurrences across
>   the WHOLE prompt, not just the command. `mark2` states the count up
>   front ("exactly N marks") and replaces every illustrative placeholder
>   with the word HERE, leaving the real marks as the only numbered tokens
>   anywhere in the prompt — confirmed fixed (every `mark2` reply has
>   exactly as many keys as real marks). **Still net negative** on the full
>   293-row trap-stratified TRAIN sample (48/48 traps, 95% CI +/-5.7%):
>   exact-row 64.8% -> 57.0%, item-count 86.0% -> 75.1%, fixes 13 / breaks
>   36. Fixing the counting bug did not rescue the judgement — inspected
>   failures show the SAME sentence template ("scrap X off the calendar and
>   throw Y on there instead") getting different true/false verdicts across
>   near-identical rows, and the "every tuesday and thursday" recurrence
>   mis-split recurring unchanged from `mark` v1.
>
> **Read together: five independent task shapes, six prompts, one model,
> zero net-positive results.** Full-rewrite (V1-V6, V3, V4), cut-then-copy
> (`boundaries`), count-only (`count`), absolute-position (`word-index`) and
> local-classification (`mark`/`mark2`) all lose. The common thread is not
> one prompt defect — each was tuned or bug-fixed and re-measured — it is
> that **llama3.1:8b's judgement on where FastSeg's cut is wrong is
> unreliable in the direction that matters**: it does not merely miss real
> errors, it invents disagreements with correct proposals more often than it
> catches real ones, on every framing tried. The next lever, if this is
> picked up again, is a DIFFERENT MODEL — only llama3.1:8b is pulled
> locally today — not another prompt for this one; `experiments/prompt_lab.py`
> has the harness and the cache ready for whichever one arrives.
>
> Board D (needs both a FastSeg and a final prediction, so it only reports
> with LLMSeg on) still has not run — moot while the oracle ceiling is 0%,
> since there is nothing for it to find LLMSeg earning back.

> ### The flag
>
> ```python
> llmseg.ENABLED          # False unless MACALENDAR_LLMSEG is set
> segment(text)                      # -> FastSeg only, route "fastseg-only"
> segment(text, use_model=True)      # -> forces the model on, for experiments
> segment(text, use_model=False)     # -> forces it off
> ```
>
> `MACALENDAR_LLMSEG=1` turns it on for one command. **The default is OFF**
> (Gil, 2026-09-08). LLMSeg stays wired, tested and kept — it simply does not
> run unless something asks for it.
>
> **Any board measuring LLMSeg must pass `use_model=True` explicitly.** If a
> measurement inherited the default it would report FastSeg's numbers under
> LLMSeg's name, and that class of silent-measurement bug has already bitten
> this module twice.
>
> **When Segmentation is promoted over `old_seg`, this becomes a config
> setting** — `engine.segmentation.llmseg: off` in `config.yaml`, mirrored into
> `config.example.yaml` per the project convention. It is a module flag today
> only because the component is not yet wired to `config.py`.
>
> **Why it is off**, in one line: measured four independent ways against
> FastSeg on 571 trap-stratified rows, every one came back negative, and the
> most decisive test used a prompt written *after* an audit fixed five defects
> in the old one — so the prompt was not the problem. Numbers in §6.



One schema-shaped call to the local llama3.1:8b, anchored on FastSeg's
proposal, followed by two deterministic guards.

```
   FastSeg proposal ──► prompt ──► model ──► TAG COERCION ──► ACCEPT ──► items
                                                                 │
                                            invariant fails ─────┘──► keep FastSeg
```

**The protocol was measured, not assumed.** Against llama3.1:8b on 14 cases:

| | |
|---|---|
| V1 "No Change" or a correction | 5/14 |
| V2 V1 + a four-point checklist | 1/14 — it narrates |
| **V3 no judgement, always emit, we diff** | **11/14** |
| V6 V3 with no proposal shown | 8/14 — the anchor is worth +3 |

Asking an 8B "is this right?" invites the accept bias — V1 waved through 4 of
7 broken inputs, the same self-assessment over-estimate ADaPT measured at 30+
points. Taking the decision away from the model fixes it.

**TAG COERCION** snaps whatever string comes back to `event|task|review`
(exact → synonym → word scan → closest match → FastSeg's tag), so the tag is
structurally correct rather than trusted.

**ACCEPT** takes the model's answer only if it satisfies the invariant. Its
commonest failure is deleting a shared `"tomorrow"` instead of distributing it,
or dropping `remind` from `"remind me to X"` — 12 of 37 rejections in one run.

**The prompt is V4, and `experiments/check_prompt.py` proves it still agrees
with the spec.** V3 was audited and found to teach five things the gold no
longer accepts: the symmetric edge rule (12.2% of rows), a missing date floor
in an example that contradicted another example in the same prompt, a dropped
preposition, a half-stated floor rule, and nothing at all about what the tag
means for a delete. Every one graded the model **wrong for obeying its
instructions**, which makes any measurement taken against V3 worthless as
evidence about the model. The check parses the shipped examples and asserts
each satisfies the invariant, the floor, preposition capture and the tag
vocabulary — the same idea as `test_artifact_claims.py` keeping published pages
honest about the code.

---

## 4 · The datasets — `datasets/`

**1,694 rows**, split BY FAMILY so a family never straddles the boundary.

| | rows | source | traps |
|---|---|---|---|
| TRAIN | 1,040 | 960 generated / 80 hand-written | 44/44 |
| **TEST (sealed)** | 654 | 594 / 60 | 44/44 |

Leakage: 0 family overlap, 0 exact-text overlap; 11 test rows (1.8%) share a
gold action-set with train — the one blemish, recorded rather than hidden.

**1,554 rows did not start from scratch.** `assistant/engine/fastrule/datasets/banks/
complex_patterns.json` already held 321 templates built for a different board,
and they carry exactly what segment gold needs: an `atomic` flag and **named
slots**. Because the template says `{date}`, the action/time split is *known by
construction* rather than inferred — a regex over rendered text would just be
FastSeg marking its own homework. 187 templates are atomic and **74 of those
contain a joiner** ("buy {item} and {item2}"), which makes them decoy rows a
naive splitter fails: the most expensive kind to write by hand.

**62 families are excluded and reported, never guessed.** 38 are `propose`
("should i book X?"), which asks for advice and has no honest label in a
three-tag contract.

**Known gaps.** 13 traps have fewer than 4 rows in the whole train pool, and
`review` is thin (61 items). The next expansion should target thin traps, not
more volume from the same templates.

---

## 5 · The evaluation — `experiments/score.py`

**Six boards, never one number.** A single figure hides *which way* a run is
failing, and the two ways cost very different amounts.

| board | what it answers |
|---|---|
| **A boundaries** | exact-set, exact-row, item count (*the cut alone*), item P/R/F1, over- vs under-split **kept separate and never summed** |
| **A2 partial credit** | 2 of 3 fields, action judged by *kind* of difference — plus which field is being missed |
| **B action/time** | the invariant (invention · loss, both MUST be 0) + time on a *spoken* time vs the `today` default |
| **C tag** | accuracy, per-class P/R/F1, confusion |
| **D verifier** | does the model's correction pay for itself |
| **E cost** | model calls/row, latency/row |
| **F composition** | what the score was computed *over* — ask-count spread, per-trap breakdown |

**`exact-row`** is the product-level number: the predicted decomposition, as a
multiset of `(action, time, tag)`, equal to gold. All-or-nothing — one wrong
tag on one item of a two-item command sinks the row.

**`A2` exists because the action boundary is a judgement call.** A similarity
threshold was tried first and **rejected on measurement**: at Dice 0.80 it
admitted 140 real errors while rejecting 85 genuine boundary calls, because the
two populations overlap and no cutoff separates them. Cosine and Jaccard invert
the same way — the catastrophic under-split scores *higher* than the harmless
boundary call, because overlap measures penalise proportionally and a short
action is punished harder for the same absolute error.

> So the test is not *how much* differs but *what kind* of token differs:
> **the action is correct when every token the two readings disagree on is a
> TIME token.** No threshold, and it uses only data already in the items.

Report the missed-field breakdown beside the 2-of-3 rate, always: "2 of 3" can
be passed by failing the *same* field every time.

**Sampling is trap-stratified** (`MIN_PER_TRAP` first, then proportional). The
first prompt slice was proportional and left 13 of 44 traps EMPTY — including
`serial-verb` and `name-coordination`, the shapes most likely to *refute* the
hypothesis being tested. Measuring a hypothesis on a set that excludes its
failure mode is not a measurement.

---

## 6 · Results

FastSeg alone, segment-tuning **TRAIN** half (1,040 rows). The sealed 654 rows
have never been scored.

| metric | start | segment-tuning | **+ span vocabulary (2026-09-09)** |
|---|---|---|---|
| exact-set | — | 61.2% | **76.3%** |
| exact-row | 33.1% | 51.5% | **64.8%** |
| item count — *the cut* | 78.6% | 84.5% | **85.3%** |
| item F1 | 91.2% | 94.1% | **94.5%** |
| over / under split | — | 51 / 110 | **47 / 108** |
| time on a SPOKEN time | 49.1% | 74.2% | **91.6%** |
| row-level 2-of-3 | — | 79.7% | **83.5%** |
| tag accuracy | 83.7% | 87.5% | 87.3% |
| NO-INVENTION violations | 0 | 0 | **0** |
| latency | 3 ms | ~10 ms | **~10 ms**, zero model calls |

The third column is `PLAN.md` Phase 1 — the time-span vocabulary, which was the
oracle ablation's biggest lever (+205 rows) and turned out to be entries in ONE
table plus two one-line changes. **Downstream it moved the pipeline from 51.6% to
86.0%** rows-fully-right (`decompose_validate/eval_metrics/end_to_end.py`), and the
attribution there still shows zero value errors that are the resolver's own.

Traps that moved: `lead_time` 0.0% → 50.0% (72 rows), `time_list_vs_range`
2.8% → 72.2%, `recurrence` 61.1% → 88.9%, `until_through` 33.3% → 64.3%.

**Tag is now the binding constraint** — flat at 87.3% while everything around it
moved, and it is the field A2 reports missed most often (129) now that time has
fallen to 21. That is the case for the `kind`-head candidate in §2 Phase 3.

### Where the remaining headroom is — oracle ablation

| give FastSeg the gold for… | exact-row | gain |
|---|---|---|
| nothing | 51.5% | — |
| perfect tag | 59.2% | +82 rows |
| perfect action only | 56.6% | +55 |
| perfect time only | 52.7% | +14 |
| **perfect SPAN (action+time together)** | **71.1%** | **+205** |
| perfect everything on correctly-cut rows | 84.5% | +345 |

**The span is the biggest lever, and the singles understate it badly.** The
errors are coupled: a mis-cut span leaves residue in the action *and* truncates
the time, so fixing either field alone still fails the row. The work is
multi-word fuzzy time expressions — `late afternoon`, `first thing in the
morning`, `9 in the morning`.

### Refuted — recorded so they are not re-attempted

| hypothesis | verdict |
|---|---|
| a spaCy POS/dependency rewrite fixes the tagger | **NO** — 65.0% vs 84.7%. Calendar commands are VERB-rooted imperatives, so "root is a VERB → task" calls `add vet appointment to my calendar` a task. Of 439 items no verb list decides, **349 are events**. |
| the destination distributes like an edge time | **NO** — +15 blanket, −23 scoped |
| gating LLMSeg to the right rows rescues it | **NO** — it fixes 6 and breaks 16, so an *oracle* gate is worth +3.8% |
| the model should do the cutting, FastSeg the copying | **NO** — item-count 83.9% → **57.3%**, breaks 132. Predicted from DialogUSR's cut-vs-copy gap, but that compares a model's cut to its *own* copy, not to a tuned deterministic cutter. |
| a similarity threshold can score the action | **NO** — see §5 |
| **the logistic `kind` head is a better TAG** | **NO — 88.7% → 80.4%**, and refuted on all three slices including hand-written rows that cannot be in its fitting data. It over-predicts `task`: task recall rises 90.2% → 92.8% while **event recall collapses 87.7% → 71.4%**, event→task errors 106 → 247. Tried as a decisive-only tier (81.2%) and as a one-way veto over `event` (80.1%) — both worse. `experiments/tag_head.py` |
| **a STRUCTURAL classifier (dependency-parse features, not keyword presence) beats the hand rules** | **NO, but closer — 94.4% 5-fold OOF vs the rules' 96.9%** (gold-item tag accuracy; hand-written slice 88.6% vs 89.9%), tried after §0b's 16 fixes specifically to test whether the ORIGINAL head's loss was about features (keyword-presence: `with\s+[a-z]+` cannot tell a verb's real argument from an unrelated word after a shared preposition) rather than about ML itself. It was: swapping to genuine parse-derived features (does the verb's own `dobj`/`prep→pobj` carry a PROPN, "before"'s transitivity, the engine's own `_kind_of` verdict as an input) recovered 14.0 of the 16.5-point gap (80.4%→94.4%), but 1,051 rows split three ways — many idioms at 6-12 examples — is not enough for ANY fitted model, however featured, to beat rules individually verified against the corpus's full label distribution. Tried as a one-way veto over `event` too (95.4% best, still below 96.9%): when it disagrees with the rules, it is wrong more often than right. `experiments/tag_structural.py` |
| **word vectors (`en_core_web_md`) can replace the closed verb lists** | **NO, on all three questions.** Held-out verbs asserted absent from every lexicon, nearest-prototype cosine with the EXISTING lexicons as prototypes. TAG (task vs event): 66.7% (18/27 answered at threshold 0.30), 75% (6/8) at 0.60 — vs the rules' 96.9% (n=1,501). INTENT_MAP family: ~45% (13/29). **Separation is the decisive failure**: at threshold 0.40, 22/24 NON-verbs ("budget"→`plan` 0.89, "friday"→`mark` 0.78, "groceries"→`cook` 0.76) read as command verbs; even at 0.65 it is 10/24 nouns passing vs 10/35 verbs — no threshold separates them, because static vectors encode topic, not part of speech, and `_is_command_verb` feeds the CUT. `md`'s pruned 20k-row table also collides unrelated words at exactly 1.00 ("mend"=`walk`); `lg` would fix that, not the POS-blindness. Model installed in the venv only, never in requirements. `experiments/verb_vectors.py` |

### LLMSeg's standing — turned OFF, on SIX measurements now

| test | result |
|---|---|
| V3 full rewrite | −10 rows — **void**, the prompt taught a superseded rule on 12.2% of rows |
| `boundaries` — model cuts, FastSeg copies | exact-row −17.3pp, item-count −26.6pp, **NO-INVENTION 0 → 4** |
| `count` — model returns only a digit | −2.4pp, breaks 19 |
| **`v4-full` — every prompt defect fixed** | **−12pp; fixes 1, breaks 42** |
| `word-index` — model outputs word-index cut points (2026-09-16) | item-count **85.0% → 15.0%**, fixes 0 / breaks 12 (20-row pilot; refuted too hard to need more) |
| `mark2` — local true/false at each candidate join, no counting (2026-09-16) | exact-row 64.8% → 57.0%, item-count 86.0% → 75.1%, fixes 13 / breaks 36 (293 rows, 48/48 traps, 95% CI ±5.7%) |

**2026-09-16 re-test against the CURRENT (much stronger) FastSeg**: the
2026-09-09 note below this table said every prior comparison was stale
because FastSeg had gone from 51.5% to 68%+ exact-row since these were
measured. Re-run fresh (`gate_sizing.py` on 204 TRAIN rows, V4, current
FastSeg as anchor): the oracle-gate ceiling — the best ANY gate could
achieve, including a hindsight-cheating one — fell from +3.8% to **+0.0%**.
LLMSeg fixed zero rows and broke 57; every one of 13 candidate runtime
features scored as a gate came back negative or flat. Two new task shapes
(`word-index`, `mark`/`mark2`, detailed in §3's callout) were tried
specifically to fix the failure modes the four historical tests exposed —
absolute-position output instead of verbatim copying, then local
classification instead of absolute position — and both still lose. Five
task shapes, six prompts, one model, zero net-positive results: the
limiting factor reads as the model's judgement on this task, not the
prompt's wording.

Full board for `boundaries`, all twenty metrics, 571 identical rows:

| metric | FastSeg | +LLMSeg | |
|---|---|---|---|
| exact-set / exact-row | 61.1% / 51.1% | 40.8% / 33.8% | WORSE |
| right item count | 83.9% | 57.3% | WORSE |
| item P / R / F1 | 95.8 / 92.5 / 94.1 | 51.5 / 94.7 / 66.7 | WORSE |
| rows over- / under-split | 33 / 59 | **238** / 6 | WORSE |
| A2 rows ≥ 2 of 3 | 78.3% | 53.6% | WORSE |
| NO-INVENTION items *(must be 0)* | **0** | **4** | WORSE |
| NO-LOSS items *(must be 0)* | 89 | 226 | WORSE |
| tag accuracy | 86.5% | 85.4% | WORSE |
| seconds / row | 0.01 | 6.30 | WORSE |

Read the "better" cells carefully: recall rises only because it over-splits 238
rows, and precision falls 44 points to pay for it. **Over- and under-split are
never summed** — an over-split makes garbage immediately, an under-split gets
two more chances downstream, so trading one for the other is not a win.

`v4-full` is the one that settles it. Every prompt defect fixed, examples
verified mechanically by `check_prompt.py`, and it still fixed **one row in
358**:

```
put do the laundry and return the rental car on my list
```

### old_seg vs FastSeg — the promotion question, measured

294 trap-stratified TRAIN rows, judged only on what BOTH systems were built to
do. `old_seg` emits `(text, kind)` and never separated time from action, so
`time` and `exact-row` are N/A for it **by design** — it is not scored on them,
and its gold is rebuilt as `action + time` (the span it should have produced),
minus the date floor, which is a value the labelling adds rather than a word the
speaker said.

| | item count | item F1 | tag acc | over / under | sec/row |
|---|---|---|---|---|---|
| `old_seg` (shipped) | **86.1%** | **95.1%** | 84.6% | 21 / 20 | **0.903** |
| FastSeg (new) | 83.7% | 94.0% | **87.2%** | 19 / 29 | **0.002** |
| delta | −2.4% | −1.1% | +2.6% | | **551× faster** |

**Read the cost column first, because it changes what the rest means.**
`old_seg` falls back to the LLM whenever its deterministic pass finds nothing,
so its 86.1% is a **model-assisted** score. FastSeg is within 2.4 points of it
with **zero model calls**, at 551× the speed — and it additionally produces the
`time` field, which `old_seg` does not do at all.

So FastSeg is **not yet a clear win on boundaries alone**, and that is the
honest state of the promotion question: it trades ~2 points of cut accuracy for
a 551× latency cut, a better tagger, and a field the old stage never had. The
+205-row span headroom in the oracle table above is what would settle it.

### Three limits of that conclusion — recorded so it can be revisited honestly

1. **The corpus is 92% template-generated**, from the very templates FastSeg
   was tuned against. That is a structural bias toward the deterministic side.
2. **One model, one protocol.** llama3.1:8b rewriting a proposal item-by-item.
   This does not show that no model belongs in Segmentation.
3. **The strongest case for a model is a population this dataset cannot
   measure.** A corpus of templates plus hand-written traps cannot contain
   phrasings nobody thought of, and that is exactly where a model would earn
   its keep. `scripts/weekly_review.py` on real usage is the instrument for
   that, and per CLAUDE.md real usage **outranks** every dataset number.

The `v4-full` run was stopped at 458 of 571 rows, so the generated-vs-handwritten
split is **untested** — every hand-written row sorts after the generated ones
and none was reached. If that split is ever wanted, the cache makes it cheap to
finish.

---

## 7 · Layout

```
segmentation/
    ARCHITECTURE.md     this file
    fastseg/            the deterministic half + invariant.py
    llmseg/             the model half + prompts/
    (old_seg/           retired 2026-09-20 -> retired/segmentation-old-seg/)
    datasets/           1,694 rows, train/test split by family
    experiments/        scorer, boards, generator, and every study above
```

**`old_seg` is still the stage the engine runs.** FastSeg and LLMSeg are proven
on their own dataset first, per STAGE ISOLATION mode; promotion is a separate,
deliberate change. Note the coupling honestly: `fastseg` currently *imports*
`old_seg` for `_kind_of` / `_enforce_pinned_kinds`, so the two are not yet
independent.

---

## 7b · What the stage below measures coming out of here (2026-09-09)

`decompose_validate/eval_metrics/end_to_end.py` runs the real FastSeg and then
resolves values, and splits every value error by whose it is. On the 1,924 rows of
that stage's train split:

| | |
|---|---:|
| gold items that reached the next stage | **89.6%** (2292/2557) |
| spurious items produced | **162** |
| items with TWO clock times inside one | **54** |
| items whose action ends in a dangling joiner | **52** |
| value errors downstream caused by different WORDS arriving | **1,445** |
| value errors that were the resolver's own | **0** |

The last two lines are the ones to read together. The downstream stage scores
99.9% when fed gold items and makes **zero** errors of its own on real ones — so
the 51.6% end-to-end row accuracy is this stage's number, not its.

None of this is a new defect: the dangling joiner and the two-clock item are §8.1
and its (a)/(b) split, seen at scale instead of one example. The 265 missing items
and 162 spurious ones are the item-count metric of §6 (FastSeg 77.9% there) from
the receiving end.

---

# 8 · TO FIX — known defects, recorded not repaired

Each is a real case with a real reproduction. They are written down rather than
fixed because the work in flight is elsewhere; this section is the queue.

## 8.1 · RESOLVED 2026-09-09 — a bounded enumeration of times must SPLIT

> **Done.** Phase 3 (`_expand_enumerations`) implements it and the five gold rows
> were corrected in the same change; the trap was renamed from
> `two-times-one-activity`, whose NAME was the mistaken premise, to
> `time-enumeration`. It scores 66.7% now (0.0% before) — the remaining row fails
> on the action wording, not the cut. **The record below is kept as written**,
> because it called the fix, the decoy risk and the board's dip in advance and that
> is worth being able to check.

### The original entry (Gil, 2026-09-08)

**The gold is wrong, and so is the code.**

```
'walk the dog at 9 and 2:30'                                -> gold 1, should be 2
'take the tablets at noon and at six'                       -> gold 1, should be 2
'guitar practice at 11 and 4 tomorrow'                      -> gold 1, should be 2
'gym session on tuesday and thursday this week'             -> gold 1, should be 2
'can you add the stand up meeting on monday and wednesday'  -> gold 1, should be 2
```

All five carry the trap `two-times-one-activity`, which is itself the mistaken
premise — **they are one activity happening SEVERAL TIMES, which is several
events.** Gil: *"the segmentation is supposed to split 'walk the dog at 9 and
2:30' into two events of walk the dog."*

**The rule that separates it from recurrence:**

> A **bounded enumeration** of times is SEVERAL items.
> An **unbounded `every X`** is ONE item with a recurrence.

```
"walk the dog at 9 and 2:30"              TWO events  — two instances
"gym on tuesday and thursday this week"   TWO events  — bounded by "this week"
"gym every tuesday and thursday"          ONE event, recurring
```

Recurrence is a FEATURE of an item, not more segmentation — and it is
`decompose_validate`'s to fill, not this stage's.

**It is implementable without endangering the must-not-split decoys**, because
the trailing conjunct's TYPE separates them, and `find_time_refs` already
identifies the type:

| | trailing conjunct is | verdict |
|---|---|---|
| `walk the dog at 9 and 2:30` | only a TIME | split |
| `meeting with Sam and Alex at 8` | a NAME | keep |
| `buy milk and eggs` | an OBJECT | keep |

Today the verbless-conjunct tier keeps all three whole via "the right side has
no content of its own". That guard is right for the last two and wrong for the
first.

**Expect the board to DROP when the gold is fixed and before the rule lands** —
those five rows currently pass and will start failing. That is the gold getting
more correct ahead of the code, not a regression.

**Fallback if this is missed:** Gil, 2026-09-08 — if segmentation fails to split
a multi-DAY enumeration, `decompose_validate` should read it as a recurrence
rather than lose the second day. A degraded answer, but not a lost one.

### Live evidence, measured end to end (2026-09-09)

`"walk the dog at 9 and 2:30"` produces this from THIS stage:

    [('walk the dog and', 'today at 9 2:30', 'task')]
       ^^^^^^^^^^^^^^^^^^         ^^^^^^^^^^
       the joiner leaked          TWO clocks, one item

and the engine then commits `create_todo 'walk the dog'` **plus**
`create_event 'Untitled Event'` at 14:30 — neither of the two events the sentence
names.

**Isolate it and the blame is unambiguous.** The single case is flawless, so
nothing downstream is at fault:

| said | items | committed |
|---|---|---|
| `walk the dog at 9` | `[('walk the dog', 'today at 9', 'task')]` | event, 9–10 AM ✓ |
| `walk the dog at 2:30` | `[('walk the dog', 'today at 2:30', 'task')]` | event, 2:30–3:30 PM ✓ |
| `walk the dog` | `[('walk the dog', 'today', 'task')]` | todo ✓ |
| **`walk the dog at 9 and walk the dog at 2:30`** | two items | **two correct events** ✓ |
| **`walk the dog at 9 and 2:30`** | **one malformed item** | **todo + `'Untitled Event'`** ✗ |

The fourth row is the one that settles it: repeat the verb and the machinery
handles it perfectly. So this is not a hard problem downstream — it is the CUT
declining to split, and once one item carries two clocks no later stage can
recover, because one item is all the words it has.

### TWO defects here, and they are independently fixable

**(a) The joiner leaks into the action.** `'walk the dog and'` is wrong on any
reading — "and" belongs to neither the action nor the time. This is a bug even if
the keep-decision stands, and it is the smaller of the two.

**(b) The keep-decision itself.** §2 Phase 1 lists this sentence as a deliberate
KEEP ("nothing is left on the right"), and that is the rule §8.1 says is wrong: a
bounded enumeration of times must SPLIT. Note the tension is real rather than an
oversight — the same rule correctly keeps `take the tablets at noon and at six`
whole, so the fix has to distinguish an enumeration of times for ONE action from
a decoy, not simply drop the condition.

## 8.2 · The month can be severed from its ordinal

Recorded rather than fixed, because the current job is wiring the engine
together, not improving FastSeg (Gil, 2026-09-08). Each is a real case with a
real reproduction.

### The month can be severed from its ordinal

**Input**

```
add gym on tuesday at 6am and add yoga on tuesday at 7pm
and add my conference on the 20th of November at 9am
```

**What Segmentation returns for the third item**

```
text = 'add my conference of November'      <- the month is in the ACTION
time = 'on the 20th at 9am'                 <- and missing from the TIME
```

**What went wrong.** `_TIME_PATTERNS` knows `November 20` but not
`the 20th of November`, so the bare-ordinal pattern claims `the 20th` and
`of November` is left behind in the action. No token is lost — `spoken()`
returns `add my conference of November on the 20th at 9am` — but the month has
moved *before* the ordinal, and the title now reads "conference of November".

**Consequence.** The event books in the CURRENT month.
`tests/integration/test_date_sanity_fixes.py::
test_a_relative_date_repeated_for_two_events_does_not_swallow_a_third` fails
because of this — **it is a NEW red introduced by the wiring**, not one of the
three pre-existing failures, and it should be counted as such.

**The fix, when we get to it**, is a pattern, not a downstream repair: capture
`the 20th of November` as one span. That stays inside the capture contract —
it adds no information and resolves nothing. A downstream fix cannot help here,
because by then the month is already part of the title.

> **Distinguish this from the case that is NOT a gap.** "the 20th" with no month
> at all is correctly captured as `on the 20th` and correctly resolved
> downstream to the next future 20th. Segmentation captures words; deciding
> WHICH 20th is `decompose_validate`'s job and it already works.

## 8.3 · The date FLOOR is injected into `time` as a WORD (found 2026-09-08)

`fastseg.py`'s floor block writes the literal string `"today"` into an item's
`time` when the item names a clock but no day:

```python
if not any(_slot(r) == "day" for r in mine):
    time_str = f"today {time_str}".strip()      # fastseg.py:352
```

**This resolves, and segmentation's contract is CAPTURE, DO NOT RESOLVE.** The
floor is a value-level default, and `decompose_validate` owns it —
`checks.date_floor` applies it there, from the anchor, without putting a word in
the item that nobody said.

### Why it is worth fixing rather than living with

It makes a FLOORED day indistinguishable from a SPOKEN one for every consumer
downstream, and two separate workarounds already exist for that:

1. `Item.spoken()` filters the injected `"today"` back out, and says so:
   *"pasting that in would put a word in the title that nobody uttered."*
2. `validate._resolve_onto_intent` now strips it again at this stage's boundary,
   because a carried day could not tell it had permission to fill a gap.

**The live failure it caused**, from the audit corpus:

    "set a meeting tomorrow at 1 pm, another one at 4 pm and then pizza
     at 6:30 pm tomorrow"

Item 2 arrives as `time="today at 4 pm"`. The day was never spoken — the
transcript contains no `"today"` at all — but it LOOKS spoken, so the leading
`"tomorrow"` cannot carry forward and the event books on the wrong day. Both
workarounds above exist solely to undo this one injection.

### What it costs to fix

The reason it was added is in the code comment: FastSeg emitted the bare form
while the tuned LLMSeg prompt taught the floored one, so **the two halves
disagreed on every clock-only item and the accept step paid for it each time**.
Note that LLMSeg is OFF by default (§3), so today the injection serves an inert
component while an active stage pays for it.

So the fix is not a one-line deletion:

- **Segmentation's own gold encodes the floored form.** `experiments/generate.py`
  inserts `("day", "today")`, and `experiments/check_prompt.py` asserts
  *"FLOOR requires 'today {t}'"*. Removing the injection means regenerating the
  dataset and re-reading the boards — the `time_default_ok` metric in
  `compare_boards.py` is scoring exactly this.
- **LLMSeg's prompt teaches the floored form.** If both halves must agree, the
  normalisation belongs at LLMSeg's ACCEPT step (strip a floored `"today"` from
  what the model returns) rather than in FastSeg's output, so the bare form is
  what both emit.
- **`Item.spoken()`'s filter can then go**, along with this stage's boundary
  strip — which is the test that the fix actually landed: two workarounds
  disappear.

Not urgent — the boundary strip contains it — but it is a contract violation, and
it has already cost one live bug and two workarounds.
