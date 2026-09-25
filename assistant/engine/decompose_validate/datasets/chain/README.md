# The chain dataset — sequence items with their resolved times

`chain.jsonl`: the same 3,580 rows as
`segmentation/datasets/sequence/sequence.jsonl` (same ids, families, split,
text, damage and twins), with each gold item RESOLVED — for this stage's
**chain board** (`../../experiments/chain_board.py`).

    gold: [{"action", "kind": event|task, "date": ISO, "start_time", "end_time",
            "linked_todo": true|false|null, "chained": bool,
            "role": head|chained|clocked|untimed|task|same_span|decoy}]

Every row carries `"anchor": "2026-09-09T06:00"`, a **Wednesday**. 06:00 is
earlier than every clock and every default hour in the data, so Q42's "a clock
that has already gone by means tomorrow" never fires and the date floor is
always today: this dataset measures the chain, not that rule.

## The rules the gold follows

**DEVQA Q51** (Gil, 2026-09-25), applied literally:

- A **sequence** item with **no clock of its own** starts when the item it
  follows ENDS, plus the gap (0). That end is the stated end (a range), else
  start + stated duration ("for 2 hours"), else start + 60 minutes. The chained
  item lasts its own stated duration, else 60 minutes.
- **The chain beats a meal's own hour**: "gym at 9, then lunch" is lunch at
  10:00. **A stated clock always wins**, and the chain continues from it:
  "dentist at 9 then lunch then gym at 3 then dinner" is dinner at 16:00.
- An untimed item that is not chained resolves the usual way: a meal's own hour
  (breakfast 09:00, lunch and brunch 13:00, dinner and supper 19:00 — Q32),
  else 09:00 (Q36).
- A sequence part with no day of its own **inherits the date** of the item it
  follows. A list or sentence part keeps today's behaviour — its own day, else
  a leading day, else today — and is never chained.
- **A to-do in a chain is chained too**, as an event with `linked_todo: true`
  ("walk the dog at 5, then do the laundry" → laundry 18:00–19:00, linked). A
  to-do outside a sequence stays a to-do (its date, no clock). A to-do with its
  own clock is an event (Q25), not linked.
- **"right after <named earlier item>"** anchors to THAT item, not merely the
  previous one.
- A **person encounter** ("coffee with Dana", "call Dana") is an event (Q47),
  not linked. A **role call** ("call the plumber") is an event (Q50); its
  companion to-do is Q50's and filed by the executor, so `linked_todo` is
  `null` on it and the board does not score that field there.
- A **new day partway through with no clock** ("…, then on friday supper") is
  still a sequence part with no clock, so it starts when the part before it
  ends — on friday. (The literal rule; the other reading, a meal's own hour on
  the new day, is not a ruling. Family `s3_newday_untimed`.)
- Chains end before midnight: a draw whose chain would reach 24:00 is rejected
  (the object layer caps an end at 23:59, so 24:00 has two spellings). The one
  exception is the `rollover` family (12 rows, train), where a chained item
  starting at or after midnight rolls to the next date; its head ends at
  "00:00". Reported as its own slice.
- Decoys resolve as the single item they are; `ambiguous` rows carry a gold
  but are never scored.

The gap and the length are settings (Q51.4, `assistant/event_defaults.py`);
the gold is built on the defaults, 0 and 60, and the chain board points
`MACALENDAR_CONFIG` and `MACALENDAR_CATEGORIES` at scratch so a machine's own
settings cannot move the reading.

## Counts

8,444 scored-or-slice items outside the ambiguous rows: 4,184 chained, 3,352
heads, 494 clocked non-heads, 78 untimed list parts (a meal's own hour), 130 to-dos, 26
enumerated, 180 decoys; 770 items whose gold `linked_todo` is true, 364 role
calls with it `null`. Split and diversity: see the sequence README (train 2,886
rows / 124 families, test 694 / 30, 483 distinct skeletons).

## Regenerate

Written by the same generator as the sequence file:

    ./.venv/bin/python -m assistant.engine.segmentation.datasets.sequence.generate
