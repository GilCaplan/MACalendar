# LLMJudge

**The last check before anything is trusted**, and the stage that answers what
FastRule could not build. Formerly `crosscheck`.

`PLAN.md` is the design record — §1–§5 are the 2026-09-09 port from FastRule,
**§6 is the agreed structure this file now describes** (Gil, 2026-09-10). This
file is how it works today.

---

## Two jobs, in this order

```
   X4 (objects + DEFERs + the raw text)
        │
        ├─ 0 · rescue.py    answer FastRule's DEFERs — the model lives here now
        │
        └─ 1 · judge        compare what came out against what was said
                 │
                 ├── evidence.py   the model, asked two COPYING questions
                 ├── verdict.py    deterministic code, which does all the deciding
                 ├── findings.py   the taxonomy and the router
                 └── rewrite.py    X1', when an honest one exists
```

Job 0 runs first because the check compares what was PRODUCED against what was
said, and a deferred item has not been produced yet.

## What this stage does NOT do (re-cut 2026-09-10)

It used to make a SECOND model call, `extract_asks`, listing the separate things
the raw text asked for, and diff that list against the objects to find a
`missing` ask or an `extra` object. Gil:

> *"I don't want extraction, that defeats the point of what segmentation →
> decompose_validate → FastRule did. The job of this task is to verify which
> objects to commit and label (or just pass to review panel) or pass back as X1'
> as a rewrite to redo."*

Segmentation ALREADY decided how many asks there are — deterministically, with
its own dataset and board. Asking an 8B to decide again produced a second,
weaker answer, and every disagreement was scored as segmentation's fault. The
project had already measured the cost three ways: the only false flag on this
stage's board was the extraction inventing an ask out of *"i already handled
it"*; run 8 counted 39 loop storms, most of them the matcher's artefact; and
segmentation is FROZEN, so a `missing` finding blamed a stage nobody may change.

**So the stage is now ONE model call and strictly per-object.** What was given
up — noticing that segmentation MERGED two asks — is recorded in `TASKS.md` as
a segmentation question, which is where it belongs.

## The founding rule: the model EXTRACTS, deterministic code JUDGES

Asked *"is this object correct?"* an 8B says yes. That is the accept bias, and
it is the same family as the verbosity, position and rubric-order effects the
LLM-as-judge literature keeps measuring — prompt SHAPE moves a small model's
verdict more than object QUALITY does. Here a rubber stamp writes a wrong row to
the calendar.

So the model is given two jobs it is genuinely good at, both of them copying:

| | question | catches |
|---|---|---|
| `extract_asks` | list the separate things the raw text asks for | an ask nothing covers — **recall** |
| `ground_claims` | quote the words behind each field of each object | a field nothing said — **precision** |

Neither subsumes the other, which is why both run. `verdict.py` turns the two
lists into findings. The model never sees a score, never names a stage, and
never decides what commits.

## The temporal fields never reach the model at all

`CalendarIntent.fill_defaults` stamps `date = today`, `start_time = the current
hour` and `end_time = start + 1h` the moment an object exists. So an object's
date is present whether or not anybody said one, and asking a model to ground it
would flag every correct event that happens to be today.

`item.slots` is the honest record: `decompose_validate` resolved the values from
the words and `build` COPIES them, so **a temporal field on the intent and
absent from slots is a pydantic default the words never gave.**
`render.unsupported_by_slots` reads exactly that, deterministically, for free.
Which leaves the model only the fields made of WORDS — title, target, attendees,
location — and those are where invention actually happens.

Deterministic-first, the same rule as the rest of the engine.

## The taxonomy, and the router

The route is a property of the FINDING, never an opinion about the object.

| finding | means | route |
|---|---|---|
| `ungrounded_subject` | the object's title or target is not established by the words | **REWRITE** — X1', costs a round |
| `coordinated_subject` | ONE calendar event whose words list three or more things (Gil, 2026-09-20) | **REWRITE** — X1' is one clause per thing, costs a round |
| `unsplit_subject` | ONE object whose own words still hold an ask seam — "and then", ". Also,", "; then" (Gil, 2026-09-20) | **REWRITE** — the deterministic tier cannot split it, so the MODEL writes X1' as a list of asks; costs a round |
| `unsupported_field` | a VALUE the words never gave | **COMMIT, and say so** |
| `not_an_ask` | NOTHING about this object is supported | **PANEL** |

