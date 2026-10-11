"""RankerView — the Mac's Ranker tab: drop a table and/or screenshots, get a ranking.

Four bands, top to bottom:

  INPUT     one drop zone for the whole panel. Any mix of table files
            (.html .htm .csv .tsv .txt .json) and pictures (.png .jpg .heic
            …), dragged in, chosen with "Choose files…", or pasted (⌘V / Ctrl+V
            of an image, a file, or a copied table). A table is read at once
            (`table.read`); pictures are read in a background thread
            (`ocr.numbers_from_images` compiles its Swift helper the first time,
            1–4 s) and their numbers become the saved list.
  NUMBERS   the list as editable text, and a "Filter by these numbers" switch.
            Off ranks every row but KEEPS the list (`use_numbers` in the store),
            so switching back on restores it. After a ranking, the numbers with
            no row in the table are named.
  RANKING   the recipe (a saved preset): key column, combined columns,
            conditions, criteria, shown columns. Every change re-ranks, debounced.
            Dropdowns show a column's LABEL (the fire-emoji "24h" header) and store its NAME
            ("Burned24h"), as the presets do.
  RESULT    the ranked rows, sortable by any header (# returns to rank order),
            per-criterion percentiles in the score's tooltip; Copy (TSV) and
            Export CSV….

The panel calls `table`, `ocr`, `rank` and `store` directly, as the other Mac
panels call their stores — never the HTTP routes, which are the phone's door.
"""

from __future__ import annotations

import copy
import csv
import io
import os
import re
import threading
from typing import Callable

from PyQt6.QtCore import QBuffer, QIODevice, QObject, Qt, QTimer, QUrl, pyqtSignal
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
_DIRECTION = {"higher": "▲ Higher is better", "lower": "▼ Lower is better"}


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
QLabel#rk_title {{ font-size: 20px; font-weight: 600; }}
QLabel#rk_muted {{ color: {p['muted']}; }}
QLabel#rk_section {{ font-size: 11px; font-weight: 600; color: {p['muted']};
    letter-spacing: 0.5px; }}
QLabel#rk_error {{ color: {p['bad']}; }}
QLabel#rk_warn {{ color: {p['accent']}; }}
QLabel#rk_summary {{ font-weight: 600; }}
QFrame#rk_drop {{ border: 1px dashed {p['mid']}; border-radius: 8px; background: {p['bg2']}; }}
QFrame#rk_drop[hot="true"] {{ border: 2px dashed {p['accent']}; background: {p['soft']}; }}
QFrame#rk_drop QLabel {{ background: transparent; border: none; }}
QFrame#rk_box {{ border: 1px solid {p['border']}; border-radius: 8px; background: {p['surface']}; }}
QFrame#rk_box QLabel {{ background: transparent; border: none; }}
QFrame#rk_rule {{ background: {p['border']}; border: none; max-height: 1px; min-height: 1px; }}
QPushButton#rk_chip {{ padding: 3px 10px; border: 1px solid {p['border']}; border-radius: 4px;
    background: transparent; color: {p['text']}; }}
QPushButton#rk_chip:hover {{ border-color: {p['accent']}; }}
QPushButton#rk_chip:checked {{ background: {p['soft']}; border-color: {p['accent']}; }}
QPushButton#rk_link, QToolButton#rk_link {{ border: none; background: transparent;
    color: {p['muted']}; padding: 0 4px; }}
QPushButton#rk_link:hover, QToolButton#rk_link:hover {{ color: {p['accent']}; }}
QPushButton#rk_danger {{ color: {p['bad']}; }}
QToolButton#rk_toggle {{ border: none; background: transparent; font-size: 14px; font-weight: 600;
    color: {p['text']}; padding: 0; }}
QToolButton#rk_cols {{ border: 1px solid {p['border']}; border-radius: 4px; padding: 3px 8px;
    background: {p['bg2']}; color: {p['text']}; text-align: left; }}
