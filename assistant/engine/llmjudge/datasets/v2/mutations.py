"""The object-level plants — one known defect per case, and where it lands.

A case is a RECIPE (`datasets/generate.py`'s rule, kept): the row stores the
gold items and the plant, and a board rebuilds the object with the real
converter (`fastrule.build`) before applying it. So what is judged is what
production would produce, not a fixture that drifts away from it.

## The twelve defects, and the three the taxonomy has no name for

Six are v1's, carried over because they are each a defect this engine has
shipped or provably can. Six are new, and they are the classes `PLAN.md` §7.1
says the stage is blind to by construction:

    mutation                 expect                  where it comes from
    ---------------------------------------------------------------------
    generic_title            ungrounded_subject      an event titled "event"
    invented_title           ungrounded_subject      the cycle-7 fabrication
    near_miss_title          ungrounded_subject      "buy groceries" from "buy milk"
    dropped_date             unsupported_field       pydantic's fill wearing a
    dropped_time             unsupported_field         resolved value's clothes
    unrelated_object         not_an_ask              an object nobody asked for
    subject_dropped_for_kind ungrounded_subject      Q42: a bare kind over words
                                                     that DID name the thing
    merged_asks              unsplit_subject   (seam)     two asks in one object
                             coordinated_subject (list)
                             — (plain "and")
    dropped_ask              —                       an ask with nothing built
    wrong_kind               —                       event read as to-do
    wrong_operation          —                       a create for a change
    clock_residue_title      —                       "meeting a.m" as a title

**A dash is not an oversight.** `expect: null` with `defect: true` means the
defect is real and today's finding taxonomy has NO type for it — the ask diff
that could see a dropped ask was removed on 2026-09-10, and nothing reads the
kind, the operation or a clock inside a title. Those cases are scored as their
own column ("blind"), and they must NEVER be pooled with the clean rows: a
clean row is the false-flag denominator, and counting a planted defect there
would reward the judge for missing it.
"""
from __future__ import annotations

import copy
import re

#: mutation -> the finding type it should produce, or None when the taxonomy
#: has no name for it. `merged_asks` is decided per case (see `_merge_expect`).
EXPECT = {
    "clean": None,
    "generic_title": "ungrounded_subject",
    "invented_title": "ungrounded_subject",
    "near_miss_title": "ungrounded_subject",
    "subject_dropped_for_kind": "ungrounded_subject",
    "dropped_date": "unsupported_field",
    "dropped_time": "unsupported_field",
    "unrelated_object": "not_an_ask",
    "merged_asks": "unsplit_subject",
    "dropped_ask": None,
    "wrong_kind": None,
    "wrong_operation": None,
    "clock_residue_title": None,
}

DEFECTS = tuple(m for m in EXPECT if m != "clean")

#: What the program calls an entry when it has no name for one (v1's `_GENERIC`).
_GENERIC = {"event": "Event", "task": "Reminder"}

#: Ordinary calendar nouns to fabricate with — a nonsense string would be caught
#: by any check at all and would measure nothing. v1 learned the second half of
#: this the hard way: taking the first candidate that fit made one noun win 269
#: times out of 269, so the choice ROTATES.
_FABRICATIONS = ("physiotherapy", "budget review", "team standup",
                 "car service", "piano lesson", "board meeting",
                 "dermatology referral", "quarterly audit", "violin practice",
                 "boiler inspection", "tax filing", "orthodontist checkup")

#: A near miss shares a word with the transcript and names the wrong thing —
#: the case where the zero-overlap test cannot help.
_NEAR_MISS_NOUNS = ("groceries", "paperwork", "batteries", "prescription",
                    "insurance", "textbooks")

#: The kind words Q42 rules on. Planted over words that DID name the subject,
#: which is the half of Q42 that is still a finding.
_KIND_WORDS = {"event": ("meeting", "appointment", "event"),
               "task": ("reminder", "task", "alert")}

#: event <-> to-do, the same operation. Segmentation's tag error is
#: one-directional in the wild (event read as task, 116 of 175), so both
#: directions are planted and the board can read them apart.
_KIND_FLIP = {"create_event": "create_todo", "create_todo": "create_event",
              "delete_event": "delete_todo", "delete_todo": "delete_event",
              "update_event": "update_todo", "query_schedule": "query_todos",
              "query_todos": "query_schedule"}

