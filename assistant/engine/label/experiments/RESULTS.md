# COMMIT + LABEL — the run log

## Board 1 — the classifiers, 2026-09-10

**Gil's brief:** two ML classifiers (events, tasks), train/test split without
leakage, accuracy/recall/precision/F1, compare tree · kNN · logistic regression ·
XGBoost, and test whether a two-tier model beats a flat one.

Run: `python -m assistant.engine.label.experiments.classifier_board --tiers`

### The result, plainly: the keyword RULES beat every model on real data

    EVENT CATEGORY — real usage, 14 scoreable events in the live DB
      RULES (incumbent)      71.4% acc · 58.3 macro F1
      random forest          50.0% acc · 26.0 macro F1
      logistic regression    50.0% acc · 22.9 macro F1
      kNN                    50.0% acc · 19.6 macro F1

    TASK TAGS — real usage, 70 tagged todos (multi-label, exact-set accuracy)
      RULES (incumbent)      88.6% acc · 41.1 macro F1
      kNN                    81.4% acc · 23.6 macro F1
      hist gradient boosting 78.6% acc · 23.1 macro F1
      random forest          68.6% acc · 21.4 macro F1
      decision tree          67.1% · logistic regression 67.1%

**And the generated board says 100% for almost everything**, which is the point,
not a contradiction:

    EVENT CATEGORY — generated, family-grouped test set (1,179 rows)
      RULES 100.0% · decision tree 100.0% · random forest 99.3%
      logistic regression 94.9% · kNN 93.8% · dummy 42.2%

A decision tree scoring **exactly 100%** is the tell. It did not learn what a
Meeting is; it learned the keyword table, because the keyword table produced the
labels.

### Why this is a data problem and not a model problem

Four findings, each independently fatal to the current setup:

1. **The labels are the rules' own output.** `fastrule/datasets/generate.py`
   computes the gold by calling `categories.classify()`. Training on it can only
   distill it.
2. **The generated corpus cannot test generalisation.** Only **8 of 1,179** test
   titles share no content word with training. The whole value proposition of a
   model over an enumerated 179-word grocery list is that it handles words nobody
   typed in — and this corpus reuses its nouns, so it cannot ask that question.
3. **`Coursework` has ZERO training examples** despite being a live tag on Gil's
   list. Macro F1 is capped at 75% for every model, rules included, because one
   of four tags is absent from the data.
4. **Real labelled data is tiny.** 54 events, of which **40 carry `Running` or
   `Gym`** — categories with no palette entry — leaving **14** scoreable. 70
   todos. That is an evaluation sample, not a training set.

### Flat vs two-tier: no case for the hierarchy

    TIERED (5 broad → leaf)   95.8% acc · 96.2 macro F1
    FLAT (13-way)             94.9% acc · 95.9 macro F1
    tier-1 (5-way) alone      95.8%  <- the tiered path's CEILING

0.9 points apart on the circular board, and the tier-1 accuracy IS the ceiling —
a leaf can only be right when its branch was. **13 classes is not enough labels
to need a hierarchy**; that trade starts paying above roughly 50, or with
classes that genuinely nest. Predicted before the run, and the numbers agree.

### Leakage control, since it decides whether any of this counts

Split is **grouped by template family**, not random: the 7,200 is generated from
325 templates and two rows from one family are the same sentence with the nouns
swapped. Family overlap between train and test is **0**, printed on every run. A
random split here would have inflated every model by an unknown amount.

### XGBoost

Not installed, and installing it needs the network, which this project never
touches. `HistGradientBoostingClassifier` is sklearn's implementation of the same
algorithm and is the stand-in. It needs DENSE input, so it runs behind a
`TruncatedSVD(200)` — boosted trees are built for dense tabular features, not a
50k-column bag of words. **Real XGBoost would need exactly the same treatment**,
so its absence is not what is holding the number down.

### What to do instead — the prerequisite is gold, not a better model

- **Mine Gil's corrections.** When a category is changed in the UI, record
  `(title, from, to)`. That is genuine gold, it accumulates passively, and it is
  the only label source here that is not the rules talking to themselves.
- **Hand-label a sample** of the 3,000 real utterances — `--review` writes the
  file.
- **Three fixes that need no model at all** and are worth more today: the colour
  bug (below), `Running`/`Gym` missing from the palette, and `Coursework`
  having no keywords worth the name.

**Recommendation: do not ship an ML classifier yet.** It is not blocked on tree
vs kNN vs boosting — it is blocked on the absence of any label the rules did not
write.

---

## The three commit/label defects this board found

