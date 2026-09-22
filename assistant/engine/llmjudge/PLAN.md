# LLMJudge — the plan (2026-09-09)

`ARCHITECTURE.md` is how it works today. This is what is coming to it and what to
do about it. **Nothing here is built yet** — it is written now because two pieces
of FastRule are moving here, and the receiving end should be designed before they
arrive rather than after.

---

## 1 · Two things arrive from FastRule (Gil, 2026-09-09)

FastRule is being trimmed to one job — `Item -> object` — because *"if there's an
issue it tells the LLMVerify."* Two of its four current jobs are this stage's.

---

## 1.0 · STEP 0 — the port comes BEFORE the demolition (Gil, 2026-09-09)

> Gil: *"make sure before we start breaking FastRule code to port what's relevant
> to the LLMJudge folder to deal with when we get there — then the rest of the
> FastRule restructure plan."*

**This is the first step of the whole restructure, ahead of everything in
FastRule's own `PLAN.md` §3.** The reason is not tidiness. If FastRule is trimmed
first, the ~118 lines of `Gatekeeper` and the ~150 of the LLM fallback exist only
in git history, and "port" quietly becomes "rewrite from memory" — which is how a
guard gets dropped. `_guard_inventions` is the one that matters: it exists because
of a measured cycle-7 defect where a model fabricated an event onto the calendar,
and nothing about the LLM fallback's new home makes that risk smaller.

### It is a MOVE with an import redirect — not a copy

The distinction decides whether this step is safe:

```
    PORT  = FastRule phase A               TRIM = FastRule phase B (B5/B6)
    the code LIVES here                    FastRule's call sites go away
    FastRule imports it from here          the redirect goes away with them
    behaviour identical, boards identical  behaviour changes, boards re-run
```

A **copy** would leave two versions of `_honour_refusal` alive at once — and the
rule it enforces (*a REFUSAL may be resolved, never overturned*) has already been
broken once in this codebase, by exactly that mechanism: the per-item path
re-implemented the commit test with the gates omitted. Two copies of a guard is
the shape of that bug, not a step toward fixing it.

So step 0 changes **no behaviour and moves no board**. That is its acceptance
test: `pytest tests/unit/test_fastrule.py` and FastRule's product-shape board
report the same numbers before and after. A port that moves a number is a port
that changed something, and should be reverted rather than explained.

### The inventory — verified against the code, 2026-09-09

| name | today | lines | port verdict |
|---|---|---|---|
| `Gatekeeper` | `fastrule.py:284-351` | ~68 | **moves** |
| `_which_store_holds` | `fastrule.py:234-259` | ~26 | **moves** — Gatekeeper's only caller |
| `_names_something_real` | `fastrule.py:260-283` | ~24 | **moves** — Gatekeeper's only caller |
| `_GENERIC_TARGET_RE` | `fastrule.py:54` | 8 | **moves** — see below |
| `_POLITE_IMPERATIVE_RE` | `fastrule.py:62` | 4 | **moves** — Gatekeeper-only |
| `_INTERROGATIVE_RE` | `fastrule.py:66` | 4 | **moves** — Gatekeeper-only |
| `_llm_trace` | `objects.py:150-160` | 11 | **moves** |
| `_honour_refusal` | `objects.py:161-196` | 36 | **moves** |
| `_parse_item` (model half) | `objects.py:197-280` | ~84 | **moves** — the hard one, below |
| `_grounded_title` + `_TITLE_STOP` | `objects.py:281-300` | 20 | **moves** |
| `_guard_inventions` | `objects.py:301-318` | 18 | **moves** |
| `REFUSAL` · `STRUCTURE` · `INCAPACITY` · `_REASON_CLASS` · `reason_class()` | `fastrule.py:103-131` | ~30 | **STAYS in FastRule** |

**The LLM fallback is in `objects.py`, not `fastrule.py`** — §1.2 below says "FastRule
itself calls the model" and that is true of the stage, not of the file. Worth
stating because the two files have very different shapes: `fastrule.py` is the
rule engine, `objects.py` is the per-item build loop, and the fallback is woven
into the second.

### There is no circular import — the first reading of this was wrong

Counting raw occurrences suggested `REFUSAL` (6 uses in `fastrule.py`) and
`_GENERIC_TARGET_RE` (3 uses outside it) were SHARED, and that moving them would
create `fastrule -> llmjudge -> fastrule`. Reading the enclosing scopes says
otherwise, and the difference is the whole design of this step:

- **`REFUSAL`'s six "uses" in `fastrule.py` are its own definition** — the constant
  at line 103 and the five `_REASON_CLASS` table rows at 111-114 — plus one
  comment inside `Gatekeeper`. Nothing in FastRule *reads* it.
- **Every code use of `_GENERIC_TARGET_RE` is inside a piece that is already
  moving**: `Gatekeeper` at 326/338/343, and `_honour_refusal` at
  `objects.py:178/183`. The remaining hit is a comment in `fastrule_shape.py`.

So the pieces are coupled to **each other**, not to the rest of FastRule. They lift
out as one connected component and the cycle never forms. The lesson is the one
this project keeps re-learning: **a usage count is not a dependency** — the
enclosing scope is.