#: create <-> change <-> remove, WITHIN one store. A wrong operation is the
#: expensive defect — a wrong delete costs 4 on the harm scale — and it was
#: measured once at net +2 on 266 rows, which is why §7.5's H4 wants it
#: planted at size.
_OP_FLIP = {"create_event": "delete_event", "delete_event": "create_event",
            "update_event": "create_event", "create_todo": "delete_todo",
            "delete_todo": "create_todo", "complete_todo": "delete_todo",
            "query_schedule": "create_event", "query_todos": "create_todo"}


def _words(text: str) -> set:
    return set(re.findall(r"[a-z']+", (text or "").casefold()))


def _identity(intent) -> "str | None":
    """Which field carries this object's identity — `titles`, `match_title` or
    `title`. v1 planted on `title` unconditionally and 92 plants were no-ops on
    target-taking operations, which the board scored as misses."""
    if getattr(intent, "titles", None):
        return "titles"
    if getattr(intent, "match_title", None) is not None:
        return "match_title"
    if getattr(intent, "title", None) is not None:
        return "title"
    return None


def _current_title(intent) -> str:
    field = _identity(intent)
    if field == "titles":
        return (list(intent.titles) or [""])[0]
    return getattr(intent, field, "") or "" if field else ""


def _set_title(intent, value: str) -> bool:
    field = _identity(intent)
    try:
        if field == "titles":
            intent.titles = [value] + list(intent.titles)[1:]
        elif field:
            setattr(intent, field, value)
        else:
            return False
    except Exception:
        return False
    return True


def _fabrication_for(text: str, rng) -> "str | None":
    have = _words(text)
    pool = [c for c in _FABRICATIONS if not (_words(c) & have)]
    return pool[rng.randrange(len(pool))] if pool else None


def _near_miss_for(title: str, text: str, rng) -> "str | None":
    from assistant.engine.llmjudge.verdict import _TITLE_STOP
    head = [w for w in re.findall(r"[a-z']+", (title or "").lower())
            if len(w) > 2 and w not in _TITLE_STOP]
    if not head:
        return None
    have = _words(text)
    pool = [n for n in _NEAR_MISS_NOUNS if n not in have]
    return f"{head[0]} {pool[rng.randrange(len(pool))]}" if pool else None


def _slot_backed(action: str, slot: str) -> bool:
    from assistant.engine.llmjudge.render import SLOT_BACKED
    return slot in set((SLOT_BACKED.get(action) or {}).values())


def _named_subject(row: dict, ask_id: int) -> bool:
    """Did the WORDS name the thing? Q42: a bare kind commits when they did
    not, so a kind-word plant is only a defect when they did."""
    for a in row["asks"]:
        if a["ask_id"] == ask_id:
            return bool(a["title"]) and not a["bare_kind"] and not a["anaphor"]
    return False


def _ask_of(row: dict, item_id: str) -> dict:
    n = int(item_id.split("_")[-1])
    for a in row["asks"]:
        if a["ask_id"] == n:
            return a
    return {}


def _flip_intent(action: str, title: str, slots: dict):
    """Build the object of ANOTHER action from the same words, with the real
    converter's own constructor — a wrong kind or a wrong operation is still a
    well-formed object, which is exactly what makes it hard to see."""
    from assistant.engine.fastrule.build import _new_intent, _value_kwargs
    values, _copied = _value_kwargs(action, slots or {})
    try:
        return _new_intent(action, title, [], values, [title] if title else None)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# which plants this command can carry
# ---------------------------------------------------------------------------