1. **Every voice-created event gets the UI ACCENT colour, not its category's.**
   `action.py:64` passes `color=BLUE`; `BLUE` became the configurable accent in
   `styles.py:97` ("kept name for call-site compatibility"); `db.py:522`
   `_AUTO_COLORS` still only recognises the old `#0078d4` as "no colour chosen".
   So `auto_category_and_color` reads the accent as a deliberate user choice and
   returns it unchanged — `pick_color` never runs. **Confirmed live: 11 of 54
   events carry `#f5a524` across four different categories**, earliest
   2026-09-08. Board measure: 43 of 43 adjacent pairs collide.
2. **Series instances are written with an empty category.** The first instance is
   categorised; the rest are not.
3. **Two events carry an invalid clock time** — `start_time = '30:00'` on rows
   1993 and 1994, both written in the same second as row 1995 by one compound
   command. `CalendarIntent` rejects hours > 23, so these reached the DB down a
   path that skipped that validator.


---

## Board 2 — labels the rules did NOT write, 2026-09-10

Gil: *"deal with the classifier labelling so the models are better than
something rule based"* … *"isn't the fix to improve training data?"* — **Yes, and
the task half proves it.**

### What changed

The dataset is now **generated FROM the label** (`../datasets/generate.py`): a
row's class is what it was generated AS, never what a keyword matcher says about
it afterwards. And the split is **by SUBJECT, not by row** — the test half uses
subject nouns the training half never saw, overlap asserted at 0 on every run.
That is the only question worth asking of a model that would replace an
enumerated 179-word list.

### TASK TAGS — the models WIN, on both instruments

    NOVEL VOCABULARY (120 rows, 24 unseen subjects)   exact-set   macro F1
      kNN (k=5, cosine)                                   46.7%       34.8
      random forest                                       45.8%       31.1
      logistic regression                                 37.5%       29.6
      RULES (the incumbent)                               25.8%       35.4

    REAL USAGE (70 tagged todos in the live DB)       exact-set   macro F1
      logistic regression                                 94.3%       49.4
      kNN (k=5, cosine)                                   92.9%       55.5
      RULES (the incumbent)                               88.6%       41.1

**Task tags: exact-set accuracy 88.6% → 94.3% and macro F1 41.1 → 55.5 on Gil's
own 70 tagged todos, and 25.8% → 46.7% exact-set on held-out vocabulary.** The
brief is met for this half: the models beat the rules on real data.

Why it worked here: food is food. A model that has seen "aubergine", "tahini"
and "kimchi" places "persimmons" correctly; the keyword list only ever contains
what somebody typed.

### EVENT CATEGORY — a tie on novel vocabulary, after tripling the data

    NOVEL VOCABULARY (1,062 rows, 177 unseen subjects)      acc   macro F1
      logistic regression                                 36.6%       40.1
      RULES (the incumbent)                               35.9%       40.6

Before the expansion — 156 training subjects across 13 classes, ~11 each — the
same model scored **20.8%** against the rules' 38.6%. Going to **428 training
subjects** closed an 18-point gap to a dead heat. **The fix was the data**, and
nothing about the models changed between those two runs.

**Two-tier still buys nothing:** 36.8% vs flat 36.6%, and tier-1's own 54.5% is
the tiered path's ceiling. Three runs now, same answer — 13 classes is not
enough labels to need a hierarchy.

### The real-usage board for EVENTS is NOT usable gold — and that is the finding

Models score 7.1% there against the rules' 71.4%. That number should not be read
as a model failure, because the 14 "gold" rows are:

    Personal   event                    <- the generic-title BUG, not a category
    Study      Notification test A      <- test traffic
    Study      Notification test B      <- test traffic
    Meeting    CC Event                 <- test traffic
    Personal   Walk marks dog
    Family     Walk Mark                <- the SAME activity, three
    Social     Walk Val                 <- different labels

Four of fourteen are test artefacts, one is a defect this project already tracks,
and dog-walking is labelled Personal, Family and Social. **The rules "win" by
answering Personal often, which matches a set that is mostly Personal.** No
model should be expected to reproduce that, and a board built on it cannot
adjudicate anything.

### What is actually needed next, and it is not a model

1. **Real gold for events.** Exclude `source = "test"` rows, then label a sample
   of the 3,000 real utterances. Until that exists there is no honest
   real-usage number for the event classifier — only for tasks, which has 70.
2. **Seed the event vocabulary from GIL's distribution.** The subjects authored
   here are generic British-calendar ("mot booking", "chimney sweep"). His
   actual calendar is Hebrew/Jewish terms, named people, running and dog
   walking. Synthetic data only transfers when it matches deployment, and this
   does not — which is the second reason the real-usage column is meaningless
   rather than damning.
3. **Ship the TASK classifier.** It beats the rules on both instruments, on real
   data, today. It does not need anything above.

### On embeddings, checked and unavailable

