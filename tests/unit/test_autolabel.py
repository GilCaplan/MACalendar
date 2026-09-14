"""Labels are the store's job, not each caller's.

Events have always been categorised inside `create_event_from_dict`, so an
event is labelled whichever surface made it. Tasks put the same job on every
CALLER, and the callers disagreed: the API and the GUI's quick-add inferred a
tag, calendar sync and the workout planner did not. Whether a task got a tag
depended on where it came from rather than on what it said — 14 of 89 tasks on
the real calendar were untagged, half of them plain grocery items.

These pin the rule that replaced that: the store fills in a label NOBODY chose,
and never overrules one that was.
"""

import pytest

from assistant.db import CalendarDB


@pytest.fixture
def db(tmp_path):
    return CalendarDB(path=str(tmp_path / "autolabel.db"))


def _event(db, title, color="#0078d4", date="2026-09-20", **kw):
    data = {"title": title, "date": date, "start_time": "10:00", "end_time": "11:00",
            "attendees": "", "location": "", "description": "", "color": color,
            "recurrence": "", "recurrence_end": ""}
    data.update(kw)
    return db.create_event_from_dict(data)


# --------------------------------------------------------------------- tasks

def test_caller_that_says_nothing_gets_a_tag(db):
    """`tags=None` means nobody chose — this is calendar sync, workout plans,
    the coursework view and the importer, all of which used to create untagged."""
    tid = db.create_todo(title="buy zucchini and canola oil")
    assert db.get_todo(tid)["tags"] == ["Groceries"]


def test_empty_list_means_deliberately_untagged(db):
    """`[]` is a decision, and the todo list's Untagged filter depends on it:
    adding a task while looking at Untagged must not tag it."""
    tid = db.create_todo(title="buy milk", tags=[])
    assert db.get_todo(tid)["tags"] == []


def test_a_chosen_tag_is_never_second_guessed(db):
    tid = db.create_todo(title="buy milk", tags=["Work"])
    assert db.get_todo(tid)["tags"] == ["Work"]


def test_no_tag_is_a_valid_answer(db):
    """A wrongly tagged task has to be undone by hand; an untagged one doesn't."""
    tid = db.create_todo(title="Chapter of MT")
    assert db.get_todo(tid)["tags"] == []


def test_renaming_an_untagged_task_labels_it(db):
    """How calendar sync renames a task when its event is renamed."""
    tid = db.create_todo(title="asdfgh")
    assert db.get_todo(tid)["tags"] == []
    db.update_todo(tid, title="buy pepsi and gatorade")
    assert db.get_todo(tid)["tags"] == ["Groceries"]


def test_renaming_a_tagged_task_keeps_its_tag(db):
    tid = db.create_todo(title="buy milk")
    assert db.get_todo(tid)["tags"] == ["Groceries"]
    db.update_todo(tid, title="finish the NLP homework")
    assert db.get_todo(tid)["tags"] == ["Groceries"]


# -------------------------------------------------------------------- events

def test_renaming_an_event_moves_its_category(db):
    eid = _event(db, "meeting")
    assert db.get_event(eid)["category"] == "Meeting"
    db.update_event(eid, title="nlp lecture")
    assert db.get_event(eid)["category"] == "Study"


def test_an_auto_colour_follows_the_new_category(db):
    """The colour written AT CREATION is this code's, not the user's.

    `_AUTO_COLORS` only recognises a colour nothing has touched, so without the
    palette check every categorised event looks hand-picked and a renamed event
    keeps the old category's colour for life.
    """
    from assistant.actions.calendar.categories import color_for

    eid = _event(db, "meeting")
    assert db.get_event(eid)["color"] in color_for("Meeting")
    db.update_event(eid, title="nlp lecture")
    assert db.get_event(eid)["color"] in color_for("Study")


def test_a_hand_picked_colour_survives_a_rename(db):
    """The category layer's standing invariant."""
    eid = _event(db, "meeting", color="#2fae5c")
    db.update_event(eid, title="nlp lecture")
    row = db.get_event(eid)
    assert row["category"] == "Study"
    assert row["color"] == "#2fae5c"


def test_an_explicit_category_is_not_reclassified(db):
    eid = _event(db, "meeting")
    db.update_event(eid, title="gym session", category="Work")
    assert db.get_event(eid)["category"] == "Work"


def test_editing_without_renaming_leaves_the_label_alone(db):
    eid = _event(db, "nlp lecture")
    before = db.get_event(eid)
    db.update_event(eid, start_time="14:00")
    after = db.get_event(eid)
    assert (after["category"], after["color"]) == (before["category"], before["color"])
