"""The engine's FIRST reading of an item's kind — event, task or review.

`fastseg.tag` starts from this reading and applies its one-way vetoes over
`event`; everything here was written against the FastRule 7,200 train half,
one vocabulary at a time, and each list carries the measurement that put it
there. It lived in the retired `old_seg` module until 2026-09-20, imported
across a boundary that read as "the live tagger depends on the retired
segmenter"; the retired module now imports it from here, so there is ONE copy.

    kind_of(text) -> "event" | "task" | "review"
"""
from __future__ import annotations

import re

# A schedule question, not an instruction to create anything.
#
# The "my schedule" arm used to be UNANCHORED, so any command that merely
# mentioned the schedule was read as a question about it — "drop piano lesson
# from my schedule" is a DELETE, and it was scoring as a review (14 rows on
# the FastRule train half, every one of them a `drop … from my schedule`).
# It now needs a looking verb in front of it, which is what made it a question
# in the first place.
#
# The looking verbs also had a gap of their own: "check my calendar for this
# week" and "could you tell me what's on my calendar" are plainly reviews and
# matched nothing (50 rows read as events).
# Deliberately NOT here: "remind me of" and "give me" — the first is a
# reminder and the second opens a lead-time clause ("give me a heads up
# 30 minutes before"). Both read as questions and are not; including them
# turned 25 tasks into reviews.
# "check OFF mail the package" completes a to-do; only a bare "check" is a
# looking verb. Same trap as the schedule arm: a word that reads as a query
# in isolation is part of an action verb here.
_LOOK_VERB = (r"(?:what(?:'s| is| do| have| does)?|show|tell me|"
              r"check(?!\s*(?:off|out)\b)|see|"
              r"look at|pull up|read|bring up|"
              r"do i have|when is|when's|how many|list|"
              # the yes/no question: "is today st. patricks day", "is it on
              # my calendar" — a question about the day, not a booking of it
              r"is\s+(?:today|tomorrow|tonight|it|there))")

#: A wake word is not a word of the command. "PDA do i have any appointments
#: set for tomorrow?" made a TO-DO because the looking verb was not first.
_WAKE = r"(?:(?:hey|ok|okay)\s+)?(?:siri|alexa|pda|olly|google|computer)[,\s]+"

_REVIEW_RE = re.compile(
    rf"^(?:{_WAKE})?(?:please\s+|hey\s+|um+\s+|so\s+)?(?:can|could|would|will)?\s*"
    rf"(?:you\s+)?{_LOOK_VERB}\b"
    # A command never opens with a bare auxiliary; a question does. "is today
    # st. patricks day" reached the tagger as "is st. patricks day" — the
    # time already cut out — so the "is today" form above never saw it and an
    # event 'St. Patrick's Day' was booked (dev-100 run 25). "are you able to
    # add…" is a polite imperative, hence the (?!you).
    rf"|^(?:{_WAKE})?(?:please\s+)?(?:is|are|was|were|does|did|am)\s+(?!you\b)"
    rf"|\b{_LOOK_VERB}\b[^.?!]{{0,40}}\bmy\s+"
    rf"(?:schedule|day|week|agenda|calendar|diary)\b",
    re.I)

# To-do phrasing. Only used as a first reading; step 5 decides the action.
#
# It used to recognise CREATE-shaped to-do wording and nothing else, so every
# way of COMPLETING, EDITING or UN-LISTING a task fell through to "event" —
# and because `decompose.run()` branches entirely on kind, that cost the
# decomposition as well as the label. Measured on the FastRule 7,200 train
# half: non-create to-do operations scored 8.8% (41 of 467), and task RECALL
# was 0.341 against event recall 0.978. The errors were almost all one
# direction: 730 tasks read as events, 41 events read as tasks.

