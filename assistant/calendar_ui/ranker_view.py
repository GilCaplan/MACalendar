"""RankerView — the Mac's Ranker tab: drop a table and screenshots, get a ranking.

The RESULT TABLE is the point of the panel, so it gets the space. Gil,
2026-10-11, using the first version for real: "the ranker seems
overcomplicated", "i cant scroll down to table", "why is it only showing 4" —
the recipe editor had taken the whole panel and the result was a one-row
sliver. So, top to bottom:

  TOP BAR   "History (N)", "New search" (the search on screen goes to
            History, keep the saved rankings), Paste, Choose files…
  HISTORY   folded until asked for (Gil, 2026-10-12: "make it easy to
            archive, delete history"): each past search — its table,
            numbers and ranking — with Open, Archive / Unarchive and Delete
            (asked twice); archived ones behind "Show archived". The phone
            files its own and the two sync (`store.py`).
  EMPTY     with no table: one big drop area. Any mix of table files
            (.html .htm .csv .tsv .txt .json) and pictures (.png .jpg .heic …),
            dragged, chosen or pasted. Pictures and a table together go straight
            to a ranked result.
  WORKING   with a table, compact controls:
              the source line (file · rows · columns);
              the number list, one editable line, with "Filter by these
              numbers" (off ranks every row but KEEPS the list). New pictures
              REPLACE the list; a new table replaces the table;
              "Rank by": rows of [column] [Higher/Lower] [x] and "+ Add";
              "More options", collapsed: weights, conditions, combined columns,
              saved rankings.
            then the summary, "Columns" (a check per column, all by default),
            Copy, Export CSV…, any notes, and the result table, which stretches
            and scrolls inside itself. If the controls ever outgrow the window
            the whole panel scrolls — the table is never squashed to a sliver.

Which column the numbers match is not asked: `rank.best_key` reads it off the
data, and the summary names it.

The panel calls `table`, `ocr`, `rank` and `store` directly, as the other Mac
panels call their stores — never the HTTP routes, which are the phone's door.
"""

from __future__ import annotations

import copy
import csv
import io
import os
import re
import datetime as _dt
import threading
from typing import Callable

from PyQt6.QtCore import QBuffer, QIODevice, QObject, QPoint, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from assistant.calendar_ui import styles as _styles
from assistant.calendar_ui.feature_panel import FeaturePanel
from assistant.features.ranker import ocr, rank as ranking, store, table

TABLE_EXT = (".html", ".htm", ".csv", ".tsv", ".txt", ".json")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff")
FILE_FILTER = ("Tables and pictures (*.html *.htm *.csv *.tsv *.txt *.json "
               "*.png *.jpg *.jpeg *.heic *.webp *.gif);;"
               "Tables (*.html *.htm *.csv *.tsv *.txt *.json);;"
               "Pictures (*.png *.jpg *.jpeg *.heic *.webp *.gif);;All files (*)")
DEBOUNCE_MS = 250
MIN_ROWS = 10                      # the result always shows at least this many
MISSING_INLINE = 8                 # more missing numbers than this fold behind "show"
_DIRECTION = {"higher": "▲ Higher", "lower": "▼ Lower"}
_DROP_TEXT = "Drop screenshots and a table (.html .csv .tsv .json) — or Choose files…"


# ---------------------------------------------------------------- pure helpers

def parse_numbers(text: str) -> "list[int]":
    """'#1172, 153 209' -> [1172, 153, 209]; unique, in the order typed."""
    out, seen = [], set()
    for n in (int(x) for x in re.findall(r"\d+", text or "")):
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def format_numbers(nums) -> str:
    return ", ".join(str(n) for n in nums)


def is_percent(name: str, label: str) -> bool:
    return "%" in (label or "") or "percent" in (name or "").lower()


def format_value(v, name: str = "", label: str = "") -> str:
    """How a cell reads: 3.62e9 -> 3.62B, 4574.0 -> 4574, 10.013 (a percent) -> 10%,
    2.345 -> 2.3; text unchanged."""
    n = table.number(v) if not isinstance(v, str) or v.strip() else None
    if n is None:
        return "" if v is None else str(v)
    if is_percent(name, label):
        return f"{n:.0f}%" if abs(n) >= 10 or n == int(n) else f"{n:.1f}%"
    a = abs(n)
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e5, "K")):
        if a >= size:
            return f"{n / size:.3g}{suffix}"
    if n == int(n):
        return str(int(n))
    return f"{n:.1f}"


def _palette(dark: bool) -> dict:
    ramp = _styles.accent_tokens(_styles.get_accent())
    return {
        "bg": _styles.D_WHITE if dark else _styles.WHITE,
        "bg2": _styles.D_GRAY_BG if dark else _styles.GRAY_BG,
        "surface": _styles.D_GRAY_LIGHT if dark else _styles.GRAY_LIGHT,
        "border": _styles.D_GRAY_BORDER if dark else _styles.GRAY_BORDER,
        "mid": _styles.D_GRAY_MID if dark else _styles.GRAY_MID,
        "text": _styles.D_GRAY_DARK if dark else _styles.GRAY_DARK,
        "muted": _styles.D_GRAY_TEXT if dark else _styles.GRAY_TEXT,
        "accent": ramp["accent"],
        "on_accent": ramp["on_accent"],
        "soft": ramp["accent_soft_dark"] if dark else ramp["accent_soft_light"],
        "bad": _styles.DESTRUCTIVE_DARK if dark else _styles.DESTRUCTIVE,
    }