### Which leaves exactly one dependency edge, and it points the right way

`_parse_item` reads `REFUSAL`/`STRUCTURE`/`INCAPACITY` (`objects.py:213, 255, 268`),
so after the move LLMJudge imports the reason-class contract from FastRule:

    llmjudge  ──imports the DEFER vocabulary──►  fastrule        ✔ one direction

That is the correct direction and the reason the contract **stays put**: the DEFER
is FastRule's *product*, `REFUSAL/STRUCTURE/INCAPACITY` is the vocabulary it is
written in, and the consumer of a value importing that value's vocabulary is
ordinary. Moving the contract here would invert it — LLMJudge is not the only
consumer (`atomizer_board.py`, `test_artifact_claims.py` and `objects.py` all read
it), and a contract does not belong inside one of its readers.

During the window between the port and FastRule's **B5/B6** there is a transitional back-edge —
`fastrule.objects` calls into `llmjudge` for the fallback it has not yet stopped
calling. **Both edges are function-local imports** (`objects.py`'s imports at 178
and 213 already are), so nothing resolves at import time and no cycle can bite.
The back-edge disappears with the trim; it is not a design, it is scaffolding, and
FastRule's B6 is not done while it survives.

### What goes red the moment `Gatekeeper` leaves the folder

Named here so it is planned rather than discovered:

| | what to do |
|---|---|
| `test_artifact_claims.py:610` — the published page names `FastRule · Atomicity · Gatekeeper · Scorer` as FastRule's components | the page and its claim check are updated **in the same change** — the artifact-claims rule exists for exactly this |
| `engine/ARCHITECTURE.md:111` — the Component-vs-Stage table puts `Gatekeeper` in `fastrule/` | move the row to `llmjudge/` |
| `fastrule/ARCHITECTURE.md:25,34` — the flow diagram and the component table | redraw without the veto box |
| `tests/unit/test_fastrule.py` | Gatekeeper's tests move with it, to `test_engine_llmjudge.py` |

`BRAIN_VERSION` is **not** bumped by any of this. Gatekeeper and the fallback are
Components, not Stages — the chain's shape is unchanged, `Stage("fastrule")` and
`Stage("llmjudge")` both still exist and still run in that order. This is the
`old_seg -> FastSeg` case from `engine/ARCHITECTURE.md`, not the rename case.

### Order within step 0

| # | | why |
|---|---|---|
| 0a | `llmjudge/gatekeeper.py` — the six Gatekeeper names, verbatim | self-contained; nothing else can be affected |
| 0b | `llmjudge/llm_fallback.py` — the five fallback names, verbatim | the connected component's second half |
| 0c | FastRule imports both from their new homes; call sites unchanged | the redirect. Behaviour identical by construction |
| 0d | Move the tests that belong to the moved code | a guard without its test is half-ported |
| 0e | Re-run `test_fastrule.py` + the product-shape board | **the numbers must not move.** If they do, the port changed something |

---

### THE MANIFEST — everything "go" needs, already resolved

Written out so execution is transcription, not re-derivation. Line numbers are
2026-09-09; the names are the contract, the numbers are a convenience.

**0a · new file `llmjudge/gatekeeper.py`** — cut from `fastrule/fastrule.py`:

| name | from | lines |
|---|---|---|
| `_GENERIC_TARGET_RE` | `fastrule.py:54-57` | 4 |
| `_POLITE_IMPERATIVE_RE` | `fastrule.py:62-64` | 3 |
| `_INTERROGATIVE_RE` | `fastrule.py:66-69` | 4 |
| `_which_store_holds` | `fastrule.py:234-257` | 24 |
| `_names_something_real` | `fastrule.py:260-281` | 22 |
| `Gatekeeper` | `fastrule.py:284-349` | 66 |

Needs `import re` and nothing else at module scope — `assistant.db` is already
imported lazily inside both store helpers, which is what keeps this file free of
the database at import time. **Carry the comment blocks verbatim**: the ones at
`fastrule.py:295-304` (why the store lookup must CONFIRM the parse, not merely
permit it) and `314-330` (why `_GENERIC_TARGET_RE` and not validate's
`is_placeholder_title` — using the latter as a commit veto broke 14 tests) are
each a recorded defect, and a port that keeps the code and drops the reason
invites the same fix to be re-attempted.

**0b · new file `llmjudge/llm_fallback.py`** — cut from `fastrule/objects.py`:

| name | from | lines |
|---|---|---|
| `_llm_trace` | `objects.py:150-158` | 9 |
| `_honour_refusal` | `objects.py:161-194` | 34 |
| `_TITLE_STOP` | `objects.py:281` | 1 |
| `_grounded_title` | `objects.py:284-298` | 15 |
| `_guard_inventions` | `objects.py:301-316` | 16 |

Needs `import re` and `from assistant.engine.state import EngineState, Item`.
`_honour_refusal`'s own `from …fastrule import _GENERIC_TARGET_RE` at
`objects.py:178` becomes a local import from `.gatekeeper` — same file, one hop
shorter.

**`_parse_item` does NOT move in step 0.** It is the branch point, not a unit;
it stays in `objects.py` calling the four helpers at their new addresses.
FastRule's **B5/B6** replaces it with a `DEFER(INCAPACITY)` consumer, which is a
behaviour change and therefore not this step's business.

