"""What a correction TELLS us, kept apart from what it STORES.

`memory.set_feedback` stores the record as it stands AFTER the user edits it in
the UI, and `feedback_for_record` stores the original parse with the edited
fields merged in. Either way the stored correction is the FINAL STATE of the
row, which is two different things at once: a corrected READING of the
sentence ("3.45 pm" -> 15:45) and a later CHANGE OF PLAN ('Date <heart>' typed
over 'meeting', a clock dragged to 09:02). The real-usage board found on
2026-09-18 that scoring the second kind punishes the engine for not reading the
speaker's mind and caps the corrected tier forever: 7 of 16 rows had to be
hand-marked unusable, and the headline was computed over 9.

So a correction is ANNOTATED when it is stored (and, for rows stored before
this existed, when the board reads them): per action, which fields CHANGED
against what the engine produced, and which of those new values are REACHABLE
from the words that were said. The rules are deliberately plain and are
printed beside every number that uses them:

- an unchanged field is reachable: the engine's own value, which the speaker
  let stand;
- a changed TITLE is reachable when every content word of the new title is in
  the transcript. "Walk Mark dog" from "Walk, Mark, Stog" is not: that is the
  recogniser's failure and the vocabulary owns it, not the parser;
- a changed CLOCK is reachable when it sits on the five-minute grid people
  speak in: 15:45 yes, 09:02 no, that one was dragged;
- a changed DATE is not reachable: a day moved after the fact is a schedule
  change, and the words that named the day are still the words;
- a changed cadence is reachable when the words carry a cadence word at all.

None of this changes what is stored as the correction; it adds `changed` and
`reachable` beside `action` and `parameters`, and a reader that does not know
them ignores them (Gil, 2026-09-22, the plan behind "can we consider it done").
"""
from __future__ import annotations

import copy
import re

FIELDS = ("title", "date", "start_time", "end_time", "recurrence", "recur_until")

_STOP = frozenset(
    "a an the and or of for to with at on in by from my our your his her its "
    "their this that".split())
_CADENCE = re.compile(
    r"\b(every|each|daily|weekly|monthly|yearly|annually|weekdays?|weekends?)\b",
    re.I)


def norm(field: str, value) -> str:
    """The same normalisation the real-usage board scores with."""
    if value is None:
        return ""
    s = str(value).strip()
    if field == "title":
        s = " ".join(s.lower().split())
    if field in ("start_time", "end_time") and len(s) > 5:
        s = s[:5]                                   # HH:MM:SS -> HH:MM
    if field == "recurrence":
        s = s.lower()
    return s


def _words(text: str) -> set:
    return {w for w in re.split(r"[^a-z0-9']+", (text or "").lower()) if w}


def _content(title: str) -> list:
    return [w for w in _words(title) if len(w) >= 3 and w not in _STOP]


def _on_spoken_grid(clock: str) -> bool:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", clock or "")
    return bool(m) and int(m.group(2)) % 5 == 0


def changed_fields(then_action: dict, gold_action: dict) -> list:
    """The fields whose value differs between what the engine made and the
    correction, in FIELDS order. A changed action name is reported as "action"."""
    out = []
    if (then_action.get("action") or "") != (gold_action.get("action") or ""):
        out.append("action")
    tp = then_action.get("parameters") or {}
    gp = gold_action.get("parameters") or {}
    for f in FIELDS:
        if norm(f, tp.get(f)) != norm(f, gp.get(f)):
            out.append(f)
    return out


def reachable_fields(said: str, then_action: dict, gold_action: dict) -> dict:
    """Per field: can a parser of the words have produced the correction's value?"""
    changed = set(changed_fields(then_action, gold_action))
    gp = gold_action.get("parameters") or {}
    out = {}
    for f in FIELDS:
        if f not in changed:
            out[f] = True
        elif f == "title":
            words = _content(str(gp.get("title") or ""))
            out[f] = bool(words) and all(w in _words(said) for w in words)
        elif f in ("start_time", "end_time"):
            out[f] = _on_spoken_grid(norm(f, gp.get(f)))
        elif f == "date":
            out[f] = False
        else:
            out[f] = bool(_CADENCE.search(said or ""))
    return out


def annotate(said: str, then: list, gold: list) -> list:
    """The correction with `changed` and `reachable` on every action, matched
    to the engine's actions by position (the same pairing the board scores by).
    An action beyond what the engine produced is compared with nothing: every
    field it states is a change."""
    then = then if isinstance(then, list) else [then] if then else []
    gold = gold if isinstance(gold, list) else [gold] if gold else []
    out = []
    for i, g in enumerate(gold):
        if not isinstance(g, dict):
            out.append(g)
            continue
        base = then[i] if i < len(then) and isinstance(then[i], dict) else {}
        g = copy.deepcopy(g)
        g["changed"] = changed_fields(base, g)
        g["reachable"] = reachable_fields(said, base, g)
        out.append(g)
    return out
