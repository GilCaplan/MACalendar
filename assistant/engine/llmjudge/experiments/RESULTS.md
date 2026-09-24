# LLMJudge — the run log

The board is `judge_board.py`; the data is `../datasets/judge_cases.jsonl`.
**Every number here names its dataset, its metric and what it MEANS.** The
metric is always a PAIR — catch rate on planted defects AND false-flag rate on
clean ones — because always-accept wins one and always-reject wins the other.

---

## Cycle 1 — the first board, 2026-09-10

**BASELINE.** The rebuilt judge (PLAN.md §6), no tuning, first read.

    LLMJudge isolation board · train half · 110 scored cases (40 skipped:
    the converter declined) · 1173 s

    mutation          planted  caught  catch rate   collateral
    dropped_date           20      20      100.0%            0
    dropped_time            7       7      100.0%            0
    missing                13      13      100.0%            0
    not_asked              19      19      100.0%           38
    generic_title          20      14       70.0%            0
    invented_title         16       4       25.0%            0
    ALL PLANTED            95      77       81.1%

    false-flag rate    1/15 = 6.7%

**What it MEANS.** The stage catches four fifths of planted defects while
complaining about one clean object in fifteen. But the headline is the least
interesting line on the board, and the split under it is the whole result:

- **Everything DETERMINISTIC is at 100%.** `dropped_date`, `dropped_time` (the
  `item.slots` check) and `missing`/`not_asked` (the coverage diff) do not miss.
  That is the design paying off exactly where it was aimed: the decision to keep
  the temporal fields away from the model and read `item.slots` instead was
  taken on a *reasoning* about pydantic defaults, and it holds.
- **Everything MODEL-DEPENDENT is the weak half**, and `invented_title` at
  **25% (4/16)** is the binding constraint. A fabricated title — a plausible
  calendar noun whose every word is absent from the transcript — is waved
  through three times in four.

**And that is the accept bias, measured on our own model.** The grounding pass
asks the model to quote the supporting words or answer `none`. It rarely answers
`none`: it quotes something loosely related instead. This is the exact failure
the stage's founding rule was written against, and finding it at 25% rather than
at 0% is only because `_GENERIC_TARGET_RE` and the coverage diff catch some of
the same rows by another route.

**Two things the failing rows say that the number does not.** Several
`generic_title` misses came back with `['missing', 'extra']` instead of
`ungrounded_subject` — the object was still flagged and still routed to a
rewrite, just under a different finding. So the practical miss rate is lower
than the per-mutation rate, and the board is being strict about WHICH finding
fires, which is the right strictness for improving it. And the 38 collateral on
`not_asked` are the planted object's own unsupported date and time — the
machinery working, not a defect.

---

## Cycle 2 — PREDICTION, registered before the run

**Hypothesis.** Title grounding is being asked of the model when it is largely
answerable WITHOUT one. Two deterministic checks are already in this folder and
neither is wired into the verdict:

- `_GENERIC_TARGET_RE` (gatekeeper.py) — is the title only the program's own
  noun for a calendar entry? That is Gatekeeper's generic-title veto, and it
  needs no model at all.
- `_grounded_title` (llm_fallback.py) — is every content word of the title
  spoken in the transcript? Already trusted enough to DROP a fabricated event in
  the rescue path, so trusting it merely to FLAG one here is strictly weaker.

Wire both as deterministic subject checks, and demote the model's citation to a
third opinion for the paraphrase cases the two miss.

**Predicted:** `invented_title` 25% → 85%+ and `generic_title` 70% → 95%+, since
a planted fabrication has no word in the transcript by construction.
**Predicted cost:** the false-flag rate RISES — a legitimately paraphrased title
("ring my mother" → "call mom") is ungrounded by this test and would be flagged.
That is the trade the pair exists to price. If false-flag goes above ~15% the
check is too blunt and the citation-verification variant is next instead.

**What would REFUTE it:** `invented_title` staying under 50%, which would mean
the fabricated titles are somehow grounded in the words and the plant is weaker
than it looks.

### Cycle 2 — RESULT, 2026-09-10

    LLMJudge isolation board · train half · 110 scored cases · 1298 s

    mutation          planted  caught  catch rate            collateral
    dropped_date           20      20      100.0%   (=)               0
    dropped_time            7       7      100.0%   (=)               0
    missing                13      13      100.0%   (=)               0
    not_asked              19      19      100.0%   (=)         38 → 51
    generic_title          20      20      100.0%   (70.0 → 100.0)    4
    invented_title         16      15       93.8%   (25.0 →  93.8)    8
    ALL PLANTED            95      94       98.9%   (81.1 →  98.9)

    false-flag rate    1/15 = 6.7%   (6.7 → 6.7, UNCHANGED)

**Predicted vs actual.** `invented_title` 25% → **93.8%** (predicted 85%+ —
beaten). `generic_title` 70% → **100%** (predicted 95%+ — beaten). Catch rate on
all planted defects 81.1% → **98.9%** on the FastRule-derived judge set, train
half: the stage now catches essentially every planted defect while complaining
about one clean object in fifteen.

**The NOVEL effect, and it is the interesting one: the predicted cost never
arrived.** The false-flag rate was predicted to RISE and did not move at all.
The reason is the mid-cycle correction: the first cut used `_grounded_title`
(every content word must be spoken) and immediately flagged an event titled
"gym session" built from "gym saturday". Softening the line to ZERO overlap
(`verdict.names_nothing_spoken`) kept the whole catch — a planted fabrication
has no word in the transcript by construction — while costing nothing, because
FastRule builds titles OUT of the words, so a real title always shares one.

**So the strict/loose distinction was the whole cycle**, and it generalises: a
test that guards a DROP and a test that raises a FLAG should not be the same
test. `_grounded_title` stays strict where it drops a fabricated event;
`names_nothing_spoken` is its weaker sibling where it only flags.

**What this says about the model.** Two cycles have now moved this stage's
headline 81 → 99 by taking work AWAY from the 8B and giving it to deterministic
code. The model-dependent path was the only weak half in cycle 1 and is no
longer the constraint. Worth remembering before reaching for a bigger model:
at this stage the model is not what is binding.

---

## Cycle 3 — PREDICTION, registered before the run

Two things left on the board, and only one of them is this stage's.

**The one remaining false flag is a RECALL-side over-extraction, not a verdict
bug.** "remove wash the car from my list, i already handled it" → `extract_asks`
returned "i already handled it" as a separate TASK, so the diff correctly
reported that nothing covers it. The judge is reasoning properly about a bad
ask list. That is `_EXTRACT_SYSTEM`'s counting rules, whose one gap is trailing
justification clauses — "i already handled it", "since I'm free then" — which
are commentary on an ask, never an ask.