**The `_friendly` question, decided.** `_honour_refusal` calls `_friendly`
(`objects.py:145`) for its trace label, and `_friendly` **stays** — it has eight
other callers in `objects.py`, including one at line 362 outside everything that
is moving. So `llm_fallback._honour_refusal` imports it **lazily, inside the
function**, exactly as it already imports `assistant.trace.RULE` two lines above.
Three reasons this is the right call rather than a compromise:

- **No import-time cycle is possible.** `objects.py`'s only top-level engine
  import is `assistant.engine.state`; every FastRule→LLMJudge call is a
  function-local import. Neither module can be loaded "first" and break.
- **Moving `_friendly` to `state.py` was the tidier alternative and is rejected** —
  it edits the frozen contract module during a step whose entire guarantee is
  that nothing structural changed. Tidiness does not buy enough to spend that.
- **It becomes a tripwire.** When FastRule's B5/B6 dismantles `objects.py`, this import
  fails loudly and names the last thing that needs a home — which is better than
  a silent loss, and a silent loss is the whole risk Gil asked to eliminate.

**0d · the tests that move**, from `tests/unit/test_fastrule.py` to a new
`tests/unit/test_engine_llmjudge.py` (the stage has **no unit test file today** —
this port creates its first):

| test | what it pins |
|---|---|
| `test_f4a_polite_imperative_is_not_a_question` | the `_POLITE_IMPERATIVE_RE` exemption |
| `test_f7_rename_never_commits_a_create` | the rename-misroute veto |
| `test_personalisation_is_lookup_not_training` | `_names_something_real` — lookup, not a refit |

Three more files reference the moved names and must be checked, not assumed:
`test_engine_generate.py`, `test_event_matching.py`, `test_artifact_claims.py`.
The first two go through the public path and should need nothing; the third is
the published-page agreement check and **will** go red (§ "What goes red" above).

**0e · the acceptance test, exactly**

    pytest tests/unit/test_fastrule.py tests/unit/test_engine_generate.py \
           tests/unit/test_event_matching.py tests/unit/test_artifact_claims.py
    python -m assistant.engine.fastrule.experiments.fastrule_shape   # train half

The board must print the §5 baseline unchanged — `handled 69.1% ·
correct-on-handled 94.2% · deferred 30.9%`. **A moved number means the port
changed behaviour and should be reverted rather than explained**; that is the
one rule that makes this step worth separating from the restructure at all.

Only then does FastRule's `PLAN.md` §3 start. Steps 1-3 there (measure the ceiling,
build the converter, move `Atomicity`) no longer touch any of this code, because it
is no longer in the building.

### Why `_parse_item` is the hard one, and what to do about it

The other ten names are lifts. `_parse_item` is not: it is the per-item **branch
point**, and the model half is woven into it rather than sitting beside it —
it reads FastRule's partial parse, decides rules-vs-model, calls the model,
then runs `_honour_refusal` and `_guard_inventions` over the result.

**Do not try to make the port clean here.** The honest move is to port the model
half and its three guards as one function that FastRule *calls* at the same branch
point, leaving the branch itself in `objects.py` until FastRule's B6 deletes it.
The alternative — restructuring the branch during the port — is a behaviour change
wearing a port's clothes, and it would break step 0's one acceptance test.

The clean version of this boundary is `DEFER(INCAPACITY)` returned by
`build()` and read here, which is what §1.2 describes. **That shape belongs to
FastRule's phase B, not to this port.** Step 0 only guarantees the code is here,
tested, and no longer duplicated when the demolition starts.

## 1.1 · `Gatekeeper` moves here, and becomes CONTEXT rather than a veto

> Gil: *"perhaps move Gatekeeper code to LLMJudge… so it's given to the LLM as
> context."*

