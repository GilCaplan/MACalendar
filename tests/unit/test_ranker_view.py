"""The Mac Ranker tab — new search, drop, choose, paste, type, rank by, columns — driven by clicks.

House rule: a UI test that never sends a mouse event tests nothing, so every
control here is clicked or typed into. The store is a tmp file through
MACALENDAR_RANKER; the picture reader is monkeypatched (Vision is not what
this tests — `test_ranker.py` covers reading).
"""

from __future__ import annotations

import json
import pathlib
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QMimeData, Qt, QUrl  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from assistant.calendar_ui import ranker_view  # noqa: E402
from assistant.calendar_ui.ranker_view import RankerView, format_value, parse_numbers  # noqa: E402
from assistant.features.ranker import ocr, store, table  # noqa: E402

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "ranker" / "migration_3scrolls.html"
LEFT = Qt.MouseButton.LeftButton
DEBOUNCE = ranker_view.DEBOUNCE_MS + 150


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ranker_file(tmp_path, monkeypatch):
    path = tmp_path / "ranker.json"
    monkeypatch.setenv("MACALENDAR_RANKER", str(path))
    assert store.store_path() == str(path)
    return path


def _settle(qapp, ms: int = 0):
    if ms:
        QTest.qWait(ms)
    for _ in range(3):
        qapp.processEvents()


@pytest.fixture
def view(qapp, ranker_file):
    v = RankerView(dark=True)
    v.resize(1100, 800)
    v.show()
    _settle(qapp)
    yield v
    v._cols_menu.hide()
    v.hide()
    v.deleteLater()


def _click(w, pos=None):
    if pos is None:
        QTest.mouseClick(w, LEFT)
    else:
        QTest.mouseClick(w, LEFT, Qt.KeyboardModifier.NoModifier, pos)
    QApplication.processEvents()
    QApplication.processEvents()


def _drop_files(view, *paths):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    assert view.take_mime(md)          # what dropEvent hands the mime data to
    _settle(QApplication.instance())


def _wait(qapp, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return True
        QTest.qWait(20)
    return cond()


def _type_numbers(view, qapp, text):
    edit = view._numbers_edit
    _click(edit.viewport())
    edit.selectAll()
    QTest.keyClick(edit.viewport(), Qt.Key.Key_Backspace)
    QTest.keyClicks(edit.viewport(), text)
    _settle(qapp, DEBOUNCE)


def _picture(tmp_path, name="shot.png"):
    pic = tmp_path / name
    img = QImage(30, 20, QImage.Format.Format_RGB32)
    img.fill(0)
    img.save(str(pic), "PNG")
    return pic


def _head(view):
    return view.visible_rows()[0]


def _column(view, label):
    i = _head(view).index(label)
    return [r[i] for r in view.visible_rows()[1:]]


def _fixture_labels():
    return [l for _n, l in table.read(FIX.name, FIX.read_bytes()).columns]


# ---------------------------------------------------------------- helpers

def test_number_formatting():
    assert format_value(3.62e9, "Top50Power", "Top50") == "3.62B"
    assert format_value(8.5e8) == "850M"
    assert format_value(4574.0) == "4574"
    assert format_value(10.013117790222168, "InactivePercent", "x %") == "10%"
    assert format_value(2.345) == "2.3"
    assert format_value("Mordor") == "Mordor"
    assert parse_numbers("#1172, 153 209, 153") == [1172, 153, 209]


# ---------------------------------------------------------------- empty state + new search

def test_a_fresh_panel_is_one_big_drop_area(view):
    assert view._empty.isVisible() and not view._work.isVisible()
    assert view._drop_hint.text() == ranker_view._DROP_TEXT
    assert view._empty_choose_btn.isVisible() and view._empty_paste_btn.isVisible()


def test_new_search_clears_and_shows_the_drop_area(view, qapp, ranker_file):
    _drop_files(view, FIX)
    _type_numbers(view, qapp, "1, 711 708")
    assert view._work.isVisible() and view._grid.rowCount() == 3
    presets = json.loads(ranker_file.read_text())["presets"]

    _click(view._new_search_btn)
    assert view._empty.isVisible() and not view._work.isVisible()
    assert view._grid.rowCount() == 0 and view._numbers_edit.toPlainText() == ""
    saved = json.loads(ranker_file.read_text())
    assert saved["last_table"] is None and saved["numbers"] == [] and saved["presets"] == presets

    # the next launch starts empty too
    again = RankerView(dark=True)
    again.show()
    _settle(qapp)
    assert again._empty.isVisible() and again._grid.rowCount() == 0
    again.deleteLater()


def test_pictures_and_a_table_dropped_together_go_straight_to_a_result(view, qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "numbers_from_images", lambda images: [708, 707, 702])
    _drop_files(view, FIX, _picture(tmp_path))
    assert _wait(qapp, lambda: view._grid.rowCount() == 3)
    assert view._work.isVisible()
    assert view._numbers_edit.toPlainText() == "708, 707, 702"


def test_pictures_before_the_table_wait_for_it(view, qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "numbers_from_images", lambda images: [1, 711])
    _drop_files(view, _picture(tmp_path))
    assert _wait(qapp, lambda: view._empty_numbers.isVisible())
    assert "2 numbers ready" in view._empty_numbers.text()
    _drop_files(view, FIX)
    assert view._grid.rowCount() == 2


# ---------------------------------------------------------------- input

def test_a_dropped_table_shows_every_column_and_is_remembered(view, qapp, ranker_file):
    _drop_files(view, FIX)
    assert view._grid.rowCount() == 40
    assert "40 rows" in view._table_lbl.text() and "14 columns" in view._table_lbl.text()
    assert view._summary.text().startswith("Ranked 40 of 40 rows")
    head = _head(view)
    assert head[0] == "#" and "Score" not in head              # nothing to rank by yet
    assert head[1:] == _fixture_labels() and len(head[1:]) == 14
    assert view._cols_btn.text().startswith("Columns: all 14")
    saved = json.loads(ranker_file.read_text())
    assert saved["last_table"]["filename"] == FIX.name and len(saved["last_table"]["rows"]) == 40

    again = RankerView(dark=True)                               # the next launch
    again.show()
    _settle(qapp)
    assert again._grid.rowCount() == 40
    again.deleteLater()


def test_choose_files_takes_the_same_path(view, qapp, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([str(FIX)], "")))
    _click(view._empty_choose_btn)
    assert view._grid.rowCount() == 40


