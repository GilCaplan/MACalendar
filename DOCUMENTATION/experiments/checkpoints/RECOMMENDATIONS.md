# What the retrospective says is worth fixing (2026-09-13)

Grounded in the checkpoint sweep (`RESULTS.md`, 2026-09-12 milestone) and in
reading the engine. **None of these is a structural change** — Gil, 2026-09-13:
implementation fixes only. Held for after the one-shot experiment.

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

## What NOT to do

**More cycles against dev-fast-250.** Four of the last five moved less than the
noise floor, and the personas board shows why: the rebuild delivered +26.3
points of phrasing robustness (54.7 → 81.0) that the main benchmark cannot
see, because every sealed row is one voice.

*(A fourth item — A/B the segmentation swap via `MACALENDAR_SEGMENTATION` —
was dropped by Gil on 2026-09-13 as not relevant.)*
