# Label

**The only place a row is written, and where it gets its label — in the same
step.** An event gets one of thirteen categories and its colour; a task gets a
set of tags. Never a later step: a row written now and categorised later is a
row that can exist uncategorised, and that window is where per-category settings
(reminder leads, notification rules, filters) silently stop applying.

    label.py       reads the labels back onto the item, for the reply and trace
    model.py       the learned labellers, and how they ship
    train.py       fit them, gate them, promote them
    feedback.py    the user's own corrections — the only labels worth learning
    datasets/      generated FROM the label, so nothing is circular
    experiments/   the boards, and RESULTS.md — every number this file quotes

## Two problems, not one

| | shape | palette |
|---|---|---|
| event **category** | SINGLE label | 13, `actions/calendar/categories.py::DEFAULTS` |
| task **tags** | MULTI label | 4 keyword-backed, `actions/todo/tagging.py` |

They are kept apart everywhere — separate datasets, separate splits, separate
models, separate metrics — because a task can be Groceries *and* Errands at once
and answering with the strongest tag alone would silently drop the other.

## The rules keep their rows. The model fills the blanks.

Measured on held-out vocabulary: the task rules score **macro precision 91.7%,
recall 34.9%**; the model **63.9% / 39.8%**. A keyword match is nearly always
right when it fires and rarely fires. So:

    RULES first        keeps their precision on every row they answer
    MODEL second       only where the rules fell through to the catch-all
    CATCH-ALL last     `Personal` / no tag, when neither is confident

Replacing the rules with the model would trade 91.7% precision for 63.9% on rows
that were already right. No accuracy number justifies that, and this is a
selective classifier — the same shape FastRule's front door uses.

**Abstention is an answer.** `predict` returns None below `MIN_CONFIDENCE`
rather than guessing. An event labelled `Travel` at 0.21 because that was the
argmax is worse than the catch-all it replaced.

## Two tiers, because a user is not the author

    BASE      identical for everyone · fitted from the COMMITTED datasets ·
              contains nobody's data · built automatically on first use
    PERSONAL  base + THIS user's corrections · upweighted · gated · local only

`load()` prefers personal and falls back to base, so it degrades in the right
order: your model, then everyone's, then the rules. Before the base tier existed
a new user silently got the keyword rules for ever — the model was a property of
whoever had run the trainer, not of the product.

## The one rule that makes the retraining safe

**Silence is not agreement.** A label the system assigned and the user never
touched is NOT evidence they agreed — most people never look at a category.
Training on it teaches the model its own output, which is the exact circularity
this whole workstream exists to escape (`fastrule/datasets/generate.py` computes
its category gold by calling `classify()`, which is why a decision tree once
scored *exactly* 100% and meant nothing).

Feed model output back as gold and the trap returns INVISIBLY: the labels agree
with the predictions by construction, so every board looks fine while the model
amplifies its own bias.

So exactly two things are gold, and both require a human act — a **correction**
(the best signal there is: a labelled error) and an **explicit pick**. An
untouched label is recorded and never trained on. `feedback.py` enforces it;
`tests/unit/test_label_learning.py` pins it.

## The promotion gate

A retrain does not ship because it is newer. Two sets, two jobs:

| set | role |
|---|---|
| **generic held-out** (frozen, shipped) | regression floor — must not fall more than `GENERIC_TOLERANCE` |
| **personal held-out** (this user's) | the promotion criterion — must improve or hold |

Neither alone is safe: gating only on generic rejects the personalisation that
is the whole point, and gating only on personal lets the model forget everything
it is not corrected on.

**The personal split is by TIME, not random.** Corrections arrive in bursts — a
user fixes five grocery items in one sitting — so a random split puts
near-duplicates on both sides and every retrain scores as a win. Holding out the
most RECENT slice also asks the deployment question: will this help tomorrow?
Below 60 gold rows it is cross-validated instead (25% of 25 is 6 rows, and a
6-row test set is a coin toss); below 10 it cannot judge at all.

**The incumbent is re-scored on today's sets**, never compared against the number
stored when it was fitted — the personal set grows with every correction, so a
stored figure was computed on different rows and comparing them is two unrelated
numbers wearing a comparison's clothes.

## Personal data

`~/.assistant_tools/models/` and `~/.assistant_tools/label_feedback.jsonl`, both
env-overridable (`MACALENDAR_MODELS`, `MACALENDAR_LABEL_FEEDBACK`) so tests and
boards never touch the real ones. Neither is ever committed. The BASE model in
`label/models/` is the exception and is safe precisely because `train_base`
never reads `feedback.gold()` — pinned by a test.

## The numbers

`experiments/RESULTS.md` is the record. Headlines as of 2026-09-10:

- **novel vocabulary** (subjects never seen in training): event category
  **49.1%** vs the rules' 33.0%; task tags **46.8%** exact-set vs 38.3%.
- **real usage** (the live DB): task tags **95.7%** exact-set vs the rules'
  88.6%, macro F1 41.1 → 49.6. The event real-usage column is **not usable
  gold** — 4 of its 14 rows are test traffic and dog-walking is labelled three
  different ways; RESULTS.md §Board 3 says why.
- **persona spread** (six synthetic speakers): rules 28.5 pt, model 10.4 pt. The
  model is roughly three times more even-handed across dialects.
- **scaling was monotonic**: ~11 → ~33 → ~57 training subjects per class took
  logistic regression 20.8% → 36.6% → 49.1% while the rules drifted 38.6% →
  33.0%. Nothing about the models changed across those three runs.

## Two invariants the category layer owns

Adjacent events never share a colour, and a colour the user picked is never
overridden. Both were broken on 2026-09-08 and fixed on 2026-09-10: the voice
path was passing the UI accent as if it were a choice, so `pick_color` never ran
and 11 of 54 live events came out the same amber across four categories.
`tests/unit/test_categories.py` pins both, plus that every instance of a series
carries the series' category.