def test_a_dropped_drag_event_reaches_the_handler(view, qapp):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QDropEvent
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(FIX))])
    ev = QDropEvent(QPointF(50, 50), Qt.DropAction.CopyAction, md,
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.dropEvent(ev)
    _settle(qapp)
    assert view._grid.rowCount() == 40


def test_a_file_that_is_not_a_table_is_said(view, qapp, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("just a sentence")
    _drop_files(view, bad)
    assert view._status.isVisible() and "notes.txt" in view._status.text()
    assert view._grid.rowCount() == 0 and view._empty.isVisible()


# ---------------------------------------------------------------- numbers

def test_typed_numbers_rank_with_every_column_and_the_switch_toggles_them(view, qapp, ranker_file):
    _drop_files(view, FIX)
    _type_numbers(view, qapp, "1, 711 708")
    assert view._grid.rowCount() == 3
    assert sorted(_column(view, "K")) == ["1", "708", "711"]
    assert len(_head(view)) == 1 + 14
    assert json.loads(ranker_file.read_text())["numbers"] == [1, 711, 708]
    assert "matched numbers on K" in view._summary.text()      # found, not asked

    _click(view._use_box)                      # off: every row, list kept
    assert not view._use_box.isChecked()
    assert view._grid.rowCount() == 40
    assert view._numbers_edit.toPlainText() == "1, 711 708"
    saved = json.loads(ranker_file.read_text())
    assert saved["use_numbers"] is False and saved["numbers"] == [1, 711, 708]

    _click(view._use_box)                      # on again: the list is back
    assert view._grid.rowCount() == 3


def test_a_number_with_no_row_is_named(view, qapp):
    _drop_files(view, FIX)
    _type_numbers(view, qapp, "1 99999")
    assert view._grid.rowCount() == 1
    assert view._summary.text().endswith("1 number not in the table: 99999")
    assert not view._missing_btn.isVisible()


def test_a_long_missing_list_folds(view, qapp):
    _drop_files(view, FIX)
    _type_numbers(view, qapp, "1 " + " ".join(str(90000 + i) for i in range(10)))
    assert view._summary.text().endswith("10 numbers not in the table")
    assert view._missing_btn.isVisible() and not view._missing_lbl.isVisible()
    _click(view._missing_btn)
    assert view._missing_lbl.isVisible() and "90009" in view._missing_lbl.text()


def test_a_pasted_picture_fills_the_list(view, qapp, monkeypatch):
    import threading
    seen, release = [], threading.Event()

    def fake(images):                  # holds until the test has seen the reading state
        seen.append(images)
        release.wait(5)
        return [1, 711]

    monkeypatch.setattr(ocr, "numbers_from_images", fake)
    _drop_files(view, FIX)
    img = QImage(30, 20, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    QApplication.clipboard().setImage(img)
    _click(view._paste_btn)
    assert "Reading numbers" in view._status.text()
    release.set()
    assert _wait(qapp, lambda: view._numbers_edit.toPlainText() == "1, 711")
    assert seen and seen[0][0][0] == "pasted.png" and seen[0][0][1][:4] == b"\x89PNG"
    assert view._use_box.isChecked() and view._grid.rowCount() == 2
    assert store.load()["numbers"] == [1, 711]


def test_new_pictures_replace_the_list(view, qapp, monkeypatch, tmp_path):
    _drop_files(view, FIX)
    _type_numbers(view, qapp, "1, 2, 3")
    monkeypatch.setattr(ocr, "numbers_from_images", lambda images: [708, 707])
    _drop_files(view, _picture(tmp_path, "a.png"))
    assert _wait(qapp, lambda: view._numbers_edit.toPlainText() == "708, 707")
    monkeypatch.setattr(ocr, "numbers_from_images", lambda images: [702])
    _drop_files(view, _picture(tmp_path, "b.png"))
    assert _wait(qapp, lambda: view._numbers_edit.toPlainText() == "702")
    assert store.load()["numbers"] == [702] and view._grid.rowCount() == 1


# ---------------------------------------------------------------- rank by

def test_adding_a_rank_by_row_and_flipping_it_re_ranks(view, qapp):
    _drop_files(view, FIX)
    assert view._criterion_rows == []
    _click(view._add_criterion_btn)
    _settle(qapp, DEBOUNCE)
    assert len(view._criterion_rows) == 1
    col = view._recipe["criteria"][0]["column"]
    label = dict(view._columns())[col]
    assert view._criterion_rows[0]["column"].currentText() == label   # labels, from THIS table
    assert "Score" in _head(view)
    one = _column(view, "K")
    flip = view._criterion_rows[0]["direction"]
    assert flip.text().startswith("▲")
    _click(flip)
    assert flip.text().startswith("▼")
    _settle(qapp, DEBOUNCE)
    flipped = _column(view, "K")
    assert flipped != one and flipped[0] == one[-1]
    assert view._dirty_lbl.text() == "edited"

    _click(view._criterion_rows[0]["remove"])
    _settle(qapp, DEBOUNCE)
    assert view._criterion_rows == [] and "Score" not in _head(view)


def test_more_options_starts_collapsed_and_holds_the_rest(view, qapp):
    _drop_files(view, FIX)
    _click(view._add_criterion_btn)
    _settle(qapp, DEBOUNCE)
    assert not view._more.isVisible()
    assert not view._weight_spins[0].isVisible() and not view._preset_combo.isVisible()
    _click(view._more_toggle)
    assert view._more.isVisible()
    assert view._weight_spins[0].isVisible() and view._add_filter_btn.isVisible()
    assert view._add_derived_btn.isVisible() and view._preset_combo.isVisible()

    _click(view._add_filter_btn)                    # a condition narrows the result
    _settle(qapp, DEBOUNCE)
    val = view._filter_rows[0]["value"]
    _click(val)
    val.selectAll()
    QTest.keyClicks(val, "0")
    _settle(qapp, DEBOUNCE)
    assert view._grid.rowCount() < 40 and "failed a condition" in view._summary.text()


def test_a_saved_ranking_naming_a_missing_column_still_ranks(qapp, ranker_file):
    blank = dict(store.BLANK_RECIPE)
    old = {"name": "Old", "key": "Kingdom", "derived": [], "filters": [], "show": [],
           "criteria": [{"column": "Nope", "better": "higher", "weight": 1},
                        {"column": "Players", "better": "higher", "weight": 1}]}
    ranker_file.write_text(json.dumps({"presets": {blank["name"]: blank, "Old": old},
                                       "preset": blank["name"], "numbers": [], "use_numbers": True,
                                       "last_table": None}))
    v = RankerView(dark=True)
    v.resize(1100, 800)
    v.show()
    _settle(qapp)
    _drop_files(v, FIX)
    _click(v._more_toggle)
    combo = v._preset_combo
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    _settle(qapp)
    assert v._preset == "Old"
    assert v._grid.rowCount() == 40 and "Score" in _head(v)
    assert v._notes_lbl.isVisible() and "'Nope'" in v._notes_lbl.text()
    players = [int(x) for x in _column(v, "Players")]
    assert players == sorted(players, reverse=True)
    v.deleteLater()


def test_saving_a_ranking_persists(view, qapp, ranker_file):
    _drop_files(view, FIX)
    _click(view._add_criterion_btn)
    _click(view._criterion_rows[0]["direction"])
    _settle(qapp, DEBOUNCE)
    _click(view._more_toggle)
    _click(view._saveas_btn)
    assert view._name_bar.isVisible()
    view._name_edit.clear()
    QTest.keyClicks(view._name_edit, "Fewest first")
    _click(view._name_ok_btn)
    saved = json.loads(ranker_file.read_text())
    assert saved["preset"] == "Fewest first"
    assert saved["presets"]["Fewest first"]["criteria"][0]["better"] == "lower"
    assert len(saved["presets"]) == 2 and view._dirty_lbl.text() == ""

    _click(view._delete_btn)                        # asks in the panel first
    assert view._confirm_bar.isVisible()
    assert "Fewest first" in json.loads(ranker_file.read_text())["presets"]
    _click(view._confirm_btn)
    saved = json.loads(ranker_file.read_text())
    assert "Fewest first" not in saved["presets"] and len(saved["presets"]) == 1


# ---------------------------------------------------------------- which columns show

def _menu_click(view, act):
    m = view._cols_menu
    _click(m, m.actionGeometry(act).center())


def test_the_columns_dropdown_toggles_each_column_and_stays_open(view, qapp):
    _drop_files(view, FIX)
    _click(view._cols_btn)
    m = view._cols_menu
    assert m.isVisible()
    acts = view._col_actions
    assert len(acts) == 14 and all(a.isChecked() for a in acts.values())

    _menu_click(view, acts["Players"])                    # off
    assert m.isVisible()                                  # still open for the next one
    assert not acts["Players"].isChecked() and "Players" not in _head(view)
    _menu_click(view, acts["Top50Power"])
    assert "Top50" not in _head(view) and view._cols_btn.text().startswith("Columns: 12 of 14")
    assert view._recipe["show"] and "Players" not in view._recipe["show"]

    _menu_click(view, view._key_only_act)
    assert _head(view) == ["#", "K"] and view._recipe["show"] == ["Kingdom"]
    _menu_click(view, acts["Players"])                    # back on, one at a time
    assert _head(view) == ["#", "K", "Players"]

    _menu_click(view, view._show_all_act)
    assert len(_head(view)) == 15 and view._recipe["show"] == []
    assert view._cols_btn.text().startswith("Columns: all 14")
    m.hide()


# ---------------------------------------------------------------- the table stays reachable

def test_the_table_gets_at_least_ten_rows_of_room(view, qapp):
    _drop_files(view, FIX)
    _settle(qapp)
    g = view._grid
    ten = 10 * g.verticalHeader().defaultSectionSize() + g.horizontalHeader().height()
    assert g.isVisible() and g.height() >= ten
    _click(view._add_criterion_btn)
    _click(view._more_toggle)                       # everything open
    _click(view._add_filter_btn)
    _settle(qapp, DEBOUNCE)
    assert g.height() >= ten

    view.resize(1100, 420)                          # a short window: the panel scrolls instead
    _settle(qapp)
    assert g.height() >= ten
    assert view._scroll.verticalScrollBar().maximum() > 0


def _click_header(grid, section):
    from PyQt6.QtCore import QPoint
    h = grid.horizontalHeader()
    x = h.sectionViewportPosition(section) + h.sectionSize(section) // 2
    QTest.mouseClick(h.viewport(), LEFT, Qt.KeyboardModifier.NoModifier, QPoint(x, h.height() // 2))
    QApplication.processEvents()


def test_sorting_by_a_header_and_back_to_rank(view, qapp):
    _drop_files(view, FIX)
    g = view._grid
    players = _head(view).index("Players")
    _click_header(g, players)
    vals = [int(r[players]) for r in view.visible_rows()[1:]]
    assert vals in (sorted(vals), sorted(vals, reverse=True))
    _click_header(g, 0)
    ranks = [int(r[0]) for r in view.visible_rows()[1:]]
    if ranks != list(range(1, 41)):
        _click_header(g, 0)                     # a second click flips the direction
        ranks = [int(r[0]) for r in view.visible_rows()[1:]]
    assert ranks == list(range(1, 41))


def test_copy_puts_the_visible_result_on_the_clipboard(view, qapp):
    _drop_files(view, FIX)
    _click(view._copy_btn)
    lines = QApplication.clipboard().text().splitlines()
    assert len(lines) == 41 and lines[0].startswith("#\tK\t")
