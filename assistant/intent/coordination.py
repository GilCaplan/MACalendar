"""Coordination-type check — is this "and" joining two THINGS or two ASKS?

The multi-intent literature's core finding (F5 / research sweep, see
DOCUMENTATION/experiments/FASTRULE_RESEARCH.md idea 1): splitting on the
position of conjunctions alone cannot tell "meeting with Tal and Sam"
(NP-coordination — one event, two guests) from "book the gym and remind me
to buy milk" (clause-coordination — two asks). The dependency parse can:
spaCy marks the second conjunct with dep_ == "conj", and the POS of what got
coordinated says which kind of join it is — a VERB conjunct is a second
clause, a NOUN/PROPN conjunct is a longer noun phrase.

One function, three intended call sites: FastRule's strong-compound gate
(wired in this batch), the segment stage's deterministic pre-split and the
compound-hint filter (later batches). Deterministic, ~ms on command-length
text, and honest about failure: if spaCy is unavailable or the parse is
degenerate, it reports NO clause-coordination — the caller's regexes remain
the floor, so a parse outage can never over-abstain.
"""

from __future__ import annotations

import functools
import re

#: One ASK-JOINER between two asks; N joiners announce N+1 asks. ", and" and
#: "and then" are ONE joiner, not two — the alternation is ordered longest-
#: first so the compound forms win, and a trailing comma is swallowed. A
#: comma inside a single ask ("friday, march 5th") over-counts, which is the
#: safe direction for both consumers: FastRule's `_parse_covers_the_compound`
#: then prefers to defer, and the `joiner-mid` feature then prefers "middle".
ASK_JOINER_RE = re.compile(
    r"(?:"
    r",?\s*\band\s+(?:then|also)\b"
    r"|,\s*(?:then|also|plus)\b"
    r"|[.;!?]\s+(?:also|then|plus|and)\b"
    r"|\s[—–]\s*and\b"
    r"|,?\s*\band\b"
    r"|[;,]"
    r"),?",
    re.I)


#: A `conj` dependency needs a coordinator, so a sentence with none cannot
#: have clause coordination and does not need to be parsed at all. 57% of
#: the two datasets' 9,899 utterances match nothing here, and the parse is
#: ~9 ms — the difference between the check being free on a simple command
#: and being the fast track's largest single cost. Deliberately WIDER than
#: `ASK_JOINER_RE` ("or", "but", "plus", "as well as"): a cheap pre-filter
#: must never be the thing that decides, and this one is verified lossless
#: over both datasets in full.
#: "then"/"after that" are SEQUENCERS, not coordinators, so they were absent
#: while this gate only fronted a `conj` search. They must be here now that a
#: second imperative joined by one is a candidate — the pre-filter is only
#: allowed to be cheap, never to be the thing that decides, and a joiner it
#: does not list is a compound the splitter can never see.
_COORDINATOR_RE = re.compile(
    r"\b(?:and|or|but|plus|then|also|as well as|along with|after that)\b|[,;]",
    re.I)


@functools.lru_cache(maxsize=256)
def parsed(text: str):
    """The spaCy doc for `text`, memoised.

    Two callers now want the same parse of the same utterance in the same
    ~50 ms: this check (layer 0's rules tier) and `AtomicityFeatures`'
    clause-coord signal (its model tier, F17). Without the cache the parse
    is paid twice per command. Returns None — never raises — when spaCy is
    unavailable or the parse fails, so every caller degrades to "saw
    nothing" rather than to an exception.
    """
    from assistant.intent import rule_parser as _rp

    _rp._ensure_nlp()
    nlp = _rp._NLP
    if nlp is None or not text or " " not in text:
        return None
    try:
        return nlp(text)
    except Exception:
        return None


class Boundary:
    """Where one ask ends and the next begins, as character offsets.

    `text[:ends]` is the first ask, `text[begins:]` the second; the span
    between them is the coordinator ("and", ", and then", ";") which belongs
    to neither. Keeping both offsets rather than one split point is what lets
    a caller drop the joiner without re-guessing how many words it was.
    """

    __slots__ = ("ends", "begins", "joiner")

    def __init__(self, ends: int, begins: int, joiner: str):
        self.ends = ends            # first ask ends here (exclusive)
        self.begins = begins        # second ask begins here
        self.joiner = joiner        # the words cut out, for the trace

    def __repr__(self) -> str:      # pragma: no cover - debugging aid
        return f"Boundary({self.ends}, {self.begins}, {self.joiner!r})"


#: Words that join two asks and belong to neither of them. Used only to widen
#: the cut once the PARSE has already decided there is a boundary here — it
#: never decides on its own.
#: "as" and "well" are here for the multi-word joiner "as well as", which the
#: pre-filter already lists but the walk-back did not: cutting at the final
#: "as" stranded "as well" on the first ask and dropped the "as" entirely.
#: They are safe because this walk only ever consumes tokens IMMEDIATELY
#: adjacent to a boundary the parse already found — "mark the task as done and
#: X" stops at "done", which is not a joiner.
_COORD_WORDS = frozenset({"and", "then", "also", "plus", "or", "but",
                          "as", "well"})

#: A split is only worth making if both halves are substantive. One word on
#: either side is a parse artifact, not an ask — and an empty half would hand
#: the next stage a blank item to invent a title for.
_MIN_WORDS_PER_ASK = 2

#: Dependency labels that mean "this verb carries an argument of its own" —
#: what separates a real second ask ("remind ME", "delete THE GYM SESSION")
#: from a bare verb sharing its neighbour's object ("wash and fold THE
#: LAUNDRY"). Shared by the main walk and the subordinate-first path.
_OWN_ARG = ("dobj", "obj", "ccomp", "xcomp", "dative", "attr", "oprd",
            "npadvmod", "appos", "compound", "prep", "prt", "advcl")


