"""Rule-based NLU fast-path for MACalendar.

Replaces LLM calls for simple, high-confidence voice commands.
Falls back to (or augments) the LLM for complex/ambiguous inputs.

Architecture
------------
Pipeline calls RuleBasedParser.analyze(transcript, current_view) which runs 7
phases and returns a RuleParseResult containing:
  - confidence (0.0–1.0)
  - intents (list of validated (action_name, BaseIntent) tuples)
  - missing_slots (required slots that could not be filled)
  - raw_slots (intermediate per-action slot dicts for LLM partial handoff)

If confidence >= RULE_THRESHOLD and missing_slots == []:
  → execute directly, no LLM call
Else:
  → pass raw_slots to LLM as pre-analysis context (parse_with_context)

Pipeline catches it and falls through to full LLM parse.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from assistant.intent.list_split import lead_verb, split_items

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports — availability probed at import time, models loaded lazily
# on first parse call so the ~80 MB spaCy + thinc footprint is deferred until
# the user actually uses voice input.
# ---------------------------------------------------------------------------

import importlib.util as _iutil
import threading as _thr

# --- spaCy ---
_RULE_PARSER_AVAILABLE: bool = _iutil.find_spec("spacy") is not None
_NLP = None          # set by _ensure_nlp()
_nlp_lock = _thr.Lock()
_nlp_loaded = False

def _ensure_nlp() -> None:
    """Load the spaCy model on first call (thread-safe)."""
    global _NLP, _nlp_loaded
    if _nlp_loaded:
        return
    with _nlp_lock:
        if _nlp_loaded:
            return
        try:
            import spacy as _spacy
            _NLP = _spacy.load("en_core_web_sm")
            _nlp_loaded = True
            logger.info("spaCy model loaded (lazy).")
        except (ImportError, OSError) as exc:
            global _RULE_PARSER_AVAILABLE
            _RULE_PARSER_AVAILABLE = False
            logger.warning("RuleBasedParser disabled: %s", exc)
            _nlp_loaded = True  # don't retry

# --- recognizers-text-date-time ---
_DT_AVAILABLE: bool = _iutil.find_spec("recognizers_date_time") is not None
_DT_MODEL = None     # set by _ensure_dt()
_dt_lock = _thr.Lock()
_dt_loaded = False

def _ensure_dt() -> None:
    """Load the date/time recognizer model on first call (thread-safe)."""
    global _DT_MODEL, _dt_loaded
    if _dt_loaded:
        return
    with _dt_lock:
        if _dt_loaded:
            return
        try:
            from recognizers_date_time import DateTimeRecognizer, Culture as _Culture
            _DT_MODEL = DateTimeRecognizer(_Culture.English).get_datetime_model()
            _dt_loaded = True
            logger.info("DateTime recognizer loaded (lazy).")
        except Exception as exc:
            global _DT_AVAILABLE
            _DT_AVAILABLE = False
            logger.warning("DateTime recognizer disabled: %s", exc)
            _dt_loaded = True  # don't retry

if TYPE_CHECKING:
    from assistant.actions.base import BaseIntent
    from assistant.actions import ActionRegistry

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

RULE_THRESHOLD = 0.80   # tuned 2026-09-07: whole-command sweep, +2pp coverage at flat 87% precision (sub-item bar is 0.60)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RuleParseResult:
    """Full result from RuleBasedParser.analyze()."""

    confidence: float
    intents: list[tuple[str, "BaseIntent"]]
    missing_slots: list[str]
    raw_slots: dict  # {action_name: {slot_name: value}}
    transcript: str
    routed_to_llm: bool = False
    dropped_spans: int = 0   # parts of the command the rule parser could not route
    #: Phrases whose date was CHOSEN out of a range ("next week") rather than
    #: named. Non-empty ⇒ the caller asks before committing (Gil, 2026-09-17):
    #: the day is a reading of the span, not the speaker's own word for it.
    range_dates: "list[str] | None" = None


class RuleParserSkip(Exception):
    """Raised when the rule parser cannot handle the input (complexity gate or no match).
    Pipeline should catch this and fall through to the standard LLM parse.
    """


# ---------------------------------------------------------------------------
# STT shorthand expansion table
# ---------------------------------------------------------------------------

_STT_EXPANSIONS: list[tuple[str, str]] = [
    (r"\btmrw\b", "tomorrow"),
    (r"\btomoro\b", "tomorrow"),
    (r"\bnxt\b", "next"),
    (r"\bmtg\b", "meeting"),
    (r"\bappt\b", "appointment"),
    (r"\bw/\b", "with"),
    (r"\bthru\b", "through"),
    (r"\bcal\b", "calendar"),
    (r"\bsched\b", "schedule"),
    (r"\bappt\b", "appointment"),
    (r"\bwk\b", "week"),
    (r"\bmon\b(?=\s)", "monday"),
    (r"\btue\b", "tuesday"),
    (r"\bwed\b(?=\s)", "wednesday"),
    (r"\bthu\b", "thursday"),
    (r"\bfri\b(?=\s)", "friday"),
    (r"\bsat\b(?=\s)", "saturday"),
    (r"\bsun\b(?=\s)", "sunday"),
    # "get rid of X" is removal-speak the verb map can't key on (multi-word):
    # normalize so ("remove", …) routing applies and a generic target like
    # "this list" hits the fast gate's veto (sandbox batch F2).
    (r"\bget rid of\b", "remove"),
    # "take / clear / knock X OFF my calendar|list" is a removal (2026-09-25):
    # "take sales call off my calendar" built an EMPTY to-do, and "clear
    # doctor's appointment off my calendar" deleted 'doctor'. Rewritten to the
    # form the router keys on, keeping the destination word it reads for the
    # domain. "tick / cross X off" is a COMPLETION and is left alone.
    (r"\b(?:take|clear|knock)\s+(.+?)\s+off\s+((?:my|the)\s+(?:calendar|calender|schedule|agenda|(?:to-?\s?do\s+)?list|to-?\s?dos?|tasks?))\b",
     r"remove \1 from \2"),
    # --- F9 (simple-first abstain mining): 209 of 540 simple abstains were
    # outright skips caused by leading filler/courtesy hiding the command
    # from ^-anchored routing. Strip them FIRST (list order applies).

    (r"^(?:could|can)\s+you\s+tell\s+me\s+", ""),
    # F18a: the general form — "can you remove X" was extracting the TARGET
    # as "you" (then correctly vetoed as generic). The interrogative gate
    # reads the RAW text, so stripping here cannot smuggle a question past it.
    (r"^(?:can|could|would|will)\s+you\s+(?:please\s+)?", ""),          # "…what's on my calendar" = query
    (r"^(?:could|can|would)\s+you\s+(?=remind\b)", ""),     # "could you remind me to X"
    # "let's do/have/get X" is create-speak the verb map can't key on
    (r"^let'?s\s+(?:do|have|get)\s+", "book "),
    # STT misspellings the expansion table lacked (measured, not guessed)
    (r"\btommorow\b", "tomorrow"),
    (r"\breshedule\b|\breschdule\b", "reschedule"),        # F19 (12 rows)
    (r"\bgotta\b|\bgot to\b|\bhave got to\b", "need to"),  # F19 (15 rows)
    (r"^i\s+should\s+(?=see|talk|speak|meet|catch up|call\b)", "i need to "),
    (r"^note to self[,:]?\s+", "add "),                       # F19 (9 rows)
    # "put a marker on <date> for <thing>" is the day-marking family
    (r"\bput\s+a\s+marker\s+on\s+(.+?)\s+for\s+(.+)$", r"add \2 on \1"),
    (r"\bapointment\b", "appointment"),
    (r"\bremindar\b", "reminder"),
    # "mark <date> as <occasion>" marks a DAY, it does not tick a task off:
    # "mark 13 october of this year as my birthday" fast-committed a wrong
    # complete_todo (F4b). Rewritten to the create shape the parser already
    # handles ("add my birthday on 13 october …"); requires a date-looking
    # object so "mark groceries as done" keeps completing, and a done-ish
    # label is left alone outright.
    (r"\bmark\s+((?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?"
     r"(?:january|february|march|april|may|june|july|august|september|october|"
     r"november|december)(?:\s+of\s+this\s+year|\s+this\s+year)?"
     r"|(?:january|february|march|april|may|june|july|august|september|october|"
     r"november|december)\s+(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?"
     r"|today|tomorrow|next\s+\w+day)\s+as\s+"
     r"(?!done\b|complete\b|completed\b|finished\b)(.+)$",
     r"add \2 on \1"),
    # (b, F6) date-marking beyond explicit month-days: weekdays, relatives,
    #     named days ("christmas day"), "note" as the verb, an optional
    #     "on my calendar" infix. Same rewrite target as F4b.
    (r"\b(?:mark|note|put)\s+((?:next|this|coming)\s+\w+|today|tomorrow|"
     r"the\s+day\s+after\s+tomorrow|tonight|\w+(?:'s)?\s+day|\w+\s+eve|"
     r"(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?)\s+down\s+as\s+"
     r"(?!done\b|complete\b|completed\b|finished\b)(.+)$",
     r"add \2 on \1"),
    (r"\b(?:mark|note)\s+((?:next|this|coming)\s+\w+|today|tomorrow|"
     r"the\s+day\s+after\s+tomorrow|\w+(?:'s)?\s+day|\w+\s+eve)\s+"
     r"(?:on\s+my\s+calendar\s+)?as\s+"
     r"(?!done\b|complete\b|completed\b|finished\b)(.+)$",
     r"add \2 on \1"),
    # --- F6 (FastRule-6000 train mining, 2026-09-07): three systematic
    # false-accept families, each rewritten to a form the router already
    # handles correctly (the F2/F4b pattern: normalize, don't special-case).
    # (b) completion speak: "check off X" hit query_schedule, "i'm done with
    #     X" created a todo. "mark X as done" is the completion phrasing the
    #     router provably handles — rewrite everything completion-shaped to it.
    (r"^(?:yeah,?\s+|ok,?\s+|okay,?\s+)?(?:i(?:'m| am)\s+done\s+with|"
     r"i\s+already\s+did|i\s+finished)\s+(.+)$", r"mark \1 as done"),
    (r"^check\s+off\s+(.+)$", r"mark \1 as done"),
    (r"^complete\s+(?!the\s*$)(.+)$", r"mark \1 as done"),
]

# --- F15 (stage isolation, 2026-09-07): spoken time vocabulary. 807 of the
# atomic deferrals were a missing date/start_time, and these phrasings are
# why. re.sub takes a callable, so "quarter to nine" is arithmetic, not 12
# hand-written rows. Vague dayparts get ONE documented default each — the
# deep track would resolve them the same way, and a defer helps nobody.
_WORD_HOUR = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
              "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,
              "1":1,"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,
              "10":10,"11":11,"12":12}
_HOUR_RE = "|".join(_WORD_HOUR)


def _quarter_to(m) -> str:
    h = _WORD_HOUR[m.group(1).lower()] - 1
    return f"{12 if h == 0 else h}:45"


def _quarter_past(m) -> str:
    return f"{_WORD_HOUR[m.group(1).lower()]}:15"


def _half_past(m) -> str:
    return f"{_WORD_HOUR[m.group(1).lower()]}:30"


_SPOKEN_TIMES = [
    (rf"\bquarter\s+to\s+({_HOUR_RE})\b", _quarter_to),
    (rf"\bquarter\s+past\s+({_HOUR_RE})\b", _quarter_past),
    (rf"\bhalf\s+past\s+({_HOUR_RE})\b", _half_past),
    # vague dayparts → one documented default each
    (r"\bfirst thing(?:\s+in the morning)?\b", "at 8am"),
    (r"\b(?:early|first thing in the)\s+morning\b", "at 8am"),
    (r"\blate\s+morning\b", "at 11am"),
    (r"\bmidday\b|\bmid-?day\b", "at 12pm"),
    (r"\bearly\s+afternoon\b", "at 1pm"),
    (r"\blate\s+afternoon\b", "at 4pm"),
    (r"\bearly\s+evening\b", "at 6pm"),
    (r"\blate\s+evening\b", "at 9pm"),
    (r"\blate\s+night\b", "at 10pm"),
    # "all day" is a real answer to "what time?", not a missing slot
    (r"\bfor\s+all\s+day\b|\ball\s+day\s+long\b|\ball[- ]day\b", "all day"),
]

# ---------------------------------------------------------------------------
# Intent routing tables
# ---------------------------------------------------------------------------

# (verb_lemma, domain_hint | None) → action_name
# More specific (non-None domain) entries take priority.
INTENT_MAP: dict[tuple[str, str | None], str] = {
    # --- Calendar create ---
    ("schedule", None): "create_event",
    ("book", None): "create_event",
    ("plan", None): "create_event",
    ("block", None): "create_event",
    ("add", "calendar"): "create_event",
    ("create", "calendar"): "create_event",
    ("make", "calendar"): "create_event",
    ("set", "calendar"): "create_event",
    ("organize", None): "create_event",
    ("invite", None): "create_event",     # F19: "invite Sam to the meeting"
    # --- Calendar update ---
    ("move", None): "update_event",
    ("reschedule", None): "update_event",
    ("postpone", None): "update_event",
    ("delay", None): "update_event",
    ("push", None): "update_event",
    ("advance", None): "update_event",
    ("shift", None): "update_event",
    ("change", "calendar"): "update_event",
    ("update", "calendar"): "update_event",
    ("edit", "calendar"): "update_event",
    # --- Calendar delete ---
    ("cancel", None): "delete_event",
    ("delete", "calendar"): "delete_event",
    ("remove", "calendar"): "delete_event",
    ("clear", "calendar"): "delete_event",
    ("drop", "calendar"): "delete_event",
    # --- Calendar update (additional verbs) ---
    ("rename", None): "update_event",
    # Extend / shorten duration
    ("extend", None): "update_event",
    ("lengthen", None): "update_event",
    ("shorten", None): "update_event",
    ("stretch", None): "update_event",
    ("prolong", None): "update_event",
    ("trim", "calendar"): "update_event",
    # --- Schedule query ---
    ("show", "calendar"): "query_schedule",
    ("list", "calendar"): "query_schedule",
    ("read", "calendar"): "query_schedule",
    ("check", "calendar"): "query_schedule",
    ("summarize", "calendar"): "query_schedule",
    # --- Todo create ---
    ("add", "todo"): "create_todo",
    ("create", "todo"): "create_todo",
    ("make", "todo"): "create_todo",
    ("remind", None): "create_todo",
    ("buy", None): "create_todo",
    ("call", None): "create_todo",
    ("email", None): "create_todo",
    ("text", None): "create_todo",
    ("pick", None): "create_todo",
    ("get", "todo"): "create_todo",
    ("write", "todo"): "create_todo",
    ("send", None): "create_todo",
    ("order", None): "create_todo",
    ("pay", None): "create_todo",
    ("fix", "todo"): "create_todo",
    ("clean", "todo"): "create_todo",
    ("wash", None): "create_todo",
    # F19: counted in the skip bucket — the router had no entry at all
    ("grab", None): "create_todo",
    ("sort", None): "create_todo",
    ("review", None): "create_todo",
    ("water", None): "create_todo",
    ("pack", None): "create_todo",
    ("file", None): "create_todo",
    ("renew", None): "create_todo",
    ("cook", None): "create_todo",
    ("prepare", None): "create_todo",
    # Found missing via segmentation's adversarial stress test (§0c,
    # 2026-09-16/17) — common task verbs with no entry at all, so a bare
    # "finalize the budget and text karen" never even split (`_is_command_
    # verb` reads this same table). "prep" is "prepare"'s own shorthand,
    # already routed; "draft"/"finalize" are new.
    ("draft", None): "create_todo",
    ("finalize", None): "create_todo",
    ("prep", None): "create_todo",
    # --- The tag lexicon's errand verbs the cut did not know, 2026-09-20.
    #     `fastseg._TASK_VERBS` and this table are different inventories, and
    #     `_is_command_verb` reads only this one — so "first RESTOCK the
    #     pantry, then let's get piano lesson on the calendar" produced its
    #     boundary on the subordinate-clause path and the walk never asked
    #     for it. Family from FastRule's own 7,200 train gold, atomic rows
    #     where the verb heads the command (create_todo / everything else):
    #     back 8/2 · charge 6/1 · feed 8/2 · print 6/1 · refill 6/3 ·
    #     restock 9/1 · return 16/1 · submit 3/0 · vacuum 4/2 · walk 6/1.
    #     Left out on the same evidence: "take" (14 of 22 are "take X off my
    #     calendar", a delete), and collect / fold / top / arrange / rebook,
    #     which head no train row at all.
    ("back", None): "create_todo",
    ("charge", None): "create_todo",
    ("feed", None): "create_todo",
    ("print", None): "create_todo",
    ("refill", None): "create_todo",
    ("restock", None): "create_todo",
    ("return", None): "create_todo",
    ("submit", None): "create_todo",
    ("vacuum", None): "create_todo",
    ("walk", None): "create_todo",
    # --- Mined from REAL speech, 2026-09-17 (segmentation/experiments/
    #     missing_verbs.py): ask-verbs used in HWU-64 (2,699 human-written
    #     utterances, sealed 300 excluded), the author's own command memory
    #     (lemma counts only), and FastRule's train half, that no lexicon
    #     knew. Family from FastRule's own gold where it has the verb, from
    #     the HWU examples otherwise — never from the generated corpus, whose
    #     vocabulary is this table. Counts: hwu / memory / fastrule.
    # encounters — create_event per gold (meet 127, talk 45/45, catch 15/15,
    # touch 15/15, head 15/15, squeeze 14/14, pencil 13/13)
    ("meet", None): "create_event",         # 48 / 3 / 21
    ("talk", None): "create_event",         # 2 / 0 / 45   "talk to Taylor in five days"
    ("catch", None): "create_event",        # 0 / 0 / 15   "catch up with Cameron"
    ("touch", None): "create_event",        # 0 / 0 / 15   "touch base with Alex"
    ("head", None): "create_event",         # 0 / 0 / 15   "head to standup"
    ("squeeze", None): "create_event",      # 0 / 0 / 14   "squeeze in piano lesson"
    ("pencil", None): "create_event",       # 3 / 0 / 13   "pencil me in for…"
    ("attend", None): "create_event",       # 7 / 0 / 0
    # reminder framing — create_event per gold (notify 17/17, alert 15/15):
    # "alert me 2 hours before my meeting" is a reminder OF an event
    ("notify", None): "create_event",       # 26 / 0 / 3
    ("alert", None): "create_event",        # 14 / 0 / 3
    ("label", "calendar"): "create_event",  # 0 / 0 / 15   "label the 15th as my birthday"
    # errands — create_todo per gold (confirm 19, mail 24, sign 22 as the ask;
    # the rest of their counts are rows where they are the wrapped title)
    ("confirm", None): "create_todo",       # 0 / 0 / 48
    ("mail", None): "create_todo",          # 0 / 0 / 35
    ("sign", None): "create_todo",          # 0 / 0 / 25
    ("tick", None): "complete_todo",        # 0 / 0 / 13   "tick X off my list"
    # deletes — qualified like delete/remove/clear; rid splits 15/14 by domain
    ("erase", "calendar"): "delete_event",  # 19 / 0 / 0   "erase the haircut i have scheduled"
    ("erase", "todo"): "delete_todo",
    ("rid", "calendar"): "delete_event",    # 4 / 0 / 29   "get rid of …"
    ("rid", "todo"): "delete_todo",
    # adds — qualified like add/put/create/make (HWU only)
    ("place", "calendar"): "create_event",  # 9 / 0 / 0    "place this on the calendar"
    ("place", "todo"): "create_todo",
    ("enter", "calendar"): "create_event",  # 7 / 0 / 0    "enter a reminder in my calendar"
    ("enter", "todo"): "create_todo",
    ("include", "calendar"): "create_event",  # 8 / 0 / 0  "include an item to a list"
    ("include", "todo"): "create_todo",
    # --- Todo complete ---
    ("mark", None): "complete_todo",
    ("check", "todo"): "complete_todo",   # "check off" / "check the task"
    ("complete", None): "complete_todo",
    ("finish", None): "complete_todo",
    ("done", None): "complete_todo",
    # --- Todo update ---
    ("update", "todo"): "update_todo",
    ("edit", "todo"): "update_todo",
    ("change", "todo"): "update_todo",
    ("set", "todo"): "update_todo",
    ("rename", "todo"): "update_todo",
    ("move", "todo"): "update_todo",    # "move task X to general" — overrides calendar "move"
    ("note", "todo"): "update_todo",
    ("annotate", None): "update_todo",
    # --- Todo delete ---
    ("delete", "todo"): "delete_todo",
    ("remove", "todo"): "delete_todo",
    ("clear", "todo"): "delete_todo",
    ("drop", "todo"): "delete_todo",
    ("scrap", None): "delete_todo",
    # --- Todo query ---
    ("show", "todo"): "query_todos",
    ("list", "todo"): "query_todos",
    ("read", "todo"): "query_todos",
}

# Words that strongly signal the calendar domain
_CALENDAR_SIGNALS = frozenset({
    "meeting", "event", "appointment", "sync", "standup", "stand-up",
    "interview", "session", "class", "lecture", "conference", "call",
    "seminar", "webinar", "calendar", "agenda", "schedule",
})

# Words that strongly signal the todo/task domain
_TODO_SIGNALS = frozenset({
    "task", "todo", "to-do", "reminder", "list", "grocery", "groceries",
    "errand", "chore", "shopping", "item", "priority", "subtask",
})

# Scope keywords for query_schedule
#: "tonight", "this morning/afternoon/evening" — a part of TODAY.
_PART_OF_TODAY_RE = re.compile(r"\b(?:tonight|this\s+(?:morning|afternoon|evening))\b", re.I)

_SCOPE_PHRASES: list[tuple[str, str]] = [
    ("this week", "week"),
    ("next week", "week"),
    ("the week", "week"),
    ("week", "week"),
    ("tomorrow", "tomorrow"),
    ("next day", "tomorrow"),
    ("today", "today"),
    ("this morning", "today"),
    ("this afternoon", "today"),
    ("tonight", "today"),
    ("this evening", "today"),
]

#: "to be 15 minutes", "to 45 mins", "for an hour and a half". The leading
#: "to be"/"to" marks the ABSOLUTE form — the event's new whole length — which
#: is the one this file can answer without reading the event.
_DURATION_RE = re.compile(
    r"\b(?:to\s+be|to\s+last|to|for)\s+"
    r"(\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|half|quarter)"
    r"(?:\s+and\s+(?:a\s+)?(half|quarter))?\s*"
    # "half AN hour", "quarter OF AN hour" — the article sits between the
    # amount and the unit in exactly the phrasings people actually say.
    r"(?:(?:of\s+)?an?\s+)?"
    r"(hours?|hrs?|h|minutes?|mins?|m)\b", re.IGNORECASE)

_DURATION_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
                   "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                   "ten": 10, "half": 0, "quarter": 0}


def _duration_minutes(m) -> "int | None":
    """A matched duration phrase as whole minutes, or None."""
    raw = (m.group(1) or "").lower()
    n = float(_DURATION_WORDS[raw]) if raw in _DURATION_WORDS else (
        float(raw) if raw.isdigit() else None)
    if n is None:
        return None
    if raw == "half":
        n = 0.5
    elif raw == "quarter":
        n = 0.25
    extra = (m.group(2) or "").lower()
    if extra == "half":
        n += 0.5
    elif extra == "quarter":
        n += 0.25
    unit = (m.group(3) or "").lower()
    minutes = n * 60 if unit.startswith(("hour", "hr", "h")) else n
    minutes = int(round(minutes))
    return minutes or None


# Verbs that extend/shorten the duration of an event (not move it)
# For these, "at X" = match_start_time (finder) and "to Y" = new_end_time (change)
_EXTEND_VERBS = frozenset({"extend", "lengthen", "stretch", "prolong", "shorten", "trim"})


def _extend_verbs() -> "frozenset[str]":
    """`_EXTEND_VERBS` plus anything the person added in Settings.

    Read through `lexicon` rather than used directly, so "the way I say it" is a
    setting and not a code change (Gil, 2026-09-18). The union is one-way: an
    edit can only ever widen this, never take a verb away — see
    `assistant/intent/lexicon.py`.
    """
    try:
        from assistant.intent.lexicon import effective
        return effective("extend_verbs") or _EXTEND_VERBS
    except Exception:                       # a broken store must never stop a parse
        return _EXTEND_VERBS

# Anaphoric references that trigger context memory lookup
_ANAPHORS = frozenset({
    "it", "that", "this", "the meeting", "the event", "that event",
    "this event", "the task", "that task", "the last one",
    "the last event", "the last task", "my last one",
})

# Required slots per action — used for confidence scoring and missing-slot detection
_REQUIRED_SLOTS: dict[str, list[str]] = {
    "create_event": ["title", "date", "start_time"],
    "update_event": ["match_title"],
    "delete_event": ["match_title"],
    "query_schedule": [],
    "create_todo": ["titles"],
    "complete_todo": ["match_title"],
    "delete_todo": ["match_title"],
    "update_todo": ["match_title"],
    "query_todos": [],
    "add_subtask": ["parent_title", "subtask_title"],
    "complete_subtask": ["parent_title", "subtask_title"],
    "delete_subtask": ["parent_title", "subtask_title"],
}

# Optional slots whose presence boosts confidence
_BONUS_SLOTS: dict[str, list[str]] = {
    "create_event": ["end_time", "attendees"],
    "update_event": ["new_start_time", "new_date", "match_start_time"],
    "delete_event": ["match_date", "match_start_time"],
    "create_todo": ["due_date", "priority"],
    "update_todo": ["new_priority", "new_due_date"],
}

# Priority keyword → priority level
_PRIORITY_KEYWORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(urgent|critical|asap|important|high[- ]priority)\b"), "high"),
    (re.compile(r"\bmedium[- ]priority\b"), "medium"),
    (re.compile(r"\blow[- ]priority\b"), "low"),
]

# Priority name words used in "set priority to X" patterns
_PRIORITY_NAMES = {"high": "high", "medium": "medium", "low": "low",
                   "urgent": "high", "critical": "high", "important": "high"}

# ---------------------------------------------------------------------------
# Pre-processing helpers
# ---------------------------------------------------------------------------


def _preprocess(transcript: str) -> "tuple[str, bool, int | None]":
    """Normalise text and check complexity gate.

    Returns (normalised_text, should_skip, lead_minutes) — the last is the
    spoken reminder lead time the lead-time reader took out of the text
    ("remind me 30 minutes before"), or None.
    should_skip=True means the complexity gate fired → caller should raise RuleParserSkip.
    """
    if not _RULE_PARSER_AVAILABLE:
        return transcript, True, None

    _ensure_nlp()
    if not _RULE_PARSER_AVAILABLE:  # may have been cleared by load failure
        return transcript, True, None

    text = transcript.strip().lower()

    # Strip view-context prefix injected by pipeline
    text = re.sub(r"^\[tasks view\]\s*", "", text)

    # Expand STT shorthands
    for pattern, replacement in _STT_EXPANSIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    for pattern, replacement in _SPOKEN_TIMES:      # F15
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # F16: the lead-time clause ("remind me 5 minutes before about X") ate
    # the title — FastRule failed 100% of those rows because the strip only
    # existed in the deep track's decompose stage.
    from assistant.intent import lead_time as _lead_time
    text, _minutes = _lead_time.split(text, restore_verb=True, trailing=True)
    # The same spoken-noise reader the transcript stage uses (one copy, two
    # callers): FastRule is also handed RAW text directly by the sandbox and
    # by any caller that skips the pipeline, and these patterns are
    # idempotent, so cleaning twice costs nothing.
    from assistant.intent.cleanup import strip_spoken_noise
    text = strip_spoken_noise(text, drop_courtesy=False)

    # Complexity gate: content-word count (stop/filler words don't add complexity)
    _FILLER = frozenset({
        "a", "an", "the", "my", "your", "our", "its", "i", "you", "we", "they",
        "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
        "can", "could", "will", "would", "should", "shall", "may", "might",
        "have", "has", "had", "of", "in", "on", "at", "to", "for", "with",
        "by", "from", "up", "about", "into", "and", "or", "but", "that", "this",
        "these", "those", "me", "him", "her", "us", "them", "it", "so",
        "please", "kindly", "just", "go", "ahead", "okay", "ok", "well",
        "actually", "really", "also", "too", "then", "there", "here",
        "what", "when", "where", "which", "who", "how", "let", "execute",
    })
    content_words = [w for w in text.split() if w.rstrip(".,!?;:") not in _FILLER]
    # REMOVED 2026-09-07 (Gil, pre-loop change #3): a >12-content-word gate
    # was a crude proxy for "this is probably compound", written before
    # layer 0 existed. It now fires BEFORE the real atomicity layer can
    # speak, so a long-but-single booking ("book the quarterly planning
    # workshop with Sam and Jordan next tuesday at half past nine in the
    # big conference room") is refused by the executor whose entire job is
    # single items — and lands in the "skip" bucket the loop mines, next to
    # genuinely unroutable text that needs the opposite fix. Length is not
    # evidence of multiplicity; the atomicity model reads the actual shape.
    _ = content_words

    # Clause-count gate via spaCy
    doc = _NLP(text)
    clause_verbs = [
        tok for tok in doc
        if tok.pos_ == "VERB"
        and (tok.dep_ == "ROOT" or tok.dep_ == "conj")
        and any(child.dep_ in ("nsubj", "nsubjpass", "expl") for child in tok.subtree)
    ]
    if len(clause_verbs) > 3:
        return text, True, _minutes

    # Relative clause with an explicit subject (e.g. "delete the event you created")
    # → too ambiguous for the rule parser, let the LLM handle it.
    has_relcl_with_subj = any(
        tok.pos_ == "VERB" and tok.dep_ == "relcl"
        and any(c.dep_ in ("nsubj", "nsubjpass") for c in tok.children)
        for tok in doc
    )
    if has_relcl_with_subj:
        return text, True, _minutes

    return text, False, _minutes


# ---------------------------------------------------------------------------
# Phase 1: Multi-intent splitting
# ---------------------------------------------------------------------------


_IMPERATIVE_VERB_LEMMAS: frozenset = frozenset(lemma for (lemma, _domain) in INTENT_MAP.keys())

# Common Whisper mishearings of sentence-initial imperative verbs. Only consulted
# at ROOT position in _route_intent (see Pass 5) — never as a general text
# substitution — so "meeting by 3pm" (where "by" is a legitimate preposition,
# not the ROOT) is unaffected.
_STT_HOMOPHONE_VERBS: dict = {
    "by": "buy",
    "bye": "buy",
}


def _lexicon_split_points(doc) -> list:
    """Fallback split-point detector for when spaCy's VERB-conjunct detection fails.

    spaCy's statistical POS tagger frequently mistags a bare imperative verb
    immediately followed by a bare-noun object as a NOUN compound instead of a
    VERB — e.g. "schedule meeting tomorrow" gets ROOT="meeting" (NOUN), hiding
    "schedule" from the VERB-conjunct search entirely. "book", "plan", and
    "block" show the same failure mode with their own bare-noun objects.

    Rather than fight the tagger, use vocabulary we already control: INTENT_MAP's
    verb lemmas. A token qualifies as a split point only if it's sentence-initial
    or immediately follows a coordinating "and"/"or" — both low-risk positions
    (a command verb mid-clause, e.g. "the schedule needs an update", won't match
    either condition), so this can't fire on ordinary single-action sentences.
    """
    points = []
    for i, tok in enumerate(doc):
        if tok.lemma_.lower() not in _IMPERATIVE_VERB_LEMMAS:
            continue
        sentence_initial = i == 0
        follows_cc = i > 0 and doc[i - 1].dep_ == "cc" and doc[i - 1].lower_ in ("and", "or")
        if not (sentence_initial or follows_cc):
            continue
        # The same object-sharing guard the dependency path uses. Without it
        # this fallback UNDOES that decision: suppressing the split above just
        # drops `split_verbs` below two, which is the exact condition that
        # hands the sentence to this function, and "sort and file the
        # paperwork" was cut in half here instead of there.
        if follows_cc and points and _serial_verbs(points[-1], tok):
            continue
        points.append(tok)
    return points


#: dependency labels for "this verb has an object of its own"
_OBJECT_DEPS = frozenset({"dobj", "dative", "attr", "obj", "oprd"})


def _serial_verbs(head, conj) -> bool:
    """Two coordinated verbs sharing ONE object — "wash and fold the laundry".

    One task, not two, and its name keeps both verbs: 50 rows of the FastRule
    7,200 set say so (families `c_npdecoy_serial_*`, gold title 'wash and fold
    the laundry'). The engine used to cut at the "and" and produce a task
    called 'wash', which is not a thing anyone can do.

    The signal is what the FIRST verb is missing: it has no object, and the
    second one does, so the object after the second verb is the object of both.
    "buy milk and call mom" has one each and stays two tasks.

    spaCy mistags the leading verb often enough here ("clean" comes back ADJ in
    "clean and organize the garage") that the HEAD's tag is not checked — only
    that it has no object. The conjunct's own VERB tag carries the reading.

    ADJACENCY is what keeps that leniency safe. Serial verbs have nothing
    between them but the conjunction, and requiring it is the difference
    between this reading and a mistake: "book gym on tuesday at 7am and remind
    me to buy milk" parses with ROOT=`gym` (NOUN — the tagger lost `book`
    entirely), so `remind` is a conjunct of a head with no object, and without
    adjacency this merged a real two-command sentence into one.
    """
    if conj.pos_ != "VERB":
        return False
    cc = conj.i - 1
    if cc <= head.i or conj.doc[cc].dep_ != "cc" or cc - 1 != head.i:
        return False
    if not any(c.dep_ in _OBJECT_DEPS for c in conj.children):
        return False
    return not any(c.dep_ in _OBJECT_DEPS for c in head.children)


def _serial_verb_pairs(span) -> "frozenset[str]":
    """The "wash and fold" bigrams in a span, for `split_items` to keep whole.

    `list_split` is pure string work by design and has no parse to consult, so
    the parse is read HERE and handed down as pairs, the same way `_AND_IDIOMS`
    already protects "fish and chips".
    """
    pairs = set()
    for tok in span:
        if tok.dep_ != "conj" or not _serial_verbs(tok.head, tok):
            continue
        cc = next((c for c in tok.head.children
                   if c.dep_ == "cc" and c.i < tok.i), None)
        if cc is not None:
            pairs.add(f"{tok.head.text} {cc.text} {tok.text}".lower())
    return frozenset(pairs)


def _split_intents(doc) -> list:
    """Split a spaCy Doc into per-intent Span objects.

    Finds the ROOT verb and any conjunct VERBs, then builds subtree spans
    for each, so "buy milk and call mom" → two spans.
    """
    root = next((tok for tok in doc if tok.dep_ == "ROOT"), None)
    if root is None:
        return [doc[:]]

    # A COURTESY TAIL is not a second intent. "extend open house by an hour
    # and LET AVERY KNOW" split into two spans, the second routed to nothing,
    # and an unroutable span costs the whole parse 30% of its confidence —
    # so 15 atomic rows of the train half deferred at 0.66 for a tail that
    # asks for nothing. The pattern is `coordination`'s, the same one the
    # deep track's cut uses, so the two splitters agree about what a tail
    # is. ONLY the courtesy tail: a lead-time tail ("…, remind me a week
    # before") is still split off here, because keeping it in the span put
    # "remind me before" into three titles — reading it as a lead time is a
    # separate gap in this parser, filed.
    from assistant.intent.coordination import _COURTESY_TAIL_RE

    split_verbs = [root] + [
        tok for tok in doc
        if tok.dep_ == "conj" and tok.head == root and tok.pos_ == "VERB"
        # ...unless the two verbs share one object, in which case the "and"
        # joins them rather than separating two commands (`_serial_verbs`).
        and not _serial_verbs(root, tok)
        and not _COURTESY_TAIL_RE.match(doc[tok.i:].text.strip())
    ]

    if len(split_verbs) < 2:
        # spaCy's dependency parse found only one verb — try the lexicon fallback
        # before giving up and treating this as a single-intent sentence.
        lexicon_points = _lexicon_split_points(doc)
        if len(lexicon_points) >= 2:
            # These tokens aren't reliable syntactic heads (mistagged as NOUN, so
            # their .subtree is unusable — it may not cover the clause's temporal
            #/object tokens at all). Partition the doc by raw token position
            # between consecutive split points instead of by subtree.
            points_sorted = sorted(lexicon_points, key=lambda t: t.i)
            spans = []
            for idx, tok in enumerate(points_sorted):
                start = tok.i
                end = points_sorted[idx + 1].i if idx + 1 < len(points_sorted) else len(doc)
                if start < end:
                    spans.append(doc[start:end])
            return spans if spans else [doc[:]]
        return [doc[:]]

    # Sort by position and build non-overlapping spans.
    # A conj verb's own .subtree always includes everything nested under it, and
    # since conj verbs hang off the ROOT, the ROOT's subtree also covers the whole
    # sentence — using raw subtree bounds would make span[0] duplicate the full
    # transcript alongside the later per-verb spans. Clip each span so it stops at
    # the start of the next split verb and starts no earlier than the previous
    # span's end, giving contiguous, non-overlapping chunks instead.
    split_verbs_sorted = sorted(split_verbs, key=lambda t: t.i)
    spans = []
    prev_end = 0
    for idx, verb in enumerate(split_verbs_sorted):
        subtree_tokens = sorted(verb.subtree, key=lambda t: t.i)
        start = max(subtree_tokens[0].i, prev_end)
        end = subtree_tokens[-1].i + 1
        if idx < len(split_verbs_sorted) - 1:
            end = min(end, split_verbs_sorted[idx + 1].i)
        if start < end:
            spans.append(doc[start:end])
            prev_end = end

    return spans if spans else [doc[:]]


# ---------------------------------------------------------------------------
# Phase 2: Temporal extraction
# ---------------------------------------------------------------------------


def _normalize_time(value: str) -> str:
    """Convert 'T15:00:00' or '15:00:00' to 'HH:MM'."""
    value = value.lstrip("T")
    parts = value.split(":")
    if len(parts) >= 2:
        return f"{int(parts[0]):02d}:{parts[1]}"
    return value


# "7am" / "7a.m." — an hour with the meridiem written against it. The datetime
# recogniser sometimes hands back BOTH readings for these (it separates cleanly
# on "7 am"), and preferring PM then turned an explicitly stated morning time
# into an evening one.
# "rename the meeting with Tal to robotics sync" — everything between the verb
# and the final "to"/"as" is the event, the rest is its new name.
# "the meeting with Ima", "lunch with Tal" — noun chunking stops at the noun and
# drops the person, leaving a bare "meeting" that matches ANY meeting. Since the
# name is the only thing distinguishing one from another, keep it.
_WITH_WHOM_RE = re.compile(
    r"\b{title}\s+(with\s+[A-Za-z][\w'’-]*(?:\s+(?:and|&)\s+[A-Za-z][\w'’-]*)?)",
    re.IGNORECASE,
)


def _extend_title_with_whom(span_text: str, title: str) -> str:
    """Append a trailing "with <name>" to a matched title, when one was said."""
    if not title:
        return title
    pattern = _WITH_WHOM_RE.pattern.format(title=re.escape(title.strip()))
    m = re.search(pattern, span_text, re.IGNORECASE)
    if not m:
        return title
    return f"{title.strip()} {m.group(1).strip()}"


# "with the dentist" / "with my mum" — the word after "with" is a determiner, so
# the person's name never made it in. Half a phrase ("meeting with the") is a
# worse needle than the bare word, so it does not count as naming anybody.
_NOT_A_NAME_AFTER_WITH = frozenset({
    "the", "a", "an", "my", "our", "your", "his", "her", "their", "its",
    "this", "that", "these", "those", "some", "any", "each", "both",
    "him", "them", "me", "us", "someone", "somebody", "everyone", "everybody",
})


def _title_with_person(span_text: str, title: str) -> tuple[str, bool]:
    """Return the title plus any trailing "with <name>", and whether one was found.

    The flag is what lets a caller tell "meeting with Ima" (identifies one
    event) from a bare "meeting" (identifies any of them).
    """
    if not title:
        return title, False
    extended = _extend_title_with_whom(span_text, title)
    if extended.strip().lower() == title.strip().lower():
        return title, False
    whom = extended[len(title.strip()):].split()      # ["with", "<name>", ...]
    if len(whom) < 2 or whom[1].lower() in _NOT_A_NAME_AFTER_WITH:
        return title, False
    return extended, True


_RENAME_RE = re.compile(
    r"\b(?:rename|re-?name)\s+(?:the\s+|my\s+)?(.+?)\s+(?:to|as)\s+(.+?)\s*$",
    re.IGNORECASE,
)

_SAID_MERIDIEM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\.?\b", re.I)


#: A DOT CLOCK — "6.30am", "at 7.15" — the way a transcript often writes the
#: minutes. The recogniser reads the colon form and drops the dot form's
#: minutes: "tomorrow at 6.30" came out 18:00, "tomorrow morning at 6.30am"
#: 06:00 (Gil's real command id 213; FastRule board, 2026-09-25). Only a clock
#: in a time context is rewritten — followed by am/pm, or after a time
#: preposition — so "2.5 hours" and "$5.99" are never read as clocks. The
#: rewrite is one character for one, so every span offset stays valid.
_DOT_CLOCK = re.compile(
    r"(?:(?<=\bat\s)|(?<=\bfrom\s)|(?<=\bto\s)|(?<=\buntil\s)|(?<=\btill\s)|(?<=\bby\s)"
    r"|(?<=\baround\s)|(?<=\babout\s))(\d{1,2})\.([0-5]\d)\b"
    r"|\b(\d{1,2})\.([0-5]\d)(?=\s*[ap]\.?\s?m\b)", re.I)


def _dot_clocks_to_colons(text: str) -> str:
    return _DOT_CLOCK.sub(lambda m: f"{m.group(1) or m.group(3)}:{m.group(2) or m.group(4)}",
                          text or "")


_EIGHT_OCLOCK = re.compile(r"\b(?:8|eight)\s*o'?\s?clock\b", re.I)


def _pick_business_hour_time(values: list[dict], said: str = "") -> str | None:
    """Given multiple time values (AM/PM ambiguity), prefer PM for hours 1–7.

    `said` is the text the values came from: when it states am or pm outright
    that wins, because there is no ambiguity left to resolve.
    """
    if not values:
        return None
    times = [v.get("value", "") or v.get("timex", "") for v in values]
    parsed: list[tuple[int, str]] = []
    for t in times:
        normalized = _normalize_time(t)
        try:
            h = int(normalized.split(":")[0])
            parsed.append((h, normalized))
        except Exception:
            pass
    if not parsed:
        return None

    # Honour an explicitly spoken meridiem before guessing.
    for m in _SAID_MERIDIEM.finditer(said or ""):
        hour12 = int(m.group(1)) % 12
        wanted = hour12 + (12 if m.group(3).lower() == "p" else 0)
        for h, t in parsed:
            if h == wanted:
                return t

    # Prefer PM (12-19) for business hours ambiguity; else just take highest hour
    pm_options = [(h, t) for h, t in parsed if 12 <= h <= 20]
    if pm_options:
        return min(pm_options, key=lambda x: x[0])[1]
    return min(parsed, key=lambda x: abs(x[0] - 10))[1]  # closest to 10 AM


#: Nouns that make "the Nth" an ordinal POSITION rather than a date — "remove
#: the 2nd row from the list". Both this and the "of every" exclusion below come
#: from the verification pool, not from imagination: real speech uses the same
#: three words for a place in a list and for a day of the month.
_ORD_NOT_A_DATE = (r"row|item|one|line|column|entry|element|paragraph|page|cell|"
                   r"slot|place|position|step|section|chapter|floor|time|"
                   r"anniversary|birthday")

#: A BARE ordinal day — "the 30th", "call Jordan the 3rd". The DateTime
#: recogniser resolves "ON the 15th" and returns NOTHING AT ALL for the bare
#: form, so the date was silently dropped: the task was created with no due
#: date, on the Today list, at a confidence high enough to commit instantly
#: (filed 2026-09-17). Excluded: an ordinal position, and "the 15th of every
#: month", which is a RECURRENCE — resolving that to one day would book a
#: single event and lose the series.
_BARE_ORDINAL_DATE = re.compile(
    r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b"
    r"(?!\s+of\s+(?:every|each))"
    r"(?!\s+(?:" + _ORD_NOT_A_DATE + r")\b)",
    re.IGNORECASE,
)


def _ordinal_to_date(day: int, today: datetime.date) -> "str | None":
    """A bare "the Nth" means THIS month if that day has not yet passed, else
    NEXT month — the same convention the recogniser applies to "on the 15th",
    so the two phrasings cannot disagree. None for a day that is not a day, and
    for "the 31st" of a 30-day month: nothing beats a wrong date.
    """
    if not 1 <= day <= 31:
        return None
    if day >= today.day:
        try:
            return today.replace(day=day).isoformat()
        except ValueError:
            return None
    nxt = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    try:
        return nxt.replace(day=day).isoformat()
    except ValueError:
        return None


#: "in two weeks", "in a month" — a DURATION from now, not a named span. The
#: recogniser returns these as a `daterange` whose START is badly wrong for the
#: everyday reading: "in a week" came back as TOMORROW (the start of the coming
#: week) and "in two months" as one month out. Its END is closer but off by one,
#: the ranges being half-open, so the arithmetic is done here instead of
#: inferring the library's convention. "in N days" is NOT here: the recogniser
#: already returns a plain `date` for those and gets them right.
_DURATION_AHEAD = re.compile(
    r"\bin\s+(a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+"
    r"(week|month|year)s?\b", re.IGNORECASE)
_NUMBER_WORD = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
                "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _duration_ahead_to_date(n: int, unit: str, today: datetime.date) -> "str | None":
    """now + N weeks/months/years, clamped to a real day: "in two months" from
    the 31st lands on the 30th rather than raising."""
    unit = unit.lower()
    if unit == "week":
        return (today + datetime.timedelta(weeks=n)).isoformat()
    months = n * 12 if unit == "year" else n
    total = (today.year * 12 + today.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = today.day
    while day > 1:
        try:
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            day -= 1                      # 31st of a 30-day month
    return datetime.date(year, month, 1).isoformat()


#: The keyword that opens a SERIES BOUND — "every monday until the end of the
#: month". Both spellings of thru are listed although `_preprocess` normalises
#: one to the other: `_extract_temporal` is also called directly, on raw text.
_SERIES_BOUND_KW = re.compile(
    r"\b(up\s+until|up\s+to|until|till|til|through|thru|including)\b", re.IGNORECASE)

#: Which side of the named day the series stops. Gil's standing ruling:
#: *"until" excludes the day it names; "through" and "including" keep it* — with
#: the documented exception that "until the END OF <period>" is INCLUSIVE, because
#: that phrase names the final day rather than a boundary past it.
_BOUND_INCLUSIVE_KW = re.compile(r"\b(through|thru|including)\b", re.IGNORECASE)
_BOUND_END_OF = re.compile(r"\bend\s+of\b", re.IGNORECASE)

#: What may stand between the bound keyword and the date it names: nothing, or
#: a function word ("until THE end of the month", "through TO friday"). Anything
#: else means the keyword is not opening a bound at all — "walk THROUGH the
#: slides tomorrow at 3pm" read "the slides tomorrow" as a series end, invented a
#: bound, and ate the event's own day. The old guard ("no date, no bound") was
#: satisfied by a date three words away.
_BOUND_GAP = re.compile(r"^[\s,]*(?:(?:the|on|at|to|about|around|of|by)\s+)*$",
                        re.IGNORECASE)


#: A clock time sitting at the END of the bound's own match. The recogniser
#: returns "next tuesday at 5 pm" as ONE datetime, but in "daily through next
#: tuesday at 5 pm" the 5 pm is the EVENT's time — masking the whole match lost
#: it and the row committed with no time at all.
_BOUND_TRAILING_TIME = re.compile(
    r"\s*(?:\bat\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?"
    r"|noon|midday|midnight|quarter\s+(?:to|past)\s+\w+|half\s+past\s+\w+)\s*$",
    re.IGNORECASE)


def _bound_date(tail: str, today: datetime.date, inclusive: bool) -> "tuple[str, int] | None":
    """Resolve a bound phrase. -> (ISO date, chars of `tail` it occupies).

    Which END of a range is meant depends on the speaker's word, and the two
    readings genuinely differ:

        "until next month"          the month is the STOP -> the day before it starts
        "until the end of the month"  names the final day  -> the last day of it
        "through next week"         runs to the END of next week

    So an exclusive bound counts back from the range's START and an inclusive one
    from its END — and the recogniser's range ends are exclusive, hence the extra
    day off. A plain date needs no arithmetic beyond the exclusive step.
    """
    if _DT_AVAILABLE:
        _ensure_dt()
    if _DT_AVAILABLE and _DT_MODEL is not None:
        ref = datetime.datetime.combine(today, datetime.time())
        try:
            found = _DT_MODEL.parse(tail, ref)
        except Exception:
            found = []
        for res in found:
            if not _BOUND_GAP.match(tail[:res.start]):
                continue                     # a date, but not THIS keyword's
            for wren in (getattr(res, "resolution", None) or {}).get("values", []):
                kind = wren.get("type", "")
                iso = None
                if kind in ("date", "datetime"):
                    raw = (wren.get("value") or "").split(" ")[0]
                    if raw and raw != "not":
                        iso = raw
                    if iso and not inclusive:
                        iso = (datetime.date.fromisoformat(iso)
                               - datetime.timedelta(days=1)).isoformat()
                elif kind == "daterange":
                    edge = wren.get("end") if inclusive else wren.get("start")
                    if edge:
                        try:
                            iso = (datetime.date.fromisoformat(str(edge)[:10])
                                   - datetime.timedelta(days=1)).isoformat()
                        except ValueError:
                            iso = None
                if not iso:
                    continue
                # Keep a trailing clock time out of the masked span.
                text = tail[res.start:res.end + 1]
                trimmed = _BOUND_TRAILING_TIME.sub("", text)
                return iso, res.start + max(len(trimmed), 1)

    # No recogniser answer: this file's own readers still know "the 3rd".
    m = _BARE_ORDINAL_DATE.search(tail)
    if m and _BOUND_GAP.match(tail[:m.start()]):
        iso = _ordinal_to_date(int(m.group(1)), today)
        if iso:
            if not inclusive:
                iso = (datetime.date.fromisoformat(iso)
                       - datetime.timedelta(days=1)).isoformat()
            return iso, m.end()
    return None


def _series_bound(span_text: str, today: datetime.date) -> "tuple[str, int, int] | None":
    """Find and resolve a series bound. -> (ISO date, start, end) over `span_text`.

    None when there is no bound keyword, or when nothing after it resolves to a
    date — which is the guard that stops "a tour through the museum" being read
    as a boundary.
    """
    m = _SERIES_BOUND_KW.search(span_text)
    if not m:
        return None
    phrase = span_text[m.start():]
    inclusive = (bool(_BOUND_INCLUSIVE_KW.search(m.group(1)))
                 or bool(_BOUND_END_OF.search(phrase)))
    got = _bound_date(span_text[m.end():], today, inclusive)
    if not got:
        return None
    iso, consumed = got
    return iso, m.start(), m.end() + consumed


#: A COARSE DAYPART, as the recogniser spells it: `TMO` / `TAF` / `TEV` / `TNI`.
#: An explicit range is `(T15,T16,PT1H)` and a clock is `T07`, so this shape is
#: exactly the readings that name a WINDOW rather than a time.
_DAYPART_TIMEX = re.compile(r"^T[A-Z]{2,3}$")

#: A daypart that QUALIFIES the clock before it — "at 6 IN THE evening", "9 IN
#: THE morning". The recogniser returns the two as separate readings, and the
#: second is the first's meridiem, not a window of its own. The preposition is
#: the tell, and the recogniser sometimes keeps it inside the daypart's own
#: match ("in the evening") and sometimes leaves it in the gap — so both are
#: read. A bare daypart straight after a clock ("at 7am morning pages") is NOT
#: a qualifier: with no preposition it is the next thing's name.
_QUALIFIER_GAP = re.compile(r"^[\s,]*(?:in|of)\s+(?:the\s+)?$", re.IGNORECASE)
_QUALIFIER_LEAD = re.compile(r"^(?:in|of)\s+(?:the\s+)?\w", re.IGNORECASE)


def _extract_temporal(span_text: str, today: datetime.date,
                      _bound_pass: bool = False) -> dict:
    """Extract date/time information from a span of text.

    Returns a dict with keys:
      date, start_time, end_time, spans (list of (start_char, end_char) blocked)
      _source: "recognizer" | "regex_fallback"
    """
    span_text = _dot_clocks_to_colons(span_text)
    result: dict = {
        "date": None,
        "start_time": None,
        "end_time": None,
        "spans": [],
        "_source": "recognizer",
        "_used_anaphora": False,
        "_domain_inferred": False,
        #: Where a recurring series STOPS, as an ISO date, already adjusted for
        #: whether the speaker's word includes the day it names. None unless the
        #: text carries a bound.
        "recur_until": None,
        #: The phrase a RANGE date came from ("next week"), when the date below
        #: is one day CHOSEN out of a span rather than one the speaker named.
        #: The caller asks the speaker to confirm it instead of committing —
        #: Gil's ruling, 2026-09-17. None when the date is unambiguous.
        "_date_from_range": None,
    }
    range_candidates: list = []
    #: Daypart WINDOWS seen on the way, applied only if nothing states a clock.
    daypart_candidates: list = []
    #: Where the last reading that carried a CLOCK ended, so a daypart that
    #: follows it directly can be read as that clock's meridiem.
    last_clock_end: "int | None" = None

    # THE SERIES BOUND COMES OFF FIRST, or it is read as the item's own date.
    # `_rec.start_date()` in `_fill_slots` already anchors "every monday" on the
    # soonest Monday, correctly — and then `temporal["date"]` overwrote it with
    # whatever the bound resolved to, so "every monday until the end of the
    # month" started on a WEDNESDAY and "twice a week until next month" started a
    # month late. Masking with spaces keeps every later character offset valid,
    # which `result["spans"]` and the title extraction both depend on.
    if not _bound_pass:
        bound = _series_bound(span_text, today)
        if bound:
            iso, b_start, b_end = bound
            result["recur_until"] = iso
            result["spans"].append((b_start, b_end))
            span_text = (span_text[:b_start]
                         + " " * (b_end - b_start)
                         + span_text[b_end:])

    if _DT_AVAILABLE:
        _ensure_dt()
    if _DT_AVAILABLE and _DT_MODEL is not None:
        dt_ref = datetime.datetime.combine(today, datetime.time())
        recognized = _DT_MODEL.parse(span_text, dt_ref)
        for res in recognized:
            span = (res.start, res.end + 1)
            # The recogniser can return a match with no resolution at all —
            # "from 9 to 10" is one — and dereferencing it raised an
            # AttributeError that escaped the parser entirely, killing the
            # command instead of falling back to the LLM.
            resolution = getattr(res, "resolution", None) or {}
            values = resolution.get("values", [])
            # A DAYPART IS A WINDOW, NOT A CLOCK. Read in order, "morning" in
            # "book morning pages tomorrow at 7am" set 08:00-12:00 first and the
            # stated 7am was then refused as a second start — the title's word
            # decided the event's clock. The convention is the one
            # decompose_validate already applies: a stated clock ALWAYS wins and
            # a window is the last resort, so the window is held back until the
            # span has been read. A window that loses claims no span, and its
            # word stays in the title, where it belongs.
            #
            # EXCEPT directly after a clock, where it is that clock's MERIDIEM:
            # "at 6 in the evening" comes back as "6" and "in the evening" in two
            # readings, and the second says which 6 — it is not a window and not
            # a title word. Measured on the 7,200 train half before this branch
            # existed: nine rows of exactly that shape, and dropping the
            # qualifier as a lost window put "in the evening" into every title.
            if values and all(v.get("type") == "timerange"
                              and _DAYPART_TIMEX.match(v.get("timex") or "")
                              for v in values):
                gap = (span_text[last_clock_end:res.start]
                       if last_clock_end is not None else None)
                if gap is not None and (
                        _QUALIFIER_GAP.match(gap)
                        or (not gap.strip(" ,") and _QUALIFIER_LEAD.match(res.text or ""))):
                    result["spans"].append(span)
                    result["_daypart_qualifier"] = values[0].get("timex")
                else:
                    daypart_candidates.append(
                        (span, values[0].get("start", ""), values[0].get("end", "")))
                continue
            result["spans"].append(span)
            if any(v.get("type") in ("time", "datetime", "timerange") for v in values):
                last_clock_end = res.end + 1
            for wren in values:
                timex_type = wren.get("type", "")

                # A RANGE ("next week", "this weekend", "by friday") carries no
                # `value` at all — the answer is in `start`/`end`. Nothing read
                # these, so the date was silently DROPPED: a task landed on the
                # Today list with no due date at a confidence high enough to
                # commit instantly. Collected here and applied only AFTER the
                # loop, so an exact date anywhere in the span always wins.
                if timex_type == "daterange" and not wren.get("value"):
                    range_candidates.append(
                        (res.start, res.end + 1, wren.get("start"), wren.get("end")))
                    continue

                # A DATE THAT CARRIES THE CLOCK outranks a bare one read
                # earlier. "book monday standup tomorrow at 9am" landed on
                # MONDAY because the first date in the string won; the day the
                # speaker attached the clock to is the event's day. The losing
                # reading KEEPS its claim on its words: a date word that lost
                # precedence is still a date word, and handing its span back
                # to the title put "tomorrow" into "set a meeting tomorrow on
                # tuesday at 6pm with etai" (a pinned title test).
                if timex_type == "datetime" and (
                        not result["date"] or result.get("_bare_date_span")):
                    raw = wren.get("value", "")
                    if raw and raw != "not resolved":
                        parts = raw.split(" ")
                        date_part = parts[0]
                        time_part = parts[1][:5] if len(parts) > 1 else None
                        if date_part >= today.isoformat():
                            # A STATED DAY already read beats a WEEKDAY the clock
                            # was attached to (`_DELIBERATE_DAY_RE`): "tomorrow on
                            # tuesday at 6pm" is tomorrow, and the clock is still
                            # taken. Everything else keeps the clock rule above.
                            prior = result.get("_bare_date_span")
                            prior_text = span_text[prior[0]:prior[1]] if prior else ""
                            this_text = span_text[span[0]:span[1]]
                            weekday_only = bool(_WEEKDAY_WORD_RE.search(this_text)
                                                and not _DELIBERATE_DAY_RE.search(this_text))
                            if (prior and result["date"] and weekday_only
                                    and _DELIBERATE_DAY_RE.search(prior_text)):
                                if time_part and not result["start_time"]:
                                    result["start_time"] = time_part
                            else:
                                result.pop("_bare_date_span", None)
                                result["date"] = date_part
                                result["_weekday_date"] = weekday_only
                                if time_part and not result["start_time"]:
                                    result["start_time"] = time_part
                        elif "_dt_past_fallback" not in result:
                            # Past date — keep as fallback in case no future value follows
                            result["_dt_past_fallback"] = (date_part, time_part)

                elif timex_type == "date" and not result["date"]:
                    raw = wren.get("value", "")
                    if raw and raw != "not resolved":
                        # For ambiguous dates (multiple values like Friday past/future),
                        # we'll take the last recognized result (processed on next iteration)
                        candidate = raw
                        if candidate >= today.isoformat():
                            result["date"] = candidate
                            result["_bare_date_span"] = span
                            this_text = span_text[span[0]:span[1]]
                            result["_weekday_date"] = bool(
                                _WEEKDAY_WORD_RE.search(this_text)
                                and not _DELIBERATE_DAY_RE.search(this_text))
                        elif "_dt_past_fallback" not in result:
                            # A PAST-ONLY date is kept as a fallback, exactly as
                            # the datetime branch above already does. It used to
                            # be dropped on the floor, and the asymmetry was
                            # invisible for a specific reason: a bare weekday
                            # ("friday") resolves to TWO values, past and future,
                            # so the future one set the date on the next
                            # iteration and nothing was lost. "this friday"
                            # resolves to exactly ONE — the current week's — so
                            # from Saturday onward it is in the past and the
                            # command lost its date entirely.
                            #
                            # Losing it is the worst outcome available: the
                            # speaker said a day. Recovering it lets
                            # `_rule_past_date_bump` do its job — "within a week
                            # back it's a weekday that just went → same weekday
                            # next week" — which turns "this friday" said on a
                            # Sunday into the coming Friday.
                            result["_dt_past_fallback"] = (candidate, None)

                elif timex_type == "time" and not result["start_time"]:
                    # May have multiple values (AM/PM ambiguity) — pick business hours
                    all_time_vals = (getattr(res, "resolution", None) or {}).get("values", [])
                    result["start_time"] = _pick_business_hour_time(all_time_vals, span_text)

                elif timex_type == "timerange":
                    start_v = wren.get("start", "")
                    end_v = wren.get("end", "")
                    if start_v and not result["start_time"]:
                        result["start_time"] = _normalize_time(start_v)
                    if end_v and not result["end_time"]:
                        result["end_time"] = _normalize_time(end_v)

        # The other way round: the date came from a WEEKDAY alone and the words
        # also carry an ordinal that lands elsewhere — "monday the 13th", "on
        # the 14th on tuesday". The ordinal is the deliberate one; it wins, and
        # its words leave the title (`_DELIBERATE_DAY_RE`, cycle 36).
        if result.get("date") and result.pop("_weekday_date", False):
            m_ord = _BARE_ORDINAL_DATE.search(span_text)
            if m_ord:
                resolved = _ordinal_to_date(int(m_ord.group(1)), today)
                if resolved and resolved != result["date"]:
                    result["date"] = resolved
                    result["spans"].append((m_ord.start(), m_ord.end()))
        result.pop("_weekday_date", None)
        result.pop("_bare_date_span", None)

        # "this coming thursday" → the soonest Thursday (see `_COMING_WEEKDAY_RE`).
        # Only when the date the recogniser produced IS that weekday and a week
        # too far; nothing else about the reading is touched.
        m_coming = _COMING_WEEKDAY_RE.search(span_text)
        if m_coming and result.get("date"):
            try:
                got_d = datetime.date.fromisoformat(result["date"])
                want = _WEEKDAY_INDEX[m_coming.group(1).lower()]
                ahead = (want - today.weekday()) % 7 or 7
                soonest = today + datetime.timedelta(days=ahead)
                if got_d.weekday() == want and got_d > soonest:
                    result["date"] = soonest.isoformat()
            except ValueError:
                pass

        # THE QUALIFIER SETTLES AM/PM. A datetime with two readings ("today at
        # 6" -> 06:00 and 18:00) took the first, so "today at 6 in the evening"
        # was booked at 06:00 with the evening as its END; the word after the
        # clock is what says which one was meant.
        qualifier = result.pop("_daypart_qualifier", None)
        if qualifier and result["start_time"]:
            try:
                _qh, _qm = result["start_time"].split(":")
                _qh = int(_qh)
                if qualifier == "TMO" and _qh >= 12:
                    _qh -= 12
                elif qualifier in ("TAF", "TEV", "TNI") and _qh < 12:
                    _qh += 12
                result["start_time"] = f"{_qh:02d}:{_qm}"
            except (ValueError, AttributeError):
                pass

        # Apply past-datetime fallback if no future date was resolved
        if not result["date"] and "_dt_past_fallback" in result:
            date_part, time_part = result.pop("_dt_past_fallback")
            result["date"] = date_part
            if time_part and not result["start_time"]:
                result["start_time"] = time_part
        else:
            result.pop("_dt_past_fallback", None)

        # Handle datetime with AM/PM ambiguity (two values returned)
        if recognized:
            all_dt_vals = [
                v for res in recognized
                for v in (getattr(res, "resolution", None) or {}).get("values", [])
                if v.get("type") == "datetime"
            ]
            if len(all_dt_vals) >= 2 and result["start_time"] is None:
                # Re-pick based on business hours
                result["start_time"] = _pick_business_hour_time(
                    [{"value": v.get("value", "").split(" ")[-1] if " " in v.get("value", "") else ""}
                     for v in all_dt_vals],
                    span_text,
                )
            if all_dt_vals and result["date"] is None:
                raw = all_dt_vals[0].get("value", "")
                if raw and " " in raw:
                    result["date"] = raw.split(" ")[0]

    # A RANGE date, when the span named no exact day. Which END of the range is
    # meant depends on the preposition: "by friday" is a DEADLINE and means the
    # last day, while "next week" means the soonest day in it — the same
    # instinct as the existing ruling that a weekly series starts on the
    # soonest weekday the sentence names.
    if not result["date"]:
        m_dur = _DURATION_AHEAD.search(span_text)
        if m_dur:
            raw = m_dur.group(1).lower()
            n = _NUMBER_WORD.get(raw) or (int(raw) if raw.isdigit() else None)
            resolved = _duration_ahead_to_date(n, m_dur.group(2), today) if n else None
            if resolved:
                result["date"] = resolved
                # Still a reading rather than a day the speaker named, so it is
                # confirmed like a range — "in two weeks" is not a date the way
                # "the 15th" is.
                result["_date_from_range"] = m_dur.group(0).strip()
                result["spans"].append((m_dur.start(), m_dur.end()))

    if not result["date"] and range_candidates:
        for c_start, c_end, r_from, r_to in range_candidates:
            phrase = span_text[c_start:c_end]
            deadline = re.search(r"\b(?:by|before|no later than)\s*$",
                                 span_text[:c_start], re.IGNORECASE) is not None
            picked = (r_to or r_from) if deadline else (r_from or r_to)
            if not picked:
                continue
            picked = str(picked)[:10]
            if picked < today.isoformat():
                continue                     # a past reading; try the next one
            result["date"] = picked
            result["_date_from_range"] = phrase.strip()
            result["spans"].append((c_start, c_end))
            break

    # Regex fallback for simple "today" / "tomorrow" if recognizer missed them
    if not result["date"]:
        result["_source"] = "regex_fallback"
        lower = span_text.lower()
        if re.search(r"\btoday\b", lower):
            result["date"] = today.isoformat()
        elif re.search(r"\btomorrow\b", lower):
            result["date"] = (today + datetime.timedelta(days=1)).isoformat()
        else:
            m_ord = _BARE_ORDINAL_DATE.search(span_text)
            if m_ord:
                resolved = _ordinal_to_date(int(m_ord.group(1)), today)
                if resolved:
                    result["date"] = resolved
                    # Block the span, or the date words land in the TITLE —
                    # the recogniser supplies these for every date it reads and
                    # this fallback has to do it itself.
                    result["spans"].append((m_ord.start(), m_ord.end()))

    # Regex fallback: "noon" → 12:00, "midnight" → 00:00, "now" → the clock.
    #
    # "now" belongs here with the other spoken time words. Without it, "create
    # an event NOW to go out for a run" carried no time at all and defaulted
    # to midnight — real usage, 2026-09-08, and the user got a run booked for
    # 12 AM. It is the same class of word as noon: a time the speaker gave in
    # words rather than digits.
    if not result["start_time"]:
        lower = span_text.lower()
        if re.search(r"\bnoon\b", lower):
            result["start_time"] = "12:00"
            result["_source"] = "regex_fallback"
        elif re.search(r"\bmidnight\b", lower):
            result["start_time"] = "00:00"
            result["_source"] = "regex_fallback"
        elif re.search(r"\b(?:right now|now|immediately|asap)\b", lower):
            result["start_time"] = datetime.datetime.now().strftime("%H:%M")
            result["_source"] = "regex_fallback"

    # Compact clocks (see `_COMPACT_AP_RE`): the recogniser reads none of them
    # whole. With a meridiem the form is unambiguous and OVERRIDES what the
    # recogniser made of its pieces — "at 9 10 am" came back as 09:00 from
    # "at 9" plus a stray "10 am" (Q42, 2026-09-22); the bare form still only
    # fills a clock nothing else read.
    for pat in (_COMPACT_AP_RE, _COMPACT_BARE_RE):
        if result["start_time"] and pat is _COMPACT_BARE_RE:
            break
        found = False
        for m in pat.finditer(span_text):
            h, mins = int(m.group(1)), int(m.group(2))
            ampm = (m.group(3) or "").lower()[:1] if pat is _COMPACT_AP_RE else ""
            if mins >= 60 or (ampm and not 1 <= h <= 12) or (not ampm and h > 23):
                continue
            if ampm == "p" and h < 12:
                h += 12
            elif ampm == "a" and h == 12:
                h = 0
            elif not ampm and 1 <= h <= 7:
                h += 12  # the same business-hours reading as "at 3" below
            result["start_time"] = f"{h:02d}:{mins:02d}"
            result["spans"].append((m.start(), m.end()))
            result["_source"] = "regex_fallback"
            found = True
            break
        if found:
            break

    # Regex fallback for bare time like "at 3" or "at 3pm" if recognizer missed
    if not result["start_time"]:
        result["_source"] = "regex_fallback"
        m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", span_text, re.IGNORECASE)
        if m:
            h = int(m.group(1))
            mins = m.group(2) or "00"
            ampm = (m.group(3) or "").lower()
            if ampm == "pm" and h < 12:
                h += 12
            elif not ampm and 1 <= h <= 7:
                h += 12  # business-hours heuristic
            result["start_time"] = f"{h:02d}:{mins}"

    # Regex fallback for "from X to Y" when recognizer misses ambiguous times
    if not result["start_time"] and not result["end_time"]:
        m = re.search(
            r"\bfrom\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+to\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
            span_text, re.IGNORECASE
        )
        if m:
            result["_source"] = "regex_fallback"
            sh, sm = int(m.group(1)), m.group(2) or "00"
            eh, em = int(m.group(4)), m.group(5) or "00"
            sampm = (m.group(3) or "").lower()
            eampm = (m.group(6) or "").lower()
            if eampm == "pm" and eh < 12:
                eh += 12
            if sampm == "pm" and sh < 12:
                sh += 12
            elif not sampm and sh < eh and eh >= 12:
                sh += 12  # infer PM from end marker
            elif not sampm and 1 <= sh <= 7:
                sh += 12  # business-hours heuristic
                # If we bumped start to PM, end should also be PM if it's < start
                if eh < sh:
                    eh += 12
            result["start_time"] = f"{sh:02d}:{sm}"
            result["end_time"] = f"{eh:02d}:{em}"

    # Fallback for "to HH" alone (update_event: "reschedule to 4pm")
    if result["start_time"] is None and result["end_time"] is None:
        m = re.search(r"\bto\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", span_text, re.IGNORECASE)
        if m:
            h = int(m.group(1))
            mins = m.group(2) or "00"
            ampm = (m.group(3) or "").lower()
            if ampm == "pm" and h < 12:
                h += 12
            elif not ampm and 1 <= h <= 7:
                h += 12
            # For update_event "to X" → new_start_time (not end_time)
            result["start_time"] = f"{h:02d}:{mins}"
            result["_source"] = "regex_fallback"

    # THE WINDOW IS THE LAST RESORT (see the loop above): only when nothing —
    # the recogniser or any fallback — has stated a clock does a daypart name
    # the time, and only then does it claim its words.
    if not result["start_time"] and daypart_candidates:
        span, start_v, end_v = daypart_candidates[0]
        if start_v:
            result["start_time"] = _normalize_time(start_v)
            if end_v and not result["end_time"]:
                result["end_time"] = _normalize_time(end_v)
            result["spans"].append(span)

    # An end time before the start means the range crossed noon without saying so
    # ("lunch from 12 to 1" → 12:00–01:00, a negative hour). Push the end into
    # the afternoon, unless it was explicitly stated as a morning time.
    if result["start_time"] and result["end_time"]:
        try:
            _sh, _sm = (int(x) for x in result["start_time"].split(":"))
            _eh, _em = (int(x) for x in result["end_time"].split(":"))
            _end_is_am = re.search(r"to\s+\d{1,2}(?::\d{2})?\s*a\.?\s?m\.?(?![a-z])",
                                   span_text, re.IGNORECASE)
            if (_eh * 60 + _em) <= (_sh * 60 + _sm) and _eh < 12 and not _end_is_am:
                result["end_time"] = f"{_eh + 12:02d}:{_em:02d}"
        except (ValueError, AttributeError):
            pass

    # Post-process: business-hours PM heuristic for recognizer-extracted times.
    # "2 o'clock", "3 o'clock" etc. without explicit AM context are almost
    # always afternoon in a calendar/meeting context — convert 1–7 to PM.
    if result["start_time"]:
        # "7am" has no word boundary between the digit and "am", and "a.m."
        # doesn't end on one either — so the old \b(am|a\.m\.)\b test missed both
        # and turned an explicitly stated 7am into 19:00. Match the meridiem
        # against the digit instead, and treat morning words as morning.
        _has_am = (
            re.search(r"\d\s*a\.?\s?m\.?(?![a-z])", span_text, re.IGNORECASE)
            or re.search(r"\b(morning|midnight|breakfast|shacharit|sunrise)\b",
                         span_text, re.IGNORECASE)
        )
        if not _has_am:
            try:
                _h, _m = result["start_time"].split(":")
                _h = int(_h)
                # 8 JOINS 1-7 (DEVQA Q28, 2026-09-20: a bare 7 or 8 is PM when
                # nobody can be asked). It stayed out, so "tomorrow at 8" was
                # booked 08:00 while the reply said "I read "8" as 8 PM", and
                # "quarter to nine" (8:45) came out AM beside a day word and PM
                # without one. "8 o'clock" keeps its morning — it reads AM on
                # both tracks, the ruling leaves it alone.
                if 1 <= _h <= 7 or (_h == 8 and not _EIGHT_OCLOCK.search(span_text)):
                    result["start_time"] = f"{_h + 12:02d}:{_m}"
            except (ValueError, AttributeError):
                pass

    if not _bound_pass:
        _values_from_the_resolver(result, span_text, today)
    return result


_ONLY_PART_OF_DAY = re.compile(
    r"(?:(?:on|for|in|to|by|until|till|at|around)\s+)?(?:this\s+|the\s+)?(?:tonight|morning|afternoon|evening|night|lunchtime)", re.I)

_PART_OF_DAY_WORD = re.compile(
    r"\b(?:tonight|morning|afternoon|evening|night|lunchtime|noon)\b", re.I)

#: How often the front door's OWN reading was the answer because the resolver
#: read nothing — the fallback Q53 leaves in place until that count says it can
#: go. Read by the readers board; never used to decide anything.
FALLBACK_READS = {"n": 0}


def _values_from_the_resolver(result: dict, span_text: str, today) -> None:
    """ONE READER FOR THE HALF OF THE DAY (DEVQA Q53, Gil 2026-09-25).

    Where this function and decompose_validate's resolver read the SAME clock
    and differ only by twelve hours, the resolver's half stands — the
    convention (Q28, a day word beside the clock, a meal word) now lives in
    one place, `resolve._bare_hour`, instead of two that drifted: two fixes
    had to be made here on 2026-09-25 that the deep reader already had.

    Narrowed on measurement. Handing the resolver all the values wholesale
    lost what this function handles and the resolver, given only the joined
    time words, does not: a range's clocks ("lunch from 12 to 1"), an ordinal
    POSITION ("the 2nd row"), an ordinal recurrence ("the 15th of every
    month") and a series bound ("until …") — 7 unit tests. Dates therefore
    stay this function's; unifying them is filed with that evidence."""
    st = result.get("start_time")
    if not st or result.get("end_time") and result["end_time"] < st:
        return
    from assistant.engine.decompose_validate import resolve as _R
    from assistant.engine.segmentation.fastseg.fastseg import find_time_refs
    refs = [r for r in find_time_refs(span_text) if r.kind == "clock"]
    if len(refs) != 1:
        FALLBACK_READS["n"] += 1
        return
    try:
        v = _R.resolve(refs[0].text + " " + span_text, today, span_text, action=span_text)
    except Exception:
        FALLBACK_READS["n"] += 1
        return
    got = v.get("start_time")
    if not got or got == st:
        return
    h1, m1 = (int(x) for x in st.split(":"))
    h2, m2 = (int(x) for x in got.split(":"))
    if m1 == m2 and h1 % 12 == h2 % 12:          # the same clock, the other half
        result["start_time"] = got
        if result.get("end_time"):
            eh, em = (int(x) for x in result["end_time"].split(":"))
            result["end_time"] = f"{(eh + (h2 - h1)) % 24:02d}:{em:02d}"






# ---------------------------------------------------------------------------
# Phase 3: Intent/domain routing
# ---------------------------------------------------------------------------


#: Q25 / Q15, shared with `fastseg.tag` — see `_route_intent`'s use below.
#: The speaker asking for the WHOLE day, in their own words — the one
#: thing that outranks a meal's own hour.
_ALL_DAY_RE = re.compile(r"\ball[- ]?day\b|\bwhole day\b|\bentire day\b", re.I)

#: "start a new list of dog breeds" — the frame, and what goes IN the list.
#: Anchored at the head so "add milk to the new list" (an item FOR a list)
#: is not read as making one.
from assistant.intent.coordination import ASK_JOINER_RE as _ASK_JOINER_RE

#: Verbs that name the ASKING rather than the doing. A title keeps what to
#: do, never how it was requested.
_REMINDER_VERBS = frozenset({"remind", "reminder", "notify", "alert"})

_NEW_LIST_RE = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?"
    r"(?:start|begin|create|make|set\s+up|open(?:\s+up)?|add)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?:new\s+|another\s+|fresh\s+)(?:to-?do\s+|task\s+)?list\b"
    r"(?P<body>.*)$", re.I)