Today `Gatekeeper` (~68 lines, plus `_which_store_holds` and `_names_something_real`
which query the user's own stores) sits inside FastRule and **vetoes** readings that
must not execute as stated:

| it catches | example |
|---|---|
| a mutation aimed at a bare noun | "move it to five" — move WHAT? |
| a rename that would misroute | "rename the dentist to physio" hitting the wrong record |
| an interrogative that would create | "should I book the gym?" creating the gym |

**Why it is better here.** As a veto it has exactly one move — refuse — and a
refusal is the end of the conversation. The objection it raises is precisely the
kind a model CAN answer: *"move it"* has an antecedent somewhere in the utterance,
and resolving anaphora is what a language model is for. So the same judgement,
handed over as context, becomes answerable instead of terminal.

**The rule it must not break.** `REFUSAL` today means *the LLM may RESOLVE the
objection but must never overturn it* — the deep track once re-committed exactly
what the front door had vetoed, and the engine audit named it. Moving the code here
puts the veto and its escape hatch in the SAME module, which makes that rule easier
to hold, not harder:

    the model may answer  "move it"  ->  "move the dentist appointment"
    the model may NOT answer  "move it"  ->  "move it"   (the same empty target)

So the prompt gets the objection AND the constraint: *here is what is wrong with
this reading; you may fix it by naming the thing, and you may not hand it back
unchanged.*

## 1.2 · The LLM fallback moves here

Today, when FastRule cannot read an item, **FastRule itself** calls the model
(`_parse_item`'s model half, plus `_honour_refusal`, `_grounded_title`,
`_guard_inventions`, `_llm_trace` — about 150 lines, all of them in
`fastrule/objects.py`, not `fastrule.py`; §1.0 has the line numbers). Under Gil's definition
FastRule reports `DEFER(INCAPACITY)` and carries its partial parse forward; the
model call happens where the model lives.

**What comes with it, and must not be dropped on the way:**

- **`_guard_inventions`** — a model-fabricated event never reaches the calendar.
  This exists because of a measured cycle-7 defect, and rule-parser output is
  deliberately never subject to it.
- **`_grounded_title`** — every content word of an LLM title must have been spoken.
- **`_honour_refusal`** — the REFUSAL rule above, in code.
- **the partial parse rides along** — `state.fastrule_verdict` already carries
  reason, reason class and confidence forward (Gil, 2026-09-07: *"a deferral never
  wastes the work"*). The model starts from FastRule's reading, not cold.

---

## 1.3 · THE LOOP — commit what is right, rewrite only what is wrong (Gil, 2026-09-09)

> *"Given the output from FastRule it compares the original text prompt and the
> objects, and for the objects which are good it pushes them through. Whatever is
> left it fixes/trims the original text to pass only the objects that are wrong and
> need fixing, in better wording… if FastRule passed 5 objects and 3 are good and 2
> are bad, LLMJudge lets the 3 good ones get committed and the 2 bad ones it rewords
> best it can into a new prompt and passes it back to segmentation. This cycle
> repeats up to 3 times before objects get committed or thrown away."*

```
   original text ─────────────────────────────────────────────┐
        |                                                     │
        v                                                     │
   segmentation -> decompose_validate -> FastRule             │
        |                                                     │
        v                                                     │
   ┌──────────────────── LLMJudge ────────────────────┐       │
   │  compare each object against the ORIGINAL text   │       │
   │                                                  │       │
   │   3 good  ─────────────────────► COMMIT now      │       │
   │                                                  │       │
   │   2 bad   ─► reword ONLY those parts ──► X1' ────┼───────┘
   └──────────────────────────────────────────────────┘   round < 3
                                  |
                            round == 3
                                  v
                        commit best / discard
```

### Why the rewrite is a TRIM, not a retry of the whole thing

This is the part that makes the loop safe, and it is worth stating as a rule
rather than leaving to the implementation:

**X1′ contains only the failed asks.** Not the original utterance, not the original
minus a flag — the words for the two things that went wrong, reworded. Three
consequences, each of which is the point:

1. **No double-commit.** The three good objects are already written. If X1′ still
   described them, round two would create them again. The trim is what prevents
   that, so it is a correctness requirement rather than an optimisation.
2. **Each round is a SMALLER problem.** Five asks became two. A command that was
   too tangled to segment correctly gets simpler every round instead of being
   re-attempted at full difficulty — which is why three rounds is enough.
3. **The retry can actually differ.** Segmentation is DETERMINISTIC, so re-entering
   with unchanged text returns the identical answer and burns the budget for
   nothing. Real usage, 2026-09-08: *"Let an event to go out for a run now"* looped
   three times to the same result and apologised after 30 seconds. A trimmed,
   reworded X1′ is a genuinely different input — which is exactly why
   `rewrite_for_retry` was gated as a stub until it could produce one.

### What "good" means, and who decides it

The model must not be the judge — that is this stage's founding rule. So:

- the model **EXTRACTS** the asks it can see in the original text;
- deterministic code **DIFFS** that list against the objects FastRule built;
- an object is GOOD when it matches an extracted ask and carries no finding
  against it. Everything else is bad and goes into the trim.

Which means `extract_asks` and `_produced` — both already here — are the machinery
the loop needs; what is missing is the partition and the rewrite.

### The budget, and what happens when it runs out

Three rounds per original prompt, counted per COMMAND rather than per object, so a
row cannot loop forever by failing a different ask each time.

On exhaustion the existing convention holds and should not be quietly changed:
**commit the best attempt, say so in the reply, and mark the memory record
uncertain** so it reaches the review queue. Gil's *"committed or thrown away"* leaves
the choice open; discarding silently is the one option that is not acceptable,
because the speaker asked for something and heard nothing back.

> **Open question for Gil.** Should a *destructive* ask that is still unresolved at
> round 3 commit as the best attempt, or be dropped with an explanation? The
> project's own rule — *"when the engine cannot identify what to delete, 'I couldn't
> find…' is the right answer; guessing is not"* — argues for dropping deletes and
> committing creates, but that asymmetry should be a decision rather than an
> inference.

## 2 · What this stage then is

    IN    the objects FastRule built + the DEFERs it could not, with reasons
          + Gatekeeper's objections as context
          + the ORIGINAL text, which is what everything is compared against
    OUT   the GOOD objects, committed now
          + X1' — only the failed asks, reworded, back to segmentation
          + on round 3, the best attempt and an honest reply

Which makes the existing shape more honest, not less: LLMJudge already **extracts**
what the raw text asked for and lets deterministic code diff it. It gains the two
places where a model is genuinely the right tool — resolving an objection, and
reading an item the rules could not.

---

## 3 · The thing to fix that is already here

**The loop never fires.** `rewrite_for_retry` is a stub returning `None`, so the
re-entry budget is never spent and the one mechanism for recovering from a bad
segmentation is inert. It is gated deliberately — segmentation is deterministic, so
re-entering with unchanged text cannot produce a new answer (real usage, 2026-09-08:
*"Let an event to go out for a run now"* looped three times to the identical result
and apologised after 30 seconds).

So the gate is right and the rewrite is the missing half. It wants a model call
grounded on `state.raw_text` that produces a CLEARER utterance in the same format —
and with `Gatekeeper`'s objections now available here as context, it has something
concrete to rewrite *toward* rather than a vague "try again".

---

## 4 · Order

| # | step | why |
|---|---|---|
| **0** | **PORT the code here, behaviour unchanged** — §1.0 | Gil: *port before breaking FastRule.* Trimming first would leave the guards in git history only |
| **⏸** | **WAIT — FastRule phases B, C and D** (`fastrule/PLAN.md` §3) | Gil, 2026-09-09: *"once we totally finish FastRule then let me know and we can work on LLMJudge"* |
| 1 | Turn `Gatekeeper` from a veto into prompt context | now a local change — the code is already here |
| 2 | Make the fallback a `DEFER(INCAPACITY)` consumer, and delete FastRule's branch | the boundary change; one stage's behaviour at a time |
| 3 | `rewrite_for_retry` | last, because it is the only piece that needs the other three to be useful |

**Step 0 happens NOW; steps 1-3 wait for Gil.** The port is FastRule's phase A —
it runs first precisely so this code is safe while FastRule is taken apart. Steps
1-3 are this stage's own redesign and do not begin until FastRule is finished and
Gil says to start.

**Step 0 is a MOVE; steps 1-2 are the BEHAVIOUR change.** Splitting them is the
point: step 0's acceptance test is that no number moves, so anything that does move
a number is provably in steps 1-2 and not in the relocation. Doing both at once
gives up that isolation, and the boards are the only way this stage is measured.

## 5 · Rules

**The model EXTRACTS; deterministic code JUDGES.** That is this stage's founding
idea and none of the above changes it — Gatekeeper's objections are computed
deterministically and handed over; the model answers them.

**A REFUSAL may be resolved, never overturned.** The one rule that has already
been broken once in this codebase.

**Board D has never run.** It needs both a FastSeg answer and a final prediction, so
it only reports with LLMSeg on — see segmentation's `ARCHITECTURE.md` §3. The one
board built to ask *"does the correction pay for itself"* has no data, and that is
worth fixing before trusting any verdict this stage produces.

---

# 6 · THE AGREED STRUCTURE (Gil, 2026-09-10)

§1–§5 above are the history: what moved here in phase A and what §1.3 sketched
the loop to be. **This section supersedes §1.3's mechanism** (not its intent) and
is what gets built. Gil's framing, and the four amendments agreed in the same
conversation.

## 6.1 · Gil's structure

> *"X4 from FastRule — the judge looks at each object (or the tostring of it,
> because looking at the pointer reference is kind of meaningless). Pass valid
> objects on to be committed. Objects labeled bad but potentially good, rewrite
> the prompt i.e. X1' (omitting valid objects — no point doing double work).
> And objects which are not meant to be committed, pass to the review panel to
> show the user this isn't relevant to be put into the calendar/task list."*

Three buckets, two steps: a per-object verdict, then a router that sends each
bucket where it goes. That shape is adopted. Four things change inside it.

## 6.2 · Amendment 1 — the model gives EVIDENCE, not a verdict

The founding rule of this stage stands: **the model extracts, deterministic code
judges.** "Is this object correct?" asked of an 8B is answered *yes* — that is
the measured accept bias, and the same family as the verbosity / position /
rubric-order biases the judge literature documents. Here a rubber-stamp puts a
wrong row on the calendar.

So the per-object pass is a GROUNDING pass, in the FActScore / MiniCheck shape:
the object's FIELDS are its atomic claims, and the model is asked, per field,
to **quote the words that support it or say `none`**. That is extraction, which
small models do well. Code turns spans into the verdict.

    NOT   "create_event dentist 2026-09-14 15:00 — is this right?"  -> "yes"
    BUT   "which words support title=dentist? date=2026-09-14? 15:00?"
          -> "dentist" / "next monday" / none        -> code: start_time invented

The same output serves all three consumers: the router (which bucket), the
rewrite (which field to clarify), and the panel (the span that justified a
field). One extraction, three uses.

## 6.3 · Amendment 2 — BOTH directions of comparison

The stage today walks text → objects. Gil's proposal walks objects → text.
Neither subsumes the other and both are needed:

| direction | catches | machinery |
|---|---|---|
| text → objects | an ask nothing covers — **missing** | `extract_asks` (kept; its counting rules are earned) |
| objects → text | a field nothing said — **invented** | the grounding pass, new |

Recall and precision. `extract_asks`'s prompt survives verbatim; what does not
survive is `_produced`/`_tokens`/`_overlap`/the 0.25 threshold — a weak matcher
with patches around it, and the source of the false missing/extra that drove the
2026-09-08 loop storms.

## 6.4 · Amendment 3 — the router keys on the FINDING, not on an opinion

"Bad but potentially good" vs "not meant to be committed" is not one decision and
not the model's to make. It is a table, keyed the way the DEFER classes already
are:

| finding | route | why |
|---|---|---|
| `missing_ask` | **REWRITE** → X1' | a re-segmentation can genuinely recover a merged ask |
| `generic_target` | **REWRITE** → X1' | Gatekeeper's objection; anaphora is what the model is FOR |
| `unsupported_field` | **COMMIT, field dropped + flagged** | a retry cannot invent a date nobody said |
| `not_asked` | **PANEL** — "not relevant" | never retried |
| `not_an_ask` | **PANEL** | segmentation tagged it `other`; already decided |

Only the top two spend loop budget. That is the discipline that keeps *"Let an
event to go out for a run now"* — three dead rounds, 30 seconds — from returning
in a new costume.

**`not_asked` and `not_an_ask` use the SAME carrier** as FastRule's
`NotAnObject` (`item.blocked` + `slots["fastrule_result"]`), so the panel draws
one outcome, not two.

## 6.5 · Amendment 4 — FREEZE, don't commit mid-loop

§1.3 said the good objects commit while the bad ones loop. That moves `_commit`
INSIDE the judge loop: partial commits, a retract-and-re-commit path, and
memory/revert bookkeeping spanning rounds — for no user-visible gain, since the
reply is only spoken at the end anyway.

**Instead: the good items stay in `state.items` and are FROZEN; only the failed
asks are re-parsed from X1' and APPENDED.**

    parse()   state.items = []                 -> keeps the frozen items,
              re-runs all three stages            re-runs the three stages on X1'
                                                  and extends

Same benefit — no double work, no double commit, each round a smaller problem —
with one commit point and no retract machinery. And coverage stays correct for
free: the ask diff still runs against the **original** text every round, with the
frozen objects counting as covering their asks.

## 6.6 · X1' is grounded, or it is not sent

The recorded failure: the first attempt built X1' out of `finding.detail`, the
human-readable EXPLANATION, and segmentation parsed the explanation.

The invariant that kills the whole class — `_grounded_title` lifted from title to
sentence:

> **every content word of X1' must appear in `raw_text`.**

X1' is a RESTATEMENT of the speaker's words, never a description of the problem.
Deterministic, cheap, testable, and it fails closed: not grounded → no rewrite →
no loop, which is exactly today's safe behaviour.

## 6.7 · The prompt structure, and why

Four parts, each blocking a documented failure mode:

1. **the source first, verbatim** — the raw transcript, named as the only truth.
2. **the objects rendered canonically** — one line each, **only the fields that
   are set** (a pydantic dump with twelve nulls invites commentary on nulls),
   in a **fixed field order** (order shifts judge scores measurably), with a
   stable id. `render.py` owns this, and the panel shows the SAME string, so
   what the judge saw is what the user sees.
3. **a per-field extraction instruction** — "quote the supporting words or say
   `none`". No scores, no "is this good".
4. **schema-constrained output**, as every other call here already is.

Explicitly NOT: a numeric quality score, a holistic verdict, or letting the
model name the blamed stage.

## 6.8 · What is kept, what is rebuilt

| | |
|---|---|
| **kept verbatim** | `gatekeeper.py`, the three guards in `llm_fallback.py` — every one is a paid-for bug |
| **kept** | `rescue.py` — job #1 (answer the DEFERs) runs before job #2 and is untouched |
| **kept** | `_EXTRACT_SYSTEM`'s counting rules |
| **rebuilt** | `_produced` / `_tokens` / `_overlap` / 0.25 / the capacity accounting |
| **rebuilt** | `BLAME` + `_loop_target` → the §6.4 router |
| **built** | `render.py`, `evidence.py`, `verdict.py`, `rewrite.py` |

## 6.9 · Measurement — two stages, and the metric must be a PAIR

**Stage 1, ISOLATION** (`experiments/judge_board.py`, `datasets/`). Labels come
free from FastRule's 7,200: build the gold object from `expect`, then MUTATE it
in controlled ways, one mutation per finding type. A naturally-mined set is
dominated by valid objects, so an always-accept judge scores ~90% on it —
**accuracy is gameable here.** The board reports a pair, per finding type:

    catch rate      flagged / planted          (recall on invalid objects)
    false-flag rate flagged / genuinely valid  (the cost of the catch)

Train half mines; the test half stays sealed, same rule as everywhere else.

**Stage 2, CONNECTED.** This is Board D, which §5 admits **has never run**. The
metric is the project's own framing: *rows the judge FIXED minus rows the judge
BROKE*, net. A stage with a beautiful isolated board and a negative net is a
liability. Expect most findings to point at segmentation, which is FROZEN — those
go to TASKS.md, not into this stage's work.

## 7 · PROPOSED 2026-09-22 — the data this stage needs, and the shape it should take

_Proposed for Gil, not agreed. Written after the judge board read 100.0% /
98.8% catch on its two halves and Board D read net 0 at 400 rows: the stage
is at ceiling on the defects we know how to plant, and the instrument that
could show anything else does not exist._

### 7.1 · Why the stage cannot be improved on its own data

The judge's set is 1,800 cases built from FastRule's template corpus with six
synthetic defects. Two things follow. First, a deterministic judge already
catches those six at ceiling, so any change — a model call, a new rule — reads
as noise there. Second, this stage LOOPS: a finding rewrites the command and
re-enters segmentation, so its real output is the whole chain's second and
third pass, which only a connected board (Board D) measures — and Board D
holds 400 rows against a rule that says thousands. Real speech fails on
classes the six defects do not contain: disfluent titles, recogniser garbage,
a subject the words held and the reader dropped, merged asks, a wrong kind or
operation. The stage is blind to them by construction, not by implementation.

### 7.2 · The dataset — the part that can be delegated

**One generator, gold by construction, never a model's opinion.** A model
labelling what a model will be judged on is circular, and free-form LLM gold
is what the dropped real-speech set was. The delegated agent writes the
GENERATOR and the VERIFIER; it never writes an answer by hand and never reads
a test half. Its brief:

1. **Command-level gold by grammar.** A catalog of asks defined by grammar
   (one to four asks; event / to-do / query / update / delete; a time in every
   spoken form the readers know, including the compact and dotted ones from
   cycle 35; recurrence; an anaphoric edit "the one you just made"), composed
   into commands with the joiners real speech uses ("and", ". Also,", ", then",
   comma runs with and without a conjunction). The gold is the ask list with
   its fields, derived from the grammar, so it is exact.
2. **Realised in voices.** Each command rendered in the six persona voices
   (`dataset/personas/`) plus a plain one, so phrasing varies while the gold
   does not.
3. **Then damaged, by observed operations.** The damage comes from what has
   been SEEN, never invented: the STT operations `scripts/vocab_repair_bench.py`
   already carries; the disfluency shapes from the real-usage taxonomy
   (trailing interjections, hold-on chatter, one-word swaps, stutters, a
   retraction "no, I said that"); a generic or junk title; a clock residue in
   a title. Each operation is a named function with a count, so the set can
   say "N distinct shapes" as the vocabulary bench does.
4. **Object-level cases planted from those commands**, the way `generate.py`
   does now, with the six defects plus the real classes: dropped ask, merged
   asks, wrong kind, wrong operation, subject dropped for a kind word, clock
   residue in the title.
5. **Split by template FAMILY** so no phrasing of a family sits in both
   halves; a `verify.py` that checks every gold value is reachable from the
   command's words (the `intent/correction.py` rule) and that the halves share
   no command text; a `README` that prints the diversity counts — grammars,
   voices, damage operations, families per split.

**Size:** ~5,000 command-level rows and ~10,000 object cases, split in half.
**Diversity is the deliverable, not the count:** the agent reports distinct
shapes, and a set of 5,000 rows from 30 templates is rejected.

**Guardrails for the agent:** no edits under `assistant/engine/*/` except the
new `llmjudge/datasets/` files; stores redirected; `MACALENDAR_LLM_DISABLED=1`
(the generator needs no model); never opens `test_split.json` or any test
half; a 100-row sample of the TRAIN half is read by a person before the set
is used to decide anything.

### 7.2a · LANDED 2026-09-22 — the v2 set, and what its first probe said

`datasets/v2/` (README there): 5,292 commands, 11,187 cases, 189 families
split 90/99, 61 grammars, 7 voices, 16 observed damage operations, 13 plants.
Verified by rule (reachable, no text or family leak, every voice and operation
on both halves). Two things the agent's train-half PROBE (900 sampled cases,
never banked) surfaced, and both are now the first work of §7.3:

