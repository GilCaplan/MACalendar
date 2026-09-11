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
    # now the store is known — but the parse reads it as a CREATE, which
    # disagrees. The lookup must CONFIRM a parse, never merely permit one.
    r = fastrule.run("rename flu shot to sales call")
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
