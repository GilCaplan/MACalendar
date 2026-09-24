"""KIND TWO-STAGE — does the label classifiers' reading help decide event vs to-do?

    ./.venv/bin/python -m assistant.engine.decompose_validate.experiments.kind_two_stage
    ./.venv/bin/python -m assistant.engine.decompose_validate.experiments.kind_two_stage --embed   # + ollama vectors

MEASUREMENT ONLY. Nothing here changes the engine; the decision to ship is Gil's.

Gil, 2026-09-24: *"the classifier of the category tag together with like
whatever other information we have would be enough to decide if it's an event
or a to-do... It would be like a two-stage model... just to route whether it's
an event or to-do task."*

    STAGE 1   the label classifiers read an ITEM's words and give probabilities:
              the event-category n-gram model (13 classes), the to-do-tag model
              (4 one-vs-rest), and the keyword rules (`categories.classify`,
              `tagging.infer_tag`) as one-hots.
    STAGE 2   a small classifier decides KIND from stage-1's outputs plus
              sentence-shape flags (stated clock, day, part of day, person,
              frames, head verb, question form).

The question is the ABLATION — shape alone, stage-1 alone, both — and whether
any of them beats the incumbent: `fastseg.tag(action, time)`, the engine's own
kind decision on the same item words.

Items, not commands: every row is ONE ask's own words and its own time phrase.
Sources keep their own split; TRAIN numbers are out-of-fold (5-fold, grouped by
family, so a row is never scored by a model that saw its family); TEST is
scored once by a model fitted on the whole TRAIN pool. Real usage has no split
and is never fitted on — it is a gate, TEST-only.

Rulings (DEVQA Q25/Q26/Q27/Q47) are LAW: `RULINGS` is a battery built from
their own examples, and a model is reported raw and GATED (the ruling's own
engine regex wins wherever it fires).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import time

# --- the scratch block: every store redirected BEFORE `assistant` is imported
_S = pathlib.Path(os.environ.get("KIND2_SCRATCH", tempfile.mkdtemp(prefix="kind2_")))
_S.mkdir(parents=True, exist_ok=True)
for _v, _n in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
               ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
               ("TRACE_BUS", "trace_bus.jsonl"), ("MODELS", "models"),
               ("LABEL_FEEDBACK", "fb.jsonl"), ("LLM_BUS", "llm_calls.jsonl"),
               ("CHECKPOINTS", "checkpoints"),
               ("DEVICE_SECRET", "device_secret"), ("DEVICES", "devices.json")):
    os.environ[f"MACALENDAR_{_v}"] = str(_S / _n)
os.environ["MACALENDAR_NO_WARMUP"] = "1"
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
os.environ.setdefault("MACALENDAR_LLM_SEED", "17")
os.environ["MACALENDAR_OBSERVANCE"] = "0"
for _t in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_t, "1")

import numpy as np  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
ENGINE = HERE.parents[1]                      # assistant/engine
ROOT = ENGINE.parents[1]
FASTRULE = ENGINE / "fastrule" / "datasets" / "fastrule_7200.jsonl"
V2 = ENGINE / "llmjudge" / "datasets" / "v2" / "commands_v2.jsonl"
SEG = ENGINE / "segmentation" / "datasets"
BOARD_D_CK = pathlib.Path.home() / ".assistant_tools" / "checkpoints" / "board_d_c45.jsonl"
REAL_DB = pathlib.Path.home() / ".assistant_tools" / "nlu_memory.db"
KINDS = ("event", "task")


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


# ---------------------------------------------------------------------------
# 1 · the items, per source, each with its own split
# ---------------------------------------------------------------------------

def load_fastrule() -> list:
    out = []
    for l in FASTRULE.open():
        r = json.loads(l)
        e = r["expect"]
        if e.get("atomic") is not True or e.get("action") not in ("create_event", "create_todo"):
            continue
        it = e.get("item") or {}
        out.append({"src": "fastrule", "id": r["id"], "family": r["family"], "split": r["split"],
                    "text": it.get("text") or r["text"], "time": it.get("time") or "",
                    "gold": "event" if e["action"] == "create_event" else "task"})
    return out


def load_v2() -> list:
    out = []
    for l in V2.open():
        r = json.loads(l)
        for a in r["asks"]:
            if a.get("action") not in ("create_event", "create_todo") or not a.get("item"):
                continue
            out.append({"src": "v2", "id": f"{r['id']}#{a['ask_id']}", "family": r["family"],
                        "split": r["split"], "text": a["item"]["text"], "time": a["item"].get("time") or "",
                        "gold": a["kind"]})
    return out


def load_seg(fastrule_split: dict) -> list:
    """Segmentation's corpus: every gold item tagged event|task. The hand-written
    trap files carry a split; `generated.jsonl` is split by segmentation's own
    family hash (`run_board.assign_splits`). Its families are FastRule's, so a
    family that is TEST on EITHER side is TEST here — the stricter reading."""
    from assistant.engine.segmentation.experiments import run_board as RB
    out = []
    for name in ("generated", "nosplit_traps", "split_traps"):
        rows = [json.loads(l) for l in (SEG / f"{name}.jsonl").open()]
        RB.assign_splits(rows)
        for r in rows:
            split = r["split"]
            if fastrule_split.get(r.get("family")) == "test":
                split = "test"
            for i, g in enumerate(r["gold"]):
                if g.get("tag") not in KINDS:
                    continue
                out.append({"src": "seg", "id": f"{r['id']}#{i}", "family": f"seg:{r.get('family')}",
                            "split": split, "text": g["action"], "time": g.get("time") or "",
                            "gold": g["tag"]})
    return out


def load_real() -> list:
    """Gil's reviewed commands, read-only. Kind gold ONLY where his review makes
    it unambiguous: an APPROVED create (he accepted the kind) or a CORRECTED one
    (the kind he recorded), and only where every create in the command is the
    same kind, so the items fastseg cuts can all carry it. TEST-only, no split."""
    if not REAL_DB.is_file():
        return []
    con = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT id, COALESCE(NULLIF(raw_transcript,''), transcript), feedback, actions_json, "
        "correction_json FROM examples WHERE source != 'test' AND feedback IN ('approved','corrected')"
    ).fetchall()
    con.close()
    from assistant.engine.segmentation.fastseg.fastseg import fastseg

    def acts(blob):
        try:
            d = json.loads(blob or "null")
        except ValueError:
            return []
        d = [d] if isinstance(d, dict) else (d or [])
        return [x.get("action") or x.get("name") for x in d if isinstance(x, dict)]

    out = []
    for rid, said, fb, aj, cj in rows:
        gold_acts = acts(cj) if fb == "corrected" else acts(aj)
        creates = {a for a in gold_acts if a in ("create_event", "create_todo")}
        if len(creates) != 1 or any(a not in creates for a in gold_acts):
            continue
        kind = "event" if creates == {"create_event"} else "task"
        said = re.sub(r"[,.\s]*\bexecute\b[?.!\s]*$", "", said or "", flags=re.I)
        for i, it in enumerate(fastseg(said)):
            out.append({"src": "real", "id": f"real{rid}#{i}", "family": f"real{rid}", "split": "test",
                        "text": it["action"], "time": it["time"] or "", "gold": kind, "tier": fb})
    return out


# ---------------------------------------------------------------------------
# 2 · the rulings battery — each sentence decided by a ruling, cited
# ---------------------------------------------------------------------------

RULINGS = [
    # Q25/Q26: a stated CLOCK makes an event, any phrasing, "remind me to" included
    ("remind me to feed the cat at 14:00", "event", "Q26"),
    ("remind me to call the bank at 5pm", "event", "Q26"),
    ("remind me to email Robin at 10am", "event", "Q26"),
    ("walk the dog at 9", "event", "Q25"),
    ("buy milk tomorrow at 6pm", "event", "Q25"),
    ("i need to go to the dentist on the 24th at 3 o'clock", "event", "Q25"),
    ("remind me to take out the trash tonight at 8", "event", "Q26"),
    ("file the taxes every weekday at 3:45pm", "event", "Q25"),
    ("review the contract daily at 8:30pm", "event", "Q25"),
    ("block off time to print the boarding pass from 2 to 3", "event", "Q26 range"),
    ("pay rent on friday at noon", "event", "Q25"),
    ("water the plants at half past six", "event", "Q25"),
    ("pick up the dry cleaning at 5:30", "event", "Q25"),
    ("clean the garage saturday at 11am", "event", "Q25"),
    # Q47(A) + Q27: a part of the day is not a time; a chore with one is a to-do
    ("remind me to water the garden this evening", "task", "Q47A"),
    ("remind me to take the trash out tonight", "task", "Q47A"),
    ("buy onions and index cards this afternoon", "task", "Q27"),
    ("clean and organize the garage this morning", "task", "Q27"),
    ("add book a flight to my todo list tonight", "task", "Q27"),
    ("fold the laundry this evening", "task", "Q47A"),
    ("remind me to pack for the trip tomorrow morning", "task", "Q47A"),
    ("remind me to renew the car registration tonight", "task", "Q47A"),
    # Q27: a scheduling verb with a part of the day is an event
    ("schedule birthday dinner this evening", "event", "Q27"),
    ("book standup this afternoon", "event", "Q27"),
    ("pencil in doctor's appointment late afternoon", "event", "Q27"),
    # Q47(B) + Q1: seeing a PERSON on a stated day is an event
    ("see mom on sunday", "event", "Q47B"),
    ("i should see Parker the 21st", "event", "Q47B"),
    ("visit grandma tomorrow", "event", "Q47B"),
    ("lunch with dad on friday", "event", "Q47B"),
    ("meet Dana next tuesday", "event", "Q47B"),
    ("pick up my sister tomorrow", "event", "Q47B"),
    ("catch up with Jordan on thursday", "event", "Q47B"),
    ("on monday the 20th i need to have a conversation with Greg", "event", "Q1"),
    # Q26 table: no time at all -> a to-do (Q47: "call Mom" with no day stays one)
    ("call Mom", "task", "Q47/Q26"),
    ("buy milk", "task", "Q26"),
    ("remind me to sign the permission slip", "task", "Q26"),
    ("renew my passport", "task", "Q26"),
    ("add eggs to my shopping list", "task", "Q26"),
    # Q26 table: a bare day with a chore -> a to-do
    ("buy a gift for mom tomorrow", "task", "Q26"),
    ("pay the electricity bill on friday", "task", "Q26"),
    ("submit the report tomorrow", "task", "Q26"),
    # the reminder convention (Gil 2026-09-04): a reminder ABOUT an occasion on a day is an event
    ("remind me about my meeting tomorrow", "event", "2026-09-04"),
    ("set a reminder for my meeting today", "event", "2026-09-04"),
]


# ---------------------------------------------------------------------------
# 3 · features
# ---------------------------------------------------------------------------

class Featuriser:
    """One item -> {group: vector}. Groups are what the ablations switch."""

    def __init__(self, embed: bool = False) -> None:
        import joblib
        import importlib
        FS = importlib.import_module("assistant.engine.segmentation.fastseg.fastseg")
        from assistant.engine.segmentation.fastseg import kind as K
        from assistant.actions.calendar import categories as C
        from assistant.actions.todo import tagging as T
        self.FS, self.K, self.C, self.T = FS, K, C, T
        base = ENGINE / "label" / "models"
        ev = joblib.load(base / "event_label.joblib")
        tk = joblib.load(base / "task_label.joblib")
        self.ev_pipe, self.ev_classes = ev["pipeline"], list(ev["pipeline"].classes_)
        self.tk_pipe, self.tk_classes = tk["pipeline"], list(tk["classes"])
        self.ev_embed, self.tk_embed = ev.get("embed"), tk.get("embed")
        self.cat_names = [c["name"] for c in C.DEFAULTS]
        self.tag_names = list(T.KEYWORDS) + ["<none>"]
        self.embed = embed
        self.heads: list = []
        self._daypart = re.compile(r"\b(morning|afternoon|evening|tonight|night|noon|midday|lunchtime)\b", re.I)
        self._recur = re.compile(r"\b(every|each|daily|weekly|monthly|yearly|weekday|weekdays|weekends)\b", re.I)
        self._range = re.compile(r"\bfrom\s+\S+\s+(?:to|until|till)\s+\S+|\bbetween\s+\S+\s+and\s+\S+", re.I)
        self._day = re.compile(
            r"\b(today|tomorrow|tonight|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|"
            r"sunday|weekend|week|month|january|february|march|april|may|june|july|august|"
            r"september|october|november|december|\d{1,2}(st|nd|rd|th))\b", re.I)
        self._frames = {
            "remind_to": re.compile(r"\bremind\s+\w+\s+to\b", re.I),
            "remind_about": re.compile(r"\bremind\s+\w+\s+(?:about|of)\b|\breminder\s+(?:for|about)\b", re.I),
            "reminder_word": re.compile(r"\bremind(?:er)?s?\b|\bnotify\b", re.I),
            "list_dest": re.compile(K._LIST_DEST, re.I),
            "calendar_dest": K._CALENDAR_DEST_RE,
            "sched_verb": re.compile(r"\b(book|schedule|set\s+up|pencil\s+in|arrange|plan|organi[sz]e\s+a|"
                                     r"put\s+.*\bin\s+the\s+diary|add\s+an?\s+event|create\s+an?\s+event|"
                                     r"set\s+an?\s+(?:event|meeting|appointment))\b", re.I),
            "note_to_self": re.compile(r"\bnote\s+to\s+self\b|\bdon'?t\s+(?:let\s+me\s+)?forget\b|\bremember\s+to\b", re.I),
            "need_to": re.compile(r"\bi\s+(?:need to|have to|gotta|got to|must|should)\b", re.I),
            "task_word": re.compile(r"\b(to-?do|task|errand)s?\b", re.I),
            "event_word": re.compile(r"\b(event|appointment|meeting|calendar)\b", re.I),
            "occasion": K._OCCASION_RE,
            "chore_verb": re.compile(K._CHORE_VERB, re.I),
            "gathering": K._GATHERING_RE,
            "question": re.compile(r"\?\s*$|^(?:what|when|where|who|do i|is|are|can i)\b", re.I),
            "done_frame": re.compile(K._TODO_DONE, re.I),
        }

    # -- the incumbent -------------------------------------------------------
    def engine_kind(self, text, time_) -> str:
        return self.FS.tag(text, time_)

    # -- the rulings' own gates, read with the engine's regexes ----------------
    def ruling(self, text, time_) -> "str | None":
        FS = self.FS
        clock = bool(FS._STATED_CLOCK.search(time_ or ""))
        if clock and not FS._VAGUE_TIME_HEDGE.search(text) and not FS._DUE_DATE_EDIT.match(text) \
                and not FS._is_not_calendar(text, time_):
            return "event"                                   # Q25/Q26
        real_day = _norm(time_) not in ("", "today")
        if real_day and self.person_rule(text):
            return "event"                                   # Q47(B)
        return None

    def person_rule(self, text) -> bool:
        """Q47(B) read FAITHFULLY: a person on a stated day, where the ask is
        an ENCOUNTER. Two things the engine's working-tree `_meets_a_person`
        does not do, and this gate does, because its own docstring says so:
        an outreach verb behind a reminder frame ("remind me to CALL Jordan")
        is still outreach — the engine reads the head as "remind" — and a
        named to-do destination ("add … to my tasks") is not an encounter
        whatever spaCy calls a garbled word."""
        FS = self.FS
        core = re.sub(r"^(?:please\s+)?(?:remind\s+\w+(?:\s+to)?|don'?t\s+let\s+me\s+forget\s+to|"
                      r"remember\s+to)\s+", "", text.strip(), flags=re.I)
        if FS._head_is_outreach_verb(core) or self._frames["list_dest"].search(text):
            return False
        from assistant.intent.encounter import is_encounter
        return FS._has_person_argument(core) or is_encounter(text)

    def engine_person_promoted(self, text, time_) -> bool:
        """Did the engine's own Q47 promotion fire where the faithful gate does not?"""
        FS = self.FS
        return (_norm(time_) not in ("", "today") and FS._meets_a_person(text)
                and not self.person_rule(text))

    def head(self, text) -> str:
        words = [w.strip(".!?,") for w in text.lower().split()]
        while words and words[0] in self.FS._PREAMBLE:
            words.pop(0)
        return words[0] if words else "<empty>"

    def shape(self, text, time_) -> dict:
        FS = self.FS
        t = time_ or ""
        f = {
            "clock": float(bool(FS._STATED_CLOCK.search(t))),
            "day": float(bool(self._day.search(t))),
            "real_time": float(_norm(t) not in ("", "today")),
            "no_time": float(_norm(t) == ""),
            "daypart": float(bool(self._daypart.search(t)) and not FS._STATED_CLOCK.search(t)),
            "recur": float(bool(self._recur.search(t))),
            "range": float(bool(self._range.search(t))),
            "person_arg": float(FS._has_person_argument(text)),
            # `_KIN_RE` moved into `assistant/intent/encounter.py` (6621452); the
            # encounter reader is the feature now
            "kin": float(__import__("assistant.intent.encounter", fromlist=["x"]).is_encounter(text)),
            "outreach_head": float(FS._head_is_outreach_verb(text)),
            "vague_hedge": float(bool(FS._VAGUE_TIME_HEDGE.search(text))),
            "anchored": float(bool(FS._ANCHORED_TO_EVENT.search(text))),
            "n_words": min(len(text.split()), 20) / 20.0,
        }
        lk = FS._lexicon_kind(text)
        f["lex_event"], f["lex_task"] = float(lk == "event"), float(lk == "task")
        for k, rx in self._frames.items():
            f[f"frame_{k}"] = float(bool(rx.search(text)))
        return f

    def stage1(self, texts) -> "np.ndarray":
        """Stage 1: the event-category model's 13 probabilities, the to-do-tag
        model's 4 one-vs-rest probabilities, and the keyword rules as one-hots."""
        ev = self.ev_pipe.predict_proba(texts)
        feats = self.tk_pipe.named_steps["feat"].transform(texts)
        tk = np.column_stack([est.predict_proba(feats)[:, 1]
                              for est in self.tk_pipe.named_steps["clf"].estimators_])
        cat = np.zeros((len(texts), len(self.cat_names)))
        tag = np.zeros((len(texts), len(self.tag_names)))
        for i, t in enumerate(texts):
            c = self.C.classify(t)
            if c in self.cat_names:
                cat[i, self.cat_names.index(c)] = 1
            g = self.T.infer_tag(t) or "<none>"
            tag[i, self.tag_names.index(g)] = 1
        return np.hstack([ev, ev.max(1, keepdims=True), tk, tk.max(1, keepdims=True), cat, tag])

    def stage1_names(self) -> list:
        return ([f"evp_{c}" for c in self.ev_classes] + ["evp_max"]
                + [f"tkp_{c}" for c in self.tk_classes] + ["tkp_max"]
                + [f"rule_cat_{c}" for c in self.cat_names] + [f"rule_tag_{c}" for c in self.tag_names])

    def embed_probs(self, texts) -> "np.ndarray":
        """The Q46 embedding heads' probabilities (nomic-embed-text via ollama)."""
        from assistant.engine.label import embed as E
        texts = list(texts)
        parts = []
        for i in range(0, len(texts), 512):
            for attempt in range(6):          # a cold model load can time out the first batch
                v = E.vectors(texts[i:i + 512])
                if v is not None:
                    break
                E._down_until = 0
                print(f"  {time.strftime('%H:%M:%S')} embed chunk {i} failed (attempt {attempt + 1}): "
                      f"{_embed_diagnose(texts[i:i + 512])}", flush=True)
                time.sleep(20)
            if v is None:
                raise SystemExit("embedding unavailable")
            parts.append(np.asarray(v))
        V = np.vstack(parts)
        pe = self.ev_embed.proba(list(texts), V)
        pt = self.tk_embed.proba(list(texts), V)
        return np.hstack([pe, pt])