def _reads_as_an_ask(tok) -> bool:
    """Is this clause head something the speaker is ASKING for, or a remark?

    An ask is a base-form verb — an imperative, or the complement of a
    modal ("i'd rather WALK the dog", "LET's get…") — or a head whose own
    complement is one ("i need to BOOK…"), never negated. A remark is what
    is left: past tense ("i already HANDLED it", "finally GOT to it"), a
    participle ("it's DONE"), a negation ("i DON'T remember the name"), or
    no verb at all ("NO EXCEPTIONS"). Tense, polarity and part of speech —
    nothing here is a list of remark phrases.
    """
    if any(c.dep_ == "neg" for c in tok.children):
        return False
    if tok.pos_ == "VERB" and tok.tag_ == "VB":
        return True
    if tok.pos_ in ("NOUN", "PROPN") and _is_command_verb(tok):
        return True                     # an imperative spaCy mis-tagged as a noun
    for c in tok.children:
        if (c.dep_ in ("xcomp", "ccomp") and c.pos_ == "VERB" and c.tag_ == "VB"
                and not any(g.dep_ == "neg" for g in c.children)):
            return True
    return False


def _subordinate_first_boundary(doc, tok, text: str) -> "Boundary | None":
    """The seam after a command clause spaCy subordinated to a LATER verb.

    "forget email the landlord, i'd rather walk the dog" parses `forget` as
    `advcl` of `walk` (the ROOT, eight tokens later); "first prepare the
    presentation, then let's get therapy session…" parses `prepare` as
    `advcl` of `let`. Two asks either way, and the walk over conj/dep
    never visits either — the subordinate clause has no coordinator tag
    at all. This reads the shape instead of a list of phrases ("i'd
    rather", "then let's"): the candidate must be a command verb that
    CARRIES ITS OWN ARGUMENT and sits BEFORE the verb it hangs off, and the
    main clause must carry one too.

    Three structural guards keep genuine subordinate clauses — which are
    NOT asks — from splitting off, each read from the parse, none from a
    word list:
      • it has no subject of its own — "when YOU get a chance, water the
        plants" is a time clause, and `get` is a command verb, so this is
        the guard that actually stands between it and a bogus split;
      • it has no subordinating `mark` — "IF it rains…", "BEFORE i leave…";
      • it is not an infinitival purpose clause — "call the plumber TO fix
        the sink" hangs `fix` off `call` with an infinitival `to`, one ask.
    And the MAIN clause has to be an ask too, not a remark about the first
    one — "check off this reminder, IT'S DONE", "move that one to next
    wednesday, I DON'T REMEMBER THE NAME", "book it every month at 7am, NO
    EXCEPTIONS" all parse as exactly this shape (the command subordinated
    to a trailing comment), and splitting them cost 17 rows on the first
    measurement. `_reads_as_an_ask` tells them apart by tense, negation
    and part of speech — read off the parse, not off the words.
    And, as everywhere in this module, something must JOIN the two — a
    comma, a "then" — or there is no seam: a subordinate clause with
    nothing between it and its head is inside the same breath.
    """
    head = tok.head
    if head.i <= tok.i:
        return None                     # a trailing advcl is a tail, not a first ask
    if tok.tag_ != "VB":
        return None                     # not an imperative/base form ("book MOVING day…")
    kids = list(tok.children)
    if any(c.dep_ in ("nsubj", "nsubjpass", "csubj") for c in kids):
        return None
    if any(c.dep_ == "mark" for c in kids):
        return None
    if any(c.dep_ == "aux" and c.tag_ == "TO" for c in kids):
        return None
    if not any(c.dep_ in _OWN_ARG for c in kids):
        return None
    if not any(c.dep_ in _OWN_ARG for c in head.children if c is not tok):
        return None
    if not _reads_as_an_ask(head):
        return None
    right = max(t.i for t in tok.subtree)
    if right >= head.i:
        return None                     # the subtree swallowed the main clause: parse not trusted
    j = right + 1
    while j < head.i and (doc[j].is_punct or doc[j].dep_ == "cc"
                          or doc[j].lower_ in _COORD_WORDS):
        j += 1
    if j == right + 1:
        return None                     # nothing joined them; not a seam
    ends_tok = doc[right]
    ends = ends_tok.idx + len(ends_tok.text)
    begins = doc[j].idx
    if begins <= ends:
        return None
    if (len(text[:ends].split()) < _MIN_WORDS_PER_ASK
            or len(text[begins:].split()) < _MIN_WORDS_PER_ASK):
        return None
    return Boundary(ends, begins, text[ends:begins].strip())


def has_clause_coordination(text: str) -> bool:
    """True when the parse shows two coordinated CLAUSES (two asks).

    NP-coordination ("Tal and Sam", "chicken and rice") returns False — those
    joins are part of one ask. See `clause_boundaries` for the reasoning; this
    is the same judgement reported as a yes/no for callers that only gate on it.
    """
    return bool(clause_boundaries(text))


