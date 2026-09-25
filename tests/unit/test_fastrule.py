"""FastRule — the selective classifier's gates, unit-level (no LLM).

The three gate tests that belonged to `Gatekeeper` moved to
`test_engine_llmjudge.py` with it in the 2026-09-09 port.

conftest.py has already pointed every store at scratch before this import.
"""
import pytest
from freezegun import freeze_time

from assistant.engine.fastrule.fastrule import FastRule


@pytest.fixture
def fastrule(registry_with_real_actions):
    # the autouse isolated_registry empties the action registry; intents are
    # built from it, so FastRule needs the real actions restored
    return FastRule(0.80)


def test_f4b_marking_a_date_never_completes_a_task(fastrule):
    """"mark 13 october as my birthday" marks a DAY; it fast-committed
    complete_todo at 0.95 (would tick off an unrelated task). Now it must
    never commit a complete_* — abstaining to deep is the accepted outcome."""
    r = fastrule.run("mark 13 october of this year as my birthday")
    assert not any(n.startswith("complete_") for n, _ in r.intents)
    # F15 improved the outcome: it now COMMITS this as an all-day event
    # (a dated create with no spoken clock time). The rule being pinned is
    # "never tick a task off", not the old inability to handle it at all.
    if r.committed:
        assert r.intents[0][0] == "create_event"
    r = fastrule.run("mark groceries as done")
    assert r.committed and r.intents[0][0] == "complete_todo"


def test_f5_plain_and_clause_coordination_abstains(fastrule):
    """F5: a plain "and" joining two asks (no cue words) must defer — the
    regex gate only knows announced joiners. Names and lists never trip it.

    UPDATED 2026-09-18. The gate is `len(intents) <= 1 and has_clause_
    coordination(text)`: it fires when the parse got only HALF the command, which
    is the thing worth deferring. The subtractive title now titles both halves of
    "book the gym ... and remind me to buy milk", so the parse covers the whole
    compound and DEVQA Q13 applies — "a fast commit on a compound the parse fully
    covers is fine". Deferring a complete, correct answer would throw it away, and
    with no LLM reachable it would throw away the only answer.

    So the assertion changed from "defers" to "covers both asks". The gate itself
    is untouched, and the row below still proves it stays out of NP-coordination.
    Corpus evidence: non-atomic rows "covered (all asks present)" 299 -> 331 while
    HALF-EXECUTED moved only 72 -> 74.
    """
    r = fastrule.run("book the gym for tomorrow at 6 and remind me to buy milk")
    names = [n for n, _ in r.intents]
    assert any("event" in n for n in names) and any("todo" in n for n in names), \
        f"the parse must cover BOTH asks, got {names}"
    if not r.committed:
        assert r.reason == "clause-coordination"
    r = fastrule.run("schedule meeting with Tal and Sam tomorrow at 3pm")
    assert r.reason != "clause-coordination"  # NP-coordination: one event,
    # two guests - whatever else the parser decides, the F5 gate stays out



def test_f7_priority_setting_is_an_update(fastrule):
    """"set X as high priority" read as create at 1.00 — it's a structured
    update: match_title + priority, phrase-delimited."""
    r = fastrule.run("set pick up the dry cleaning as high priority")
    assert r.committed and r.intents[0][0] == "update_todo"
    it = r.intents[0][1]
    assert getattr(it, "new_priority", None) == "high"
    assert "dry cleaning" in (getattr(it, "match_title", "") or "")
    # the rename extractor must not read "as high priority" as a new name
    assert not getattr(it, "new_title", None)


def test_f10_mutation_phrases_delimit_multiword_titles(fastrule):
    """Noun-chunking drops multi-word titles in mutations; the phrase itself
    delimits them. Generic targets still abstain (the veto judges captures).

    NB the reschedule row said "to this weekend" until 2026-09-17. That is a
    RANGE, and a mutation on a day the speaker never named no longer commits
    (see `test_a_range_date_never_mutates_on_a_guess` below) — so the date is
    now an explicit one, which is what this test was always about. The phrase
    being tested is the delimiter, not the date.
    """
    assert fastrule.run("delete wedding rehearsal from my calendar").committed
    assert fastrule.run("reschedule haircut to friday").committed
    assert fastrule.run("mark walk the dog complete").intents[0][0] == "complete_todo"
    assert not fastrule.run("delete this event").committed


