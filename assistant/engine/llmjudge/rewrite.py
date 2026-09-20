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
    "that is are was were be please about from by as up out off into onto over".split())

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
    "properties": {"asks": {"type": "array", "items": {"type": "string"}}},
    "required": ["asks"],
}

_REWRITE_SYSTEM = """You repair ONE spoken command to a calendar and to-do assistant. Part of \
it could not be acted on. What you write is read by a DETERMINISTIC parser on \
the next attempt, so the SHAPE of each line matters as much as the words.

YOUR INPUT
- THE SPEAKER SAID: the whole command, verbatim. The ONLY source of words.
- STILL TO DO: the part that failed, in the speaker's words.
- ALREADY DONE: asks the assistant has finished. Never write them again.
- WHAT WAS TRIED: every earlier attempt, what it produced, and what the judge \
found wrong with it. Never hand back a line that was already tried. Fix the \
thing the judge named.

YOUR OUTPUT
{"asks": ["...", "..."]} — one string per ask, in the order spoken. An ask is \
ONE calendar event or ONE to-do. If STILL TO DO holds two things, write two \
asks. If it cannot be made into an ask at all — no subject ("add this", \
"remind me at this time") — return {"asks": []}. Never guess a subject.
A line that is neither a calendar entry nor a to-do item is NOT an ask and is \
left out: "open calendar", "reopen groceries", "show me", "go to settings", \
"set event" with nothing to set. Fewer lines beats a line that is not an ask.

THE WORDS — the guard refuses the whole answer otherwise
- Every meaningful word must appear in THE SPEAKER SAID. Never add a name, a \
place, a thing, a number, a date, a time or a repeat the speaker did not say.
- You MAY open an ask with one of these framing verbs even if the speaker did \
not: add, put, make, set, book, schedule, remind, create, list, note.
- Never introduce delete, remove, cancel, clear, move, rename or complete \
unless the speaker said it.
- Drop wake words, politeness and filler: "hey siri", "alexa", "please", "can \
you", "for me", "okay".

THE SHAPE — what the parser reads correctly
1. VERB FIRST: "book dentist on friday at 3pm", "add milk to my list", \
"remind me to call mom tomorrow". A line without a verb is dropped.
2. ONE THING PER LINE. Never join two with "and", "then", "also" or a full \
stop — the list is the separation.
3. TO-DO framing for errands and list items: "add <thing> to my list", \
"remind me to <verb> <thing>". A bare "add milk" reads as a calendar entry — \
when the speaker named a list (list, groceries, shopping, to-do), EVERY item \
line ends with the destination: "add milk to my shopping list", "put xxx on \
the list". CALENDAR framing for anything with a date, a clock time or an \
occasion: "book <thing> on <day> at <time>", "remind me of <occasion> on <day>".
4. TIME AT THE END of the line it belongs to. Digits with am/pm: "at 3pm", \
"at 9:30am", never "at three". Keep the speaker's date words as spoken: \
"tomorrow", "on friday", "next monday", "march 25th", "in two hours".
5. REPEATS: keep the speaker's recurrence phrase EXACTLY and put it at the end \
of the one line it belongs to — "every monday", "every tuesday and thursday", \
"every other week", "daily", "every morning", "for the next three sundays" — \
with its bound if spoken: "until june 3rd". A repeating reminder is a \
calendar line: "remind me to take out the trash every monday". Never spread \
a repeat onto a line the speaker did not repeat.
6. NO "the" before the subject: "book dentist", not "book the dentist".
7. No questions, no explanations, no punctuation inside a line except the time.

EXAMPLES
STILL TO DO: "set event, and then can you please create a list for me"
→ {"asks": ["set event", "create a list"]}

STILL TO DO: "remind me every monday to take out the trash. Also, PUT MILK ON MY SHOPPING LIST"
→ {"asks": ["remind me to take out the trash every monday", "add milk to my shopping list"]}

STILL TO DO: "for the next three sundays remind me i have yoga class at noon, and then yashas birthday with vinay"
→ {"asks": ["remind me of yoga class at 12pm for the next three sundays", "add yashas birthday with vinay"]}

STILL TO DO: "reopen groceries and add milk. Also, put xxx on the list"
→ {"asks": ["add milk to my groceries list", "put xxx on the list"]}

STILL TO DO: "add this on my calender"
→ {"asks": []}

Return JSON: {"asks": [...]}"""


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
        if any(tk.startswith(stem) or w.startswith(tk[:4])
               for tk in have if len(tk) > 2):
            return True
        # A transcript typo is still the speaker's word: "bithday" refused a
        # correct "birthday" and with it the whole repair (dev-100, 2026-09-20).
        # One edit, and only on words long enough that one edit cannot make a
        # different word of them: "monday" -> "sunday" is two.
        return len(w) >= 6 and any(len(tk) >= 6 and _one_edit(w, tk) for tk in have)

    return all(ok(w) for w in words)


