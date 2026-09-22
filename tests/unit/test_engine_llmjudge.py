"""LLMJudge — the intent-level vetoes, unit-level (no LLM).

This file was created by the 2026-09-09 PORT (`llmjudge/PLAN.md` §1.0): three
tests came here from `test_fastrule.py` with the code they pin. A guard without
its test is only half ported, so they moved in the same change.

They still drive `FastRule.run()` rather than `Gatekeeper.judge()` directly,
and deliberately so: during the port FastRule is still the caller, and a test
that changed what it exercises would stop being evidence that behaviour did not
move — which is the port's one acceptance condition. When phase B turns the
veto into prompt CONTEXT (§1.1), these become the tests that say what changed.

conftest.py has already pointed every store at scratch before this import.
"""
import pytest

from assistant.engine.fastrule.fastrule import FastRule


@pytest.fixture
def fastrule(registry_with_real_actions):
    # the autouse isolated_registry empties the action registry; intents are
    # built from it, so FastRule needs the real actions restored
    return FastRule(0.80)


def test_f4a_polite_imperative_is_not_a_question(fastrule):
    """"Can you create X" wants X created — the interrogative gate must not
    read the courtesy as a question. Real questions still abstain."""
    r = fastrule.run("Can you create a new list in my podcast?")
    assert r.committed and r.intents[0][0] == "create_todo"
    r = fastrule.run("Do I need to be reminded of any meetings on Monday?")
    assert not r.committed and r.reason == "interrogative-create"


def test_a_create_over_a_noun_list_defers_on_the_front_door(fastrule):
    """"create an event for dentist, haircut and gym" is three events (Gil,
    2026-09-20), and one event titled with the list is the wrong answer done
    instantly. The front door declines it as STRUCTURE and the deep track's
    judge rewrites it one clause per thing."""
    from assistant.engine.fastrule.fastrule import STRUCTURE, reason_class
    r = fastrule.run("on friday create an event for dentist, haircut and gym")
    assert not r.committed and r.reason == "list-title", r
    assert reason_class(r.reason) == STRUCTURE
    # attendees and pairs are one thing and never trip it
    assert fastrule.run("meeting with sam, alex and jordan on friday").committed
    assert fastrule.run("book wine and cheese evening on friday").reason != "list-title"


def test_f7_rename_never_commits_a_create(fastrule):
    """"rename flu shot to sales call" fast-committed create_todo at 0.95 —
    and FastRule can't know which store holds the old title anyway. Renames
    abstain; deep's matcher searches both stores."""
    r = fastrule.run("rename flu shot to sales call")
    assert not r.committed and r.reason == "rename-misroute"


def test_personalisation_is_lookup_not_training(fastrule):
    """Gil's principle: the shipped models stay generic and identical for
    every user; the personal part is the DATA they are pointed at. So a
    lookup against the user's own stores must (a) resolve what generic
    English cannot, and (b) never let a wrong parse through just because
    something was found."""
    from assistant.db import get_db
    from assistant.actions.calendar.intent import CalendarIntent

    # nothing in the stores: the rename cannot be resolved, so it defers
    r = fastrule.run("rename flu shot to sales call")
    assert not r.committed and r.reason == "rename-misroute"

    get_db().create_event(CalendarIntent(title="flu shot", date="2026-09-10",
                                         start_time="09:00", end_time="10:00"))
    # (a) now the store is known AND the parse agrees — the router reads the
    # leading imperative since 2026-09-20, so this is the update it is — and
    # the user's own data resolves what generic English cannot: it commits.
    r = fastrule.run("rename flu shot to sales call")
    assert r.committed and r.intents[0][0] == "update_event"

    # (b) the lookup must CONFIRM a parse, never merely permit one: the old
    # title lives in the OTHER store, so data and parse disagree — deferred.
    get_db().create_todo("sales report")
    r = fastrule.run("rename sales report to quarterly numbers")
    assert not r.committed, "a lookup must not launder a wrong parse"


def test_the_ported_code_lives_here_now(fastrule):
    """The port itself, pinned: these names resolve from `llmjudge`, and
    FastRule's redirect is the same object rather than a second copy.

    Two copies of a guard is the exact shape of the bug this project already
    paid for — the per-item path re-implemented the commit test with the gates
    omitted and re-committed what the front door had vetoed. A copy would have
    reintroduced that shape; this asserts it is a move.
    """
    from assistant.engine.fastrule import fastrule as fr
    from assistant.engine.llmjudge import llm_fallback as fo
    from assistant.engine.llmjudge import gatekeeper as gk
    from assistant.engine.llmjudge import llm_fallback as lf

    assert fr.Gatekeeper is gk.Gatekeeper
    assert fr._GENERIC_TARGET_RE is gk._GENERIC_TARGET_RE
    assert fo._guard_inventions is lf._guard_inventions
    assert fo._honour_refusal is lf._honour_refusal

    # …and the DEFER vocabulary deliberately did NOT move: it is FastRule's
    # product, with three other readers. A contract does not belong inside one
    # of its consumers.
    assert fr.REFUSAL == "refusal" and fr.reason_class("generic-target") == fr.REFUSAL
    assert not hasattr(gk, "REFUSAL"), "the reason-class contract stays in fastrule"


# ---------------------------------------------------------------------------
# A fast item's words are ITS words (reported by the review session, 2026-09-11)
# ---------------------------------------------------------------------------
#
# `fast_propose` built every fast item with `text=state.text`, so a two-ask
# command committed on the fast path produced two items both carrying the whole
# utterance. `_produced` tokenizes `it.text` into the set it matches asks
# against, so every ask overlapped every item and the matching went degenerate
# — on the ONE path that commits before it is checked.

def _fast_items(text, intents):
    """What `fast_propose` builds, without needing a rule parse to produce it."""
    from assistant.engine.fastrule.fast_track import _fast_item_words, kind_for as _kind_for
    from assistant.engine.state import EngineState, Item

    st = EngineState(raw_text=text, text=text)
    st.parse_path = "fast"
    st.items = [Item(id=f"item_{i + 1}", kind=_kind_for(name),
                     text=_fast_item_words(intent, text),
                     action=name, intent=intent)
                for i, (name, intent) in enumerate(intents)]
    return st


class _Made:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_two_fast_items_do_not_carry_the_same_words():
    st = _fast_items(
        "book gym tomorrow at 7 and remind me to buy milk",
        [("create_event", _Made(title="gym")),
         ("create_todo", _Made(title="buy milk"))])
    texts = [it.text for it in st.items]
    assert texts == ["gym", "buy milk"], texts
    assert len(set(texts)) == 2, "both fast items carry the same words"


