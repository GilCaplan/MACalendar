"""The Mac Flashcards tab — library, study round, editor — driven by clicks.

House rule: a UI test that never sends a mouse event tests nothing, so every
step here goes through QTest.mouseClick / keyClicks on the real control. The
store is a tmp_path file injected into the view; the real `flashcards.db`
holds what Gil is studying.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QMenu, QToolButton  # noqa: E402

from assistant.calendar_ui.flashcards_view import (  # noqa: E402
    FlashcardsView, SetEditorDialog, Tile, missing_words)
from assistant.features.flashcards import fsrs  # noqa: E402
from assistant.features.flashcards.store import FlashcardStore  # noqa: E402

def _make_png() -> bytes:
    """A real 40x20 PNG — the picture tests check it DECODES, not just that
    some bytes arrived."""
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QImage
    QApplication.instance() or QApplication([])
    img = QImage(40, 20, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


PNG = _make_png()
LEFT = Qt.MouseButton.LeftButton


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _ui_state(tmp_path, monkeypatch):
    """Each test folds subjects in its own QSettings file — ids restart at 1
    in every scratch store, so a shared file would carry one test's folds
    into the next."""
    monkeypatch.setenv("MACALENDAR_UI_STATE", str(tmp_path / "ui_state.ini"))


@pytest.fixture
def store(tmp_path):
    return FlashcardStore(str(tmp_path / "flashcards.db"))


def _doc(cards, set_="Verbs", subject="Spanish", **kw):
    return {"subject": subject, "set": set_, "cards": cards, **kw}


BASIC = [{"type": "basic", "front": f"q{i}", "back": f"a{i}"} for i in range(5)]
MC = [{"type": "mc", "question": f"m{i}", "choices": ["right", "wrong1", "wrong2"], "answer": "right"}
      for i in range(4)]


def _view(store, qapp) -> FlashcardsView:
    v = FlashcardsView(store=store, dark=True)
    v.resize(900, 700)
    v.show()
    for _ in range(3):
        qapp.processEvents()
    return v


def _click(w):
    QTest.mouseClick(w, LEFT)
    QApplication.processEvents()
    QApplication.processEvents()


def _labels(widget) -> "list[str]":
    return [l.text() for l in widget.findChildren(QLabel) if l.isVisibleTo(widget)]


def _start(view, sets, *, mode="all", size=0):
    _click(view._none_btn)
    for sid in sets:
        _click(view._set_boxes[sid])
    _click(view._mode_btns[mode])
    _click(view._size_btns[size])
    assert view._study_btn.isEnabled(), view._study_btn.text()
    _click(view._study_btn)
    assert view._pages.currentWidget() is view._study_page


def _tile(view, text) -> Tile:
    return next(t for t in view._face.findChildren(Tile) if t.text == text and t.isVisible())


def _reviews(store):
    with sqlite3.connect(store.path) as c:
        return c.execute("SELECT card_id, item, grade, source FROM reviews ORDER BY id").fetchall()


# ---------------------------------------------------------------- library

def test_library_shows_imported_sets_with_counts(store, qapp):
    a = store.import_doc(_doc(BASIC, set_="A"))[0]["set_id"]
    store.import_doc(_doc(MC, set_="B"))
    store.review(store.get_set(a)["cards"][0]["id"], "", 1)    # one due now (relearn), one seen
    view = _view(store, qapp)
    texts = _labels(view._lib_body)
    assert "Spanish" in texts
    assert "5 cards" in texts and "4 cards" in texts
    assert any("2 sets · 9 cards" in t for t in texts)
    names = sorted(cb.text() for cb in view._lib_body.findChildren(QCheckBox))
    assert names == ["A", "B"]
    assert view._inbox_lbl.text() == store.inbox_dir
    assert not view._study_btn.isEnabled()                     # nothing selected yet


def test_reload_picks_up_the_inbox_and_says_so(store, qapp, tmp_path):
    view = _view(store, qapp)
    import yaml
    import os
    os.makedirs(store.inbox_dir, exist_ok=True)
    with open(os.path.join(store.inbox_dir, "x.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(_doc(BASIC, set_="Dropped"), f)
    with open(os.path.join(store.inbox_dir, "bad.yaml"), "w", encoding="utf-8") as f:
        f.write("subject: S\nset: T\ncards: []\n")
    view.reload()
    assert "Dropped +5 cards" in view._status.text()
    assert "bad.yaml failed" in view._status.text()
    assert "Dropped" in [cb.text() for cb in view._lib_body.findChildren(QCheckBox)]


def test_two_sets_selected_mix_into_one_round(store, qapp):
    a = store.import_doc(_doc(BASIC, set_="A"))[0]["set_id"]
    b = store.import_doc(_doc(MC, set_="B"))[0]["set_id"]
    store.import_doc(_doc(BASIC, set_="C"))
    view = _view(store, qapp)
    _click(view._none_btn)
    _click(view._set_boxes[a])
    _click(view._set_boxes[b])
    _click(view._mode_btns["all"])
    _click(view._size_btns[0])
    assert view._study_btn.text() == "Study 9 cards"
    _click(view._study_btn)
    assert {e["set_id"] for e in view._queue} == {a, b}
    assert len(view._queue) == 9


def test_exam_mode_hides_type_chips_and_counts_only_mc(store, qapp):
    a = store.import_doc(_doc(BASIC + MC, set_="Mixed"))[0]["set_id"]
    view = _view(store, qapp)
    _click(view._set_boxes[a])
    _click(view._size_btns[0])
    _click(view._mode_btns["exam"])
    assert not view._type_row.isVisible()
    assert view._study_btn.text() == "Study 4 cards"
    _click(view._study_btn)
    _click(_tile(view, "right"))
    _click(view._action_btn)
    assert _reviews(store) == []                               # an exam only scores
    assert view._idx == 1


# ---------------------------------------------------------------- study

def test_mc_click_grades_and_advances(store, qapp):
    b = store.import_doc(_doc(MC[:2], set_="B"))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [b])
    first = view._queue[0]
    _click(_tile(view, "wrong1"))
    assert _tile(view, "wrong1").property("state") == "wrong"
    assert _tile(view, "right").property("state") == "right"
    assert view._action_btn.text() == "Continue"
    _click(view._action_btn)
    assert _reviews(store) == [(first["card_id"], "", 1, "mac")]
    # an Again comes back later in the round
    assert len(view._queue) == 3 and view._queue[-1]["card_id"] == first["card_id"]
    assert view._idx == 1
    # keyboard: pick choice by number, continue with Space
    second = view._queue[1]
    n = [t.text for t in view._cur["tiles"]].index("right") + 1
    QTest.keyClick(view._study_page, Qt.Key(Qt.Key.Key_0 + n))
    QTest.keyClick(view._study_page, Qt.Key.Key_Space)
    assert _reviews(store)[-1] == (second["card_id"], "", 3, "mac")


def test_basic_reveal_and_grade_by_keyboard(store, qapp):
    a = store.import_doc(_doc(BASIC[:1], set_="A"))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [a])
    assert not view._grade_box.isVisible()
    QTest.keyClick(view._study_page, Qt.Key.Key_Space)
    assert view._cur["answer_lbl"].text() == "a0"
    assert view._grade_box.isVisible()
    assert view._grade_btns[1].text() == "Again\n10 min"
    assert view._grade_btns[4].text().endswith(f"{fsrs.interval_days(fsrs.W[3])}d")
    _click(view._grade_btns[4])
    assert _reviews(store)[-1][2] == 4
    assert view._pages.currentWidget() is view._sum_page
    assert view._sum_pct.text() == "100%"


def test_order_card_check(store, qapp):
    steps = ["one", "two", "three", "four"]
    a = store.import_doc(_doc([{"type": "order", "prompt": "count", "steps": steps}]))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [a])
    assert not view._action_btn.isEnabled()
    # a wrong pick, undone
    _click(_tile(view, "two"))
    _click(view._undo_btn)
    for s in steps:
        _click(_tile(view, s))
    assert view._action_btn.isEnabled()
    _click(view._action_btn)                                   # Check
    placed = view._cur["placed_tiles"]
    assert [t.property("state") for t in placed] == ["right"] * 4
    _click(view._action_btn)                                   # Continue
    assert _reviews(store) == [(view._first[next(iter(view._first))]["entry"]["card_id"], "", 3, "mac")]


def test_order_card_marks_wrong_positions(store, qapp):
    steps = ["one", "two", "three"]
    a = store.import_doc(_doc([{"type": "order", "prompt": "count", "steps": steps}]))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [a])
    for s in ["two", "one", "three"]:
        _click(_tile(view, s))
    _click(view._action_btn)
    assert [t.property("state") for t in view._cur["placed_tiles"]] == ["wrong", "wrong", "right"]
    assert "Correct order" in _labels(view._face)
    _click(view._action_btn)
    assert _reviews(store)[-1][2] == 1


def test_occlusion_one_at_a_time_reveals_the_target(store, qapp):
    card = {"type": "occlusion", "image": "images/map.png", "prompt": "Where?",
            "labels": [{"text": "Haifa", "box": [10, 10, 30, 10]},
                       {"text": "Eilat", "box": [50, 80, 30, 10]}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("set.json", json.dumps(_doc([card], set_="Map")))
        zf.writestr("images/map.png", PNG)
    sid = store.import_file("map.zip", buf.getvalue())[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [sid])
    canvas = view._canvas
    assert canvas.has_picture() and canvas.mode == "one"
    target = canvas.target
    assert canvas.revealed == set()
    # the boxes sit on the picture at its displayed scale
    r = canvas.box_rect(target)
    assert 0 <= r.left() and r.right() <= canvas.width() + 0.5 and r.bottom() <= canvas.height() + 0.5
    _click(view._action_btn)                                   # Show answer
    assert canvas.revealed == {target}
    assert view._cur["answer_lbl"].text() == card["labels"][target]["text"]
    _click(view._grade_btns[3])
    assert _reviews(store)[-1][1] == f"l{target}"


def test_occlusion_all_at_once_click_each_box(store, qapp):
    card = {"type": "occlusion", "image": "images/m.png", "ask": "all_at_once",
            "labels": [{"text": "A", "box": [0, 0, 50, 50]}, {"text": "B", "box": [50, 50, 50, 50]}]}
    sid = store.create_set("Geo", "Pics")
    store.save_media(sid, "images/m.png", PNG)
    store.add_card(sid, card)
    view = _view(store, qapp)
    _start(view, [sid])
    c = view._canvas
    QTest.mouseClick(c, LEFT, pos=c.box_rect(0).center().toPoint())
    assert c.revealed == {0} and not view._grade_box.isVisible()
    QTest.mouseClick(c, LEFT, pos=c.box_rect(1).center().toPoint())
    assert view._grade_box.isVisible()
    _click(view._grade_btns[3])
    assert _reviews(store)[-1][1] == ""


def test_rtl_set_lays_its_card_out_right_to_left(store, qapp):
    sid = store.import_doc(_doc([{"type": "basic", "front": "שלום", "back": "hello"}],
                                set_="He", lang="he"))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [sid])
    assert view._face.layoutDirection() == Qt.LayoutDirection.RightToLeft
    q = next(l for l in view._face.findChildren(QLabel) if l.text() == "שלום")
    assert q.alignment() & Qt.AlignmentFlag.AlignRight


def test_typed_marks_missing_words_ignoring_niqqud_and_punctuation():
    marked = missing_words("כָּל עוֹד, בַּלֵּבָב פְּנִימָה", "כל עוד פנימה")
    assert [t for t, m in marked if m] == ["בַּלֵּבָב"]


def test_typed_card_check_then_self_grade(store, qapp):
    sid = store.import_doc(_doc([{"type": "typed", "front": "poem", "answer": "one two three"}]))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [sid])
    QTest.keyClicks(view._cur["editor"], "one three")
    _click(view._action_btn)
    assert "1 of 3" not in view._cur["answer_lbl"].text()
    assert "2 of 3 words" in " ".join(_labels(view._face))
    assert "underline\">two</span>" in view._cur["answer_lbl"].text()
    _click(view._grade_btns[2])
    assert _reviews(store)[-1][2] == 2


# ---------------------------------------------------------------- editor

def test_editor_adds_a_basic_card_and_refuses_an_unmarked_mc(store, qapp):
    sid = store.create_set("Spanish", "Food")
    dlg = SetEditorDialog(store, sid)
    dlg.show()
    qapp.processEvents()
    form = dlg.forms["basic"]
    QTest.keyClicks(form.front, "pan")
    QTest.keyClicks(form.back, "bread")
    QTest.keyClicks(dlg.tags, "food, nouns")
    _click(dlg.save_btn)
    cards = store.get_set(sid)["cards"]
    assert [(c["front"], c["back"], c["tags"]) for c in cards] == [("pan", "bread", ["food", "nouns"])]
    assert dlg.list.count() == 1 and dlg.error.text() == ""

    _click(dlg.add_btn)
    dlg.type_combo.setCurrentIndex(dlg.type_combo.findData("mc"))
    mc = dlg.forms["mc"]
    QTest.keyClicks(mc.question, "agua?")
    for (_, _, edit), text in zip(mc.rows, ["water", "fire", "earth", "air"]):
        QTest.keyClicks(edit, text)
    _click(dlg.save_btn)
    assert "correct answer" in dlg.error.text()
    assert len(store.get_set(sid)["cards"]) == 1

    # mark one, then empty its text: the answer is no longer a choice
    _click(mc.rows[0][1])
    mc.rows[0][2].clear()
    _click(dlg.save_btn)
    assert dlg.error.text()                                     # cardformat's sentence, inline
    assert len(store.get_set(sid)["cards"]) == 1
    QTest.keyClicks(mc.rows[0][2], "water")
    _click(dlg.save_btn)
    assert dlg.error.text() == ""
    assert [c["type"] for c in store.get_set(sid)["cards"]] == ["basic", "mc"]


def test_editor_cloze_make_gap_and_move(store, qapp):
    sid = store.create_set("Spanish", "Cloze")
    store.add_card(sid, {"type": "basic", "front": "first", "back": "x"})
    dlg = SetEditorDialog(store, sid)
    dlg.show()
    dlg.type_combo.setCurrentIndex(dlg.type_combo.findData("cloze"))
    f = dlg.forms["cloze"]
    QTest.keyClicks(f.text, "Lima is in Peru")
    cur = f.text.textCursor()
    cur.setPosition(0)
    cur.setPosition(4, cur.MoveMode.KeepAnchor)
    f.text.setTextCursor(cur)
    _click(f.gap_btn)
    assert f.text.toPlainText() == "{{Lima}} is in Peru"
    _click(dlg.save_btn)
    assert dlg.error.text() == ""
    _click(dlg.up_btn)
    assert [c["type"] for c in store.get_set(sid)["cards"]] == ["cloze", "basic"]


def test_editor_occlusion_drag_draws_a_label(store, qapp, tmp_path):
    from PyQt6.QtGui import QImage
    img = QImage(200, 100, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFF)
    pic = tmp_path / "board.png"
    img.save(str(pic))
    sid = store.create_set("Geo", "Board")
    dlg = SetEditorDialog(store, sid)
    dlg.pick_picture = lambda: str(pic)
    dlg.show()
    dlg.type_combo.setCurrentIndex(dlg.type_combo.findData("occlusion"))
    f = dlg.forms["occlusion"]
    _click(f.pic_btn)
    assert f.image == "images/board.png" and f.canvas.has_picture()
    c = f.canvas
    QTest.mousePress(c, LEFT, pos=QPoint(10, 10))
    QTest.mouseMove(c, QPoint(60, 40))
    QTest.mouseRelease(c, LEFT, pos=QPoint(60, 40))
    assert len(c.labels) == 1
    QTest.keyClicks(f.label_text, "Gate")
    _click(dlg.save_btn)
    assert dlg.error.text() == ""
    card = store.get_set(sid)["cards"][0]
    assert card["labels"][0]["text"] == "Gate"
    x, y, w, h = card["labels"][0]["box"]
    assert w > 0 and h > 0 and x + w <= 100 and y + h <= 100


# ---------------------------------------------------------------- import

def test_import_button_takes_a_zip_with_its_picture(store, qapp, tmp_path):
    card = {"type": "image", "image": "images/p.png", "back": "dot"}
    z = tmp_path / "pics.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("deck/set.yaml", json.dumps(_doc([card], set_="Pics")))
        zf.writestr("deck/images/p.png", PNG)
    view = _view(store, qapp)
    told = []
    view._pick_import_files = lambda: [str(z)]
    view._inform = lambda title, text, error=False: told.append((title, text, error))
    _click(view._import_btn)
    assert told == [("Imported", "Pics: 1 added, 0 kept, 0 removed", False)]
    sid = store.library()[0]["sets"][0]["id"]
    with open(store.media_path(sid, "images/p.png"), "rb") as f:
        assert f.read() == PNG
    assert "Pics" in [cb.text() for cb in view._lib_body.findChildren(QCheckBox)]

    # the same file again asks replace-or-add; a broken file says why
    asked = []
    view._ask_import_mode = lambda name, existing: asked.append(existing) or "append"
    bad = tmp_path / "bad.yaml"
    bad.write_text("subject: S\nset: T\ncards: [{type: mc, question: q, choices: [a, b], answer: c}]\n")
    view._pick_import_files = lambda: [str(z), str(bad)]
    _click(view._import_btn)
    assert asked == [["Pics"]]
    title, text, error = told[-1]
    assert error and "bad.yaml" in text and "not one of the choices" in text
    assert "Pics: 0 added, 1 kept" in text


# ---------------------------------------------------------------- archive / delete / fold / rename

@pytest.fixture
def menu_pick(monkeypatch):
    """QMenu.exec would block; instead it records the menu's entries and
    TRIGGERS the one the test names — the same action a click would fire."""
    seen: list = []
    want: list = []

    def fake_exec(self, *a, **k):
        texts = [a_.text() for a_ in self.actions() if not a_.isSeparator()]
        seen.append(texts)
        pick = want.pop(0)
        act = next(a_ for a_ in self.actions() if a_.text() == pick)
        act.trigger()
        return act

    monkeypatch.setattr(QMenu, "exec", fake_exec)

    def choose(text):
        want.append(text)
        return seen
    return choose


def _set_row(view, name):
    cb = next(cb for cb in view._lib_body.findChildren(QCheckBox) if cb.text() == name)
    return cb.parentWidget()


def _subject_block(view, name):
    return next(l for l in view._lib_body.findChildren(QLabel)
                if l.objectName() == "fc_subject" and l.text() == name).parentWidget().parentWidget()


def _main_sets(view):
    return sorted(view._set_boxes.keys())


def _archived_texts(view):
    box = view._archived_box
    return [] if box is None else [l.text() for l in box.findChildren(QLabel)]


def test_archive_a_set_leaves_the_list_and_the_round_then_unarchive(store, qapp, menu_pick):
    a = store.import_doc(_doc(BASIC, set_="A"))[0]["set_id"]
    b = store.import_doc(_doc(MC, set_="B"))[0]["set_id"]
    view = _view(store, qapp)
    _click(view._all_btn)
    _click(view._mode_btns["all"])
    _click(view._size_btns[0])
    assert view._study_btn.text() == "Study 9 cards"

    seen = menu_pick("Archive")
    _click(_set_row(view, "A").more_btn)
    assert "Archive" in seen[-1] and "Delete…" in seen[-1]
    assert store.library()[0]["sets"][0]["archived"] is True
    assert _main_sets(view) == [b]
    assert view._study_btn.text() == "Study 4 cards"          # A left the round
    assert any("1 set · 4 cards" in t for t in _labels(view._lib_body))   # header excludes it
    # under Archived (1), collapsed until its arrow is clicked
    box = view._archived_box
    assert "Archived (1)" in _archived_texts(view)
    assert not box.body.isVisible()
    _click(box.toggle_btn)
    assert box.body.isVisible()
    assert "A" in _archived_texts(view)

    seen = menu_pick("Unarchive")
    _click(view._archived_box.rows[("set", a)].more_btn)
    assert seen[-1] == ["Unarchive", "Delete…"]
    assert _main_sets(view) == [a, b]
    assert view._archived_box is None
    _click(view._set_boxes[a])
    assert view._study_btn.text() == "Study 9 cards"


def test_archive_a_subject_takes_all_its_sets_out(store, qapp, menu_pick):
    store.import_doc(_doc(BASIC, set_="A"))
    store.import_doc(_doc(MC, set_="B"))
    c = store.import_doc(_doc(BASIC, set_="C", subject="Hebrew"))[0]["set_id"]
    view = _view(store, qapp)
    _click(view._all_btn)
    menu_pick("Archive subject")
    _click(_subject_block(view, "Spanish").more_btn)
    assert _main_sets(view) == [c]
    assert sorted(view._selected) == [c]
    assert "Spanish" not in [l.text() for l in view._lib_body.findChildren(QLabel)
                             if l.objectName() == "fc_subject"]
    assert "Archived (1)" in _archived_texts(view)
    assert any("subject · 2 sets · 9 cards" in t for t in _archived_texts(view))


def test_delete_from_archived_asks_then_removes(store, qapp, menu_pick):
    a = store.import_doc(_doc(BASIC, set_="A"))[0]["set_id"]
    store.import_doc(_doc(MC, set_="B"))
    store.set_archived("set", a, True)
    view = _view(store, qapp)
    asked = []
    answer = [False]
    view._confirm = lambda title, text, yes="Delete": asked.append(text) or answer[0]
    _click(view._archived_box.toggle_btn)
    menu_pick("Delete…")
    _click(view._archived_box.rows[("set", a)].more_btn)
    assert asked and "“A”" in asked[0]
    assert a in {s["id"] for s in store.library()[0]["sets"]}   # cancelled: still there
    answer[0] = True
    menu_pick("Delete…")
    _click(view._archived_box.rows[("set", a)].more_btn)
    assert a not in {s["id"] for s in store.library()[0]["sets"]}
    assert view._archived_box is None
    assert store.deleted()["sets"][0]["id"] == a


def test_right_click_opens_the_same_menus(store, qapp, menu_pick):
    store.import_doc(_doc(BASIC, set_="A"))
    view = _view(store, qapp)
    seen = menu_pick("Edit cards…")
    view._edit_set = lambda sid: None
    row = _set_row(view, "A")
    row.customContextMenuRequested.emit(QPoint(5, 5))
    assert "Archive" in seen[-1]
    view._rename_subject = lambda sub: None
    menu_pick("Rename subject…")
    block = _subject_block(view, "Spanish")
    block.name_label.customContextMenuRequested.emit(QPoint(2, 2))
    assert "Archive subject" in seen[-1] and "Delete subject…" in seen[-1]


def test_subject_folds_to_its_header_and_stays_folded_across_restarts(store, qapp):
    store.import_doc(_doc(BASIC, set_="A"))
    store.import_doc(_doc(BASIC, set_="H", subject="Hebrew"))
    view = _view(store, qapp)
    for subj in ("Spanish", "Hebrew"):                        # every subject's arrow works
        block = _subject_block(view, subj)
        assert block.rows.isVisible()
        _click(block.toggle_btn)
        assert not block.rows.isVisible()
    assert any("1 set · 5 cards" in t for t in _labels(view._lib_body))   # counts stay on the header
    _click(_subject_block(view, "Hebrew").toggle_btn)       # open Hebrew again
    view.reload()
    QApplication.processEvents()
    assert not _subject_block(view, "Spanish").rows.isVisible()
    assert _subject_block(view, "Hebrew").rows.isVisible()
    # a new panel (an app restart) reads the same state back
    view2 = _view(store, qapp)
    assert not _subject_block(view2, "Spanish").rows.isVisible()
    assert _subject_block(view2, "Hebrew").rows.isVisible()
    # and none of it went into the flashcards store
    with sqlite3.connect(store.path) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any("collaps" in t or "ui" == t for t in tables)


def test_rename_subject_by_menu_and_double_click_with_a_readable_error(store, qapp, menu_pick):
    store.import_doc(_doc(BASIC, set_="A"))
    store.import_doc(_doc(BASIC, set_="H", subject="Hebrew"))
    view = _view(store, qapp)
    told = []
    view._inform = lambda title, text, error=False: told.append((title, text, error))
    view._ask_text = lambda title, label, text="": "Español"
    menu_pick("Rename subject…")
    _click(_subject_block(view, "Spanish").more_btn)
    assert sorted(s["name"] for s in store.library()) == ["Español", "Hebrew"]

    view._ask_text = lambda title, label, text="": "Español"     # already taken
    QTest.mouseDClick(_subject_block(view, "Hebrew").name_label, LEFT)
    QApplication.processEvents()
    assert told and told[-1][2] is True
    assert "already a subject called 'Español'" in told[-1][1]
    assert "Hebrew" in told[-1][1]
    view._ask_text = lambda title, label, text="": "Ivrit"
    QTest.mouseDClick(_subject_block(view, "Hebrew").name_label, LEFT)
    QApplication.processEvents()
    assert sorted(s["name"] for s in store.library()) == ["Español", "Ivrit"]


# ---------------------------------------------------------------- English (`en`)

HE = [{"type": "basic", "front": "מה צבע הערכה?", "back": "ירוק", "explain": "כך כתוב",
       "en": {"front": "What colour is the kit?", "back": "Green", "explain": "So it says"}}]


def test_english_is_folded_under_the_question_and_shown_under_the_answer(store, qapp):
    """Gil, 2026-10-12: on a Hebrew card, the English of the question can be
    opened (and stays folded until it is); the English of the answer sits
    right under the answer."""
    sid = store.import_doc(_doc(HE, set_="He", lang="he"))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [sid])
    toggle = view._face.findChild(QToolButton, "fc_english_toggle")
    assert toggle is not None and toggle.text() == "English"
    assert "What colour is the kit?" not in _labels(view._face)        # folded
    _click(toggle)
    assert "What colour is the kit?" in _labels(view._face)
    assert view._cur["english_prompt"].layoutDirection() == Qt.LayoutDirection.LeftToRight

    _click(view._action_btn)                                             # Show answer
    assert view._cur["answer_lbl"].text() == "ירוק"
    shown = _labels(view._face)
    assert "Green" in shown and "So it says" in shown
    assert shown.index("Green") == shown.index("ירוק") + 1               # straight under it

    # opened once, it stays open for the next card (and the next session)
    view2 = _view(store, qapp)
    _start(view2, [sid])
    assert "What colour is the kit?" in _labels(view2._face)


def test_a_card_without_english_shows_no_toggle(store, qapp):
    sid = store.import_doc(_doc(BASIC[:1], set_="A"))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [sid])
    assert view._face.findChild(QToolButton, "fc_english_toggle") is None


def test_editing_a_card_keeps_its_english(store, qapp):
    sid = store.import_doc(_doc(HE, set_="He", lang="he"))[0]["set_id"]
    dlg = SetEditorDialog(store, sid)
    dlg.show()
    qapp.processEvents()
    dlg.list.setCurrentRow(0)
    qapp.processEvents()
    QTest.keyClicks(dlg.tags, "colours")
    _click(dlg.save_btn)
    card = store.get_set(sid)["cards"][0]
    assert card["tags"] == ["colours"] and card["en"]["back"] == "Green"


def test_copy_buttons_copy_the_question_and_the_answer(store, qapp):
    """Gil, 2026-10-12: a copy button at the bottom right of the question and
    of the answer — to paste the Hebrew into a translator, say."""
    sid = store.import_doc(_doc(HE, set_="He", lang="he"))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [sid])
    copy_q = view._face.findChild(QToolButton, "fc_copy_prompt")
    _click(copy_q)
    assert QApplication.clipboard().text() == "מה צבע הערכה?"
    assert copy_q.text() == "Copied"
    assert view._face.findChild(QToolButton, "fc_copy_answer") is None   # not before the answer
    _click(view._action_btn)
    _click(view._face.findChild(QToolButton, "fc_copy_answer"))
    assert QApplication.clipboard().text() == "ירוק"


def test_a_card_without_english_still_has_copy(store, qapp):
    sid = store.import_doc(_doc(MC[:1], set_="M"))[0]["set_id"]
    view = _view(store, qapp)
    _start(view, [sid])
    _click(view._face.findChild(QToolButton, "fc_copy_prompt"))
    assert QApplication.clipboard().text().startswith("m0\n")
    _click(_tile(view, "right"))
    _click(view._face.findChild(QToolButton, "fc_copy_answer"))
    assert QApplication.clipboard().text() == "right"
