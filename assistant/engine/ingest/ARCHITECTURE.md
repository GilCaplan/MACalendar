# Ingest

**The step between "what Whisper wrote" and "words worth parsing."** Everything
Segmentation sees has been through here.

## What it is FOR (Gil, 2026-09-20)

> *"The idea of ingest is **a.** to fix deterministically bad transcribe
> wording **b.** finetuned list of vocabulary from user to fix."*

Two aims, and keeping them apart is what decides where a fix belongs:

**(a) GENERIC, DETERMINISTIC repair.** Damage that happens to everybody, fixed
the same way for everybody, with no reference to who is speaking: stop
keywords, openers, stutters, filler phrases, trailing hedges,
self-corrections — and the COMMAND FRAMES the routing depends on. "remind me
to" is not personal; every speaker says it, and `_ROUTE_OVERRIDES` matches on
it, so a mangled frame ("rewind me to", "remind mitt to") is misrouted for
everyone. It belongs here.

**(b) THE SPEAKER'S OWN WORDS.** Names, places, shorthand, loanwords — things
English does not know and only this person says. `assistant/stt/vocab.py` and
the aliases learned from their corrections.

**Putting a fix on the wrong shelf is a real bug, not a tidiness question.**
"remind me to" was briefly taught as a per-user alias on the word "rewind" —
and because an alias is exact and unguarded, it then rewrote "rewind the video
to the start" for that user and helped nobody else. Ask which aim a repair
serves before writing it: if every speaker needs it, it is (a).

**Only (a) may be deterministic in the strict sense.** (b) LEARNS — an alias
added today changes tomorrow's answer — so the vocabulary path is
path-dependent by design. Measured on 400 cases: identical across repeats and
across entry order, and differing only with learning on, where all ten changes
were repairs that became correct and none regressed.

Two jobs, and they were in two different places before this folder existed:

```
   audio transcript(s)
          |
          v
   +-------------------+
   |      INGEST       |
   |  coalesce.py      |  several queued recordings -> ONE input
   |  repair.py        |  vocabulary fixes, false starts, uncertain words
   +-------------------+
          |
          v      state.text, state.corrections, state.needs_edit
      SEGMENTATION
```

## coalesce.py — concatenation

Commands arriving while a run is in progress are queued (FIFO). Before the next
run starts, queued inputs are coalesced up to a token budget
(`engine.coalesce_max_tokens`) into one input as `("…")and("…")`. The wrapper
keeps each command's logic independent for Segmentation, and is deterministic
to split back. Overflow beyond the budget stays queued and runs sequentially.
The phone's bracket-batched requests feed the same mechanism.

## repair.py — the words

Reads `state.raw_text`, `state.source`, `state.supports_edit`; writes
`state.text`, `state.corrections`, `state.needs_edit`, `state.ignored`, and
`VOCAB` trace steps.

- trailing stop keywords go
- false starts are declared trivial — **and never remembered**, because
  recording one teaches the model that junk is normal
- the personal vocabulary repairs what it is confident about
- what it is **not** confident about is surfaced: as `needs_edit` when the
  client can show an editor and the setting asks for one, as advisory
  `uncertain_words` otherwise

The vocabulary is hand-curated and lives outside the repo in
`~/.assistant_tools/`. Writing junk into it quietly degrades the assistant, so
any script exercising this stage must set `MACALENDAR_VOCAB` to a scratch path.

## Status

Not yet dug into. Moved here for structure; no dataset, no board of its own.

## Cycle 37 — disfluent speech (2026-09-22)

Three shapes from Gil's own commands that the spoken-noise passes
(`intent/cleanup.py`, aim (a): generic, no vocabulary) did not know, and one
bug they exposed:

- **A trailing interjection**, said to nobody after the command: *"…at 6.30.
  excuse me. excuse me."*, *"…, meeting, excuse me."* Both became part of the
  title. `_TRAILING_INTERJECTION` peels them off the end, each one after
  punctuation, so "I'm sorry" inside a command and a title that merely ends in
  one of the words are left alone. "thank you"/"thanks" are deliberately not
  in the list: they are stop keywords the speaker configures, and *"remind me
  to say thank you"* is a command.
- **Hold-on chatter**: *"…at 11 o'clock, in one second, one moment, one
  moment, bear with me, i want…"* was cut into three asks by the commas it
  left. The filler list knows the phrases now, and the pass matches with a
  LOOKBEHIND instead of consuming the separator — a pattern that ate the comma
  before each match took the comma the previous filler needed and left one
  behind.
- **A one-word swap**: *"with pelic sorry, i mean edo"*. The clause rule
  wants a clause to survive after the marker and rightly refuses a single
  word; `_WORD_SWAP_CORRECTION` reads the narrower shape first.
- **The bug**: the filler pass ate ", i mean," before `_SELF_CORRECTION` could
  see it, so the rule's own docstring example — *"buy milk, I mean, buy
  bread"* — produced *"buy milk buy bread"*, two items where one was meant.
  "i mean" is a filler only without a comma before it now.

Every rewrite counted first over the clean corpora (2,699 real utterances
minus the sealed 300, 4,800 FastRule train rows, 1,592 segmentation rows):
**0 of 9,091 outputs changed** — these shapes exist only in real speech. The
explorer's ingest walkthrough is regenerated (`scripts.gen_ingest_demo
--write`) and its claims test names the two new passes.

## Misspelled command words (2026-09-24)

Aim (a), generic damage: `repair._WORD_REPAIRS` puts back fourteen misspelled
COMMAND words ("updat", "remindar", "shedule", "delet", "cancle",
"apointment" …), every one a non-word, so no real word can be rewritten
(a test holds that against /usr/share/dict/words). Negative surface before
adding: 2 of 3,003 real HWU-64 commands touched ("shedule"), 0 of Gil's 76.
Found by the save step's cross-store board: "updat walk the dog on my list"
CREATED a task called 'updat walk the dog'. On that board (whole engine,
FastRule TRAIN change rows, n=746) wrong creates fell 27 -> 14; the 13 rows
now change nothing, which is honest — "update X on my list" names no change.
