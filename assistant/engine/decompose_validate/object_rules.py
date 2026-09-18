"""Post-generation rules that are not value resolution.

Each needs `item.intent` to exist, which is why they run after generate
rather than in the text pass. Grouped by what they are FOR:

  boundaries   junk_event_drop, question_creates_nothing,
               interrogative_create_asks_first  -- PLAN.md argues these
               belong to segmentation; recorded, not yet moved
  text         morning_title_guard
  reply        cadence_round_and_announce
  residual     past_date_bump, now_means_now -- the only two date rules that
               survived the swap, because neither reads the transcript as a
               list: one rolls a past date forward, the other reads "now".

RETIRED FROM `validate.py` (Gil, 2026-09-08). That module was the ported v1
implementation of this stage; `resolve.py` + `checks.py` replaced everything it
did with VALUES, and what remained were rules that were never value resolution.
Leaving them in a file called `validate.py` made the file's name a lie, so they
live where they belong. The original is in `retired/decompose-validate-v1/`.
"""
from __future__ import annotations

import datetime as _dt
import re

from assistant.engine.decompose_validate.targeting import _CREATE_VERB
from assistant.engine.decompose_validate.text_helpers import unsupported_cadence
from assistant.engine.state import EngineState

_NOW_RE = re.compile(r"\b(?:right\s+now|now|immediately|asap)\b", re.I)


_JUNK_TITLES = {"task", "tasks", "todo", "event", "events", "reminder",
                "list", "item", "items"}


_QUESTION_START = re.compile(
    r"^(does|do|did|is|are|was|were|will|can|could|would|what|when|where|who|how)\b", re.I)


_QUERY_OPENER = re.compile(
    r"^(?:please\s+)?(give me|show me|show|list|read( me)?|tell me|check)\b", re.I)


def _rule_past_date_bump(state, intent, today) -> None:
    """Row 29: roll a past date forward without discarding what was said.
    Within a week back it's a weekday that just went → same weekday next week;
    further back the speaker named a calendar day → same day next year."""
    d = getattr(intent, "date", None)
    if not d:
        return
    try:
        dd = _dt.date.fromisoformat(d)
    except ValueError:
        return
    if dd >= today:
        return
    if (today - dd).days <= 7:
        bump = dd
        while bump < today:
            bump += _dt.timedelta(days=7)
    else:
        try:
            bump = dd.replace(year=dd.year + 1)
        except ValueError:                       # 29 Feb → 28 Feb
            bump = dd.replace(year=dd.year + 1, day=28)
    state.add_fix("validate", "past_date_bump", d, bump.isoformat(), note="was in the past")
    intent.date = bump.isoformat()


def _rule_now_means_now(state, intent, transcript) -> None:
    """"now" is a time the speaker gave — book it at the clock, not midnight.

    Real usage, 2026-09-08: "create an event NOW to go out for a run" was
    booked 12 AM–1 AM. The word carries no digits, so the temporal reader
    found nothing, the event fell to the 00:00 default, and both the fast
    parse and the model that inherited it kept it.

    It lives here rather than in the reader because BOTH paths have to be
    caught — FastRule's partial parse and the model's own answer — and this
    stage is the one that sees the produced object either way. Guarded three
    ways: the speaker must actually have said "now", must NOT have said
    midnight, and the object must be sitting on exactly the 00:00 default.
    """
    if not _NOW_RE.search(transcript or ""):
        return
    if re.search(r"\bmidnight\b", (transcript or ""), re.I):
        return
    start = getattr(intent, "start_time", None)
    if start != "00:00":
        return                       # a real time was read; leave it alone
    import datetime as _dt
    now = _dt.datetime.now()
    fresh = f"{now.hour:02d}:{now.minute:02d}"
    intent.start_time = fresh
    end = getattr(intent, "end_time", None)
    if end in ("01:00", "23:59", None, ""):
        intent.end_time = f"{(now.hour + 1) % 24:02d}:{now.minute:02d}"
    state.add_fix("validate", "now_means_now", start, fresh,
                  note="\"now\" is the clock, not midnight")