**Prediction:** one added counting rule ("a clause explaining or justifying an
ask is part of that ask, never a new one") takes the false-flag rate 6.7% → 0%
with `ALL PLANTED` unchanged at ≥ 97%.

**Then the SEALED confirm.** `--split test` on the 900 held-out cases, reported
as aggregates only, no row detail, never mined. Train says 98.9/6.7; the test
half is what says whether that is real. **This is a pure eval — it may not spawn
a hypothesis**, per the standing rule.

### Cycle 3 — RESULT, 2026-09-10

    LLMJudge isolation board · train half · 110 scored cases · 901 s

    mutation          planted  caught  catch rate     collateral
    dropped_date           20      20      100.0%              0
    dropped_time            7       7      100.0%              0
    missing                13      13      100.0%              0
    not_asked              19      19      100.0%             49
    generic_title          20      20      100.0%              4
    invented_title         16      15       93.8%              5
    ALL PLANTED            95      94       98.9%   (98.9 → 98.9)

    false-flag rate     0/15 = 0.0%        (6.7 → 0.0)

**Predicted vs actual: exactly as registered.** One added counting rule in
`_EXTRACT_SYSTEM` — *"a clause that EXPLAINS, JUSTIFIES or COMMENTS ON an ask is
PART of that ask, never a new one"*, with the worked example — took the
false-flag rate to **0.0%** with the catch rate unmoved at 98.9%.

**What it MEANS.** The single false flag was never a verdict bug: `extract_asks`
had returned *"i already handled it"* as a separate TASK, and the diff correctly
reported that nothing covered it. The judge was reasoning properly about a bad
ask list. Fixing the ask list fixed the finding — which is the argument for
keeping the two directions of comparison SEPARATE, since a combined
"is this right?" prompt would have given no way to tell a recall error from a
precision one.

**Board reads, train half of the FastRule-derived judge set (110 scored cases):
catch rate on planted defects 81.1% → 98.9% over three cycles, false-flag rate
on clean objects 6.7% → 0.0%.** The stage now flags essentially every planted
defect and complains about none of the untouched ones.

**Two cautions on that pair, both mine to state:**

- It is a TRAIN number. The sealed 900-case test half decides whether it is real.
- The catch rate is inflated by construction on `not_asked` and `missing`, which
  a deterministic diff cannot miss once the ask list is right. The number that
  moved on merit is `invented_title`, 25% → 93.8%, and it moved by leaving the
  model out of the decision.

---

## Cycle 4 — SEALED CONFIRM (pure eval, no hypothesis)

`--split test`, 900 held-out cases, aggregates only. **This run may not spawn a
hypothesis and its rows are never read** — direction comes from training-pool
failures alone, the same rule as every other sealed set here.

### Cycle 4 — SEALED RESULT, 2026-09-10

    LLMJudge isolation board · TEST half · 77 scored cases
    (73 skipped: the converter declined) · 471 s

    mutation          planted  caught  catch rate      train was
    dropped_date           12      12      100.0%          100.0%
    dropped_time            4       4      100.0%          100.0%
    missing                14      14      100.0%          100.0%
    not_asked              13      13      100.0%          100.0%
    generic_title          10       9       90.0%          100.0%
    invented_title         13       9       69.2%           93.8%
    ALL PLANTED            66      61       92.4%           98.9%

    false-flag rate     2/11 = 18.2%                          0.0%

**The sealed set is worse than train, and that is the result.** Catch rate
**98.9% → 92.4%**, false-flag **0.0% → 18.2%**. The train numbers were
optimistic and **should not be quoted as this stage's performance**; these are.

**Where the gap is.** Entirely in the two model-dependent mutations —
`invented_title` 93.8% → 69.2% and `generic_title` 100% → 90%. Every
deterministic check held at 100% on both halves. So the deterministic half of
the design generalises perfectly and the model-dependent half does not, which is
the same finding cycle 1 made, now confirmed on held-out data.

**What is NOT concluded here.** This run may not spawn a hypothesis and its rows
were not read — the standing rule for every sealed set in this project.
Direction comes from training-pool failures alone. Noting *"invented_title is
the weak one"* is safe only because cycle 1 established it on the TRAIN half
first; nothing new is inferred from these rows.

**Two honest caveats on the numbers themselves**, neither of which rescues them:

- 73 of 150 cases were skipped because the converter declined, so 77 scored.
  Small.
- The false-flag denominator is **11 clean cases**. 2 flags reads as 18.2% but
  the interval around it is very wide. It is evidence that the rate is not zero,
  not a measurement of what it is.

**Standing board, LLMJudge isolation, sealed test half (77 cases): catch rate on
planted defects 92.4%, false-flag rate on clean objects 18.2%.** The train half
reads 98.9 / 0.0 and is the mining set, not the score.

---

## Cycle 5 — next, and it is a DATA cycle not a tuning one

The sealed gap is concentrated in the model-dependent path, and the clean-case
denominator is too small to steer by. Before any more tuning: **grow the clean
slice**. `datasets/generate.py` emits roughly one clean case in seven because
the mutation is chosen uniformly at random per row; the false-flag rate is the
number most likely to block shipping and it has the fewest rows behind it. A
50/50 clean-to-planted split costs nothing but generation time and would make
both halves of the pair equally trustworthy.

---

## Cycle 5 — THE RESTRUCTURE, 2026-09-10

**The stage changed shape** (Gil): the ask extraction is gone, so this board's
mutation set changed with it and **cycles 1–4 are not comparable to what
follows**. `missing` and `not_asked` are no longer findings this stage can make;
`near_miss_title` and `unrelated_object` are new.

### First, a VOID run and why it is recorded

The first attempt printed a full table **in 2 seconds**: `ALL PLANTED 70.9%`,
`near_miss_title 5.3%`, every deterministic check at 100%. Ollama had died
mid-session and `ground_claims` swallowed the connection error and returned
`None`, so only the free checks ran. It read like a finding about near misses
and was an artefact of a missing model.

**The board now pings the model and ABORTS rather than reporting.** A board that
degrades quietly is worse than one that crashes: the crash costs a minute, the
quiet number costs a decision. Recorded because the numbers were nearly banked.

### The real read

    LLMJudge isolation board · train half · 141 scored cases
    (59 skipped: the converter declined) · 523 s

    mutation           planted  caught  catch rate
    dropped_date            10      10      100.0%
    dropped_time             3       3      100.0%
    unrelated_object        15       7       46.7%
    generic_title           14      12       85.7%
    invented_title          18      15       83.3%
    near_miss_title         19       1        5.3%
    ALL PLANTED             79      48       60.8%

    false-flag rate      0/62 = 0.0%

**Board reads: catch rate on planted defects 60.8%, false-flag rate 0.0%, on the
train half of the rebuilt judge set (141 cases).** The false-flag denominator is
now 62 rather than 11, which was the point of rebalancing the set.

### What it MEANS — two findings, one of them mine

**1 · `near_miss_title` 5.3% (1 of 19): the model adds nothing on the only case
that is its to decide.**

A near miss shares a CONTENT word with the transcript and names the wrong thing
— "meeting groceries" from *"book a meeting with Sage this evening"*. The
deterministic test structurally cannot see it (a word IS spoken), so this is the
one mutation where the model's answer decides. It clears them: shown a partially
overlapping title, it quotes the overlapping part and calls the field supported.

That is the accept bias again, now measured on the case built specifically to
expose it. **The honest summary of this stage is that the deterministic checks
carry it and the model contributes close to nothing.**

**2 · `unrelated_object` 46.7% was MY defect, now fixed.**

Every miss had the same signature: the object WAS flagged `ungrounded_subject`
deterministically and correctly, while `not_an_ask` was suppressed — because
`_not_an_ask` let a positive grounding answer clear a claim the deterministic
test had already failed. The model cheerfully quoted something for the title of
an event nobody mentioned, and that cleared the object.

Letting a model overturn a deterministic verdict is backwards, and the board
priced it at 8 rows in 15. `verdict._not_an_ask` no longer consults the model
where `names_nothing_spoken` has already answered.

---

## Cycle 6 — PREDICTION, registered before the run

**From fix 2:** `unrelated_object` 46.7% → 90%+, nothing else moving, false-flag
staying at 0%. It is a suppression being removed, so the only risk is that some
of those 62 clean cases were being spared by the same suppression.

**On `near_miss_title`, a hypothesis for AFTER that run — not bundled with it:**
the prompt asks the model to VALIDATE a title it has been shown, and a shown
title is an anchor an 8B will rationalise. Asking it to PRODUCE one instead —
*"what is this event called, in the speaker's own words?"* — and diffing its
answer against the object deterministically keeps the founding rule (the model
extracts, code judges) while removing the anchor. Registered, not run: bundling
it with fix 2 would make neither attributable.

### Cycle 6 — RESULT, 2026-09-10

    mutation           planted  caught  catch rate        was
    dropped_date            10      10      100.0%     100.0%
    dropped_time             3       3      100.0%     100.0%
    unrelated_object        15      15      100.0%      46.7%
    generic_title           14      12       85.7%      85.7%
    invented_title          18      15       83.3%      83.3%
    near_miss_title         19       1        5.3%       5.3%
    ALL PLANTED             79      56       70.9%      60.8%

    false-flag rate      0/62 = 0.0%                     0.0%

**Predicted 90%+, actual 100%, and nothing else moved** — which is what makes it
attributable. Removing one suppression fixed exactly the rows it was suppressing.
The worry that some of the 62 clean cases were being spared by the same
suppression did not materialise: false-flag stayed at 0.0%.

**Board reads: catch rate 70.9%, false-flag rate 0.0%, train half, 141 cases.**

**The constraint is now unambiguous and singular: `near_miss_title`, 1 of 19.**
Every other mutation is at 83% or above. A near miss is the ONLY case whose
answer belongs to the model, and the model gets 5% of them.

---

## Cycle 7 — the near-miss hypothesis

**Diagnosis.** The prompt SHOWS the model a title and asks which words support
it. A shown value is an anchor, and an 8B rationalises anchors — given
"meeting groceries" against *"book a meeting with Sage"*, it quotes "meeting"
and calls the field supported. Every near-miss failure has that shape.

**Change.** Stop asking the model to VALIDATE a title. Ask it to PRODUCE one:
*"what does the command call this thing?"* — then diff its answer against the
object's title in code. The model still only extracts; the anchor is gone.

**Predicted:** `near_miss_title` 5.3% → 60%+, `invented_title` and
`generic_title` steady or better (both become the same comparison), false-flag
rising somewhat — a produced name that legitimately differs in wording from a
good title is a new false-positive path, and that is the cost to price.
**Refuted if** near_miss stays under 25%, which would say the anchor was not the
mechanism and the model simply cannot do this task.

### Cycle 7 — RESULT: **REFUTED, and reverted**

    train half · 55 scored cases · 280 s      (cycle 6 was 141 cases)

    mutation           planted  caught  catch rate       cycle 6
    dropped_date             5       5      100.0%        100.0%
    dropped_time             2       2      100.0%        100.0%
    unrelated_object         5       5      100.0%        100.0%
    invented_title           9       9      100.0%         83.3%
    generic_title            8       7       87.5%         85.7%
    near_miss_title          6       0        0.0%          5.3%
    ALL PLANTED             35      28       80.0%         70.9%

    false-flag rate      6/20 = 30.0%                       0.0%

**The prediction was `near_miss_title` 5.3% → 60%+. It went to 0.0%, and the
false-flag rate went 0% → 30%.** Refuted on the primary claim and the cost came
in worse than priced. Reverted.

**The mechanism, which is the useful part.** Both halves are structural, not
tuning:

- **A near miss cannot be caught by comparing a produced name to the title.** It
  shares a CONTENT word with the transcript *by definition* — that is what makes
  it near. So the produced name shares that word too, and any overlap test says
  the two agree. "meeting groceries" vs the model's "meeting with Sage": both
  contain "meeting", so they match. The approach cannot see the case it was
  built for.
- **A legitimate title often differs from the obvious name.** The clean row
  *"book a meeting with Dana to discuss oil change"* is titled **"oil change"**
  by FastRule and named **"meeting with Dana"** by the model. Both are correct
  readings of the same sentence. Six of twenty clean cases were like this — the
  30% is mostly this, not model error.

**What was really learned.** `invented_title` DID improve, 83.3% → 100%: hiding
the title stops the model rationalising toward it. But that gain rode on a
comparison that cannot be made safe, because "what is this called" has more than
one right answer and the check has to treat disagreement as a defect.

### Standing board after the revert (= cycle 6)

    catch rate 70.9% · false-flag 0.0% · train half, 141 cases
    dropped_date 100 · dropped_time 100 · unrelated_object 100
    generic_title 85.7 · invented_title 83.3 · near_miss_title 5.3

**`near_miss_title` is UNSOLVED and may not be this stage's to solve.** Three
cycles have now established that every deterministic check saturates and every
model-dependent one plateaus. The near miss is the only defect whose answer is
genuinely the model's, and llama3.1:8b does not make it — not by validating a
shown title (cycle 5: 1/19) and not by producing one (cycle 7: 0/6).

**Do not spend a fourth cycle on the prompt.** The honest options are a stronger
model for this one question, or accepting that a title which shares a word with
the command and names the wrong thing gets committed — and saying so in
`ARCHITECTURE.md` rather than leaving a 5% number looking like a bug to fix.

---

## Cycle 8 — NEXT, and it is not more prompt work

The sealed confirm on the rebuilt set. Cycles 5–6 changed the mutation set, so
the last sealed read (92.4/18.2) measures a stage that no longer exists. One
`--split test` run, aggregates only, no hypothesis.

### Cycle 8 — SEALED CONFIRM on the rebuilt set, 2026-09-10

    test half · 97 scored cases (103 skipped: the converter declined) · 344 s

    mutation           planted  caught  catch rate     train half
    dropped_time             1       1      100.0%         100.0%
    unrelated_object        11      11      100.0%         100.0%
    generic_title           13      12       92.3%          85.7%
    dropped_date            13      12       92.3%         100.0%
    invented_title           8       7       87.5%          83.3%
    near_miss_title          6       0        0.0%           5.3%
    ALL PLANTED             52      43       82.7%          70.9%

    false-flag rate      0/45 = 0.0%                         0.0%

**Standing board: catch rate 82.7%, false-flag rate 0.0%, sealed test half of
the rebuilt judge set (97 cases).**

**Read the ROWS, not the aggregate.** 82.7% beats the train half's 70.9%, and
that is not the stage improving — the two halves have different mutation mixes
(near_miss is 6 of 52 here against 19 of 79 there, and near_miss is the row that
scores near zero). The aggregate is mix-dependent and should not be compared
across halves. **Per mutation it generalises**: every row is within a few points
of train, four of six are at or above it, and the false-flag rate is 0.0% on 45
clean cases — a real denominator this time, where cycle 4's was 11.

**Contrast with the last sealed read before the restructure (92.4 / 18.2).** That
measured a stage that no longer exists — it had the ask extraction, and its
false-flag rate came from the extraction inventing asks. Removing it took
false-flag to zero on both halves.

**near_miss_title is 0.0% here and 5.3% there: the same unsolved case, confirmed
on held-out data.** Cycle 7 established it is structural. It is not a tuning gap
and should not be treated as one.


---

## Cycle 9 — the REWRITE, tuned against the parser it feeds, 2026-09-10

Gil: *"tune the prompt for the LLMJudge step whilst understanding well how the
segmentation, the decompose_validate steps, and the fastrule steps work, and
using that information to tune the new derived prompt."*

The prompt had been written from general principles. It is now written from
measurements of the three stages it feeds.

### What the stages actually do — measured, not assumed

    verbs + " and "        -> 2 items          full stops   -> 1 item
    verbs + " and then "   -> 2 items          commas       -> 1 item
    bare nouns + "and"     -> 1 item

**Full stops do not split.** The old prompt said "put each ask on its own
clause", and a model left to its instincts writes sentences — which merge into
one ask and keep the stray punctuation (`"book gym . add milk to my list"`).
Only a verb-initial ask joined by *and* cuts. This is the one that would never
have been guessed.

Through decompose_validate and FastRule:

    book dentist next tuesday at three      -> title 'dentist'              no clock
    book THE dentist next tuesday at three  -> title 'the dentist at three'  <- leak
    book dentist on next tuesday at 3pm     -> title 'dentist'  start_time 15:00
    dentist appointment next tuesday        -> Defer (no verb -> no operation)

So: verb first, join with *and*, no definite article, digit times with am/pm.
Segmentation's own board explains why the shape matters — under-split 95 vs
over-split 28, and 1-ask rows score 71.8% against 2-ask at 53.9%.

**One consequence:** rule 4 tells the model to write "3pm" where the speaker said
"three", and the grounding guard would have rejected every rewrite that obeyed.
Digit time tokens are now exempt — a normalisation of something that WAS said is
not the invention the guard exists to stop. A new subject still is.

`tests/unit/test_rewrite_targets_the_parser.py` pins all four against the real
chain: a prompt that instructs a model in downstream behaviour is a CLAIM about
that behaviour, and nothing else in the suite would notice it going stale.

### Then the rewrite board, which found the real ceiling

`experiments/rewrite_board.py`, 80 rows:

    rows the chain got wrong first pass          9
    ...the judge raised NO rewritable finding    9      <- unreachable by any prompt
    an honest X1' was produced for               0

**Zero.** Not one failing row reached the rewrite, so the retune — correct as it
is — currently applies to nothing. Three blind spots, from the rows:

| | |
|---|---|
| a title that is a grounded FRAGMENT — "quinn" for "talk to Quinn" | 4 of 9 |
| a title that is a bare pronoun — an event titled **"i"** | 1 of 9 |
| a wrong OPERATION — `delete_todo` where the words said create | 1 of 9 |

### Fixed: the pronoun

`_GENERIC_TARGET_RE` held you/it/me/this/that/them and not `i`. A one-character
title survives every other check — the content-word filters drop it, so
`names_nothing_spoken` sees an empty word list and returns False. Measured:
*"i'm free christmas day so book staff meeting at 5 pm"* produced an event
titled **"i"** with no finding against it. `i`, `we`, `us` added. Costs nothing:
zero of the 880 clean cases have a title that is exactly one of those.

### Measured, priced, REJECTED: the dropped-verb check

The fragment class is the big one, so it was worth trying. A title that drops
the action — "quinn" for "talk to Quinn" — is detectable, and both cuts worked:

    any non-command verb dropped   catch 70.9 -> 86.1   false-flag 0.0 -> 61.3%
    only an EMBEDDED verb (xcomp)  catch 70.9 -> 77.2   false-flag 0.0 -> 27.4%

**Rejected.** Six points of catch for twenty-seven of false flags is not a trade
worth making against a 0.0% baseline — a quarter of CORRECT commands sent back
around is the loop-storm pathology this stage was rebuilt to end. The code is
kept unwired with its numbers, because the measurement is the useful part.

**But it refutes cycle 7's conclusion.** `near_miss_title` went 5.3% → **42.1%**
under the first cut. It is NOT structurally unsolvable, as cycle 7 claimed — it
is solvable at a price nobody should pay yet. The earlier wording was too strong
and this supersedes it.

### Where this leaves the loop

**The rewrite prompt is now correct and provably fits the parser. The loop still
almost never fires**, because the judge's three findings do not cover the ways
the chain actually fails on this corpus. That is the ceiling, it is upstream of
any prompt, and it is the thing to fix next — not the prompt.


---

## Cycle 10 — the TRIM becomes deterministic, 2026-09-10

Gil: *"what if the succeeded objects, we take the text in those which are not
stop words and remove those words from the original phrase, then have the LLM
fix up the new broken string?"* — and then: *"a change I would add is for
segmentation to add a feature to the existing three: the original substring that
item was made from."*

### First, the question that prompted it: was the old trim working?

Measured, three multi-ask commands with one object failed in each:

    "book gym tomorrow at 7am and add milk to my list"   kept 'gym'   leak: none
    "book dentist … and sort out the car thing"          kept 'dentist' leak: none
    "add milk … and call the plumber and book gym"       kept 'milk'  leak: none

**Yes — but by INSTRUCTION.** The model was shown the finished objects and told
to leave them out, and it obeyed. That is a property of this model on these
three rows, not a guarantee.

### The change: `Item.source`, a fourth value from segmentation

A DELIBERATE contract addition, recorded in `state.py`, `test_engine_contracts.py`
and ENGINE.md. Segmentation now carries the VERBATIM substring each item was cut
from, beside (action, time, tag).

**Why `text` could not do this job.** The time has been split off it and
`decompose_validate` may repair its words, so by the time anything wants to
subtract a finished ask from the command, `text` is no longer a substring of
anything. The span is.

**Why a SPAN and not a word set** — this is the part Gil's first formulation
would have hit. Subtracting the finished ask's WORDS from "book gym and book
dentist" takes the shared verb with them and leaves the survivor unparseable. A
contiguous span cannot: it removes exactly one ask and nothing else. Pinned by
`test_a_shared_verb_survives_the_trim`.

An ENUMERATION shares one span across its items ("walk the dog at 9 and 2:30"),
so removing it once removes both — correct, since they were one ask.

### What it buys

    BEFORE   model is shown the finished objects, told "leave these out"
    AFTER    the finished spans are GONE before the model sees anything

Two consequences, and the second matters more:

1. **No double commit BY CONSTRUCTION.** A succeeded object cannot appear in
   X1' because its words are not in the input. Models are poor at negation; this
   stops asking them to do any.
2. **The model's job shrinks to REPAIR.** Not "select the failed parts and
   reword them" but "make this fragment into a command" — the task it is good
   at, and the one the grounding guard already fits, since the residue is made
   only of the speaker's own words.

The prompt was rewritten to match: it now says the understood parts *have been
cut out*, and asks for a repair.

### Measured end to end

    command                                          residue                         X1'
    "add milk … and call the plumber and book gym"   "call the plumber and book gym"  "call plumber and book gym at 7am"
    "book dentist … and sort out the car thing"      "sort out the car thing"         "sort out car"
    "book gym … and add milk to my list"             (unchanged — see below)          None

**The known limit, visible in row three: the trim is only as precise as the
CUT.** Segmentation under-split that command into ONE item whose span is the
whole string, so nothing could be removed, the residue equalled the original,
and the unchanged-string guard correctly refused to spend a round. That is the
right failure — and it is segmentation's under-split, which its own board
already names as the binding constraint (95 under vs 28 over on sealed).


---

## Cycle 11 — five ways to build X1', and the model loses, 2026-09-10

Gil: *"test different versions of my idea and decide what's best… the llmjudge
is how can we fix the prompt to send back in a more deterministic way."*

`experiments/x1_variants.py`. Each row is a real multi-ask command; its FIRST
object is treated as succeeded and the rest as failed, so every variant faces
the same job — carry the failures forward, leave the finished one behind.

    60 multi-ask rows, train half
    variant                    recovered  leaked  empty   net
    C failed spoken()                 54       8      0     46   <- CHOSEN
    D failed spans                    54       8      0     46
    B residue raw                     53      18      2     35
    E residue + code reshape          50      18      2     32
    A residue + LLM repair            41      13     10     28   <- worst

    (100 rows without the model: C/D 92-15 net 77 · B 87-28 net 59 · E 85-28 net 57)

### The model made it WORSE, on every axis

Fewer asks recovered (41 vs 54), more finished asks leaked back in (13 vs 8),
and **ten rows where the guard had to refuse what it wrote**. Asking a model to
rebuild a command out of pieces it can see is asking it to paraphrase, and a
paraphrase is the one thing X1' must not be.

**So the rewrite path now calls no model at all.** The most deterministic
construction is also the best one, which is the answer to the question as asked.

### Building from the failures beat SUBTRACTING the successes

That is the first shape of Gil's idea (B and E), and it loses to C/D by 11
points of net. A subtraction leaves seams and shared context that re-parse into
the finished ask again — **18 leaks against 8**. Cutting the finished span out
is exact, but what is left around the cut still carries the finished ask's
grammar.

**`Item.source` still earns its place**: it is what makes an exact subtraction
possible at all, it is variant D, and `residue()` is kept with its measured
number so the alternative is documented rather than remembered.

### E is the one worth noting

Reshaping the residue in CODE toward the four measured parser rules made it
slightly WORSE than leaving it raw (32 vs 35). Rule 1 — every ask needs its own
verb — is the one that matters most and the one code cannot do, because
inventing a verb is exactly what the grounding guard exists to stop. The other
three were not enough on their own.

### `spoken()` over `source`, on a tie

They scored identically. `spoken()` wins the tie-break because when
`decompose_validate` splits one span into sub-items they SHARE a source, so
spans would carry a sibling back alongside the failure while `spoken()` carries
only what failed.

### What is now true of X1'

    built by CODE from the failed items' own words · no model call
    the finished asks cannot appear — they are not in the input
    unchanged input is refused, so an under-split command spends no round
    the grounding guard stays as a net for a repaired-but-invented word


---

## Cycle 12 — the one remaining model call buys NOTHING, 2026-09-10

Gil: *"where would an LLM be useful if we had to use only one llm call in the
llmjudge round?"* — the first half is measurable, because the stage already has
exactly one.

`judge_board --no-grounding` runs the identical rows with `ground_claims`
returning None:

    with the grounding pass      75.9% catch · 19.4% false-flag · 510 s
    WITHOUT it                   75.9% catch · 19.4% false-flag ·   3 s

**Every per-mutation figure identical. 170x faster.** The one model call in this
stage contributes nothing at all.

**Why, and it was built this way on purpose without anyone noticing the
consequence.** Cycle 2 put the deterministic subject checks FIRST with a
`continue`; cycle 6 stopped the model overturning a deterministic verdict. Between
them, the model's answer is now consulted only for a claim that passed both
deterministic tests — and on this corpus that set is empty of disagreements. Each
change was right on its own board. Together they hollowed out the call neither
was looking at.

### Also caught: the fragment check was 19.4%, not 0.3%

An offline proxy against GOLD titles said 0.3% false flags on train. The board,
running the real chain, said **19.4%** — the PRODUCED title differs from the gold
one far more often than the proxy assumed. Reverted, and the baseline returns to
**73.4% catch / 3.2% false-flag with no model at all, in 2 seconds**.

Two rounds of tuning against a cheap approximation bought nothing. The project's
own rule covers it — *before trusting any board, run it* — and a hand-rolled
proxy is not a board. (The 2 remaining false flags were not individually
inspected; the display filled with near-miss misses before reaching them.)

### So where WOULD one call be useful

The pattern across five cycles is consistent. The model fails at **fine-grained,
span-level, high-cardinality** judgements:

    per-field grounding          contributes 0 (this cycle)
    validating a shown title     1 of 19 near-misses (cycle 5)
    producing a name             0 of 6, +30% false flags (cycle 7)
    rebuilding X1'               worst of five constructions (cycle 11)

Every one asks *"which of these many words"* or *"is this subtly wrong"*.

What is left UNCOVERED is the opposite shape — coarse, two-way, semantic, and
impossible for the deterministic code:

1. **THE OPERATION.** Create something new, or change something that exists?
   Cycle 9 found a wrong operation in 1 of 9 real failures — `delete_todo`
   where the words asked to CREATE a to-do called "cancel the subscription".
   Nothing in this stage checks operations at all, and the product-shape board
   already weights a wrong delete at 4x a wrong create, so it is the most
   expensive class to get wrong.
2. **THE KIND.** Event or to-do? Segmentation's tag accuracy is 89.7% and its
   error is ONE-DIRECTIONAL — event read as task, 116 of 175 — which gives a
   targeted check a clear prior.

Both are two-way questions about meaning, which is what an 8B is good at, and
both name a defect that actually occurs. **Operation is the higher-value target**
because the cost is asymmetric: a wrong kind puts a row on the wrong screen, a
wrong delete destroys data.

**Recommended, pending Gil:** spend the one call on *"does this command ask to
create something new, or to change or remove something that already exists?"* —
once per command, on the raw text, with the produced operations shown. A
disagreement becomes a finding. Not built: which question the single call asks
is a design decision, not an implementation one.


---

## Cycle 13 — the operation check REFUTED, and the board finally run at size

### The recommendation from cycle 12 does not survive contact

Cycle 12 recommended spending the single model call on *create vs change*. A
probe measured it (`/tmp/op_probe.py`, the shape is in this entry):

    82 rows    FastRule 93.9%  ·  model 96.3%  ·  6 disagreements  ·  net +2
    266 rows   FastRule 95.9%  ·  model 96.6%  · 18 disagreements  ·  net +2
                                     10 would FIX  ·  8 would BREAK

**Ten fixes against eight breaks is a coin flip.** The model is not reliably
better than FastRule at this, and net +2 over 266 rows does not justify 3.6
seconds per command or the risk of overturning a correct destructive operation.
**Not built.** The recommendation was wrong and this supersedes it.

### Every candidate for the one call has now been measured and rejected

    per-field grounding      contributes 0                     (cycle 12)
    validating a title       1 of 19 near-misses               (cycle 5)
    producing a name         0 of 6, +30% false flags          (cycle 7)
    rebuilding X1'           worst of five constructions       (cycle 11)
    create-vs-change         net +2 on 266 rows, 10 fix / 8 break

**So the stage should ship with NO model call**, and that is a finding rather
than a gap. Everything this judge does well, it does deterministically; every
attempt to buy more with an 8B has been measured and has cost more than it
returned.

### The boards were running 141 rows out of habit

Gil, 2026-09-10: *"i would check on thousands of rows especially deterministic
calls which are quick… llm just test on a few since it is very slow."*

Correct, and the small samples were FLATTERING:

    mutation           141 rows   |   753 rows (whole train split)
    dropped_date         100.0%   |      92.3%     <- not perfect after all
    generic_title         85.7%   |      74.3%
    invented_title        94.4%   |      78.9%
    ALL PLANTED           73.4%   |      74.9%
    false-flag       3.2% (n=62)  |  1.2% (n=343)

`judge_board` now defaults to the WHOLE split whenever the grounding pass is
off, because 753 cases cost 8 seconds and the confidence is free.

### THE STANDING BOARD, whole splits, no model

    train  753 cases  ·  catch 74.9%  ·  false-flag 1.2% (343 clean)  ·   8 s
    SEALED 623 cases  ·  catch 73.5%  ·  false-flag 3.2% (317 clean)  ·  11 s

    mutation           train   SEALED
    unrelated_object   100.0%   100.0%
    dropped_date        92.3%    93.8%
    dropped_time        90.0%    76.9%
    invented_title      78.9%    81.1%
    generic_title       74.3%    76.7%
    near_miss_title      3.2%     0.0%

**It generalises**: every row within a few points across halves except
`dropped_time`, which has the smallest denominator (13 on the sealed half).

### Two things this exposes that the small board hid

1. **`dropped_date` is NOT 100%.** It is a deterministic slot check and should
   be exact by construction — 6 of 78 missed on train, 4 of 64 on the sealed
   half. Something about the mutation or the check is wrong on a minority of
   rows, and the 141-row sample never showed it. **Open.**
2. **`generic_title` at 74-77%** is much weaker than the 85-93% the small
   samples reported. `_GENERIC_TARGET_RE` matches an exact set of nouns; a
   quarter of planted generics are getting past it. **Open.**

Both are deterministic, both are cheap to iterate on, and both are better uses
of the next cycle than any model call.

---

## Cycle 14 — the dataset was lying about two of its own mutations

**Prediction:** verifying the generated cases would find some plants that do
nothing, and the miss rows would be concentrated there.

**Instrument:** `datasets/verify.py` (new) — five checks over every case:
BUILDABLE, EFFECTIVE (does the mutation change the object at all), DISTINCT,
ANSWERABLE (can the check that must catch it even see the field), BALANCED.

**Found, on the 900-case set:**

    92 plants that changed NOTHING   `_mutate` set `intent.title` on
                                     target-taking operations, which carry
                                     `match_title` and never read `title`
     9 plants nothing could answer   `delete_todo`/`complete_todo` map no date
                                     and `query_schedule` maps no clock, so a
                                     "dropped" slot was never there

The 9 unanswerable rows were EXACTLY the 6 `dropped_date` and 3 `dropped_time`
misses that cycle 13 left open as *"something about the check is wrong"*. The
check was right; the dataset was asking a question with no answer. Both fixed —
`_mutate` now plants on `titles` → `match_title` → `title` in that order, and
`generate._applicable` consults `render.SLOT_BACKED[action]` before planting a
slot defect.

**Result** (train half, 753 cases, no model, 8s):

    dropped_date      92.3% -> 100.0%
    dropped_time      90.0% -> 100.0%
    generic_title     74.3% -> 100.0%
    invented_title    78.9% ->  98.8%
    unrelated_object 100.0% -> 100.0%
    near_miss_title    3.2% ->   0.0%
    ALL PLANTED       74.9% ->  83.9%

Both of cycle 13's OPEN items were dataset defects, not judge defects. **A
board is an instrument and an instrument needs calibrating**; two cycles of
"the check is weak" were really "the question was unanswerable".

That leaves `near_miss_title` as the ENTIRE remaining gap — 0% on 63 cases,
every other mutation at 98.8% or better.

---

## Cycle 15 — the near miss, the one model call, and a broken tokeniser

**Prediction:** a hand-written set aimed at the near miss would show where the
one model call earns its keep, because a near-miss is the case the
deterministic tests cannot see and a language model can.

**Refuted, twice, and the second refutation is the interesting one.**

### The instrument: 32 hand-written cases

`datasets/handcrafted.jsonl` + `experiments/handcrafted_board.py`. Written
because the generator cannot produce the two cases that matter: a title that is
CORRECT but shares no word with the transcript ("ring my mother" → "call mom"),
and one that is GROUNDED but amputated ("i need to talk to Quinn" → "quinn").
The object is CONSTRUCTED from the row, so nothing upstream can move the answer;
the temporal slots still come from the real chain.

**The board's first run measured a false-flag rate of 56% and it was the
BOARD'S fault** — it skipped segmentation, so `Item.time` was None,
`resolve_values` had nothing to resolve, and eight clean rows that named a time
out loud were flagged for asserting one. Fixed by routing the WHEN through real
segmentation and the WHAT from the row. **A board is not a measurement until it
has been debugged like code.**

### The one model call: DET and +LLM identical on 32 of 32

    DET   catch 12/23   false flags 2/9
    +LLM  catch 12/23   false flags 2/9      bought nothing, cost nothing

Not because the model is silent — dumping what it answered says why:

    title 'meeting groceries'  from "book a meeting with Sage…"   -> "meeting with Sage"
    title 'gym membership'     from "book gym session on tuesday" -> "gym session"
    title 'pick up the parcel' from "pick up the prescription…"   -> "pick up the prescription"
    title 'dentist bill'       from "dentist appointment next…"   -> "dentist appointment"
    title 'milk bottles'       from "add milk to my shopping list" -> "milk bottles"

**The model is not doing the copying task.** It quotes the words behind the
title the object SHOULD have had, or echoes the wrong title back as its own
evidence. Every one of those is a non-`none` answer and `verdict.py` asks the
answer exactly one question — *is it `none`?* — so every one is accepted. This
stage's founding rule is that the model EXTRACTS and code JUDGES; on this call
the second half was never written.

### Four readings of that answer, scored

`experiments/quote_variants.py`, handcrafted 32 and generated train 753:

    V0 shipped (flag on `none`)                      near-miss  25%  /   0%
    V1 + the quote itself uses unspoken words                   38%  /   —
    V2 every title word must be spoken — NO MODEL              100%  / 100%
    V3 V1 + quote-widened V2                                   100%  /   —

**V2 needs no model and wins.** The model reading (V1) adds 13 points on the
handcrafted set and nothing V2 does not already have. So the answer to *"where
would a llm be useful if we had to use only one llm call"* is, measured for the
sixth time: **nowhere.**

### The cost of V2 — and the instrument was broken for that too

`experiments/title_falseflag.py` (new) runs the REAL chain over three corpora
(realspeech 1200, fastrule 7200, segmentation 1549 — personas EXCLUDED, they
may not direct a change) and asks how often each test complains about a title
the system ACTUALLY BUILT. No ground truth is used: every fire counts as a cost.

First run, 3175 titles: ZERO-OVERLAP 7, EVERY-WORD 34. Reading the 34 found a
defect in the READING, not the test:

    remove 'team meeting' from my calendar  ->  ["'team", "meeting'", …]

`[a-z0-9']+` keeps the apostrophe so "o'clock" survives, and eats the QUOTE
MARKS too. Nothing matches `'team`. A TRAILING apostrophe was harmless, which is
why it survived — `names_nothing_spoken` needs every word to fail and the second
always passed. **A title the speaker quoted verbatim read as words nobody
said.** Fixed with one `tokens()` shared by every grounding test in the stage
(`verdict`, `llm_fallback`, `rewrite`).

    3175 titles   ZERO-OVERLAP  7 -> 0      EVERY-WORD  34 -> 7

**The full corpus, 7,640 chain-produced titles:**

    ZERO-OVERLAP (shipped)      0 / 7640    0.00%
    EVERY-WORD   (V2)          14 / 7640    0.18%
    …by corpus: realspeech 0.0% · segmentation 0.0% · fastrule 0.3%

All fourteen are ONE family — *"remind me to fix the leaky faucet tommorow"*
titled `fix the leaky faucet tomorrow`, where FastRule failed to strip a
MISSPELLED time phrase and spell-normalised it into the title. A time word does
not belong in a title and the speaker did not say "tomorrow". **Those are
FastRule findings this test surfaces, not costs it imposes.**

### Cycle 2's anecdote was fictional

V2 is what cycle 2 rejected, on one unpriced anecdote: it flags "gym session"
produced from *"gym saturday"*. Asked for **"book gym saturday at nine"** the
real chain titles the event **"gym"**. FastRule does not pad titles with words
nobody said — which is exactly why the measured cost is 0.18% and not the
double-digit figure the anecdote implied. Two unit tests pinned that anecdote
and now record the trade instead.

### Result — `verdict.unspoken_word` replaces zero-overlap as the identity test

    train  753 cases                  SEALED 623 cases
    near_miss_title    0% -> 100%     near_miss_title      96.3%
    ALL PLANTED     83.9% ->  99.7%   ALL PLANTED          98.1%
    false-flag       2.0% (7/355)     false-flag      2.3% (7/302)

Only ONE of those 7 train false flags is the new test (the FastRule
`tommorow` defect); the other six are the pre-existing generic-title check
firing on gold titles of "i" and "this reminder", which are correct catches the
dataset mislabels as clean.

Handcrafted: catch **52% → 78%**, false flags unchanged at 2/9 — both of them
cases written to be hard (a true paraphrase, and an all-day ask stamped with a
clock by `fill_defaults`).

`names_nothing_spoken` is UNCHANGED and still guards `_not_an_ask`: "not one
field can be pointed at" authorises offering to REMOVE an object, and that must
stay the weak reading.

### Next — the five rows the handcrafted board still misses

    frag-01/02/03   "i need to talk to Quinn" -> title 'quinn'
    unr-01          not_an_ask, blocked by the date FLOOR
    amb-02          "cancel that appointment"

`title_dropped_the_verb` is measured and unwired for the fragments (3.1% false
flags on the sealed half). `unr-01` is the one worth doing first, because it is
not a tuning question: `resolve_values` defaults an untimed item to today, so
`slots["date"]` is ALWAYS set, so `_not_an_ask`'s "is any claim grounded" test
always answers yes and the PANEL route may be unreachable in production. The
isolation board scores it 100% only because its synthetic extra object carries
`slots={}` — an object shape production never builds. **Next cycle: prove or
disprove that the panel route can fire at all.**

---

## Cycle 16 — the PANEL route could not fire, and fixing that broke a second thing

**Prediction** (registered at the end of cycle 15): `resolve_values` defaults an
untimed item to today, so `slots["date"]` is always set, so `_not_an_ask`'s "is
any claim grounded" test always answers yes and the PANEL route may be
unreachable in production.

**Confirmed, and not marginally.** 2,000 utterances through the real chain:

    create objects built                      1780
    …with `slots["date"]` set                 1780   100.0%
    …where that date is a FLOOR nobody spoke   393    22.1%
    …on which `_not_an_ask` COULD fire           0     0.0%

Segmentation stamps `Item.time = "today"` on an item that named no time;
`decompose_validate` resolves it faithfully; the judge reads a present slot as
"the words gave this". One of the three routes Gil specified was dead.

**Fix 1 — `slot_came_from_words`.** `Item.time` is the honest witness: the
contract says it is the time reference AS SPOKEN, so if its words are in the
transcript the resolution came from the speaker, and if it says "today" and
nobody said "today" it is a floor. Deliberately gates `_not_an_ask` ONLY.

**And on its own it cost `invented_title` 98.8% -> 81.7%** on 753 cases. With
the date no longer counting as grounding, every plain wrong title on a command
that named no time became "nothing here is supported" and routed to the PANEL —
which tells the user *you never asked for this* about a command whose one ask is
real.

**Fix 2 — the sibling condition.** The ONLY object a command built is never
spurious. This module's own rule, written before either change: *"an object with
a good title and an invented time is a WRONG object… not offered to the user as
something they never asked for."* A spurious object is one produced BESIDE the
ones that answer the command, which needs no view of how many asks there were —
only whether anything else was built. It does not re-open the ask diff.

**Result:**

    train  753 cases   ALL PLANTED  99.5%   false-flag 2.0% (7/355)
    SEALED 623 cases   ALL PLANTED  97.5%   false-flag 2.3% (7/302)

    mutation           train   SEALED
    dropped_date      100.0%   100.0%
    dropped_time      100.0%   100.0%
    generic_title     100.0%    98.4%
    near_miss_title   100.0%    96.3%
    invented_title     98.8%    96.1%
    unrelated_object   99.0%    96.7%

    handcrafted 32:   catch 78% -> 83%,  false flags unchanged 2/9

### The route is reachable and still never fires — and that is the answer

Across the same 2,000 utterances, `not_an_ask` fires **zero** times. Not a gap:
the same corpus run measured **0 of 7,640** chain-produced titles with no word in
the transcript. FastRule builds a title out of the item's own words, so it cannot
fabricate one, and a producer that cannot fabricate cannot produce a spurious
object. The panel guards the producer that CAN — LLMSeg, wired and INERT.

**Standing board, whole splits, no model call anywhere:**

    train  753 cases  ·  catch 99.5%  ·  false-flag 2.0% (355 clean)  ·   8 s
    SEALED 623 cases  ·  catch 97.5%  ·  false-flag 2.3% (302 clean)  ·  11 s

Six of the seven train false flags are the generic-title check firing on GOLD
titles of "i" and "this reminder" — correct catches the dataset mislabels as
clean. The seventh is the FastRule `tommorow` defect. **The dataset is now the
weaker instrument**, which is where the next cycle goes.

### Next

    1  the 4 rows the handcrafted board still misses:
       frag-01/02/03  "i need to talk to Quinn" -> title 'quinn'   (amputated;
                      `title_dropped_the_verb` measured, 3.1% sealed, unwired)
       amb-02         "cancel that appointment" — `_GENERIC_TARGET_RE` has no
                      "that " in its determiner prefix
    2  the FLOOR, in `unsupported_by_slots` this time: 22.1% of created events
       assert a date nobody spoke and the judge says nothing. Much larger blast
       radius than cycle 16's narrow gate — its own cycle, deliberately.
    3  relabel the 6 mislabelled clean rows in the generated set (titles of "i")

## Cycle 17 — Board D, run for the first time (2026-09-15)

**Prediction**, registered against the retrospective's deep-track-vs-fast-path
gap (sealed 300, `split:"test"`, cited only as motivation — not as evidence,
per protocol): since the isolated board already shows job 1 (`verdict.py`) is
strong (97.5%+ catch), the loop's *connected* net effect was the one number
this stage had never measured, and Board D's own docstring says so
(`board_d.py:5`, *"this board has never run"*). Expected a small positive net,
and expected reading the broken/fixed rows to point at whether any residual
weakness is job 0 (`rescue.py`, unmeasured in isolation) or upstream.

**Run 1** (`--checkpoint board_d_session1 -n 120`, fresh): 120 rows, 5 min,
loop OFF 96/120 80.0%, ON 97/120 80.8%, **NET +1**. Read at the time as
"noise-scale, not a liability" — **wrong, superseded within the hour by run 2**.
The lesson survives on its own: 120 rows was not enough to trust a fixed-minus-
broken count this small, and the direction itself flipped at scale.

**Run 2 — the full population found on disk, and why its answer is INVALID
for HEAD, corrected within the hour of being written.** Initially read as the
real answer — 3,648 rows, dated 2026-09-11 02:17, NET −7, "the loop is a
liability", plus a dominant delete-swallowing pattern (10+ of 16 broken rows
turning a correct `delete_event` into an empty outcome). **All of that was
measured against a system that stopped existing today.** `objects.py` — the
FastRule module those 3,648 rows ran through — was dismantled on the
`engine-component-folders` branch on 2026-09-10 (`11beb4a`), but that branch
only merged into `main` **today**, 2026-09-15 (`9701f59`, 12:40). `main` on
2026-09-11 02:17, when the overnight run actually executed, still had the OLD
`objects.py`-based FastRule. Board D's checkpoint resume has no version
check — `Checkpoint.has(rid)` is a bare id lookup, so replaying a row from a
different code revision reads back as an ordinary cache hit. **The 3,648-row
result and the delete-swallowing pattern are retracted as evidence about
current HEAD.** They may describe a real defect in the code that existed
until this morning; they say nothing confirmed about the code that exists
now. Caught by tracing three of the "broken" rows directly against HEAD
(`remove 'team meeting' from my calendar`, `delete vet appointment from my
calender`, `clear open house off my calendar`) and finding a THIRD, different
outcome for all three — see below.

