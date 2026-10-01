""""now" as a TIME — and only when it is one (Gil, 2026-09-30).

*"when I say like now, then you can automatically change that or replace now
with the time that it is currently … in a very deterministic manner … as long
as that now is not something more vague. So I'd also double check on that."*

Three real commands that day, all wrong: "Walk, Val, now" (a to-do, no time),
"Walk my dog Val now, thanks to …" (an event at the right clock — TOMORROW,
the passed-clock floor having rolled it a day), "The event now for walking my
dog …" (a to-do, no time). The date recogniser reads "now" as today 00:00, so
the reader's own "now -> the clock" fallback never fired, and the tagger that
decides event-or-to-do had no "now" in its table of times.

ONE definition, read by every place that needs it — segmentation's tagger
(`fastseg`: it is a clock, so Q26 makes it an event), FastRule's time reader
(`rule_parser._extract_temporal`) and Decompose/Validate's net
(`object_rules._rule_now_means_now`), and the two passed-clock floors, which
must never roll the present minute into tomorrow.

The vague senses are VETOES, each a phrase people say without meaning the
clock: "for now", "from now on", "a week from now" (arithmetic, not the
present), "now that …", "is now at 9" (an update), "by now", "until/till/up to now", "just now" (the
past), "not now", "as of now", "than now", "every now and then", "now and
again", and "Now, …" opening a sentence ("now, what do I have today").
"asap" and "immediately" are not here: they say how URGENT, not when.
"""
from __future__ import annotations

import datetime
import re

#: Before "now": the word that makes it vague. One lookbehind each (fixed width).
_BEFORE = (r"(?<!\bfor\s)(?<!\bby\s)(?<!\buntil\s)(?<!\btill\s)(?<!\bnot\s)(?<!\bjust\s)"
           r"(?<!\bfrom\s)(?<!\bup\sto\s)(?<!\bof\s)(?<!\bthan\s)(?<!\bevery\s)"
           # "the eye exam is now at 8:30" — "now" as "from here on", an update
           r"(?<!\bis\s)(?<!\bare\s)(?<!\bwas\s)(?<!'s\s)")
#: After "now": the words that make it vague.
_AFTER = r"(?!\s+on\b)(?!\s+that\b)(?!\s+and\s+(?:then|again)\b)"

#: "do it now", "do that now": how URGENT, like "asap" — not a slot.
_URGENT = r"(?<!\bit\s)(?<!\bthat\s)(?<!\bthis\s)"
#: A "now" OPENING a clause — at the start, or after a comma or full stop — is
#: the discourse word ("feed the cat is done, now add the trash to my list";
#: "now, what do I have") unless nothing follows it ("Walk, Val, now"). Found
#: on the negative surface: ten FastRule rows of exactly that shape became
#: events at the clock on the first cut.
_CLAUSE_HEAD = r"(?:(?<![,.;:]\s)(?<![,.;:])(?<!^)\bnow\b|\bnow(?=\s*[.!?]*\s*$))"

#: "now" or "right now" said as a time.
NOW_RE = re.compile(
    rf"(?:\bright\s+now\b|{_BEFORE}{_URGENT}{_CLAUSE_HEAD}){_AFTER}",
    re.I)


def says_now(text: str) -> bool:
    """Did the speaker give "now" as the time?"""
    return bool(NOW_RE.search(text or ""))


def clock(now: "datetime.datetime | None" = None) -> str:
    """The present minute, "HH:MM"."""
    return (now or datetime.datetime.now()).strftime("%H:%M")
