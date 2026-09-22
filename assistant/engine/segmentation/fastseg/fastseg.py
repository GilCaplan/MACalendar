"""FastSeg — the deterministic half of the segment component.

    text  ->  [(action, time, tag), ...]

Three phases, in this order, and the order is measured rather than chosen:
DialogUSR's ablation (Findings of EMNLP 2022) reports Split -> (Delete +
Complete) beating the reverse by 9 exact-match points, which is exactly the
cut-then-assign shape below.

  1  CUT          delimiters, then the clause parse, looped to a fixed point
  2  ASSIGN TIME  reads the pieces AND the original string together
  3  TAG          event | task | review

It lives in `assistant/engine/segmentation/experiments/` rather than in `assistant/engine/` on purpose:
this is the thing being tuned, and the engine is serving a phone. It IMPORTS
the two stable readers it needs (the clause splitter and the ask guard) rather
than copying them, so a fix there is not made twice.

Why phase 2 exists as its own phase, in Gil's words: "given a string input we
need to break down to all the independent actions, then GIVEN THAT AND THE
ORIGINAL STRING adjust the time tag." Once a command has been cut, a splitter
working piece-by-piece can no longer see that a leading "tomorrow" covers the
second piece too. Holding both is what makes the distribution possible.
"""
from __future__ import annotations

import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from assistant.engine.segmentation.fastseg import invariant as _invariant   # noqa: E402

# ---------------------------------------------------------------------------
# TIME EXPRESSIONS
#
# The extractor answers one question: where in the string is a time reference,
# and what kind is it. It never RESOLVES — "next friday" stays "next friday".
# Gil: "the time will be friday. dont add more information that is not your
# job here." Resolution belongs to a later stage; doing it here would invent
# information the speaker did not give.
# ---------------------------------------------------------------------------

_WEEKDAY = (r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
            r"|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun")
_MONTH = (r"january|february|march|april|may|june|july|august|september"
          r"|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept"
          r"|oct|nov|dec")

