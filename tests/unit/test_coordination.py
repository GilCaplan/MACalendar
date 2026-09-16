"""assistant/intent/coordination.py — the NP-vs-clause-coordination split,
and the two rescues built on top of it for a command verb spaCy mis-tags as
a noun. No dedicated test file existed for this module before; it is shared
by FastRule's compound gate and segment's pre-split, so a regression here is
invisible until it shows up as a wrong count somewhere else entirely.
"""
from __future__ import annotations

from assistant.intent.coordination import split_clauses


# --- the baseline: real clause-coordination splits, NP-coordination doesn't ---

def test_two_asks_split():
    assert split_clauses("book gym and remind me to buy milk") == \
        ["book gym", "remind me to buy milk"]


def test_two_people_do_not_split():
    assert split_clauses("meeting with Sam and Alex at 8") == \
        ["meeting with Sam and Alex at 8"]


def test_two_objects_of_one_verb_do_not_split():
    assert split_clauses("buy milk and eggs") == ["buy milk and eggs"]


def test_two_verbs_one_object_do_not_split():
    assert split_clauses("wash and fold the laundry") == \
        ["wash and fold the laundry"]


# --- the compound-chain rescue: a verb hiding as a NOUN compound (row 45 fix) ---

def test_a_flat_compound_hides_the_second_verb():
    # book and tennis both direct children of lesson
    assert split_clauses("remind me to wash the car and then book tennis lesson") == \
        ["remind me to wash the car", "book tennis lesson"]


def test_a_nested_compound_chain_hides_the_second_verb():
    # book -> compound -> yoga -> compound -> class: one level deeper than
    # the flat case above, and invisible to a direct-children-only search.
    assert split_clauses(
        "remind me to water the plants and then book yoga class the 30th at 11am"
    ) == ["remind me to water the plants",
          "book yoga class the 30th at 11am"]


# --- the family-mismatch rescue: the conjunct's head is a NOUN, not the ROOT verb ---

def test_a_different_intent_family_rescues_the_split():
    # `appointment`'s head is `bananas` (a NOUN) so the primary compound-
    # chain gate refuses; buy=create_todo, book=create_event differ, so the
    # family-mismatch rescue fires instead.
    assert split_clauses(
        "buy 3 bananas and book car service appointment at the end of the month"
    ) == ["buy 3 bananas",
          "book car service appointment at the end of the month"]


def test_the_same_intent_family_does_not_rescue_the_split():
    # water=create_todo, buy=create_todo: SAME family, stays refused. This
    # is the exact false-positive the compound-chain gate exists to catch,
    # now doubly guarded by the rescue's own family check.
    assert split_clauses("buy apples and water bottles") == \
        ["buy apples and water bottles"]


def test_an_nmod_tagged_hidden_verb_is_found_too():
    # spaCy tags the hidden verb "compound" ("book yoga class") or "nmod"
    # ("book annual checkup") for the same real relationship, unpredictably —
    # both links must be walked.
    assert split_clauses("buy six stamps and then book annual checkup in two days") == \
        ["buy six stamps", "book annual checkup in two days"]


def test_a_verb_outside_the_lexicon_rescues_nothing():
    # "confirm" has no INTENT_MAP entry, so there is no family to compare —
    # the rescue must fail closed (no split), never guess.
    assert split_clauses(
        "confirm the reservation and then book webinar this weekend at 11am"
    ) == ["confirm the reservation and then book webinar this weekend at 11am"]


# --- the bare-object extension: no article at all, English never puts one here ---

def test_a_bare_noun_object_with_no_article_still_splits():
    assert split_clauses(
        "remind me to restock the pantry and book eye exam next month at quarter to nine"
    ) == ["remind me to restock the pantry",
          "book eye exam next month at quarter to nine"]


def test_a_bare_object_followed_by_a_date_word_does_not_split():
    # The exact case the article requirement existed to protect: a name that
    # collides with a command verb, followed by a bare DATE word rather than
    # an object — "tomorrow" must not be read as what was booked.
    assert split_clauses("meeting with Tal and Mark tomorrow") == \
        ["meeting with Tal and Mark tomorrow"]
