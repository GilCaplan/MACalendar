"""Audit the dataset against the PRODUCT's conventions and emit overrides.

The HWU-64-derived ground truth encodes its source corpus' worldview: separate
list objects, standing "notify me when" alerts, per-kind compound splits taken
from the source utterances' intents. Our product deliberately differs (no list
objects — Today/General + tags; no standing alerts; "remind me to VERB" with
no clock time is a task even when the source called it an event). Scoring
those rows raw penalizes the engine for being right.

Inputs stay frozen. This script classifies rows by MECHANICAL RULES —
written from dev-region evidence (tier_rank ≤ 600) only, then applied to the
whole dataset without inspecting held-out rows — and writes
`dataset/inputs/convention_overrides.json`, a versioned second layer the
scorer applies as an ADJUSTED metric next to the raw one. Raw `count_ok`
never changes, so every logged run stays comparable.

Treatments (implemented in scripts/score_dataset_run.py):

  noop_ok        an honest nothing is as correct as a sensible creation:
                 pass if (0 creations, 0 mutations) or (≥1 creation, none
                 garbage-titled)
  half_flexible  compound with one half our product legitimately declines
                 (placeholder text, standing alert): pass if total ≥ 1 clean
                 creation
  split_flexible compound whose per-kind split came from source intents our
                 conventions re-file ("remind me to X" halves): pass on
                 total ≥ 2 creations, kinds free
  per_half       the row's `owed` counts, re-read half by half (2026-09-28):
                 pass on ≥ owed events, ≥ owed to-dos, ≥ owed objects and
                 NOTHING CHANGED (every per_half row is creates only, so an
                 update/delete/complete is one nobody asked for); when nothing
                 is owed, only on nothing made either

Run:  python -m scripts.audit_dataset_conventions        # writes + summarizes
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "dataset" / "inputs" / "hwu64_sample.json"
OUT = ROOT / "dataset" / "inputs" / "convention_overrides.json"

_PLACEHOLDER = re.compile(r"\bxx+x\b|[{}]|<insert\b", re.I)
_TRUNCATED = re.compile(r"\b(of|to|the|a|my|for|and|in|with|on|at)\s*[.?!]?$", re.I)
# The verb must act on the LIST ITSELF ("open a new list") — never on an item
# ("add cereal to my shopping list" is a task + tag and stays strictly scored).
# Anchored full-text so any "<item> to my … list" shape falls through; a
# "list of <content>" also falls through (there is something to create).
_LIST_BARE = re.compile(
    r"^(?:\w+[,!]?\s+)?(?:(?:please|can you|could you|i need to|i want to|i'd like to)\s+)*"
    r"(?:open(?: up)?|start|create|make|begin)\s+(?:me\s+)?(?:a|an|another|the)?\s*"
    r"(?:new\s+)?(?:[a-z' -]+\s+)?list(?:\s+(?:called|named)\s+.+)?\s*[.?!]*$", re.I)
_LIST_BARE_ADD = re.compile(r"^(?:please\s+)?add\s+(?:a\s+)?new\s+list\s*[.?!]*$", re.I)
#: A bare list-create as ONE CLAUSE of a compound. `_LIST_BARE` is anchored to
#: the whole text, so a compound whose other half is a real ask never matched
#: it and the bare half was scored as an ask the engine owed an object.
#:
#: Gil, 2026-09-20 (DEVQA Q37): a list with no name is REFUSED — "I couldn't
#: tell what to call it" — and the gold rows that expect a creation are the
#: wrong half of the disagreement. Content still disqualifies it: "make a new
#: list OF DOG BREEDS" names what goes in the list and owes an object, which
#: is why the trailing group stops at a clause end rather than allowing "of".
_LIST_BARE_HALF = re.compile(
    r"(?:^|[.;!?]\s*|\b(?:and|also|then)[,\s]+)"
    r"(?:(?:please|can you|could you|pda|alexa|olly|hey siri)\s+)*"
    r"(?:open(?: up)?|start|create|make|begin)\s+(?:me\s+)?"
    r"(?:a|an|another|the)?\s*(?:new\s+)?list"
    r"(?:\s+for\s+(?:me|us))?\s*(?:please)?\s*(?:[.;!?,]|$)", re.I)
_ALERT = re.compile(
    r"\b(notify|alert|tell)\s+me\s+(when|if|whenever|every time)\b"
    r"|\blet me know\s+(when|if)\b", re.I)
_REMIND_TO = re.compile(r"\bremind (me )?to\b", re.I)


_CLAUSE = re.compile(r"\s*(?:,|\.|—|;)?\s*\b(?:and then|and also|also|and|then)\b\s*"
                     r"|\s*[.;—]\s+", re.I)


def _list_management(text: str) -> "tuple[int, int] | None":
    """(clauses, list-management clauses) when any clause is Q52 list
    management, else None."""
    import sys
    sys.path.insert(0, str(ROOT))
    from assistant.intent.junk import junk_reason
    parts = [p for p in _CLAUSE.split(text) if p and p.strip()]
    junk = sum(1 for p in parts if junk_reason(p))
    return (len(parts), junk) if junk else None



# --- Per-half re-reading (2026-09-28, from the DEV triage) -------------------
# A compound is exactly two HWU utterances joined by one of five connectives
# (`fetch_hwu64_sample._CONNECTIVES`), the first half of the first kind in the
# label. So the key can be re-derived HALF BY HALF from the text alone — never
# from the engine's output — and each half is owed what the rulings say:
#
#   owed nothing   Q38 a clause naming nothing ("add an event to my calendar"),
#                  an anaphor with nothing to point at in a fresh store ("please
#                  repeat this event", "add this to the list"), Q52 list
#                  management (the engine's reader PLUS this key's own list —
#                  the key must not inherit the engine's misses), a question
#   kind free      Q25/Q47: a clock makes an event, no clock a to-do; a day
#                  with no clock is unruled (Q63 declined it), so either kind
#                  passes for an event half without a clock and for a to-do
#                  half with one. The COUNT is still owed.
#
# Treatment `per_half` carries the owed counts; the scorer passes a row when
# it made at least that many events, to-dos and objects — and, when nothing
# is owed, only if it made nothing and changed nothing (Q38: a row the
# speaker must find and delete is worse than a refusal).

_CONNECTIVE_SPLITS = (". Also, ", " — and ", ", and then ", " and also ", " and ")

_WAKE_POLITE = (r"^\W*(?:(?:hey|ok|okay)\s+)?(?:(?:alexa|olly|pda|google|siri)\b[,.]?\s*)?"
                r"(?:(?:please|pls|plz|can you|could you|would you|will you|i need to|"
                r"i want to|i'd like to|i would like to|i want you to)\s+)*")
_CAL = r"(?:calendar|calender|calandar|calander|schedule|agenda)"
_NAMELESS = re.compile(
    _WAKE_POLITE +
    r"(?:(?:add|set(?:\s+up)?|create|make|schedule|put|book)\s+(?:me\s+)?"
    r"(?:(?:a|an|the|my|one|another|new|recurring)\s+)*"
    r"'?(?:(?:calendar\s+)?event|appointment|reminder|meeting|entry|date|thing)'?"
    r"(?:\s+(?:to|in|on|into)\s+(?:my\s+|the\s+)?" + _CAL + r")?"
    r"|remind\s+me\s+about\s+(?:a\s+)?thing\s+at\s+time"
    r"|add\s+(?:an?\s+)?event\s+with\s+these\s+people)"
    r"(?:\s+please)?\s*[.?!]*$", re.I)
_ANAPHOR = re.compile(
    _WAKE_POLITE +
    r"(?:(?:repeat|set)\s+(?:this|that)\s+(?:event|date|meeting|reminder)"
    r"(?:\s+to\s+repeat(?:\s+reminder)?)?"
    r"|(?:add|put|save)\s+(?:this|that|it)\s+(?:to|on|in)\s+(?:the|my)\s+list)"
    r"\s*[.?!]*$", re.I)
# Q52 by this key's own reading, beside the engine's `junk_reason`: the list
# itself is the object ("add a new list", "show a new list", "update list
# with new item", "refresh the list with new one"). "<thing> to my list" and
# "list of <contents>" (Q33) never match — both owe a to-do.
_LIST_OP = re.compile(
    _WAKE_POLITE +
    r"(?:add|show|set|prepare|open(?:\s+up)?|start|create|make|begin|save|reopen|refresh|update)"
    r"\s+(?:me\s+)?(?:(?:a|an|the|my|new|another)\s+)*(?:\w+\s+)?list"
    r"(?:\s*(?:for\s*(?:me|us|\.+)|with\s+(?:a\s+)?new\s+(?:items?|one)))?"
    r"(?:\s+please)?\s*[.?!]*$", re.I)
_QUESTION = re.compile(r"^\W*(?:when|what|where|who|which|how|do|does|did|is|are|am|"
                       r"was|were|have|has)\b[^?]*\?\s*$", re.I)
_CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?\s?m\b\.?|p\.?\s?m\b\.?)|\b\d{1,2}:\d{2}\b"
                    r"|\bnoon\b|\bmidnight\b|o'?clock\b", re.I)


_CAL_NAMED = re.compile(r"\b(?:to|in|on|into)\s+(?:my\s+|the\s+)?" + _CAL + r"\b", re.I)
_DAY = re.compile(
    r"\b(?:today|tonight|tomorrow|tommorow|tomorrows|yesterday|weekend|week|month|year|"
    r"mon|tues?|wed|thur?s?|fri|sat|sun)(?:day)?s?\b"
    r"|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b|\b\d{1,2}/\d{1,2}\b|\bevery\b|\bdaily\b", re.I)
_STANDING = re.compile(r"\bremind\s+me\s+(?:when|if|whenever)\b", re.I)


def _owed_nothing(half: str) -> "str | None":
    h = half.strip()
    if _PLACEHOLDER.search(h):
        return "placeholder"
    if _NAMELESS.match(h):
        return "nameless"
    if _ANAPHOR.match(h):
        return "anaphor"
    lm = _list_management(h)
    if _LIST_OP.match(h) or (lm and lm[0] == lm[1]):   # every clause of it
        return "list_management"
    if _ALERT.search(h) or _STANDING.search(h):
        return "standing_alert"
    if _QUESTION.match(h):
        return "question"
    return None


def _halves(text: str) -> "list[tuple[str, str]]":
    """Every (first, second) reading of a compound — one per occurrence of
    the first connective found. More than one means the join is ambiguous."""
    for conn in _CONNECTIVE_SPLITS:
        idx = [m.start() for m in re.finditer(re.escape(conn), text)]
        if idx:
            return [(text[:i], text[i + len(conn):]) for i in idx]
    return []


def per_half(row: dict) -> "tuple[str, dict] | None":
    """(class, owed) for a compound the rulings re-read, else None."""
    kinds = row["intent"].split("+")
    readings = _halves(row["text"])
    if not readings:
        return None
    best = None
    for a, b in readings:
        reasons = [_owed_nothing(a), _owed_nothing(b)]
        if len(readings) > 1 and not any(reasons):
            continue                   # an ambiguous join needs a clear half
        owed = {"events": 0, "tasks": 0, "total": 0}
        classes = []
        for half, kind, why in zip((a, b), kinds, reasons):
            if why:
                classes.append(why)
                continue
            owed["total"] += 1
            clocked = bool(_CLOCK.search(half))
            # Q63: no day AND no clock with the calendar named is an event
            placed = bool(_CAL_NAMED.search(half)) and not _DAY.search(half)
            if kind == "event" and not clocked and not placed or kind == "task" and clocked:
                classes.append("clock_kind")      # Q25/Q47: kind free
            else:
                owed["events" if kind == "event" else "tasks"] += 1
        if classes:
            hit = ("+".join(sorted(set(classes))), owed)
            if best is None or owed["total"] > best[1]["total"]:   # ambiguous: owe more
                best = hit
    return best

def classify(row: dict) -> "tuple[str, str] | tuple[str, str, dict] | None":
    """(class, treatment[, owed]) for a row our conventions re-read, else None.

    Compounds are read half by half first (`per_half`, which subsumes the
    older whole-row compound classes); single asks keep the older classes and
    gain the per-half reasons a whole command can be owed nothing for."""
    text, scen, intent = row["text"], row["scenario"], row["intent"]
    creator = intent in ("set", "createoradd")
    if scen == "compound" and intent in ("event+event", "event+task", "task+task"):
        hit = per_half(row)
        if hit:
            return hit[0], "per_half", hit[1]
    old = _classify_whole(row)
    if old or not creator or scen == "compound":
        return old
    why = _owed_nothing(text)
    if why in ("standing_alert", "placeholder"):
        return why, "noop_ok"            # as the whole-row classes treat them
    if why:
        return why, "per_half", {"events": 0, "tasks": 0, "total": 0}
    return None


def _classify_whole(row: dict) -> "tuple[str, str] | None":
    """The whole-row classes (2026-09-05 .. 2026-09-27)."""
    text, scen, intent = row["text"], row["scenario"], row["intent"]
    creator = intent in ("set", "createoradd")
    if _PLACEHOLDER.search(text):
        if scen == "compound":
            return "placeholder", "half_flexible"
        if creator:
            return "placeholder", "noop_ok"
        return None                      # query/remove already expect nothing
    if creator and scen != "compound" and _TRUNCATED.search(text.strip()):
        return "truncated", "noop_ok"
    if scen == "lists" and intent == "createoradd" and (
            _LIST_BARE.match(text.strip()) or _LIST_BARE_ADD.match(text.strip())):
        return "list_create_bare", "noop_ok"     # no list objects here
    if scen == "compound" and _LIST_BARE_HALF.search(text):
        return "list_create_bare", "half_flexible"
    if (creator or scen == "compound") and _list_management(text):
        # DEVQA Q52 (2026-09-25): managing lists (open / bring up / save / start
        # / delete a list) is not something this product does — the engine
        # refuses it by `intent/junk.py`. Read clause by clause with that same
        # reader (Q47's shared-reader precedent): all of it list management ->
        # an honest nothing; a real ask beside it -> only the real ask is owed.
        parts, junk = _list_management(text)
        return "list_management", ("noop_ok" if junk == parts else "half_flexible")
    if _ALERT.search(text):
        if scen == "compound":
            return "standing_alert", "half_flexible"
        if creator:
            return "standing_alert", "noop_ok"   # no standing-alert object
        return None
    if scen == "compound" and intent in ("event+event", "event+task") \
            and _REMIND_TO.search(text):
        return "remind_half", "split_flexible"   # remind-to may be a task
    return None


def build() -> dict:
    rows = json.loads(FIXTURE.read_text())["rows"]
    out: dict[str, dict] = {}
    for r in rows:
        hit = classify(r)
        if hit:
            out[r["text"]] = {"class": hit[0], "treatment": hit[1]}
            if len(hit) > 2:
                out[r["text"]]["owed"] = hit[2]
    return {
        "version": 2,
        "generated": "2026-09-28",
        "note": ("Mechanical rules mined from dev region (tier_rank<=600) "
                 "only, applied dataset-wide. Raw count_ok is never changed; "
                 "the scorer reports these as count_ok_adj. 2026-09-20: the "
                 "list_create_bare class gained its COMPOUND form (DEVQA "
                 "Q37) — a list with no name is refused, so a compound whose "
                 "other half is a real ask is half_flexible. 68 rows joined; "
                 "4 moved from remind_half, being more specifically a "
                 "declinable list half than a re-filed reminder. "
                 "2026-09-27: list_management (DEVQA Q52) — any clause the "
                 "engine's junk reader calls list management is owed nothing. "
                 "2026-09-28 (v2): per_half — a compound is re-read half by "
                 "half (Q38 nothing named, anaphors, Q52 by this key's own "
                 "reading too, standing alerts, placeholders, questions owe "
                 "nothing; Q25/Q47 an unclocked event half or a clocked to-do "
                 "half is kind-free), and a single ask naming nothing owes "
                 "nothing — with nothing made and nothing changed."),
        "rows": out,
    }


def main() -> int:
    doc = build()
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    rows = json.loads(FIXTURE.read_text())["rows"]
    dev = {r["text"] for r in rows if int(r["tier_rank"]) <= 600}
    from collections import Counter
    total = Counter(v["class"] for v in doc["rows"].values())
    in_dev = Counter(v["class"] for t, v in doc["rows"].items() if t in dev)
    print(f"overrides written: {len(doc['rows'])}/{len(rows)} rows -> {OUT}")
    print(f"{'class':<18}{'dev(<=600)':>11}{'all':>7}")
    for cls, n in total.most_common():
        print(f"{cls:<18}{in_dev.get(cls, 0):>11}{n:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
