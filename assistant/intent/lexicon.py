"""The personal LEXICON — the word lists, editable by the person who speaks them.

Gil, 2026-09-18, after "Can you shorten the event at 2pm walk Jada to be 15
minutes" silently did nothing:

    "for all these like list of words, like extend verbs and anything else
     related in the project, I think in the settings we should have a section
     where these are all listed out and linked to what's in the code and can be
     dynamically updated such that the user, if he has some ways that he says
     how he wants to shorten or update, then he can just put it there"

That bug was not a parsing failure. `_MUTATE_VERB` in the deep track's safety
net had simply never learned the word "shorten", while `rule_parser` had known
it all along — two hand-typed lists of the same idea, drifted apart. There are
**239 pattern constants** under `assistant/intent/` and `assistant/engine/`, and
every one of them is a place where the engine's idea of English can fall behind
the person using it.

**The vocabulary is the precedent, not a new invention.** `assistant/stt/vocab.py`
already does this for NAMES: a personal store, a REST surface, a settings screen,
and the engine reads it before parsing. This is the same shape for VERBS and
PHRASES.

WHAT MAKES THIS SAFE
--------------------
**User entries ADD; they never remove.** `effective()` is always
`built_in | user`, so no edit can take a word away from the engine and leave a
command that used to work broken. The floor stays where it is and the ceiling
goes up. Removing a built-in would be a different feature with a different risk
profile, and it is deliberately not this one.

**A name is declared once, in `LEXICONS`, with the code it belongs to.** That is
the "linked to what's in the code" half: the settings screen shows the built-in
entries as read-only fact, sourced from the module that uses them, beside the
person's own additions. `tests/unit/test_lexicon.py` fails if a declaration
names a module attribute that no longer exists — the same contract
`test_panel_agreement.py` holds the thinking panel to.

**The store is personal data.** `~/.assistant_tools/lexicon.json`, overridden by
`MACALENDAR_LEXICON` and scratched by `tests/conftest.py`, exactly like the
vocabulary, the categories and the command memory.
"""
from __future__ import annotations

import json
import os
import threading
import time

LEXICON_PATH = (os.environ.get("MACALENDAR_LEXICON")
                or os.path.expanduser("~/.assistant_tools/lexicon.json"))


class Lexicon:
    """One named word list: what the code ships, and what the person added.

    `module`/`attr` point at the built-in so the settings screen can show it
    without this file keeping a second copy — a second copy is the whole defect
    this exists to prevent.
    """

    __slots__ = ("name", "label", "why", "module", "attr", "example")

    def __init__(self, name, label, why, module, attr, example=""):
        self.name = name
        self.label = label          # what the settings screen calls it
        self.why = why              # one line: what adding a word here does
        self.module = module
        self.attr = attr
        self.example = example

    def built_in(self) -> "frozenset[str]":
        """The words the code ships with, read from the module that owns them."""
        import importlib
        try:
            mod = importlib.import_module(self.module)
        except ImportError:
            return frozenset()
        value = getattr(mod, self.attr, None)
        if value is None:
            return frozenset()
        if isinstance(value, (set, frozenset, list, tuple)):
            return frozenset(str(v).lower() for v in value)
        return frozenset()


#: Every list a person may extend. NOT all 239 — only the ones that are about
#: HOW SOMEONE SPEAKS. A regex for an ISO date is not a dialect; a verb for
#: making an event shorter is.
#:
#: Adding one here is cheap and is the point: declare it, and both the API and
#: the settings screen pick it up with no further wiring.
LEXICONS: "dict[str, Lexicon]" = {
    lx.name: lx for lx in (
        Lexicon("extend_verbs", "Making something longer or shorter",
                "Words that change how long an event lasts, rather than moving it.",
                "assistant.intent.rule_parser", "_EXTEND_VERBS",
                example="shorten, extend, trim"),
        Lexicon("mutate_verbs", "Words that change something",
                "Words that mean you are CHANGING or REMOVING something that "
                "already exists — they are what stops a question being treated "
                "as an instruction.",
                "assistant.engine.decompose_validate.object_rules", "_MUTATE_VERBS",
                example="move, cancel, shorten"),
        Lexicon("title_strip_verbs", "Words to leave out of a title",
                "Instruction words that should not end up in the NAME of the "
                "thing — \"book the dentist\" is called \"the dentist\".",
                "assistant.intent.rule_parser", "_TITLE_STRIP_VERBS",
                example="book, schedule, add"),
        Lexicon("calendar_words", "Generic words for an entry",
                "Words that mean \"a thing in the calendar\" rather than naming "
                "one, so they are never treated as a title on their own.",
                "assistant.intent.rule_parser", "_CALENDAR_SIGNALS",
                example="meeting, appointment, event"),
    )
}


