"""Is there a SEQUENCE seam here? — the rule both tracks share (DEVQA Q51).

"walk the dog at 5 followed by lunch followed by gym", "dentist at 9 and after
that lunch": the speaker said the parts happen one after another, so they are
separate things. Two readers must agree on that: segmentation's cutter
(`fastseg._hard_seams`), which cuts there and marks the relation, and FastRule's
compound gate (`fastrule.rule_verdict`), which must hand such a command to the
deep track instead of committing it whole as ONE event titled "walk the dog
followed by lunch followed by gym" — which is what it did until 2026-09-25.
One module, so they cannot disagree (the same reason `encounter.py` exists).
"""
from __future__ import annotations

import re

#: THE WORDS of a sequence, with the misspellings a transcript leaves in them
#: (Gil, 2026-09-25: *"capture the variety of wording … and account for
#: misspellings, because maybe they get fixed, maybe they don't"*):
#:   followed by   — also folowed / fallowed / followd / folowd
#:   then          — "and than" / ", than" too (never a bare "than": "more than")
#:   after that    — also after this / after tht / after dat; right / straight /
#:                   just after that; and then after that
#:   afterwards    — afterward / afterwords / after wards
#:   after which · subsequently · "and / then finally" (never a bare
#:                   "finally": "mark it done, finally got to it" is an aside)
#:   next up
#:   once / when / as soon as (that's | it's | I'm) done / finished / over
#:                   (with that) — the subject is required: "dinner when
#:                   finished work" is a time, not a seam; "once done," with
#:                   its comma is the one bare form
#: A doubled joiner ("then then") is swallowed whole.
SEQUENCE_WORDS = (
    r"(?:(?:and\s+)?then\s+)?(?:right\s+|straight\s+|just\s+)?"
    r"(?:f[ao]l+o?w?e?d\s+by"
    r"|(?:and\s*|,\s*)th[ae]n|then"
    r"|after\s+(?:that|this|tht|dat)"
    r"|after\s*w[ao]rds?|after\s+which|subsequently|(?:and|then)\s+finally|next\s+up"
    r"|(?:once|when|as\s+soon\s+as)\s+(?:that|it|i)(?:'s|'m|\s+is|\s+am)?\s+"
    r"(?:done|finished|over)(?:\s+with\s+(?:that|it))?"
    r"|once\s+(?:done|finished)(?=\s*,))"
    r"(?:\s+then)?")

#: "NEXT" orders a list only when it is set off — ", next X", ". Next, X",
#: "and next X" — and never before a date word ("next friday", "next week's
#: report") or after an article ("the next meeting", which the set-off
#: requirement already excludes).
_NEXT = (r"next\b(?!\s*'s)(?!\s+(?:week|weekend|month|year|time|days?|morning|afternoon|evening|night"
         r"|(?:mon|tues|wednes|thurs|fri|satur|sun)day|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*)")

#: The seam: the words, set off from what precedes them by a space or a comma.
SEQUENCE_SEAM = re.compile(r"(?:\s*,\s*(?:and\s+)?(?:than\b|" + SEQUENCE_WORDS + r")"
                           r"|\s+(?:and\s+)?" + SEQUENCE_WORDS + r")\b[,\s]*"
                           r"|\s*[,.;]\s*(?:and\s+)?" + _NEXT + r"[,\s]*"
                           r"|\s+and\s+" + _NEXT + r"[,\s]*", re.I)
_WORDS_ONLY = re.compile(r"\b(?:" + SEQUENCE_WORDS + r"|" + _NEXT + r")\b", re.I)


def is_sequence_words(between: str) -> bool:
    """Do the words BETWEEN two items say "one after the other"? Read by
    segmentation's `relate` so the relation names the same seams the cutter
    cuts at."""
    return bool(_WORDS_ONLY.search(between or ""))


#: A part that opens with a subject pronoun and a verb is a remark about the
#: plan ("and then we'll see", "then it's done"), not a thing to schedule.
_REMARK_OPENER = re.compile(
    r"^(?:i|we|you|it|that|this|they|he|she|there)(?:'ll|'s|'re|'m|'d|\s+(?:will|is|are|was|"
    r"were|can|could|should|might|may|would|have|had|do|did|see|go|get))\b", re.I)


def starts_a_remark(right: str) -> bool:
    return bool(_REMARK_OPENER.match((right or "").strip()))


def _has_content(right: str) -> bool:
    return bool(re.search(r"[a-z]{2,}", right or "", re.I))


def has_sequence_seam(text: str) -> bool:
    """True when `text` holds a sequence seam with a thing on each side that is
    not a remark, and the seam is not inside a time reference."""
    from assistant.engine.segmentation.fastseg.fastseg import find_time_refs
    refs = find_time_refs(text or "")
    for m in SEQUENCE_SEAM.finditer(text or ""):
        if any(r.start < m.end() and m.start() < r.end for r in refs):
            continue
        left, right = text[:m.start()], text[m.end():]
        if left.strip() and _has_content(right) and not starts_a_remark(right):
            return True
    return False


#: A POSTPOSED marker — the sequence said AFTER the thing it orders: "physio at
#: 2, product demo after that", "…, a working lunch afterwards", "…, training
#: with Mark right after the play". The comma before such a part is a sequence
#: seam; the marker is not part of the title, except a NAMED anchor ("right
#: after the play"), which the chain needs to find what it follows.
TRAILING_MARKER = re.compile(
    r"\s+(?P<m>(?:(?:right|straight|just)\s+)?(?:after\s*w[ao]rds?|after\s+(?:that|this|tht|dat)))\s*[.!]?\s*$"
    r"|\s+(?P<named>(?:right|straight|just)\s+after\s+(?:the\s+|my\s+|our\s+)?[a-z][\w' -]{1,40})\s*[.!]?\s*$",
    re.I)


def trailing_marker(piece: str) -> "re.Match | None":
    """The postposed sequence marker ending `piece`, when something precedes it."""
    m = TRAILING_MARKER.search(piece or "")
    if m and _has_content(piece[:m.start()]):
        return m
    return None
