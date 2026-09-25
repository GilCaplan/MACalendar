"""The canonical rendering of an object, and which of its fields are CLAIMS.

    claims(action, intent)            -> [Claim, …]  fixed order, defaults dropped
    render_line(action, intent)       -> "create event · title=dentist · …"
    render_block(oid, action, intent) -> the judge's view of the same object

Gil, 2026-09-10: *"the judge looks at each object (or the tostring of it,
because looking at the pointer reference is kind of meaningless)."* This is that
tostring — ONE definition with two renderings, rather than two definitions that
agree today and drift next month.

## Why the field list is a table and not `model_dump()`

A pydantic dump of a `CalendarIntent` is twelve keys of which eight are usually
`None`, and handing that to a judge invites it to comment on the nulls. Prompt
SHAPE moves judge scores on its own — rubric order, option position and score
IDs all do, measurably — so the shape here is fixed rather than incidental:

    only fields that are SET and not at a default nobody spoke are rendered
    the ORDER is fixed, never `dict` order
    the panel's line and the judge's block come from the same `claims()` call

## The part that decides whether this stage can work at all

**Not every claim is answerable by a model, and the temporal ones are not.**
`CalendarIntent.fill_defaults` stamps `date = today`, `start_time = the current
hour` and `end_time = start + 1h` the moment the object exists. So by the time
there IS an object, its date is present whether or not anybody said one, and
asking a model "which words support date=2026-09-10?" gets `none` on every
correct event that happens to be today. That is a false-flag generator, not a
check.

`item.slots` is the honest answer. `decompose_validate` RESOLVED the values from
the words and `build` COPIES them (`build.py::_value_kwargs`, whose own docstring
names this same trap). So:

    a temporal field present on the intent and ABSENT from slots
        = a pydantic default = the words never said it        DETERMINISTIC

Which leaves the model exactly the fields it is good at — the ones made of
WORDS: title, target, attendees, location. Those are also where invention
actually happens (the cycle-7 fabricated event; the event titled "event"). This
is the project's own deterministic-first rule applied to a stage that had not
had it applied: a model is asked only what the deterministic reading cannot
answer.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

#: Which slot key backs each temporal claim, per action. RESTATED from
#: `fastrule/build.py::_VALUE_MAP` rather than imported, following that module's
#: own convention for `VALUE_FIELDS`: the two stages are contract-coupled, not
#: implementation-coupled, so a change on that side must turn a TEST red here
#: instead of silently re-shaping this reading. `test_engine_llmjudge.py` pins
#: the agreement.
SLOT_BACKED = {
    "create_event": {"date": "date", "start_time": "start_time",
                     "end_time": "end_time", "recurrence": "recurrence",
                     "recur_days": "recur_days", "recur_until": "recur_until",
                     "reminder_minutes": "reminder_minutes"},
    "create_todo": {"due_date": "date"},
    "update_event": {"new_date": "date", "new_start_time": "start_time",
                     "new_end_time": "end_time"},
    "delete_event": {"match_date": "date", "match_start_time": "start_time"},
    "update_todo": {"new_due_date": "date"},
    "query_schedule": {"date": "date"},
}

#: Claim fields in render order, per operation family: (attribute, label, kind).
_EVENT_CLAIMS = (
    ("title", "title", "text"),
    ("match_title", "target", "text"),
    ("date", "date", "date"),
    ("new_date", "new_date", "date"),
    ("match_date", "match_date", "date"),
    ("start_time", "start_time", "clock"),
    ("new_start_time", "new_start_time", "clock"),
    ("match_start_time", "match_start_time", "clock"),
    ("end_time", "end_time", "clock"),
    ("new_end_time", "new_end_time", "clock"),
    ("recurrence", "recurrence", "text"),
    ("recur_days", "recur_days", "list"),
    ("recur_until", "recur_until", "date"),
    ("attendees", "attendees", "list"),
    ("location", "location", "text"),
    ("reminder_minutes", "reminder_minutes", "minutes"),
)

_TODO_CLAIMS = (
    # `CreateTodoIntent` carries `titles` (plural) and the loop in `claims()`
    # expands it, so this row is the FALLBACK for a todo intent that carries a
    # singular `title` instead. Without it such an object produced NO claims at
    # all and was therefore unjudgeable — every check passed by vacancy. Found
    # 2026-09-10, when the ask diff that used to cover for it went away.
    ("title", "title", "text"),
    ("match_title", "target", "text"),
    ("due_date", "due_date", "date"),
    ("new_due_date", "new_due_date", "date"),
    ("tags", "tags", "list"),
)

#: Values a field carries when nobody said anything — never a claim.
_DEFAULTS = {"list_name": {"today", ""}, "priority": {"none", ""}}


@dataclass(frozen=True)
class Claim:
    """One thing the object asserts, and who can check it.

    `slot_key` says whether the claim can be checked DETERMINISTICALLY against
    `item.slots`. `kind` says what the claim is MADE OF. They are not the same
    question, and reading one as the other is a defect this class shipped:

    > *"when `slot_key` is None the claim is made of words"*

    False. `match_date` and `match_start_time` on an `update_event` carry a
    RESOLVED value — `2026-09-16` — and are absent from `SLOT_BACKED`, because
    that table maps the values `build` COPIES from slots and a match-date is not
    one. So they had `slot_key is None` and were treated as words. Nothing
    noticed while the model was the one being asked, since a model shown
    "which words gave match_date=2026-09-16" simply answers something. It
    surfaced the moment a DETERMINISTIC test was pointed at the same claims and
    reported *"the words never said 2026"* on a correct object (2026-09-10).

    So: ask `is_words` before applying a grounding test, never `needs_model`.
    """

    label: str
    rendered: str
    raw: str
    slot_key: "str | None" = None
    kind: str = "text"

    @property
    def needs_model(self) -> bool:
        return self.slot_key is None

    @property
    def is_words(self) -> bool:
        """Is this claim's value made of the speaker's WORDS, so that asking
        whether they said it is a question with an answer?"""
        return self.kind in ("text", "list")


def _fmt_date(v) -> str:
    """`2026-09-14` -> `2026-09-14 (Monday 14 September)` — the parenthetical is
    what would let a reader connect the value to "next monday" in the words."""
    s = str(v or "").strip()
    try:
        d = _dt.date.fromisoformat(s)
    except (ValueError, TypeError):
        return s
    return f"{s} ({d.strftime('%A %-d %B')})"


def _fmt_clock(v) -> str:
    s = str(v or "").strip()
    try:
        t = _dt.datetime.strptime(s, "%H:%M").time()
    except (ValueError, TypeError):
        return s
    hour = t.hour % 12 or 12
    suffix = "am" if t.hour < 12 else "pm"
    spoken = f"{hour}{'' if t.minute == 0 else ':%02d' % t.minute}{suffix}"
    return f"{s} ({spoken})"


def _fmt_minutes(v) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return str(v)
    if n >= 60 and n % 60 == 0:
        return f"{n} ({n // 60} hour{'s' if n != 60 else ''} before)"
    return f"{n} ({n} minutes before)"


_FORMAT = {"date": _fmt_date, "clock": _fmt_clock, "minutes": _fmt_minutes}


def _format(kind: str, value) -> str:
    if kind == "list":
        return ", ".join(str(x) for x in value)
    return _FORMAT.get(kind, lambda v: str(v).strip())(value)


def _is_set(attr: str, value) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    if attr in _DEFAULTS and str(value).strip().lower() in _DEFAULTS[attr]:
        return False
    return True


def _is_derived_end(attr: str, intent) -> bool:
    """An `end_time` that is exactly start + the default length (an hour
    unless Settings says otherwise) is `fill_defaults` doing its
    job, not an assertion about the words.

    It is dropped from the claims entirely rather than reported unsupported: it
    is present on EVERY event, so flagging it would put one finding on every
    correct row — and a check that fires everywhere tells you nothing. When the
    speaker DID say "three to four", the slot is there and the claim survives
    through the ordinary path; when they said "three to five" the value is not
    start+1h and it survives too.
    """
    if attr not in ("end_time", "new_end_time"):
        return False
    start = getattr(intent, "start_time", None) or getattr(intent, "new_start_time", None)
    end = getattr(intent, attr, None)
    try:
        sh, sm = map(int, str(start).split(":"))
        eh, em = map(int, str(end).split(":"))
    except (ValueError, AttributeError, TypeError):
        return False
    start_min, end_min = sh * 60 + sm, eh * 60 + em
    # The length `fill_defaults` adds is a SETTING since DEVQA Q51 (global,
    # or the title's category's own) — read from the same place, or a user
    # who set 90 minutes would see every defaulted end reported as invented.
    try:
        from assistant import event_defaults
        length = event_defaults.length_minutes(
            event_defaults.category_of(getattr(intent, "title", "") or ""))
    except Exception:
        length = 60
    if start_min + length >= 24 * 60:
        # `CalendarIntent.fill_defaults` caps an end that would cross
        # midnight at "23:59" instead of rolling into the next day — a
        # start hour of 23 with no time said produces a 59-minute gap, not
        # 60, and this check missed it: a correct default got reported as
        # an EXTRA invented value on top of the start time it already is,
        # on every event fill_defaults dates near midnight.
        return end_min == 23 * 60 + 59
    return end_min - start_min == length


def claims(action: str, intent, slots: "dict | None" = None) -> "list[Claim]":
    """The object's atomic claims, fixed order.

    `titles` expands to one claim PER title — "buy milk, eggs and bread" is
    three asks and therefore three claims, not one list-shaped one.

    `slots` is only needed to decide which claims are slot-backed; passing None
    makes every claim a word claim, which is the right reading when there is no
    item behind the object (the isolation board's synthetic rows).
    """
    if intent is None:
        return []
    backing = SLOT_BACKED.get(action or "", {})
    out: "list[Claim]" = []

    titles = list(getattr(intent, "titles", None) or [])
    quantities = list(getattr(intent, "quantities", None) or [])
    for i, t in enumerate(titles):
        label = "title" if len(titles) == 1 else f"title_{i + 1}"
        qty = quantities[i] if i < len(quantities) else 1
        rendered = str(t).strip()
        if qty and qty != 1:
            rendered = f"{rendered} (×{qty})"
        out.append(Claim(label, rendered, str(t).strip(), kind="text"))

    table = _TODO_CLAIMS if "todo" in (action or "") else _EVENT_CLAIMS
    for attr, label, kind in table:
        if label == "title" and titles:
            continue                      # already expanded above
        value = getattr(intent, attr, None)
        if not _is_set(attr, value) or _is_derived_end(attr, intent):
            continue
        out.append(Claim(label, _format(kind, value), str(value).strip(),
                         slot_key=backing.get(attr), kind=kind))
    return out


def unsupported_by_slots(action: str, intent, slots: "dict | None") -> "list[Claim]":
    """The slot-backed claims the words never said — a pydantic default wearing
    a resolved value's clothes. Deterministic; no model is consulted."""
    have = slots or {}
    return [c for c in claims(action, intent, slots)
            if c.slot_key is not None
            and have.get(c.slot_key) in (None, "", [], {})]


def render_line(action: str, intent, slots: "dict | None" = None) -> str:
    """The human one-liner — the panel's string and the judge block's header, so
    the two cannot disagree about what the object contains."""
    parts = [str(action or "unknown").replace("_", " ")]
    parts += [f"{c.label}={c.rendered}" for c in claims(action, intent, slots)]
    return " · ".join(parts)


def render_block(oid: str, action: str, intent, slots: "dict | None" = None) -> str:
    """The judge's view of one object: the line, then ONLY the word-claims as
    the exact keys the model must answer under. Slot-backed claims are not shown
    — they are already decided, and listing them would invite the model to
    re-decide something a deterministic check already answered."""
    lines = [f"[{oid}] {render_line(action, intent, slots)}"]
    for c in claims(action, intent, slots):
        if c.needs_model:
            lines.append(f"    {c.label} = {c.rendered}")
    return "\n".join(lines)