def test_the_judge_can_tell_two_fast_items_apart():
    """The point of the fix, measured where the rebuilt judge still reads
    `item.text` (verdict.py:340 `title_dropped_the_verb`, :600 the title
    fallback when an intent names none) — `llmjudge._produced`'s old
    token-overlap check is gone with the RE-CUT judge (2026-09-10), but the
    field it was protecting is still live."""
    from assistant.engine.llmjudge import verdict

    st = _fast_items(
        "book gym tomorrow at 7 and remind me to buy milk",
        [("create_event", _Made(title="gym")),
         ("create_todo", _Made(title="buy milk"))])
    produced = verdict.collect(st)
    assert len(produced) == 2
    gym, milk = produced[0].item.text, produced[1].item.text
    assert gym != milk, "the two items present the same words to the judge"
    assert "milk" not in gym, "the gym item still claims the whole utterance"
    assert "gym" not in milk


def test_a_multi_title_todo_keeps_every_title():
    """One fast `create_todo` carries every title in ONE intent, and its
    capacity is titles×N — the words must cover all of them."""
    st = _fast_items("buy milk, eggs and bread",
                     [("create_todo", _Made(titles=["milk", "eggs", "bread"]))])
    assert st.items[0].text == "milk, eggs, bread"


def test_an_intent_that_names_nothing_keeps_the_whole_command():
    """A query has no title, and there the old behaviour was right."""
    st = _fast_items("what do i have on friday",
                     [("query_schedule", _Made())])
    assert st.items[0].text == "what do i have on friday"


# ---------------------------------------------------------------------------
# THE REBUILT JUDGE (2026-09-10, PLAN.md §6) — render / findings / verdict /
# rewrite. No model: `evidence.py` is the only piece that calls one, and it is
# faked here the way test_engine_crosscheck.py fakes it.
# ---------------------------------------------------------------------------

from types import SimpleNamespace                                    # noqa: E402

from assistant.actions.calendar.intent import CalendarIntent         # noqa: E402
from assistant.actions.todo.intent import CreateTodoIntent           # noqa: E402
from assistant.engine.llmjudge import findings as F                  # noqa: E402
from assistant.engine.llmjudge import render, rewrite, verdict       # noqa: E402
from assistant.engine.state import CheckFinding, EngineState, Item   # noqa: E402


@pytest.fixture
def cfg():
    import assistant.engine as engine
    return engine.load_config()


def _state(items, text="x"):
    st = EngineState(raw_text=text, text=text)
    st.items = items
    return st


# --- render: what an object SAYS -------------------------------------------

def test_slot_backing_agrees_with_the_converter():
    """`render.SLOT_BACKED` is the INVERSE of `build._VALUE_MAP`, restated
    rather than imported — `build.py`'s own convention for `VALUE_FIELDS`, so a
    change on that side turns this red instead of silently re-shaping which
    fields this stage believes are grounded."""
    from assistant.engine.fastrule.build import _VALUE_MAP
    for action, mapping in _VALUE_MAP.items():
        want = {attr: slot for slot, attr in mapping.items()}
        assert render.SLOT_BACKED.get(action, {}) == want, action


def test_defaults_nobody_spoke_are_not_claims(registry_with_real_actions):
    """`list_name="today"` and `priority="none"` are what the class fills in,
    not what the speaker said. Rendering them would invite the judge to ground
    a word that was never uttered."""
    labels = [c.label for c in render.claims(
        "create_todo", CreateTodoIntent(titles=["milk"]))]
    assert labels == ["title"]


def test_a_derived_end_time_is_not_a_claim(registry_with_real_actions):
    """`fill_defaults` makes every event end an hour after it starts. Claiming
    that would put one finding on every correct row, and a check that fires
    everywhere says nothing."""
    ev = CalendarIntent(title="gym", date="2026-09-14", start_time="07:00")
    assert ev.end_time == "08:00"                       # the class filled it
    assert "end_time" not in [c.label for c in render.claims("create_event", ev)]
    # …but a spoken end survives: "three to five" is not start + 1h.
    ev2 = CalendarIntent(title="gym", date="2026-09-14",
                         start_time="15:00", end_time="17:00")
    assert "end_time" in [c.label for c in render.claims("create_event", ev2)]


def test_each_title_is_its_own_claim(registry_with_real_actions):
    """"buy milk, eggs and bread" is three asks, so it is three claims — not one
    list-shaped one that a model can half-answer."""
    labels = [c.label for c in render.claims(
        "create_todo", CreateTodoIntent(titles=["milk", "eggs", "bread"]))]
    assert labels == ["title_1", "title_2", "title_3"]


def test_a_pydantic_filled_when_is_unsupported_by_the_slots(registry_with_real_actions):
    """The whole reason the temporal fields never reach the model: the object
    has a date and a start whether or not anybody said either, and `item.slots`
    is the only honest record of what was actually resolved."""
    ev = CalendarIntent(title="gym")                    # nothing said about when
    bad = [c.label for c in render.unsupported_by_slots("create_event", ev, {})]
    assert set(bad) == {"date", "start_time"}
    ok = render.unsupported_by_slots(
        "create_event", CalendarIntent(title="gym", date="2026-09-14"),
        {"date": "2026-09-14"})
    assert [c.label for c in ok] == ["start_time"]


def test_a_midnight_capped_end_is_still_a_derived_default(registry_with_real_actions):
    """`fill_defaults` caps an end that would cross midnight at "23:59"
    instead of rolling into the next day (`assistant/actions/calendar/
    intent.py::fill_defaults`), so a start hour of 23 with nothing said
    produces a 59-minute gap, not the usual 60. `_is_derived_end`'s exact
    "== 60" check missed this and reported the capped end as an EXTRA
    invented value on top of the start time it already is — for every event
    `fill_defaults` dates during the 23:00 hour, discovered when a routine
    test run at 23:18 local time turned up two "unrelated" failures that
    were really this one bug. Deterministic — sets start/end directly
    rather than depending on the real clock hitting 23:xx to reproduce."""
    ev = CalendarIntent(title="gym", start_time="23:00", end_time="23:59")
    bad = [c.label for c in render.unsupported_by_slots("create_event", ev, {})]
    assert set(bad) == {"date", "start_time"}          # end_time NOT extra

    # A genuinely different end (the speaker DID say something) must still
    # survive as its own claim — this guard must not swallow real values.
    said = CalendarIntent(title="gym", start_time="23:00", end_time="23:30")
    bad_said = [c.label for c in render.unsupported_by_slots(
        "create_event", said, {"end_time": "23:30"})]
    assert "end_time" not in bad_said                  # it's slot-backed, not invented