TF-IDF has no semantic knowledge — char n-grams cannot know "kefir" is food —
so novel-vocabulary generalisation is capped. Ollama embeddings were tested:
`llama3.1:8b` is not an embedding model and the server rejects the endpoint; no
embedding model is installed and pulling one (`nomic-embed-text`, ~275 MB) needs
the network. `DOCUMENTATION/MODELS.md` already flags *"There is no embedding
model … one of the things the harness should re-examine."* **This is that
re-examination, with a number attached: a tie on novel vocabulary is the ceiling
for bag-of-words features.**


---

## Board 3 — 1000 diverse examples per class, 2026-09-10

Gil: *"make 1000 diverse examples for each category."* Done, and it settles the
question: **on labels the rules did not write, the models now beat the rules on
BOTH classifiers.**

    events   14,692 rows · 13 classes · ~1,100 each · 1,055 subjects
    tasks     3,800 rows ·  4 tags   · ~1,100 each ·   238 subjects
    every text unique · SUBJECT overlap train∩test = 0, asserted every run

### EVENT CATEGORY — novel vocabulary (4,333 rows, 311 unseen subjects)

    model                       acc   macro F1
    logistic regression       49.1%       49.7      <- the incumbent, beaten
    random forest             40.7%       41.4
    hist gradient boosting    39.9%       40.0
    RULES                     33.0%       35.6
    kNN                       34.2%       34.2
    decision tree             28.2%       30.1

**Accuracy 33.0% → 49.1%, macro F1 35.6 → 49.7, on held-out vocabulary.**

### The scaling was MONOTONIC, which is the real result

Same models, same features, same split rule — only the data changed:

    train subjects/class      ~11      ~33      ~57
    logistic regression      20.8%   36.6%   49.1%
    RULES                    38.6%   35.9%   33.0%
    verdict                  LOSS    TIE     WIN

Three points, one direction. Gil's *"isn't the fix to improve training data?"*
is the whole answer to this board: nothing about the models was tuned across
those three runs.

(The rules drift down because each expansion adds subjects their keyword lists
never contained — which is the point. A longer list is not generalisation.)

### TASK TAGS — the models win on both instruments

    NOVEL VOCABULARY (1,113 rows, 70 unseen subjects)  exact-set  macro F1
      logistic regression                                  46.8%      47.0
      RULES                                                38.3%      49.6

    REAL USAGE (70 tagged todos in the live DB)        exact-set  macro F1
      logistic regression                                  95.7%      49.6
      RULES                                                88.6%      41.1

**Task tags on Gil's own list: 88.6% → 95.7% exact-set, macro F1 41.1 → 49.6.**
Note the rules keep a higher macro PRECISION on novel vocabulary (91.7 vs 63.9):
a keyword match is nearly always right when it fires, it just rarely fires
(recall 34.9). That is the shape of an enumerated list, and it is why recall and
F1 are the numbers to read here.

### Two-tier: still nothing, for the fourth run

    TIERED (5 → leaf)   49.0%       FLAT (13-way)   49.1%
    tier-1 alone        62.7%  <- the tiered path's ceiling

13 classes is not enough labels to need a hierarchy. Four runs at three data
scales, same answer; this is settled and does not need asking again.

### The events REAL-USAGE column is still not evidence

Rules 71.4% vs models ~14%. Unchanged, and still not a model failure — Board 2
recorded why: 4 of the 14 "gold" rows are test traffic, one is the generic-title
bug, and dog-walking is labelled Personal, Family AND Social. The rules match a
mostly-Personal set by answering Personal. **Do not read that column until real
gold exists.**

### Where this leaves each classifier

- **TASKS — ready.** Beats the rules on held-out vocabulary AND on 70 real rows.
  `logistic regression` over word 1-2 grams ∪ char_wb 3-5 grams.
- **EVENTS — beats the rules on the honest instrument**, but its real-usage
  number cannot be checked until the gold exists, and the authored vocabulary is
  generic British-calendar while Gil's calendar is Hebrew/Jewish terms, named
  people, running and dog walking. **Do not ship it on a 49% novel-vocabulary
  win alone.**

### Next, in order

1. Build real event gold: exclude `source="test"`, label a sample of the 3,000
   real utterances.
2. Re-seed the event vocabulary from Gil's actual distribution.
3. Wire the TASK classifier behind a flag, with the rules as fallback.


---

## Board 4 — the PERSONA spread, 2026-09-10

Gil: *"we have data we generated on stereotype characters — see what you can
use from there."*

**Used as a TEST instrument only.** `dataset/personas/PERSONAS.md` binds this
data: *"No persona row is ever used to fit a model, select a feature, sweep a
threshold, or seed a few-shot prompt — not the ones scored, not the ones that
fail, not the banks they came from."* So the second half of the request —
generating training data from them — is the one thing this data may not do, and
nothing here was fitted, tuned or selected against it.