**So the only Board D reading that is actually about HEAD is run 1**: 120
rows, fresh, NET +1 — noise-scale, and the honest state of this question is
**still unmeasured at a size that means anything**. A trustworthy connected
read of the post-merge loop needs a fresh run (real model calls, not a
resumed checkpoint) at a size Gil is willing to spend the minutes on — the
3,648-row pool took several hours overnight; CLAUDE.md's own checkpointing
story is about exactly that kind of run.

**What tracing those three rows against HEAD did surface, and it reproduces
on every one of the three**: FastRule's `build()` throws
`Validation failed for 'delete_event': Either match_title or
match_start_time must be provided` on the FIRST parse, before the loop-back
logic is even reachable — the SAME `decompose_validate` malformed-value
defect `TASKS.md` filed on 2026-09-10 and never fixed, live again today, on
both arms equally (confirmed by reproducing `board_d.py`'s own warm-up calls
and frozen clock exactly, to rule those out as the difference). Since it
fires identically pre- and post-loop, it cannot be what makes Board D's
off/on arms diverge — but it is a real, currently-live defect, independent
of this cycle's question. See `TASKS.md`'s 2026-09-10 entry, still open.

**Novel effect, not predicted**: the run's stderr filled with the SAME
pydantic rejections `TASKS.md` filed against `decompose_validate` on
2026-09-10 and marked unfixed — `Either match_title or match_start_time must
be provided` (empty-slot deletes) and `time must be HH:MM, got 'HH:MM:SS'` —
plus **one shape TASKS.md's filing didn't have**: a full ISO datetime
(`'2026-12-31T23:50:00'`) reaching the same HH:MM field. All three fire on
BOTH arms of the same row (the defect is upstream of the judge, in
`decompose_validate`/`fastrule`'s build), so they silently zero out the
outcome on both sides and are invisible to Board D's fixed/broken/net split —
they just sink both arms' accuracy together. `assistant/intent/rule_parser.py:
634 _hhmm_from_iso`-shaped normalisation exists for the rule path; nothing in
`decompose_validate/resolve.py` calls an equivalent before the value reaches
the intent. **Five days old, still live, not this stage's bug to fix** — but
a better-evidenced next target than anything internal to LLMJudge right now.

**Process note for next time**: `Checkpoint`/`board_d.py` has no guard against
resuming a checkpoint written under different code — `Checkpoint.has(rid)` is
a bare id lookup with no code-revision fingerprint. A checkpoint found on disk
should be treated as suspect until its date is checked against the git log of
the code it exercises, the same discipline `STATUS.md` already applies to
docs.

**Run 3 — fresh, 400 rows, HEAD `c826c83`** (`--checkpoint
board_d_head_c826c83`, named after the commit precisely so this cannot repeat
run 2's mistake). Contains run 1's 120 rows as a prefix (same seed, same
filtered pool, so `rows[:120] == rows[:400][:120]`) — supersedes it rather
than adding to it.

    correct, loop OFF   324/400  81.0%
    correct, loop ON    324/400  81.0%
    rows FIXED    1
    rows BROKE    1
    NET          +0

**The clean answer this cycle was chasing.** Dead flat, and the single fixed
and single broken row are unrelated one-offs (a `scrap` command the OFF arm
missed entirely; a slow-down on a multi-clause create), not a repeat of the
retracted delete-swallowing pattern — that pattern is confirmed specific to
the pre-merge `objects.py`, not present on HEAD in this sample. **Read as
settling the question**: on current HEAD, the connected loop is neither a
liability nor a fix — negligible either way, converging toward zero as N grew
(120 rows: +1 -> 400 rows: +0). Diminishing returns on scaling further; not
recommending another round of this specific board without a reason to doubt
the zero.

**What dominates the miss instead, and it is not the loop**: the same
`decompose_validate` malformed-value defect fired dozens of times across the
400 rows — not just the two shapes TASKS.md filed 2026-09-10 (empty
match_title/match_start_time on deletes; HH:MM:SS reaching an HH:MM field) but
two more never logged before: a full ISO datetime reaching the same field, and
the bare words **"morning"/"evening" reaching `start_time`/`end_time`
directly**, unresolved to a clock time at all. Every one of these throws
instead of committing a flagged best-effort object, so the item silently
produces nothing on BOTH arms — a much larger share of the ~19% both-arms-wrong
rows than anything inside this stage. **This is the actual next fix**, and it
belongs to `decompose_validate`/`fastrule`, not LLMJudge.

## Cycle 18 — the "malformed value" bug traced, and it was never
decompose_validate's (2026-09-15)

**Prediction, going in**: cycle 17 pointed at `decompose_validate` emitting
values pydantic refuses. Tracing the exact `delete_event` shape
(`Either match_title or match_start_time must be provided`) by running the
three offending texts through the stages one at a time (not the whole engine
at once) found something different at every layer:

- `decompose_validate` resolves everything correctly.
- **FastRule's `build()` also succeeds** — the deterministic rule parser
  correctly extracts a valid `match_title` and constructs a fully valid
  object.
- `fastrule/stage.py`'s `_may_commit` refuses to let FastRule commit a
  delete/update/complete on its own (`_COMMITTABLE = ("create", "query")`,
  by design — "deleting is destructive"), so it wraps the ALREADY-CORRECT
  object as `Defer("needs-target-check", ...)` and hands it to the model
  for confirmation before it goes live.
- **The hand-off was broken.** `Defer.partial` — the dataclass field that
  has existed since this stage's restructure specifically for this, with
  the comment *"what WAS read, so LLMJudge starts warm"* — was never
  populated at this call site; `stage.py` only ever passed `fields={"action":
  res.action}`. And on the receiving end, `rescue.py`'s `_Verdict.partial`
  was hardcoded to `None` in `__init__` with nothing else in
  `assistant/engine/` ever assigning it (confirmed by
  `grep -rn '\.partial\s*=' assistant/engine/`). So `_ask_the_model` always
  took the cold-parse branch — the model re-read the words from scratch,
  with no idea FastRule had already solved it, and occasionally (measured
  directly with logprobs, see below) gambled on leaving `match_title` empty.

**Confidence, measured directly** (the model's own token logprobs, requested
for the first time — nothing in the codebase asks Ollama for them today):
on `"remove 'team meeting' from my calendar"` the model was confident (68%
on its least-sure token) and never failed in 4 tries; on the two rows that
DID flip between correct and empty across repeated identical calls
("vet appointment", "open house"), the least-confident token sat at 37-43%.
The uncertain token was the SAME spot every time — the opening quote of the
`match_title` value — i.e. the model was not unsure what the answer was, it
was unsure whether to commit to one at all. **Decided against building a
confidence-threshold system on this**: it would cut against this stage's own
founding rule (*"the model never judges, never scores... deterministic code
does all the deciding"*), needs calibration data and adds a real request-size
cost, and the actual fix was already a plumbing gap, not a modeling one.

**Fix 1 — wire the hint that was already designed and never connected.**
`fastrule/build.py`: `_read_action_words` now also returns the raw
`RuleParseResult` (`rr`); `Built` gets a `rule_parse` field carrying it.
`fastrule/stage.py`: the `needs-target-check` Defer's `fields` now carries
`rr.raw_slots` / `.confidence` / `.transcript` / `.missing_slots` — JSON-safe
primitives only, since `item.slots` crosses the stage boundary and has to
stay that way (no back-edge into another stage's objects). `llmjudge/
rescue.py`: `take_deferrals` reconstructs a `RuleParseResult` from those
fields and sets it as `verdict.partial`, so `_ask_the_model` now takes the
`parse_with_context` branch and the model sees *"Filled slot 'match_title':
'team meeting'"* instead of nothing.

**Fix 2 — a deterministic fallback for when the model still fails.**
`llmjudge/rescue.py::_target_check_fallback`: on a `ParseError` from a
`needs-target-check` item specifically (the only Defer reason this is
reachable from a `Built`, per `stage.py`), re-run FastRule's own `build()` —
cheap, deterministic, no model call — and use that object instead of failing
the item outright. Scoped narrowly: every OTHER Defer reason means FastRule
never built an object in the first place, so there is nothing to fall back
to. Verified mechanically by forcing every model call to raise: 3/3 rows
recovered, no exceptions, no generic "I couldn't read this part" message.

**Measured, each fix on its own** (Gil, 2026-09-15: *"before goes into
production every stage/component needs to be tested and measured at the
very least"* — logged as [[feedback_test_measure_each_change]]):

- Fix 1 alone: the three known-flaky rows go from a measured ~40-60%
  per-call failure rate (the logprobs run above) to 18/18 across repeated
  attempts. A fresh fresh 300-row Board D (`board_d_c826c83_partialfix`)
  read 83.7%/82.3% vs the pre-fix 81.0%/81.0% — suggestive but not
  conclusive at n=300 (95% CI on a proportion this size is roughly ±1.3 pt).
- Fix 2 alone, same 300 rows: NET +2 on the loop, but the OFF arm itself
  moved 83.7%→82.3% between two runs on the IDENTICAL row set with no loop
  logic touched — Ollama's temperature (0.1, no seed pinned in the request)
  is not fully deterministic, and 300 rows is not enough to separate that
  from a real effect. **Board D was the wrong instrument for this
  question** — most of its 3,648-row pool never reaches `needs-target-check`
  at all, diluting the signal along with the noise.
- **The real measurement**: every train row whose gold action is
  update/delete/complete (884 rows, one model call each — no two-arm setup
  needed) rather than a subsample of the whole board.
  `targeted_fallback_c826c83`, 884 rows, 41 min:

      needs-target-check reached          552 / 884
      model's own attempt raised            2 / 552  =  0.4%
      BEFORE fix 2 (raise = hard fail)    521 / 552  = 94.4%
      AFTER  fix 2 (fallback engages)     523 / 552  = 94.7%
      of the 2 that raised: fallback built something 2/2, correct 2/2

**What it means**: the raw failure rate across the real population (0.4%) is
far below what the three hand-picked adversarial rows suggested (~40-60%) —
those were unusually hard cases (a quoted title, a misspelled "calender"),
not representative. Fix 1 already does the heavy lifting, which is why the
BEFORE number here is 94.4% rather than something alarming. Fix 2 is a
small, cleanly-attributed, fully-verified safety net (+2 rows, both correct)
for the residual — not the large lever it looked like from the board-level
noise. Both fixes are tested (`tests/unit/test_fastrule.py`,
`test_fastrule_build.py`, `test_engine_llmjudge.py`,
`test_engine_contracts.py`, full unit suite: 1655 passed) and measured
independently.

**Corrected from cycle 17's framing**: the "morning"/"evening"/HH:MM:SS/ISO-
datetime shapes are a REAL, separate, still-unaddressed defect family — but
it was never `decompose_validate`'s per se either, going by this cycle's
method; it needs the same per-stage trace before assuming where it lives.
Two more shapes surfaced while measuring this cycle, both in `update_event`:
bare relative-duration phrases reaching a clock field unresolved
(`{'new_end_time': 'by an hour'}`, `{'new_end_time': '20 minutes'}`).

**Next**: trace the time-resolution family the same way this cycle traced
the target-check family — one text at a time, stage by stage — before
assuming it is `decompose_validate`'s fix to make. Not started this cycle.

## Cycle 19 — the time-resolution family, traced and fixed (2026-09-15)

Followed cycle 18's own method rather than guessing: found real reproducing
rows first (`scan_time_bug.py`, 300 create_event/update_event train rows,
one model call each), then traced the mechanism. All 4 real hits share a
shape: `decompose_validate.run_objects`/`_resolve_onto_intent`
(`stage.py:147-160`) **unconditionally re-resolves and overwrites**
`start_time`/`end_time` from the item's own words on EVERY intent that
reaches it, model-built or FastRule-built — so whatever the model puts in
those fields is pure throwaway. The crash happens earlier: `assistant/
intent/parser.py::_parse_response` constructs the model's raw JSON straight
into the pydantic intent, and when the model answers with a full ISO
datetime (`'2026-09-09T14:45:00'`), a clock with seconds (`'18:00:00'`), or
the bare phrase itself (`'late afternoon'`), the validator correctly refuses
it — over a value about to be discarded regardless. None of the 4 had a
fix-18 partial hint (they hit `skip`/`generic-title`, not
`needs-target-check`), so fixing that path doesn't reach this one.

**Fix**: `parser.py::_normalize_time_fields`, called on `parameters` right
before `model_validate` in `_parse_response`. Extracts the HH:MM prefix an
ISO datetime or an HH:MM:SS both carry; drops anything else (a phrase, a
relative duration like `"by an hour"`) to `None` rather than crash — `fill_
defaults` stamps a placeholder and `run_objects` replaces it with the real
value regardless, exactly as it already does for a value the model never
supplied at all. Fixes the producer's OUTPUT normalization, not the
validator — "a time is HH:MM" stays true.

Verified against all 4 real reproducing rows: 4/4 build cleanly now: title
and action both correct in every case; the only messages left are the
system's existing HONEST FLAGS for a value it can't ground (e.g. "end_time
= 19:00 — nothing in the words said it"), not crashes.

**Measured on the full population** — every create_event/update_event train
row (1,963 rows, the single largest action family, ~54% of the whole
eligible pool), one model call each, "before" reconstructed in the same run
by spying on whether the normalizer actually changed a value (it does that
only when a fix-18-style before/after would apply, so no second pass or
model call needed):

    would have raised the HH:MM error   187 / 1963  =  9.5%
    BEFORE this fix   1568/1963 = 79.9%
    AFTER  this fix   1739/1963 = 88.6%
    of the 187 that would have raised: 171/187 = 91.4% now score correct

**CORRECTED 2026-09-15, same day, before this ever reached a commit
message**: the first pass of this measurement scored `update_event`/
`delete_event` rows by reading `.title`, an attribute those intents do not
have (they carry `.match_title`) — so `getattr(intent, "title", None)`
silently returned `None` and every correctly-built update/delete row scored
as wrong, in BOTH the before and after buckets alike. Caught reading the 77
"recovered but still wrong" rows by hand for a completely different reason
(chasing one of the five ideas queued after cycle 19) and noticing ~70 of
them were `update_event` rows with the RIGHT action and a title of exactly
`None` — too clean a pattern to be 77 independent misses. Confirmed by
tracing three of them directly: `"extend dentist appointment by 30
minutes"` built `match_title='dentist appointment'` (correct) the whole
time. Fixed the scorer (check `match_title` for target-taking actions) and
re-ran the full 1,963 rows fresh — a stale checkpoint could not be
rescored, since the original run never captured `match_title` to rescore
from. **The corrected numbers are the ones above; the previously reported
73.6%→79.8% (122/199 recovered) undercounted both sides and is retracted.**

**+8.7 points on the largest action family in the dataset, 91.4% of
crash-recovered rows landing fully correct** — the fix is stronger than
first reported, not weaker; this was a measurement bug, not an optimistic
one. Full unit suite green throughout (1664 passed, 2 skipped, 1 xfailed).

**Process note**: this is the second scoring/measurement bug this project
has caught mid-session by refusing to accept a suspiciously clean pattern
at face value (cycle 17's stale-checkpoint retraction was the first). Read
the actual rows before banking a number, every time — a board's own output
is not automatically ground truth about what it measured.

## Reading at size, 2026-09-22 — the production judge on both halves

`judge_board`, dataset `datasets/judge_cases.jsonl` (1,800 cases: 900 train,
900 test; one defect planted per case over a gold object the real converter
builds, plus clean cases). Scored only where the converter builds the object.
No model call anywhere in the judge.

| split | n scored / total (skipped: converter declined) | catch rate on planted | false-flag on clean | wall |
|---|---|---|---|---|
| TRAIN | 785 / 900 (115) | **100.0%** (411/411) | 2.7% (10/374) | 8 s |
| TEST | 663 / 900 (237) | **98.8%** (334/338) | 2.2% (7/325) | 10 s |

Per mutation on TEST: dropped_date 100% (49), dropped_time 100% (19),
generic_title 98.5% (66), invented_title 98.1% (52), near_miss_title 98.2%
(57), unrelated_object 98.9% (95). The same board on the last banked reading
(cycle 16) was train 99.5% / 2.0% (753 cases) and test 97.5% / 2.3% (623);
n grew because the converter builds more of the gold now.

For the version comparison Gil asked for, the LLM-era judge's readings stand
in cycles 1–4 and 12 above: train 98.9% / 0.0% and test 92.4% / 18.2% on the
141-row sample of the earlier dataset (77 scored test cases, 11 clean), and
the cycle-12 ablation on identical rows — with the model call 75.9% / 19.4%
in 510 s, without it 75.9% / 19.4% in 3 s.

## Board D v2 — 1,200 TRAIN rows, 2026-09-22: net +2, and the loop fires on 1.7% of rows

`board_d -n 1200`, fresh (the board resumes only by flag now), FastRule
7,200 train half, both arms interleaved per row under a ticking frozen clock.
Record: `experiments/runs/board_d_train_1200_20260922T1740.json`.

| | loop OFF | loop ON |
|---|---|---|
| correct (action AND title) | 1073/1200 = 89.4% | 1075/1200 = 89.6% |
| fixed · broke · changed-no-better · NET | | 3 · 1 · 16 · **+2** |
| arms disagreed at all | | 20 rows (1.7%) |
| latency p50 / p95 | 0.0 s / 6.4 s | 0.0 s / 6.9 s |

By shape: atomic n=1,008, 89.6 → 89.8% (net +2); compound n=192, 88.5% both
(net 0). By re-entries the loop spent: 0 on 1,180 rows (90.3% both), 1 on 19
rows (42.1 → 47.4%, net +1), 2 on 1 row. The rewrite's MODEL round (H6) fired
on 8 rows: 50.0% both arms, net 0. The three fixed rows are two "set a
remindar to …" read as an event OFF and a to-do ON, and "um can you just
delete that one for me" that produced nothing OFF; the one broken row is
"drop take out the trash from my tasks", a DELETE that the loop turned into
a CREATE — the harm class the FastRule board weights at 4.

**What it says.** On the constructed corpus the loop is nearly inert: it
changes 20 rows in 1,200 and nets +2, inside the noise of a fixed-minus-broken
count at this n, and its cost is half a second at p95. The one broken row is
the kind that matters most (a delete made into a create), which is exactly
what H4's operation check exists to test. The 19 rows where the loop spent
one round score 42% either way: the loop is reaching the hard rows and not
moving them, which is the case H2's round selector is registered for. And
the model round fired eight times for nothing, which is H6's baseline. The
sealed half is not run until a change is proposed against it.

## The v2 set's baseline — both halves, 2026-09-22, before any change

`judge_board_v2` (new: a wrong finding TYPE is a miss; the blind plants are
reported apart; per voice and per damage operation). Dataset
`datasets/v2/judge_cases_v2.jsonl`, 5,385 train / 5,802 test cases, none
skipped. No model call. ~170 s a half.

| | TRAIN | TEST |
|---|---|---|
| typed plants caught (expected finding on the expected item) | **92.2%** (1821/1975) | **92.9%** (1933/2080) |
| false-flag rate on clean objects | 0.1% (3/2347) | 0.2% (4/2628) |
| dropped_date · dropped_time · near_miss_title | 100 · 100 · 100% | 100 · 100 · 99.6% |
| generic_title · unrelated_object | 99.2 · 99.2% | 98.5 · 93.2% |
| merged_asks | 78.7% (197) | 87.8% (221) |
| **subject_dropped_for_kind** | **85.0%** — 38 answered `not_an_ask` | **86.8%** — 35 `not_an_ask` |
| **invented_title** | **72.4%** — 69 answered `not_an_ask` | **76.7%** — 62 `not_an_ask` |
| blind: wrong_kind · wrong_operation · dropped_ask · clock_residue (flagged at all) | 31.9 · 5.5 · 0 · 0% | 29.4 · 7.5 · 0 · 0% |
| typed catch by voice (lowest → highest) | esl 89.7 … observant 94.0% | — |
| typed catch by damage (lowest → highest) | trailing_interjection 88.6 … hold-on 96.8% | — |

**The defect the v1 set could not show.** On both halves the two title
plants that leave a REAL ask behind a wrong title — a fabricated title, a
kind word in place of the subject — are answered `not_an_ask` roughly a
quarter of the time. `_not_an_ask` asks whether any FIELD of the object can
be pointed at in the words; when the ask named no time and the title was
replaced, no field can, and the object is called spurious — which routes it
to the panel ("you never asked for this") instead of to the rewrite. But the
object was BUILT FROM A REAL ASK: its item's own words are in the transcript.
That evidence is never consulted. Cycle 41 is that one condition.

**What the blind rows say.** A dropped ask and a clock residue in a title
are invisible to every rule (0%); a wrong kind is flagged by accident about
30% of the time (usually as an unsupported field the wrong kind implies); a
wrong operation almost never. Those are H3's and H4's ground, and until a
finding type exists they stay outside every catch rate.

**The voice and damage spread is small** (89.7–94.0% by voice, 88.6–96.8% by
operation): the judge is not the reader that speech damages; the stages
before it are, which is what the whole-chain boards measure.

## Cycle 41 — an object cut from the words is never `not_an_ask` (2026-09-22)

**Hypothesis.** `verdict._not_an_ask` asked whether any FIELD of the object
could be pointed at in the words and never consulted the one thing that
settles it: whether the ITEM the object was built from is in the transcript.
Prediction: the two title plants that leave a real ask behind a wrong
title (`invented_title`, `subject_dropped_for_kind`) stop being answered
`not_an_ask` on the v2 set, both halves; the v1 set does not move (every
v1 row names a time, so the field test never failed there); false flags
unchanged (the condition only ever returns False sooner). Change: one
condition before the claims loop — the item's own words (its source piece,
else its text, two words or more) appear whole in the normalised transcript.
A synthetic extra carries text that does not, and stays spurious; two tests
pin both sides.

**Judge boards, no model, fresh.** Metric: typed plants caught (the expected
finding TYPE on the expected item) and the false-flag rate on clean objects,
defined in `dataset/METRICS.md`.

| dataset · split | n (cases) | before → after | false flags |
|---|---|---|---|
| v2 · TRAIN | 5,385 (1,975 typed plants / 2,347 clean) | **92.2% → 97.5%** (1821 → 1926 / 1975) | 0.1% → 0.1% (3/2347) |
| v2 · TEST | 5,802 (2,080 typed / 2,628 clean) | **92.9% → 97.4%** (1933 → 2025 / 2080) | 0.2% → 0.2% (4/2628) |
| v1 · TRAIN | 785 (411 planted / 374 clean) | 100.0% → 100.0% (411/411) | 2.7% → 2.7% (10/374) |
| v1 · TEST | 663 (338 planted / 325 clean) | 98.8% → 98.8% (334/338) | 2.2% → 2.2% (7/325) |

By plant, train / test: `invented_title` 72.4 → **98.4%** / 76.7 → **98.5%**
(3 and 4 still `not_an_ask`); `subject_dropped_for_kind` 85.0 → **99.6%** /
86.8 → **98.1%** (1 and 5); `generic_title` 99.2 → 100 / 98.5 → 100 (the same
condition — a generic title on a real ask was sometimes called spurious);
`unrelated_object` 99.2 / 93.2% unchanged; `merged_asks` 78.7 / 87.8%
unchanged; the three always-caught plants unchanged. Spread by voice
96.2–99.3% (was 89.7–94.0), by damage 95.2–100% (was 88.6–96.8): the
title-plant deficit was what spread the voices apart, not the voices.

**Actual vs expected.** As predicted on every line, including the two
negative controls (v1 both halves byte-identical; false flags unchanged on
both v2 halves). Novel: `generic_title` moved too, for the same reason.

**What it means.** A speaker whose ask FastRule or the model titled wrongly
was told, a quarter of the time, that they never asked for it. Now the object
goes to the rewrite, which is the loop's job. The whole-chain read (Board D
v2, 1,200 train rows) follows below; the judge board says the routing is
right, the chain board says whether the rewrite then fixes the title.

