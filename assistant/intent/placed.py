"""Does a command say (or let us infer) WHERE a new thing goes? — DEVQA Q63.

Gil, 2026-09-27: *"if the date isn't given, then we can just make it a to-do,
to be honest... if we don't have a time to put in at all, and nothing to infer
where we would go, then it would just become a to-do."*

One reader for the three places that ask it — segmentation's FastSeg, its
`run` over several envelopes, and the front door — so they cannot drift. The
command is PLACED when any of these holds, anywhere in the WHOLE command:

  * a day or a clock (`find_time_refs`), or "now";
  * a person (Q47 B / Q50 put those on the calendar at 09:00);
  * a sequence — its parts are chained from the one before (Q51);
  * the speaker naming the calendar or an EVENT as the thing to make
    ("create an event …", "add this on my calendar").

A command that is none of these said nothing about where, and an item the
tagger would have called an event only because nothing said otherwise becomes
a to-do.
"""
from __future__ import annotations

import re

_NOW = re.compile(r"\b(?:right\s+now|now|immediately|asap)\b", re.I)
_SAYS_EVENT = re.compile(
    r"\b(?:an?|the|new)\s+(?:calendar\s+)?(?:event|appointment)\b"
    r"|\b(?:on|to|in|onto)\s+(?:my|the)\s+(?:calendar|calender|schedule|diary|agenda)\b",
    re.I)


def nothing_to_infer(text: str) -> bool:
    """True when the whole command names no day, clock, person, sequence or
    calendar — the condition under which Q63 files a to-do."""
    from assistant.engine.segmentation.fastseg.fastseg import find_time_refs
    from assistant.intent.sequence import is_a_sequence, names_someone
    t = text or ""
    return not (find_time_refs(t) or _NOW.search(t) or names_someone(t)
                or is_a_sequence(t) or _SAYS_EVENT.search(t))
