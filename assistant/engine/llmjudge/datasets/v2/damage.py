"""The damage operations — what happens to a command between the mouth and X0.

**WHICH HALF OF THIS IS REAL** (the honesty `scripts/vocab_repair_bench.py`
puts at the top of itself, and for the same reason):

  * The OPERATIONS are observed. The six `stt_*` ones are not re-implemented
    here — they are literally the functions `scripts/vocab_repair_bench.py`
    carries, imported, and that file documents each as a shape present in the
    observed corpus (`dataset/realspeech/`, `banks/speech.json`). The ten
    speech ones are derived from the CLASSES in
    `DOCUMENTATION/experiments/real_usage/taxonomy.jsonl` — `disfluency`,
    `generic-title`, `stt-garbage`, `stutter-split` — each docstring naming
    the rows the shape was read off.
  * The TERMS are invented (`banks.py`), and **no real transcript is copied**.
    A docstring may name a row id and the marker words the class is defined by
    ("sorry, i mean", "no, i said that"); it never reproduces what was said.

**GOLD AND DAMAGE.** A command's gold is derived from the grammar and carried
through every voice and every damage UNCHANGED — except where an operation
DEFINES a change, which is stated in that operation's docstring and nowhere
else. Exactly three KINDS of operation do (eight of the sixteen):

    stt_*                    the gold TITLE becomes the damaged form, because
                             the words no longer hold the clean one; the clean
                             one is kept as `intended_title`. This is
                             `assistant/intent/correction.py`'s rule, verbatim:
                             a title the recogniser mangled "is the
                             recogniser's failure and the vocabulary owns it,
                             not the parser".
    bare_kind_title          the gold TITLE becomes the bare kind word, per
                             DEVQA Q41/Q42 — a bare 'meeting' with the day and
                             clock COMMITS; there is no subject left to reach.
    retraction               the repeated ask is NOT in the gold. The clause is
                             in the words; the retraction cancels it.

Everything else adds noise around a gold that does not move.

Each operation is `op(cmd, rng) -> bool` — True when it applied, False when
this command gave it nothing to work on (a subject with no damageable head, a
one-ask command for a retraction). A refusal is never approximated.
"""
from __future__ import annotations

import re

# The STT operations are IMPORTED, not re-implemented: two copies of a damage
# shape is how a bench and the rule it measures drift apart. A rename in that
# file breaks this import loudly, which is the intended failure.
from scripts.vocab_repair_bench import (      # noqa: E402
    _boundary_shift, _corrupt, _join, _sound_swap, _syllable_split, mash,
)

_STOP = frozenset("the a an of for to with at on in by from my our your and "
                  "is are be do i me it that this".split())


def _head(subject: str) -> "str | None":
    """The word a recogniser is most likely to mangle: the longest content
    word. `vocab_repair_bench` damages the HEAD and leaves the tail intact
    because that is what the observed pairs do."""
    words = [w for w in re.findall(r"[a-z']+", subject.lower())
             if w not in _STOP and len(w) >= 5]
    return max(words, key=len) if words else None


def _swap_core(cmd, ask, new_core: str) -> bool:
    """Put the damaged subject into the words AND into the gold.

    The gold title moves because the WORDS moved — the clean form is no longer
    reachable from what was said, and a gold value nothing in the words can
    reach is a gold value nobody could have produced. `ask["title"]` is always
    the subject's core (no article), and `ask["subject_said"]` is that core as
    this voice rendered it, so one replacement keeps the two in step.
    """
    clause = cmd.clause_for(ask)
    said = ask.get("subject_said")
    core = ask.get("title")
    if clause is None or not said or not core or core not in said:
        return False
    if said not in clause["text"] or not new_core or new_core == core:
        return False
    new_said = said.replace(core, new_core, 1)
    clause["text"] = clause["text"].replace(said, new_said, 1)
    if ask.get("intended_title") is None:
        ask["intended_title"] = core
    ask["title"] = new_core
    ask["subject_said"] = new_said
    return True


def _subject_asks(cmd):
    """The asks that NAME something, and still do.

    Two exclusions, each a case that produced nonsense:

    * an ANAPHORIC ask ("the one you just made") has words but no title, and
      damaging those words is not a title defect — it is a different ask;
    * an ask a `bare_kind_title` already emptied. Mangling the kind word
      afterwards gave "appoi ntme nt", which is neither a kind word Q42 can
      commit bare nor a subject anything can reach.
    """
    return [a for a in cmd.asks
            if a.get("subject_said") and a.get("title") and not a.get("bare_kind")]


