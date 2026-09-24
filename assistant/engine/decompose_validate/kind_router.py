"""The event-or-to-do ROUTER — basic rules, otherwise a model.

Gil, 2026-09-24 (DEVQA Q47), on the router between an event and a to-do:
*"basic rules, otherwise model"*.

    rules        the tagger's own readers (`fastseg.tag_path`) and the rulings'
                 regexes. Whenever ONE of them fired, its answer stands —
                 a stated clock (Q25/Q26), an encounter with a person (Q47), a
                 named to-do list, "remind me to <verb>", a scheduling or chore
                 verb, a calendar destination, … every path `tag_path` names.
    otherwise    `path == "default"`: `_kind_of` fell through to its catch-all
                 `event` and nothing moved it — the tagger had NO reading, it
                 said "event" because nothing said otherwise. Only there does
                 the learned model decide, from the words' SHAPE (frames, head
                 verb, day/part-of-day/recurrence flags) and the tagger's verdict.

"No rule fired" is therefore a CODE PATH, not a confidence: the model can
never overturn a reading any rule gave, so it cannot contradict a ruling.

## Why here, and not in segmentation or at the front door

The kind is FINAL at this stage's entry: `decompose.run` branches entirely on
it (an event is time-split, a to-do is list-split and quantity-read), and
FastRule's converter narrows the create action by it. So the router runs FIRST
in `stage.run`, before anything reads the kind. Segmentation is frozen to
implementation fixes (Gil, 2026-09-12) and a learned model inside it is a
design change; this is where Gil placed the idea ("for the decompose validate
step stage"). The FRONT DOOR (`fastrule/fast_track.py`) is untouched: it only
commits when the rule parser is CONFIDENT, which is a rule firing by
definition, so the model's domain — no rule fired — never reaches it.

## The model

`models/kind_router.joblib`, fitted by
`experiments/kind_router_board.py --fit` on the TRAIN halves only (FastRule
7,200, LLMJudge v2, segmentation's corpus — gold relabelled by rule for Q26 and
Q47 on 2026-09-24). sklearn, loaded lazily, no model server: nothing here
touches ollama. A missing or unreadable artefact means the tagger's answer
stands, which is exactly the behaviour before this existed.

Category (the label classifiers) is deliberately NOT a feature: measured on
6,844 TEST items it added −0.2 to +0.4 pt beyond shape
(`experiments/RESULTS.md`, 2026-09-24).
"""
from __future__ import annotations

import functools
import importlib
import pathlib
import re

import numpy as np

MODEL_PATH = pathlib.Path(__file__).resolve().parent / "models" / "kind_router.joblib"

#: Bumped whenever `shape_features` changes: an artefact fitted on another
#: feature layout is refused rather than read wrong.
FEATURE_VERSION = 1

KINDS = ("event", "task")


def _fs():
    return importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def rule_fired(text: str, time_str: str) -> "tuple[str, str] | None":
    """`(kind, path)` when a rule decided this item's kind, else None.

    The tagger's own path first: anything but "default" is a reader that
    fired. On the default path the rulings are checked explicitly as well —
    the tagger's catch-all `event` can coincide with a stated clock, and that
    item was decided by Q26, not by the catch-all.
    """
    FS = _fs()
    kind, path = FS.tag_path(text, time_str)
    if path != "default":
        return kind, path
    t = time_str or ""
    if FS._STATED_CLOCK.search(t) and not FS._VAGUE_TIME_HEDGE.search(text) \
            and not FS._DUE_DATE_EDIT.match(text) and not FS._is_not_calendar(text, time_str):
        return "event", "stated_clock"
    from assistant.intent.encounter import is_encounter
    if is_encounter(text):
        return "event", "encounter"
    from assistant.engine.segmentation.fastseg import kind as K
    if _list_dest().search(text):
        return "task", "todo_destination"
    if K._REMIND_TO_VERB_RE.search(text):
        return "task", "remind_to_verb"
    return None


@functools.lru_cache(maxsize=1)
def _list_dest() -> "re.Pattern":
    """The tagger's own to-do-destination pattern (`kind._LIST_DEST`)."""
    from assistant.engine.segmentation.fastseg import kind as K
    return re.compile(K._LIST_DEST, re.I)