QPlainTextEdit#rk_numbers {{ font-family: {_styles.MONO_FONT}; background: {p['bg2']};
    border: 1px solid {p['border']}; border-radius: 4px; padding: 2px 4px; }}
QPlainTextEdit#rk_numbers:focus {{ border-color: {p['accent']}; }}
QLineEdit {{ background: {p['bg2']}; border: 1px solid {p['border']}; border-radius: 4px;
    padding: 3px 6px; }}
QLineEdit:focus {{ border-color: {p['accent']}; }}
QCheckBox#rk_switch {{ font-weight: 600; }}
QTableWidget#rk_result {{ background: {p['bg']}; alternate-background-color: {p['bg2']};
    border: 1px solid {p['border']}; border-radius: 6px; gridline-color: transparent; }}
QTableWidget#rk_result::item {{ padding: 2px 16px 2px 6px; }}
QTableWidget#rk_result::item:selected {{ background: {p['soft']}; color: {p['text']}; }}
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


def _rule() -> QFrame:
    f = QFrame()
    f.setObjectName("rk_rule")
    return f


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
        self._ocr_job = 0
        self._reading = False
        self._name_mode = ""                     # "new" | "saveas" while the name bar is open
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
        outer.setContentsMargins(20, 16, 20, 12)
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(_label("Ranker", "rk_title", wrap=False))
        top.addStretch(1)
        self._paste_btn = _button("Paste", "", self.paste)
        self._paste_btn.setToolTip("Paste a picture, a file or a copied table (⌘V / Ctrl+V)")
        self._choose_btn = _button("Choose files…", "", self._choose_files)
        top.addWidget(self._paste_btn)
        top.addWidget(self._choose_btn)
        outer.addLayout(top)

        # INPUT — the drop zone
        self._drop = QFrame()
        self._drop.setObjectName("rk_drop")
        self._drop.setProperty("hot", False)
        dv = QVBoxLayout(self._drop)
        dv.setContentsMargins(14, 10, 14, 10)
        dv.setSpacing(3)
        self._drop_hint = _label(
            "Drop a table (.html .csv .tsv .json) and/or screenshots anywhere here — "
            "or Choose files…, or paste.", "rk_muted")
        dv.addWidget(self._drop_hint)
        self._table_lbl = _label("No table yet.", "rk_summary")
        self._table_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dv.addWidget(self._table_lbl)
        self._status = _label("", "rk_muted")
        self._status.hide()
        dv.addWidget(self._status)
        eng = ocr.engine()
        self._engine_lbl = _label(
            "Reading numbers from pictures needs a Mac (Apple Vision) or Tesseract installed — "
            "you can type the numbers below instead." if eng == "none"
            else f"Pictures are read on this machine ({'Apple Vision' if eng == 'vision' else 'Tesseract'}).",
            "rk_warn" if eng == "none" else "rk_muted")
        dv.addWidget(self._engine_lbl)
        outer.addWidget(self._drop)

        # NUMBERS
        nums = QFrame()
        nums.setObjectName("rk_box")
        nv = QVBoxLayout(nums)
        nv.setContentsMargins(14, 10, 14, 10)
        nv.setSpacing(6)
        nrow = QHBoxLayout()
        self._use_box = QCheckBox("Filter by these numbers")
        self._use_box.setObjectName("rk_switch")
        self._use_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._use_box.toggled.connect(self._use_toggled)
        nrow.addWidget(self._use_box)
        self._count_lbl = _label("", "rk_muted", wrap=False)
        nrow.addWidget(self._count_lbl)
        nrow.addStretch(1)
        self._clear_nums_btn = _button("Clear list", "rk_link", self._clear_numbers)
        nrow.addWidget(self._clear_nums_btn)
        nv.addLayout(nrow)
        self._numbers_edit = QPlainTextEdit()
        self._numbers_edit.setObjectName("rk_numbers")
        self._numbers_edit.setTabChangesFocus(True)
        self._numbers_edit.setFixedHeight(52)
        self._numbers_edit.setPlaceholderText(
            "Numbers from a picture, or typed: 1172, 153, 209 … — empty ranks every row")
        self._numbers_edit.textChanged.connect(self._numbers_typed)
        nv.addWidget(self._numbers_edit)
        self._missing_lbl = _label("", "rk_warn")
        self._missing_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._missing_lbl.hide()
        nv.addWidget(self._missing_lbl)
        outer.addWidget(nums)

        # RANKING — the recipe
        rbox = QFrame()
        rbox.setObjectName("rk_box")
        rv = QVBoxLayout(rbox)
        rv.setContentsMargins(14, 8, 14, 8)
        rv.setSpacing(6)
        head = QHBoxLayout()
        self._recipe_toggle = QToolButton()
        self._recipe_toggle.setObjectName("rk_toggle")
        self._recipe_toggle.setCheckable(True)
        self._recipe_toggle.setText("▸  Ranking")
        self._recipe_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._recipe_toggle.toggled.connect(self._toggle_recipe)
        head.addWidget(self._recipe_toggle)
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(260)
        self._preset_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._preset_combo.currentIndexChanged.connect(lambda _i: self._preset_chosen())
        head.addWidget(self._preset_combo)
        self._dirty_lbl = _label("", "rk_warn", wrap=False)
        head.addWidget(self._dirty_lbl)
        head.addStretch(1)
        self._new_btn = _button("New", "", lambda: self._open_name_bar("new"))
        self._save_btn = _button("Save", "", self._save_preset)
        self._saveas_btn = _button("Save as…", "", lambda: self._open_name_bar("saveas"))
        self._delete_btn = _button("Delete", "", self._ask_delete)
        for b in (self._new_btn, self._save_btn, self._saveas_btn, self._delete_btn):
            head.addWidget(b)
        rv.addLayout(head)

        # name bar (New / Save as) and delete confirmation, in the panel
        self._name_bar = QWidget()
        nb = QHBoxLayout(self._name_bar)
        nb.setContentsMargins(0, 0, 0, 0)
        self._name_caption = _label("Name:", "rk_muted", wrap=False)
        nb.addWidget(self._name_caption)
        self._name_edit = QLineEdit()
        self._name_edit.returnPressed.connect(self._name_ok)
        nb.addWidget(self._name_edit, 1)
        self._name_ok_btn = _button("OK", "", self._name_ok)
        self._name_cancel_btn = _button("Cancel", "", self._close_bars)
        nb.addWidget(self._name_ok_btn)
        nb.addWidget(self._name_cancel_btn)
        self._name_bar.hide()
        rv.addWidget(self._name_bar)

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
        rv.addWidget(self._confirm_bar)
        self._recipe_msg = _label("", "rk_error")
        self._recipe_msg.hide()
        rv.addWidget(self._recipe_msg)

        self._recipe_scroll = QScrollArea()
        self._recipe_scroll.setWidgetResizable(True)
        self._recipe_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._recipe_scroll.setMaximumHeight(340)
        self._recipe_body = QWidget()
        self._recipe_layout = QVBoxLayout(self._recipe_body)
        self._recipe_layout.setContentsMargins(0, 4, 6, 4)
        self._recipe_layout.setSpacing(4)
        self._recipe_scroll.setWidget(self._recipe_body)
        self._recipe_scroll.hide()
        rv.addWidget(self._recipe_scroll)
        outer.addWidget(rbox)

        # RESULT
        rrow = QHBoxLayout()
        self._summary = _label("", "rk_summary")
        self._summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        rrow.addWidget(self._summary, 1)
        self._copy_btn = _button("Copy", "", self._copy)
        self._export_btn = _button("Export CSV…", "", self._export)
        rrow.addWidget(self._copy_btn)
        rrow.addWidget(self._export_btn)
        outer.addLayout(rrow)

        self._grid = QTableWidget()
        self._grid.setObjectName("rk_result")
        self._grid.setAlternatingRowColors(True)
        self._grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._grid.verticalHeader().hide()
        self._grid.setShowGrid(False)
        self._grid.horizontalHeader().setHighlightSections(False)
        self._grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._grid.horizontalHeader().setStretchLastSection(False)
        self._grid.setSortingEnabled(True)
        outer.addWidget(self._grid, 1)

    # ------------------------------------------------------------ contract

    def reload(self) -> None:
        """Re-read presets, the number list and the remembered table; re-rank.
        An unsaved edit to the open recipe survives a reload of the same preset."""
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

    def apply_theme(self, dark: bool) -> None:
        self._dark = dark
        self._pal = _palette(dark)
        self.setStyleSheet(_qss(self._pal))

    def apply_ui_config(self, ui) -> None:
        """Nothing size-related is configurable here yet."""

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        QTimer.singleShot(0, self.reload)

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
        self._drop.setProperty("hot", on)
        _repolish(self._drop)

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
            low = p.lower()
            (pictures if low.endswith(IMAGE_EXT) else tables).append(p)
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
        paths, _f = QFileDialog.getOpenFileNames(self, "Choose a table and/or pictures", "", FILE_FILTER)
        if paths:
            self.take_files(list(paths))

    def _load_table(self, name: str, data: bytes) -> None:
        try:
            t = table.read(name, data)
        except (table.TableError, ValueError) as e:
            self._say(f"{name}: {e}", error=True)
            return
        self._table, self._filename = t, name
        store.update(last_table={"filename": name, **t.to_json()})
        self._say("")
        self._show_table_status()
        self._rebuild_editor()
        self._rank()

    def _show_table_status(self) -> None:
        if self._table is None:
            self._table_lbl.setText("No table yet.")
        else:
            self._table_lbl.setText(f"{self._filename} · {len(self._table.rows)} rows · "
                                    f"{len(self._table.columns)} columns")

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
            self._say("No numbers found in that picture — type them below.", error=True)
            return
        self._say(f"Found {len(found)} numbers in the picture.")
        self._set_numbers([int(n) for n in found], use=True)

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
        store.update(**fields)
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

    def _use_toggled(self, on: bool) -> None:
        self._use_numbers = on
        store.update(use_numbers=on)
        self._rank()

    def _active_numbers(self) -> "list[int]":
        return list(self._numbers) if self._use_numbers else []

    # ------------------------------------------------------------ presets

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
        self._dirty_lbl.setText("• edited" if self._dirty() else "")

    def _preset_chosen(self) -> None:
        name = self._preset_combo.currentData()
        if not name or name == self._preset:
            return
        self._preset = name
        self._recipe = copy.deepcopy(self._data["presets"][name])
        self._data = store.update(preset=name)
        self._close_bars()
        self._rebuild_editor()
        self._update_dirty()
        self._rank()

    def _recipe_error(self, text: str) -> None:
        self._recipe_msg.setText(text)
        self._recipe_msg.setVisible(bool(text))

    def _save_preset(self, name: "str | None" = None) -> None:
        name = name or self._preset
        if not self._recipe.get("criteria"):
            self._recipe_error("A recipe needs at least one thing to rank by — add a criterion first.")
            return
        recipe = copy.deepcopy(self._recipe)
        recipe["name"] = name
        presets = dict(self._data["presets"])
        presets[name] = recipe
        self._data = store.update(presets=presets, preset=name)
        self._preset, self._recipe = name, copy.deepcopy(recipe)
        self._recipe_error("")
        self._close_bars()
        self._fill_presets()

    def _open_name_bar(self, mode: str) -> None:
        self._confirm_bar.hide()
        self._name_mode = mode
        self._name_caption.setText("New recipe:" if mode == "new" else "Save as:")
        self._name_edit.setText("" if mode == "new" else f"{self._preset} (copy)")
        self._name_bar.show()
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _name_ok(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._recipe_error("Give the recipe a name.")
            return
        if self._name_mode == "new":
            if name in self._data["presets"]:
                self._recipe_error(f"There is already a recipe called {name!r}.")
                return
            self._recipe = self._blank_recipe(name)
            self._preset = name
            presets = dict(self._data["presets"])
            presets[name] = copy.deepcopy(self._recipe)
            self._data = store.update(presets=presets, preset=name)
            self._recipe_error("")
            self._close_bars()
            self._fill_presets()
            self._recipe_toggle.setChecked(True)
            self._rebuild_editor()
            self._rank()
        else:
            self._save_preset(name)

    def _blank_recipe(self, name: str) -> dict:
        cols = self._table.names if self._table else []
        key = cols[0] if cols else ""
        numeric = [c for c in cols[1:] if self._table and
                   any(table.number(r.get(c)) is not None for r in self._table.rows[:20])]
        crit = [{"column": numeric[0], "better": "higher", "weight": 1}] if numeric else []
        return {"name": name, "key": key, "derived": [], "filters": [], "criteria": crit, "show": []}

    def _ask_delete(self) -> None:
        if len(self._data["presets"]) <= 1:
            self._recipe_error("Keep at least one recipe — edit this one instead.")
            return
        self._name_bar.hide()
        self._confirm_lbl.setText(f"Delete the recipe {self._preset!r}? This cannot be undone.")
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
        self._name_mode = ""

    # ------------------------------------------------------------ recipe editor

    def _toggle_recipe(self, on: bool) -> None:
        self._recipe_toggle.setText(("▾" if on else "▸") + "  Ranking")
        self._recipe_scroll.setVisible(on)

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
        for n, l in cols:
            box.addItem(l if l == n else f"{l}  ({n})", n)
        if selected and box.findData(selected) < 0:
            box.addItem(f"{selected}  (not in this table)", selected)
        i = box.findData(selected)
        box.setCurrentIndex(max(i, 0))
        box.currentIndexChanged.connect(lambda _i: on_change(box.currentData()))
        return box

    def _columns_menu_button(self, chosen: "list[str]", cols, on_change, empty_text: str) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("rk_cols")
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
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
            act = menu.addAction(l if l == n else f"{l}  ({n})")
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
        lay = self._recipe_layout
        _clear(lay)
        r = self._recipe
        cols = self._columns()
        table_cols = list(self._table.columns) if self._table else []

        # key
        row = QHBoxLayout()
        row.addWidget(_label("Numbers match the column", "rk_muted", wrap=False))
        self._key_combo = self._column_combo(r.get("key") or (table_cols[0][0] if table_cols else ""),
                                             table_cols, lambda v: self._edit("key", v))
        row.addWidget(self._key_combo)
        row.addStretch(1)
        lay.addLayout(row)

        # criteria
        lay.addWidget(_label("RANK BY", "rk_section", wrap=False))
        self._criterion_rows = []
        for i, c in enumerate(r.get("criteria", [])):
            row = QHBoxLayout()
            combo = self._column_combo(c["column"], cols, lambda v, i=i: self._edit_list("criteria", i, "column", v))
            combo.setMinimumWidth(240)
            row.addWidget(combo)
            dirb = _button(_DIRECTION.get(c.get("better"), _DIRECTION["higher"]), "rk_chip")
            dirb.setToolTip("Click to flip")
            dirb.clicked.connect(lambda _=False, i=i: self._flip_direction(i))
            dirb.setMinimumWidth(150)
            row.addWidget(dirb)
            row.addWidget(_label("weight", "rk_muted", wrap=False))
            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setValue(int(round(float(c.get("weight", 1)))))
            spin.valueChanged.connect(lambda v, i=i: self._edit_list("criteria", i, "weight", v))
            row.addWidget(spin)
            rm = self._remove_btn(lambda i=i: self._remove("criteria", i))
            row.addWidget(rm)
            row.addStretch(1)
            lay.addLayout(row)
            self._criterion_rows.append({"column": combo, "direction": dirb, "weight": spin, "remove": rm})
        self._add_criterion_btn = _button("+ Add criterion", "rk_link", self._add_criterion)
        lay.addWidget(self._add_criterion_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # conditions
        lay.addWidget(_label("ONLY ROWS WHERE", "rk_section", wrap=False))
        for i, f in enumerate(r.get("filters", [])):
            row = QHBoxLayout()
            fcombo = self._column_combo(f["column"], cols,
                                        lambda v, i=i: self._edit_list("filters", i, "column", v))
            fcombo.setMinimumWidth(240)
            row.addWidget(fcombo)
            op = QComboBox()
            op.addItems(list(ranking.OPS))
            op.setCurrentIndex(max(op.findText(f.get("op", "<=")), 0))
            op.currentTextChanged.connect(lambda v, i=i: self._edit_list("filters", i, "op", v))
            row.addWidget(op)
            val = QLineEdit(str(f.get("value", "")))
            val.setFixedWidth(120)
            val.textEdited.connect(lambda v, i=i: self._edit_list("filters", i, "value", v))
            row.addWidget(val)
            row.addWidget(self._remove_btn(lambda i=i: self._remove("filters", i)))
            row.addStretch(1)
            lay.addLayout(row)
        lay.addWidget(_button("+ Add condition", "rk_link", self._add_filter), 0, Qt.AlignmentFlag.AlignLeft)

        # combined columns
        lay.addWidget(_label("COMBINED COLUMNS (a sum of others)", "rk_section", wrap=False))
        for i, d in enumerate(r.get("derived", [])):
            row = QHBoxLayout()
            name = QLineEdit(d.get("name", ""))
            name.setPlaceholderText("name")
            name.setFixedWidth(130)
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
        lay.addWidget(_button("+ Add combined column", "rk_link", self._add_derived), 0, Qt.AlignmentFlag.AlignLeft)

        # shown columns
        row = QHBoxLayout()
        row.addWidget(_label("Show", "rk_muted", wrap=False))
        row.addWidget(self._columns_menu_button(
            r.get("show", []), cols, lambda v: self._edit("show", v),
            "the key and the criteria"))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self._update_dirty()

    def _edit(self, field: str, value) -> None:
        self._recipe[field] = value
        self._changed()

    def _edit_list(self, field: str, i: int, key: str, value) -> None:
        items = self._recipe.setdefault(field, [])
        if 0 <= i < len(items):
            items[i][key] = value
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

    def _first_numeric(self) -> str:
        cols = self._columns()
        key = self._recipe.get("key")
        for n, _l in cols:
            if n != key:
                return n
        return cols[0][0] if cols else ""

    def _add_criterion(self) -> None:
        self._recipe.setdefault("criteria", []).append(
            {"column": self._first_numeric(), "better": "higher", "weight": 1})
        self._rebuild_editor()
        self._changed()

    def _add_filter(self) -> None:
        self._recipe.setdefault("filters", []).append({"column": self._first_numeric(), "op": "<=", "value": "1"})
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
        stored = self._data.get("numbers") or []
        if self._numbers != stored:
            self._data = store.update(numbers=self._numbers)
        self._rank()

    # ------------------------------------------------------------ rank + result

    def _rank(self) -> None:
        self._debounce.stop()
        n = len(self._numbers)
        self._count_lbl.setText(f"{n} number{'s' if n != 1 else ''}" + ("" if self._use_numbers or not n
                                                                          else " · not filtering"))
        if self._table is None:
            self._result = None
            self._fill_grid()
            self._summary.setText("Drop a table to rank it.")
            self._missing_lbl.hide()
            return
        try:
            res = ranking.rank(self._table, self._recipe_for_rank(), self._active_numbers())
        except (ranking.RecipeError, KeyError, TypeError, ValueError) as e:
            self._result = None
            self._fill_grid()
            self._summary.setText("")
            self._recipe_error(str(e))
            self._missing_lbl.hide()
            return
        self._result = res
        self._recipe_error("")
        self._fill_grid()
        key = res.get("key") or ""
        noun = f"{key.lower()}s" if key.isalpha() and not key.lower().endswith("s") else "rows"
        text = f"Ranked {res['kept']} of {res['total']} {noun}"
        if self._active_numbers():
            text += f" (filtered by {len(self._active_numbers())} numbers, from {len(self._table.rows)} in the table)"
        if res["kept"] < res["total"]:
            text += f" — {res['total'] - res['kept']} failed a condition"
        self._summary.setText(text)
        miss = res.get("missing") or []
        if miss:
            are = "isn't" if len(miss) == 1 else "aren't"
            self._missing_lbl.setText(f"{len(miss)} of these {are} in the table: {', '.join(miss)}")
            self._missing_lbl.show()
        else:
            self._missing_lbl.hide()

    def _recipe_for_rank(self) -> dict:
        """The recipe as the ranker wants it: half-built rows left out, so an
        edit in progress does not blank the result."""
        r = copy.deepcopy(self._recipe)
        r["derived"] = [d for d in r.get("derived", []) if d.get("name") and d.get("sum")]
        names = set(self._table.names) | {d["name"] for d in r["derived"]} if self._table else set()
        r["filters"] = [f for f in r.get("filters", []) if str(f.get("value", "")).strip()
                        and f.get("column") in names]
        r["criteria"] = [c for c in r.get("criteria", []) if c.get("column") in names]
        r["show"] = [s for s in r.get("show", []) if s in names]
        if r.get("key") and self._table and r["key"] not in self._table.names:
            r["key"] = self._table.names[0]
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
        have = {n for n, _ in display}
        labels = dict(self._columns())
        for c in self._recipe_for_rank().get("criteria", []):
            if c["column"] not in have:
                display.append((c["column"], labels.get(c["column"], c["column"])))
                have.add(c["column"])
        self._display = display
        g.setColumnCount(2 + len(display))
        g.setHorizontalHeaderLabels(["#", "Score"] + [l for _n, l in display])
        rows = res["rows"]
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        numeric = [all(table.number(r.get(n)) is not None for r in rows[:50] if r.get(n) not in (None, ""))
                   for n, _l in display]
        for c in (0, 1):
            g.horizontalHeaderItem(c).setTextAlignment(right)
        for j, (n, l) in enumerate(display):
            hi = g.horizontalHeaderItem(2 + j)
            if hi is not None:
                hi.setTextAlignment(right if numeric[j] else left)
                if l != n:
                    hi.setToolTip(n)
        g.setRowCount(len(rows))
        crit_labels = {c["column"]: labels.get(c["column"], c["column"])
                       for c in self._recipe_for_rank().get("criteria", [])}
        for i, row in enumerate(rows):
            rank_item = _Item(str(row["_rank"]), row["_rank"])
            rank_item.setTextAlignment(right)
            g.setItem(i, 0, rank_item)
            score = _Item(f"{row['_score']:.1f}", row["_score"])
            score.setTextAlignment(right)
            parts = row.get("_parts") or {}
            if parts:
                score.setToolTip("Percentile per criterion (100 = best):\n" + "\n".join(
                    f"  {crit_labels.get(k, k)}: {v:.0f}" for k, v in parts.items()))
            g.setItem(i, 1, score)
            for j, (n, l) in enumerate(display):
                v = row.get(n)
                num = table.number(v) if v is not None and not (isinstance(v, str) and not v.strip()) else None
                it = _Item(format_value(v, n, l), num if num is not None else str(v if v is not None else ""))
                if num is not None:
                    it.setTextAlignment(right)
                g.setItem(i, 2 + j, it)
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