- **`invented_title` catches 65.2%** on this set against ~100% on v1: the
  judge answers `not_an_ask` where `ungrounded_subject` is due, which routes
  the object to the panel instead of the rewrite. A wrong finding TYPE is a
  miss. This is the judge's first real defect in two weeks, and it is found
  only because the set carries voices the template corpus never had.
- **Four plants are BLIND to today's taxonomy** — dropped ask, wrong kind,
  wrong operation, a clock residue in a title (2,157 cases): no finding type
  exists, so no rule can fire. That is §7.1's prediction measured, and it is
  the ground H3 (kind) and H4 (operation) stand on.

A `judge_board_v2` that scores the pair on this set, wrong type counted as a
miss and the blind plants reported apart, is the instrument for §7.3 and
§7.5, and comes before any change.

### 7.3 · The stage's shape — four decisions, each boarded alone

Measured on Board D v2 (loop on vs off, both halves, fixed minus broken, with
a per-class breakdown and p50/p95 beside it) and on the judge board v2 (the
pair); the real-usage board as the outer gate.

1. **Keep the judge deterministic.** No change; the pair is at ceiling and the
   ablation showed the model call inert. This is the null hypothesis the other
   three are tested against.
2. **Rescue self-consistency.** Where FastRule declined, sample the rescue
   twice; commit when the two agree on count and kind; when they disagree,
   one pairwise call — "which reading is what was asked?" — decides. Costs a
   second call on compounds only. Prediction: the deep path's count-correct
   rises, the false-flag pair is untouched, p95 rises on compounds.