@freeze_time("2026-09-16")
def test_a_range_date_never_mutates_on_a_guess(fastrule):
    """Gil, 2026-09-17: ask instead of guessing — and where asking is not on
    offer because the act is destructive, decline.

    "this weekend" is a SPAN. Picking Saturday out of it and then deleting or
    moving a real record acts on a day the speaker never said, which the
    project already rules out ("deleting is destructive... guessing is not"
    the right answer). A CREATE with the same phrase is offered for
    confirmation instead — that path is `fast_propose`'s, since only it knows
    whether the client can render a prompt.
    """
    for text in ("reschedule haircut to this weekend",
                 "cancel therapy session this weekend",
                 "move the dentist to next week"):
        res = fastrule.run(text)
        assert not res.committed, f"{text!r} committed on a guessed day"
        assert res.reason == "range-date-target", f"{text!r} -> {res.reason}"

    from assistant.engine.fastrule.fastrule import REFUSAL, reason_class
    assert reason_class("range-date-target") == REFUSAL

    # ...and the range itself WAS read: the deep track inherits the day rather
    # than starting from a command with no date in it at all.
    res = fastrule.run("cancel therapy session this weekend")
    assert res.rule_result.range_dates == ["this weekend"]


def test_f11_model_tier_fires_only_where_rules_found_nothing(fastrule):
    """Q10: verbless/unseen phrasings route via the model tier at the
    inference-billed confidence; rule-covered commands are byte-identical."""
    # verbless remind-speak + occasion + date: rules find no verb to route,
    # both model margins clear the SAFE floors (2.5/1.5 — the dual-gate
    # tightening), so the model tier composes new×event
    r = fastrule.run("don't forget the parent teacher conference wednesday 5pm")
    assert r.committed and r.intents[0][0] == "create_event"
    # model-routed commits are billed as inference (the ×0.85 channel) —
    # never at rule-tier confidence. (Margins shift with refits; behavior,
    # not specific margins, is what this test pins.)
    r2 = fastrule.run("gym session friday 6pm")
    if r2.committed:
        assert r2.intents[0][0] == "create_event" and r2.confidence <= 0.9
    r = fastrule.run("book gym tomorrow at 7am")   # rules tier, unchanged
    assert r.committed and r.confidence > 0.9


def test_f16_lead_time_no_longer_eats_the_title(fastrule):
    """The lead-time strip lived only in decompose (a deep-track stage), so
    FastRule failed 100% of lead-time rows: "remind me 5 minutes before
    about X" routed a titleless todo. Shared now (intent/lead_time.py), and
    the pinned convention applies — a clock-timed reminder is an EVENT."""
    r = fastrule.run("remind me 5 minutes before about product demo tonight at 7pm")
    assert r.committed and r.intents[0][0] == "create_event"
    assert fastrule.run("remind me to buy milk").intents[0][0] == "create_todo"
    # "remind me in 5 minutes" IS the request, not a lead time on something else
    assert not fastrule.run("remind me in 5 minutes").committed


def test_f16_marking_a_day_is_a_calendar_create(fastrule):
    """"mark/label ‹when› … as ‹occasion›" was 36% of committed-but-wrong
    atomic rows (routed complete_todo / update_event / query_schedule).
    Completions must be unaffected."""
    assert fastrule.run("mark march 5th on my calendar as the tax deadline"
                        ).intents[0][0] == "create_event"
    assert fastrule.run("mark groceries as done").intents[0][0] == "complete_todo"


def test_f16_sentence_initial_calendar_verb_wins(fastrule):
    """"book sales call…" routed create_todo because the NOUN "call" was read
    as the verb. An imperative opening with book/schedule is a calendar
    create; reschedule stays an update (regression caught in F16)."""
    assert fastrule.run("book sales call this friday all day"
                        ).intents[0][0] == "create_event"
    assert fastrule.run("reschedule haircut to this weekend"
                        ).intents[0][0] == "update_event"


