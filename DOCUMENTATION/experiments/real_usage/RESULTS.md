# Real-usage board

_Run 2026-09-22 10:18. `python -m scripts.real_usage_board`._

> Guard passed: no real store changed during the run.

## The headline

**Corrected tier, every REACHABLE field right: 6.7% (n=15 of 16)** — a field is scored only where the gold value is one a parse of the words could produce (`intent/correction.py`: unchanged, or a title whose words were said, or a clock on the five-minute grid); 1 rows have no reachable field at all. Item count right on 80.0%. Read by hand mark alone, as the 2026-09-18 headline was: 11.1% (n=9).

### Per field, corrected tier

| field | right | scored |
|---|---|---|
| title | 36.8% | 19 |
| date | 73.7% | 19 |
| start_time | 44.4% | 18 |
| end_time | 44.4% | 18 |
| recurrence | — | 0 |
| recur_until | — | 0 |

_A field is scored only where the gold states it; a gold silent on `end_time` is not evidence about `end_time`._

_`start_time`/`end_time` read LOW for a reason beyond the parse: on a row whose gold came from Gil's UI edits, the times were often dragged by hand too (`3.45 pm` spoken, gold `09:02-09:58`). `gold_usable` is per ROW, so a row kept for its derivable TITLE brings its hand-set times along. Treat `title` and `date` as the trustworthy columns and the clock pair as an upper bound on the damage._

## Regression and movement

- **Approved tier (n=17):** the replay still produces what he accepted on **47.1%**. Anything less than 100% is a regression against a command he blessed.
- **Rejected tier (n=42):** the output CHANGED on **73.8%**. Changed is not fixed — there is no gold here — but unchanged is certainly not fixed.

## Under Q41 — the generic-title class against what the words hold

Gil, 2026-09-22 (DEVQA Q41): *"just make a meeting according to other details with bare title is fine."* So the largest class is re-scored against REACHABLE gold — `reachable` in `taxonomy.jsonl`, hand-authored on each row's own clock: the subject the words actually held, or a bare title where nothing beyond the kind was said, plus the stated day and clock. The tiers above are untouched; this is the same rows read under the ruling.

**Right, or acceptable under Q41: 61.9% of 21 rows** (item count right on 100.0%).

| items | n | title right | …and no junk in it | day+clock right | title and when |
|---|---|---|---|---|---|
| subject was SAID — the title must carry it | 15 | 100.0% | 100.0% | 73.3% | 73.3% |
| nothing but the kind was said — bare is right | 7 | 42.9% | 0.0% | 71.4% | 28.6% |

_Per ITEM in the table, per ROW in the bold line. A said subject is right when the title CONTAINS the phrase (any spelling the vocabulary produces); junk is `score_dataset_run.is_garbage_title`; `end_time` is scored only where the words stated one._

Rows still wrong under Q41:

- id=4 (rejected, said) wrong: date — made [('go visit my friend tal got', '2026-09-03', '13:00')]
  - create event this coming thursday to go visit my friend tal at 1 p.m. 
- id=12 (rejected, bare) wrong: title — made [('i have an event a meeting', '2026-08-26', '18:00')]
  - today i have an event at 6 o'clock a meeting
- id=14 (rejected, said) wrong: start_time — made [('the 13th for maccabi visiting the doctor', '2026-09-13', '00:00')]
  - please make a meeting for me at 1040 on monday the 13th for makabi vis
- id=18 (rejected, bare) wrong: start_time, title-junk — made [('Appointment', '2026-08-27', '09:00')]
  - set an appointment for tomorrow morning on tuesday at 910am
- id=26 (rejected, bare) wrong: title, title — made [('meeting a.m', '2026-08-27', '11:00'), ('meeting p.m. p.m. as well', '2026-08-27', '17:30')]
  - set a meeting for me tomorrow at 11 a.m. and also set meeting for 5.30