def clause_boundaries(text: str, date_spans=None) -> "list[Boundary]":
    """Every place two coordinated CLAUSES meet, in order.

    This is the same judgement `has_clause_coordination` reports, but keeping
    the POSITION it found instead of discarding it. The check already had to
    locate the second clause to decide the question; throwing that away meant
    the project could DETECT compounds well (87.9% recall in the atomicity
    model) and still never SPLIT one — segment's deterministic tier looked for
    brackets and separators, which the phone inserts and speech never does, so
    it split nothing in 4,920 rows.

    Imperatives are the common shape, and spaCy tags an imperative's verb as
    the sentence ROOT with the second command attached as its VERB conjunct
    ("book the gym and remind me…" — remind is conj of book, both VERB). STT
    text is lowercase and unpunctuated, which spaCy's small model handles well
    enough for POS at this coarseness; the NOUN/PROPN check is the guard
    against splitting names.

    Under-split bias is preserved: a boundary is reported only for the
    signature below, and only when both halves survive `_MIN_WORDS_PER_ASK` —
    a wrongly merged item gets two more chances downstream, a wrongly split
    one becomes two garbage items immediately.
    """
    if not _COORDINATOR_RE.search(text):
        return []                    # no coordinator ⇒ no `conj` ⇒ nothing to see
    doc = parsed(text)
    if doc is None:
        return []
    OWN_ARG = _OWN_ARG
    found: list[Boundary] = []
    for tok in doc:
        # A command clause spaCy SUBORDINATED to a later verb — "FORGET email
        # the landlord, i'd rather walk the dog" hangs `forget` off `walk` as
        # `advcl` — never gets a conj/dep tag, so the walk below cannot see
        # it, and `_boundary_at` cannot cut it either (it assumes the head
        # precedes the conjunct; here it follows). Its own path, with its
        # own guards, in `_subordinate_first_boundary`.
        if tok.dep_ == "advcl" and _is_command_verb(tok):
            b = _subordinate_first_boundary(doc, tok, text)
            if b is not None and not _non_splitting_tail(text[b.begins:]):
                found.append(b)
            continue
        # "dep" is spaCy's I-don't-know label, and it is where a second
        # imperative lands when the joiner is a sequencer rather than a
        # coordinator — "call mom THEN pick up the dry cleaning" tags `pick`
        # dep, not conj, so the conj-only loop never saw it. It is admitted
        # only as a VERB, and everything below still has to hold.
        if tok.dep_ not in ("conj", "dep"):
            continue
        # On lowercase STT spaCy routinely tags a second imperative's VERB as
        # a noun COMPOUND of its own object — "…and then BOOK tennis lesson"
        # makes `book` a compound of `lesson`, and `lesson` the conjunct. The
        # verb gate below then rejects the whole clause because the conjunct
        # is a noun. Look through it: a command verb sitting as a compound
        # modifier IS the second ask's verb.
        verb = tok if (tok.pos_ in ("VERB", "AUX") or _is_command_verb(tok)) \
            else _compound_command_verb(tok) or _rescued_by_family(doc, tok)
        if verb is None:
            continue
        if tok.dep_ == "dep" and verb is not tok and tok.pos_ not in ("NOUN", "PROPN"):
            continue
        # The head's POS is UNRELIABLE on lowercase STT imperatives — spaCy
        # tags "book the gym…" ROOT as PROPN and "schedule lunch…" as a NOUN
        # compound — so the head's verb-ness must not be required. The
        # reliable second-ask signature (measured on the canonical cases) is:
        #   • the conjunct IS a verb, AND carries its own argument
        #     ("remind ME", "delete THE GYM SESSION"), AND
        #   • the head carries its own content too ("book THE GYM",
        #     "lunch WITH MARK") — a bare head sharing the conjunct's object
        #     ("wash and fold the laundry") is a serial verb, one ask.
        if verb is tok and tok.pos_ not in ("VERB", "AUX") and not _is_command_verb(tok):
            # the conjunct side suffers the same lowercase mis-tag ("…and
            # book a haircut" tags book NOUN): the domain's own verb
            # inventory (INTENT_MAP) resolves what POS cannot — but only a
            # conjunct WITH its own arguments below counts, so a bare name
            # that collides with a verb ("…with Tal and Mark") stays safe.
            continue
        # F15 (corrected): a SERIAL VERB shares the head's object — "wash
        # and fold THE LAUNDRY", "clean and organize THE GARAGE" — one ask.
        # The tell is positional, not the mere absence of an object: the
        # conjunct has no object of its own AND the head's object sits
        # AFTER the conjunct, i.e. both verbs govern the same later noun.
        # (The first cut just required a dobj on the conjunct, which also
        # blinded the check to real compounds — violations rose 100→141.)
        conj_obj = [c for c in tok.children if c.dep_ in ("dobj", "obj", "ccomp", "xcomp")]
        if not conj_obj:
            head_obj = [c for c in tok.head.children
                        if c.dep_ in ("dobj", "obj") and c.i > tok.i]
            if head_obj:
                continue          # shared object → serial verb → one ask
        # A DATE hanging off the conjunct is not an object of it — "…and DREW
        # this coming saturday" attaches "saturday" to `Drew` as npadvmod,
        # and counting that as an argument was the one thing that over-split
        # an attendee list (ARCHITECTURE.md §0, the `Drew` row).
        conj_has_own = any(c.dep_ in OWN_ARG and not _is_date_argument(doc, c)
                           for c in tok.children)
        # When the head is a DATE rather than a verb, spaCy has mis-attached
        # the second ask's object to the first clause — "…on friday and book
        # a haircut" hangs `book` off `friday` with no children at all, so
        # the argument test cannot see the object that is plainly there. A
        # determiner immediately after a command verb is that object opening,
        # and it is what separates "…and BOOK A haircut" from the name
        # collision "…with tal and MARK tomorrow", where no determiner follows.
        if not conj_has_own and _is_command_verb(tok) and tok.i + 1 < len(doc):
            nxt = doc[tok.i + 1]
            # …but a determiner opening a DATE is not an object — "with Reese
            # and Drew THIS coming saturday" is an attendee list whose second
            # name happens to be a past-tense verb, and "this saturday" is
            # when the one event happens, not what a second ask acts on.
            conj_has_own = (nxt.pos_ in ("DET", "PRON")
                            and not _opens_a_date(doc, nxt.i))
            # A BARE noun object opens one too, with no article at all —
            # "book eye exam", "book staff meeting", "add water the garden"
            # are all real objects, and English never articles a compound
            # like this ("book an eye exam" is the only spoken form, "book
            # the eye exam" implies one already discussed). Still gated on
            # `_opens_a_date` for the same reason as the DET branch, so
            # "…and MARK tomorrow" stays a name collision, not an object.
            if not conj_has_own and nxt.pos_ in ("NOUN", "PROPN"):
                conj_has_own = not _opens_a_date(doc, nxt.i)
            # The object may carry its own modifier first — "order NEW office
            # supplies", "book QUICK haircut" — and the noun is one or two
            # tokens further on. Looking only at the very next token missed
            # every one of these (the "intervening ADJECTIVE" bucket in
            # ARCHITECTURE.md §0). Skipped by POS, so this is not a list of
            # adjectives; `_opens_a_date` still reads from the modifier, the
            # same window it has always used.
            if not conj_has_own:
                k = tok.i + 1
                while k < len(doc) and doc[k].pos_ in ("ADJ", "ADV"):
                    k += 1
                if k > tok.i + 1 and k < len(doc) and doc[k].pos_ in ("NOUN", "PROPN"):
                    conj_has_own = not _opens_a_date(doc, tok.i + 1)
        # THE ASYMMETRY THIS CANCELS. The conjunct side above already discounts
        # a date argument (`_is_date_argument`, line ~327); the head side did
        # not. So "clean and organize the garage THIS AFTERNOON" is one ask —
        # the head `clean` owns nothing — while "THIS AFTERNOON clean and
        # organize the garage" is two, because the fronted phrase attaches to
        # `clean` as `npadvmod` and counts as its content. Same words, same
        # meaning, different number of asks, decided by word order.
        head_kids = [c for c in tok.head.children if c is not tok]
        head_has_own = any(c.dep_ in OWN_ARG for c in head_kids)
        if head_has_own and date_spans and not any(
                c.dep_ in OWN_ARG and not _is_edge_date_argument(c, text, date_spans)
                for c in head_kids):
            # The head's ONLY argument is the utterance's edge time phrase.
            # That alone is NOT enough to refuse a boundary — emptying the head
            # also makes "by tonight schedule a meeting with Quinn and buy
            # groceries" look headless, and collapsing that loses an ask the
            # speaker gave. Require the POSITIVE serial-verb signature as well:
            # the conjunct owns the clause's only object, so both verbs govern
            # it ("clean and organize THE GARAGE"). A head with an object of
            # its own is a second ask, whatever the time phrase is doing.
            # ANY real noun argument, not just `dobj`. `_OWN_ARG` has no
            # `nsubj`, and spaCy mis-tags a bare imperative's object as the
            # subject often enough to matter: "by tonight schedule A MEETING
            # with Quinn and buy groceries" parses `meeting` as `nsubj` of a
            # NOUN-tagged `schedule`. Checking `dobj` alone missed it, the gate
            # fired, and a two-ask command collapsed into one — measured
            # against the baseline, which split it correctly.
            head_owns_object = any(
                c.dep_ in ("dobj", "obj", "nsubj", "attr", "dative", "oprd",
                           "ccomp", "xcomp")
                and not _is_edge_date_argument(c, text, date_spans)
                for c in head_kids)
            if conj_obj and not head_owns_object:
                head_has_own = False
        if not head_has_own and tok.head.dep_ != "ROOT":
            # The conjunct hangs off a token buried INSIDE the first clause —
            # typically its date ("…on friday and book a haircut" makes
            # `friday` the head, whose only children are the coordinator and
            # the conjunct). The first ask's content sits upstream of that
            # head rather than under it, so the argument test cannot see it.
            # The serial-verb case this guard defends against ("wash and fold
            # the laundry") only arises when both verbs hang off the ROOT.
            head_has_own = True
        if conj_has_own and head_has_own:
            b = _boundary_at(doc, tok, text)
            if b is not None and not _non_splitting_tail(text[b.begins:]):
                # "book eye exam this weekend at late afternoon and remind me
                # two hours before" — "remind" is a real VERB conjunct here
                # (not a mis-tagged compound, so it never reaches the
                # fallback below, where this same guard already applies) but
                # the clause carries no object of its own: it is a LEAD TIME
                # on the event just booked, the identical idiom
                # `_lexicon_fallback_boundaries` and `fastseg.py`'s own
                # splitter both already refuse to split on. Anchored to the
                # rest of the TEXT rather than just this clause, same as the
                # fallback's own check — it only exempts a clause with
                # nothing after it, so a genuine third ask still splits.
                found.append(b)
    if not found:
        found = _lexicon_fallback_boundaries(doc, text, date_spans)
    return found