_REMINDER_TASK_FRAME = re.compile(r"^\s*(?:please\s+)?remind me\s+to\b", re.I)
#: COMPACT CLOCKS — how the recogniser writes a spoken "nine ten" or "eight
#: thirty": "910am", "230PM", and after a clock preposition a bare "830" /
#: "1040". The same two patterns as `decompose_validate/resolve.py` so the two
#: tracks read the same digits the same way (real usage, 2026-09-22: "at 1040"
#: committed at 09:00 on the fast path, "for 830" at 20:00 on the deep one). A
#: meridiem makes it a clock anywhere; a bare one needs a clock preposition in
#: front and nothing noun-like after it — "for 200 people" is a count.
_COMPACT_AP_RE = re.compile(r"\b(\d{1,2}) ?(\d{2})\s*(am|pm|a\.m\.|p\.m\.)(?!\w)", re.I)   # "9 10 am" too (Q42)
_COMPACT_BARE_RE = re.compile(
    r"\b(?:at|for|from|until|till|by|around|about)\s+(\d{1,2})(\d{2})\b(?![:.]\d)"
    r"(?=\s*(?:$|[,.;!?]|(?:on|tomorrow|today|tonight|this|next|and|then|to|for|"
    r"with|in|at|the|execute|sharp|o'?clock|morning|afternoon|evening|night|"
    r"shacharit|shachris|mincha|maariv|arvit)\b))", re.I)
