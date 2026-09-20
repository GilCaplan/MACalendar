"""Speech fails phonetically; the matcher compared letters.

Every one of these was a real command that produced a wrong record, and in
every case the word the speaker meant was ALREADY in the personal word list:

    heard "bugroot", meant "Bagrut"    0.62 by letters, needed 0.90
    heard "makabi",  meant "Maccabi"   0.77
    heard "ofeer",    meant "Ofir"      0.75
    heard "yotem",   meant "Yotam"     0.80

None was reachable, so none was corrected, so the alias was never learned, and
the same command failed identically the next day. The learning loop was sound
and could never start.

Lowering the letter threshold is not the fix — that is what previously rewrote
correct names to wrong ones. Instead a word is coded by how it SOUNDS, and a
match on that code is allowed at a much lower letter threshold, behind three
guards. The guards are the interesting part: each one stopped a real mistake
found while measuring this against the whole command history.
"""
from __future__ import annotations

import pytest

from assistant.stt.vocab import VocabStore, phonetic_key


@pytest.fixture
def vocab(tmp_path):
    """A word list holding the words these transcripts should resolve to."""
    v = VocabStore(str(tmp_path / "vocab.json"))
    for word in ("Bagrut", "Maccabi", "Ofir", "Yotam", "Nachman", "Doron", "daven"):
        v.add_word(word)
    return v


def _fix(vocab: VocabStore, heard: str) -> str:
    _, corrections = vocab.correct(f"meeting with {heard} tomorrow", learn=False)
    return corrections[0].replacement if corrections else ""


# ---------------------------------------------------------------------------
# The failures this exists for — all on FIRST encounter, before any learning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("heard, meant", [
    ("bugroot", "Bagrut"),
    ("makabi",  "Maccabi"),
    ("ofeer",    "Ofir"),
    ("yotem",   "Yotam"),
    ("Doran",   "Doron"),
    ("Doven",   "daven"),
])
def test_a_misheard_name_is_recovered_the_first_time(vocab, heard, meant):
    assert _fix(vocab, heard) == meant


def test_the_letter_matcher_still_handles_what_it_always_did(vocab):
    """'nahman' scores 0.92 and never needed phonetics. It must not regress."""
    assert _fix(vocab, "nahman") == "Nachman"


# ---------------------------------------------------------------------------
# The guards. Each of these stopped a real false positive.
# ---------------------------------------------------------------------------

def test_an_ordinary_word_is_not_rewritten_to_a_short_code_twin(tmp_path):
    """The one that nearly shipped: 'pasta' and 'pset' share the code P-S-T.

    Soundex discards vowels, which is exactly the difference between them.
    Requiring the same number of vowel runs separates them, and this was found
    by replaying the whole command history rather than by reasoning about it.
    """
    v = VocabStore(str(tmp_path / "v.json"))
    v.add_word("pset")
    assert _fix(v, "pasta") == "", "'pasta' was rewritten to a word it does not sound like"


def test_a_multi_word_entry_is_never_matched_phonetically(tmp_path):
    """Word boundaries move when a phrase is misheard, so a code over a phrase
    is not comparable to one over the transcript. Caught 'set meeting for'
    being rewritten to 'set a meeting'."""
    v = VocabStore(str(tmp_path / "v.json"))
    v.add_word("set a meeting")
    _, corrections = v.correct("set meeting for tomorrow", learn=False)
    assert not [c for c in corrections if c.reason == "phonetic"]


def test_a_real_english_word_is_left_alone(tmp_path):
    """The pre-existing guard, which the phonetic branch must not bypass."""
    v = VocabStore(str(tmp_path / "v.json"))
    v.add_word("Mira")
    assert _fix(v, "meter") == ""


def test_when_two_words_sound_alike_the_letters_decide(tmp_path):
    """A bucket of one is unambiguous; a bucket of several is not, so the
    closest spelling wins rather than whichever happened to be checked first."""
    v = VocabStore(str(tmp_path / "v.json"))
    v.add_word("Doron")
    v.add_word("Duran")
    assert phonetic_key("Doron") == phonetic_key("Duran"), "test needs a real collision"
    assert _fix(v, "Doran") == "Doron"


# ---------------------------------------------------------------------------
# The loop this unblocks
# ---------------------------------------------------------------------------

def test_a_phonetic_hit_is_remembered_so_the_next_one_is_instant(vocab):
    """The whole point. The correction was never made, so it was never learned.

    Once made, the existing auto-learn stores the misheard spelling as an
    alias and every later occurrence is an exact hit rather than a guess.
    """
    vocab.correct("meeting with bugroot tomorrow", learn=True)
    entry = next(e for e in vocab.entries if e.word == "Bagrut")
    assert "bugroot" in [a.lower() for a in entry.aliases], \
        "the recovered mishearing was not learned"

    _, corrections = vocab.correct("bugroot exam friday", learn=False)
    assert corrections and corrections[0].reason == "alias", \
        "the second encounter should be an exact alias hit, not another guess"


# ---------------------------------------------------------------------------
# The coding itself
# ---------------------------------------------------------------------------

def test_words_that_sound_alike_share_a_code():
    assert phonetic_key("bugroot") == phonetic_key("Bagrut")
    assert phonetic_key("makabi") == phonetic_key("Maccabi")


def test_words_that_merely_look_alike_do_not():
    assert phonetic_key("Tal") != phonetic_key("Talk")


