# Segment tuning — the run log

One entry per cycle. Each states the hypothesis BEFORE the run, then actual vs.
expected, then what it means. A score is a pointer, not the point.

**Every number here names three things: the DATASET, the METRIC, and what it
MEANS.** "55.9%" is not a result; "exact-row 33.1% → 43.3% on the segment-tuning
train half (1,040 rows) — it now gets action, time and tag all three right on
4 rows in 10 instead of 3" is.

## The corpus these numbers are computed over

`assistant/engine/segmentation/datasets/*.jsonl` — **1,694 rows**, split BY FAMILY (a family never
straddles), ~60/40 train/test.

| | rows | train | note |
|---|---|---|---|
| `nosplit_traps.jsonl` | 65 | 37 | hand-written, 11 must-NOT-split traps |
| `split_traps.jsonl` | 75 | 43 | hand-written, must-split shapes |
| `generated.jsonl` | 1,554 | — | 259 template families, gold by construction |

Ask-count spread `{1: 978, 2: 604, 3: 110, 4: 2}`. The **test half is not scored
except at a milestone**, reports aggregates only, and never spawns a hypothesis.

---

## Cycle 1 — 2026-09-08 · the corpus's first contact with the code

**Hypothesis.** Building gold from the templates' *structure* (slot names, not
surface regex) would disagree with FastSeg wherever FastSeg was wrong, and the
disagreements would be findable. Predicted change: none — this cycle was meant
to produce a baseline, not move a number.

**What actually happened: the generator found four bugs, three of them in the
code rather than in the gold.** That was not the predicted outcome and is the
main result of the cycle.

### The four

1. **The invariant existed as three drifted copies.** The runtime guard in
   `llmseg.accept` would reject a model answer that defaulted an untimed item
   to `"today"` — which is what SPEC tells it to do. A correct answer was
   being thrown away for being correct. Now one `invariant.py`, imported by
   the guard, the scorer and the generator.
2. **`find_time_refs` asserted longest-match in a docstring, not in code.**
   The pattern list is grouped by KIND, so bare `today` outranked `a week from
   today`; "plan lunch a week from today" yielded `today` and stranded "a week
   from" in the action. Matches are now collected and taken longest-first, so
   the ordering of `_TIME_PATTERNS` cannot silently decide the answer.
3. **The time dropped its preposition.** SPEC captures AS SPOKEN — `on the
   15th`, `for christmas day` — but only some patterns spelt the preposition
   out. It cost twice: missing from the time AND stranded in the action
   ("schedule flight to Chicago for"). One absorb step fixed both.
4. **Two labelling rules were genuinely undecided, and the two hand-written
   files had been built to OPPOSITE conventions.** Settled in SPEC:
   - **The date floor** — the day defaults to `today`, the clock never does.
     FastSeg emitted `at 8` while the tuned LLMSeg prompt taught `today at 8`,
     so the deterministic and model halves disagreed on *every* clock-only
     item and the accept step paid for it on each.
   - **Edge distribution is directional** — leading times scope forward per
     slot class; trailing times reach back only to an item with no time at all.
     Per-class in both directions gave "do i have anything this weekend and
     book the haircut at 3:45" the gold `this weekend at 3:45` for the
     question.

### FastSeg alone — segment-tuning TRAIN half, 1,040 rows

| metric | before | after | |
|---|---|---|---|
| exact-row (action+time+tag) | 33.1% | **43.3%** | +10.2 |
| exact-set (actions only) | 51.5% | **55.9%** | +4.4 |
| time on a SPOKEN time | 49.1% | **66.1%** | +17.0 |
| NO-LOSS violations | 304 items / 275 rows | **152 / 145** | −50% |
| right item count (the CUT) | 78.6% | 78.6% | unchanged |
| tag accuracy | 83.7% | 83.7% | unchanged |
| latency | — | **~3 ms/row** | no model |

**What it means.** The component now keeps the words it was given and puts the
time in the right place far more often — but it cuts in exactly the same places
it did before, because nothing in this cycle touched the splitter. The two
unchanged lines are the honest ones: **the cut and the tagger are now the
ceiling**, and every point of exact-row above ~55% has to come from them.

### Where it is weak, read off board F

