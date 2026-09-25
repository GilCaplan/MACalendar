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