# ---------------------------------------------------------------------------
# 1 · the recogniser — six shapes, imported from the vocabulary bench
# ---------------------------------------------------------------------------

def stt_boundary_shift(cmd, rng) -> bool:
    """'barista course' -> 'ba rista course'. One space inserted at a syllable
    edge. Observed: `scripts/vocab_repair_bench.py`'s `_boundary_shift`, a
    shape it records as present in `banks/speech.json`. GOLD CHANGE (see the
    module docstring)."""
    for ask in _pick(cmd, rng):
        head = _head(ask["title"])
        out = _boundary_shift(head) if head else None
        if out and _swap_core(cmd, ask, ask["title"].replace(head, out, 1)):
            return True
    return False


def stt_syllable_split(cmd, rng) -> bool:
    """'kombucha order' -> 'ko mbu cha order'. Every syllable spaced. Observed:
    `vocab_repair_bench._syllable_split`. GOLD CHANGE."""
    for ask in _pick(cmd, rng):
        head = _head(ask["title"])
        out = _syllable_split(head) if head else None
        if out and _swap_core(cmd, ask, ask["title"].replace(head, out, 1)):
            return True
    return False


def stt_compound_join(cmd, rng) -> bool:
    """'ice cream' -> 'icecream'. The boundary between two words disappears.
    Observed: `vocab_repair_bench._join`, and the real-usage class
    `stt-garbage` carries the same shape (a two-word subject arriving as one
    token). GOLD CHANGE."""
    for ask in _pick(cmd, rng):
        out = _join(ask["title"])
        if out and _swap_core(cmd, ask, out):
            return True
    return False


def stt_letter_corrupt(cmd, rng) -> bool:
    """'club' -> 'cub'. One letter dropped, never the last. Observed:
    `vocab_repair_bench._corrupt`. GOLD CHANGE."""
    for ask in _pick(cmd, rng):
        head = _head(ask["title"])
        out = _corrupt(head) if head else None
        if out and _swap_core(cmd, ask, ask["title"].replace(head, out, 1)):
            return True
    return False


def stt_sound_swap(cmd, rng) -> bool:
    """'quinoa' -> 'kwinoa'. Letters change, the sound does not — the half of
    real damage a boundary move cannot imitate. Observed:
    `vocab_repair_bench._sound_swap` and its calibration note. GOLD CHANGE."""
    for ask in _pick(cmd, rng):
        head = _head(ask["title"])
        for k in range(3):
            out = _sound_swap(head, k) if head else None
            if out and _swap_core(cmd, ask, ask["title"].replace(head, out, 1)):
                return True
    return False


def stt_word_mash(cmd, rng) -> bool:
    """Two adjacent words re-segmented so they SOUND the same and READ wrong —
    Gil's construction, 2026-09-19. Observed: `vocab_repair_bench.mash`, and
    the real-usage class `stt-garbage` is largely this shape. GOLD CHANGE."""
    for ask in _pick(cmd, rng):
        core = ask["title"]
        if " " not in core:
            continue
        a, b = core.split(" ")[0], core.split(" ")[1]
        rest = core.split(" ")[2:]
        options = [m for m in mash(a, b) if m != f"{a} {b}"]
        if not options:
            continue
        out = " ".join([options[rng.randrange(len(options))]] + rest)
        if _swap_core(cmd, ask, out):
            return True
    return False


# ---------------------------------------------------------------------------
# 2 · the speaker — the disfluency shapes the real-usage taxonomy names
# ---------------------------------------------------------------------------

def trailing_interjection(cmd, rng) -> bool:
    """A courtesy or an apology hung off the end of the ask.

    Observed: `taxonomy.jsonl` class `disfluency` — rows 23, 40 and 54 each end
    in one, and 54 is the row DEVQA Q43 was ruled on. No gold change: it is
    noise after the ask, not part of it."""
    cmd.tail.append(rng.choice(["excuse me.", "thank you.", "yeah.",
                                "sorry about that.", "is that ok?"]))
    return True


def hold_on_chatter(cmd, rng) -> bool:
    """The speaker stalls mid-command and keeps the microphone.

    Observed: `taxonomy.jsonl` class `disfluency`, rows 30 and 56 — 'one
    moment' became part of the parse on one of them. No gold change."""
    filler = rng.choice(["one moment,", "one moment, one moment,",
                         "bear with me,", "hold on, hold on,",
                         "in one second, one moment,"])
    if len(cmd.clauses) > 1:
        i = 1 + rng.randrange(len(cmd.clauses) - 1)
        cmd.clauses[i]["prefix"] = (cmd.clauses[i].get("prefix", "") + " " + filler).strip()
    else:
        cmd.clauses[0]["prefix"] = (filler + " " + cmd.clauses[0].get("prefix", "")).strip()
    return True