def _rule_max_duration_cap(state, intent, cfg) -> None:
    """A ceiling on what the ENGINE ITSELF builds. `engine.max_event_hours`
    (default 4) — a `create_event` this stage produced longer than that is
    clipped from the END, keeping the start the speaker gave. Never touches a
    manual GUI edit, which never reaches this stage at all.

    Scoped to the clear case only: `end_after_start` (checks.py) already ran
    and either fixed a same-day span or left a flag on an unresolved one
    (`end <= start`, e.g. an unread wraparound) — that flagged case is not
    this rule's to fix, so it is left alone rather than guessed at.
    """
    start = getattr(intent, "start_time", None)
    end = getattr(intent, "end_time", None)
    if not start or not end:
        return
    try:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
    except ValueError:
        return
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if end_min <= start_min:
        return
    max_hours = getattr(getattr(cfg, "engine", None), "max_event_hours", 4.0)
    max_min = int(max_hours * 60)
    if end_min - start_min <= max_min:
        return
    capped_min = min(start_min + max_min, 24 * 60 - 1)
    capped = f"{capped_min // 60:02d}:{capped_min % 60:02d}"
    state.add_fix("validate", "max_duration_cap", end, capped,
                  note=f"clipped to the {max_hours:g}-hour cap")
    intent.end_time = capped


def _rule_quiet_hours_flag(state, item, intent, cfg) -> None:
    """A window the engine will not place a start or end time in without
    saying so (`engine.quiet_hours_start`/`_end`, default 23:00-06:00).

    A FLAG, NOT A BLOCK — same shape as the observance gate just below: ANY
    engine-built `create_event`, whether the time came from the speaker's own
    words or a default, gets a note the speaker can act on rather than a
    silent change. Runs after `_rule_max_duration_cap` so it flags the FINAL
    end_time, not one a clip is about to replace.
    """
    eng = getattr(cfg, "engine", None)
    win_start = getattr(eng, "quiet_hours_start", None) or "23:00"
    win_end = getattr(eng, "quiet_hours_end", None) or "06:00"
    try:
        wsh, wsm = map(int, win_start.split(":"))
        weh, wem = map(int, win_end.split(":"))
    except (ValueError, AttributeError):
        return
    win_start_min = wsh * 60 + wsm
    win_end_min = weh * 60 + wem
    if win_start_min == win_end_min:
        return                        # a zero-width window flags nothing

    def _in_window(hhmm) -> bool:
        try:
            h, m = map(int, hhmm.split(":"))
        except (ValueError, AttributeError, TypeError):
            return False
        t = h * 60 + m
        if win_start_min < win_end_min:
            return win_start_min <= t < win_end_min
        return t >= win_start_min or t < win_end_min          # spans midnight

    which = [label for label, val in (("start", getattr(intent, "start_time", None)),
                                       ("end", getattr(intent, "end_time", None)))
             if val and _in_window(val)]
    if not which:
        return
    reason = (f"{' and '.join(which)} time is inside quiet hours "
              f"({win_start}–{win_end})")
    state.add_fix("validate", "flag:quiet_hours",
                  getattr(intent, "title", ""), "", note=reason)
    item.slots.setdefault("flags", []).append(f"quiet_hours: {reason}")


def _rule_morning_title_guard(state, intent, transcript) -> None:
    """A morning word in the event's OWN title means morning — "Shacharit at
    6:30" was booked at 18:30. Scoped to the title so one "Shacharit" cannot
    drag every event in the sentence back twelve hours."""
    title_l = (getattr(intent, "title", "") or "").lower()
    morning = re.search(r"\b(?:shacharit|breakfast|sunrise)\b", title_l)
    st = getattr(intent, "start_time", None) or ""
    if not (morning and re.fullmatch(r"1[2-9]:\d{2}|2[0-3]:\d{2}", st)):
        return
    hh, mm = map(int, st.split(":"))
    am = f"{hh - 12:02d}:{mm:02d}"
    if f"{hh - 12}:{mm:02d}" in transcript or str(hh - 12) in transcript:
        intent.start_time = am
        end = getattr(intent, "end_time", None)
        if end:
            try:
                eh, em = map(int, end.split(":"))
                intent.end_time = f"{max(0, eh - 12):02d}:{em:02d}"
            except ValueError:
                pass
        state.add_fix("validate", "morning_title_guard", st, am, note="a morning event")