def test_f17_recurrence_is_a_slot_not_n_items(fastrule):
    """Gil's architecture call: a recurring command is ONE atomic item that
    repeats — db.create_event expands the series. FastRule never filled the
    slot, so "every monday" produced no cadence AND no date and deferred.
    The anchor is the soonest named day (the project's weekly-series rule)."""
    r = fastrule.run("book haircut every monday at 9am")
    assert r.committed and len(r.intents) == 1          # ONE item, not N
    intent = r.intents[0][1]
    assert intent.recurrence == "weekly"
    import datetime
    assert datetime.date.fromisoformat(intent.date).weekday() == 0   # a Monday
    # a cadence we do not support is ROUNDED, never invented
    assert fastrule.run("book yoga every other tuesday at 6pm"
                        ).intents[0][1].recurrence == "weekly"
    # non-recurring commands are untouched
    assert fastrule.run("book gym tomorrow at 7am").intents[0][1].recurrence is None
def test_f16_the_model_tier_is_consulted_on_a_multi_intent_parse(fastrule):
    """Layer 0 answers "one item or several", and a ≥2-intent parse is not
    an answer to that question.

    Until F16 the model tier sat behind `len(intents) <= 1`, so a compound
    the parser had split was reported ATOMIC — 110 of the layer's 195
    B-test misses. `judge` must now say compound there; what routing DOES
    about it is the next test's business.
    """
    from types import SimpleNamespace
    from assistant.engine.fastrule.fastrule import Atomicity
    two = [("create_event", SimpleNamespace()), ("create_todo", SimpleNamespace())]
    text = "book gym on tuesday at 7am and remind me to buy milk"
    assert Atomicity().judge(text, two) == "model-compound"


def test_f16_routing_commits_a_compound_the_parse_fully_covers(fastrule):
    """The atomicity ANSWER and the routing DECISION are separate (F16).

    A compound whose every ask the parser recovered is not half-executed by
    committing it — and deferring it loses the command outright when the
    LLM is unreachable. But "covers" means intent count ≥ asks: a three-ask
    sentence read as two intents drops one, which is the real harm.
    """
    from types import SimpleNamespace
    from assistant.engine.fastrule.fastrule import _parse_covers_the_compound
    two = [("create_event", SimpleNamespace()), ("create_todo", SimpleNamespace())]
    one = [("create_event", SimpleNamespace())]
    assert _parse_covers_the_compound(
        "model-compound", "book gym at 7. Also, add milk to my list", two)
    # three asks, two intents -> one ask lost -> defer
    assert not _parse_covers_the_compound(
        "model-compound",
        "book flu shot this morning, training session the 3rd, "
        "and remind me to call the plumber", two)
    # a single-intent parse never covers a compound
    assert not _parse_covers_the_compound(
        "model-compound", "book gym at 7 and remind me to buy milk", one)
    # the RULE verdicts are never carved out — they name a structure the
    # gates recognised, not a classifier's opinion
    assert not _parse_covers_the_compound(
        "strong-compound", "book gym at 7. Also, add milk to my list", two)


def test_f18_the_ambiguity_bucket_is_split_by_evidence(fastrule):
    """"and" in the middle with nothing else was ONE feature vector.

    235 B-train rows shared it — 160 atomic ("call Devon and Reese this
    sunday"), 75 compound ("take the medicine at midnight and 9:15") — so
    the margin floor could only buy or reject the whole pile. Two signals
    tell the sides apart: a WHEN on both sides of the joiner (two events),
    and "between X and Y" (a range, one ask).
    """
    from assistant.intent.classifier import AtomicityFeatures
    f = AtomicityFeatures()
    i_range = f.names.index("between-range")
    i_both = f.names.index("both-sides-time")
    v = f.extract("set up therapy session at around lunchtime and town hall at midnight")
    assert v[i_both] == 1.0 and v[i_range] == 0.0
    v = f.extract("take the medicine at midnight and 9:15")
    assert v[i_both] == 1.0, "bare H:MM and 'midnight' are times too"
    v = f.extract("set up open house between 2 and 4 this afternoon")
    assert v[i_range] == 1.0 and v[i_both] == 0.0
    v = f.extract("call Devon and Reese this sunday")
    assert v[i_both] == 0.0 and v[i_range] == 0.0, "one WHEN for the whole ask"


