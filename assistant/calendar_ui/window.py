"""Main calendar application window."""

from __future__ import annotations

from assistant import users
from assistant.users import local_session as _local_session
import datetime
import logging
import os
import queue
import threading
import time
from typing import Optional


logger = logging.getLogger(__name__)
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QCloseEvent, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QDialog,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QSpinBox,
    QGridLayout,
    QLineEdit,
)

from assistant.calendar_ui import icons
from assistant.calendar_ui import view_prefs as _vp
from assistant.calendar_ui.agenda_view import AgendaView, DAYS_AHEAD as _AGENDA_DAYS
from assistant.calendar_ui.day_view import DayView
from assistant.calendar_ui.event_dialog import EventDialog, repeat_rule_changed
from assistant.calendar_ui.month_view import MonthView
from assistant.calendar_ui.sidebar import Sidebar
from assistant.calendar_ui.undo import UndoManager
import assistant.calendar_ui.styles as _styles
from assistant.calendar_ui.styles import get_app_style, BLUE, GRAY_BORDER, GRAY_DARK, GRAY_TEXT, GRAY_BG
from assistant.calendar_ui.week_view import WeekView
from assistant.features import registry as _features
from assistant.calendar_ui.importer import parse_ics, scan_macos_calendar, import_events
from assistant.db import CalendarDB
from assistant.pipeline import (
    STATUS_CONFIRM,
    STATUS_DONE,
    STATUS_EDIT,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_LISTENING,
    STATUS_PROCESSING,
    STATUS_REVIEW,
)

STATUS_REFRESH = "refresh"
STATUS_SWITCH_TODAY = "switch_today"
STATUS_SWITCH_TODO = "switch_todo"


def _fmt_time(time_str: str) -> str:
    """'14:30' as the person reads times (Settings ▸ Appearance ▸ Clock)."""
    from assistant.calendar_ui import view_prefs as _vp
    return _vp.fmt_hhmm(time_str)

#: The mic button's picture per status — GraphicsLibrary icons
#: (`calendar_ui/icons`), drawn in the button's ink; idle is the drawn mic.
_MIC_ICONS = {
    STATUS_IDLE: "mic",
    STATUS_LISTENING: "record",
    STATUS_REVIEW: "envelope",
    STATUS_EDIT: "pencil",
    STATUS_CONFIRM: "help_circle",
    STATUS_PROCESSING: "gear",
    STATUS_DONE: "check_circle",
    STATUS_ERROR: "warning",
    STATUS_REFRESH: "check_circle",
    STATUS_SWITCH_TODAY: "check_circle",
    STATUS_SWITCH_TODO: "check_circle",
}

_MIC_OBJ_NAMES = {
    STATUS_IDLE: "mic_idle",
    STATUS_LISTENING: "mic_listening",
    STATUS_REVIEW: "mic_processing",
    STATUS_EDIT: "mic_processing",
    STATUS_CONFIRM: "mic_processing",
    STATUS_PROCESSING: "mic_processing",
    STATUS_DONE: "mic_idle",
    STATUS_ERROR: "mic_idle",
    STATUS_REFRESH: "mic_idle",
    STATUS_SWITCH_TODAY: "mic_idle",
    STATUS_SWITCH_TODO: "mic_idle",
}