**What is left on the typed rows.** `merged_asks` at 78.7% train is the
largest deficit (42 rows): every miss is a LIST-mode merge that pulled a
TASK's verb phrase into an event's list — "the car service, charge the
batteries and the sun screen order" — which is not a noun list, so the
coordinated-subject reader (a noun list joined by a conjunction) sees no
list. Cycle 42 reads those rows before deciding whether it is the reader's
defect or the plant's.

**Board D v2 after cycle 41 — 1,200 train rows, fresh, with the model.**
Record `runs/board_d_train_1200_20260922T1857.json`; previous
`…T1740.json` (before the cycle). Metric: count-correct with the loop OFF
and ON, the fixed/broke pair, and latency (`dataset/METRICS.md`).

| | before (T1740) | after cycle 41 (T1857) |
|---|---|---|
| correct, loop OFF | 89.4% (1073/1200) | 89.3% (1072/1200) |
| correct, loop ON | 89.6% (1075/1200) | 89.4% (1073/1200) |
| fixed / broke / net | 3 / 1 / +2 | 2 / 1 / +1 |
| arms disagreed | 20 rows (1.7%) | 19 rows (1.6%) |
| latency p95 OFF / ON | 6.4 / 6.9 s | 5.6 / 6.9 s |
| re-entries spent: 1 | 19 rows, 42.1 → 47.4% | 18 rows, 33.3 → 38.9% |
| model round fired (H6) | 8 rows, net 0 | 9 rows, net 0 |