#: "THIS COMING thursday" is the soonest Thursday, like "this thursday". The
#: recogniser reads "coming" as "next" and lands a week late (real usage,
#: 2026-09-22: "this coming Sunday" said on a Wednesday became the Sunday
#: after next, ids 4 and 52).
_COMING_WEEKDAY_RE = re.compile(
    r"\b(?:this\s+)?coming\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
from assistant.common.wordlists import WEEKDAY_INDEX as _WEEKDAY_INDEX  # noqa: E402
_WEEKDAY_WORD_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
#: A DAY NAMED ON PURPOSE — "today", "tomorrow", "the 13th", "Sept 14" — as
#: opposed to a weekday, which speakers mis-say: three of Gil's real commands
#: carried both and the weekday was wrong every time ("tomorrow on tuesday"
#: said on a Wednesday, "monday the 13th" when the 13th was a Sunday, "the
#: 14th on tuesday" when the 14th was a Monday). When the two disagree the
#: stated day wins (cycle 36, 2026-09-22). This also keeps "book monday standup
#: tomorrow at 9am" on tomorrow, which the clock rule below used to carry alone.
_DELIBERATE_DAY_RE = re.compile(
    r"\b(?:today|tomorrow|tonight|the\s+\d{1,2}(?:st|nd|rd|th)|\d{1,2}(?:st|nd|rd|th)\s+of\s+\w+"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2})\b", re.I)