#: "remind me a day before", "notify me two hours before", "give me a heads
#: up 30 minutes before", "warn me a week before that" — a lead time on the
#: FIRST clause's own event, never a second ask by itself. Matched against a
#: candidate second clause's FULL text (`^...$`) rather than searched for,
#: because a clause that says MORE than this ("remind me to call the vet in
#: an hour" has its own object, "call the vet") is a real second ask that
#: happens to carry a lead-time-shaped tail, not this idiom.
_REMINDER_LEAD_RE = re.compile(
    r"^(?:(?:remind|notify|warn|alert)\s+me|give\s+me\s+a\s+(?:heads?\s+up|nudge))\s+"
    r"(?:\d+|a|an|half\s+an?|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:minutes?|mins?|hours?|days?|weeks?)?\s*"
    # A second, redundant lead-marker sometimes follows the first ("10
    # minutes before BEFOREHAND") — the generator's own idiom stacking,
    # same shape fastseg.py's `_LEAD_INTRANSITIVE` accepts for the identical
    # reason. Still anchored to the end: real content after either marker
    # is a genuine second ask, not this idiom.
    r"before\b(?:\s+(?:that|beforehand|ahead|prior|in\s+advance))?\s*$",
    re.I)


#: "change the due date of X to Y and ADD A NOTE" — a bare, object-less "add
#: a note" is an elaboration on the task just named, not a second ask (6/6 on
#: the corpus): there is nothing here to note ABOUT, so nothing for a second
#: item to be. "add a note that/about X" (a real object) is unaffected —
#: that is a genuine second ask.
_TRIVIAL_TAIL_RE = re.compile(r"^add\s+a\s+note\s*$", re.I)