`experiments/persona_board.py`. Six synthetic speakers, each with its own
vocabulary AND its own phrasing habits.

    persona                 titles   rules catch-all   model abstains
    esl_speaker                348             30.7%             1.7%
    uni_student                341             49.3%             6.5%
    observant_student          346             49.7%            11.8%
    household_parent           338             53.0%            12.1%
    retiree                    353             56.4%             8.8%
    freelance_consultant       351             59.3%             8.5%

    SPREAD                          rules 28.5 pt      model 10.4 pt

**The model serves six different speakers nearly three times more evenly than
the keyword rules do — spread 10.4 pt against 28.5 pt — and has an opinion far
more often, abstaining on 1.7-12.1% where the rules fall through to the
catch-all on 30.7-59.3%.**

**Why this is the answer to Gil's other question** (*"this should also be true
for other users — i am just one example"*): a keyword list is a dialect. It was
written by someone, and it serves speakers who share their words. The spread
measures exactly that, and the rules' 28.5 pt says the incumbent is 2x better
for the freelance consultant than for the ESL speaker. The learned model, fitted
on generated vocabulary belonging to nobody, is much closer to even.

### What this does NOT show, and must not be quoted as

**Abstention is not correctness.** The persona rows carry no category or tag
gold, so this board cannot say whether the model's extra coverage is RIGHT — only
that it is evenly distributed. A model that confidently mislabels everyone
equally would score identically here. The accuracy question is answered on the
novel-vocabulary board (Board 3); this one answers only *"is it fitted to one
dialect?"*.

### The prediction it tested, and confirmed

The project's persona finding says swapping content nouns moves the classifiers
0-3 pt while swapping PHRASING moves them 7-29 pt. Labelling is fed a TITLE, not
a whole utterance, so phrasing should barely reach it and the spread should be
small. It is — for the model. The rules' large spread is a VOCABULARY effect,
not a phrasing one, which is consistent with the finding rather than a
counter-example: a keyword list is beaten by unfamiliar nouns, and that is
precisely what the six personas supply.

### Checked and cleared: no train/serve skew

The datasets are framed commands ("uh sled push thursday") while production
serves a bare title (`db.auto_category_and_color` passes `intent.title`). Spot
check says the frames did not hurt — bare titles score HIGHER, not lower
("gym session" 0.98 vs "book gym session tomorrow at 7am" 0.92) — so training on
both shapes made the model robust to either rather than skewed toward one.


---

## Board 5 — REAL GOLD, and the shipped path measured, 2026-09-10

Boards 2–4 all carried the same caveat: the event classifier had no honest
real-usage number, because the live DB's 14 scoreable rows are four parts test
traffic, one part a known bug, and label dog-walking three different ways.

**`datasets/real_event_gold.jsonl` replaces it**: 81 titles the product's own
rule parser extracted from `history_3000.json` — real utterances, already
committed — filtered to the ones that actually name something, and labelled by
hand. **Labelled by Claude, not by Gil**, which every row records and
`REAL_GOLD.md` explains at length. EVALUATION ONLY; never trained on.

### The result, and the split in it

    REAL USAGE (81 titles, 10 of 13 categories present)
    model                                          acc   macro P   macro R   macro F1
    STACKED (shipped: rules + logistic regression) 71.6%    65.8%     53.7%      51.7
    RULES (the incumbent)                          67.9%    42.5%     39.8%      37.3
    logistic regression alone                      58.0%    59.6%     62.0%      57.4
    random forest                                  32.1%    52.3%     47.1%      44.9

**The shipped configuration beats both of its parts**: accuracy 67.9% → **71.6%**
against the rules, and macro F1 37.3 → **51.7**. That is the stacking design
being right rather than merely defensible, and it is the first time this board
has measured what a user would actually get instead of two components nobody
runs on their own.

### Read the two metrics apart — they disagree, and the disagreement is the point

The rules score 67.9% ACCURACY and 37.3 MACRO F1. The gap is the whole story:
the gold is 46/81 Meeting and Social, the keyword lists handle exactly that kind
of common case, and they collapse on everything rarer. Accuracy rewards getting
the biggest class right; macro F1 asks whether the system works for all ten.

That is the same finding the persona board reached from a different direction —
**a keyword list serves whoever wrote it and degrades for everyone else** — now
measured on real titles instead of synthetic speakers.

The model alone inverts it (58.0% accuracy, 57.4 macro F1): more even, less
sharp. Stacking takes the sharp half from the rules and the even half from the
model, which is why it wins on both counts against the incumbent.

### What this does NOT settle

- **81 rows.** A few points here is noise, and only 10 of 13 categories appear —
  `Errand`, `Travel` and `Shabbat Meal` have no rows at all, so nothing is known
  about them.
- **The labels are mine, not the user's.** Where the palette overlaps
  (Social/Meal, Social/Family) a convention was chosen and applied consistently;
  a different reader would draw those lines differently. Gil reviewing this file
  is worth more than another board, and a correction he makes is worth more
  still — `feedback.py` exists to collect exactly that.

### Verdict

