# The sequence dataset — "X followed by Y followed by Z"

`sequence.jsonl`: 3,580 generated commands whose parts are joined by
SEQUENCE words, with list controls, decoys and damaged twins, for
segmentation's **relation** board (`../../experiments/relation_board.py`).
The same rows, with every item's resolved values, are
`decompose_validate/datasets/chain/chain.jsonl` (the chain board).

It exists for **DEVQA Q51** (Gil, 2026-09-25): segmentation splits on sequence
words and hands each item its relation to the one before — `Item.relation =
{"to", "kind", "words"}`, kinds `sequence · list · sentence · envelope ·
same_span · adjacent · unknown` — and decompose_validate chains the times.
Gil's follow-up the same day asked for the full *wording* of sequencing and for
misspellings, "because maybe they get fixed, maybe they don't".

## A row

    {"id", "family", "bucket", "split", "text", "skeleton",
     "decoy", "ambiguous", "rollover", "damage", "twin", "joiners",
     "gold": [{"action", "time", "tag", "relation": null | {"to_index", "kind", "joiner"}}]}

`action` / `time` / `tag` follow `../generated.jsonl` and `../../experiments/SPEC.md`:
the time is the words as spoken, day first, with the date floor `today` when no
day applies; a LEADING day scopes over every item, an interior one binds to its
own; a duration ("for 2 hours") and a "right after <named>" anchor stay in the
action; fillers and hedges stay in the action of the item they open; a
lead-time tail ("and remind me 10 minutes before") puts "and remind me" in the
last action and "10 minutes before" in its time. `tag` is what the item's own
words say — a stated clock makes an event (Q26), a person encounter or a role
call is an event (Q47, Q50), an untimed to-do is `task` even when
decompose_validate will chain it.

`relation.kind` is read from the words between the two items, **sequence >
sentence > list** (". Then" is a sequence, ". Also," a sentence). Two readings
sit inside the next item rather than between: a trailing "afterwards" / "after
that" ("gym at 9, lunch afterwards") is a sequence, and "X right after
<named earlier item>" is a sequence whose `to_index` is THAT item. An
enumeration ("at 9 and 11") is `same_span`. `joiner` names the bank the words
came from, so a board can read per joiner.

## The gold is by construction

`generate.py` builds each row from a structured specification (parts, joiners,
where the clocks and days sit) and computes both golds from it. Nothing in
`assistant/engine/` is run or consulted for a value, and no model is asked. The
rules — Q51 plus the conventions it rests on — are in the generator's
docstring; the chain half is summarised in
`decompose_validate/datasets/chain/README.md`.

## What varies — 154 families, 483 distinct skeletons

- **every sequence joiner Gil listed, its own bank**: then · and then · followed
  by · then after · and then after that · after that · right after that ·
  straight after that · afterwards · afterward · after which · next · and next
  · next up · and after · after this · once that's done · once done · when
  that's done · when I'm done (with that) · when finished · as soon as that's
  done · subsequently · ". Then" · "first X then Y then finally Z" — and the
  trailing forms "lunch afterwards" / "a haircut after that";
- **list and sentence joiners** as controls (and · comma · also · plus · ". "
  · "; "), alone and mixed with sequence joiners in one command;
- 2 to 5 parts; clocks on the first part only, first and middle, all, none, the
  middle only, and after a chained part;
- stated durations (before or after the clock) and ranges;
- the day leading (with and without a comma), inside the first part (before or
  after the clock), and a new day partway through, with and without a clock;
- meals chained, meals as an untimed head, meals as a list control;
- to-dos chained ("walk the dog at 5, then do the laundry"), "remind me to …",
  a to-do head with a clock, to-dos as list controls;
- person encounters ("coffee with Dana", "call Dana") and role calls ("call the
  plumber");
- "right after <named earlier item>", naming the previous item or one further back;
- enumerations ("at 10 and 4, then dinner");
- fillers, hedges, polite openers, sentence case with periods, lead-time tails;
- **decoys that must not split** (9 families, 180 rows): "meet Sam at 5 and then we'll
  see", "remind me to … then", "until then", "back then", "if Dana is free
  then", "the next …", "after that meeting", "by then", "before then";
- **damage** (14 families, 182 pairs): misspelt joiners ("folowed / followd /
  fallowed by", "afterwords", "after wards", "than", "after tht / dat", "nxt"),
  a split word ("the n"), a doubled joiner ("then then"), missing commas, and a
  typo'd title. Each damaged row has a clean twin — same family, different id,
  identical gold, since the gold is the INTENDED command — so the pair measures
  both "the damage got fixed upstream" and "it did not".

A skeleton is the row's structure with every filler removed (part classes,
clock/duration/day placement, joiner lexemes, style, damage); 483 distinct
skeletons sit behind the 3,580 rows. Titles, names, and times come from
FastRule's filler banks (`fastrule/datasets/banks/fillers.json`, base pools
only, read-only), filtered so a title never carries a rule its family did not
ask for (meal words to the meal pool, "call the plumber" to the role pool).

`ambiguous: true` rows (48) are generated and split like any other family and
**never scored**: "the talk followed by questions" (one event with a
programme, or two?), an untimed to-do heading a chain, "later", "after lunch".

## The split — by family, 80/20

|  | rows | families | skeletons | clean · damaged | decoys | ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| train | 2,886 | 124 | 392 | 2,743 · 143 | 140 | 36 |
| test | 694 | 30 | 96 | 655 · 39 | 40 | 12 |

Stratified by `bucket` over a stable hash of the family name (FastRule's
mechanism): every bucket of two or more families has one on each side, a
singleton (`rollover`) stays in train. The joiner sweep is split by joiner
instead: for about 40% of joiners ONE of its two families is test, so every
joiner is seen in train and the test half holds unseen (joiner, shape) pairs.
`build()` asserts no family is on both sides. The test half has no `sentence`
or `same_span` relation and no rollover row — read those from train only.

TEST is aggregates only (`engine/TRAIN_TEST_SPLIT_CONVENTION.md`): the boards
print no row and no family name for it and refuse `--show` there.

## Regenerate

    ./.venv/bin/python -m assistant.engine.segmentation.datasets.sequence.generate          # writes both files
    ./.venv/bin/python -m assistant.engine.segmentation.datasets.sequence.generate --check  # compare, write nothing

Deterministic (seed `sequence-q51-v1`); `tests/unit/test_sequence_dataset.py`
rebuilds it and fails when the committed files are stale.
