# Real-usage board

_Run 2026-09-18 12:23. `python -m scripts.real_usage_board`._

> **A real store changed during the run:** calendar.db. Either an override was missed (a leak — distrust everything below) or the assistant was simply used while the board ran.

> No rows appeared in the real calendar, so nothing the board created reached it — the change was elsewhere (a log, a setting, the command memory the live app writes on every command).

## The headline

**Corrected tier, all fields right: 11.1% (n=9)** — of 16 corrected rows, 7 are excluded because the gold is a title Gil TYPED rather than said, which no parser can reach (see the note below). Item count right on 77.8%.

### Per field, corrected tier

| field | right | scored |
|---|---|---|
| title | 38.9% | 18 |
| date | 78.6% | 14 |
| start_time | 50.0% | 14 |
| end_time | 50.0% | 14 |
| recurrence | — | 0 |
| recur_until | — | 0 |

_A field is scored only where the gold states it; a gold silent on `end_time` is not evidence about `end_time`._

_`start_time`/`end_time` read LOW for a reason beyond the parse: on a row whose gold came from Gil's UI edits, the times were often dragged by hand too (`3.45 pm` spoken, gold `09:02-09:58`). `gold_usable` is per ROW, so a row kept for its derivable TITLE brings its hand-set times along. Treat `title` and `date` as the trustworthy columns and the clock pair as an upper bound on the damage._

## Regression and movement

- **Approved tier (n=16):** the replay still produces what he accepted on **43.8%**. Anything less than 100% is a regression against a command he blessed.
- **Rejected tier (n=41):** the output CHANGED on **75.6%**. Changed is not fixed — there is no gold here — but unchanged is certainly not fixed.

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

## The error bar, measured

Two full replays of the same 73 rows on unchanged code, 2026-09-18:

| tier | run 1 | run 2 |
|---|---|---|
| corrected, all fields (n=9) | 11.1% | 11.1% |
| corrected, count (n=9) | 77.8% | 77.8% |
| approved, unchanged (n=16) | 43.8% | 43.8% |
| rejected, changed (n=41) | 63.4% | 61.0% |

**The corrected and approved tiers reproduced exactly; the rejected tier moved 2.4 pt.** That is the deep track's model output varying between runs, and it lands only on the rejected tier because that tier's question is "did the output change at all" — the most sensitive thing one could ask. So: treat a move under ~3 pt on the rejected tier as noise, and anything on the other two as real. Re-measure this after any change to the deep track.

## Latency, by the path the replay took

| parse path | n | p50 | p95 |
|---|---|---|---|
| deep | 33 | 4.3s | 20.9s |
| fast | 38 | 0.1s | 0.1s |
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
- id=207 [stt-garbage] count 3/3, wrong: title
  - WalkMoxDog today at 2pm, and also WalkMoxDog tomorrow at 8.30am, and I
- id=219 [stutter-split] count 2/2, wrong: start_time, end_time
  - Movie at Lincoln Square tomorrow, AMC, 11.15 AM tomorrow, execute.
- id=220 [stt-garbage] count 1/1, wrong: title
  - Walk, Mark, Stog, at 5.30pm today, execute.
- id=223 [disfluency] count 4/4, wrong: title
  - I need to buy some ice, I need to buy green onion, and I also need to 

### Rejected, output unchanged (still wrong the same way)

- id=6 [anaphoric-edit] ['update_event']
  - the last event that you just created on next monday on the 13th fixer 
- id=18 [generic-title] ['create_event']
  - set an appointment for tomorrow morning on tuesday at 910am
- id=34 [generic-title] ['create_event']
  - set a meeting for me tomorrow at 4pm
- id=40 [disfluency] ['create_event']
  - set meeting on thursday for three o'clock. thank you. is this why you 
- id=41 [generic-title] ['create_event']
  - set a meeting on thursday for 11 a.m. to
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

---

# Run 2 — 2026-09-21, after two days of engine work. IT MOVED NOTHING.

Same instrument, same rows, `python -m scripts.real_usage_board`. Guard
passed: no real store changed during the run.