def applicable(row: dict, items: list, results: list, built: list) -> list:
    """The mutations that can be planted HONESTLY on this command.

    A plant that cannot change the object is skipped rather than approximated:
    v1 planted `dropped_time` on rows that resolved no clock, there was nothing
    to drop, and the board blamed the judge for not finding it.
    """
    out = ["clean"]
    text = row["text"]
    titled = [(it, r) for it, r in built if _identity(r.intent)]
    named = [(it, r) for it, r in titled
             if _named_subject(row, int(it.id.split("_")[-1]))]

    if named:
        out += ["generic_title", "subject_dropped_for_kind"]
        if _fabrication_for(text, _Det(0)):
            out.append("invented_title")
        if any(_near_miss_for(_current_title(r.intent), text, _Det(0))
               for _it, r in named):
            out.append("near_miss_title")
    for it, r in built:
        if (it.slots or {}).get("date") and _slot_backed(r.action, "date"):
            if "dropped_date" not in out:
                out.append("dropped_date")
        if (it.slots or {}).get("start_time") and _slot_backed(r.action, "start_time"):
            if "dropped_time" not in out:
                out.append("dropped_time")
    if _fabrication_for(text, _Det(0)):
        out.append("unrelated_object")
    if len(built) >= 2:
        out += ["dropped_ask", "merged_asks"]
    if any(_KIND_FLIP.get(r.action) for _it, r in built):
        out.append("wrong_kind")
    if any(_OP_FLIP.get(r.action) for _it, r in built):
        out.append("wrong_operation")
    if any(_ask_of(row, it.id).get("said", {}).get("clock_phrase")
           for it, _r in built if _identity(_r.intent)):
        out.append("clock_residue_title")
    return out


class _Det:
    """A one-value stand-in for an rng, so `applicable` can ask "is there a
    candidate at all" without consuming the real stream and making the pick
    depend on how many times it was asked."""

    def __init__(self, k: int):
        self.k = k

    def randrange(self, n: int) -> int:
        return self.k % max(1, n)


# ---------------------------------------------------------------------------
# planting
# ---------------------------------------------------------------------------

def _merge_expect(row: dict, n: int) -> tuple:
    """Which finding a merge SHOULD produce: `(mode, seam, expect, how many)`.

    Keyed on `findings.py`'s own definitions, not on the detectors' regexes:
    UNSPLIT_SUBJECT is "one object whose own words still hold an ask seam —
    'and then', '. Also,', '; then'"; COORDINATED_SUBJECT is "one object named
    with several things … a bare noun list of three or more". A merge on a
    plain "and" is neither, and today's taxonomy has no name for it — which is
    the third population and the reason this mutation carries three.
    """
    from assistant.engine.llmjudge.datasets.v2.generate_v2 import SEAM_JOINERS
    joiner = row["joiner"].split("x")[0]
    if joiner in SEAM_JOINERS:
        seam = {"and_then": " and then ", "also": ". Also, ",
                "comma_then": ", then "}[joiner]
        return "seam", seam, "unsplit_subject", 2
    if n >= 3:
        return "list", None, "coordinated_subject", 3
    return "plain", " and ", None, 2