def _one_edit(a: str, b: str) -> bool:
    """Levenshtein distance <= 1, without the table."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


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

    **THE CHOSEN CONSTRUCTION FOR TIER 1, and it uses no model at all** (Gil,
    2026-09-10: *"how can we fix the prompt to send back in a more
    deterministic way"*). Since 2026-09-20 it is the FIRST tier: given the
    same failure twice it writes the same string twice, so the rounds after
    it go to `rewrite_with_model` (Gil: *"on the second iteration it will do
    the same thing and there we would need a llm"*).
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

    TWO TIERS, deterministic first (Gil, 2026-09-20):

    1. `failed_asks` — the failed asks in the speaker's own words, no model.
       It is a trim or an expansion of what was said, so given the same
       failure twice it writes the same string twice; the second round of it
       is dead by construction.
    2. When that has nothing NEW to say — the string was already tried, or the
       one failed item's words are the whole command (an under-split) — the
       MODEL is asked for X1' (`rewrite_with_model`), with everything that was
       tried so far and what the judge said about each attempt. Its answer
       goes through the same grounding guard and fails closed.

    None is returned — rather than a guess — when nothing earns a rewrite,
    when the model is down or refuses, when its lines use words the speaker
    never said, or when it hands back a string already tried. The orchestrator
    reads None as "stop": commit what passed, say what did not.
    """
    if not F.rewritable(state.findings):
        return None
    tried = _tried(state)
    # An UNSPLIT subject is one object whose words hold two asks. A trim of
    # those words is one ask with the other half dropped — measured: "Remind
    # me to take out the trash. Also" trimmed to "Remind me to take out the
    # trash", the recurrence and the milk gone, and the loop called it fixed.
    # No deterministic construction can split it, so it goes to the model.
    if any(f.type == F.UNSPLIT_SUBJECT for f in F.rewritable(state.findings)):
        return rewrite_with_model(state, cfg, tried)
    candidate = failed_asks(state)
    if candidate and candidate.casefold() not in tried:
        # The guard is near-tautological here — the words come from the items,
        # which came from the command — and it stays because "near" is not
        # "always": `decompose_validate` may repair an item's text, and a
        # repair that invents a word must not reach segmentation unnoticed.
        if not grounded(candidate, state.raw_text):
            state.add_fix("llmjudge", "rewrite_rejected", candidate[:60], "",
                          note="the rewrite used words the speaker never said")
            return None
        _record(state, candidate, "rewrite")
        return candidate
    return rewrite_with_model(state, cfg, tried)


def _tried(state) -> "set[str]":
    """Every string segmentation has already been given for this command."""
    out = {(state.raw_text or "").casefold().strip(), (state.text or "").casefold().strip()}
    for fx in getattr(state, "fixes", []) or []:
        if fx.stage == "llmjudge" and fx.rule in ("rewrite", "rewrite_model"):
            out.add((fx.after or "").casefold().strip())
    out.discard("")
    return out


def _record(state, candidate: str, how: str) -> None:
    """The attempt ledger, kept on the state's own fix list: `before` is the
    string that was tried and failed, `note` is what it produced and what the
    judge said, `after` is what goes in next. The model round reads this back
    as WHAT WAS TRIED, so it never repeats an attempt and knows what to fix."""
    state.add_fix("llmjudge", how, before=state.text or "", after=candidate,
                  note=_outcome(state))


def _outcome(state) -> str:
    """What the current text produced, and what the judge said about it."""
    made = []
    for it in state.items:
        if it.intent is None or not it.action:
            continue
        made.append(f"{it.kind} “{_title_of(it)}”" + (f" ({it.time})" if it.time else ""))
    said = "; ".join(f.detail for f in state.findings) or "nothing wrong"
    return "produced: " + ("; ".join(made) or "nothing") + " · judge: " + said


def _title_of(item) -> str:
    intent = item.intent
    t = getattr(intent, "title", None)
    if not t:
        ts = getattr(intent, "titles", None)
        t = ", ".join(ts) if ts else None
    return (t or item.text or "").strip()


