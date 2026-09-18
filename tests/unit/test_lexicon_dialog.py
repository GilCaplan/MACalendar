"""Settings ▸ How I Say Things, driven with real clicks.

Per this repo's rule, a UI test that never sends a mouse event tests nothing:
the word is typed with `QTest.keyClicks` and added by clicking the button, and
the assertion is that the ENGINE's effective list changed — not that a widget
looks right.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt                                          # noqa: E402
from PyQt6.QtTest import QTest                                       # noqa: E402
from PyQt6.QtWidgets import (                                        # noqa: E402
    QApplication, QLineEdit, QListWidget, QPushButton,
)

from assistant.intent import lexicon as lx                           # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(lx, "LEXICON_PATH", str(tmp_path / "lexicon.json"))
    lx.reset()
    yield
    lx.reset()


def _dialog(app):
    from assistant.calendar_ui.lexicon_dialog import LexiconDialog
    return LexiconDialog(None, dark=True)


def test_it_shows_the_built_in_words_as_fact(app):
    """"Linked to what's in the code" was the request: the built-ins are read
    out of the module that uses them, not copied into the dialog."""
    dlg = _dialog(app)
    assert dlg.findChildren(QLineEdit), "no input rows were built"
    # Every declared lexicon has a row of its own.
    for name in lx.LEXICONS:
        assert dlg.findChild(QLineEdit, f"lexicon_input_{name}") is not None, name
        assert dlg.findChild(QPushButton, f"lexicon_add_{name}") is not None, name


def test_typing_a_word_and_clicking_add_reaches_the_engine(app):
    dlg = _dialog(app)
    field = dlg.findChild(QLineEdit, "lexicon_input_extend_verbs")
    button = dlg.findChild(QPushButton, "lexicon_add_extend_verbs")
    listing = dlg.findChild(QListWidget, "lexicon_added_extend_verbs")
    # `is not None`, not truthiness: an EMPTY QListWidget is falsy in PyQt, so
    # `assert listing` fails on the very widget it just found.
    assert field is not None and button is not None and listing is not None

    assert "squeeze" not in lx.effective("extend_verbs"), "premise changed"

    QTest.keyClicks(field, "squeeze")
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert "squeeze" in lx.effective("extend_verbs"), \
        "the click did not reach the store"
    assert [listing.item(i).text() for i in range(listing.count())] == ["squeeze"]
    assert field.text() == "", "the field should clear after adding"


def test_removing_your_own_word_leaves_the_built_ins(app):
    dlg = _dialog(app)
    field = dlg.findChild(QLineEdit, "lexicon_input_extend_verbs")
    add = dlg.findChild(QPushButton, "lexicon_add_extend_verbs")
    remove = dlg.findChild(QPushButton, "lexicon_remove_extend_verbs")
    listing = dlg.findChild(QListWidget, "lexicon_added_extend_verbs")

    QTest.keyClicks(field, "squeeze")
    QTest.mouseClick(add, Qt.MouseButton.LeftButton)
    listing.setCurrentRow(0)
    QTest.mouseClick(remove, Qt.MouseButton.LeftButton)

    assert "squeeze" not in lx.effective("extend_verbs")
    built = lx.LEXICONS["extend_verbs"].built_in()
    assert built <= lx.effective("extend_verbs"), "a built-in was lost"
    assert listing.count() == 0


def test_the_dialog_opens_for_every_declared_lexicon(app):
    """A declaration that names a renamed constant would show an empty list and
    quietly tell Gil the assistant knows no such words."""
    dlg = _dialog(app)
    for name, entry in lx.LEXICONS.items():
        assert entry.built_in(), f"{name} resolved to nothing"
        assert dlg.findChild(QListWidget, f"lexicon_added_{name}") is not None