_HOURWORD = (r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve")
#: Minute words a spoken clock can end in. Deliberately a CLOSED list: an open
#: `\w+` would read "book three rooms" as 3:00-something.
_MINWORD = (r"o'?clock|fifteen|twenty[\s-]five|twenty|thirty[\s-]five|thirty|"
            r"forty[\s-]five|forty|fifty[\s-]five|fifty|ten|five")
_COUNTWORD = (r"a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
              r"|\d+")
#: One end of a spoken range. Bare numbers are allowed HERE and nowhere else,
#: because "between 2 and 4" is unambiguous while a loose "2" is not.
_RANGEEND = (rf"(?:\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm|a\.m\.|p\.m\.)?"
             rf"|noon|midday|midnight|{_HOURWORD})")

#: Ordered longest-first: a longer phrase must win over a fragment of itself,
#: or "every friday" is read as the bare date "friday" and the recurrence is
#: lost. Each entry is (pattern, kind).
_TIME_PATTERNS: "list[tuple[str, str]]" = [
    # --- recurrence. Temporal repetition IS the time (Gil's ruling), so it is
    #     captured whole rather than reduced to the weekday inside it.
    (rf"\bevery\s+other\s+(?:{_WEEKDAY}|day|week|month)\b", "recurrence"),
    (rf"\bevery\s+(?:{_WEEKDAY}|weekday|day|week|month|morning|evening|night)\b",
     "recurrence"),
    (r"\b(?:daily|weekly|monthly|nightly)\b", "recurrence"),
    (rf"\beach\s+(?:{_WEEKDAY}|day|week|month)\b", "recurrence"),

    # --- deadline markers. These are what distribute across a whole command
    #     ("submit the grades and prepare the slides BY FRIDAY").
    (rf"\b(?:by|before|due|until|till)\s+(?:the\s+)?"
     rf"(?:{_WEEKDAY}|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?|today|tomorrow|tonight"
     rf"|next\s+\w+|this\s+\w+|the\s+\d{{1,2}}(?:st|nd|rd|th)|end\s+of\s+\w+)\b",
     "deadline"),

    # --- clock times
    # `(?!\w)` and not `\b` after a meridiem: a word boundary needs a word
    # character on one side, and after the final "." of "p.m." at the end of
    # the sentence there is none — so "at 11 a.m." matched only "at 11" and
    # left "a.m." stranded in the ACTION, which is where the real-usage
    # titles 'meeting a.m' and 'meeting p.m. p.m. as well' came from
    # (2026-09-22, cycle 35). Every meridiem in this table ends the same way.
    # `[:.]` — the period separator too, so "at 14.30" is ONE candidate of
    # eight characters and beats "at 14" outright. It used to win by accident:
    # the period entry below swallowed its trailing space into the match and
    # was longer by one, which `(?!\w)` no longer allows.
    (r"\bat\s+(?:around\s+|about\s+)?\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?"
     r"(?:\s*o'?clock)?(?!\w)", "clock"),
    # "for 1 p.m.", "for 12 o'clock": a clock after FOR. Only with a meridiem
    # or o'clock, because "for 2 hours" and "for 3 people" are not clocks.
    (r"\bfor\s+\d{1,2}(?:[:.]\d{2})?\s*(?:(?:am|pm|a\.m\.|p\.m\.)(?!\w)|o'?clock\b)",
     "clock"),
    # COMPACT clocks — how the recogniser writes a spoken "nine ten": "910am",
    # "230PM", and after a clock preposition a bare "830" / "1040". The same
    # two shapes the resolvers read (`decompose_validate/resolve.py`,
    # `rule_parser.py`); a bare one needs the preposition and nothing
    # noun-like after it, so "for 200 people" stays a count.
    (r"\b\d{3,4}\s*(?:am|pm|a\.m\.|p\.m\.)(?!\w)", "clock"),
    (r"\b(?:at|for|from|until|till|by|around|about)\s+\d{3,4}\b(?![:.]\d)"
     r"(?=\s*(?:$|[,.;!?]|(?:on|tomorrow|today|tonight|this|next|and|then|to|for|"
     r"with|in|at|the|execute|sharp|o'?clock|morning|afternoon|evening|night|"
     r"shacharit|shachris|mincha|maariv|arvit)\b))", "clock"),
    (r"\b\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?(?!\w)", "clock"),
    # PERIOD as the hour/minute separator ("11.15am", "11.15 AM", bare
    # "14.30") -- the international way of writing a clock time, and a real
    # live-usage defect: without this, the bare "N (am|pm)" entry below can
    # only match from the FIRST digit onward, so against "11.15 AM" it finds
    # nothing starting at "11" (followed by "." not "am") and matches
    # "15 AM" instead -- stranding "11" in the action and reading the clock
    # as 15:00 (3pm) rather than 11:15. am/pm is OPTIONAL here, matching the
    # colon form above -- Gil's call (2026-09-15), knowingly traded against a
    # bare decimal number or a price ("$11.15") now being read as a clock
    # and pulled out of whatever title it was part of.
    (r"\b\d{1,2}\.\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?(?!\w)", "clock"),
    (r"\b\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.)(?!\w)", "clock"),
    (r"\b(?:half\s+past|quarter\s+past|quarter\s+to)\s+\w+\b", "clock"),
    (r"\b(?:noon|midday|midnight)\b", "clock"),
    (r"\bat\s+(?:first\s+thing|lunchtime|dinnertime)\b", "clock"),

    # --- dates
    (r"\b(?:the\s+)?day\s+after\s+tomorrow\b", "date"),
    (r"\b(?:today|tomorrow|tonight|yesterday)\b", "date"),
    (rf"\b(?:next|this|last|coming)\s+(?:{_WEEKDAY}|week|month|year|weekend)\b",
     "date"),
    (rf"\bthis\s+coming\s+(?:{_WEEKDAY})\b", "date"),
    (rf"\bon\s+(?:the\s+)?(?:{_WEEKDAY})\b", "date"),
    (rf"\b(?:{_WEEKDAY})\b", "date"),
    (rf"\b(?:{_MONTH})\s+\d{{1,2}}(?:st|nd|rd|th)?\b", "date"),
    (r"\bthe\s+\d{1,2}(?:st|nd|rd|th)\b", "date"),
    (r"\bin\s+(?:a|an|one|two|three|four|five|\d+)\s+(?:day|week|month)s?\b", "date"),
    # "two weeks from now", "a week from today". Generalised from the original
    # "a week from (today|tomorrow|now)": the bank renders counted variants too,
    # and the narrow pattern found only the bare "today" inside them.
    (r"\b(?:a|an|one|two|three|four|five|six|\d+)\s+(?:day|week|month)s?\s+"
     r"from\s+(?:today|tomorrow|now)\b", "date"),
    (r"\b(?:this|next)\s+(?:morning|afternoon|evening)\b", "date"),
    (r"\b(?:in\s+the\s+)?(?:morning|afternoon|evening)\b", "date"),
    (r"\bnew\s+year'?s\s+eve\b", "date"),
    (r"\bchristmas(?:\s+day)?\b", "date"),

    # ================= 2026-09-09 span vocabulary (PLAN.md Phase 1) ==========
    # Ordering in this list does NOT matter: `find_time_refs` collects every
    # candidate and takes them longest-first. These are entries, not placements.

    # --- LEAD TIME, a reference in its own right. The `lead_time` trap sat at
    #     0.0% on 72 rows because nothing here matched "15 minutes before".
    (rf"\b(?:half\s+an?|{_COUNTWORD})\s+(?:minute|min|hour|day|week)s?\s+"
     r"(?:before|beforehand|ahead|prior|in\s+advance)\b", "lead"),

    # --- RANGES as ONE reference. Matched as two ends (or not at all), which
    #     left "from 3" in the action and "to 4pm" as the whole time.
    (rf"\b(?:from|between)\s+{_RANGEEND}\s+(?:to|until|till|and|through|thru)\s+"
     rf"{_RANGEEND}\b", "range"),

    # --- CLOCK + half of day as ONE span. Two refs before this, so the digit
    #     stranded in the action AND "in the morning" read as a DAY, which
    #     suppressed the date floor. One entry, two symptoms.
    (rf"\b(?:\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)?|{_HOURWORD})\s+in\s+the\s+"
     r"(?:morning|afternoon|evening)\b", "clock"),

    # --- COARSE + MODIFIER. The bare word matched and the modifier stranded
    #     ("book yoga late" / "afternoon"). Clock-class because gold FLOORS it.
    (r"\b(?:early|late|mid)[\s-]*(?:morning|afternoon|evening|night)\b", "clock"),
    (r"\bfirst\s+thing(?:\s+in\s+the\s+morning)?\b", "clock"),
    (r"\b(?:around|about)?\s*(?:lunchtime|dinnertime|suppertime)\b", "clock"),

    # --- SPOKEN CLOCKS. Not matched at all before; Whisper writes what was said.
    (rf"\b(?:{_HOURWORD})\s+(?:{_MINWORD})\b", "clock"),
    (rf"\b(?:half|quarter|twenty[\s-]five|twenty|fifteen|ten|five)\s+"
     rf"(?:past|to)\s+(?:{_HOURWORD}|\d{{1,2}})\b", "clock"),

    # --- "12 noon": `noon` won and the 12 stranded — the `at late` bug again.
    (r"\b12\s*(?:noon|midday)\b", "clock"),

    # --- OFFSET IN HOURS. The offset pattern covers day/week/month and not hour,
    #     so "in two hours" produced no reference whatsoever (corpus 25x).
    (rf"\bin\s+(?:{_COUNTWORD})\s+hours?\b", "clock"),

    # --- END OF A MONTH / YEAR (corpus 74x), outside a deadline marker too.
    (rf"\b(?:the\s+)?end\s+of\s+(?:the\s+)?(?:month|year|week|{_MONTH})\b", "date"),

    # --- A PLURAL WEEKDAY IS A SERIES, not a date: "gym on sundays" is weekly.
    #     `\bsunday\b` cannot match "sundays" (corpus 31x, dataset had 0 rows).
    (rf"\b(?:on\s+)?(?:{_WEEKDAY})s\b", "recurrence"),

    # --- ONE-WORD and FREQUENCY cadences (corpus 79x).
    (r"\b(?:everyday|every\s+year|annually|yearly|biweekly|fortnightly)\b",
     "recurrence"),
    (r"\b(?:once|twice|thrice)\s+a\s+(?:day|week|month|year)\b", "recurrence"),
    (r"\bevery\s+(?:weekend|other\s+day)\b", "recurrence"),
    (r"\bevery\s+\w+\s+(?:days|weeks|months)\b", "recurrence"),

    # --- MONTH + ORDINAL in the "of" order. This is §8.2: the bare-ordinal
    #     pattern won and "of november" stranded, so the MONTH was never handed
    #     downstream at all.
    (rf"\b(?:the\s+)?\d{{1,2}}(?:st|nd|rd|th)?\s+of\s+(?:{_MONTH})\b", "date"),

    (r"\bthe\s+rest\s+of\s+the\s+day\b", "date"),

    # --- A BOUNDED ENUMERATION OF TIMES (§8.1). "at 9 and 2:30" is one activity
    #     at SEVERAL times, so it is captured whole here and expanded into one
    #     item per time by `_expand_enumerations` below. Captured rather than cut
    #     because `cut` returns substrings of the text and `_locate` needs them to
    #     be substrings — a synthesised "walk the dog at 2:30" is not one.
    #
    #     It cannot swallow the decoys: `between 2 and 4` and
    #     `every tuesday and thursday` are LONGER patterns and win outright, and
    #     `meeting with Sam and Alex at 8` has no time on the left of its joiner.
    (rf"\b(?:at\s+)?{_RANGEEND}(?:\s*,\s*(?:at\s+)?{_RANGEEND})*"
     rf"\s+and\s+(?:at\s+)?{_RANGEEND}\b", "enum_clock"),
    (rf"\b(?:on\s+)?(?:{_WEEKDAY})(?:\s*,\s*(?:on\s+)?(?:{_WEEKDAY}))*"
     rf"\s+and\s+(?:on\s+)?(?:{_WEEKDAY})\b", "enum_day"),

    # --- WEEKDAY + half of day as ONE span. As two refs, the trailing "morning"
    #     made the right-hand side of a conjunct look TIMED, and
    #     "a cut and blow dry on saturday morning" split into two items.
    (rf"\b(?:{_WEEKDAY})\s+(?:morning|afternoon|evening|night)\b", "date"),
    (rf"\b(?:tomorrow|today|tonight)\s+(?:morning|afternoon|evening|night)\b", "date"),

    # --- A MULTI-DAY SERIES is ONE reference: "every tuesday and thursday" is a
    #     weekly series naming two days (Gil, 2026-09-08), not two references
    #     with a joiner between them — read as two, the "and" split the series.
    (rf"\bevery\s+(?:{_WEEKDAY})(?:\s*,\s*(?:{_WEEKDAY}))*"
     rf"(?:\s+and\s+(?:{_WEEKDAY}))+\b", "recurrence"),
]

_COMPILED = [(re.compile(p, re.I), kind) for p, kind in _TIME_PATTERNS]


class TimeRef:
    """One time expression, and where it sits in the command."""

    __slots__ = ("start", "end", "text", "kind")

    def __init__(self, start: int, end: int, text: str, kind: str):
        self.start, self.end, self.text, self.kind = start, end, text, kind

    def __repr__(self) -> str:                     # pragma: no cover
        return f"TimeRef({self.text!r}@{self.start}:{self.end},{self.kind})"


def find_time_refs(text: str) -> "list[TimeRef]":
    """Every time expression in the command, left to right, non-overlapping.

    Longest match wins at a given position, which is what keeps "every friday"
    whole instead of yielding the bare date "friday".

    That used to be a claim in this docstring rather than a property of the
    code: the pattern list is grouped by KIND, and within the date group the
    bare `today` sits above `a week from today`, so "plan lunch a week from
    today" yielded `today` and left "a week from" stranded in the action. It
    cost 31 of the 66 content-loss rows and mis-assigned the time on every one
    of them. Now the matches are collected first and taken longest-first, so
    the ordering of `_TIME_PATTERNS` cannot silently decide the answer.
    """
    candidates: list[tuple[int, int, str]] = []
    for rx, kind in _COMPILED:
        for m in rx.finditer(text):
            candidates.append((m.start(), m.end(), kind))
    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))

    refs: list[TimeRef] = []
    taken = [False] * (len(text) + 1)
    for start, end, kind in candidates:
        if any(taken[start:end]):
            continue                               # inside something already taken
        # Trim trailing whitespace the pattern swallowed. "at 7 " ended one
        # character past its own piece, so the reference fell OUTSIDE the
        # piece that owned it and was treated as an edge — which silently
        # distributed a clock time across the whole command.
        s, e = start, end
        while e > s and text[e - 1].isspace():
            e -= 1
        s = _absorb_preposition(text, s, taken)
        refs.append(TimeRef(s, e, text[s:e].strip(), kind))
        for i in range(s, e):
            taken[i] = True
    refs.sort(key=lambda r: r.start)
    return refs