def _non_splitting_tail(text: str) -> bool:
    """True when `text` (a candidate second clause) is one of the idioms
    that read as a VERB clause but are never a second ask by themselves —
    the shared gate for both the main walk and the lexicon fallback below."""
    t = text.strip()
    return bool(_REMINDER_LEAD_RE.match(t) or _TRIVIAL_TAIL_RE.match(t))


#: What an object can be before a verb's particle or the object proper —
#: "remind ME", "pick IT up" — skipped when looking past a verb for its
#: object.
_OBJ_PRONOUNS = frozenset({"me", "it", "that", "this", "them", "us", "him", "her"})


def _is_edge_date_argument(c, text: str, date_spans) -> bool:
    """Is this child ONLY the utterance's leading or trailing time phrase?

    Decided from the CALLER's spans, never from the parse, because the parse is
    what moves: "this afternoon" is `npadvmod` of the head when it is fronted
    and of the conjunct when it trails, which is the whole asymmetry this
    exists to cancel.

    EDGE, not merely "is a date". An INTERIOR daypart names a thing — "cancel
    the EVENING shiur", "set up the MORNING standup" — and must keep counting
    as the head's own content, or those rows stop splitting.
    """
    if not date_spans:
        return False
    start, end = c.idx, c.idx + len(c.text)
    n = len(text)
    for span_start, span_end in date_spans:
        if span_start <= start and end <= span_end and (span_start == 0 or span_end >= n):
            return True
    return False


def _is_date_argument(doc, c) -> bool:
    """Is this child of a verb a DATE rather than an object?

    Asked of the child ITSELF, not of what follows it — `_opens_a_date` is
    a forward scan built for the slot after a verb, and pointed at a verb's
    children it read "set up MOVING DAY for new year's eve" as three dates
    (the particle "up", because "day" sits two tokens on; "day", an event
    NAME that happens to contain a temporal word; and the prep, correctly).
    So: a preposition is a date if its object opens one ("ON saturday
    morning"); a nominal argument is a date if its own head is a temporal
    word or a short number ("this coming SATURDAY", "the 3RD") — unless a
    `compound` names it ("moving DAY", "game DAY"), which is a thing, not a
    when. Everything else a verb can govern (a particle, a clause, a
    dative) is never a date.
    """
    if c.dep_ == "prep":
        return _opens_a_date(doc, c.i + 1)
    if c.dep_ in ("npadvmod", "nmod", "dobj", "obj", "attr", "oprd", "appos"):
        if any(k.dep_ == "compound" for k in c.children):
            return False
        word = (c.lemma_ or c.text).lower()
        return word in _TEMPORAL_WORDS or bool(c.like_num and len(c.text) <= 4)
    return False


def _carries_an_object(doc, tok, end: int) -> bool:
    """Does this candidate verb ask for anything — carry an argument of its
    own that is not a DATE?

    The main walk always had this test; the lexicon fallback never did, and
    it showed the moment "meet" joined `INTENT_MAP`: "meeting with tal and
    MARK tomorrow" — `mark` is a name colliding with a verb, "meeting"
    (lemma "meet") is now a command verb, the families differ
    (create_event vs complete_todo), and nothing else stood in the way. A
    verb followed by a date word, or by nothing, asks for nothing.

    A date is never an object even when spaCy hangs it off the verb —
    "lunch with Reese and DREW this coming saturday" attaches "saturday"
    to `Drew` as `npadvmod`, which is in `_OWN_ARG`, and that one
    attachment was the whole reason this row over-split (ARCHITECTURE.md
    §0, filed 2026-09-16). Excluding date-opening children closes it.
    """
    if any(c.dep_ in _OWN_ARG and not _is_date_argument(doc, c) for c in tok.children):
        return True
    k = tok.i + 1
    while k < end and (doc[k].lower_ in _OBJ_PRONOUNS or doc[k].pos_ in ("ADJ", "ADV")):
        k += 1
    if k >= end or doc[k].is_punct:
        return False
    if doc[k].pos_ in ("DET", "PRON", "NOUN", "PROPN", "NUM"):
        return not _opens_a_date(doc, k)
    if doc[k].pos_ in ("ADP", "PART") and k + 1 < end:
        # "talk TO taylor", "head TO standup", "sign UP for the class" — a
        # preposition introduces an argument, unless that argument is a
        # date ("…and MARK on friday"), the same test a `prep` child gets.
        return not _opens_a_date(doc, k + 1)
    return False


def _inside(tok, spans) -> bool:
    """Does this token lie inside one of the caller's time spans?"""
    return any(s <= tok.idx and tok.idx + len(tok.text) <= e for s, e in (spans or ()))


