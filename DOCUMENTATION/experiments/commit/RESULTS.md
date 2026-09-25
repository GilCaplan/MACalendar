# The save step (commit) — results

Boards for what happens AFTER the judge: the action executors and the
engine's `_commit`. `scripts/cross_store_board.py` is the first (the save step has
no stage folder, so its board lives with the other cross-stage ones).

## The other-list lookup (2026-09-24)

**Stage: commit · `engine._other_store`.** A change or delete whose target is
not found in the store the engine chose now looks in the other store and runs
there on exactly ONE strong match (title contains the words or is contained
in them); an anaphor, two candidates, or a field only one side has refuses.

`cross_store_board`, every change row of the FastRule set (update, delete,
complete; generic targets excluded), whole engine, model-free, a fresh scratch
store per row with the gold target on its gold list plus three decoys on each
list; lookup off vs on at one commit:

| FastRule · split · n | right, off | right, on | changed |
|---|---|---|---|
| TRAIN · 746 | 55.8% (416) | **59.5% (444)** | 28 nothing → right, 0 worse |
| TEST · 380 | 31.3% (119) | **37.4% (142)** | 23 nothing → right, 0 worse |

"Right" = the seeded target changed as the gold asks. The fixes are the
shape the lookup was built for: "scrap vet appointment", "drop water the
plants from my tasks", "take book club off my calendar".

**What the board found beyond it — the next thing to fix.** A DECOY changed on
35 train and 120 test rows in BOTH arms: the executors' fuzzy matchers
(`_find_todo`, `_find_event`) take the best any-word overlap, so a target
that is absent can match an unrelated item and delete or edit it. That is the
harm class weighted 4, and it is independent of this lookup.

## The matchers stop guessing (2026-09-24)

**Stage: commit · the executors' title matchers** (`actions/calendar/action.
_find_event`, `actions/todo/action._find_todo`). The board above counted a
"decoy changed" on 35 train rows; split by what happened, **27 were a CREATE
instead of a change** (a wrong operation — "add a note to …", "updat X on my
list"), and **8 were an existing item edited or deleted in place of the one
named** — the harm class weighted 4:

- "delete water the garden from my list" deleted 'water the plants': the front
  door handed over "water" (it cut the name), and two tasks tied on it.
- "move team meeting to next friday" moved 'team standup': the generic-word
  filter dropped "meeting", leaving "team", tied with the standup.
- "cancel conference call in five days" DELETED 'team standup': "conference"
  and "call" are both generic, so the matcher fell back to the first event on
  that date.

Two rules for both matchers: an item whose title IS the named words wins
outright (on the named day when one was given), and a tie at the top between
DIFFERENT titles is not an answer — "I couldn't find" is (series instances
share a title and are not a tie).

| cross_store_board · TRAIN · n=746 | before | after |
|---|---|---|
| right | 444 (59.5%) | **446 (59.8%)** |
| an existing item wrongly edited/deleted | **8** | **0** |
| created instead of changing | 27 | 27 |

TEST (n=380): 142 right both; no wrong-target edit before or after (its 120
"decoy" rows were all creates). The six "water the garden" rows are now "not
found" rather than a wrong delete; they need the front door to hand over the
whole name — the FastRule stage, next.