#: SPEC captures the time AS SPOKEN — "by friday", "on the 15th", "for
#: christmas day" — but only some patterns spell their preposition out, so
#: `the 15th` and `christmas day` came back bare. That cost twice over: the
#: preposition was missing from the time AND left stranded in the action
#: ("schedule flight to Chicago for"). Absorbing it here fixes both at once,
#: and keeps this list identical to the generator's `_PREP`, so gold and
#: prediction cannot disagree by convention.
_LEADING_PREP = re.compile(
    r"\b(at|on|for|by|from|in|to|starting|until|through|around)\s+$", re.I)


def _absorb_preposition(text: str, start: int, taken: "list[bool]") -> int:
    """Extend a reference left over the preposition(s) it was spoken with.

    "for at the end of the month" stacks two — the generator glues "at" onto
    "the end of the month" the same way it does everywhere else, and "for"
    governs the whole deadline phrase on top of that — so one hop absorbed
    "at" and left "for" stranded as a dangling word in the action. Looped
    rather than a single hop, same reason `_tidy`'s own dangling-preposition
    strip is a loop ("…for on" needs two passes) — one preposition can sit
    directly in front of another.
    """
    while True:
        m = _LEADING_PREP.search(text, 0, start)
        if not m or any(taken[m.start():start]):
            return start
        start = m.start()


# ---------------------------------------------------------------------------
# PHASE 1 — CUT
# ---------------------------------------------------------------------------

def cut(text: str, max_rounds: int = 3) -> "list[str]":
    """The command split into independent asks, as substrings.

    Looped to a FIXED POINT rather than run once. Measured before building:
    re-running the splitter on its own output changes the count on 2 of 5,014
    FastRule rows and 8 of 847 real-speech rows, and the rows it fixes are the
    three-ask ones — the splitter can leave a boundary on the table. The loop
    is free (no model, microseconds) and collects that whole ceiling.

    A fixed point is also the stopping test the literature uses: DisSim
    recurses a rule set until no rule fires, ADaPT recurses on executor
    failure, DecomP on a size check. None of them train an "is this atomic?"
    model, and the one paper that did reports 54-66% on the decision.
    """
    from assistant.intent.asks import every_part_is_an_ask
    from assistant.intent.coordination import split_clauses

    def once(piece: str) -> "list[str]":
        # Hand over the time spans this module has ALREADY found, position-
        # independently. `clause_boundaries` cannot ask the parse where the
        # time is — the parse is what moves — so the reader that located it
        # supplies the answer.
        parts = [q.strip() for q in split_clauses(
            piece, date_spans=[(r.start, r.end) for r in find_time_refs(piece)])
            if q.strip()]
        if len(parts) < 2 or not every_part_is_an_ask(parts):
            return _split_verbless_conjuncts(piece)
        return parts

    pieces = _hard_seams(text)
    for _ in range(max_rounds):
        nxt: list[str] = []
        for piece in pieces:
            nxt.extend(once(piece))
        if len(nxt) == len(pieces):
            break                                   # fixed point reached
        pieces = nxt
    return [p for p in pieces if p.strip()]


#: An ask seam the SPEAKER put there: a sentence boundary followed by a
#: joiner ("trash. Also, PUT MILK…"), a dash-and, or ", (and) then". FastRule's
#: front door has treated every one of these as a compound since its first
#: board (`_STRONG_COMPOUND_RE`) — and the cutter never cut there: the clause
#: tier wants two verbs it can see, and the joiner regex below wants a comma
#: before "also" and whitespace after. Four of the dev-100 checkpoint's 26
#: misses were exactly this (2026-09-20): one item, then decompose_validate
#: multiplied it into junk.
_HARD_SEAM = re.compile(
    r"[.;!?]\s+(?:and\s+)?(?:also|then|plus|and)\b[,\s]*"
    r"|\s+[—–]\s*and\b[,\s]*"
    r"|\s*,\s*(?:and\s+)?then\b[,\s]*", re.I)
#: NOT here: a bare " and then " with no comma. The clause tier already cuts it
#: when both sides have a verb, and as a hard seam it cut "meet sam and then
#: we'll see" into an ask and a remark.


def _hard_seams(text: str) -> "list[str]":
    """Cut at the seams the speaker marked, before any parse. Each piece is a
    substring of `text` with the seam itself removed, so the verbatim-span
    lookup (`_source_piece`) still finds it. A seam inside a time reference is
    never a boundary ("between 2 and then…" does not occur; a range's "and"
    has no "then"/"also" after it, but the guard is kept for the dash form)."""
    refs = find_time_refs(text)
    out, start = [], 0
    for m in _HARD_SEAM.finditer(text):
        if any(r.start < m.end() and m.start() < r.end for r in refs):
            continue
        left, right = text[start:m.start()], text[m.end():]
        if len(left.split()) < 2 or len(right.split()) < 2:
            continue                                # a seam needs an ask on each side
        out.append(left.strip())
        start = m.end()
    out.append(text[start:].strip())
    return [p.strip(" ,;.") for p in out if p.strip(" ,;.")]


_CUT_JOINER = re.compile(r"\s*,\s*(?:and then|and also|and|then|also|plus)\s+"
                         r"|\s+(?:and then|and also|as well as|and|then|also|plus)\s+"
                         r"|\s*,\s*")


def _split_verbless_conjuncts(piece: str) -> "list[str]":
    """Split "set up physical therapy at 9:15 and birthday dinner at midnight".

    The clause splitter cannot see this boundary: the second conjunct is a bare
    NOUN PHRASE with no verb of its own, so nothing marks it as a clause. It is
    the single largest cut failure in the corpus — 29 of the 189 under-split
    rows sit on a plain "and", and another 24 on a bare comma.

    The evidence used instead of a verb is that **both sides carry their own
    time reference, and the right side has content that is not part of its
    time**. That second condition is what keeps the must-not-split decoys
    intact, and it is doing real work:

        set up physical therapy at 9:15 and birthday dinner at midnight
            right = "birthday dinner at midnight" -> "birthday dinner" left
            over once its time is removed                        -> SPLIT
        walk the dog at 9 and 2:30
            right = "2:30" -> nothing left over                  -> keep
        take the tablets at noon and at six
            right = "at six" -> nothing left over                -> keep
        meeting with Sam and Alex at 8
            LEFT carries no time at all                          -> keep

    A joiner sitting INSIDE a time reference is never a boundary — "book gym
    between 2 and 4" would otherwise cut its own range in half.
    """
    refs = find_time_refs(piece)
    if len(refs) < 2:
        return [piece]

    def timed(span: str) -> bool:
        """Does this side carry a time of its OWN?

        A LEAD TIME does not count. "book the gym at 1pm and give me a nudge an
        hour before" is ONE ask: the lead time modifies the same event rather than
        timing a second one, and counting it made the reminder clause look like an
        independent ask — 20 rows of over-split the moment lead times became
        visible (2026-09-09).
        """
        return any(r.kind != "lead" for r in find_time_refs(span))

    def has_own_content(span: str) -> bool:
        """Content left in the span once its time expressions are removed."""
        rest = span
        for ref in sorted(find_time_refs(span), key=lambda r: -r.start):
            rest = rest[:ref.start] + " " + rest[ref.end:]
        return bool(_invariant.content(rest))

    out: "list[str]" = []
    start = 0
    for m in _CUT_JOINER.finditer(piece):
        if any(r.start < m.end() and m.start() < r.end for r in refs):
            continue                                # joiner inside a time span
        left, right = piece[start:m.start()], piece[m.end():]
        if not left.strip() or not right.strip():
            continue
        if timed(left) and timed(right) and has_own_content(right):
            out.append(left.strip())
            start = m.end()
    out.append(piece[start:].strip())
    out = [p for p in out if p]
    return out if len(out) > 1 else [piece]