def test_stale_weights_are_refused_rather_than_silently_truncated(fastrule):
    """`scores` dots with zip, which truncates: a weights file fitted before
    a feature was added would keep answering, ignoring the new signals — a
    wrong answer with no error anywhere. Load must refuse it."""
    from assistant.intent.classifier import LogisticModel, AtomicityFeatures
    m = LogisticModel("atomicity", ("atomic", "compound"), AtomicityFeatures())
    short = [0.0] * (len(AtomicityFeatures()) - 2)
    m.load({"weights": {"atomic": short, "compound": short}})
    assert m.weights == {}
    assert m.predict("anything at all") == (None, 0.0)




@freeze_time("2026-09-20")   # a SUNDAY, which is what caught this
def test_an_update_that_changes_nothing_is_refused(fastrule):
    """CI runs on a different day, and that is how this surfaced.

    "reschedule haircut to this weekend" is refused as `range-date-target` six
    days a week. On a SUNDAY the recogniser stops calling "this weekend" a
    range — today IS the weekend — so `range_dates` is empty, that refusal
    cannot fire, and what committed was an `update_event` carrying a target and
    NO CHANGE AT ALL: no new date, no new time, nothing. It touched a real
    record to no purpose and reported success.

    The date guard had been doing this guard's job by accident. An update with
    every `new_*` slot empty is not an update, whatever the date did.
    """
    for text in ("reschedule haircut to this weekend",
                 "shorten standup by 30 minutes"):
        res = fastrule.run(text)
        assert not res.committed, f"{text!r} committed with nothing to change"
        assert res.reason == "no-change", f"{text!r} -> {res.reason}"

    from assistant.engine.fastrule.fastrule import REFUSAL, reason_class
    assert reason_class("no-change") == REFUSAL

    # ...and a real change is never refused as "no-change", on the same day.
    for text in ("move the dentist to friday", "rename gym to workout"):
        assert fastrule.run(text).reason != "no-change", f"{text!r} is a real change"
    assert fastrule.run("move the dentist to friday").committed
    # "rename gym to workout" is a real change too, but a rename abstains on
    # the fast path unless the user's own data says which store holds "gym"
    # (F7, `test_f7_rename_never_commits_a_create`). In the full suite an
    # earlier test may have stored a gym event, and then the gate's lookup
    # confirms the parse and it commits; alone, it defers as rename-misroute.
    # Either is the ruling; a no-change refusal never is.
    r = fastrule.run("rename gym to workout")
    assert r.reason in (None, "rename-misroute"), r.reason


# --- the dev-100 checkpoint's fast-path holes (2026-09-20) --------------------

def test_a_new_list_is_never_answered_with_a_query(fastrule):
    """"begin new list of lottery numbers", "open up a new list", "start a new
    list" all committed query_todos through the noun "list" in the router's
    any-token pass — a QUERY for a create. A noun with its own determiner or
    adjective is an object, not a command, so those rows defer now (what a
    new list creates is Gil's to rule); "schedule meeting" still routes."""
    for t in ("Begin new list of lottery numbers", "Open up a new list and add a Tab to the shopping list",
              "start a new list and add grocery shopping to today's to-do list."):
        r = fastrule.run(t)
        assert "query_todos" not in [n for n, _ in r.intents], (t, r.intents, r.reason)
    r = fastrule.run("schedule meeting tomorrow at 3pm")
    assert r.committed and r.intents[0][0] == "create_event"


def test_remind_me_about_of_when_is_a_calendar_entry_on_the_fast_path(fastrule):
    """The tagger's convention (`fastseg/kind.py`), now on the fast path too:
    "remind me about/of/when X" is an event, "remind me to <verb>" an errand
    unless clock-timed. "Remind me when it is lunchtime" was a to-do."""
    r = fastrule.run("Remind me when it is lunchtime")
    assert "create_todo" not in [n for n, _ in r.intents], r.intents   # defers (no date), never a to-do
    r = fastrule.run("remind me about the party tomorrow")
    assert r.committed and [n for n, _ in r.intents] == ["create_event"], r.intents
    r = fastrule.run("remind me of my dentist appointment in two hours")
    assert r.committed and [n for n, _ in r.intents] == ["create_event"], r.intents
    r = fastrule.run("remind me to buy milk")
    assert [n for n, _ in r.intents] == ["create_todo"], r.intents


