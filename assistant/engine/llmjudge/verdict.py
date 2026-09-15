"""The deterministic half — evidence in, findings out. No model is called here.

    collect(state)                -> [Produced, …]   the objects to check
    judge(state, produced, ground) -> [CheckFinding, …]

`evidence.py` asks the model ONE copying question. **This module does all the
deciding**, which is the division the stage was built on and the one thing the
2026-09-10 re-cut did not change.

## What went away, and why (Gil, 2026-09-10)

This module used to diff an ask list against the objects — token overlap on the
item text at a 0.25 threshold, a two-pass kind relaxation, a capacity counter —
to produce `missing` and `extra`. All of it is gone.

> *"I don't want extraction, that defeats the point of what segmentation →
> decompose_validate → FastRule did."*

The ask list was a SECOND opinion on something segmentation had already decided,
produced by a weaker instrument, and every disagreement was scored against
segmentation. The residue was false `missing` and false `extra` — which is what
paid for the 2026-09-08 loop storms — and the one false flag on this stage's own
board was the extraction inventing an ask out of *"i already handled it"*.

**Every check here is now per-object and needs no view of the whole command.**

## Three sources of finding, in order of cost

    the SLOT check      a temporal field the object asserts and
                        `decompose_validate` never resolved      free, no model
    the SUBJECT tests   a generic title, or a title with no word
                        in the transcript                        free, no model
    the model's `none`  a field it could not point at            one call

The first two run FIRST and `continue` past the third, so a fabrication with no
word in the words is caught without consulting anything. That ordering is what
took `invented_title` from 25% to 94% on the isolation board: the model was
answering that question badly, and the fix was to stop asking it.

## One thing kept from the old code, bought with a defect

**A BLOCKED item is still collected but never `not_an_ask`.** The observance
gate ANSWERED that ask with an explained refusal; treating it as unsupported
sent every gated command into a loop that could not change a policy decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from assistant.engine.state import CheckFinding
from assistant.engine.llmjudge import findings as F
from assistant.engine.llmjudge import render

#: "rename X to Y" / "change X to Y" / "call it Y instead of X" — a sentence
#: that names two things on purpose. See `title_dropped_the_verb`.
_RENAME_SHAPE = re.compile(
    r"\b(?:rename|re-?name)\b|\bchange\b.+\bto\b|\bcall it\b.+\binstead of\b",
    re.I)

#: Claim labels that establish WHO OR WHAT the object is about. Ungrounding one
#: of these is a different finding from ungrounding a value — see findings.py.
_IDENTITY = re.compile(r"^(?:title(?:_\d+)?|target)$")

_MUTATIONS = ("update_event", "delete_event", "update_todo", "delete_todo",
              "complete_todo", "add_subtask")

#: Words too generic to ground a title on their own. Shared in spirit with
#: `llm_fallback._TITLE_STOP` and restated rather than imported: that one guards
#: a DROP and this one a FLAG, so they are free to diverge and a change to
#: either must be a decision rather than a side effect.
#:
#: THE COMMAND VERBS ARE IN HERE, and that is the difference that matters. A
#: title carries a verb the speaker almost certainly said whatever the object is
#: about — "add", "buy", "book" — so counting the verb as grounding meant an
#: object titled "buy groceries" looked supported by the words "buy milk". The
#: verb is shared; the SUBJECT is not, and the subject is the whole question
#: this test asks. Found 2026-09-10 by a test that used to pass through the ask
#: diff and had nothing to catch it once the ask diff was gone.
_TITLE_STOP = {
    "the", "a", "an", "and", "with", "for", "new", "my", "our",
    # command verbs — present in the words for almost any command
    "add", "buy", "get", "book", "set", "make", "put", "call", "schedule",
    "remind", "reminder", "create", "plan", "arrange", "need", "want",
    # These reach the EMBEDDED position and are still instructions rather than
    # content: "MARK submit the report as done", "LET'S DO staff meeting",
    # "RENAME walk the dog to …". Measured on the clean cases — each one was a
    # false fire before it was listed. `cancel`/`move`/`remove` deliberately
    # stay OUT: they are commands as a ROOT verb, which the xcomp test already
    # excludes, and genuine content when embedded ("remind me to CANCEL the
    # subscription"), which is a catch worth keeping.
    "mark", "do", "let", "rename", "check", "extend",
}


def tokens(text: str) -> "list[str]":
    """The words of a string, as every grounding test here reads them.

    ONE definition, because there were four and they disagreed about a quote
    mark. `[a-z0-9\']+` keeps the apostrophe so "don\'t" and "o\'clock" survive
    as single words — and then eats the QUOTE MARKS around a quoted title too:

        remove \'team meeting\' from my calendar   ->   ["\'team", "meeting\'", …]

    Nothing matches `\'team`. The prefix stemmer compares `w[:4]` against
    `tk[:4]`, and `\'tea` is not `team`, so a title the speaker QUOTED VERBATIM
    read as a word they never said. Measured 2026-09-10 on 3,175 chain-produced
    titles: 34 flagged by the strict subject test, and the quoted-title rows were
    the largest single cause — every one of them a title the command spelled out
    in full.

    A TRAILING apostrophe was harmless (`meeting\'`.startswith("meet")), which is
    exactly why this survived: `names_nothing_spoken` needs EVERY word to fail,
    the second word always passed, and the defect only surfaced once a test asked
    whether ALL of them ground.

    Stripped at the edges only — an internal apostrophe is part of the word.
    """
    return [w for w in (t.strip("'") for t in
                        re.findall(r"[a-z0-9']+", (text or "").casefold())) if w]


@dataclass
class Produced:
    """One object the engine decided about — the unit everything compares to."""

    item: object
    oid: str
    kind: str                       # event | task | review
    action: str
    intent: object
    slots: dict = field(default_factory=dict)
    #: A create that actually wrote a row — the only kind that can be a
    #: `not_an_ask` candidate. A mutation names an EXISTING record, so "the
    #: words do not support it" is a different question with a different
    #: answer, and treating one as spurious would offer to undo a row the
    #: speaker asked to change.
    removable: bool = False


def collect(state) -> "list[Produced]":
    """Everything the engine decided about, as the comparable surface."""
    out: "list[Produced]" = []
    for it in state.items:
        if it.intent is None or not it.action:
            continue
        slots = dict(it.slots or {})
        if it.action in ("create_event", "create_todo"):
            kind = "event" if it.action == "create_event" else "task"
            out.append(Produced(it, it.id, kind, it.action, it.intent, slots,
                                removable=not it.blocked))
        elif it.action in _MUTATIONS:
            out.append(Produced(it, it.id, "event" if "event" in it.action else "task",
                                it.action, it.intent, slots))
        elif it.action == "query_schedule":
            out.append(Produced(it, it.id, "review", it.action, it.intent, slots))
    return out


def names_nothing_spoken(title: str, raw_text: str) -> bool:
    """Is NOT ONE content word of this title anywhere in the transcript?

    **Deliberately weaker than `llm_fallback._grounded_title`, and the
    difference is what each one is allowed to do.** `_grounded_title` requires
    EVERY content word to be spoken, because it DROPS a fabricated event — a
    strict test guarding a destructive action. This one only FLAGS, and routes
    to a rewrite, so the strict version is miscalibrated for it: cycle 2's first
    cut used `_grounded_title` and immediately flagged an event titled "gym
    session" produced from "gym saturday", which is a good title with one extra
    word.

    Zero overlap is the honest line. A fabrication has no word in the words —
    that is what makes it a fabrication — while a title that is merely loose,
    abbreviated or slightly padded still shares its subject with the transcript.

    Prefix-stemmed at four characters like every other grounding test here, so
    "meeting" counts as spoken when the words say "meet".
    """
    words = [w for w in tokens(title)
             if len(w) > 2 and w not in _TITLE_STOP]
    if not words:
        return False                  # bare or stopword-only: judged elsewhere
    have = [tk for tk in tokens(raw_text) if len(tk) > 2]
    for w in words:
        stem = w[:4]
        if any(tk.startswith(stem) or w.startswith(tk[:4]) for tk in have):
            return False              # at least one word IS spoken
    return True


def unspoken_word(title: str, raw_text: str) -> "str | None":
    """The first content word of this title the transcript never said, if any.

    **THE IDENTITY TEST, since 2026-09-10 — and it replaces zero-overlap.**

    `names_nothing_spoken` asks whether NOT ONE word was said, which a near
    miss passes by construction: "gym membership" from *"book gym session on
    tuesday"* shares "gym", so the shipped test sees a word it recognises and
    waves the object through. That is the whole of `near_miss_title`, and it sat
    at **0% on 63 planted cases** for thirteen cycles.

    This asks the other question — is there a word here nobody said — and
    answers 63 of 63. The word it returns is the evidence, and it goes in the
    finding: *"membership" was never said* is a sentence a person can check, and
    a far better rewrite signal than "this title is wrong".

    ## Why the strictness is affordable now, and was not judged so before

    Cycle 2 rejected exactly this test on ONE anecdote — it flagged "gym
    session" produced from *"gym saturday"*. The anecdote was never priced.
    Priced, on 7,640 titles the REAL chain produced from three corpora
    (`experiments/title_falseflag.py`, 2026-09-10):

        ZERO-OVERLAP  (shipped)      0 / 7640    0.00%
        EVERY-WORD    (this)        14 / 7640    0.18%
        …realspeech 0.0%, segmentation 0.0%, fastrule 0.3%

    and all fourteen are ONE defect family — *"remind me to fix the leaky faucet
    tommorow"* titled `fix the leaky faucet tomorrow`, where FastRule failed to
    strip a MISSPELLED time phrase and spell-normalised it into the title. The
    title really does contain a word the speaker did not say, and it really
    should not contain a time word at all. Those are FastRule findings this test
    surfaces, not costs it imposes.

    **Half of that measurement was a defect in the reading, not the test.**
    Before `tokens()` stripped quote marks the same board read 34 fires and the
    shipped test read 7; the quoted-title rows were an artefact of the
    tokeniser. A cost measured with a broken instrument is not a cost, and the
    first run of this board would have priced the change out at six times its
    real price.

    ## What it is NOT allowed to do

    `_not_an_ask` keeps `names_nothing_spoken`, deliberately. "Not one field of
    this object can be pointed at" is a claim about a SPURIOUS object, offered
    to the user as something to remove, and the strict reading would offer to
    remove an object with one imperfect word in an otherwise correct title. The
    two tests ask different questions now, and each is calibrated for the move
    it authorises: this one FLAGS and rewrites, that one PROPOSES A REMOVAL.
    """
    ws = [w for w in tokens(title) if len(w) > 2 and w not in _TITLE_STOP]
    if not ws:
        return None                   # bare or stopword-only: judged elsewhere
    have = [tk for tk in tokens(raw_text) if len(tk) > 2]
    for w in ws:
        stem = w[:4]
        if not any(tk.startswith(stem) or w.startswith(tk[:4]) for tk in have):
            return w
    return None


def _subject_findings(state, produced) -> list:
    """Identity and value claims the words do not support.

    ONE source since 2026-09-10, and it is deterministic: the slot check (a
    temporal field the words never gave — `render.unsupported_by_slots`) and the
    two subject tests. The model's `none` answers were the third and are retired;
    see the comment at the old call site below.
    """
    from assistant.engine.llmjudge.gatekeeper import _GENERIC_TARGET_RE

    raw = state.raw_text or ""
    out = []
    for p in produced:
        for c in render.unsupported_by_slots(p.action, p.intent, p.slots):
            out.append(CheckFinding(
                type=F.UNSUPPORTED_FIELD, item_id=p.oid,
                detail=f"{c.label} = {c.rendered} — nothing in the words said it",
                blamed_stage=F.BLAMED[F.UNSUPPORTED_FIELD]))

        for c in render.claims(p.action, p.intent, p.slots):
            if not c.needs_model:
                continue
            identity = bool(_IDENTITY.match(c.label))

            # 1 · DETERMINISTIC, and it runs FIRST — cycle 2, 2026-09-10.
            #
            # Cycle 1 measured `invented_title` caught 4 of 16 (25%) on the
            # train half: a title whose every word is absent from the
            # transcript was waved through three times in four. That is the
            # accept bias on our own 8B — asked to quote the supporting words
            # or answer `none`, it rarely answers `none` and quotes something
            # loosely related instead.
            #
            # Both of these checks were already in this folder and neither
            # reached the verdict. `_grounded_title` is ALREADY trusted enough
            # to DROP a fabricated event in the rescue path, so trusting it
            # merely to FLAG one here is strictly the weaker use.
            if identity and c.raw and c.is_words:
                if _GENERIC_TARGET_RE.match(c.raw):
                    out.append(CheckFinding(
                        type=F.UNGROUNDED_SUBJECT, item_id=p.oid,
                        detail=f"“{c.raw}” is the program's own word for a "
                               f"calendar entry, not a name for one",
                        blamed_stage=F.BLAMED[F.UNGROUNDED_SUBJECT]))
                    continue
                unspoken = unspoken_word(c.raw, raw)
                if unspoken:
                    out.append(CheckFinding(
                        type=F.UNGROUNDED_SUBJECT, item_id=p.oid,
                        detail=f"“{c.raw}” — the words never said "
                               f"“{unspoken}”",
                        blamed_stage=F.BLAMED[F.UNGROUNDED_SUBJECT]))
                    continue

            # 2 · THE SAME TEST ON A NON-IDENTITY WORD CLAIM — `location`,
            # `attendees`. Different finding TYPE, because the route differs: a
            # subject the words never named is rewritten, a VALUE they never gave
            # is committed with a notice, and this stage's whole point is that
            # those are not the same move.
            #
            # These fields had NO deterministic check before 2026-09-10 — the
            # model's `none` was the only thing looking at them, so retiring the
            # call would have left "location = the roof" on an event built from
            # *"book gym monday at nine"* with nothing to say. `unspoken_word`
            # was already answering exactly this question one claim over.
            if c.is_words and c.raw and unspoken_word(c.raw, raw):
                out.append(CheckFinding(
                    type=F.UNSUPPORTED_FIELD, item_id=p.oid,
                    detail=f"{c.label} = {c.rendered} — the words never said "
                           f"“{unspoken_word(c.raw, raw)}”",
                    blamed_stage=F.BLAMED[F.UNSUPPORTED_FIELD]))
                continue

            # 3 · THERE IS NO SECOND OPINION ANY MORE — the model's citation was
            # asked for here until 2026-09-10 and is retired
            # (`retired/llmjudge-grounding-call/`). It was 57% of every Ollama
            # call the system made and it changed no outcome: on 32 hand-written
            # cases the judge scored identically with and without it, row for
            # row. Shown a title of "gym membership" from *"book gym session on
            # tuesday"* the model quotes **"gym session"** — the words behind the
            # title the object SHOULD have had — and a non-`none` answer is an
            # accepted one. It answers the question it wishes it had been asked.
            #
            # Everything it was meant to catch, `unspoken_word` above catches for
            # free. RESULTS.md cycles 5, 7, 11, 12 and 15 are the whole ledger.
    return out


def title_dropped_the_verb(title: str, item_text: str) -> bool:
    """Did the title keep the object and throw away the ACTION?