# ---------------------------------------------------------------------------
# PHASE 2 — ASSIGN TIME
# ---------------------------------------------------------------------------

#: What can follow "before" WITHOUT making it the object of that "before" —
#: a to-infinitive ("...before TO submit the report"), a preposition fronting
#: a separate clause about what the reminder concerns ("...before ABOUT
#: annual checkup", "...before FOR flight to Chicago"), or another lead-marker
#: synonym starting its OWN clause ("15 minutes BEFORE BEFORE team meeting",
#: "30 minutes before AHEAD OF conference call" — two idioms concatenated by
#: the generator, where the first "before" is the extractable duration-lead
#: and the second is the transitive one governing the named event). English
#: "before" is used BOTH transitively (governing a noun right after it:
#: "before haircut") and intransitively/adverbially ("an hour before", full
#: stop, or continued by a clause of its own) — this is the closed set the
#: corpus's generated templates use for the second reading.
_LEAD_INTRANSITIVE = re.compile(
    r"^\s*(?:about|for|to|before|beforehand|ahead|prior|in\s+advance)\b", re.I)


def _lead_has_no_object(text: str, ref: "TimeRef",
                        spans: "list[tuple[int, int]]") -> bool:
    """A DURATION-before reference ("an hour before") is its own time slot
    only when "before" has no NOUN object of its own within this piece —
    nothing follows it at all, or what follows is a to-infinitive/preposition
    starting a new clause rather than the thing "before" governs.

    "remind me to organize the garage an hour before SCHOOL PLAY at around
    lunchtime" was matching "an hour before" as a clock-class ref on its own,
    which stripped it from the action and left "school play" an orphaned
    fragment glued onto whatever came before it ("…the garage school play") —
    "before" here is TRANSITIVE, governing "school play" as its object, so the
    object has to stay with it in the action, the same as any other
    preposition-object pair ("with SAM", "to THE STORE").
    "remind me two hours before about annual checkup the 30th at 14:00" is the
    other reading: "before" here is used adverbially ("in advance"), and
    "about annual checkup" is a SEPARATE clause naming what the reminder
    concerns, not its object — the correct case to still treat "before" as
    its own time reference (`_is_reminder_lead_time` is `coordination.py`'s
    version of the same distinction, anchored to the whole clause instead of
    to what immediately follows).
    """
    piece_end = next((e for s, e in spans if s <= ref.start and ref.end <= e),
                     len(text))
    tail = text[ref.end:piece_end]
    if not re.search(r"[A-Za-z0-9]", tail):
        return True                      # bare idiom, nothing follows at all
    return bool(_LEAD_INTRANSITIVE.match(tail))


def assign_times(text: str, pieces: "list[str]") -> "list[tuple[str, str]]":
    """(action, time) per piece, from the pieces AND the original together.

    The rule, from Gil's five worked cases:

        INTERIOR reference  -> binds to its own piece
        EDGE reference      -> covers every piece that has none of its own

    "Edge" means the reference sits before the first piece's content or after
    the last piece's, belonging to no piece on its own. That single rule gets
    all five cases right, including the two that look contradictory: a leading
    "tomorrow" covers both pieces, a trailing "by friday" covers both, and a
    "tomorrow" sitting INSIDE the second piece does not reach back to the
    first.
    """
    spans = _locate(text, pieces)
    refs = [r for r in find_time_refs(text)
            if r.kind != "lead" or _lead_has_no_object(text, r, spans)]

    owned: "list[list[TimeRef]]" = [[] for _ in pieces]
    lead: "list[TimeRef]" = []
    trail: "list[TimeRef]" = []
    last = len(pieces) - 1
    for ref in refs:
        for i, (s, e) in enumerate(spans):
            if s <= ref.start and ref.end <= e:
                owned[i].append(ref)
                # EDGE means at the boundary of the whole COMMAND, not outside
                # every piece — a trailing reference is textually inside the
                # last piece. So: opening the first piece, or closing the last.
                if len(pieces) > 1:
                    if i == 0 and ref.start <= s + 1:
                        lead.append(ref)
                    elif i == last and ref.end >= e - 1:
                        trail.append(ref)
                break
        else:
            lead.append(ref)

    out: "list[tuple[str, str]]" = []
    for i, piece in enumerate(pieces):
        mine = list(owned[i])
        # The two edges do NOT distribute the same way.
        #
        # LEADING fills a SLOT the piece left empty, not merely a piece that
        # named nothing at all: "tomorrow gym at 7 and meeting at 11" — the
        # second piece has a clock but no DAY, so "tomorrow" still reaches it.
        # Distributing only to time-less pieces would leave that meeting today.
        #
        # TRAILING reaches only a piece with NO time whatsoever. "submit the
        # grades and prepare the slides by friday" — the first piece has
        # nothing, so it takes "by friday". But in "do i have anything this
        # weekend and book the haircut at 3:45" the trailing clock must stay
        # with the haircut; per-slot distribution gave the question "this
        # weekend at 3:45", which is wrong. Found by generating gold from the
        # templates, not by reasoning — see generate.py.
        have = {_slot(r) for r in mine}
        for r in lead:
            if _slot(r) not in have and r not in mine:
                mine.append(r)
                have.add(_slot(r))
        if not mine:
            mine = list(trail)
        # BY SLOT CLASS, then position — the order gold uses
        # (`order = {"day": 0, "clock": 1}`, stable). Joining by position alone
        # scored "every week at 8 o'clock until next tuesday" against gold's
        # "every week until next tuesday at 8 o'clock": same tokens, wrong order.
        time_str = " ".join(r.text for r in sorted(
            mine, key=lambda r: (_SLOT_ORDER[_slot(r)], r.start)))
        action = _strip_spans(piece, [(r.start - spans[i][0], r.end - spans[i][0])
                                      for r in owned[i]])
        # THE DATE FLOOR (SPEC): the day defaults to today, the clock never
        # does. An item with a clock and no day is "today at 7", not "at 7".
        # FastSeg emitted the bare form while the tuned LLMSeg prompt taught
        # the floored one, so the two halves disagreed on every clock-only
        # item and the accept step paid for it on each.
        if not any(_slot(r) == "day" for r in mine):
            time_str = f"today {time_str}".strip()
        out.append((action, time_str))
    return out


#: The gold's own two classes (`experiments/generate.py`: `_DAY_SLOTS` /
#: `_CLOCK_SLOTS`), and the order it joins them in. Matched rather than invented —
#: gold puts `lead_time` and `time_range` on the CLOCK side, so a lead falling to
#: "day" here would both collide with a real date and satisfy the
#: `any(_slot(r) == "day")` test that guards the date floor, silently switching the
#: floor off.
_SLOT_ORDER = {"day": 0, "clock": 1}


def _slot(ref: "TimeRef") -> str:
    """Which slot a reference fills. A day and a clock time are different
    slots, so one does not block the other from being distributed."""
    return "clock" if ref.kind in ("clock", "range", "lead", "enum_clock") else "day"


def _locate(text: str, pieces: "list[str]") -> "list[tuple[int, int]]":
    """Where each piece sits in the original. Pieces are substrings by
    construction (the cut only ever removes joiners), so a forward scan is
    exact; a piece that cannot be found falls back to a zero-width span at the
    cursor, which simply means it owns no time reference."""
    spans, cursor = [], 0
    for p in pieces:
        idx = text.find(p, cursor)
        if idx < 0:
            idx = text.find(p)
        if idx < 0:
            spans.append((cursor, cursor))
            continue
        spans.append((idx, idx + len(p)))
        cursor = idx + len(p)
    return spans


def _strip_spans(piece: str, spans: "list[tuple[int, int]]") -> str:
    """The piece with its own time expressions removed — this is `action`.

    Everything else stays, which is the point: the verb, the object, people,
    places, and any quantity ("buy 5 apples"). Gil: "make sure the action
    includes all the text for that item that is not related to time so we dont
    lose information like occurences etc which the decompose step is suppose
    to deal with."
    """
    if not spans:
        return _tidy(piece)
    keep, cursor = [], 0
    for s, e in sorted(spans):
        s, e = max(0, s), min(len(piece), e)
        if s > cursor:
            keep.append(piece[cursor:s])
        cursor = max(cursor, e)
    keep.append(piece[cursor:])
    return _tidy(" ".join(keep))