def one_word_swap(cmd, rng) -> bool:
    """The speaker says the wrong word and names the right one: "<wrong>,
    sorry, i mean <right>".

    Observed: `taxonomy.jsonl` class `disfluency`, row 39 — the wrong attendee
    was kept. NO GOLD CHANGE, and that is the point: the corrected value is
    what was asked for, and it is in the words, so it is reachable; the
    superseded one must not win."""
    asks = _subject_asks(cmd)
    if not asks:
        return False
    ask = asks[rng.randrange(len(asks))]
    clause = cmd.clause_for(ask)
    said = ask["subject_said"]
    if clause is None or said not in clause["text"]:
        return False
    from assistant.engine.llmjudge.datasets.v2 import banks
    pool = (banks.EVENT_SUBJECTS if ask["kind"] == "event" else banks.TASK_SUBJECTS)
    wrong = rng.choice([p for p in pool if p != ask.get("title")])
    marker = rng.choice(["sorry, i mean", "no sorry, i mean", "sorry i meant"])
    clause["text"] = clause["text"].replace(said, f"{wrong} {marker} {said}", 1)
    return True


def stutter_repeat(cmd, rng) -> bool:
    """A word or a short run said twice — "of of the", "from 6 from 6".

    Observed: `taxonomy.jsonl` class `disfluency`, rows 30 and 68; the class
    `stutter-split` (row 219) is what happens when the repeat gets read as a
    second ask. No gold change."""
    clause = cmd.clauses[rng.randrange(len(cmd.clauses))]
    words = clause["text"].split()
    if len(words) < 2:
        return False
    i = rng.randrange(len(words) - 1)
    words.insert(i + 1, words[i])
    clause["text"] = " ".join(words)
    return True


def retraction(cmd, rng) -> bool:
    """An ask is said twice and the second one is cancelled: "…no, i said
    that."

    Observed: `taxonomy.jsonl` class `disfluency`, row 223 — four items were
    created for two, because the marker read as filler. **GOLD CHANGE, and it
    is the only op that removes an ask from what the speaker asked for:** the
    repeated clause is in the words and carries no gold ask, so a reader that
    ignores the marker over-counts by exactly one."""
    if not cmd.clauses:
        return False
    src = cmd.clauses[rng.randrange(len(cmd.clauses))]
    echo = {"ask": None, "text": src["text"], "time": src["time"],
            "time_first": src["time_first"], "prefix": "",
            "suffix": " " + rng.choice(["no, i said that.", "no, i said that already.",
                                        "wait, i said that."])}
    cmd.clauses.append(echo)
    cmd.repeated_clause = True
    return True


def wake_word_tail(cmd, rng) -> bool:
    """The trailing wake word this assistant is actually spoken to with.

    Observed: `taxonomy.jsonl` — 'execute.' ends rows 46, 47, 49, 118, 136,
    185, 207, 220 and on row 116 it arrived ALONE and created an event. No
    gold change: it is addressed to the machine, not part of the ask."""
    cmd.tail.append(rng.choice(["execute.", "execute", "go ahead.", "ok go."]))
    return True


def leading_filler(cmd, rng) -> bool:
    """An opener before the command starts.

    Observed: `taxonomy.jsonl` rows 22 ('again,'), 46 ('Right,') and 143
    ('Alright, we have…'). No gold change."""
    cmd.head.append(rng.choice(["right,", "alright,", "again,", "ok so,",
                                "so yeah,", "um,"]))
    return True


# ---------------------------------------------------------------------------
# 3 · the title classes the real-usage board named
# ---------------------------------------------------------------------------