def test_a_title_that_holds_the_joiner_is_not_a_covered_compound(fastrule):
    """The Q13 carve-out commits a compound the parse fully covers. A title
    that still contains "and then" is the proof it did not: "remind me when it
    is lunchtime, and then i need oranges added to my grocery list" committed
    'remind when it is lunchtime and then i' at 0.95."""
    from types import SimpleNamespace
    from assistant.engine.fastrule.fastrule import _parse_covers_the_compound
    text = "remind me when it is lunchtime, and then i need oranges added to my grocery list"
    good = [("create_event", SimpleNamespace(title="lunchtime")),
            ("create_todo", SimpleNamespace(titles=["oranges"]))]
    bad = [("create_todo", SimpleNamespace(titles=["remind when it is lunchtime and then i"])),
           ("create_todo", SimpleNamespace(titles=["oranges"]))]
    assert _parse_covers_the_compound("model-compound", text, good)
    assert not _parse_covers_the_compound("model-compound", text, bad)


def test_note_and_date_are_the_programs_words_not_titles(fastrule):
    """"make a NOTE of it on the corresponding date" committed an event titled
    'note' at 0.86; the generic-title veto now names note and date."""
    r = fastrule.run("make a note of it on my calendar for march 25th")
    # The names-something gate (Q26) now removes 'note of it' in the PARSER,
    # so the refusal arrives as a missing title rather than a generic one.
    # Either way nothing is committed, which is what the veto is for.
    assert not r.committed, r
    assert r.reason.startswith("generic-title") or "title" in str(r.missing_slots), r


def test_a_meal_with_no_clock_lands_at_its_own_hour(fastrule):
    """Gil, 2026-09-20: "have default for breakfast/lunch/dinner as
    0900/1300/1900 if not given for an event." A dated meal with no spoken
    clock was an all-day block on the fast path and the clock-of-now on the
    deep one — the most common wrong row on the dev-100 board."""
    for text, hour in (("book dinner reservations on the 26th", "19:00"),
                       ("book breakfast with sam tomorrow", "09:00"),
                       ("book team lunch on friday", "13:00")):
        r = fastrule.run(text)
        assert r.committed and r.intents[0][1].start_time == hour, (text, r.intents)
    # a stated clock always wins
    assert fastrule.run("book dinner tomorrow at 8pm").intents[0][1].start_time == "20:00"
    # the speaker asking for the whole day keeps the block
    r = fastrule.run("book all day dinner party on the 26th")
    assert r.intents[0][1].start_time == "00:00" and r.intents[0][1].end_time == "23:59"
    # a non-meal takes the general untimed default, and "lunchbox" is not
    # lunch (09:00 since DEVQA Q36, 2026-09-20 — it was the all-day block
    # when this test was written the same morning)
    assert fastrule.run("book the dentist on the 26th").intents[0][1].start_time == "09:00"
    assert fastrule.run("book lunchbox shopping on the 26th").intents[0][1].start_time == "09:00"


def test_the_deep_track_reads_the_same_meal_hours():
    """Both tracks build CalendarIntent, so the untimed default lives there
    and cannot disagree between them."""
    from assistant.actions.calendar.intent import CalendarIntent, meal_hour
    assert meal_hour("dinner reservations") == "19:00"
    assert meal_hour("brunch") == "13:00" and meal_hour("supper") == "19:00"
    assert meal_hour("lunchbox shopping") is None and meal_hour("the dentist") is None
    assert CalendarIntent(title="dinner reservations", date="2026-09-26").start_time == "19:00"


def test_a_new_list_creates_a_general_todo_named_for_its_contents(fastrule):
    """Gil, 2026-09-20: a new list is a to-do in General titled with what
    follows. Until the router stopped reading the noun "list" as a command
    these committed `query_todos` — a QUERY for a create."""
    for text, title in (("start a new list of dog breeds", "dog breeds"),
                        ("Begin new list of lottery numbers", "lottery numbers"),
                        ("start a new list called groceries", "groceries")):
        r = fastrule.run(text)
        assert r.committed, (text, r.reason)
        name, intent = r.intents[0]
        assert name == "create_todo" and intent.titles == [title], (text, intent)
        assert intent.list_name == "general", intent.list_name
    # nothing to name it by: the generic-title veto, not a list called 'please'
    assert not fastrule.run("Create a new list, please").committed
    # an item FOR a list is not the making of one, and stays on Today
    r = fastrule.run("add milk to the new list")
    assert r.committed and r.intents[0][1].titles == ["milk"]
    assert r.intents[0][1].list_name == "today"