_STATED_CLOCK_RE = re.compile(
    r"\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)\b|\bat\s+\d{1,2}\b|\bnoon\b|\bmidnight\b"
    r"|\d{3,4}\s*(?:am|pm)\b|\bat\s+\d{3,4}\b"
    r"|\bo'?clock\b|\b(?:half|quarter)\s+(?:past|to)\b", re.I)

#: "change / move / push / set the due date of X to Y" — a to-do's due date
#: (2026-09-25). It had no phrasing at all: the router read an edit of a
#: calendar event called 'due date' (14 of 14 such TRAIN rows).
_DUE_DATE_OF = re.compile(
    r"^\s*(?:please\s+)?(?:change|move|push|update|set|shift|bump)\s+(?:the\s+)?"
    r"due\s+date\s+(?:of|for|on)\s+(?P<what>.+?)\s+to\s+", re.I)

_ROUTE_OVERRIDES = [
    (_DUE_DATE_OF, "update_todo"),
    (re.compile(r"^\s*(?:please\s+)?(?:add|put)\s+.+\s+(?:on|to)\s+(?:my|the)\s+(?:\w+\s+)?list\b"), "create_todo"),
    # F6a: an encounter being ARRANGED is an event — must outrank the
    # need-to→todo row below ("i need to talk to Quinn friday" was a todo).
    # "see my …" excluded: that's query-speak ("i need to see my lists").
    (re.compile(r"^\s*(?:please\s+)?(?:book|schedule)\s+(?!.*\b(?:off|from)\s+(?:my|the)\b)"),
     "create_event"),
    (re.compile(r"^\s*(?:please\s+)?(?:i\s+)?(?:need|want)\s+to\s+(?:talk|speak|"
                r"meet|catch\s+up|touch\s+base|sit\s+down|see\s+(?!my\b))"), "create_event"),
    # F6c: completion-speak routes by PHRASE — the inner title's own verbs
    # ("buy", "change") were hijacking verb-routing ("mark buy groceries as
    # done" → create_todo). Rewrites funnel done-with/already-did/check-off
    # into this shape; the override then routes them all.
    (re.compile(r"^\s*(?:please\s+)?mark\s+.+\s+as\s+done\b"), "complete_todo"),
    # F16b: "mark/label/note/put ‹something› on my calendar as ‹occasion›"
    # and "label ‹when› as ‹occasion›" — marking a DAY, i.e. creating a
    # calendar entry. Routed complete_todo/update_event/query_schedule
    # before (36% of all committed-but-wrong atomic rows). The done-forms
    # above are matched first, so completions are unaffected.
    (re.compile(r"^\s*(?:please\s+)?(?:mark|label|note|put)\s+.+"
                r"\bon\s+my\s+calendar\b(?:\s+(?:as|for)\b|\s*$)"), "create_event"),
    (re.compile(r"^\s*(?:please\s+)?(?:mark|label|note)\s+"
                r"(?:the\s+)?(?:\d{1,2}(?:st|nd|rd|th)?|today|tonight|tomorrow|"
                r"(?:next|this|coming)\s+\w+|\w+day|\w+\s+eve)\b.*\bas\b"
                r"(?!\s+(?:done|complete|completed|finished)\b)"), "create_event"),
    # F15: "call it X instead of Y" / "rename X to Y" is renaming, never a
    # create (14 rows committed create_todo at high confidence).
    (re.compile(r"^\s*(?:please\s+)?call\s+it\s+.+\s+instead\s+of\b"), "update_todo"),
    # F7b: "set X as high priority" is a fully-structured UPDATE — the verb
    # heuristics read it as a create ("set" → create at 1.00, the worst kind
    # of confident wrong).
    (re.compile(r"^\s*(?:please\s+)?(?:set|make)\s+.+\s+as\s+"
                r"(?:high|medium|low)\s+priority\b"), "update_todo"),
    # THE CLOCK TIME IS THE TELL — the same convention the pinned-reminder row
    # below already applies to "remind me", extended to the need-to family
    # because the gold says it holds there too. Gil reported this one from his
    # phone (2026-09-18): "I need to walk Val at 3pm" became a TASK, and the
    # kind board shows it is 4 out of 4 of that board's event-read-as-task
    # errors.
    #
    # Measured on the FastRule 7,200 atomic rows before writing it:
    #
    #     with a stated clock      30 rows  -> create_event   30/30, no exceptions
    #     with no clock           139 rows  -> 96 event / 43 todo   genuinely mixed
    #
    # So the clock decides and nothing else does — which is why this rule
    # requires one rather than routing the whole family. "remind me TO …" keeps
    # its own row below and stays a task even with a clock: that phrasing asks
    # for a REMINDER, while "I need to" states a commitment.
    (re.compile(r"^\s*(?:please\s+)?(?:i\s+)?(?:need|have|want|got)\s+to\s+.*"
                r"(?:\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\bat\s+\d{1,2}\b"
                r"|\b(?:noon|midnight)\b|\bo'?clock\b)"), "create_event"),
    (re.compile(r"^\s*(?:please\s+)?(?:i\s+)?(?:need|have|want|got)\s+to\s+"), "create_todo"),
    # The pinned reminder convention: the clock time is the tell, and this must
    # outrank the bare remind-me→todo row below.
    #
    # `(?!to\b)` USED TO SIT HERE, excluding "remind me TO ..." on Q15's
    # authority. Q26 (Gil, 2026-09-18) reversed that: "an event is something
    # that you put on the calendar, so reminding me to do something at a
    # specific time counts as an event." So "remind me to feed the cat at
    # 14:00" is an event now, and the 32 corpus rows that said otherwise were
    # relabelled in the same change. The task Gil also wants on the day is not
    # a second parse — `db.sync_calendar_to_todos` already makes it.
    (re.compile(r"^\s*(?:please\s+)?remind me\s+.*"
                r"(?:\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\bat\s+\d{1,2}\b"
                r"|\b(?:noon|midnight)\b)"), "create_event"),
    # The product convention the tagger already applies (`fastseg/kind.py`):
    # "remind me ABOUT / OF / WHEN / THAT <something>" is a calendar entry,
    # "remind me TO <verb>" is an errand unless clock-timed (the row above).
    # The fast path had one unconditional remind→todo row, so "remind me when
    # it is lunchtime" became a to-do and the two tracks disagreed (dev-100
    # checkpoint, 2026-09-20).
    (re.compile(r"^\s*(?:please\s+)?remind me\s+(?:about|of|when|that)\b"), "create_event"),
    (re.compile(r"^\s*(?:please\s+)?remind me\b"), "create_todo"),
    (re.compile(r"^\s*(?:please\s+)?add\s+(?:a\s+|\d+\s+|two\s+|three\s+)?(?:new\s+)?tasks?\b"), "create_todo"),
    # A NEW LIST is a create, never a query (Gil, 2026-09-20). The noun
    # "list" deliberately no longer routes on its own — that is what used to
    # commit `query_todos` for "begin new list of lottery numbers" — so the
    # frame is what routes these now, and the slot filling below titles the
    # to-do with what the list is OF.
    (_NEW_LIST_RE, "create_todo"),
    (re.compile(r"^\s*(?:what|which|show|list|read)\b.*\b(?:tasks?|todos?|to-dos?)\b"), "query_todos"),
    # F19: two very common spoken query shapes the router had no rule for
    (re.compile(r"^\s*do\s+i\s+have\b"), "query_schedule"),
    (re.compile(r"^\s*am\s+i\s+(?:free|busy|available)\b"), "query_schedule"),
]