`not_an_ask` is what survives of `extra`, and it is a stronger test: `extra`
meant *"the model's ask list did not mention it"*, which was as often the ask
list's fault as the object's. This means *"not one field of it can be pointed at
in the transcript, AND something else was built that answers the command"* — no
second opinion about ask counts required.

**Two conditions were added on 2026-09-10, and the route did not work without
either.** `slot_came_from_words` stops a FLOOR from counting as grounding:
segmentation stamps `Item.time = "today"` on an item that named no time and
`decompose_validate` faithfully resolves it, so `slots["date"]` is set on
**1,780 of 1,780** create objects measured through the real chain — and a test
asking "is any claim grounded" that always answers yes could never fire. The
sibling condition stops it firing too easily: the ONLY object a command built is
never spurious, because the speaker asked for something and it was merely named
wrong, which is a rewrite. Without that second condition the first cost
`invented_title` 98.8% → 81.7% on 753 cases, every one of them a wrong title
offered to the user as something they never asked for.

**The route is now reachable and still does not fire on real speech**, and that
is the correct answer rather than a gap: across 2,000 utterances through the
real chain the deterministic producers never built an object with nothing
grounded — the same measurement that found **0 of 7,640** chain-produced titles
with no word in the transcript. FastRule builds titles out of the item's own
words, so it cannot fabricate one. The panel is the guard for a producer that
CAN — LLMSeg, which is wired and INERT.

Only the first spends budget, and that is the fix for the 2026-09-08 storm —
*"Let an event to go out for a run now"*, three dead rounds, 30 seconds, the
trace saying "unchanged since the last attempt" every time. A rewrite cannot
invent a value nobody said, and an object nothing asks for is not made real by
re-parsing.

**The subject test is about NOUNS, not verbs.** A title carries a verb the
speaker almost certainly said whatever the object is about, so counting "buy" as
grounding made an object titled *"buy groceries"* look supported by the words
*"buy milk"*. The command verbs are stop words in `verdict._TITLE_STOP` for
exactly that reason.

**Subject and value are separate types because their routes must differ.** An
unsupported value can be committed and reported — the object is still the thing
the speaker asked for. An unsupported subject cannot: committing it puts a
fabricated row on the calendar, which is the measured cycle-7 defect.

## The loop: freeze, rewrite, append

```
   good objects ─────────── FROZEN, carried across the round ──────────┐
                                                                       │
   failed asks ─► rewrite.py ─► X1' ─► segmentation ─► … ─► new objects┴─► judge
                                                              round < 3
```

**X1' is a TRIM.** It carries only the failed asks, never the original and never
the original minus a flag. Three consequences, each the point: the frozen
objects cannot be built twice; each round is a smaller problem than the last;
and the retry is genuinely a different input, which is the only thing that makes
spending a round rational against a DETERMINISTIC segmenter.

**Freeze, not commit.** The good objects stay in `state.items` and are excluded
from the re-parse (`engine.parse(frozen=…)`, ids re-prefixed per round);
`_commit` still runs exactly once, at the end. The alternative — committing them
mid-loop — buys partial commits, a retract-and-re-commit path and memory
bookkeeping spanning rounds, for no user-visible gain, since the reply is spoken
once either way.

**X1' has TWO TIERS** (Gil, 2026-09-20: *"the whole point of the loop is that
the llm sends a fix if relevant as X1' to iterate on, otherwise commit"*).
Tier 1 is code: `failed_asks`, the failed asks in the speaker's own words, or
`expand_list`, one clause per listed thing. It is a trim or an expansion, so
given the same failure twice it writes the same string twice — the second
round of it is dead by construction. Tier 2 is the model, `rewrite_with_model`,
asked only when tier 1 has nothing new (the string was already tried) or
cannot help (an `unsplit_subject`: trimming one object's words drops the other
ask). It is shown the transcript, the leftover (`residue`), the finished asks,
and every earlier attempt with what it produced and what the judge said about
it — the attempt ledger lives in the state's own fix list, rules `rewrite` and
`rewrite_model`. It answers a LIST of asks, and the prompt fixes the shape the
parser reads: verb first, one thing per line, to-do vs calendar framing, the
time at the end of its line as digits, the speaker's recurrence phrase kept
exactly and attached to one line. Code joins the list as the ingest envelope
`("a")and("b")`, which segmentation opens before it reads any language, so the
cut the model chose is the cut that happens. The 2026-09-10 measurement that
retired the model repair (worst of five constructions: 41 recovered, 13 leaks,
10 empties on 60 rows) is answered by construction rather than by prompt: the
finished asks are cut out in code and listed as done, the seams are put in by
code, and a line that invents a word refuses the whole answer.

