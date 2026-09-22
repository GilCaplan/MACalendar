# Real-usage board

_Run 2026-09-22 14:00. `python -m scripts.real_usage_board`._

> Guard passed: no real store changed during the run.

## The headline

**Corrected tier, every REACHABLE field right: 21.4% (n=14 of 16)** — a field is scored only where the gold value is one a parse of the words could produce (`intent/correction.py`: unchanged, or a title whose words were said, or a clock on the five-minute grid); 2 rows have no reachable field at all. Item count right on 64.3%. Read by hand mark alone, as the 2026-09-18 headline was: 22.2% (n=9).

### Per field, corrected tier

| field | right | scored |
|---|---|---|
| title | 37.5% | 16 |
| date | 82.4% | 17 |
| start_time | 62.5% | 16 |
| end_time | 62.5% | 16 |
| recurrence | — | 0 |
| recur_until | — | 0 |

_A field is scored only where the gold states it; a gold silent on `end_time` is not evidence about `end_time`._

_`start_time`/`end_time` read LOW for a reason beyond the parse: on a row whose gold came from Gil's UI edits, the times were often dragged by hand too (`3.45 pm` spoken, gold `09:02-09:58`). `gold_usable` is per ROW, so a row kept for its derivable TITLE brings its hand-set times along. Treat `title` and `date` as the trustworthy columns and the clock pair as an upper bound on the damage._

## Regression and movement

- **Approved tier (n=17):** the replay still produces what he accepted on **64.7%**. Anything less than 100% is a regression against a command he blessed.
- **Rejected tier (n=42):** the output CHANGED on **90.5%**. Changed is not fixed — there is no gold here — but unchanged is certainly not fixed.

## Under Q41 — the generic-title class against what the words hold

Gil, 2026-09-22 (DEVQA Q41): *"just make a meeting according to other details with bare title is fine."* So the largest class is re-scored against REACHABLE gold — `reachable` in `taxonomy.jsonl`, hand-authored on each row's own clock: the subject the words actually held, or a bare title where nothing beyond the kind was said, plus the stated day and clock. The tiers above are untouched; this is the same rows read under the ruling.

**Right, or acceptable under Q41: 81.0% of 21 rows** (item count right on 90.5%).

| items | n | title right | …and no junk in it | day+clock right | title and when |
|---|---|---|---|---|---|
| subject was SAID — the title must carry it | 15 | 100.0% | 100.0% | 100.0% | 100.0% |
| nothing but the kind was said — bare is right | 5 | 60.0% | 0.0% | 100.0% | 60.0% |

_Per ITEM in the table, per ROW in the bold line. A said subject is right when the title CONTAINS the phrase (any spelling the vocabulary produces); junk is `score_dataset_run.is_garbage_title`; `end_time` is scored only where the words stated one._

Rows still wrong under Q41:

- id=12 (rejected, bare) wrong: title — made [('i have an event a meeting', '2026-08-26', '18:00')]
  - today i have an event at 6 o'clock a meeting
- id=18 (rejected, ) wrong: count 0/1 — made []
  - set an appointment for tomorrow morning on tuesday at 910am
- id=26 (rejected, bare) wrong: title-junk, title — made [('Meeting', '2026-08-27', '11:00'), ('meeting as well', '2026-08-27', '17:30')]
  - set a meeting for me tomorrow at 11 a.m. and also set meeting for 5.30
- id=118 (corrected, ) wrong: count 0/1 — made []
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
| deep | 29 | 5.4s | 52.7s |
| fast | 44 | 0.1s | 0.1s |
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
- id=68 [generic-title] count 2/1, wrong: count only; unreachable: title
  - Sunday, set for 830, to go to Doven, pre-Shacharit, and then after tha
- id=118 [generic-title] count 0/1, wrong: count only
  - Add an event for 5 p.m. execute.
- id=136 [stt-garbage] count 3/2, wrong: title
  - I need to buy cold brew, and I need to also buy, Conello oil, can, exe
