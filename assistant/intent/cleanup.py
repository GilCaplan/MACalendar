"""Spoken-noise cleanup — the words that carry no request.

Gil's architecture call (2026-09-07): the person-specific work belongs in
the INITIAL CLEANUP step — the personal vocabulary repairing what was
misheard, and the "mhmm"/"umm" filler coming off — so that everything
downstream is generic and works for anybody. Nothing after this stage
should need to know how a particular person talks.

It lives in `intent/` because BOTH readers need it and the layering runs one
way (engine → intent): the deep track's transcript stage cleans the whole
command once, and FastRule cleans again when it is handed raw text directly
(the sandbox, and any caller that skips the pipeline). Cleaning twice is
harmless — these patterns are idempotent — and the alternative, one copy per
caller, is how the lead-time reader ended up fixing only half the system.

Why it matters, measured: filler stripping used to live inside FastRule's
own normalisation, so the DEEP track never got it. Real-usage review showed
the LLM path failing 5 of 5 on rambling dictation that opened with exactly
these words.
"""
from __future__ import annotations

import re

#: Openers that announce speech rather than a request: "um", "so", "alright",
#: "okay so". Only stripped from the FRONT — "ok" inside a sentence can be
#: meaningful ("mark the ok as done").
_OPENERS = re.compile(
    r"^(?:(?:um+|uh+|erm+|mm+|mhm+|hmm+|so|well|ok(?:ay)?|alright|"
    r"right|hey|yeah|yep|look|listen|actually|basically)[,\s]+)+",
    re.I)

#: "now," as an opener — but ONLY with the comma. "now" alone is a real time
#: word ("do it now"), so this is the one entry that cannot join the list
#: above, where a bare space is enough. Measured on the realspeech corpus:
#: every review-read-as-event error there opened this way — "now, do i have
#: anything this week", "now, what do i have the rest of the day".
_NOW_OPENER = re.compile(r"^\s*now\s*,\s*", re.I)

#: A STUTTER: the same word twice in a row, which Whisper writes down
#: faithfully. "remind me ME to prepare the presentation", "i need to go GO to
#: kombucha order ON ON friday". It breaks the fixed command frames the
#: routing depends on — "remind me to" stops matching — so the sentence is
#: misrouted by a word the speaker did not mean to say twice.
#:
#: Punctuation between the copies is allowed because a repair often arrives
#: with one: "fix the meeting tomorrow — tomorrow, the one with Parka".
_STUTTER = re.compile(r"\b(\w+)(?:[\s,—–-]+\1\b)+", re.I)

#: Courtesy wrappers that hide the command from anything anchored at ^.
_COURTESY = re.compile(
    r"^(?:can|could|would|will)\s+you\s+(?:please\s+)?"
    r"|^(?:please|kindly)\s+",
    re.I)

#: Mid-sentence self-corrections: "buy milk, I mean, buy bread". The speaker
#: replaced what came before, so the marker and what precedes it in that
#: clause are noise. Conservative: only after a comma, so it cannot eat a
#: sentence that merely contains the words.
_SELF_CORRECTION = re.compile(
    r",\s*(?:i mean|sorry|no wait|scratch that|rather)\b[,\s]*", re.I)

#: Trailing verbal shrug: "…tomorrow or something", "…at 6 or whatever".
_TRAILING_HEDGE = re.compile(
    r"\s+(?:or\s+(?:something|whatever|so)|you know|i guess)\s*[.!?]?$", re.I)


def strip_spoken_noise(text: str, drop_courtesy: bool = True) -> str:
    """Remove the words that carry no request. Idempotent and lossless in
    meaning: it never touches titles, dates, times or targets.

    `drop_courtesy` is False for readers that judge politeness themselves —
    FastRule's interrogative gate reads the RAW text to tell a question from
    a polite imperative, so the caller decides.
    """
    if not text:
        return text
    out = _OPENERS.sub("", text.strip())
    out = _NOW_OPENER.sub("", out)
    out = _STUTTER.sub(r"\1", out)
    if drop_courtesy:
        out = _COURTESY.sub("", out)
    out = _TRAILING_HEDGE.sub("", out)
    # a self-correction replaces the clause before it
    m = _SELF_CORRECTION.search(out)
    if m:
        head, tail = out[:m.start()], out[m.end():]
        if len(tail.split()) >= 2:          # only if something survives
            # keep any leading imperative the speaker did not retract
            lead = re.match(r"^\s*(\w+)\s", head)
            out = tail if not lead else tail
    return out.strip(" ,;")