def _lexicon_fallback_boundaries(doc, text: str, date_spans=None) -> "list[Boundary]":
    """When the walk above finds NOTHING — not one token, because spaCy
    swallowed the FIRST clause's verb into being a noun-phrase SUBJECT of
    the second clause rather than mis-tagging it as a stray compound.

    "schedule budget review for next week and add water the plants to my
    list" parses `review` as `nsubj` of `add` — the whole first clause reads
    as "[Scheduling a budget review] adds water the plants", nonsensical,
    and `schedule` never gets a `conj`/`dep` tag at all, so the main walk
    above has nothing to visit for it. Every downstream check in this
    module trusts a token's `.head`/`.subtree` because the walk above only
    ever widens what counts as a VALID conjunct signature; this is a
    different situation — there IS no conjunct signature, the parse itself
    lost the clause boundary.

    Ported from `rule_parser._lexicon_split_points` (FastRule's own,
    independently-proven fix for the identical spaCy failure, first found
    there) — WITH one addition that fix does not need: position alone
    ("sentence-initial, or right after a coordinator") is not enough here.
    "buy apples and water bottles" puts `water` in exactly that position
    too, and `water` is a real `INTENT_MAP` verb — position can find the
    NP-coordination false positive as easily as the real seam. What tells
    them apart is the same family-mismatch evidence `_rescued_by_family`
    already uses: `schedule` (create_event) and `add` (create_todo) differ,
    `buy` and `water` do not (both create_todo). Boundaries are cut by RAW
    TOKEN POSITION rather than `_boundary_at`'s subtree walk, because a
    mistagged token's own subtree is exactly the thing that cannot be
    trusted here.
    """
    points = []
    hard_boundary: set = set()
    for i, tok in enumerate(doc):
        if not _is_command_verb(tok):
            continue
        # A verb GOVERNED BY ANOTHER COMMAND VERB is that verb's object, not a
        # clause of its own: "add SCHEDULE a haircut to my list" names a to-do
        # whose title starts with a verb, "remind me TO BUY milk" wraps one.
        # And a preposition's object that asks for nothing ("to my LIST") is
        # not an ask either. Both were counted as clause points, which scoped
        # the real clause to a single word — `add`'s family was then read off
        # nothing, matched `schedule`'s, and the seam was refused. Only those
        # two shapes: a sentence-initial verb is trusted by POSITION, and
        # testing it for an object refused "MARK 'haircut' as done…" over the
        # quote mark that follows it (seven rows, measured).
        if tok.dep_ in ("dobj", "obj", "xcomp", "ccomp") and _is_command_verb(tok.head):
            continue
        if tok.dep_ == "pobj" and not _carries_an_object(doc, tok, len(doc)):
            continue
        # "remind me to X. also remind me to Y" is TWO spaCy sentences, not
        # one — the period is strong enough punctuation that its own
        # sentencizer splits there, and the second "remind" gets its OWN
        # ROOT rather than a conj/dep tag relative to the first. But the
        # sentence's OWN first token is "also" here, not "remind" — a plain
        # `tok.is_sent_start` check would miss it, so this walks back to the
        # sentence's start and accepts a run of coordinator words/punct
        # (`also`, `then`, ...) before the verb as still "sentence-initial",
        # same idea as `i == 0` but per-sentence instead of doc-wide.
        sent_start = tok.sent.start
        sentence_initial = all(
            doc[j].lower_ in _COORD_WORDS or doc[j].is_punct
            for j in range(sent_start, i))
        # The ROOT of a LATER sentence is sentence-initial whatever sits in
        # front of it — "along with that, REMIND me…", "on top of that, BOOK
        # the dentist" — because everything before a root inside its own
        # sentence is a dependent of that root (a fronted adverbial), not a
        # clause of its own. Read off the parse, so it needs no list of
        # tolerated lead-in phrases; the coord-word walk above stays for the
        # first sentence's own preamble, where there is no earlier sentence
        # to have ended.
        if tok.dep_ == "ROOT" and sent_start > 0:
            sentence_initial = True
        # The joiner may be separated from the verb by the second ask's OWN
        # date — "call the surveyor and ON FRIDAY book the valuation". The
        # caller already located every time phrase, so look back across it.
        j = i - 1
        while j >= 0 and _inside(doc[j], date_spans):
            j -= 1
        follows_coord = j >= 0 and (doc[j].dep_ == "cc"
                                    or doc[j].lower_ in _COORD_WORDS
                                    # A bare comma joins two asks only when a
                                    # date phrase was skipped to reach it:
                                    # "book the car wash, ON WEDNESDAY add the
                                    # client lunch". Alone it is NP-coordination
                                    # as often as a seam, and stays refused.
                                    or (j < i - 1 and doc[j].is_punct))
        if sentence_initial or follows_coord:
            points.append(tok)
            if sentence_initial and i > 0:
                # A MID-TEXT sentence boundary is punctuation-driven evidence
                # a coordinator position never has — English does not put a
                # sentence-ending period inside "buy apples and water
                # bottles". Strong enough to trust WITHOUT the family check
                # below, which exists for the weaker positions and would
                # otherwise block a real "remind me to X. also remind me to
                # Y" (same family on both sides, and rightly so).
                hard_boundary.add(tok.i)
    if len(points) < 2:
        return []
    out: list[Boundary] = []
    for idx in range(len(points) - 1):
        prev, nxt = points[idx], points[idx + 1]
        # Each verb's OWN clause only — the words from it to the next point
        # (or to the end, past the last point) — so one clause's "calendar"
        # can never resolve the other clause's qualifier.
        nxt_end = points[idx + 2].i if idx + 2 < len(points) else len(doc)
        if nxt.i not in hard_boundary:
            prev_words = {t.lower_ for t in doc[prev.i:nxt.i]}
            nxt_words = {t.lower_ for t in doc[nxt.i:nxt_end]}
            prev_family = _verb_intent_family(prev, prev_words)
            nxt_family = _verb_intent_family(nxt, nxt_words)
            if prev_family is None or nxt_family is None or prev_family == nxt_family:
                continue
        if not _carries_an_object(doc, nxt, nxt_end):
            continue                 # "…and MARK tomorrow": a name, not an ask
        if _non_splitting_tail(doc[nxt.i:nxt_end].text):
            # "book webinar sunday at 8:30pm and remind me two hours before"
            # IS a real family mismatch (book=event, remind=todo) and would
            # otherwise rescue clean — but the second clause is nothing BUT a
            # lead time on the FIRST clause's own event, not a second ask.
            # fastseg.py's own splitter already knows this shape (`timed()`,
            # "a LEAD TIME does not count... 20 rows of over-split the
            # moment lead times became visible") — same rule, this module's
            # own copy, since the two splitters never share one code path.
            continue
        # The second ask begins at its own date phrase when one sits between
        # the joiner and the verb ("…and ON FRIDAY book the valuation"): the
        # date belongs to the ask it introduces.
        opens = nxt.i
        j = nxt.i - 1
        while j > prev.i and _inside(doc[j], date_spans):
            opens = j
            j -= 1
        first = opens
        while j > prev.i and (doc[j].dep_ == "cc" or doc[j].lower_ in _COORD_WORDS
                              or doc[j].is_punct):
            first = j
            j -= 1
        if first == opens:
            continue                 # nothing joined them; not a real seam
        ends_tok = doc[first - 1]
        ends = ends_tok.idx + len(ends_tok.text)
        begins = doc[opens].idx
        if begins <= ends:
            continue
        if (len(text[:ends].split()) < _MIN_WORDS_PER_ASK
                or len(text[begins:].split()) < _MIN_WORDS_PER_ASK):
            continue
        out.append(Boundary(ends, begins, text[ends:begins].strip()))
    return out


