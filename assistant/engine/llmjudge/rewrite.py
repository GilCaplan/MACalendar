"""X1' — the failed asks, reworded, and nothing else.

    rewrite_for_retry(state, cfg) -> str | None

## The contract (Gil, 2026-09-08 and 2026-09-09)

The loop used to re-enter Segmentation with the SAME text, which cannot work:
Segmentation is DETERMINISTIC, so the same string yields the same items and the
retry spends the budget to reach the identical answer. Real usage, 2026-09-08:
*"Let an event to go out for a run now"* looped three times to the same result
and apologised after 30 seconds. **No rewrite, no loop.**

And the rewrite is a **TRIM, not a retry of the whole thing** — X1' carries only
the asks that failed. Three consequences, each of them the point:

1. **No double commit.** The good objects are frozen and will be committed. If
   X1' still described them, round two would build them again. The trim is a
   correctness requirement, not an optimisation.
2. **Each round is a SMALLER problem.** Five asks become two. A command too
   tangled to segment gets simpler every round instead of being re-attempted at
   full difficulty — which is why three rounds is enough.
3. **The retry can actually differ**, which is the only thing that makes
   spending a round rational.

## The guard, and the defect it exists for

The first attempt at this built X1' out of `finding.detail` — the human-readable
EXPLANATION ("the words ask for a task — “buy milk” — but nothing produced
covers it") — and Segmentation then parsed the explanation. **A rewrite that
invents text is worse than no rewrite: it replaces the user's words with the
machine's.**

So the invariant, which is `_grounded_title` lifted from a title to a sentence:

    every content word of X1' must already appear in the raw transcript

Function words are exempt; operation verbs are NOT — "delete" appearing in a
rewrite of a command that never said it would change what happens to the user's
data, and that is precisely the class this guard is here to stop. It fails
CLOSED: not grounded means no rewrite means no loop, which is exactly the safe
behaviour the stub had.
"""
from __future__ import annotations

import re

from assistant.engine.llmjudge import findings as F
from assistant.engine.llmjudge import render
from assistant.engine.llmjudge.verdict import tokens as _tokens

#: Function words a rewrite may use even though they carry no content.
_FREE = frozenset(
    "a an the and or but then also at on in to for of with my me i you it this "
    "that is are was were be please".split())

#: Verbs a rewrite MAY introduce, and the asymmetry is the whole point.
#:
#: A bare list — "milk eggs bread" — has no verb at all, and the useful rewrite
#: is "add milk to my list and add eggs to my list". Forbidding every new verb
#: would forbid exactly that, which is most of what X1' is for. So creation
#: verbs are free.
#:
#: DESTRUCTIVE verbs are not, and never become so: delete, remove, cancel,
#: clear, move, rename, complete. A rewrite that introduces one changes what
#: happens to data the speaker never asked to touch, and this project's own rule
#: is that when the engine cannot identify what to delete, "I couldn't find…" is
#: the right answer and guessing is not. Those must be grounded in the words
#: like any other content word.
_SAFE_VERBS = frozenset(
    "add put make set book schedule remind create list note".split())

_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"command": {"type": "string"}},
    "required": ["command"],
}

_REWRITE_SYSTEM = """You are REPAIRING a broken command so an assistant can \
read it on a second attempt.

The parts it already understood have been CUT OUT, so what you are given is a
fragment — the leftovers, often ungrammatical. Your job is to make those
leftovers into a clean command. Nothing else.

WHAT TO SAY
- ONLY what is in the fragment. The parts that were cut out are done; do not
  put them back, do not guess at them, do not mention them.
- Use the speaker's OWN words. Every meaningful word must appear in the
  fragment or in the whole command shown beneath it.
- Never add a subject, a name or a place that is not there.
- Do NOT apologise or explain. Write the command.

HOW TO SAY IT — these are what the reader can actually parse:
1. START EACH ASK WITH ITS VERB: "book dentist…", "add milk…". A fragment with
   no verb is not recognised as an ask at all and will be dropped.
2. JOIN ASKS WITH " and " or " and then ". NEVER a full stop, NEVER a comma —
   the reader does not split on those and will run the asks together.
3. NO "the" BEFORE THE SUBJECT. "book dentist on tuesday" reads correctly;
   "book the dentist on tuesday" mis-reads the subject.
4. WRITE TIMES AS DIGITS WITH am/pm: "at 3pm", not "at three".
5. Keep each ask SHORT — verb, subject, time. Nothing else.

Example.
What is left of the command: milk eggs bread
→ {"command": "add milk to my list and add eggs to my list and add bread to my list"}

Example.
What is left of the command: sort out the dentist thing next tuesday at three
→ {"command": "book dentist on next tuesday at 3pm"}

Return JSON: {"command": "..."}"""