| | 2026-09-18 | **2026-09-21** |
|---|---|---|
| corrected, all fields (n=9) | 11.1% | **11.1%** |
| corrected, item count | 77.8% | **77.8%** |
| title | 38.9% (18) | **38.9%** (18) |
| date | 78.6% (14) | **78.6%** (14) |
| start_time · end_time | 50.0% (14) | **50.0%** (14) |
| approved, unchanged | 43.8% (7/16) | 47.1% (8/17) |
| rejected, changed | 75.6% (41) | 73.8% (42) |

**Every corrected-tier number is identical, and the "corrected, still wrong"
list is the same eight ids in the same fields** (46, 118, 136, 143, 207, 219,
220, 223). The approved tier gained one row and one pass; the rejected tier
moved 1.8 pt, inside the 2.4 pt error bar this file measured on 2026-09-18.

## What happened in between, and why it did not land here

2026-09-20 ran eleven cycles against dev-100 and moved it a long way: field
quality 88.7 → 91.9%, item precision 75.8 → 93.0%, junk-title rate 29 → 4%,
count-correct 74 → 79%. Four of those cycles (30–33) were explicitly about
TITLES, which is the class this board has named as the largest since its
first run.

**None of it reached a single failing row here.** The two corpora fail
differently:

| dev-100's titles | this board's titles |
|---|---|
| the program's own words leaking in — 'event', 'new list', 'note of it' | the speaker never named the thing: *"set a meeting for me tomorrow at 4pm"* |
| a command frame the verb left behind — 'remind about of all event in calenders' | speech that restarts mid-sentence — *"set a date for tomorrow at 11 o'clock, in one second, one moment…"* |
| a cut that ended mid-phrase — "grocery shopping 's to-do list" | words the recogniser mangled — 'WalkMoxDog', 'Walk, Mark, Stog', 'Conello oil' |

Yesterday's work fixed the left column. The right column is `generic-title`
(42%), `disfluency` (16%) and `stt-garbage` (12%) — and the left column
barely exists in Gil's speech.

**This is the answer to the question Q39 was asked about.** Gil ruled on
2026-09-21 that real usage comes before more dev-100 work, on the suspicion
that a day of tuning had been spent on a corpus that is not his speech. The
suspicion was correct, and this run is the measurement of it.

## One thing DID change, and this board is why it was found

`fastrule/build.py` read `titles[0]` from the parser and rebuilt a ONE-ITEM
to-do from it, so every multi-item to-do on the deep track lost everything
after the first:

    "I need to buy Dr. Brown and Pepsi"
       parser:    ['buy dr. brown', 'buy pepsi']
       committed: ['buy dr. brown']     — and the reply named only that

No board here could see it. The fast path commits the parser's intents with
the list intact, and count-correctness reads one to-do out of a to-do ask as
the right COUNT. It surfaced in the APPROVED tier, whose only question is
"does it still do what he accepted" — Gil had approved the two-item answer
back when it worked. Fixed; both FastRule boards byte-identical, suite 2,170.

## A process failure worth recording

This board was rebuilt from scratch on 2026-09-21 by a session that had read
`REAL_SPEECH_PLAN.md` and not checked whether the deliverable already
existed — the 770-line version from 2026-09-18 was overwritten by a cruder
404-line one, and three findings already written here (the unreachable gold,
titles as the weak field, the measured error bar) were "discovered" again.
Restored from git. **The plan is not the record of what has been built; the
RESULTS.md beside the script is.** Check for the artefact before building it.

## Registered next — cycle 35

Work the classes this board names, not dev-100's. **`generic-title` first**
(21 of 50 non-approved rows): *"set a meeting for me tomorrow at 4pm"* names
no subject, and Q38 now says refuse rather than create 'meeting' — so the
question is whether these rows already refuse, and if so whether refusing is
the right answer for a command that is otherwise complete and confident.
**Prediction:** the rejected tier's unchanged count falls (those rows change
behaviour); the corrected tier is unmoved, because only id=118 is in this
class. If dev-100 moves at all, the change has reached past real speech.