#: Prepositions left dangling when the time they governed is cut out — "book
#: the gym ON" reads as damage, and the token carries no information once its
#: object is gone.
_DANGLING = re.compile(r"\s+(?:on|at|for|in|by|from|to|of|this|next)\s*$", re.I)

#: A bare leading "to" is what's left of "remind me TO sign the permission
#: slip" once cut() severs it from "remind me" at a clause boundary ("remind
#: me to X and TO Y") — the infinitive marker belonged to the framing verb,
#: not to this piece's own content. Checked against the whole corpus (1,711
#: rows, both halves): not one gold action ever starts with "to " — the
#: framing verb's OWN piece keeps "remind me to X" whole (there the "to" is
#: attached to a verb IN this piece), so the strip is safe applied everywhere
#: `_tidy` runs, not just at a clause boundary.
_LEADING_TO = re.compile(r"^to\s+", re.I)


def _tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" ,;.")
    prev = None
    while prev != s:                                # "…for on" needs two passes
        prev = s
        s = _DANGLING.sub("", s).strip(" ,;.")
    s = _LEADING_TO.sub("", s).strip(" ,;.")
    return s


# ---------------------------------------------------------------------------
# PHASE 3 — TAG
# ---------------------------------------------------------------------------

#: Verbs that put something on the CALENDAR, and verbs that put something on
#: the TO-DO LIST. Read off TRAIN failures, so this is a train-derived lexicon
#: and carries the usual overfitting risk — the sealed half is what confirms
#: it. It is deliberately SMALL: it only has to beat the engine tagger on the
#: cases that tagger already gets wrong.
_CALENDAR_VERBS = frozenset("""
    book schedule plan arrange reschedule rebook cancel move postpone
    delete clear block
    meet talk catch touch head squeeze pencil attend
""".split())

_TASK_VERBS = frozenset("""
    buy call email text pick collect grab wash clean fold pack sort
    file pay submit prepare print water walk take change top order renew
    return drop send finish write update fix charge vacuum feed refill
    restock organize review back draft finalize prep
    confirm mail sign tick
    rinse stack scrub wipe mop sweep iron hoover proofread chase do
""".split())
# The last line above: household chores the train board still read as events
# ("rinse and stack the dishes", "proofread the report, chase the signatures")
# — verbs that only ever describe an errand, so the one-way veto is safe on
# them. Measured 2026-09-20.
# The last line of each list above was mined from REAL speech (HWU-64, the
# author's command memory, FastRule's train half) and family-checked against
# FastRule's own gold — `segmentation/experiments/missing_verbs.py`, and the
# INTENT_MAP block in rule_parser.py carries the per-verb counts.

#: Verb particles — a closed grammatical class (what spaCy tags `prt`), not
#: vocabulary. The pronouns are the ones an object can take between verb and
#: particle ("sign ME up", "pick IT up").
_PARTICLES = frozenset("up off out in on down away back over".split())
_OBJECT_PRONOUNS = frozenset("me it that this them us him her".split())
#: What can NEVER be a verb's object: auxiliaries, copulas, prepositions,
#: conjunctions, quantifiers. Closed class. Anything else after a candidate
#: head verb is read as its object ("buy MILK", "charge THE scooter").
_NOT_AN_OBJECT = frozenset(
    "is are was were am be been being and or but then also plus nor to for "
    "from on at in by with of as until till through per all every no not "
    "as well".split())

#: Phrasal verbs whose kind differs from their bare verb's, or whose bare
#: verb has no entry at all. Found the honest way — "sign me up for the
#: pottery class" (split_traps sp-0003, gold `event`) regressed to `task`
#: the moment "sign" (task, 22/22 on FastRule's gold for "sign the
#: permission slip") joined `_TASK_VERBS`. Entries need the same evidence
#: as the flat lists: sign up / set up / catch up / meet up are enrolments
#: and encounters, the rest are to-do completions and errands.
_PHRASAL_KINDS = {
    "sign up": "event", "set up": "event", "catch up": "event", "meet up": "event",
    "wrap up": "task", "tick off": "task", "check off": "task", "drop off": "task",
    "put out": "task", "put away": "task",       # "put out the bins" (2026-09-20)
}


#: NOT A CALENDAR ASK AT ALL — `other`, the fourth value `ITEM_KINDS` has always
#: carried and that nothing ever produced (2026-09-09).
#:
#: WHY A CLOSED LIST rather than a shape test: a bare noun phrase is the NORMAL way
#: to name an event — "physio", "standup", "dentist appointment", "coffee with sam"
#: — so "this does not look like a command" cannot be the test. `_kind_of` returns
#: `event` for every one of those AND for "i love you", because syntactically they
#: are the same thing. The difference is semantic, so the signal has to be
#: vocabulary.
#:
#: EVERY PATTERN IS TESTED AGAINST A SEGMENTED ACTION, not a raw sentence. A rule
#: for "call mum/dad" as a phone action was in this list for about ten minutes and
#: it was wrong twice over: calling your mother is a perfectly ordinary thing to put
#: on a list, and it only showed up because the pipeline passes the ACTION ("call
#: mum") while the first check passed whole sentences ("call mum at 5"), which never
#: matched the anchored pattern. Verify with `fastseg(text)`, never with `tag(text)`.
#:
#: Measured harm before this existed: of eleven unusable inputs, SIX reached the
#: calendar — "i love you", "play some music", "turn on the lights", "the weather is
#: nice today" and "hmm let me think" each created an event, and "wait no forget it"
#: MODIFIED one.
_NOT_CALENDAR = (
    # greetings, thanks, acknowledgements — a whole utterance, not a fragment
    r"^(?:hi|hey|hello|thanks|thank\s+you|cheers|ta|bye|goodbye|good\s+(?:morning|"
    r"night)|ok(?:ay)?(?:\s+(?:cool|great|thanks|then))?|cool|great|nice|sure|yes|"
    r"no|yeah|yep|nope|never\s+mind|nevermind|forget\s+it|scrap\s+that)"
    # ...and the intensifier people actually say after it. Anchored `$` alone,
    # bare "thanks" was tagged `other` and "thanks so much" was read as an
    # EVENT — so the politeness at the end of a real command was the thing that
    # made it look like a command. Kept to a closed list: anything longer than
    # these is a sentence, and a sentence may well be an ask.
    r"(?:\s+(?:so\s+much|very\s+much|a\s+lot|again|mate|man|buddy|"
    r"anyway|though))?$",
    # abandoning the thought
    r"\b(?:never\s+mind|forget\s+it|forget\s+that|scrap\s+that|ignore\s+that|"
    r"my\s+mistake|wrong\s+one)\b",
    # thinking aloud
    r"^(?:hmm|erm|um|uh)?\s*(?:let\s+me\s+think|hold\s+on|one\s+(?:sec|second|"
    r"moment)|wait)\b",
    # another domain entirely — a calendar cannot act on these
    r"^(?:play|pause|stop|skip|resume)\s+(?:some\s+|the\s+)?(?:music|song|playlist|"
    r"radio|podcast|tv)\b",
    r"\bturn\s+(?:on|off|up|down)\s+the\s+\w+",
    r"^(?:what'?s|how'?s|tell\s+me)\s+the\s+(?:weather|temperature|news|time)\b",
    # conversation about the world rather than the diary
    r"^the\s+weather\s+is\b", r"^i\s+(?:love|hate|miss)\s+you\b",
)
_NOT_CALENDAR_RE = [re.compile(p, re.I) for p in _NOT_CALENDAR]


def _is_not_calendar(action: str, time_str: str = "") -> bool:
    """True when the words are not a calendar ask at all.

    A STATED TIME OVERRULES THE VETO. "turn on the lights" is a smart-home
    command; "turn on the oven at 6" is a reminder, and the only thing telling
    them apart is that the speaker scheduled one. Erring this way is deliberate:
    a false `other` LOSES a command the speaker gave, while a missed one puts a
    row on the calendar they can delete. The floor's bare "today" does not count,
    since the engine wrote that rather than the speaker.
    """
    a = (action or "").strip().lower()
    if not a:
        return False
    said_a_time = (time_str or "").strip().lower() not in ("", "today")
    if said_a_time:
        return False
    return any(rx.search(a) for rx in _NOT_CALENDAR_RE)