def _route_intent(span, current_view: str) -> tuple[str | None, str, bool, bool]:
    """Route a span to an (action_name, domain, domain_inferred, domain_material) tuple.

    domain_inferred=True means we fell back to view context (lower confidence).
    domain_material=True means the *guessed* domain was actually load-bearing in
    picking the action (INTENT_MAP had a domain-specific entry for this verb, e.g.
    ("delete", "todo") vs ("delete", "calendar") give different actions). Verbs
    that map via the domain-agnostic (lemma, None) entry — "buy", "call", "email",
    etc. always mean create_todo regardless of domain — have domain_material=False,
    since the domain guess played no role in resolving them.
    """
    span_text = span.text.lower()
    span_words = set(re.findall(r"\w+", span_text))

    # --- Phrase-level overrides (checked before verb heuristics) ---
    for pat, action in _ROUTE_OVERRIDES:
        if pat.search(span_text):
            return action, ("todo" if "todo" in action else "calendar"), False, False

    # --- Domain detection ---
    has_calendar = bool(span_words & _CALENDAR_SIGNALS)
    has_todo = bool(span_words & _TODO_SIGNALS)

    if has_calendar and not has_todo:
        domain = "calendar"
        domain_inferred = False
    elif has_todo and not has_calendar:
        domain = "todo"
        domain_inferred = False
    elif has_todo and has_calendar:
        # Both signals: default to todo (most common conflict: "add task to calendar")
        domain = "todo"
        domain_inferred = True
    else:
        # No explicit signal: fall back to current_view
        domain = "todo" if current_view in ("todo", "tasks") else "calendar"
        domain_inferred = True

    # --- Find action verb and route to action ---
    # Strategy: collect all candidate verb tokens, try each until one maps to an action.
    # This handles cases where spaCy tags the action word as NOUN/ADJ/PROPN (e.g.
    # "schedule" as NOUN in "schedule meeting", "mark" as PROPN in "mark it done").
    #
    # Priority:
    #   1. ROOT verb/aux that maps to INTENT_MAP
    #   2. ROOT verb/aux (even if no direct map, use for WH fallback)
    #   3. Any VERB/AUX in span that maps to INTENT_MAP
    #   4. Any token (any POS) whose lemma maps to INTENT_MAP

    def _maps_to_action(lemma: str) -> tuple[str | None, bool]:
        """Returns (action_name, domain_was_material) — see docstring above."""
        # A verb Gil added in Settings routes like the built-in ones it sits
        # beside. Checked BEFORE `INTENT_MAP` only in the sense that it is
        # checked at all: without this the added word reached the extend/shorten
        # SLOT logic and never the router, so "squeeze the event ... to be 15
        # minutes" parsed as nothing at all. One list in one place is not enough
        # — which is the drift this whole feature exists to stop.
        if lemma in _extend_verbs() and lemma not in _EXTEND_VERBS:
            return "update_event", False
        domain_specific = INTENT_MAP.get((lemma, domain))
        if domain_specific:
            return domain_specific, True
        generic = INTENT_MAP.get((lemma, None))
        if generic:
            return generic, False
        return None, False

    # WH-word check first — "what/when/how many" sentences are queries regardless
    # of what other INTENT_MAP verbs appear in the span (e.g. "what's on my schedule")
    _WH_RE = re.compile(r"^(what|when|how\s+many|which|show|list|read)\b", re.IGNORECASE)
    if _WH_RE.search(span_text.strip()):
        wh_action = "query_schedule" if domain == "calendar" else "query_todos"
        return wh_action, domain, False, True  # WH-word is explicit, not inferred

    root_verb = None
    action = None
    domain_material = False

    # Pass 0: THE LEADING IMPERATIVE IS THE COMMAND. "mark WALK the dog
    # complete", "tick RETURN the library books off my list", "update FEED
    # the cat": the routing verb inside the object phrase is the thing's
    # NAME, and spaCy often makes it the ROOT while the real command sits
    # first as a mis-tagged noun that only pass 4 reaches. Measured the day
    # the errand verbs (walk, return, feed, …) joined this table: 18 wrong
    # commits, every one this shape. English puts the imperative first, so
    # the first word of the span — past a politeness opener — wins when it
    # maps. A leading time or subject ("tomorrow …", "i need to …") does
    # not map and falls through to the passes below, unchanged.
    for tok in span:
        if tok.lower_ in ("please", "can", "could", "you", "just", "also", "and", "then"):
            continue
        mapped, material = _maps_to_action(tok.lemma_)
        if mapped:
            root_verb = tok
            action = mapped
            domain_material = material
        break

    # Pass 1: ROOT verb that directly maps
    for tok in span:
        if action is not None:
            break
        if tok.dep_ == "ROOT" and tok.pos_ in ("VERB", "AUX"):
            mapped, material = _maps_to_action(tok.lemma_)
            if mapped:
                root_verb = tok
                action = mapped
                domain_material = material
                break

    # Pass 2: ROOT verb even without map (for WH-fallback path)
    if root_verb is None:
        for tok in span:
            if tok.dep_ == "ROOT" and tok.pos_ in ("VERB", "AUX"):
                root_verb = tok
                break

    # Pass 3: any VERB/AUX with map
    if action is None:
        for tok in span:
            if tok.pos_ in ("VERB", "AUX"):
                mapped, material = _maps_to_action(tok.lemma_)
                if mapped:
                    root_verb = tok
                    action = mapped
                    domain_material = material
                    break

    # Pass 4: any token with known action lemma (noun-verb ambiguity, ADJ mis-tags, etc.)
    if action is None:
        for tok in span:
            # A noun with its own determiner or adjective is an OBJECT, not a
            # mis-tagged command: "begin NEW LIST of lottery numbers", "open up
            # A LIST" routed query_todos through ("list", todo) — three of the
            # dev-100 checkpoint's fast-path misses committed a QUERY for a
            # create (2026-09-20). "schedule meeting" (no determiner) still
            # reaches this pass as the verb it is.
            if tok.pos_ in ("NOUN", "PROPN") and any(
                    c.dep_ in ("det", "amod", "poss", "nummod") for c in tok.children):
                continue
            mapped, material = _maps_to_action(tok.lemma_)
            if mapped:
                root_verb = tok
                action = mapped
                domain_material = material
                break

    # Pass 5: STT homophone fallback, ROOT position only. A preposition/adverb
    # can't legitimately be a well-formed sentence's syntactic ROOT — when spaCy
    # lands there, it's a signal the transcript is a fragment, usually because
    # Whisper misheard an imperative verb as its homophone (e.g. "buy" -> "by").
    # Restricted to ROOT to avoid false positives on legitimate uses elsewhere in
    # the sentence (e.g. "meeting by 3pm", where "by" is a prep, not the ROOT).
    if action is None:
        for tok in span:
            if tok.dep_ != "ROOT":
                continue
            alias = _STT_HOMOPHONE_VERBS.get(tok.lower_)
            if alias:
                mapped, material = _maps_to_action(alias)
                if mapped:
                    root_verb = tok
                    action = mapped
                    domain_material = material
            break  # only one ROOT per span

    if action is None:
        # No-verb fallbacks: WH-word query
        if re.match(r"\b(what|when|how many|which|show|list|read)\b", span_text):
            action_fallback = "query_schedule" if domain == "calendar" else "query_todos"
            return action_fallback, domain, domain_inferred, True
        # Q10 model tier (F11): where the rules found NOTHING, the two
        # logistic subsystems may compose an action — only when both margins
        # clear their floors, else the old skip stands. Model-routed =
        # inference, billed through the domain-inferred ×0.85 channel so the
        # front-door threshold still guards the commit.
        from assistant.intent import route_models as _rm
        guessed = _rm.route(span_text)
        if guessed:
            gdomain = "todo" if "todo" in guessed else "calendar"
            return guessed, gdomain, True, True
        return None, domain, domain_inferred, True

    # Q25, the same rule the SEGMENTER applies (`fastseg.tag`): a stated clock
    # means scheduled. Both tracks need it or they disagree about the same
    # sentence — which is exactly what happened when only the segmenter had it:
    # `fastseg` called "file the taxes every weekday at 3:45pm" an event while
    # this returned create_todo, and the product-shape board charged the
    # difference as 8 wrong commits.
    #
    # No reminder-frame exception (Q26) — see `fastseg.tag`, which carries the
    # same rule and must carry the same exceptions, which is exactly none.
    if action == "create_todo" and _STATED_CLOCK_RE.search(span_text):
        return "create_event", "calendar", True, domain_material

    return action, domain, domain_inferred, domain_material


# ---------------------------------------------------------------------------
# Phase 4: Slot filling
# ---------------------------------------------------------------------------


def _in_temporal(tok, temporal_spans: list[tuple[int, int]]) -> bool:
    return any(start <= tok.idx < end for start, end in temporal_spans)


_PRONOUN_TITLES = frozenset({"me", "i", "it", "you", "us", "them", "that", "this", "task", "tasks", "todo", "reminder", "list"})

_TODO_LEAD = re.compile(
    r"^\s*(?:(?:please|hey|ok|okay)[,\s]+)?"
    r"(?:remind me(?:\s+(?:tomorrow|today|tonight|later|on\s+\w+|next\s+\w+|this\s+\w+))?\s+(?:to|about|that)\s+"
    r"|add\s+(?:a\s+|the\s+|\d+\s+|two\s+|three\s+)?(?:new\s+)?tasks?\s*(?:to|:|-|—)?\s*(?:my\s+list\s*)?(?:to\s+)?"
    r"|(?:i\s+)?(?:need|have|want|got)\s+to\s+"
    r"|(?:add|put)\s+(?:to\s+(?:my|the)\s+(?:\w+\s+)?list\s*:?\s*)"
    r"|(?:make|create)\s+(?:a\s+)?(?:todo|task|reminder)\s+(?:to\s+|for\s+|:\s*)?"
    r"|(?:todo|task|reminder)\s*:\s*)",
    re.IGNORECASE,
)
_TODO_TRAIL = re.compile(
    r"\s+(?:on|to)\s+(?:my|the)\s+(?:\w+\s+)?list\s*$|\s+(?:due|by|for|on)\s+(?:tomorrow|today|tonight|next\s+\w+|this\s+\w+|\w+day|the\s+\d+\w*)\s*$",
    re.IGNORECASE,
)


def _todo_titles_from_text(text: str, temporal_spans, span) -> list[str]:
    """'remind me tomorrow to send the syllabus to Guri' → ['send the syllabus to Guri'];
    'add buy milk, eggs and bread to my list' → ['buy milk', 'buy eggs', 'buy bread'].

    The WHEN is blanked before anything else reads the sentence. This function
    took `temporal_spans` from the day it was written and never once looked at
    them — it stripped dates with two hand-written regexes instead, which only
    matched a date at the very END and only when a preposition introduced it.
    So every phrasing they missed carried the time into a task's NAME:

        "remind me to buy milk and bread tomorrow"  -> [..., 'buy bread tomorrow']
        "wash and fold the laundry the 30th"        -> [..., 'fold the laundry the 30th']
        "I need to walk Val at 3pm"                 -> ['walk val at 3pm']

    The last one is Gil's, reported from his phone on 2026-09-18, and it shows
    the second cost: the date resolved correctly AS WELL, so the task was both
    named after a time and due at it. The recogniser already found those spans
    — `_subtractive_title` blanks the same ones for events — so this is the
    reader that was skipped, not a rule that was missing.
    """
    text = _blank_spans(text, _grow_stranded(text, temporal_spans or []))
    t = text.strip().rstrip(".!?")
    m = _TODO_LEAD.match(t)
    if not m:
        # "put milk and bananas on the groceries list" / "add X to my list"
        m2 = re.match(r"^\s*(?:add|put)\s+(.+?)\s+(?:on|to)\s+(?:my|the)\s+(?:\w+\s+)?list\s*$", t, re.IGNORECASE)
        if not m2:
            return []
        body = m2.group(1)
    else:
        body = t[m.end():]
        body = _TODO_TRAIL.sub("", body)
    body = re.sub(r"\s+(?:due|by)\s+.*$", "", body, flags=re.IGNORECASE).strip(" ,;:")
    if not body:
        return []
    # Blanking leaves the preposition that introduced the date stranded
    # ("call mom at", "meeting on"), so each part is tidied the same way
    # `_subtractive_title` tidies its own.
    parts = [_tidy_part(p) for p in split_items(
        body, drop=_PRONOUN_TITLES, keep_together=_serial_verb_pairs(span))[:10]]
    return [p for p in parts if p]


# "put it on the groceries list" / "tag it as coursework" — the user naming a
# tag outright. Resolved against the real palette by CreateTodoAction; a word
# that isn't a tag is dropped there.
_TODO_TAG_PATTERNS = (
    re.compile(r"\b(?:on|to)\s+(?:my|the)\s+([\w-]+)\s+list\b", re.IGNORECASE),
    re.compile(r"\btag(?:ged)?\s+(?:it\s+)?(?:as|with)\s+([\w-]+)", re.IGNORECASE),
    re.compile(r"\bunder\s+([\w-]+)\s*$", re.IGNORECASE),
)
# List names, not tags.
_NOT_TAG_WORDS = frozenset({"today", "general", "todo", "to-do", "task", "tasks",
                            "my", "the", "this", "that", "shopping"})


def _todo_tags_from_text(text: str) -> list[str]:
    """Tag names the user said out loud, if any."""
    tags: list[str] = []
    for pattern in _TODO_TAG_PATTERNS:
        m = pattern.search(text)
        if m:
            word = m.group(1).strip().lower()
            if word and word not in _NOT_TAG_WORDS and word not in tags:
                tags.append(word)
    return tags


# ---------------------------------------------------------------------------
# THE SUBTRACTIVE TITLE (Gil approved the design change 2026-09-18)
#
# `_extract_title` below picks ONE noun chunk. That is why "set a meeting
# tomorrow at 2 o'clock meeting with omri for project" is titled "meeting": the
# first dobj chunk wins and everything naming the thing is discarded. On the
# corpus that reads title exactly-right 41.8% (n=1535) against
# right-OR-A-SUBSTRING 85.6% — 44 points of TRUNCATION. On real speech it is the
# largest failure class outright, 42% of 50 reviewed commands
# (DOCUMENTATION/experiments/real_usage/RESULTS.md).
#
# Subtractive instead: every reader that already claimed words gives them up —
# temporal spans, the cadence phrase, the series bound (blanked upstream), the
# destination, the stop keyword, the imperative shell — and the title is what is
# left. The same move the series-bound fix made for one phrase, applied on
# purpose.
# ---------------------------------------------------------------------------

#: The imperative shell. Stripped from the FRONT only: "book" frames in "book
#: the dentist" and is the object in "return the book", and position is the only
#: thing that tells them apart.
_FRAME_LEAD = re.compile(
    r"^(?:\s*(?:please|kindly|can you|could you|would you|i want to|i need to|"
    r"i'd like to|let's|lets|go ahead and|um|uh|ok|okay|alright|right)\b[,\s]*)*"
    # THE REMINDER FRAMES, widened 2026-09-20. "remind me to" and "remind me"
    # were the only two, so every other way of asking for one kept its frame
    # as the NAME: 'remind early that i have a teleconference', 'remind about
    # of all event in calenders', 'remind at this time', 'Send me a reminder
    # to pick up my dog from the groomer' — six of the fourteen junk titles
    # left on dev-100 (2026-09-20), each committed at confidence 0.95 or
    # better. Measured before writing: of the 7,200's 6,880 gold titles,
    # **none** begins with "remind" at all, so nothing legitimate is caught.
    # Longest first — the alternation is ordered, not sorted.
    # "add / make a note to …", "note to self," — a to-do frame; the title is
    # what follows it (2026-09-24: 'note to pay the electricity bill' kept the
    # frame as its title).
    r"(?:\s*(?:(?:add|make|leave|write|take|jot)\s+(?:a\s+|me\s+a\s+)?(?:quick\s+)?note\s+to|note\s+to\s+self,?)\s+)?"
    # THE CALENDAR-ENTRY SHELL (2026-09-25). "plan book club", "pencil in open
    # house", "squeeze in piano lesson", "block out back up the laptop",
    # "i'm free so book …", "label as moving day" — the verb that SAYS "put it
    # on the calendar" stayed on the front of the name. 142 of the 1,795
    # committed-create titles on the FastRule 7,200 TRAIN half began with one.
    r"(?:\s*(?:i'?m\s+free\s+(?:\w+\s+)?so\s+|"
    # "plan" only when no other frame verb follows it: stripping both made
    # "plan book club" 'club'.
    r"(?:plan(?!\s+(?:book|schedule|set|make|create|add|put|arrange)\b)|"
    r"pencil\s+(?:me\s+)?in|squeeze\s+in|"
    r"block\s+(?:out|off)(?:\s+(?:for|to))?|"
    r"block\s+(?:out\s+)?(?:my\s+)?(?:whole\s+)?(?:calendar|day)\s+(?:for|to)|"
    r"(?:mark(?!['\u2019]s)|label|note)(?!\s+(?:book|schedule|set|make|create|add|put|arrange)\b)"
    r"(?:\s+(?:it\s+)?(?:down\s+)?as)?)\s+))?"
    r"(?:\s*(?:(?:send|give)\s+me\s+(?:an?\s+)?(?:reminder|alert)\s+"
    r"(?:to|about|of|for|that)|"
    r"set\s+(?:an?\s+)?(?:reminder|alert)\s+(?:to|about|of|for|that)|"
    r"remind\s+me\s+(?:to|about|of|when|that)|remind\s+me|remind|"
    r"set|create|make|add|book|schedule|put|arrange|organise|organize|"
    r"start|get|have)\b\s*)?"
    r"(?:\s*(?:up|an|a|the|my|me|for me|for us)\b\s*)*"
    # "create an EVENT FOR staff meeting", "book an APPOINTMENT FOR flu shot":
    # the entry word is only scaffolding when "for" names the thing after it —
    # "schedule a meeting with Harper" keeps its "meeting".
    r"(?:(?:event|appointment|apointment|entry)\s+for\s+(?:the\s+|my\s+|a\s+)?)?",
    re.IGNORECASE)

#: The framing verb is not always at the FRONT. "next week on monday on the 13th
#: create event to ta class" put it in the middle, and an anchored pattern left
#: it in the title — "create event to ta class", against a row Gil had approved
#: as "TA Class". Only the verb+entry-word pair is safe to remove anywhere:
#: a bare "set"/"add" mid-sentence is often content ("add milk").
_FRAME_ANYWHERE = re.compile(
    r"\b(?:set|create|make|add|book|schedule|put|arrange)\s+"
    r"(?:up\s+)?(?:an?|the|my)?\s*"
    r"(?:event|meeting|appointment|reminder|task|todo|entry)s?\b",
    re.IGNORECASE)

#: A subtractive title longer than this has not understood the sentence — it has
#: copied it. id=145 produced twelve words of rambling transcript where the old
#: reader produced one wrong word; both are wrong, and the long one is worse to
#: look at on a lock screen. Over the cap, the chunk-based reader is used instead.
#: Eight is a judgement, not a measurement: the longest sensible real title seen
#: in the corpus gold is six words.
_TITLE_MAX_WORDS = 8

_FRAME_TAIL = re.compile(
    r"(?:\s*[,.]?\s*\b(?:execute|thanks|thank you|please|"
    # TAILS THAT ARE NOT THE NAME (2026-09-25), each a residue the FastRule
    # 7,200 TRAIN half left on committed titles: a sign-off ("ok"), a hedge
    # ("or so"), a standing qualifier ("until further notice", "no
    # exceptions", "except when i'm busy"), the lead-time ask with its time
    # already taken ("notify me before"), and the leftovers of a recurrence or
    # a recurrence whose phrase was read ("starting", "twice") or of a joiner
    # ("plus"). Not a bare "before": "…, remind me a week before" leaves a
    # second to-do titled 'before', and blanking it turned 6 committed rows
    # into deferrals — that junk item is its own defect, filed.
    r"ok|okay|or so|until further notice|no exceptions|except when i'?m busy|"
    r"(?:notify|ping|alert|buzz)\s+me\s+before(?:hand)?|"
    r"starting|twice|plus)\b\s*[.!]?\s*)+$",
    re.IGNORECASE)
_DESTINATION = re.compile(
    r"\s*\b(?:on|to|in|onto|into)\s+(?:my|the)\s+"
    # "calender" and "to-do list" too: 'training session to my calender' and
    # 'feed the cat to my to-do' (2026-09-25).
    r"(?:calendar|calender|schedule|(?:to-?\s?do\s+)?list|to-?\s?dos?|todos?|tasks?|agenda|diary)\b",
    re.IGNORECASE)