def _qss(p: dict) -> str:
    return f"""
QScrollArea#rk_scroll, QWidget#rk_body {{ background: transparent; border: none; }}
QLabel#rk_title {{ font-size: 20px; font-weight: 600; }}
QLabel#rk_muted {{ color: {p['muted']}; }}
QLabel#rk_note {{ color: {p['muted']}; font-size: 11px; }}
QLabel#rk_section {{ font-size: 11px; font-weight: 600; color: {p['muted']};
    letter-spacing: 0.5px; }}
QLabel#rk_error {{ color: {p['bad']}; }}
QLabel#rk_warn {{ color: {p['accent']}; }}
QLabel#rk_summary {{ font-weight: 600; }}
QLabel#rk_drop_title {{ font-size: 16px; font-weight: 600; }}
QFrame#rk_drop {{ border: 2px dashed {p['mid']}; border-radius: 12px; background: {p['bg2']}; }}
QFrame#rk_drop[hot="true"] {{ border: 2px dashed {p['accent']}; background: {p['soft']}; }}
QFrame#rk_drop QLabel {{ background: transparent; border: none; }}
QFrame#rk_box {{ border: 1px solid {p['border']}; border-radius: 8px; background: {p['surface']}; }}
QFrame#rk_box[hot="true"] {{ border: 2px dashed {p['accent']}; }}
QFrame#rk_box QLabel, QFrame#rk_box QCheckBox, QWidget#rk_more {{ background: transparent; border: none; }}
QPushButton#rk_primary {{ background: {p['accent']}; color: {p['on_accent']}; border: none;
    border-radius: 6px; padding: 5px 14px; font-weight: 600; }}
QPushButton#rk_chip {{ padding: 3px 10px; border: 1px solid {p['border']}; border-radius: 4px;
    background: transparent; color: {p['text']}; }}
QPushButton#rk_chip:hover {{ border-color: {p['accent']}; }}
QPushButton#rk_link, QToolButton#rk_link {{ border: none; background: transparent;
    color: {p['muted']}; padding: 0 4px; }}
QPushButton#rk_link:hover, QToolButton#rk_link:hover {{ color: {p['accent']}; }}
QPushButton#rk_danger {{ color: {p['bad']}; }}
QToolButton#rk_toggle {{ border: none; background: transparent; font-weight: 600;
    color: {p['muted']}; padding: 0; }}
QToolButton#rk_toggle:hover {{ color: {p['accent']}; }}
QToolButton#rk_cols {{ border: 1px solid {p['border']}; border-radius: 4px; padding: 3px 8px;
    background: {p['bg2']}; color: {p['text']}; text-align: left; }}
QPlainTextEdit#rk_numbers {{ font-family: {_styles.MONO_FONT}; background: {p['bg2']};
    border: 1px solid {p['border']}; border-radius: 4px; padding: 0 4px; }}
QPlainTextEdit#rk_numbers:focus {{ border-color: {p['accent']}; }}
QLineEdit {{ background: {p['bg2']}; border: 1px solid {p['border']}; border-radius: 4px;
    padding: 3px 6px; }}
QLineEdit:focus {{ border-color: {p['accent']}; }}
QCheckBox#rk_switch {{ font-weight: 600; }}
QTableWidget#rk_result {{ background: {p['bg']}; alternate-background-color: {p['bg2']};
    border: 1px solid {p['border']}; border-radius: 6px; gridline-color: transparent; }}
QTableWidget#rk_result::item {{ padding: 2px 16px 2px 6px; }}
QTableWidget#rk_result::item:selected {{ background: {p['soft']}; color: {p['text']}; }}
QTableWidget#rk_result QScrollBar:horizontal {{ height: 10px; background: transparent; border: none;
    margin: 2px; }}
QTableWidget#rk_result QScrollBar::handle:horizontal {{ background: {p['mid']}; border-radius: 4px;
    min-width: 30px; }}
QTableWidget#rk_result QScrollBar::add-line:horizontal,
QTableWidget#rk_result QScrollBar::sub-line:horizontal {{ width: 0; }}
QTableWidget#rk_result QHeaderView::section {{ background: {p['surface']}; color: {p['muted']};
    border: none; border-bottom: 1px solid {p['border']}; padding: 4px 16px 4px 6px; font-weight: 600; }}
"""


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def _clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