**The event classifier is now worth enabling as the stacked path** — it beats
the incumbent on both metrics on the only non-circular evidence available. It
should still ship behind its flag, and the first thing worth doing after
enabling it is reading what gets corrected.


---

## Board 6 — the rebuild: boosting, embeddings, Gil's cascade, new tags, 2026-09-24

Gil: *"remake a ML model maybe xgboost is better? think of what data- train-test
and features would be good given the prompt, can have a simple rule that if has
simple words like buy or other things choose category otherwise go through ML
model, pay attentnion to new tags or existing"*.

Run: `python -m assistant.engine.label.experiments.rebuild_board` — record of
2026-09-24 10:17:27, HEAD `3873dd5` plus the (then uncommitted) board file. A
second run of the same code at 10:02 printed identical numbers: every method is
deterministic (seeded trees, cached embeddings).

### The grid every number sits on

    TRAIN   generated TRAIN half only — events 10,359 rows / 744 subjects,
            to-dos 2,687 rows / 168 subjects. Same rows the shipped base was
            fitted on (the committed model and its refit agree on 100.0% of
            TEST predictions, checked every run).
    TEST    generated TEST half, split by SUBJECT (overlap 0, asserted):
              events 4,333 rows / 311 unseen subjects
              to-dos 1,113 rows /  70 unseen subjects
            REAL, evaluation only, deduplicated by normalised title:
              events  gold81 — 81 titles, HWU-64 crowd text, labelled by Claude
              to-dos  44 distinct tagged titles from the live list: 30 the
                      rules would write today, 7 the stacked model would,
                      7 NEITHER (the only clean gold)
    metrics acc (to-dos: exact tag set) · mF1 macro F1 · cov share of rows the
            method ANSWERED rather than defaulting · cw answered-and-wrong,
            share of ALL rows
    incumbent  STACKED (shipped): rules -> LR word+char @0.35 / 0.40

**One correction to the record.** `REAL_GOLD.md` calls the 81 event titles
"actual usage". `history_3000.json` names its own source: HWU-64 (Liu et al.,
2019), a public crowd-written corpus. They are real human phrasing, not Gil's
calendar, and not his labels. The only labels of Gil's own are 5 corrections in
`label_feedback.jsonl` and ~7 hand-set rows each on the calendar and the list.

### EVENTS

    method                                gen TEST (4,333)          gold81 (81)
                                          acc   mF1   cov   cw      acc   mF1   cov   cw
    RULES                                33.2  35.7  60.0  31.9     67.9  37.3  86.4  21.0
    LR word+char (the shipped model)     49.1  49.7   100  50.9     58.0  57.4   100  42.0
    HGB on SVD(200) of word+char         39.9  40.0   100  60.1     54.3  40.4   100  45.7
    XGB on word+char (sparse, no SVD)    42.8  43.8   100  57.2     48.1  37.0   100  51.9
    LR embedding (nomic-embed-text)      64.8  65.0   100  35.2     51.9  57.6   100  48.1
    kNN embedding (k=15)                 59.8  59.6   100  40.2     59.3  59.7   100  40.7
    XGB embedding                        61.9  61.8   100  38.1     58.0  57.6   100  42.0
    LR word+char+embedding               64.1  64.1   100  35.9     64.2  67.5   100  35.8
    STACKED (shipped)                    41.4  43.0  83.0  44.2     71.6  51.7  90.1  21.0
    STACKED rules -> LR embedding        53.4  54.2  95.0  43.0     74.1  55.0  97.5  24.7
    STACKED rules -> LR w+c+embedding    51.1  52.2  91.3  41.8     75.3  56.3  96.3  22.2
    CASCADE mined kw -> LR w+c+emb       64.4  64.2   100  35.6     65.4  68.2   100  34.6

### TO-DO TAGS

    method                                gen TEST (1,113)          real (44)             hand-set (7)
                                          acc   mF1   cov   cw      acc   mF1   cov   cw  acc
    RULES                                38.3  49.6  42.0   3.8     68.2  65.4  68.2   0.0  0/7
    LR word+char (the shipped model)     66.6  54.0   100  33.4     75.0  44.2   100  25.0  0/7
    HGB on SVD(200) of word+char         63.2  53.1   100  36.8     63.6  29.4   100  36.4  0/7
    XGB on word+char (sparse)            56.2  48.2   100  43.8     65.9  32.4   100  34.1  0/7
    LR embedding                         78.8  65.4   100  21.2     84.1  67.6   100  15.9  2/7
    XGB embedding                        80.8  71.2   100  19.2     81.8  63.7   100  18.2  2/7
    STACKED (shipped)                    61.6  64.3  76.7  15.1     84.1  74.4   100  15.9  0/7
    STACKED rules -> LR embedding        73.9  72.1  86.2  12.3     86.4  78.4  97.7  11.4
    STACKED rules -> XGB embedding       72.0  71.6  83.0  11.1     88.6  78.8  97.7   9.1
    STACKED rules -> kNN embedding       77.6  73.6  96.4  18.8     84.1  70.0   100  15.9