#: The generic word for an entry. Kept when it is all that was said ("Add an
#: event for 5 p.m."), and it takes a qualifier rather than losing to one.
_GENERIC_ENTRY = re.compile(
    r"^(?:an?|the|my|this)?\s*"
    r"(?:reminder|alert|event|appointment|meeting|task|todo|thing|item|"
    r"entry|session)s?$", re.IGNORECASE)

#: A surviving phrase that QUALIFIES the one before it instead of replacing it.
#: `at`/`in`/`on` belong here — "Movie" + "at the Lincoln AMC" is one title, and
#: treating that `at` as stranded produced "Movie the Lincoln AMC Theatre".
_TITLE_QUALIFIER = re.compile(
    r"^(?:with|for|about|regarding|re|at|in|on)\b", re.IGNORECASE)

#: A part that is ONLY function words — what a blanked phrase leaves behind
#: ("on" from "on tuesday"). Dropped whole. That is what distinguishes it from a
#: preposition whose object SURVIVED and which therefore still means something.
_ONLY_FUNCTION = re.compile(
    r"^(?:at|on|in|for|to|from|by|of|with|and|the|a|an|my|me|is|it|"
    r"until|till|through|that|this)(?:\s+(?:at|on|in|for|to|from|by|of|with|"
    r"and|the|a|an|my|me|is|it|until|till|through|that|this))*$", re.IGNORECASE)

_INFINITIVE_LEAD = re.compile(r"^to\s+(?=\w)", re.IGNORECASE)
_STRANDED_TAIL = re.compile(
    r"\s*\b(?:at|on|in|for|to|from|by|of|with|and|the|a|an|until|till|through)$",
    re.IGNORECASE)
_FOR_ME = re.compile(r"\bfor\s+(?:me|us)\b", re.IGNORECASE)

#: A trailing SOURCE phrase — "buy milk FROM THE STORE AND THE MARKET". Where the
#: thing came from is not part of its name, and sweeping it in is a defect
#: `test_todo_item_splitting` was written for. Deliberately only `from`: `at` is a
#: VENUE and belongs in the title ("Movie at the Lincoln AMC Theatre").
_SOURCE_TAIL = re.compile(
    r"\s+\bfrom\s+(?:the\s+|my\s+|a\s+|an\s+)?\w+"
    r"(?:\s+and\s+(?:the\s+|my\s+|a\s+)?\w+)*\s*$", re.IGNORECASE)


#: The preposition that INTRODUCED a time phrase, which the recogniser's span
#: leaves behind. `_extract_temporal("at 6pm remind me …")` returns (3,6) —
#: "6pm" — so blanking gives "at␣␣␣␣␣remind me …" and the stranded "at " sits
#: at position 0, where `_FRAME_LEAD` and `_TODO_LEAD` are anchored. Both then
#: fail to strip the lead-in and the whole frame becomes the title.
#:
#: `to` is deliberately ABSENT. "to Y" is the extend branch's NEW END TIME
#: ("extend standup to 3pm"), and growing over it would eat the thing that
#: branch reads.
#:
#: `due` is absent too, for a different reason: it is a predicate, not a date
#: preposition — "remind me when my car is due" is not a stranded head.
_HEAD_LEADIN = re.compile(
    r"(?:\b(?:at|on|in|by|from|until|till|through|starting|beginning)\s+)+$",
    re.IGNORECASE)

#: The comma after a FRONTED adverbial: "tomorrow, remind me to …".
_HEAD_COMMA = re.compile(r"^[\s]*[,;][\s,;]*")


def _grow_stranded(text: str, spans) -> list:
    r"""Widen each temporal span over the preposition that introduced it.

    `_tidy_part` already right-trims what blanking strands off the TAIL, and
    says "Only the end" deliberately. This is the head, and nothing did it.

    THE COMMA IS GROWN ONLY AT POSITION 0, which is not fussiness — it is the
    whole difference between a fix and a regression. `split_items` splits on
    COMMAS ONLY (`re.split(r"\s*[,;]\s*", body)`), never on a whitespace run,
    so blanking a comma anywhere else silently MERGES list items: measured, 28
    rows changed and 27 of them LOST an item, the dominant shape being a
    `mixed` row where the comma is the only boundary between the task and the
    event. Gated on position 0 that becomes 1 row changed and 0 losing, and
    every win survives — because a fronted adverbial's comma is the only comma
    that is a boundary rather than a delimiter.
    """
    out = []
    for a, b in spans or []:
        m = _HEAD_LEADIN.search(text[:a])
        start = m.start() if m else a
        end = b
        if start == 0:
            t = _HEAD_COMMA.match(text[b:])
            if t:
                end = b + len(t.group(0).rstrip())
        out.append((start, end))
    return out


def _blank_spans(text: str, spans) -> str:
    """Replace each (start, end) with spaces — equal length, so every later
    offset stays valid for the callers that index into this text."""
    chars = list(text)
    for a, b in spans:
        for i in range(max(0, a), min(len(chars), b)):
            chars[i] = " "
    return "".join(chars)


def _tidy_part(text: str) -> str:
    """Drop a part that is only function words; strip stranded ones off the END.

    Only the end. A leading preposition whose object survived still means
    something ("at the Lincoln AMC"); a trailing one lost its object to the
    blanking and says nothing ("meeting with ora at").
    """
    out = _FOR_ME.sub(" ", text)
    out = re.sub(r"\s+", " ", out).strip(" ,.;:-")
    if not out or _ONLY_FUNCTION.match(out):
        return ""
    out = _INFINITIVE_LEAD.sub("", out).strip(" ,.;:-")
    for _ in range(4):
        before = out
        out = _STRANDED_TAIL.sub("", out).strip(" ,.;:-")
        if out == before:
            break
    return "" if _ONLY_FUNCTION.match(out) else out


#: A TITLE HAS TO NAME SOMETHING. What survives subtraction is sometimes only
#: the scaffolding — "Remind me at this time." leaves 'at this time', "i need
#: to set reminder on 15th march" leaves 'set reminder', "pls add list of
#: things to buy" leaves 'things' — and each of those was committed as a
#: to-do at 0.95 confidence or better (dev-100, 2026-09-20).
#:
#: The test: at least one word that is not scaffolding. Function words are
#: not names, time words are not names, the program's own nouns are not names
#: (that is the same judgement `Gatekeeper._GENERIC_TARGET_RE` makes about a
#: whole title, applied word by word), and neither is a command verb.
#:
#: MEASURED BEFORE WRITING, on the 7,200's gold: of **3,944 CREATE titles it
#: refuses 0**. The 179 it would refuse are all mutation match-titles ("that
#: appointment", "my list", "it"), which a create never produces and this
#: path never sees — `_extract_title` only takes the subtractive route for
#: `create_event` and `create_todo`.
_NOT_A_NAME_FUNCTION = frozenset(
    "a an the this that these those my your our his her its their and or but "
    "then also plus to for of on at in with by from off out up about as is "
    "are was were be been am do does did i me you we us them it he she they "
    "there here what which when how please kindly just so um uh ok okay "
    # quantifiers and bare modifiers: "REMIND ABOUT OF ALL EVENT IN CALENDERS"
    # kept 'all' as its name. A real title survives them on its own words —
    # "all hands meeting" still has hands and meeting.
    "all some any every each other another new more few several "
    # "open" and "close" act on a surface, not on a thing to be named: 'open
    # calendar' is not an entry's name. "open house" keeps its own name on
    # 'house', and 0 of the 3,944 create gold titles are refused by either.
    "open close".split())
_NOT_A_NAME_TIME = frozenset(
    "time day days week weeks month months year years morning afternoon "
    "evening night today tomorrow tonight yesterday now later soon early "
    "earlier late am pm oclock noon midnight hour hours minute minutes second "
    "seconds monday tuesday wednesday thursday friday saturday sunday weekend "
    "weekday january february march april may june july august september "
    "october november december".split())
_NOT_A_NAME_PROGRAM = frozenset(
    "event events reminder reminders alert alerts appointment appointments "
    "task tasks todo todos list lists calendar calender calendars calenders "
    "schedule diary agenda entry item items thing things note notes "
    # the recurrence words: "Set a calendar event to repeat yearly on this
    # date" kept 'repeat' as its name.
    "repeat repeats repeating repeated recurring recurrence daily weekly "
    "monthly yearly annually nightly".split())


#: Q42 (Gil, 2026-09-22): a bare KIND word — the whole title once its article
#: is off — IS a name: "appointment", "an event", "the date" commit with their
#: day and clock, and the phone shows the hint once ("say what it's about").
#: Gil's own review on "Add an event for 5 p.m." had kept 'event' as the
#: title. "this event" (an anaphor) and "set reminder" (a frame) still name
#: nothing, and the program's furniture — list, note, calendar, agenda, item,
#: thing — never does: those are what Q38 was ruled on.
_BARE_KIND = frozenset(
    "event events appointment appointments reminder reminders alert alerts "
    "task tasks todo todos date dates meeting meetings call calls".split())
_BARE_ARTICLE = frozenset("a an the my our your".split())

#: A determiner and "one" is a PRONOUN, not a name (cycle 44, 2026-09-22):
#: "that one", "this one", "the last one". Q38 refuses a title that names
#: nothing EVERYWHERE, and this shape passed both gates — "one" is in no
#: list — so the judge's loop could commit `delete_event "that one"` after the
#: front door's accidental refusal fell away. The judge's `_GENERIC_TARGET_RE`
#: carries the same arm; "one on one" and "capital one" are untouched.
_PRONOUN_ONE_RE = re.compile(
    r"^(?:the |this |that |these |those |my |your )?"
    r"(?:last |first |next |previous |other |same |new |second )?ones?$", re.I)


def names_something(title: str, bare_kind_is_a_name: bool = True) -> bool:
    """Is any word of this title a NAME rather than scaffolding?

    `bare_kind_is_a_name=False` asks the pre-Q42 question — does the text name
    anything BEYOND a kind of thing — which is what the judge asks of the
    transcript when a title is only the kind: "create an event to go for a
    run" names a run, and 'event' is then a dropped subject, not a bare one."""
    # A QUESTION IS NOT A NAME — but only when the question mark is the
    # TITLE'S, not the transcript's. "Can you create a new list in my
    # podcast?" carries the sentence's mark into the title, and refusing it
    # cost a polite imperative that had always committed (caught by
    # `test_f4a_polite_imperative_is_not_a_question`, 2026-09-20). A mark
    # with a space before it is the parse's own leftover: 'date ?'.
    if re.search(r"\s[?]\s*$", title or ""):
        return False
    if _PRONOUN_ONE_RE.match((title or "").strip()):
        return False                                  # "that one" — a pronoun
    words = [w for w in re.findall(r"[a-z0-9']+", (title or "").lower())
             if len(w) > 1]
    if (bare_kind_is_a_name and words and words[-1] in _BARE_KIND
            and all(w in _BARE_ARTICLE for w in words[:-1])):
        return True                                   # Q42: a bare kind commits
    return any(w not in _NOT_A_NAME_FUNCTION and w not in _NOT_A_NAME_TIME
               and w not in _NOT_A_NAME_PROGRAM and not w.isdigit()
               and not any(w == verb for verb, _ in INTENT_MAP)
               for w in words)


_NAMES_ANOTHER_DAY_RE = re.compile(
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|\btomorrow\b|\bnext\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b|\bin (?:a|an|one|two|three|four|five|six|\d+) "
    r"(?:days?|weeks?|months?)\b", re.I)

#: Imperatives spaCy sometimes tags as nouns at the head of a short sentence.
_BARE_LEAD_VERBS = frozenset(
    "take do go get call pick walk clean pay buy cook wash finish send email "
    "text check make fix bring drop order return renew print water feed".split())


def _bare_noun_event(span, temporal: dict) -> bool:
    """Does this span OPEN with a noun and name a day or a clock? — the shape
    `analyze` routes to create_event when no verb mapped. A question, a
    pronoun or a leading verb never qualifies; the words left once the time is
    taken must name something (Q38's gate)."""
    if not (temporal.get("date") or temporal.get("start_time")):
        return False
    text = span.text.strip()
    if not text or "?" in text:
        return False
    toks = [t for t in span if not t.is_punct and t.lower_ not in
            ("um", "uh", "so", "ok", "okay", "hey", "please", "just", "the", "a", "an", "my", "our")]
    if not toks or toks[0].pos_ not in ("NOUN", "PROPN", "ADJ"):
        return False
    # NO VERB ANYWHERE. A verb the router could not map ("vet appointment
    # TAKES all day", "take the medicine at 9" when spaCy tags the imperative
    # as a noun) is a sentence this rule cannot title honestly — it kept
    # "takes" in the title — so the model keeps it.
    if any(t.pos_ in ("VERB", "AUX") or t.tag_ in ("VB", "VBP", "VBZ", "VBD")
           for t in span if not t.is_punct):
        return False
    if toks[0].lemma_.lower() in _BARE_LEAD_VERBS:
        return False
    # A MISHEARD COMMAND VERB is not a noun: "shedule physical therapy for next
    # tuesday" titled itself 'shedule physical therapy'. A lead word one slip
    # from a verb the router knows goes to the model, which reads the verb.
    import difflib
    if difflib.get_close_matches(toks[0].lower_, _IMPERATIVE_VERB_LEMMAS, n=1, cutoff=0.8):
        return False
    # THE WORDS NAME A DAY BUT THE READING LANDED ON TODAY — the recogniser
    # lost the day, as it does after a clock range: "birthday dinner from 6 to
    # 8 next monday", "blood test from 3 to 4pm march 5th" both came back as
    # today. The model reads those right; this rule does not guess.
    from assistant.intent import recurrence as _recur
    if (not _recur.detect(text)          # a series takes its start from the cadence
            and temporal.get("date") in (None, "", datetime.date.today().isoformat())
            and _NAMES_ANOTHER_DAY_RE.search(text)
            and not re.search(r"\b(?:today|tonight|this (?:morning|afternoon|evening))\b", text, re.I)):
        return False
    if toks[0].lower_ in ("what", "when", "which", "who", "where", "how", "it", "this", "that"):
        return False
    title = _subtractive_title(text, temporal.get("spans"))
    # TIME RESIDUE IN THE TITLE means the time words were not all read —
    # "open house between 5 and 6:30 at the end of the month" left "open house
    # between 5" and a wrong clock. Then the reading is not trusted and the
    # model keeps the sentence.
    if re.search(r"\d|\b(?:between|from|until|till|at|on|in|by|before|after|around|to)\b",
                 title or "", re.I):
        return False
    return bool(title) and names_something(title)


def _subtractive_title(span_text: str, temporal_spans) -> str:
    """The title as what REMAINS once every other reader has taken its words."""
    spans = list(temporal_spans or [])
    from assistant.intent import recurrence as _recur
    rec = _recur.detect(span_text)
    if rec.cadence and rec.span:
        spans.append(rec.span)

    # The temporal spans are grown LOCALLY here and in `_todo_titles_from_text`,
    # never on `temporal["spans"]` itself: `_fill_slots` hands those to
    # `_in_temporal` for token membership and to `_extract_title`'s chunk
    # fallbacks, and widening them there would shift offsets those readers
    # depend on. Local growth is an implementation fix; a wider span in the
    # shared dict would be a contract change.
    text = _blank_spans(span_text, _grow_stranded(span_text, spans))
    # A POSSESSIVE BELONGS TO ITS TIME WORD. Blanking "today" out of "add
    # grocery shopping to TODAY'S to-do list" leaves the "'s" behind, and the
    # title came out "grocery shopping 's to-do list" — two of the eight junk
    # titles left after cycle 32 were exactly this. Only a possessive stranded
    # against a blank gap or the start; "john's list" keeps its own.
    text = re.sub(r"(^|\s{2,})\s*'s\b", r"\1", text)
    text = _DESTINATION.sub(" ", text)
    text = _FRAME_TAIL.sub("", text)
    # MID-STRING ONLY. At position 0 this is `_FRAME_LEAD`'s job, and it
    # deliberately keeps the entry word so "schedule a meeting with Harper"
    # stays "meeting with Harper". Letting this pattern fire there instead
    # removed the head and left "with Harper" — 1.6 pt of corpus title
    # exactness, measured.
    text = re.sub(
        _FRAME_ANYWHERE,
        lambda m: m.group(0) if m.start() == 0 else "  ",
        text)
    text = _FRAME_LEAD.sub("", text, count=1)

    # Two or more blanked characters is a real gap, so the pieces either side
    # are separate things rather than one phrase.
    parts = [_tidy_part(p) for p in re.split(r"\s{2,}|[,;]", text)]
    parts = [p for p in parts if p]
    if not parts:
        return ""

    head, rest = parts[0], parts[1:]
    quals = [p for p in rest if _TITLE_QUALIFIER.match(p)]
    things = [p for p in rest if not _TITLE_QUALIFIER.match(p)]
    if _GENERIC_ENTRY.match(head) and things:
        out = " ".join(things + quals)          # "event" loses to "movie at X"
    else:
        out = " ".join([head] + things + quals)  # "meeting" keeps "with etai"
    out = _SOURCE_TAIL.sub("", _tidy_part(out))
    if not names_something(out):
        # Only scaffolding survived, so there is no name here. Empty sends the
        # caller to its missing-slots / generic-title refusal, which is the
        # honest answer — better than a to-do called 'at this time'.
        return ""
    # "for for causal infant projects" — a doubled function word is the mark of
    # two fragments joined at a blank, not of anything the speaker said.
    out = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", out, flags=re.IGNORECASE)
    if len(out.split()) > _TITLE_MAX_WORDS:
        return ""                                # hand back to the chunk reader
    return out


def _extract_title(span, temporal_spans: list[tuple[int, int]],
                   *, subtractive: bool = True) -> str | None:
    """Extract the best title from a span, blocking temporal token positions.

    SUBTRACTIVE FIRST (2026-09-18): what survives once every other reader has
    taken its words. The noun-chunk priorities below are the fallback for when
    subtraction leaves nothing at all — they were the whole method until now,
    and they are why a title truncated to "meeting".

    **`subtractive=False` for a target-taking operation, and the difference is
    destructive.** This same function supplies `match_title`, which is a NEEDLE
    for finding a record that already exists — and a richer phrase is a worse
    needle. Turned on for updates and deletes, the corpus board's `update_todo`
    destructive errors went from 1 to 27 in one run. Naming a new thing wants
    every word the speaker said; finding an old one wants the few that identify
    it.
    """
    if subtractive:
        chosen = _subtractive_title(span.text, temporal_spans)
        if chosen:
            return chosen

    # Priority 1: noun chunk containing dobj of root verb
    dobj_chunks = [
        chunk for chunk in span.noun_chunks
        if chunk.root.dep_ == "dobj"
        and not any(_in_temporal(t, temporal_spans) for t in chunk)
    ]
    for c in dobj_chunks:
        t = _clean_title(c.text)
        if t:
            return t

    # Priority 2: noun chunk containing pobj (object of preposition)
    pobj_chunks = [
        chunk for chunk in span.noun_chunks
        if chunk.root.dep_ == "pobj"
        and not any(_in_temporal(t, temporal_spans) for t in chunk)
    ]
    for c in pobj_chunks:
        t = _clean_title(c.text)
        if t:
            return t

    # Priority 3: any noun chunk not in temporal zone, closest to root
    root_tok = next((tok for tok in span if tok.dep_ == "ROOT"), span[0])
    candidates = [
        chunk for chunk in span.noun_chunks
        if not any(_in_temporal(t, temporal_spans) for t in chunk)
    ]
    if candidates:
        closest = min(candidates, key=lambda c: abs(c.root.i - root_tok.i))
        return _clean_title(closest.text)

    return None


def _dobj_conjunct_title(span, temporal_spans: list[tuple[int, int]]) -> "str | None":
    """The FULL coordinated object list, not just the first — "buy X, Y, and
    Z" keeps every one (DEVQA Q14 reversed, 2026-09-16: a shared verb over a
    bare, coordinated object list is ONE segmentation item, so its title
    must not silently drop everything after the first object).

    `_extract_title`'s Priority-1 branch returns on the FIRST `dobj` chunk
    it finds — correct for a single-object command, wrong for a
    coordinated one, and it was found live: "buy eight sticky notes,
    apples, and printer paper" saved as a task titled "sticky notes ×8",
    apples and printer paper silently gone (TASKS.md, 2026-09-16).

    spaCy attaches a coordinated object's conjunct EITHER to the object noun
    ("buy eight sticky notes, APPLES, and printer PAPER" — apples/paper
    both `conj` of `notes`) OR to the ROOT VERB directly ("call the dentist
    and the VET" — vet is `conj` of `call`, not of `dentist`) — both are
    real spaCy outputs for genuinely coordinated objects, unpredictably
    which one a given sentence gets, so both are walked.

    The verb-attachment case needs ONE guard the noun-attachment case does
    not: a coordinated PREPOSITIONAL OBJECT can ALSO surface as `conj` of
    the root verb ("buy milk FROM THE STORE and the MARKET" — market is
    `conj` of `buy`, not of `store`, even though it coordinates with
    "store", not with "milk"). A `prep` child of the root verb sitting
    BETWEEN the dobj and the candidate conjunct means the candidate belongs
    to that prepositional phrase's own coordination, not the object's — the
    guard this function checks for specifically, found by exactly this case
    over-including "from the store and the market" in a task title before
    it was added.
    """
    dobj_chunks = [
        chunk for chunk in span.noun_chunks
        if chunk.root.dep_ == "dobj"
        and not any(_in_temporal(t, temporal_spans) for t in chunk)
    ]
    if not dobj_chunks:
        return None
    dobj = dobj_chunks[0]
    root_verb = next((tok for tok in span if tok.dep_ == "ROOT"), dobj.root.head)
    preps = [tok.i for tok in root_verb.children if tok.dep_ == "prep"]

    frontier = [dobj.root, root_verb]
    seen = {dobj.root.i, root_verb.i}
    conj_roots: set = set()
    while frontier:
        tok = frontier.pop()
        for child in tok.children:
            if (child.dep_ == "conj" and child.i not in seen
                    and child.pos_ in ("NOUN", "PROPN")
                    and not any(dobj.root.i < p < child.i for p in preps)):
                seen.add(child.i)
                conj_roots.add(child.i)
                frontier.append(child)
    if not conj_roots:
        return None                      # nothing coordinated — no widening needed

    chunks = [dobj] + [c for c in span.noun_chunks
                       if c.root.i in conj_roots
                       and not any(_in_temporal(t, temporal_spans) for t in c)]
    chunks.sort(key=lambda c: c.start)
    first, last = chunks[0], chunks[-1]
    # Sliced from the ORIGINAL text rather than rebuilt from the chunks, so
    # the speaker's own commas and "and" survive verbatim — "eight sticky
    # notes, apples, and printer paper" stays exactly that.
    return _clean_title(span.doc[first.start:last.end].text)