- id=143 [compound] count 4/4, wrong: title, start_time, end_time
  - Alright, we have a few events set for Tuesday to walk Moxdog at 9 a.m.
- id=207 [stt-garbage] count 3/3, wrong: title
  - WalkMoxDog today at 2pm, and also WalkMoxDog tomorrow at 8.30am, and I
- id=211 [other] count 1/1, wrong: start_time, end_time; unreachable: title
  - Create an event now to go out for a run, execute.
- id=219 [stutter-split] count 1/2, wrong: title, start_time, end_time
  - Movie at Lincoln Square tomorrow, AMC, 11.15 AM tomorrow, execute.
- id=223 [disfluency] count 4/4, wrong: title
  - I need to buy some ice, I need to buy green onion, and I also need to 

### Approved, no longer reproduced (a regression against a blessed command)

- id=7 was ['update_event'] → now []
  - no, edit event next week on the 13th. that says 9am, change it to the 
- id=8 was ['create_event'] → now ['create_event']
  - this week on friday set for 12 o'clock defend my eurovision homox exec
- id=119 was ['create_event'] → now ['create_event']
  - Movie today at 4.30pm at the Lincoln AMC Theatre. Execute.
- id=122 was ['create_event'] → now ['create_event']
  - Set for today to walk Mark's dog at 2.30pm, execute.
- id=142 was ['complete_todo'] → now ['create_event', 'create_event']
  - Walk Mark's Dog on this coming Tuesday next week at 9am and 2.30pm, ex
- id=208 was ['create_todo'] → now ['create_event']
  - Go for a run now, execute.

### Rejected, output unchanged (still wrong the same way)

- id=34 [generic-title] ['create_event']
  - set a meeting for me tomorrow at 4pm
- id=41 [generic-title] ['create_event']
  - set a meeting on thursday for 11 a.m. to
- id=141 [?] ['create_event']
  - Have a movie today from 3pm to 6pm, execute.
- id=243 [?] ['create_event']
  - Every event tomorrow night at 9pm, to search for kingdoms, execute.

---

# Run 2 — 2026-09-21, after two days of engine work. IT MOVED NOTHING.

> **CORRECTION, 2026-09-22 — this run never replayed anything.** The board's
> `Checkpoint` resumes by default and only warns on a commit mismatch; every
> one of the 75 rows below was read back from the cache written by the FIRST
> run (commit `4b47af8`, 2026-09-18 12:04). "Identical numbers" was the cache,
> not the engine, and the conclusion that two days of work reached no real
> row is WRONG — run 4 below has the true before/after. The converter bug
> this run found was real (it surfaced in the cached approved rows against
> the live converter). Kept as written; the lesson is in `CLAUDE.md`.

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

> **CORRECTION, same day:** "fresh replay … byte-for-byte the same" below was
> the same cache as run 2. The Q41 re-read and the per-field corrected tier
> are valid as READINGS of those cached rows (the 2026-09-18 engine); the
> true numbers for today's engine are in run 4.

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

---

# Run 4 — 2026-09-22, the first real replay since 09-18, and cycle 35

The board now replays fresh by default (`--resume` is opt-in, for a crash at
the same commit). To attribute cycle 35 honestly, the pre-cycle commit
(`6c1e5c0`) was replayed in a worktree with a fresh sandbox, and both replays
are scored with the same scorer — which also had two faults fixed today: a
query's parameter-less reply read as a changed date, and one `create_todo`
carrying `titles` read as a different shape from two creates.

