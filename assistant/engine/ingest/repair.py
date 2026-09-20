"""Step 1 — transcript repair.

Contract (see DOCUMENTATION/ENGINE.md):
  reads   state.raw_text, state.source, state.supports_edit
  writes  state.text, state.corrections, state.needs_edit, state.ignored,
          trace steps (VOCAB)

The stage owns everything between "what Whisper wrote" and "words worth
parsing": trailing stop keywords go, false starts are declared trivial (and
never remembered — recording one teaches the model junk is normal), the
personal vocabulary repairs what it is confident about, and what it is *not*
confident about is surfaced — as `needs_edit` when the client can show an
editor and the setting asks for one, as advisory `uncertain_words` otherwise.
"""

from __future__ import annotations

import re

from assistant.engine.state import EngineState

# ---------------------------------------------------------------------------
# Stop keywords ("execute", "done" …) end a recording; they are not content.
# These lived in pipeline.py while the GUI parsed for itself; the engine owns
# them now and the GUI imports from here.
# ---------------------------------------------------------------------------

# Longest first so "set events" beats "set event".
_BUILTIN_STOP_PATTERNS = [
    r"\bset\s+events?\b",
    r"\bexecute\b",
    r"\bxq\b",        # STT mishearing of "execute"
    r"\bdone\b",
    r"\bstop\b",
    r"\bsubmit\b",
    r"\bconfirm\b",
    r"\bthat'?s?\s+it\b",
    r"\bok\s+go\b",
]


def build_stop_re(extra_phrases: "list[str] | None" = None) -> "re.Pattern[str]":
    """Stop-keyword regex from built-ins plus user-configured phrases."""
    patterns = list(_BUILTIN_STOP_PATTERNS)
    for phrase in (extra_phrases or []):
        phrase = phrase.strip()
        if not phrase:
            continue
        escaped = r"\s+".join(re.escape(w) for w in phrase.split())
        patterns.append(r"\b" + escaped + r"\b")
    combined = r"[\s,.!?]*(?:" + "|".join(patterns) + r")[\s,.!?]*$"
    return re.compile(combined, re.IGNORECASE)


_STOP_RE = build_stop_re()


def _peel_stop_keywords(transcript: str, extra_phrases: "list[str] | None" = None) -> str:
    """Every trailing stop keyword off, not just the last one.

    The regex is anchored at the end, so one pass removes one keyword: "add
    milk, done, execute" came out as "add milk, done" and the parser was left
    to make sense of a title ending in "done". Peeling until nothing more
    matches is also what makes the stop-word-only case visible — "that's it"
    and "set events" reduce to nothing at all, which is the signal the engine's
    front door reads (`is_ignorable`).
    """
    stop_re = build_stop_re(extra_phrases) if extra_phrases else _STOP_RE
    cur = (transcript or "").strip()
    prev = None
    while cur != prev:
        prev = cur
        cur = stop_re.sub("", cur).strip()
    return cur


def strip_stop_keyword(transcript: str, extra_phrases: "list[str] | None" = None) -> str:
    """Remove trailing stop keywords from the transcript.

    Falls back to the original when that leaves nothing: the words were ALL
    stop words, and an empty string downstream is less informative than what
    was actually said. `is_ignorable` is the check that catches that case.
    """
    cleaned = _peel_stop_keywords(transcript, extra_phrases)
    return cleaned if cleaned else transcript


def is_ignorable(raw_text: str, extra_phrases: "list[str] | None" = None) -> bool:
    """Nothing to act on — the cheapest read there is, and the first one taken.

    Three shapes of non-command reach the brain: silence that transcribed to
    nothing, a recording that is only the word that ended it ("execute"), and
    a false start. All three used to be found by `run()` — i.e. AFTER the
    engine had queued behind whatever command was already running and loaded
    the config. The engine's front door calls this first instead, so an empty
    transcript costs microseconds and never waits on the run lock.

    `run()` keeps its own check: this one is deliberately built-in-stop-words
    only (it is called before any config is read), so a user's custom stop
    phrase is caught one step later rather than not at all.
    """
    if not (raw_text or "").strip():
        return True
    return is_trivial_transcript(_peel_stop_keywords(raw_text, extra_phrases))


