# What the retrospective says is worth fixing (2026-09-13)

Grounded in the checkpoint sweep (`RESULTS.md`, 2026-09-12 milestone) and in
reading the engine. **None of these is a structural change** — Gil, 2026-09-13:
implementation fixes only. The one-shot experiment they were held for is
done (sealed + personas, 2026-09-13/14) — see RUN_STATUS.md.

## The finding that frames the rest

On the SAME 170 rows, `main`'s two paths:

    fast path (rules, ~0 ms)       93.1% correct
    deep path (6 stages + LLM)     65.3% correct

The cheap deterministic path is **28 points better** than the expensive one.
Every stage in the deep track exists to handle what the rules cannot — and on
this evidence, handing a row to the model makes it LESS likely to be right.
That inverts the architecture's premise, in which the LLM is the smart
fallback.

## 1 · Skip the not-found recheck when there is nothing to have mismatched

**25 of the 30 slow fast-path rows are deletes.** A delete commits in
milliseconds, `execute()` raises `TargetNotFound`, and `_commit` fires
`_recheck_not_found` — a full LLM parse, ~40 s — which agrees the target is
missing and changes nothing. The row was already correct.

If the target store holds no candidate rows, the model cannot re-read a target
into existence: the not-found is CERTAIN and the call is pure cost. Gate on
that. ~20% of fast-path traffic, ~40 s each.

Keep the recheck where it earns its place — the run-9 case it was built for
("Walk Mark's dog" → `complete_todo 'walk mark stalk'`) has candidates present.
So the gate is a CANDIDATE COUNT, never a switch. **Read "The condition these
were measured under" below before acting on this one: the board that produced
the finding ran every row against an emptied calendar.**

## 2 · Raise fast-path coverage — the highest-leverage lever available

43% of rows (130/300) at 93% correct, against a deep path at 65%. Every row
moved from deep to fast is expected to GAIN accuracy and lose ~44 s. This is
threshold and gate calibration — R2's queued job — and needs no structural
change.

## 3 · Fix the `llm_ms` recording gap

`_recheck_not_found` calls the model without adding to `state.llm_ms`, so the
slow fast rows record `llm_ms` 0 against `total_ms` 40,000. Every board that
splits latency by `llm_ms` is wrong on the fast path, which is how a 40-second
call stayed invisible.

## The condition these were measured under

**§1 was measured under exactly the condition that guarantees its finding.**
`scripts/checkpoint_sweep.py:178` calls `reset_calendar()` before EVERY row,
and that function deletes `events`, `todos` and `subtasks` from the scratch
store (`:145-155`). So every delete and update on that board met an empty
calendar: the not-found was structural, not a misread, and the recheck could
not possibly have found anything. A live store is the normal case and this
board never had one.

Re-derived from the archive rather than from the report
(`dataset/runs/checkpoint-sweep-pass1/main/engine_run.db`, `parse_path='fast'
AND total_ms>10000`): **32 fast-path rows over 10 s — 25 `delete_*`, 3
`query_*`, 2 `update_*`, 2 `create_*` — while the other 98 fast rows all finish
under 2.0 s.** (§1's "30" has no recorded threshold; 32 is what a 10 s line
gives. The shape is the same.)

Two things that follow, and they pull in opposite directions:

- **27 of the 32 end at "I couldn't find …"** — the model was asked, agreed,
  and changed nothing. That is the waste §1 is about, and on a board with an
  empty store it is the ceiling, not the estimate.
- **5 of the 32 did not** — including `Remove fruits from the list` →
  `create_todo 'remove fruits'`, an outcome the first parse's not-found did not
  produce. The archive records the FINAL action and keeps no trace, so which
  of the five the recheck itself changed cannot be settled from it; what it
  does settle is that slow fast rows are not uniformly idle rechecks. Two of
  the five are creates, which `_recheck_not_found` cannot explain at all —
  post-commit model work on the fast path (`engine/__init__.py:630
  fix_title_async`) is unaccounted for in the same way §3 describes.

**§2 may not be justified by the numbers that motivated it.** Both boards are
`split:"test"` — every sealed row and every personas row — so under
ITERATION_PROTOCOL none of this picks the next thing to work on. The 93.1 / 65.3
split is a REPORT. Re-derive it on the training pool first: `fastrule-v1` vs
`main` on dev-fast-250, which is freely mineable. Expect that to be the first
real cost of §2. §2 also runs straight into Gil's own standing fence on
fast-rule work (STATUS.md, "user-gated, do not start unprompted"), which is a
decision for him and not something this file settles.

## What NOT to do

**More cycles against dev-fast-250.** Four of the last five moved less than the
noise floor, and the personas board shows why: the rebuild delivered phrasing
robustness the main benchmark cannot see, because every sealed row is one
voice. **The size of that gain is smaller than this file first said.** The
+26.3 pt (54.7 → 81.0) written here on 2026-09-13 came from the FIRST personas
sampler, `537dcfbc4dbd:300`, which drew 49% two-event compounds against 6% in
the real distribution and no queries or tasks at all — superseded. On the
re-sampled board that stands (`1a3064b09c1c:300`, count-correctness,
pre-engine-v2 72.3 → main 79.3) the gain is **+7.0 pt**, against −1.7 pt on the
sealed 300 over the same two checkpoints. The argument survives — one board
sees a gain the other cannot — at a quarter of the size.

*(A fourth item — A/B the segmentation swap via `MACALENDAR_SEGMENTATION` —
was dropped by Gil on 2026-09-13 as not relevant. Confirmed 2026-09-14: it was
removed before this file was first committed, so no version of it has ever
carried a fourth recommendation — `git log -- RECOMMENDATIONS.md` is the single
commit `8d37800`, and the three above are the whole list.)*

## What governs this list

Gil, 2026-09-13/14, recorded here because it is the rule these three were
written against and it was nowhere in the repo:

> "well segmentation as long as the structure remains the same, and just
> fixing implementations then its fine. same for fastrules."

> "i don't really want to make structural changes if i don't have to."

So: IMPLEMENTATION fixes inside `assistant/engine/segmentation/` and
`assistant/engine/fastrule/` are allowed; STRUCTURE and DESIGN changes are not.
That supersedes the blanket "no edits to segmentation at all" gloss the docs
carried, and it is why all three items above are one-function changes. The
canonical home for the ruling is STATUS.md / TASKS.md; this copy exists so a
reader of these recommendations knows the fence they sit inside.