| trap | exact-row | reading |
|---|---|---|
| `lead_time` | 0.0% | "remind me an hour before X" — treated as a time, not a modifier |
| `time_list_vs_range` | 0.0% | "at 9 and 2:30" vs "from 9 to 2:30" |
| `joiner` | 17.9% | verbless conjuncts: "gym at 7, tomorrow meeting at 10" |
| `three_ask` | 2.4% | three-item commands |
| `attendee` | 83.3% | name coordination is solid |
| `np_decoy` | 69.4% | the must-not-split decoys mostly hold |

**Under-split 189 rows vs over-split 34** — the designed bias is intact
(precision 97.2% / recall 86.2%). Under-splitting is the cheap failure: the
deep track gets two more chances at it, whereas an over-split makes garbage
immediately.

### Next cycle's hypothesis

Fix the **verbless-conjunct cut** ("gym session at 7, tomorrow meeting at 10"
comes back as one piece). Expect: right-item-count 78.6% → ~84% and `joiner`
exact-row 17.9% → ~40% on the train half; expect exact-row to follow about
half as far. Expect NO effect on tag accuracy — if tag moves, something
unintended happened and the run should be read again before it is believed.

---

## Cycle 2 — the verbless conjunct · PREDICTED AND CONFIRMED

**Hypothesis** (registered above): right-item-count 78.6% → ~84%, `joiner`
exact-row 17.9% → ~40%, no tag movement.

**Actual — segment-tuning TRAIN half, 1,040 rows:**

| metric | before | after | predicted |
|---|---|---|---|
| right item count (the CUT) | 78.6% | **84.5%** | ~84% ✓ |
| `joiner` trap exact-row | 17.9% | **42.3%** | ~40% ✓ |
| exact-row | 43.3% | **48.4%** | ~46% ✓ |
| item F1 | 91.4% | **94.1%** | — |
| `np_decoy` (must-NOT-split) | 69.4% | **69.4%** | unchanged ✓ |
| tag accuracy | 83.7% | 84.7% | unchanged ✓ |

**The rule.** A clause splitter cannot see "set up physical therapy at 9:15 and
birthday dinner at midnight" — the second conjunct is a bare noun phrase with
no verb. The evidence used instead: **both sides carry their own time
reference, AND the right side has content that is not part of its time.** The
second condition is what protects the decoys — "walk the dog at 9 and 2:30"
has nothing left on the right once its time is removed, so it does not split.

Cost: under-split 189 → 110 rows, over-split 34 → 51. Precision fell 97.2% →
96.2% while recall rose 86.2% → 92.1%. Worth it, but the bias is now less
lopsided than designed and should not be pushed further without cause.

---

## Cycle 3 — the tagger · TWO HYPOTHESES REFUTED, THIRD ONE PAID

Task recall had not moved all session (70.7%; 159 tasks called events). Three
candidate explanations, tested before any was built.

**1 · "A POS/dependency parse will fix it." REFUTED, decisively.**
Every parser variant scored WORSE than the tagger already in place
(`pos_sizing.py`, same 1,383 matched items):

| tagger | accuracy | task→event fixed | new event→task |
|---|---|---|---|
| current `tag()` | **84.7%** | — | — |
| syntactic (root POS) | 65.0% | +116 | +359 |
| lexical (verb lists) | 80.1% | −7 | +27 |
| lexical → syntactic | 68.5% | +72 | +267 |
| clock-time control | 59.3% | +102 | +424 |

Why: calendar commands are VERB-rooted imperatives — "add vet appointment to
my calendar" has root `add`/VERB, so "VERB → task" calls an event a task. Of
the 439 items no verb list decides, **349 are events**. The root POS is
anti-correlated with the answer. **This killed a planned spaCy rewrite of
FastSeg**, which is the cycle's most valuable output.

**2 · "The destination distributes like an edge time." REFUTED.**
118 of the 159 errors have no list marker in the item because the split
stripped it ("remind me to X and to Y" → item 2 is a bare "to Y"), so the
theory was that `remind me to` / `on my list` should scope every item without
its own. Simulated both readings:

| variant | fixes | breaks | net |
|---|---|---|---|
| blanket command-level override | 46 | 31 | **+15** |
| scoped (only items with no local verb) | 11 | 34 | **−23** |

Predicted ~+150. The scoped version is *worse* because the items with no local
verb evidence are overwhelmingly events, so they inherit "task" and break.

**3 · "Use the lexicon only where the current tagger says `event`." PAID.**

