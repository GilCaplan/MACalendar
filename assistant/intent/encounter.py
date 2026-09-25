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

#: A LIVE CALL TO A ROLE (DEVQA Q50, 2026-09-25: "Two also same thing" — calling
#: the plumber, the bank, the dentist is an event like calling a person). Only
#: the live-call verbs, only "the/my/our <someone>" straight after them, and not
#: the idioms where the object is not who is being called.
_CALL_ROLE = re.compile(
    r"\b(?:call|phone|ring|facetime)\s+(?:back\s+)?(?:the|my|our)\s+"
    r"(?!(?:meeting|event|appointment|shots|roll|list|day|game|order)s?\b)"
    rf"(?!(?:{KIN})\b)[a-z][\w'-]*",
    re.I)

#: Verbs that act on an item already on the list, not on the person.
_ACTS_ON_IT = re.compile(
    r"\b(?:check|cross|tick|strike|knock|take)\s+off|\b(?:delete|remove|scrap|drop|"
    r"cancel|complete|finish|mark|move|push|rename|reschedule|done\s+with)\b", re.I)

_WRITTEN = re.compile(r"\b(?:email|e-mail|text|message|msg|write\s+to|send|ping|dm)\b", re.I)

_TODO_DESTINATION = re.compile(
    r"\b(?:to|on|onto|in|into|from|off)\s+(?:my|the|our)\s+"
    r"(?:to[- ]?do\s+|task\s+|shopping\s+|grocery\s+)?(?:list|lists|tasks|to[- ]?dos?)\b", re.I)


def names_the_list(text: str) -> bool:
    """"add ... to my list" — naming the to-do list keeps anything a to-do."""
    return bool(_TODO_DESTINATION.search(text or ""))


def is_encounter(text: str) -> bool:
    """True when the words bring the speaker together with a named person —
    or, by Q50, put them on a live call with a role ("call the plumber")."""
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
    return is_role_call(t)


def is_role_call(text: str) -> bool:
    """True for a live call to a ROLE rather than a named person — "call the
    plumber", "phone my accountant" (DEVQA Q50). Such a call is an event, and
    its executor also files a LINKED to-do beside it (Gil, 2026-09-25: *"make
    it a to-do in addition, in parallel, and it should be linked"*): a call to
    a business is a job that can slip past its slot, which a call to mum is not."""
    t = (text or "").strip()
    if not t or _TODO_DESTINATION.search(t):
        return False
    m = _CALL_ROLE.search(t)
    if not m or re.search(r"\boff\b", t[m.end():m.end() + 12], re.I):
        return False
    head = t[:m.start()].lower()
    # "check off / delete / move call the plumber" acts on a to-do that exists
    return not (_WRITTEN.search(head[-24:]) or _ACTS_ON_IT.search(head[-24:]))