**What it means — and what it cannot say.** The whole-chain number moved
by one to two rows, which is inside this board's noise, and the noise is
now measured: the two runs' per-row checkpoints differ on **22 of 1,200
rows**, and 21 of those spent NO re-entry and fired no model round — the
judge's loop never touched them. They are the RESCUE (job 0, the model
parsing what FastRule deferred) answering differently run to run:
"delete book club" one time and "delete club" the next, "file the taxes"
then "taxes", an object present in one run and absent in the other (13
wording-only, 9 structural, spread over both arms). The model call is not
seeded — `parser.py` sets a temperature and sends no `seed` — so **Board
D's run-to-run floor is ~22 rows, larger than the 19 rows the arms disagree
on**. A net of +1 or +2 on this board is not a reading of the loop; it is
the model's dice. Cycle 41's effect on the chain is therefore UNMEASURED
here, not null: the judge board says the routing moved (105 more objects
to the rewrite on train), and the chain board cannot see a change that
size through its own variance.

**Registered next, as an instrument fix before any H1–H6 cycle:** make
the board's model calls deterministic — a fixed `seed` and temperature 0
on the ollama options, switchable from the environment so live traffic is
untouched — and prove it by running the same code twice and counting
differing rows, which must be 0 before the fixed/broke pair means anything.
Until then every Board D net under the floor is reported as "inside the
floor", never as a gain or a loss.