| tagger | accuracy | task recall | event recall |
|---|---|---|---|
| baseline | 84.7% | 70.7% | 94.2% |
| lexicon when it knows, else current | 82.4% | 78.5% | 85.6% |
| **lexicon only where current says event** | **87.5%** | **87.1%** | 87.8% |

Asymmetric on purpose: the current tagger's `task` verdicts are already good
(89.3% precision), so only its `event` verdicts are second-guessed. Net +2.8pp
accuracy, +16.4pp task recall.

**Not yet banked.** The verb lists were written by reading TRAIN failures, so
this is a train-derived hypothesis and only counts once it survives the sealed
half. It is also a *lexicon*, which is the kind of thing that overfits
quietly — the test-half number is the one to believe.

---

## FLAGGED FROM DOWNSTREAM — FastRule's board, 2026-09-10

**Not measured here, and not fixed here.** Segmentation is FROZEN (Gil,
2026-09-09), so this is a note left for whoever unfreezes it, filed under the
rule that produced it (Gil, 2026-09-10):

> *"If it receives bad input then the output should be the same — the question
> then becomes what stage failed and where, and to flag in the relevant md file
> to go fix there."*

FastRule's stage board (`assistant/engine/fastrule/experiments/stage_board.py`)
audits every item BEFORE converting it, so that it scores its own conversion
rather than the chain's. The rows it refuses to score are attributed here.

**1,200 atomic rows of the FastRule 7,200 TRAIN half. 182 (15.2%) arrived at
FastRule already broken:**

| rows | what the audit saw |
|---:|---|
| **61** | an ATOMIC row split into 2 items |
| **41** | tagged `task`, the gold is an event |
| **31** | tagged `event`, the gold is a task |
| 12 | the action words lost a word (`about`, `with`, `this`) |

**The 72 kind mis-tags are the interesting half**, because they are nearly
symmetric and this stage's own tag accuracy reads 89.7% train / 90.2% sealed —
so these are not a surprise so much as the same number seen from downstream,
where it costs an object. Worked examples:

    "note to self, pay the electricity bill"     tagged event, gold task
    "i need to talk to Charlie on next tuesday"  tagged task,  gold event
    "scrap the back up the laptop task"          tagged event, gold task
    "rename mail the package to change the air"  tagged event, gold task

Three of those four contain an explicit task word (`note to self`, `task`, and a
to-do title) and were still tagged `event`.

**The 61 over-splits are of an atomic row**, and they line up with the
`over-split 46` line in the §0 table rather than contradicting it — different
corpus, same defect. The shape is a trailing conjunct that is not a second ask:

    "extend open house by an hour and let Avery know"
    "extend staff meeting by an hour and let Jordan know"
    "call Charlie and Dana at the end of the month"

The first two are one edit plus a courtesy clause; the third is one call with two
people. All three become two items.

**Why this is worth having written down even while frozen:** FastRule now takes
segmentation's `tag` as the kind rather than re-deriving it, deliberately — the
upstream decided it on more evidence. That makes these 72 rows unrecoverable
downstream by design, where previously a re-derivation might accidentally have
corrected some of them. The trade is right (re-deciding cost more than it saved),
but it means the tag's accuracy is now load-bearing in a way it was not before.


---

## 2026-09-20 — implementation fixes after the audit: gold debt first, then the cut

Gil, after the segmentation audit: *"work on implementation fixes, can
reiterate as long as improving… careful that code doesn't get overall
convoluted."* Structure untouched (the five phases, the one-way vetoes, the
parse-based cut). Every change below was measured ALONE on this board (train
half, 1,051 rows) before the next was applied, with FastRule's product-shape
board as the guard for the shared `coordination.py` and `asks.py`.

### The board, start to end of day

| metric | start | after the gold relabel | after the code fixes |
|---|---|---|---|
| exact-row (action+time+tag) | 84.1% (884) | 87.8% (923) | **89.2% (937)** |
| exact-set (actions) | 90.3% | 90.3% | **90.8%** |
| right item count — the cut | 97.6% | 97.6% | **98.1%** |
| over-split · under-split | 3 · 22 | 3 · 22 | **1 · 19** |
| tag accuracy | 94.5% | 97.2% | **98.0%** |
| events read as tasks · tasks read as events | 69 · 13 | 23 · 19 | 8 · ~24 |
| adversarial phrasing (`adversarial_tag.py`) | 28/31 | 28/31 | 28/31 |
| FastRule product-shape board | — | — | byte-identical throughout |

