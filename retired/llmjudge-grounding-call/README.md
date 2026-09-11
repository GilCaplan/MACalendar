# The judge's grounding call — retired 2026-09-10 (Gil approved)

`evidence.ground_claims` was LLMJudge's one model call: every WORD claim on
every produced object went to llama3.1:8b with a COPYING task — *quote the
speaker's own words behind this field, or answer `none`* — and `verdict.py`
turned `none` into a finding.

**It was 57% of every Ollama call the system made** (0.53 of 0.93 calls per
command, measured over 40 real commands through the full engine) and it changed
no outcome.

## Why it went

Seven candidates for the one call were measured over cycles 5-15
(`assistant/engine/llmjudge/experiments/RESULTS.md`):

    per-field grounding      contributes 0                   cycle 12
    validating a title       1 of 19 near-misses             cycle 5
    producing a name         0 of 6, +30% false flags        cycle 7
    rebuilding X1'           worst of five constructions     cycle 11
    create-vs-change         net +2 on 266 rows              cycle 12
    reading the QUOTE        +13pts, all of it also free     cycle 15
    the whole call, A/B      identical on 32 of 32 rows      cycle 15

The last one is the clearest. On the 32 hand-written cases the judge scores
**identically with and without it, row for row** — and not because the model is
silent:

    title 'gym membership'     from "book gym session on tuesday" -> quotes "gym session"
    title 'pick up the parcel' from "pick up the prescription…"   -> quotes "pick up the prescription"
    title 'milk bottles'       from "add milk to my shopping list" -> quotes "milk bottles"

**It does not do the copying task.** It quotes the words behind the title the
object SHOULD have had, or echoes the wrong title back as its own evidence.
Both are non-`none`, so both are accepted. That is the accept bias in its
purest form: the model answers the question it wishes it had been asked.

Everything the call was supposed to catch is now caught deterministically by
`verdict.unspoken_word` — `near_miss_title` 0% -> 100% train / 96.3% sealed,
at a cost of 0.18% measured on 7,640 chain-produced titles.

## What is NOT retired

`llmjudge/rescue.py` still calls the model, and should: that is **job 0** —
parsing what FastRule DEFERRED — which is the model doing a parse, not judging
one. This project's rule is that the model EXTRACTS and deterministic code
JUDGES. Removing the grounding call is that rule finally applied to the judge.

## Contents

    evidence.py        the retired module, both prompts intact (`ground_claims`
                       and the never-wired `name_objects` from cycle 7)
    quote_variants.py  the board that priced four readings of its answer and
                       found the best one needed no model at all