def _label(text: str = "", name: str = "", *, wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _button(text: str, name: str = "", cb: "Callable | None" = None) -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if cb is not None:
        b.clicked.connect(lambda _=False: cb())
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def _box(name: str = "rk_box") -> "tuple[QFrame, QVBoxLayout]":
    f = QFrame()
    f.setObjectName(name)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(12, 8, 12, 8)
    lay.setSpacing(6)
    return f, lay


class _Item(QTableWidgetItem):
    """A cell that sorts by its value, not its formatted text (3.62B > 850M)."""

    def __init__(self, text: str, key) -> None:
        super().__init__(text)
        self._key = key

    def __lt__(self, other):  # noqa: D105
        a, b = self._key, getattr(other, "_key", None)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a < b
        if isinstance(a, (int, float)) != isinstance(b, (int, float)):
            return isinstance(a, (int, float))           # numbers before text
        return str(a).lower() < str(b).lower()


class _StayOpenMenu(QMenu):
    """A menu that stays open after a click, so several columns can be
    switched on and off in one visit."""

    def mouseReleaseEvent(self, ev):  # noqa: N802
        act = self.actionAt(ev.position().toPoint())
        if act is not None and act.isEnabled() and not act.isSeparator():
            act.trigger()
            return
        super().mouseReleaseEvent(ev)


class _Bridge(QObject):
    """Carries the picture reader's answer from its thread back to the GUI's."""
    done = pyqtSignal(int, list)
    failed = pyqtSignal(int, str)


# ---------------------------------------------------------------- the panel

class RankerView(FeaturePanel):
    feature_name = "ranker"

    def __init__(self, db=None, config=None, dark: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._dark = dark
        self._pal = _palette(dark)
        self._data: dict = store._blank()
        self._table: "table.Table | None" = None
        self._filename = ""
        self._numbers: "list[int]" = []
        self._use_numbers = True
        self._recipe: dict = copy.deepcopy(self._data["presets"][self._data["preset"]])
        self._preset = self._data["preset"]
        self._result: "dict | None" = None
        self._display: "list[tuple[str, str]]" = []
        self._col_actions: dict = {}
        self._col_order: "list[str]" = []
        self._ocr_job = 0
        self._reading = False
        self._bridge = _Bridge()
        self._bridge.done.connect(self._numbers_read)
        self._bridge.failed.connect(self._numbers_failed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._commit_and_rank)
        self.setAcceptDrops(True)
        self._build()
        paste = QShortcut(QKeySequence(QKeySequence.StandardKey.Paste), self)
        paste.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        paste.activated.connect(self.paste)
        self.apply_theme(dark)
        self.reload()

    # ------------------------------------------------------------ build

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("rk_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)
        body = QWidget()
        body.setObjectName("rk_body")
        self._scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 14, 20, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(_label("Ranker", "rk_title", wrap=False))
        top.addStretch(1)
        self._history_btn = QToolButton()
        self._history_btn.setObjectName("rk_cols")
        self._history_btn.setCheckable(True)
        self._history_btn.setText("History")
        self._history_btn.setToolTip("Past searches: open, archive or delete them")
        self._history_btn.toggled.connect(lambda on: self._toggle_history(on))
        top.addWidget(self._history_btn)
        self._new_search_btn = _button("New search", "rk_primary", self.new_search)
        self._new_search_btn.setToolTip("Start over with new pictures and a new table. Saved rankings stay.")
        self._paste_btn = _button("Paste", "", self.paste)
        self._paste_btn.setToolTip("Paste a picture, a file or a copied table (Cmd+V)")
        self._choose_btn = _button("Choose files…", "", self._choose_files)
        for b in (self._paste_btn, self._choose_btn, self._new_search_btn):
            top.addWidget(b)
        lay.addLayout(top)

        self._status = _label("", "rk_muted")
        self._status.hide()
        lay.addWidget(self._status)

        self._build_history(lay)
        self._build_empty(lay)
        self._build_work(lay)

    def _build_history(self, lay: QVBoxLayout) -> None:
        self._history_box, hv = _box()
        head = QHBoxLayout()
        head.addWidget(_label("Past searches", "rk_section", wrap=False))
        head.addStretch(1)
        self._show_archived = QCheckBox("Show archived")
        self._show_archived.toggled.connect(lambda _on: self._fill_history())
        head.addWidget(self._show_archived)
        hv.addLayout(head)
        self._history_list = QVBoxLayout()
        self._history_list.setSpacing(4)
        hv.addLayout(self._history_list)
        self._history_box.hide()
        self._history_rows: "dict[str, dict]" = {}
        self._confirm_delete: "str | None" = None
        lay.addWidget(self._history_box)
    def _build_empty(self, lay: QVBoxLayout) -> None:
        self._empty = QFrame()
        self._empty.setObjectName("rk_drop")
        self._empty.setProperty("hot", False)
        self._empty.setMinimumHeight(320)
        ev = QVBoxLayout(self._empty)
        ev.setContentsMargins(24, 24, 24, 24)
        ev.setSpacing(12)
        ev.addStretch(1)
        self._drop_hint = _label(_DROP_TEXT, "rk_drop_title")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(self._drop_hint)
        self._empty_numbers = _label("", "rk_warn")
        self._empty_numbers.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_numbers.hide()
        ev.addWidget(self._empty_numbers)
        row = QHBoxLayout()
        row.addStretch(1)
        self._empty_choose_btn = _button("Choose files…", "rk_primary", self._choose_files)
        self._empty_paste_btn = _button("Paste", "", self.paste)
        row.addWidget(self._empty_choose_btn)
        row.addWidget(self._empty_paste_btn)
        row.addStretch(1)
        ev.addLayout(row)
        eng = ocr.engine()
        self._engine_lbl = _label(
            "Reading numbers from pictures needs a Mac (Apple Vision) or Tesseract — "
            "you can type the numbers after dropping the table." if eng == "none"
            else "Pictures are read on this Mac; nothing leaves it.",
            "rk_warn" if eng == "none" else "rk_note")
        self._engine_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(self._engine_lbl)
        ev.addStretch(1)
        lay.addWidget(self._empty, 1)

    def _build_work(self, lay: QVBoxLayout) -> None:
        self._work = QWidget()
        wl = QVBoxLayout(self._work)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(8)

        # controls: one box, compact
        self._controls, cv = _box()
        self._controls.setProperty("hot", False)
        src = QHBoxLayout()
        self._table_lbl = _label("", "rk_summary", wrap=False)
        self._table_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        src.addWidget(self._table_lbl)
        src.addWidget(_label("· drop new pictures or a table anywhere to replace", "rk_note", wrap=False))
        src.addStretch(1)
        cv.addLayout(src)

        nrow = QHBoxLayout()
        nrow.setSpacing(8)
        self._use_box = QCheckBox("Filter by these numbers")
        self._use_box.setObjectName("rk_switch")
        self._use_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._use_box.toggled.connect(self._use_toggled)
        nrow.addWidget(self._use_box)
        self._numbers_edit = QPlainTextEdit()
        self._numbers_edit.setObjectName("rk_numbers")
        self._numbers_edit.setTabChangesFocus(True)
        self._numbers_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._one_line = self._numbers_edit.fontMetrics().lineSpacing() + 12
        self._numbers_edit.setFixedHeight(self._one_line)
        self._numbers_edit.setPlaceholderText("numbers from the pictures, or typed: 1172, 153, 209 — empty ranks every row")
        self._numbers_edit.textChanged.connect(self._numbers_typed)
        nrow.addWidget(self._numbers_edit, 1)
        self._count_lbl = _label("", "rk_muted", wrap=False)
        nrow.addWidget(self._count_lbl)
        self._expand_nums_btn = _button("expand", "rk_link", self._toggle_numbers_height)
        nrow.addWidget(self._expand_nums_btn)
        self._clear_nums_btn = _button("clear", "rk_link", self._clear_numbers)
        nrow.addWidget(self._clear_nums_btn)
        cv.addLayout(nrow)

        self._rankby_layout = QVBoxLayout()
        self._rankby_layout.setSpacing(4)
        cv.addLayout(self._rankby_layout)

        self._more_toggle = QToolButton()
        self._more_toggle.setObjectName("rk_toggle")
        self._more_toggle.setCheckable(True)
        self._more_toggle.setText("▸  More options")
        self._more_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._more_toggle.toggled.connect(self._toggle_more)
        cv.addWidget(self._more_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._more = QWidget()
        self._more.setObjectName("rk_more")
        mv = QVBoxLayout(self._more)
        mv.setContentsMargins(14, 0, 0, 4)
        mv.setSpacing(4)
        self._more_layout = QVBoxLayout()
        self._more_layout.setSpacing(4)
        mv.addLayout(self._more_layout)
        self._build_saved(mv)
        self._more.hide()
        cv.addWidget(self._more)
        self._recipe_msg = _label("", "rk_error")
        self._recipe_msg.hide()
        cv.addWidget(self._recipe_msg)
        wl.addWidget(self._controls)

        # result
        rrow = QHBoxLayout()
        self._summary = _label("", "rk_summary")
        self._summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rrow.addWidget(self._summary, 1)
        self._missing_btn = _button("show", "rk_link", self._toggle_missing)
        self._missing_btn.hide()
        rrow.addWidget(self._missing_btn)
        self._cols_btn = _button("Columns", "rk_chip", self._open_columns)
        self._cols_btn.setToolTip("Choose which columns the result shows")
        self._cols_menu = _StayOpenMenu(self)
        rrow.addWidget(self._cols_btn)
        self._copy_btn = _button("Copy", "", self._copy)
        self._export_btn = _button("Export CSV…", "", self._export)
        rrow.addWidget(self._copy_btn)
        rrow.addWidget(self._export_btn)
        wl.addLayout(rrow)
        self._missing_lbl = _label("", "rk_warn")
        self._missing_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._missing_lbl.hide()
        wl.addWidget(self._missing_lbl)
        self._notes_lbl = _label("", "rk_note")
        self._notes_lbl.hide()
        wl.addWidget(self._notes_lbl)

        self._grid = QTableWidget()
        self._grid.setObjectName("rk_result")
        self._grid.setAlternatingRowColors(True)
        self._grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._grid.verticalHeader().hide()
        self._grid.setShowGrid(False)
        self._grid.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._grid.horizontalHeader().setHighlightSections(False)
        self._grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._grid.horizontalHeader().setStretchLastSection(False)
        self._grid.setSortingEnabled(True)
        self._grid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._grid.setMinimumHeight(self.min_table_height())
        wl.addWidget(self._grid, 1)
        lay.addWidget(self._work, 1)

    def _build_saved(self, mv: QVBoxLayout) -> None:
        """Saved rankings: load, save, save as, delete — out of the way."""
        mv.addWidget(_label("SAVED RANKINGS", "rk_section", wrap=False))
        head = QHBoxLayout()
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(220)
        self._preset_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._preset_combo.currentIndexChanged.connect(lambda _i: self._preset_chosen())
        head.addWidget(self._preset_combo)
        self._dirty_lbl = _label("", "rk_warn", wrap=False)
        head.addWidget(self._dirty_lbl)
        self._save_btn = _button("Save", "", self._save_preset)
        self._saveas_btn = _button("Save as…", "", self._open_name_bar)
        self._delete_btn = _button("Delete", "", self._ask_delete)
        for b in (self._save_btn, self._saveas_btn, self._delete_btn):
            head.addWidget(b)
        head.addStretch(1)
        mv.addLayout(head)

        self._name_bar = QWidget()
        nb = QHBoxLayout(self._name_bar)
        nb.setContentsMargins(0, 0, 0, 0)
        nb.addWidget(_label("Save as:", "rk_muted", wrap=False))
        self._name_edit = QLineEdit()
        self._name_edit.returnPressed.connect(self._name_ok)
        nb.addWidget(self._name_edit, 1)
        self._name_ok_btn = _button("OK", "", self._name_ok)
        self._name_cancel_btn = _button("Cancel", "", self._close_bars)
        nb.addWidget(self._name_ok_btn)
        nb.addWidget(self._name_cancel_btn)
        self._name_bar.hide()
        mv.addWidget(self._name_bar)

        self._confirm_bar = QWidget()
        cb = QHBoxLayout(self._confirm_bar)
        cb.setContentsMargins(0, 0, 0, 0)
        self._confirm_lbl = _label("", "rk_error", wrap=False)
        cb.addWidget(self._confirm_lbl, 1)
        self._confirm_btn = _button("Delete", "rk_danger", self._delete_preset)
        self._confirm_cancel_btn = _button("Cancel", "", self._close_bars)
        cb.addWidget(self._confirm_btn)
        cb.addWidget(self._confirm_cancel_btn)
        self._confirm_bar.hide()
        mv.addWidget(self._confirm_bar)

    def min_table_height(self) -> int:
        """Room for the header and MIN_ROWS rows."""
        row = self._grid.verticalHeader().defaultSectionSize() if hasattr(self, "_grid") else 30
        return self.fontMetrics().height() + 16 + MIN_ROWS * row + 4

    # ------------------------------------------------------------ contract

    def reload(self) -> None:
        """Re-read saved rankings, the number list and the remembered table; re-rank.
        An unsaved edit to the open ranking survives a reload of the same one."""
        self._data = store.load()
        name = self._data["preset"]
        if name not in self._data["presets"]:
            name = next(iter(self._data["presets"]))
        if name != self._preset or not self._dirty():
            self._recipe = copy.deepcopy(self._data["presets"][name])
        self._preset = name
        self._numbers = [int(n) for n in self._data.get("numbers") or []]
        self._use_numbers = bool(self._data.get("use_numbers", True))
        last = self._data.get("last_table")
        if last and last.get("columns"):
            self._table = table.Table([(c["name"], c.get("label") or c["name"]) for c in last["columns"]],
                                      last.get("rows") or [])
            self._filename = last.get("filename") or "table"
        else:
            self._table, self._filename = None, ""
        if not self._numbers_edit.hasFocus():
            self._show_numbers()
        self._use_box.blockSignals(True)
        self._use_box.setChecked(self._use_numbers)
        self._use_box.blockSignals(False)
        self._fill_presets()
        self._show_table_status()
        self._rebuild_editor()
        self._rank()
        self._fill_history()

    def apply_theme(self, dark: bool) -> None:
        self._dark = dark
        self._pal = _palette(dark)
        self.setStyleSheet(_qss(self._pal))

    def apply_ui_config(self, ui) -> None:
        """Nothing size-related is configurable here yet."""

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        QTimer.singleShot(0, self.reload)

    # ------------------------------------------------------------ new search

    def new_search(self) -> None:
        """Forget the table and the numbers; keep the saved rankings. The open
        ranking goes back to its saved form."""
        self._ocr_job += 1                       # a picture still being read is dropped
        self._reading = False
        self._data = store.new_search()
        self._table, self._filename = None, ""
        self._numbers, self._use_numbers = [], True
        if self._preset in self._data["presets"]:
            self._recipe = copy.deepcopy(self._data["presets"][self._preset])
        self._show_numbers()
        self._use_box.blockSignals(True)
        self._use_box.setChecked(True)
        self._use_box.blockSignals(False)
        self._say("")
        self._close_bars()
        self._fill_presets()
        self._show_table_status()
        self._rebuild_editor()
        self._rank()
        self._fill_history()

    # ------------------------------------------------------------ history

    def _toggle_history(self, on: bool) -> None:
        self._history_box.setVisible(on)
        if on:
            self._fill_history()

    def _fill_history(self) -> None:
        hist = self._data.get("history") or []
        live = [e for e in hist if not e.get("archived")]
        archived = len(hist) - len(live)
        self._history_btn.setText(f"History ({len(live)})" if hist else "History")
        self._show_archived.setText(f"Show archived ({archived})")
        self._show_archived.setVisible(archived > 0)
        if not self._history_box.isVisible():
            return
        _clear(self._history_list)
        self._history_rows = {}
        shown = hist if self._show_archived.isChecked() else live
        if not shown:
            self._history_list.addWidget(_label(
                "Nothing yet — a search is kept here when you start a new one or drop a different table.",
                "rk_muted"))
            return
        for e in shown:
            self._history_list.addWidget(self._history_row(e))

    def _history_row(self, e: dict) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        rows = len((e.get("table") or {}).get("rows") or [])
        nums = len(e.get("numbers") or [])
        d = _dt.datetime.fromtimestamp(float(e.get("saved_at") or 0))
        when = f"{d.day} {d:%b %H:%M}"
        bits = [f"{rows} rows"] + ([f"{nums} numbers"] if nums else []) + ([e["preset"]] if e.get("preset") else [])
        text = f"{e.get('name') or e.get('filename')} · {' · '.join(bits)} · {when}"
        lab = _label(text, "rk_muted" if e.get("archived") else "", wrap=False)
        lab.setToolTip(text)
        row.addWidget(lab, 1)
        hid = e["id"]
        open_btn = _button("Open", "rk_chip", lambda: self._open_history(hid))
        arch_btn = _button("Unarchive" if e.get("archived") else "Archive", "rk_chip",
                           lambda: self._archive_history(hid, not e.get("archived")))
        del_btn = _button("Delete", "rk_danger", lambda: self._delete_history(hid))
        for b in (open_btn, arch_btn, del_btn):
            row.addWidget(b)
        self._history_rows[hid] = {"open": open_btn, "archive": arch_btn, "delete": del_btn, "label": lab}
        return w

    def _open_history(self, hid: str) -> None:
        if store.history_open(hid) is None:
            self._say("That search is no longer kept.", error=True)
            return
        self._confirm_delete = None
        self.reload()
        self._recipe = copy.deepcopy(self._data["presets"][self._data["preset"]])
        self._rebuild_editor()
        self._rank()

    def _archive_history(self, hid: str, on: bool) -> None:
        data = store.history_set(hid, archived=on)
        if data is not None:
            self._data = data
        self._fill_history()

    def _delete_history(self, hid: str) -> None:
        """Asked twice: the first click turns the button into "Delete for good"."""
        if self._confirm_delete != hid:
            self._confirm_delete = hid
            b = self._history_rows.get(hid, {}).get("delete")
            if b is not None:
                b.setText("Delete for good")
            return
        self._confirm_delete = None
        self._data = store.history_delete(hid)
        self._fill_history()

    # ------------------------------------------------------------ input

    def dragEnterEvent(self, ev):  # noqa: N802
        md = ev.mimeData()
        if md.hasUrls() or md.hasImage():
            ev.acceptProposedAction()
            self._set_hot(True)
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):  # noqa: N802
        if ev.mimeData().hasUrls() or ev.mimeData().hasImage():
            ev.acceptProposedAction()

    def dragLeaveEvent(self, ev):  # noqa: N802
        self._set_hot(False)

    def dropEvent(self, ev):  # noqa: N802
        self._set_hot(False)
        if self.take_mime(ev.mimeData()):
            ev.acceptProposedAction()

    def _set_hot(self, on: bool) -> None:
        for w in (self._empty, self._controls):
            w.setProperty("hot", on)
            _repolish(w)

    def take_mime(self, md) -> bool:
        """What a drop and a paste both do with what arrived: files by their
        kind, a bitmap as a picture, text as a table or as numbers."""
        if md is None:
            return False
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []
        if not paths and md.hasText():
            for line in md.text().splitlines():
                s = line.strip()
                p = QUrl(s).toLocalFile() if s.startswith("file:") else s
                if p and os.path.isfile(p):
                    paths.append(p)
        if paths:
            self.take_files(paths)
            return True
        if md.hasImage():
            img = md.imageData()
            if img is not None and not img.isNull():
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img.save(buf, "PNG")
                self._read_pictures([("pasted.png", bytes(buf.data()))])
                return True
        if md.hasHtml() and "<table" in md.html().lower():
            self._load_table("pasted.html", md.html().encode("utf-8"))
            return True
        if md.hasText():
            text = md.text()
            if "<table" in text.lower() or (text.count("\n") >= 1 and ("\t" in text or "," in text)
                                            and re.search(r"[A-Za-z]", text)):
                self._load_table("pasted.html" if "<table" in text.lower() else "pasted.csv",
                                 text.encode("utf-8"))
                return True
            nums = parse_numbers(text)
            if nums:
                self._set_numbers(nums, use=True)
                return True
        self._say("Nothing to use in that — drop or paste a table file or a picture.", error=True)
        return False

    def take_files(self, paths: "list[str]") -> None:
        tables, pictures = [], []
        for p in paths:
            (pictures if p.lower().endswith(IMAGE_EXT) else tables).append(p)
        for p in tables:                           # one table at a time: the last one wins
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except OSError as e:
                self._say(f"Could not open {os.path.basename(p)}: {e.strerror or e}", error=True)
                continue
            self._load_table(os.path.basename(p), data)
        if pictures:
            images = []
            for p in pictures:
                try:
                    with open(p, "rb") as f:
                        images.append((os.path.basename(p), f.read()))
                except OSError as e:
                    self._say(f"Could not open {os.path.basename(p)}: {e.strerror or e}", error=True)
            if images:
                self._read_pictures(images)

    def paste(self) -> None:
        self.take_mime(QGuiApplication.clipboard().mimeData())

    def _choose_files(self) -> None:
        paths, _f = QFileDialog.getOpenFileNames(self, "Choose a table and pictures", "", FILE_FILTER)
        if paths:
            self.take_files(list(paths))

    def _load_table(self, name: str, data: bytes) -> None:
        try:
            t = table.read(name, data)
        except (table.TableError, ValueError) as e:
            self._say(f"{name}: {e}", error=True)
            return
        self._table, self._filename = t, name
        self._data = store.update(last_table={"filename": name, **t.to_json()})
        self._fill_history()
        self._say("")
        self._show_table_status()
        self._rebuild_editor()
        self._rank()

    def _show_table_status(self) -> None:
        has = self._table is not None
        self._empty.setVisible(not has)
        self._work.setVisible(has)
        if has:
            self._table_lbl.setText(f"{self._filename} · {len(self._table.rows)} rows · "
                                    f"{len(self._table.columns)} columns")
        n = len(self._numbers)
        self._empty_numbers.setText(f"{n} number{'s' if n != 1 else ''} ready — now drop the table.")
        self._empty_numbers.setVisible(not has and n > 0)

    def _say(self, text: str, *, error: bool = False) -> None:
        self._status.setObjectName("rk_error" if error else "rk_muted")
        _repolish(self._status)
        self._status.setText(text)
        self._status.setVisible(bool(text))

    # ------------------------------------------------------------ pictures

    def _read_pictures(self, images: "list[tuple[str, bytes]]") -> None:
        self._ocr_job += 1
        job = self._ocr_job
        self._reading = True
        n = len(images)
        self._say(f"Reading numbers from {n} picture{'s' if n != 1 else ''}…")

        def work():
            try:
                found = ocr.numbers_from_images(images)
            except Exception as e:                 # noqa: BLE001 — said in the panel
                self._bridge.failed.emit(job, str(e))
            else:
                self._bridge.done.emit(job, list(found))

        threading.Thread(target=work, name="ranker-ocr", daemon=True).start()

    def _numbers_read(self, job: int, found: list) -> None:
        if job != self._ocr_job:
            return                                 # a newer picture superseded this one
        self._reading = False
        if not found:
            self._say("No numbers found in the pictures — type them in the number line.", error=True)
            return
        self._say(f"Found {len(found)} numbers in the pictures.")
        self._set_numbers([int(n) for n in found], use=True)     # REPLACES the list

    def _numbers_failed(self, job: int, msg: str) -> None:
        if job != self._ocr_job:
            return
        self._reading = False
        self._say(msg, error=True)

    # ------------------------------------------------------------ numbers

    def _set_numbers(self, nums: "list[int]", *, use: "bool | None" = None) -> None:
        self._numbers = nums
        self._show_numbers()
        fields = {"numbers": nums}
        if use is not None:
            self._use_numbers = use
            fields["use_numbers"] = use
            self._use_box.blockSignals(True)
            self._use_box.setChecked(use)
            self._use_box.blockSignals(False)
        self._data = store.update(**fields)
        self._show_table_status()
        self._rank()

    def _show_numbers(self) -> None:
        self._numbers_edit.blockSignals(True)
        self._numbers_edit.setPlainText(format_numbers(self._numbers))
        self._numbers_edit.blockSignals(False)

    def _numbers_typed(self) -> None:
        self._numbers = parse_numbers(self._numbers_edit.toPlainText())
        self._debounce.start()

    def _clear_numbers(self) -> None:
        self._set_numbers([])

    def _toggle_numbers_height(self) -> None:
        tall = self._numbers_edit.height() > self._one_line
        self._numbers_edit.setFixedHeight(self._one_line if tall else self._one_line * 4)
        self._numbers_edit.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if tall else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._expand_nums_btn.setText("expand" if tall else "fold")

    def _use_toggled(self, on: bool) -> None:
        self._use_numbers = on
        self._data = store.update(use_numbers=on)
        self._rank()

    def _active_numbers(self) -> "list[int]":
        return list(self._numbers) if self._use_numbers else []

    # ------------------------------------------------------------ saved rankings

    def _fill_presets(self) -> None:
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        for name in self._data["presets"]:
            self._preset_combo.addItem(name, name)
        i = self._preset_combo.findData(self._preset)
        self._preset_combo.setCurrentIndex(max(i, 0))
        self._preset_combo.blockSignals(False)
        self._delete_btn.setEnabled(len(self._data["presets"]) > 1)
        self._update_dirty()

    def _dirty(self) -> bool:
        saved = self._data["presets"].get(self._preset)
        return saved is not None and _norm(saved) != _norm(self._recipe)

    def _update_dirty(self) -> None:
        self._dirty_lbl.setText("edited" if self._dirty() else "")

    def _preset_chosen(self) -> None:
        name = self._preset_combo.currentData()
        if not name or name == self._preset:
            return
        self._preset = name
        self._recipe = copy.deepcopy(self._data["presets"][name])
        self._data = store.update(preset=name)
        self._close_bars()
        self._rebuild_editor()
        self._rank()

    def _recipe_error(self, text: str) -> None:
        self._recipe_msg.setText(text)
        self._recipe_msg.setVisible(bool(text))

    def _save_preset(self, name: "str | None" = None) -> None:
        name = name or self._preset
        recipe = copy.deepcopy(self._recipe)
        recipe["name"] = name
        presets = dict(self._data["presets"])
        presets[name] = recipe
        self._data = store.update(presets=presets, preset=name)
        self._preset, self._recipe = name, copy.deepcopy(recipe)
        self._recipe_error("")
        self._close_bars()
        self._fill_presets()

    def _open_name_bar(self) -> None:
        self._confirm_bar.hide()
        self._name_edit.setText(f"{self._preset} (copy)")
        self._name_bar.show()
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _name_ok(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._recipe_error("Give the ranking a name.")
            return
        self._save_preset(name)

    def _ask_delete(self) -> None:
        if len(self._data["presets"]) <= 1:
            self._recipe_error("Keep at least one saved ranking — edit this one instead.")
            return
        self._name_bar.hide()
        self._confirm_lbl.setText(f"Delete the saved ranking {self._preset!r}? This cannot be undone.")
        self._confirm_bar.show()

    def _delete_preset(self) -> None:
        presets = dict(self._data["presets"])
        presets.pop(self._preset, None)
        if not presets:
            return
        nxt = next(iter(presets))
        self._data = store.update(presets=presets, preset=nxt)
        self._preset = nxt
        self._recipe = copy.deepcopy(presets[nxt])
        self._close_bars()
        self._fill_presets()
        self._rebuild_editor()
        self._rank()

    def _close_bars(self) -> None:
        self._name_bar.hide()
        self._confirm_bar.hide()

    # ------------------------------------------------------------ recipe editor

    def _toggle_more(self, on: bool) -> None:
        self._more_toggle.setText(("▾" if on else "▸") + "  More options")
        self._more.setVisible(on)

    def _columns(self) -> "list[tuple[str, str]]":
        """(name, label) choices: the table's columns, then the combined ones."""
        cols = list(self._table.columns) if self._table else []
        have = {n for n, _ in cols}
        for d in self._recipe.get("derived", []):
            if d.get("name") and d["name"] not in have:
                cols.append((d["name"], d.get("label") or d["name"]))
                have.add(d["name"])
        return cols

    def _label_of(self, name: str) -> str:
        return dict(self._columns()).get(name, name)

    def _column_combo(self, selected: str, cols: "list[tuple[str, str]]", on_change) -> QComboBox:
        box = QComboBox()
        box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for n, l in cols:
            box.addItem(l, n)
            if l != n:
                box.setItemData(box.count() - 1, n, Qt.ItemDataRole.ToolTipRole)
        if selected and box.findData(selected) < 0:
            box.addItem(f"{selected} (not in this table)", selected)
        box.setCurrentIndex(max(box.findData(selected), 0))
        box.currentIndexChanged.connect(lambda _i: on_change(box.currentData()))
        return box

    def _columns_menu_button(self, chosen: "list[str]", cols, on_change, empty_text: str) -> QToolButton:
        """For a combined column's parts: a checklist of the table's columns."""
        btn = QToolButton()
        btn.setObjectName("rk_cols")
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = _StayOpenMenu(btn)
        state = list(chosen)
        labels = dict(cols)

        def caption():
            if not state:
                return empty_text
            shown = ", ".join(labels.get(n, n) for n in state[:4])
            return shown + (f" +{len(state) - 4}" if len(state) > 4 else "")

        def flip(name, on):
            if on and name not in state:
                state.append(name)
            elif not on and name in state:
                state.remove(name)
            btn.setText(caption())
            on_change(list(state))

        for n, l in cols:
            act = menu.addAction(l)
            act.setCheckable(True)
            act.setChecked(n in state)
            act.toggled.connect(lambda on, n=n: flip(n, on))
        btn.setMenu(menu)
        btn.setText(caption())
        return btn

    def _remove_btn(self, cb) -> QPushButton:
        b = _button("×", "rk_link", cb)
        b.setToolTip("Remove")
        return b

    def _rebuild_editor(self) -> None:
        self._rebuild_rank_by()
        self._rebuild_more()
        self._update_dirty()

    def _rebuild_rank_by(self) -> None:
        lay = self._rankby_layout
        _clear(lay)
        cols = self._columns()
        self._criterion_rows = []
        crit = self._recipe.get("criteria", [])
        for i, c in enumerate(crit):
            row = QHBoxLayout()
            row.setSpacing(6)
            cap = _label("Rank by" if i == 0 else "then", "rk_muted", wrap=False)
            cap.setFixedWidth(56)
            row.addWidget(cap)
            combo = self._column_combo(c["column"], cols, lambda v, i=i: self._edit_list("criteria", i, "column", v))
            combo.setMinimumWidth(180)
            row.addWidget(combo)
            dirb = _button(_DIRECTION.get(c.get("better"), _DIRECTION["higher"]), "rk_chip")
            dirb.setToolTip("Which is better — click to flip")
            dirb.clicked.connect(lambda _=False, i=i: self._flip_direction(i))
            dirb.setMinimumWidth(90)
            row.addWidget(dirb)
            rm = self._remove_btn(lambda i=i: self._remove("criteria", i))
            row.addWidget(rm)
            row.addStretch(1)
            lay.addLayout(row)
            self._criterion_rows.append({"column": combo, "direction": dirb, "remove": rm})
        row = QHBoxLayout()
        row.setSpacing(6)
        if not crit:
            cap = _label("Rank by", "rk_muted", wrap=False)
            cap.setFixedWidth(56)
            row.addWidget(cap)
        else:
            row.addSpacing(62)
        self._add_criterion_btn = _button("+ Add", "rk_link", self._add_criterion)
        self._add_criterion_btn.setToolTip("Rank by another column")
        row.addWidget(self._add_criterion_btn)
        if not crit:
            row.addWidget(_label("nothing yet — the table's own order", "rk_note", wrap=False))
        row.addStretch(1)
        lay.addLayout(row)

    def _rebuild_more(self) -> None:
        lay = self._more_layout
        _clear(lay)
        r = self._recipe
        cols = self._columns()
        table_cols = list(self._table.columns) if self._table else []
        labels = dict(cols)

        # weights
        lay.addWidget(_label("WEIGHTS", "rk_section", wrap=False))
        self._weight_spins = []
        row = QHBoxLayout()
        row.setSpacing(6)
        if not r.get("criteria"):
            row.addWidget(_label("Add a Rank-by column first.", "rk_note", wrap=False))
        for i, c in enumerate(r.get("criteria", [])):
            row.addWidget(_label(labels.get(c["column"], c["column"]), "rk_muted", wrap=False))
            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setValue(int(round(float(c.get("weight", 1)))))
            spin.valueChanged.connect(lambda v, i=i: self._edit_list("criteria", i, "weight", v))
            row.addWidget(spin)
            row.addSpacing(10)
            self._weight_spins.append(spin)
        row.addStretch(1)
        lay.addLayout(row)

        # conditions
        lay.addWidget(_label("ONLY ROWS WHERE", "rk_section", wrap=False))
        self._filter_rows = []
        for i, f in enumerate(r.get("filters", [])):
            row = QHBoxLayout()
            fcombo = self._column_combo(f["column"], cols,
                                        lambda v, i=i: self._edit_list("filters", i, "column", v))
            fcombo.setMinimumWidth(180)
            row.addWidget(fcombo)
            op = QComboBox()
            op.addItems(list(ranking.OPS))
            op.setCurrentIndex(max(op.findText(f.get("op", "<=")), 0))
            op.currentTextChanged.connect(lambda v, i=i: self._edit_list("filters", i, "op", v))
            row.addWidget(op)
            val = QLineEdit(str(f.get("value", "")))
            val.setFixedWidth(110)
            val.textEdited.connect(lambda v, i=i: self._edit_list("filters", i, "value", v))
            row.addWidget(val)
            row.addWidget(self._remove_btn(lambda i=i: self._remove("filters", i)))
            row.addStretch(1)
            lay.addLayout(row)
            self._filter_rows.append({"column": fcombo, "op": op, "value": val})
        self._add_filter_btn = _button("+ Add condition", "rk_link", self._add_filter)
        lay.addWidget(self._add_filter_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # combined columns
        lay.addWidget(_label("COMBINED COLUMNS (a sum of others)", "rk_section", wrap=False))
        for i, d in enumerate(r.get("derived", [])):
            row = QHBoxLayout()
            name = QLineEdit(d.get("name", ""))
            name.setPlaceholderText("name")
            name.setFixedWidth(120)
            name.editingFinished.connect(lambda i=i, w=name: self._rename_derived(i, w.text().strip()))
            row.addWidget(name)
            lab = QLineEdit(d.get("label", ""))
            lab.setPlaceholderText("label")
            lab.setFixedWidth(90)
            lab.textEdited.connect(lambda v, i=i: self._edit_list("derived", i, "label", v))
            row.addWidget(lab)
            row.addWidget(_label("=", "rk_muted", wrap=False))
            row.addWidget(self._columns_menu_button(
                d.get("sum", []), table_cols,
                lambda v, i=i: self._edit_list("derived", i, "sum", v), "choose columns…"))
            row.addWidget(self._remove_btn(lambda i=i: self._remove("derived", i)))
            row.addStretch(1)
            lay.addLayout(row)
        self._add_derived_btn = _button("+ Add combined column", "rk_link", self._add_derived)
        lay.addWidget(self._add_derived_btn, 0, Qt.AlignmentFlag.AlignLeft)

    def _edit(self, field: str, value) -> None:
        self._recipe[field] = value
        self._changed()

    def _edit_list(self, field: str, i: int, key: str, value) -> None:
        items = self._recipe.setdefault(field, [])
        if 0 <= i < len(items):
            items[i][key] = value
            if field == "criteria" and key == "column":
                QTimer.singleShot(0, self._rebuild_more)     # the weight's caption
            self._changed()

    def _flip_direction(self, i: int) -> None:
        c = self._recipe["criteria"][i]
        c["better"] = "lower" if c.get("better") == "higher" else "higher"
        self._criterion_rows[i]["direction"].setText(_DIRECTION[c["better"]])
        self._changed()

    def _remove(self, field: str, i: int) -> None:
        items = self._recipe.get(field, [])
        if 0 <= i < len(items):
            gone = items.pop(i)
            if field == "derived":
                self._drop_references(gone.get("name"))
            QTimer.singleShot(0, self._rebuild_editor)   # not while the clicked button is mid-signal
            self._changed()

    def _drop_references(self, name: "str | None") -> None:
        if not name:
            return
        r = self._recipe
        r["criteria"] = [c for c in r.get("criteria", []) if c["column"] != name]
        r["filters"] = [f for f in r.get("filters", []) if f["column"] != name]
        r["show"] = [s for s in r.get("show", []) if s != name]

    def _rename_derived(self, i: int, new: str) -> None:
        items = self._recipe.get("derived", [])
        if not (0 <= i < len(items)) or not new or items[i].get("name") == new:
            return
        old = items[i].get("name")
        items[i]["name"] = new
        r = self._recipe
        for c in r.get("criteria", []) + r.get("filters", []):
            if c["column"] == old:
                c["column"] = new
        r["show"] = [new if s == old else s for s in r.get("show", [])]
        QTimer.singleShot(0, self._rebuild_editor)
        self._changed()

    def _next_column(self) -> str:
        """A column not yet ranked by, numeric if there is one."""
        used = {c["column"] for c in self._recipe.get("criteria", [])}
        key = (self._result or {}).get("key") or self._recipe.get("key")
        cols = [n for n, _l in self._columns() if n not in used and n != key]
        rows = self._table.rows[:20] if self._table else []
        for n in cols:
            if any(table.number(r.get(n)) is not None for r in rows):
                return n
        return cols[0] if cols else (self._columns()[0][0] if self._columns() else "")

    def _add_criterion(self) -> None:
        self._recipe.setdefault("criteria", []).append(
            {"column": self._next_column(), "better": "higher", "weight": 1})
        self._rebuild_editor()
        self._changed()

    def _add_filter(self) -> None:
        self._recipe.setdefault("filters", []).append({"column": self._next_column(), "op": "<=", "value": "1"})
        self._rebuild_editor()
        self._changed()

    def _add_derived(self) -> None:
        names = {d.get("name") for d in self._recipe.get("derived", [])}
        n = 1
        while f"Sum{n}" in names:
            n += 1
        self._recipe.setdefault("derived", []).append({"name": f"Sum{n}", "label": f"Sum {n}", "sum": []})
        self._rebuild_editor()
        self._changed()

    def _changed(self) -> None:
        self._update_dirty()
        self._recipe_error("")
        self._debounce.start()

    def _commit_and_rank(self) -> None:
        """The debounce's end: keep the typed number list, then rank."""
        if self._numbers != (self._data.get("numbers") or []):
            self._data = store.update(numbers=self._numbers)
        self._rank()

    # ------------------------------------------------------------ which columns show

    def _all_columns(self) -> "list[str]":
        """Every column the result can show, in the order it shows them."""
        if self._table is None:
            return []
        key = (self._result or {}).get("key") or self._recipe.get("key") or self._table.names[0]
        r = self._recipe_for_rank()
        return list(dict.fromkeys([key] + [c["column"] for c in r.get("criteria", [])]
                                  + [d["name"] for d in r.get("derived", [])] + self._table.names))

    def _shown(self) -> "set[str]":
        show = [s for s in self._recipe.get("show", []) if s in self._col_order]
        return set(show) if show else set(self._col_order)

    def _set_show(self, names: "set[str]") -> None:
        if not names:
            return
        ordered = [n for n in self._col_order if n in names]
        self._recipe["show"] = [] if len(ordered) == len(self._col_order) else ordered
        self._update_dirty()
        self._rank()

    def _toggle_column(self, name: str, on: bool) -> None:
        shown = self._shown()
        (shown.add if on else shown.discard)(name)
        if not shown:                              # never none at all
            self._sync_column_checks()
            return
        self._set_show(shown)

    def _show_all(self) -> None:
        self._set_show(set(self._col_order))

    def _show_key_only(self) -> None:
        if self._col_order:
            self._set_show({self._col_order[0]})

    def _refresh_columns_menu(self) -> None:
        order = self._all_columns()
        if order != self._col_order and not self._cols_menu.isVisible():
            self._col_order = order
            m = self._cols_menu
            m.clear()
            self._show_all_act = m.addAction("Show all")
            self._show_all_act.triggered.connect(lambda _=False: self._show_all())
            self._key_only_act = m.addAction("Show none except the key")
            self._key_only_act.triggered.connect(lambda _=False: self._show_key_only())
            m.addSeparator()
            labels = dict(self._columns())
            self._col_actions = {}
            for n in order:
                act = m.addAction(labels.get(n, n))
                act.setCheckable(True)
                act.toggled.connect(lambda on, n=n: self._toggle_column(n, on))
                self._col_actions[n] = act
        self._sync_column_checks()

    def _sync_column_checks(self) -> None:
        shown = self._shown()
        for n, act in self._col_actions.items():
            act.blockSignals(True)
            act.setChecked(n in shown)
            act.blockSignals(False)
        total = len(self._col_order)
        k = len([n for n in self._col_order if n in shown])
        self._cols_btn.setText(f"Columns: all {total} ▾" if k == total else f"Columns: {k} of {total} ▾")

    def _open_columns(self) -> None:
        self._refresh_columns_menu()
        self._cols_menu.popup(self._cols_btn.mapToGlobal(QPoint(0, self._cols_btn.height())))

    # ------------------------------------------------------------ rank + result

    def _rank(self) -> None:
        self._debounce.stop()
        n = len(self._numbers)
        self._count_lbl.setText(f"{n} number{'s' if n != 1 else ''}" + ("" if self._use_numbers or not n
                                                                          else " · off"))
        self._expand_nums_btn.setVisible(n > 20)
        self._clear_nums_btn.setVisible(n > 0)
        if self._table is None:
            self._result = None
            self._fill_grid()
            self._summary.setText("")
            self._show_missing([])
            self._show_notes([])
            return
        try:
            res = ranking.rank(self._table, self._recipe_for_rank(), self._active_numbers())
        except (ranking.RecipeError, KeyError, TypeError, ValueError) as e:
            self._result = None
            self._fill_grid()
            self._summary.setText("")
            self._recipe_error(str(e))
            self._show_missing([])
            self._show_notes([])
            return
        self._result = res
        self._recipe_error("")
        self._refresh_columns_menu()
        self._fill_grid()
        parts = [f"Ranked {res['kept']} of {len(self._table.rows)} rows"]
        if self._active_numbers():
            parts.append(f"matched numbers on {self._label_of(res.get('key') or '')}")
        if res["kept"] < res["total"]:
            parts.append(f"{res['total'] - res['kept']} failed a condition")
        miss = res.get("missing") or []
        if miss:
            noun = "number" if len(miss) == 1 else "numbers"
            parts.append(f"{len(miss)} {noun} not in the table"
                         + (": " + ", ".join(miss) if len(miss) <= MISSING_INLINE else ""))
        self._summary.setText(" · ".join(parts))
        self._show_missing(miss if len(miss) > MISSING_INLINE else [])
        self._show_notes(res.get("notes") or [])

    def _show_missing(self, miss: "list[str]") -> None:
        self._missing_lbl.setText(", ".join(miss))
        self._missing_btn.setVisible(bool(miss))
        if not miss:
            self._missing_lbl.hide()
        self._missing_btn.setText("hide" if self._missing_lbl.isVisible() else "show")

    def _toggle_missing(self) -> None:
        self._missing_lbl.setVisible(not self._missing_lbl.isVisible())
        self._missing_btn.setText("hide" if self._missing_lbl.isVisible() else "show")

    def _show_notes(self, notes: "list[str]") -> None:
        self._notes_lbl.setText("\n".join(notes))
        self._notes_lbl.setVisible(bool(notes))

    def _recipe_for_rank(self) -> dict:
        """The recipe as the ranker wants it: half-built rows left out, so an
        edit in progress does not blank the result. What names a column this
        table lacks is left for `rank.fit`, which says so in `notes`."""
        r = copy.deepcopy(self._recipe)
        r["derived"] = [d for d in r.get("derived", []) if d.get("name") and d.get("sum")]
        r["filters"] = [f for f in r.get("filters", []) if str(f.get("value", "")).strip()]
        return r

    def _fill_grid(self) -> None:
        g = self._grid
        g.setSortingEnabled(False)
        g.clear()
        res = self._result
        if not res:
            g.setRowCount(0)
            g.setColumnCount(0)
            self._display = []
            return
        display = [(c["name"], c["label"]) for c in res["columns"]]
        self._display = display
        criteria = self._recipe_for_rank().get("criteria", [])
        scored = bool(res["rows"] and res["rows"][0].get("_parts"))
        lead = ["#", "Score"] if scored else ["#"]
        g.setColumnCount(len(lead) + len(display))
        g.setHorizontalHeaderLabels(lead + [l for _n, l in display])
        rows = res["rows"]
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        numeric = [all(table.number(r.get(n)) is not None for r in rows[:50] if r.get(n) not in (None, ""))
                   for n, _l in display]
        for c in range(len(lead)):
            g.horizontalHeaderItem(c).setTextAlignment(right)
        off = len(lead)
        for j, (n, l) in enumerate(display):
            hi = g.horizontalHeaderItem(off + j)
            if hi is not None:
                hi.setTextAlignment(right if numeric[j] else left)
                if l != n:
                    hi.setToolTip(n)
        g.setRowCount(len(rows))
        labels = dict(self._columns())
        crit_labels = {c["column"]: labels.get(c["column"], c["column"]) for c in criteria}
        for i, row in enumerate(rows):
            rank_item = _Item(str(row["_rank"]), row["_rank"])
            rank_item.setTextAlignment(right)
            g.setItem(i, 0, rank_item)
            if scored:
                score = _Item(f"{row['_score']:.1f}", row["_score"])
                score.setTextAlignment(right)
                score.setToolTip("Percentile per Rank-by column (100 = best):\n" + "\n".join(
                    f"  {crit_labels.get(k, k)}: {v:.0f}" for k, v in (row.get("_parts") or {}).items()))
                g.setItem(i, 1, score)
            for j, (n, l) in enumerate(display):
                v = row.get(n)
                num = table.number(v) if v is not None and not (isinstance(v, str) and not v.strip()) else None
                it = _Item(format_value(v, n, l), num if num is not None else str(v if v is not None else ""))
                if num is not None:
                    it.setTextAlignment(right)
                g.setItem(i, off + j, it)
        g.setSortingEnabled(True)
        g.sortItems(0, Qt.SortOrder.AscendingOrder)

    def visible_rows(self) -> "list[list[str]]":
        """The result as shown — header first, rows in the on-screen order."""
        g = self._grid
        if g.columnCount() == 0:
            return []
        out = [[g.horizontalHeaderItem(c).text() for c in range(g.columnCount())]]
        for r in range(g.rowCount()):
            out.append([(g.item(r, c).text() if g.item(r, c) else "") for c in range(g.columnCount())])
        return out

    def _copy(self) -> None:
        rows = self.visible_rows()
        if not rows:
            return
        QGuiApplication.clipboard().setText("\n".join("\t".join(r) for r in rows))
        self._say(f"Copied {len(rows) - 1} rows.")

    def _export(self) -> None:
        rows = self.visible_rows()
        if not rows:
            return
        base = os.path.splitext(self._filename or "ranking")[0] + "-ranked.csv"
        path, _f = QFileDialog.getSaveFileName(self, "Export the ranking", base, "CSV (*.csv)")
        if not path:
            return
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(buf.getvalue())
        except OSError as e:
            self._say(f"Could not save {os.path.basename(path)}: {e.strerror or e}", error=True)
            return
        self._say(f"Saved {len(rows) - 1} rows to {os.path.basename(path)}.")


def _norm(recipe: dict) -> dict:
    """A recipe compared for "edited": name aside, weights as numbers."""
    r = copy.deepcopy(recipe)
    r.pop("name", None)
    for c in r.get("criteria", []):
        c["weight"] = float(c.get("weight", 1))
    for k in ("derived", "filters", "criteria", "show"):
        r.setdefault(k, [])
    return r