def test_the_judge_block_shows_only_word_claims(registry_with_real_actions):
    """Slot-backed claims are already decided; listing them would invite the
    model to re-decide an answer it cannot improve on."""
    ev = CalendarIntent(title="dentist", date="2026-09-14", start_time="15:00")
    block = render.render_block("obj_1", "create_event", ev,
                                {"date": "2026-09-14", "start_time": "15:00"})
    assert "    title = dentist" in block
    assert "\n    date =" not in block                  # header only, not a key


# --- findings: the router ---------------------------------------------------

def test_only_the_subject_earns_a_round():
    """A rewrite cannot invent a value nobody said, and an object nothing asks
    for is not made real by re-parsing. Both are the 2026-09-08 loop storm in
    code form — three dead rounds and a 30-second apology."""
    assert F.route(F.UNGROUNDED_SUBJECT) == F.REWRITE
    assert F.route(F.UNSUPPORTED_FIELD) == F.COMMIT_FLAGGED
    assert F.route(F.NOT_AN_ASK) == F.PANEL
    assert F.route("something new nobody routed") == F.PANEL   # fails to a human


def test_wants_rewrite_reads_the_table_not_the_type():
    made = [CheckFinding(type=F.UNSUPPORTED_FIELD, item_id="item_1",
                         detail="d", blamed_stage="decompose_validate")]
    assert not F.wants_rewrite(made)
    made.append(CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id="item_2",
                             detail="d", blamed_stage="fastrule"))
    assert F.wants_rewrite(made)
    assert [f.type for f in F.rewritable(made)] == [F.UNGROUNDED_SUBJECT]


# --- verdict: the deterministic half ---------------------------------------

def _ev_item(iid, title, text="", slots=None, blocked=None):
    return Item(id=iid, kind="event", text=text or title, action="create_event",
                intent=CalendarIntent(title=title, date="2026-09-14",
                                      start_time="09:00"),
                slots=dict(slots or {"date": "2026-09-14", "start_time": "09:00"}),
                blocked=blocked)


def test_a_blocked_item_is_never_called_spurious(registry_with_real_actions):
    """The observance gate ANSWERED that ask with an explained refusal. Treating
    it as unsupported sent every gated command into a loop that could not change
    a policy decision."""
    st = _state([_ev_item("item_1", "shiur", blocked="it falls inside Shabbat")],
                text="book shiur saturday")
    assert verdict.judge(st, verdict.collect(st)) == []


def test_a_mutation_is_never_called_spurious(registry_with_real_actions):
    """A mutation names an EXISTING record, so "the words do not support it" is
    a different question with a different answer — offering to undo a row the
    speaker asked to CHANGE would be worse than saying nothing."""
    it = Item(id="item_1", kind="event", text="move the dentist to six",
              action="update_event", slots={},
              intent=SimpleNamespace(match_title="dentist", title=None))
    st = _state([it], text="move the dentist to six")
    types = [f.type for f in verdict.judge(st, verdict.collect(st))]
    assert F.NOT_AN_ASK not in types


def test_a_field_the_model_never_answered_for_is_not_a_finding(registry_with_real_actions):
    """Absent is NOT `none`. A long list is where an 8B runs out of attention,
    and reading silence as a fabrication would flag correct objects for the
    model's stamina."""
    st = _state([_ev_item("item_1", "dentist")], text="book dentist monday 9am")
    assert verdict.judge(st, verdict.collect(st)) == []


def test_an_explicit_none_on_a_title_is_an_ungrounded_subject(registry_with_real_actions):
    """Identity and value split here, and the routes are why: committing an
    object whose subject the words never named puts a fabrication on the
    calendar — the cycle-7 defect."""
    st = _state([_ev_item("item_1", "physiotherapy")],
                text="book something for monday at nine")
    found = verdict.judge(st, verdict.collect(st))
    assert [f.type for f in found] == [F.UNGROUNDED_SUBJECT]
    assert F.route(found[0].type) == F.REWRITE


def test_a_generic_title_is_named_as_the_program_s_own_word(registry_with_real_actions):
    """Real usage, 2026-09-08: "Create an event now to go out for a run" gave
    the user an event called "event"."""
    st = _state([_ev_item("item_1", "Event")],
                text="create an event now to go for a run")
    found = verdict.judge(st, verdict.collect(st))
    assert found[0].type == F.UNGROUNDED_SUBJECT
    assert "the program's own word" in found[0].detail


def test_an_ungrounded_value_commits_instead_of_looping(registry_with_real_actions):
    """A retry cannot invent a location nobody said, so this one is told to the
    speaker rather than sent back around."""
    ev = CalendarIntent(title="gym", date="2026-09-14", start_time="09:00",
                        location="the roof")
    it = Item(id="item_1", kind="event", text="book gym", action="create_event",
              intent=ev, slots={"date": "2026-09-14", "start_time": "09:00"})
    st = _state([it], text="book gym monday at nine")
    found = verdict.judge(st, verdict.collect(st))
    assert [f.type for f in found] == [F.UNSUPPORTED_FIELD]
    assert F.route(found[0].type) == F.COMMIT_FLAGGED


def test_an_object_nothing_supports_goes_to_the_panel(registry_with_real_actions):
    """What survives of `extra` after the ask list went away, and a stronger
    test: not "the model's ask list didn't mention it" but "not one field of it
    can be pointed at in the transcript".

    It takes a SIBLING, since 2026-09-10. The only object built from a command
    is never spurious — the speaker asked for something and it was named wrong,
    which is a rewrite. Spurious means produced BESIDE the objects that answer
    the command, and that is the shape here: "call the plumber" is answered, and
    a physiotherapy appointment appears next to it.
    """
    good = Item(id="item_1", kind="task", text="call the plumber",
                action="create_todo", slots={},
                intent=CreateTodoIntent(titles=["call the plumber"]))
    it = Item(id="item_2", kind="event", text="physiotherapy",
              action="create_event", slots={},
              intent=CalendarIntent(title="physiotherapy"))
    st = _state([good, it], text="remind me to call the plumber")
    found = verdict.judge(st, verdict.collect(st))
    assert [f.type for f in found] == [F.NOT_AN_ASK]
    assert found[0].item_id == "item_2"
    assert F.route(found[0].type) == F.PANEL


