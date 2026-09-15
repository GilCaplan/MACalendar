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