**When the budget runs out, a subject that names nothing is HELD BACK.** The
judge raised `ungrounded_subject` on 'Appointment' and 'this on my calender'
every round, no rewrite could invent a subject nobody said, and the object was
committed anyway — four dev-100 rows on 2026-09-20, one of them written twice.
`engine._block_unresolved_subjects` sets `item.blocked`, which `_commit`
already reports ("I didn't book 'X': …") and the panel already draws. It reads
`_GENERIC_TARGET_RE`, the fast path's own veto, so the two tracks agree about
what "no subject" means — this is the REFUSAL contract that CLAUDE.md records
as broken once before, at the other end of the chain. Narrow twice over: only
`ungrounded_subject` (a COORDINATED or UNSPLIT subject has a real title and is
two asks in one), and only a program word or bare pronoun (a specific but
unsupported title still commits with its notice).

The loop is NOT short-circuited for those objects, though the rounds look
wasted. Tried and reverted the same day: "let's just skip appointment at time"
is titled 'Appointment' on the first pass and re-parses as a DELETE that finds
nothing, which is the right answer to a garbled command, and refusing the round
committed an event instead.

**The guard on X1'.** Every content word of the rewrite must already appear in
the transcript — both tiers, every line. The recorded defect: the first attempt built X1' out of
`finding.detail` — the human-readable EXPLANATION — and segmentation parsed the
explanation. One asymmetry: creation verbs (`add`, `set`, `book`…) may be
introduced, because a bare list has no verb and "add milk to my list" is the
whole point; destructive ones (`delete`, `cancel`, `move`, `rename`…) never may.
It fails CLOSED — no honest rewrite means no loop.

**The rescue's invention guard covers every word field** (`llm_fallback.
_guard_inventions`, widened 2026-09-20). A fabricated event TITLE drops the
object — cycle 7's rule, unchanged. A fabricated VALUE on a real object drops
the field: an ungrounded `location`, a `recurrence` with no marker in the
words ("every", "each", "daily", "repeat" — a speaker never says "weekly"),
and a to-do's ungrounded `titles`, the object going only when none survive.
The asymmetry is the one this stage's router already uses: a subject nobody
said means there is no object, a value nobody gave is one bad field. Measured
on dev-100: 'Grocery List Review' AT HOME, a DAILY "reopen groceries", and
'milk, eggs and bread' from a command naming no groceries — all three survived
every loop round, because the judge can refuse a field but the rewrite cannot
change what the parser returns.

## What must not be broken

- **A REFUSAL may be RESOLVED, never overturned** (`llm_fallback._honour_refusal`).
  The model may answer *"move it"* → *"move the dentist appointment"*; it may not
  hand back *"move it"* and have it executed. Already broken once in this
  codebase, when the per-item path re-implemented the commit test with the gates
  omitted.
- **`_guard_inventions`** — a model-fabricated event never reaches the calendar
  (cycle 7). Rule-parser output deliberately never routes through it: rules are
  grounded by construction.
- **`_grounded_title`** — every content word of an LLM title must have been
  spoken.
- **A command must never fail because its checker could not run.** Model offline
  means no model-derived findings; the slot check still runs, because it never
  needed one.

## Measurement

**Stage 1 — isolation.** `experiments/judge_board.py` over
`datasets/judge_cases.jsonl`: gold items, converted by the real
`fastrule.build`, then mutated in one known way. **The metric is a PAIR** —
catch rate on planted defects and false-flag rate on clean ones — because
always-accept wins one and always-reject wins the other, and only the pair tells
them apart. Reported per mutation; scored as a DELTA against the unmutated
object, since "clean" means "nothing planted", not "flawless".

**Stage 2 — connected.** Board D, which has never run. The metric is *rows
fixed minus rows broken*, net. A stage with a good isolated board and a negative
net is a liability.

## The naming gap, corrected

An earlier note here said the trace identifier was still `Stage("crosscheck")`.
It is not, and has not been since the 2026-09-08 re-cut: `state.STAGES` and the
orchestrator both say `llmjudge`, and `test_engine_contracts.py` pins it. The
module alias `_crosscheck` inside the orchestrator is the only survivor of the
old name.