def _embed_diagnose(texts) -> str:
    """The door swallows its exception; ask once more, outside it, to say why."""
    import urllib.request
    from assistant.engine.label import embed as E
    body = json.dumps({"model": E.MODEL, "input": [E.PREFIX + t for t in texts]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"{E.DEFAULT_URL}/api/embed", data=body,
                headers={"Content-Type": "application/json"}), timeout=180) as r:
            got = json.loads(r.read()).get("embeddings")
        return f"direct call returned {len(got or [])} of {len(texts)}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def build(items, fz: Featuriser, heads_vocab=None, embed=False):
    """Items -> (X by group, names by group). `heads_vocab` is fitted on TRAIN."""
    texts = [it["text"] for it in items]
    sh = [fz.shape(it["text"], it["time"]) for it in items]
    shape_names = list(sh[0].keys())
    heads = [fz.head(it["text"]) for it in items]
    H = np.zeros((len(items), len(heads_vocab) + 1))
    for i, h in enumerate(heads):
        H[i, heads_vocab.get(h, len(heads_vocab))] = 1
    X = {"shape": np.hstack([np.array([[d[k] for k in shape_names] for d in sh]), H]),
         "stage1": fz.stage1(texts),
         # the TAGGER's verdict on these words (on Board D the incumbent is the
         # chain's commit, but the feature is still the tagger's reading)
         "engine": np.array([[float(it["tagk"] == "event"), float(it["tagk"] == "task"),
                              float(it["tagk"] not in KINDS)] for it in items])}
    names = {"shape": shape_names + [f"head={h}" for h in heads_vocab] + ["head=<other>"],
             "stage1": fz.stage1_names(), "engine": ["eng_event", "eng_task", "eng_other"]}
    if embed:
        X["embed"] = fz.embed_probs(texts)
        names["embed"] = [f"emb_ev_{c}" for c in fz.ev_embed.classes] + [f"emb_tk_{c}" for c in fz.tk_embed.classes]
    return X, names