- id=54 (rejected, said) wrong: start_time — made [('ta office hour meeting', '2026-08-30', '09:00')]
  - Set a meeting on this coming Sunday for 1 p.m. TA, Office Hour, meetin
- id=68 (corrected, said) wrong: start_time — made [('for 830 go to daven pre', '2026-08-30', '20:00'), ('Training practice', '2026-08-30', '20:00')]
  - Sunday, set for 830, to go to Doven, pre-Shacharit, and then after tha
- id=118 (corrected, bare) wrong: start_time, title — made [('5 p.m', '2026-08-28', '13:00')]
  - Add an event for 5 p.m. execute.

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
| fast | 40 | 0.1s | 0.1s |
| ignored | 2 | 0.0s | 0.0s |

## Why part of the corrected gold cannot be scored

`memory.set_feedback` stores whatever the client sends, and the review flow sends the record as it stands AFTER Gil edits it in the UI. So a correction is the FINAL STATE of the row, not a corrected reading of the sentence:

    said:  "Set a meeting for 10 a.m. tomorrow morning"
    gold:  title "Date <heart>", 11:00-15:00

No parse produces that, and scoring it would cap this metric forever and blame the engine for not reading his mind. Since 2026-09-22 the memory ANNOTATES every correction as it is stored — per action, which fields changed against the engine's parse and which new values the words could reach (`assistant/intent/correction.py`, rules in its docstring) — and this board applies the same rules to rows stored before then. A field is scored when reachable; a hand mark `gold_usable` in `taxonomy.jsonl` still scores a whole row and is what the strict number above reads.

## Rows to read

### Corrected, still wrong

- id=46 [compound] count 2/4, wrong: title, date, start_time, end_time
  - Right, set an event for today at 3.45 pm, which are already past, Walk
- id=47 [other] count 1/1, wrong: start_time, end_time; unreachable: title
  - Set a meeting for 10 a.m. tomorrow morning, execute.
- id=49 [other] count 1/1, wrong: date; unreachable: title
  - I had an event on the 17th of September, from 7 p.m. to 10 p.m. going 
- id=52 [other] count 1/1, wrong: date; unreachable: end_time, start_time, title
  - Set a meeting for me this coming Sunday at... Let's see, it is...
- id=56 [disfluency] count 1/1, wrong: title; unreachable: date, end_time, start_time
  - set a date for tomorrow at 11 o'clock, in one second, one moment, one 
- id=68 [generic-title] count 2/1, wrong: start_time, end_time; unreachable: title
  - Sunday, set for 830, to go to Doven, pre-Shacharit, and then after tha
- id=118 [generic-title] count 1/1, wrong: title, start_time, end_time
  - Add an event for 5 p.m. execute.
- id=136 [stt-garbage] count 2/2, wrong: title
  - I need to buy cold brew, and I need to also buy, Conello oil, can, exe
- id=143 [compound] count 5/4, wrong: title, date, start_time, end_time
  - Alright, we have a few events set for Tuesday to walk Moxdog at 9 a.m.
- id=207 [stt-garbage] count 3/3, wrong: title
  - WalkMoxDog today at 2pm, and also WalkMoxDog tomorrow at 8.30am, and I
- id=211 [other] count 1/1, wrong: start_time, end_time; unreachable: title
  - Create an event now to go out for a run, execute.
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
- id=243 [?] ['create_event']
  - Every event tomorrow night at 9pm, to search for kingdoms, execute.

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


---

# Run 3 — 2026-09-22, the same rows read under Q41

Fresh replay (`python -m scripts.real_usage_board`), guard passed, byte-for-byte
the same three tiers as run 2: corrected 11.1% (n=9), approved 47.1% (8/17),
rejected changed 73.8% (42). What changed is the READING. Gil ruled today
(DEVQA Q41) that *"a meeting according to the other details with a bare title
is fine"*, so the largest class was re-scored against what the words hold —
`reachable` in `taxonomy.jsonl`, hand-authored per row on its own clock, 21
rows, 22 items — and the generated section "Under Q41" above carries the table.