def test_the_only_object_a_command_built_is_never_spurious(registry_with_real_actions):
    """THE DATE FLOOR, and the condition that had to come with fixing it.

    `slot_came_from_words` stopped a floor date from counting as grounding —
    without it `_not_an_ask` could not fire on ANY of 1,780 create objects
    measured through the real chain, because segmentation stamps
    `Item.time = "today"` and `decompose_validate` resolves it. But on its own
    that fix cost `invented_title` 98.8% -> 81.7%: every plain wrong title on a
    command that named no time became "nothing here is supported" and was
    offered to the user as something they never asked for.
    """
    it = Item(id="item_1", kind="event", text="physiotherapy",
              action="create_event", slots={},
              intent=CalendarIntent(title="physiotherapy"))
    st = _state([it], text="remind me to call the plumber")
    found = verdict.judge(st, verdict.collect(st))
    assert F.NOT_AN_ASK not in [f.type for f in found]
    # Reported field by field instead — the title nobody said, and the date and
    # clock `fill_defaults` stamped on an object with no slots.
    subject = [f for f in found if f.type == F.UNGROUNDED_SUBJECT]
    assert len(subject) == 1
    assert F.route(subject[0].type) == F.REWRITE
    assert all(f.type in (F.UNGROUNDED_SUBJECT, F.UNSUPPORTED_FIELD) for f in found)


def test_a_wrong_object_is_not_a_spurious_one(registry_with_real_actions):
    """The distinction the `not_an_ask` test has to keep: a good title with an
    invented time is a WRONG object, reported field by field and committed —
    not one the speaker never asked for."""
    it = Item(id="item_1", kind="event", text="call the plumber",
              action="create_event", slots={},
              intent=CalendarIntent(title="call the plumber"))
    st = _state([it], text="remind me to call the plumber")
    types = [f.type for f in verdict.judge(st, verdict.collect(st))]
    assert F.NOT_AN_ASK not in types
    assert types == [F.UNSUPPORTED_FIELD, F.UNSUPPORTED_FIELD]   # date + time


def test_a_fabricated_title_is_caught_without_a_model(registry_with_real_actions):
    """Cycle 1 measured `invented_title` caught 4/16 (25%) — the accept bias on
    our own 8B. A title with no word in the transcript needs no model."""
    it = _ev_item("item_1", "physiotherapy")
    st = _state([it], text="moving day on the 15th at nine, all day")
    found = verdict.judge(st, verdict.collect(st))
    assert [f.type for f in found] == [F.UNGROUNDED_SUBJECT]


def test_zero_overlap_still_answers_its_own_question(registry_with_real_actions):
    """`names_nothing_spoken` is unchanged and still guards `_not_an_ask`.

    It moved OUT of the identity check on 2026-09-10 and did not change: the
    question "can not one field of this be pointed at" is the one that
    authorises offering to REMOVE an object, and it must stay the weak reading.
    """
    assert verdict.names_nothing_spoken("physiotherapy", "gym saturday")
    assert not verdict.names_nothing_spoken("gym session", "gym saturday")
    assert not verdict.names_nothing_spoken("Meeting", "meet Tal at noon")


def test_a_near_miss_title_is_caught_by_its_unspoken_word(registry_with_real_actions):
    """THE CYCLE-14 TRADE, and this test is the record of it.

    This case used to assert the OPPOSITE — "gym session" from "gym saturday"
    was the one anecdote cycle 2 rejected the strict test on, and it was never
    priced. Priced on 7,640 titles the real chain produced from three corpora
    (`llmjudge/experiments/title_falseflag.py`), the strict test costs **0.18%**
    against zero-overlap's 0.00%, and all fourteen fires are one FastRule defect
    family (a misspelled time phrase left in the title). It buys
    `near_miss_title` 0% -> 100% on 63 planted cases.

    And the anecdote itself was fictional: asked for *"book gym saturday at
    nine"* the chain titles the event **"gym"**, never "gym session". FastRule
    does not pad titles with words nobody said, which is why the cost is 0.18%
    and not the double-digit figure the anecdote implied.
    """
    assert verdict.unspoken_word("gym session", "gym saturday") == "session"
    assert verdict.unspoken_word("gym", "book gym saturday at nine") is None
    # a title the speaker DID say, quote marks and all — the tokeniser defect
    assert verdict.unspoken_word(
        "team meeting", "remove 'team meeting' from my calendar") is None
    st = _state([_ev_item("item_1", "gym membership")],
                text="book gym session on tuesday at 7am")
    found = verdict.judge(st, verdict.collect(st))
    assert [f.type for f in found] == [F.UNGROUNDED_SUBJECT]
    assert "membership" in found[0].detail    # the evidence, not just a verdict


# --- rewrite: X1' and the guard --------------------------------------------

def test_the_rewrite_guard_rejects_words_the_speaker_never_said():
    """The recorded defect: X1' was built from `finding.detail` — the human
    EXPLANATION — and segmentation parsed the explanation."""
    raw = "book gym tomorrow at seven and milk eggs bread"
    assert rewrite.grounded("add milk to my list and add eggs to my list", raw)
    assert not rewrite.grounded(
        "the words ask for a task but nothing produced covers it", raw)


def test_the_rewrite_guard_allows_inflection_but_not_a_new_verb():
    """"reminder" grounds on "remind". "delete" grounds on nothing, and an
    operation word the speaker never said is the one thing a rewrite must never
    introduce."""
    assert rewrite.grounded("set a reminder for the run", "remind me to run")
    assert not rewrite.grounded("delete the run", "remind me to run")
    assert rewrite.grounded("add milk to my list", "milk eggs bread")
    assert not rewrite.grounded("cancel the milk", "milk eggs bread")


def test_no_rewritable_finding_means_no_rewrite(cfg):
    st = _state([], text="x")
    st.findings = [CheckFinding(type=F.UNSUPPORTED_FIELD, item_id="item_1",
                                detail="d", blamed_stage="decompose_validate")]
    assert rewrite.rewrite_for_retry(st, cfg) is None