**UNWIRED AGAIN, and this time by the board rather than by a proxy.**

An offline check of this function against GOLD titles predicted 0.3% false
flags on train. The isolation board, running the real chain, measured **19.4%**
— the produced title differs from the gold one far more often than the proxy
assumed, and each difference is a chance to fire. Two rounds of tuning against
a cheap approximation bought nothing, and the lesson is the project's own:
before trusting any board, run it — and a hand-rolled proxy is not it.

Kept unwired with the whole curve, because the curve is the useful part.

**The history, from the fourth cut:** The first three were rejected on price and the
    trade only became worth making once the over-firing was understood rather
    than guessed at — `experiments/RESULTS.md` §Cycle 10 has the whole curve:

        any non-command verb dropped      catch 70.9 -> 86.1   false-flag 61.3%
        embedded verbs only (xcomp)       catch 70.9 -> 77.2   false-flag 27.4%
        + main clause only (pre-comma)                         false-flag  3.3%
        + embedded command verbs listed                        false-flag  2.0%
        + renames excluded                                     false-flag  0.3%

    The last three came from READING the clean rows that fired rather than
    turning a threshold: every over-fire was a trailing commentary clause
    ("cancel yoga class, SOMETHING CAME UP"), an instruction verb in embedded
    position ("MARK submit the report as done"), or a rename, where the second
    verb belongs to the new name.

    **Those last figures are the TRAIN half, and the test half says 3.1%.** Four
    rounds of looking at train rows is four chances to fit them, and the gap is
    what that cost. 3.1% is the number to quote.

    The largest blind spot the rewrite board found (2026-09-10): four of nine
    failing rows had a title that was a grounded FRAGMENT of the right answer,
    so nothing was looking for it —

        "i need to talk to Quinn on a week from today"  -> title "quinn"
        "i should see Jesse next month"                 -> title "jesse"
        "invite Quinn and Morgan to town hall"          -> title "quinn"

    Every word of "quinn" IS in the transcript, so `names_nothing_spoken` is
    False. The title is not fabricated; it is amputated.

    ## The distinction that makes this safe

    A title is SUPPOSED to drop the command verb — "book gym" gives "gym", and
    flagging that would fire on every correct row in the corpus. It is not
    supposed to drop a CONTENT verb, because the content verb is what the event
    IS: talking to Quinn, seeing Jesse, walking the dog.

    So the test is: the item's words contain a verb that is **not a command
    verb** (`_TITLE_STOP` holds those) and **not in the title**. That single
    condition separates the two cases cleanly:

        "book gym"        verb `book` is a command verb        -> fine
        "walk the dog"    verb `walk` IS in the title          -> fine
        "talk to Quinn"   verb `talk`, kept out of the title   -> FLAG

    POS, not NER, and deliberately: `en_core_web_sm` will not tag "Quinn" as a
    PERSON even in context (measured — it caught 1 of 3), while it tags "talk"
    a VERB reliably. The evidence that was available was not the evidence the
    first attempt reached for.
    """
    t_words = {w for w in tokens(title) if len(w) > 2}
    if not t_words:
        return False
    # ONLY THE MAIN CLAUSE. Everything before the first comma.
    #
    # Every false fire measured on the clean cases had its verb in a TRAILING
    # COMMENTARY clause — "cancel yoga class, SOMETHING CAME UP", "mark submit
    # the report as done, FINALLY GOT TO IT", "move that appointment to, I DON'T
    # REMEMBER the name". None of those verbs is a dropped subject; they are the
    # speaker talking about the ask rather than making it, and segmentation
    # already calls them discourse tails.
    head = (item_text or "").split(",", 1)[0].strip()
    if not head:
        return False
    # A RENAME NAMES TWO THINGS, and the second verb belongs to the new name,
    # not to a subject that was dropped: "rename walk the dog to FIX the leaky
    # faucet", "call it SUBMIT the report instead of return the library books".
    # Every false fire left after the comma rule was one of these.
    if _RENAME_SHAPE.search(head):
        return False
    try:
        from assistant.intent import rule_parser as _rp
        _rp._ensure_nlp()
        if _rp._NLP is None:
            return False
        doc = _rp._NLP(head)
    except Exception:
        return False
    for tok in doc:
        if tok.pos_ != "VERB":
            continue
        # ONLY AN EMBEDDED VERB COUNTS, and this is the line between the two
        # cases. The ROOT verb is the INSTRUCTION to the calendar — "book gym",
        # "block off the day", "invite Quinn" — and a title is supposed to drop
        # it. An embedded verb is what the event IS: "remind me TO CANCEL the
        # subscription", "i need TO TALK to Quinn".
        #
        # The first cut flagged any non-command verb and priced out at a 61.3%
        # false-flag rate on the isolation board — it fired on every correct row
        # whose root verb was not in a hand-written list, and no list is ever
        # long enough. The parse already knows the difference; the list was
        # trying to re-derive it by hand.
        if tok.dep_ not in ("xcomp", "ccomp", "advcl") or tok.head.pos_ != "VERB":
            continue
        lemma = (tok.lemma_ or tok.text).lower()
        if lemma in _TITLE_STOP or tok.text.lower() in _TITLE_STOP:
            continue
        if lemma in t_words or tok.text.lower() in t_words:
            continue                  # the title kept it
        return True                   # the action, embedded, and thrown away
    return False


def _shares_subject(said: str, title: str) -> bool:
    """Do the model's produced name and the object's title name the same thing?

    Content-word overlap with the same four-character stemming every other
    grounding test here uses, and the same stop list — so the shared VERB in
    "buy groceries" vs "buy milk" cannot make them agree, which is the whole
    case this is here to separate.
    """
    def words(t: str) -> set:
        return {w[:4] for w in tokens(t)
                if len(w) > 2 and w not in _TITLE_STOP}
    a, b = words(said), words(title)
    if not a or not b:
        return True                   # nothing to compare: judged elsewhere
    return bool(a & b)


def slot_came_from_words(item, raw_text: str) -> bool:
    """Was this item's WHEN resolved from something the speaker said?

    **THE DATE FLOOR, and it had killed a whole route** (2026-09-10).

    Segmentation stamps `Item.time = "today"` on an item that named no time, and
    `decompose_validate` faithfully resolves that into `slots["date"]`. So by the
    time an object exists, its date slot is set — whether or not anybody said a
    date. Measured on 2,000 utterances through the real chain:

        create objects built                     1780
        …with `slots["date"]` set                1780   100.0%
        …where that date is a FLOOR nobody spoke  393    22.1%

    `_not_an_ask` asks "is ANY claim of this object grounded" and treats a
    present slot as a yes. A slot that is always present is always a yes, so
    **`_not_an_ask` could not fire on a single one of those 1,780 objects** and
    the PANEL route — one of the three Gil specified — was unreachable in
    production. The isolation board scores it 100% only because its synthetic
    spurious object carries `slots={}`, an object shape the chain never builds.

    `Item.time` is the honest witness: the contract says it is the time
    reference AS SPOKEN. If its words are in the transcript the resolution came
    from the speaker; if it says "today" and nobody said "today", it is a floor.

    Deliberately narrow. This gates `_not_an_ask` ONLY — the question "did the
    speaker give a when at all", which decides whether an object is spurious.
    It is NOT wired into `unsupported_by_slots`, where the same floor means 22%
    of created events assert a date nobody spoke: that is a real finding and a
    much larger blast radius, and it belongs to its own cycle rather than
    riding along with this one.
    """
    when = (getattr(item, "time", "") or "").strip()
    if not when:
        return False
    ws = [w for w in tokens(when) if len(w) > 2]
    if not ws:
        return False
    have = [tk for tk in tokens(raw_text) if len(tk) > 2]
    return any(any(tk.startswith(w[:4]) or w.startswith(tk[:4]) for tk in have)
               for w in ws)


def _not_an_ask(state, p, siblings: bool = False) -> bool:
    """Is NOTHING about this object supported by the words?

    What survives of `extra` after the ask list went away, and a stronger test
    than `extra` was: that one meant *"the model's ask list did not mention
    it"*, which was as often the ask list's fault as the object's. This means
    *"not one field of it can be pointed at in the transcript"*, which needs no
    opinion about how many asks there were.

    Deliberately demanding. An object with a good title and an invented time is
    a WRONG object, not a spurious one, and it must be reported field by field
    and committed — not offered to the user as something they never asked for.
    So every claim has to fail before this fires.

    **THE MODEL CANNOT OVERTURN THIS, and that is a measured decision.** An
    earlier cut let a positive grounding answer clear a claim the deterministic
    test had already failed. The board caught what that costs: `unrelated_object`
    was detected 7 times in 15, and every miss looked the same — the object was
    flagged `ungrounded_subject` (deterministically, correctly) while
    `not_an_ask` was suppressed because the model had cheerfully quoted
    something for the title of an event nobody mentioned.
    That is the accept bias defeating the check built to survive it. Where
    `names_nothing_spoken` says no word of a title was uttered, the model's
    opinion is not evidence to the contrary.
    """
    if not p.removable:
        return False                  # a mutation names an existing record
    if p.item.blocked:
        return False                  # already answered, with a reason
    if not siblings:
        # THE ONLY OBJECT BUILT FROM THIS COMMAND IS NEVER SPURIOUS.
        #
        # Added the same hour as the floor fix, because the floor fix without it
        # cost `invented_title` 98.8% -> 81.7% on 753 cases: with the date no
        # longer counting as grounding, every plain wrong title on a command
        # that named no time became "nothing here is supported" and routed to
        # the PANEL. The panel says *you never asked for this*, and about a
        # command whose one ask is real that is simply false — the speaker asked
        # for something and FastRule named it wrong, which is a REWRITE.
        #
        # This module's own rule, written before either change: "an object with
        # a good title and an invented time is a WRONG object, not a spurious
        # one, and it must be reported field by field and committed — not
        # offered to the user as something they never asked for."
        #
        # A spurious object is one the engine produced BESIDE the ones that
        # answer the command. That needs no view of how many asks there were —
        # only whether anything else was built — so it does not re-open the ask
        # diff this stage deleted.
        return False
    cs = render.claims(p.action, p.intent, p.slots)
    if not cs:
        return False
    spoken_when = slot_came_from_words(p.item, state.raw_text or "")
    for c in cs:
        if c.slot_key is not None:
            if (spoken_when
                    and (p.slots or {}).get(c.slot_key) not in (None, "", [], {})):
                return False          # a value the words really gave
            continue
        if not names_nothing_spoken(c.raw, state.raw_text or ""):
            return False              # a word of it WAS spoken
    return True


def judge(state, produced) -> "list[CheckFinding]":
    """Everything wrong with what was produced, one object at a time.

    **NO MODEL IS CONSULTED, at all, since 2026-09-10.** The signature used to
    carry a `grounding` dict and `None` meant "Ollama was unreachable"; there is
    no such case now, and a command is verified exactly as well with the model
    down as with it up. That was already the direction of travel — the slot check
    and both subject tests never needed one — and the measurement finished the
    job: the call was 57% of the system's Ollama traffic and moved nothing.
    """
    out: list = []
    for p in produced:
        # WHOLLY unsupported comes first and replaces the per-field findings for
        # that object: telling the speaker "the title is ungrounded AND the date
        # is ungrounded AND the time is ungrounded" about a row they never asked
        # for is three sentences where one is true — *this should not be here*.
        if _not_an_ask(state, p, siblings=len(produced) > 1):
            title = getattr(p.intent, "title", None) or p.item.text
            out.append(CheckFinding(
                type=F.NOT_AN_ASK, item_id=p.oid,
                detail=f"a {p.kind} — “{title}” — that nothing in the words asks for",
                blamed_stage=F.BLAMED[F.NOT_AN_ASK]))
            continue
        out += _subject_findings(state, [p])
    return out
