# Dataset run score — `/var/folders/0f/nk3dnvrd54jbjz_qn40_ynwh0000gn/T/engine_compare_hkhl4thr/engine_run.db`

**SEALED TEST RUN — aggregates only. Row-level detail is
suppressed by design: test results are never mined, and a
test score never spawns a hypothesis (leakage guard).**

- product-adjusted count-correct **75%** (23 overridden rows; raw below is the comparable number)
- **301 prompts** scored · count-correct **73%** · garbage-title rate **7%**
- total_ms p50 77 · p95 46206
- parse paths: {'deep': 177, 'fast': 124}

## By complexity

| Tier | n | count-correct | garbage titles | total_ms p50 |
|---|---:|---:|---:|---:|
| simple | 97 | 86% | 1% | 35 |
| medium | 101 | 92% | 5% | 48 |
| complex | 103 | 42% | 14% | 5230 |

## By compound kind

| Kind | n | count-correct | garbage titles | dates collapsed |
|---|---:|---:|---:|---:|
| event+event | 35 | 51% | 9% | 11% |
| task+task | 36 | 33% | 17% | 8% |
| event+task | 32 | 41% | 16% | 19% |

## event+task: which half goes missing when it fails

- both present: 13 · event missing: 5 · task missing: 14 · both missing: 0

## Correctness by parse path

| Path | count-correct |
|---|---:|
| deep | 57% |
| fast | 95% |

## Count-mismatch failures (82)


## Comparison

- 300 shared prompts (2699 only in A, 0 only in B)
- count-correct rate: 70% → 73%
- **33 got worse**, **40 got better**, 178 still pass, 49 still fail