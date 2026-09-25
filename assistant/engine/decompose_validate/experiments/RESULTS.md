# decompose_validate experiments: the run log

One entry per board. Every number carries the dataset, the split, n as
scored/total, the metric and the incumbent's reading on the same items.

---

## 2026-09-24: KIND TWO-STAGE. Does the label classifiers' reading help decide event vs to-do?

`kind_two_stage.py`. **This is a measurement only. No engine code, config or
model was changed, and whether to ship is Gil's call.**

**The idea (Gil, 2026-09-24).** *"the classifier of the category tag together
with like whatever other information we have would be enough to decide if it's
an event or a to-do... It would be like a two-stage model... just to route
whether it's an event or to-do task."*

- **STAGE 1:** the label classifiers read one ITEM's words and give probabilities.
  That means the event-category n-gram model (13 classes), the to-do-tag n-gram
  model (4, one-vs-rest), the keyword rules (`categories.classify` and
  `tagging.infer_tag`) as one-hots, and optionally the Q46 embedding heads
  (nomic-embed-text through ollama).
- **STAGE 2:** logistic regression or `HistGradientBoosting` decides KIND from
  those probabilities plus SHAPE flags. The flags are: a stated clock (fastseg
  `_STATED_CLOCK`), a day word, a part of the day, recurrence, a range, a
  person (`_has_person_argument`, `_KIN_RE`), the frames ("remind me to/about",
  a list destination, a calendar destination, scheduling verbs, "note to
  self", "i need to", completion), the occasion noun, the head-verb lexicon and
  the head word, and question form. `engine` is the tagger's own verdict used
  as a feature.
- **The incumbent** is `fastseg.tag(action, time)` on the same item words. On
  Board D it is what the chain committed.

**Engine code:** `f845aec` (the Q47 commit), clean. **Record:**
`runs/kind_two_stage_20260924T1639_embed.json`. It started 2026-09-24 16:28:15
and finished 16:39:35. A second run at the same commit was checked for
identical output (see "Determinism" below).

### Data: items, not commands, each source on its own split

Each item is one ask's own words and its own time phrase, after the
transcript's `strip_spoken_noise`, the same cleanup `fastseg()` applies before
cutting. Without it the `^`-anchored kind regexes invent misses the chain never
has (`dataset/METRICS.md` Level 3b). The gold is event or task.

| source | split | n items | families | kind gold | note |
|---|---|---|---|---|---|
| FastRule 7,200 (atomic `create_event`/`create_todo`) | TRAIN | 2,161 (2,129 in the fit pool) | 146 | 1,551 / 610 | |
| | TEST | 905 → 900 scored | 74 | 588 / 317 | 5 stale-gold rows dropped |
| LLMJudge v2 (`commands_v2`, create asks) | TRAIN | 4,732 (3,300 in the pool) | 85 | 2,940 / 1,792 | 224 conflicts dropped |
| | TEST | 4,704 → 4,547 scored | 94 | 2,968 / 1,736 | 157 conflicts dropped |
| segmentation corpus (gold items) | TRAIN | 1,069 (956 in the pool) | 143 | 652 / 417 | |
| | TEST | 1,397 | 175 | 859 / 538 | |
| real usage (approved + corrected, one kind per command) | TEST only | 41 items / 25 commands | 25 | 33 / 8 | never fitted on |
| Board D one-object CREATE rows (`board_d_c45`, seeded) | TRAIN | 707 | 148 | | FastRule train rows, scored out-of-fold |

**The fit pool.** It is the TRAIN items of all three generated sources,
deduplicated on (words, time). Any item whose words appear in any TEST set is
removed. A segmentation family that is TEST on FastRule's side is TEST here
too, because the segmentation corpus is generated from FastRule's families.
TRAIN numbers are out-of-fold: 5 folds grouped by family, so no row is scored
by a model that saw its family. TEST is scored once, by a model fit on the
whole pool.

**Gold that a ruling contradicts is dropped from both fitting and scoring.**
That is 381 v2 asks, the `ct_dt`/`ct_t` shapes: a to-do with a clock, which
Q25/Q26 make an event. The FastRule residue is 9 TRAIN rows (`c_recur_7`,
`c_recur_12`, `s_ct_task_with_time`, the Q26 relabel's leftovers) and 5 TEST
rows in one family.

**Distinct shapes:** 371 families behind the fit pool. v2's 94 test families
share their seven VOICES with the train half. A voice's frame, such as "make a
note to …", is in both halves, so v2's TEST is a new *grammar* rather than new
*phrasing*.

### Metric

**Kind accuracy** is the share of items whose event/task routing equals the
gold. A `review` or `other` from the tagger stands, since routing it is not
stage 2's question, and counts as wrong. **NET** is items fixed minus items
broken against the incumbent on the same items.

**GATED** means the ruling wins wherever it fires. It is read with the
engine's own regexes:

- Q25/Q26: a stated clock makes an event.
- Q47(B): a person on a stated day makes an event. The reading is faithful:
  outreach verbs behind a frame ("remind me to CALL Jordan") and named to-do
  destinations stay to-dos.

GATED is the headline, because an ungated model that beats the incumbent by
contradicting a ruling is not a candidate.

### The table: kind accuracy, GATED, with NET vs the engine on the same items

| model | FastRule TRAIN (2,129) | FastRule TEST (900) | v2 TRAIN (3,300) | v2 TEST (4,547) | seg TRAIN (956) | seg TEST (1,397) | real TEST (41) |
|---|---|---|---|---|---|---|---|
| **ENGINE `fastseg.tag`** (incumbent) | **98.0%** | **88.4%** | **97.1%** | **95.2%** | **98.6%** | **96.8%** | **95.1%** |
| lr: shape | 96.1% −42 | 94.2% +52 | 99.7% +86 | 99.4% +191 | 96.1% −24 | 94.8% −27 | 97.6% +1 |
| lr: stage1 | 85.0% −278 | 82.1% −57 | 95.0% −71 | 89.8% −244 | 81.5% −164 | 78.0% −263 | 92.7% −1 |
| lr: shape+stage1 | 96.5% −33 | 95.1% +60 | 99.5% +78 | 99.4% +190 | 97.4% −12 | 96.1% −9 | 92.7% −1 |
| lr: engine+shape | 98.3% +5 | 96.2% +70 | 99.7% +85 | 99.5% +195 | 97.2% −14 | 95.0% −25 | 97.6% +1 |
| lr: engine+shape+stage1 | 98.2% +4 | 96.0% +68 | 99.7% +84 | 99.4% +193 | 97.7% −9 | 97.0% +3 | 95.1% 0 |
| lr: engine+shape+embed | 98.3% +6 | 96.0% +68 | 99.6% +82 | 99.4% +191 | 97.6% −10 | 96.9% +1 | 95.1% 0 |
| hgb: shape | 96.0% −43 | 94.8% +57 | 99.3% +73 | 99.2% +181 | 96.0% −25 | 95.4% −19 | 97.6% +1 |
| hgb: stage1 | 93.8% −91 | 92.2% +34 | 99.0% +63 | 97.1% +85 | 91.5% −68 | 88.8% −112 | 92.7% −1 |
| hgb: shape+stage1 | 98.9% +18 | 95.4% +63 | 99.5% +79 | 98.8% +165 | 97.7% −9 | 97.3% +7 | 95.1% 0 |
| **hgb: engine+shape** | 97.2% −17 | **97.8% +84** | 99.4% +75 | 99.2% +183 | 97.4% −12 | 96.6% −3 | 97.6% +1 |
| hgb: engine+shape+stage1 | 98.4% +9 | 94.7% +56 | 99.6% +83 | 99.3% +187 | 98.4% −2 | 97.1% +5 | 95.1% 0 |
| hgb: shape+embed | 99.0% +20 | 97.7% +83 | 99.5% +77 | 99.0% +174 | 97.0% −16 | 97.6% +12 | 95.1% 0 |
| hgb: engine+shape+embed | 98.4% +7 | 97.3% +80 | 99.7% +84 | 98.9% +171 | 98.3% −3 | 98.4% +22 | 95.1% 0 |
| hgb: engine+shape+stage1+embed | 98.5% +11 | 96.7% +74 | 99.8% +89 | 99.4% +192 | 98.2% −4 | 97.7% +13 | 95.1% 0 |

The RAW (ungated) table is in the record. It differs little, because a model
with shape features learns the clock rule on its own.

### Paired, pooled TEST (FastRule + v2 + seg = 6,844 items), gated, McNemar exact

| A → B | A right only | B right only | net | p |
|---|---|---|---|---|
| ENGINE → hgb: engine+shape | 45 | 309 | **+264** (94.6% → 98.5%) | 1e-49 |
| ENGINE → hgb: shape+stage1 | 67 | 302 | +235 | 1e-36 |
| **hgb: shape → hgb: shape+stage1** | 75 | 91 | **+16** | 0.24 |
| **hgb: engine+shape → +stage1** | 68 | 52 | **−16** | 0.17 |
| **lr: shape → lr: shape+stage1** | 22 | 47 | **+25** | 0.004 |
| **lr: engine+shape → +stage1** | 15 | 39 | **+24** | 0.002 |

### Board D: seeded `board_d_c45`, 707 one-object CREATE rows (FastRule TRAIN), `_correct` = action AND title

The chain as committed is 95.3% (674/707). Stage 2 overrides the action's kind
where it disagrees. Predictions are out-of-fold (a row's family is never in its
model's fit).

| model (gated) | changed | fixed | broke | NET |
|---|---|---|---|---|
| one-rule category hint (a keyword-rule answer implies a kind; no model) | 363 had an opinion | 6 | 60 | **−54** |
| lr: stage1 | 111 | 13 | 98 | −85 |
| hgb: stage1 | 39 | 14 | 25 | −11 |
| hgb: shape | 18 | 9 | 9 | 0 |
| hgb: shape+stage1 | 13 | 13 | 0 | +13 |
| hgb: engine+shape | 17 | 15 | 2 | **+13** |
| hgb: engine+shape+stage1 | 15 | 15 | 0 | **+15** |
| lr: engine+shape | 15 | 14 | 1 | **+13** |
| lr: engine+shape+stage1 | 17 | 14 | 3 | **+11** |
| hgb: engine+shape+stage1+embed | 15 | 15 | 0 | +15 |

The category hint is a reconstruction; the original probe's mapping was not
recorded. It reproduces today's result in direction and size: the original
had 316 with an opinion, 8 fixed and 55 broken.

### Rulings battery: 43 sentences from Q25, Q26, Q27, Q47(A/B), Q1 and the 2026-09-04 reminder convention

The battery is in `RULINGS` in the board. Each sentence goes through
`fastseg()` the way the chain would cut it. "call Mom tomorrow" is left out
because Gil put it back to himself.

- **Engine: 43/43.**
- **Every model with shape features: 43/43 gated.** `hgb: engine+shape` and
  `hgb: engine+shape+stage1` get 43/43 even raw. Raw lr and hgb shape-only
  models get 40–42/43.
- **Stage-1-only models violate rulings even gated** (lr 33/43, hgb 40/43).
  They call chores with a part of the day, "buy milk", and "call Mom" events.
  **They are disqualified.**

### What carries the weight

The test is to permute one feature group on the pooled TEST and measure the
accuracy drop:

| model | shape | stage1 | engine |
|---|---|---|---|
| hgb: shape+stage1 (base 97.9%) | −40.3 pt | −3.5 pt | |
| hgb: engine+shape+stage1 (base 98.3%) | −6.8 pt | −3.1 pt | −24.6 pt |
| lr: shape+stage1 (base 97.2%) | −40.5 pt | −1.5 pt | |

The top standardised LR coefficients are: stated clock +4.08, scheduling verb
+1.67, event/appointment word +1.63, head-verb task lexicon −1.42, list
destination −1.24, and length −1.07. The first stage-1 feature is 8th:
event-model `Fitness` +0.86, then `Personal` −0.79 and `Health` +0.65.

### What it means

1. **Stage 1 does not carry the decision.** Alone it is worse than the engine
   on every source, from −57 to −278 rows. It violates the rulings even gated,
   and on Board D it breaks far more than it fixes (−11 to −85). Category
   means "what the thing is about". An event and a to-do can be about the same
   thing ("dentist appointment" / "call the dentist"), so it cannot route.
2. **Stage 1 adds at most about half a point beyond the shape features, and
   inconsistently.**
   - On the pooled TEST (6,844 items) it adds +16 to +25 items (0.2–0.4 pt)
     over shape alone, and between −16 and +24 once the engine's verdict is a
     feature.
   - The LR gain is significant (p = 0.002–0.004).
   - The HGB change is not, and its sign flipped between otherwise identical
     configurations during the session: +14, +9 and −16 across the three
     reruns.
   - Board D: +2 (hgb) and −2 (lr).
   - Real usage: 0 to −2 of 41 (a probe).
   - The embedding heads (Q46) behave the same way. Over the pooled TEST they
     add +50 to a shape-only hgb, but only +9 (hgb) and +20 (lr) once the
     engine's verdict is in. On Board D they add +1 or less.
3. **The big gap is to the TAGGER, and SHAPE closes it, not category.**
   - A learned combiner of the engine's verdict and shape flags beats
     `fastseg.tag` by +264 of 6,844 TEST items (94.6% → 98.5%, p = 1e-49).
   - It beats it by +13 on Board D's 707 rows (95.3% → 97.2%, 15 fixed and
     2 broken).
   - It passes every ruling.
   - The gain is almost all on two sources. **FastRule TEST +84 of 900**: the
     tagger is 98.0% on the train half its rules were written against, and
     88.4% on the test half. **v2 +183 of 4,547**: v2's voices use frames the
     tagger lacks, such as "make a note to …", "need to …" with no "i", and
     "i must to book a meeting". These are voice-shared, so the v2 gain is
     partly the model learning the generator's frames.
   - On segmentation's corpus, which the tagger was tuned on, the learned
     model only ties it (−3 to +22).
4. **The verdict on Gil's question.** Category information, whether n-gram,
   keyword rules or embedding, is **not enough on its own** to route event vs
   to-do. **Beyond the shape features it adds between −0.2 and +0.4 points**
   on 6,844 TEST items and ±2 of 707 Board D rows. That is within the noise
   for boosted trees, and small but real for logistic regression. What does
   move the number is a learned stage 2 over SHAPE plus the tagger's verdict,
   gated by the rulings: +3.9 pt on TEST and +1.9 pt on Board D. Most of that
   could equally be had as implementation fixes to `kind.py`'s frames, and a
   learned model would add a component with its own drift. **That is a design
   decision for Gil.**

### Findings about the engine and the data, found on the way (TRAIN rows only)

- **A Q47 working-tree regression, already fixed at `f845aec`.** Before that
  commit, `_meets_a_person` read the head of "remind me to call Jordan the
  30th" as `remind`. That let the outreach check pass, so reminders to call or
  email a named person on a day became events: 45 FastRule TRAIN errors
  (`c_attendee_8/9`, `s_ct_call_someone_date`). The commit's
  `_OUTREACH_AFTER_FRAME` closes it: the engine's FastRule TRAIN reading went
  from 96.6% to 98.0%.
- **Still open: spaCy calls a garbled lowercase word a PROPN, and the person
  promotion then fires on an explicit to-do destination.** "add swe epthe
  balcony to my tasks" + "on monday" becomes an event: 3 v2 TRAIN and 15 v2
  TEST items. A named list destination probably ought to veto the person
  promotion.
- **v2's gold contradicts Q26 on 381 create asks** (`ct_dt`, `ct_t`: a to-do
  with a clock). The generator needs a by-rule relabel, as FastRule's
  `c_recur_7` got, or v2 will keep charging the engine for obeying Gil.
  FastRule still carries 9 TRAIN and 5 TEST rows of the same kind.
- **Tagger frame gaps on v2 TRAIN** (the incumbent's misses): "make a note to
  …" (to-do, read as event), "need to <verb> …" without "i", and "i must to
  book a meeting" (event, read as to-do).
- **Ops note:** `label.embed.vectors()` returned None on 14 of about 25
  512-text batches with no Board D running. A direct call to `/api/embed` returned
  every vector each time, so the failure is inside the door (`hold()` wait
  plus its timeout), not in ollama. The board retries. A live categoriser
  would silently fall back to n-grams.

### Determinism

The board fits deterministic models: `random_state` is fixed and the folds are
grouped `GroupKFold`. **Two `--embed` runs at `f845aec` produced identical
output**, started at 16:28:15 and 16:39:55. The records are
`runs/kind_two_stage_20260924T1639_embed.json` and the one from the second
run. Three earlier runs from this session are superseded and not banked: two
before the transcript cleanup was applied, and one on the pre-`f845aec`
working tree.

---

## 2026-09-24 (evening): the ruler moved, then the router shipped

Gil answered two questions on the same evening, both recorded in DEVQA Q47:

- *"Call mum is an event at a default time like 9, same for similar
  events"*. An encounter with a person is an event, day or no day. This is
  `assistant/intent/encounter.py`, commit 6621452.
- *"basic rules, otherwise model"* for the event-or-to-do router.

The two changes below were made in that order, each with its own before and
after.

### 1 · Gold relabelled BY RULE in the generators (an instrument change, not an engine change)

| dataset | ruling | rows moved | split | how |
|---|---|---|---|---|
| FastRule 7,200 | Q26 (a clock or a range) | 42 hand-relabelled earlier, now reproduced by the generator; plus 7 train and 5 test that the hand rule missed ("at 9 in the morning", bare ranges) | train / test | `generate.py` `RULED_FAMILIES` |
| FastRule 7,200 | Q26, the compounds ("walk the dog at 9 and 2:30", "remind me to X at 5 and then …") | 72 train | train | same |
| FastRule 7,200 | Q47 (calling a named person) | 92 train | train | same |
| LLMJudge v2 commands | Q26 (`ct_dt`) | 364 commands, 224 train / 140 test | both | `generate_v2.py` `RULED_SHAPES` |
| LLMJudge v2 cases | follows its commands | 805 of 11,187 cases | both | `generate_v2.rule_cases` |

**Verification.** Each regenerated file was row-diffed against the committed
one:

- **FastRule:** 218 rows differ, all in the 15 declared families. No id or
  split moved. The 42 older relabels gain only `ruled` and `category`.
- **v2 commands:** exactly the 364 `ct_dt` commands differ. The text is
  byte-identical.
- **v2 cases:** 805 cases differ, all on ruled commands. Ids are unchanged.
- **Gates:** `verify_v2` passes; `test_llmjudge_dataset_v2`,
  `test_rule_parser` and `test_artifact_claims` are green.
- **Rules check:** after the relabel, no atomic `create_todo` in either
  FastRule split names a clock or an encounter by the engine's own readers.

**The ruler moving, read on unchanged engine outputs:**

| board | split · n | metric | old gold | new gold |
|---|---|---|---|---|
| FastRule product-shape (`fastrule_shape`), HEAD 9aaf038 | TRAIN · 3,200 atomic (2,467 committed) | correct-on-handled | 94.0% | **96.5%** |
| | | harm (weighted wrong commits) | 166 (149) | **103 (86)** |
| | TEST · 1,472 atomic (1,011 committed) | correct-on-handled | 80.7% | 80.8% |
| | | harm | 201 (195) | 200 (194) |
| Board D, seeded checkpoint `board_d_q47b` (f5da878, before the encounter rule) | TRAIN · 1,200 | correct (action and title), both loop arms | 92.3% | 91.8% |

The Board D dip is 13 rows that are now right and 19 that are now wrong. The
wrong ones are the call families: `f5da878` still made calls into to-dos, so
the new gold charges it for the old behaviour. The engine at HEAD carries the
encounter rule, and the whole-chain run below reads it.

**Not relabelled, reported instead:**

- **Segmentation's corpus has 24 Q47 contradictions**: `c_attendee_8`,
  `c_joiner_commathen_tt_1` and `c_npdecoy_call_two_task` rows tagged task.
  Its generator no longer reproduces the committed file (35 rows of
  `c_mixedmode_1` differ on a clean regeneration). A relabel there would ship
  that drift too, so it is left to segmentation's owner. The router board
  drops these 24 from fitting and scoring and says so.
- **LLMJudge v1 `judge_cases.jsonl`** is built from FastRule rows using
  `hash()`, which varies with `PYTHONHASHSEED`, so it cannot be regenerated
  byte-stably. It still carries the pre-relabel gold.

### 2 · "Basic rules, otherwise model": `decompose_validate/kind_router.py`

**Where.** The router is the first step of `decompose_validate.run`. The kind
is final there: `decompose` branches on it and FastRule narrows the create
action by it. The front door is not touched, because it commits only on a
confident rule parse, which is a rule firing.

**"No rule fired"** is the tagger's own code path:

- `fastseg.tag_path` now names the reader that decided. This is a pure
  refactor: `tag()` is identical to HEAD on all 18,820 distinct
  (words, time) pairs in the three corpora.
- `path == "default"` means `_kind_of` fell through to its catch-all `event`
  and nothing moved it.
- On that path the rulings' regexes are checked as well: stated clock,
  encounter, to-do destination, remind-to.

**The model** is logistic regression over the words' shape plus the tagger's
verdict. No category features are used; they added nothing in the first
entry. Model selection used TRAIN only, out-of-fold, on the 633 reached TRAIN
items:

| candidate | reached-item accuracy |
|---|---|
| **lr, fit on reached items** | **98.6%** |
| lr, fit on all | 98.4% |
| hgb, fit on all | 97.3% |
| hgb, fit on reached items | 95.9% |
| the tagger | 87.8% |

The artefact is `models/kind_router.joblib`: 7 KB, sklearn, lazily loaded, no
model server.

**Board** (`kind_router_board.py`, 2026-09-24 17:55, record
`runs/kind_router_20260924T1755.json`). Kind accuracy, router against the
tagger on the same item words. TRAIN is out-of-fold. Gold that a ruling
contradicts is dropped (seg: 6 train, 18 test).

| source | split | n | reach the model | tagger | router | fixed / broke | on reached items |
|---|---|---|---|---|---|---|---|
| FastRule | TRAIN | 2,138 | 218 (10.2%) | 98.3% | **98.9%** | 13 / 0 | 94.0% → 100% |
| FastRule | TEST | 905 | 182 (20.1%) | 88.5% | **95.6%** | 74 / 10 | 49.5% → 84.6% |
| v2 | TRAIN | 3,496 | 330 (9.4%) | 97.4% | **99.0%** | 57 / 2 | 82.7% → 99.4% |
| v2 | TEST | 4,704 | 394 (8.4%) | 95.5% | **99.2%** | 172 / 0 | 56.3% → 100% |
| seg | TRAIN | 950 | 85 (8.9%) | 98.6% | 98.6% | 1 / 1 | 91.8% → 91.8% |
| seg | TEST | 1,379 | 164 (11.9%) | 96.9% | **97.2%** | 12 / 8 | 88.4% → 90.9% |
| real usage | TEST (a probe) | 41 | 13 (31.7%) | 95.1% | 95.1% | 0 / 0 | — |

- **Rulings battery:** 53 sentences, the first entry's 43 with "call Mom"
  now an event, plus 10 call and written-message sentences. Both the tagger
  and the router get 53/53; 2 of them reached the model.
- **Unit suite:** 2,420 passed, 2 skipped, 1 xfailed. That includes 17 new
  tests in `tests/unit/test_engine_kind_router.py`.

**Caveats:**

- v2's TEST gain is mostly the frames its voices share across halves ("make a
  note to …", "need to …" with no "i").
- FastRule TEST, with families unseen in training, is the honest
  generalisation read: +64 of 905.
- One firm path is weak and stays rule-decided by design: `dated_anchor` is
  37.5% right on 24 TRAIN items.

**Whole-chain gates.** Router off against on at one working tree (HEAD
9aaf038 plus this change), switched per process by `MACALENDAR_KIND_ROUTER=0|1`,
one model job at a time. Checkpoints were scratched.

| board | split · n | metric | router OFF | router ON | net |
|---|---|---|---|---|---|
| Board D v2, seeded (`-n 1200 --split train`) | TRAIN · 1,200 | correct (action and title), loop off | 93.2% (1,118) | **93.8% (1,126)** | 8 fixed, 0 broken (22 rows changed) |
| | | correct, loop on | 93.2% | **93.8%** | 8 fixed, 0 broken |
| | | latency, loop-off arm, p50 / p95 | 0.03 s / 5.48 s | 0.03 s / 5.49 s | — |
| real usage (`scripts.real_usage_board`, seed 17) | all 76 reviewed commands | corrected reachable-fields | 25.0% (n=16) | 25.0% | 0 created objects differ on 76 commands |
| | | approved unchanged | 64.7% (n=17) | 64.7% | |
| | | rejected changed | 88.1% (n=42) | 88.1% | |

**The Board D fixes:**

- 2 are `s_ct_note_to_self` ("note to self, book a flight").
- 6 are `s_dt_scrap_task` ("scrap the X task"). The item went from a
  catch-all event to a to-do, so the converter reached the delete. Some of
  those titles are only partly right ("scrap the book"). `_correct`'s
  content-word overlap accepts them, and that is a scorer property, not a
  win to over-read.

**Real usage** is identical to the committed 11:43 reading, with 47 fast and
27 deep rows. None of Gil's reviewed commands reaches the router with an
answer different from the tagger's.

Records:

- Board D: `llmjudge/experiments/runs/board_d_train_1200_20260924T1848.json`
  (router off) and `…T1940.json` (router on).
- Real usage: `DOCUMENTATION/experiments/real_usage/RESULTS.md`, the router-on
  arm; the off arm is identical.

**What each arm ran, and the attribution.**

- **Board D:** both arms started from the 9aaf038 working tree (17:59 and
  18:49). Two engine commits landed during the router-on arm:
  - 28cc8bc, at 19:06: model_protocol yields to live traffic;
  - 1b1d6cb, at 19:13: Q48, commit the ready objects first.

  A running process had already imported that code, and Board D calls
  `parse` and `judge` directly, not `run`, which is where Q48 lives.

  **All 22 changed rows are explained by a router move.** Re-segmenting each
  row, every one has an item that reached the model and changed kind. So the
  +8 belongs to the router.
- **Real usage:** both arms ran after 1b1d6cb, at 19:40 and 19:47, so the two
  arms are at one commit.

## The rule layer ISOLATED — rules alone, words only, model alone, and both (2026-09-24 23:19)

Gil: *"when testing perhaps should isolate the rule based on/off just to see the
effect"*. `kind_router_board.py` now scores four arms on the same item words
(TRAIN out-of-fold, TEST read once), with the rulings battery beside them.
Record: `runs/kind_router_20260924T2319.json` (working tree at 6633372).

| source · split (n) | rules alone | words only | model alone | rules, otherwise model (shipped) |
|---|---|---|---|---|
| FastRule · TRAIN (2,152) | 98.9% | 96.8% | 98.5% | 98.9% |
| FastRule · TEST (905) | 88.5% | 94.7% | 97.0% | 96.8% |
| v2 · TRAIN (3,496) | 98.3% | 99.8% | 99.8% | 99.0% |
| v2 · TEST (4,704) | 98.0% | 99.5% | 99.9% | 99.1% |
| segmentation · TRAIN (956) | 98.6% | 94.9% | 96.8% | 98.6% |
| segmentation · TEST (1,397) | 96.9% | 94.6% | 95.8% | 97.2% |
| real usage · TEST (54) | 96.3% | 96.3% | 96.3% | 96.3% |
| rulings battery (53) | 53/53 | 52/53 | 53/53 | 53/53 |

"Words only" drops every rule, even as an input (no tagger verdict features);
"model alone" is the same family fitted on every item but still reads the
tagger's verdict as three features. What it MEANS: the rules are worth the most
on the hand-built segmentation corpus (+2 to +4 pt over words only) and on
the rulings (the one words-only miss is Q27, "add book a flight to my todo list
tonight"); the model is worth the most on the generated FastRule TEST half,
whose templates the rules never saw (88.5% → 96.8%). The shipped combination is
the only arm within 0.8 pt of the best on every set that also breaks no ruling.
The model alone edging it on the two GENERATED sets is not a reason to drop
the rules: it loses 1.4 pt on the hand-built set and the rules are what make
the rulings a guarantee rather than a statistic. No change shipped.