def test_x1_is_built_from_the_failed_asks_with_no_model(registry_with_real_actions, cfg):
    """The chosen construction, and it calls nothing. Five were measured against
    each other (RESULTS.md §Cycle 11) and the LLM one came LAST — fewer asks
    recovered, more finished asks leaked back, and ten rows where the guard had
    to refuse what it wrote."""
    good = _ev_item("item_1", "gym", text="book gym")
    good.time = "tomorrow at 7am"
    bad = _ev_item("item_2", "milk", text="add milk to my list")
    st = _state([good, bad], text="book gym tomorrow at 7am and add milk to my list")
    st.raw_text = st.text
    st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id="item_2",
                                detail="d", blamed_stage="fastrule")]

    import assistant.engine.llm as engine_llm
    def _boom(*a, **k):
        raise AssertionError("the rewrite must not call a model")
    monkey = engine_llm.call_json
    engine_llm.call_json = _boom
    try:
        got = rewrite.rewrite_for_retry(st, cfg)
    finally:
        engine_llm.call_json = monkey
    assert got == "add milk to my list"
    assert "gym" not in got.lower(), "the finished ask came back"


def test_an_unchanged_x1_is_refused(registry_with_real_actions, cfg):
    """Segmentation is DETERMINISTIC, so re-entering it with the command we
    already tried returns the identical items. This is what happens when
    segmentation UNDER-SPLIT: the single item's words are the whole command,
    so there is nothing to carry forward and nothing to gain."""
    only = _ev_item("item_1", "gym", text="book gym tomorrow")
    st = _state([only], text="book gym tomorrow")
    st.raw_text = "book gym tomorrow"
    st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id="item_1",
                                detail="d", blamed_stage="fastrule")]
    assert rewrite.rewrite_for_retry(st, cfg) is None


def test_the_guard_still_catches_a_repaired_word_nobody_said(registry_with_real_actions, cfg):
    """Near-tautological now — the words come from the items, which came from
    the command — and kept because "near" is not "always": decompose_validate
    may repair an item's text, and a repair that invents a word must not reach
    segmentation unnoticed."""
    bad = _ev_item("item_1", "x", text="book physiotherapy")
    st = _state([bad], text="book the thing")
    st.raw_text = "book the thing"
    st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id="item_1",
                                detail="d", blamed_stage="fastrule")]
    assert rewrite.rewrite_for_retry(st, cfg) is None
    assert any(fx.rule == "rewrite_rejected" for fx in st.fixes)


def test_the_trim_is_done_in_CODE_not_asked_of_the_model(registry_with_real_actions):
    """The finished ask is CUT OUT of the string before the model sees it, so a
    succeeded object cannot come back — not because the prompt forbids it, but
    because its words are not in the input. Models are poor at negation, and the
    old version handed them exactly that job."""
    good = _ev_item("item_1", "gym", text="book gym tomorrow at 7am")
    good.source = "book gym tomorrow at 7am"
    bad = _ev_item("item_2", "Event", text="set an event")
    bad.source = "set an event"
    st = _state([good, bad], text="book gym tomorrow at 7am and set an event")
    st.raw_text = "book gym tomorrow at 7am and set an event"
    st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id="item_2",
                                detail="d", blamed_stage="fastrule")]
    left = rewrite.residue(st)
    assert "gym" not in left.lower(), left
    assert "set an event" in left.lower(), left
    assert not left.lower().startswith("and"), "the seam was left behind"


def test_a_shared_verb_survives_the_trim(registry_with_real_actions):
    """Removal is by SPAN, not by word set. Subtracting the finished ask's
    WORDS from "book gym and dentist" would take the shared verb with them and
    leave the survivor unparseable; a contiguous span cannot."""
    good = _ev_item("item_1", "gym", text="book gym")
    good.source = "book gym"
    bad = _ev_item("item_2", "dentist", text="book dentist")
    bad.source = "book dentist"
    st = _state([good, bad], text="book gym and book dentist")
    st.raw_text = "book gym and book dentist"
    st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id="item_2",
                                detail="d", blamed_stage="fastrule")]
    assert rewrite.residue(st).lower() == "book dentist"


def test_nothing_left_means_no_rewrite(registry_with_real_actions, cfg):
    """Every ask finished, so there is nothing to retry and no round to spend."""
    good = _ev_item("item_1", "gym", text="book gym")
    good.source = "book gym"
    st = _state([good], text="book gym")
    st.raw_text = "book gym"
    st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id=None,
                                detail="d", blamed_stage="fastrule")]
    assert rewrite.residue(st) == ""
    assert rewrite.rewrite_for_retry(st, cfg) is None


# --- the orchestrator's freeze-and-append ----------------------------------

def test_frozen_items_exclude_only_what_is_being_retried(registry_with_real_actions):
    from assistant.engine import _frozen_items
    st = _state([_ev_item("item_1", "gym"), _ev_item("item_2", "Event")])
    st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id="item_2",
                                detail="d", blamed_stage="fastrule"),
                   CheckFinding(type=F.NOT_AN_ASK, item_id="item_1", detail="d",
                                blamed_stage="segment")]
    # `not_an_ask` does not route to REWRITE, so it does not un-freeze item_1 —
    # only a rewrite-routed finding does.
    assert [it.id for it in _frozen_items(st)] == ["item_1"]


# --- the coordinated subject: one event over a list of things ---------------

def test_a_create_over_a_noun_list_is_a_coordinated_subject(registry_with_real_actions):
    """One create_event whose words list three things is three events, and
    the judge says so with a finding that REWRITES (Gil, 2026-09-20)."""
    it = _ev_item("item_1", "dentist, haircut and gym",
                  text="create an event for dentist, haircut and gym")
    st = _state([it], text="on friday create an event for dentist, haircut and gym")
    found = verdict.judge(st, verdict.collect(st))
    types = [f.type for f in found]
    assert F.COORDINATED_SUBJECT in types, types
    assert F.route(F.COORDINATED_SUBJECT) == F.REWRITE
    # a task over a list is segmentation's multiply, not this
    todo = Item(id="item_2", kind="task", text="buy milk, eggs and bread",
                action="create_todo", slots={},
                intent=CreateTodoIntent(titles=["buy milk, eggs and bread"]))
    st = _state([todo], text="buy milk, eggs and bread")
    assert F.COORDINATED_SUBJECT not in [f.type for f in verdict.judge(st, verdict.collect(st))]