# Action verb lemmas that spaCy sometimes drags into noun chunks as compound modifiers
_TITLE_STRIP_VERBS = frozenset({
    "schedule", "book", "plan", "cancel", "delete", "add", "create",
    "remind", "buy", "call", "email", "text", "pick", "get", "write",
    "send", "order", "pay", "fix", "clean", "wash", "cook", "prepare",
    "move", "reschedule", "postpone", "push", "update", "rename",
    "mark", "check", "complete", "finish", "remove", "clear", "drop",
    "show", "list", "read", "summarize",
})


def _clean_title(text: str) -> str:
    """Strip leading determiners, possessives, and action verb compounds."""
    text = re.sub(r"^(my|the|a|an|our|your)\s+", "", text, flags=re.IGNORECASE).strip()
    # Strip leading word if it's a known action verb (compound mis-tag)
    words = text.split()
    while words and words[0].lower() in _TITLE_STRIP_VERBS:
        words = words[1:]
    text = " ".join(words)          # may be empty when the chunk was only a verb ("book")
    text = re.sub(r"\s+", " ", text)
    return text


#: Every verb the router keys on, as a bare word.
_ROUTING_VERBS = frozenset(v for v, _d in INTENT_MAP)


def _fill_slots(span, action_name: str, temporal: dict, current_view: str) -> dict:
    """Fill action-specific slots from the span and temporal extraction."""
    temporal_spans = temporal.get("spans", [])
    slots: dict = {}

    # Only a CREATE is naming something new; everything else is looking for a
    # record that already exists (see `_extract_title`).
    title = _extract_title(span, temporal_spans,
                           subtractive=action_name in ("create_event", "create_todo"))

    if action_name == "create_event":
        if title:
            slots["title"] = title
        # F17: recurrence is a SLOT of this one atomic item — db.create_event
        # expands the series itself. Filling it also supplies the anchor DATE
        # ("every monday" starts on the soonest Monday, the project's rule),
        # which is why recurring rows used to defer as "missing date".
        from assistant.intent import recurrence as _recur
        _rec = _recur.detect(span.text)
        if _rec:
            slots["recurrence"] = _rec.cadence
            if _rec.days:
                # "every tuesday and thursday": one weekly series on BOTH days
                # (`db._next_date` steps between the named days).
                slots["recur_days"] = list(_rec.days)
            if _rec.rounded_from:
                slots["recurrence_rounded_from"] = _rec.rounded_from
            if not temporal.get("date"):
                slots["date"] = _rec.start_date(datetime.date.today()).isoformat()
            # Where the series STOPS. `db.create_event` has honoured
            # `recur_until` since it was written and NOTHING in this parser ever
            # set it, so "every monday until the end of the month" became an
            # UNBOUNDED weekly series — 81 rows of the FastRule train half
            # created a series that fires forever where the speaker named an end.
            # Only on a recurrence: a bound with nothing to bound is meaningless.
            if temporal.get("recur_until"):
                slots["recur_until"] = temporal["recur_until"]
        if temporal.get("date"):
            slots["date"] = temporal["date"]
        if action_name == "create_event" and _rec and _rec.days and slots.get("date"):
            # "every tuesday and thursday": the recogniser reads ONE of the
            # listed weekdays (the last) as the date, which started the series
            # on Thursday and skipped the Tuesday before it. When the date it
            # read is just one of the series' own days, the series starts on
            # the SOONEST named day (the project's rule) instead.
            try:
                read = datetime.date.fromisoformat(slots["date"])
                names = ("monday", "tuesday", "wednesday", "thursday",
                         "friday", "saturday", "sunday")
                if names[read.weekday()] in _rec.days:
                    slots["date"] = _rec.start_date(datetime.date.today()).isoformat()
            except ValueError:
                pass
        if temporal.get("start_time"):
            slots["start_time"] = temporal["start_time"]
        # end_time defaults to "" so the CalendarIntent model_validator can auto-fill it
        slots["end_time"] = temporal.get("end_time") or ""
        # Attendees: "with <PROPN>" pattern
        attendees = []
        for tok in span:
            if tok.lower_ == "with" and not _in_temporal(tok, temporal_spans):
                for child in tok.children:
                    if child.pos_ in ("PROPN", "NOUN") and not _in_temporal(child, temporal_spans):
                        attendees.append(child.text)
        if attendees:
            slots["attendees"] = attendees
            # "set a meeting with Ravid" → title "meeting with Ravid" instead of a bare placeholder
            if slots.get("title", "").lower() in {"meeting", "set meeting", "event", "appointment", "call", "lunch", "dinner", "coffee", "zoom"}:
                slots["title"] = f"{slots['title'].replace('set ', '')} with {' and '.join(attendees)}"

    elif action_name == "update_event":
        # F10: the mutation phrase delimits multi-word titles noun-chunking
        # drops ("reschedule HAIRCUT to this weekend"); the generic-target
        # veto still judges whatever is captured.
        m10 = re.search(r"\b(?:reschedule|move|push|shift|postpone)\s+(.+?)\s+"
                        r"(?:to|until|for)\b", span.text, re.IGNORECASE)
        phrase_target = None
        if m10:
            cand = _clean_title(m10.group(1))
            if cand and cand.lower() not in _CALENDAR_SIGNALS:
                slots.setdefault("match_title", cand)
                phrase_target = cand
        # Detect whether this is an extend/shorten action (vs. a move/reschedule)
        _ext = _extend_verbs()
        is_extend = any(tok.lemma_.lower() in _ext for tok in span) or any(
            w in _ext for w in span.text.lower().split())

        if is_extend:
            # Extend/shorten semantics:
            #   "at X"  → match_start_time  (which event to find)
            #   "to Y"  → new_end_time      (what to change)
            #   "on D"  → match_date        (which day to look on)
            # Generic calendar words ("event", "appointment") are not real titles here.
            if title and title.lower() not in _CALENDAR_SIGNALS:
                slots["match_title"] = _extend_title_with_whom(span.text, title)
            if temporal.get("date"):
                slots["match_date"] = temporal["date"]
            if temporal.get("start_time"):
                slots["match_start_time"] = temporal["start_time"]
            # end_time from recognizer directly → new_end_time
            if temporal.get("end_time"):
                slots["new_end_time"] = temporal["end_time"]
            # Also scan for "to Xpm" in the raw text — recognizer stops after the first
            # time hit, so "extend at 1pm to 3pm" won't yield end_time automatically.
            if not slots.get("new_end_time"):
                m = re.search(
                    r"\bto\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
                    span.text, re.IGNORECASE,
                )
                if m:
                    h = int(m.group(1))
                    mins = m.group(2) or "00"
                    ampm = (m.group(3) or "").lower()
                    if ampm == "pm" and h < 12:
                        h += 12
                    elif not ampm and 1 <= h <= 7:
                        h += 12
                    slots["new_end_time"] = f"{h:02d}:{mins}"
            # "...TO BE 15 MINUTES" — a DURATION, not a clock time. Gil, from
            # his phone 2026-09-18: "Can you shorten the event at 2pm walk Jada
            # to be 15 minutes" reached `update_event` and then answered "No
            # changes specified", because every reader here was looking for a
            # new END TIME and he had given a LENGTH.
            #
            # Only the ABSOLUTE form is computed here ("to be 15 minutes" = the
            # event now lasts 15 minutes), and only when the start is known,
            # because that is the whole answer: new_end = start + length. The
            # RELATIVE form ("by 30 minutes") needs the event's current end,
            # which this stage cannot read — filed in TASKS.md rather than
            # guessed at.
            if not slots.get("new_end_time") and slots.get("match_start_time"):
                dur = _DURATION_RE.search(span.text)
                if dur:
                    minutes = _duration_minutes(dur)
                    if minutes:
                        try:
                            sh, sm = (int(x) for x in
                                      str(slots["match_start_time"]).split(":")[:2])
                            total = sh * 60 + sm + minutes
                            if 0 < total < 24 * 60:
                                slots["new_end_time"] = f"{total // 60:02d}:{total % 60:02d}"
                        except (ValueError, TypeError):
                            pass
        else:
            # Standard move/reschedule/rename semantics:
            #   title    → match_title
            #   time     → new_start_time
            #   date     → new_date
            # For rename: "rename X to Y" — match_title = X, new_title = Y (pobj of "to")
            new_title_from_rename: str | None = None
            for tok in span:
                if tok.lower_ == "to" and tok.dep_ in ("prep", "dative", "aux"):
                    pobj_chunks = [
                        c for c in span.noun_chunks
                        if c.root.head == tok and not any(_in_temporal(t, temporal_spans) for t in c)
                    ]
                    if pobj_chunks:
                        new_title_from_rename = _clean_title(pobj_chunks[0].text)
                        break

            # The dependency route above is fragile: "rename gym to workout"
            # yields nothing, and "with Tal" or a two-word name derails it
            # ("… to robotics sync" came back as just "robotics"). When the
            # sentence says "rename X to/as Y" outright, read it literally.
            if not new_title_from_rename:
                m = _RENAME_RE.search(span.text)
                if m:
                    old_name, new_name = m.group(1).strip(), m.group(2).strip()
                    # "rename the meeting to 3pm" is a reschedule, not a rename.
                    _probe = _extract_temporal(new_name, datetime.date.today())
                    if new_name and not _probe.get("start_time"):
                        new_title_from_rename = _clean_title(new_name)
                        if old_name:
                            slots["match_title"] = _extend_title_with_whom(span.text, _clean_title(old_name))

            if new_title_from_rename:
                slots["new_title"] = new_title_from_rename
                if not slots.get("match_title"):
                    root_chunks = [
                        c for c in span.noun_chunks
                        if c.root.dep_ == "ROOT" and not any(_in_temporal(t, temporal_spans) for t in c)
                    ]
                    if root_chunks:
                        slots["match_title"] = _extend_title_with_whom(span.text, _clean_title(root_chunks[0].text))
                    elif title and title != new_title_from_rename:
                        slots["match_title"] = _extend_title_with_whom(span.text, title)
            else:
                # THE PHRASE'S NAME WINS (2026-09-24): F10 above read "move TEAM
                # MEETING to next friday" whole, and this line overwrote it with
                # the noun reader's "team" — which then moved 'team standup'.
                # Only fill the target when the phrase read none.
                if title and not phrase_target:
                    slots["match_title"] = _extend_title_with_whom(span.text, title)

            if temporal.get("start_time"):
                slots["new_start_time"] = temporal["start_time"]
            if temporal.get("end_time"):
                slots["new_end_time"] = temporal["end_time"]
            if temporal.get("date"):
                slots["new_date"] = temporal["date"]

    elif action_name == "delete_event":
        # A bare calendar word is a placeholder rather than a name ("delete the
        # event at 6pm"), and deleting on one could take any event — so it is
        # dropped and the date/time has to identify the event instead.
        #
        # Noun chunking, though, reduces "the meeting with Ima" to that same bare
        # "meeting", and there the person is the whole identity of the event.
        # Keep such a title once the name is recovered, and only then: with no
        # name to pin it down, empty slots (answered with "I couldn't find …")
        # beat deleting somebody else's meeting.
        titled, names_a_person = _title_with_person(span.text, title)
        if titled and (names_a_person or titled.lower() not in _CALENDAR_SIGNALS):
            slots["match_title"] = titled
        # F10: "delete WEDDING REHEARSAL from my calendar" — the phrase
        # delimits what chunking dropped; the veto judges the capture.
        if not slots.get("match_title"):
            m10 = re.search(r"\b(?:delete|remove|cancel|drop|clear|take|wipe)\s+(.+?)\s+"
                            r"(?:from|off)\s+(?:my|the)\s+(?:calendar|schedule)\b",
                            span.text, re.IGNORECASE)
            if m10:
                cand = _clean_title(m10.group(1))
                if cand and cand.lower() not in _CALENDAR_SIGNALS:
                    slots["match_title"] = cand
        if temporal.get("date"):
            slots["match_date"] = temporal["date"]
        if temporal.get("start_time"):
            slots["match_start_time"] = temporal["start_time"]

    elif action_name == "query_schedule":
        # Scope detection on raw span text (before temporal exclusion)
        span_lower = span.text.lower()
        scope = "today"
        for phrase, scope_val in _SCOPE_PHRASES:
            if phrase in span_lower:
                scope = scope_val
                break
        slots["scope"] = scope
        # _SCOPE_PHRASES knows "today", "tomorrow" and "week" and nothing else,
        # so a named day — "what do I have on friday" — matched no phrase and
        # silently kept the default. The same extractor that dates an event
        # resolves it, so the two agree about what Friday means.
        if scope != "week" and temporal.get("date"):
            slots["date"] = temporal["date"]
        # Query type
        if any(w in span_lower for w in ("first", "earliest")):
            slots["query_type"] = "first"
        elif any(w in span_lower for w in ("next", "upcoming")):
            slots["query_type"] = "next"
        elif any(w in span_lower for w in ("how many", "count", "number")):
            slots["query_type"] = "count"
        else:
            slots["query_type"] = "full"

    elif action_name == "create_todo" and temporal.get("start_time") and re.search(r"\bremind me (?:about|of)\b", span.text, re.I):
        # "remind me about X at 9 am" is a calendar event, not a task
        slots["_reroute"] = "create_event"
        slots["title"] = re.sub(r"^\s*remind me (?:about|of)\s+(?:the\s+|my\s+)?", "", span.text, flags=re.I)
        slots["title"] = re.sub(r"\s+(?:tomorrow|today|tonight|on\s+\w+|next\s+\w+|this\s+\w+|at\s+[\d:.]+\s*(?:am|pm)?).*$", "", slots["title"], flags=re.I).strip() or "reminder"
        if temporal.get("date"):
            slots["date"] = temporal["date"]
        slots["start_time"] = temporal["start_time"]
        slots["end_time"] = temporal.get("end_time") or ""
    elif action_name == "create_todo" and _NEW_LIST_RE.match(span.text.strip()):
        # A NEW LIST IS A TO-DO IN GENERAL, titled with what follows (Gil,
        # 2026-09-20). "start a new list of dog breeds" was committing
        # `query_todos` — a QUERY for a create — until the router stopped
        # reading the noun "list" as a command; this is what it does instead.
        # `general` rather than `today`, because a list of dog breeds is not
        # something to do today.
        m = _NEW_LIST_RE.match(span.text.strip())
        body = re.sub(r"^(?:for|of|called|named|titled)\s+", "",
                      (m.group("body") or "").strip(), flags=re.I)
        # The list's name ends where the next ask begins — "start a new list
        # AND add grocery shopping to today's list" titled a to-do 'and' —
        # and courtesy is not a name: "create a new list, PLEASE" titled one
        # 'please'.
        body = _ASK_JOINER_RE.split(body)[0]
        body = re.sub(r"\b(?:please|for me|thanks|thank you)\b", " ", body, flags=re.I)
        body = re.sub(r"\s+", " ", body).strip(" ,.;")
        if body and body.lower() not in _PRONOUN_TITLES:
            slots["titles"] = [body]
            slots["list_name"] = "general"
        else:
            # "create a new list, please" names nothing to put in it. The
            # generic-title veto is the right answer, not a list called 'list'.
            slots["title"] = "list"
    elif action_name == "create_todo":
        # Phrase-level extraction first: dependency heuristics produce "me"
        # for "remind me to …" and "task" for "add a task to …".
        phrase_titles = _todo_titles_from_text(span.text, temporal_spans, span)
        if phrase_titles:
            slots["titles"] = phrase_titles
        elif title and title.lower() not in _PRONOUN_TITLES:
            # A bare imperative with no lead-in phrase never reaches
            # `_todo_titles_from_text` above (its whole job is matching a
            # LEAD-IN, which a bare "buy X and Y" has none of) — widen the
            # single title to the FULL coordinated object list before the
            # verb gets put back, or "buy eight sticky notes, apples, and
            # printer paper" keeps only "sticky notes" (TASKS.md, 2026-09-16).
            widened = _dobj_conjunct_title(span, temporal_spans)
            if widened:
                title = widened
            # The noun-chunk fallback keeps only the object: "call the dentist"
            # became a task called "dentist". Put the verb back so the task says
            # what to do rather than what it is about.
            #
            # NOT A REMINDER VERB (2026-09-20, DEVQA Q26). "remind" says how
            # the ask was PHRASED, not what to do about it — putting it back
            # is what produced 'remind about of all event in calenders',
            # 'remind at this time' and 'remind early that i have a
            # teleconference', each committed at 0.95 or better on dev-100.
            # `_subtractive_title` had already stripped the frame correctly;
            # this line re-attached it. Errand verbs still come back, which is
            # the whole point of the line: 'dentist' -> 'call the dentist'.
            verb = lead_verb(span.text.strip())
            if verb and verb.lower() in _REMINDER_VERBS:
                verb = None
            if verb and not title.lower().startswith(verb.lower()):
                title = f"{verb} {title}"
            slots["titles"] = [title]
        if temporal.get("date"):
            slots["due_date"] = temporal["date"]
        elif _PART_OF_TODAY_RE.search(span.text) and not re.search(r"\btomorrow\b", span.text, re.I):
            # A PART OF TODAY is due today (2026-09-24, DEVQA Q47: a to-do with
            # no clock is due THAT day). "…water the plants this evening" had
            # no due day while "…today" had one, so the same ask went overdue
            # tomorrow or not depending on the word. To-dos only: the temporal
            # reader deliberately leaves these dateless, and giving EVERY
            # parse a date moved 23 of 462 train rows onto the fast path
            # wrongly (an afternoon chore booked as a 09:00 event, a Monday
            # series "starting tonight" begun on a Wednesday).
            slots["due_date"] = datetime.date.today().isoformat()
        # Detect list_name from explicit "general" / "someday" keywords in span
        span_lower = span.text.lower()
        if re.search(r"\b(general|someday|later|backlog)\b", span_lower):
            slots["list_name"] = "general"
        else:
            slots["list_name"] = "today"
        # Extract priority from keywords ("urgent", "high priority", etc.)
        for pattern, level in _PRIORITY_KEYWORDS:
            if pattern.search(span_lower):
                slots["priority"] = level
                break
        tags = _todo_tags_from_text(span.text)
        if tags:
            slots["tags"] = tags

    elif action_name in ("delete_todo", "complete_todo", "update_todo"):
        # F6c: the completion funnel "mark X as done" delimits X by the
        # phrase itself — noun-chunk extraction returns nothing when X is
        # verb-led ("mark WALK THE DOG as done"), so capture it directly.
        m6 = re.search(r"\bmark\s+(.+?)\s+(?:as\s+)?(?:done|complete[d]?|finished)\b",
                       span.text, re.IGNORECASE)
        if m6 and not slots.get("match_title"):
            slots["match_title"] = _clean_title(m6.group(1))
        # F10: mutation phrases delimit multi-word titles noun-chunking
        # drops ("remove BUY SOCKS from my list", "delete WALK THE DOG").
        if not slots.get("match_title"):
            m10 = re.search(r"\b(?:delete|remove|cancel|drop|clear|take)\s+(.+?)\s+"
                            r"(?:from|off)\s+(?:my|the)\s+(?:\w+\s+)?(?:list|tasks?|to-?dos?)\b",
                            span.text, re.IGNORECASE)
            if m10:
                slots["match_title"] = _clean_title(m10.group(1))
        # F7b: "set X as <level> priority" — phrase-delimited, like m6
        m7 = re.search(r"\b(?:set|make)\s+(.+?)\s+as\s+(high|medium|low)\s+priority\b",
                       span.text, re.IGNORECASE)
        if m7:
            if not slots.get("match_title"):
                slots["match_title"] = _clean_title(m7.group(1))
            slots["priority"] = m7.group(2).lower()
            # the rename extractor reads "as high priority" as a new NAME —
            # a priority change must never retitle the task
            slots.pop("new_title", None)
        # For complete/update/delete, also try extracting the subject noun
        # (e.g. "mark groceries as done" → subject "groceries", not "mark groceries")
        #
        # ONLY WHEN THE PHRASES ABOVE READ NOTHING (2026-09-24). "delete WATER
        # THE GARDEN from my list" was read whole by F10 and then overwritten
        # by the noun reader's "water" — which tied 'water the plants' with
        # 'water the garden', and the plants were deleted.
        phrase_target = slots.get("match_title")
        subject_chunks = [] if phrase_target else [
            chunk for chunk in span.noun_chunks
            if chunk.root.dep_ in ("nsubj", "nsubjpass")
            and not any(_in_temporal(t, temporal_spans) for t in chunk)
        ]
        if subject_chunks:
            candidate = _clean_title(subject_chunks[0].text)
            if candidate:
                slots["match_title"] = _extend_title_with_whom(span.text, candidate)
        elif title and not phrase_target:
            slots["match_title"] = _extend_title_with_whom(span.text, title)

        if action_name == "update_todo":
            span_lower = span.text.lower()
            # "rename X to Y" / "rename X as Y" → new_title from pobj of "to"/"as"
            for tok in span:
                if tok.lower_ in ("to", "as") and tok.dep_ in ("prep", "dative"):
                    pobj_chunks = [
                        c for c in span.noun_chunks
                        if c.root.head == tok and not any(_in_temporal(t, temporal_spans) for t in c)
                    ]
                    if pobj_chunks:
                        cand = _clean_title(pobj_chunks[0].text)
                        # F7b: "set X as HIGH PRIORITY" — the priority phrase
                        # is a level, never the task's new name
                        if not re.match(r"^(?:high|medium|low)\s+priority$", cand, re.I):
                            slots["new_title"] = cand
                        break
            # "set priority to high/medium/low" or "make it high priority"
            # Only match explicit priority-level words to avoid false hits like "grocery priority"
            _PRI_WORDS = r"(high|medium|low|urgent|critical|important)"
            m = re.search(rf"\bpriority\s+(?:to\s+)?{_PRI_WORDS}\b", span_lower)
            if not m:
                m = re.search(rf"\b{_PRI_WORDS}\s+priority\b", span_lower)
            if m:
                word = m.group(1).lower()
                slots["new_priority"] = _PRIORITY_NAMES.get(word, word)
            # "set due date to Friday" / "change due date to next Monday"
            if temporal.get("date") and re.search(r"\bdue\b", span_lower):
                slots["new_due_date"] = temporal["date"]
            m_due = _DUE_DATE_OF.match(span.text)
            if m_due:
                slots["match_title"] = _clean_title(m_due.group("what"))
                slots.pop("new_title", None)
            # "move to general / today list"
            if re.search(r"\b(general|someday|later|backlog)\b", span_lower):
                slots["new_list"] = "general"
            elif re.search(r"\btoday\b", span_lower):
                slots["new_list"] = "today"

    elif action_name == "query_todos":
        span_lower = span.text.lower()
        if "general" in span_lower:
            slots["list_name"] = "general"
        elif "all" in span_lower:
            slots["list_name"] = "all"
        else:
            slots["list_name"] = "today"
        slots["include_completed"] = "complete" in span_lower or "done" in span_lower

    # ONE GATE, EVERY PATH (2026-09-20, DEVQA Q26). A create's title is
    # assigned in four places — the subtractive extractor, the phrase
    # extractor, the new-list frame, and the noun-chunk fallback with the verb
    # put back — and a title that names nothing got through whichever one this
    # sentence happened to take. Three cycles of fixing them one at a time
    # moved the junk-title rate by nothing, because each fix reached one path.
    # Here the rule is stated once, after every path has run, and a title that
    # is all scaffolding is REMOVED so the caller's missing-slots refusal
    # answers instead of a to-do called 'at this time'.
    if action_name in ("create_event", "create_todo"):
        if slots.get("title") and not names_something(str(slots["title"])):
            slots.pop("title", None)
        kept = [t for t in (slots.get("titles") or []) if names_something(str(t))]
        if slots.get("titles") and not kept:
            slots.pop("titles", None)
        elif slots.get("titles"):
            slots["titles"] = kept

    # A CHANGE'S TARGET NEVER STARTS WITH THE VERB THAT ROUTED IT (2026-09-25).
    # "scrap oil change" -> delete_todo 'scrap oil change': spaCy reads the
    # bare "scrap oil change" as one noun compound, so the verb rode into the
    # needle and nothing on either list could match it ("scrap THE oil change"
    # was fine). Only the span's own leading word, and only when it is a word
    # the router keys on — "Mark's birthday" is not the verb "mark".
    if action_name.split("_", 1)[0] in ("delete", "update", "complete") and slots.get("match_title"):
        mt = str(slots["match_title"]).strip()
        first = (span.text.strip().split() or [""])[0].lower()
        if first and first in _ROUTING_VERBS and mt.lower().startswith(first + " "):
            rest = mt[len(first):].strip()
            if names_something(rest):
                slots["match_title"] = rest

    return slots


