"""assistant/intent/coordination.py — the NP-vs-clause-coordination split,
and the two rescues built on top of it for a command verb spaCy mis-tags as
a noun. No dedicated test file existed for this module before; it is shared
by FastRule's compound gate and segment's pre-split, so a regression here is
invisible until it shows up as a wrong count somewhere else entirely.
"""
from __future__ import annotations

import pytest

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


# --- the lexicon fallback: spaCy swallows the WHOLE first verb, not just one token ---

def test_a_swallowed_root_verb_still_splits():
    # "schedule budget review... and add water the plants..." parses `review`
    # as nsubj of `add` — the whole first clause reads as a noun-phrase
    # subject, and `schedule` gets no conj/dep tag at all for the main walk
    # to find. The fallback trusts INTENT_MAP instead of the broken parse.
    assert split_clauses(
        "schedule budget review for next week and add water the plants to my list"
    ) == ["schedule budget review for next week",
          "add water the plants to my list"]


def test_the_fallback_still_refuses_same_family_np_coordination():
    # Position alone (sentence-initial / after a coordinator) would ALSO
    # find `water` here — the family-mismatch check is still required, not
    # just the parse-repair.
    assert split_clauses("buy apples and water bottles") == \
        ["buy apples and water bottles"]


def test_the_fallback_never_fires_mid_clause():
    assert split_clauses("the schedule needs an update") == \
        ["the schedule needs an update"]


def test_a_verb_with_no_unqualified_intent_map_entry_resolves_from_context():
    # "add" has ONLY qualified entries (calendar / todo) — "to my list" must
    # resolve it to create_todo, not whichever qualifier the table lists
    # first, or it would falsely match "schedule"'s create_event family and
    # never split.
    assert split_clauses(
        "schedule retrospective for in three weeks and add pay the electricity bill to my list"
    ) == ["schedule retrospective for in three weeks",
          "add pay the electricity bill to my list"]


def test_a_lead_time_reminder_is_not_a_second_ask():
    # "book webinar... and remind me two hours before" IS a real family
    # mismatch (book=event, remind=todo) and would otherwise rescue clean —
    # but the second clause is nothing but a lead time on the event just
    # booked, the same idiom fastseg.py's own splitter already protects.
    assert split_clauses(
        "book webinar this sunday at 8:30pm and remind me two hours before"
    ) == ["book webinar this sunday at 8:30pm and remind me two hours before"]


def test_a_reminder_with_its_own_content_is_still_a_second_ask():
    # The lead-time guard must not swallow a real second ask that happens to
    # end in a similar-looking phrase — this one has its own object ("call
    # the vet"), so it is not the bare "remind me ... before" idiom.
    assert split_clauses(
        "schedule budget review for next week and remind me to call the vet in an hour"
    ) == ["schedule budget review for next week",
          "remind me to call the vet in an hour"]


# --- the sentence-boundary exception: a period is stronger evidence than a coordinator ---

def test_a_period_separated_sentence_splits_even_same_family():
    # "remind me to X. also remind me to Y" is TWO spaCy sentences (the
    # period is strong enough to split there), both `create_todo` — same
    # family, which would normally block the fallback, but a real sentence
    # boundary is punctuation-driven evidence a coordinator position never
    # has, so the family check is skipped for it specifically.
    assert split_clauses(
        "remind me to pick up the dry cleaning. also remind me to renew the passport"
    ) == ["remind me to pick up the dry cleaning",
          "remind me to renew the passport"]


def test_the_sentence_start_skips_leading_discourse_markers():
    # The sentence's own first token is "also", not "remind" — the walk
    # back to the sentence start must tolerate a leading coordinator word
    # without losing the token as a valid split point.
    assert split_clauses(
        "remind me to return the library books. also remind me to book a flight"
    ) == ["remind me to return the library books",
          "remind me to book a flight"]


# --- the MAIN WALK's own lead-time guard: "remind" as a real VERB conjunct
# (not a mis-tagged compound) never reaches the fallback above, so it needed
# its own copy of the same idiom check ---