def bare_kind_title(cmd, rng) -> bool:
    """The speaker never names the thing — only what KIND of thing it is.

    Observed: `taxonomy.jsonl` class `generic-title`, the largest class at 42%
    of 50 non-approved rows; rows 18, 34 and 118 are the pure form (nothing
    beyond the kind was said). **GOLD CHANGE:** per DEVQA Q41/Q42 a bare kind
    word COMMITS with the day and the clock, so the gold title becomes that
    word — there is no subject in the words to reach, and `intended_title`
    stays empty because none was ever said."""
    asks = [a for a in _subject_asks(cmd) if a["action"].startswith("create_")]
    if not asks:
        return False
    ask = asks[rng.randrange(len(asks))]
    clause = cmd.clause_for(ask)
    said = ask["subject_said"]
    if clause is None or said not in clause["text"]:
        return False
    from assistant.engine.llmjudge.datasets.v2 import banks
    word = rng.choice(banks.KIND_WORDS["event" if ask["kind"] == "event" else "task"])
    clause["text"] = clause["text"].replace(said, f"a {word}", 1)
    ask["title"] = word
    # AND NO INTENDED TITLE. If a recogniser operation had already mangled this
    # subject, its record goes with the subject: the words now hold neither
    # form, so claiming one would be a gold value nothing can reach. The
    # undamaged sentence is still on the row as `clean_text`.
    ask["intended_title"] = None
    ask["subject_said"] = f"a {word}"
    ask["bare_kind"] = True
    return True


def clock_residue_title(cmd, rng) -> bool:
    """The clock is said again INSIDE the subject phrase, where a reader can
    keep it as part of the name.

    Observed: `taxonomy.jsonl` class `generic-title`, rows 26 and 12 — the
    engine produced titles reading 'meeting a.m' and 'i have an event a
    meeting'. No gold change: the title is still the subject, and the clock is
    still the clock."""
    asks = [a for a in _subject_asks(cmd) if a.get("clock_phrase")]
    if not asks:
        return False
    ask = asks[rng.randrange(len(asks))]
    clause = cmd.clause_for(ask)
    said = ask["subject_said"]
    if clause is None or said not in clause["text"]:
        return False
    spoken = ask["clock_phrase"].split(" ", 1)[1]      # drop the preposition
    clause["text"] = clause["text"].replace(said, f"{said} {spoken}", 1)
    return True


def stated_day_wrong_weekday(cmd, rng) -> bool:
    """A weekday named beside a day the speaker chose, and disagreeing with it.

    Observed: `taxonomy.jsonl` rows 18, 21 and 25 ("tomorrow … on tuesday").
    No gold change, by cycle 36 (2026-09-22): a DELIBERATE day — today,
    tomorrow, an ordinal — beats a weekday, which is a gloss speakers mis-say.
    So this only lands on a deliberate day; on a weekday it would rewrite the
    gold instead of testing it."""
    from assistant.engine.llmjudge.datasets.v2 import banks
    asks = [a for a in cmd.asks if a.get("date_deliberate") and a.get("date_phrase")]
    if not asks:
        return False
    ask = asks[rng.randrange(len(asks))]
    clause = cmd.clause_for(ask)
    if clause is None or not clause["time"]:
        return False
    named = {d for d in banks.WEEKDAYS if d in (ask["date_phrase"] or "")}
    pool = [d for d in banks.WEEKDAYS if d not in named]
    day = pool[rng.randrange(len(pool))]
    clause["time"] = clause["time"].replace(
        ask["date_said"], f"{ask['date_said']} on {day}", 1)
    ask["wrong_weekday"] = day
    return True


def _pick(cmd, rng) -> list:
    """The subject-bearing asks in a shuffled order, so an operation that
    cannot land on the first one tries the next rather than giving up."""
    asks = _subject_asks(cmd)
    rng.shuffle(asks)
    return asks


#: The registry. A name here is what a row's `damage` list carries, and
#: `verify_v2.py` requires every one of them in BOTH halves.
OPERATIONS = {
    "stt_boundary_shift": stt_boundary_shift,
    "stt_syllable_split": stt_syllable_split,
    "stt_compound_join": stt_compound_join,
    "stt_letter_corrupt": stt_letter_corrupt,
    "stt_sound_swap": stt_sound_swap,
    "stt_word_mash": stt_word_mash,
    "trailing_interjection": trailing_interjection,
    "hold_on_chatter": hold_on_chatter,
    "one_word_swap": one_word_swap,
    "stutter_repeat": stutter_repeat,
    "retraction": retraction,
    "wake_word_tail": wake_word_tail,
    "leading_filler": leading_filler,
    "bare_kind_title": bare_kind_title,
    "clock_residue_title": clock_residue_title,
    "stated_day_wrong_weekday": stated_day_wrong_weekday,
}

#: The three that DEFINE a gold change, named here so a reader does not have to
#: infer it from sixteen docstrings. `verify_v2.py` reads this list.
GOLD_CHANGING = ("stt_boundary_shift", "stt_syllable_split", "stt_compound_join",
                 "stt_letter_corrupt", "stt_sound_swap", "stt_word_mash",
                 "bare_kind_title", "retraction")