def make_case(row: dict, items: list, results: list, built: list,
              name: str, rng) -> "dict | None":
    """One case, with its plant resolved to VALUES (never to an rng call at
    board time) and checked to be EFFECTIVE before it is written."""
    from assistant.engine.llmjudge import render

    plant: dict = {}
    expect = EXPECT.get(name)
    expect_item = None
    text = row["text"]
    titled = [(it, r) for it, r in built if _identity(r.intent)]
    named = [(it, r) for it, r in titled
             if _named_subject(row, int(it.id.split("_")[-1]))]

    if name in ("generic_title", "subject_dropped_for_kind", "invented_title",
                "near_miss_title", "clock_residue_title"):
        pool = named if name != "clock_residue_title" else [
            (it, r) for it, r in titled
            if _ask_of(row, it.id).get("said", {}).get("clock_phrase")]
        if not pool:
            return None
        it, res = pool[rng.randrange(len(pool))]
        ask = _ask_of(row, it.id)
        expect_item = it.id
        if name == "generic_title":
            plant["title"] = _GENERIC.get(ask.get("kind") or "event", "Event")
        elif name == "subject_dropped_for_kind":
            words = _KIND_WORDS["event" if ask.get("kind") == "event" else "task"]
            plant["title"] = words[rng.randrange(len(words))]
        elif name == "invented_title":
            plant["title"] = _fabrication_for(text, rng)
        elif name == "near_miss_title":
            plant["title"] = _near_miss_for(_current_title(res.intent), text, rng)
        else:
            spoken = ask["said"]["clock_phrase"].split(" ", 1)[1]
            plant["title"] = f"{_current_title(res.intent)} {spoken}"
        if not plant["title"]:
            return None
        plant["item"] = it.id

    elif name in ("dropped_date", "dropped_time"):
        slot = "date" if name == "dropped_date" else "start_time"
        pool = [(it, r) for it, r in built
                if (it.slots or {}).get(slot) and _slot_backed(r.action, slot)]
        if not pool:
            return None
        it, _r = pool[rng.randrange(len(pool))]
        plant["item"], plant["slot"] = it.id, slot
        expect_item = it.id

    elif name == "unrelated_object":
        plant["title"] = _fabrication_for(text, rng)
        if not plant["title"]:
            return None
        expect_item = "item_x"

    elif name == "dropped_ask":
        it, _r = built[rng.randrange(len(built))]
        plant["item"] = it.id

    elif name == "merged_asks":
        # AN UNDER-SPLIT IS A DEFECT OF THE WORDS, not only of the title.
        # Both detectors read the ITEM — `_unsplit_findings` looks for a seam
        # in `item.spoken()`, `_coordinated_findings` reads the noun list off
        # `item.text` — so a plant that merged the titles alone was invisible
        # to the judge by construction and scored 0/34 on the first probe. The
        # plant merges the WORDS and titles the surviving object from both,
        # which is what an under-split actually looks like coming out of
        # segmentation.
        mode, seam, expect, n_merge = _merge_expect(row, len(built))
        pool = [(it, r) for it, r in built if _identity(r.intent)]
        if len(pool) < 2:
            return None
        keep, others = pool[0], pool[1:n_merge]
        if not others:
            return None
        titles = [_current_title(r.intent) for _it, r in [keep] + others]
        if mode == "list":
            subject = (_ask_of(row, keep[0].id).get("said") or {}).get("subject")
            if not subject or subject not in keep[0].text:
                return None
            # A NOUN LIST IS MADE OF THE GOLD SUBJECTS, AND ONLY OF EVENTS'
            # (cycle 42, 2026-09-22). This plant listed the CONVERTER'S titles
            # of whatever it had built, and the judge board read 42 misses on
            # the train half where nearly every list-mode plant was one of:
            # a task's verb phrase inside the list ("the car service, charge
            # the batteries and …"), a member still wearing its frame ("block
            # off the car service", "i would like to schedule the dentist
            # appointment"), or a pair — three asks of which only two had a
            # title. None of those is "a bare noun list of three or more
            # things" (`findings.py`), and `coordination.noun_list` refuses
            # each on purpose: a member that is a command verb is a list of
            # ASKS, which is the cut's defect, and a pair cannot be told from
            # "wine and cheese". The gold is the grammar's, not the
            # converter's, so the members are the asks' `said.subject` — and
            # an ask that is not an event with a subject in its words makes
            # the row a PLAIN merge (the blind population), never a wrong
            # expectation. The None conditions above are unchanged so every
            # other case of the set is byte-identical after the change.
            def _subject(it):
                return (_ask_of(row, it.id).get("said") or {}).get("subject")
            events = [(it, r) for it, r in pool
                      if r.action == "create_event" and _subject(it)
                      and _subject(it) in it.text]
            if len(events) >= 3:
                keep, others = events[0], events[1:n_merge]
                subjects = [_subject(it) for it, _r in [keep] + others]
                listed = ", ".join(subjects[:-1]) + " and " + subjects[-1]
                merged_text = keep[0].text.replace(subjects[0], listed, 1)
                merged_title = listed
            else:
                mode, seam, expect, n_merge = "plain", " and ", None, 2
                keep, others = pool[0], pool[1:n_merge]
                titles = [_current_title(r.intent) for _it, r in [keep] + others]
        if mode != "list":
            merged_text = seam.join([it.text for it, _r in [keep] + others])
            merged_title = seam.join(titles).strip()
        plant.update({"item": keep[0].id, "title": merged_title,
                      "text": merged_text,
                      "drop": [it.id for it, _r in others]})
        expect_item = keep[0].id

    elif name in ("wrong_kind", "wrong_operation"):
        table = _KIND_FLIP if name == "wrong_kind" else _OP_FLIP
        pool = [(it, r) for it, r in built if table.get(r.action)]
        if not pool:
            return None
        it, res = pool[rng.randrange(len(pool))]
        action = table[res.action]
        title = _current_title(res.intent) or (_ask_of(row, it.id).get("title") or "")
        if not _flip_intent(action, title, it.slots):
            return None
        plant.update({"item": it.id, "action": action, "title": title})
        expect_item = it.id

    case = {
        "id": f"{row['id']}#{name}",
        "command_id": row["id"],
        "split": row["split"],
        "family": row["family"],
        "grammar": row["grammar"],
        "joiner": row["joiner"],
        "voice": row["voice"],
        "damage": row["damage"],
        "n_asks": row["n_asks"],
        "text": row["text"],
        "items": [{"id": f"item_{a['ask_id']}", "kind": a["item"]["kind"],
                   "text": a["item"]["text"], "time": a["item"]["time"] or None}
                  for a in row["asks"]],
        "mutation": name,
        "defect": name != "clean",
        "expect": expect,
        "expect_item": expect_item,
        "plant": plant,
    }

    if name == "clean":
        return case

    # EFFECTIVE, checked here rather than trusted: a plant that does not change
    # the object is not a defect, and the board scores it as a MISS against a
    # judge that had nothing to find. v1 shipped six of those and they read as
    # a deterministic check scoring 92% when it was scoring 100%.
    #
    # The check runs on a DEEP COPY. `apply` mutates the objects it is handed —
    # it is the board's plant — and a rejected candidate would otherwise leave
    # a corrupted title behind for whichever mutation is tried next.
    probe_items, probe_results = copy.deepcopy((items, results))
    probe_built = [(it, r) for it, r in zip(probe_items, probe_results)
                   if type(r).__name__ == "Built"]
    before = [(render.render_line(r.action, r.intent, it.slots),
               tuple(sorted((it.slots or {}).items(), key=str)))
              for it, r in probe_built]
    shown = apply(case, probe_items, probe_results)
    after = [(render.render_line(it.action, it.intent, it.slots),
              tuple(sorted((it.slots or {}).items(), key=str))) for it in shown]
    return None if before == after else case