3. **A pairwise selector at loop exhaustion.** When rounds produced different
   objects for one ask, one comparative call chooses; today the last round
   wins unjudged against the earlier ones. Prediction: fixed-minus-broken on
   rows with two or more rounds goes positive; zero calls on rows with one.
4. **Rescue as its own trace step.** It is a parse, not a judgement (CLAUDE.md
   says so). Drawing it as its own step inside this stage changes no
   behaviour, makes Board D's "which half moved" readable, and needs the panel
   procedure (BRAIN_VERSION, CHAINS, the explorer). _Deferred on 2026-09-22
   when the program started: a chain-spec split is a BRAIN_VERSION bump, which
   also re-verifies the tips and re-renders the panel on both platforms, and
   Board D v2 already breaks the net down by re-entries, so the rescue's share
   is readable without it. Do it if the cycles say the rescue is where the
   change lands._

What is NOT proposed: a second extraction of asks, per-field grounding, a
model naming things, a yes/no model verdict on the rescue's output — each
measured and lost between cycles 1 and 12.

### 7.4 · Order, and what decides

Board D v2 first (an afternoon: n to thousands, the class breakdown, the
disagreement counter) → the dataset (delegated; a day or two) → decision 4
(bookkeeping) → decisions 2 and 3 as cycles, one change per board run, keep
or revert on the pair plus latency → the real-usage board says whether any of
it reached real speech. If the outer gate does not move, the classes in the
set are wrong, and that is the finding.