def test_the_list_rewrite_is_one_clause_per_thing(registry_with_real_actions, cfg):
    """Gil's own example, 2026-09-20: given "on friday create an event for
    dentist, haircut and gym", X1' should be "on friday create an event for
    dentist and on friday create an event for haircut and on friday create an
    event for gym". Every word is the speaker's, so the grounding guard passes
    by construction, and " and " is the one seam segmentation cuts on."""
    it = _ev_item("item_1", "dentist, haircut and gym",
                  text="create an event for dentist, haircut and gym")
    it.time = "on friday"
    st = _state([it], text="on friday create an event for dentist, haircut and gym")
    st.raw_text = st.text
    st.findings = [CheckFinding(type=F.COORDINATED_SUBJECT, item_id="item_1",
                                detail="d", blamed_stage="segment")]
    assert rewrite.rewrite_for_retry(st, cfg) == (
        "on friday create an event for dentist and "
        "on friday create an event for haircut and "
        "on friday create an event for gym")


def test_an_injected_date_floor_stays_out_of_the_list_rewrite(registry_with_real_actions, cfg):
    """An untimed item carries the "today" floor in `time`; the speaker never
    said it, and a rewrite must not put it in their mouth — the tail goes
    back where it was instead."""
    it = _ev_item("item_1", "dentist, haircut and gym",
                  text="add dentist, haircut and gym to my calendar")
    it.time = "today"
    st = _state([it], text="add dentist, haircut and gym to my calendar")
    st.raw_text = st.text
    st.findings = [CheckFinding(type=F.COORDINATED_SUBJECT, item_id="item_1",
                                detail="d", blamed_stage="segment")]
    assert rewrite.rewrite_for_retry(st, cfg) == (
        "add dentist to my calendar and add haircut to my calendar and "
        "add gym to my calendar")


def test_a_list_becomes_three_events_end_to_end(registry_with_real_actions, cfg, monkeypatch):
    """The whole loop, no model: segmentation keeps the list as ONE event
    (Q14: a shared verb over a bare noun list is one item), the judge raises
    the coordinated subject, the rewrite re-enters segmentation with one
    clause per thing, and three events land on the Friday the speaker named.
    A second ask beside the list is frozen and kept."""
    import assistant.engine as engine
    from assistant.intent import rule_parser as RP
    from freezegun import freeze_time

    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    RP._ensure_nlp(); RP._ensure_dt()          # spaCy before the frozen clock
    with freeze_time("2026-09-09 10:00:00"):   # a Wednesday
        E = engine.Engine()
        st = EngineState(raw_text="on friday create an event for dentist, haircut and gym",
                         text="on friday create an event for dentist, haircut and gym")
        E.parse(st, cfg)
        assert len(st.items) == 1, [i.text for i in st.items]
        E.judge(st, cfg)
        events = [i for i in st.items if i.action == "create_event"]
        assert [i.intent.title.split()[-1] for i in events] == ["dentist", "haircut", "gym"]
        assert {i.intent.date for i in events} == {"2026-09-11"}
        assert st.retries == {"segment": 1}

        st = EngineState(raw_text="create an event for dentist, haircut and gym on friday and remind me to call mom",
                         text="create an event for dentist, haircut and gym on friday and remind me to call mom")
        E.parse(st, cfg)
        E.judge(st, cfg)
        assert sorted(i.action for i in st.items) == ["create_event"] * 3 + ["create_todo"]


# --- the unsplit subject and the model round of the rewrite -------------------

_TRASH = "Remind me every Monday to take out the trash. Also, PUT MILK ON MY SHOPPING LIST"


def test_a_seam_left_inside_one_object_is_an_unsplit_subject(registry_with_real_actions):
    """One built object whose own words still hold "and then" / ". Also," is
    two asks the cut left together. Deterministic; it is what reaches the
    model round, because no trim of those words can split them."""
    it = _ev_item("item_1", "open calendar",
                  text="open calendar set event and then create a list")
    st = _state([it], text="open calendar set event and then create a list")
    types = [f.type for f in verdict.judge(st, verdict.collect(st))]
    assert F.UNSPLIT_SUBJECT in types, types
    clean = _ev_item("item_1", "gym", text="book gym tomorrow at 7am")
    st = _state([clean], text="book gym tomorrow at 7am")
    assert F.UNSPLIT_SUBJECT not in [f.type for f in verdict.judge(st, verdict.collect(st))]


def _recorder(monkeypatch, answer):
    """A fake model: records the prompt it was given, answers with `answer`."""
    import assistant.engine.llm as _llm
    calls = []

    def fake(cfg, system, user, schema=None):
        calls.append((system, user, schema))
        if isinstance(answer, Exception):
            raise answer
        return answer, 7
    monkeypatch.setattr(_llm, "call_json", fake)
    return calls


def _unsplit_state(text=_TRASH):
    it = Item(id="item_1", kind="task", text=text, action="create_todo", slots={},
              intent=CreateTodoIntent(titles=["take out the trash. also"]))
    st = _state([it], text=text)
    st.raw_text = text
    st.findings = [CheckFinding(type=F.UNSPLIT_SUBJECT, item_id="item_1",
                                detail="“Remind me…” still holds two asks around “. Also”",
                                blamed_stage="segment")]
    return st


def test_the_model_writes_x1_as_a_list_and_code_joins_it(registry_with_real_actions, cfg, monkeypatch):
    """When the failed item's words ARE the command, the deterministic rewrite
    has nothing new, so the model is asked. It answers a LIST; the seams are
    put in by code as the ingest envelope, which segmentation opens before it
    reads any language — so the cut the model chose is the cut that happens."""
    calls = _recorder(monkeypatch, {"asks": ["remind me to take out the trash every monday",
                                             "add milk to my shopping list"]})
    st = _unsplit_state()
    got = rewrite.rewrite_for_retry(st, cfg)
    assert got == ('("remind me to take out the trash every monday")'
                   'and("add milk to my shopping list")'), got
    assert len(calls) == 1
    system, user, schema = calls[0]
    assert schema["properties"]["asks"]["type"] == "array"
    # the brief carries the words, the leftover, and what was tried with the
    # judge's complaint — the context Gil asked for
    assert f'THE SPEAKER SAID: "{_TRASH}"' in user
    assert "still holds two asks" in user
    assert 'take out the trash. also' in user           # what the last attempt produced
    assert "every monday" in system and "for the next three sundays" in system
    assert [fx.rule for fx in st.fixes] == ["rewrite_model"]
    assert st.fixes[0].before == _TRASH and st.fixes[0].after == got