#: The strongest signal there is, and the one that needed no verb: an explicit
#: to-do DESTINATION anywhere in the sentence. "get rid of cancel the
#: subscription ON MY LIST", "remove X FROM MY LIST", "drop X FROM MY TASKS"
#: name no create verb at all, and the destination is what makes them tasks.
#: "calendar" and "schedule" are deliberately absent — those are events.
_LIST_DEST = (
    r"\b(?:to-?do|task|shopping|grocer(?:y|ies)|errand)s?\s+list\b"
    # bare "list" belongs here: the commonest spoken form is "on my list" /
    # "from my list" with no qualifier at all, and requiring one missed every
    # such row ("just get rid of cancel the subscription ON MY LIST").
    r"|\b(?:on|to|off|from|in)\s+(?:my|the)\s+"
    r"(?:to-?do|task|shopping|grocer(?:y|ies)|errand|list)s?(?:\s+list)?\b"
    r"|\bmy\s+(?:to-?do|task|errand|list)s?\b"
    # A NEW list, or a list OF things, is a to-do ask however it is verbed:
    # "make a new list of dog breeds", "begin new list of lottery numbers",
    # "i need a list of my clients" all tagged EVENT (dev-100 run 22: five of
    # the twelve kind misses). "list" as a looking verb ("list my events")
    # is read by `_REVIEW_RE` first and is not this shape.
    r"|\b(?:new|another|fresh)\s+list\b"
    r"|\blist\s+(?:of|for|called|named|titled)\b"
)

#: Completing a to-do. These say nothing about a calendar and cannot be
#: confused with booking something: "mark X as done", "i already did X",
#: "check off X", "i finished X", "i'm done with X".
#: `complet(?:e|ed)?` rather than `complete` because the corpus carries the
#: truncation the recogniser actually produces ("mark X as complet").

_TODO_DONE = (
    r"\bmark\b[^.?!]{0,40}\b(?:as\s+)?(?:done|complet(?:e|ed)?|finished)\b"
    r"|\b(?:check|cross|tick)\s+(?:it\s+|that\s+|this\s+)?off\b"
    r"|^(?:complete|finish|finished)\s+\w"
    r"|\bi\s+(?:already\s+)?(?:did|finished|completed)\b"
    r"|\bi'?m\s+done\s+with\b"
    r"|\balready\s+(?:did|done|finished|handled)\b"
)

#: Naming a to-do outright, and the errand openers the original list missed
#: ("i gotta pack for the trip", "create a task to water the plants").
_TODO_NAMED = (
    r"^(?:create|add|make|set)\s+(?:a|an)\s+(?:new\s+)?(?:task|to-?do)\b"
    # "set a reminder TO <verb>" is an errand; "set a reminder 2 hours before
    # FOR standup" is a calendar entry with a lead time. Only the first is a
    # to-do, and the "to" is what tells them apart.
    r"|^(?:create|add|make|set)\s+(?:a|an)\s+remind\w*\s+to\b"
    r"|^i\s+(?:gotta|have to|got to|must|should|need to)\b"
    r"|^(?:don'?t let me forget|do not forget|dont forget)\b"
)

#: CHORE verbs in the imperative — the errands a to-do list is for. Nothing
#: here can book anything: the calendar verbs (book, schedule, meet, plan,
#: invite) are deliberately absent, and so is "call", which is genuinely
#: ambiguous between an errand and an appointment and is left to the model.
_CHORE_VERB = (
    r"^(?:file|wash|fold|print|clean|organi[sz]e|pack|water|vacuum|hoover|"
    r"restock|refill|renew|mail|post|submit|charge|feed|sweep|mow|iron|dust|"
    r"declutter|tidy|empty|defrost|sort out|drop off|take out|back up|"
    r"wrap|donate|recycle|shred|scan|photocopy)\b"
)

_TASK_RE = re.compile(
    r"^(?:add|put)\s+.*\b(?:to|on)\s+(?:my\s+)?(?:to-?do|task|shopping)|"
    r"^(?:remind me to|i need to|remember to|buy|get(?!\s+rid\b)|pick up)\b|"
    # "i want sweet potato pie from a local bakery" is a thing wanted — an
    # errand. Not "i want TO …" (the encounter rule owns "i want to meet"),
    # and not a wanted OCCASION ("i want a meeting with sam tomorrow").
    r"^i\s+want\b(?!\s+to\b)(?![^.?!]{0,24}\b(?:meeting|appointment|party|"
    r"dinner|lunch|brunch|breakfast|call|session|class|lesson|date)\b)|"
    rf"{_LIST_DEST}|{_TODO_DONE}|{_TODO_NAMED}|{_CHORE_VERB}",
    re.I)