# ---------------------------------------------------------------------------
# False starts. Four of these were once parsed, executed and remembered as
# real commands ("Execute.", "No.", "I need a b-"), teaching the model that
# junk is normal. Trivial means: not parsed, not executed, not remembered.
# ---------------------------------------------------------------------------

_FILLER = frozenset({
    "a", "an", "the", "um", "uh", "er", "hmm", "ok", "okay", "yes", "yeah",
    "no", "nope", "yep", "so", "and", "but", "well", "just", "please",
})


def is_trivial_transcript(text: str) -> bool:
    """True when there is nothing here to act on."""
    words = [w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w]
    if not words:
        return True
    meaningful = [w for w in words if w not in _FILLER and len(w) > 1]
    # One meaningful word is an instruction only if it names something to do,
    # and by this point the stop words are already gone — so it does not.
    return len(meaningful) < 2


def run(state: EngineState, cfg) -> EngineState:
    from assistant.stt.vocab import apply_vocab, get_vocab
    from assistant.trace import VOCAB, DONE

    # Peeled, not merely stripped — and the peeled value is what decides
    # whether this is a command at all. "that's it" and "set events" are stop
    # keywords that happen to be two words each, so the old
    # strip-then-fall-back-to-the-original left two "meaningful" words on the
    # state and the whole chain ran on a transcript that said nothing.
    bare = _peel_stop_keywords(state.raw_text, cfg.audio.stop_phrases)
    text = bare or state.raw_text
    # Spoken noise comes off HERE, once, so everything downstream is generic
    # (Gil's architecture call): the "mhmm"/"umm" openers, the courtesy
    # wrapper, a trailing "or something", a mid-sentence self-correction.
    # This used to live inside FastRule's own normalisation, so the DEEP
    # track never got it — and real-usage review showed the LLM path failing
    # 5 of 5 on rambling dictation that opened with exactly these words.
    # Courtesy is left ON here: FastRule's interrogative gate reads the raw
    # words to tell a question from a polite imperative.
    from assistant.intent.cleanup import strip_spoken_noise
    text = strip_spoken_noise(text, drop_courtesy=False)

    if not bare or is_trivial_transcript(text):
        state.ignored = True
        state.text = text
        state.parse_path = "ignored"
        if state.trace:
            state.trace.step(DONE, "Nothing to do",
                             "Heard a stop word or a false start, nothing to act on.")
        return state

    text, vocab_fixes = apply_vocab(text, source=state.source)
    state.text = text
    state.corrections = [c.to_dict() for c in vocab_fixes]

    # Words the vocabulary is *not* sure about. With a capable client and the
    # setting on, these gate execution behind a "please edit the transcription"
    # round-trip; otherwise they ride along as advisory `uncertain_words`, the
    # existing tap-a-word affordance.
    doubtful: list = []
    try:
        doubtful = get_vocab().suggestions(text)
    except Exception:
        doubtful = []
    confirm = bool(getattr(getattr(cfg, "engine", None), "confirm_transcript", False))
    if doubtful and confirm and state.supports_edit:
        state.needs_edit = list(doubtful)

    if state.trace:
        state.trace.step(
            VOCAB, "Vocabulary",
            ("Fixed " + ", ".join(f"{c.original}→{c.replacement}" for c in vocab_fixes))
            if vocab_fixes else "No corrections needed",
            transcript=text, corrections=state.corrections or None,
        )
    return state


def uncertain_words(text: str) -> list:
    """Advisory low-confidence words for the client's tap-a-word UI."""
    try:
        from assistant.stt.vocab import get_vocab
        return get_vocab().suggestions(text)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Learning from the needs_edit round-trip — so the gate fires LESS over time.
# The endpoint calls these before re-running the corrected transcript; they
# are stage-1 public API (like validate's readers), not part of run().
# ---------------------------------------------------------------------------