## Cycle 42 — the list-merge plant listed the converter's titles, not the grammar's subjects (2026-09-22, 19:07)

**An instrument fix; the judge did not change.** Cycle 41 left `merged_asks`
as the largest typed deficit (78.7% train, 42 rows). Reading the train
misses: every one was a LIST-mode plant, and the list was built from the
CONVERTER'S titles of whatever had been built — a task's verb phrase inside
an event's list ("the car service, charge the batteries and …"), a member
still wearing its frame ("block off the car service", "i would like to
schedule the dentist appointment"), or a pair (three asks, two titled).
`findings.py` defines `coordinated_subject` as "a bare noun list of three or
more things" and `coordination.noun_list` refuses a command verb and a pair
on purpose (Gil, 2026-09-20; DEVQA Q43), so the plant was expecting the
reader to break its own rule. The gold is the grammar's, not the
converter's: the members are now the asks' gold `said.subject`, events
only, three or more; a row that cannot supply that is a PLAIN merge (the
blind population, expect None). The None conditions of the plant are
unchanged, so the regenerated set differs from the previous one on exactly
73 lines, all `merged_asks` (55 list rows → plain, 18 rebuilt from gold
subjects); commands byte-identical; 11,187 cases, same ids.
`test_a_list_merge_is_three_or_more_gold_event_subjects` pins it.

**Judge boards, no model, fresh, same judge code as cycle 41.** Metric as
above. Records `runs/judge_v2_{train,test}_*_20260922T19{07,10}.json`;
before = the cycle-41 records (T1801 / T1804).

| dataset · split | typed plants n | typed caught | `merged_asks` typed | blind `merged_asks` | false flags |
|---|---|---|---|---|---|
| v2 · TRAIN | 1,975 → 1,947 | 97.5% → **99.5%** (1938/1947) | 78.7% (155/197) → **98.8%** (167/169) | 55 → 83 rows, 0% flagged | 0.1% (3/2347), unchanged |
| v2 · TEST | 2,080 → 2,053 | 97.4% → **98.6%** (2025/2053) | 87.8% (194/221) → **100%** (194/194) | 39 → 66 rows, 0% flagged | 0.2% (4/2628), unchanged |

Every other plant line is identical to cycle 41's on both halves (the set
did not change there). The two list rows still missed on train are reader
limits, read and left: a head that is itself a kind phrase ("make an
appointment for the dentist appointment, the …") and a retraction inside
the list ("empanada night no sorry, i mean the kombucha order, …").

**What it means.** The judge is at 99.5 / 98.6% of what today's taxonomy
can name, false flags at 0.1 / 0.2%, and the remaining room is the blind
population — 2,212 cases (dropped ask, wrong kind, wrong operation, clock
residue, plain merges) that no finding type covers. That is §7.3's and
§7.5's ground, not another rule.

**Two things the set cannot yet measure, registered.** (1) The TEST half
has ZERO list-mode rows: its 56 commands with three event asks sit in two
families whose joiners are seams ("also", "and then"), so `coordinated_
subject` is measured on 18 train rows only — a thin n, and a list-of-three-
events family on a plain "and" in both halves is the way to more (a
generator change, so a new set revision with its own baseline). (2) The
list-mode n went from 46+27 to 18+0 because the grammar mixes kinds inside
a three-ask command; that is the corpus telling the truth about how often a
speaker lists three events under one verb, not a plant to loosen.

## The seeded board — proven, and the loop's real footprint (2026-09-22, 20:12 / 20:25)

**The instrument fix.** `model_protocol.seed_options()`: a board sets
`MACALENDAR_LLM_SEED` and every ollama door sends `seed` and temperature 0;
live traffic is untouched (commit `68f39ab`). Proof by a same-code double
run at that commit: Board D v2, 1,200 train rows (record
`runs/board_d_train_1200_20260922T2012.json`), then the first 300 of the
same shuffled order again (`…_300_20260922T2025.json`). **0 of 300 shared
rows differ**, against 22 of 1,200 between the two unseeded runs. The seed
itself moved 18 of 1,200 rows against the unseeded T1857 run (temperature
0.1 → 0: 12 wording-only, 6 structural), which is the size of the dice it
removed, not a change to the engine.

**The seeded baseline — what H1–H6 are read against.**

| Board D v2 · 1,200 TRAIN · seeded | reading |
|---|---|
| correct, loop OFF / ON | 89.4% (1073) / 89.5% (1074) |
| fixed / broke / net | 1 / 0 / +1 |
| **arms disagreed** | **3 rows (0.2%)** — was 19–20 unseeded |
| re-entries spent: 1 / 2 | 18 rows (33.3 → 38.9%) / 1 row |
| rewrite's model round fired (H6) | 9 rows, 44.4% either arm, net 0 |
| latency p95 OFF / ON | 5.8 / 6.8 s |

**What it means.** The 19–20 "rows the arms disagree on" that every
unseeded reading carried were the model's dice between two arms, not the
loop: seeded, the ON arm's final objects differ from OFF's on THREE rows in
1,200. The loop still re-enters on 19 rows (a rewrite finding was raised),
and on 16 of them the re-entry comes back with the SAME objects — the
deterministic trim re-enters segmentation and the chain answers the same
way, which is the case the model tier exists for, and it fired on 9 rows
for a net of 0. The three rows it did move: a misspelled "apointment for
workout session" retitled "workout session" by the model round; "call"
retitled "call with drew and jesse"; and a generic delete ("that one")
that OFF produced nothing for (the one FIXED). So on the constructed
corpus the loop is not noisy and not harmful; it is nearly inert, and the
rows it reaches (33% correct) it mostly cannot change. Of the 127 rows
wrong with the loop OFF, the judge raises a rewrite finding on 19; the
other 108 carry no finding at all, which is the blind population the v2 set
measured from the other side (dropped ask, wrong kind, wrong operation,
plain merges). That is where the whole-chain loss is, and it is §7.3's and
§7.5's ground, not the rewrite's.

**The 127 rows wrong with the loop OFF, read by class** (seeded baseline,
train, Board D's own scorer on its checkpoint: gold action present AND a
content word of the gold title; no model run for the read):

| class | rows | share | example |
|---|---|---|---|
| WRONG KIND — right verb, task↔event | 40 | 31% | "set a remindar to water the garden this evening" → event; "i should see Parker the 21st" → to-do; "rename pack for the trip …" → update_event |
| WRONG OPERATION — right store, wrong verb | 26 | 20% | "add cancel the subscription to my list" → DELETE; "scrap sales call" → CREATE "scrap sales call"; "updat organize the garage" → create |
| nothing built — a generic target refused | 23 | 18% | "get rid of that appointment on my calendar next month" → (); gold `delete_event "that appointment"` |
| count — two clocks, one object, or the reverse | 19 | 15% | "water the plants at half past six and at late afternoon" → one; "schedule a haircut at 7am and 9:15" → two |
| same operation, title wrong | 10 | 8% | "clear water the garden off my to-do list" → `delete_todo "to-do list"` |
| kind AND operation | 9 | 7% | "add a note to call the plumber" → `create_event "note to call the plumber"` |

Half the loss is the KIND or the OPERATION — the two classes the judge is
blind to by construction (0% on the v2 set's `wrong_kind` / `wrong_
operation` plants) and the ground H3 and H4 were registered on. The
generic-target rows are a board convention to settle, not an engine
defect: the front door REFUSES a demonstrative target on purpose (DEVQA;
"deleting is destructive"), the corpus's gold expects the operation with
the generic title, and `_correct` cannot be satisfied by a refusal, so
those 23 rows are a ceiling on this board until the gold or the scorer
says which is right. Two "count" rows in three are a to-do with two clocks
built as one object, which is segmentation's line, not this stage's.

## Cycle 43 — Board D scores a generic target the way Q38 rules it (2026-09-22, 20:31)

**An instrument fix.** The corpus records the literal referring phrase as
the title ("that appointment", `generic_target: true`) because that is
what was said, and `_correct` demanded an object carrying it. The engine
refuses such a target on purpose (DEVQA Q38: *"a title that names nothing
is refused, everywhere"*; CLAUDE.md: *"deleting is destructive"*). So a
refusal is right; an object with the right action and a RESOLVED title is
right (the LLM may resolve an anaphor — FastRule's contract); an object
carrying the phrase, or a wrong action, is wrong. Four tests pin it
(`test_board_d_scorer.py`). No corpus row changed.

**Rescored from the seeded checkpoint, no rerun** (`--resume` on
`board_d_seed_a` at HEAD; record `runs/board_d_train_1200_20260922T2031.json`):

| Board D v2 · 1,200 TRAIN · seeded | before (T2012) | rescored (T2031) |
|---|---|---|
| correct, loop OFF / ON | 89.4 / 89.5% | **91.1% (1093) / 91.0% (1092)** |
| fixed / broke / net | 1 / 0 / +1 | **0 / 1 / −1** |
| arms disagreed | 3 | 3 |

**What it means.** Twenty-three rows moved from wrong to right on both
arms: the engine was obeying the ruling and the board was marking it down.
And the loop's one "fix" flipped to its one BREAK: on "um can you just
delete that one for me" the front door refused the target and the loop's
model round handed back `delete_event "that one"` — the very thing
FastRule's contract says the LLM may resolve but must never overturn.
That is a real defect, in the loop, and it is cycle 44.

## Cycle 44 — a determiner and "one" names nothing, on every gate (2026-09-22, 21:34)

**Hypothesis.** Cycle 43's one broken row: on "um can you just delete that
one for me" the front door refused only by accident — decompose_validate's
anaphor guard matched "you just", rewrote the target to "it", and the judge
refused "it". The loop's trim took "can you" off, the guard fell silent,
the model round handed back `delete_event "that one"`, and neither gate
knew the shape: "one" is in no list. Q38 refuses a title that names nothing
EVERYWHERE, so the arm — a determiner, an optional ordinal, "one(s)" —
goes on the front door (`rule_parser.names_something`), the judge's
`_GENERIC_TARGET_RE`, and the deep path's per-item builder. Measured
before writing: 16 of 4,629 FastRule train gold titles match, every one a
row the corpus marks `generic_target`; "one on one", "capital one", "the
one with dan" do not. Prediction: the broken row becomes a refusal on
both arms (net 0, disagreements 3 → 2); the judge boards unchanged (no
v2 plant carries the shape); the FastRule shape board's handle rate drops
by the refused rows and nothing else moves.

| board | before | after |
|---|---|---|
| Board D v2 · 1,200 TRAIN · seeded, fresh (`runs/…T2134.json`) | OFF 91.1 / ON 91.0%, 0 fixed / 1 broke, disagreed 3 | **OFF 91.2% (1094) / ON 91.2% (1094), 0 / 0 / net 0, disagreed 2**; p95 5.9 / 6.9 s |
| judge v2 · TRAIN / TEST (`…T2039` / `…T2041`) | 99.5% / 98.6%, ff 0.1 / 0.2% | 99.5% / 98.6%, ff 0.1 / 0.2% — identical |
| FastRule shape · TRAIN 4,800 (front door) | handled 77.5%, correct-on-handled 96.4%, harm 106, date right 91.6% (n=777) | handled **76.8%**, correct-on-handled 96.4%, harm 106, date right 91.6% — only the refusals moved |

**Actual vs expected.** As predicted on every line. The row that broke
is refused on both arms now, and OFF gained it too (1093 → 1094): the
front door refuses "that one" before the anaphor guard's accident. The
loop's footprint on this corpus is now 2 rows in 1,200, net 0.

**What it means.** With the scorer honest (cycle 43) and the loop no longer
able to overturn a refusal (cycle 44), Board D reads 91.2% either arm: the
loop neither helps nor harms on the constructed corpus, and the 106 rows
still wrong are wrong BEFORE the judge — half of them the kind or the
operation, which no finding type names. The next cycle is the H3 probe's
answer: whether a seeded one-word model question, asked only when the kind
tagger and the built object disagree (83 of 961 one-object rows), sides
with the gold more often than the object does (72%).

## H3 probe — the model, asked the kind only where the tagger and the object disagree (2026-09-22, 21:50) — REFUTED

**A probe, never banked as an engine number; no engine code touched.**
§7.5 H3: a coarse two-way model question under a condition whose fire rate
is reported. Condition: segmentation's kind tagger disagrees with the kind
of the one object the chain built. Fire rate **83 of 961 one-object rows
(8.6%)** on the seeded baseline's checkpoint (`board_d_c44`, train). On
those 83 the object is right on 60 and the tag on 23, so "follow the tag"
would break 60 to fix 23 (net −37). Then one seeded call per row to Llama
3.1 8B — *event or to-do?* — schema-constrained, 0.70 s p50 / 0.71 s p95.

| on the 83 rows the condition fires | right |
|---|---|
| the object the chain built | **60 / 83 = 72.3%** |
| the kind tagger | 23 / 83 = 27.7% |
| the model, one-word question | 54 / 83 = 65.1% |

Crossed: the model agrees with a RIGHT object on 43, contradicts a right
object on 17, agrees with a wrong one on 12, and corrects a wrong one on
11. Following the model on the condition: **fixes 11, breaks 17, net −6**.
Requiring the tag AND the model against the object: the same 11 fixes, the
same 17 breaks (the tag is wrong on every object-right row by construction).
Where the model goes wrong is telling: "hey remind me to pick up the dry
cleaning tonight" → event; "confirm the reservation by this morning" →
event; "water the plants at half past six and at late afternoon" → event —
a clock in the sentence pulls the 8B model to "event" the way it pulls the
converter, so it adds no independent evidence exactly where the converter
is uncertain.

**Verdict.** H3 is refuted at this model size and this question: on the
only rows a kind check could act, the converter is the better reader by 7
points, and a model round would cost 0.7 s on 8.6% of one-object commands
to lose 6 rows in 1,200. The 40 wrong-kind rows stay where they are — the
converter's — and the next kind work is deterministic, on the converter's
own board, or waits for a model that reads "remind me to" as a to-do. No
REBUILD route is brought to Gil, because nothing measured wants one.

## H2, H6 and H4's condition, read off the seeded checkpoint (2026-09-22, 22:05) — no model run

All from `board_d_c44` (1,200 train, seeded), Board D's own scorer.

**H2 — the round selector: refuted by its fire rate.** It fires only where
two or more rounds produced different objects for one ask. Rows with two
or more re-entries: **1 of 1,200** ("move this to a week from today, i
don't remember the name" — both arms right, a refusal). Rows where the
arms differ at all: 2, both right either way. A selector's ceiling on this
corpus is 0 rows; there is nothing for it to select between. It stays
registered for the v2 set's merged-ask cases, which is the only place two
rounds disagree by construction.

**H6 — the model round we already have: fires on 10 rows (0.8%), net 0.**
On all 10 both arms are right; on 9 the ON objects equal the OFF objects
(seven are generic-target refusals scored right since cycle 43, three are
"book an apointment for X" rows where the round returned the same title);
on 1 it trimmed "appointment for workout session" to "workout session",
which the scorer counts the same. So tier 2 costs the p95 gap (OFF 5.9 →
ON 6.9 s on the rows that loop) and moves nothing the scorer can see. Its
verdict is a latency question, not a correctness one, and the fair test is
the real-usage board, where the rows that reach it are Gil's.

**H4 — the operation, when the words carry both: the condition is badly
aimed.** "A create verb and a change verb, or an anaphor, both present"
fires on **177 of 1,200 (14.8%)**, and the built object is right on 163 of
them (92.1%). Of the 40 wrong-OPERATION rows on the board the condition
catches **8**; the other 32 carry one verb. A perfect model under this
condition nets +14 at most; a Llama 8B reading of H3's quality (65%) would
break ~60 to fix ~9. The probe (§7.5's rule: every hypothesis gets its
number) runs after the confirmation board; it is not expected to pay. What
the fired-and-wrong rows do show is DETERMINISTIC: five of the fourteen are
one shape — a create FRAME wrapping a change verb, "add cancel the
subscription to my list", "remind me to cancel the subscription in two
days" — built as `delete_todo "the subscription"`. The frame says create;
the verb inside the title is the title's. That is the front door's
precedence, harm class 4 (a wrong delete), and it is cycle 45, on FastRule's
own board first.

**Cycle 44b — the per-item builder's copy of the gate, boarded alone and
REVERTED** (2026-09-22, 22:35; record `runs/board_d_train_1200_20260922T2235.json`).
The builder gate was committed with cycle 44 and boarded after it, on its own:
OFF 91.2 → 91.1%, ON 91.2 → 91.1% (1094 → 1093), 0 fixed / 0 broke; the one
row that moved is the cycle's own target, "um can you just delete that one
for me", which the builder's refusal turned into an `unknown` object instead
of the judge's reasoned refusal ("I couldn't tell what to call it"). Nothing
reached the builder that the judge's gate did not already refuse, so the copy
bought nothing and cost the better reply. Reverted, with its test; the front
door's and the judge's arms stay. One change per board run is how this was
visible at all.

## Cycle 45 — a create frame keeps a remove verb in the title (2026-09-24, 09:57)

**Hypothesis.** Five of the fourteen rows H4's condition fired on and got
wrong were one shape: a CREATE frame wrapping a change verb — "remind me to
cancel the subscription", "add cancel the subscription to my list" — built as
`delete_todo "the subscription"`. The front door reads every one as the
to-do it is (checked); the delete came from decompose_validate's
`_rule_create_from_remove_guard`, which turns a create whose TITLE starts
with a remove verb into a delete, reading the title and never the frame in
front of it. Change: the guard stands down when the item's own words open
with a create frame (`remind me to/about`, `set a reminder to`, `note to
self`, `add`, `put`, `write down`). Its original case — "remove 'table' from
furniture", no frame — still converts (test kept). Prediction: the
frame-wrapped deletes become creates, nothing else moves; harm falls, since a
wrong delete is the class weighted 4.

| Board D v2 · 1,200 TRAIN · seeded, fresh | before (cycle 44b, T2235) | after (T0957) |
|---|---|---|
| correct, loop OFF / ON | 91.1 / 91.1% (1093) | **91.6 / 91.6% (1099)** |
| fixed / broke / net | 0 / 0 / 0 | 0 / 0 / 0 |
| rows that changed | — | 9 of 1,200, all wrong → right |

Eight of the nine are the shape predicted, every one a wrong DELETE that is
now the to-do asked for (three of them inside compound commands, where the
other asks were already right). The ninth is cycle 44b's revert: "um can you
just delete that one for me" is back to the reasoned refusal. **Actual vs
expected: as predicted; 8 wrong deletes removed from 1,200 rows.**

## Q47 — a person on a stated day is an event (2026-09-24, 16:03)

Gil's ruling (DEVQA Q47): no clock -> a to-do due that day ("remind me to water
the garden this evening"); seeing a PERSON on a stated day -> an event, 09:00
when no clock was said. The first half already held on the whole chain. The
second did not: segmentation cuts the day into the item's time before the kind
tag runs, so "i should see Parker the 21st" was tagged a to-do, and "see mom"
opened with the look-verb and read as a schedule question. Fix in segmentation
(`fastseg._meets_a_person`, `kind._SEE_A_PERSON_RE`): a capitalised name as
someone's argument or a kinship word you are WITH, on a stated day, promotes a
to-do to an event; outreach verbs (call, email, text) do not.

Segmentation's board (1,051 train rows, fastseg): identical on every line,
kind tags included — its corpus has no such row. **Seeded Board D v2, 1,200
train** (`runs/…T1603.json`): 1099 -> **1103** both arms; 14 rows changed, all
to events: 9 encounters now right ("i should see Parker the 21st", "i need to
talk to Drew on next wednesday"), 5 "remind me to call Morgan tomorrow" now
WRONG — the outreach check read the head verb ("remind"), not the verb behind
the frame. Fixed in the same change (`_OUTREACH_AFTER_FRAME`) and verified on
all 14 sentences through the chain, model-free: the 5 calls are to-dos again,
the 9 encounters stay events — **expected 1108/1200 (92.3%)**, confirmed on the
next full run. None of the day's other front-door changes (weekday list,
passed clock, bare noun) moved a Board D row. "Call Mom tomorrow" under Q47
is put back to Gil.