#: Scaffolding in front of the verb — politeness, modals, and the "i need to" /
#: "i'd like to" frame. Skipped before the head verb is read, never treated as one.
_PREAMBLE = frozenset("""
    i i'd id we you your my me us please can could would should will shall
    need needs want wants like to gonna gotta got going have has had let lets let's
    so um uh er hmm ok okay and then also first next now just really
""".split())
# "gotta"/"got" (2026-09-20): "like i gotta restock the pantry" kept "gotta" as
# its head, so the errand verb behind it was never read — five train rows.

#: A time the speaker STATED, as opposed to the floor's bare "today". Needed
#: the SPOKEN clock forms too ("ten thirty") — Whisper writes what was said,
#: and `find_time_refs`'s own "clock" kind already recognises them
#: (`_HOURWORD` + `_MINWORD`), so this checked less than what actually lands
#: in `time_str`.
#: Q15's frame: the speaker ASKING for a reminder, which outranks the "a clock
#: means scheduled" inference. "remind me TO feed the cat at 14:00" is a task;
#: "remind me ABOUT the dentist at 9am" is not this shape and stays an event.
_REMINDER_TASK_FRAME = re.compile(r"^\s*(?:please\s+)?remind me\s+to\b", re.I)

_STATED_CLOCK = re.compile(
    rf"\d{{1,2}}:\d{{2}}|\d{{1,2}}\s*(?:am|pm)|\bat\s+\d{{1,2}}\b|\bnoon\b|\bmidnight\b"
    rf"|\d{{3,4}}\s*(?:am|pm)|\b(?:at|for)\s+\d{{3,4}}\b"                 # compact: 910am, for 830
    rf"|\bo'?clock\b|\b(?:half|quarter)\s+(?:past|to)\b"
    rf"|\b(?:{_HOURWORD})\s+(?:{_MINWORD})\b"
    # A spoken hour after "at" ("at six") and a RANGE ("from noon to 1",
    # "between 5 and 6:30") state a time too — Q26 names a range outright,
    # and this pattern only ever reads the assigned TIME string, so "from
    # the store to the office" cannot reach it.
    rf"|\bat\s+(?:{_HOURWORD})\b"
    r"|\bfrom\s+\S+\s+to\s+\S+|\bbetween\s+\S+\s+and\s+\S+", re.I)

#: A hedge that says nothing was actually committed to a slot — "schedule a
#: haircut AT SOME POINT" names an intention, not an appointment, whatever
#: the verb. Closed list, same shape as `_is_not_calendar`'s own vocabulary
#: veto: measured on the corpus (6/6 gold rows carrying this phrase are
#: `task`), not a general "any vague time" heuristic.
_VAGUE_TIME_HEDGE = re.compile(
    r"\bat\s+some\s+(?:point|stage)\b|\bsometime\b|\bsome\s+time\b|\bwhenever\b",
    re.I)

#: "BLOCK OFF/OUT (time) TO do X" is reserving a slot for yourself, not
#: scheduling an event with anyone or anything else — even though the head
#: verb ("block") sits in `_CALENDAR_VERBS`. The "to VERB" is the tell:
#: "block off the whole day FOR client call" (a named event, no "to") stays
#: `event` (measured 7/7); only the "to VERB" infinitive shape is `task`
#: (measured 12/12 across both "block off time to…" and "block out … to…").
#: "CARVE OUT"/"SET ASIDE" are the same self-time-reservation idiom with a
#: different verb, not in the corpus but the same shape.
_TIME_BLOCKING = re.compile(
    r"^(?:block\s+(?:off|out)|carve\s+out|set\s+aside)\b.*\bto\s+\w", re.I)

#: "GIVE ME A NUDGE (to do X)" is the same reminder framing as "remind me",
#: just not spelled with a verb `_lexicon_kind` reads — head-of-action is
#: "give me", neither in `_CALENDAR_VERBS` nor `_TASK_VERBS`, so the lexicon
#: abstains and whatever the wrapped verb suggests ("book a flight" reads
#: event-ish) stands unchallenged. Measured 6/6 `task` on the corpus.
#: Synonyms of "give me a nudge" this dataset never happened to spell —
#: "poke"/"buzz"/"ping" me are the same REMINDER-FRAMING idiom with a
#: different verb, and the closed regex above only matched the one dataset
#: verb. Corpus-unverifiable (none of these appear in it) but not a guess:
#: same idiom, same reasoning `_NUDGE_IDIOM`'s own docstring gives.
_NUDGE_IDIOM = re.compile(r"^give\s+me\s+a\s+nudge\b|^(?:poke|buzz|ping)\s+me\b", re.I)

#: A "before" that SURVIVES into the action (rather than being lifted into
#: time_str as a deadline or a lead-time, both already handled upstream) is
#: always transitive here — "before HAIRCUT", "before SCHOOL PLAY" — because
#: the only other things "before" can govern (a date word, or nothing at
#: all) are already gone by this point. "about" reaches the same shape one
#: hop earlier — "remind me to email Robin ABOUT onboarding session" — no
#: duration/"before" at all, just a reminder ANCHORED to a named event.
#: Excludes a bare pronoun ("...a week before THAT") — the one idiom that
#: survives with no named object of its own — and "before/about I …", which
#: is the "can you check what i have before i commit to anything" REVIEW
#: shape, not a reminder.
#: "concerning"/"regarding"/"ahead of" are the same anchoring preposition as
#: "about" — synonyms this dataset's templates never happened to render
#: together with a NAMED object ("ahead of" already matters to
#: `_LEAD_INTRANSITIVE` upstream, but only for the time-extraction question,
#: never for TAG until "ping me ahead of conference call" regressed here).
_ANCHORED_TO_EVENT = re.compile(
    r"\b(?:before|about|concerning|regarding|ahead\s+of)\s+(?!that\b|it\b|i\b)\w",
    re.I)


#: "call/email/text/message/notify/write/send PERSON" is an OUTREACH task
#: regardless of who the person is — the whole point of the verb is a
#: one-way errand, not a scheduled encounter. `_has_person_argument` exists
#: to protect ENCOUNTER verbs ("grab coffee with", "see", "catch up with")
#: that happen to sit in `_TASK_VERBS` for their generic-object sense ("grab
#: milk") — it must not ALSO protect these, or "call Dana and Avery" (task,
#: a phone-call errand) gets talked back up to `event` for no better reason
#: than the person's name being capitalised. Regressed 13 rows before this
#: exclusion was added; caught by the row-ID diff, not anticipated.
_OUTREACH_VERBS = frozenset({"call", "email", "text", "message", "notify",
                             "write", "send", "ping"})


def _head_is_outreach_verb(action: str) -> bool:
    """Same head-of-action read `_lexicon_kind` uses (preamble skipped
    first), checked against the outreach-verb subset specifically."""
    words = [w.strip(".!?,") for w in action.lower().split()]
    while words and words[0] in _PREAMBLE:
        words.pop(0)
    return bool(words and words[0] in _OUTREACH_VERBS)


def _has_person_argument(action: str) -> bool:
    """Does this action carry a capitalised proper noun as SOMEONE'S
    argument — a verb's direct object, or the object of a preposition —
    AND the head verb isn't one of the outreach verbs above?

    "grab coffee with DEVESH" — STRUCTURAL, not a verb list: it generalises
    "meet"/"sync up with" to any verb a speaker might use for a
    person-ENCOUNTER ("catch up with", "see", "drop by", "grab lunch with",
    ...) without enumerating them, the same distinction `experiments/
    tag_structural.py`'s `_has_propn_argument` measured (and which that
    experiment's classifier still lost overall — this is the ONE signal
    from it worth porting into the rules directly, since it is structural
    rather than a fitted weight, and it fixes a real veto-mode failure:
    "grab" sits in `_TASK_VERBS`, so `_lexicon_kind` was talking a genuine
    encounter back down to `task` with nothing to stop it).

    Scanned over the WHOLE action rather than just the root's direct
    children — spaCy's lowercase-STT parse is unreliable about exactly
    which token "with X" attaches to ("grab coffee with Devesh" hangs it off
    "coffee", not "grab", once "Devesh" is capitalised and the parse
    reshuffles) — the action is already one segmented item by the time TAG
    sees it, so there is no second clause here to accidentally match.
    """
    if _head_is_outreach_verb(action):
        return False
    from assistant.intent.coordination import parsed
    doc = parsed(action)
    if doc is None:
        return False
    return any(t.pos_ == "PROPN" and t.dep_ in ("dobj", "obj", "dative", "pobj")
               for t in doc)