# A clock time inside a "remind" phrasing flips it to the calendar: the
# product rule (pinned in the corpus) is "remind me to call Ravid" = task,
# "remind me about the dentist tomorrow at 9 am" = event.
_CLOCKISH_RE = re.compile(
    r"\b\d{1,4}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)(?!\w)|\b\d{1,2}:\d{2}\b|\bat\s+\d{1,2}\b|"
    r"\b(?:at|for)\s+\d{3,4}\b|"
    r"\b(noon|midnight|tonight|morning|evening|afternoon)\b", re.I)

# Any remind-flavoured wording — the verb or the noun ("a birthday wish
# reminder for tomorrow at 10 AM" carries no "remind me to").
_REMINDISH_RE = re.compile(r"\b(?:remind(?:er)?s?|notify)\b", re.I)   # notify: cycle 4

# The "remind me to <verb> …" errand form — stays a task unless clock-timed.
_REMIND_TO_VERB_RE = re.compile(r"\bremind\s+\w+\s+to\b", re.I)

# "I need to <meet/talk/…>" — an encounter being arranged, not an errand.
_NEED_ENCOUNTER_RE = re.compile(
    r"\bi\s+(?:need to|should|want to|would like to|gotta|have to|must)\s+"
    r"(?:meet|talk|speak|see|catch up|sit down|"
    r"have\s+a\s+(?:conversation|chat|word|meeting|call))\b", re.I)

# An occasion someone attends (not an errand someone does) …
_OCCASION_RE = re.compile(
    r"\b(meeting|appointment|party|get-?together|dinner|lunch|brunch|breakfast|"
    r"birthday|anniversary|wedding|funeral|concert|recital|interview|class|"
    r"lesson|shiur|conference|ceremony|festival|event)\b", re.I)   # festival: cycle 4