def test_non_latin_script_has_no_code_and_is_never_matched(tmp_path):
    """The coding table is meaningless for Hebrew, and 54 entries are in it.

    An empty key must never match another empty key, or every Hebrew word in
    the list would be interchangeable with every other.
    """
    assert phonetic_key("בוקר") == ""
    v = VocabStore(str(tmp_path / "v.json"))
    v.add_word("בוקר")
    v.add_word("מנחה")
    _, corrections = v.correct("meeting with מנחה tomorrow", learn=False)
    assert not [c for c in corrections if c.reason == "phonetic"]


# ---------------------------------------------------------------------------
# MULTI-WORD REPAIR: the window may be WIDER or NARROWER than the entry
#
# Whisper does not keep a phrase's word boundaries when it mishears it, so the
# token count moves: 'quinoa delivery' comes back as 'quin oh a delivery' (4
# tokens for 2) and 'ice cream' as 'icecream' (1 for 2). The phonetic path was
# hard-gated `n == 1` for a documented reason — a code computed over a phrase
# whose boundaries have moved is not comparable — so none of these were
# repairable at all.
#
# Lifting the gate needs three things the gate was standing in for, each of
# which was measured into existence:
#   * compare SPACE-STRIPPED, because the spaces are part of the damage
#   * an UNTRUNCATED phonetic code for multi-word windows, because Soundex
#     truncates to four characters and over a phrase becomes a prefix test
#   * a DAMAGE GATE: a window of entirely real words is never merged
#
# Gil, 2026-09-19: "run n equals two before n equals one. But in cases where
# two sequential words, one is good and one is bad, then you don't combine
# because we want that n equals one to also work."
# ---------------------------------------------------------------------------

def _store(tmp_path, monkeypatch, *words):
    monkeypatch.setenv("MACALENDAR_VOCAB", str(tmp_path / "vocab.json"))
    from assistant.stt.vocab import VocabStore
    store = VocabStore()
    for w in words:
        store.add_word(w)
    return store


def test_a_wider_window_repairs_a_multi_word_term(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch, "barista course", "kombucha order")
    assert store.correct("book bar rista course on friday")[0] == \
        "book barista course on friday"
    assert store.correct("book kom bootcha order tomorrow")[0] == \
        "book kombucha order tomorrow"


def test_a_narrower_window_repairs_a_joined_compound(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch, "ice cream")
    assert store.correct("add icecream to my list")[0] == "add ice cream to my list"


def test_the_single_word_path_still_works_beside_it(tmp_path, monkeypatch):
    """The REGRESSION this nearly shipped with. 'poker knight' against a
    'poker night' entry is two REAL English words, so the damage gate refused
    a repair the released code performs. The gate now applies only to a
    WIDENED window — at the entry's own width the shipped path is untouched.
    Found end-to-end through the ingest stage, not by the bench, because the
    bench's damaged forms are all non-words."""
    store = _store(tmp_path, monkeypatch, "poker night")
    assert store.correct("book poker knight on friday")[0] == \
        "book poker night on friday"


@pytest.mark.parametrize("text", [
    # the documented regression the n == 1 gate was written to prevent
    "set meeting for tomorrow",
    # ordinary English that merely sits near an entry
    "do you know when the meeting is",
    "buy milk and call mom",
    "water the plants this afternoon",
    "add buy groceries to my list",
    "call mom and dad",
])
def test_a_window_of_real_words_is_never_merged(tmp_path, monkeypatch, text):
    store = _store(tmp_path, monkeypatch, "set a meeting", "poker night",
                   "barista course", "ice cream", "water the garden")
    assert store.correct(text)[0] == text


def test_an_empty_vocabulary_changes_nothing(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    for text in ("book bar rista course", "add icecream to my list", "buy milk"):
        assert store.correct(text)[0] == text


# ---------------------------------------------------------------------------
# A WORD IN NO DICTIONARY IS SURFACED, not silently accepted
#
# `suggestions()` flagged a CAPITALISED unknown ("Pesach") and a near-miss of
# a vocabulary word, and nothing else — so "tellmond" went straight into an
# event title and the speaker never saw it happen. Measured on 187 real
# commands: 8 carry one, and they are the right ones (tellmond, yarev,
# manachem, bagru, squirmant).
#
# Gil, 2026-09-20: the edit box "is another visual way to add fixes, i.e.
# finetuned words to the vocab list" — so a word flagged here and typed out
# is LEARNED, and the same mishearing repairs itself afterwards.
# ---------------------------------------------------------------------------

def test_an_unrecognised_word_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_VOCAB", str(tmp_path / "vocab.json"))
    from assistant.stt.vocab import VocabStore
    store = VocabStore(str(tmp_path / "vocab.json"))
    store.add_word("Ora")

    flagged = {s["heard"].lower(): s["reason"]
               for s in store.suggestions("set a meeting with tellmond tomorrow")}
    assert flagged.get("tellmond") == "unrecognised", flagged
    # nothing to suggest, and saying so is the point
    assert all(s["candidate"] is None
               for s in store.suggestions("set a meeting with tellmond tomorrow")
               if s["heard"].lower() == "tellmond")


@pytest.mark.parametrize("sentence", [
    # the 1934 word list has no inflections; without the allowance these are
    # all "unrecognised" and one flag in four is an ordinary word
    "buy groceries tomorrow",
    "water the plants this afternoon",
    "he says the meeting moved",
    "set an event at 6 o'clock",
    "remind me to call the plumber",
])
def test_ordinary_speech_is_not_flagged(tmp_path, monkeypatch, sentence):
    from assistant.stt.vocab import VocabStore
    store = VocabStore(str(tmp_path / "vocab.json"))
    store.add_word("Ora")
    assert [s for s in store.suggestions(sentence)
            if s["reason"] == "unrecognised"] == []
