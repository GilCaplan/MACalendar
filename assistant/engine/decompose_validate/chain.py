"""A SEQUENCE's untimed parts start when the part before them ends (DEVQA Q51).

Gil, 2026-09-25: *"X followed by Y followed by Z … if the time isn't given …
maybe Y is just the following hour after X, or after the length of the X
event."* Segmentation cuts at the sequence words and says so on each item
(`Item.relation`, kind `sequence`); this is the part of decompose_validate that
reads that relation and fills what the speaker left out:

  * an item with a clock of its OWN keeps it, and the chain runs on from it
  * an untimed item in a sequence starts at the previous item's END plus the
    gap — the chain beats a meal's own hour ("gym at 9, then lunch" is lunch
    at 10:00, *"we want to be consistent"*)
  * the previous item's end is its stated end, else its start plus its stated
    duration ("for 2 hours"), else plus the default length
  * the item lasts its own stated duration, else the default length
  * a part that names no DAY of its own takes the previous part's day; a part
    that names a DIFFERENT day starts fresh ("…, then on friday lunch" is not
    after the gym in time), and what follows chains from it
  * a TO-DO in a sequence is chained too, as an event AND a linked to-do
    ("walk the dog at 5, then do the laundry" — Gil: *"laundry would be like
    a linked one, a to-do and a[n event] at 6 p.m."*)
  * "right after <something said earlier>" chains from THAT item, whatever
    the relation to the one immediately before

The default length and gap are SETTINGS (`assistant/event_defaults.py`, per
category, then global, then 60 / 0) — the same numbers `CalendarIntent` uses
for any event whose end was not said, so a chained event and a lone one agree.
"""
from __future__ import annotations

import re

#: "…right after davening", "…straight after the dentist", "…after the gym":
#: the named earlier thing, at the END of an item's words.
_AFTER_NAMED = re.compile(
    r"\s*,?\s*\b(?:right\s+|straight\s+|just\s+)?after\s+(?:the\s+|my\s+|our\s+)?"
    r"(?P<name>[a-z][\w' -]{1,40})$", re.I)

#: A sequence part keeps its own day only when its own words name one.
_DAY_KINDS = {"date", "range"}


from assistant.common.timeutil import to_hhmm as _hhmm      # noqa: E402
from assistant.common.timeutil import to_minutes as _minutes  # noqa: E402


def _names_a_day(source: str) -> bool:
    from assistant.engine.segmentation.fastseg.fastseg import find_time_refs
    return any(r.kind in _DAY_KINDS for r in find_time_refs(source or ""))


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2}


def _anchor_by_name(i: int, items: list) -> "tuple[int, str] | None":
    """(index of the earlier item "right after X" names, the phrase), or None."""
    m = _AFTER_NAMED.search(items[i].text or "")
    if not m:
        return None
    want = _words(m.group("name"))
    if not want:
        return None
    best, score = None, 0
    for j in range(i):
        n = len(want & _words(items[j].text))
        if n > score:
            best, score = j, n
    return (best, m.group(0)) if best is not None else None


def _start_of(d: dict, item) -> "int | None":
    """When an earlier item starts, for chaining — its own clock, else the
    hour `CalendarIntent` would give an untimed EVENT (a meal's, else 09:00).
    An untimed to-do has no start, so nothing chains from it."""
    from assistant.actions.calendar.intent import meal_hour
    if d.get("start_time"):
        return _minutes(d["start_time"])
    if item.kind == "event":
        return _minutes(meal_hour(item.text) or "09:00")
    return None


def _length_of(item) -> int:
    from assistant import event_defaults
    from assistant.engine.decompose_validate import resolve as _resolve
    return (_resolve.resolve_duration(item.text)
            or event_defaults.length_minutes(event_defaults.category_of(item.text)))


def chain(items: list, dicts: list) -> list:
    """Fill the untimed parts of every sequence, in order. `dicts` are the
    resolved values, aligned with `items`; both are updated in place. Returns
    the fixes, one per chained item, for the trace."""
    from assistant import event_defaults
    from assistant.engine.decompose_validate import checks as _checks

    fixes = []
    for i in range(1, len(items)):
        item, d = items[i], dicts[i]
        rel = getattr(item, "relation", None) or {}
        anchored = _anchor_by_name(i, items)
        if rel.get("kind") != "sequence" and not anchored:
            continue
        if item.kind not in ("event", "task") or d.get("start_time") or d.get("recurrence"):
            continue                                  # its own clock wins
        j = anchored[0] if anchored else i - 1
        prev, p = items[j], dicts[j]
        own_day = _names_a_day(item.source or item.text)
        if own_day and d.get("date") and p.get("date") and d["date"] != p["date"]:
            continue                                  # a new day starts fresh
        begin = _start_of(p, prev)
        if begin is None:
            continue
        end_prev = (_minutes(p["end_time"]) if p.get("end_time")
                    else begin + _length_of(prev))
        start = end_prev + event_defaults.gap_minutes(event_defaults.category_of(item.text))
        end = start + _length_of(item)
        day = p.get("date")
        if start >= 24 * 60:                          # rolled past midnight
            days, offset = start // (24 * 60), (start // (24 * 60)) * 24 * 60
            start, end = start - offset, end - offset
            if day:
                import datetime as _dt
                day = (_dt.date.fromisoformat(day) + _dt.timedelta(days=days)).isoformat()
        end = min(end, 24 * 60 - 1)
        if not _names_a_day(item.source or item.text) and day:
            d["date"] = day
        d["start_time"], d["end_time"] = _hhmm(start), _hhmm(end)
        # What the chain decided, kept apart from the ordinary slots: the object
        # pass re-reads each item from its OWN words, which name no clock here,
        # so without this the model's (or a meal's) hour would win on the way
        # to the object. `run_objects` applies it last.
        item.slots["chained"] = {"date": d.get("date"), "start_time": d["start_time"],
                                 "end_time": d["end_time"], "after": prev.id}
        if anchored:
            item.text = item.text[:len(item.text) - len(anchored[1])].strip() or item.text
        if item.kind == "task":
            # Chained, so it happens at a time — an event — and it is still
            # something to do: the linked to-do beside it (Q51, like Q50's).
            item.kind = "event"
            item.slots["linked_todo"] = True
        fixes.append(_checks.Fix("sequence_chain", "start_time", None, d["start_time"],
                                 f"follows {prev.text!r}, which ends at {_hhmm(end_prev)}"))
    return fixes
