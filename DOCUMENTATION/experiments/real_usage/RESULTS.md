# Real-usage board

_Run 2026-09-18 10:35. `python -m scripts.real_usage_board`._

> Guard passed: no real store changed during the run.

## The headline

**Corrected tier, all fields right: 11.1% (n=9)** — of 16 corrected rows, 7 are excluded because the gold is a title Gil TYPED rather than said, which no parser can reach (see the note below). Item count right on 77.8%.

### Per field, corrected tier

| field | right | scored |
|---|---|---|
| title | 33.3% | 18 |
| date | 78.6% | 14 |
| start_time | 42.9% | 14 |
| end_time | 42.9% | 14 |
| recurrence | — | 0 |
| recur_until | — | 0 |

_A field is scored only where the gold states it; a gold silent on `end_time` is not evidence about `end_time`._

_`start_time`/`end_time` read LOW for a reason beyond the parse: on a row whose gold came from Gil's UI edits, the times were often dragged by hand too (`3.45 pm` spoken, gold `09:02-09:58`). `gold_usable` is per ROW, so a row kept for its derivable TITLE brings its hand-set times along. Treat `title` and `date` as the trustworthy columns and the clock pair as an upper bound on the damage._

## Regression and movement

- **Approved tier (n=16):** the replay still produces what he accepted on **43.8%**. Anything less than 100% is a regression against a command he blessed.
- **Rejected tier (n=41):** the output CHANGED on **63.4%**. Changed is not fixed — there is no gold here — but unchanged is certainly not fixed.

## Failure taxonomy

| class | rows | share |
|---|---|---|
| generic-title | 21 | 42.0% |
| disfluency | 8 | 16.0% |
| stt-garbage | 6 | 12.0% |
| anaphoric-edit | 5 | 10.0% |
| compound | 3 | 6.0% |
| stutter-split | 1 | 2.0% |
| non-command | 1 | 2.0% |
| other | 5 | 10.0% |

_Hand-classified once over 50 non-approved rows, stored in `taxonomy.jsonl` keyed on the verbatim transcript._

## What this run says to do next

**`generic-title` is the largest class at 42.0% of 50 non-approved rows**, and the corrected tier agrees from the other direction: `title` is the worst field by a distance while `date` is comparatively healthy. Read those two together before choosing work — they name the same component.

`REAL_SPEECH_PLAN.md` predicted `stt-garbage` + `disfluency` would dominate and ordered its phases on that. **They do not**, and the plan says in that case to stop and say so rather than build Phase 2 anyway. See this file's git history for the correction.

## Latency, by the path the replay took

| parse path | n | p50 | p95 |
|---|---|---|---|
| deep | 40 | 4.7s | 51.0s |
| fast | 31 | 0.1s | 0.1s |
| ignored | 2 | 0.0s | 0.0s |

## Why half the corrected gold cannot be scored

`memory.set_feedback` (`assistant/intent/memory.py:229`) stores whatever the client sends, and the review flow sends the record as it stands AFTER Gil edits it in the UI. So a correction is the FINAL STATE of the row, not a corrected reading of the sentence:

    said:  "Set a meeting for 10 a.m. tomorrow morning"
    gold:  title "Date <heart>", 11:00-15:00

No parse produces that, and scoring it would cap this metric forever and blame the engine for not reading his mind. Each corrected row is therefore hand-marked `gold_usable` and both counts are printed. **The durable fix is to record the corrected PARSE alongside the record state** — until then this tier stays small.

## Rows to read

### Corrected, still wrong

- id=46 [compound] count 2/4, wrong: title, date, start_time, end_time
  - Right, set an event for today at 3.45 pm, which are already past, Walk
- id=118 [generic-title] count 1/1, wrong: title, start_time, end_time
  - Add an event for 5 p.m. execute.
- id=136 [stt-garbage] count 2/2, wrong: title
  - I need to buy cold brew, and I need to also buy, Conello oil, can, exe
- id=143 [compound] count 5/4, wrong: title, date, start_time, end_time
  - Alright, we have a few events set for Tuesday to walk Moxdog at 9 a.m.
- id=185 [generic-title] count 1/1, wrong: title, start_time, end_time
  - Set for 2 p.m. tomorrow, CC event, execute.
- id=207 [stt-garbage] count 3/3, wrong: title
  - WalkMoxDog today at 2pm, and also WalkMoxDog tomorrow at 8.30am, and I
- id=219 [stutter-split] count 2/2, wrong: start_time, end_time
  - Movie at Lincoln Square tomorrow, AMC, 11.15 AM tomorrow, execute.
- id=220 [stt-garbage] count 1/1, wrong: title
  - Walk, Mark, Stog, at 5.30pm today, execute.

### Rejected, output unchanged (still wrong the same way)

- id=6 [anaphoric-edit] ['update_event']
  - the last event that you just created on next monday on the 13th fixer 
- id=12 [generic-title] ['create_event']
  - today i have an event at 6 o'clock a meeting
- id=14 [generic-title] ['create_event']
  - please make a meeting for me at 1040 on monday the 13th for makabi vis
- id=18 [generic-title] ['create_event']
  - set an appointment for tomorrow morning on tuesday at 910am
- id=32 [generic-title] ['create_event']
  - set tomorrow a meeting with ora at 5pm
- id=34 [generic-title] ['create_event']
  - set a meeting for me tomorrow at 4pm
- id=38 [disfluency] ['create_event']
  - set a meeting tomorrow. sorry, not tomorrow. set a meeting on tuesday.
- id=40 [disfluency] ['create_event']
  - set meeting on thursday for three o'clock. thank you. is this why you 
- id=41 [generic-title] ['create_event']
  - set a meeting on thursday for 11 a.m. to
- id=55 [generic-title] ['create_event']
  - Set a meeting of his hours meeting on Sunday at 1 p.m. this coming Sun
- id=135 [?] ['create_todo']
  - Groceries, I need to buy zucchini, cold brew, execute.
- id=137 [?] ['create_todo']
  - 10,000, you'd buy Gatorade and Dr. Brown, execute.
- id=140 [?] ['create_todo']
  - I need to buy some groceries, which includes pasta times 5, execute.
- id=141 [?] ['create_event']
  - Have a movie today from 3pm to 6pm, execute.
- id=218 [?] ['create_event']
  - We'll start an event for later, walking Jada at 2.30pm, execute.