| | 09-18 engine (the cache) | pre-35, fresh | **cycle 35, fresh** |
|---|---|---|---|
| corrected, every reachable field (n=15) | 6.7% | 13.3% | **20.0%** |
| corrected, hand-marked rows (n=9) | 11.1% | 22.2% | **22.2%** |
| corrected, item count right | 80.0% | 60.0% | 60.0% |
| title (n≈17) | 36.8% | 35.3% | 35.3% |
| date | 73.7% | 76.5% | **82.4%** |
| start_time | 44.4% | 56.2% | **62.5%** |
| approved, unchanged (17) | 64.7% | 64.7% | 64.7% |
| rejected, changed (42) | 81.0% | 90.5% | 90.5% |
| generic-title right/acceptable under Q41 (21 rows) | 61.9% | 52.4% | **66.7%** |

**What the four days between 09-18 and pre-35 really did** (middle column
against the left): the corrected tier's fields improved — every reachable
field right 6.7 → 13.3%, hand-marked 11.1 → 22.2%, clock 44.4 → 56.2% — while
item COUNT fell 80 → 60% (over-splits on disfluent speech: id=56 now 3 items
for 1, id=136 3 for 2, id=219 1 for 2) and three generic-title rows lost their
DAY: *"tomorrow on tuesday"* (21), *"next week on the 14th on tuesday"* (11)
and *"monday the 13th"* (14) now land on the weekday and drop the stated day,
which the 09-18 engine had right. Neither movement was visible while the board
was serving the cache.

