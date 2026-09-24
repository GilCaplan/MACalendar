"""Is this ask an ENCOUNTER with a person? — the rule both tracks share.

DEVQA Q47 (Gil, 2026-09-24): *"given a person, it should be an event no
matter what. So if the time isn't given, you just say like default time 9
a.m."*, and then: *"Call mum is an event at a default time like 9, same for
similar events."* So meeting, seeing or talking to someone — in person or by
a live call — is an EVENT, with or without a stated day or clock. A WRITTEN
message ("email Dana the report", "text Sam") is not an encounter and stays a
to-do; so is a mention ("buy a gift for mom"); and naming the to-do list
("add ... to my tasks") always wins.

One module because two readers decide kind: segmentation's tagger
(`fastseg.tag`) and the front door (`rule_parser._route_intent`). Two copies
of this rule is how "i should see Parker the 21st" came out an event on one
track and a to-do on the other.
"""
from __future__ import annotations

import re

#: People named without a capital letter.
KIN = (r"mom|mum|mommy|mummy|mother|dad|daddy|father|parents|grandma|grandpa|"
       r"grandmother|grandfather|bubbie|bubby|saba|savta|ima|abba|sister|brother|"
       r"wife|husband|son|daughter|aunt|uncle|cousin|boss|rabbi|friend|friends")

#: Verbs that bring you together with the person, including a LIVE call.
_MEET_VERBS = (r"see|visit|meet(?:\s+up\s+with)?|meet\s+with|catch\s+up\s+with|"
               r"hang\s+out\s+with|sit\s+down\s+with|have\s+(?:lunch|dinner|coffee|breakfast|a\s+call|a\s+meeting)\s+with|"
               r"talk\s+(?:to|with)|speak\s+(?:to|with)|chat\s+with|"
               r"call|phone|ring|facetime|video\s+call|zoom\s+with|skype|"
               r"pick\s+up|drop\s+off|drive|take")

#: Words after a verb that are NOT a person's name even when capitalised.
_NOT_A_NAME = set(
    "monday tuesday wednesday thursday friday saturday sunday january february "
    "march april may june july august september october november december today "
    "tomorrow tonight the a an my our your this that it me us them him her".split())

#: Verbs, articles and kinship words match in any case ("Call Mom", "call
#: mom"); a plain NAME needs its capital, which is what tells "call Dana"
#: from "call the plumber".
_ENCOUNTER_RE = re.compile(
    rf"\b(?i:{_MEET_VERBS})\s+(?i:up\s+)?(?i:my\s+|the\s+|our\s+)?(?P<who>(?i:{KIN})\b|[A-Z][a-z]+)\b"
    rf"|\b(?i:with)\s+(?i:my\s+|the\s+)?(?P<with>(?i:{KIN})\b|[A-Z][a-z]+)\b")

_WRITTEN = re.compile(r"\b(?:email|e-mail|text|message|msg|write\s+to|send|ping|dm)\b", re.I)

_TODO_DESTINATION = re.compile(
    r"\b(?:to|on|onto|in|into)\s+(?:my|the|our)\s+"
    r"(?:to-?do\s+|task\s+|shopping\s+|grocery\s+)?(?:list|lists|tasks|to-?dos?)\b", re.I)


def is_encounter(text: str) -> bool:
    """True when the words bring the speaker together with a named person."""
    t = (text or "").strip()
    if not t or _TODO_DESTINATION.search(t):
        return False
    for m in _ENCOUNTER_RE.finditer(t):
        who = (m.group("who") or m.group("with") or "")
        if who.lower() in _NOT_A_NAME:
            continue
        # "The" at a sentence start is an article, not a name.
        # A written message to the person is not an encounter ("email Dana").
        head = t[:m.start()].lower()
        if _WRITTEN.search(head[-24:]) and not re.search(r"\bcall|\bmeet|\bsee\b", head[-24:]):
            continue
        # A lowercase non-kin word is not a name ("call the plumber" never
        # matches: "the" is skipped and "plumber" is lowercase).
        if who and who[0].islower() and not re.fullmatch(KIN, who, re.I):
            continue
        return True
    return False
