"""Choosing an event's category in the Mac editor — and teaching the labeller
only when a person actually chose (Gil, 2026-10-10: "when i manually add
events make sure the category ml model runs and tags it accordingly").

The category was assigned and could not be corrected in the editor, so the
learned labeller never heard where it was wrong: five Teach-tab rows were its
only real feedback. Driven by real key events and a click on Save, like
test_event_dialog_repeat.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt                                           # noqa: E402
from PyQt6.QtTest import QTest                                        # noqa: E402
from PyQt6.QtWidgets import QApplication, QComboBox, QDialogButtonBox  # noqa: E402

from assistant.calendar_ui.event_dialog import EventDialog            # noqa: E402
from assistant.db import CalendarDB                                   # noqa: E402

DAY = dt.date(2026, 10, 12)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    return CalendarDB(path=str(tmp_path / "cat.db"))


@pytest.fixture
def feedback(tmp_path, monkeypatch):
    """The label feedback file, scratched — what the labeller will train on."""
    from assistant.engine.label import feedback as fb
    path = tmp_path / "label_feedback.jsonl"
    monkeypatch.setattr(fb, "_feedback_path", lambda: path)

    def rows():
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
    return rows


def _category(dlg) -> QComboBox:
    return dlg.findChild(QComboBox, "event_category")


def _pick(combo: QComboBox, text: str) -> None:
    assert combo.findText(text) >= 0, f"{text!r} not offered"
    combo.setFocus()
    QTest.keyClicks(combo, text)
    QApplication.processEvents()
    assert combo.currentText() == text


def _save(dlg: EventDialog) -> dict:
    buttons = dlg.findChild(QDialogButtonBox)
    QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton)
    assert dlg.event_data is not None
    return dlg.event_data


def _new(db, title: str) -> EventDialog:
    dlg = EventDialog(default_date=DAY, default_time=dt.time(9, 0), db=db)
    dlg.show()
    QTest.keyClicks(dlg.findChild(type(dlg._title), "title_input"), title)
    return dlg


def test_a_new_event_starts_on_automatic_and_the_labeller_decides(app, db, feedback):
    dlg = _new(db, "walk my dog")
    assert _category(dlg).currentText() == "Automatic"
    data = _save(dlg)
    assert "category" not in data and "category_explicit" not in data
    eid = db.create_event_from_dict(data)
    assert db.get_event(eid)["category"] == "Dog walking"      # the rules, 2026-10-10
    assert feedback() == [], "an automatic category is not the user's label"


def test_a_category_picked_for_a_new_event_is_kept_and_taught(app, db, feedback):
    dlg = _new(db, "Army ceremony")
    _pick(_category(dlg), "Social")
    data = _save(dlg)
    assert data["category"] == "Social" and data["category_explicit"] is True
    eid = db.create_event_from_dict(data)
    assert db.get_event(eid)["category"] == "Social"
    rows = feedback()
    assert len(rows) == 1
    assert rows[0]["text"] == "Army ceremony" and rows[0]["label"] == "Social"
    assert rows[0]["origin"] == "explicit"


def test_changing_an_existing_events_category_is_a_correction(app, db, feedback):
    eid = db.create_event_from_dict({"title": "visit the statue of liberty", "date": DAY.isoformat(),
                                     "start_time": "10:00", "end_time": "12:00"})
    event = db.get_event(eid)
    assert event["category"] == "Family"                         # what the rules said
    dlg = EventDialog(event=event, db=db)
    dlg.show()
    assert _category(dlg).currentText() == "Family"              # shows what it IS
    _pick(_category(dlg), "Travel")
    data = _save(dlg)
    assert data["category"] == "Travel" and "category_explicit" not in data
    db.update_event(eid, **{k: v for k, v in data.items() if k != "id"})
    assert db.get_event(eid)["category"] == "Travel"
    rows = feedback()
    assert [(r["text"], r["was"], r["label"], r["origin"]) for r in rows] == [
        ("visit the statue of liberty", "Family", "Travel", "correction")]


def test_editing_something_else_sends_no_category(app, db, feedback):
    eid = db.create_event_from_dict({"title": "Dinner with Dana", "date": DAY.isoformat(),
                                     "start_time": "19:00", "end_time": "21:00"})
    dlg = EventDialog(event=db.get_event(eid), db=db)
    dlg.show()
    data = _save(dlg)
    assert "category" not in data, "an untouched category must not travel"
    db.update_event(eid, **{k: v for k, v in data.items() if k != "id"})
    assert feedback() == []


def test_a_copy_or_undo_carrying_a_category_teaches_nothing(app, db, feedback):
    """Duplicate, undo and restore re-create rows with the category they had —
    nobody just chose it, so it must not be filed as a label."""
    db.create_event_from_dict({"title": "Army ceremony", "date": DAY.isoformat(),
                               "start_time": "08:00", "end_time": "20:00", "category": "Study"})
    assert feedback() == []


# --- the phone's editor: the same rules over HTTP ----------------------------

@pytest.fixture
def client():
    import assistant.api.server as server
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _body(**extra):
    return {"title": "Army ceremony", "date": DAY.isoformat(),
            "start_time": "08:00", "end_time": "20:00", **extra}


def test_the_phones_pick_on_a_new_event_is_taught(client, feedback):
    r = client.post("/events", json=_body(category="Social", category_explicit=True))
    assert r.status_code == 201
    assert [(x["label"], x["origin"]) for x in feedback()] == [("Social", "explicit")]


def test_a_posted_category_without_the_mark_teaches_nothing(client, feedback):
    """Offline replays and copies post a category nobody just chose."""
    assert client.post("/events", json=_body(category="Social")).status_code == 201
    assert feedback() == []


def test_a_category_changed_from_the_phone_is_a_correction(client, feedback):
    eid = client.post("/events", json=_body()).get_json()["id"]
    assert client.patch(f"/events/{eid}", json={"category": "Social"}).status_code == 200
    assert [(x["label"], x["origin"]) for x in feedback()] == [("Social", "correction")]


def test_the_phone_editor_sends_a_category_only_when_changed():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "MACalendar-iOS" / "MACalendar-iOS"
           / "Features" / "Calendar" / "EventDetailView.swift").read_text()
    assert 'Picker("Category", selection: $category)' in src
    assert 'Text("Automatic").tag("")' in src
    assert 'if !category.isEmpty && category != initialCategory {' in src
    assert 'if isNew { fields["category_explicit"] = true }' in src