**Cycle 35** (right column against the middle; the change was the three
clock readers — segmentation's phrase table, the deep resolver, the fast
parser — learning "for 1 p.m.", "for 830", "at 1040", "at 910am", the dotted
meridiem at the end of a sentence, and "this coming thursday" as the soonest
Thursday). Prediction was generic-title 13 → 17+ of 21 against the cached
baseline; the TRUE baseline was 11, and it is **14 of 21** now (ids 4, 54, 68
fixed; 26's first item is a clean bare 'Meeting'). Corrected `start_time` was
predicted 50 → 60%+ and is **56.2 → 62.5%** (n=16); `date` 76.5 → 82.4%.
Every stage board was identical before and after (segmentation 1,051 train
rows, dv 2,004 rows, FastRule 4,800 train rows: none of them contains these
forms), and the new patterns fire zero times over 9,091 clean corpus rows —
so this is a real-usage-only class, which is what the board exists to find.

Two rows the cycle turned into refusals instead of fixes, and they are the
same question: **id=18** *"set an appointment for tomorrow morning on tuesday
at 910am"* and **id=118** *"Add an event for 5 p.m."* now commit NOTHING —
with the clock stripped, the title is the bare kind ('appointment', 'event')
and the Q38 gate refuses it. Q41 says a bare 'meeting' with the right details
is fine; whether that extends to 'appointment' (and to the program word
'event', which Gil's own gold on id=118 accepted) is his call — filed in
TASKS.md, not decided here.

## Registered next — cycle 36: a stated day beats a weekday

**Component:** the fast path's date reading (`rule_parser._extract_temporal`;
ids 11, 14, 21 are all `parse=fast`). **Change:** when the words name BOTH a
weekday and a stated day — "tomorrow", an ordinal "the 13th" — the stated day
wins and the weekday is a (possibly wrong) gloss; today the weekday wins.
**Prediction:** generic-title right/acceptable 14 → 17 of 21; corrected tier
unmoved (those three rows are rejected-tier); dev-100 unmoved or up — the
synthetic pool rarely states a day twice. Boarded on FastRule's own board
first.

---

# Run 5 — 2026-09-22, cycle 36: a stated day beats a weekday

Fresh replay, guard passed. One change, on the fast path only
(`rule_parser._extract_temporal`): when the words name both a weekday and a
STATED day — "tomorrow", "today", "the 13th", a month-day — and the two
disagree, the stated day wins. It ran both ways: a weekday carrying the clock
no longer overrides a "tomorrow" read before it (*"tomorrow on tuesday at
6pm"*), and a date read from a weekday alone yields to an ordinal elsewhere in
the words (*"monday the 13th"*, *"on the 14th on tuesday"*). "book monday
standup tomorrow at 9am" still lands on tomorrow.

| | cycle 35 | **cycle 36** |
|---|---|---|
| generic-title right/acceptable under Q41 (21 rows) | 66.7% (14) | **81.0% (17)** |
| …items where the subject was said, title AND when right | 12/15 | **15/15** |
| corrected, every reachable field (n=15) · date · start_time | 20.0% · 82.4% · 62.5% | 20.0% · 82.4% · 62.5% |
| approved reproduced (17) · rejected changed (42) | 64.7% · 90.5% | 64.7% · 90.5% |

**Prediction was 14 → 17; it is 17.** Corrected tier unmoved, as predicted
(the three rows are rejected-tier). FastRule's board (4,800 train rows):
byte-identical — the corpus never states a day twice. dev-100: **75 → 76%
count-correct, precision 91.7 → 93.0%**, F1 80.0 → 80.5, field quality 91.9%
(one row: one fewer wrong create). Not zero, so the change reached past real
speech, and in the right direction.

**What is left of the generic-title class (4 of 21):** two are refusals
waiting on the Q38/Q41 ruling (id=18 'appointment', id=118 'event'); id=12
*"today i have an event at 6 o'clock a meeting"* is a statement whose title
is the whole clause; id=26's second item keeps a trailing "as well". Every
row where the speaker named the thing is now right on title, day and clock.

## Registered next — cycle 37: disfluent speech

The corrected tier's item COUNT fell 80 → 60% between 09-18 and 09-21
(measured for the first time in run 4) and did not recover: id=56 *"set a
date for tomorrow at 11 o'clock, in one second, one moment, one moment, bear
with me, i want to be at …"* makes 3 items for 1; id=136 *"…, and I need to
also buy, Conello oil, can, execute"* 3 for 2; id=23 keeps *"excuse me.
excuse me."* in its title; id=39 keeps *"sorry, i mean edo"* because the
self-correction rule needs a comma BEFORE "sorry". **Component:** ingest's
spoken-noise passes (`intent/cleanup.py`, aim (a): generic, no vocabulary):
a trailing interjection sentence ("excuse me." repeated), hold-on chatter
("in one second", "one moment", "bear with me"), and a self-correction
whose comma comes after the marker. **Prediction:** corrected item count 60
→ 73%+ (n=15; ids 56 and 136), corrected title +1 (id=23 is rejected-tier
— so the title column moves on the Q41 list, not here); dev-100 unmoved
(the pool has no such chatter); every rewrite counted over the 9,091 clean
rows first, because a noise pass that eats a real word is invisible to the
speaker.

---

# Run 6 — 2026-09-22, cycle 37: disfluent speech

Fresh replay, guard passed. Ingest's spoken-noise passes (`intent/cleanup.py`)
learned a trailing interjection ("…. excuse me. excuse me."), the hold-on
chatter ("in one second, one moment, bear with me,"), and a one-word
self-correction ("with pelic sorry, i mean edo"); the filler pass stopped
eating ", i mean," before the self-correction rule could see it. Zero of
9,091 clean corpus outputs changed.

| | cycle 36 | **cycle 37** |
|---|---|---|
| corrected, every reachable field (scored rows) | 20.0% (15) | 21.4% (14) |
| corrected, item count right | 60.0% | **64.3%** |
| corrected `title` · `date` · `start_time` | 35.3% · 82.4% · 62.5% | 37.5% · 82.4% · 62.5% |
| generic-title right/acceptable under Q41 (21 rows) | 81.0% (17) | **76.2% (16)** |
| approved reproduced · rejected changed | 64.7% · 90.5% | 64.7% · 90.5% |

**A mixed cycle, read row by row.** Prediction was corrected item count 60 →
73%+; it is 64.3%. What moved:

- **Fixed:** id=23 *"…at 6.30. excuse me. excuse me."* no longer carries the
  interjection in its title; id=39 *"…with pelic sorry, i mean edo"* is now
  'meeting with edo'; id=56's hold-on chatter no longer cuts the command into
  three asks.
- **Exposed, not fixed:** with the chatter gone, id=56 *"set a date for
  tomorrow at 11 o'clock, …"* is a bare 'date' and the Q38 gate REFUSES it —
  nothing created. That is the same open ruling as 'appointment' (id=18) and
  'event' (id=118): **three rows now wait on whether Q41's "a bare title is
  fine" reaches the words Q38 refuses.** The row also leaves the scored set
  (its gold title, day and clock were all hand-set), which is why n is 14.
- **Regressed:** id=54 *"Set a meeting on this coming Sunday for 1 p.m. TA,
  Office Hour, meeting, excuse me."* With ", excuse me." gone the tail reads
  "TA, Office Hour, meeting" — three comma-separated things — and the
  coordinated-subject rule (Gil, 2026-09-20: one event whose words list three
  or more things is rewritten one per thing) splits it into three events.
  Before, the interjection kept the list from being seen. The rule is doing
  what it was told; whether a comma list with NO conjunction ("A, B, C" as
  opposed to "A, B and C") should count as a list is a ruling, filed.
- **dev-100 75% (was 76%)**: the one row that moved is *"let's just skip
  appointment at time"*, a deep-path row the model answers differently across
  a gap (cycle 34's "one row can flip"); its words carry none of the shapes
  this cycle touches. Precision, recall, F1 and field quality are cycle 35's
  numbers to the tenth.

## What the day did, start to finish

| real usage, fresh replays | start of day (pre-35) | **end of day (cycle 37)** |
|---|---|---|
| generic-title right/acceptable under Q41 (21 rows) | 52.4% | **76.2%** |
| …items where the subject was said, title AND when right | 9/15 | **14/15** |
| corrected, every reachable field right | 13.3% (n=15) | 21.4% (n=14) |
| corrected `date` · `start_time` | 76.5% · 56.2% | **82.4% · 62.5%** |
| corrected item count right | 60.0% | 64.3% |
| approved reproduced | 64.7% | 64.7% |
| dev-100 count-correct · precision | 75% · 91.7% | 75% · 91.7% |

Three cycles, each moving only this board, each with every stage board
identical and zero rewrites on 9,091 clean rows: the classes Gil's speech
fails on do not exist in any constructed corpus, which is why this
instrument outranks the others and why it must never serve a cache again.

## Registered next

The milestone run on the sealed 300 (`--test`, aggregates only), as the
plan behind "can we consider it done" set out — after that, the next real-
usage cycle waits on one ruling with three rows behind it (bare 'date',
'appointment', 'event' under Q38 vs Q41) and one with one row (a comma list
without a conjunction).

---

# Run 7 — 2026-09-22, cycle 38: a comma run with no conjunction is not a list (Q43)

Fresh replay, guard passed. One change: `coordination.noun_list` needs an
"and" or "or" among its separators. id=54 *"…for 1 p.m. TA, Office Hour,
meeting"* is one event again.

| | cycle 37 | **cycle 38** |
|---|---|---|
| generic-title right/acceptable under Q41 (21 rows) | 76.2% (16) | **81.0% (17)** |
| …items where the subject was said, title AND when right | 14/15 | **15/15** |
| corrected, every reachable field (n=14) · item count | 21.4% · 64.3% | 21.4% · 64.3% |
| approved reproduced · rejected changed | 64.7% · 90.5% | 64.7% · 90.5% |
| dev-100 count-correct · precision | 75% · 91.7% | **76% · 93.0%** |

FastRule's board (4,800 train rows) byte-identical: its generated lists all
carry an "and". dev-100's +1 is the same deep-path row that flipped down in
cycle 37 flipping back (cycle 34's "one row across a gap"), not the change.
What is left of the class: two refusals (id=18 'appointment', id=118 'event')
that Q42 — ruled the same afternoon — turns into commits in cycle 39, one
statement (id=12), one trailing "as well" (id=26).