### 7.5 · Where Llama 3.1 8B might be worth its latency — the hypotheses to TEST

_Added the same day at Gil's request. Each is a registered test, not a
decision. What the record says about this model, in one line: it loses every
span-level, high-cardinality question ("which of these words", "is this
subtly wrong") and can win a coarse, two-way, comparative one — so every
hypothesis below is shaped that way, asked only under a CONDITION, with the
condition's fire rate reported beside the result, because a call that fires
on 2% of rows can neither move a number nor cost much latency._

**The protocol, the same for all six.** Dataset and split named; n as
scored/total; the pair (catch / false-flag) or fixed-minus-broken; p50 and
p95 on the deep path with a budget agreed before the run (proposal: no more
than +5 s at p95 per call added); the condition's fire rate; a prediction
registered before the run; keep or revert on the pair AND the budget. Every
call is schema-constrained, grounded on the raw words, asks the model to COPY
or to CHOOSE, never "is this correct", and runs at background priority on a
board. The four refuted uses (per-field grounding, validating a shown title,
naming a thing, a second ask extraction) are re-run once on the new set as
NEGATIVE CONTROLS at full size, and stay refuted unless the pair moves.

| # | the question, and when it is asked | what could move | board · dataset · n |
|---|---|---|---|
| H1 | **Rescue self-consistency.** Two samples of the rescue's parse for an item FastRule declined; commit on agreement; on disagreement one comparative call: "which of these two readings is what was asked?" Fires on compounds only. | deep-path count-correct (57% on the test 300); the compound families | Board D v2, both halves, thousands; the test 300 as the milestone |
| H2 | **The round selector.** At loop exhaustion, when two rounds produced different objects for one ask: "which reading is what was asked?" Fires only on rows with two or more disagreeing rounds — Board D v2 counts that rate first. | fixed-minus-broken on multi-round rows, today taken unjudged from the last round | Board D v2; the new set's merged-ask and dropped-subject cases |
| H3 | **The kind, when the tagger is unsure.** Event or to-do? Segmentation's tag error is one-directional (event read as task, 116 of 175), and the personas board showed kind accuracy spreads 17.3 pt with phrasing alone. Fires when the tagger's margin is low or the tagger and the converter disagree — the seam the 09-20 cycles found. | kind accuracy on the kind board; count-correct on event+task compounds | `scripts/kind_board.py` (Level 3b) and the new set's wrong-kind plants, thousands, both halves |
| H4 | **The operation, when the words carry both.** Create something, or change something that exists? Measured once at net +2 on 266 rows (10 fixed, 8 broken) — refuted at THAT n. Fires only when a create verb and a change verb, or an anaphor, are both present. Retest at thousands with the operation defect planted. | harm (a wrong delete costs 4), the mutation rows | FastRule board + the new set's wrong-operation plants, both halves |
| H5 | **A retraction.** "…and I also need to buy ice. No, I said that." — does this clause CANCEL the item before it? Two-way, fires only when ingest finds a retraction marker (no / wait / scratch that / I said that). Today the marker is a filler at best. | corrected item count on real usage (id=223), the disfluency operation rows | the new set's retraction operations; real usage as the gate (n=75) |
| H6 | **The model round we already have.** Tier 2 of the rewrite, measured on its own: rows that reach it, fixed, broken, and what tier 1 would have done. This is the one live model use in the stage and it has never been scored at size. | its own fixed-minus-broken; whether it should fire earlier or later | Board D v2 with the ledger read per row |

**What decides.** A hypothesis is KEPT when the pair improves on the test
half, latency stays inside the budget, and the condition fires often enough
to matter (reported, not assumed). It is REVERTED when the pair is flat —
which is what H4 did at 266 rows, and what the grounding call did at 141 —
and the negative controls are the check that the reasoning still holds on
data the old boards never had.