def _confirms_path() -> str:
    """Confirmation counters live BESIDE the vocabulary, never inside it —
    vocab.json is hand-curated and junk written there degrades the assistant."""
    import os
    from assistant.stt.vocab import VOCAB_PATH
    return os.path.join(os.path.dirname(VOCAB_PATH), "transcript_confirms.json")


CONFIRMS_TO_WHITELIST = 2


def learn_from_edit(original: str, edited: str, source: str = "test") -> list:
    """The user's saved edit is a correction they already typed out: each word
    they replaced becomes a vocab alias (misheard → meant), so the same
    mishearing auto-corrects next time and the gate stays quiet. Returns the
    (wrong, right) pairs learned."""
    import difflib

    from assistant.stt.vocab import get_vocab

    o_words = original.split()
    e_words = edited.split()
    pairs: list = []
    sm = difflib.SequenceMatcher(None, [w.lower() for w in o_words],
                                 [w.lower() for w in e_words])
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        # A PHRASE, when either side is more than one word. This is the shape
        # boundary damage actually takes — Whisper does not keep a term's word
        # boundaries when it mishears it, so "poker night" comes back as
        # "pokernight" (1 word for 2) or "poe konaight" (2 for 2, but neither
        # word is right). Both were being thrown away or, worse, learned as
        # separate word aliases: "konaight" -> "night" hangs a nonsense alias
        # on a common English word, where it can fire on anything.
        #
        # Learned as ONE term with ONE alias, so the next occurrence is an
        # exact hit rather than another guess — and it is learned from the
        # only source that can know it, the speaker correcting it. Deriving
        # phrases from past transcripts was tried and measured first: it
        # cannot reach a term that is ALWAYS misheard, because such a term
        # never appears correctly in the history to be derived from
        # (DEVQA.md, 2026-09-19).
        span_o = (i2 - i1) > 1 or (j2 - j1) > 1
        if span_o:
            wrong = " ".join(o_words[i1:i2]).strip(".,!?;:")
            right = " ".join(e_words[j1:j2]).strip(".,!?;:")
            # A whole clause is not a term. Four words either side is already
            # generous for a name, a place or a piece of shorthand.
            if (wrong and right and wrong.lower() != right.lower()
                    and (i2 - i1) <= 4 and (j2 - j1) <= 4):
                try:
                    get_vocab().add_alias(wrong, right)
                    pairs.append((wrong, right))
                except Exception:
                    pass
            continue
        if (i2 - i1) != (j2 - j1):
            continue                      # only clean word-for-word swaps teach
        for wrong, right in zip(o_words[i1:i2], e_words[j1:j2]):
            wrong = wrong.strip(".,!?;:")
            right = right.strip(".,!?;:")
            if not wrong or not right or wrong.lower() == right.lower():
                continue
            try:
                # add_alias creates `right` as a vocab word when it is new.
                get_vocab().add_alias(wrong, right)
                pairs.append((wrong, right))
            except Exception:
                continue
    return pairs


def confirm_unchanged(text: str) -> list:
    """The user looked and sent the words back untouched: each doubted word
    earns a confirmation, and at CONFIRMS_TO_WHITELIST it joins the vocabulary
    as itself — the gate never asks about it again. Returns words whitelisted
    this time."""
    import json
    import os

    from assistant.stt.vocab import get_vocab

    try:
        doubted = [s.get("heard") for s in get_vocab().suggestions(text) if s.get("heard")]
    except Exception:
        return []
    if not doubted:
        return []
    path = _confirms_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            counts = json.load(f)
    except Exception:
        counts = {}
    promoted = []
    for word in doubted:
        key = word.lower()
        counts[key] = int(counts.get(key, 0)) + 1
        if counts[key] >= CONFIRMS_TO_WHITELIST:
            try:
                get_vocab().add_word(word)
                promoted.append(word)
            except Exception:
                continue
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(counts, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        pass
    return promoted