VARIANTS = {
    "shape":              ("shape",),
    "stage1":             ("stage1",),
    "shape+stage1":       ("shape", "stage1"),
    "engine+shape":       ("engine", "shape"),
    "engine+shape+stage1": ("engine", "shape", "stage1"),
}


def _mat(X, groups):
    return np.hstack([X[g] for g in groups])


def make_model(kind: str):
    if kind == "lr":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=4000))
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
                                          l2_regularization=1.0, random_state=0)


# ---------------------------------------------------------------------------
# 4 · scoring
# ---------------------------------------------------------------------------

def decide(p_event: np.ndarray, items, gated: bool) -> list:
    """Stage-2's routing: event/task only. A `review`/`other` from the tagger is
    not a routing question and stands; a ruling (when gated) wins."""
    out = []
    for p, it in zip(p_event, items):
        if it["engine"] not in KINDS:
            out.append(it["engine"])
            continue
        if gated and it["ruling"]:
            out.append(it["ruling"])
            continue
        out.append("event" if p >= 0.5 else "task")
    return out


def score(items, pred) -> dict:
    n = len(items)
    ok = sum(p == it["gold"] for p, it in zip(pred, items))
    inc = sum(it["engine"] == it["gold"] for it in items)
    fixed = sum(p == it["gold"] and it["engine"] != it["gold"] for p, it in zip(pred, items))
    broke = sum(p != it["gold"] and it["engine"] == it["gold"] for p, it in zip(pred, items))
    return {"n": n, "acc": ok / n if n else None, "inc": inc / n if n else None,
            "fixed": fixed, "broke": broke, "net": fixed - broke}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed", action="store_true", help="add the ollama embedding heads as a stage-1 variant")
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args()
    t0 = time.time()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"kind_two_stage · started {stamp} · scratch {_S}", flush=True)

    fr = load_fastrule()
    fr_split = {it["family"]: it["split"] for it in fr}
    for l in FASTRULE.open():
        r = json.loads(l)
        fr_split.setdefault(r["family"], r["split"])
    sources = {"fastrule": fr, "v2": load_v2(), "seg": load_seg(fr_split), "real": load_real()}
    fz = Featuriser(embed=a.embed)

    allitems = [it for v in sources.values() for it in v]
    # THE TRANSCRIPT CLEANUP FIRST, for the incumbent and the model alike:
    # `fastseg()` runs `strip_spoken_noise` over the utterance before any item
    # is cut, and several kind regexes are `^`-anchored, so raw dataset words
    # ("one moment, i need to …", "would you make a note to …") invent misses
    # the live chain never has (`dataset/METRICS.md` Level 3b, learned the hard way).
    from assistant.intent.cleanup import strip_spoken_noise
    for it in allitems:
        if it["src"] != "real":                 # real items came through fastseg already
            it["text"] = strip_spoken_noise(it["text"]) or it["text"]
            it["time"] = strip_spoken_noise(it["time"]) if it["time"] else ""
    print(f"  items loaded: " + ", ".join(f"{k} {len(v)}" for k, v in sources.items()), flush=True)
    for i, it in enumerate(allitems):
        it["engine"] = it["tagk"] = fz.engine_kind(it["text"], it["time"])
        it["ruling"] = fz.ruling(it["text"], it["time"])
        # gold that a RULING contradicts is stale gold, not a target: never fitted, never scored
        it["conflict"] = bool(it["ruling"] and it["ruling"] != it["gold"])
        it["eng_person_bug"] = (it["engine"] == "event" and it["gold"] == "task"
                                and fz.engine_person_promoted(it["text"], it["time"]))
        if i % 2000 == 0:
            print(f"  {time.strftime('%H:%M:%S')} tagged {i}/{len(allitems)}", flush=True)

    # --- the TRAIN pool: deduped by (words, time); nothing whose words appear in ANY test set
    test_keys = {(_norm(it["text"]), _norm(it["time"])) for it in allitems if it["split"] == "test"}
    pool, seen = [], set()
    for it in allitems:
        if it["split"] != "train" or it["conflict"]:
            continue
        k = (_norm(it["text"]), _norm(it["time"]))
        if k in test_keys or k in seen:
            continue
        seen.add(k)
        pool.append(it)
    head_counts = collections.Counter(fz.head(it["text"]) for it in pool)
    heads_vocab = {h: i for i, (h, c) in enumerate(head_counts.most_common()) if c >= 5}
    print(f"  TRAIN pool {len(pool)} unique items ({len({it['family'] for it in pool})} families), "
          f"{len(heads_vocab)} head verbs", flush=True)

    Xp, names = build(pool, fz, heads_vocab, a.embed)
    yp = np.array([it["gold"] == "event" for it in pool], dtype=int)
    groups = np.array([it["family"] for it in pool])
    variants = dict(VARIANTS)
    if a.embed:
        variants["shape+embed"] = ("shape", "embed")
        variants["engine+shape+embed"] = ("engine", "shape", "embed")
        variants["engine+shape+stage1+embed"] = ("engine", "shape", "stage1", "embed")

    from sklearn.model_selection import GroupKFold
    folds = list(GroupKFold(n_splits=5).split(Xp["shape"], yp, groups))
    fold_of_family = {}
    for fi, (_, te) in enumerate(folds):
        for j in te:
            fold_of_family[groups[j]] = fi

    # evaluation sets, featurised once
    evalsets = {}
    for s, items in sources.items():
        te = [it for it in items if it["split"] == "test" and not it["conflict"]]
        if te:
            evalsets[(s, "test")] = (te, build(te, fz, heads_vocab, a.embed)[0])
    # Board D: the seeded checkpoint's one-object CREATE rows, re-segmented by fastseg
    board = board_d_rows(fz)
    Xb = build(board, fz, heads_vocab, a.embed)[0] if board else None

    results, fitted = {}, {}
    oof_all = {}
    for mname in ("lr", "hgb"):
        for vname, gs in variants.items():
            key = f"{mname}:{vname}"
            M = _mat(Xp, gs)
            oof = np.zeros(len(pool))
            fold_models = []
            for tr, te in folds:
                m = make_model(mname).fit(M[tr], yp[tr])
                oof[te] = m.predict_proba(M[te])[:, 1]
                fold_models.append(m)
            full = make_model(mname).fit(M, yp)
            fitted[key] = full
            oof_all[key] = oof
            res = {}
            for s in sources:
                idx = [i for i, it in enumerate(pool) if it["src"] == s]
                if not idx:
                    continue
                sub = [pool[i] for i in idx]
                for gated in (False, True):
                    res[(s, "train", gated)] = score(sub, decide(oof[idx], sub, gated))
            for (s, sp), (items, Xe) in evalsets.items():
                pe = full.predict_proba(_mat(Xe, gs))[:, 1]
                for gated in (False, True):
                    res[(s, sp, gated)] = score(items, decide(pe, items, gated))
                res[("pred", s)] = decide(pe, items, True)
            if board:
                Mb = _mat(Xb, gs)
                pb = np.zeros(len(board))
                for i, it in enumerate(board):
                    fi = fold_of_family.get(it["family"])
                    m = fold_models[fi] if fi is not None else full
                    pb[i] = m.predict_proba(Mb[i:i + 1])[0, 1]
                for gated in (False, True):
                    res[("boardD", "train", gated)] = board_score(board, decide(pb, board, gated))
                    if gated:
                        res[("boardD_rows", gated)] = decide(pb, board, gated)
            rp = ruling_check(fz, full, gs, heads_vocab, a.embed)
            res["rulings"] = rp
            results[key] = res
            print(f"  {time.strftime('%H:%M:%S')} fitted {key}", flush=True)

    report(sources, pool, results, board, fz, heads_vocab, variants, stamp, t0, a,
           fitted, Xp, names, yp, evalsets)
    return 0