def _rule_junk_event_drop(state, item, intent, n_events, pairs) -> None:
    """Hybrid junk: an extra create_event with a generic title alongside real
    todos is parser noise, not a booking."""
    t = (getattr(intent, "title", "") or "").strip().lower()
    if n_events > 0 and t in _JUNK_TITLES and any(a == "create_todo" for _, a, _i in pairs):
        state.add_fix("validate", "junk_event_drop", t, "", note="dropped junk event")
        item.intent = None


def _rule_question_creates_nothing(state, cfg, pairs) -> None:
    """Dataset triage: "…does my daughter have a recital?" INVENTED a task
    from the question's subordinate clause. An item whose own words are a
    question feeds the query — it never creates. Scoped to the item's text,
    so "book gym and what's on friday?" keeps its booking."""
    for item, action, intent in pairs:
        if item.intent is None or not action or not action.startswith("create_"):
            continue
        if _rule_interrogative_create_asks_first(state, cfg, item, pairs):
            continue
        text = (item.text or "").strip()
        imperative_query = bool(_QUERY_OPENER.match(text)) and not _CREATE_VERB.search(text)
        if not text.endswith("?") and not _QUESTION_START.match(text) \
                and not imperative_query:
            continue
        if imperative_query:
            title = (getattr(intent, "title", None)
                     or (getattr(intent, "titles", None) or [""])[0] or item.text[:30])
            state.add_fix("validate", "question_creates_nothing", str(title), "",
                          note="an ask-to-see request creates nothing")
            item.intent = None
            continue
        base = item.id.split("-")[0]
        sibling_query = any(
            other.id.split("-")[0] == base and other.action
            and other.action.startswith("query")
            for other, _a, _i in pairs if other is not item)
        whole_question = text.endswith("?") and bool(_QUESTION_START.match(text))
        if sibling_query or whole_question:
            title = (getattr(intent, "title", None)
                     or (getattr(intent, "titles", None) or [""])[0] or item.text[:30])
            state.add_fix("validate", "question_creates_nothing", str(title), "",
                          note="a question asks; it does not create")
            item.intent = None


#: The verbs that make a sentence an INSTRUCTION to change something. A
#: question containing one is still an instruction ("can you move my dentist
#: appointment to 3?"); a question containing none is just a question.
#: Deliberately the same shape as `_CREATE_VERB` and read beside it, rather
#: than a fifth opinion about what an imperative looks like — audit P2 is that
#: this codebase already answers "is this a question?" in four places.
#: The verbs that make a question-shaped sentence an INSTRUCTION. This is a
#: SAFETY NET's escape hatch, so every verb the router treats as a mutation has
#: to be here — a verb the router knows and this pattern does not is a real
#: command silently vetoed.
#:
#: It drifted, and Gil caught it from his phone (2026-09-18): "Can you shorten
#: the event at 2pm walk Jada to be 15 minutes" parsed as `update_event` at
#: confidence 1.00 and then `question_mutates_nothing` emptied it, because the
#: whole extend/shorten family was missing. Nothing happened and the card said
#: the rules had answered.
#:
#: `test_engine_checks` now asserts this covers `rule_parser._EXTEND_VERBS` and
#: every update/delete verb in `_VERB_ACTION`, so the two cannot drift again.
_MUTATE_VERB = re.compile(
    r"\b(move|change|reschedule|shift|push|postpone|delay|rename|retitle|"
    r"update|edit|cancel|delete|remove|drop|clear|complete|finish|"
    r"tick|check\s+off|mark|"
    # the duration family — `rule_parser._EXTEND_VERBS`, and the reason this
    # comment exists
    r"extend|lengthen|shorten|stretch|prolong|trim)\b", re.I)