#: "i have to MEET Quinn", "i need to SYNC UP with Jordan" — an encounter
#: with a PERSON is always an event (6/6 each on the corpus), unlike the
#: generic task verbs this shape otherwise resembles ("i have to call/email/
#: text Quinn" stay task-neutral, not promoted — meeting/syncing up IS the
#: scheduled thing, not an errand about a person).
_MEETING_HEAD = re.compile(r"\bmeet\b|\bsync(?:ing)?\s+up\b", re.I)

#: "get X ON THE BOOKS" — the idiom for getting something scheduled
#: (measured 6/6 `event`), not literally putting a book somewhere. The head
#: verb "get" carries no signal of its own (not in either lexicon), so
#: without this the wrapped noun phrase decides nothing and the engine
#: tagger's own guess stands unchallenged.
_ON_THE_BOOKS = re.compile(r"\bon\s+the\s+books\b", re.I)

#: "GIVE ME THE RUNDOWN" asks what is scheduled — a review, not an event —
#: measured 6/6 on the corpus. Neither "give" nor "rundown" is in either
#: lexicon, so nothing else here would ever route it away from `event`.
_RUNDOWN_IDIOM = re.compile(r"\bgive\s+me\s+the\s+rundown\b", re.I)

#: "CHANGE/FLIP THE DUE DATE on X" — editing a task's own due date, always
#: `task` (12/12) whatever the wrapped task-title X happens to look like
#: ("…on confirm the reservation" reads event-ish to the engine tagger on
#: its own, per `_lexicon_kind`'s docstring: a NOUN inside the action must
#: not decide, only the head — this is that same guard, extended to a
#: closed two-word head phrase instead of one word).
#: "shift"/"push back"/"bump"/"move" are the same due-date-editing verb as
#: "change"/"flip", not seen in the corpus but the same idiom.
_DUE_DATE_EDIT = re.compile(
    r"^(?:change|flip|shift|bump|move|push\s+back)\s+the\s+due\s+date\b", re.I)


def _lexicon_kind(action: str) -> "str | None":
    """The verb's verdict, read at the HEAD of the action only.

    Scanning every word made a NOUN decide: "add the budget review" and "add a
    call with Riley" were tagged `task` because `review` and `call` are on the
    task list, though the verb is `add` in both. That was the single largest tag
    error — 56 of 179 — and reading the head instead fixes it without touching
    the lexicon's contents.

    TWO words, not one, because the head can carry a particle: "block off",
    "put out", "top up".

    AND THE PREAMBLE IS SKIPPED FIRST. "um so i need to book birthday dinner" puts
    `i need` in the first two slots and the real verb three words later, so a
    literal head-of-string reading lost the `book` that scanning everything used to
    find — six `texture` rows regressed on exactly that before this was added. The
    head verb is the first word that is not scaffolding.
    """
    words = [w.strip(".!?,") for w in action.lower().split()]
    while words and words[0] in _PREAMBLE:
        words.pop(0)
    # A PHRASAL verb is a different word from its bare verb: "sign the
    # permission slip" is a task, "sign me UP for the pottery class" is an
    # event (enrolling). The particle may sit past an object pronoun ("sign
    # ME up", "pick IT up"), so it is looked for within two tokens, skipping
    # pronouns. Particles are a closed grammatical set, not vocabulary;
    # only the phrasal FORMS are lexicon entries, and only those with
    # evidence — `_PHRASAL_KINDS`.
    if words:
        for nxt in words[1:3]:
            if nxt in _OBJECT_PRONOUNS:
                continue
            if nxt in _PARTICLES:
                phrasal = _PHRASAL_KINDS.get(f"{words[0]} {nxt}")
                if phrasal:
                    return phrasal
            break
    # THE SECOND WORD IS READ ONLY WHEN IT HEADS A VERB PHRASE OF ITS OWN —
    # something that can be its object follows it: "put CHARGE the scooter",
    # "add CALL the plumber", "add BUY milk", "put PICK up the dry cleaning"
    # (a placement verb the lexicons leave out, wrapping the errand's verb;
    # 24 train rows). A bare NOUN phrase is followed by nothing, or by a
    # function word — "oil change", "client call", "conference call IS an
    # all-day thing", "oil change , ALL day" — and reading its second word
    # vetoed those to `task` on "change"/"call", the error the head reading
    # exists to end. Grammar, not a list: what cannot be an object is a
    # closed class, like the particles. (Requiring a determiner instead lost
    # "add buy milk", whose object is a bare noun — a live test caught it.)
    depth = 1
    if len(words) > 2:
        k = 3 if words[2] in _PARTICLES and len(words) > 3 else 2
        if words[k] not in _NOT_AN_OBJECT:
            depth = 2
    for word in words[:depth]:
        if word in _CALENDAR_VERBS:
            return "event"
        if word in _TASK_VERBS:
            return "task"
    return None