# ---------------------------------------------------------------------------
# 5 · Board D rows and the rulings battery
# ---------------------------------------------------------------------------

def board_d_rows(fz) -> list:
    if not BOARD_D_CK.is_file():
        return []
    from assistant.engine.llmjudge.experiments.board_d import _as_outcome  # noqa: F401
    from assistant.engine.segmentation.fastseg.fastseg import fastseg
    ck = {}
    for l in BOARD_D_CK.open():
        r = json.loads(l)
        if "k" in r:
            ck[r["k"]] = r["v"]
    rows = {json.loads(l)["id"]: json.loads(l) for l in FASTRULE.open()}
    out = []
    for k, v in ck.items():
        r = rows.get(k)
        off = v.get("off") or []
        if not r or r["expect"]["action"] not in ("create_event", "create_todo"):
            continue
        if len(off) != 1 or off[0][0] not in ("create_event", "create_todo"):
            continue
        segs = [s for s in fastseg(r["text"]) if s["tag"] in ("event", "task", "review", "other")]
        if len(segs) == 1:
            text, t = segs[0]["action"], segs[0]["time"] or ""
        else:                          # fastseg cut it differently: the gold item's own words
            from assistant.intent.cleanup import strip_spoken_noise
            it = r["expect"].get("item") or {}
            text = strip_spoken_noise(it.get("text") or r["text"]) or (it.get("text") or r["text"])
            t = strip_spoken_noise(it.get("time") or "") if it.get("time") else ""
        chain = "event" if off[0][0] == "create_event" else "task"
        out.append({"src": "boardD", "id": k, "family": r["family"], "split": "train",
                    "text": text, "time": t, "gold": "event" if r["expect"]["action"] == "create_event" else "task",
                    "row": r, "off": off, "chain": chain,
                    # the incumbent on Board D is what the CHAIN committed
                    "engine": chain, "tagk": fz.engine_kind(text, t), "ruling": fz.ruling(text, t)})
    return out