def test_the_model_round_sees_every_earlier_attempt_and_never_repeats_one(registry_with_real_actions, cfg, monkeypatch):
    st = _unsplit_state()
    st.add_fix("llmjudge", "rewrite", before=_TRASH,
               after="remind me to take out the trash. also every monday and remind put milk on my shopping list",
               note="produced: task “take out the trash. also”; task “remind put milk on my shopping list” · judge: still holds two asks")
    st.text = "remind me to take out the trash. also every monday and remind put milk on my shopping list"
    # a model that hands back the attempt already made is refused
    calls = _recorder(monkeypatch, {"asks": [st.text]})
    assert rewrite.rewrite_for_retry(st, cfg) is None
    _, user, _ = calls[0]
    assert '1. "' + _TRASH + '"' in user and "2. \"remind me to take out the trash. also" in user
    assert "remind put milk on my shopping list" in user


def test_the_model_round_fails_closed(registry_with_real_actions, cfg, monkeypatch):
    """An invented word, an empty answer, or a model that is down: no rewrite,
    no loop — and each says why in the fix ledger."""
    st = _unsplit_state()
    _recorder(monkeypatch, {"asks": ["book dentist on friday", "add milk to my shopping list"]})
    assert rewrite.rewrite_for_retry(st, cfg) is None
    assert st.fixes[-1].rule == "rewrite_rejected"
    st = _unsplit_state()
    _recorder(monkeypatch, {"asks": []})
    assert rewrite.rewrite_for_retry(st, cfg) is None
    assert st.fixes[-1].rule == "rewrite_empty"
    from assistant.exceptions import OllamaUnavailableError
    st = _unsplit_state()
    _recorder(monkeypatch, OllamaUnavailableError("down"))   # what call_json raises when disabled
    assert rewrite.rewrite_for_retry(st, cfg) is None
    assert not st.fixes


def test_the_deterministic_rewrite_still_goes_first(registry_with_real_actions, cfg, monkeypatch):
    """Round one is the trim, no model: the coordinated list of 2026-09-20 is
    written by code exactly as before, and the model is not consulted."""
    _recorder(monkeypatch, AssertionError("the model must not be asked here"))
    it = _ev_item("item_1", "dentist, haircut and gym",
                  text="create an event for dentist, haircut and gym")
    it.time = "on friday"
    st = _state([it], text="on friday create an event for dentist, haircut and gym")
    st.raw_text = st.text
    st.findings = [CheckFinding(type=F.COORDINATED_SUBJECT, item_id="item_1",
                                detail="d", blamed_stage="segment")]
    got = rewrite.rewrite_for_retry(st, cfg)
    assert got.startswith("on friday create an event for dentist and ")
    assert [fx.rule for fx in st.fixes] == ["rewrite"]


def test_an_under_split_is_repaired_end_to_end_by_the_model_round(registry_with_real_actions, cfg, monkeypatch):
    """The whole loop on the checkpoint's own row: segmentation leaves ". Also,"
    inside one item, decompose_validate multiplies it into junk, the judge
    raises the unsplit subject, the deterministic round has nothing new, the
    model writes two lines, the envelope re-enters segmentation, and two clean
    objects come out."""
    import assistant.engine as engine
    from assistant.intent import rule_parser as RP
    from freezegun import freeze_time

    # A bare "and then" with no verb on its right: FastSeg leaves it to the
    # clause tier, which cannot cut it (". Also," is a hard seam now, so the
    # trash-and-milk row never reaches the judge — this one still does).
    T = "For the next three Sundays remind me I have yoga class at noon and then yashas bithday with vinay"
    _recorder(monkeypatch, {"asks": ["remind me of yoga class at 12pm for the next three sundays",
                                     "remind me of yashas birthday with vinay"]})
    RP._ensure_nlp(); RP._ensure_dt()
    with freeze_time("2026-09-09 10:00:00"):
        E = engine.Engine()
        st = EngineState(raw_text=T, text=T)
        E.parse(st, cfg)
        assert len(st.items) == 1, [i.text for i in st.items]
        E.judge(st, cfg)
        assert not any("and then" in i.text.lower() for i in st.items), [i.text for i in st.items]
        assert sum(1 for i in st.items if i.action == "create_event") == 2, [(i.text, i.action) for i in st.items]
        assert st.retries.get("segment", 0) >= 1
        assert any(fx.rule == "rewrite_model" for fx in st.fixes)


def test_the_model_round_never_repeats_a_finished_ask(registry_with_real_actions, cfg, monkeypatch):
    """The 8B writes a done ask again despite the prompt; re-entering it beside
    the frozen original built it twice on dev-100. Dropped in code."""
    done = Item(id="r1_item_2", kind="task", text="make next week's to-do list",
                action="create_todo", slots={}, intent=CreateTodoIntent(titles=["make 's to-do list"]))
    bad = Item(id="item_1", kind="event", text="make a list of thing I have to shop tomorrow",
               action="create_todo", slots={}, intent=CreateTodoIntent(titles=["milk", "eggs"]))
    raw = "make a list of thing I have to shop tomorrow and also i want to make next week's to-do list"
    st = _state([done, bad], text="make a list of thing I have to shop tomorrow")
    st.raw_text = raw
    st.findings = [CheckFinding(type=F.UNGROUNDED_SUBJECT, item_id="item_1", detail="milk", blamed_stage="fastrule")]
    st.add_fix("llmjudge", "rewrite", before=raw, after=st.text, note="produced: …")   # round 1 spent
    calls = _recorder(monkeypatch, {"asks": ["make a list of thing I have to shop tomorrow",
                                             "make next week's to-do list"]})
    assert rewrite.rewrite_for_retry(st, cfg) is None      # the only new line repeats the done ask; the other was tried
    assert "STILL TO DO: \"make a list of thing I have to shop tomorrow\"" in calls[0][1]


def test_a_transcript_typo_does_not_refuse_the_repair():
    """"bithday" in the transcript refused a correct "birthday" and with it the
    whole repair. One edit on a word of six letters or more is the speaker's
    word; short words and two edits are not."""
    assert rewrite.grounded("remind me of yashas birthday with vinay",
                            "yashas bithday with vinay ,vally")
    assert not rewrite.grounded("book sunday", "book monday")
    assert not rewrite.grounded("book thursday", "book tuesday")


# --- the exhaustion path holds back a subject that names nothing -------------