# … said with a date reference (a weekday, a relative day, an ordinal, a month).
_DATED_RE = re.compile(
    r"\b(today|tomorrow|tonight)\b|"
    r"\b(next|this|on)\s+(week|month|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|weekend)\b|"
    r"\bthe\s+\d{1,2}(st|nd|rd|th)?\b|"
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\b", re.I)



def _enforce_pinned_kinds(kind: str, text: str) -> str:
    """The pinned reminder rules, enforced over the LLM's own labels.

    Cycle 1 (dataset loop): `_kind_of` flips remind + clock-time to the
    calendar, but on the deep path the LLM's kind label won unchecked — so
    "create a birthday wish reminder for tomorrow at 10 AM" landed as a todo
    and generate's event-kind retry (which keys off kind == "event") never
    fired. The event half of a compound was mis-kinded, not dropped.

    Cycle 2 (product convention, Gil 2026-09-04): a reminder ABOUT an occasion
    with a date is a calendar entry even without a clock time — "set a
    reminder for my meeting today", "remind me of my meeting tomorrow" — while
    the errand form "remind me to <verb> …" stays a task unless clock-timed
    (cycle 1's rule)."""
    if kind != "task":
        return kind
    # "send a calendar invite …" names the calendar outright — no remind-word
    # needed (cycle 4: "…calendar invite out to James and Alice for brunch at
    # 11 am" was labelled task and produced no event).
    if re.search(r"\bcalendar\s+invite\b", text, re.I):
        return "event"
    # Q1 (product convention, Gil 2026-09-06): a dated "I need to <meet/
    # talk/have a conversation> …" is an appointment being made — "on Monday,
    # the 20th, I need to have a conversation with Greg" is a calendar event,
    # no remind-word required. Encounter verbs only: "I need to buy …" is
    # still an errand, and an undated encounter stays a task.
    if (_NEED_ENCOUNTER_RE.search(text)
            and (_DATED_RE.search(text) or _CLOCKISH_RE.search(text))):
        return "event"
    if not _REMINDISH_RE.search(text):
        return kind
    if _CLOCKISH_RE.search(text):
        return "event"
    if (not _REMIND_TO_VERB_RE.search(text)
            and _OCCASION_RE.search(text) and _DATED_RE.search(text)):
        return "event"
    return kind


#: The calendar named as the destination. It OUTRANKS every to-do signal:
#: "get rid of that task on my calendar the 3rd" says "task" and means an
#: event, and the destination is the speaker being explicit about which of
#: the two lists they mean.
_CALENDAR_DEST_RE = re.compile(
    r"\b(?:on|to|in|from|off)\s+(?:my|the)\s+"
    r"(?:calendar|schedule|diary|agenda)\b", re.I)


#: Arranging to be in the same place as someone — "get Blake and me TOGETHER
#: for staff meeting", "meet up with Sage", "catch up with Jordan". These open
#: with `get`, which the errand list claims, but nobody puts a gathering on a
#: to-do list; it is an appointment being made.
_GATHERING_RE = re.compile(
    r"\bget\s+[\w' ]{0,30}\btogether\b"
    r"|\bmeet(?:\s+up)?\s+with\b"
    r"|\bcatch\s+up\s+with\b"
    r"|\bsit\s+down\s+with\b", re.I)


#: SEEING A PERSON is not looking something up (Q47, 2026-09-24): "see mom
#: on sunday", "visit Parker" opened with the look-verb "see" and were tagged
#: a review — a question about the schedule — so nothing was booked.
_SEE_A_PERSON_RE = re.compile(
    r"^(?:please\s+|hey\s+|um+\s+|so\s+|i\s+(?:need to|should|want to|have to|will|'ll)\s+)?"
    r"(?:see|visit)\s+(?:my\s+)?(?:(?:mom|mum|mother|dad|father|parents|grandma|grandpa|"
    r"grandmother|grandfather|bubbie|saba|savta|sister|brother|wife|husband|son|"
    r"daughter|aunt|uncle|cousin|boss|doctor|dr|rabbi|teacher|friends?)\b|[A-Z][a-z]+\b)")


def _kind_of(text: str) -> str:
    t = text.strip()
    if _SEE_A_PERSON_RE.search(t):
        return "event"
    if _REVIEW_RE.search(t):
        return "review"
    if _CALENDAR_DEST_RE.search(t) or _GATHERING_RE.search(t):
        return "event"
    if _TASK_RE.search(t):
        # The pinned convention distinguishes "remind me TO <verb> …" (an
        # errand — stays a task) from "remind me ABOUT <occasion> …" (a
        # calendar entry). `_enforce_pinned_kinds` already honours that split;
        # this call site did not, and flipped ANY remind-worded row carrying a
        # clock time to the calendar. "remind me to feed the cat at 14:00" is
        # a to-do with a time on it, not a meeting with the cat.
        if (re.search(r"\bremind", t, re.I) and _CLOCKISH_RE.search(t)
                and not _REMIND_TO_VERB_RE.search(t)):
            return "event"
        return "task"
    # A DAMAGED OR PREFIXED FRAME still names a task. `_TASK_RE` is the only
    # reader above, and it does not match when Whisper mangles a word INSIDE
    # the frame ("remind mitt to sign the permission slip", "remind need to
    # …") or when a UI tag precedes it ("[TASKS VIEW] can you remind me to
    # book a flight"). Those fell through to this catch-all `event` — which is
    # how a reminder ended up on the calendar.
    #
    # `_REMIND_TO_VERB_RE` already matches every one of them and is position-
    # free, so nothing new is needed: it was simply consulted only INSIDE the
    # branch the damaged text never enters. This is the reader being fixed
    # rather than the speaker's words being rewritten, which is the whole
    # point — `assistant/stt/vocab.py` is where a MISHEARD word is repaired,
    # and it needs a vocabulary entry, not a hidden table in the segmenter.
    #
    # Returning `task` here does not fight Q26: `fastseg.tag` applies the
    # stated-clock promotion AFTER this, so "remind mitt to feed the cat at
    # 14:00" still becomes an event on the clock, as Gil ruled.
    if _REMIND_TO_VERB_RE.search(t):
        return "task"
    return "event"


def kind_of(text: str) -> str:
    """The first reading with the pinned reminder conventions applied — the
    pair every caller wants together."""
    return _enforce_pinned_kinds(_kind_of(text), text)