def board_score(board, pred) -> dict:
    from assistant.engine.llmjudge.experiments.board_d import _as_outcome, _correct
    n = len(board)
    fixed = broke = ok_new = ok_old = changed = 0
    for it, p in zip(board, pred):
        old = _as_outcome(it["off"])
        new = old
        if p in KINDS and p != it["chain"]:
            changed += 1
            new = tuple((("create_event" if p == "event" else "create_todo"), t) for _a, t in old)
        o, nn = _correct(old, it["row"]), _correct(new, it["row"])
        ok_old += o
        ok_new += nn
        fixed += (nn and not o)
        broke += (o and not nn)
    return {"n": n, "acc": ok_new / n, "inc": ok_old / n, "fixed": fixed, "broke": broke,
            "net": fixed - broke, "changed": changed}


def ruling_check(fz, model, gs, heads_vocab, embed) -> dict:
    from assistant.engine.segmentation.fastseg.fastseg import fastseg
    items = []
    for sent, want, cite in RULINGS:
        segs = fastseg(sent)
        s = segs[0] if segs else {"action": sent, "time": ""}
        items.append({"text": s["action"], "time": s["time"] or "", "gold": want, "cite": cite,
                      "sent": sent, "n_items": len(segs),
                      "engine": fz.engine_kind(s["action"], s["time"] or ""),
                      "tagk": fz.engine_kind(s["action"], s["time"] or ""),
                      "ruling": fz.ruling(s["action"], s["time"] or "")})
    X = build(items, fz, heads_vocab, embed)[0]
    p = model.predict_proba(_mat(X, gs))[:, 1]
    raw, gated = decide(p, items, False), decide(p, items, True)
    return {"n": len(items),
            "engine_ok": sum(it["engine"] == it["gold"] for it in items),
            "raw_ok": sum(r == it["gold"] for r, it in zip(raw, items)),
            "gated_ok": sum(g == it["gold"] for g, it in zip(gated, items)),
            "raw_viol": [(it["sent"], it["cite"], r) for r, it in zip(raw, items) if r != it["gold"]],
            "gated_viol": [(it["sent"], it["cite"], g) for g, it in zip(gated, items) if g != it["gold"]],
            "engine_viol": [(it["sent"], it["cite"], it["engine"]) for it in items if it["engine"] != it["gold"]]}