def tag(action: str, time_str: str) -> str:
    """event | task | review.

    The engine's own reader decides first, so the tuning module and the engine
    cannot disagree about what a review looks like. Then ONE correction is
    applied, and only in one direction.

    MEASURED, not assumed (1,383 matched TRAIN items). The engine tagger's
    `task` verdicts are already good — 89.3% precision — but its `event`
    verdicts are where the errors live: 159 tasks were being called events, and
    that number had not moved all session. So the lexicon is consulted ONLY to
    talk it out of `event`, never into it:

        engine tagger alone            84.7%   task recall 70.7%
        lexicon overrides everywhere   82.4%   task recall 78.5%   (worse)
        lexicon only over `event`      87.5%   task recall 87.1%   <- this

    Overriding in both directions loses more events than it gains tasks, which
    is why the asymmetry is the whole point rather than an implementation
    detail. A parser was tried here first and was much worse (65.0%) — see
    `pos_sizing.py`; calendar commands are VERB-rooted imperatives, so a
    root-POS signal is anti-correlated with the answer.
    """
    from assistant.engine.segmentation.fastseg.kind import kind_of

    kind = kind_of(action)
    if kind not in ("event", "task", "review"):
        kind = "event"
    # Q25 (Gil, 2026-09-18): "anything that has an AM or PM time, like 1
    # o'clock, 2.30, that is for sure an event... if we're just given a day,
    # maybe it's an event, maybe it's a task, it depends on the context."
    #
    # The clock rule already existed BELOW, but only inside the `event` branch,
    # where it stops the task lexicon vetoing an event. When `_kind_of` answers
    # `task` up front the branch is never entered, so the clock never gets a
    # say: "i need to go to the dentist on the 24th at 3 o'clock" stayed a
    # task. This is the missing direction, not a new rule.
    #
    # NO REMINDER-FRAME EXCEPTION (Q26, Gil, 2026-09-18). A narrowing shipped
    # earlier the same day kept "remind me TO <verb>" a task on Q15's
    # authority; Gil then ruled the other way and Q15's parenthetical with it:
    # "an event is something that you put on the calendar, so reminding me to
    # do something at a specific time counts as an event." The 32 corpus rows
    # that said otherwise were relabelled in the same change, so no gold is
    # left contradicting this.
    # `_TIME_BLOCKING` ("block off time TO print the boarding pass") is NOT an
    # exception here: with a stated clock or range it is an appointment the
    # speaker gave a slot, and Q26 puts it on the calendar — FastRule's own
    # gold relabelled `c_range_ct_1` that way the day it was ruled. Without a
    # clock the idiom still reads as a task, below.
    stated = bool(_STATED_CLOCK.search(time_str or ""))
    if kind == "task" and stated \
            and not _VAGUE_TIME_HEDGE.search(action) \
            and not _DUE_DATE_EDIT.match(action) \
            and not _is_not_calendar(action, time_str):
        return "event"
    if kind == "event":
        # A ONE-WAY VETO, over `event` only — the third time that asymmetry is the
        # thing that works here. The task lexicon below wins the same way (87.5%
        # against 82.4% overriding both directions), and the logistic head failed
        # BECAUSE it answered in both directions. `other` can therefore never
        # swallow a task or a review, and `_kind_of` calls everything it cannot
        # place an event, so `event` is exactly where an unusable ask lands.
        if _is_not_calendar(action, time_str):
            return "other"
        if _RUNDOWN_IDIOM.search(action):
            return "review"
        if _VAGUE_TIME_HEDGE.search(action) or _DUE_DATE_EDIT.match(action) \
                or (_TIME_BLOCKING.search(action) and not stated):
            return "task"
        if _NUDGE_IDIOM.match(action) and not _ANCHORED_TO_EVENT.search(action):
            # "ping me AHEAD OF conference call" is the anchored idiom (an
            # actual named event), not the bare "give me a nudge TO submit
            # the report" idiom "ping" was added to `_NUDGE_IDIOM` to cover —
            # the anchor must win, or widening the verb list regressed a row
            # this exact idiom already handled correctly (§0b, fix #10).
            return "task"
        verdict = _lexicon_kind(action)
        anchored = _ANCHORED_TO_EVENT.search(action) and not _head_is_outreach_verb(action)
        if verdict == "task" and (
                _STATED_CLOCK.search(time_str or "")
                or anchored
                or _has_person_argument(action)):
            # A STATED CLOCK MEANS SCHEDULED. "walk the dog" is a to-do and "walk
            # the dog at 9" is an appointment — same verb, and the only thing that
            # changed is that the speaker named a time. The floor's bare "today"
            # does not count, because the engine wrote that rather than the
            # speaker. Second largest error class, 34 of 179.
            #
            # The other two guards catch what a stated clock cannot: "grab"
            # sits in `_TASK_VERBS` (correctly, for "grab milk"), so "grab
            # coffee with DEVESH" was being vetoed to `task` with nothing to
            # stop it — a real person-argument or an anchor clause is the
            # same "this is scheduled" evidence a clock is, just spelled
            # differently. Found stress-testing §0b's fixes against phrasing
            # the dataset never generated (Gil, 2026-09-16: "continuing more
            # as is is definitely overfitting").
            return kind
        return verdict or kind
    if kind == "task":
        # The MIRROR promotion, still one-way and still narrow — not the
        # blanket bidirectional override that measured worse above. Both
        # triggers are STRUCTURAL, not a verb-list flip, so neither repeats
        # the refuted experiment: a real stated time (day or clock — the
        # bare "today" floor does not count, same distinction `_STATED_CLOCK`
        # already draws for the mirror case) plus either a surviving
        # "before/about NAMED EVENT" clause the engine tagger never reaches
        # (it reads the head verb+object, "remind me to ORGANIZE THE
        # GARAGE…", before the anchor clause that actually places this on a
        # calendar), or the head verb being "meet" — meeting a person is the
        # one verb in this shape where the whole point IS the encounter.
        real_time = (time_str or "").strip().lower() not in ("", "today")
        if real_time and (_ANCHORED_TO_EVENT.search(action)
                          or _MEETING_HEAD.search(action)
                          or _ON_THE_BOOKS.search(action)):
            return "event"
    return kind


# ---------------------------------------------------------------------------
# the component
# ---------------------------------------------------------------------------

_ENUM_SPLIT = re.compile(r"\s*,\s*|\s+and\s+", re.I)


def _expand_enumerations(pairs: "list[tuple[str, str]]") -> "list[tuple[str, str]]":
    """One activity at SEVERAL times becomes several items (§8.1).

    Gil, 2026-09-08: *"the segmentation is supposed to split 'walk the dog at 9
    and 2:30' into two events of walk the dog."* A bounded enumeration is several
    items; an unbounded `every X` is ONE item with a recurrence, and recurrence is
    a FEATURE that `decompose_validate` fills rather than more segmentation.

    Done here, after `assign_times`, rather than in `cut`: the cutter returns
    substrings and `_locate` maps them back to the original text, so a synthesised
    piece has nowhere to be located. On (action, time) pairs there is no such
    constraint, and `cut` stays the fixed-point loop it is.

    The action is COPIED, not divided — that is the whole point, and it is why the
    invariant permits a token in more than one item.
    """
    out: "list[tuple[str, str]]" = []
    for action, time_str in pairs:
        enum = next((r for r in find_time_refs(time_str)
                     if r.kind in ("enum_clock", "enum_day")), None)
        if enum is None:
            out.append((action, time_str))
            continue
        parts = [p.strip() for p in _ENUM_SPLIT.split(enum.text) if p.strip()]
        if len(parts) < 2:
            out.append((action, time_str))
            continue
        # Whatever surrounds the enumeration is SHARED by every instance: the
        # trailing "tomorrow" in "at 11 and 4 tomorrow" dates both of them.
        before = time_str[:enum.start].strip()
        after = time_str[enum.end:].strip()
        # THE PREPOSITION IS SHARED TOO. "at 9 and 2:30" says "at" once and means
        # it twice, so a part that lost it gets it back — otherwise the second item
        # reads "today 2:30" while the first reads "today at 9", and SPEC captures a
        # time AS SPOKEN rather than as punctuated.
        lead = re.match(r"(at|on|from|by|for)\s+", parts[0], re.I)
        prep = lead.group(1) + " " if lead else ""
        for part in parts:
            if prep and not re.match(r"(at|on|from|by|for)\s+", part, re.I):
                part = prep + part
            out.append((action, " ".join(x for x in (before, part, after) if x)))
    return out


def fastseg(text: str) -> "list[dict]":
    """text -> [{"action", "time", "tag"}, ...]"""
    from assistant.intent.cleanup import strip_spoken_noise

    # A TRAILING CONFIRMATION is discourse about the command, not part of it
    # (Gil, 2026-09-09) -- "cross off take out the trash does that seem right".
    # Stripped HERE so it never enters the pipeline, and using the invariant's own
    # function so the guard and the segmenter cannot disagree about whether those
    # words are content. Safe before `cut` because the tail is at the end, so no
    # earlier offset moves.
    clean = _invariant.strip_discourse_tail(strip_spoken_noise(text or ""))
    pieces = cut(clean)
    pairs = _expand_enumerations(assign_times(clean, pieces))
    return [{"action": a, "time": t, "tag": tag(a, t),
             "source": _source_piece(a, pieces)} for a, t in pairs]


def _source_piece(action: str, pieces: "list[str]") -> str:
    """The VERBATIM substring this item was cut from (Gil, 2026-09-10).

    A fourth value beside (action, time, tag), and it exists for one reason:
    once an object is validated, its words have to come OUT of the command so
    the retry carries only what failed. `action` cannot do that job — the time
    has been split off it and `decompose_validate` may have repaired it, so it
    is no longer a substring of anything. The piece is.

    An ENUMERATION maps several items onto one piece ("walk the dog at 9 and
    2:30"), and they honestly share a source: they were cut from the same span.
    Removing it removes both, which is right — they succeed or fail together.

    Matched by containment first, then by word overlap, because `assign_times`
    strips the time out of the action and the two no longer match literally.
    """
    a = (action or "").strip().lower()
    if not a or not pieces:
        return action or ""
    for piece in pieces:
        if a in piece.lower():
            return piece
    import re as _re
    want = {w for w in _re.findall(r"[a-z0-9']+", a) if len(w) > 2}
    if not want:
        return action or ""
    best, score = action or "", 0
    for piece in pieces:
        have = {w for w in _re.findall(r"[a-z0-9']+", piece.lower()) if len(w) > 2}
        n = len(want & have)
        if n > score:
            best, score = piece, n
    return best


if __name__ == "__main__":                          # pragma: no cover
    for probe in ("tomorrow gym at 7 and meeting at 11",
                  "gym session at 7, tomorrow meeting at 10",
                  "submit the grades and prepare the slides by friday",
                  "every friday buy groceries",
                  "buy 5 apples",
                  "meeting with Sam and Alex at 8",
                  "book the gym and remind me to buy milk"):
        print(f"\n{probe!r}")
        for it in fastseg(probe):
            print(f"   action={it['action']!r:38s} time={it['time']!r:22s} {it['tag']}")
