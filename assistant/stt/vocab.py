"""Personal vocabulary — teaches the STT layer your names and non-English words.

Two mechanisms, both driven by one shared store (~/.assistant_tools/vocab.json):

1. **Whisper biasing** — every vocab word is fed to faster-whisper as
   ``initial_prompt`` so the decoder is nudged towards spelling them correctly
   in the first place (works surprisingly well for names like "Kyra", "Shaul").

2. **Post-transcription auto-correct** — each transcript is scanned for tokens
   that are (a) a known *alias* of a vocab word (something Whisper previously
   produced and you corrected), or (b) fuzzy-similar to a vocab word above a
   threshold. Matches are replaced and the misheard form is remembered as a
   new alias so it becomes an exact hit next time — the system learns.

The store is a JSON file rather than the SQLite DB so the Mac app process and
the iOS API process can both read/write it without schema coordination.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# MACALENDAR_VOCAB lets tests/audits point at a scratch file, the same way
# MACALENDAR_DB and MACALENDAR_MEMORY_DB do — without it, anything that
# exercised the pipeline wrote into the user's real personal vocabulary.
VOCAB_PATH = os.environ.get("MACALENDAR_VOCAB") or os.path.expanduser("~/.assistant_tools/vocab.json")

DEFAULT_THRESHOLD = 0.80   # difflib ratio; 1.0 = identical
MIN_FUZZY_LEN = 3          # never fuzzy-match tokens shorter than this
#: How far a phonetic match may fall below the user's own similarity setting.
#:
#: Expressed as a relaxation of `threshold` rather than as a fixed number, so
#: it follows whatever strictness this user has chosen instead of a value
#: fitted to one person's mistakes. Someone who tightens the dial tightens the
#: phonetic path with it.
#:
#: The size is set by what phonetic identity is worth as evidence, not by a
#: sample: two words with the same sound code, the same syllable count, and no
#: other word in the list sharing that code are nearly certainly the same word,
#: so the spelling barely has to agree — but it cannot be ignored entirely, or
#: any two words in a bucket would be interchangeable.
PHONETIC_RELAXATION = 0.25
RECENT_LIMIT = 20          # transcripts kept for the "fix a word" UI

# Very common English words that must never be fuzzy-replaced by a vocab word
# (e.g. vocab "Kyra" vs transcript "data"). Exact alias hits still win.
_PROTECTED = {
    "the", "and", "for", "from", "with", "that", "this", "then", "than", "them",
    "there", "their", "they", "have", "has", "had", "was", "were", "will", "what",
    "when", "where", "who", "why", "how", "data", "date", "day", "days", "time",
    "today", "tomorrow", "week", "month", "year", "meeting", "event", "task",
    "todo", "add", "set", "make", "create", "delete", "remove", "move", "change",
    "morning", "noon", "afternoon", "evening", "night", "next", "last", "every",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "one", "two", "three", "four",
    "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "half",
    "quarter", "past", "till", "until", "before", "after", "about", "around",
    "execute", "done", "stop", "go", "submit", "confirm", "please", "walk", "call",
    "with", "into", "onto", "over", "under", "also", "some", "more", "note",
}


_ENGLISH: set[str] | None = None


#: Where a system word list lives. macOS ships `words`; a Debian/Ubuntu box has
#: it only once `wamerican` (or `wbritish`) is installed, and then usually as a
#: symlink to the language-specific file — so both are tried.
_DICT_PATHS = ("/usr/share/dict/words",
               "/usr/share/dict/american-english",
               "/usr/share/dict/british-english",
               "/usr/dict/words")


def _english() -> set[str]:
    """System dictionary — a fuzzy match must never rewrite a real English word.

    An EMPTY result turns that guard off completely: every real English word
    becomes eligible for replacement by a vocabulary entry that merely sounds
    like it, so "a shawl for Tal" comes back "a Shaul for Tal". That is the
    whole failure this list exists to prevent, and it used to happen SILENTLY
    on any machine without the file — which is every stock Linux box and every
    CI runner. It is still degraded there, because nothing may be downloaded
    (CLAUDE.md), but it now says so once instead of never.
    """
    global _ENGLISH
    if _ENGLISH is None:
        for path in _DICT_PATHS:
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    _ENGLISH = {w.strip().lower() for w in f if w.strip()}
                break
            except OSError:
                continue
        if not _ENGLISH:
            _ENGLISH = set()
            logger.warning(
                "No system word list (tried %s). The guard that stops a "
                "phonetic match rewriting a real English word is OFF — install "
                "`wamerican` (Debian/Ubuntu) to restore it.",
                ", ".join(_DICT_PATHS))
    return _ENGLISH


def _norm(s: str) -> str:
    """Lowercase, strip punctuation/diacritics-ish noise for comparison."""
    return re.sub(r"[^a-z0-9֐-׿' ]+", "", s.lower()).strip()


def _flat(s: str) -> str:
    """Letters and digits only — no spaces, no apostrophes.

    The comparison basis for every path below. Whisper does not keep a phrase's
    word boundaries when it mishears it, so the spaces are part of the damage,
    not part of the evidence: "quin oh a delivery" against "quinoa delivery" is
    three spurious spaces and one letter, and comparing them spaced makes the
    pair look nothing alike (and fails the length guard outright).
    """
    return re.sub(r"[^a-z0-9֐-׿]", "", s.lower())


#: Crude de-inflection: enough to recognise that a plural is a real word.
_SUFFIXES = ("s", "es", "'s", "ed", "d", "ing", "ly", "er", "ers", "es'")


def _base_forms(flat: str) -> set:
    out = set()
    for suf in _SUFFIXES:
        if flat.endswith(suf) and len(flat) - len(suf) >= 3:
            stem = flat[: -len(suf)]
            out.add(stem)
            out.add(stem + "e")            # "plans"/"planes", "tasting"/"taste"
            if len(stem) > 3 and stem[-1] == stem[-2]:
                out.add(stem[:-1])         # "planning" -> "plan"
            if stem.endswith("i"):
                out.add(stem[:-1] + "y")   # "groceries" -> "grocery"
    return out


def _edge_needed(flats: "list[str]", flat_t: str, dmg: "tuple[bool, ...]",
                 score: float) -> bool:
    """Is every UNDAMAGED word at the window's edge actually needed?

    The damage gate says a window has something broken in it; it does not say
    the window STOPS at the break. "pilates session on" has "pilates" in no
    dictionary, so the gate lets a three-token window through — and it matched
    `pilates session` at 0.93, swallowing an "on" the speaker said and meant.

    A wrong merge always grows by absorbing a NEIGHBOUR, and a neighbour is at
    an edge, so that is where the test belongs: drop the edge word and score
    again. If the match is no worse without it, the word was not part of the
    misheard phrase and the narrower window — which is tried next — should have
    it instead. This is the other half of Gil's ordering rule: run the wider
    window first, but never let it keep a word the narrower one explains just
    as well.

    Interior words are deliberately exempt. A mishearing splits an unknown word
    into pieces that are often ordinary words — "quin OH a delivery", "fell
    AWFUL run", "bar RISTA course" — and repairing those is the whole point.
    """
    if len(flats) < 2:
        return True
    for idx in (0, len(flats) - 1):
        if not flats[idx]:
            continue
        sub = "".join(flats[:idx] + flats[idx + 1:]) if idx else "".join(flats[1:])
        if len(sub) < MIN_FUZZY_LEN:
            continue
        without = difflib.SequenceMatcher(None, sub, flat_t).ratio()
        # An undamaged edge loses ties: if the narrower window is just as good,
        # the word was context. A damaged edge is given the benefit of the
        # doubt and only dropped when leaving it out is strictly BETTER —
        # which is how "espresso tasting xq" stopped eating the "xq".
        if without >= score if not dmg[idx] else without > score:
            return False
    return True


@dataclass
class _Pre:
    """Everything about one entry that does not change as the window slides."""
    entry: Any
    n: int
    target: str
    flat_target: str
    key: str
    full_key: str
    aliases: frozenset
    flat_aliases: frozenset
    alias_lens: frozenset
    onset: str
    tlen: int
    thr: float


@dataclass
class _Ctx:
    """What every window match needs to know about the whole word list."""
    pre: list
    english: set
    vocab_keys: set
    vocab_flat: set
    alone: dict


def phonetic_key(word: str) -> str:
    """A code for how a word sounds, so mishearings can be matched at all.

    Speech recognition fails phonetically and `difflib` compares letters, so
    the two are blind to each other in exactly the case that matters most:

        heard "bugroot", meant "Bagrut"   -> 0.62 by letters, needs 0.90
        heard "makabi",  meant "Maccabi"  -> 0.77
        heard "ofeer",    meant "Ofir"     -> 0.75

    Every one of those targets was already in the word list. None was reachable,
    so none was corrected, so the alias was never learned and the same command
    failed identically the next day. Lowering the letter threshold is not the
    answer — that is what rewrote correct names to wrong ones before.

    This is Soundex: keep the first letter, code the consonants by where they
    are made in the mouth, drop the vowels. Words that sound alike collide;
    words that merely look alike do not. Non-Latin script returns "" and is
    never matched, since the coding table means nothing for it.
    """
    letters = [c for c in word.upper() if "A" <= c <= "Z"]
    if not letters:
        return ""                       # Hebrew script, digits, punctuation
    codes = {"B": "1", "F": "1", "P": "1", "V": "1",
             "C": "2", "G": "2", "J": "2", "K": "2",
             "Q": "2", "S": "2", "X": "2", "Z": "2",
             "D": "3", "T": "3",
             "L": "4",
             "M": "5", "N": "5",
             "R": "6"}
    out = letters[0]
    previous = codes.get(letters[0], "")
    for ch in letters[1:]:
        code = codes.get(ch, "")
        if code and code != previous:
            out += code
        # H and W are transparent: they do not separate two like consonants.
        if ch not in ("H", "W"):
            previous = code
    return (out + "000")[:4]


def phonetic_full(word: str) -> str:
    """`phonetic_key` without the truncation — a code as long as the word.

    Soundex stops after three consonant codes because it was built to bucket
    SURNAMES on an index card. Over a phrase that is not a code, it is a prefix:
    every string beginning "water…" that has a T and an R in it lands on W364,
    so "water the plants to" and "water Dana's plants" are phonetically
    identical to it. That is not a flaw the old `n == 1` gate hid, it is the
    reason the gate was needed: with the window widened and this test still
    truncated, it made 14 wrong phonetic rewrites over 1,200 fastrule rows
    (before the damage gate learned about plurals, which now stops the same
    ones earlier — so this guard is a belt behind that brace).

    Keeping every code digit makes the test length-proportional, so a longer
    phrase has to agree in more places rather than fewer.
    """
    letters = [c for c in word.upper() if "A" <= c <= "Z"]
    if not letters:
        return ""
    codes = {"B": "1", "F": "1", "P": "1", "V": "1",
             "C": "2", "G": "2", "J": "2", "K": "2",
             "Q": "2", "S": "2", "X": "2", "Z": "2",
             "D": "3", "T": "3", "L": "4", "M": "5", "N": "5", "R": "6"}
    out = letters[0]
    previous = codes.get(letters[0], "")
    for ch in letters[1:]:
        code = codes.get(ch, "")
        if code and code != previous:
            out += code
        if ch not in ("H", "W"):
            previous = code
    return out


def _vowel_groups(word: str) -> int:
    """Roughly the syllable count — the structure Soundex throws away.

    Soundex codes consonants and discards vowels entirely, which is what lets
    "pasta" and "pset" share a code: P-S-T either way. They do not sound alike
    at all, and the difference is exactly the vowels. Requiring the same number
    of vowel runs puts back enough of that structure to tell them apart, while
    still ignoring *which* vowels they are — which is the whole point, since a
    mishearing changes vowel quality constantly ("bagrut" heard as "bugroot").
    """
    return len(re.findall(r"[aeiouy]+", word.lower()))


def _best_by_letters(window: str, candidates: list[str]) -> str:
    """Of several words that sound alike, the one spelled most like this."""
    return max(candidates,
               key=lambda w: difflib.SequenceMatcher(None, window, _norm(w)).ratio())


@dataclass
class VocabEntry:
    """A word this user says that English does not know.

    Three things can be true of such a word, and they are deliberately
    separate because they behave differently:

    `aliases` fix a mishearing. "hexagon" was never what you said, so the
    transcript is rewritten and nothing is lost.

    `expands_to` is shorthand. "MT" *is* what you said and meant, so it is
    never substituted into your text — expanding it would edit your words
    rather than correct them. It is context: what the acronym means, for
    labelling, for search, and for telling the model.

    `label` is what the word implies about a task or event. "Haxaga" is a
    course, so a task mentioning it is Coursework. This is the field that was
    missing: the vocabulary already knew Haxaga and Malag were your words, and
    the tagger could not use that, so both systems learned about the same 374
    words separately.
    """

    word: str
    aliases: list[str] = field(default_factory=list)
    hits: int = 0
    added: float = field(default_factory=time.time)
    expands_to: str = ""
    label: str = ""

    @property
    def is_acronym(self) -> bool:
        return bool(self.expands_to)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"word": self.word, "aliases": self.aliases,
                             "hits": self.hits, "added": self.added}
        # Written only when set, so 374 existing entries keep the shape they
        # have and a hand-edited vocab.json does not grow empty fields.
        if self.expands_to:
            d["expands_to"] = self.expands_to
        if self.label:
            d["label"] = self.label
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VocabEntry":
        return cls(
            word=str(d.get("word", "")).strip(),
            aliases=[str(a) for a in d.get("aliases", []) if str(a).strip()],
            hits=int(d.get("hits", 0)),
            added=float(d.get("added", time.time())),
            expands_to=str(d.get("expands_to", "") or "").strip(),
            label=str(d.get("label", "") or "").strip(),
        )


@dataclass
class Correction:
    original: str
    replacement: str
    reason: str  # "alias" | "fuzzy"
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {"from": self.original, "to": self.replacement, "reason": self.reason,
                "score": round(self.score, 3)}


class VocabStore:
    """Thread-safe, file-backed vocabulary. Reloads if the file changes on disk."""

    def __init__(self, path: "str | None" = None) -> None:
        # RESOLVED AT CALL TIME, not bound as a default. `VOCAB_PATH` is read
        # from the environment at IMPORT, so a default argument freezes
        # whatever `MACALENDAR_VOCAB` said then — and a test that sets it
        # afterwards gets the frozen one. Every store in the suite then shared
        # ONE file, so a test asserting "an empty vocabulary changes nothing"
        # was handed the previous test's words and passed or failed by
        # accident. The identical mistake was fixed in `intent/lexicon.py` on
        # 2026-09-18; this is its twin.
        self._path = path or os.environ.get("MACALENDAR_VOCAB") or VOCAB_PATH
        self._lock = threading.RLock()
        self._entries: list[VocabEntry] = []
        #: word-sound index, rebuilt lazily; None means "stale"
        self._phonetic_cache: "dict[str, list[str]] | None" = None
        self._recent: list[dict[str, Any]] = []
        self.auto_correct: bool = True
        self.learn_aliases: bool = True
        self.threshold: float = DEFAULT_THRESHOLD
        self.onboarded: bool = False
        self._mtime: float = -1.0
        self._load()

    # ---------------------------------------------------------------- I/O

    def _load(self) -> None:
        with self._lock:
            try:
                mtime = os.path.getmtime(self._path)
            except OSError:
                self._entries, self._recent, self._mtime = [], [], -1.0
                return
            if mtime == self._mtime:
                return
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:  # corrupt file — don't crash the assistant
                logger.warning("Vocab file unreadable (%s); starting empty", e)
                data = {}
            self._entries = [VocabEntry.from_dict(d) for d in data.get("entries", [])]
            self._entries = [e for e in self._entries if e.word]
            self._phonetic_cache = None      # the word list just changed
            self._recent = list(data.get("recent", []))[-RECENT_LIMIT:]
            self.auto_correct = bool(data.get("auto_correct", True))
            self.learn_aliases = bool(data.get("learn_aliases", True))
            self.threshold = float(data.get("threshold", DEFAULT_THRESHOLD))
            self.onboarded = bool(data.get("onboarded", False))
            self._mtime = mtime

    def _save(self) -> None:
        self._phonetic_cache = None      # a word was added, edited or removed
        with self._lock:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            data = {
                "auto_correct": self.auto_correct,
                "learn_aliases": self.learn_aliases,
                "threshold": self.threshold,
                "onboarded": self.onboarded,
                "entries": [e.to_dict() for e in self._entries],
                "recent": self._recent[-RECENT_LIMIT:],
            }
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
            try:
                self._mtime = os.path.getmtime(self._path)
            except OSError:
                pass

    def reload(self) -> None:
        self._load()

    # ---------------------------------------------------------- accessors

    @property
    def entries(self) -> list[VocabEntry]:
        self._load()
        with self._lock:
            return sorted(self._entries, key=lambda e: e.word.lower())

    @property
    def recent(self) -> list[dict[str, Any]]:
        self._load()
        with self._lock:
            return list(reversed(self._recent))

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_correct": self.auto_correct,
            "learn_aliases": self.learn_aliases,
            "threshold": self.threshold,
            "onboarded": self.onboarded,
            "words": [e.to_dict() for e in self.entries],
            "recent": self.recent,
        }

    def _find(self, word: str) -> VocabEntry | None:
        key = _norm(word)
        for e in self._entries:
            if _norm(e.word) == key:
                return e
        return None

    # ---------------------------------------------------------- mutators

    def add_word(
        self,
        word: str,
        aliases: list[str] | None = None,
        *,
        label: str = "",
        expands_to: str = "",
    ) -> VocabEntry:
        word = word.strip()
        if not word:
            raise ValueError("Word cannot be empty")
        self._load()
        with self._lock:
            entry = self._find(word)
            if entry is None:
                entry = VocabEntry(word=word)
                self._entries.append(entry)
            for a in aliases or []:
                self._add_alias_to(entry, a)
            # Only set when given, so re-adding an existing word to add an
            # alias does not blank a label it already carried.
            if label.strip():
                entry.label = label.strip()
            if expands_to.strip():
                entry.expands_to = expands_to.strip()
            self._save()
            return entry

    def update_word(
        self,
        word: str,
        *,
        label: "str | None" = None,
        expands_to: "str | None" = None,
        aliases: "list[str] | None" = None,
    ) -> "VocabEntry | None":
        """Edit an existing word. Returns None if there is no such word.

        Only the fields passed are touched, so a caller that knows about
        labels but not acronyms cannot wipe an acronym by omitting it. Passing
        an empty string clears a field — which is different from omitting it,
        and is how the settings screens offer "remove this label".

        `aliases`, when given, replaces the list outright: the editing screens
        show all of them at once, so a partial update would silently drop
        whatever the screen had not been told about.
        """
        self._load()
        with self._lock:
            entry = self._find(word)
            if entry is None:
                return None
            if label is not None:
                entry.label = label.strip()
            if expands_to is not None:
                entry.expands_to = expands_to.strip()
            if aliases is not None:
                entry.aliases = []
                for alias in aliases:
                    self._add_alias_to(entry, alias)
            self._save()
            return entry

    def _phonetic_bucket(self, key: str) -> list[str]:
        """Every known word that sounds like this one.

        Built once and cached, because it is consulted for every entry of every
        window of every command. Cleared whenever the word list changes.
        """
        if self._phonetic_cache is None:
            index: dict[str, list[str]] = {}
            for e in self._entries:
                k = phonetic_key(e.word)
                if k:
                    index.setdefault(k, []).append(e.word)
            self._phonetic_cache = index
        return self._phonetic_cache.get(key, [])

    def _add_alias_to(self, entry: VocabEntry, alias: str) -> bool:
        alias = alias.strip()
        if not alias or _norm(alias) == _norm(entry.word):
            return False
        if any(_norm(a) == _norm(alias) for a in entry.aliases):
            return False
        entry.aliases.append(alias)
        return True

    def add_alias(self, wrong: str, right: str) -> VocabEntry:
        """Record that STT heard ``wrong`` when you said ``right``.

        Creates ``right`` as a vocab word if it doesn't exist yet.
        """
        self._load()
        with self._lock:
            entry = self._find(right) or self.add_word(right)
            self._add_alias_to(entry, wrong)
            self._save()
            return entry

    def remove_word(self, word: str) -> bool:
        self._load()
        with self._lock:
            entry = self._find(word)
            if entry is None:
                return False
            self._entries.remove(entry)
            self._save()
            return True

    def remove_alias(self, word: str, alias: str) -> bool:
        self._load()
        with self._lock:
            entry = self._find(word)
            if entry is None:
                return False
            before = len(entry.aliases)
            entry.aliases = [a for a in entry.aliases if _norm(a) != _norm(alias)]
            if len(entry.aliases) != before:
                self._save()
                return True
            return False

    def update_settings(self, *, auto_correct: bool | None = None,
                        learn_aliases: bool | None = None,
                        threshold: float | None = None) -> None:
        self._load()
        with self._lock:
            if auto_correct is not None:
                self.auto_correct = bool(auto_correct)
            if learn_aliases is not None:
                self.learn_aliases = bool(learn_aliases)
            if threshold is not None:
                self.threshold = max(0.5, min(1.0, float(threshold)))
            self._save()

    def set_onboarded(self, value: bool) -> None:
        self._load()
        with self._lock:
            self.onboarded = bool(value)
            self._save()

    def record_recent(self, original: str, corrected: str,
                      corrections: list[Correction], source: str) -> None:
        """Remember a transcript so the UI can offer "tap a word to fix it"."""
        self._load()
        with self._lock:
            self._recent.append({
                "ts": time.time(),
                "source": source,
                "original": original,
                "corrected": corrected,
                "corrections": [c.to_dict() for c in corrections],
            })
            self._recent = self._recent[-RECENT_LIMIT:]
            self._save()

    # ---------------------------------------------------------- whisper

    def whisper_prompt(self, max_words: int = 60) -> str | None:
        """Comma-separated vocab for faster-whisper's ``initial_prompt``.

        Whisper treats the prompt as preceding text, so listing the words
        biases the decoder toward those spellings. Kept short — the prompt
        eats into the 448-token context window.
        """
        # Whisper's prompt window is small (~224 tokens): prefer words that have
        # actually needed correcting, then the most recently added.
        ranked = sorted(self.entries, key=lambda e: (-e.hits, -e.added))
        words = [e.word for e in ranked[:max_words]]
        if not words:
            return None
        return "Names and words: " + ", ".join(words) + "."

    # ---------------------------------------------------------- correct

    #: How far a window may stretch either side of the entry's own word count.
    #:
    #: A misheard phrase does not keep its word boundaries — "barista course"
    #: comes back as THREE tokens, "ice cream" as ONE — so a window fixed at the
    #: entry's length can only match a mishearing that happened to preserve the
    #: spacing, which is the one kind that barely needs repairing. Two either
    #: way covers every pair in the realspeech bench (worst case four tokens for
    #: a two-word entry) without letting the window wander off the phrase.
    WINDOW_SLACK = 2

    #: Ablation switches — every one of these is a guard, and the point of the
    #: prototype is to know what each one is worth. All six ON is the proposal;
    #: the ablation table is in the report that came with this change.
    ARM_DAMAGE_GATE = True    # a merged window must contain something broken
    ARM_DEFER_SINGLE = True   # Gil's rule: leave a lone repairable token to n == 1
    ARM_EDGE_ANCHOR = True    # an undamaged EDGE token must survive the rewrite
    ARM_FULL_CODE = True      # compare untruncated phonetic codes for phrases
    ARM_MORPH = True          # inflections count as real words, not as damage
    ARM_UNAMBIGUOUS = True    # a merge that fits two entries alike is refused
    ARM_TIE_BAND = 0.10       # how close a rival has to be to count as a tie

    def _is_damaged(self, token: str, english: set[str], vocab_flat: set[str]) -> bool:
        """Is this ONE token something that needs repairing at all?

        The damage gate. A window may only be MERGED into a vocabulary entry
        when at least one of its tokens is neither a real English word nor a
        word this user has taught the system — that is, when there is visible
        damage to repair. "set meeting for" is three real words, so nothing in
        it is broken and the widened window can never touch it, which is the
        regression the old `n == 1` gate was there to prevent. "bar rista
        course" carries "rista", which is in no list, so it is eligible.

        One-letter tokens are never damage: "quin oh a delivery" has an "a" in
        it, and a rule that called that broken would make every window with a
        stray article eligible.
        """
        flat = _flat(token)
        if len(flat) < 2:
            return False
        if token in english or flat in english:
            return False
        if self.ARM_MORPH and _base_forms(flat) & english:
            # The word list is /usr/share/dict/words, which on macOS is web2 —
            # a 1934 dictionary with no plurals in it. "plants" and "groceries"
            # are not in it, so without this the damage gate reads "water the
            # plants" as damaged and the widened window rewrites it (measured:
            # 16 of 1,200 fastrule rows). A gate whose word list is thin is a
            # gate that is quietly open, which is the failure `_english`'s own
            # docstring warns about one level up.
            return False
        return flat not in vocab_flat

    def _repairable_alone(self, token: str, ctx: "_Ctx") -> bool:
        """Would the SINGLE-WORD pass fix this token by itself?

        Gil, 2026-09-19: *"in cases where two sequential words, one is good and
        one is bad, then you don't combine because we want that n equals one to
        also work."* The wider window runs first, so without this the merge
        would eat a bigram whose damage is one token that the single-word path
        already handles — and the n == 1 repair would never be reached. So a
        window whose damage is confined to ONE token stands aside when that
        token is repairable on its own.
        """
        if token in ctx.alone:
            return ctx.alone[token]
        ok = False
        for pre in ctx.pre:
            if self._match_window(token, 1, pre, ctx, (True,), (token,))[0] is not None:
                ok = True
                break
        ctx.alone[token] = ok
        return ok

    def _match_window(self, window: str, m: int, pre: "_Pre", ctx: "_Ctx",
                      dmg: "tuple[bool, ...]", toks: "tuple[str, ...]") -> "tuple[str | None, float]":
        """Does this window of *m* tokens spell `pre.entry`'s word, badly?

        Everything is compared SPACE-STRIPPED, because the token count moves
        when a phrase is misheard and the spaces are exactly what moved:
        "quin oh a delivery" and "quinoa delivery" differ by three spaces and
        one letter, and only one of those is a mistake.
        """
        flat_w = _flat(window)
        # 1. ALIAS — a form this user has already corrected once. No gate: they
        #    said themselves that this is wrong.
        if window in pre.aliases or (flat_w and flat_w in pre.flat_aliases):
            return "alias", 1.0

        if m >= 2:
            # 2. THE DAMAGE GATE — nothing broken here, nothing to repair.
            #
            # ONLY ON A WIDENED WINDOW (m != pre.n). The gate exists to make
            # the NEW sizes safe; at the entry's own width this is the path
            # that already shipped, already measured, and gating it is a
            # REGRESSION — "poker knight" against a "poker night" entry is two
            # real English words, so the gate refused a repair the released
            # code performs. Caught end-to-end through the ingest stage, not by
            # the bench, because the bench's damaged forms are all non-words.
            if (self.ARM_DAMAGE_GATE and m != pre.n and not any(dmg)):
                return None, 0.0
            if (self.ARM_DEFER_SINGLE and sum(dmg) == 1
                    and self._repairable_alone(toks[dmg.index(True)], ctx)):
                return None, 0.0        # leave it to n == 1 (see above)
        elif window in ctx.english or flat_w in ctx.english:
            # A real English word is never rewritten by resemblance. This used
            # to be conditioned on the ENTRY being one word, which left
            # "airport" rewritable by an "air port" entry.
            return None, 0.0

        if (len(flat_w) < MIN_FUZZY_LEN or window in _PROTECTED
                or window in ctx.vocab_keys
                # ...another known word — but NOT this entry's own letters. The
                # spaced form could never collide with its own target (that is
                # skipped before we get here); the flattened one does, and while
                # it did, every respacing pair in the bench ("icecream",
                # "bookclub", "water Averysplants") was rejected as if it were
                # some other vocabulary word.
                or (flat_w != pre.flat_target and flat_w in ctx.vocab_flat)
                or abs(len(flat_w) - len(pre.flat_target)) > 2):
            return None, 0.0

        # 3. RESPACE — the same letters, cut in different places
        #    ("icecream", "bookclub", "water Averysplants").
        if flat_w == pre.flat_target:
            if m >= 2 and self.ARM_EDGE_ANCHOR and not _edge_needed(
                    [_flat(t) for t in toks], pre.flat_target, dmg, 1.0):
                return None, 0.0
            return "respace", 1.0

        score = difflib.SequenceMatcher(None, flat_w, pre.flat_target).ratio()
        if m >= 2 and self.ARM_EDGE_ANCHOR and not _edge_needed(
                [_flat(t) for t in toks], pre.flat_target, dmg, score):
            return None, 0.0
        if score >= pre.thr and flat_w[:1] == pre.flat_target[:1]:
            return "fuzzy", score
        # 4. PHONETIC — same sound code, same syllable count, unambiguous
        #    bucket. The `n == 1` hard gate is gone; the damage gate above and
        #    the flattened comparison replace it.
        if (score >= self.threshold - PHONETIC_RELAXATION
                and _vowel_groups(flat_w) == _vowel_groups(pre.flat_target)):
            key = phonetic_key(flat_w)
            # A phrase needs the untruncated code (see phonetic_full): four
            # characters is a prefix test, and over sixteen letters a prefix
            # test matches almost anything.
            if max(m, pre.n) > 1 and self.ARM_FULL_CODE:
                if phonetic_full(flat_w) != pre.full_key:
                    return None, 0.0
            if key and key == pre.key:
                rivals = self._phonetic_bucket(key)
                if len(rivals) == 1 or _best_by_letters(
                        flat_w, [_flat(_norm(r)) for r in rivals]) == pre.flat_target:
                    return "phonetic", score
        return None, 0.0

    def _unambiguous(self, window: str, m: int, pre: "_Pre", ctx: "_Ctx",
                     dmg, toks, score: float) -> bool:
        """Is this window one entry's word, or the shape of several of them?

        The phonetic path has always demanded an unambiguous bucket — "nothing
        else in the word list sounds the same, so there is nothing to confuse
        it with". A widened window needs the same standard on the LETTER path,
        because merging is where a vocabulary full of same-shaped phrases
        ("return Taylor's book", "return Robin's book", "return Quinn's book")
        turns one speaker's word into another's: the first entry in iteration
        order won, not the best one. Measured on the realspeech clean rows,
        that family was 20 wrong rewrites of 771 before this change.

        A near-tie is the evidence. If a second entry matches this window
        within `ARM_TIE_BAND`, what the window identifies is the TEMPLATE rather
        than the word.
        """
        flat_w = _flat(window)
        for other in ctx.pre:
            if other.entry is pre.entry or not other.flat_target:
                continue
            # Raw letter similarity, not "would this one also match": a rival
            # that fails a gate of its own is still a rival, and asking the
            # gates here made the test vacuous (measured: it refused nothing).
            if difflib.SequenceMatcher(None, flat_w, other.flat_target).ratio() \
                    >= score - self.ARM_TIE_BAND:
                return False
        return True

    def correct(self, transcript: str, *, learn: bool | None = None) -> tuple[str, list[Correction]]:
        """Apply alias + fuzzy + phonetic corrections. Returns (fixed, corrections).

        A vocab entry is matched against token windows AROUND its own word
        count, widest first, and only a window with actual damage in it may be
        merged. See `_is_damaged` and `_match_window`.
        """
        self._load()
        if not transcript or not self._entries:
            return transcript, []
        learn = self.learn_aliases if learn is None else learn

        # Tokenise keeping the original spans so we can rebuild the sentence.
        tokens = [(m.group(0), m.start(), m.end())
                  for m in re.finditer(r"[^\s]+", transcript)]
        if not tokens:
            return transcript, []

        # Word part of each token (strip surrounding punctuation), normalised.
        def core(tok: str) -> tuple[str, str, str]:
            m = re.match(r"^([^\w֐-׿]*)(.*?)([^\w֐-׿]*)$", tok)
            return (m.group(1), m.group(2), m.group(3)) if m else ("", tok, "")

        with self._lock:
            entries = list(self._entries)

        # Longest entries first so "Minchat Maariv" beats "Maariv".
        entries.sort(key=lambda e: -len(e.word.split()))
        english = _english()
        vocab_keys = {_norm(e.word) for e in entries}
        vocab_flat = {_flat(k) for k in vocab_keys}
        pre = []
        for e in entries:
            target = _norm(e.word)
            flat_t = _flat(target)
            pre.append(_Pre(
                entry=e, n=len(e.word.split()), target=target, flat_target=flat_t,
                key=phonetic_key(e.word), full_key=phonetic_full(e.word),
                aliases=frozenset(_norm(a) for a in e.aliases),
                flat_aliases=frozenset(_flat(_norm(a)) for a in e.aliases),
                alias_lens=frozenset(len(_flat(_norm(a))) for a in e.aliases),
                onset=flat_t[:1], tlen=len(flat_t),
                thr=self.threshold + (0.08 if len(flat_t) <= 5
                                      else 0.04 if len(flat_t) <= 7 else 0.0)))
        ctx = _Ctx(pre=pre, english=english, vocab_keys=vocab_keys,
                   vocab_flat=vocab_flat, alone={})

        parts = [core(t[0]) for t in tokens]
        norms = [_norm(p[1]) for p in parts]
        damaged = [self._is_damaged(w, english, vocab_flat) for w in norms]
        # Four window sizes per entry over a long utterance is a lot of windows
        # (172,088 plausible ones over the two corpora, and an order of
        # magnitude more implausible ones). Length and first letter decide most
        # of them and both can be had without building the string: a prefix sum
        # of flattened token lengths, and the first token's first letter.
        flats = [_flat(w) for w in norms]
        pref = [0]
        for f in flats:
            pref.append(pref[-1] + len(f))
        onsets = []
        for j in range(len(flats)):
            onsets.append(next((f[:1] for f in flats[j:] if f), ""))

        replaced = [False] * len(tokens)
        out_tokens = [t[0] for t in tokens]
        corrections: list[Correction] = []
        dirty = False

        for p in pre:
            entry = p.entry
            # WIDER WINDOW FIRST (Gil, 2026-09-19: "you have to run n equals
            # two before you run n equals one"), and never below one token.
            sizes = [m for m in range(p.n + self.WINDOW_SLACK, 0, -1)
                     if p.n - self.WINDOW_SLACK <= m <= len(tokens)]
            for m in sizes:
                i = 0
                while i + m <= len(tokens):
                    if any(replaced[i:i + m]):
                        i += 1
                        continue
                    lw = pref[i + m] - pref[i]
                    if not (abs(lw - p.tlen) <= 2 and onsets[i] == p.onset) \
                            and lw not in p.alias_lens:
                        i += 1
                        continue
                    window = " ".join(norms[i:i + m]).strip()
                    if not window or window == p.target:
                        i += 1
                        continue
                    dmg = tuple(damaged[i:i + m])
                    toks = tuple(norms[i:i + m])
                    reason, score = self._match_window(window, m, p, ctx, dmg, toks)
                    if reason is None:
                        i += 1
                        continue
                    if (m >= 2 and self.ARM_UNAMBIGUOUS and reason != "alias"
                            and not self._unambiguous(window, m, p, ctx, dmg, toks, score)):
                        i += 1
                        continue

                    # Preserve leading punct of first token and trailing punct of last.
                    lead, _, _ = parts[i]
                    _, _, trail = parts[i + m - 1]
                    original_text = " ".join(x[1] for x in parts[i:i + m])
                    out_tokens[i] = lead + entry.word + trail
                    for j in range(i + 1, i + m):
                        out_tokens[j] = ""
                    for j in range(i, i + m):
                        replaced[j] = True
                    corrections.append(Correction(original_text, entry.word, reason, score))
                    entry.hits += 1
                    # Remember the mishearing so the next one is an exact hit
                    # rather than another guess. A phonetic or respaced match is
                    # learned even though its letter score is low — the score is
                    # low BECAUSE the spelling differs, which is the whole reason
                    # it was missed before. It has already passed the damage,
                    # vowel-group, bucket-of-one, not-English and
                    # not-another-known-word guards; a letter threshold on top of
                    # those would only re-impose the test it was designed to get
                    # past.
                    learnable = (reason in ("phonetic", "respace")
                                 or (reason == "fuzzy" and score >= 0.9))
                    if learn and learnable and self._add_alias_to(entry, original_text):
                        logger.info("Vocab learned alias %r → %r (%s)",
                                    original_text, entry.word, reason)
                    dirty = True
                    i += m

        if dirty:
            try:
                self._save()
            except Exception as e:
                logger.warning("Vocab save failed: %s", e)

        fixed = " ".join(t for t in out_tokens if t)
        return fixed, corrections


    # ---------------------------------------------------------- suggest

    def label_for(self, text: str) -> str:
        """The label implied by any of this user's own words in *text*.

        Checked before the generic keyword lists, because a word the user
        curated by hand outranks a word that ships with the app: "Haxaga" is a
        course because they said so, whatever else the sentence looks like.

        Longest word first, so "Modern Computer Vision" wins over a "vision"
        entry rather than depending on dictionary order.
        """
        self._load()
        if not text:
            return ""
        hay = " " + re.sub(r"[^\w\s'-]", " ", text.lower()) + " "
        with self._lock:
            labelled = [e for e in self._entries if e.label]
            for e in sorted(labelled, key=lambda x: -len(x.word)):
                needle = " " + e.word.lower() + " "
                if needle in hay:
                    return e.label
        return ""

    def acronyms(self) -> list[VocabEntry]:
        """Shorthand this user uses, longest first. Never substituted into
        their text — see VocabEntry — but worth telling the model about."""
        self._load()
        with self._lock:
            return sorted((e for e in self._entries if e.expands_to),
                          key=lambda x: -len(x.word))

    def expansion_note(self, text: str) -> str:
        """A one-line gloss of any shorthand in *text*, for the LLM prompt.

        "Chapter of MT" stays exactly that in the task; the model is simply
        told, alongside it, that MT means Mishnah Torah.
        """
        if not text:
            return ""
        hay = " " + re.sub(r"[^\w\s'-]", " ", text.lower()) + " "
        found = [e for e in self.acronyms() if " " + e.word.lower() + " " in hay]
        if not found:
            return ""
        return "Shorthand this user uses: " + ", ".join(
            f"{e.word} = {e.expands_to}" for e in found)

    @staticmethod
    def _looks_like_english(word: str, english: "set[str]") -> bool:
        """Is this an ordinary word, allowing for a word list from 1934?

        `/usr/share/dict/words` on macOS is web2 and has no inflections — no
        "plants", no "groceries", no "says" — so a bare membership test calls
        ordinary speech unrecognised. The damage gate learned this the
        expensive way (127 wrong rewrites); the same allowance is needed here
        or one flag in four is an ordinary word.
        """
        low = word.lower().strip("'")
        if low in english:
            return True
        for suffix in ("s", "es", "'s", "ed", "d", "ing", "ly", "er", "ers",
                       "'ll", "'re", "'ve", "n't", "est", "ies"):
            if low.endswith(suffix) and low[:-len(suffix)] in english:
                return True
        if low.endswith("ies") and low[:-3] + "y" in english:
            return True
        if "'" in low:                       # o'clock, it's, don't
            if low.replace("'", "") in english or low.split("'")[0] in english:
                return True
        return False

    def suggestions(self, transcript: str, floor: float = 0.6) -> list[dict[str, Any]]:
        """Words the user may want to check: near-misses of vocab words below
        the auto-correct threshold, plus capitalised mid-sentence tokens that
        aren't known (likely names Whisper guessed at)."""
        self._load()
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        tokens = re.findall(r"[^\s]+", transcript)
        with self._lock:
            entries = list(self._entries)
        known = {_norm(e.word) for e in entries} | {_norm(a) for e in entries for a in e.aliases}
        for i, tok in enumerate(tokens):
            core = re.sub(r"^[^\w֐-׿]+|[^\w֐-׿]+$", "", tok)
            key = _norm(core)
            if not key or key in seen or key in known or key in _PROTECTED or len(key) < MIN_FUZZY_LEN:
                continue
            best, best_score = None, 0.0
            for e in entries:
                if len(e.word.split()) != 1:
                    continue
                sc = difflib.SequenceMatcher(None, key, _norm(e.word)).ratio()
                if sc > best_score:
                    best, best_score = e.word, sc
            if best is not None and floor <= best_score < self.threshold + (0.05 if len(best) <= 4 else 0):
                out.append({"heard": core, "candidate": best, "score": round(best_score, 2), "reason": "near-miss"})
                seen.add(key)
            elif i > 0 and core[:1].isupper() and not core.isupper() and core.isalpha():
                out.append({"heard": core, "candidate": None, "score": 0.0, "reason": "unknown-name"})
                seen.add(key)
            elif (len(key) >= 4 and core.isalpha()
                  and not self._looks_like_english(core, _english())):
                # A WORD IN NO DICTIONARY AND NEAR NOTHING WE KNOW. Until now
                # only a CAPITALISED unknown was surfaced, so "Pesach" got a
                # prompt and "tellmond" did not — it went straight into an
                # event title and the speaker never saw it happen.
                #
                # There is nothing to suggest here, and saying so is the
                # point: the prompt is an admission, not a correction. Gil,
                # 2026-09-20 — the edit box "is another visual way to add
                # fixes, i.e. finetuned words to the vocab list", so a word
                # flagged here and typed out is LEARNED, and the same
                # mishearing repairs itself next time.
                #
                # Measured on 187 real commands: 15 carry one (8%), and they
                # are the right ones — tellmond, manachem, WalkJaydo, Doven.
                out.append({"heard": core, "candidate": None, "score": 0.0,
                            "reason": "unrecognised"})
                seen.add(key)
        return out[:6]


_store: VocabStore | None = None
_store_lock = threading.Lock()


def get_vocab() -> VocabStore:
    """Process-wide singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = VocabStore()
    return _store


def apply_vocab(transcript: str, source: str = "mac") -> tuple[str, list[Correction]]:
    """Convenience: correct (if enabled) + record recent. Never raises."""
    try:
        store = get_vocab()
        if store.auto_correct:
            fixed, corrections = store.correct(transcript)
        else:
            fixed, corrections = transcript, []
        store.record_recent(transcript, fixed, corrections, source)
        if corrections:
            logger.info("Vocab corrections (%s): %s", source,
                        ", ".join(f"{c.original}→{c.replacement}" for c in corrections))
        return fixed, corrections
    except Exception as e:
        logger.warning("Vocab correction skipped: %s", e)
        return transcript, []