def _rule_question_mutates_nothing(state, cfg, pairs) -> None:
    """A question must never MOVE or DELETE anything.

    HYPOTHESES.md, open bug found 2026-09-06 by the query-no-mutation check:
    "Is my appointment to the dentist still on for tomorrow morning?" produced
    `update_event(match_title="dentist")` — a question that reschedules a real
    appointment. 14 hits on the full-3000 sweep, present in every archived run.

    `_rule_question_creates_nothing` above has guarded CREATE since the
    dataset triage; this is the same rule for the other half, and the half
    that can destroy something the speaker already has. Asking about a thing
    is the most common way to mention it, so the blast radius is larger here
    than for create, not smaller.

    The exception is an imperative wearing a question mark — "can you move my
    dentist appointment to 3?" is an instruction, and `_MUTATE_VERB` is what
    tells the two apart. Emptying the intent (rather than rewriting it to a
    query) is deliberate: the engine's honest answer to "I read this as a
    question" is to answer the question, and an empty slot surfaces as
    "I couldn't find…", which CLAUDE.md prefers to a guess.
    """
    for item, action, intent in pairs:
        if item.intent is None or not action:
            continue
        if not action.startswith(("update_", "delete_", "complete_")):
            continue
        text = (item.text or "").strip()
        asks = bool(text.endswith("?")) or bool(_QUESTION_START.match(text))
        if not asks or _MUTATE_VERB.search(text) or _CREATE_VERB.search(text):
            continue
        title = (getattr(intent, "match_title", None)
                 or getattr(intent, "title", None) or text[:30])
        state.add_fix("validate", "question_mutates_nothing", str(title), "",
                      note=f"{action} from a question with no instruction in it")
        item.intent = None


def _rule_interrogative_create_asks_first(state, cfg, item, pairs) -> bool:
    """Gil's ruling (2026-09-07, DEVQA Q9): an interrogative create —
    "should i add yoga to my calendar tomorrow?" — must neither auto-create
    nor be silently dropped. It gets a confirmation prompt instead.

    Returns True when this item is held for confirmation: the intent SURVIVES
    (fully validated, ready to POST) and `slots["confirm_create"]` tells the
    orchestrator to ask rather than commit — the same shape as the transcript
    gate's `needs_edit`, and gated the same way on the client saying it can
    render the prompt.

    Only when the question is the whole command. A confirmation holds
    everything, so "book gym at 7 and should i add yoga?" would strand the
    booking behind a dialog about the yoga; there the question half keeps
    today's behaviour and the booking runs.
    """
    if not state.supports_confirm:
        return False
    if not getattr(getattr(cfg, "engine", None), "confirm_create", True):
        return False
    from assistant.engine.segmentation.old_seg.segment import is_interrogative_create
    if not is_interrogative_create(item.text or ""):
        return False
    if sum(1 for other, _a, _i in pairs if other.intent is not None) != 1:
        return False
    item.slots["confirm_create"] = True
    title = (getattr(item.intent, "title", None)
             or (getattr(item.intent, "titles", None) or [""])[0] or item.text[:30])
    state.add_fix("validate", "interrogative_create_asks_first", str(title), "",
                  note="a question that would create something — asking first")
    return True


def _rule_cadence_round_and_announce(state, tl) -> None:
    """A cadence the model cannot represent is approximated — and the
    approximation is SAID, not done quietly ("every other tuesday" once
    became a single event with no mention)."""
    cadence = unsupported_cadence(tl)
    if not cadence:
        return
    made = next((it.intent for it in state.items
                 if it.action == "create_event" and it.intent is not None), None)
    if made is None:
        return
    # "two days a week" is `unsupported_cadence`'s label for "every tuesday
    # and thursday"-style text — TRUE for the fast/rule path, which has no
    # way to carry more than one weekday, but not for whatever resolved this
    # object if `recur_days` actually has more than one entry: `resolve.py`
    # (the deep track) reads every named weekday into it, so nothing was
    # lost and announcing a rounding that didn't happen is the false alarm.
    if cadence == "two days a week" and len(getattr(made, "recur_days", None) or []) > 1:
        return
    as_what = getattr(made, "recurrence", None) or "one-off"
    state.messages.append(
        f"Note: I can only repeat daily, weekly, monthly or yearly, so "
        f"“{cadence}” became {as_what} — adjust it if that is wrong.")
    state.add_fix("validate", "cadence_round_and_announce", cadence, str(as_what),
                  note="the model has no way to express the first")

