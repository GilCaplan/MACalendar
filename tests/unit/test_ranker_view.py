"""The Mac Ranker tab — drop, choose, paste, type, toggle, re-rank — driven by clicks.

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
from assistant.features.ranker import ocr, store  # noqa: E402

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "ranker" / "migration_3scrolls.html"
LEFT = Qt.MouseButton.LeftButton


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
    v.hide()
    v.deleteLater()


def _click(w):
    QTest.mouseClick(w, LEFT)
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
    _settle(qapp, ranker_view.DEBOUNCE_MS + 150)


def _ranked_kingdoms(view):
    rows = view.visible_rows()[1:]
    return [r[2] for r in rows]


# ---------------------------------------------------------------- helpers

def test_number_formatting():
    assert format_value(3.62e9, "Top50Power", "Top50") == "3.62B"
    assert format_value(8.5e8) == "850M"
    assert format_value(4574.0) == "4574"
    assert format_value(10.013117790222168, "InactivePercent", "😴 %") == "10%"
    assert format_value(2.345) == "2.3"
    assert format_value("Mordor") == "Mordor"
    assert parse_numbers("#1172, 153 209, 153") == [1172, 153, 209]


# ---------------------------------------------------------------- input

def test_a_dropped_table_ranks_all_40_rows_and_is_remembered(view, qapp, ranker_file):
    assert view._grid.rowCount() == 0
    _drop_files(view, FIX)
    assert view._grid.rowCount() == 40
    assert "40 rows" in view._table_lbl.text()
    assert view._summary.text().startswith("Ranked 40 of 40 kingdoms")
    head = view.visible_rows()[0]
    assert head[:3] == ["#", "Score", "K"] and "🔥 24h" in head
    saved = json.loads(ranker_file.read_text())
    assert saved["last_table"]["filename"] == FIX.name and len(saved["last_table"]["rows"]) == 40

    # a fresh panel (the next launch) ranks the remembered table without a drop
    again = RankerView(dark=True)
    again.show()
    _settle(qapp)
    assert again._grid.rowCount() == 40
    again.deleteLater()


def test_choose_files_takes_the_same_path(view, qapp, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([str(FIX)], "")))
    _click(view._choose_btn)
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
    assert view._grid.rowCount() == 0


# ---------------------------------------------------------------- numbers

def test_typed_numbers_filter_and_the_switch_toggles_them(view, qapp, ranker_file):
    _drop_files(view, FIX)
    _type_numbers(view, qapp, "1, 711 708")
    assert view._grid.rowCount() == 3
    assert sorted(_ranked_kingdoms(view)) == ["1", "708", "711"]
    assert json.loads(ranker_file.read_text())["numbers"] == [1, 711, 708]
    assert "filtered by 3 numbers" in view._summary.text()

    _click(view._use_box)                      # off: every row, list kept
    assert not view._use_box.isChecked()
    assert view._grid.rowCount() == 40
    assert view._numbers_edit.toPlainText() == "1, 711 708"       # kept as typed
    saved = json.loads(ranker_file.read_text())
    assert saved["use_numbers"] is False and saved["numbers"] == [1, 711, 708]

    _click(view._use_box)                      # on again: the list is back
    assert view._grid.rowCount() == 3


def test_a_number_with_no_row_is_named(view, qapp):
    _drop_files(view, FIX)
    _type_numbers(view, qapp, "1 99999")
    assert view._grid.rowCount() == 1
    assert view._missing_lbl.isVisible()
    assert view._missing_lbl.text() == "1 of these isn't in the table: 99999"


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


def test_a_dropped_picture_and_table_together(view, qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "numbers_from_images", lambda images: [708, 707, 702])
    pic = tmp_path / "shot.png"
    img = QImage(30, 20, QImage.Format.Format_RGB32)
    img.fill(0)
    img.save(str(pic), "PNG")
    _drop_files(view, FIX, pic)
    assert _wait(qapp, lambda: view._grid.rowCount() == 3)


# ---------------------------------------------------------------- recipe

def test_flipping_a_criterion_re_ranks(view, qapp):
    _drop_files(view, FIX)
    _click(view._recipe_toggle)
    assert view._recipe_scroll.isVisible()
    # click away all but the first criterion, so the order is that column's order
    while len(view._recipe["criteria"]) > 1:
        _click(view._criterion_rows[-1]["remove"])
        _settle(qapp, 10)
    _settle(qapp, ranker_view.DEBOUNCE_MS + 150)
    assert view._grid.rowCount() == 40
    one = _ranked_kingdoms(view)
    flip = view._criterion_rows[0]["direction"]
    assert flip.text().startswith("▲")
    _click(flip)
    assert flip.text().startswith("▼")
    _settle(qapp, ranker_view.DEBOUNCE_MS + 150)
    flipped = _ranked_kingdoms(view)
    assert flipped != one and flipped[0] == one[-1]
    assert view._dirty_lbl.text() == "• edited"


def test_saving_a_preset_persists(view, qapp, ranker_file):
    _drop_files(view, FIX)
    _click(view._recipe_toggle)
    _click(view._criterion_rows[0]["direction"])
    _settle(qapp, ranker_view.DEBOUNCE_MS + 150)
    _click(view._saveas_btn)
    assert view._name_bar.isVisible()
    view._name_edit.clear()
    QTest.keyClicks(view._name_edit, "Fewest players")
    _click(view._name_ok_btn)
    saved = json.loads(ranker_file.read_text())
    assert saved["preset"] == "Fewest players"
    assert saved["presets"]["Fewest players"]["criteria"][0]["better"] == "lower"
    assert len(saved["presets"]) == 2
    assert view._dirty_lbl.text() == ""

    # delete asks in the panel first
    _click(view._delete_btn)
    assert view._confirm_bar.isVisible()
    assert "Fewest players" in json.loads(ranker_file.read_text())["presets"]   # not yet
    _click(view._confirm_btn)
    saved = json.loads(ranker_file.read_text())
    assert "Fewest players" not in saved["presets"] and len(saved["presets"]) == 1


def _click_header(grid, section):
    from PyQt6.QtCore import QPoint
    h = grid.horizontalHeader()
    x = h.sectionViewportPosition(section) + h.sectionSize(section) // 2
    QTest.mouseClick(h.viewport(), LEFT, Qt.KeyboardModifier.NoModifier, QPoint(x, h.height() // 2))
    QApplication.processEvents()


def test_sorting_by_a_header_and_back_to_rank(view, qapp):
    _drop_files(view, FIX)
    g = view._grid
    players = view.visible_rows()[0].index("Players")
    _click_header(g, players)
    vals = [int(r[players]) for r in view.visible_rows()[1:]]
    assert vals in (sorted(vals), sorted(vals, reverse=True))
    assert view.visible_rows()[1][0] != "1" or vals == sorted(vals)
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
    assert len(lines) == 41 and lines[0].startswith("#\tScore\tK")