### The gold relabels (data, no code)

- **Q26 was never applied here.** 112 gold-`task` items carried a stated
  clock or a range — "remind me to take out the trash" at 14:00, "file the
  taxes every monday at midnight", "block off time to print the boarding
  pass from noon to 1" — exactly the rows the 2026-09-18 ruling turned into
  events, which `fastseg.tag` had followed since. FastRule's set was
  relabelled the day it was ruled; this one was not, so every tag number
  printed since measured the ruling. `generate.q26_tag` now applies it at
  render time, and the committed files were relabelled by the same function:
  75 items, 53 train / 24 test, the test half transformed without being
  read. **In place, not regenerated**: regeneration reverts the hand-applied
  Q14 correction on five `c_threeask_ttt_2` rows (the template bank is
  FastRule's; filed). exact-row +3.7 pt, tag +2.7 pt, the cut unmoved.
- **A calendar destination outranks the slot's surface.** "remove
  '{quoted_item}' from my calendar" was task because the quoted slot said so.
  Generator rule + 1 train item. exact-row +0.1.

### The code fixes, in order, each with its own board run

| # | where | what was wrong | board |
|---|---|---|---|
| 1 | `intent/asks.py` | the tag-question pattern read any leading "do" as a question, so "do the laundry" failed the ask gate and a three-ask comma list could never be cut | under 22→21, count 97.6→97.7 |
| 2 | `coordination` fallback | a verb governed by a command verb ("add SCHEDULE a haircut") and a preposition's objectless object ("to my LIST") counted as clause points; the joiner could not be seen across the second ask's own date ("and ON FRIDAY book the valuation") | under 21→20 |
| 3 | `coordination` walk | "sticky NOTES" read as the verb "note" by lemma alone: a modified noun is a thing | over 3→2 (one three-piece accident became a two-piece under-split; that row's gold is the Q14 conflict below) |
| 2b | `coordination` fallback | a joiner, then a fronted date, then a verb is a hard boundary — the family test refused "book the car wash, on wednesday add the client lunch" because both verbs are calendar | under 21→20, count 97.9 |
| 4 | `coordination` walk | the walk's own partial object test knew no preposition; it asks `_carries_an_object` now ("pack FOR the trip") and the second copy is gone | under 20→19, count 98.0 |
| 5 | `coordination` walk | the "buried in the first clause" rescue fired when only a fronted date sat upstream ("the 30th, wash and fold the laundry") — the `front,`-vs-`front` gap the invariance board keeps apart on purpose | no train row; pinned test + invariance board |
| 6 | `fastseg.tag` | `_STATED_CLOCK` knew no range and no spoken hour after "at"; `_TIME_BLOCKING` vetoed a stated clock | exact-row 88.2→89.1, tag 97.2→97.9, over 2→1 |
| 8 | `coordination` tail gate | "and let Avery know" is a courtesy tail; a lead time marked "ahead"/"prior" with a number past ten ("ping me thirty minutes ahead") is still a lead time | FastRule stage board (chain input, 1,200 rows): atomic rows split in two 80→76, sound input 88.0→88.3%; all 15 courtesy rows leave FastSeg as one item |
| 9 | `fastseg/kind.py` | the live tagger imported its first reading from the retired `old_seg`; moved verbatim, one copy, the retired module imports it back | byte-identical |

### Filed, not fixed

- **Gold conflict on a shared verb.** Four hand-written trap families
  (`leading-edge-two`, `as-well-as-plain`, `three-ask-and-chain`,
  `list-of-things-source`) expect "tomorrow book the physio at 8 and the
  team sync at 11" split with the verb COPIED into item 2; the generated
  gold ("set up physical therapy at 9:15 and birthday dinner at midnight" →
  "birthday dinner") does not copy, and Q14-reversed says a shared verb over
  a noun list is one item. 8 train items. Needs a ruling, not code.
- **"schedule" inside a to-do title is a calendar signal** to the fallback's
  family test, so "…, then add SCHEDULE a haircut to my list" is still
  refused (2 rows, `c_joiner_commathen_et_1`).
- **"forget X, i'd rather Y"** (5 rows): "forget" is in no verb inventory,
  and "don't forget to X" makes it a risky one to add.
- **Chore verbs the tagger does not know**: "do the laundry", "put out the
  bins", "rinse and stack" read as events without a clock (~5 rows).
- **`c_threeask_ttt_2` drifts on regeneration** — the Q14 correction lives
  only in the jsonl; the template bank is FastRule's.
- **`is_interrogative_create`** is still borrowed from `old_seg` by
  `decompose_validate/object_rules.py`; and `old_seg` itself is retired in
  word but not yet moved to `retired/` with its tag.

### The sealed half, read once at this milestone — aggregates only (660 rows)

| metric | 2026-09-16 (map) | 2026-09-20 |
|---|---|---|
| exact-set | 85.6% | **87.3%** (576/660) |
| exact-row | 78.2% | **79.7%** (526/660) |
| right item count — the cut | 92.1% | **93.5%** (617/660) |
| over-split · under-split | 22 · 34 | **16 · 27** |
| time on a spoken time | 96.0% | 95.9% (n=679) |
| tag accuracy | 92.6% | **93.6%** (934/998) |
| NO-INVENTION | 0 | 0 |

Read as: the cut fixes generalise (over-split fell on both halves, under-split
fell on both), and the tag gap between halves — 98.0% train against 93.6%
sealed — is the honest size of the tagger's vocabulary fit, the same shape
the adversarial check reports at 28/31. The sealed half's own gold was
relabelled by the same Q26 rule (24 items), never read.

### The guards

- Full unit suite: 2,084 passed, 2 skipped, 1 xfailed.
- FastRule product-shape board (train, 3,200 atomic rows): byte-identical
  to the start of the day on every rate.
- Position-invariance board (`scripts/invariance_board.py`, 1,548 groups):
  segmentation 13.8% → **13.2%** position-dependent, decompose_validate
  6.3% → 5.7%, fastrule 4.8% → 4.3%, front door 49.4% unchanged (it does
  not call this stage); `front,` correctness 55.0% → 55.5%; the multi-ask
  arm's under-split fell at every position (end 50→47, front 81→79,
  `front,` 68→66) with over-split unchanged.


---

## 2026-09-20, second pass — the queue Gil approved ("ok do those")

Five items, in the order proposed; each measured alone on this board, with
FastRule's product-shape board as the guard for anything in the shared
modules. Train half, 1,051 rows.

| metric | start of pass | end of pass |
|---|---|---|
| exact-row | 89.2% (937) | **90.1% (947)** |
| exact-set | 90.8% | **91.1%** |
| right item count — the cut | 98.1% | **98.4%** |
| over-split · under-split | 1 · 19 | **1 · 16** |
| tag accuracy | 98.0% | **98.8%** |
| NO-LOSS violations (a scorer line) | 34 items | **19 items** |
| adversarial phrasing | 28/31 | 28/31 |

1. **The tagger's chore vocabulary — and the veto's second word.** The
   real-speech miner (`missing_verbs.py`) surfaced another assistant's
   vocabulary, not chores, so the evidence stayed the train misses. Three
   things: "do", the wet-work verbs (rinse, stack, scrub, wipe, mop, sweep,
   iron, hoover, proofread, chase) and the phrasals "put out"/"put away"
   joined the veto lexicon; "gotta"/"got" joined the preamble ("like i gotta
   restock the pantry" kept "gotta" as its head, five rows); and the veto's
   two-word head reading was gated — "oil change", "client call",
   "conference call is…" were vetoed to task on their SECOND word. Two wrong
   gates were measured on the way (one word: −24 rows; the parser's verb
   inventory: −16, "put" is not in it; a determiner test: lost "add BUY
   milk", a live test); the one that holds is grammar — the second word
   heads a verb phrase unless a function word follows it. exact-row 89.2 →
   89.8, tag 98.0 → 98.7, confusions 30 → 20.
2. **One definition of content in the scorer.** Its joiner set had drifted
   from `invariant.py`'s again and charged "can you" as lost content. The
   invariant's stop set is now three named parts and the scorer shares the
   disfluencies and openers; prepositions stay content there on purpose.
   NO-LOSS 34 → 19 items, engine untouched.
3. **`old_seg` retired.** `retired/segmentation-old-seg/` with a README, tag
   `segmentation-old-seg`; the interrogative-create reader moved to its one
   caller in `decompose_validate/object_rules.py`; the stage lost its switch;
   the doctor, two experiments and seven tests repointed; the artifact check
   that counts model-calling stages now reads LLMSeg's file and knows its
   `urlopen` socket. Board byte-identical.
4. **FastRule's front door and the courtesy tail.** With the tail intact the
   parser built the right `update_event` target but at confidence 0.66: its
   own splitter cut "let Avery know" into a span it could not route, and an
   unroutable span costs 30%. A courtesy tail now stays in the first span
   (`coordination`'s pattern, so both splitters agree). Deferral reasons
   below-threshold 202 → 187, no-change 69 → 84: the rows now defer for the
   true reason, that "extend by an hour" has no field to carry its
   duration until the store supplies the start. Filed with it: the built
   intent copies the floor date as `new_date`; a lead-time tail ("…, remind
   me a week before") is split off as a junk todo titled "remind before".
5. **The under-split residue, two halves.** (a) A command clause that TRAILS
   its head as an `advcl` ("i need to submit the report, FILE the taxes,
   and print…") passes the same structural tests the leading path applies:
   under-split 19 → 18. (b) Ten errand verbs the tag lexicon knew and the
   routing table did not (family from FastRule's own train gold: back 8/2,
   charge 6/1, feed 8/2, print 6/1, refill 6/3, restock 9/1, return 16/1,
   submit 3/0, vacuum 4/2, walk 6/1; "take" and five with no rows left out):
   under-split 18 → 16, exact-row 90.1%. **Added alone they opened a hole
   in FastRule's router 18 rows wide** — "mark WALK the dog complete" became
   a create, because the to-do's own verb was the ROOT and the real command
   sat first as a noun only the router's last pass reached — which is how a
   defect older than the widening was found: the leading imperative is now
   the router's first pass, and FastRule's harm fell 159 → 106 (its
   ledger, cycle 25).

### Still open, filed

The shared-verb gold conflict (4 hand-written families vs the generated
gold and Q14, 8 items); "schedule" inside a to-do title reading as a
calendar signal to the fallback's family test (2 rows); "forget X, i'd
rather Y" (5 rows — "forget" is in no inventory and "don't forget to"
makes it a risky one); `c_threeask_ttt_2`'s regeneration drift; "put X and
Y on my list" losing its destination on the first item (5 rows, needs the
tag to see the sentence); and the two extend/lead-time findings above,
which are FastRule's.

### The sealed half, read once more at the end of the second pass (660 rows)

| metric | morning read | end of day |
|---|---|---|
| exact-row | 79.7% (526/660) | **80.5%** (531/660) |
| exact-set | 87.3% | 87.3% |
| right item count — the cut | 93.5% | 93.5% |
| over-split · under-split | 16 · 27 | 16 · 27 |
| tag accuracy | 93.6% | **94.2%** (940/998) |
| NO-INVENTION | 0 | 0 |

The tag work generalised (+0.6 on the sealed half against +0.8 on train);
the cut fixes of this pass touched shapes the sealed half does not hold.
Two reads of the sealed half today, both aggregates only.


## 2026-09-20 (evening) — the checkpoint's queue: the kind tagger and the hard seams

The whole-chain checkpoint on dev-100 (`dataset/RESULTS.md`, run 22) charged
segmentation with 16 of its 26 misses: 12 the KIND decision, 4 the CUT. Both
are implementation fixes inside the stage, each boarded alone on the train
half (1,051 rows).

| change | exact-row | the cut | under-split | tag misses | no-loss items |
|---|---|---|---|---|---|
| baseline (morning) | 90.1% | 98.4% | 16 | 11 | 19 |
| **kind**: `_LIST_DEST` learns a NEW list / a list OF things and "groceries list"; a wake word or a yes/no question before a looking verb is still a review; "i want <thing>" is an errand | 90.1% | 98.4% | 16 | 11 | 19 — **byte-identical** |
| **cut**: `_hard_seams` before the parse — ". Also,", "; then", a dash-and, ", (and) then"; a bare "and then" stays with the clause tier | **90.3%** | **98.6%** | **14** | 11 | **17** |

The kind change is silent on this board because none of its shapes are in
the stage's corpus: no "new list of", no wake word, no "i want <thing>".
Its positive surface is the checkpoint's own rows, all of which now read
right on a probe (`kind_of`: "Make a new list of dog breeds" → task, "PDA
do i have any appointments set for tomorrow?" → review, "is today st.
patricks day" → review, "I want sweet potato pie…" → task; "i want to meet
sam on friday" and "i want a meeting with sam" stay events) and the tests in
`test_engine_segment.py`. The negative surface is the 1,051 rows: nothing
moved.

The cut change is the class the invariance board already separated as
"front," vs "front": the front door has treated these seams as a compound
since its first board, so the rows defer to the deep track, where the cutter
then left them whole and `decompose_validate` multiplied the one item into
junk ('take out the trash. also', 'remind put milk on my shopping list').
Two train rows recovered; over-split unchanged; precision unchanged. A bare
" and then " was tried as a hard seam and dropped: it cut "meet sam and then
we'll see" into an ask and a remark and the board gained nothing from it.

Both measured next on dev-100 (`dataset/RESULTS.md`).


## Cycle 35 — the phrase table learns the spoken clock forms (2026-09-22)

Real usage found four clock shapes the table did not know, so the clock stayed
in the ACTION and the resolvers never saw it: "for 1 p.m." (no `for` entry),
"for 830" / "at 1040" / "at 910am" (compact, no separator), and every dotted
meridiem at the end of a sentence — the `\b` after "p.m." needs a word
character next, so "at 11 a.m." matched only "at 11" and stranded "a.m." in
the action, which is where the live titles 'meeting a.m' and 'meeting p.m.
p.m. as well' came from. Five entries changed or added; every meridiem in the
table now ends in `(?!\w)`, and the `at` entry takes the period separator so
"at 14.30" is one candidate rather than a tie it used to win by swallowing a
space.

Train board (1,051 rows): **byte-identical** before and after — exact-set
91.2%, exact-row 90.3%, time assignment 98.3% — because the corpus holds none
of these forms (0 fires over 1,592 segmentation rows, 4,800 FastRule train
rows and the 2,699 mineable real utterances). The movement is on the
real-usage board only: generic-title right/acceptable 52.4 → 66.7% (11 → 14
of 21 rows), corrected `start_time` 56.2 → 62.5% (n=16)
(`DOCUMENTATION/experiments/real_usage/RESULTS.md`, run 4).

## A clock said with a NUMBER WORD (2026-09-25 00:0x, engine-next)

Found on a real command (2026-09-24 23:10, "Tomorrow at one such for …"): the
time finder had no entry for a bare "at <number word>", for a number word with
a meridiem ("at seven pm"), and lost the minutes of "ten past nine in the
morning" to the longer "nine in the morning". Corpus sweep (45,620 distinct
transcripts): 177 of 1,267 "at <number word>" phrases read as no clock or the
wrong one; the negatives that must stay words ("a scan at twelve weeks", "at one
point", "at one with") are guarded by a closed follow-list.

**Board (FastSeg alone, TRAIN, 1,051 rows):** exact-row 949 → 950, exact-set
959 → 960, spoken-time assignment 97.9% → 98.0% (n=1,147); item count 1036 →
1035 and over-split 1 → 2 rows. Read row by row (all 1,711 rows, both halves:
9 changed): 7 better — the clock left the title for the time; 1 now splits two
appointments correctly but gives the second "today" instead of "on monday";
1 regresses ("lunch tomorrow with morgan and casey at one" cuts after morgan).
**Both of the last two are the digit form's existing behaviour** — "…casey at
1" and "physio at 9 and the optician at 4" do exactly the same today — so the
word form now behaves like the digit form, and the two defects are filed as
their own cycles (lowercase-name coordination after "with"; a leading day not
distributed to the second timed ask). Also found and filed: a meridiem ENDING
the command ("dinner at 8 p.m.") leaves the clock in the action, digits too.

## A meridiem ENDING the command stays in the title (2026-09-25)

"dinner at 8 p.m." → action 'dinner at 8 p.m', time 'today at 8 p.m.': the cut
trims the command's final "." off the last piece, so the clock (ending at
"p.m.") ran one character past the piece and was filed as an EDGE reference —
the right time, never stripped from the title. Digits and words alike; the
real-usage titles 'meeting a.m' (cycle 35) were the same family. `assign_times`
now lets a reference own its piece when only punctuation runs past the end.

Segmentation corpus (1,711 rows, both halves): 0 rows changed — it has no
command ending in a meridiem, which is why no board saw this. Across the 45,620
distinct corpus transcripts: 461 carry a dotted meridiem, 136 change, and all
136 are the clock leaving the title. Found beside it and filed: a TRAILING clock
reaches a time-less first piece ("buy milk and book the dentist at 3pm" gives
the milk 3pm, which then reads as an event under Q25) — the existing
distribution rule, the same for "3pm" without dots.