# ---------------------------------------------------------------------------
# features — the words' SHAPE, plus the tagger's verdict
# ---------------------------------------------------------------------------

_DAYPART = re.compile(r"\b(morning|afternoon|evening|tonight|night|noon|midday|lunchtime)\b", re.I)
_RECUR = re.compile(r"\b(every|each|daily|weekly|monthly|yearly|weekday|weekdays|weekends)\b", re.I)
_RANGE = re.compile(r"\bfrom\s+\S+\s+(?:to|until|till)\s+\S+|\bbetween\s+\S+\s+and\s+\S+", re.I)
_DAY = re.compile(
    r"\b(today|tomorrow|tonight|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday|weekend|week|month|january|february|march|april|may|june|july|august|"
    r"september|october|november|december|\d{1,2}(st|nd|rd|th))\b", re.I)

_FRAMES_SRC = {
    "remind_to": r"\bremind\s+\w+\s+to\b",
    "remind_about": r"\bremind\s+\w+\s+(?:about|of)\b|\breminder\s+(?:for|about)\b",
    "reminder_word": r"\bremind(?:er)?s?\b|\bnotify\b",
    "calendar_dest": r"\b(?:on|to|in|from|off)\s+(?:my|the)\s+(?:calendar|schedule|diary|agenda)\b",
    "sched_verb": (r"\b(book|schedule|set\s+up|pencil\s+in|arrange|plan|organi[sz]e\s+a|"
                   r"put\s+.*\bin\s+the\s+diary|add\s+an?\s+event|create\s+an?\s+event|"
                   r"set\s+an?\s+(?:event|meeting|appointment))\b"),
    "note_to_self": r"\bnote\s+to\s+self\b|\bdon'?t\s+(?:let\s+me\s+)?forget\b|\bremember\s+to\b|\bmake\s+a\s+note\b",
    "need_to": r"\b(?:i\s+)?(?:need to|have to|gotta|got to|must|should)\b",
    "task_word": r"\b(to-?do|task|errand|list)s?\b",
    "event_word": r"\b(event|appointment|meeting|calendar)\b",
    "question": r"\?\s*$|^(?:what|when|where|who|do i|is|are|can i)\b",
}
_FRAMES = {k: re.compile(v, re.I) for k, v in _FRAMES_SRC.items()}


def head_word(text: str) -> str:
    FS = _fs()
    words = [w.strip(".!?,") for w in (text or "").lower().split()]
    while words and words[0] in FS._PREAMBLE:
        words.pop(0)
    return words[0] if words else "<empty>"


def shape_features(text: str, time_str: str) -> dict:
    """Named 0/1 (and one length) features of the item's own words and time."""
    FS = _fs()
    from assistant.engine.segmentation.fastseg import kind as K
    from assistant.intent.encounter import is_encounter
    t = time_str or ""
    norm_t = " ".join(t.lower().split())
    clock = bool(FS._STATED_CLOCK.search(t))
    f = {
        "clock": float(clock),
        "day": float(bool(_DAY.search(t))),
        "real_time": float(norm_t not in ("", "today")),
        "no_time": float(norm_t == ""),
        "daypart": float(bool(_DAYPART.search(t)) and not clock),
        "recur": float(bool(_RECUR.search(t))),
        "range": float(bool(_RANGE.search(t))),
        "person_arg": float(FS._has_person_argument(text)),
        "encounter": float(is_encounter(text)),
        "outreach_head": float(FS._head_is_outreach_verb(text)),
        "vague_hedge": float(bool(FS._VAGUE_TIME_HEDGE.search(text))),
        "anchored": float(bool(FS._ANCHORED_TO_EVENT.search(text))),
        "n_words": min(len(text.split()), 20) / 20.0,
        "list_dest": float(bool(_list_dest().search(text))),
        "occasion": float(bool(K._OCCASION_RE.search(text))),
        "chore_verb": float(bool(re.search(K._CHORE_VERB, text, re.I))),
        "gathering": float(bool(K._GATHERING_RE.search(text))),
        "done_frame": float(bool(re.search(K._TODO_DONE, text, re.I))),
    }
    lk = FS._lexicon_kind(text)
    f["lex_event"], f["lex_task"] = float(lk == "event"), float(lk == "task")
    for k, rx in _FRAMES.items():
        f[f"frame_{k}"] = float(bool(rx.search(text)))
    return f


