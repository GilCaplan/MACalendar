"""The Mac's Fix… dialog, driven the way a person drives it.

Real clicks (this repo's rule: a UI test that never sends a mouse event tests
nothing). Gil, 2026-09-24: a six-part command showed one object in the fix
view, and there was no way to say nothing should have been done.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt                                           # noqa: E402
from PyQt6.QtTest import QTest                                        # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialogButtonBox            # noqa: E402

import assistant.engine as engine                                     # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _rules_only(monkeypatch, registry_with_real_actions):
    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    import assistant.engine.llm as _llm
    monkeypatch.setattr(_llm, "is_reachable", lambda cfg=None: True)


def _example(text):
    from assistant.intent import review
    out = engine.run_transcript(text, source="mac")
    return next(e for e in review.unreviewed() if e["id"] == out["memory_id"])


def test_every_object_gets_a_row(app):
    from assistant.calendar_ui.review_dialog import CorrectionDialog
    dlg = CorrectionDialog(_example("schedule a meeting tomorrow at 3pm and buy milk"))
    assert [w.row.action for w in dlg._widgets] == ["create_event", "create_todo"]


def test_nothing_should_have_been_done_then_save(app):
    from assistant.calendar_ui.review_dialog import CorrectionDialog
    dlg = CorrectionDialog(_example("schedule a meeting tomorrow at 3pm and buy milk"))
    QTest.mouseClick(dlg._nothing, Qt.MouseButton.LeftButton)
    assert all(w.row.choice == "undo" for w in dlg._widgets)
    save = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
    QTest.mouseClick(save, Qt.MouseButton.LeftButton)
    assert dlg.plan["feedback"] == "corrected" and dlg.plan["correction"] == []
    assert [op[0] for op in dlg.plan["ops"]] == ["delete_event", "delete_todo"]


def test_change_opens_the_editor_and_the_kind_can_flip(app):
    from assistant.calendar_ui.review_dialog import CorrectionDialog
    dlg = CorrectionDialog(_example("buy milk"))
    (w,) = dlg._widgets
    assert not w._editor.isVisibleTo(dlg)
    QTest.mouseClick(w._choice_btns["change"], Qt.MouseButton.LeftButton)
    assert w._editor.isVisibleTo(dlg)
    w._kind.setCurrentIndex(0)                                         # Event
    save = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
    QTest.mouseClick(save, Qt.MouseButton.LeftButton)
    assert [op[0] for op in dlg.plan["ops"]] == ["delete_todo", "create_event"]