#: A clock time written in digits. EXEMPT from the grounding check, because the
#: prompt asks for exactly this: the speaker said "three" and the rewrite must
#: say "3pm", since `decompose_validate` resolves the digit form and often
#: misses the worded one (measured 2026-09-10: "book dentist on next tuesday at
#: 3pm" resolves start_time 15:00; "…at three" resolves no clock at all).
#:
#: Without the exemption the guard would reject every rewrite that followed its
#: own instruction — a normalisation of something the speaker DID say is not the
#: invention the guard exists to stop.
_TIME_TOKEN = re.compile(r"^\d{1,2}(?::\d{2})?(?:am|pm)?$")


def _content_words(text: str) -> list:
    return [w for w in _tokens(text)
            if len(w) > 2 and w not in _FREE and w not in _SAFE_VERBS
            and not _TIME_TOKEN.match(w)]


def grounded(candidate: str, raw_text: str) -> bool:
    """Is every content word of the rewrite already in the transcript?

    Prefix-stemmed at four characters, the same tolerance `_grounded_title`
    uses, so "reminder" grounds on "remind" and "meeting" on "meet" — the
    speaker's word in a different inflection is still the speaker's word.
    """
    words = _content_words(candidate)
    if not words:
        return False                  # an empty or function-word-only rewrite
    have = set(_tokens(raw_text))

    def ok(w: str) -> bool:
        stem = w[:4]
        return any(tk.startswith(stem) or w.startswith(tk[:4])
                   for tk in have if len(tk) > 2)

    return all(ok(w) for w in words)


def residue(state) -> str:
    """The command with every FINISHED ask cut out of it, verbatim.

    THE TRIM, DONE IN CODE (Gil, 2026-09-10). It used to be an instruction —
    the model was shown the finished objects and told "leave these out" — and
    models are poor at negation. Now the words are simply gone before the model
    sees anything, so a succeeded object cannot appear in X1' because it is not
    in the input.

    Two things this buys, and the second is the one that matters:

      * no double commit, BY CONSTRUCTION rather than by instruction;
      * the model's job shrinks from "select the failed parts and reword them"
        to "repair this broken string", which is the task it is good at and the
        one the grounding guard already fits — the residue is made only of the
        speaker's own words, so almost anything built from it is grounded.

    Removal is by `Item.source`, the VERBATIM span segmentation cut the item
    from — not by word set. "book gym and dentist" with gym finished would lose
    the shared verb if words were subtracted; the span cannot, because it is a
    contiguous piece of the original.

    An ENUMERATION shares one span across its items ("walk the dog at 9 and
    2:30"), so removing it once removes both. That is right: they were one ask
    and they succeed or fail together.
    """
    blamed = {f.item_id for f in F.rewritable(state.findings) if f.item_id}
    text = state.raw_text or ""
    for it in state.items:
        finished = (it.intent is not None and it.action and not it.blocked
                    and it.id not in blamed)
        if not finished:
            continue
        span = (it.source or "").strip()
        if not span:
            continue
        i = text.lower().find(span.lower())
        if i >= 0:
            text = text[:i] + " " + text[i + len(span):]
    # Tidy the seams a removal leaves: doubled joiners, a leading "and", the
    # punctuation that held two asks together.
    text = re.sub(r"\s+", " ", text).strip(" ,.;")
    text = re.sub(r"^(?:and|then|also|plus)\b\s*", "", text, flags=re.I)
    text = re.sub(r"\s*,?\s*\b(?:and|then|also|plus)\b\s*$", "", text, flags=re.I)
    text = re.sub(r"\b(?:and|then)\s+(?:and|then)\b", "and", text, flags=re.I)
    return text.strip(" ,.;")


