#!/usr/bin/env python3
"""Generate the FastRule eval/train dataset from pattern + filler banks
under assistant/engine/fastrule/datasets/banks/. Currently 8,400 rows: the original 6,000-row
stratified 80/20 pool (train 4,800 / test 1,200), a 1,200-row forced-test-only
pool grown on top of it (Gil, 2026-09-07), and a 1,200-row forced-TRAIN-only
pool grown on top of both (2026-09-25) — see `build_forced_test()`,
`build_forced_train()` and assistant/engine/TRAIN_TEST_SPLIT_CONVENTION.md.
The file keeps its historical name, `fastrule_7200.jsonl`, for the same reason
`SEED` keeps its: forty-odd boards and tests read it by that path.

WHY a generator instead of thousands of hand-written rows: the banks are the
authored artifact (pattern SKELETONS + generic slot fillers); this script
deterministically expands them into concrete rows and assigns ground truth
BY CONSTRUCTION — it knows exactly which filler it dropped into which slot,
so no row needs human labelling. That includes label-level ground truth
(event `category`, task `tags`): each family declares which of its title
slots are real CREATED events/tasks (excluding delete/update/query/complete
targets), and this script classifies those titles by calling the actual
`assistant.actions.calendar.categories.classify()` /
`assistant.actions.todo.tagging` scoring functions against this dataset's
own frozen `banks/categories_fixture.json` — see `setup_label_env()`.

Determinism: a fixed SEED plus the banks' on-disk content are the only
inputs (no network, no wall-clock, no dict-iteration-order dependence —
every RNG stream is reseeded from a stable string key, independently per
family, so one family's row content can never depend on any OTHER family
existing at all — see `_init_family`/`gen_family_rows`). Regenerating
reproduces the previous fastrule_7200.jsonl byte-for-byte, and growing either
forced pool further leaves every existing row (train AND the original
stratified test) untouched — that's the whole point of pulling force_split
families out before the stratified path ever runs (`main()`). The forced-train
rows are also shuffled on their own RNG stream and APPENDED after the rest, so
the original 7,200 keep their line order too. Stable ids
are "<family>-<counter>", counter local to that family's rows in the order
generated. `SEED` still reads `"fastrule-6000-v1"` — a fixed historical
identifier now, not a live row-count description; renaming the STRING would
reseed every family's RNG stream and break every existing row, which is
exactly the one thing this growth was required not to do.

Usage:
    python -m assistant.engine.fastrule.datasets.generate            # generate + verify
    python -m assistant.engine.fastrule.datasets.generate --no-write  # verify-only dry run

See assistant/engine/fastrule/datasets/DATASET.md for the schema and design rationale, and
assistant/engine/TRAIN_TEST_SPLIT_CONVENTION.md for how the 80/20 train/test split is built and
why TEST ROWS MUST NEVER BE MINED (Gil's ruling — see that file).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

# MOVED HERE 2026-09-10 (from `scripts/gen_fastrule_dataset.py`, brought in by
# the `engine-component-folders` merge, TASKS.md row 91). HEAD had fixed the
# same rot IN PLACE at the old path (`ROOT = parents[1]` from `scripts/` is the
# repo root, which was correct there); this merge instead takes the branch's
# fix, which also relocates the file — "a stage owns its folder and the
# datasets used to improve it" (CLAUDE.md), matching where every other stage's
# generator already lives.
#
# MIND THE `ROOT` TRAP, which is what made the first repair of the other three
# worse: from here, `parents[1]` is the STAGE folder, not the repo root. The
# banks and the output are siblings of this file; only the sys.path insert in
# setup_label_env() wants the repo, four levels up
# (datasets -> fastrule -> engine -> assistant -> repo).
HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[4]
BANKS = HERE / "banks"
OUT = HERE / "fastrule_7200.jsonl"
CATEGORIES_FIXTURE = BANKS / "categories_fixture.json"

# Changing SEED changes every row's fillers and the split assignment — only
# do it deliberately, and note the regen in engine/TRAIN_TEST_SPLIT_CONVENTION.md / DATASET.md.
SEED = "fastrule-6000-v1"

SIMPLE_TOTAL = 2000
COMPLEX_TOTAL = 4000
TRAIN_FRAC = 0.8

# Test-only growth (Gil, 2026-09-07): families with `force_split: "test"` in
# the banks are assigned directly to test, on top of (not carved out of) the
# totals above — see build_forced_test(). Train stays exactly SIMPLE_TOTAL*0.8
# + COMPLEX_TOTAL*0.8 = 4,800 rows, byte-identical to before this pool existed.
SIMPLE_FORCE_TEST_TOTAL = 400
COMPLEX_FORCE_TEST_TOTAL = 800

# Train-only growth (2026-09-25), the mirror of the pool above: families with
# `force_split: "train"` are assigned directly to TRAIN, again on top of every
# total above — see build_forced_train(). The FastRule board read 96.8% vs
# 81.0% correct-on-handled (atomic rows, train vs test) while real speech
# showed no gap, because the test half holds whole phrasing STYLES (the
# forced-test pool) that train never sees. These families widen train's
# phrasing instead. They were written without reading any test family or test
# row (TRAIN_TEST_SPLIT_CONVENTION.md, "Growing train-only").
SIMPLE_FORCE_TRAIN_TOTAL = 400
COMPLEX_FORCE_TRAIN_TOTAL = 800

# action -> (atomic, events, tasks) for SIMPLE-tier families, which are
# single-intent by construction so this is fully determined by the action.
# COMPLEX-tier families state atomic/events/tasks explicitly in their bank
# entry instead (compounds vary too much to default).
ACTION_DEFAULTS = {
    "create_event": (True, 1, 0),
    "create_todo": (True, 0, 1),
    "query": (True, 0, 0),
    "delete_event": (True, 0, 0),
    "delete_todo": (True, 0, 0),
    "complete_todo": (True, 0, 0),
    "update_event": (True, 0, 0),
    "update_todo": (True, 0, 0),
}
ALL_ACTIONS = set(ACTION_DEFAULTS) | {"mixed", "propose"}   # propose: Q9 ruling - a question proposes, user confirms

# placeholder base name -> (filler bank key, semantic slot key | None).
# None means the placeholder is cosmetic text only (not ground truth).
# A placeholder like "{event_title2}" reuses the "event_title" base bank
# and writes to "title_2" instead of "title" — see _placeholder_info().
BASE_INFO = {
    "event_title": ("event_titles", "title"),
    "task_title": ("task_titles", "title"),
    "item": ("items", "title"),
    "qty": ("quantities", "quantity"),
    "date": ("dates", "date_phrase"),
    "time": ("times", "time_phrase"),
    "time_range": ("time_ranges", "time_phrase"),
    "recurrence": ("recurrences", "recurrence"),
    "name": ("names", "attendee"),
    "occasion": ("occasions", "title"),
    "lead_time": ("lead_times", "lead_time"),
    "duration": ("durations", "duration"),
    "quoted_item": ("quotable", "title"),
    "generic_target": ("generic_targets", "title"),
    "query_range": ("query_ranges", "date_phrase"),
    "filler": ("filler_words", None),
    # 2026-09-25, for the train-only growth. NEW bank keys only — an existing
    # bank list is never edited, because a longer list changes which filler
    # every existing family's rng.choice() lands on, and so every existing row.
    "weekday": ("weekdays", "date_phrase"),
    "clock": ("clock_times", "time_phrase"),          # every value states a clock (Q26)
    "uk_time": ("uk_times", "time_phrase"),
    "uk_date": ("uk_dates", "date_phrase"),
    "recurrence_more": ("recurrences_more", "recurrence"),
    "list_name": ("list_names", None),
    "wake": ("wake_words", None),
    "opener": ("polite_openers", None),
    "hedge": ("hedges", None),
}

# Recurrence must round to daily/weekly/monthly (CLAUDE.md convention).
# recurrence_rounded records what the engine's output SHOULD be; the raw
# `recurrence` slot keeps exactly what the speaker said.
RECURRENCE_ROUND = {
    "every day": "daily", "daily": "daily",
    "every week": "weekly", "weekly": "weekly", "every monday": "weekly",
    "every tuesday and thursday": "weekly", "every other week": "weekly",
    "every other tuesday": "weekly", "every weekday": "weekly",
    "every weekend": "weekly", "once a week": "weekly",
    "twice a week": "weekly", "every sunday": "weekly",
    "monthly": "monthly", "every month": "monthly",
    # `recurrences_more` (2026-09-25). New keys only: no existing row's raw
    # recurrence is one of these, so no existing row can gain a rounding.
    "every fortnight": "weekly", "fortnightly": "weekly", "once a fortnight": "weekly",
    "every morning": "daily", "every evening": "daily", "every single day": "daily",
    "every other day": "daily", "each week": "weekly", "every thursday": "weekly",
    "every saturday": "weekly", "every friday": "weekly", "once a month": "monthly",
}

TOKEN_RE = re.compile(r"\{(\w+)\}")
TITLE_KEY_RE = re.compile(r"^title(_(\d+))?$")
_WORD_CLEAN_RE = re.compile(r"[^\w\s'-]")


def load_json(name: str):
    with open(BANKS / name, encoding="utf-8") as f:
        return json.load(f)


def setup_label_env():
    """Category/tag ground truth is computed by calling the REAL
    assistant.actions.calendar.categories.classify() and
    assistant.actions.todo.tagging._score() against this dataset's own
    frozen banks/categories_fixture.json — not a reimplementation of their
    scoring math, so the ground truth can never subtly drift from what the
    product actually does. `categories.classify()` reads its keyword scheme
    from CATEGORIES_PATH (env MACALENDAR_CATEGORIES), so pointing that at
    the fixture is exactly the mechanism a real scoring run would use too
    (see DATASET.md). `tagging.py` has no equivalent file-based override —
    its KEYWORDS is a hardcoded module dict — so the fixture's `task_tags`
    section is a dataset-only companion, consumed only by this script.

    Per CLAUDE.md, every store honours an environment override; all of them
    are pointed at a throwaway scratch directory here so nothing this
    script imports (categories.py's people-name fallback in particular)
    can ever read or write ~/.assistant_tools/.
    """
    import sys
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    scratch = Path(tempfile.mkdtemp(prefix="fastrule_gen_"))
    os.environ["MACALENDAR_CATEGORIES"] = str(CATEGORIES_FIXTURE)
    os.environ.setdefault("MACALENDAR_VOCAB", str(scratch / "vocab.json"))
    os.environ.setdefault("MACALENDAR_DB", str(scratch / "calendar.db"))
    os.environ.setdefault("MACALENDAR_MEMORY_DB", str(scratch / "memory.db"))
    os.environ.setdefault("MACALENDAR_TRACE_BUS", str(scratch / "trace_bus.jsonl"))
    from assistant.actions.calendar import categories as categories_mod
    from assistant.actions.todo import tagging as tagging_mod
    return categories_mod, tagging_mod


def classify_event_category(categories_mod, title: str) -> str:
    return categories_mod.classify(title)


def classify_task_tags(tagging_mod, task_tag_keywords: dict[str, list[str]], title: str) -> list[str]:
    """Every tag whose keyword score is > 0 against `title`, using the
    product's own per-tag scoring function (`tagging._score`) — NOT just
    the single argmax `tagging.infer_tag()` returns, since ground truth
    here is intentionally multi-label (Gil's schema addition: "tags (a
    list, may be empty or multi)") while the shipped product currently only
    ever assigns one. Sorted by score desc, name asc for determinism."""
    text = " " + _WORD_CLEAN_RE.sub(" ", title.lower()) + " "
    text = re.sub(r"\s+", " ", text)
    scored = []
    for name, keywords in task_tag_keywords.items():
        score = tagging_mod._score(text, keywords)
        if score > 0:
            scored.append((score, name))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [name for _, name in scored]


def title_like_keys(fam: dict) -> list[str]:
    """Every semantic slot key this family can produce that looks like
    title/title_2/title_3 — from template placeholders AND from
    `fixed_slots` overrides (a family can synthesize e.g. title_2 purely via
    fixed_slots, as the time-list-split families do when duplicating one
    title across two occurrences at different times). Ordered title,
    title_2, title_3, ..."""
    tokens = family_tokens(fam["template"])
    keys = set()
    for tok in tokens:
        _, semantic, _ = placeholder_info(tok)
        if semantic and TITLE_KEY_RE.match(semantic):
            keys.add(semantic)
    for key in fam.get("fixed_slots", {}):
        if TITLE_KEY_RE.match(key):
            keys.add(key)

    def sort_key(key: str) -> int:
        m = TITLE_KEY_RE.match(key)
        return int(m.group(2)) if m.group(2) else 1
    return sorted(keys, key=sort_key)


def resolve_label_sources(fam: dict) -> tuple[list[str], list[str]]:
    """(event_label_sources, task_label_sources): the ordered semantic slot
    keys whose VALUE is the title of a CREATED event / task in this family's
    rows — i.e. exactly what category/tags should be computed from.

    An explicit family-level override wins (required for every `action:
    "mixed"` family, since a single title-ish key there could belong to
    either an event or a task ask, or to a delete/update/complete TARGET
    that was never created and so must be excluded from labelling
    entirely — see the `mixed_mode` families in complex_patterns.json).
    Otherwise auto-derived from a homogeneous create_event/create_todo
    action, where every title-ish key present belongs to that one type.
    A family may also override for a homogeneous action when a title-ish
    key is a redundant duplicate already folded into another (the NP-decoy
    "buy {item} and {item2}" families: item2 exists only to render the
    sentence, not as a second countable task).
    """
    if "event_label_sources" in fam or "task_label_sources" in fam:
        ev = fam.get("event_label_sources", [])
        ta = fam.get("task_label_sources", [])
    elif fam["action"] == "create_event":
        ev, ta = title_like_keys(fam), []
    elif fam["action"] == "create_todo":
        ev, ta = [], title_like_keys(fam)
    else:
        ev, ta = [], []
    if len(ev) != fam["events"] or len(ta) != fam["tasks"]:
        raise ValueError(
            f"family {fam['family']}: label sources event={ev} task={ta} "
            f"don't match declared events={fam['events']} tasks={fam['tasks']} "
            f"— add explicit event_label_sources/task_label_sources")
    return ev, ta


def add_labels(fam: dict, slots: dict, categories_mod, tagging_mod, task_tag_keywords: dict) -> None:
    """Mutate `slots` in place: category/category_2/... for each expected
    event (from `fam['_label_sources'][0]`, in order), tags/tags_2/... for
    each expected task. Absent when events/tasks is 0, matching every other
    "not applicable to this row" slot key."""
    ev_sources, ta_sources = fam["_label_sources"]
    for i, key in enumerate(ev_sources):
        title_text = str(slots.get(key, ""))
        out_key = "category" if i == 0 else f"category_{i + 1}"
        slots[out_key] = classify_event_category(categories_mod, title_text)
    for i, key in enumerate(ta_sources):
        title_text = str(slots.get(key, ""))
        out_key = "tags" if i == 0 else f"tags_{i + 1}"
        slots[out_key] = classify_task_tags(tagging_mod, task_tag_keywords, title_text)


def stable_int(*parts: str) -> int:
    """A deterministic integer from arbitrary strings — independent of
    PYTHONHASHSEED / dict order, unlike the builtin hash()."""
    h = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def placeholder_info(token: str):
    """Resolve a template token ('event_title2') to (bank_key, semantic_key,
    base_name). Trailing digit N>=2 suffixes the semantic key ('title_2')
    while reusing the base's bank. Raises on an unknown placeholder."""
    if token in BASE_INFO:
        bank_key, semantic = BASE_INFO[token]
        return bank_key, semantic, token
    m = re.match(r"^(.+?)(\d)$", token)
    if m and m.group(1) in BASE_INFO:
        base = m.group(1)
        bank_key, semantic = BASE_INFO[base]
        digit = m.group(2)
        if semantic is not None:
            semantic = f"{semantic}_{digit}"
        return bank_key, semantic, base
    raise ValueError(f"unknown placeholder token: {{{token}}}")


#: Which BASE_INFO placeholders are a WHEN. Read off the bank each token draws
#: from, so a new time placeholder cannot be forgotten here — it has to name one
#: of these banks to be a time at all.
TIME_BANKS = {"dates", "times", "time_ranges", "recurrences", "durations",
              "lead_times", "query_ranges",
              "weekdays", "clock_times", "uk_times", "uk_dates", "recurrences_more"}

#: Prepositions and connectives that exist ONLY to attach the time that follows
#: them. Removed with it, or the action words keep a dangling "at".
_TIME_LEADIN = re.compile(
    r"(?:\s+(?:at|on|in|for|by|from|until|till|through|starting|beginning|"
    r"every|due)\b)?\s*$", re.I)


def _is_time_token(tok: str) -> bool:
    bank_key, _semantic, _base = placeholder_info(tok)
    return bank_key in TIME_BANKS


def gold_item(fam: dict, template: str, values: dict) -> dict:
    """The Item segmentation and decompose_validate SHOULD hand FastRule.

    This is the whole point of C1 (`fastrule/PLAN.md` §3): FastRule's board was
    feeding it the REAL segmenter's output, so the stage was being measured
    through an upstream that is frozen and lossy — and the rows it did get were
    a biased subset (the ones segmentation happened to get right). Gold items
    let the stage be tested ALONE.

    **The gold cannot come from running the pipeline** — that would score
    FastRule against what the upstream produced rather than against truth, and
    bake in the upstream's 265 lost items and 162 invented ones. It comes from
    the TEMPLATE, which is not circular: the generator composed the sentence
    from named slots, so it knows which words are the action and which are the
    time BEFORE any stage reads them.

    Returns `{"text", "time", "kind"}` — `Item.text` (the action words),
    `Item.time` (the when, AS SPOKEN, unresolved), and the tag.
    """
    action_parts: list[str] = []
    time_parts: list[str] = []
    pos = 0
    for m in TOKEN_RE.finditer(template):
        tok = m.group(1)
        before = template[pos:m.start()]
        if _is_time_token(tok):
            # drop the connective that only existed to attach this time
            action_parts.append(_TIME_LEADIN.sub("", before))
            time_parts.append(before[len(_TIME_LEADIN.sub("", before)):])
            time_parts.append("{" + tok + "}")
        else:
            action_parts.append(before)
            action_parts.append("{" + tok + "}")
        pos = m.end()
    action_parts.append(template[pos:])

    def _render(parts):
        s = "".join(parts).format(**values)
        return re.sub(r"\s+", " ", s).strip(" ,.")

    action = _render(action_parts)
    when = _render(time_parts)

    act = fam.get("action") or ""
    kind = ("task" if act.endswith("todo")
            else "event" if act.endswith("event")
            else "review" if act.startswith("query")
            else "event")
    return {"text": action, "time": when or None, "kind": kind}


def family_tokens(template: str):
    seen = []
    for tok in TOKEN_RE.findall(template):
        if tok not in seen:
            seen.append(tok)
    return seen


def validate_family(fam: dict, fillers: dict):
    """Catch authoring bugs early: two different placeholders writing the
    same semantic slot key (the second would silently clobber the first)."""
    tokens = family_tokens(fam["template"])
    semantic_keys = []
    for tok in tokens:
        bank_key, semantic, _ = placeholder_info(tok)
        if bank_key not in fillers:
            raise ValueError(f"family {fam['family']}: unknown bank '{bank_key}'")
        if semantic is not None:
            semantic_keys.append(semantic)
    dupes = [k for k, n in Counter(semantic_keys).items() if n > 1]
    if dupes:
        raise ValueError(
            f"family {fam['family']}: template writes slot(s) {dupes} from "
            f"two different placeholders — suffix the second ask's token "
            f"(e.g. task_title2) so it doesn't clobber the first")


def family_capacity(fam: dict, fillers: dict) -> int:
    """Rough upper bound on unique renderable rows for this family — the
    product of each distinct placeholder's bank size, capped so one
    enormous family can't be asked to swallow the whole quota."""
    tokens = family_tokens(fam["template"])
    if not tokens:
        return 1
    cap = 1
    for tok in tokens:
        bank_key, _, _ = placeholder_info(tok)
        cap *= max(1, len(fillers[bank_key]))
        if cap > 5000:
            return 5000
    return cap


def resolve_slots(fam: dict, values: dict, tokens: list[str]) -> dict:
    slots = {}
    for tok in tokens:
        _, semantic, _ = placeholder_info(tok)
        if semantic is not None:
            slots[semantic] = values[tok]
    # fixed_slots may reference the row's own picks via {token} — resolved
    # AFTER the auto slots so an explicit override wins on key collision.
    for key, wren in fam.get("fixed_slots", {}).items():
        if isinstance(wren, str) and "{" in wren:
            wren = wren.format(**values)
        slots[key] = wren
    for key, wren in fam.get("flags", {}).items():
        slots[key] = wren
    if "quoted_item" in tokens:
        slots["quoted"] = True
    if "generic_target" in tokens:
        slots["generic_target"] = True
    raw_recurrence = slots.get("recurrence")
    if raw_recurrence and raw_recurrence in RECURRENCE_ROUND:
        slots.setdefault("recurrence_rounded", RECURRENCE_ROUND[raw_recurrence])
    return slots


def gen_family_rows(fam: dict, quota: int, fillers: dict,
                    global_seen: set) -> list[tuple[str, dict, dict, dict]]:
    tokens = family_tokens(fam["template"])
    value_lists = {}
    for tok in tokens:
        bank_key, _, _ = placeholder_info(tok)
        value_lists[tok] = fillers[bank_key]

    rng = random.Random(f"{SEED}:{fam['family']}")
    rows: list[tuple[str, dict]] = []
    seen_combo = set()
    attempts = 0
    max_attempts = max(200, quota * 60)
    while len(rows) < quota and attempts < max_attempts:
        attempts += 1
        if tokens:
            combo = tuple(rng.choice(value_lists[t]) for t in tokens)
        else:
            combo = ()
        if combo in seen_combo:
            continue
        seen_combo.add(combo)
        values = dict(zip(tokens, combo))
        text = fam["template"].format(**values).strip()
        text = re.sub(r"\s+", " ", text)
        if text in global_seen:
            continue
        slots = resolve_slots(fam, values, tokens)
        global_seen.add(text)
        # The GOLD ITEM, computed here because `values` is only in scope here.
        # C1: it makes FastRule testable ALONE, without the real segmenter in
        # the path. See `gold_item` for why the template is the only
        # non-circular source for it.
        rows.append((text, slots, gold_item(fam, fam["template"], values), values))
    return rows


def distribute_quota(total: int, families: list[str], capacities: dict[str, int]) -> dict[str, int]:
    """Largest-remainder distribution of `total` rows across `families`,
    each capped at its own capacity, with any resulting deficit spread
    round-robin (deterministic order) across families with spare room. Sums
    to exactly `total` as long as aggregate capacity allows it."""
    order = sorted(families, key=lambda f: stable_int(SEED, "order", f))
    n = len(order)
    base, rem = divmod(total, n)
    quotas = {f: base for f in order}
    for f in order[:rem]:
        quotas[f] += 1

    deficit = 0
    for f in order:
        cap = capacities[f]
        if quotas[f] > cap:
            deficit += quotas[f] - cap
            quotas[f] = cap

    if deficit:
        i = 0
        guard = 0
        while deficit > 0 and guard < 1_000_000:
            guard += 1
            f = order[i % n]
            i += 1
            if quotas[f] < capacities[f]:
                quotas[f] += 1
                deficit -= 1
        if deficit:
            raise ValueError(
                f"cannot fit {total} rows into families {order}: "
                f"total capacity {sum(capacities[f] for f in order)}")
    assert sum(quotas.values()) == total
    return quotas


def stratified_split(families: list[dict]) -> dict[str, str]:
    """Family -> 'train'|'test'. Stratified by (tier, action) so every
    action type present in a tier has representation on both sides — the
    held-out set must measure generalisation to UNSEEN pattern families,
    never just unseen fillers of a family the model already trained on."""
    buckets = defaultdict(list)
    for fam in families:
        buckets[(fam["tier"], fam["action"])].append(fam["family"])

    split = {}
    for key, fams in buckets.items():
        order = sorted(fams, key=lambda f: stable_int(SEED, "split", *key, f))
        n = len(order)
        if n == 1:
            # can't split a singleton bucket without losing coverage on one
            # side; keep it in train (train is where mining happens).
            test_n = 0
        else:
            test_n = max(1, round(0.2 * n))
            test_n = min(test_n, n - 1)  # always leave >=1 in train
        for f in order[:test_n]:
            split[f] = "test"
        for f in order[test_n:]:
            split[f] = "train"
    return split


def _init_family(fam: dict, tier: str, fillers: dict) -> None:
    """Shared per-family setup: tier tag, bank/collision validation, simple-tier
    action defaults, and label-source resolution. Used identically by the
    stratified path (`build_tier`) and the force-split path
    (`build_forced_test`) so a family behaves the same regardless of which
    pool it's declared in."""
    fam["tier"] = tier
    validate_family(fam, fillers)
    if tier == "simple":
        atomic, events, tasks = ACTION_DEFAULTS[fam["action"]]
        fam.setdefault("atomic", atomic)
        fam.setdefault("events", events)
        fam.setdefault("tasks", tasks)
    assert fam["action"] in ALL_ACTIONS, f"{fam['family']}: bad action {fam['action']}"
    assert isinstance(fam["atomic"], bool)
    assert isinstance(fam["events"], int) and isinstance(fam["tasks"], int)
    fam["_label_sources"] = resolve_label_sources(fam)


# ---------------------------------------------------------------------------
# GOLD FOLLOWS THE RULINGS — applied here, by construction, never by hand
# ---------------------------------------------------------------------------
#
# Two of Gil's rulings moved gold after these templates were written:
#
#   Q25/Q26 (2026-09-18)  a stated CLOCK or RANGE makes it an event, whatever
#                         the phrasing — "remind me to feed the cat at 14:00"
#                         is an event.
#   Q47     (2026-09-24)  an ENCOUNTER with a person — met, seen, talked to or
#                         CALLED — is an event, day or no day ("call mum is an
#                         event at a default time like 9"). A written message
#                         ("email Dana") and a mention stay to-dos.
#
# Q26's relabel was first applied to the JSONL by hand (8dcf047, 12c78dd: 42
# rows), so this generator stopped reproducing the file — and the hand rule
# missed rows it should have taken ("at 9 in the morning", bare ranges like
# "between 2 and 4": 7 train rows, 5 sealed-test rows left contradicting Q26).
# The relabel lives HERE now (2026-09-24), declared per family by the part of
# the template that decides it, so a regeneration reproduces it and cannot
# drift. Words are untouched — only the gold follows the ruling — and ids and
# splits do not move. Each relabelled row carries `expect.ruled` naming the
# ruling. DATASET.md §"Gold that follows a ruling" has the counts.

#: The `times` fillers that are NOT a clock: a part of the day or a hedge, which
#: Q27/Q47(A) leave to the verb. Every other `times` filler states a clock.
NOT_A_CLOCK = frozenset({"first thing in the morning", "around lunchtime", "late afternoon"})

#: family -> (ruling, [(title slot that becomes an event, the token whose value
#: decides, or None when the family's words always qualify)]).
RULED_FAMILIES = {
    # Q26 — a to-do said with its own clock or range
    "s_ct_task_with_time":  ("Q26", [("title", "time")]),
    "c_recur_7":            ("Q26", [("title", "time")]),
    "c_recur_12":           ("Q26", [("title", "time")]),
    "c_range_ct_1":         ("Q26", [("title", "time_range")]),
    "c_remindthen_2":       ("Q26", [("title", "time")]),
    "c_timelist_ct_1":      ("Q26", [("title", "time"), ("title_2", "time2")]),
    "c_timelist_ct_2":      ("Q26", [("title", "time"), ("title_2", "time2")]),
    "c_timelist_ct_3":      ("Q26", [("title", "time"), ("title_2", "time2")]),
    "c_timelist_ct_4":      ("Q26", [("title", "time"), ("title_2", "time2")]),
    # Q47 — calling a named person is an encounter ("email {name}" is not)
    "s_ct_call_someone":        ("Q47", [("title", None)]),
    "s_ct_call_someone_date":   ("Q47", [("title", None)]),
    "c_attendee_8":             ("Q47", [("title", None)]),
    "c_npdecoy_call_two_task":  ("Q47", [("title", None)]),
    "c_joiner_commathen_tt_1":  ("Q47", [("title", None), ("title_2", None)]),
    "c_remindthen_5":           ("Q47", [("title", None)]),
}


#: OPERATION relabels by ruling (2026-09-24, Gil: "todo is fine if not given a
#: time, if time given make an event, i have been clear on previous similar
#: things"). "add a note to {task_title}" was gold UPDATE_TODO (a note on an
#: existing task); read by the rulings it is a new TO-DO — "make a note to"
#: is a create frame, and its template carries no time. family -> (ruling,
#: new action).
RULED_OPERATIONS = {
    "s_ut_add_note": ("Q47", "create_todo"),
}


def _states_a_clock(token: str, value: str) -> bool:
    bank_key, _semantic, _base = placeholder_info(token)
    if bank_key == "time_ranges":
        return True
    return bank_key == "times" and value not in NOT_A_CLOCK


#: Q50 (2026-09-25) — a live call to a ROLE ("call the plumber", from the
#: `task_titles` bank) is an event like a call to a person. Decided by the
#: title's own words through the engine's shared rule, not per family, because
#: the phrase arrives through a bank that 40-odd families draw on. A command
#: that names the to-do list keeps it a to-do (Q47).
def _q50_moves(fam: dict, slots: dict, text: str, ta: list) -> list:
    from assistant.intent.encounter import is_role_call, names_the_list
    if fam["action"] not in ("create_todo", "mixed") or names_the_list(text):
        return []
    return [k for k in ta if is_role_call(str(slots.get(k) or ""))]


def ruled_family(fam: dict, values: dict, slots: "dict | None" = None,
                 text: str = "") -> "dict | None":
    """The family as the RULINGS read this row, or None when no ruling
    touches it. A copy: action, counts and label sources follow the parts
    that became events; the template, the words and the split do not move."""
    op = RULED_OPERATIONS.get(fam["family"])
    if op:
        ruling, action = op
        out = dict(fam)
        out["action"] = action
        out["events"], out["tasks"] = 0, 1
        out["_label_sources"] = ([], ["title"])
        out["_ruled"] = ruling
        return out
    spec = RULED_FAMILIES.get(fam["family"])
    ev, ta = (list(x) for x in fam["_label_sources"])
    moved = []
    ruling = None
    if spec:
        ruling, parts = spec
        moved = [key for key, tok in parts
                 if key in ta and (tok is None or _states_a_clock(tok, values[tok]))]
    role = [k for k in _q50_moves(fam, slots or {}, text, ta) if k not in moved]
    if role:
        ruling = f"{ruling}+Q50" if moved else "Q50"
        moved += role
    if not moved:
        return None
    ta = [k for k in ta if k not in moved]
    ev = sorted(ev + moved, key=lambda k: int(TITLE_KEY_RE.match(k).group(2) or 1))
    out = dict(fam)
    out["events"], out["tasks"] = len(ev), len(ta)
    out["action"] = ("mixed" if ev and ta else "create_event" if ev else fam["action"])
    out["_label_sources"] = (ev, ta)
    out["_ruled"] = ruling
    return out


def _emit_family_rows(fam: dict, split_name: str, quota: int, tier: str, fillers: dict,
                       global_seen: set, categories_mod, tagging_mod, task_tag_keywords: dict) -> list[dict]:
    """Generate `quota` rows for one family already assigned to `split_name`,
    label them, and return them as finished row dicts."""
    fam_rows = gen_family_rows(fam, quota, fillers, global_seen)
    if len(fam_rows) < quota:
        raise ValueError(
            f"family {fam['family']} only produced {len(fam_rows)}/{quota} "
            f"unique rows — widen its filler banks")
    out = []
    counter = 0
    for text, slots, item, values in fam_rows:
        counter += 1
        row_fam = ruled_family(fam, values, slots, text) or fam
        if row_fam is not fam:
            item = dict(item, kind="task" if row_fam["action"].endswith("todo") else "event")
        add_labels(row_fam, slots, categories_mod, tagging_mod, task_tag_keywords)
        out.append({
            "id": f"{fam['family']}-{counter:03d}",
            "text": text,
            "split": split_name,
            "tier": tier,
            "family": fam["family"],
            "expect": {
                "events": row_fam["events"],
                "tasks": row_fam["tasks"],
                "action": row_fam["action"],
                "atomic": fam["atomic"],
                "slots": slots,
                # The Item the two upstream stages SHOULD produce (C1,
                # 2026-09-10). ADDITIVE — every field above is untouched, which
                # C2 asserts by regenerating and diffing with this key removed.
                "item": item,
                **({"ruled": row_fam["_ruled"]} if row_fam is not fam else {}),
            },
        })
    return out


def build_tier(tier: str, patterns: list[dict], total: int, fillers: dict, global_seen: set,
                categories_mod, tagging_mod, task_tag_keywords: dict):
    """The original stratified 80/20 path — unchanged in every particular
    from before force-split families existed. `patterns` must already
    exclude any family with `force_split` set (see `main()`): mixing forced
    families into this function's stratification would shift the hash-based
    80/20 computation for every OTHER family in their (tier, action) bucket,
    which is exactly the perturbation force-split exists to avoid."""
    for fam in patterns:
        assert "force_split" not in fam, f"{fam['family']}: forced family passed to build_tier"
        _init_family(fam, tier, fillers)

    split_of = stratified_split(patterns)
    for fam in patterns:
        fam["split"] = split_of[fam["family"]]

    capacities = {fam["family"]: family_capacity(fam, fillers) for fam in patterns}

    rows = []
    for split_name, target in (("train", round(total * TRAIN_FRAC)), ("test", total - round(total * TRAIN_FRAC))):
        fams = [fam for fam in patterns if fam["split"] == split_name]
        quotas = distribute_quota(target, [f["family"] for f in fams], capacities)
        for fam in fams:
            rows += _emit_family_rows(fam, split_name, quotas[fam["family"]], tier, fillers,
                                       global_seen, categories_mod, tagging_mod, task_tag_keywords)
    return rows


def build_forced_test(tier: str, patterns: list[dict], total: int, fillers: dict, global_seen: set,
                       categories_mod, tagging_mod, task_tag_keywords: dict):
    """Families with `force_split: "test"` — assigned directly, bypassing
    `stratified_split()`'s hash-based 80/20 entirely (that mechanism, and
    every row it produces for the ORIGINAL families, is untouched — see
    `build_tier`). `total` is this pool's own row target (engine/TRAIN_TEST_SPLIT_CONVENTION.md), added
    ON TOP of the tier's original SIMPLE_TOTAL/COMPLEX_TOTAL, not carved out
    of it — that's what keeps train exactly as it was."""
    return _build_forced("test", tier, patterns, total, fillers, global_seen,
                         categories_mod, tagging_mod, task_tag_keywords)


def build_forced_train(tier: str, patterns: list[dict], total: int, fillers: dict, global_seen: set,
                        categories_mod, tagging_mod, task_tag_keywords: dict):
    """Families with `force_split: "train"` (2026-09-25) — the exact mirror of
    `build_forced_test`: assigned directly to TRAIN, bypassing
    `stratified_split()`, with `total` (SIMPLE/COMPLEX_FORCE_TRAIN_TOTAL) added
    on top of every other pool. `main()` runs it LAST, so every existing row —
    train, stratified test and forced test — has already claimed its text in
    `global_seen` and can never be displaced by a new family's render."""
    return _build_forced("train", tier, patterns, total, fillers, global_seen,
                         categories_mod, tagging_mod, task_tag_keywords)


def _build_forced(split_name: str, tier: str, patterns: list[dict], total: int, fillers: dict,
                  global_seen: set, categories_mod, tagging_mod, task_tag_keywords: dict):
    """The one body both forced pools share. Byte-identical to the original
    `build_forced_test` loop for `split_name == "test"`."""
    for fam in patterns:
        assert fam.get("force_split") == split_name, (
            f"{fam['family']}: the forced-{split_name} pool only takes "
            f"force_split={split_name!r} (got {fam.get('force_split')!r})")
        _init_family(fam, tier, fillers)
        fam["split"] = split_name

    capacities = {fam["family"]: family_capacity(fam, fillers) for fam in patterns}
    quotas = distribute_quota(total, [f["family"] for f in patterns], capacities)

    rows = []
    for fam in patterns:
        rows += _emit_family_rows(fam, split_name, quotas[fam["family"]], tier, fillers,
                                   global_seen, categories_mod, tagging_mod, task_tag_keywords)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-write", action="store_true",
                     help="build and verify in memory but don't write the jsonl")
    ap.add_argument("--out", default=str(OUT),
                    help="where to write (default: the committed fastrule_7200.jsonl); "
                         "a scratch path is how a regeneration is diffed before it lands")
    args = ap.parse_args()

    fillers = load_json("fillers.json")
    simple_patterns = load_json("simple_patterns.json")
    complex_patterns = load_json("complex_patterns.json")
    categories_fixture = load_json("categories_fixture.json")
    task_tag_keywords = {t["name"]: t["keywords"] for t in categories_fixture["task_tags"]}
    categories_mod, tagging_mod = setup_label_env()

    # force_split families are pulled OUT before the stratified path ever
    # sees them: build_tier's input set (and therefore its hash-based 80/20
    # bucket membership and every row it produces) is then IDENTICAL to what
    # it was before any force_split family existed — that's what makes the
    # train set — and the original 6,000 stratified rows generally —
    # byte-identical across this growth.
    for fam in simple_patterns + complex_patterns:
        if fam.get("force_split") not in (None, "test", "train"):
            raise ValueError(f"{fam['family']}: unknown force_split {fam['force_split']!r}")
    simple_free = [f for f in simple_patterns if not f.get("force_split")]
    simple_forced = [f for f in simple_patterns if f.get("force_split") == "test"]
    simple_forced_train = [f for f in simple_patterns if f.get("force_split") == "train"]
    complex_free = [f for f in complex_patterns if not f.get("force_split")]
    complex_forced = [f for f in complex_patterns if f.get("force_split") == "test"]
    complex_forced_train = [f for f in complex_patterns if f.get("force_split") == "train"]

    global_seen: set[str] = set()
    rows = []
    rows += build_tier("simple", simple_free, SIMPLE_TOTAL, fillers, global_seen,
                        categories_mod, tagging_mod, task_tag_keywords)
    rows += build_tier("complex", complex_free, COMPLEX_TOTAL, fillers, global_seen,
                        categories_mod, tagging_mod, task_tag_keywords)
    stratified_row_count = len(rows)

    # Forced-test families run AFTER the stratified path completes and only
    # ever APPEND to global_seen/rows — so even in the (astronomically
    # unlikely) event a new family's text would collide with an existing
    # one, the EXISTING family always wins the string; new families just
    # skip to their next candidate. Existing rows never even see this pool.
    rows += build_forced_test("simple", simple_forced, SIMPLE_FORCE_TEST_TOTAL, fillers, global_seen,
                               categories_mod, tagging_mod, task_tag_keywords)
    rows += build_forced_test("complex", complex_forced, COMPLEX_FORCE_TEST_TOTAL, fillers, global_seen,
                               categories_mod, tagging_mod, task_tag_keywords)

    # Final deterministic shuffle so consecutive rows aren't bursts from one
    # family — still 100% reproducible from SEED.
    order_rng = random.Random(f"{SEED}:final-order")
    order_rng.shuffle(rows)

    # Forced-TRAIN families run LAST (2026-09-25), after every existing row has
    # claimed its text, and are shuffled on their OWN stream and appended — so
    # the 7,200 rows above keep their content, their ids AND their line order,
    # and the committed file's diff for this pool is a pure append.
    train_growth = []
    train_growth += build_forced_train("simple", simple_forced_train, SIMPLE_FORCE_TRAIN_TOTAL, fillers,
                                       global_seen, categories_mod, tagging_mod, task_tag_keywords)
    train_growth += build_forced_train("complex", complex_forced_train, COMPLEX_FORCE_TRAIN_TOTAL, fillers,
                                       global_seen, categories_mod, tagging_mod, task_tag_keywords)
    random.Random(f"{SEED}:final-order:forced-train").shuffle(train_growth)
    rows += train_growth

    # ---- verification -----------------------------------------------
    texts = [r["text"] for r in rows]
    expected_total = (SIMPLE_TOTAL + COMPLEX_TOTAL + SIMPLE_FORCE_TEST_TOTAL + COMPLEX_FORCE_TEST_TOTAL
                      + SIMPLE_FORCE_TRAIN_TOTAL + COMPLEX_FORCE_TRAIN_TOTAL)
    assert len(rows) == expected_total, (len(rows), expected_total)
    assert len(set(texts)) == len(texts), "duplicate text rows"

    by_split = Counter(r["split"] for r in rows)
    train_n, test_n = by_split["train"], by_split["test"]
    total = len(rows)

    forced_families = {f["family"] for f in (simple_forced + complex_forced)}
    forced_train_families = {f["family"] for f in (simple_forced_train + complex_forced_train)}
    forced_test_rows_in_train = [r for r in rows if r["family"] in forced_train_families and r["split"] != "train"]
    if forced_test_rows_in_train:
        raise ValueError(f"force_split='train' family produced non-train rows: {forced_test_rows_in_train[:3]}")
    growth_n = sum(1 for r in rows if r["family"] in forced_train_families)
    if growth_n != SIMPLE_FORCE_TRAIN_TOTAL + COMPLEX_FORCE_TRAIN_TOTAL:
        raise ValueError(f"forced-train pool produced {growth_n} rows")

    # The ORIGINAL stratified pool must still land at ~80/20 — the same
    # invariant as before force_split existed, checked over exactly the same
    # population (excluding the new forced-test rows entirely).
    assert stratified_row_count == SIMPLE_TOTAL + COMPLEX_TOTAL
    stratified_test_n = sum(1 for r in rows if r["family"] not in forced_families and r["split"] == "test")
    stratified_test_frac = stratified_test_n / stratified_row_count
    if not (0.19 <= stratified_test_frac <= 0.21):
        raise ValueError(f"stratified-pool split fraction out of tolerance: test={stratified_test_frac:.4f}")

    # Train must be EXACTLY the original 4,800: force_split families are
    # test-only by construction (build_forced_test asserts this on every
    # family), so any forced-family row landing in train means the
    # mechanism leaked, and any drift in the total train count at all means
    # the stratified pool was perturbed.
    forced_train_rows = [r for r in rows if r["family"] in forced_families and r["split"] == "train"]
    if forced_train_rows:
        raise ValueError(f"force_split family produced train rows: {forced_train_rows[:3]}")
    expected_train = round(SIMPLE_TOTAL * TRAIN_FRAC) + round(COMPLEX_TOTAL * TRAIN_FRAC)
    stratified_train_n = sum(1 for r in rows if r["split"] == "train"
                             and r["family"] not in forced_train_families)
    if stratified_train_n != expected_train:
        raise ValueError(f"stratified train count drifted from the original {expected_train}: "
                         f"{stratified_train_n}")
    if train_n != expected_train + growth_n:
        raise ValueError(f"train count {train_n} != {expected_train} + forced-train {growth_n}")

    fam_counts = Counter(r["family"] for r in rows)
    max_family_frac = max(fam_counts.values()) / total
    if max_family_frac > 0.03:
        worst = fam_counts.most_common(1)[0]
        raise ValueError(f"family {worst} exceeds 3% of total ({max_family_frac:.2%})")

    train_families = {r["family"] for r in rows if r["split"] == "train"}
    test_families = {r["family"] for r in rows if r["split"] == "test"}
    leaked = train_families & test_families
    if leaked:
        raise ValueError(f"families present in both train and test: {leaked}")

    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids), "duplicate ids"

    # ---- composition table -------------------------------------------
    print(f"TOTAL rows: {total}  (stratified pool {stratified_row_count}: "
          f"simple {SIMPLE_TOTAL} / complex {COMPLEX_TOTAL}  +  "
          f"forced-test pool {SIMPLE_FORCE_TEST_TOTAL + COMPLEX_FORCE_TEST_TOTAL}: "
          f"simple {SIMPLE_FORCE_TEST_TOTAL} / complex {COMPLEX_FORCE_TEST_TOTAL}  +  "
          f"forced-train pool {SIMPLE_FORCE_TRAIN_TOTAL + COMPLEX_FORCE_TRAIN_TOTAL}: "
          f"simple {SIMPLE_FORCE_TRAIN_TOTAL} / complex {COMPLEX_FORCE_TRAIN_TOTAL})")
    print(f"Split: train={train_n} ({train_n/total:.1%})  test={test_n} ({test_n/total:.1%})  "
          f"[train is EXACTLY the original {expected_train} + the forced-train {growth_n}]")
    print(f"  of which forced-test: {len(forced_families)} families, "
          f"{sum(1 for r in rows if r['family'] in forced_families)} rows "
          f"(all test, by construction)")
    print(f"  of which forced-train: {len(forced_train_families)} families, "
          f"{growth_n} rows (all train, by construction)")
    print(f"  stratified-pool-only split: test={stratified_test_frac:.1%} "
          f"(the original ~80/20, unperturbed by the forced pool)")
    print(f"Unique texts: {len(set(texts))}/{total}")
    print(f"Families: {len(fam_counts)} total "
          f"({len(train_families)} train, {len(test_families)} test, "
          f"{len(leaked)} leaked)")
    print(f"Largest family: {fam_counts.most_common(1)[0][0]} = "
          f"{fam_counts.most_common(1)[0][1]} rows "
          f"({max_family_frac:.2%} of total)")
    print()
    print("By tier x split:")
    tier_split = Counter((r["tier"], r["split"]) for r in rows)
    for tier in ("simple", "complex"):
        print(f"  {tier:8s}  train={tier_split[(tier,'train')]:5d}  "
              f"test={tier_split[(tier,'test')]:5d}")
    print()
    print("By action x tier (row counts):")
    action_tier = Counter((r["expect"]["action"], r["tier"]) for r in rows)
    actions_sorted = sorted(ALL_ACTIONS)
    print(f"  {'action':16s} {'simple':>8s} {'complex':>8s} {'total':>8s}")
    for act in actions_sorted:
        s = action_tier[(act, "simple")]
        c = action_tier[(act, "complex")]
        print(f"  {act:16s} {s:8d} {c:8d} {s+c:8d}")
    print()
    print("By atomic flag x tier:")
    atomic_tier = Counter((r["tier"], r["expect"]["atomic"]) for r in rows)
    for tier in ("simple", "complex"):
        print(f"  {tier:8s}  atomic={atomic_tier[(tier, True)]:5d}  "
              f"compound={atomic_tier[(tier, False)]:5d}")
    print()
    print("Nuance families (complex tier):")
    nuance_fam = defaultdict(set)
    nuance_rows = Counter()
    for fam in complex_patterns:
        nuance_fam[fam.get("nuance", "?")].add(fam["family"])
    for r in rows:
        if r["tier"] == "complex":
            fam = next(f for f in complex_patterns if f["family"] == r["family"])
            nuance_rows[fam.get("nuance", "?")] += 1
    for nuance in sorted(nuance_fam):
        print(f"  {nuance:24s} families={len(nuance_fam[nuance]):3d}  "
              f"rows={nuance_rows[nuance]:4d}")

    print()
    print("Event category coverage (rows with >=1 expected event):")
    cat_counts = Counter()
    events_expected = 0
    for r in rows:
        n = r["expect"]["events"]
        events_expected += n
        for i in range(1, n + 1):
            key = "category" if i == 1 else f"category_{i}"
            cat_counts[r["expect"]["slots"].get(key, "<MISSING>")] += 1
    for cat, n in cat_counts.most_common():
        print(f"  {cat:12s} {n:5d}  ({n/max(1,events_expected):.1%})")
    print()
    print("Task tag coverage (rows with >=1 expected task):")
    tasks_expected = 0
    untagged = 0
    tag_counts = Counter()
    multi_tag = 0
    for r in rows:
        n = r["expect"]["tasks"]
        tasks_expected += n
        for i in range(1, n + 1):
            key = "tags" if i == 1 else f"tags_{i}"
            tags = r["expect"]["slots"].get(key, None)
            if tags is None:
                raise ValueError(f"row {r['id']}: expected task #{i} has no '{key}'")
            if not tags:
                untagged += 1
            else:
                tag_counts.update(tags)
                if len(tags) > 1:
                    multi_tag += 1
    print(f"  untagged (empty list): {untagged:5d}  ({untagged/max(1,tasks_expected):.1%})")
    print(f"  multi-tag (2+ tags):   {multi_tag:5d}  ({multi_tag/max(1,tasks_expected):.1%})")
    for tag, n in tag_counts.most_common():
        print(f"  {tag:12s} {n:5d}")

    if args.no_write:
        print("\n--no-write: skipping file output")
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True))
            f.write("\n")
    print(f"\nWrote {total} rows to {out}")


if __name__ == "__main__":
    main()