def vectorise(rows, heads: dict) -> "np.ndarray":
    """rows: [(text, time, tagger_kind)] -> X. `heads` maps a head word to a
    column (fitted on TRAIN); anything else is the one `<other>` column."""
    out = []
    for text, time_str, tagk in rows:
        sh = shape_features(text, time_str)
        h = np.zeros(len(heads) + 1)
        h[heads.get(head_word(text), len(heads))] = 1
        eng = [float(tagk == "event"), float(tagk == "task"), float(tagk not in KINDS)]
        out.append(np.concatenate([np.array(list(sh.values())), h, eng]))
    return np.vstack(out) if out else np.zeros((0, 0))


def feature_names(heads: dict) -> list:
    names = list(shape_features("add milk to my list", "").keys())
    return names + [f"head={h}" for h in heads] + ["head=<other>"] + ["eng_event", "eng_task", "eng_other"]


# ---------------------------------------------------------------------------
# the model, lazily
# ---------------------------------------------------------------------------

_MODEL: dict = {}


def load(path: "pathlib.Path | None" = None) -> "dict | None":
    """The fitted artefact, or None (missing, unreadable, or another feature
    layout). Read once per process."""
    key = str(path or MODEL_PATH)
    if key not in _MODEL:
        blob = None
        try:
            import joblib
            p = pathlib.Path(key)
            if p.exists():
                blob = joblib.load(p)
                if blob.get("feature_version") != FEATURE_VERSION:
                    blob = None
        except Exception:
            blob = None
        _MODEL[key] = blob
    return _MODEL[key]


def reset() -> None:
    _MODEL.clear()


def route(text: str, time_str: str, model: "dict | None" = None) -> "tuple[str, str]":
    """`(kind, why)` for one item: `why` is `rule:<path>` or `model:<p_event>`,
    or `tagger:no-model` when no artefact is present (the tagger stands)."""
    got = rule_fired(text, time_str)
    if got is not None:
        return got[0], f"rule:{got[1]}"
    FS = _fs()
    tagk = FS.tag_path(text, time_str)[0]
    blob = model if model is not None else load()
    if not blob:
        return tagk, "tagger:no-model"
    X = vectorise([(text, time_str, tagk)], blob["heads"])
    p = float(blob["model"].predict_proba(X)[0, 1])
    return ("event" if p >= 0.5 else "task"), f"model:{p:.2f}"


def enabled(cfg) -> bool:
    """`engine.kind_router` (default on). `MACALENDAR_KIND_ROUTER=0|1` overrides
    it for ONE process — how a board runs the off/on arms at one commit
    without touching anyone's config.yaml."""
    import os
    env = os.environ.get("MACALENDAR_KIND_ROUTER")
    if env in ("0", "1"):
        return env == "1"
    eng = getattr(cfg, "engine", None)
    return bool(getattr(eng, "kind_router", True)) if eng is not None else True


def run(state, cfg):
    """Route every event/task item whose kind is the tagger's reading of its
    own words. An item whose kind came from elsewhere (a model segmenter, a
    rewrite that carried a kind) is not the tagger's call to revisit, so it is
    left alone."""
    if not enabled(cfg):
        return state
    FS = _fs()
    moved = []
    for item in state.items:
        if item.kind not in KINDS:
            continue
        text, when = item.text or "", item.time or ""
        tagk, path = FS.tag_path(text, when)
        if tagk != item.kind or path != "default":
            continue
        kind, why = route(text, when)
        if kind != item.kind and why.startswith("model:"):
            state.add_fix("decompose_validate", "kind_router", item.kind, kind,
                          f"no rule fired; the model read {why[6:]} event")
            moved.append(f"{item.id}: {item.kind} → {kind}")
            item.kind = kind
    if moved and state.trace:
        from assistant.trace import RULE
        state.trace.step(RULE, "Kind", "no rule fired — the router's model: " + "; ".join(moved))
    return state