def failed_asks(state) -> str:
    """X1' — the failed asks, in the speaker's own words, joined by " and ".

    **THE CHOSEN CONSTRUCTION, and it uses no model at all** (Gil, 2026-09-10:
    *"how can we fix the prompt to send back in a more deterministic way"*).
    Five ways of building X1' were measured against each other on 60 multi-ask
    rows — `experiments/x1_variants.py`, banked in RESULTS.md §Cycle 11:

        variant                    recovered  leaked  empty   net
        C failed spoken()                 54       8      0     46   <- this
        D failed spans                    54       8      0     46
        B residue raw                     53      18      2     35
        E residue + code reshape          50      18      2     32
        A residue + LLM repair            41      13     10     28   <- worst

    **The model made it worse on every axis**: fewer asks recovered, more
    finished asks leaked back in, and ten rows where the guard had to refuse
    what it wrote. Asking a model to rebuild a command out of pieces it can see
    is asking it to paraphrase, and a paraphrase is the one thing X1' must not
    be.

    Building it from the failed items also beat SUBTRACTING the finished ones
    from the original (B/E), which was the first shape of this idea: a
    subtraction leaves seams and shared context that re-parse into the finished
    ask again — 18 leaks against 8.

    `spoken()` rather than `Item.source` breaks the tie: the two scored
    identically, but when `decompose_validate` splits one span into sub-items
    they SHARE a source, so spans would carry a sibling back with the failure
    while `spoken()` carries only what failed.
    """
    blamed = {f.item_id for f in F.rewritable(state.findings) if f.item_id}
    listed = {f.item_id for f in F.rewritable(state.findings)
              if f.type == F.COORDINATED_SUBJECT}
    parts, seen = [], set()
    for it in state.items:
        if it.id not in blamed:
            continue
        pieces = (expand_list(it) if it.id in listed else None) or [it.spoken()]
        for said in pieces:
            said = (said or "").strip()
            key = said.lower()
            if said and key not in seen:
                seen.add(key)
                parts.append(said)
    return _tidy(" and ".join(parts))


def expand_list(item) -> "list[str] | None":
    """One clause per listed thing, in the speaker's own words.

        "create an event for dentist, haircut and gym"  +  "on friday"
        -> ["on friday create an event for dentist",
            "on friday create an event for haircut",
            "on friday create an event for gym"]

    Gil's own example (2026-09-20), verbatim in shape: the shared time leads
    each clause, the head and tail are copied around each member, and the
    joiner is " and " — the one seam segmentation cuts on. Every word is the
    speaker's, so the grounding guard below passes by construction; the
    injected date floor is left out the way `Item.spoken()` leaves it out.
    """
    from assistant.intent.coordination import noun_list

    found = noun_list(item.text or "")
    if not found:
        return None
    head, members, tail = found
    when = " ".join(w for w in (item.time or "").split()
                    if w.lower() != "today" or "today" in (item.text or "").lower())
    out = []
    for m in members:
        out.append(_tidy(" ".join(x for x in (when, head, m, tail) if x)))
    return out


def _tidy(text: str) -> str:
    """Close the seams: doubled joiners, a leading "and", trailing punctuation."""
    text = re.sub(r"\s+", " ", text or "").strip(" ,.;")
    text = re.sub(r"^(?:and|then|also|plus)\b\s*", "", text, flags=re.I)
    text = re.sub(r"\s*,?\s*\b(?:and|then|also|plus)\b\s*$", "", text, flags=re.I)
    text = re.sub(r"\b(?:and|then)\s+(?:and|then)\b", "and", text, flags=re.I)
    return text.strip(" ,.;")


def rewrite_for_retry(state, cfg) -> "str | None":
    """X4 + the findings -> X1', or None when no honest retry exists.

    NO MODEL CALL. It had one until 2026-09-10 and the measurement removed it —
    see `failed_asks`. `cfg` stays in the signature because the orchestrator
    calls it that way and every other stage entry point takes it; a signature
    change here is a contract change for nothing.

    None is returned — rather than a guess — for each of: nothing earns a
    rewrite, the failed asks have no words of their own, the result is the
    command we already tried, or it somehow fails the grounding guard. Each is
    a reason not to spend a round, and the orchestrator reads None as "stop".
    """
    if not F.rewritable(state.findings):
        return None

    candidate = failed_asks(state)
    if not candidate:
        return None
    # An unchanged string re-enters a DETERMINISTIC segmenter and returns the
    # identical items — the exact loop this mechanism exists to break. This is
    # what happens when segmentation under-split: the one item's words ARE the
    # whole command, so there is nothing to carry forward and nothing to gain.
    if candidate.casefold() == (state.text or "").casefold().strip():
        return None
    # The guard is now near-tautological — the words come from the items, which
    # came from the command — and it stays because "near" is not "always":
    # `decompose_validate` may repair an item's text, and a repair that invents
    # a word must not reach segmentation unnoticed.
    if not grounded(candidate, state.raw_text):
        state.add_fix("llmjudge", "rewrite_rejected", candidate[:60], "",
                      note="the rewrite used words the speaker never said")
        return None
    return candidate
