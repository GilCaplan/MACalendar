"""Asks the assistant throws out as JUNK — and says why (DEVQA Q52).

Gil, 2026-09-25, on requests to manage LISTS themselves ("open grocery list",
"delete this list", "save the new list", "what lists do I have"): *"just ignore
and throw out as junk... just mark so we can see why we threw it out."* The
app has no list objects (2026-09-05: lists stay Today/General plus tags), so
there is nothing such a request could do; sending it to the model cost a call
on ~6% of real commands (152 of 2,699 in the non-sealed pool) to produce
nothing useful.

What is NOT junk, by earlier rulings:
  * putting something ON a list — "add milk to my grocery list" is a to-do
  * a list NAMED FOR ITS CONTENTS — "make a list of dog breeds" is a to-do
    called "dog breeds" (Q33)
  * reading what is on a list — "read my shopping list" is a to-do query

One module so the front door (FastRule) and segmentation's tagger agree.
`junk_reason(words)` is the reason string, or None.
"""
from __future__ import annotations

import re

#: The reason, as the speaker reads it in the reply and the review (Q52).
LIST_MANAGEMENT = "managing lists isn't something I do — lists live as tags on your to-dos"

_PRE = (r"^\W*(?:(?:hey|ok|okay)\s+)?(?:(?:alexa|olly|pda|google|cortana|siri)\b[,.]?\s*)?"
        r"(?:(?:please|pls|can you|could you|would you|will you|i want you to|i need you to|"
        r"i want to|i need to|i'd like to|i would like to|let's|go ahead and|just)\s+)*")
_LIST = (r"(?:(?:a|an|the|my|this|that|these|those|all|all of my|me|us|another|new|empty|blank|"
         r"separate|whole|entire|to-?do|todo|to\s+do|things?\s+to\s+do|grocery|groceries|shopping|"
         r"check|wish|[a-z]+'s)\s+){0,5}(?:check)?lists?")
_TAIL = (r"(?:\s*,?\s+(?:for me|for us|please|now|right now|from the database|google|alexa|olly|siri))*"
         r"\s*[.?!]*$")

_PATTERNS = [
    # an UNNAMED list made ("create a new list", "make me a list") — Q37 already
    # refused it for want of a name; there is nothing to make either way
    re.compile(_PRE + r"(?:create|make|start|set\s+up|begin|build|get)\s+(?:me\s+)?" + _LIST + _TAIL, re.I),
    # an operation ON a list as a container
    re.compile(_PRE + r"(?:open|save|delete|destroy|remove|clear|reset|close|rename|erase|wipe|empty|"
               r"get\s+rid\s+of|bring\s+up|pull\s+up|go\s+to|find)\s+" + _LIST + _TAIL, re.I),
    # asking which lists exist
    re.compile(_PRE + r"(?:what|which)\s+lists?\b", re.I),
    re.compile(r"\bnames?\s+of\s+(?:all\s+)?(?:my\s+|the\s+)?lists\b", re.I),
    re.compile(r"\bwhat\s+(?:do|does)\s+my\s+lists?\s+look\s+like\b", re.I),
    re.compile(r"\bhow\s+many\s+lists\b", re.I),
]


def junk_reason(words: str) -> "str | None":
    """Why these words are thrown out, or None when they are a real ask."""
    t = (words or "").strip()
    if not t:
        return None
    if any(rx.search(t) for rx in _PATTERNS):
        return LIST_MANAGEMENT
    return None
