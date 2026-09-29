"""Words whose part of speech we KNOW, told to spaCy before anything reads it.

Gil, 2026-09-29: *"Can have vocab words tagged ahead of time to switch out
what spacy model does"*. The small English model guesses at words it has never
seen, and guesses badly: "shiur on rosh chodesh kislev at 8pm" came back with
"shiur" an ADVERB, and the router's bare-noun rule — which needs the command
to open with a noun — read nothing at all. A Hebrew word, a friend's name or a
place is not a verb, whatever the sentence around it looks like.

Two lists, one rule — a listed word spaCy tagged as something other than a
noun is re-tagged after the tagger has run:

    JEWISH_NOUNS   the calendar and synagogue words (NOUN) — the same for
                   everybody, like ingest's aim (a)
    the vocabulary each user's own words (PROPN: names, places, shorthand),
                   read from the vocabulary of whoever the command is for —
                   aim (b) — and skipped when the word is real English, the
                   guard the vocabulary itself uses

Only the tag changes. The dependency parse ran before this step and is not
redone; the router and the title readers read ``pos_`` / ``tag_``.
"""

from __future__ import annotations

import os
import re
import threading

#: Calendar and synagogue words, NOUN. Short words that are also English or
#: other parts of speech ("bar", "tu", "lag", "av", "yom", "tov") are left out:
#: a wrong NOUN costs as much as a wrong VERB.
JEWISH_NOUNS = frozenset("""
shiur shiurim minyan shul kiddush havdalah shacharit mincha maariv musaf hallel
selichot chavruta chavrusa tefillin seudah shlishit kabbalat shabbat shabbos
motzei motzash erev chag rosh chodesh hodesh hashana hashanah kippur sukkot
succot sukkos succos simchat simchas atzeret atzeres shemini shmini chanukah
chanuka hanukkah hanukah chanukkah purim pesach pesah seder hamoed baomer
shavuot shavuos tisha bishvat yahrzeit yortzeit aufruf chuppah simcha mitzvah
brit milah bris sheva brachot megillah leyning davening yeshiva kollel
nisan nissan iyar sivan tammuz tamuz elul tishrei tishri cheshvan heshvan
marcheshvan kislev tevet teves shevat shvat adar
""".split())

_lock = threading.Lock()
_cache: dict = {}


def _vocab_words() -> frozenset:
    """The current user's vocabulary words, lower-cased, single tokens,
    real English left out. Cached per vocabulary file and its mtime."""
    try:
        from assistant.stt import vocab as _v
        store = _v.get_vocab()
        path = getattr(store, "_path", "") or ""
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            stamp = None
        key = (path, stamp)
        with _lock:
            if key in _cache:
                return _cache[key]
        english = _v._english()
        words = set()
        for e in store.entries:                   # a property, not a method
            for w in re.findall(r"[a-z][a-z'\-]+", (e.word or "").lower()):
                if len(w) >= 3 and w not in english:
                    words.add(w)
        got = frozenset(words)
        with _lock:
            _cache.clear()
            _cache[key] = got
        return got
    except Exception:                 # no vocabulary is no reason to fail a parse
        return frozenset()


def pretag(doc):
    """The spaCy component: re-tag listed words spaCy did not read as nouns."""
    mine = _vocab_words()
    for tok in doc:
        if tok.pos_ in ("NOUN", "PROPN"):
            continue
        low = tok.lower_
        if low in JEWISH_NOUNS:
            tok.pos_, tok.tag_ = "NOUN", "NN"
        elif low in mine:
            tok.pos_, tok.tag_ = "PROPN", "NNP"
    return doc


def install(nlp) -> None:
    """Add the step to a loaded pipeline, once, after every tagger."""
    from spacy.language import Language
    if not Language.has_factory("macalendar_pretag"):
        Language.component("macalendar_pretag", func=pretag)
    if "macalendar_pretag" not in nlp.pipe_names:
        nlp.add_pipe("macalendar_pretag", last=True)