**Generic-title, right or acceptable under Q41: 61.9% (13 of 21 rows).**

| items | n | title carries the subject / is bare | day+clock right | both |
|---|---|---|---|---|
| the subject WAS said | 15 | 100% | 73.3% | 73.3% |
| nothing but the kind was said | 7 | 42.9% | 71.4% | 28.6% |

Two things this says that the taxonomy's label hid:

- **The class was mis-named.** In 15 of 21 rows the speaker DID name the thing
  ("with etai", "with omri for the project", "office hour") and the old engine
  dropped it. Today's engine keeps the subject in 15/15. The ruling that a
  bare title is fine applies to 7 items, and it is not the engine's problem
  on those either: it is the TIME that is wrong on them.
- **The residue is the CLOCK, not the title.** Of the 8 rows still wrong, 6
  lose a stated time and all six share a shape the readers do not know:
  *"for 830"* → 20:00, *"for 1 p.m."* → 09:00, *"for 5 p.m."* → 13:00,
  *"at 1040"* → 00:00, *"at 910am"* → 09:00, *"this coming thursday"* → a
  week late. The other 2 keep the time phrase's dots in the title ('meeting
  a.m', 'meeting p.m. p.m. as well') — the same reader failing to consume
  "11 a.m." — plus 'i have an event a meeting'. Across the whole board, 36
  rows carry a spoken clock; "for <clock>", colon-less "830"/"1040"/"230PM",
  dotted "a.m."/"p.m.", and "9am and 2.30pm" (→ '30:00', id=142) are the
  forms that fail.

## The corrected tier, read per field (same day)

The durable fix this file asked for on 2026-09-18 is in: `memory.set_feedback`
and `feedback_for_record` now ANNOTATE every correction as it is stored — per
action, `changed` (which fields differ from the engine's parse) and
`reachable` (which new values a parse of the words could produce; rules in
`assistant/intent/correction.py`) — and the board applies the same rules to
the 16 rows stored before. A field is scored when reachable; the hand mark
still scores a whole row and gives the strict number.

| corrected tier | 2026-09-18 reading | per reachable field |
|---|---|---|
| rows scored | 9 of 16 | **15 of 16** |
| every scored field right | 11.1% | **6.7%** |
| title | 38.9% (18) | 36.8% (19) |
| date | 78.6% (14) | 73.7% (19) |
| start_time · end_time | 50.0% (14) | 44.4% (18) |

The number went DOWN because the instrument got wider, not because the engine
moved: six rows that used to be thrown out for a typed title now score their
date and clock, and most of them have one of those wrong too. Two of the new
failures are the same defect: id=52 *"this coming Sunday"* and id=4 *"this
coming thursday"* both land a week late on the fast path (the recogniser
reads "coming" as "next"), which cycle 35 below takes with the clock forms.

## Registered next — cycle 35: spoken clock forms

**Component:** the temporal readers on both tracks — `intent/rule_parser.py`
(`_extract_temporal`, fast path) and `decompose_validate/resolve.py` (deep).
**Change:** read "for <clock>" as a start time; compact clocks "830", "1040",
"910am", "230PM" as HH:MM; dotted "a.m."/"p.m." consumed with the hour so
neither the hour nor the dots survive into the title; "9am and 2.30pm" as two
clocks. **Prediction:** generic-title right/acceptable 13 → 17+ of 21 (ids 14,
18, 54, 68, 118 on time; 26 on title); corrected tier `start_time` 50% → 60%+
(n=14); dev-100 unchanged within a row (the synthetic pool has few compact
clocks) — if it moves down, the reader over-fires and the change is wrong.
Boarded first on FastRule's own board (`fastrule_shape --split train`) and the
dv stage board, one change, before either whole-chain run.