# ---------------------------------------------------------------------------
# 6 · the report
# ---------------------------------------------------------------------------

def _pct(x):
    return "   —  " if x is None else f"{100 * x:5.1f}%"


def report(sources, pool, results, board, fz, heads_vocab, variants, stamp, t0, a,
           fitted, Xp, names, yp, evalsets):
    print(f"\nKIND TWO-STAGE — started {stamp}, finished {time.strftime('%Y-%m-%d %H:%M:%S')} "
          f"({(time.time() - t0) / 60:.1f} min)\n")
    print("  DATA (items = one ask's own words + time phrase; kind gold event|task)")
    for s, items in sources.items():
        for sp in ("train", "test"):
            sub = [it for it in items if it["split"] == sp]
            if not sub:
                continue
            inpool = sum(1 for it in pool if it["src"] == s) if sp == "train" else "-"
            conf = sum(it["conflict"] for it in sub)
            pbug = sum(it["eng_person_bug"] for it in sub)
            fams = len({it["family"] for it in sub})
            shapes = len({(_norm(it["text"]), _norm(it["time"])) for it in sub})
            ev = sum(it["gold"] == "event" for it in sub)
            print(f"    {s:9s} {sp:5s} n={len(sub):5d} (in fit pool {inpool}) families={fams:4d} "
                  f"distinct items={shapes:5d} event/task={ev}/{len(sub) - ev} "
                  f"gold-vs-ruling conflicts={conf} (dropped) engine-person-promotion errors={pbug}")
    if board:
        print(f"    boardD    train n={len(board):5d} one-object CREATE rows of board_d_c45 (seeded), "
              f"families={len({b['family'] for b in board})}")

    import subprocess
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "assistant/engine/segmentation",
                                 "assistant/engine/fastrule", "assistant/engine/label", "assistant/actions"],
                                capture_output=True, text=True).stdout.strip())
    print(f"  engine code: {head}{' (DIRTY)' if dirty else ''}")
    record = {"started": stamp, "finished": time.strftime("%Y-%m-%d %H:%M:%S"), "git_head": head,
              "engine_dirty": dirty, "embed": a.embed, "results": {}}
    for gated in (False, True):
        print(f"\n  KIND ACCURACY — {'GATED (rulings win where they fire)' if gated else 'RAW model'}; "
              f"TRAIN = out-of-fold (5-fold by family), TEST = fit on the whole TRAIN pool")
        cols = [(s, sp) for s in ("fastrule", "v2", "seg") for sp in ("train", "test")] + [("real", "test")]
        hdr = "    " + f"{'model':30s}" + "".join(f"{s[:5]+'/'+sp[:2]:>15s}" for s, sp in cols)
        print(hdr)
        any_key = next(iter(results))
        line = "    " + f"{'ENGINE (fastseg.tag)':30s}"
        for c in cols:
            r = results[any_key].get((c[0], c[1], gated))
            line += f"{_pct(r['inc']) if r else '   —  ':>15s}" if r else f"{'—':>15s}"
        print(line)
        for key, res in results.items():
            line = "    " + f"{key:30s}"
            for c in cols:
                r = res.get((c[0], c[1], gated))
                line += (f"{_pct(r['acc'])} {r['net']:+5d}".rjust(15)) if r else f"{'—':>15s}"
            print(line)
        print("    (cell = accuracy, then NET rows fixed-minus-broken vs the engine on the same items)")

    print("\n  n per cell: " + ", ".join(
        f"{c[0]}/{c[1]}={results[next(iter(results))].get((c[0], c[1], False), {}).get('n')}"
        for c in [(s, sp) for s in ("fastrule", "v2", "seg") for sp in ("train", "test")] + [("real", "test")]))

    if board:
        print(f"\n  BOARD D one-object CREATE rows (n={len(board)}; seeded checkpoint board_d_c45; "
              f"_correct = action AND title; out-of-fold predictions)")
        r0 = results[next(iter(results))][("boardD", "train", False)]
        print(f"    chain as committed: {_pct(r0['inc'])} correct")
        for key, res in results.items():
            for gated in (False, True):
                r = res[("boardD", "train", gated)]
                print(f"    {key:30s} {'gated' if gated else 'raw  '}  {_pct(r['acc'])}  "
                      f"changed {r['changed']:3d}  fixed {r['fixed']:3d}  broke {r['broke']:3d}  net {r['net']:+d}")
        hint = category_hint_probe(board, fz)
        print(f"    one-rule category hint (reconstruction of today's probe): opinion on {hint['opinion']}, "
              f"fixed {hint['fixed']}, broke {hint['broke']}, net {hint['fixed'] - hint['broke']:+d}")
        record["category_hint"] = hint

    print(f"\n  RULINGS battery ({len(RULINGS)} sentences from Q25/Q26/Q27/Q47/Q1 + the 2026-09-04 convention)")
    r0 = results[next(iter(results))]["rulings"]
    print(f"    engine (fastseg.tag): {r0['engine_ok']}/{r0['n']}  violations: {r0['engine_viol']}")
    for key, res in results.items():
        rp = res["rulings"]
        print(f"    {key:30s} raw {rp['raw_ok']:2d}/{rp['n']}   gated {rp['gated_ok']:2d}/{rp['n']}")
        if rp["gated_viol"]:
            print(f"        gated violations: {rp['gated_viol']}")

    # --- what carries the weight: group permutation on the pooled TEST sets
    print("\n  FEATURE WEIGHT — accuracy drop on pooled TEST (fastrule+v2+seg) when a group is permuted")
    te_items, te_X = [], collections.defaultdict(list)
    for (s, sp), (items, Xe) in evalsets.items():
        if s == "real":
            continue
        te_items += items
        for g, M in Xe.items():
            te_X[g].append(M)
    te_X = {g: np.vstack(v) for g, v in te_X.items()}
    yt = np.array([it["gold"] == "event" for it in te_items], dtype=int)
    rng = np.random.default_rng(0)
    for key in ("hgb:shape+stage1", "hgb:engine+shape+stage1", "lr:shape+stage1"):
        if key not in fitted:
            continue
        gs = variants[key.split(":", 1)[1]]
        m = fitted[key]
        base = (m.predict(_mat(te_X, gs)) == yt).mean()
        drops = []
        for g in gs:
            Xs = dict(te_X)
            Xs[g] = te_X[g][rng.permutation(len(yt))]
            drops.append((g, base - (m.predict(_mat(Xs, gs)) == yt).mean()))
        print(f"    {key:28s} base {100 * base:.1f}%  " + "  ".join(f"{g}: -{100 * d:.1f}pt" for g, d in drops))
    # the top single features by LR coefficient
    key = "lr:shape+stage1"
    if key in fitted:
        coefs = fitted[key][-1].coef_[0]
        nm = names["shape"] + names["stage1"]
        order = np.argsort(-np.abs(coefs))[:20]
        print("    top LR (standardised) coefficients, + = event:")
        print("      " + ", ".join(f"{nm[i]} {coefs[i]:+.2f}" for i in order))

    # --- rows: where stage-1 changes the answer on TEST
    key_a, key_b = "hgb:engine+shape", "hgb:engine+shape+stage1"
    if key_a in fitted and key_b in fitted and a.show:
        print(f"\n  TEST items where adding stage-1 changed the answer ({key_a} -> {key_b}), gated:")
        pa = decide(fitted[key_a].predict_proba(_mat(te_X, variants['engine+shape']))[:, 1], te_items, True)
        pb = decide(fitted[key_b].predict_proba(_mat(te_X, variants['engine+shape+stage1']))[:, 1], te_items, True)
        diffs = [(it, x, y) for it, x, y in zip(te_items, pa, pb) if x != y]
        good = sum(y == it["gold"] for it, x, y in diffs)
        print(f"    {len(diffs)} changed: {good} to the gold kind, {len(diffs) - good} away from it")

    # --- paired comparisons on the pooled TEST (fastrule+v2+seg), gated, McNemar exact
    from math import comb

    def mcnemar(b, c):
        n = b + c
        if not n:
            return 1.0
        k = min(b, c)
        return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)

    srcs = [s for (s, sp) in evalsets if s != "real"]
    gold = [it["gold"] for s in srcs for it in evalsets[(s, "test")][0]]
    eng = [it["engine"] for s in srcs for it in evalsets[(s, "test")][0]]

    def preds(key):
        return [p for s in srcs for p in results[key][("pred", s)]]
    print(f"\n  PAIRED on pooled TEST (n={len(gold)}; gated): A-right/B-wrong vs A-wrong/B-right, McNemar exact p")
    pairs = [("ENGINE", "hgb:engine+shape"), ("ENGINE", "hgb:shape+stage1"),
             ("ENGINE", "hgb:engine+shape+stage1"),
             ("hgb:shape", "hgb:shape+stage1"), ("hgb:engine+shape", "hgb:engine+shape+stage1"),
             ("lr:shape", "lr:shape+stage1"), ("lr:engine+shape", "lr:engine+shape+stage1")]
    record["paired"] = {}
    for A, B in pairs:
        pa = eng if A == "ENGINE" else preds(A)
        pb = preds(B)
        b = sum(x == g and y != g for x, y, g in zip(pa, pb, gold))
        c = sum(x != g and y == g for x, y, g in zip(pa, pb, gold))
        pv = mcnemar(b, c)
        record["paired"][f"{A} -> {B}"] = {"a_only": b, "b_only": c, "net": c - b, "p": pv}
        print(f"    {A:26s} -> {B:26s}  A-only {b:4d}  B-only {c:4d}  net {c - b:+4d}  p={pv:.3g}")

    for key, res in results.items():
        record["results"][key] = {("|".join(map(str, k)) if isinstance(k, tuple) else k): v
                                  for k, v in res.items() if not (isinstance(k, tuple) and k[0] in ("boardD_rows", "pred"))}
    out = HERE / "runs"
    out.mkdir(exist_ok=True)
    p = out / f"kind_two_stage_{time.strftime('%Y%m%dT%H%M')}{'_embed' if a.embed else ''}.json"
    p.write_text(json.dumps(record, indent=1, default=str))
    print(f"\n  record: {p}")


def category_hint_probe(board, fz) -> dict:
    """ONE RULE, no model: the keyword rules' answer implies a kind — a to-do
    tag with no event category means `task`, an event category with no to-do
    tag means `event` — and overrides the chain. My reconstruction of today's
    probe (the original's exact mapping was not recorded)."""
    pred = []
    op = 0
    for it in board:
        cat = fz.C.classify(it["text"])
        tag = fz.T.infer_tag(it["text"])
        if tag and cat in ("Personal", "Errand"):
            pred.append("task"); op += 1
        elif not tag and cat not in ("Personal",):
            pred.append("event"); op += 1
        else:
            pred.append(it["chain"])
    r = board_score(board, pred)
    return {"opinion": op, "fixed": r["fixed"], "broke": r["broke"]}


if __name__ == "__main__":
    sys.exit(main())