def test_a_real_verb_conjunct_lead_time_does_not_split():
    # "remind" gets a proper conj tag off "book" here (unlike the fallback
    # case above), so this exercises the MAIN walk's guard, not the
    # fallback's — the two used to disagree before both shared one check.
    assert split_clauses(
        "book eye exam this weekend at late afternoon and remind me two hours before"
    ) == ["book eye exam this weekend at late afternoon and remind me two hours before"]


def test_a_stacked_lead_marker_still_does_not_split():
    # "10 minutes before BEFOREHAND" — a second, redundant lead-marker the
    # generator sometimes appends; `_REMINDER_LEAD_RE` must still anchor to
    # the end past it.
    assert split_clauses(
        "set up client call next month and remind me 10 minutes before beforehand"
    ) == ["set up client call next month and remind me 10 minutes before beforehand"]


def test_a_bare_add_a_note_does_not_split():
    # No object to note ABOUT, so nothing for a second item to be — the
    # `_non_splitting_tail` idiom shared with the reminder-lead-time guard.
    assert split_clauses(
        "change the due date of do the laundry to two weeks from now and add a note"
    ) == ["change the due date of do the laundry to two weeks from now and add a note"]


# --- structural, not enumerative (2026-09-17): a subordinate-FIRST command
# clause, a second-sentence root behind a lead-in phrase, and an object that
# carries a modifier -- three shapes the walk used to be blind to, none fixed
# with a phrase list ---

def test_a_subordinate_first_command_clause_splits():
    # `prepare` is `advcl` of `let` (the ROOT, six tokens later) -- no conj/dep
    # tag anywhere, so only the subordinate-first path can see it.
    assert split_clauses(
        "first prepare the presentation, then let's get therapy session on the calendar"
    ) == ["first prepare the presentation",
          "let's get therapy session on the calendar"]


@pytest.mark.parametrize("text", [
    # the same parse shape, but the main clause is a REMARK, not an ask --
    # past tense, negation, a participle, no verb at all. 17 rows regressed
    # the first time this path shipped without this guard.
    "check off this reminder, it's done",
    "move that one to next wednesday, i don't remember the name",
    "book moving day every month at 7am, no exceptions",
    "remove schedule a haircut from my list, i already handled it",
])
def test_a_command_followed_by_a_remark_stays_whole(text):
    assert split_clauses(text) == [text]


@pytest.mark.parametrize("text", [
    # genuine subordinate clauses: a subject of its own, a subordinating
    # marker, or an infinitival purpose -- each read from the parse
    "when you get a chance, water the plants",
    "if it rains, cancel the picnic",
    "call the plumber to fix the sink",
    "before i leave, remind me to lock up",
])
def test_a_real_subordinate_clause_stays_whole(text):
    assert split_clauses(text) == [text]


def test_a_second_sentence_root_behind_a_lead_in_splits():
    # `remind` is the ROOT of a new sentence; "along with that," in front of
    # it is its own fronted adverbial, not a clause -- read off `dep_ ==
    # "ROOT"`, so no list of tolerated lead-in phrases is needed. The
    # lead-in stays with the previous item, per the dataset's own gold.
    parts = split_clauses(
        "schedule workshop for on the 15th. along with that, remind me to file the taxes")
    assert len(parts) == 2 and parts[1] == "remind me to file the taxes"


def test_an_object_carrying_a_modifier_still_counts_as_an_object():
    # "order NEW office supplies" -- the bare-object check used to look only
    # at the very next token and see an adjective.
    assert split_clauses(
        "i need to fix the leaky faucet and order new office supplies"
    ) == ["i need to fix the leaky faucet", "order new office supplies"]


def test_add_a_note_with_its_own_object_still_splits():
    # "add a note ABOUT X" has a real object — not the bare idiom, so it is
    # a genuine second ask.
    assert split_clauses(
        "change the due date of do the laundry to two weeks from now "
        "and add a note about the delivery"
    ) == ["change the due date of do the laundry to two weeks from now",
          "add a note about the delivery"]