class LexiconStore:
    """The person's additions, on disk. Small, flat and hand-editable on purpose.

    Shape:  {"extend_verbs": ["squeeze", "stretch out"], "stop_words": [...]}
    """

    def __init__(self, path: "str | None" = None) -> None:
        # Resolved at CALL time, not as a default argument. A default is bound
        # at import, and this project's stores are all read at import — which is
        # exactly why `conftest.py` sets its overrides before importing
        # `assistant` at all. Here it would also make the path unpatchable from
        # a fixture, which is how the first version of this failed its own test.
        self.path = path or LEXICON_PATH
        self._lock = threading.Lock()
        self._data: dict = {}
        self._mtime: float = -1.0
        self._load()

    def _load(self) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self._data, self._mtime = {}, -1.0
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return                              # keep what we had; never crash a parse
        if isinstance(raw, dict):
            self._data = {
                k: sorted({str(w).strip().lower() for w in v if str(w).strip()})
                for k, v in raw.items()
                if k in LEXICONS and isinstance(v, (list, tuple))
            }
        self._mtime = mtime

    # -- reading -----------------------------------------------------------

    def added(self, name: str) -> "list[str]":
        """Just the person's own words for `name`."""
        self._load()                            # a PATCH from the phone lands on disk
        return list(self._data.get(name, ()))

    def effective(self, name: str) -> "frozenset[str]":
        """What the engine should actually use: built-in PLUS the person's.

        Union, always. An edit can only ever widen what the engine understands.
        """
        lx = LEXICONS.get(name)
        if lx is None:
            return frozenset()
        return lx.built_in() | frozenset(self.added(name))

    def describe(self) -> list:
        """Everything the settings screen needs, in one call."""
        out = []
        for name, lx in LEXICONS.items():
            out.append({
                "name": name,
                "label": lx.label,
                "why": lx.why,
                "example": lx.example,
                "source": f"{lx.module}.{lx.attr}",
                "built_in": sorted(lx.built_in()),
                "added": self.added(name),
            })
        return out

    # -- writing -----------------------------------------------------------

    def add(self, name: str, word: str) -> bool:
        word = (word or "").strip().lower()
        if name not in LEXICONS or not word:
            return False
        if word in LEXICONS[name].built_in():
            return False                        # already known; nothing to store
        with self._lock:
            self._load()
            words = set(self._data.get(name, ()))
            if word in words:
                return False
            words.add(word)
            self._data[name] = sorted(words)
            self._save()
        return True

    def remove(self, name: str, word: str) -> bool:
        """Removes one of the PERSON'S OWN words. A built-in cannot be removed —
        see this module's docstring: an edit may only ever widen the engine."""
        word = (word or "").strip().lower()
        with self._lock:
            self._load()
            words = set(self._data.get(name, ()))
            if word not in words:
                return False
            words.discard(word)
            self._data[name] = sorted(words)
            self._save()
        return True

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = f"{self.path}.tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self._mtime = os.path.getmtime(self.path)


_store: "LexiconStore | None" = None
_store_lock = threading.Lock()


def get_lexicon() -> LexiconStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = LexiconStore()
    return _store


def effective(name: str) -> "frozenset[str]":
    """The engine's entry point. Cheap: the file's mtime is the only syscall on
    the common path, and the parse that calls this runs in ~50 ms."""
    return get_lexicon().effective(name)


def reset() -> None:
    """Tests swap the store path; the singleton must not outlive it."""
    global _store
    _store = None