# ---------------------------------------------------------------------------
# Phase 5: Anaphora resolution
# ---------------------------------------------------------------------------


def _resolve_anaphora(slots: dict, action_name: str, memory) -> tuple[dict, bool]:
    """Substitute anaphoric match_title with the known context entity.

    Returns (updated_slots, used_anaphora).
    """
    key = "match_title" if action_name in (
        "update_event", "delete_event", "complete_todo", "delete_todo", "update_todo"
    ) else None

    if key is None:
        return slots, False

    current_val = slots.get(key, "")
    if current_val.lower().strip() not in _ANAPHORS:
        return slots, False

    if "event" in action_name and memory.last_event_title:
        slots[key] = memory.last_event_title
        if not slots.get("match_date") and memory.last_event_date:
            slots["match_date"] = memory.last_event_date
        return slots, True

    if "todo" in action_name and memory.last_todo_title:
        slots[key] = memory.last_todo_title
        return slots, True

    # Anaphor present but memory is empty — can't resolve
    return slots, False


# ---------------------------------------------------------------------------
# Phase 6: Confidence scoring
# ---------------------------------------------------------------------------


#: a spoken clock time — if one is present but unparsed, the parse really IS
#: incomplete and must defer; if absent, "no time" is the answer, not a gap.
#: Does the speaker name a clock time at all? Used by the all-day rule below
#: to tell "add the interview on friday" (all-day, legitimately) from a
#: command whose time we simply failed to read (which must defer).
#:
#: "now" is deliberately NOT here. Adding it was tried on 2026-09-08 and made
#: things worse: it stopped the all-day rule claiming the row, which changed
#: the grounding the deep track received and cost the correct title. The
#: right place to resolve "now" is where the time is READ, not where its
#: absence is judged.
_CLOCK_MENTION_RE = re.compile(
    r"\b\d{1,4}\s*(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)(?!\w)|\b\d{1,2}:\d{2}\b"
    r"|\bat\s+\d{1,2}\b|\b(?:noon|midnight|o'?clock)\b", re.I)


def _compute_missing_slots(action_name: str, slots: dict) -> list[str]:
    # delete_event / update_event: match_title OR match_start_time is sufficient
    if action_name in ("delete_event", "update_event"):
        if not slots.get("match_title") and not slots.get("match_start_time"):
            return ["match_title"]
        return []
    required = _REQUIRED_SLOTS.get(action_name, [])
    missing = [s for s in required if not slots.get(s)]
    # F15: a create_event with a DATE but no spoken clock time is an ALL-DAY
    # event, not an incomplete parse — "add the interview date on next
    # friday" names everything it needs. Deferring these was the single
    # largest atomic-defer bucket (215 rows). The intent model fills the
    # block (00:00–23:59); a missing DATE still defers, and a text that
    # mentions a time we failed to read still defers (that IS incomplete).
    if (action_name == "create_event" and missing == ["start_time"]
            and slots.get("date") and slots.get("title")
            and not _CLOCK_MENTION_RE.search(slots.get("_raw_text", ""))):
        # A MEAL NAMES ITS OWN HOUR (Gil, 2026-09-20: *"have default for
        # breakfast/lunch/dinner as 0900/1300/1900 if not given for an
        # event"*), so it is not an all-day block. Decided HERE rather than in
        # `CalendarIntent.fill_defaults` because this is the last place that
        # can tell the two apart: once the block is stamped, an all-day the
        # SPEAKER asked for and a bare date we defaulted are the same two
        # values. 5 of the 7,200 rows say "all day" about a meal, and they
        # keep their block.
        from assistant.actions.calendar.intent import meal_hour
        meal = meal_hour(slots.get("title"))
        if meal and not _ALL_DAY_RE.search(slots.get("_raw_text", "")):
            slots["start_time"] = meal
            slots["end_time"] = slots.get("end_time") or ""
        elif _ALL_DAY_RE.search(slots.get("_raw_text", "")):
            slots["start_time"] = "00:00"
            slots["end_time"] = slots.get("end_time") or "23:59"
        else:
            # 09:00 (Gil, 2026-09-20, DEVQA Q36). A dated event with no clock
            # used to be an all-day BLOCK here and the clock-of-now on the
            # deep track, so the same sentence got two answers and the deep
            # one flagged itself — most of the judge's `unsupported_field`
            # notices on dev-100 were this row. All-day is now what the
            # SPEAKER asks for (the branch above), not what we fall back to.
            slots["start_time"] = "09:00"
            slots["end_time"] = slots.get("end_time") or ""
        return []
    # THE MIRROR CASE (Q26, Gil, 2026-09-18): a stated CLOCK and no day.
    # "remind me to feed the cat at 14:00" and "I need to walk Val at 3pm" —
    # both Gil's own commands, both events under Q26 — named a time and no
    # date, and then deferred on the date ALONE.
    #
    # SPEC floors an item with no date to TODAY, and the deep track already
    # does it without hesitating (`resolve_date`: "ISO, floored to today"), so
    # a fast track that defers here makes the two tracks disagree about a
    # sentence one of them answers outright. The title and the clock are both
    # present; the only thing missing is the day, and the project already has
    # one answer for that.
    #
    # ONE ASK ONLY, and this was bought immediately: without the guard,
    # "book the gym at 6 and remind me to buy milk" — a COMPOUND — started
    # committing on the fast track. The missing date had been holding it back,
    # so filling it silently removed a deferral that was doing real work.
    # `test_fastrule_work_travels_forward_when_it_declines` caught it. A
    # compound belongs to the deep track (Gil's ruling), and a convenience
    # default must never be what decides that.
    if (action_name == "create_event" and missing == ["date"]
            and slots.get("_n_spans", 1) == 1
            and slots.get("start_time") and slots.get("title")):
        # Q42 (Gil, 2026-09-22): the floor is today — unless the stated clock
        # has already gone by, then tomorrow ("Add an event for 5 p.m." said
        # at 6pm is tomorrow's 5pm). The deep track applies the same rule
        # (`object_rules._rule_passed_clock_means_tomorrow`).
        now = datetime.datetime.now()
        floor = now.date()
        if str(slots["start_time"])[:5] < now.strftime("%H:%M"):
            floor = floor + datetime.timedelta(days=1)
        slots["date"] = floor.isoformat()
        return []
    return missing


def _compute_confidence(
    action_name: str,
    slots: dict,
    temporal: dict,
    domain_inferred: bool,
    used_anaphora: bool,
) -> float:
    # delete_event / update_event: satisfied by match_title OR match_start_time
    if action_name in ("delete_event", "update_event"):
        base = 1.0 if (slots.get("match_title") or slots.get("match_start_time")) else 0.0
    else:
        required = _REQUIRED_SLOTS.get(action_name, [])
        total_required = len(required)
        if total_required == 0:
            base = 1.0
        else:
            filled = sum(1 for s in required if slots.get(s))
            base = filled / total_required

    multiplier = 1.0

    if temporal.get("_source") == "regex_fallback":
        multiplier *= 0.95

    if domain_inferred and action_name not in ("query_schedule", "query_todos"):
        multiplier *= 0.85

    if used_anaphora:
        multiplier *= 0.80

    # Two distinct clock times in one span usually means two events ("lunch at noon
    # and coffee at 9") — the single-intent slots can't represent that; force hybrid.
    if action_name == "create_event" and temporal.get("_n_times", 0) >= 2 and not temporal.get("end_time"):
        multiplier *= 0.7

    confidence = base * multiplier

    # Bonus for optional slots
    bonus_list = _BONUS_SLOTS.get(action_name, [])
    bonus = sum(0.05 for s in bonus_list if slots.get(s))
    confidence = min(1.0, confidence + min(0.10, bonus))

    return round(confidence, 3)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class RuleBasedParser:
    """Fast-path NLU parser using spaCy + recognizers-text-date-time.

    Handles simple voice commands in <10ms without an LLM call.
    For ambiguous or complex inputs, raises RuleParserSkip (caller uses LLM).
    For partial matches, returns a RuleParseResult with confidence < RULE_THRESHOLD
    so the caller can hand off to the LLM with pre-filled slot context.
    """

    def __init__(self, registry: "ActionRegistry") -> None:
        self._registry = registry
        from assistant.intent.context import context_memory
        self._memory = context_memory

    def analyze(self, transcript: str, current_view: str = "month") -> RuleParseResult:
        """Full 7-phase analysis.

        Raises RuleParserSkip if the complexity gate fires or no intent matches.
        Otherwise returns a RuleParseResult (which may have low confidence or
        missing slots, in which case the pipeline should hand off to the LLM).
        """
        if not _RULE_PARSER_AVAILABLE:
            raise RuleParserSkip("spaCy not available")

        # Phase 0: Preprocess + complexity gate
        normalized, should_skip, lead_minutes = _preprocess(transcript)
        if should_skip:
            raise RuleParserSkip(f"Complexity gate fired for: {transcript!r}")

        doc = _NLP(normalized)

        # Phase 1: Multi-intent splitting
        spans = _split_intents(doc)

        today = datetime.date.today()

        all_intents: list[tuple[str, "BaseIntent"]] = []
        all_missing: list[str] = []
        range_dates: list[str] = []
        all_raw_slots: dict = {}
        confidences: list[float] = []
        dropped_spans = 0
        #: A date resolved on a span that carried no action. None = none seen,
        #: "" = more than one, which is not carried (see the drop site below).
        carried_date: "str | None" = None

        for span in spans:
            # Phase 2: Temporal extraction
            temporal = _extract_temporal(span.text, today)

            # Phase 3: Intent/domain routing
            action_name, _, domain_inferred, domain_material = _route_intent(span, current_view)
            if action_name == "create_todo":
                # Q47 (Gil, 2026-09-24): an encounter with a person — met,
                # seen, called — is an event, day or no day ("call mum is an
                # event at a default time like 9"). Checked HERE, on the words
                # as said: `_route_intent` lowercases them (so "call Morgan"
                # lost the capital that marks a name) and its phrase overrides
                # return before any rule at its end. The same rule the
                # segmentation tagger applies (`intent/encounter.py`).
                from assistant.intent.encounter import is_encounter
                # `_preprocess` lowercases the whole sentence, so the span's
                # own text has no capital left to mark a name: read the same
                # stretch of the transcript AS SAID where it can be found.
                said = span.text
                at = transcript.lower().find(span.text)
                if at >= 0:
                    said = transcript[at:at + len(span.text)]
                if is_encounter(said):
                    action_name, domain_inferred = "create_event", True
                    # "if the time isn't given, you just say like default
                    # time 9 a.m." — and with no day either, the soonest 9 AM
                    # (today, or tomorrow once 9 has passed: Q42's "whichever
                    # is closer"). Filled here so a plain "call mum" commits on
                    # the fast path instead of deferring for missing slots.
                    if not temporal.get("start_time"):
                        temporal["start_time"] = "09:00"
                    if not temporal.get("date"):
                        now = datetime.datetime.now()
                        day = now.date() if now.hour < 9 else now.date() + datetime.timedelta(days=1)
                        temporal["date"] = day.isoformat()
            if action_name is None and len(spans) == 1 and _bare_noun_event(span, temporal):
                # A BARE NOUN WITH A DAY OR A CLOCK IS AN EVENT (2026-09-24).
                # "Dentist tomorrow at 4", "vet appointment takes all day march
                # 5th", "team meeting in three weeks, all day" carry no verb for
                # the router to map, so every one DEFERRED to the model — which
                # reads them right, several seconds later (found verifying the
                # tutorial; 55 such event rows in the FastRule train half). Only
                # when the sentence OPENS with a noun: a verb it cannot map
                # ("take the medicine at 9", "do the laundry") is still the
                # model's, because those are mostly to-dos. Routed as INFERRED,
                # so the ×0.85 channel and the front-door threshold still
                # guard the commit.
                action_name, domain_inferred, domain_material = "create_event", True, True
            if action_name is None:
                if len(spans) == 1:
                    raise RuleParserSkip(f"No action matched for: {span.text!r}")
                # Multi-span: skip unmatched span, continue — but remember it: part of
                # the command was ignored, so the LLM should get a look (hybrid).
                #
                # ...and KEEP ITS DATE. The temporal was resolved two lines up,
                # before routing, and dropping the span dropped the date with
                # it: "the 30th, wash and fold the laundry" cuts into a
                # date-only fragment and a real ask, and the ask committed with
                # NO DUE DATE at all. 13 of the 20 rows this reaches are wrong
                # at the END position too, so it is not a position bug — it is
                # a fragment that was never an ask taking a date that was.
                #
                # ONE SURVIVOR ONLY, and that bound is what keeps this out of
                # Q16's territory. Q16 (as amended 2026-09-18) governs which of
                # SEVERAL asks a shared date scopes over — a marked deadline
                # over tasks, a bare day over events. With exactly one ask
                # left there is nobody to share with and no scope to decide,
                # so this cannot contradict that ruling or become a fourth
                # date-sharing convention. If more than one ask survives, the
                # date stays dropped and the deep track decides.
                dropped_spans += 1
                if temporal.get("date"):
                    carried_date = temporal["date"] if carried_date is None else ""
                continue

            # Phase 4: Slot filling
            _tt = re.sub(r"(\d)\.(\d)", r"\1:\2", span.text)   # 4.30 pm → 4:30 pm
            temporal["_n_times"] = len(re.findall(
                r"(?<![\d:])(?:\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?|\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.)|noon|midnight|\d{1,2}\s*o'clock|at\s+\d{1,2}(?![\d:]))\b",
                _tt, re.I))
            if temporal.get("_date_from_range"):
                range_dates.append(temporal["_date_from_range"])
            slots = _fill_slots(span, action_name, temporal, current_view)
            if "_reroute" in slots:
                action_name = slots.pop("_reroute")

            # Phase 5: Anaphora resolution
            slots, used_anaphora = _resolve_anaphora(slots, action_name, self._memory)
            temporal["_used_anaphora"] = used_anaphora
            temporal["_domain_inferred"] = domain_inferred

            # Phase 6: Confidence + validation
            slots["_raw_text"] = span.text
            # How many asks this utterance carries, for the date floor below —
            # see `_compute_missing_slots`. Stashed the same way `_raw_text` is,
            # and popped straight back out, because the slot dict is the object
            # that reaches the intent model.
            slots["_n_spans"] = len(spans)
            missing = _compute_missing_slots(action_name, slots)
            slots.pop("_raw_text", None)
            slots.pop("_n_spans", None)
            # Only penalize the guessed domain when it was actually load-bearing in
            # picking the action (domain_material) — a domain-agnostic verb like
            # "buy"/"call"/"email" maps to create_todo regardless of domain, so an
            # unresolved domain guess shouldn't dock confidence on those.
            confidence = _compute_confidence(
                action_name, slots, temporal, domain_inferred and domain_material, used_anaphora
            )

            all_missing.extend(missing)
            confidences.append(confidence)
            all_raw_slots[action_name] = slots

            logger.debug(
                "Rule parser: action=%s confidence=%.2f missing=%s slots=%s",
                action_name, confidence, missing, slots,
            )

            # Attempt Pydantic validation when all required slots are present
            if not missing:
                action_cls = self._registry.get(action_name)
                if action_cls is not None:
                    try:
                        intent = action_cls.intent_model.model_validate(slots)
                        all_intents.append((action_name, intent))
                    except Exception as exc:
                        logger.debug("Rule parser validation failed for %s: %s", action_name, exc)
                        all_missing.append("validation_error")
                        confidences[-1] = round(confidence * 0.5, 3)

        # THE LEAD TIME REACHES THE EVENT (2026-09-25). `_preprocess` has read
        # "remind me 30 minutes before" out of the command since F16 — and then
        # dropped the minutes, so every fast-path event committed with no
        # reminder at all (0 of 72 on the FastRule 7,200 TRAIN half, a loss no
        # board scored). It goes on every created item that can carry one and
        # has none of its own.
        if lead_minutes:
            for _name, _intent in all_intents:
                if (_name.startswith("create_") and hasattr(_intent, "reminder_minutes")
                        and getattr(_intent, "reminder_minutes", None) is None):
                    try:
                        _intent.reminder_minutes = int(lead_minutes)
                    except (TypeError, ValueError):
                        pass

        # A date carried off a DROPPED, action-less span now lands on the one
        # ask that survived. Applied after the loop because the fragment falls
        # on either side of it: "the 30th, wash the laundry" puts it first,
        # "book the interview with Jamie and Rowan the 30th" cuts it last.
        #
        # Only when the ask named no date of its own — the speaker's own words
        # always win over a recovered one.
        if carried_date and len(all_intents) == 1 and not all_missing:
            _name, _intent = all_intents[0]
            _field = ("due_date" if hasattr(_intent, "due_date")
                      else "date" if hasattr(_intent, "date") else None)
            if _field and not getattr(_intent, _field, None):
                all_intents[0] = (
                    _name, _intent.model_copy(update={_field: carried_date}))
                all_raw_slots.setdefault(_name, {})[_field] = carried_date

        if not confidences:
            raise RuleParserSkip("No spans produced confident results")

        overall_confidence = min(confidences) * (0.7 if dropped_spans else 1.0)

        return RuleParseResult(
            confidence=overall_confidence,
            intents=all_intents,
            missing_slots=all_missing,
            raw_slots=all_raw_slots,
            transcript=normalized,
            dropped_spans=dropped_spans,
            range_dates=range_dates or None,
        )

    def parse(self, transcript: str, current_view: str = "month") -> list[tuple[str, "BaseIntent"]]:
        """Public parse API compatible with the ParserProtocol.

        Returns intents directly when confidence is high and slots are complete.
        Raises RuleParserSkip if confidence < RULE_THRESHOLD or missing_slots.
        Pipeline should catch RuleParserSkip and fall through to LLM.
        """
        result = self.analyze(transcript, current_view)
        if result.confidence >= RULE_THRESHOLD and not result.missing_slots:
            return result.intents
        raise RuleParserSkip(
            f"Confidence {result.confidence:.2f} < {RULE_THRESHOLD} or missing slots: {result.missing_slots}"
        )