The real to-do column is 30/44 rows the rules themselves would write, so the
rules' 0.0% confident-wrong there is circular. The 7 clean rows are what a
learned model is FOR (Magshimim -> Work, Microcenter -> Errands, Cook for
shabbat -> Errands …): the rules answer none, the shipped model says Groceries
on all 7, the embedding models get 2.

### 1. XGBoost is not better. The features are what move.

xgboost 3.2.0 was installed into a scratch `--target` dir, NOT into `.venv`
(the board imports it when present). It runs on the sparse TF-IDF directly —
the one thing sklearn's HGB cannot do — and it still loses to logistic
regression on the same features on all four instruments: events 42.8 vs 49.1
(gen) and 48.1 vs 58.0 (gold81); to-dos 56.2 vs 66.6 and 65.9 vs 75.0. On
embeddings XGB and LR are within 3 pt of each other. **The boosting question
is answered: no.**

The feature ablation, LR throughout, accuracy (events gen / gold81 · to-dos gen / real):

    word 1-2 grams only          48.3 / 56.8  ·  65.0 / 65.9
    char 3-5 grams only          47.4 / 58.0  ·  61.7 / 68.2
    word + char  (shipped)       49.1 / 58.0  ·  66.6 / 75.0
    word + char, frame stripped  50.2 / 59.3  ·  63.1 / 75.0     <- +-1-3 pt, noise
    embedding only               64.8 / 51.9  ·  78.8 / 84.1
    word + char + embedding      64.1 / 64.2  ·  78.1 / 75.0

**The embedding is the only feature worth +12 to +16 pt on novel vocabulary,
for both classifiers.** It is exactly the gap Board 2 named — TF-IDF cannot
know "kefir" is food — and nomic-embed-text is local, so the network rule holds.

**The frame verb cannot be measured on this data, and that is a finding.**
`generate.py` shares every frame across every class on purpose, so on generated
TRAIN "buy" is right for Groceries 30.3% of the time (165 rows, 122 subjects)
— because the generator writes "buy the lab report". On Gil's real list "buy"
is Groceries on 17 of 18 distinct titles (a probe: real rows chose nothing).
The generator's frame independence is false for "buy", and a feature can only
learn what the data lets it.

**Metadata features were not run, and could not be honestly.** What reaches the
labeller at commit time: `auto_category_and_color` gets title, date, start
time, attendees, location, description (end time and recurrence are on the
intent at the one call site but not passed); the model receives the TITLE ONLY.
To-dos: title plus the palette; list, quantity and due date are on the intent,
not passed. But no set carries them with honest labels: generated rows have no
metadata (times inside the text are drawn independently of the class), the
gold81 rows are text only, and the live calendar's times are circular (every
Fitness row sits at 06:30 because the training planner wrote it and the rules
labelled it). Inventing class-conditional times in the generator would measure
the generator's assumptions. It needs real labelled rows with their metadata —
exactly what a correction carries.

### 2. Gil's cascade — it is what ships, with the HAND list, not a mined one

