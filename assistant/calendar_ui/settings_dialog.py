"""The Assistant Settings dialog — extracted verbatim from window.py.

Convolution fix #3 (Gil-approved, 2026-09-06): window.py was a ~2,300-line
god-file and this dialog was ~450 of them. Moved whole, unchanged — the
function still takes the window as `self` so every `self._config` /
`self.show_toast` reference works exactly as before; window.py keeps a
3-line delegate. Persistence goes through assistant/config_store.

No longer verbatim: the move carried over a read of `self._pipeline._confirmer`,
an attribute the real Pipeline lost in e3ea4f6, which aborted the whole app on
open (PyQt6 → qFatal on an exception in a slot). Fixed here, and the rows built
from config.yaml / categories.json are now tolerant of what those hand-editable
files actually contain — see tests/unit/test_settings_real_shapes.py.
"""
from __future__ import annotations

import os
import re
import subprocess

from PyQt6.QtCore import QDate, QSettings, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)


from assistant.calendar_ui import icons
from assistant.calendar_ui import styles as _styles
from assistant.calendar_ui.dialog_utils import install_enter_confirms
from assistant.calendar_ui.styles import GRAY_TEXT

# The "Personal" grey, used when a category's own colour is missing or unparseable.
_CAT_DOT_FALLBACK = "#64748b"


def _ui_state() -> QSettings:
    """Which settings sections are folded shut — per machine, not per calendar.

    `QSettings` and not `config.yaml` on purpose: the phone reads that file, and
    it would be odd for folding a box on the Mac to travel. Not
    `~/.assistant_tools` either, which holds the DB, the vocabulary and the
    command memory — window chrome does not belong beside personal data.

    **Built per call, never cached in a module global.** A `QSettings` held at
    module scope is destroyed with the `QApplication` that outlived it, and every
    later use then raises `RuntimeError: wrapped C/C++ object ... has been
    deleted`. That is invisible in a single test and breaks the three that build
    a real dialog after another test has torn an app down — which is exactly how
    it showed up.

    **`MACALENDAR_UI_STATE` redirects it**, like every other store this project
    owns, because the default writes to the user's real macOS preferences and a
    test run has no business folding boxes in the app Gil is using.
    """
    path = os.environ.get("MACALENDAR_UI_STATE")
    if path:
        return QSettings(path, QSettings.Format.IniFormat)
    return QSettings("MACalendar", "CalendarUI")