def test_a_bare_seven_is_asked_about_and_otherwise_read_as_pm(registry_with_real_actions):
    """DEVQA Q28, ruled 2026-09-20: "Ask the speaker when it is genuinely 7 or
    8." The same sentence used to be 19:00 on the fast path and 07:00 on the
    deep one. Now a client that can render a prompt is asked; one that cannot
    gets the fast path's long-standing PM reading on BOTH tracks, and the
    reply says so."""
    import assistant.engine as engine
    from assistant.engine.decompose_validate.resolve import bare_hour_is_ambiguous
    from freezegun import freeze_time
    from assistant.intent import rule_parser as RP

    assert bare_hour_is_ambiguous("book team meeting tomorrow at 7") == 7
    assert bare_hour_is_ambiguous("book standup at 8") == 8
    # settled by the words, so not genuinely ambiguous
    for t in ("book gym at 5", "at 7 in the morning", "at 8 o'clock",
              "at 7am", "at 7 pm", "dinner at 7", "at 7:30"):
        assert bare_hour_is_ambiguous(t) is None, t

    RP._ensure_nlp(); RP._ensure_dt()
    with freeze_time("2026-09-09 10:00:00"):
        E = engine.Engine()
        asked = E.run("book team meeting tomorrow at 7", source="test", supports_confirm=True)
        assert asked["parse"] == "confirm_create"
        assert "7 PM" in asked["message"], asked["message"]
        told = E.run("book team meeting tomorrow at 7", source="test", supports_confirm=False)
        assert told["parse"] == "fast" and "7 PM" in told["message"]
        assert "meant the morning" in told["message"], told["message"]
        # 1 to 6 keeps the settled convention, with no question and no note
        five = E.run("book gym at 5", source="test", supports_confirm=True)
        assert five["parse"] == "fast" and "meant the morning" not in five["message"]


def test_an_untimed_dated_event_is_nine_on_both_tracks(fastrule):
    """Gil, 2026-09-20 (DEVQA Q36). "book the dentist on the 26th" was an
    all-day block on the fast path and the clock-of-now on the deep one, so
    the same sentence got two answers and the deep one flagged the value it
    had invented itself. All-day is what the speaker ASKS for now."""
    from assistant.actions.calendar.intent import CalendarIntent
    r = fastrule.run("book the dentist on the 26th")
    assert r.committed and r.intents[0][1].start_time == "09:00", r.intents
    r = fastrule.run("book all day offsite on the 26th")
    assert r.intents[0][1].start_time == "00:00" and r.intents[0][1].end_time == "23:59"
    assert fastrule.run("book standup tomorrow at 8am").intents[0][1].start_time == "08:00"
    assert fastrule.run("book dinner reservations on the 26th").intents[0][1].start_time == "19:00"
    # the deep track builds the same object and must not differ
    assert CalendarIntent(title="dentist", date="2026-09-26").start_time == "09:00"
    assert CalendarIntent(title="dinner", date="2026-09-26").start_time == "19:00"


def test_a_fronted_lead_time_needs_its_ask_at_the_end():
    """"two hours before X, ping me" — the lead time in front and the ask it
    belongs to at the end (FastRule 7,200 train, 2026-09-25). Without the ask,
    "30 minutes before the talk" is when something happens, not a reminder."""
    from assistant.intent.lead_time import split
    assert split("two hours before conference call this morning at 8:30pm, ping me",
                 restore_verb=True, trailing=True) == ("book conference call this morning at 8:30pm", 120)
    assert split("retrospective monday at 11, give me a shout 30 minutes before",
                 trailing=True) == ("retrospective monday at 11", 30)
    said = "30 minutes before the talk i need to set up the room"
    assert split(said, trailing=True) == (said, None)