def split_clauses(text: str, date_spans=None) -> "list[str]":
    """`text` cut into one string per ask — or `[text]` when it is one ask.

    The convenience segment wants: a caller that only needs the pieces should
    not have to know about offsets. Never returns an empty part, and never
    returns parts that lose words — the only thing dropped is the joiner.
    """
    bounds = clause_boundaries(text, date_spans=date_spans)
    if not bounds:
        return [text]
    parts, cursor = [], 0
    for b in bounds:
        piece = text[cursor:b.ends].strip(" ,;")
        if piece:
            parts.append(piece)
        cursor = b.begins
    tail = text[cursor:].strip(" ,;")
    if tail:
        parts.append(tail)
    return parts or [text]


def _boundary_at(doc, tok, text: str) -> "Boundary | None":
    """Character offsets around the coordinator that introduces `tok`.

    The second ask starts at the leftmost token of the conjunct's subtree
    (clamped to after the head, since a degenerate parse can hang an earlier
    token off it), and the coordinator is the run of joiner words and
    punctuation immediately before that. Both halves must be substantive or
    there is no boundary worth reporting.
    """
    left = min((t.i for t in tok.subtree), default=tok.i)
    left = max(left, tok.head.i + 1)
    if left >= len(doc) or left == 0:
        return None
    # The joiner is sometimes INSIDE the conjunct's subtree rather than before
    # it ("coffee with mark and then head to the office" hangs `then` under
    # `head`), which would leave the second ask opening with the word that
    # joined it. Walk the tail forward past any joiner run first.
    while (left + 1 < len(doc) and left <= tok.i
           and (doc[left].dep_ == "cc" or doc[left].lower_ in _COORD_WORDS
                or doc[left].is_punct)):
        left += 1
    # walk back over the joiner run: "and", ", and then", ";"
    first = left
    i = left - 1
    while i > tok.head.i and (doc[i].dep_ == "cc"
                              or doc[i].lower_ in _COORD_WORDS
                              or doc[i].is_punct):
        first = i
        i -= 1
    if first == 0 or first == left:
        # Nothing joined these two — no "and", no "then", not even a comma.
        # Speech always marks the seam between two asks, so a boundary with
        # no joiner is a cut through the middle of one ask, not between two.
        return None
    prev = doc[first - 1]
    ends = prev.idx + len(prev.text)
    begins = doc[left].idx
    if begins <= ends:
        return None
    head, tail = text[:ends], text[begins:]
    if (len(head.split()) < _MIN_WORDS_PER_ASK
            or len(tail.split()) < _MIN_WORDS_PER_ASK):
        return None                  # one-word half ⇒ parse artifact, not an ask
    return Boundary(ends, begins, text[ends:begins].strip())


#: Words that make a determiner phrase a DATE rather than an object —
#: "this saturday", "the 3rd", "that evening". Checked a few tokens past the
#: determiner because "this COMING saturday" puts a modifier in between.
_TEMPORAL_WORDS = frozenset(
    "monday tuesday wednesday thursday friday saturday sunday morning "
    "afternoon evening night noon midnight today tomorrow tonight yesterday "
    "week weekend month year day january february march april may june july "
    "august september october november december".split())


def _opens_a_date(doc, i: int) -> bool:
    """Does the phrase starting at token `i` name a time rather than a thing?

    Decided by the phrase's HEAD NOUN, not by any temporal word nearby: "a
    haircut for tuesday" is an object that happens to carry a date, while
    "this coming saturday" is the date itself. Scanning a fixed window instead
    conflates the two and blocks a real split.
    """
    for tok in doc[i:i + 5]:
        if tok.pos_ in ("NOUN", "PROPN", "NUM"):
            word = (tok.lemma_ or tok.text).lower()
            return word in _TEMPORAL_WORDS or bool(
                tok.like_num and len(tok.text) <= 4)   # "the 3rd"
    return False


#: The two dependency labels spaCy uses for "one noun modifying another,
#: sitting before it" on lowercase, unpunctuated STT text — "compound" and
#: "nmod" both show up for the exact same real relationship ("book annual
#: checkup" tags `book` as nmod of `checkup`; "book yoga class" tags `book`
#: as compound of `yoga`) and neither predicts the other. Checked against
#: the case this walk must never rescue ("buy apples and WATER bottles"):
#: `water` is `compound` there, never `nmod`, in every phrasing tried.
_CHAIN_LINK = ("compound", "nmod")