def rewrite_with_model(state, cfg, tried: "set[str]") -> "str | None":
    """Rounds where the deterministic rewrite has nothing new: the MODEL
    writes X1' as a LIST of asks, and code joins them.

    Three things learned from the 2026-09-10 measurement, where a model
    repair was the worst of five constructions (41 recovered, 13 leaks, 10
    empties on 60 rows), and each is built in rather than asked for:

    * the finished asks are CUT OUT in code (`residue`) and listed as done,
      so they cannot leak back — the model never rebuilds the whole command;
    * the answer is a list, and the seams are put in by code: several asks
      become the ingest ENVELOPE `("a")and("b")`, which segmentation opens
      before it reads any language, so the cut the model chose is the cut
      that happens. A single ask goes in bare;
    * every line is grounded on the transcript by the same guard, and the
      whole answer is refused if one line invents a word. Fails closed.

    The prompt carries the earlier attempts and the judge's complaint about
    each (Gil, 2026-09-20: *"what we already tried is given dynamically as
    context so the model knows what it's trying to fix"*).
    """
    from assistant.engine import llm as _llm
    from assistant.exceptions import AssistantError

    raw = state.raw_text or ""
    user = model_brief(state)
    try:
        out, ms = _llm.call_json(cfg, _REWRITE_SYSTEM, user, _REWRITE_SCHEMA)
    except AssistantError:
        return None                       # the model is down: no rewrite, no loop
    except (ValueError, TypeError):
        return None                       # not the JSON asked for
    asks = [_clean_ask(a) for a in (out.get("asks") or []) if isinstance(a, str)]
    asks = [a for a in asks if a and not _repeats_done(a, state)]
    _trace_model(state, cfg, ms, asks)
    if not asks:
        state.add_fix("llmjudge", "rewrite_empty", (state.text or "")[:60], "",
                      note="the model found no ask to write from the words")
        return None
    bad = [a for a in asks if not grounded(a, raw)]
    if bad:
        state.add_fix("llmjudge", "rewrite_rejected", "; ".join(bad)[:60], "",
                      note="the model's rewrite used words the speaker never said")
        return None
    candidate = asks[0] if len(asks) == 1 else "and".join(f'("{a}")' for a in asks)
    if candidate.casefold() in tried:
        return None                       # the same string cannot get a new answer
    _record(state, candidate, "rewrite_model")
    return candidate


def _repeats_done(ask: str, state) -> bool:
    """A line whose every content word is in a FINISHED ask is that ask again.
    The prompt says never to write those; an 8B does anyway, and a repeat
    re-enters segmentation beside the frozen original and is built TWICE
    (dev-100, 2026-09-20: 'make next week's to-do list' committed two times).
    Dropped in code, by construction, the way the trim is."""
    blamed = {f.item_id for f in F.rewritable(state.findings) if f.item_id}
    words = set(_content_words(ask))
    if not words:
        return False
    for it in state.items:
        if it.intent is None or not it.action or it.blocked or it.id in blamed:
            continue
        have = set(_content_words(it.spoken() or "")) | set(_content_words(_title_of(it)))
        if words <= have:
            return True
    return False


def model_brief(state) -> str:
    """The user message: the words, the leftover, what is done, what was
    tried. Built fresh each round from the state, never from a template of
    the previous prompt."""
    blamed = {f.item_id for f in F.rewritable(state.findings) if f.item_id}
    done = []
    for it in state.items:
        if it.intent is None or not it.action or it.blocked or it.id in blamed:
            continue
        done.append(f"- {it.kind} “{_title_of(it)}”" + (f" ({it.time})" if it.time else ""))
    # The failed items' own words first. `residue` cuts finished asks out of
    # the RAW transcript by their source span, and an ask frozen in a later
    # round has a span of X1', not of the transcript — so it stayed in the
    # residue, the model wrote it again, and it was built twice.
    left = failed_asks(state) or residue(state) or (state.text or "")
    attempts = [(fx.before, fx.note) for fx in getattr(state, "fixes", []) or []
                if fx.stage == "llmjudge" and fx.rule in ("rewrite", "rewrite_model")]
    attempts.append((state.text or "", _outcome(state)))
    lines = [f'THE SPEAKER SAID: "{state.raw_text or ""}"', "",
             f'STILL TO DO: "{left}"', "",
             "ALREADY DONE (never write these again):"]
    lines += done or ["- nothing yet"]
    lines += ["", "WHAT WAS TRIED, IN ORDER, AND WHAT THE JUDGE SAID:"]
    for n, (text, note) in enumerate(attempts, 1):
        lines.append(f'{n}. "{text}" → {note}')
    lines += ["", 'Write the asks still to do: {"asks": [...]}']
    return "\n".join(lines)


def _clean_ask(a: str) -> str:
    """One line, no quotes or brackets — the envelope is built from these."""
    a = re.sub(r"[\"“”()\[\]]", " ", a or "")
    return _tidy(a)


def _trace_model(state, cfg, ms: int, asks: list) -> None:
    from assistant.trace import LLM
    try:
        state.llm_ms += ms
    except AttributeError:
        pass
    if state.trace:
        engine = getattr(cfg, "llm_engine", "llm")
        model = getattr(getattr(cfg, engine, None), "model", "")
        state.trace.step(LLM, "Rewrite by the model",
                         f"{engine}:{model} · {ms} ms · {len(asks)} ask(s): "
                         + " | ".join(a[:40] for a in asks))