def test_a_subject_that_names_nothing_is_held_back_not_written(registry_with_real_actions, cfg, monkeypatch):
    """The fast path REFUSES "create an event now to go out for a run" because
    'event' is the program's word for a calendar entry. The judge had the same
    hole at the other end: it raised the finding every round, no rewrite could
    invent a subject nobody said, and it committed the object anyway — four
    dev-100 rows, one of them twice (2026-09-20)."""
    import assistant.engine as engine
    from assistant.intent import rule_parser as RP
    from freezegun import freeze_time

    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    RP._ensure_nlp(); RP._ensure_dt()
    # THE CONTRACT, not the mechanism. Cycle 28 asserted `item.blocked` set by
    # the judge's exhaustion path; since the names-something gate landed
    # (DEVQA Q26) the title never forms, so there is no object to hold back
    # and the refusal arrives earlier and cleaner. Either way: nothing is
    # written and the speaker is told which part could not be read.
    with freeze_time("2026-09-09 10:00:00"):
        E = engine.Engine()
        out = E.run("Could you add this on my calender please", source="test")
        assert not out["actions"], out["actions"]
        # Either honest refusal: the rescue naming the part it could not make
        # out, or the unknown-intent branch. Which one fires depends on
        # whether the model answered at all, so the CONTRACT is what is
        # pinned — nothing written, and the speaker told.
        assert ("couldn't" in out["message"]
                or "didn't understand" in out["message"]), out["message"]

        # a real subject still commits — a wrong title is fixable in one tap,
        # a missing event is not
        good = E.run("create an event now to go out for a run", source="test")
        assert good["actions"] == ["create_event"], good
        assert "go out for a run" in good["message"]


def test_a_pronoun_with_a_destination_names_nothing():
    """"add THIS ON MY CALENDER" titled an event 'this on my calender' and the
    judge raised nothing — every word WAS spoken. The anaphor is the subject
    and the rest is where to put it. 0 of the 7,200 gold titles and 0 of the
    3,000 real utterances have this shape."""
    from assistant.engine.llmjudge.gatekeeper import _GENERIC_TARGET_RE
    for t in ("this on my calender", "it to my list", "that for tomorrow", "this event",
              "note", "new list", "event of it", "this"):
        assert _GENERIC_TARGET_RE.match(t), t
    # Q42 (Gil, 2026-09-22): a bare kind commits — it is a name here too.
    for t in ("dentist", "go out for a run", "this weekend trip", "meeting with sam",
              "event", "an appointment", "the date", "reminder"):
        assert not _GENERIC_TARGET_RE.match(t), t


def test_a_held_back_object_is_not_recorded_as_done(registry_with_real_actions, cfg, monkeypatch):
    """The command memory feeds the review flows, the weekly board and the
    dataset scorer. A refused object recorded there says the assistant did
    something it told the speaker it had not — found 2026-09-20, the first
    run where anything was held back: the reply read "I didn't book 'this on
    my calender'" and the record carried a create_event for it."""
    import assistant.engine as engine
    from assistant.intent import rule_parser as RP
    from freezegun import freeze_time

    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    RP._ensure_nlp(); RP._ensure_dt()
    recorded = {}

    class _Mem:
        def record(self, **kw):
            recorded.update(kw)
            return 1
    import assistant.intent.memory as _memory
    monkeypatch.setattr(_memory, "get_memory", lambda: _Mem())

    with freeze_time("2026-09-09 10:00:00"):
        E = engine.Engine()
        T = "let's just skip appointment at time"
        st = EngineState(raw_text=T, text=T)
        E.parse(st, cfg)
        E.judge(st, cfg)
        for it in st.items:                  # force the case this test is about
            if it.intent is not None and it.action:
                it.blocked = "held back for the test"
                break
        else:
            raise AssertionError("no object was built, so this proves nothing")
        engine._record_memory(st, cfg, "msg", True)
    assert recorded["actions"] == [], recorded["actions"]


def test_a_bare_kind_with_nothing_else_said_is_not_a_finding(registry_with_real_actions):
    """Q42 (Gil, 2026-09-22): "Add an event for 5 p.m." commits an event
    called 'event' at 17:00 — the words held nothing else to call it. The
    sibling test above keeps the other half: when the words DO name the
    thing, the bare kind is a dropped subject and the loop rewrites it."""
    st = _state([_ev_item("item_1", "event")], text="add an event for 5 p.m.")
    found = verdict.judge(st, verdict.collect(st))
    assert not [f for f in found if f.type == F.UNGROUNDED_SUBJECT], found


def test_a_wrong_title_on_an_ask_that_was_said_is_a_rewrite_not_a_panel_item(registry_with_real_actions):
    """Cycle 41 (2026-09-22). Two asks; the first's title is a fabrication and
    the ask named no time, so not one FIELD of the object can be pointed at in
    the words — but the item it was built from was cut from them. The v2 set
    measured this answered `not_an_ask` (panel) a quarter of the time; the
    right finding is `ungrounded_subject` (rewrite)."""
    text = "remind me to confirm the eye exam and add call the plumber to my list"
    first = Item(id="item_1", kind="task", text="remind me to confirm the eye exam",
                 source="remind me to confirm the eye exam", action="create_todo",
                 intent=SimpleNamespace(title="polish the telescope lens", titles=["polish the telescope lens"]))
    second = Item(id="item_2", kind="task", text="add call the plumber to my list",
                  source="add call the plumber to my list", action="create_todo",
                  intent=SimpleNamespace(title="call the plumber", titles=["call the plumber"]))
    st = _state([first, second], text=text)
    found = verdict.judge(st, verdict.collect(st))
    on_first = [f for f in found if f.item_id == "item_1"]
    assert on_first and on_first[0].type == F.UNGROUNDED_SUBJECT, found


def test_an_object_whose_item_was_never_said_is_still_not_an_ask(registry_with_real_actions):
    text = "remind me to confirm the eye exam and add call the plumber to my list"
    real = Item(id="item_1", kind="task", text="remind me to confirm the eye exam",
                source="remind me to confirm the eye exam", action="create_todo",
                intent=SimpleNamespace(title="confirm the eye exam", titles=["confirm the eye exam"]))
    extra = Item(id="item_x", kind="event", text="polish the telescope lens", action="create_event",
                 intent=SimpleNamespace(title="polish the telescope lens"))
    st = _state([real, extra], text=text)
    found = verdict.judge(st, verdict.collect(st))
    on_extra = [f for f in found if f.item_id == "item_x"]
    assert on_extra and on_extra[0].type == F.NOT_AN_ASK, found