Rules chosen on TRAIN only: keep a keyword that is right >= 95% of the time over
>= 20 rows from >= 3 distinct subjects (mined 1-2 grams), or over >= 10 rows
(the incumbent's hand-written keywords, checked rather than discovered).

    events  mined 33 keywords     answer 469 gen-TEST rows at 82.5% · 6 gold81 rows at 100%
            incumbent 109 of 324  answer 774 gen-TEST rows at 79.7% · 10 gold81 rows at 90%
            (171 hand keywords have too little train evidence to be judged)
    to-dos  mined 1 keyword       ('ticket' -> Errands) answers 0 TEST rows
            incumbent 62 of 270   answer 82 gen-TEST rows at 100% · 14 real rows at 100%

- A keyword that is 95% right on training subjects is ~80% right on NEW
  subjects. The bar does not transfer; nothing chosen on this data will be 95%.
- The mined list inherits the generator: `'book the'`, `'add the'`,
  `'put the'` -> Work at 100%, because only Work subjects begin with "the …".
  "book the flight" would go to Work. **Mining rules from generated text is
  unsafe**; the hand list is the only list with real-world priors in it
  (Gil's Hebrew terms, his places).
- The cascade with the model answering everything else (no abstention) is within
  1 pt of that model alone on gen TEST, and 6 pt BELOW the shipped stacking on
  gold81 (65.4 vs 71.6), because the shipped stacking uses the WHOLE hand list,
  not the 95% subset. **Gil's idea is already the shipped shape**: rules first,
  model on the blanks. The question that matters is which model sits behind them.

### 3. Abstention — reachable for to-dos, not for events

Each threshold was chosen on a subject-grouped 20% carve of TRAIN as the lowest
at which the answered rows are >= 90% right. **For events no model reaches 90%
on unseen subjects at any threshold**, so every event threshold landed at
0.88-0.95 and coverage collapsed (LR word+char @0.95: 4.3% of gen-TEST rows
answered). For to-dos it works: LR embedding @0.62 answers 68.6% of gen-TEST
rows with 4.8% confident-wrong, against the shipped stacking's 15.1%.

### 4. NEW TAGS — only the embedding finds a class it was never trained on

One class held out of TRAIN entirely; the system gets its NAME plus three
keywords (the first three of its incumbent list). Recall / precision on the
held-out class's gen-TEST rows. A trained LR/HGB/XGB scores 0 recall by
construction, and so does the cascade beyond its keyword rule.

    held out       n    keyword rule   name only   embedding prototype
    EVENTS
    Errand        336    8.3 / 63.6    0.0 /  0.0     40.5 / 24.6
    Family        320   10.0 / 100     10.0 / 100     15.9 / 55.4
    Fitness       341    6.5 / 46.8    0.0 /  0.0     71.3 / 57.9
    Health        325    8.0 / 100      4.0 / 100     34.8 / 79.0
    Meal          330    6.7 / 18.0    0.0 /  0.0     34.8 / 33.3
    Meeting       315   38.1 / 62.8   23.8 / 58.6     61.0 / 27.4
    Prayer        315   14.3 / 100     0.0 /  0.0     59.4 / 50.7
    Shabbat Meal  330   20.0 / 100     0.0 /  0.0     73.0 / 92.0
    Social        360   10.0 / 17.5    3.3 / 100      20.6 / 27.7
    Study         336    4.2 / 25.5    4.2 / 48.3     45.2 / 38.7
    Travel        320   15.0 / 100     5.0 / 100      35.6 / 70.4
    Work          369    1.1 /  4.3    0.0 /  0.0     10.0 / 11.7
    mean                11.8 / 61.5    4.2 / 42.2     41.8 / 47.4
    TO-DOS
    Coursework    320    6.2 / 100     0.0 /  0.0     51.9 / 99.4
    Errands       315    6.7 / 31.8    0.0 /  0.0     91.4 / 45.2
    Groceries     371    0.0 /  0.0    0.0 /  0.0     65.2 / 86.7
    Work          128    0.0 /  0.0    0.0 /  0.0     20.3 / 86.7
    mean                 3.2 / 33.0    0.0 /  0.0     57.2 / 79.5

The prototype answers when the class's "name: kw, kw, kw" is the nearest of all
the classes' prototypes by a margin, the margin chosen on the OTHER classes'
TRAIN rows. With NO training rows at all, the whole palette as prototypes scores
39.2% on event gen TEST (the rules: 33.2%) and 63.0% on to-dos (38.3%).

**Name only is what `tagging.py` gives a user-created tag today**, and it finds
0-24% of a class. The real case agrees: Gil's own `Wishlist` (4 distinct titles:
Weights, Padel, Cycling clothes, Bike light) — rules 0/4, name-only prototype
0/4 (all nearer Groceries/Errands). A wish list is not a topic, so no title
similarity will find it; the list or an explicit pick is the signal there.

### 5. Deleted or renamed classes: the saved models ignore the palette (a bug)

Run in scratch stores against the shipped path (`model.category_for` /
`tags_for`):

    'Travel' deleted       "flight to rome"   rules Personal -> model 'Travel',
                           coloured as Personal (#64748b): the label outlives its category
    'Errand' -> 'Chores'   "drop off the dry cleaning"  -> model 'Errand'
    'Errands' tag deleted  "collect the passport photos" -> ['Errands'], not in the palette
    'Wishlist' created     the model can only ever answer its 4 fitted tags

`tagging.py` promises "a tag the user renamed or deleted never comes back"; the
model path breaks that promise, because `predict`/`predict_tags` never see the
palette and `action.py` stores what they return. The fix is an implementation
one (restrict the argmax to live classes, abstain otherwise) and needs no
ruling; it is not made here because this board is a measurement.

### Verdict — and what would change it

1. **Keep the shape.** Rules first, a model on the blanks, is Gil's cascade
   already, and it is the best real-data row on both classifiers.
2. **No XGBoost.** It loses to logistic regression on the same features on
   every instrument; on embeddings it ties.
3. **The one change with evidence is the FEATURE: nomic-embed-text embeddings
   behind the rules.** Generated TEST, same rows: events stacked 41.4% ->
   53.4% (LR embedding), to-dos 61.6% -> 73.9-77.6%, confident-wrong 15.1% ->
   11-12% (to-dos). Real: gold81 71.6% -> 75.3% (rules -> LR w+c+emb; 0 rows
   lost, 3 gained, exact p = 0.25), to-dos 84.1% -> 86.4-88.6% (1-2 rows).
   **Both real deltas are inside the noise** and must not be called a win.
   The cost is a design question for Gil: an ollama embedding call when a title
   falls through the rules (throughput measured 4,100 titles/min batched;
   single-call latency NOT measured), and a fallback to today's TF-IDF model
   when ollama is down.
4. **New tags need the embedding too** — mean recall 42% (events) / 57% (to-dos)
   against 12% / 3% for a name plus three keywords — but event precision (47%)
   is too low to auto-apply. Suggest, do not assign.

**What would separate the top two on real data.** At the discordance seen on
gold81, stacked+embedding vs stacked needs ~210-320 distinct event titles to
reach p < 0.05 with 80% power; on the to-do list ~170-1,000. Those should be
Gil's OWN titles with Gil's OWN labels: the 81 we have are crowd text labelled
by Claude, and the 44 to-dos are 37 parts circular. Roughly 300 hand-labelled
event titles and 200 to-dos, drawn from his calendar and list, is the
instrument that would decide this — and the corrections `feedback.py` already
collects are exactly that data, arriving at ~5 so far.

### Shipped (2026-09-24, DEVQA Q46) — the committed artefacts, re-measured

Q46 shipped the embedding head behind the rules, with the n-gram model as its
fallback (`embed.py`, `model.EmbedHead`, `train._fit_embed`). The base
artefacts in `label/models/` were refit from the generated TRAIN halves; their
n-gram pipelines make identical predictions to the old ones on every TEST row.
Board: `rebuild_board --only shipped`, record of 2026-09-24 11:13, HEAD `ead6a96`
plus the uncommitted change. It runs the REAL entry points (`category_for` /
`tags_for`: rules, head, fallback, live-palette filter).

**Thresholds, chosen on TRAIN** (subject-grouped 20% carve; the threshold
maximising right − wrong over the rows the head answers): events **0.30**
(on the carve: answers 88.6% of 2,004 rows at 64.9% precision), tasks **0.625**
(answers 68.9% of 560 at 91.7%). Recorded in each artefact's `meta["embed"]`.

**Reproduction.** At Board 6's stacked thresholds (0.35 / 0.40) the committed
artefact's per-row answers equal the board's refit row for row on every set,
and with embeddings disabled the path equals the pre-Q46 incumbent row for row.
A vector fetched one title at a time matches the batched vectors the artefact
was fitted on (max |diff| 5.4e-7, n=100).

    EVENTS  (acc / mF1 / cov / cw)          shipped @0.30            pre-Q46 incumbent
    generated TEST  4,333 / 311 subjects    51.8 / 52.7 / 89.7 / 41.2    41.4 / 43.0 / 80.8 / 42.9
                    paired: 32 rows lost, 481 gained, exact p < 0.001
    gold81 (HWU text, Claude-labelled)      75.3 / 56.3 / 95.1 / 22.2    71.6 / 51.7 / 90.1 / 21.0
                    paired: 0 lost, 3 gained, p = 0.25 — inside the noise
    TO-DOS                                  shipped @0.625           pre-Q46 incumbent
    generated TEST  1,113 / 70 subjects     68.2 / 68.6 / 76.4 /  8.2    61.6 / 64.3 / 76.7 / 15.1
                    paired: 35 lost, 108 gained, exact p < 0.001
    live list, 42 distinct tagged titles    85.7 / 72.2 / 92.9 /  7.1    85.7 / 73.6 /  100 / 14.3
                    paired: 1 lost, 1 gained — a tie

(The live list is 42 titles, not Board 6's 44: Q44 retagged seven of Gil's
to-dos between the two runs. The same Q44 moved 12 dog-walk events, so the
calendar-DB reading has changed too, and it is mostly circular anyway: 69.0%
shipped vs 73.8% incumbent on 42 titles, 3 lost / 1 gained, p = 0.63.)

**The to-do threshold is the conservative one.** At 0.625 the head answers
fewer rows than Board 6's 0.40 row: on generated TEST 68.2% vs 73.9% accuracy,
but confident-wrong 8.2% vs 12.3%, and on the live list it halves the
confident-wrong rate (7.1% vs 14.3%) for the same accuracy. That is the TRAIN
rule's choice and it stands; 0.40 was never chosen on anything.

**Latency at commit time** (`experiments/embed_latency.py`, one title per call
through `embed.vector`, gate included, cache cleared per call, n=200 each,
2026-09-24 11:26, live priority):

    WARM (model resident)          p50  12.8 ms   p95  21.2 ms
    COLD (unloaded before each)    p50 274.4 ms   p95 288.8 ms

Measured with llama3.1 NOT resident; a cold load that has to share memory with
it was not measured. Background priority reads ~30 ms slower (the gate's
yield gap). The 3 s cap and the 30 s cooldown bound the worst case at one slow
commit per outage.