class ElidingLabel(QLabel):
    """QLabel that elides its text with '…' when the toolbar doesn't have
    room for it, instead of silently clipping mid-character — the plain
    QLabel used for the title bar hard-cut the Hebrew month/year suffix
    with no visual indication text was missing. The full text is always
    available via tooltip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802 — overriding QLabel's API
        self._full_text = text
        self.setToolTip(text)
        self._update_elided()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided()

    def _update_elided(self) -> None:
        if not self._full_text:
            return
        fm = self.fontMetrics()
        elided = fm.elidedText(self._full_text, Qt.TextElideMode.ElideRight, self.width())
        super().setText(elided)


class _ElasticSearchBox(QLineEdit):
    """The toolbar search box: ~180px wide when there is room, shrinking down
    to 90px rather than forcing an overlap when there is not.

    `setFixedSize(180, 30)` was the actual bug behind Gil's report — it made
    the search box the one item in the toolbar row that could NEVER give up
    space, while every one of the ~20 other buttons/icons around it is also
    fixed-size or close to it. Summed, the row's own minimum content width
    sits above `CalendarWindow`'s own `setMinimumSize(900, 640)` floor, so at
    a narrow-but-explicitly-allowed window width something had to give and
    nothing could — widgets ended up drawn on top of each other instead of
    the layout simply refusing to shrink further.

    A plain `setMinimumWidth`/`setMaximumWidth` pair with a Preferred size
    policy is not enough on its own: `QLineEdit.sizeHint()` is not 180px, so
    without overriding it the box would sit at its SMALLEST allowed width
    even in the ordinary, roomy case — it only grows toward a stretch factor
    pulling on it, and giving it one would eat into the space the toolbar
    intentionally leaves as pure margin before the view tabs. Overriding
    `sizeHint()` (what the layout hands out when there IS room) while leaving
    `minimumSizeHint()` at the real floor (what the layout shrinks toward
    under pressure) gets both without touching the rest of the row's balance
    — the same fix `ElidingLabel` above makes for the title, one class down.
    """

    def sizeHint(self):  # noqa: N802 — overriding QLineEdit's API
        return QSize(180, 30)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(90, 30)


class ToastLabel(QLabel):
    """Brief notification that fades out after a few seconds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: {BLUE};
                color: white;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }}
            """
        )
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, duration_ms: int = 3000) -> None:
        self.setText(text)
        self.adjustSize()
        self.show()
        self._timer.start(duration_ms)


class ReviewBar(QFrame):
    """Redo / Add more / Send, shown for a few seconds after a recording stops.

    The Mac twin of the bar the iPhone floats above its mic. It never appears
    when a spoken stop word ended the recording — saying "execute" already
    settled it, so the pipeline sends without asking (see Pipeline._await_review).
    """

    chose = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        # QFrame, not QWidget: a plain QWidget subclass ignores a stylesheet
        # background, which left the bar transparent over the calendar.
        super().__init__(parent)
        self._remaining = 0
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(shadow)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(6)

        self._heard = QLabel("")
        self._heard.setMaximumWidth(320)
        lay.addWidget(self._heard)

        self._redo = QPushButton("Redo")
        self._redo.setToolTip("Throw that away and record again")
        self._more = QPushButton("Add more")
        self._more.setToolTip("Keep what you said and carry on")
        self._send = QPushButton("Send")
        self._cancel = QPushButton()
        self._cancel.setIcon(icons.icon("trash", None, 15))
        self._cancel.setToolTip("Discard — throw this recording away without running it")
        self._cancel.setFixedWidth(30)
        for btn, choice in ((self._redo, "redo"), (self._more, "add"),
                            (self._send, "send"), (self._cancel, "cancel")):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda _=False, c=choice: self._answer(c))
            lay.addWidget(btn)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self, seconds: int, heard: str) -> None:
        self._remaining = seconds
        self._heard.setText(f"“{heard}”" if heard else "")
        self._heard.setVisible(bool(heard))
        self._send.setText(f"Send {seconds}")
        self.show()
        self.adjustSize()          # after show(), so the label has its real width
        self.raise_()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._remaining -= 1
        # The pipeline owns the real deadline; this just counts it down on screen.
        self._send.setText(f"Send {self._remaining}" if self._remaining > 0 else "Send")

    def _answer(self, choice: str) -> None:
        self.stop()
        self.chose.emit(choice)

    def apply_theme(self, dark: bool) -> None:
        bg = _styles.D_GRAY_BG if dark else _styles.GRAY_BG
        border = _styles.D_GRAY_BORDER if dark else GRAY_BORDER
        text2 = _styles.D_GRAY_TEXT if dark else GRAY_TEXT
        accent = _styles.get_accent()
        self.setStyleSheet(
            f"ReviewBar {{ background-color: {bg}; border: 1px solid {border};"
            f" border-radius: {_styles.RADIUS_LG}px; }}"
            f"QLabel {{ color: {text2}; border: none; background: transparent; }}"
        )
        # Explicit inline styling — the app stylesheet's #primary rule has been
        # seen to apply `color` without `background-color` on nested widgets.
        self._send.setStyleSheet(
            f"QPushButton {{ background-color: {accent}; color: {_styles.on_color(accent)};"
            f" border: 1px solid {accent}; border-radius: {_styles.RADIUS_SM}px;"
            f" padding: 3px 10px; font-weight: 700; }}"
        )


def ask_transcript_edit(parent, payload_json: str) -> "str | None":
    """The gate's dialog, on its own so a test can drive it with real clicks.

    Shows the doubted transcript in an editable field. Returns the text to run
    (possibly untouched — that is a confirmation), or None for cancel.
    """
    import json as _json

    from PyQt6.QtWidgets import (
        QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout,
    )

    try:
        payload = _json.loads(payload_json or "{}")
    except ValueError:
        payload = {}
    transcript = payload.get("transcript") or ""
    words = [w for w in (payload.get("words") or []) if w]

    dlg = QDialog(parent)
    dlg.setWindowTitle("Check the transcription")
    dlg.setObjectName("transcript_edit_dialog")
    lay = QVBoxLayout(dlg)
    doubt = ", ".join(f"“{w}”" for w in words) or "some words"
    label = QLabel(f"I'm not sure I heard {doubt} right. Fix anything that's "
                   "wrong, then Send — or Send as-is if it's fine.")
    label.setWordWrap(True)
    lay.addWidget(label)
    edit = QLineEdit(transcript)
    edit.setObjectName("transcript_edit_field")
    lay.addWidget(edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
    buttons.setObjectName("transcript_edit_buttons")
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Send")
    buttons.accepted.connect(lambda: dlg.accept())
    buttons.rejected.connect(lambda: dlg.reject())
    lay.addWidget(buttons)
    edit.setFocus()

    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    text = edit.text().strip()
    dlg.deleteLater()
    return text if (accepted and text) else None


def ask_create_confirm(parent, payload_json: str) -> bool:
    """The confirm-create box, on its own so a test can drive it with real
    clicks (DEVQA Q9, Gil 2026-09-07).

    "should i add yoga to my calendar tomorrow?" is a question, so nothing has
    been created — this shows what the brain understood and asks. Returns True
    for Add, False for No or a closed box: declining is the safe default, which
    is why there is no third answer.
    """
    import json as _json

    from PyQt6.QtWidgets import (
        QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
    )

    from assistant.calendar_ui.dialog_utils import install_enter_confirms

    try:
        payload = _json.loads(payload_json or "{}")
    except ValueError:
        payload = {}
    prompt = payload.get("prompt") or "Add this to your calendar?"
    items = [str(s) for s in (payload.get("items") or []) if str(s).strip()]

    dlg = QDialog(parent)
    dlg.setWindowTitle("Add this?")
    dlg.setObjectName("create_confirm_dialog")
    lay = QVBoxLayout(dlg)
    label = QLabel(prompt)
    label.setObjectName("create_confirm_prompt")
    label.setWordWrap(True)
    lay.addWidget(label)
    if items:
        detail = QLabel("\n".join(f"• {s}" for s in items))
        detail.setObjectName("create_confirm_items")
        detail.setWordWrap(True)
        lay.addWidget(detail)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
    buttons.setObjectName("create_confirm_buttons")
    add_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
    add_btn.setText("Add")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("No")
    buttons.accepted.connect(lambda: dlg.accept())
    buttons.rejected.connect(lambda: dlg.reject())
    lay.addWidget(buttons)
    install_enter_confirms(dlg, add_btn)

    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    dlg.deleteLater()
    return accepted


class CalendarWindow(QMainWindow):
    """
    Main Outlook-style calendar window.

    Voice pipeline updates come in via pipeline.status_queue (thread-safe).
    A QTimer drains the queue on the main thread every 100ms.
    """

    # A mined new-tag proposal arrived from the API (fetched on a worker
    # thread; dialogs must run on the GUI thread, and a cross-thread signal
    # is the safe hand-off).
    _tag_suggestion_ready = pyqtSignal(dict)

    def __init__(self, pipeline=None, config=None, parent=None):
        super().__init__(parent)
        self._pipeline = pipeline
        self._config = config
        # How the calendar is drawn — before any view is built, since the
        # week view works out its first day as it is made.
        _vp.apply(getattr(config, "ui", None))
        _vp.apply_titles(config)
        # The signed-in user's calendar PLUS what others share with them — one
        # object every view keeps, reading and writing through users.sharing
        # (DEVQA Q65). Before the users migration it is just the CalendarDB.
        from assistant.calendar_ui.merged_db import MergedCalendar
        self._db = MergedCalendar(CalendarDB(), on_refused=lambda m: self.show_toast(m))
        self._current_date = datetime.date.today()
        # Calendar modes, then one per feature panel (registry-driven).
        self._view_mode = "month"
        self._undo_manager = UndoManager()

        self._dark = (config.theme == "dark") if config else False

        self.setWindowTitle("Calendar")
        self.setMinimumSize(900, 640)
        self.resize(1100, 720)

        self._build_ui()
        self._apply_theme(self._dark, show_toast=False)
        self._apply_ui_config()
        # Open on the view chosen in Settings → Appearance (Week by default).
        self._set_view(getattr(getattr(config, "ui", None), "start_view", "week") or "week")

        # Cmd+Z on macOS (Ctrl+Z elsewhere) — undoes the last direct UI edit
        # (create/update/delete/drag-reschedule/resize of an event). Separate
        # from the voice pipeline's own background-verification undo+redo.
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._on_undo)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_type_box)   # ⌘K on a Mac
        # Shift+Cmd+Z (Ctrl+Shift+Z elsewhere) — redoes an undone action.
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self._on_redo)

        # Auto-sync todos from calendar on open if configured
        if config and config.todo.sync.auto_sync_on_open and config.todo.sync.mode != "off":
            self._db.sync_calendar_to_todos(list_name=config.todo.sync.mode)

        # Poll pipeline status queue
        if pipeline is not None:
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(100)
            self._poll_timer.timeout.connect(self._poll_status)
            self._poll_timer.start()

        # Tag discovery (Gil, 2026-09-05): once per launch, a minute in — the
        # user is demonstrably at the app by then — ask the API whether the
        # history has earned a new tag class. All the politeness (evidence
        # bar, weekly cooldown, refusals-forever) is server-side; this client
        # only pulls and shows. See actions/todo/tag_discovery.py.
        self._tag_suggestion_ready.connect(self._on_tag_suggestion)
        QTimer.singleShot(60_000, self._fetch_tag_suggestion)

        # Changes made from the phone land in the same SQLite file via the API server;
        # pick them up without a manual refresh by watching the file's mtime.
        import os as _os
        self._db_mtime = 0.0
        try:
            self._db_mtime = _os.path.getmtime(self._db.path)
        except OSError:
            pass
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(5000)
        self._sync_timer.timeout.connect(self._auto_refresh_if_db_changed)
        self._sync_timer.start()

        # Connected calendars sync in the BRAIN (assistant.api), on its own
        # timer, whether or not this window is open — it used to be a 15-minute
        # QTimer here, so closing the calendar stopped every sync. What is left
        # is "Sync now": it asks the API and the answer is drained here. The
        # rows a sync writes arrive through the DB-change poll above.
        self._sync_results_queue: queue.Queue = queue.Queue()
        self._sync_running = False
        self._sync_result_timer = QTimer(self)
        self._sync_result_timer.setInterval(500)
        self._sync_result_timer.timeout.connect(self._drain_sync_results)
        self._sync_result_timer.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Standard window close event — keeps persistence."""
        event.accept()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        # Splitter: sidebar | main view
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        self._sidebar = Sidebar()
        self._sidebar.new_event_clicked.connect(self._on_new_event)
        self._sidebar.date_selected.connect(self._on_sidebar_date)
        self._build_sidebar_nav()
        splitter.addWidget(self._sidebar)

        # The calendar's own four views are MODES of one feature rather than
        # panels beside it: they share the date, the title and the navigation,
        # and switch between themselves. So the window builds them directly.
        self._stack = QStackedWidget()
        self._month_view = MonthView(self._db)
        self._week_view = WeekView(self._db)
        self._day_view = DayView(self._db)
        self._apply_visible_hours()
        self._apply_assistant_switch(bool(getattr(getattr(self._config, "engine", None),
                                                  "enabled", True)))
        self._agenda_view = AgendaView(self._db)
        for _view in (self._month_view, self._week_view,
                      self._day_view, self._agenda_view):
            self._stack.addWidget(_view)

        # Every other panel comes from the feature registry, so adding one is a
        # folder plus a line in `assistant/features/registry.py` rather than the
        # five edits in this file it used to take — import, construct,
        # addWidget, the toolbar loop and the _set_view dict. Those five had
        # already drifted apart; see assistant/features/CONVENTION.md.
        self._panels: dict = {}
        for _feature in _features.all_features():
            _panel_cls = _feature.panel()
            if _panel_cls is None:
                continue
            _panel = _panel_cls.create(self._db, config=self._config, dark=self._dark)
            self._panels[_feature.name] = _panel
            self._stack.addWidget(_panel)
        # Named attributes for the call sites that already use them.
        self._todo_view = self._panels.get("tasks")
        self._timer_view = self._panels.get("timer")
        self._coursework_view = self._panels.get("coursework")
        self._workout_view = self._panels.get("workout")
        self._month_view.date_selected.connect(self._on_day_selected)
        self._month_view.date_double_clicked.connect(self._on_day_double_clicked)
        self._month_view.event_clicked.connect(self._on_event_clicked)
        self._week_view.datetime_double_clicked.connect(self._on_datetime_double_clicked)
        self._week_view.event_clicked.connect(self._on_event_clicked)
        self._day_view.datetime_double_clicked.connect(self._on_datetime_double_clicked)
        self._day_view.event_clicked.connect(self._on_event_clicked)
        self._agenda_view.event_clicked.connect(self._on_event_clicked)
        self._day_view.briefing_requested.connect(self._on_briefing_requested)
        self._month_view.event_rescheduled.connect(self._on_event_rescheduled)
        self._week_view.event_rescheduled.connect(self._on_event_rescheduled)
        self._day_view.event_rescheduled.connect(self._on_event_rescheduled)
        splitter.addWidget(self._stack)

        splitter.setSizes([200, 900])
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

        # Toast notification (overlaid)
        self._toast = ToastLabel(central)
        self._toast.raise_()

        # Redo / Add more / Send bar (overlaid) — the desktop twin of the chip
        # the iPhone floats over its mic after a recording stops.
        self._review_bar = ReviewBar(central)
        self._review_bar.chose.connect(self._on_review_choice)
        self._review_bar.hide()

        self._update_title()

    def _build_toolbar(self) -> QWidget:
        from PyQt6.QtWidgets import QFrame
        bar = QWidget()
        self._toolbar_bar = bar
        bar.setObjectName("toolbar_bar")
        bar.setFixedHeight(54)
        # Scoped to the bar itself: unscoped, the bottom border cascaded onto
        # every widget inside it and drew a stray underline under the title,
        # the More button and the user chip.
        bar.setStyleSheet(self._toolbar_qss(GRAY_BG, GRAY_BORDER))
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(2)
        # Every widget below is added with AlignVCenter explicitly — mixed
        # fixed-height buttons, an auto-height label, and spacer items in
        # one row previously let some drift toward the top of the bar
        # instead of sitting centered in the available 30px content height.
        v_center = Qt.AlignmentFlag.AlignVCenter

        # ── Group 1: nav arrows ──────────────────────────────────────
        prev_btn = QPushButton("‹")
        prev_btn.setObjectName("nav")
        prev_btn.setFixedSize(28, 28)
        prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        prev_btn.clicked.connect(self._on_prev)
        layout.addWidget(prev_btn, alignment=v_center)

        next_btn = QPushButton("›")
        next_btn.setObjectName("nav")
        next_btn.setFixedSize(28, 28)
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.clicked.connect(self._on_next)
        layout.addWidget(next_btn, alignment=v_center)

        layout.addSpacing(4)

        today_btn = QPushButton("Today")
        today_btn.setObjectName("flat")
        today_btn.setFixedHeight(30)
        today_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        today_btn.clicked.connect(self._on_today)
        layout.addWidget(today_btn, alignment=v_center)
        # hidden on a feature panel, where a date means nothing
        self._calendar_only = (prev_btn, next_btn, today_btn)

        layout.addSpacing(6)
        self._search_box = _ElasticSearchBox()
        self._search_box.setObjectName("toolbar_search")
        self._search_box.setPlaceholderText("Search, or a date…")
        self._search_box.setFixedHeight(30)
        self._search_box.setClearButtonEnabled(True)
        self._search_box.returnPressed.connect(lambda: self._on_search())
        layout.addWidget(self._search_box, alignment=v_center)

        # ── Title ────────────────────────────────────────────────────
        layout.addSpacing(6)
        self._title_label = ElidingLabel()
        self._title_label.setObjectName("month_title")
        font = QFont()
        font.setPointSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        self._title_label.setFont(font)
        layout.addWidget(self._title_label, alignment=v_center)

        layout.addStretch()

        # ── Group 2: the calendar's four views ─────────────────────────
        # Only the calendar's own modes live here (2026-09-28, Gil: the Mac app
        # "feels messy"). The feature panels — Tasks, Timer, Account… — used to
        # share this strip, twelve buttons in a row; they are the sidebar's
        # section list now (`_build_sidebar_nav`).
        # ONE segmented control, a rounded group, rather than four loose words
        # (Gil, 2026-09-29: the right side "could be more clean").
        self._seg_group = QFrame()
        self._seg_group.setObjectName("seg_group")
        seg_lay = QHBoxLayout(self._seg_group)
        seg_lay.setContentsMargins(2, 2, 2, 2)
        seg_lay.setSpacing(2)
        for label, mode in self._toolbar_modes()[:4]:
            btn = QPushButton(label)
            btn.setObjectName("seg_btn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, m=mode: self._set_view(m))
            feature = _features.get(mode)
            if feature is not None and not feature.pinned:
                btn.setVisible(feature.visible())
            seg_lay.addWidget(btn)
            setattr(self, f"_view_btn_{mode}", btn)
            # Styled by _apply_theme(), always called right after _build_ui()
            # in __init__ — no need to style twice here.
        layout.addWidget(self._seg_group, alignment=v_center)

        # ── Separator ────────────────────────────────────────────────
        layout.addSpacing(8)
        sep = QFrame()
        self._toolbar_sep = sep
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(22)
        sep.setStyleSheet(f"color: {GRAY_BORDER};")
        layout.addWidget(sep, alignment=v_center)
        layout.addSpacing(6)

        # ── Group 3: tools ───────────────────────────────────────────
        # One labelled menu for the occasional things, instead of "Import" and
        # three unlabelled emoji buttons whose meaning lived only in tooltips.
        from PyQt6.QtWidgets import QMenu, QToolButton
        self._more_btn = QToolButton()
        self._more_btn.setObjectName("more_btn")
        self._more_btn.setText("More ▾")
        self._more_btn.setFixedHeight(30)
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more = QMenu(self._more_btn)
        more.addAction("Import events…", self._on_import).setToolTip(
            "From an .ics file or macOS Calendar")
        more.addAction("Connected calendars…", self._on_connected_calendars)
        more.addAction("Tag suggestion history…", self._on_tag_history)
        more.addSeparator()
        # The QR code a phone scans to join this Mac (assistant/pairing/, Q69).
        more.addAction("Pair a phone or tablet…", self._on_pair_device)
        # Jude — the Judaic study assistant, its own app
        # (assistant/jude/ARCHITECTURE.md). Offered only when it is switched
        # on: an entry that always answers "not installed" is worse than none.
        if getattr(getattr(self._config, "jude", None), "enabled", False):
            more.addSeparator()
            more.addAction("Ask Jude…", self._on_jude)
        self._more_menu = more
        self._more_btn.setMenu(more)
        layout.addWidget(self._more_btn, alignment=v_center)
        layout.addSpacing(4)

        # Who is signed in (hidden before the users migration).
        from assistant.calendar_ui.users_dialogs import UserChip
        self._user_chip = UserChip()          # the layout parents it
        self._user_chip.switched.connect(lambda: self._on_user_switched())
        self._user_chip.changed.connect(lambda: self.refresh_calendar())
        self._user_chip.signed_out.connect(lambda: self.close())
        layout.addWidget(self._user_chip, alignment=v_center)

        self._settings_btn = QPushButton("")
        self._settings_btn.setObjectName("icon_btn")
        self._settings_btn.setFixedSize(30, 30)
        self._settings_btn.setToolTip("Assistant Settings")
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.clicked.connect(self._on_settings_popup)
        layout.addWidget(self._settings_btn, alignment=v_center)

        self._theme_btn = QPushButton("○")
        self._theme_btn.setObjectName("icon_btn")
        self._theme_btn.setFixedSize(30, 30)
        self._theme_btn.setToolTip("Toggle dark / light mode")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._on_toggle_theme)
        layout.addWidget(self._theme_btn, alignment=v_center)
        self._update_theme_btn()

        layout.addSpacing(2)

        # Type a command instead of saying it (Gil, 2026-10-01) — one small
        # button beside the mic and ⌘K; the box pops under it, Enter sends.
        self._type_btn = QPushButton("")
        self._type_btn.setObjectName("icon_btn")
        self._type_btn.setFixedSize(30, 30)
        self._type_btn.setToolTip("Type a command instead of saying it (⌘K)")
        self._type_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._type_btn.clicked.connect(self._open_type_box)
        layout.addWidget(self._type_btn, alignment=v_center)
        self._update_theme_btn()                 # draws the keyboard in the theme's ink

        # The live level beside the mic while it listens (mic_meter.py).
        from assistant.calendar_ui.mic_meter import MicLevelMeter
        self._mic_meter = MicLevelMeter()     # the layout parents it
        layout.addWidget(self._mic_meter, alignment=v_center)

        self._mic_btn = QPushButton("")
        self._mic_btn.setObjectName("mic_idle")
        from PyQt6.QtCore import QSize as _QSize
        from assistant.calendar_ui.toolbar_icons import mic_icon as _mic_icon
        self._mic_btn.setIcon(_mic_icon(_styles.ON_ACCENT))
        self._mic_btn.setIconSize(_QSize(18, 18))
        self._mic_btn.setFixedSize(30, 30)
        self._mic_btn.setToolTip("Click or press Ctrl+J to toggle the microphone")
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._pipeline is not None:
            self._mic_btn.clicked.connect(self._pipeline.trigger)
        layout.addWidget(self._mic_btn, alignment=v_center)
        self._apply_assistant_switch(bool(getattr(getattr(self._config, "engine", None),
                                                  "enabled", True)))

        # Discard, beside the mic and only while it is listening. Cancelling a
        # recording was a double-tap on the mic, which is to say undiscoverable
        # — and tapping the mic once sends, so changing your mind mid-sentence
        # meant letting the command run and undoing it afterwards.
        self._discard_btn = QPushButton()
        self._discard_btn.setIcon(icons.icon("trash", None, 15))
        self._discard_btn.setObjectName("icon_btn")
        self._discard_btn.setFixedSize(30, 30)
        self._discard_btn.setToolTip("Discard this recording — nothing is transcribed or run")
        self._discard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._discard_btn.hide()
        if self._pipeline is not None:
            self._discard_btn.clicked.connect(self._pipeline.cancel_recording)
        layout.addWidget(self._discard_btn, alignment=v_center)

        return bar

    def _style_seg_btn(self, btn: QPushButton, active: bool) -> None:
        # Always set a complete inline stylesheet for both states rather than
        # toggling the `[active="true"]` dynamic-property selector or ever
        # clearing back to "": PyQt6's QSS engine was observed to only apply
        # part of a rule (e.g. `color` but not `background-color`) after
        # unpolish()/polish(), AND separately to only partially revert a
        # previous inline override when cleared with setStyleSheet("":) —
        # in both cases leaving stale, mismatched paint state on whichever
        # button last changed. Explicitly stating every property for both
        # states every time avoids relying on any cache invalidation.
        dark = self._dark
        text2 = _styles.D_GRAY_TEXT if dark else GRAY_TEXT
        text = _styles.D_GRAY_DARK if dark else GRAY_DARK
        hover = _styles.D_GRAY_LIGHT if dark else _styles.GRAY_LIGHT
        if active:
            btn.setStyleSheet(
                f"QPushButton#seg_btn {{ background-color: {_styles.BLUE}; "
                f"color: {_styles.ON_ACCENT}; font-weight: 700; border: none; "
                f"border-radius: 6px; padding: 0 12px; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton#seg_btn {{ background-color: transparent; color: {text2}; "
                f"font-weight: 500; border: none; border-radius: 6px; padding: 0 12px; }}"
                f"QPushButton#seg_btn:hover {{ background-color: {hover}; color: {text}; }}"
            )
        btn.setProperty("active", active)

    @staticmethod
    def _toolbar_qss(bg: str, border: str) -> str:
        """The bar's own look, and its labels and chip see-through so they sit
        on the bar instead of in boxes of the page colour."""
        return (f"QWidget#toolbar_bar {{ background-color: {bg}; border-bottom: 1px solid {border}; }}"
                " QWidget#toolbar_bar QLabel { background: transparent; }"
                " QWidget#toolbar_bar QToolButton#user_chip { background: transparent; }")

    _CALENDAR_MODES = ("month", "week", "day", "agenda")

    def _restyle_view_buttons(self) -> None:
        """The toolbar's calendar views and the sidebar's sections, marked for
        the current view. The sidebar's "Calendar" row is lit on any of the
        four calendar views."""
        mode = getattr(self, "_view_mode", "month")
        on_calendar = mode in self._CALENDAR_MODES
        grp = getattr(self, "_seg_group", None)
        if grp is not None:
            dark = getattr(self, "_dark", True)
            bg = _styles.D_GRAY_LIGHT if dark else _styles.WHITE
            border = _styles.D_GRAY_BORDER if dark else GRAY_BORDER
            grp.setStyleSheet(f"QFrame#seg_group {{ background: {bg}; border: 1px solid {border}; "
                              f"border-radius: 8px; }}")
        for _label, m in self._toolbar_modes():
            btn = getattr(self, f"_view_btn_{m}", None)
            if btn is None:
                continue
            if m in self._CALENDAR_MODES:
                self._style_seg_btn(btn, m == mode)
            else:
                self._style_nav_btn(btn, m == mode)
        cal = getattr(self, "_nav_calendar_btn", None)
        if cal is not None:
            self._style_nav_btn(cal, on_calendar)
        # the date controls mean nothing on a panel
        for w in getattr(self, "_calendar_only", ()):
            w.setVisible(on_calendar)

    def _style_nav_btn(self, btn: QPushButton, active: bool) -> None:
        """A sidebar section row. Complete inline stylesheets for both states,
        for the reason `_style_seg_btn` gives."""
        dark = self._dark
        text = _styles.D_GRAY_DARK if dark else GRAY_DARK
        text2 = _styles.D_GRAY_TEXT if dark else GRAY_TEXT
        hover = _styles.D_GRAY_LIGHT if dark else _styles.GRAY_LIGHT
        r, g, b = _styles._hex_to_rgb(_styles.BLUE)
        # the glyph is an icon in the row's own colour (Sidebar.nav_icon), so
        # every label starts at the same x whatever the symbol's width
        from assistant.calendar_ui.sidebar import Sidebar
        btn.setIcon(Sidebar.nav_icon(btn.property("glyph") or "•",
                                     _styles.BLUE if active else text))
        base = ("QPushButton#nav_item { text-align: left; padding: 6px 10px; "
                "border: none; border-radius: 6px; font-size: 13px; ")
        if active:
            btn.setStyleSheet(
                base + f"background-color: rgba({r},{g},{b},0.18); color: {_styles.BLUE}; "
                "font-weight: 700; }")
        else:
            btn.setStyleSheet(
                base + f"background-color: transparent; color: {text}; font-weight: 500; }}"
                f"QPushButton#nav_item:hover {{ background-color: {hover}; color: {text}; }}")
            _ = text2

    def _build_sidebar_nav(self) -> None:
        """The app's sections, in the sidebar: Calendar, then one row per
        feature panel from the registry (Tasks, Timer, Account…). They were
        eight more buttons in the toolbar's view strip."""
        glyphs = {"tasks": "clipboard_check", "timer": "stopwatch", "coursework": "graduation",
                  "workout": "dumbbell", "account": "user_circle", "jude": "book_open",
                  "teach": "idea"}
        self._nav_calendar_btn = self._sidebar.add_nav("Calendar", "calendar")
        self._nav_calendar_btn.clicked.connect(
            lambda: self._set_view(getattr(self, "_last_calendar_mode", "month")))
        for label, mode in self._toolbar_modes()[4:]:
            btn = self._sidebar.add_nav(label, glyphs.get(mode, "•"))
            btn.clicked.connect(lambda _=False, m=mode: self._set_view(m))
            feature = _features.get(mode)
            if feature is not None and not feature.pinned:
                btn.setVisible(feature.visible())
            setattr(self, f"_view_btn_{mode}", btn)

    def _update_theme_btn(self) -> None:
        # Show the icon for what the mode will switch TO — drawn, like the gear
        # and the mic (toolbar_icons), so the row reads as one set.
        from PyQt6.QtCore import QSize
        from assistant.calendar_ui.toolbar_icons import glyph_icon, mic_icon
        ink = _styles.D_GRAY_TEXT if self._dark else GRAY_TEXT
        self._theme_btn.setText("")
        self._theme_btn.setIcon(icons.icon("sun" if self._dark else "moon", ink, 16))
        self._theme_btn.setIconSize(QSize(16, 16))
        # vars(), not hasattr: this runs mid-_build_toolbar, before the mic
        # exists, and hasattr on a half-built Qt object raises
        gear, mic = vars(self).get("_settings_btn"), vars(self).get("_mic_btn")
        if gear is not None:
            gear.setIcon(icons.icon("gear", ink, 16))
        for trash in (vars(self).get("_discard_btn"), vars(self).get("_review_bar")):
            btn = getattr(trash, "_cancel", trash)
            if btn is not None:
                btn.setIcon(icons.icon("trash", ink, 15))
            gear.setIconSize(QSize(16, 16))
        typer = vars(self).get("_type_btn")
        if typer is not None:
            from assistant.calendar_ui.toolbar_icons import keyboard_icon
            typer.setIcon(keyboard_icon(ink, 18))
            typer.setIconSize(QSize(18, 18))
        if mic is not None and not mic.text():
            mic.setIcon(mic_icon(_styles.ON_ACCENT))
            mic.setIconSize(QSize(18, 18))
        self._theme_btn.setToolTip("Switch to light mode" if self._dark else "Switch to dark mode")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _on_prev(self) -> None:
        if self._on_panel():
            return
        if self._view_mode == "month":
            d = self._current_date.replace(day=1) - datetime.timedelta(days=1)
            self._current_date = d.replace(day=1)
        elif self._view_mode in ("week", "agenda"):
            self._current_date -= datetime.timedelta(weeks=1)
        else:  # day
            self._current_date -= datetime.timedelta(days=1)
        self._navigate()

    def _on_next(self) -> None:
        if self._on_panel():
            return
        if self._view_mode == "month":
            d = self._current_date.replace(day=28) + datetime.timedelta(days=4)
            self._current_date = d.replace(day=1)
        elif self._view_mode in ("week", "agenda"):
            self._current_date += datetime.timedelta(weeks=1)
        else:  # day
            self._current_date += datetime.timedelta(days=1)
        self._navigate()

    def _on_today(self) -> None:
        self._current_date = datetime.date.today()
        self._navigate()

    def _on_sidebar_date(self, date: datetime.date) -> None:
        self._current_date = date
        if self._on_panel():
            # a date picked while on Tasks or Timer means "show me that day"
            self._set_view("day")
            return
        self._navigate()

    # ── Toolbar search: find events/tasks, or jump straight to a date ────

    @staticmethod
    def _parse_jump_date(q: str) -> "datetime.date | None":
        """'2026-10-14', '14/10' or '14/10/2026' → that date; else None."""
        try:
            return datetime.date.fromisoformat(q)
        except ValueError:
            pass
        parts = q.split("/")
        if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
            try:
                day, month = int(parts[0]), int(parts[1])
                year = int(parts[2]) if len(parts) == 3 else datetime.date.today().year
                if year < 100:
                    year += 2000
                return datetime.date(year, month, day)
            except ValueError:
                return None
        return None

    def _on_search(self) -> None:
        q = self._search_box.text().strip()
        if not q:
            return
        jump = self._parse_jump_date(q)
        if jump is not None:
            self._search_box.clear()
            if self._view_mode not in ("month", "week", "day", "agenda"):
                self._set_view("day")
            self._current_date = jump
            self._navigate()
            return
        if len(q) < 2:
            return
        events = self._db.search_events(q, limit=10)
        todos = self._db.search_todos(q, limit=6)
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self._search_box)
        if not events and not todos:
            menu.addAction("No matches").setEnabled(False)
        for e in events:
            act = menu.addAction(f"{e['date']} {e['start_time']}  ·  {e['title'][:44]}")
            act.triggered.connect(
                lambda _, d=e["date"]: self._on_search_pick_event(d))
        if events and todos:
            menu.addSeparator()
        for t in todos:
            mark = "✓ " if t.get("completed") else ""
            act = menu.addAction(f"task  ·  {mark}{t['title'][:44]}")
            act.triggered.connect(lambda _: self._set_view("tasks"))
        menu.exec(self._search_box.mapToGlobal(
            self._search_box.rect().bottomLeft()))

    def _on_search_pick_event(self, date_str: str) -> None:
        self._search_box.clear()
        if self._view_mode not in ("month", "week", "day", "agenda"):
            self._set_view("day")
        self._current_date = datetime.date.fromisoformat(date_str)
        self._navigate()

    def _on_day_selected(self, date: datetime.date) -> None:
        self._current_date = date
        self._update_title()

    def _navigate(self) -> None:
        if self._on_panel():
            self._update_title()
            return
        if self._view_mode == "month":
            self._month_view.navigate(self._current_date.year, self._current_date.month)
        elif self._view_mode == "week":
            week_start = _vp.week_start(self._current_date)
            self._week_view.navigate(week_start)
        elif self._view_mode == "agenda":
            self._agenda_view.set_start_date(self._current_date)
        else:  # day
            self._day_view.navigate(self._current_date)
        self._update_title()

    def _toolbar_modes(self) -> "list[tuple[str, str]]":
        """The view row: the calendar's four modes, then one per feature panel.

        Built from the registry so the row, the stack, `_set_view` and the
        bounce-off can never disagree — they were five hand-kept lists, and
        they had already drifted.
        """
        modes = [("Month", "month"), ("Week", "week"),
                 ("Day", "day"), ("Agenda", "agenda")]
        modes += [(f.label, f.name) for f in _features.all_features()
                  if f.panel() is not None]
        return modes

    def _on_panel(self) -> bool:
        """Is the current view a feature panel rather than a calendar view?

        The date navigation, the title and the Today button all mean nothing on
        a panel, and each site used to spell that out as the same hardcoded
        tuple of four mode names.
        """
        return self._view_mode in self._panels

    def _set_view(self, mode: str) -> None:
        self._view_mode = mode
        widget = {
            "month":  self._month_view,
            "week":   self._week_view,
            "day":    self._day_view,
            "agenda": self._agenda_view,
        }.get(mode) or self._panels.get(mode) or self._month_view
        self._stack.setCurrentWidget(widget)
        if mode in self._CALENDAR_MODES:
            self._last_calendar_mode = mode
        self._restyle_view_buttons()
        # Keep pipeline context-aware of current view for voice routing
        if self._pipeline is not None:
            self._pipeline.current_view = mode
            if mode == "todo":
                self._mic_btn.setToolTip(
                    "Tasks mode — voice commands will create/manage tasks\n"
                    "Click or press Ctrl+J to speak"
                )
            else:
                self._mic_btn.setToolTip(
                    "Click or press Ctrl+J to toggle the microphone"
                )
        self._navigate()

    def _title_with_hebrew(self, base: str, representative_date: datetime.date) -> str:
        """Append/replace *base* with the Hebrew month+year per the configured
        display mode. Uses a single representative date (not every visible
        day) since the Hebrew month+year would otherwise repeat redundantly
        across a whole month/week grid."""
        mode = self._config.hebrew_calendar.display_mode if self._config else "english"
        if mode == "english":
            return base
        from assistant.hebrew_calendar import hebrew_month_year_string
        heb = hebrew_month_year_string(representative_date)
        return heb if mode == "hebrew" else f"{base}   ·   {heb}"

    def _update_title(self) -> None:
        # A panel's title is its feature's label — declared once, in its own
        # folder, rather than a branch per panel here.
        if self._on_panel():
            feature = _features.get(self._view_mode)
            self._title_label.setText(
                feature.label if feature else self._view_mode.title())
            return
        if self._view_mode == "month":
            base = self._current_date.strftime("%B %Y")
            # Mid-month as the representative date — the 1st can fall right
            # at a Hebrew month boundary and misrepresent most of the grid.
            mid = self._current_date.replace(day=15)
            self._title_label.setText(self._title_with_hebrew(base, mid))
        elif self._view_mode == "week":
            week_start = _vp.week_start(self._current_date)
            week_end = week_start + datetime.timedelta(days=6)
            if week_start.month == week_end.month:
                base = f"{week_start.strftime('%B %-d')} – {week_end.day}, {week_end.year}"
            else:
                base = f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}"
            mid = week_start + datetime.timedelta(days=3)
            self._title_label.setText(self._title_with_hebrew(base, mid))
        elif self._view_mode == "agenda":
            start = self._current_date
            end = start + datetime.timedelta(days=_AGENDA_DAYS - 1)
            if start.month == end.month:
                base = f"{start.strftime('%B %-d')} – {end.day}, {end.year}"
            else:
                base = f"{start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}"
            mid = start + datetime.timedelta(days=_AGENDA_DAYS // 2)
            self._title_label.setText(self._title_with_hebrew(base, mid))
        else:  # day
            base = self._current_date.strftime("%A, %B %-d, %Y")
            self._title_label.setText(self._title_with_hebrew(base, self._current_date))

    # ------------------------------------------------------------------
    # Event actions
    # ------------------------------------------------------------------

    def _on_undo(self) -> None:
        desc = self._undo_manager.undo()
        if desc:
            self.refresh_calendar()
            self.show_toast(f"Undid: {desc}")
        else:
            self.show_toast("Nothing to undo")

    def _on_redo(self) -> None:
        desc = self._undo_manager.redo()
        if desc:
            self.refresh_calendar()
            self.show_toast(f"Redid: {desc}")
        else:
            self.show_toast("Nothing to redo")

    @staticmethod
    def _event_content_fields(event: dict) -> dict:
        """Strip an event dict down to the fields create/update accept —
        excludes id/series_id/source/timestamps so a recreate never
        accidentally regenerates a whole series or collides on id.
        Includes recurrence/recurrence_end so an undo that reverts a
        recurring-vs-not change restores the field, not just the visible
        title/date/time — see the promotion guard in _on_event_clicked for
        why promoting to a series is excluded from the undo stack entirely
        rather than relying on this alone."""
        keys = ("title", "date", "start_time", "end_time", "attendees",
                "location", "description", "color", "recurrence", "recurrence_end")
        return {k: event.get(k, "") for k in keys}

    def _create_event_and_refresh(self, dialog: EventDialog) -> None:
        data = dict(dialog.event_data)
        title = data.get("title", "event")
        is_recurring = bool(data.get("recurrence"))
        # Mutable holder: redo re-creates the row under a NEW id each time,
        # so undo (which deletes "the current copy") must always read the
        # latest id rather than one frozen at push() time.
        id_holder = {"id": self._db.create_event_from_dict(data)}

        def undo():
            # A recurring create generates a whole series (create_event_from_dict
            # -> _create_series_instances) — delete_event alone would only remove
            # the root and re-root the series to the next instance, leaving the
            # rest behind. delete_series removes every generated instance.
            if is_recurring:
                self._db.delete_series(id_holder["id"])
            else:
                self._db.delete_event(id_holder["id"])

        def redo():
            id_holder["id"] = self._db.create_event_from_dict(data)

        self._undo_manager.push(f'Create "{title}"', undo, redo)
        self.refresh_calendar()

    def _on_new_event(self, default_date: Optional[datetime.date] = None) -> None:
        dialog = EventDialog(self, default_date=default_date or self._current_date, db=self._db)
        if dialog.exec() and dialog.event_data:
            self._create_event_and_refresh(dialog)

    def _on_day_double_clicked(self, date: datetime.date) -> None:
        self._on_new_event(default_date=date)

    def _on_datetime_double_clicked(self, dt: datetime.datetime) -> None:
        dialog = EventDialog(self, default_date=dt.date(), default_time=dt.time(), db=self._db)
        if dialog.exec() and dialog.event_data:
            self._create_event_and_refresh(dialog)

    def _on_event_clicked(self, event: dict) -> None:
        dialog = EventDialog(self, event=event, db=self._db)
        if dialog.exec():
            ev_id = event.get("id")
            series_id = event.get("series_id")

            if dialog.delete_series_requested and series_id:
                # Series-wide delete isn't captured for undo (would require
                # snapshotting every instance) — Cmd+Z after this reaches
                # further back to the last undoable action instead.
                count = self._db.delete_series(series_id)
                self.refresh_calendar()
                self.show_toast(f"Deleted {count} events in series")
            elif dialog.delete_requested and ev_id:
                restore_data = self._event_content_fields(event)
                # If this instance belonged to a series, it inherited that
                # series' recurrence/recurrence_end fields too — but restoring
                # it via create_event_from_dict() treats a non-empty
                # recurrence as "generate a brand new series", which would
                # spawn a second, parallel series of future instances rather
                # than just bringing back this one deleted occurrence. Clear
                # it so undo restores the row's content without side effects;
                # the restored instance just won't carry its old series
                # membership/badge — same "series identity isn't fully
                # undoable" boundary already accepted for the other cases above.
                if event.get("series_id"):
                    restore_data["recurrence"] = ""
                    restore_data["recurrence_end"] = ""
                id_holder = {"id": ev_id}
                self._db.delete_event(id_holder["id"])

                def undo():
                    id_holder["id"] = self._db.create_event_from_dict(restore_data)

                def redo():
                    self._db.delete_event(id_holder["id"])

                self._undo_manager.push(f'Delete "{event["title"]}"', undo, redo)
                self.refresh_calendar()
                self.show_toast(f"Deleted \"{event['title']}\"")
            elif dialog.duplicate_requested and ev_id:
                copy_data = self._event_content_fields(event)
                # A duplicated series instance becomes a one-off: a non-empty
                # recurrence in create_event_from_dict() would spawn a whole
                # second series (same boundary as undo-restore above).
                copy_data["recurrence"] = ""
                copy_data["recurrence_end"] = ""
                id_holder = {"id": self._db.create_event_from_dict(copy_data)}

                def undo_dup():
                    self._db.delete_event(id_holder["id"])

                def redo_dup():
                    id_holder["id"] = self._db.create_event_from_dict(copy_data)

                self._undo_manager.push(f'Duplicate "{event["title"]}"',
                                        undo_dup, redo_dup)
                self.refresh_calendar()
                self.show_toast(f"Duplicated \"{event['title']}\"")
            elif dialog.event_data:
                ev_id = dialog.event_data.pop("id", None)
                series_id = dialog.event_data.pop("series_id", None)

                if ev_id:
                    if series_id and repeat_rule_changed(event, dialog.event_data):
                        # The cadence or the end date moved. That rule belongs
                        # to every instance, so it goes to the whole series —
                        # the dialog's hint says so before Save. Offering "only
                        # this instance" here used to write a new end date onto
                        # ONE row while the rest of the series carried on.
                        try:
                            self._db.update_series(series_id, ev_id, **dialog.event_data)
                        except ValueError as e:
                            self.show_toast(f"Series not changed: {e}")
                            return
                        self.refresh_calendar()
                        n = len(self._db.get_series_events(series_id))
                        self.show_toast(f"Updated series \"{dialog.event_data['title']}\" "
                                        f"— {n} events")
                    elif series_id:
                        msg = QMessageBox(self)
                        msg.setWindowTitle("Update Recurring Event")
                        msg.setText("This is a repeating event.")
                        msg.setInformativeText("Do you want to update only this instance, or the entire series?")
                        btn_only_this = msg.addButton("Only this instance", QMessageBox.ButtonRole.ActionRole)
                        btn_series = msg.addButton("Entire series", QMessageBox.ButtonRole.AcceptRole)
                        msg.addButton(QMessageBox.StandardButton.Cancel)
                        msg.setDefaultButton(btn_only_this)
                        msg.exec()

                        if msg.clickedButton() == btn_only_this:
                            before = self._event_content_fields(event)
                            after = dict(dialog.event_data)
                            self._db.update_event(ev_id, **after)
                            self._undo_manager.push(
                                f'Update "{after["title"]}"',
                                lambda: self._db.update_event(ev_id, **before),
                                lambda: self._db.update_event(ev_id, **after),
                            )
                            self.refresh_calendar()
                            self.show_toast(f"Updated this instance of \"{dialog.event_data['title']}\"")
                        elif msg.clickedButton() == btn_series:
                            # Series-wide update isn't captured for undo either.
                            self._db.update_series(series_id, ev_id, **dialog.event_data)
                            self.refresh_calendar()
                            self.show_toast(f"Updated series \"{dialog.event_data['title']}\"")
                    else:
                        before = self._event_content_fields(event)
                        after = dict(dialog.event_data)
                        promotes_to_series = bool(after.get("recurrence")) and not before.get("recurrence")
                        self._db.update_event(ev_id, **after)
                        # If recurrence was added to a previously non-recurring event,
                        # promote it to a series root and generate future instances.
                        if after.get("recurrence"):
                            self._db.promote_to_series(ev_id)
                        if promotes_to_series:
                            # Reverting update_event alone wouldn't clean up the
                            # series instances promote_to_series just generated —
                            # same undo boundary as the series-wide branches above:
                            # don't push a record that would silently under-undo.
                            pass
                        else:
                            self._undo_manager.push(
                                f'Update "{after["title"]}"',
                                lambda: self._db.update_event(ev_id, **before),
                                lambda: self._db.update_event(ev_id, **after),
                            )
                        self.refresh_calendar()
                        self.show_toast(f"Updated \"{dialog.event_data['title']}\"")

    def _on_event_rescheduled(self, event_id: int, updates: dict) -> None:
        event = self._db.get_event(event_id)
        if event and self._db.is_event_locked(event):
            self.refresh_calendar()  # snap the drag back to its DB position
            self.show_toast("This event is read-only and can't be moved")
            return
        if "start_time" in updates and "end_time" not in updates:
            if event:
                try:
                    orig_sh, orig_sm = map(int, event["start_time"].split(":"))
                    orig_eh, orig_em = map(int, event["end_time"].split(":"))
                    duration_min = (orig_eh * 60 + orig_em) - (orig_sh * 60 + orig_sm)
                    if duration_min > 0:
                        new_sh, new_sm = map(int, updates["start_time"].split(":"))
                        end_min = min(new_sh * 60 + new_sm + duration_min, 23 * 60 + 59)
                        updates["end_time"] = f"{end_min // 60:02d}:{end_min % 60:02d}"
                except Exception:
                    pass
        if event:
            before = {k: event.get(k, "") for k in ("date", "start_time", "end_time")}
            after = dict(updates)
            self._undo_manager.push(
                f'Move "{event["title"]}"',
                lambda: self._db.update_event(event_id, **before),
                lambda: self._db.update_event(event_id, **after),
            )
        self._db.update_event(event_id, **updates)
        self.refresh_calendar()
        action = "Event resized" if ("start_time" in updates and "end_time" in updates) else "Event moved"
        self.show_toast(action)

    # ------------------------------------------------------------------
    # Voice assistant integration
    # ------------------------------------------------------------------

    def _poll_status(self) -> None:
        import time as _t
        if _t.time() - getattr(self, "_last_beat", 0) > 5:
            self._last_beat = _t.time()
            try:
                from assistant.heartbeat import beat
                beat("gui")
            except Exception:
                pass
        """Drain pipeline.status_queue on the main thread (called by QTimer)."""
        if self._pipeline is None:
            return
        try:
            while True:
                item = self._pipeline.status_queue.get_nowait()
                # Pipeline now sends (status, message) tuples
                if isinstance(item, tuple):
                    status, message = item
                else:
                    status, message = item, ""
                self._handle_status(status, message)
        except queue.Empty:
            pass

    def _fetch_tag_suggestion(self) -> None:
        import json as _json
        import threading
        import urllib.request

        def _work() -> None:
            try:
                port = getattr(getattr(self._config, "api", None), "port", 8080)
                req = urllib.request.Request(f"http://127.0.0.1:{port}/tags/suggestion")
                key = getattr(getattr(self._config, "api", None), "key", None)
                if key:
                    req.add_header("X-API-Key", key)
                for _k, _v in _local_session.headers().items():
                    req.add_header(_k, _v)
                with urllib.request.urlopen(req, timeout=5) as r:
                    c = _json.loads(r.read().decode())
                if c and c.get("name"):
                    self._tag_suggestion_ready.emit(c)
            except Exception:
                pass                      # a quiet feature: never bother anyone

        threading.Thread(target=_work, daemon=True, name="tag-suggest").start()

    def _on_tag_suggestion(self, c: dict) -> None:
        from PyQt6.QtWidgets import QMessageBox
        samples = "\n  • ".join(c.get("samples") or [])
        box = QMessageBox(self)
        box.setWindowTitle("New tag idea")
        box.setText(f"Add “{c['name']}” as a tag?")
        box.setInformativeText(
            f"{c.get('evidence', '?')} of your tasks share this theme and no "
            f"existing tag covers them, e.g.:\n  • {samples}\n\n"
            "You can review or reverse this later in the tag history.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        accept = box.exec() == QMessageBox.StandardButton.Yes

        import json as _json
        import threading
        import urllib.request

        def _post() -> None:
            try:
                port = getattr(getattr(self._config, "api", None), "port", 8080)
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/tags/suggestion/answer",
                    data=_json.dumps({"name": c["name"], "accept": accept}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
                key = getattr(getattr(self._config, "api", None), "key", None)
                if key:
                    req.add_header("X-API-Key", key)
                for _k, _v in _local_session.headers().items():
                    req.add_header(_k, _v)
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass

        threading.Thread(target=_post, daemon=True, name="tag-suggest-answer").start()

    def _on_jude(self) -> None:
        """Bring the Jude window up, starting it if it is not running.

        Its own process, like the thinking HUD and for the same reason: it
        outlives the calendar window and has nothing to do with it. Launching
        is fire-and-forget — a second click on an app that is already open is
        handled by macOS bringing it forward, and a failure to start says so in
        a toast rather than blocking the calendar.
        """
        import os as _os
        import subprocess
        import sys

        repo = _os.path.dirname(_os.path.dirname(
            _os.path.dirname(_os.path.abspath(__file__))))
        try:
            subprocess.Popen([sys.executable, "-m", "assistant.jude.app"],
                             cwd=repo, start_new_session=True)
            self.show_toast("Opening Jude…")
        except Exception as exc:                      # noqa: BLE001
            self.show_toast(f"Couldn't open Jude: {exc}")

    def _on_review_choice(self, choice: str) -> None:
        """Redo / Add more / Send / Cancel from the review bar."""
        if self._pipeline is not None:
            self._pipeline.review_choice(choice)

    def _position_review_bar(self) -> None:
        """Just above the mic button, right-aligned like the iPhone's chip."""
        bar = getattr(self, "_review_bar", None)
        if bar is None or not bar.isVisible():
            return
        parent = bar.parentWidget()
        bar.adjustSize()
        x = max(8, parent.width() - bar.width() - 16)
        bar.move(x, 58)
        bar.raise_()

    def _handle_status(self, status: str, message: str = "") -> None:
        icon = _MIC_ICONS.get(status, "mic")
        obj_name = _MIC_OBJ_NAMES.get(status, "mic_idle")
        from PyQt6.QtCore import QSize
        self._mic_btn.setText("")
        if icon == "mic":                # idle: the toolbar's own drawn microphone
            from assistant.calendar_ui.toolbar_icons import mic_icon
            self._mic_btn.setIcon(mic_icon(_styles.ON_ACCENT))
        else:
            self._mic_btn.setIcon(icons.icon(icon, _styles.ON_ACCENT, 18))
        self._mic_btn.setIconSize(QSize(18, 18))
        self._mic_btn.setObjectName(obj_name)
        self._mic_btn.style().unpolish(self._mic_btn)
        self._mic_btn.style().polish(self._mic_btn)
        # Only offered while there is a recording to throw away; the review bar
        # carries its own trash button for the few seconds it is up.
        self._discard_btn.setVisible(status == STATUS_LISTENING)
        meter = vars(self).get("_mic_meter")
        if meter is not None:
            if status == STATUS_LISTENING and self._pipeline is not None:
                pipe = self._pipeline
                meter.start(lambda: getattr(pipe, "mic_level", 0.0))
            else:
                meter.stop()

        if status == STATUS_REVIEW:
            # The message is "<seconds>|<transcript snippet>" for the review bar,
            # which shows the transcript itself — so no toast (it was leaking the
            # raw "3|add lunch…" string across the bottom of the window).
            secs, _, snippet = message.partition("|")
            self._review_bar.start(int(secs or 3), snippet)
            self._position_review_bar()
            return
        self._review_bar.stop()

        if status == STATUS_EDIT:
            # The message is a JSON payload, not a toast: the engine's gate is
            # holding execution until the doubted words are checked.
            self._show_transcript_edit(message)
            return

        if status == STATUS_CONFIRM:
            # Likewise a JSON payload: the words were a question about creating
            # something, so the brain is offering the parse instead of running
            # it (DEVQA Q9).
            self._show_create_confirm(message)
            return

        if message:
            self.show_toast(message)

        if status == STATUS_REFRESH:
            self.refresh_calendar()
            self.refresh_todos()
        elif status == STATUS_SWITCH_TODAY:
            self._current_date = datetime.date.today()
            self._set_view("day")
        elif status == STATUS_SWITCH_TODO:
            self._set_view("tasks")
            self.refresh_todos()

    def _show_transcript_edit(self, payload_json: str) -> None:
        """The engine's transcript gate: show what was heard, let the speaker
        fix it, and hand the verdict back to the pipeline's worker thread.
        Sending it back untouched is itself an answer (a confirmation the
        server counts toward whitelisting the word)."""
        verdict = ask_transcript_edit(self, payload_json)
        if self._pipeline is not None:
            self._pipeline.submit_transcript_edit(verdict)

    def _show_create_confirm(self, payload_json: str) -> None:
        """The engine's confirm gate: show what the question would create and
        let the speaker say Add or No. Nothing has been written yet — the
        answer goes back to the worker thread, which tells the server."""
        accepted = ask_create_confirm(self, payload_json)
        if self._pipeline is not None:
            self._pipeline.submit_create_confirm(accepted)

    def _auto_refresh_if_db_changed(self) -> None:
        import os as _os
        try:
            m = _os.path.getmtime(self._db.path)
        except OSError:
            return
        if m != self._db_mtime:
            self._db_mtime = m
            self.reload_panels()
            self.refresh_calendar()

    def _on_user_switched(self) -> None:
        """A different person signed in: their calendar, their panels."""
        self._db.set_own(CalendarDB())         # resolves to the new user's file
        try:
            self._db_mtime = os.path.getmtime(self._db.path)
        except OSError:
            pass
        self.reload_panels()
        self.refresh_calendar()
        from assistant.users import registry
        name = (registry.get(users.current() or "") or {}).get("display_name", "")
        self.show_toast(f"Signed in as {name}")

    def reload_panels(self) -> None:
        """Re-read every feature panel.

        This file's DB is written by the API SERVER too — the phone starts a
        timer, adds a course, logs a workout — so a change can arrive from
        another process entirely. This used to reload Tasks and, as a
        special case bolted on later, Timer; Coursework and Workout went stale
        until the app was restarted, because each panel had to be remembered
        by hand here and two of them never were.

        One panel failing must not stop the others: a stale panel is a nuisance,
        a half-refreshed window is a bug report nobody can reproduce.
        """
        for name, panel in getattr(self, "_panels", {}).items():
            try:
                panel.reload()
            except Exception:                    # noqa: BLE001
                logger.exception("panel %s failed to reload", name)

    def refresh_calendar(self) -> None:
        """Reload events from DB in all calendar views."""
        self._month_view.refresh()
        self._week_view.refresh()
        self._day_view.refresh()
        self._agenda_view.refresh()
        side = getattr(self, "_sidebar", None)
        if side is not None and hasattr(side, "refresh_countdowns"):
            side.refresh_countdowns()

    def refresh_todos(self) -> None:
        """Reload todos from DB in the TodoView and calendar (for deadline pills)."""
        if hasattr(self, "_todo_view"):
            self._todo_view.refresh()
        self.refresh_calendar()

    def show_toast(self, message: str) -> None:
        self._toast.show_message(message)
        # Centre the toast at the bottom of the window
        self._toast.adjustSize()
        x = (self.width() - self._toast.width()) // 2
        y = self.height() - self._toast.height() - 24
        self._toast.move(x, y)

    # ------------------------------------------------------------------
    # Resize: keep toast centred
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_review_bar"):
            self._position_review_bar()
        if hasattr(self, "_toast"):
            self._toast.adjustSize()
            x = (self.width() - self._toast.width()) // 2
            y = self.height() - self._toast.height() - 24
            self._toast.move(x, y)

    # ------------------------------------------------------------------
    # Dark mode
    # ------------------------------------------------------------------

    def _on_toggle_theme(self) -> None:
        self._dark = not self._dark
        self._apply_theme(self._dark, show_toast=True)

    def _apply_theme(self, dark: bool, show_toast: bool = False) -> None:
        accent = self._config.ui.accent_color if self._config else None
        self.setStyleSheet(get_app_style(dark, accent))
        self._month_view.apply_theme(dark)
        self._week_view.apply_theme(dark)
        self._day_view.apply_theme(dark)
        self._agenda_view.apply_theme(dark)
        self._sidebar.apply_theme(dark)
        # One loop, not a hasattr chain per panel. Those guards were never a
        # contract: a hasattr check for a method you are not calling passes
        # trivially, which is how three panels went unrefreshed for months.
        for panel in getattr(self, "_panels", {}).values():
            panel.apply_theme(dark)
        if hasattr(self, "_review_bar"):
            self._review_bar.apply_theme(dark)

        # Re-style toolbar
        bg = _styles.D_GRAY_BG if dark else _styles.GRAY_BG
        border = _styles.D_GRAY_BORDER if dark else GRAY_BORDER
        if hasattr(self, "_toolbar_bar"):
            self._toolbar_bar.setStyleSheet(self._toolbar_qss(bg, border))
        if hasattr(self, "_toolbar_sep"):
            self._toolbar_sep.setStyleSheet(f"color: {border};")
        # Re-apply view-button styling (colors depend on theme + accent)
        self._restyle_view_buttons()
        self._update_theme_btn()
        if show_toast:
            self.show_toast("Dark mode on" if dark else "Light mode on")

    def _apply_ui_config(self) -> None:
        """Apply font sizes and other UI constants from config."""
        ui = self._config.ui
        self._month_view.apply_ui_config(ui)
        self._week_view.apply_ui_config(ui)
        self._day_view.apply_ui_config(ui)
        self._agenda_view.apply_ui_config(ui)
        for panel in getattr(self, "_panels", {}).values():
            panel.apply_ui_config(ui)
        hebrew = self._config.hebrew_calendar
        self._month_view.apply_hebrew_config(hebrew)
        self._week_view.apply_hebrew_config(hebrew)
        self._day_view.apply_hebrew_config(hebrew)
        self._agenda_view.apply_hebrew_config(hebrew)
        self._update_title()
        self.refresh_calendar()

    def _on_briefing_requested(self) -> None:
        """Query today's events and read them aloud via TTS."""
        import threading as _threading
        events = self._db.get_events_for_day(datetime.date.today())
        events = sorted(events, key=lambda e: e.get("start_time", ""))
        n = len(events)

        if n == 0:
            summary = "Your schedule is clear today. Nothing planned."
        elif n == 1:
            ev = events[0]
            t = _fmt_time(ev.get("start_time", ""))
            summary = f"You have one event today: {ev['title']} at {t}."
        else:
            parts = [f"{ev['title']} at {_fmt_time(ev.get('start_time', ''))}" for ev in events]
            if len(parts) == 2:
                schedule = f"{parts[0]} and {parts[1]}"
            else:
                schedule = ", ".join(parts[:-1]) + f", and {parts[-1]}"
            summary = f"You have {n} events today: {schedule}."

        self.show_toast(summary[:80])
        if self._pipeline:
            _threading.Thread(
                target=lambda: self._pipeline._tts.speak(summary), daemon=True
            ).start()

    def _on_settings_popup(self) -> None:
        from assistant.calendar_ui.settings_dialog import open_settings
        open_settings(self)

    def _apply_assistant_switch(self, on: bool) -> None:
        """Settings ▸ Assistant: off shuts the mic (the brain refuses commands
        too, so a phone or a stale window cannot slip one past it)."""
        mic = vars(self).get("_mic_btn")
        if mic is None:
            return
        mic.setEnabled(on)
        mic.setToolTip("Click or press Ctrl+J to toggle the microphone" if on else
                       "The assistant is off — Settings ▸ Assistant")
        typer = vars(self).get("_type_btn")
        if typer is not None:
            typer.setEnabled(on)
            typer.setToolTip("Type a command instead of saying it (⌘K)" if on else
                             "The assistant is off — Settings ▸ Assistant")

    def _open_type_box(self) -> None:
        """The box a command is typed into: a popup under the ⌨ button, the
        same width as a sentence, gone on Enter or Esc. What is typed takes
        the spoken command's road (`Pipeline.submit_typed`)."""
        btn = vars(self).get("_type_btn")
        if self._pipeline is None or btn is None or not btn.isEnabled():
            return
        from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLineEdit
        box = QFrame(self, Qt.WindowType.Popup)
        box.setObjectName("type_command_box")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        edit = QLineEdit()
        edit.setObjectName("type_command_field")
        edit.setPlaceholderText("Type a command — e.g. lunch with Dana tomorrow at 1")
        edit.setMinimumWidth(380)
        lay.addWidget(edit)

        def send() -> None:
            if self._pipeline.submit_typed(edit.text()):
                box.close()
        edit.returnPressed.connect(send)
        box.adjustSize()
        pos = btn.mapToGlobal(btn.rect().bottomRight())
        box.move(pos.x() - box.width(), pos.y() + 6)
        box.show()
        edit.setFocus()
        self._type_box = box

    def _apply_view_prefs(self) -> None:
        """Settings ▸ Appearance saved: first day, clock, days, row height,
        week numbers — into every view that draws them."""
        _vp.apply(getattr(self._config, "ui", None))
        _vp.apply_titles(self._config)
        for view in (getattr(self, "_week_view", None), getattr(self, "_day_view", None)):
            if view is not None and hasattr(view, "relabel"):
                view.relabel()
        month = getattr(self, "_month_view", None)
        if month is not None:
            month.apply_ui_config(self._config.ui)
        side = getattr(self, "_sidebar", None)
        if side is not None and hasattr(side, "apply_first_day"):
            side.apply_first_day()
        self._apply_visible_hours()
        self._navigate()                  # the week around today, from the new first day

    def _apply_visible_hours(self) -> None:
        """Settings ▸ Appearance ▸ Show hours, into Week and Day."""
        from assistant.calendar_ui.visible_hours import span
        first, last = span(getattr(self._config, "ui", None))
        for view in (getattr(self, "_week_view", None), getattr(self, "_day_view", None)):
            if view is not None and hasattr(view, "set_visible_hours"):
                view.set_visible_hours(first, last)

    def _on_pair_device(self) -> None:
        from assistant.host.pair_dialog import PairDialog
        port = getattr(getattr(self._config, "api", None), "port", 8080)
        PairDialog(self, port=port).exec()

    def _on_tag_history(self) -> None:
        from assistant.calendar_ui.tag_history_dialog import open_tag_history
        open_tag_history(self)

    def _on_import(self) -> None:
        """Show an import dialog: choose .ics file OR scan macOS Calendar."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Import Calendar Events")
        msg.setText("How would you like to import events?")
        ics_btn = msg.addButton("Open .ics file", QMessageBox.ButtonRole.ActionRole)
        ics_btn.setIcon(icons.icon("folder", None, 15))
        mac_btn = msg.addButton("Scan macOS Calendar", QMessageBox.ButtonRole.ActionRole)
        mac_btn.setIcon(icons.icon("calendar", None, 15))
        msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == ics_btn:
            self._import_ics_file()
        elif clicked == mac_btn:
            self._import_macos_calendar()

    def _import_ics_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open ICS File",
            "",
            "iCalendar Files (*.ics *.ical);;All Files (*)",
        )
        if not path:
            return
        try:
            events = parse_ics(path)
            inserted, skipped = import_events(self._db, events)
            self.refresh_calendar()
            self.show_toast(f"Imported {inserted} event(s), {skipped} skipped")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _import_macos_calendar(self) -> None:
        try:
            events = scan_macos_calendar()
            if not events:
                QMessageBox.information(
                    self,
                    "macOS Calendar",
                    "No events found. Make sure Calendar.app has events and "
                    "that you have granted Full Disk Access if prompted.",
                )
                return
            inserted, skipped = import_events(self._db, events)
            self.refresh_calendar()
            self.show_toast(f"Imported {inserted} event(s) from macOS Calendar, {skipped} skipped")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    # ------------------------------------------------------------------
    # Connected calendars — ICS/webcal subscriptions + two-way Outlook sync
    # ------------------------------------------------------------------

    def _start_background_sync(self) -> None:
        """Ask the brain to sync every connected calendar now (after adding a
        link, or from a button). The brain runs it — the same function its
        periodic loop and the phone's "Sync now" use — so the two apps can
        never sync differently."""
        if self._sync_running or self._config is None:
            return
        self._sync_running = True

        def worker() -> None:
            from assistant.calendar_ui.connected_calendars import BrainClient
            code, body = BrainClient(self._config).call(
                "POST", "/calendar_sync/sync", {"wait": True}, timeout=180)
            if code == 200:
                results = body.get("results") or {}
            elif body.get("busy"):
                results = {}
            else:
                results = {"errors": [str(body.get("error", code))]}
            self._sync_results_queue.put(results)

        threading.Thread(target=worker, daemon=True).start()

    def _drain_sync_results(self) -> None:
        """Runs on the main-thread QTimer; picks up finished sync results."""
        try:
            while True:
                results = self._sync_results_queue.get_nowait()
                self._sync_running = False
                self.refresh_calendar()
                refresh_dialog = getattr(self, "_connected_dialog_refresh", None)
                if refresh_dialog:
                    refresh_dialog()
                pulled = sum(results.get(k, 0) for k in ("ics_synced", "outlook_pulled", "google_pulled"))
                pushed = results.get("outlook_pushed", 0) + results.get("google_pushed", 0)
                if results.get("errors"):
                    self.show_toast("Calendar sync had errors — see Connected Calendars")
                elif pulled or pushed:
                    self.show_toast(f"Calendars synced ({pulled} pulled, {pushed} pushed)")
        except queue.Empty:
            pass

    def _on_connected_calendars(self) -> None:
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem

        dialog = QDialog(self)
        dialog.setWindowTitle("Connected Calendars")
        dialog.setMinimumSize(500, 460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        intro = QLabel(
            "Subscribe to any calendar's private ICS/webcal link (Gmail, Outlook.com, "
            "iCloud, Yahoo…) for a read-only feed that auto-refreshes. Connect Google "
            "or Outlook below for two-way sync instead."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(True)
        layout.addWidget(list_widget, 1)

        def refresh_list() -> None:
            list_widget.clear()
            for source in self._db.get_calendar_sources():
                if source["kind"] in ("outlook", "google"):
                    continue            # shown by the accounts section below
                kind_label = "ICS link"
                label = source["label"] or source["url"]
                status = f"last synced {source['last_synced'][:16].replace('T', ' ')}" if source["last_synced"] else "not yet synced"
                state = "" if source["enabled"] else "  (disabled)"
                item = QListWidgetItem(f"{label}  —  {kind_label}  —  {status}{state}")
                item.setData(Qt.ItemDataRole.UserRole, source["id"])
                list_widget.addItem(item)

        self._connected_dialog_refresh = refresh_list
        refresh_list()

        remove_btn = QPushButton("Remove Selected")

        def remove_selected() -> None:
            item = list_widget.currentItem()
            if not item:
                return
            self._db.delete_calendar_source(item.data(Qt.ItemDataRole.UserRole))
            refresh_list()
            self.refresh_calendar()

        remove_btn.clicked.connect(remove_selected)
        layout.addWidget(remove_btn)

        layout.addWidget(QLabel("Add a calendar link (ICS / webcal URL):"))
        add_row = QHBoxLayout()
        label_edit = QLineEdit()
        label_edit.setPlaceholderText("Label (e.g. \"My Gmail\")")
        url_edit = QLineEdit()
        url_edit.setPlaceholderText("https://calendar.google.com/.../basic.ics")
        add_row.addWidget(label_edit, 1)
        add_row.addWidget(url_edit, 2)
        add_btn = QPushButton("Add")

        def add_ics() -> None:
            url = url_edit.text().strip()
            if not url:
                return
            self._db.create_calendar_source(kind="ics_url", label=label_edit.text().strip(), url=url)
            label_edit.clear()
            url_edit.clear()
            refresh_list()
            self._start_background_sync()

        add_btn.clicked.connect(add_ics)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)
        # Enter while typing a label/URL adds the calendar (the contextually
        # obvious action) rather than falling through to the dialog's Close
        # default below.
        label_edit.returnPressed.connect(add_ics)
        url_edit.returnPressed.connect(add_ics)

        layout.addSpacing(6)

        # Two-way accounts: the same widget Settings shows, talking to the
        # brain (which holds the sign-ins and runs the sync).
        from assistant.calendar_ui.connected_calendars import ConnectedCalendarsSection
        layout.addWidget(QLabel("<b>Two-way accounts</b>"))
        layout.addWidget(ConnectedCalendarsSection(
            dialog, self._config, toast=self.show_toast, on_synced=refresh_list))

        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()
        self._connected_dialog_refresh = None