def open_settings(self) -> None:
    if not self._pipeline:
        return

    from PyQt6.QtWidgets import QFormLayout, QFrame, QGroupBox, QScrollArea

    dialog = QDialog(self)
    dialog.setWindowTitle("Assistant Settings")
    dialog.setMinimumSize(520, 560)
    dialog.resize(560, 720)

    # Grouped into the same sections the iPhone's Settings screen uses
    # (Appearance / Tabs / Hebrew Calendar / Voice / Assistant) and scrolled,
    # with Test & Save pinned. It used to be one flat column of controls with
    # stretches between them, which squeezed everything below "Hebrew
    # Calendar" into overlapping slivers — the Font Sizes grid rendered at
    # zero height and could not be reached at all.
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    scroll.setWidget(content)
    outer.addWidget(scroll, 1)

    layout = QVBoxLayout(content)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(14)

    def section(title: str) -> QVBoxLayout:
        """One titled group that FOLDS AWAY; returns the layout for its controls.

        Gil, 2026-09-17: *"perhaps add a minimize on each section starting to be
        a lot of things there"*. Six sections had grown past one screenful, and
        the dialog scrolls, so the ones you never touch push the ones you do out
        of sight.

        Collapsing is on the header, not on `QGroupBox.setCheckable` — a
        checkbox beside a section title reads as "switch this whole section
        off", which is a different and alarming promise. An arrow that turns
        says only what it does.

        Which sections are folded is remembered in `QSettings`, per machine:
        it is window chrome, not a preference about the calendar, so it has no
        business in `config.yaml` (which the phone also reads) or in
        `~/.assistant_tools` (which holds personal data).
        """
        box = QGroupBox()
        box.setObjectName("collapsible_section")
        outer = QVBoxLayout(box)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(6)

        key = f"settings/section_open/{title}"
        # FOLDED by default (Gil, 2026-09-18: "Default is minimized please"),
        # matching the phone. Both screens shipped opening every section, which
        # undid most of the point: what is hard to find on a long settings
        # screen is a section's NAME, and six open bodies push five of the six
        # names off it. Folded, the list of names IS the screen.
        #
        # Only sections nobody has touched change — `QSettings` holds a value
        # for a section only once it has been folded or opened by hand, so a
        # deliberate choice survives this.
        open_ = _ui_state().value(key, False, type=bool)

        header = QToolButton()
        header.setObjectName(f"section_header_{title.lower().replace(' ', '_')}")
        header.setText(title)
        header.setCheckable(True)
        header.setChecked(open_)
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.setStyleSheet(
            "QToolButton { border: none; background: transparent; font-weight: 600;"
            " padding: 4px 0; text-align: left; }")
        header.setAccessibleName(f"{title} section")
        outer.addWidget(header)

        body = QWidget()
        inner = QVBoxLayout(body)
        inner.setContentsMargins(0, 4, 0, 4)
        inner.setSpacing(8)
        body.setVisible(open_)
        outer.addWidget(body)

        def _toggled(on: bool, _b=body, _h=header, _k=key) -> None:
            _b.setVisible(on)
            _h.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
            _ui_state().setValue(_k, on)
            # Without this the dialog keeps the height it had when everything
            # was open, leaving a folded section sitting above empty space.
            self.adjustSize()

        header.toggled.connect(_toggled)
        layout.addWidget(box)
        return inner

    def _apply(obj, field: str, value) -> None:
        """Set a config field in memory, skipping one this object does not have.

        **The calendar GUI does not reload itself** (CLAUDE.md), so it can be
        running a config module from before a setting existed while lazily
        importing THIS file fresh from disk the moment Settings is opened. That
        mismatch made a brand-new checkbox raise `"NotificationsConfig" object
        has no field "agenda_card"` on a machine whose config.yaml had just been
        written perfectly well.

        Skipping is right rather than lenient: the value is already persisted to
        disk by the time this runs, so the only thing lost is the in-memory
        update that a restart supplies anyway.
        """
        try:
            setattr(obj, field, value)
        except (AttributeError, ValueError, TypeError):
            pass

    def hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("muted")
        lbl.setStyleSheet(
            f"color: {_styles.D_GRAY_TEXT if self._dark else GRAY_TEXT}; font-size: 11px;")
        return lbl

    # ── Appearance ────────────────────────────────────────────────
    appearance = section("Appearance")
    appearance_form = QFormLayout()
    appearance_form.setSpacing(8)
    appearance_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    theme_combo = QComboBox()
    theme_combo.addItems(["Light", "Dark"])
    theme_combo.setCurrentText("Dark" if (self._config.theme == "dark") else "Light")
    theme_combo.setMaximumWidth(160)
    appearance_form.addRow("Theme on startup:", theme_combo)

    accent_state = {"hex": self._config.ui.accent_color or "#f5a524"}
    swatch_row = QHBoxLayout()
    swatch_row.setSpacing(8)
    swatch_buttons: list[QPushButton] = []

    def make_swatch(hex_color: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(24, 24)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def refresh():
            selected = accent_state["hex"].lower() == hex_color.lower()
            ring = "#ffffff" if selected else "transparent"
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {hex_color}; border-radius: 12px; "
                f"padding: 0; border: 2px solid {ring}; }}"
            )
        btn._refresh = refresh
        refresh()

        def on_click():
            accent_state["hex"] = hex_color
            custom_btn.setStyleSheet("")
            for b in swatch_buttons:
                b._refresh()
        btn.clicked.connect(on_click)
        return btn

    for _name, hex_color in _styles.ACCENT_PRESETS:
        b = make_swatch(hex_color)
        b.setToolTip(_name)
        swatch_buttons.append(b)
        swatch_row.addWidget(b)

    custom_btn = QPushButton("Custom…")
    custom_btn.setObjectName("flat")

    def pick_custom():
        initial = QColor(accent_state["hex"])
        color = QColorDialog.getColor(initial, dialog, "Choose Accent Color")
        if color.isValid():
            accent_state["hex"] = color.name()
            for b in swatch_buttons:
                b._refresh()
            custom_btn.setStyleSheet(f"QPushButton#flat {{ border: 2px solid {color.name()}; }}")
    custom_btn.clicked.connect(pick_custom)
    swatch_row.addWidget(custom_btn)
    swatch_row.addStretch(1)
    swatch_holder = QWidget()
    swatch_holder.setLayout(swatch_row)
    appearance_form.addRow("Accent colour:", swatch_holder)
    start_view_combo = QComboBox()
    start_view_combo.setObjectName("start_view")
    for _label, _mode in (("Month", "month"), ("Week", "week"), ("Day", "day"), ("Agenda", "agenda")):
        start_view_combo.addItem(_label, _mode)
    start_view_combo.setCurrentIndex(max(0, start_view_combo.findData(
        getattr(self._config.ui, "start_view", "week"))))
    start_view_combo.setToolTip("The view the calendar shows when the app opens")
    appearance_form.addRow("Open calendar on:", start_view_combo)

    # Which hours Week and Day fit to the window (Gil, 2026-09-29): the rest
    # stay a scroll away, so nothing outside them is ever hidden.
    from assistant.calendar_ui.visible_hours import label as _hour_label, span as _span
    _first, _last = _span(self._config.ui)
    hours_from_combo, hours_to_combo = QComboBox(), QComboBox()
    hours_from_combo.setObjectName("hours_from")
    hours_to_combo.setObjectName("hours_to")
    for _h in range(0, 24):
        hours_from_combo.addItem(_hour_label(_h), _h)
    for _h in range(1, 25):
        hours_to_combo.addItem(_hour_label(_h), _h)
    hours_from_combo.setCurrentIndex(hours_from_combo.findData(_first))
    hours_to_combo.setCurrentIndex(hours_to_combo.findData(_last))
    _hours_row = QHBoxLayout()
    _hours_row.addWidget(hours_from_combo)
    _hours_row.addWidget(QLabel("to"))
    _hours_row.addWidget(hours_to_combo)
    _hours_row.addStretch(1)
    hours_from_combo.setToolTip("Week and Day fit these hours to the window and open "
                                "at the first one. Earlier and later hours are a "
                                "scroll away — nothing is hidden.")
    hours_to_combo.setToolTip(hours_from_combo.toolTip())
    appearance_form.addRow("Show hours:", _hours_row)
    appearance.addLayout(appearance_form)

    compact_cb = QCheckBox("Compact layout density")
    compact_cb.setChecked(self._config.ui.compact_ui)
    appearance.addWidget(compact_cb)

    def update_style(compact: bool):
        layout.setSpacing(10 if compact else 14)
    compact_cb.toggled.connect(update_style)

    appearance.addWidget(hint("Font sizes"))
    font_grid = QGridLayout()
    font_grid.setVerticalSpacing(6)
    font_grid.setHorizontalSpacing(14)
    font_spins: dict[str, QSpinBox] = {}
    for i, (label, attr) in enumerate((("Month", "font_month"), ("Week", "font_week"),
                                       ("Day", "font_day"), ("Tasks", "font_tasks"),
                                       ("Coursework", "font_coursework"))):
        spin = QSpinBox()
        spin.setRange(8, 24)
        spin.setValue(getattr(self._config.ui, attr))
        font_spins[attr] = spin
        row, col = divmod(i, 2)
        font_grid.addWidget(QLabel(f"{label}:"), row, col * 2,
                            alignment=Qt.AlignmentFlag.AlignRight)
        font_grid.addWidget(spin, row, col * 2 + 1)
    font_grid.setColumnStretch(4, 1)
    appearance.addLayout(font_grid)
    month_spin, week_spin = font_spins["font_month"], font_spins["font_week"]
    day_spin, tasks_spin = font_spins["font_day"], font_spins["font_tasks"]
    coursework_spin = font_spins["font_coursework"]

    # ── Tabs ──────────────────────────────────────────────────────
    tabs = section("Tabs")
    # One switch per tab that CAN be hidden, straight from the feature
    # registry — the three hand-written boxes this replaced knew nothing of
    # Account, and wrote the old `ui.show_*` keys, which stop being read once
    # `features:` has an entry for the name.
    from assistant.features import registry as _feature_registry
    tab_boxes: dict = {}
    for _f in _feature_registry.all_features():
        if _f.pinned or not _f.has_mac_panel:
            continue
        _cb = QCheckBox(f"Show {_f.label} tab")
        _cb.setObjectName(f"tab_cb_{_f.name}")
        _cb.setChecked(_f.visible())
        tabs.addWidget(_cb)
        tab_boxes[_f.name] = _cb

    def _tab_shown(name: str) -> bool:
        cb = tab_boxes.get(name)
        return cb.isChecked() if cb is not None else True

    # ── Hebrew calendar ───────────────────────────────────────────
    hebrew = section("Hebrew Calendar")
    hebrew_form = QFormLayout()
    hebrew_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    hebrew_mode_combo = QComboBox()
    hebrew_mode_combo.addItem("English only", "english")
    hebrew_mode_combo.addItem("Hebrew only", "hebrew")
    hebrew_mode_combo.addItem("Both", "both")
    idx = hebrew_mode_combo.findData(self._config.hebrew_calendar.display_mode)
    hebrew_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
    hebrew_mode_combo.setMaximumWidth(180)
    hebrew_form.addRow("Show dates as:", hebrew_mode_combo)
    hebrew.addLayout(hebrew_form)
    hebrew_holidays_cb = QCheckBox("Show Jewish / Israeli holidays")
    hebrew_holidays_cb.setChecked(self._config.hebrew_calendar.show_holidays)
    hebrew.addWidget(hebrew_holidays_cb)
    hebrew_israel_cb = QCheckBox("Israel holiday schedule (uncheck for Diaspora)")
    hebrew_israel_cb.setChecked(self._config.hebrew_calendar.israel_holidays)
    hebrew.addWidget(hebrew_israel_cb)
    shabbat_lines_cb = QCheckBox("Mark when Shabbat && yom tov begin and end")
    shabbat_lines_cb.setObjectName("shabbat_lines_cb")
    shabbat_lines_cb.setToolTip(
        "Yellow lines on the Day and Week views at the exact minute of candle\n"
        "lighting and of nightfall, computed for the phone's location when it\n"
        "reports one (iPhone → Settings → Sundown follows this device), else\n"
        "for the place in config.yaml's observance section.")
    shabbat_lines_cb.setChecked(bool(getattr(self._config.hebrew_calendar,
                                             "show_shabbat_times", True)))
    hebrew.addWidget(shabbat_lines_cb)
    # DEVQA Q59 (Gil, 2026-09-26): the rule is a master switch. The label says
    # what it does NOW — a one-off is added with a note, not refused.
    observance_cb = QCheckBox("Keep engine-made events off Shabbat && yom tov")
    observance_cb.setObjectName("observance_enabled_cb")
    observance_cb.setToolTip(
        "For what the assistant books by voice (never your own edits):\n"
        "on a day kept off, a repeating series skips it and a one-off is\n"
        "still added, with a note. Shabbat and yom tov are kept off by\n"
        "default, chol hamoed and ordinary days are not; flip any date\n"
        "below. Uncheck to switch all of it off, whatever the days say.")
    observance_cb.setChecked(bool(getattr(getattr(self._config, "observance", None),
                                          "enabled", True)))
    hebrew.addWidget(observance_cb)

    # THE PER-DAY SWITCH (DEVQA Q60, Gil 2026-09-26): every day has one —
    # "keep engine events off this day" — on by default for Shabbat and yom
    # tov, off for chol hamoed and ordinary days, and any date can be flipped
    # either way. The label and the defaults live in `assistant.observance`
    # (SWITCH_LABEL / DEFAULT_KEPT_OFF); this section only draws them. The
    # overrides are a personal store, not config.yaml, read from the FILE so
    # a change the phone made while this dialog was closed is what you see.
    import datetime as _dt

    from assistant import observance as _ob
    ov_state: dict = dict(_ob.day_overrides())
    ov_loaded = dict(ov_state)

    def _kept_off(d) -> bool:
        v = ov_state.get(d)
        return _ob.default_kept_off(d) if v is None else v == _ob.KEEP_OFF

    def _set_day(d, kept: bool) -> None:
        """One place both lists write through; an override equal to the
        day's default is not an override."""
        if kept == _ob.default_kept_off(d):
            ov_state.pop(d, None)
        else:
            ov_state[d] = _ob.KEEP_OFF if kept else _ob.ALLOW

    def _day_text(d, year: bool = False) -> str:
        fmt = "%a %-d %b %Y" if year else "%a %-d %b"
        name = _ob.day_name(d)
        return f"{d.strftime(fmt)} — {name}" if name else d.strftime(fmt)

    # ── "This week", folded by default; widened over Sukkot / Pesach ──
    wk_start, wk_end, wk_festival = _ob.week_span()
    week_header = QToolButton()
    week_header.setObjectName("observance_week_header")
    week_title = "This week" + (f" — all of {wk_festival}" if wk_festival else "")
    week_header.setText(week_title)
    week_header.setCheckable(True)
    week_header.setChecked(False)
    week_header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    week_header.setArrowType(Qt.ArrowType.RightArrow)
    week_header.setCursor(Qt.CursorShape.PointingHandCursor)
    week_header.setStyleSheet(
        "QToolButton { border: none; background: transparent; padding: 2px 0; }")
    week_header.setAccessibleName("This week's days")
    hebrew.addWidget(week_header)

    week_body = QWidget()
    week_body.setObjectName("observance_week_body")
    week_grid = QGridLayout(week_body)
    week_grid.setContentsMargins(16, 0, 0, 0)
    week_grid.setHorizontalSpacing(10)
    week_grid.setVerticalSpacing(4)
    week_grid.setColumnStretch(0, 1)
    week_caption = QLabel(f"Checked: {_ob.SWITCH_LABEL.lower()}")
    week_caption.setObjectName("muted")
    week_grid.addWidget(week_caption, 0, 0, 1, 2)
    week_rows: dict = {}                    # date -> (label, checkbox)
    _d = wk_start
    while _d <= wk_end:
        lbl = QLabel()
        lbl.setWordWrap(True)
        cb = QCheckBox("Keep off")          # the caption above says the rest
        cb.setObjectName(f"observance_day_{_d.isoformat()}")
        cb.setAccessibleName(f"{_ob.SWITCH_LABEL}: {_d.strftime('%A %-d %B')}")
        cb.toggled.connect(lambda on, _day=_d: (_set_day(_day, on), _ov_render()))
        r = len(week_rows) + 1
        week_grid.addWidget(lbl, r, 0)
        week_grid.addWidget(cb, r, 1)
        week_rows[_d] = (lbl, cb)
        _d += _dt.timedelta(days=1)
    week_body.setVisible(False)
    hebrew.addWidget(week_body)

    def _week_toggled(on: bool) -> None:
        week_body.setVisible(on)
        week_header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.adjustSize()

    week_header.toggled.connect(_week_toggled)

    # ── the days you changed, either way ──
    ov_title = QLabel("Days you changed")
    ov_title.setObjectName("observance_overrides_title")
    hebrew.addWidget(ov_title)
    ov_list = QListWidget()
    ov_list.setObjectName("observance_overrides_list")
    ov_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    ov_list.setMaximumHeight(110)
    ov_list.setAccessibleName("Days you changed")
    hebrew.addWidget(ov_list)

    ov_row = QHBoxLayout()
    ov_row.setSpacing(8)
    ov_date = QDateEdit()
    ov_date.setObjectName("observance_override_date")
    ov_date.setCalendarPopup(True)
    ov_date.setDisplayFormat("ddd d MMM yyyy")
    _today = _dt.date.today()
    ov_date.setDate(QDate(_today.year, _today.month, _today.day))
    ov_date.setMaximumWidth(160)
    ov_row.addWidget(ov_date)
    ov_mode = QComboBox()
    ov_mode.setObjectName("observance_override_mode")
    ov_mode.addItem("Keep off", _ob.KEEP_OFF)
    ov_mode.addItem("Allow", _ob.ALLOW)
    ov_mode.setToolTip("Keep off: keep engine events off the picked day.\n"
                       "Allow: let the engine book it as any day.")
    ov_row.addWidget(ov_mode)
    ov_add = QPushButton("Add")
    ov_add.setObjectName("observance_override_add")
    ov_add.setToolTip("Set the picked day as chosen")
    ov_row.addWidget(ov_add)
    ov_remove = QPushButton("Remove")
    ov_remove.setObjectName("observance_override_remove")
    ov_remove.setToolTip("Put the selected day back to its default")
    ov_row.addWidget(ov_remove)
    ov_row.addStretch(1)
    hebrew.addLayout(ov_row)
    ov_status = hint("")
    ov_status.setObjectName("observance_override_status")
    ov_status.setVisible(False)
    hebrew.addWidget(ov_status)

    def _ov_render() -> None:
        ov_list.clear()
        for d in sorted(ov_state):
            what = "kept off" if ov_state[d] == _ob.KEEP_OFF else "engine may book"
            item = QListWidgetItem(f"{_day_text(d, year=True)}: {what}")
            item.setData(Qt.ItemDataRole.UserRole, d.isoformat())
            ov_list.addItem(item)
        ov_remove.setEnabled(ov_list.currentRow() >= 0)
        # the week rows follow the same state; a changed day reads bold
        for d, (lbl, cb) in week_rows.items():
            changed = d in ov_state
            lbl.setText(_day_text(d) + ("  (changed)" if changed else ""))
            f = lbl.font()
            f.setBold(changed)
            lbl.setFont(f)
            cb.blockSignals(True)
            cb.setChecked(_kept_off(d))
            cb.blockSignals(False)

    def _ov_add() -> None:
        q = ov_date.date()
        d = _dt.date(q.year(), q.month(), q.day())
        kept = ov_mode.currentData() == _ob.KEEP_OFF
        _set_day(d, kept)
        if d not in ov_state:
            ov_status.setText(f"{d:%a %-d %b} is already "
                              f"{'kept off' if kept else 'open to the engine'} by default.")
        else:
            ov_status.setText("")
        ov_status.setVisible(bool(ov_status.text()))
        _ov_render()

    def _ov_remove() -> None:
        item = ov_list.currentItem()
        if item is None:
            return
        ov_state.pop(_dt.date.fromisoformat(item.data(Qt.ItemDataRole.UserRole)), None)
        _ov_render()

    ov_add.clicked.connect(lambda _=False: _ov_add())
    ov_remove.clicked.connect(lambda _=False: _ov_remove())
    ov_list.currentRowChanged.connect(lambda row: ov_remove.setEnabled(row >= 0))
    _ov_render()
    hebrew.addWidget(hint(
        "On a day kept off, a series skips it and a one-off is added with a note; "
        "Shabbat and yom tov run candle lighting to nightfall (meals, leyning and "
        "davening excepted), any other day you keep off is the whole day. "
        "Saved with Save."))

    # ── Events ────────────────────────────────────────────────────
    # DEVQA Q51 (Gil, 2026-09-25): how long an event lasts when nobody said,
    # and the gap between chained events ("gym at 9, then lunch"). Both are
    # read through `assistant/event_defaults.py`, by the engine and by the New
    # Event dialog; a category can override either in Event Colours &
    # Categories, which is where "each category its own" lives.
    from assistant.config import MAX_EVENT_MINUTES, MIN_EVENT_LENGTH
    events_box = section("Events")
    events_cfg = getattr(self._config, "events", None)
    events_form = QFormLayout()
    events_form.setSpacing(8)
    events_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _minutes_spin(name: str, low: int, value) -> QSpinBox:
        spin = QSpinBox()
        spin.setObjectName(name)
        spin.setRange(low, MAX_EVENT_MINUTES)
        spin.setSingleStep(5)
        spin.setSuffix(" min")
        spin.setMaximumWidth(120)
        try:
            spin.setValue(int(value))
        except (TypeError, ValueError):
            pass                     # hand-edited to something unreadable
        return spin

    # Shown from the FILE (through event_defaults), not from `self._config`:
    # the phone can change these while the calendar is open, and the GUI's
    # config object is only read at startup — Save would otherwise write the
    # stale startup value back over the phone's.
    from assistant import event_defaults as _event_defaults
    event_length_spin = _minutes_spin(
        "events_length_spin", MIN_EVENT_LENGTH, _event_defaults.length_minutes(None))
    events_form.addRow("Default length (minutes):", event_length_spin)
    chain_gap_spin = _minutes_spin(
        "events_gap_spin", 0, _event_defaults.gap_minutes(None))
    events_form.addRow("Gap between chained events (minutes):", chain_gap_spin)
    events_box.addLayout(events_form)
    events_box.addWidget(hint(
        "An event with no end said lasts the default length. In “gym at 9, then "
        "lunch”, lunch starts this gap after the gym ends. A category can set its "
        "own of either — Assistant › Event Colours & Categories."))

    # A SERIES WITH NO END GETS A DEFAULT ONE (DEVQA Q57, Gil 2026-09-26: *"for
    # daily up to 2 weeks default, for weekly up to 8 weeks, monthly up to 12
    # months, yearly up to 10 years. can be changed in settings."*). Each is a
    # count in its cadence's own unit, so it is also how many times the series
    # happens. Bounds come from SERIES_END_BOUNDS — the table PATCH /config
    # validates against — and the values from the FILE, as above.
    from assistant.config import SERIES_END_BOUNDS
    series_title = QLabel("A repeating event with no end stops after")
    series_title.setObjectName("events_series_title")
    events_box.addWidget(series_title)
    series_form = QFormLayout()
    series_form.setSpacing(8)
    series_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    series_spins: dict = {}              # config key -> QSpinBox
    for cadence, unit in (("daily", "days"), ("weekly", "weeks"),
                          ("monthly", "months"), ("yearly", "years")):
        key = _event_defaults.SERIES_END[cadence][0]
        default, top = SERIES_END_BOUNDS[key]
        spin = QSpinBox()
        spin.setObjectName(f"events_series_{cadence}_spin")
        spin.setRange(1, top)
        spin.setSuffix(f" {unit}")
        spin.setMaximumWidth(120)
        spin.setValue(_event_defaults.series_count(cadence) or default)
        series_form.addRow(f"{cadence} —", spin)
        series_spins[key] = spin
    events_box.addLayout(series_form)
    events_box.addWidget(hint(
        "Only when the words say no end — “until …” always wins — and the reply "
        "names the end it chose."))

    # ── Notifications ─────────────────────────────────────────────
    notif = section("Notifications")
    notif_cfg = getattr(self._config, "notifications", None)

    notif_enabled_cb = QCheckBox("Pre-event notifications")
    notif_enabled_cb.setObjectName("notif_enabled_cb")
    notif_enabled_cb.setToolTip(
        "A heads-up before an event starts. The lead time below is the\n"
        "default; each category can override it or opt out entirely.")
    notif_enabled_cb.setChecked(bool(getattr(notif_cfg, "enabled", True)))
    notif.addWidget(notif_enabled_cb)

    notif_form = QFormLayout()
    notif_form.setSpacing(8)
    notif_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    notif_lead_combo = QComboBox()
    notif_lead_combo.setObjectName("notif_default_lead_combo")
    notif_lead_combo.addItem("Off", 0)
    for _mins in (5, 10, 15, 30, 60):
        notif_lead_combo.addItem(f"{_mins} minutes", _mins)
    try:
        _lead = int(getattr(notif_cfg, "default_lead_minutes", 0) or 0)
    except (TypeError, ValueError):
        _lead = 0                    # hand-edited to something unreadable
    _lead_idx = notif_lead_combo.findData(_lead)
    if _lead_idx < 0:
        # A hand-edited value keeps itself rather than snapping to Off.
        notif_lead_combo.addItem(f"{_lead} minutes", _lead)
        _lead_idx = notif_lead_combo.count() - 1
    notif_lead_combo.setCurrentIndex(_lead_idx)
    notif_lead_combo.setMaximumWidth(160)
    notif_form.addRow("Default lead time:", notif_lead_combo)
    notif.addLayout(notif_form)

    # The iPhone's lock-screen agenda card. The Mac draws no Live Activity, so
    # this control does not change anything here — it is offered so the two
    # settings screens cannot disagree about a shared value (Gil, 2026-09-17:
    # "make sure toggle value is synced with calendar app accordingly"). The
    # label says whose screen it is, or it reads as a broken Mac setting.
    notif_agenda_cb = QCheckBox("Agenda card on the iPhone lock screen")
    notif_agenda_cb.setObjectName("notif_agenda_card_cb")
    notif_agenda_cb.setToolTip(
        "Today's remaining events on the phone's lock screen, with the one\n"
        "running lit up. Clearing it on the phone hides it until 6am.\n"
        "Nothing on the Mac shows this — the switch lives here so both\n"
        "apps agree on it.")
    notif_agenda_cb.setChecked(bool(getattr(notif_cfg, "agenda_card", True)))
    notif.addWidget(notif_agenda_cb)

    notif_speak_cb = QCheckBox("Spoken heads-up (uses the assistant voice)")
    notif_speak_cb.setObjectName("notif_speak_cb")
    notif_speak_cb.setChecked(bool(getattr(notif_cfg, "speak", False)))
    notif.addWidget(notif_speak_cb)

    notif_observance_cb = QCheckBox("Hold on Shabbat && yom tov")
    notif_observance_cb.setObjectName("notif_observance_cb")
    notif_observance_cb.setToolTip(
        "No banners or speech inside Shabbat / yom tov; anything missed\n"
        "waits and is delivered after it goes out.")
    notif_observance_cb.setChecked(bool(getattr(notif_cfg, "respect_observance", True)))
    notif.addWidget(notif_observance_cb)

    notif.addWidget(hint("Per category — Muted silences it outright; Default "
                         "follows the lead time above."))
    from assistant.actions.calendar.categories import all_categories
    cat_grid = QGridLayout()
    cat_grid.setVerticalSpacing(4)
    cat_grid.setHorizontalSpacing(10)
    cat_lead_combos: dict[str, QComboBox] = {}
    # ~/.assistant_tools/categories.json is hand-editable and merged over the
    # defaults, so an entry here can be anything: no name, a null colour, a
    # colour Qt cannot parse, a duplicate of a default's name. None of that is
    # worth aborting the whole app for (PyQt6 qFatal()s on an exception in this
    # slot), so a bad row degrades to the default dot / Default lead instead.
    try:
        _cat_leads_now = dict(getattr(notif_cfg, "category_leads", None) or {})
    except (TypeError, ValueError):
        _cat_leads_now = {}
    try:
        _all_cats = list(all_categories() or [])
    except Exception:
        _all_cats = []
    _row = 0
    for _cat in _all_cats:
        if not isinstance(_cat, dict):
            continue
        _cname = str(_cat.get("name") or "").strip()
        if not _cname or _cname in cat_lead_combos:
            continue                 # nameless, or a name already given a row
        _dot = QLabel()
        _pm = QPixmap(12, 12)
        _pm.fill(Qt.GlobalColor.transparent)
        _color = QColor(str(_cat.get("color") or "") or _CAT_DOT_FALLBACK)
        if not _color.isValid():     # "", "blue-ish", a truncated hex…
            _color = QColor(_CAT_DOT_FALLBACK)
        _painter = QPainter(_pm)
        try:
            _painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            _painter.setPen(Qt.PenStyle.NoPen)
            _painter.setBrush(_color)
            _painter.drawEllipse(0, 0, 12, 12)
        finally:
            _painter.end()           # never leave a painter active on the pixmap
        _dot.setPixmap(_pm)
        cat_grid.addWidget(_dot, _row, 0)
        cat_grid.addWidget(QLabel(_cname), _row, 1)
        _cc = QComboBox()
        _cc.setObjectName(f"notif_cat_lead_{_cname}")
        _cc.addItem("Default", None)     # absent from category_leads
        _cc.addItem("Muted", 0)          # 0 = category muted (Gil's rule)
        for _mins in (5, 10, 15, 30, 60):
            _cc.addItem(f"{_mins} minutes", _mins)
        if _cname in _cat_leads_now:
            try:
                _v = int(_cat_leads_now[_cname])
            except (TypeError, ValueError):
                _v = None            # unreadable lead → show Default
            if _v is not None:
                _j = _cc.findData(_v)
                if _j < 0:
                    _cc.addItem(f"{_v} minutes", _v)
                    _j = _cc.count() - 1
                _cc.setCurrentIndex(_j)
        _cc.setMaximumWidth(130)
        cat_grid.addWidget(_cc, _row, 2)
        cat_lead_combos[_cname] = _cc
        _row += 1
    cat_grid.setColumnStretch(3, 1)
    notif.addLayout(cat_grid)

    # ── Voice ─────────────────────────────────────────────────────
    voice = section("Voice")
    mute_cb = QCheckBox("Mute voice output")
    mute_cb.setChecked(self._pipeline._tts.mute)
    voice.addWidget(mute_cb)

    voice_form = QFormLayout()
    voice_form.setSpacing(8)
    voice_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    speed_spin = QSpinBox()
    speed_spin.setRange(50, 400)
    speed_spin.setValue(self._pipeline._tts.rate)
    speed_spin.setSuffix(" wpm")
    speed_spin.setMaximumWidth(120)
    voice_form.addRow("Talking speed:", speed_spin)

    voice_combo = QComboBox()
    import subprocess
    try:
        voices = subprocess.check_output(["say", "-v", "?"], text=True).splitlines()
        voice_names = []
        for v in voices:
            if v.strip():
                name = v.split()[0]
                if name not in voice_names:
                    voice_names.append(name)
        voice_combo.addItems(voice_names)
    except Exception:
        voice_combo.addItems(["Samantha", "Daniel", "Alex", "Ava", "Zari"])
    current_voice = self._pipeline._tts.voice
    if current_voice in [voice_combo.itemText(i) for i in range(voice_combo.count())]:
        voice_combo.setCurrentText(current_voice)
    else:
        voice_combo.addItem(current_voice)
        voice_combo.setCurrentText(current_voice)
    voice_combo.setMaximumWidth(200)
    voice_form.addRow("Voice:", voice_combo)
    voice.addLayout(voice_form)

    review_cb = QCheckBox("Ask before sending (Redo / Add more / Send)")
    review_cb.setChecked(getattr(self._config.audio, "review_before_send", True))
    voice.addWidget(review_cb)

    review_row = QHBoxLayout()
    review_row.addSpacing(20)
    review_row.addWidget(QLabel("Sends by itself after"))
    review_spin = QSpinBox()
    review_spin.setRange(1, 15)
    review_spin.setSuffix(" s")
    review_spin.setValue(getattr(self._config.audio, "review_seconds", 3))
    review_spin.setMaximumWidth(80)
    review_row.addWidget(review_spin)
    review_row.addStretch(1)
    voice.addLayout(review_row)
    review_cb.toggled.connect(review_spin.setEnabled)
    review_spin.setEnabled(review_cb.isChecked())
    voice.addWidget(hint("A spoken stop word — “execute”, “done” — always sends straight "
                         "away, with no wait."))

    phrase_form = QFormLayout()
    phrase_form.setSpacing(8)
    phrase_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    stop_phrases_edit = QLineEdit()
    stop_phrases_edit.setPlaceholderText("e.g. finish, that's all, stop recording")
    stop_phrases_edit.setText(", ".join(self._config.audio.stop_phrases or []))
    stop_phrases_edit.setToolTip("Extra words that stop the mic, on top of the built-in ones")
    phrase_form.addRow("Stop phrases:", stop_phrases_edit)

    sep_edit = QLineEdit()
    sep_edit.setPlaceholderText('e.g. "next event" — blank to disable')
    sep_edit.setText(self._config.audio.event_separator or "")
    sep_edit.setToolTip('Say: "meeting at 10am next event lunch at noon"')
    phrase_form.addRow("Event separator:", sep_edit)

    keywords_edit = QLineEdit()
    keywords_edit.setPlaceholderText("e.g. meeting, appointment, activity")
    keywords_edit.setText(", ".join(self._config.nlu.event_keywords or []))
    keywords_edit.setToolTip("Create instantly with this as a placeholder title, then let the LLM improve it")
    phrase_form.addRow("Event keywords:", keywords_edit)
    voice.addLayout(phrase_form)

    # ── Assistant ─────────────────────────────────────────────────
    assistant = section("Assistant")
    # The switch (Gil, 2026-09-29): off, no command reaches the engine — from
    # this Mac or the phone — and the mics stay shut. The calendar still works.
    assistant_on_cb = QCheckBox("Assistant on — voice and typed commands")
    assistant_on_cb.setObjectName("assistant_on")
    assistant_on_cb.setChecked(bool(getattr(getattr(self._config, "engine", None), "enabled", True)))
    assistant.addWidget(assistant_on_cb)
    assistant.addWidget(hint("Off: nothing you say or type is acted on, here or on your phone, "
                             "until you switch it back on. Your calendar and to-dos work as usual."))
    auto_cb = QCheckBox("Auto-approve actions (no confirmations)")
    # config.confirmation_level is the source of truth, not the pipeline.
    # Pipeline._confirmer was deleted in e3ea4f6 ("Delete the Mac's dead half")
    # when parse+execute moved into the API process — reading it here raised
    # AttributeError inside the toolbar button's slot, and PyQt6 turns an
    # unhandled exception in a slot into qFatal(), so the whole calendar app
    # aborted (SIGABRT) the moment Settings was opened. It stayed green because
    # both settings test doubles had invented a `_confirmer` the real object
    # has not had for months.
    auto_cb.setChecked(int(getattr(self._config, "confirmation_level", 0) or 0) == 0)
    assistant.addWidget(auto_cb)

    thinking_cb = QCheckBox("Show assistant thinking (floating step-by-step HUD)")
    thinking_cb.setToolTip(
        "A timeline of what the assistant heard, parsed and did.\n"
        "It is its own always-on-top window, so it shows commands you gave\n"
        "from your phone while you were in another app.")
    thinking_cb.setChecked(getattr(self._config.ui, "show_thinking", True))
    assistant.addWidget(thinking_cb)

    thinking_row = QHBoxLayout()
    thinking_row.addSpacing(20)
    thinking_row.addWidget(QLabel("Park it in the"))
    thinking_corner_combo = QComboBox()
    for _label, _value in (("bottom right", "bottom-right"), ("bottom left", "bottom-left"),
                           ("top right", "top-right"), ("top left", "top-left")):
        thinking_corner_combo.addItem(_label, _value)
    _idx = thinking_corner_combo.findData(
        getattr(self._config.ui, "thinking_corner", "bottom-right"))
    thinking_corner_combo.setCurrentIndex(_idx if _idx >= 0 else 0)
    thinking_row.addWidget(thinking_corner_combo)
    thinking_row.addWidget(QLabel("of the screen"))
    thinking_row.addStretch(1)
    assistant.addLayout(thinking_row)

    def _thinking_toggled(on: bool) -> None:
        thinking_corner_combo.setEnabled(on)
    thinking_cb.toggled.connect(_thinking_toggled)
    _thinking_toggled(thinking_cb.isChecked())

    confirm_cb = QCheckBox("Check doubted words with me before acting")
    confirm_cb.setToolTip(
        "When the vocabulary isn't sure it heard a word right, show the\n"
        "transcription for a quick fix before anything is executed.\n"
        "Off: act on the best guess (you can still tap a word to fix it).")
    confirm_cb.setChecked(bool(getattr(getattr(self._config, "engine", None),
                                       "confirm_transcript", False)))
    assistant.addWidget(confirm_cb)

    vocab_btn = QPushButton(icons.icon("vocab"), "Vocabulary && Assistant Log…")
    vocab_btn.setToolTip("Teach the assistant names and words it mishears; review recent commands")
    vocab_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _open_vocab():
        from assistant.calendar_ui.vocab_dialog import VocabDialog
        VocabDialog(self, pipeline=self._pipeline).exec()
    vocab_btn.clicked.connect(_open_vocab)

    lexicon_btn = QPushButton(icons.icon("vocab"), "How I Say Things…")
    lexicon_btn.setObjectName("lexicon_btn")
    lexicon_btn.setToolTip(
        "The words the assistant recognises for shortening, naming and the\n"
        "rest — add the ones you use. Yours are added to what it already\n"
        "knows, never instead of them.")
    lexicon_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _open_lexicon():
        from assistant.calendar_ui.lexicon_dialog import LexiconDialog
        LexiconDialog(self, dark=self._dark).exec()
    lexicon_btn.clicked.connect(_open_lexicon)

    review_btn = QPushButton(icons.icon("thumbs_up"), "Review Commands…")
    review_btn.setToolTip("Say whether recent voice commands did the right thing — the assistant learns from it")
    review_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _open_review():
        from assistant.calendar_ui.review_dialog import ReviewDialog
        ReviewDialog(self, dark=self._dark).exec()
        _refresh_review_label()

    def _refresh_review_label():
        try:
            from assistant.calendar_ui.review_dialog import unreviewed
            n = len(unreviewed(limit=50))
        except Exception:
            n = 0
        review_btn.setText(f"Review Commands… ({n})" if n else "Review Commands…")

    review_btn.clicked.connect(_open_review)
    _refresh_review_label()

    colors_btn = QPushButton(icons.icon("corrected"), "Event Colours && Categories…")
    colors_btn.setToolTip("Categories, their colours and the keywords that pick them")
    colors_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _open_categories():
        from assistant.calendar_ui.categories_dialog import CategoriesDialog
        if CategoriesDialog(self, dark=self._dark).exec():
            self.refresh_calendar()
    colors_btn.clicked.connect(_open_categories)

    tips_btn = QPushButton(icons.icon("question"), "How to Talk to Me…")
    tips_btn.setToolTip("A few short tips on phrasing voice commands so they land right the first time")
    tips_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _open_tips():
        from assistant.calendar_ui.tips_dialog import TipsDialog
        TipsDialog(self).exec()
    tips_btn.clicked.connect(_open_tips)

    for btn in (vocab_btn, lexicon_btn, review_btn, colors_btn, tips_btn):
        assistant.addWidget(btn)

    # ── Connected Calendars ───────────────────────────────────────
    # Google / Outlook two-way and the read-only ICS links. The phone has the
    # same section; both only start a sign-in and show status — the brain
    # holds the tokens and runs the sync (assistant/calendar_sync/).
    calendars = section("Connected Calendars")
    calendars.addWidget(hint(
        "Keep Google or Outlook in step with this calendar automatically. "
        "Each needs a one-time free client registration — “Set-up steps…” "
        "walks through it."))
    from assistant.calendar_ui.connected_calendars import ConnectedCalendarsSection
    calendars.addWidget(ConnectedCalendarsSection(
        dialog, self._config, toast=self.show_toast,
        on_links=getattr(self, "_on_connected_calendars", None),
        on_synced=self.refresh_calendar))

    # Which computers run the model, and the server's log (DEVQA Q70) — the
    # same panel as the menu-bar app's "Servers & logs".
    server = section("Server")
    server.addWidget(hint(
        "This Mac is the primary — the brain. Other computers can lend it their "
        "model: open MACalendar Server on them and choose “A model helper”."))
    from assistant.host.servers_panel import ServersPanel
    server.addWidget(ServersPanel(
        dialog, port=getattr(getattr(self._config, "api", None), "port", 8080)))

    layout.addStretch(1)
    # Test & Save
    btn_layout = QHBoxLayout()
    test_btn = QPushButton("Test Audio")
    def run_test():
        if mute_cb.isChecked():
            self.show_toast("Muted. Uncheck to test.")
            return
        import threading
        threading.Thread(target=lambda: subprocess.Popen(
            ["say", "-v", voice_combo.currentText(), "-r", str(speed_spin.value()), "Hello, I am ready."],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ), daemon=True).start()
    test_btn.clicked.connect(run_test)
    btn_layout.addWidget(test_btn)

    save_btn = QPushButton("Save Config")
    save_btn.setDefault(True)
    def _checked_hours() -> tuple:
        """The two boxes as (first, last); "to" at or before "from" means the
        whole day rather than an empty view."""
        a, b = hours_from_combo.currentData(), hours_to_combo.currentData()
        return (a, b) if b > a else (0, 24)

    def save_config():
        # Only if this pipeline still has one — see the note by auto_cb above.
        _confirmer = getattr(self._pipeline, "_confirmer", None)
        if _confirmer is not None:
            _confirmer.level = 0 if auto_cb.isChecked() else 1
        self._pipeline._tts.mute = mute_cb.isChecked()
        self._pipeline._tts.rate = speed_spin.value()
        self._pipeline._tts.voice = voice_combo.currentText()
        # Parse event keywords and stop phrases from text fields
        raw_keywords = [k.strip() for k in keywords_edit.text().split(",") if k.strip()]
        self._config.nlu.event_keywords = raw_keywords
        raw_phrases = [p.strip() for p in stop_phrases_edit.text().split(",") if p.strip()]
        self._config.audio.stop_phrases = raw_phrases
        self._config.audio.event_separator = sep_edit.text().strip()
        self._config.hebrew_calendar.display_mode = hebrew_mode_combo.currentData()
        self._config.hebrew_calendar.show_holidays = hebrew_holidays_cb.isChecked()
        self._config.hebrew_calendar.israel_holidays = hebrew_israel_cb.isChecked()
        self._config.hebrew_calendar.show_shabbat_times = shabbat_lines_cb.isChecked()
        # Persist — one section-scoped, comment-preserving write
        # (assistant/config_store). Each setting names its section, so a
        # `rate:` under tts can never clobber a rate elsewhere, and keys
        # missing from an older config are inserted instead of dropped.
        # Default = absent from the map; Muted / a lead land in it as 0 / n.
        cat_leads = {name: int(combo.currentData())
                     for name, combo in cat_lead_combos.items()
                     if combo.currentData() is not None}
        try:
            from assistant.config_store import set_values
            ok = set_values({
                "": {"confirmation_level": 0 if auto_cb.isChecked() else 1,
                     "theme": theme_combo.currentText().lower()},
                "tts": {"mute": mute_cb.isChecked(),
                        "voice": voice_combo.currentText(),
                        "rate": speed_spin.value()},
                "ui": {"start_view": start_view_combo.currentData(),
                       "hours_from": _checked_hours()[0],
                       "hours_to": _checked_hours()[1],
                       "font_month": month_spin.value(),
                       "font_week": week_spin.value(),
                       "font_day": day_spin.value(),
                       "font_tasks": tasks_spin.value(),
                       "font_coursework": coursework_spin.value(),
                       "compact_ui": compact_cb.isChecked(),
                       "accent_color": accent_state["hex"],
                       "show_coursework": _tab_shown("coursework"),
                       "show_workout": _tab_shown("workout"),
                       "show_timer": _tab_shown("timer"),
                       "show_thinking": thinking_cb.isChecked(),
                       "thinking_corner": thinking_corner_combo.currentData()},
                "audio": {"review_before_send": review_cb.isChecked(),
                          "review_seconds": review_spin.value(),
                          "stop_phrases": raw_phrases,
                          "event_separator": sep_edit.text().strip()},
                "nlu": {"event_keywords": raw_keywords},
                "engine": {"confirm_transcript": confirm_cb.isChecked(),
                           "enabled": assistant_on_cb.isChecked()},
                # Read by event_defaults in whichever process asks (the API
                # re-reads on the file's mtime), and by the New Event dialog.
                "events": {"event_length_minutes": event_length_spin.value(),
                           "chain_gap_minutes": chain_gap_spin.value(),
                           **{k: sp.value() for k, sp in series_spins.items()}},
                "hebrew_calendar": {"display_mode": hebrew_mode_combo.currentData(),
                                    "show_holidays": hebrew_holidays_cb.isChecked(),
                                    "israel_holidays": hebrew_israel_cb.isChecked(),
                                    "show_shabbat_times": shabbat_lines_cb.isChecked()},
                # Read by observance.is_enabled() in the API process, which
                # loads config.yaml itself — nothing to apply in-memory here.
                "observance": {"enabled": observance_cb.isChecked()},
                # Scalars here; `category_leads`, a mapping, goes through the
                # same writer in `_persist_category_leads` below (one call
                # since 2026-09-22, when config_store learned the dict case).
                "notifications": {
                    "enabled": notif_enabled_cb.isChecked(),
                    "default_lead_minutes": int(notif_lead_combo.currentData() or 0),
                    "respect_observance": notif_observance_cb.isChecked(),
                    "agenda_card": notif_agenda_cb.isChecked(),
                    "speak": notif_speak_cb.isChecked(),
                    # No widget for sound yet — round-trip the config value.
                    "sound": bool(getattr(notif_cfg, "sound", True)),
                },
            })
            if ok:
                # Only when the days were edited here, so opening and saving
                # never writes back over days the phone changed meanwhile.
                if ov_state != ov_loaded:
                    try:
                        _ob.set_day_overrides(ov_state)
                    except (OSError, ValueError) as e:
                        QMessageBox.warning(self, "Days not saved",
                                            f"Could not save the days you changed: {e}")
                _persist_category_leads(cat_leads)
                if notif_cfg is not None:
                    _apply(notif_cfg, "enabled", notif_enabled_cb.isChecked())
                    _apply(notif_cfg, "default_lead_minutes",
                           int(notif_lead_combo.currentData() or 0))
                    _apply(notif_cfg, "respect_observance",
                           notif_observance_cb.isChecked())
                    _apply(notif_cfg, "agenda_card", notif_agenda_cb.isChecked())
                    _apply(notif_cfg, "speak", notif_speak_cb.isChecked())
                    _apply(notif_cfg, "category_leads", cat_leads)
                if events_cfg is not None:
                    _apply(events_cfg, "event_length_minutes", event_length_spin.value())
                    _apply(events_cfg, "chain_gap_minutes", chain_gap_spin.value())
                    for _key, _spin in series_spins.items():
                        _apply(events_cfg, _key, _spin.value())

                # Apply changes immediately
                self._config.confirmation_level = 0 if auto_cb.isChecked() else 1
                self._config.ui.start_view = start_view_combo.currentData()
                self._config.ui.hours_from, self._config.ui.hours_to = _checked_hours()
                _apply(getattr(self._config, "engine", None), "enabled", assistant_on_cb.isChecked())
                if hasattr(self, "_apply_assistant_switch"):
                    self._apply_assistant_switch(assistant_on_cb.isChecked())
                if hasattr(self, "_apply_visible_hours"):
                    self._apply_visible_hours()
                self._config.ui.font_month = month_spin.value()
                self._config.ui.font_week = week_spin.value()
                self._config.ui.font_day = day_spin.value()
                self._config.ui.font_tasks = tasks_spin.value()
                self._config.ui.font_coursework = coursework_spin.value()
                self._config.ui.compact_ui = compact_cb.isChecked()
                self._config.ui.accent_color = accent_state["hex"]
                self._config.ui.show_coursework = _tab_shown("coursework")
                self._config.ui.show_workout = _tab_shown("workout")
                self._config.ui.show_timer = _tab_shown("timer")
                # The HUD is a separate process; it notices config.yaml
                # changing and re-reads these itself.
                self._config.ui.show_thinking = thinking_cb.isChecked()
                self._config.ui.thinking_corner = thinking_corner_combo.currentData()
                self._config.audio.review_before_send = review_cb.isChecked()
                self._config.audio.review_seconds = review_spin.value()
                for _mode, _cb in tab_boxes.items():
                    _visible = _cb.isChecked()
                    _feature_registry.get(_mode).set_visible(_visible)
                    _btn = getattr(self, f"_view_btn_{_mode}", None)
                    if _btn is not None:
                        _btn.setVisible(_visible)
                    if not _visible and self._view_mode == _mode:
                        self._set_view("month")
                _styles.set_accent(accent_state["hex"])
                self._apply_ui_config()
                self._apply_theme(self._dark)

        except Exception as e:
            # The YAML write happens FIRST and has its own `ok`; everything after
            # it only updates the objects already in memory. So this message has
            # to say which half failed, or a successful save reads as a lost one
            # — which is exactly what Gil saw (2026-09-18): config.yaml had been
            # written correctly and the dialog said "Could not save config.yaml".
            QMessageBox.critical(
                self, "Error Saving",
                f"config.yaml was written, but applying the settings to the "
                f"running app failed: {e}\n\nRestart the calendar to pick them "
                f"up." if ok else f"Could not save config.yaml: {e}")

        self.show_toast("Settings applied!")
        self.refresh_calendar()
        dialog.accept()

    save_btn.clicked.connect(save_config)
    btn_layout.addWidget(save_btn)
    btn_layout.setContentsMargins(18, 10, 18, 14)
    outer.addLayout(btn_layout)

    dialog.exec()


# ------------------------------------------------------------------
# category_leads persistence
# ------------------------------------------------------------------

def _persist_category_leads(leads: "dict[str, int]", path: "str | None" = None) -> bool:
    """`notifications.category_leads`, written by the ordinary config writer.

    Until 2026-09-22 this file carried its own YAML writer for the mapping
    because `config_store._literal` had no dict case (a dict came out as a
    quoted Python repr, which YAML read back as a string). The writer learned
    the flow mapping and how to consume a block mapping's child lines, so this
    is one call now. 0 mutes the category outright; an absent name follows the
    default lead."""
    from assistant import config_store
    kwargs = {"path": path} if path else {}
    return config_store.set_values(
        {"notifications": {"category_leads": {str(k): int(v) for k, v in leads.items()}}}, **kwargs)


# ------------------------------------------------------------------
# ICS / macOS Calendar import
# ------------------------------------------------------------------