def apply(case: dict, items: list, results: list) -> list:
    """Plant the case's defect and return the item list the judge sees.

    `items` are the gold items after `decompose_validate` and `fastrule.build`;
    `results` are the build results in the same order. Only the objects that
    BUILT are shown — a DEFER is FastRule's product, not a judgeable object.
    """
    from assistant.engine.fastrule.build import Built
    from assistant.engine.state import Item

    shown = []
    for it, r in zip(items, results):
        if isinstance(r, Built):
            it.action, it.intent = r.action, r.intent
            shown.append(it)
    name, plant = case["mutation"], case.get("plant") or {}
    by_id = {it.id: it for it in shown}

    if name == "clean":
        return shown
    if name in ("generic_title", "subject_dropped_for_kind", "invented_title",
                "near_miss_title", "clock_residue_title"):
        target = by_id.get(plant.get("item"))
        if target is not None:
            _set_title(target.intent, plant["title"])
        return shown
    if name in ("dropped_date", "dropped_time"):
        target = by_id.get(plant.get("item"))
        if target is not None:
            (target.slots or {}).pop(plant["slot"], None)
        return shown
    if name == "unrelated_object":
        from assistant.actions.calendar.intent import CalendarIntent
        extra = Item(id="item_x", kind="event", text=plant["title"], slots={},
                     action="create_event",
                     intent=CalendarIntent(title=plant["title"]))
        return shown + [extra]
    if name == "dropped_ask":
        return [it for it in shown if it.id != plant.get("item")]
    if name == "merged_asks":
        target = by_id.get(plant.get("item"))
        if target is not None:
            _set_title(target.intent, plant["title"])
            if plant.get("text"):
                target.text = plant["text"]     # the words the cut left together
        drop = set(plant.get("drop") or [])
        return [it for it in shown if it.id not in drop]
    if name in ("wrong_kind", "wrong_operation"):
        target = by_id.get(plant.get("item"))
        if target is not None:
            intent = _flip_intent(plant["action"], plant["title"], target.slots)
            if intent is not None:
                target.action, target.intent = plant["action"], intent
        return shown
    return shown
