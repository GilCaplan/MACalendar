# real_event_gold.jsonl — 81 real titles, labelled by hand

## Why it exists

The event classifier had no honest real-usage number. The only candidate was the
live calendar's 54 rows, and `experiments/RESULTS.md` §Board 2 records why that
is not gold:

    Personal   event                 <- the generic-title bug, not a category
    Study      Notification test A   <- test traffic
    Study      Notification test B   <- test traffic
    Meeting    CC Event              <- test traffic
    Personal   Walk marks dog
    Family     Walk Mark             <- the SAME activity, three labels
    Social     Walk Val

Four of fourteen scoreable rows are test artefacts, one is a defect this project
tracks, and dog-walking is labelled three ways. **A board built on that cannot
adjudicate anything** — the rules "win" on it by answering Personal often against
a set that is mostly Personal.

## Where the titles come from

Real SPEECH, but not Gil's. `dataset/inputs/history_3000.json` is 3,000
utterances from HWU-64, a public crowd-written dataset (its own source field
says so) — corrected 2026-09-24 from "actual usage", which read as the
owner's own commands and overstated what an 81-title reading can say about
him. The labels below were written by an earlier session, not by Gil. The
file is already committed, so nothing new is exposed here. The product's own
deterministic `RuleBasedParser` extracted the event titles; the noisy output was
then filtered by hand.

**What was thrown away, and why that is not cheating:** placeholders (`event`,
`calendar`, `this`, `anything`, `reminder`), garbled fragments (`<time/date`,
`3:00pm teachers`, `valendar`) and titles that are plainly not events
(`bananas`, `more milk`). None of them HAS a correct category — a placeholder
title is the thing LLMJudge flags, not a category to predict — so scoring any
classifier on them would measure title extraction, not labelling.

## WHO LABELLED THESE, and what that means

**Claude labelled them, not Gil.** Every row carries `"labelled_by": "claude"`
so no reader has to guess. That is a real limitation and it is written down
rather than glossed:

- These are a careful reader's judgements, not the user's own. They are a much
  better labeller than a keyword list — which is the entire point, since a
  keyword list is what is being evaluated — but they are not the ground truth
  of what GIL would call these events.
- Where the palette genuinely overlaps, a CONVENTION was chosen and applied
  consistently rather than case by case, because an inconsistent gold set
  measures the labeller's mood:

      "meeting with <name>"        -> Meeting   (a conversation, no other marker)
      "<work marker> meeting"      -> Work      (boss, department, business, client)
      "dinner with <name>"         -> Social    (a named person makes it social)
      "dinner", "lunch"            -> Meal      (nobody named)
      "<name>'s birthday"          -> Social
      "brother's / mother's ..."   -> Family    (an explicit family relation)

  Reasonable people would draw the Social/Meal and Social/Family lines
  differently. **Gil should review this file**, and a correction is worth more
  than the original label — that is exactly what `feedback.py` is built to
  collect.

## What it may and may not be used for

**EVALUATION ONLY.** It is never trained on. Its whole value is being labels the
classifier's own rules did not write, and a set fitted against cannot answer the
question it exists to answer — the same rule
`dataset/personas/PERSONAS.md` binds the persona data with.

## The balance, and its limits

    Meeting 24 · Social 22 · Work 8 · Meal 6 · Health 5 · Family 5
    Fitness 4 · Prayer 3 · Personal 3 · Study 1

Three of the thirteen categories (`Errand`, `Travel`, `Shabbat Meal`) have NO
rows: nothing in the sampled pool produced one. So this set scores ten
categories, macro F1 over the ten present, and it says nothing about the other
three. It is small — 81 rows — and a few points of difference on it is noise.
It is nevertheless the only non-circular real-usage evidence this classifier
has.