def _hidden_verb_in_chain(tok):
    """Walk `tok`'s COMPOUND CHAIN for a command verb, with NO gate on
    `tok`'s own head — the gate is `_compound_command_verb`'s job for its
    normal callers. Call this directly only when a DIFFERENT safety
    condition already stands in for it, as `_rescued_by_family` below does.

    The chain can be ONE level down: "book yoga class" parses as book
    compound-of yoga compound-of class (nested), not the flatter two-
    siblings shape of "book tennis lesson" (book and tennis both direct
    children of lesson) — spaCy picks whichever shape fits its own parse of
    the two-word object, and both are real, so both must be walked.
    """
    frontier = [tok]
    seen: set = set()
    while frontier:
        cur = frontier.pop()
        for child in cur.children:
            if child.dep_ not in _CHAIN_LINK or child.i >= tok.i or child.i in seen:
                continue
            seen.add(child.i)
            if _is_command_verb(child):
                return child
            frontier.append(child)
    return None


def _compound_command_verb(tok):
    """The command verb hiding as a compound modifier of `tok`, or None.

    "remind me to wash the car and then book tennis lesson" parses with
    `lesson` as the conjunct and `book` as its compound — the verb is there,
    just mis-tagged. Only a modifier BEFORE the noun counts, and only one from
    the parser's own verb inventory, so "tennis lesson" stays one thing.
    """
    if tok.pos_ not in ("NOUN", "PROPN"):
        return None
    # Only when the conjunct hangs off a VERB. "buy apples and WATER BOTTLES"
    # coordinates two objects of one verb — `bottles` is a conjunct of
    # `apples`, a plain noun object — and `water` being in the verb inventory
    # made a shopping list look like a second clause. NP-coordination is the
    # exact thing this module exists to refuse, so the rescue must not be able
    # to override it: a real second imperative attaches to the ROOT verb, not
    # to another verb's object.
    head = tok.head
    if head.pos_ not in ("VERB", "AUX") and head.dep_ != "ROOT":
        return None
    return _hidden_verb_in_chain(tok)


def _verb_intent_family(tok, words: "set | None" = None) -> "str | None":
    """This verb's own entry in `INTENT_MAP` ("create_event", "create_todo",
    ...) — the SAME table `_is_command_verb` already reads, reused rather
    than a second lexicon that could drift from it. `(word, None)` is the
    verb's general entry, and most verbs have one.

    A handful ("add") are keyed ONLY with a qualifier — `("add", "calendar")`
    and `("add", "todo")`, nothing unqualified — because the same word
    genuinely means two different things ("add it to my calendar" vs. "add
    it to my list"). `words` (the clause's own words, lowercased — the
    caller's to scope, so one clause's "calendar" cannot resolve the OTHER
    clause's "add") is checked against the same `_CALENDAR_SIGNALS` /
    `_TODO_SIGNALS` sets `_route_intent` resolves a verb's domain from,
    before falling back to whichever qualified entry the table happens to
    list first — which is a guess, not a resolution.
    """
    from assistant.intent.rule_parser import INTENT_MAP, _CALENDAR_SIGNALS, _TODO_SIGNALS
    word = (tok.lemma_ or tok.text).lower()
    direct = INTENT_MAP.get((word, None))
    if direct is not None:
        return direct
    if words:
        if words & _CALENDAR_SIGNALS:
            qualified = INTENT_MAP.get((word, "calendar"))
            if qualified is not None:
                return qualified
        if words & _TODO_SIGNALS:
            qualified = INTENT_MAP.get((word, "todo"))
            if qualified is not None:
                return qualified
    return next((intent for (verb, _q), intent in INTENT_MAP.items() if verb == word), None)


def _rescued_by_family(doc, tok):
    """One more chance for a conjunct `_compound_command_verb` refused
    because its head isn't a VERB/AUX/ROOT — ordinarily NP-coordination,
    correctly, most of the time. But when a real command verb hides in its
    compound chain AND that verb names a DIFFERENT KIND of thing than the
    sentence's own root verb, the difference is evidence neither the POS
    tags nor the dependency tree could see on their own:

    "buy apples and water bottles" — root `buy` (create_todo), hidden
    `water` (create_todo) — SAME family, stays refused: exactly the case
    the head-gate exists to catch, now doubly guarded.
    "buy 3 bananas and book car service appointment" — root `buy`
    (create_todo), hidden `book` (create_event) — DIFFERENT family,
    rescued: `appointment`'s head is `bananas` (a NOUN, so the primary gate
    refuses), but nobody books an appointment made of car-service the way
    someone buys a bottle made of water.

    A SECOND rescue, same-family: "finalize the budget and text KAREN about
    the venue" — root `finalize`, hidden `text`, BOTH `create_todo` — family
    alone would refuse this too, but `tok` (what the hidden verb is a
    compound modifier OF) is a capitalised PROPER NOUN here, not a bare
    object like "bottles"/"water" — nobody "texts" a water bottle, and a
    verb hiding in a PERSON's name is evidence of a real second ask family
    matching cannot see, the same signal `fastseg.py`'s `_has_person_
    argument` already uses for the identical distinction one stage over.

    A verb outside `INTENT_MAP` (root OR hidden) rescues nothing — no
    family to compare means no evidence, not a guess.
    """
    if tok.pos_ not in ("NOUN", "PROPN"):
        return None
    root = next((t for t in doc if t.dep_ == "ROOT"), None)
    if root is None:
        return None
    root_family = _verb_intent_family(root)
    if root_family is None:
        return None
    hidden = _hidden_verb_in_chain(tok)
    if hidden is None:
        return None
    hidden_family = _verb_intent_family(hidden)
    if hidden_family is None:
        return None
    if hidden_family == root_family and tok.pos_ != "PROPN":
        return None
    return hidden


def _is_command_verb(tok) -> bool:
    """Is this token one of the parser's own routing verbs?"""
    from assistant.intent.rule_parser import INTENT_MAP
    word = (tok.lemma_ or tok.text).lower()
    return any(word == verb for verb, _ in INTENT_MAP)
